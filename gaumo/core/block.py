"""
Block structure for Gaumo blockchain.
"""
import time
from dataclasses import dataclass, field
from typing import List

from gaumo.crypto.hashing import canonical_json, sha256d
from gaumo.core.transaction import Transaction

# Initial target: hash must be below this 256-bit value.
# This is roughly equivalent to 5 leading zero hex digits.
INITIAL_TARGET = '00000fffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'


@dataclass
class Block:
    index: int
    previous_hash: str
    timestamp: int
    nonce: int
    transactions: List[Transaction]
    block_hash: str = field(default='')
    target: str = field(default=INITIAL_TARGET)

    def _hashable_dict(self) -> dict:
        return {
            'index': self.index,
            'nonce': self.nonce,
            'previous_hash': self.previous_hash,
            'target': self.target,
            'timestamp': self.timestamp,
            'transactions': [tx.to_dict() for tx in self.transactions],
        }

    def compute_hash(self) -> str:
        return sha256d(canonical_json(self._hashable_dict())).hex()

    def to_dict(self) -> dict:
        d = self._hashable_dict()
        d['block_hash'] = self.block_hash
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'Block':
        b = cls(
            index=d['index'],
            previous_hash=d['previous_hash'],
            timestamp=d['timestamp'],
            nonce=d['nonce'],
            transactions=[Transaction.from_dict(tx) for tx in d['transactions']],
            target=d.get('target', INITIAL_TARGET),
        )
        b.block_hash = d.get('block_hash', b.compute_hash())
        return b

    def is_valid_pow(self) -> bool:
        """Check that the block hash is numerically below the target."""
        return int(self.block_hash, 16) < int(self.target, 16)
