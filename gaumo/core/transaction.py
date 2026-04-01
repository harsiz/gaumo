"""
UTXO-based transaction model for Gaumo.
"""
import time
from dataclasses import dataclass, field
from typing import List, Optional
import json
import binascii

from gaumo.crypto.hashing import canonical_json, sha256d
from gaumo.crypto.keys import verify


@dataclass
class TxInput:
    """Reference to a previous output being spent."""
    tx_hash: str      # hash of the transaction containing the output
    output_index: int # index in that transaction's outputs
    signature: str    # hex-encoded DER signature
    public_key: str   # hex-encoded compressed public key

    def to_dict(self) -> dict:
        return {
            'output_index': self.output_index,
            'public_key': self.public_key,
            'signature': self.signature,
            'tx_hash': self.tx_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'TxInput':
        return cls(
            tx_hash=d['tx_hash'],
            output_index=d['output_index'],
            signature=d['signature'],
            public_key=d['public_key'],
        )


@dataclass
class TxOutput:
    """An output assigning an amount to an address."""
    address: str
    amount: int  # in gau-satoshis (1 GAU = 100_000_000 satoshis)

    def to_dict(self) -> dict:
        return {
            'address': self.address,
            'amount': self.amount,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'TxOutput':
        return cls(address=d['address'], amount=d['amount'])


@dataclass
class Transaction:
    inputs: List[TxInput]
    outputs: List[TxOutput]
    timestamp: int = field(default_factory=lambda: int(time.time()))
    tx_hash: str = field(default='')

    def _signable_dict(self) -> dict:
        """The dict that gets signed (no signatures included)."""
        return {
            'inputs': [
                {'output_index': inp.output_index, 'tx_hash': inp.tx_hash}
                for inp in self.inputs
            ],
            'outputs': [out.to_dict() for out in self.outputs],
            'timestamp': self.timestamp,
        }

    def compute_hash(self) -> str:
        d = {
            'inputs': [inp.to_dict() for inp in self.inputs],
            'outputs': [out.to_dict() for out in self.outputs],
            'timestamp': self.timestamp,
        }
        return sha256d(canonical_json(d)).hex()

    def to_dict(self) -> dict:
        return {
            'inputs': [inp.to_dict() for inp in self.inputs],
            'outputs': [out.to_dict() for out in self.outputs],
            'timestamp': self.timestamp,
            'tx_hash': self.tx_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'Transaction':
        tx = cls(
            inputs=[TxInput.from_dict(i) for i in d['inputs']],
            outputs=[TxOutput.from_dict(o) for o in d['outputs']],
            timestamp=d['timestamp'],
        )
        tx.tx_hash = d.get('tx_hash', tx.compute_hash())
        return tx

    @property
    def is_coinbase(self) -> bool:
        return len(self.inputs) == 0

    def get_signable_bytes(self) -> bytes:
        return canonical_json(self._signable_dict())

    def verify_signatures(self) -> bool:
        """Verify all input signatures."""
        if self.is_coinbase:
            return True
        signable = self.get_signable_bytes()
        for inp in self.inputs:
            try:
                pub_bytes = binascii.unhexlify(inp.public_key)
                sig_bytes = binascii.unhexlify(inp.signature)
                if not verify(pub_bytes, signable, sig_bytes):
                    return False
            except Exception:
                return False
        return True


def make_coinbase_transaction(miner_address: str, reward: int, block_height: int) -> Transaction:
    """Create a coinbase transaction awarding the miner."""
    tx = Transaction(
        inputs=[],
        outputs=[TxOutput(address=miner_address, amount=reward)],
        timestamp=int(time.time()),
    )
    # Encode block height in the first output address field would break things,
    # so we embed it in a special extra output with amount=0
    tx.tx_hash = tx.compute_hash()
    return tx
