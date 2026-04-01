"""
P2P Node for Gaumo.

Design: All connections are OUTBOUND. Nodes connect to seed nodes and discovered peers.
No port forwarding is required for basic operation.

If a node wants to accept connections (optional), it can run a WebSocket server
on a local port, but this is not required for participation.

Peer discovery:
1. Connect to hardcoded seed nodes
2. Request peer list from seed nodes
3. Connect to discovered peers
4. Periodically poll for new blocks/transactions
"""
import asyncio
import json
import logging
import time
import threading
from typing import Dict, List, Optional, Set

import websockets
from websockets.server import WebSocketServerProtocol
from websockets.exceptions import ConnectionClosed

from gaumo.net.protocol import (
    make_message, parse_message,
    MSG_HANDSHAKE, MSG_HANDSHAKE_ACK,
    MSG_GET_PEERS, MSG_PEERS,
    MSG_GET_BLOCKS, MSG_BLOCKS,
    MSG_NEW_BLOCK, MSG_NEW_TRANSACTION,
    MSG_GET_MEMPOOL, MSG_MEMPOOL,
    MSG_PING, MSG_PONG,
    PROTOCOL_VERSION, NODE_PORT,
)
from gaumo.net.peer import PeerConnection, PeerInfo

logger = logging.getLogger(__name__)

# Default seed nodes (these would be publicly accessible nodes)
DEFAULT_SEEDS = [
    ('vps.justharsiz.lol', 8765),
]

PEER_DISCOVERY_INTERVAL = 60   # seconds
SYNC_INTERVAL = 30             # seconds
MAX_PEERS = 20
MAX_OUTBOUND = 8


