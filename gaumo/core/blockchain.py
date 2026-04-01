"""
Main blockchain logic: chain management, validation, mining, fork resolution.
Includes disk persistence: chain is saved to a JSON file and loaded on startup.
"""
import json
import os
import threading
import time
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from gaumo.core.block import Block, INITIAL_TARGET
from gaumo.core.transaction import Transaction, TxOutput, make_coinbase_transaction
from gaumo.core.utxo import UTXOSet, UTXO
from gaumo.core.mempool import Mempool
from gaumo.crypto.hashing import canonical_json, sha256d
import binascii

logger = logging.getLogger(__name__)

BLOCK_REWARD = 50 * 100_000_000
HALVING_INTERVAL = 210_000
TARGET_BLOCK_TIME = 180
DIFFICULTY_ADJUSTMENT_INTERVAL = 10
MAX_TARGET = int(INITIAL_TARGET, 16)
MIN_TARGET = 0x0000000000000000000000000000000000000000000000000000000000000001
DEFAULT_CHAIN_FILE = 'chain.json'


def get_block_reward(height: int) -> int:
    halvings = height // HALVING_INTERVAL
    if halvings >= 64:
        return 0
    return BLOCK_REWARD >> halvings


def compute_next_target(chain: List[Block]) -> str:
    n = len(chain)
    if n < DIFFICULTY_ADJUSTMENT_INTERVAL:
        return INITIAL_TARGET
    if n % DIFFICULTY_ADJUSTMENT_INTERVAL != 0:
        return chain[-1].target
    window = chain[-DIFFICULTY_ADJUSTMENT_INTERVAL:]
    actual_time = window[-1].timestamp - window[0].timestamp
    expected_time = TARGET_BLOCK_TIME * DIFFICULTY_ADJUSTMENT_INTERVAL
    actual_time = max(actual_time, expected_time // 4)
    actual_time = min(actual_time, expected_time * 4)
    old_target = int(chain[-1].target, 16)
    new_target = old_target * actual_time // expected_time
    new_target = min(new_target, MAX_TARGET)
    new_target = max(new_target, MIN_TARGET)
    return format(new_target, '064x')


GENESIS_BLOCK_DICT = {
    'index': 0,
    'previous_hash': '0' * 64,
    'timestamp': 1743500000,
    'nonce': 0,
    'transactions': [
        {
            'inputs': [],
            'outputs': [
                {'address': 'gau1GYjEuoWp4VBvQT3gfDW3qVxPNzK1bMNaWKnm7C', 'amount': 50 * 100_000_000}
            ],
            'timestamp': 1743500000,
            'tx_hash': 'genesis_coinbase_0000000000000000000000000000000000000000000000000000000',
        }
    ],
    'target': INITIAL_TARGET,
    'block_hash': '',
}


def _make_genesis_block() -> Block:
    b = Block.from_dict(GENESIS_BLOCK_DICT)
    b.block_hash = b.compute_hash()
    return b


GENESIS_BLOCK = _make_genesis_block()


class Blockchain:
    def __init__(self, chain_file: str = DEFAULT_CHAIN_FILE):
        self._lock = threading.RLock()
        self.chain_file = chain_file
        self.chain: List[Block] = []
        self.utxo_set = UTXOSet()
        self.mempool = Mempool()
        self._load_or_init()

    def _load_or_init(self):
        """Load chain from disk, or start fresh from genesis."""
        if self.chain_file and Path(self.chain_file).exists():
            try:
                self._load_chain()
                logger.info(f"Loaded chain from {self.chain_file}. Height: {self.height}")
                return
            except Exception as e:
                logger.warning(f"Failed to load chain from disk: {e}. Starting fresh.")
        self._init_genesis()

    def _init_genesis(self):
        self.chain = [GENESIS_BLOCK]
        self.utxo_set = UTXOSet()
        for tx in GENESIS_BLOCK.transactions:
            self.utxo_set.apply_transaction(tx, 0)

    def _load_chain(self):
        with open(self.chain_file, 'r') as f:
            raw = json.load(f)
        blocks = [Block.from_dict(b) for b in raw]
        if not blocks:
            raise ValueError("Empty chain file")
        # Replay chain to rebuild UTXO set
        self.utxo_set = UTXOSet()
        self.chain = []
        for block in blocks:
            self.chain.append(block)
            for tx in block.transactions:
                self.utxo_set.apply_transaction(tx, block.index)

    def save_chain(self):
        """Persist the current chain to disk."""
        if not self.chain_file:
            return
        try:
            tmp = self.chain_file + '.tmp'
            with open(tmp, 'w') as f:
                json.dump([b.to_dict() for b in self.chain], f, separators=(',', ':'))
            os.replace(tmp, self.chain_file)
        except Exception as e:
            logger.error(f"Failed to save chain: {e}")

    @property
    def height(self) -> int:
        return len(self.chain) - 1

    @property
    def last_block(self) -> Block:
        return self.chain[-1]

    def get_block(self, index: int) -> Optional[Block]:
        if 0 <= index < len(self.chain):
            return self.chain[index]
        return None

    def get_block_by_hash(self, block_hash: str) -> Optional[Block]:
        for b in self.chain:
            if b.block_hash == block_hash:
                return b
        return None

    def get_next_target(self) -> str:
        return compute_next_target(self.chain)

    def validate_block(self, block: Block) -> Tuple[bool, str]:
        computed = block.compute_hash()
        if computed != block.block_hash:
            return False, f"Hash mismatch: {computed} != {block.block_hash}"
        if not block.is_valid_pow():
            return False, "Invalid PoW: hash does not meet target"
        if block.index > 0:
            expected_target = compute_next_target(self.chain[:block.index])
            if block.target != expected_target:
                return False, (
                    f"Wrong target at block {block.index}: "
                    f"got {block.target[:16]}... expected {expected_target[:16]}..."
                )
        if block.index > 0:
            prev = self.get_block(block.index - 1)
            if prev is None or prev.block_hash != block.previous_hash:
                return False, "Previous hash mismatch"
        if not block.transactions:
            return False, "Block has no transactions"
        coinbase_count = sum(1 for tx in block.transactions if tx.is_coinbase)
        if coinbase_count != 1 or not block.transactions[0].is_coinbase:
            return False, "Block must have exactly one coinbase as first transaction"
        for tx in block.transactions[1:]:
            if not tx.verify_signatures():
                return False, f"Invalid signature in tx {tx.tx_hash}"
        return True, ""

    def add_block(self, block: Block) -> Tuple[bool, str]:
        with self._lock:
            if block.index != self.height + 1:
                return False, f"Expected height {self.height + 1}, got {block.index}"
            valid, err = self.validate_block(block)
            if not valid:
                return False, err
            valid, err = self._validate_block_utxos(block)
            if not valid:
                return False, err
            for tx in block.transactions:
                self.utxo_set.apply_transaction(tx, block.index)
                if not tx.is_coinbase:
                    self.mempool.remove(tx.tx_hash)
            self.chain.append(block)
            self.save_chain()
            logger.info(f"Added block #{block.index} hash={block.block_hash[:16]}... target={block.target[:16]}...")
            return True, ""

    def _validate_block_utxos(self, block: Block) -> Tuple[bool, str]:
        spent_in_block: set = set()
        total_fees = 0
        for tx in block.transactions[1:]:
            input_sum = 0
            for inp in tx.inputs:
                key = (inp.tx_hash, inp.output_index)
                if key in spent_in_block:
                    return False, f"Double spend in block: {inp.tx_hash}:{inp.output_index}"
                spent_in_block.add(key)
                utxo = self.utxo_set.get(inp.tx_hash, inp.output_index)
                if utxo is None:
                    return False, f"UTXO not found: {inp.tx_hash}:{inp.output_index}"
                pub_bytes = binascii.unhexlify(inp.public_key)
                from gaumo.crypto.keys import public_key_to_address
                if public_key_to_address(pub_bytes) != utxo.address:
                    return False, "Public key/address mismatch"
                input_sum += utxo.amount
            output_sum = sum(o.amount for o in tx.outputs)
            if input_sum < output_sum:
                return False, "Inputs < outputs"
            total_fees += input_sum - output_sum
        coinbase = block.transactions[0]
        expected_reward = get_block_reward(block.index) + total_fees
        coinbase_out = sum(o.amount for o in coinbase.outputs)
        if coinbase_out > expected_reward:
            return False, f"Coinbase reward too large: {coinbase_out} > {expected_reward}"
        return True, ""

    def replace_chain(self, new_chain: List[Block]) -> Tuple[bool, str]:
        with self._lock:
            if len(new_chain) <= len(self.chain):
                return False, "New chain is not longer"
            temp_utxo = UTXOSet()
            for i, block in enumerate(new_chain):
                computed = block.compute_hash()
                if computed != block.block_hash:
                    return False, f"Bad hash at block {i}"
                if not block.is_valid_pow():
                    return False, f"Bad PoW at block {i}"
                if i > 0:
                    if block.previous_hash != new_chain[i-1].block_hash:
                        return False, f"Bad previous_hash at block {i}"
                    expected_target = compute_next_target(new_chain[:i])
                    if block.target != expected_target:
                        return False, f"Bad target at block {i}"
                for tx in block.transactions:
                    temp_utxo.apply_transaction(tx, block.index)
            self.chain = new_chain
            self.utxo_set = temp_utxo
            self.mempool = Mempool()
            self.save_chain()
            logger.info(f"Chain replaced. New height: {self.height}")
            return True, ""

    def get_blocks_from(self, start_index: int) -> List[Block]:
        return self.chain[start_index:]

    def to_dict(self) -> List[dict]:
        return [b.to_dict() for b in self.chain]

    def get_balance(self, address: str) -> int:
        return self.utxo_set.get_balance(address)
