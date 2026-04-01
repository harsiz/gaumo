# Gaumo Cryptography

## Key Generation

Gaumo uses ECDSA with the secp256k1 curve (same as Bitcoin).

```python
from gaumo.crypto import generate_keypair
private_key, public_key = generate_keypair()
```

## Address Format

Addresses use the format: `gau1` + Base58Check(RIPEMD160(SHA256(pubkey)))

Example: `gau1GYjEuoWp4VBvQT3gfDW3qVxPNzK1bMNaWKnm7C`

Version byte: `0x26`

## Signing

Transactions are signed using DER-encoded ECDSA signatures over SHA-256(canonical_json(tx_data)).

```python
from gaumo.crypto import sign, verify
sig = sign(private_key_bytes, message_bytes)
valid = verify(public_key_bytes, message_bytes, sig)
```

## Hashing

All block and transaction hashes use double SHA-256 (SHA-256d) of canonical JSON:

```python
from gaumo.crypto import hash_object
h = hash_object({"key": "value"})  # returns hex string
```

Canonical JSON: sorted keys, no whitespace.

## WIF Format

Private keys are stored in WIF format (Base58Check with version 0x80 + compression flag).

```python
from gaumo.crypto import private_key_to_wif, wif_to_private_key
wif = private_key_to_wif(private_key_bytes)
private_key = wif_to_private_key(wif)
```
