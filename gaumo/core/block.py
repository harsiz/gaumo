"""
Block structure for Gaumo blockchain.
"""
import time
from dataclasses import dataclass, field
from typing import List

from gaumo.crypto.hashing import canonical_json, sha256d
from gaumo.core.transaction import Transaction


@dataclass
class Block:
    index: int
    previous_hash: str
    timestamp: int
    nonce: int
    transactions: List[Transaction]
    block_hash: str = field(default='')
    difficulty: int = field(default=4)

    def _hashable_dict(self) -> dict:
        return {
            'difficulty': self.difficulty,
            'index': self.index,
            'nonce': self.nonce,
            'previous_hash': self.previous_hash,
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
            difficulty=d.get('difficulty', 4),
        )
        b.block_hash = d.get('block_hash', b.compute_hash())
        return b

    def is_valid_pow(self) -> bool:
        """Check that the block hash meets the difficulty target."""
        target = '0' * self.difficulty
        return self.block_hash.startswith(target)

    def meets_target(self, target: str) -> bool:
        """Check hash against a full target string."""
        return self.block_hash < target
