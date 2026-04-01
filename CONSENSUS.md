# Gaumo Consensus

## Proof of Work

Gaumo uses SHA-256d Proof of Work. Miners must find a nonce such that:

```
SHA256d(canonical_json(block)) < target
```

Target is represented as a leading zeros prefix. Difficulty 4 means the hash must start with `0000`.

## Block Time

Target: 3 minutes (180 seconds) per block.

## Difficulty Adjustment

Difficulty adjusts every 10 blocks based on actual vs expected time:

```
ratio = expected_time / actual_time
if ratio > 1.25: difficulty += 1  (too fast, harder)
if ratio < 0.75: difficulty -= 1  (too slow, easier)
```

Minimum difficulty: 1. Maximum difficulty: 64.

## Block Reward

Starting reward: 50 GAU per block.
Halvings occur every 210,000 blocks.

```
reward = 50 GAU >> (height // 210000)
```

## Chain Selection

The longest valid chain wins (most total blocks). Nodes replace their chain when they see a longer valid chain.

## Block Validation

1. Hash matches computed hash
2. Hash meets difficulty target (leading zeros)
3. Previous hash matches previous block
4. First transaction is coinbase, only one coinbase
5. All transaction signatures valid
6. No double-spending (all UTXOs exist and unspent)
7. Coinbase reward <= block_reward + fees

## Transaction Fees

Fee = sum(inputs) - sum(outputs). Fees collected by miner via coinbase.
