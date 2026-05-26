"""Sekiro slot-entry framing.

Verified by inspection of a real Sekiro `.sl2` file: USERDATA entries
are NOT AES-encrypted (unlike DS2/DS3/DSR/Elden Ring). Each entry is
laid out as:

    [16-byte MD5 of the body]
    [body — plaintext slot data, 1 MiB for character slots]

This was surprising; the framing was discovered empirically because no
public source documents Sekiro's slot crypto. The evidence:
  - Recomputed MD5(body) matches the stored 16-byte prefix on every entry.
  - Body entropy is ~0.3 bits/byte (random ciphertext is ~8); long zero
    runs dominate.
  - The player's Steam ID is sitting in plaintext at a fixed body offset.

So Sekiro saves need no key — just MD5 verification on read, and MD5
recomputation if we ever rewrite. Encrypted Souls games (DS2/DS3/DSR/ER)
use the [MD5][IV][AES-CBC ciphertext] layout in `gamebuddy/saves/crypto.py`
instead.
"""
from __future__ import annotations

import hashlib

MD5_LEN = 16


class SlotError(ValueError):
    pass


def unwrap(entry_data: bytes) -> bytes:
    """Verify the MD5 prefix and return the plaintext body.

    Raises SlotError on length issues or checksum mismatch.
    """
    if len(entry_data) < MD5_LEN:
        raise SlotError(f"entry too short for MD5 prefix: {len(entry_data)} < {MD5_LEN}")
    stored = entry_data[:MD5_LEN]
    body = entry_data[MD5_LEN:]
    if hashlib.md5(body).digest() != stored:
        raise SlotError("MD5 checksum mismatch — entry corrupted or layout assumption wrong")
    return body


def wrap(body: bytes) -> bytes:
    """Inverse of unwrap. Prepend MD5(body)."""
    return hashlib.md5(body).digest() + body
