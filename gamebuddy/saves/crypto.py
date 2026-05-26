"""AES-128-CBC entry wrap/unwrap for FromSoftware .sl2 USERDATA entries.

A wrapped entry on disk has this layout:

    [16-byte MD5 checksum]
    [16-byte AES IV]
    [ciphertext (multiple of 16 bytes)]
    [optional footer padding of `footer_length` bytes]

The MD5 covers the body (IV + ciphertext), not the footer. The ciphertext
decrypts to a plaintext laid out as:

    [4-byte little-endian length]
    [payload (`length` bytes)]
    [PKCS7 padding (1..16 bytes of value N where N is padding length)]

The AES key is a per-game 16-byte secret. Pass it in; this module doesn't
know which game it is. This path is for DS2/DS3/DSR/Elden Ring — Sekiro
turned out to skip AES entirely and uses `sekiro_slot.py` instead.

References:
  SL2Bonfire/BonfireCore — Bnd4Entry.cs (encryption + signing flow)
  Souls Modding Wiki — SL2 file format
"""
from __future__ import annotations

import hashlib
import os
import struct

from Crypto.Cipher import AES

AES_BLOCK = 16
MD5_LEN = 16
IV_LEN = 16


class CryptoError(ValueError):
    pass


def unwrap(entry_data: bytes, key: bytes, footer_length: int = 0) -> bytes:
    """Decode a wrapped entry. Returns the inner payload (no length prefix, no padding)."""
    if len(key) != 16:
        raise CryptoError(f"key must be 16 bytes, got {len(key)}")
    minimum = MD5_LEN + IV_LEN + AES_BLOCK + footer_length
    if len(entry_data) < minimum:
        raise CryptoError(f"entry too short: {len(entry_data)} < {minimum}")

    checksum = entry_data[:MD5_LEN]
    body = entry_data[MD5_LEN : len(entry_data) - footer_length]
    if hashlib.md5(body).digest() != checksum:
        raise CryptoError("MD5 checksum mismatch")

    iv = body[:IV_LEN]
    ciphertext = body[IV_LEN:]
    if len(ciphertext) == 0 or len(ciphertext) % AES_BLOCK != 0:
        raise CryptoError(
            f"ciphertext length {len(ciphertext)} is not a positive multiple of {AES_BLOCK}"
        )

    plaintext = AES.new(key, AES.MODE_CBC, iv).decrypt(ciphertext)

    # Strip PKCS7 padding
    pad = plaintext[-1]
    if pad < 1 or pad > AES_BLOCK or plaintext[-pad:] != bytes([pad]) * pad:
        raise CryptoError("invalid PKCS7 padding")
    unpadded = plaintext[:-pad]

    if len(unpadded) < 4:
        raise CryptoError("plaintext shorter than 4-byte length prefix")
    (length,) = struct.unpack("<I", unpadded[:4])
    if length > len(unpadded) - 4:
        raise CryptoError(
            f"length prefix {length} exceeds available bytes {len(unpadded) - 4}"
        )
    return unpadded[4 : 4 + length]


def wrap(
    payload: bytes,
    key: bytes,
    *,
    iv: bytes | None = None,
    footer_length: int = 0,
) -> bytes:
    """Inverse of unwrap. Used in tests; production saves are written by the game."""
    if len(key) != 16:
        raise CryptoError(f"key must be 16 bytes, got {len(key)}")
    if iv is None:
        iv = os.urandom(IV_LEN)
    elif len(iv) != IV_LEN:
        raise CryptoError(f"iv must be {IV_LEN} bytes, got {len(iv)}")

    inner = struct.pack("<I", len(payload)) + payload
    pad = AES_BLOCK - (len(inner) % AES_BLOCK)
    inner += bytes([pad]) * pad

    ciphertext = AES.new(key, AES.MODE_CBC, iv).encrypt(inner)
    body = iv + ciphertext
    checksum = hashlib.md5(body).digest()
    footer = b"\x00" * footer_length
    return checksum + body + footer