class Node:
    """
    Gaumo P2P Node.

    Supports both outbound connections (no port forwarding needed)
    and optional inbound connections (requires open port).
    """

    def __init__(self, blockchain, listen_host: str = '0.0.0.0',
                 listen_port: Optional[int] = None,
                 seeds: Optional[List[tuple]] = None):
        self.blockchain = blockchain
        self.listen_host = listen_host
        self.listen_port = listen_port  # None = no server (outbound only)
        self.seeds = seeds or DEFAULT_SEEDS

        self._peers: Dict[str, PeerConnection] = {}
        self._known_peers: Set[str] = set()  # "host:port" strings
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server = None
        self._running = False

        # For deduplication of seen messages
        self._seen_tx_hashes: Set[str] = set()
        self._seen_block_hashes: Set[str] = set()

    # ------------------------------------------------------------------
    # Public thread-safe API
    # ------------------------------------------------------------------

    def start(self):
        """Start the node in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Node started")

    def stop(self):
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def broadcast_transaction(self, tx):
        """Broadcast a transaction to all connected peers."""
        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(
                self._broadcast(MSG_NEW_TRANSACTION, tx.to_dict()), self._loop
            )

    def broadcast_block(self, block):
        """Broadcast a newly mined block to all connected peers."""
        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(
                self._broadcast(MSG_NEW_BLOCK, block.to_dict()), self._loop
            )

    def get_peer_count(self) -> int:
        return len(self._peers)

    def get_peer_list(self) -> List[dict]:
        return [p.info.to_dict() for p in self._peers.values()]

    # ------------------------------------------------------------------
    # Internal async event loop
    # ------------------------------------------------------------------

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as e:
            logger.error(f"Node loop error: {e}")
        finally:
            self._loop.close()

    async def _main(self):
        tasks = [
            self._connect_to_seeds(),
            self._peer_discovery_loop(),
            self._sync_loop(),
        ]
        if self.listen_port:
            tasks.append(self._run_server())
        await asyncio.gather(*tasks)

    async def _run_server(self):
        """Optional: Accept inbound connections if listen_port is set."""
        logger.info(f"Listening for inbound connections on {self.listen_host}:{self.listen_port}")
        async with websockets.serve(self._handle_inbound, self.listen_host, self.listen_port):
            while self._running:
                await asyncio.sleep(1)

    async def _handle_inbound(self, ws: WebSocketServerProtocol):
        """Handle an inbound peer connection."""
        host = ws.remote_address[0]
        port = ws.remote_address[1]
        logger.info(f"Inbound connection from {host}:{port}")
        info = PeerInfo(host=host, port=port)
        peer = _InboundPeerConnection(info, self, ws)
        addr = f"inbound:{host}:{port}"
        self._peers[addr] = peer
        try:
            await peer.run()
        finally:
            self._peers.pop(addr, None)

    async def _connect_to_seeds(self):
        for host, port in self.seeds:
            await self._connect_to_peer(host, port)

    async def _connect_to_peer(self, host: str, port: int):
        addr = f"{host}:{port}"
        if addr in self._peers:
            return
        info = PeerInfo(host=host, port=port)
        peer = PeerConnection(info, self)
        self._peers[addr] = peer
        asyncio.create_task(self._peer_task(peer))

    async def _peer_task(self, peer: PeerConnection):
        try:
            await peer.connect()
        except Exception as e:
            logger.debug(f"Peer task error: {e}")
        finally:
            addr = peer.info.address
            self._peers.pop(addr, None)

    async def _peer_discovery_loop(self):
        while self._running:
            await asyncio.sleep(PEER_DISCOVERY_INTERVAL)
            await self._discover_peers()

    async def _discover_peers(self):
        """Ask connected peers for their peer lists."""
        for peer in list(self._peers.values()):
            if peer.connected:
                await peer.send(MSG_GET_PEERS)

    async def _sync_loop(self):
        """Periodically check if we need to sync more blocks."""
        await asyncio.sleep(1)  # short initial delay to let connections establish
        while self._running:
            await self._request_sync()
            await asyncio.sleep(SYNC_INTERVAL)

    async def _request_sync(self):
        """Ask the best peer for blocks we're missing."""
        if not self._peers:
            return
        best_peer = max(
            (p for p in self._peers.values() if p.connected),
            key=lambda p: p.info.height,
            default=None,
        )
        if best_peer and best_peer.info.height > self.blockchain.height:
            await best_peer.send(MSG_GET_BLOCKS, {'from_height': self.blockchain.height + 1})

    async def _broadcast(self, msg_type: str, data):
        msg = make_message(msg_type, data)
        for peer in list(self._peers.values()):
            if peer.connected:
                try:
                    await peer.send_raw(msg)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Message handlers (called from PeerConnection)
    # ------------------------------------------------------------------

    async def handle_message(self, peer: PeerConnection, msg: dict):
        msg_type = msg.get('type')
        data = msg.get('data', {})

        if msg_type == MSG_HANDSHAKE:
            peer.info.height = data.get('height', 0)
            peer.info.version = data.get('version', 1)
            await peer.send(MSG_HANDSHAKE_ACK, {
                'height': self.blockchain.height,
                'version': PROTOCOL_VERSION,
            })

        elif msg_type == MSG_HANDSHAKE_ACK:
            peer.info.height = data.get('height', 0)
            # If peer is ahead, request blocks
            if peer.info.height > self.blockchain.height:
                await peer.send(MSG_GET_BLOCKS, {'from_height': self.blockchain.height + 1})

        elif msg_type == MSG_GET_PEERS:
            peer_list = [p.info.to_dict() for p in self._peers.values() if p.connected]
            await peer.send(MSG_PEERS, {'peers': peer_list})

        elif msg_type == MSG_PEERS:
            for p_info in data.get('peers', []):
                addr = f"{p_info['host']}:{p_info['port']}"
                if addr not in self._known_peers and addr not in self._peers:
                    self._known_peers.add(addr)
                    if len(self._peers) < MAX_OUTBOUND:
                        await self._connect_to_peer(p_info['host'], p_info['port'])

        elif msg_type == MSG_GET_BLOCKS:
            from_height = data.get('from_height', 0)
            blocks = self.blockchain.get_blocks_from(from_height)[:50]  # max 50 at once
            await peer.send(MSG_BLOCKS, {'blocks': [b.to_dict() for b in blocks]})

        elif msg_type == MSG_BLOCKS:
            from gaumo.core.block import Block
            for bdict in data.get('blocks', []):
                block = Block.from_dict(bdict)
                if block.block_hash in self._seen_block_hashes:
                    continue
                self._seen_block_hashes.add(block.block_hash)
                ok, err = self.blockchain.add_block(block)
                if not ok and 'not longer' not in err:
                    logger.debug(f"Block rejected: {err}")

            # If we received blocks, we might need more
            if data.get('blocks'):
                last_received = data['blocks'][-1]['index']
                if last_received < peer.info.height:
                    await peer.send(MSG_GET_BLOCKS, {'from_height': last_received + 1})

        elif msg_type == MSG_NEW_BLOCK:
            from gaumo.core.block import Block
            block = Block.from_dict(data)
            if block.block_hash not in self._seen_block_hashes:
                self._seen_block_hashes.add(block.block_hash)
                ok, err = self.blockchain.add_block(block)
                if ok:
                    # Relay to other peers
                    await self._broadcast(MSG_NEW_BLOCK, data)
                else:
                    logger.debug(f"New block rejected: {err}")

        elif msg_type == MSG_NEW_TRANSACTION:
            from gaumo.core.transaction import Transaction
            tx = Transaction.from_dict(data)
            if tx.tx_hash not in self._seen_tx_hashes:
                self._seen_tx_hashes.add(tx.tx_hash)
                ok, err = self.blockchain.mempool.add(tx, self.blockchain.utxo_set)
                if ok:
                    await self._broadcast(MSG_NEW_TRANSACTION, data)

        elif msg_type == MSG_GET_MEMPOOL:
            txs = self.blockchain.mempool.to_list()
            await peer.send(MSG_MEMPOOL, {'transactions': txs})

        elif msg_type == MSG_MEMPOOL:
            from gaumo.core.transaction import Transaction
            for txd in data.get('transactions', []):
                tx = Transaction.from_dict(txd)
                if tx.tx_hash not in self._seen_tx_hashes:
                    self._seen_tx_hashes.add(tx.tx_hash)
                    self.blockchain.mempool.add(tx, self.blockchain.utxo_set)

    def on_peer_disconnected(self, peer: PeerConnection):
        addr = peer.info.address
        self._peers.pop(addr, None)
        logger.info(f"Peer {addr} disconnected. Total peers: {len(self._peers)}")


class _InboundPeerConnection(PeerConnection):
    """Peer connection for inbound connections (already have a ws object)."""

    def __init__(self, info: PeerInfo, node, ws):
        super().__init__(info, node)
        self.ws = ws
        self._connected = True

    async def run(self):
        """Handle inbound connection messages."""
        try:
            async for raw in self.ws:
                msg = parse_message(raw)
                if msg:
                    if msg['type'] == MSG_PING:
                        await self.send_raw(make_message(MSG_PONG))
                    else:
                        await self.node.handle_message(self, msg)
        except ConnectionClosed:
            pass
        finally:
            self._connected = False

    async def connect(self):
        await self.run()
