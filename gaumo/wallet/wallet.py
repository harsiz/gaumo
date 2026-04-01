"""
Wallet management for Gaumo.
Generates, stores, and loads keypairs. Signs transactions.
"""
import binascii
import json
import os
from pathlib import Path
from typing import List, Optional, Tuple

from gaumo.core.transaction import Transaction, TxInput, TxOutput
from gaumo.core.utxo import UTXOSet, UTXO
from gaumo.crypto.keys import (
    generate_keypair, private_key_to_public_key, public_key_to_address,
    sign, private_key_to_wif, wif_to_private_key,
)
from gaumo.crypto.hashing import canonical_json


class Wallet:
    def __init__(self, private_key_bytes: bytes):
        self.private_key = private_key_bytes
        self.public_key = private_key_to_public_key(private_key_bytes)
        self.address = public_key_to_address(self.public_key)

    @classmethod
    def generate(cls) -> 'Wallet':
        priv, _ = generate_keypair()
        return cls(priv)

    @classmethod
    def from_wif(cls, wif: str) -> 'Wallet':
        priv = wif_to_private_key(wif)
        return cls(priv)

    @property
    def wif(self) -> str:
        return private_key_to_wif(self.private_key)

    def get_balance(self, utxo_set: UTXOSet) -> int:
        return utxo_set.get_balance(self.address)

    def create_transaction(
        self,
        recipient: str,
        amount: int,
        fee: int,
        utxo_set: UTXOSet,
    ) -> Transaction:
        """
        Build and sign a transaction sending `amount` satoshis to `recipient`.
        `fee` is deducted from the sender's change.
        """
        utxos = utxo_set.get_utxos_for_address(self.address)
        utxos.sort(key=lambda u: u.amount, reverse=True)  # largest first

        selected: List[UTXO] = []
        total = 0
        need = amount + fee
        for utxo in utxos:
            selected.append(utxo)
            total += utxo.amount
            if total >= need:
                break

        if total < need:
            raise ValueError(f"Insufficient balance: have {total}, need {need}")

        inputs = []
        # We'll sign after building the tx
        for utxo in selected:
            inputs.append(TxInput(
                tx_hash=utxo.tx_hash,
                output_index=utxo.output_index,
                signature='',
                public_key=self.public_key.hex(),
            ))

        outputs = [TxOutput(address=recipient, amount=amount)]
        change = total - amount - fee
        if change > 0:
            outputs.append(TxOutput(address=self.address, amount=change))

        import time
        tx = Transaction(inputs=inputs, outputs=outputs, timestamp=int(time.time()))
        tx.tx_hash = tx.compute_hash()

        # Sign all inputs
        signable = tx.get_signable_bytes()
        sig_bytes = sign(self.private_key, signable)
        sig_hex = sig_bytes.hex()
        for inp in tx.inputs:
            inp.signature = sig_hex

        # Recompute hash after signatures are set
        tx.tx_hash = tx.compute_hash()
        return tx

    def save(self, path: str):
        """Save wallet to a JSON file."""
        data = {
            'wif': self.wif,
            'address': self.address,
            'public_key': self.public_key.hex(),
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: str) -> 'Wallet':
        """Load wallet from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        return cls.from_wif(data['wif'])
