"""
Mempool: stores unconfirmed transactions pending inclusion in a block.
"""
import threading
from typing import Dict, List, Optional, Set, Tuple

from gaumo.core.transaction import Transaction
from gaumo.core.utxo import UTXOSet
from gaumo.crypto.keys import public_key_to_address
import binascii


class Mempool:
    def __init__(self):
        self._txs: Dict[str, Transaction] = {}
        self._lock = threading.Lock()

    def add(self, tx: Transaction, utxo_set: UTXOSet) -> Tuple[bool, str]:
        """
        Validate and add a transaction to the mempool.
        Returns (success, error_message).
        """
        with self._lock:
            if tx.tx_hash in self._txs:
                return False, "Transaction already in mempool"

            valid, err = self._validate(tx, utxo_set)
            if not valid:
                return False, err

            self._txs[tx.tx_hash] = tx
            return True, ""

    def _validate(self, tx: Transaction, utxo_set: UTXOSet) -> Tuple[bool, str]:
        if tx.is_coinbase:
            return False, "Coinbase transactions not allowed in mempool"

        if not tx.verify_signatures():
            return False, "Invalid signatures"

        input_sum = 0
        seen_inputs: Set[Tuple[str, int]] = set()

        for inp in tx.inputs:
            key = (inp.tx_hash, inp.output_index)
            if key in seen_inputs:
                return False, "Duplicate input"
            seen_inputs.add(key)

            utxo = utxo_set.get(inp.tx_hash, inp.output_index)
            if utxo is None:
                # Check if already spent by another mempool tx
                if self._is_spent_in_mempool(inp.tx_hash, inp.output_index):
                    return False, f"Input {inp.tx_hash}:{inp.output_index} double-spent in mempool"
                return False, f"UTXO {inp.tx_hash}:{inp.output_index} not found"

            # Verify public key matches address
            pub_bytes = binascii.unhexlify(inp.public_key)
            derived_addr = public_key_to_address(pub_bytes)
            if derived_addr != utxo.address:
                return False, "Public key does not match UTXO address"

            input_sum += utxo.amount

        output_sum = sum(out.amount for out in tx.outputs)
        if output_sum <= 0:
            return False, "Output sum must be positive"
        if input_sum < output_sum:
            return False, f"Inputs ({input_sum}) < outputs ({output_sum})"

        return True, ""

    def _is_spent_in_mempool(self, tx_hash: str, output_index: int) -> bool:
        for tx in self._txs.values():
            for inp in tx.inputs:
                if inp.tx_hash == tx_hash and inp.output_index == output_index:
                    return True
        return False

    def remove(self, tx_hash: str):
        with self._lock:
            self._txs.pop(tx_hash, None)

    def remove_confirmed(self, tx_hashes: List[str]):
        with self._lock:
            for h in tx_hashes:
                self._txs.pop(h, None)

    def get_transactions(self, max_count: int = 100) -> List[Transaction]:
        with self._lock:
            # Sort by fee rate (fee / size) - simple approximation by fee amount
            txs = list(self._txs.values())
            return txs[:max_count]

    def get(self, tx_hash: str) -> Optional[Transaction]:
        return self._txs.get(tx_hash)

    def size(self) -> int:
        return len(self._txs)

    def to_list(self) -> List[dict]:
        with self._lock:
            return [tx.to_dict() for tx in self._txs.values()]
