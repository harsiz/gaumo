"""
Main blockchain logic: chain management, validation, mining, fork resolution.
"""
import threading
import time
import logging
from typing import List, Optional, Tuple, Dict

from gaumo.core.block import Block
from gaumo.core.transaction import Transaction, TxOutput, make_coinbase_transaction
from gaumo.core.utxo import UTXOSet, UTXO
from gaumo.core.mempool import Mempool
from gaumo.crypto.hashing import canonical_json, sha256d
import binascii

logger = logging.getLogger(__name__)

# Constants
BLOCK_REWARD = 50 * 100_000_000   # 50 GAU in satoshis
HALVING_INTERVAL = 210_000         # blocks
TARGET_BLOCK_TIME = 180            # seconds (3 minutes)
DIFFICULTY_ADJUSTMENT_INTERVAL = 10  # blocks
MAX_BLOCK_SIZE_TXS = 500
GENESIS_HASH = '0' * 64

def get_block_reward(height: int) -> int:
    halvings = height // HALVING_INTERVAL
    if halvings >= 64:
        return 0
    return BLOCK_REWARD >> halvings


def difficulty_to_target(difficulty: int) -> str:
    """Convert integer difficulty (leading zeros) to a target hex string."""
    return '0' * difficulty + 'f' * (64 - difficulty)


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
    'difficulty': 4,
    'block_hash': '',
}


def _make_genesis_block() -> Block:
    b = Block.from_dict(GENESIS_BLOCK_DICT)
    b.block_hash = b.compute_hash()
    return b


GENESIS_BLOCK = _make_genesis_block()


class Blockchain:
    def __init__(self):
        self._lock = threading.RLock()
        self.chain: List[Block] = []
        self.utxo_set = UTXOSet()
        self.mempool = Mempool()
        self._init_genesis()

    def _init_genesis(self):
        self.chain = [GENESIS_BLOCK]
        # Apply genesis transactions to UTXO set
        for tx in GENESIS_BLOCK.transactions:
            self.utxo_set.apply_transaction(tx, 0)

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

    def get_current_difficulty(self) -> int:
        if len(self.chain) < DIFFICULTY_ADJUSTMENT_INTERVAL:
            return 4
        if len(self.chain) % DIFFICULTY_ADJUSTMENT_INTERVAL != 0:
            return self.last_block.difficulty

        # Adjust difficulty
        recent = self.chain[-DIFFICULTY_ADJUSTMENT_INTERVAL:]
        actual_time = recent[-1].timestamp - recent[0].timestamp
        expected_time = TARGET_BLOCK_TIME * DIFFICULTY_ADJUSTMENT_INTERVAL

        current_diff = self.last_block.difficulty
        if actual_time == 0:
            actual_time = 1

        ratio = expected_time / actual_time
        new_diff = current_diff
        if ratio > 1.25:
            new_diff = current_diff + 1
        elif ratio < 0.75:
            new_diff = max(1, current_diff - 1)

        new_diff = max(1, min(new_diff, 64))
        return new_diff

    def validate_block(self, block: Block) -> Tuple[bool, str]:
        """Validate a single block (not including UTXO validation)."""
        # Check hash
        computed = block.compute_hash()
        if computed != block.block_hash:
            return False, f"Hash mismatch: {computed} != {block.block_hash}"

        # Check PoW
        if not block.is_valid_pow():
            return False, f"Invalid PoW: {block.block_hash}"

        # Check previous hash
        if block.index > 0:
            prev = self.get_block(block.index - 1)
            if prev is None or prev.block_hash != block.previous_hash:
                return False, "Previous hash mismatch"

        # Check transactions
        if not block.transactions:
            return False, "Block has no transactions"

        coinbase_count = sum(1 for tx in block.transactions if tx.is_coinbase)
        if coinbase_count != 1 or not block.transactions[0].is_coinbase:
            return False, "Block must have exactly one coinbase as first transaction"

        # Validate non-coinbase transactions
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

            # Validate UTXOs
            valid, err = self._validate_block_utxos(block)
            if not valid:
                return False, err

            # Apply transactions
            for tx in block.transactions:
                self.utxo_set.apply_transaction(tx, block.index)
                if not tx.is_coinbase:
                    self.mempool.remove(tx.tx_hash)

            self.chain.append(block)
            logger.info(f"Added block #{block.index} hash={block.block_hash[:16]}...")
            return True, ""

    def _validate_block_utxos(self, block: Block) -> Tuple[bool, str]:
        """Validate all transactions in a block against the UTXO set."""
        spent_in_block: set = set()
        total_fees = 0

        for tx in block.transactions[1:]:  # skip coinbase
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

        # Validate coinbase reward
        coinbase = block.transactions[0]
        expected_reward = get_block_reward(block.index) + total_fees
        coinbase_out = sum(o.amount for o in coinbase.outputs)
        if coinbase_out > expected_reward:
            return False, f"Coinbase reward too large: {coinbase_out} > {expected_reward}"

        return True, ""

    def replace_chain(self, new_chain: List[Block]) -> Tuple[bool, str]:
        """Replace chain if new_chain is longer and valid."""
        with self._lock:
            if len(new_chain) <= len(self.chain):
                return False, "New chain is not longer"

            # Validate entire new chain
            temp_utxo = UTXOSet()
            for i, block in enumerate(new_chain):
                computed = block.compute_hash()
                if computed != block.block_hash:
                    return False, f"Bad hash at block {i}"
                if not block.is_valid_pow():
                    return False, f"Bad PoW at block {i}"
                if i > 0 and block.previous_hash != new_chain[i-1].block_hash:
                    return False, f"Bad previous_hash at block {i}"
                for tx in block.transactions:
                    temp_utxo.apply_transaction(tx, block.index)

            # Replace
            self.chain = new_chain
            self.utxo_set = temp_utxo
            # Rebuild mempool validity (simplified: just clear it)
            self.mempool = Mempool()
            logger.info(f"Chain replaced. New height: {self.height}")
            return True, ""

    def get_blocks_from(self, start_index: int) -> List[Block]:
        return self.chain[start_index:]

    def to_dict(self) -> List[dict]:
        return [b.to_dict() for b in self.chain]

    def get_balance(self, address: str) -> int:
        return self.utxo_set.get_balance(address)
