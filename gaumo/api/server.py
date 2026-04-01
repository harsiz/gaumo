"""
REST API for Gaumo node.
Provides endpoints for wallets, explorers, and external tools.
"""
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from typing import Optional
from urllib.parse import urlparse, parse_qs
import binascii

logger = logging.getLogger(__name__)


class GaumoAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.debug(f"API: {format % args}")

    def _send_json(self, status: int, data):
        body = json.dumps(data, sort_keys=True, indent=2).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, message: str):
        self._send_json(status, {'error': message})

    def _read_body(self) -> dict:
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')
        blockchain = self.server.blockchain
        node = self.server.node

        if path == '/status':
            self._send_json(200, {
                'height': blockchain.height,
                'last_block_hash': blockchain.last_block.block_hash,
                'peers': node.get_peer_count() if node else 0,
                'mempool_size': blockchain.mempool.size(),
                'difficulty': blockchain.get_current_difficulty(),
            })

        elif path == '/chain':
            qs = parse_qs(parsed.query)
            start = int(qs.get('start', ['0'])[0])
            limit = min(int(qs.get('limit', ['50'])[0]), 100)
            blocks = blockchain.get_blocks_from(start)[:limit]
            self._send_json(200, [b.to_dict() for b in blocks])

        elif path.startswith('/block/'):
            idx_or_hash = path[len('/block/'):]
            block = None
            if len(idx_or_hash) == 64:
                block = blockchain.get_block_by_hash(idx_or_hash)
            else:
                try:
                    block = blockchain.get_block(int(idx_or_hash))
                except ValueError:
                    pass
            if block:
                self._send_json(200, block.to_dict())
            else:
                self._send_error(404, 'Block not found')

        elif path.startswith('/balance/'):
            address = path[len('/balance/'):]
            balance = blockchain.get_balance(address)
            self._send_json(200, {'address': address, 'balance': balance, 'balance_gau': balance / 1e8})

        elif path == '/mempool':
            self._send_json(200, blockchain.mempool.to_list())

        elif path == '/peers':
            self._send_json(200, node.get_peer_list() if node else [])

        elif path.startswith('/utxos/'):
            address = path[len('/utxos/'):]
            utxos = blockchain.utxo_set.get_utxos_for_address(address)
            self._send_json(200, [u.to_dict() for u in utxos])

        else:
            self._send_error(404, 'Not found')

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')
        blockchain = self.server.blockchain
        node = self.server.node

        if path == '/transaction':
            try:
                data = self._read_body()
                from gaumo.core.transaction import Transaction
                tx = Transaction.from_dict(data)
                tx.tx_hash = tx.compute_hash()
                ok, err = blockchain.mempool.add(tx, blockchain.utxo_set)
                if ok:
                    if node:
                        node.broadcast_transaction(tx)
                    self._send_json(200, {'tx_hash': tx.tx_hash, 'status': 'accepted'})
                else:
                    self._send_error(400, err)
            except Exception as e:
                self._send_error(400, str(e))

        elif path == '/broadcast/block':
            try:
                data = self._read_body()
                from gaumo.core.block import Block
                block = Block.from_dict(data)
                ok, err = blockchain.add_block(block)
                if ok:
                    if node:
                        node.broadcast_block(block)
                    self._send_json(200, {'block_hash': block.block_hash, 'status': 'accepted'})
                else:
                    self._send_error(400, err)
            except Exception as e:
                self._send_error(400, str(e))

        else:
            self._send_error(404, 'Not found')


class APIServer:
    def __init__(self, blockchain, node=None, host='0.0.0.0', port=8080):
        self.blockchain = blockchain
        self.node = node
        self.host = host
        self.port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._server = HTTPServer((self.host, self.port), GaumoAPIHandler)
        self._server.blockchain = self.blockchain
        self._server.node = self.node
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f"API server started on http://{self.host}:{self.port}")

    def stop(self):
        if self._server:
            self._server.shutdown()
