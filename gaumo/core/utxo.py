"""
UTXO set management for Gaumo.
Tracks unspent transaction outputs.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from gaumo.core.transaction import Transaction, TxOutput
from gaumo.crypto.keys import public_key_to_address
import binascii


@dataclass
class UTXO:
    tx_hash: str
    output_index: int
    address: str
    amount: int
    block_height: int

    def to_dict(self) -> dict:
        return {
            'tx_hash': self.tx_hash,
            'output_index': self.output_index,
            'address': self.address,
            'amount': self.amount,
            'block_height': self.block_height,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'UTXO':
        return cls(**d)


class UTXOSet:
    """In-memory UTXO set."""

    def __init__(self):
        # key: (tx_hash, output_index) -> UTXO
        self._utxos: Dict[Tuple[str, int], UTXO] = {}

    def add(self, utxo: UTXO):
        self._utxos[(utxo.tx_hash, utxo.output_index)] = utxo

    def remove(self, tx_hash: str, output_index: int) -> Optional[UTXO]:
        return self._utxos.pop((tx_hash, output_index), None)

    def get(self, tx_hash: str, output_index: int) -> Optional[UTXO]:
        return self._utxos.get((tx_hash, output_index))

    def exists(self, tx_hash: str, output_index: int) -> bool:
        return (tx_hash, output_index) in self._utxos

    def get_balance(self, address: str) -> int:
        return sum(u.amount for u in self._utxos.values() if u.address == address)

    def get_utxos_for_address(self, address: str) -> List[UTXO]:
        return [u for u in self._utxos.values() if u.address == address]

    def apply_transaction(self, tx: Transaction, block_height: int):
        """Spend inputs and create outputs."""
        for inp in tx.inputs:
            self.remove(inp.tx_hash, inp.output_index)
        for idx, out in enumerate(tx.outputs):
            self.add(UTXO(
                tx_hash=tx.tx_hash,
                output_index=idx,
                address=out.address,
                amount=out.amount,
                block_height=block_height,
            ))

    def rollback_transaction(self, tx: Transaction, block_height: int, prev_utxos: List[UTXO]):
        """Undo a transaction (for chain reorganization)."""
        for idx in range(len(tx.outputs)):
            self.remove(tx.tx_hash, idx)
        for utxo in prev_utxos:
            self.add(utxo)

    def snapshot(self) -> dict:
        return {f"{k[0]}:{k[1]}": v.to_dict() for k, v in self._utxos.items()}

    def load_snapshot(self, data: dict):
        self._utxos.clear()
        for key, val in data.items():
            tx_hash, idx = key.rsplit(':', 1)
            utxo = UTXO.from_dict(val)
            self._utxos[(utxo.tx_hash, utxo.output_index)] = utxo
