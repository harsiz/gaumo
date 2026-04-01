"""
Proof-of-Work miner for Gaumo.
Embedded into the node. Mines blocks using SHA-256.
Periodically checks for newly broadcast blocks to avoid wasted work.
"""
import hashlib
import json
import logging
import threading
import time
from typing import Callable, Optional

from gaumo.core.block import Block
from gaumo.core.blockchain import Blockchain, get_block_reward
from gaumo.core.transaction import make_coinbase_transaction
from gaumo.crypto.hashing import canonical_json, sha256d
from gaumo.core.block import INITIAL_TARGET

logger = logging.getLogger(__name__)


class Miner:
    def __init__(self, blockchain: Blockchain, miner_address: str,
                 on_block_found: Optional[Callable] = None):
        self.blockchain = blockchain
        self.miner_address = miner_address
        self.on_block_found = on_block_found  # callback(block)

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Stats
        self.total_hashes = 0
        self.start_time = 0.0
        self.blocks_found = 0
        self.last_hash_rate = 0.0

    def start(self):
        """Start mining in a background thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._mine_loop, daemon=True, name="GaumoMiner")
        self._thread.start()
        logger.info(f"Miner started. Address: {self.miner_address}")

    def stop(self):
        """Stop mining."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Miner stopped")

    @property
    def hash_rate(self) -> float:
        """Current estimated hashes per second."""
        elapsed = time.time() - self.start_time
        if elapsed <= 0:
            return 0.0
        return self.total_hashes / elapsed

    def get_stats(self) -> dict:
        return {
            'running': self._running,
            'hash_rate': round(self.hash_rate, 2),
            'total_hashes': self.total_hashes,
            'blocks_found': self.blocks_found,
            'miner_address': self.miner_address,
        }

    def _mine_loop(self):
        self.start_time = time.time()
        self.total_hashes = 0

        while self._running and not self._stop_event.is_set():
            try:
                self._mine_one_block()
            except Exception as e:
                logger.error(f"Mining error: {e}")
                time.sleep(1)

    def _mine_one_block(self):
        """Attempt to mine a single block."""
        bc = self.blockchain

        # Gather transactions from mempool
        txs = bc.mempool.get_transactions(max_count=100)
        target = bc.get_next_target()
        target_int = int(target, 16)
        reward = get_block_reward(bc.height + 1)
        fee_total = self._calc_fees(txs)

        coinbase = make_coinbase_transaction(
            self.miner_address,
            reward + fee_total,
            bc.height + 1,
        )
        all_txs = [coinbase] + txs

        prev_block = bc.last_block
        template = Block(
            index=prev_block.index + 1,
            previous_hash=prev_block.block_hash,
            timestamp=int(time.time()),
            nonce=0,
            transactions=all_txs,
            target=target,
        )

        nonce = 0
        last_check = time.time()
        CHECK_INTERVAL = 5.0  # seconds between block/chain checks

        logger.info(f"Mining block #{template.index} | target={target[:16]}... | txs={len(all_txs)}")

        while self._running and not self._stop_event.is_set():
            template.nonce = nonce
            template.timestamp = int(time.time())
            h = sha256d(canonical_json(template._hashable_dict())).hex()
            self.total_hashes += 1

            if int(h, 16) < target_int:
                template.block_hash = h
                logger.info(f"Block found! #{template.index} hash={h[:20]}... nonce={nonce}")
                ok, err = bc.add_block(template)
                if ok:
                    self.blocks_found += 1
                    if self.on_block_found:
                        self.on_block_found(template)
                    self._log_stats()
                else:
                    logger.warning(f"Mined block rejected: {err}")
                return

            nonce += 1

            # Periodically check if chain changed (someone else found a block)
            now = time.time()
            if now - last_check >= CHECK_INTERVAL:
                if bc.last_block.block_hash != prev_block.block_hash:
                    logger.info("New block detected. Restarting mining...")
                    return
                self._log_stats()
                last_check = now

    def _calc_fees(self, txs) -> int:
        """Calculate total fees from a list of transactions."""
        total = 0
        for tx in txs:
            if tx.is_coinbase:
                continue
            input_sum = sum(
                (self.blockchain.utxo_set.get(inp.tx_hash, inp.output_index).amount
                 if self.blockchain.utxo_set.get(inp.tx_hash, inp.output_index) else 0)
                for inp in tx.inputs
            )
            output_sum = sum(out.amount for out in tx.outputs)
            total += max(0, input_sum - output_sum)
        return total

    def _log_stats(self):
        elapsed = time.time() - self.start_time
        rate = self.total_hashes / elapsed if elapsed > 0 else 0
        target = self.blockchain.get_next_target()
        logger.info(
            f"[Miner] Hashes: {self.total_hashes:,} | "
            f"Rate: {rate:,.0f} H/s | "
            f"Blocks: {self.blocks_found} | "
            f"Height: {self.blockchain.height} | "
            f"Target: {target[:16]}..."
        )
