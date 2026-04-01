"""
Peer connection management for Gaumo.
Uses outbound WebSocket connections so no port forwarding is needed.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import websockets
from websockets.exceptions import ConnectionClosed

from gaumo.net.protocol import make_message, parse_message, MSG_PING, MSG_PONG

logger = logging.getLogger(__name__)

PING_INTERVAL = 30   # seconds
PING_TIMEOUT = 10    # seconds


@dataclass
class PeerInfo:
    host: str
    port: int
    last_seen: float = field(default_factory=time.time)
    version: int = 1
    height: int = 0

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    def to_dict(self) -> dict:
        return {
            'host': self.host,
            'port': self.port,
            'height': self.height,
            'version': self.version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'PeerInfo':
        return cls(host=d['host'], port=d['port'],
                   height=d.get('height', 0), version=d.get('version', 1))


class PeerConnection:
    """
    Manages a single outbound WebSocket connection to a peer.
    """

    def __init__(self, info: PeerInfo, node):
        self.info = info
        self.node = node
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._send_queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self):
        uri = f"ws://{self.info.host}:{self.info.port}"
        try:
            self.ws = await websockets.connect(uri, open_timeout=5, ping_interval=None)
            self._connected = True
            logger.info(f"Connected to peer {self.info.address}")
            # Send handshake immediately so peer knows our height
            # and we can trigger block sync based on height comparison
            from gaumo.net.protocol import MSG_HANDSHAKE, PROTOCOL_VERSION
            await self.send(MSG_HANDSHAKE, {
                'height': self.node.blockchain.height,
                'version': PROTOCOL_VERSION,
            })
            await asyncio.gather(
                self._recv_loop(),
                self._send_loop(),
                self._ping_loop(),
            )
        except Exception as e:
            logger.debug(f"Peer {self.info.address} disconnected: {e}")
        finally:
            self._connected = False
            if self.ws:
                await self.ws.close()
            self.node.on_peer_disconnected(self)

    async def _recv_loop(self):
        async for raw in self.ws:
            msg = parse_message(raw)
            if msg:
                if msg['type'] == MSG_PING:
                    await self.send_raw(make_message(MSG_PONG))
                elif msg['type'] == MSG_PONG:
                    self.info.last_seen = time.time()
                else:
                    await self.node.handle_message(self, msg)

    async def _send_loop(self):
        while self._connected:
            try:
                data = await asyncio.wait_for(self._send_queue.get(), timeout=1.0)
                await self.ws.send(data)
            except asyncio.TimeoutError:
                continue
            except ConnectionClosed:
                break

    async def _ping_loop(self):
        while self._connected:
            await asyncio.sleep(PING_INTERVAL)
            await self.send_raw(make_message(MSG_PING))

    async def send_raw(self, data: str):
        await self._send_queue.put(data)

    async def send(self, msg_type: str, data=None):
        await self.send_raw(make_message(msg_type, data))

    def close(self):
        self._connected = False
