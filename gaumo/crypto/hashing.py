"""
Canonical JSON encoding and hashing utilities for Gaumo.
All JSON must be serialized with sorted keys and no extra whitespace.
"""
import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> bytes:
    """Serialize obj to canonical JSON bytes (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')


def sha256d(data: bytes) -> bytes:
    """Double SHA-256 hash."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def hash_object(obj: Any) -> str:
    """Canonical JSON hash of an object. Returns hex string."""
    return sha256d(canonical_json(obj)).hex()
