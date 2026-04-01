# Gaumo Architecture

## Overview

Gaumo (GAU) is a modular Python cryptocurrency with:
- UTXO-based transaction model
- SHA-256 Proof of Work consensus
- Outbound-only P2P networking (no port forwarding required)
- REST API, CLI, and GUI interfaces

## Module Structure

```
gaumo/
  core/          # Blockchain logic
    blockchain.py  - Chain management, validation, fork resolution
    block.py       - Block data structure
    transaction.py - UTXO transaction model
    utxo.py        - UTXO set management
    mempool.py     - Unconfirmed transaction pool
  crypto/        # Cryptographic primitives
    keys.py        - ECDSA secp256k1 keypairs, address derivation
    hashing.py     - Canonical JSON encoding, SHA-256d hashing
  net/           # P2P networking
    node.py        - Node orchestration, peer management
    peer.py        - WebSocket peer connection
    protocol.py    - Message type constants and serialization
  mining/        # Proof of Work miner
    miner.py       - SHA-256 mining with stats
  wallet/        # Key and transaction management
    wallet.py      - Keypair management, transaction signing
  api/           # REST API
    server.py      - HTTP server exposing blockchain data
  cli/           # Command-line interface
    cli.py         - argparse-based CLI
  gui/           # Graphical interface
    app.py         - Tkinter wallet GUI
```

## Data Flow

```
User → CLI/GUI → Wallet (sign tx) → API → Blockchain/Mempool → P2P Node → Peers
                                              ↑
                                           Miner
```

## Key Design Decisions

### Outbound-Only Networking
Nodes use outbound WebSocket connections to peers. No inbound port forwarding required. Nodes can optionally open a listen port to accept inbound connections (improving decentralization).

### Canonical JSON
All data is serialized with sorted keys and no whitespace for consistent hashing.

### UTXO Model
Transactions reference previous outputs explicitly. The UTXO set tracks all spendable outputs.

### Thread Safety
- Blockchain operations are protected by RLock
- Mempool operations are protected by Lock
- API runs in a separate daemon thread
- Mining runs in a separate daemon thread
- P2P networking runs in an asyncio event loop in a separate thread
