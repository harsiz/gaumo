# Gaumo Network Protocol

## Overview

Gaumo uses WebSocket connections for P2P communication. All messages are JSON-encoded.

## Connection Model

- All connections are **outbound** by default
- Nodes connect to seed nodes and discovered peers
- No inbound port forwarding required
- Optionally, nodes can accept inbound connections on a configurable port

## Message Format

```json
{
  "type": "MESSAGE_TYPE",
  "version": 1,
  "data": { ... }
}
```

## Message Types

### HANDSHAKE
Sent on connection to exchange height/version.
```json
{ "type": "HANDSHAKE", "data": { "height": 100, "version": 1 } }
```

### HANDSHAKE_ACK
Response to handshake.

### GET_PEERS / PEERS
Request and respond with peer list.
```json
{ "type": "PEERS", "data": { "peers": [{"host": "1.2.3.4", "port": 8765}] } }
```

### GET_BLOCKS / BLOCKS
Request and respond with blocks from a given height.
```json
{ "type": "GET_BLOCKS", "data": { "from_height": 50 } }
{ "type": "BLOCKS", "data": { "blocks": [...] } }
```

### NEW_BLOCK
Announce a newly mined block.
```json
{ "type": "NEW_BLOCK", "data": { <block dict> } }
```

### NEW_TRANSACTION
Announce a new transaction.
```json
{ "type": "NEW_TRANSACTION", "data": { <transaction dict> } }
```

### PING / PONG
Keepalive messages sent every 30 seconds.

## Peer Discovery

1. Node connects to hardcoded seed nodes
2. Sends GET_PEERS to each connected peer
3. Connects to returned peers (up to MAX_OUTBOUND=8)
4. Repeats every 60 seconds

## Chain Synchronization

1. On connection, exchange heights via HANDSHAKE
2. If peer is ahead, send GET_BLOCKS from current_height+1
3. Receive and validate BLOCKS response
4. Request more if still behind
5. Sync loop runs every 30 seconds as fallback
