"""
Message protocol definitions for Gaumo P2P networking.
All messages are JSON encoded.
"""
import json
from typing import Any, Optional

# Message types
MSG_HANDSHAKE = "HANDSHAKE"
MSG_HANDSHAKE_ACK = "HANDSHAKE_ACK"
MSG_GET_PEERS = "GET_PEERS"
MSG_PEERS = "PEERS"
MSG_GET_BLOCKS = "GET_BLOCKS"
MSG_BLOCKS = "BLOCKS"
MSG_NEW_BLOCK = "NEW_BLOCK"
MSG_NEW_TRANSACTION = "NEW_TRANSACTION"
MSG_GET_MEMPOOL = "GET_MEMPOOL"
MSG_MEMPOOL = "MEMPOOL"
MSG_PING = "PING"
MSG_PONG = "PONG"

PROTOCOL_VERSION = 1
NODE_PORT = 8765  # Default WebSocket port


def make_message(msg_type: str, data: Any = None) -> str:
    """Serialize a message to JSON string."""
    return json.dumps({
        'type': msg_type,
        'version': PROTOCOL_VERSION,
        'data': data or {},
    }, sort_keys=True, separators=(',', ':'))


def parse_message(raw: str) -> Optional[dict]:
    """Parse a JSON message. Returns None if invalid."""
    try:
        msg = json.loads(raw)
        if 'type' not in msg:
            return None
        return msg
    except Exception:
        return None
