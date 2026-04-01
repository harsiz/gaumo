"""
Key generation, signing, and address derivation for Gaumo.
Uses ECDSA secp256k1 (same as Bitcoin).
Address format: gau1 + base58check(RIPEMD160(SHA256(pubkey)))
"""
import hashlib
import hmac
import os
import struct
from typing import Tuple

from ecdsa import SECP256k1, SigningKey, VerifyingKey
from ecdsa.util import sigencode_der, sigdecode_der

BASE58_ALPHABET = b'123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
ADDRESS_PREFIX = 'gau1'
ADDRESS_VERSION = b'\x26'  # version byte for gau addresses


def generate_keypair() -> Tuple[bytes, bytes]:
    """Generate a new (private_key_bytes, public_key_bytes) pair."""
    sk = SigningKey.generate(curve=SECP256k1)
    vk = sk.get_verifying_key()
    return sk.to_string(), vk.to_string('compressed')


def private_key_to_public_key(private_key_bytes: bytes) -> bytes:
    """Derive compressed public key from raw private key bytes."""
    sk = SigningKey.from_string(private_key_bytes, curve=SECP256k1)
    vk = sk.get_verifying_key()
    return vk.to_string('compressed')


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _ripemd160(data: bytes) -> bytes:
    h = hashlib.new('ripemd160')
    h.update(data)
    return h.digest()


def _hash160(data: bytes) -> bytes:
    return _ripemd160(_sha256(data))


def _base58_encode(data: bytes) -> str:
    """Encode bytes to Base58 string."""
    count = 0
    for byte in data:
        if byte == 0:
            count += 1
        else:
            break
    num = int.from_bytes(data, 'big')
    result = []
    while num > 0:
        num, remainder = divmod(num, 58)
        result.append(BASE58_ALPHABET[remainder:remainder+1])
    result.extend([BASE58_ALPHABET[0:1]] * count)
    return b''.join(reversed(result)).decode('ascii')


def _base58_decode(s: str) -> bytes:
    """Decode Base58 string to bytes."""
    count = 0
    for c in s:
        if c == '1':
            count += 1
        else:
            break
    num = 0
    for char in s.encode('ascii'):
        num = num * 58 + BASE58_ALPHABET.index(char)
    result = num.to_bytes((num.bit_length() + 7) // 8, 'big') if num > 0 else b''
    return b'\x00' * count + result


def _base58check_encode(version: bytes, payload: bytes) -> str:
    data = version + payload
    checksum = _sha256(_sha256(data))[:4]
    return _base58_encode(data + checksum)


def _base58check_decode(s: str) -> Tuple[bytes, bytes]:
    """Returns (version, payload) or raises ValueError on bad checksum."""
    data = _base58_decode(s)
    if len(data) < 5:
        raise ValueError("Too short for base58check")
    version = data[:1]
    payload = data[1:-4]
    checksum = data[-4:]
    expected = _sha256(_sha256(data[:-4]))[:4]
    if not hmac.compare_digest(checksum, expected):
        raise ValueError("Bad checksum")
    return version, payload


def public_key_to_address(public_key_bytes: bytes) -> str:
    """Derive a gau1-prefixed address from a compressed public key."""
    h160 = _hash160(public_key_bytes)
    b58 = _base58check_encode(ADDRESS_VERSION, h160)
    return ADDRESS_PREFIX + b58


def validate_address(address: str) -> bool:
    """Return True if address is a valid Gaumo address."""
    if not address.startswith(ADDRESS_PREFIX):
        return False
    b58_part = address[len(ADDRESS_PREFIX):]
    try:
        version, payload = _base58check_decode(b58_part)
        return version == ADDRESS_VERSION and len(payload) == 20
    except Exception:
        return False


def sign(private_key_bytes: bytes, message: bytes) -> bytes:
    """Sign a message with a private key. Returns DER-encoded signature."""
    sk = SigningKey.from_string(private_key_bytes, curve=SECP256k1)
    msg_hash = _sha256(message)
    return sk.sign_digest(msg_hash, sigencode=sigencode_der)


def verify(public_key_bytes: bytes, message: bytes, signature: bytes) -> bool:
    """Verify a DER-encoded signature against a public key."""
    try:
        vk = VerifyingKey.from_string(public_key_bytes, curve=SECP256k1)
        msg_hash = _sha256(message)
        return vk.verify_digest(signature, msg_hash, sigdecode=sigdecode_der)
    except Exception:
        return False


def private_key_to_wif(private_key_bytes: bytes) -> str:
    """Encode private key in WIF-like format."""
    return _base58check_encode(b'\x80', private_key_bytes + b'\x01')


def wif_to_private_key(wif: str) -> bytes:
    """Decode WIF-encoded private key."""
    version, payload = _base58check_decode(wif)
    if version != b'\x80':
        raise ValueError("Invalid WIF version")
    if payload.endswith(b'\x01'):
        return payload[:-1]
    return payload
