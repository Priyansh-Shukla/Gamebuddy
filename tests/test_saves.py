"""Tests for the .sl2 save-format framework.

These cover the BND4 + AES-CBC layer with synthetic fixtures — no real
Sekiro save file involved. The Sekiro AES key and field offsets are
documented gaps in gamebuddy/providers/sekiro.py; they need a real save
file to fill in.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from gamebuddy.providers.sekiro import SekiroSaveProvider, _load_key_from_env
from gamebuddy.saves import bnd4, crypto

KEY_A = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
KEY_B = bytes.fromhex("FFEEDDCCBBAA99887766554433221100")
IV_ZERO = b"\x00" * 16


# ---- crypto: wrap/unwrap round-trip ----------------------------------------


def test_wrap_unwrap_round_trip():
    payload = b"hello, sekiro"
    wrapped = crypto.wrap(payload, KEY_A, iv=IV_ZERO)
    assert crypto.unwrap(wrapped, KEY_A) == payload


def test_wrap_uses_random_iv_when_unspecified():
    payload = b"abcdef"
    w1 = crypto.wrap(payload, KEY_A)
    w2 = crypto.wrap(payload, KEY_A)
    assert w1 != w2  # different IVs → different ciphertexts and checksums
    assert crypto.unwrap(w1, KEY_A) == payload
    assert crypto.unwrap(w2, KEY_A) == payload


def test_wrap_unwrap_with_footer():
    payload = b"with a footer"  # 13 bytes; +4 length prefix = 17 → pads to 32
    wrapped = crypto.wrap(payload, KEY_A, iv=IV_ZERO, footer_length=8)
    assert len(wrapped) == 16 + 16 + 32 + 8  # md5 + iv + 2 ciphertext blocks + footer
    assert crypto.unwrap(wrapped, KEY_A, footer_length=8) == payload


def test_unwrap_rejects_wrong_key():
    wrapped = crypto.wrap(b"secret", KEY_A, iv=IV_ZERO)
    # MD5 covers the body (IV + ciphertext), not the key, so MD5 still passes.
    # But the decrypted plaintext won't have a valid PKCS7 trailer or length
    # prefix that fits, so unwrap raises one of those errors.
    with pytest.raises(crypto.CryptoError):
        crypto.unwrap(wrapped, KEY_B)


def test_unwrap_rejects_tampered_ciphertext():
    wrapped = bytearray(crypto.wrap(b"payload", KEY_A, iv=IV_ZERO))
    wrapped[32] ^= 0xFF  # flip a bit in the ciphertext
    with pytest.raises(crypto.CryptoError, match="MD5"):
        crypto.unwrap(bytes(wrapped), KEY_A)


def test_unwrap_rejects_bad_key_length():
    with pytest.raises(crypto.CryptoError, match="16 bytes"):
        crypto.unwrap(b"x" * 64, b"short", footer_length=0)


def test_wrap_pads_aligned_payload_to_full_block():
    """PKCS7 always adds padding, even when already block-aligned."""
    # 12-byte payload + 4-byte length prefix = 16 bytes → exactly aligned.
    # PKCS7 requires a full padding block (16 more bytes of value 0x10).
    payload = b"twelve bytes"
    assert len(payload) + 4 == 16
    wrapped = crypto.wrap(payload, KEY_A, iv=IV_ZERO)
    # md5 (16) + iv (16) + 2 ciphertext blocks (32) = 64
    assert len(wrapped) == 64
    assert crypto.unwrap(wrapped, KEY_A) == payload


# ---- bnd4: build a synthetic file and parse it back ------------------------


def _build_bnd4(entries: list[tuple[str, bytes, int]]) -> bytes:
    """Construct a minimal valid BND4 with the given (name, data, footer_length) entries.

    Layout:
        [0x40]            header
        [0x20 each]       entry headers
        [name bytes]      ASCII null-terminated names
        [entry data]      one after another
    """
    n = len(entries)
    header_block = 0x40 + 0x20 * n

    name_bytes_list = [name.encode("shift_jis") + b"\x00" for name, _, _ in entries]
    names_block = b"".join(name_bytes_list)
    name_offsets: list[int] = []
    cursor = header_block
    for nb in name_bytes_list:
        name_offsets.append(cursor)
        cursor += len(nb)

    data_offsets: list[int] = []
    data_block = b""
    for _, data, _ in entries:
        data_offsets.append(cursor + len(data_block))
        data_block += data

    main_header = bytearray(0x40)
    main_header[0:4] = b"BND4"
    struct.pack_into("<I", main_header, 0x08, 0x00010000)  # Magic2
    struct.pack_into("<I", main_header, 0x0C, n)            # FileCount
    struct.pack_into("<I", main_header, 0x10, 0x40)         # Magic3
    struct.pack_into("<Q", main_header, 0x18, 0x3130303030303030)  # Signature
    struct.pack_into("<I", main_header, 0x20, 0x20)         # EntryHeaderSize
    struct.pack_into("<I", main_header, 0x28, data_offsets[0] if data_offsets else 0)
    main_header[0x30] = 0  # is_unicode = false

    entry_headers = bytearray()
    for i, (_, data, footer_len) in enumerate(entries):
        eh = bytearray(0x20)
        struct.pack_into("<Q", eh, 0, bnd4.ENTRY_HEADER_PADDING)
        struct.pack_into("<I", eh, 0x08, len(data))
        struct.pack_into("<I", eh, 0x10, data_offsets[i])
        struct.pack_into("<I", eh, 0x14, name_offsets[i])
        struct.pack_into("<I", eh, 0x18, footer_len)
        entry_headers += eh

    return bytes(main_header) + bytes(entry_headers) + names_block + data_block


def test_parse_synthetic_bnd4():
    entries_in = [
        ("USER_DATA000", b"first entry body", 0),
        ("USER_DATA001", b"second entry body", 4),
    ]
    blob = _build_bnd4(entries_in)
    parsed = bnd4.parse(blob)

    assert parsed.header.file_count == 2
    assert not parsed.header.is_unicode
    assert len(parsed.entries) == 2
    assert parsed.entries[0].name == "USER_DATA000"
    assert parsed.entries[0].data == b"first entry body"
    assert parsed.entries[0].header.footer_length == 0
    assert parsed.entries[1].name == "USER_DATA001"
    assert parsed.entries[1].data == b"second entry body"
    assert parsed.entries[1].header.footer_length == 4


def test_parse_rejects_bad_signature():
    blob = b"FAKE" + b"\x00" * 0x3C
    with pytest.raises(bnd4.Bnd4ParseError, match="signature"):
        bnd4.parse(blob)


def test_parse_rejects_short_file():
    with pytest.raises(bnd4.Bnd4ParseError, match="too short"):
        bnd4.parse(b"BND4")


def test_parse_rejects_bad_entry_padding():
    blob = bytearray(_build_bnd4([("X", b"data", 0)]))
    # corrupt the entry-header padding marker
    struct.pack_into("<Q", blob, 0x40, 0xDEADBEEFDEADBEEF)
    with pytest.raises(bnd4.Bnd4ParseError, match="padding"):
        bnd4.parse(bytes(blob))


# ---- end-to-end: BND4 + crypto ---------------------------------------------


def test_end_to_end_bnd4_with_encrypted_entry():
    """Synthesise a BND4 containing one encrypted entry; parse + unwrap = round trip."""
    payload = b"fake-slot-data-fields-here"
    wrapped = crypto.wrap(payload, KEY_A, iv=IV_ZERO, footer_length=12)
    blob = _build_bnd4([("USER_DATA000", wrapped, 12)])

    parsed = bnd4.parse(blob)
    entry = parsed.entries[0]
    recovered = crypto.unwrap(entry.data, KEY_A, footer_length=entry.header.footer_length)
    assert recovered == payload


# ---- Sekiro provider stub --------------------------------------------------


def test_sekiro_provider_collect_errors_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GAMEBUDDY_SEKIRO_KEY", raising=False)
    fake_save = tmp_path / "S0000.sl2"
    fake_save.write_bytes(b"\x00" * 0x40)  # contents don't matter; collect bails first
    provider = SekiroSaveProvider(fake_save)
    with pytest.raises(NotImplementedError, match="AES key"):
        provider.collect()


def test_sekiro_provider_inspect_works_without_key(tmp_path):
    """inspect() only parses BND4 — should work on a well-formed file without the key."""
    payload = b"opaque"
    wrapped = crypto.wrap(payload, KEY_A, iv=IV_ZERO)
    blob = _build_bnd4([("USER_DATA000", wrapped, 0)])
    save_path = tmp_path / "S0000.sl2"
    save_path.write_bytes(blob)

    inspection = SekiroSaveProvider(save_path).inspect()
    assert inspection.entry_count == 1
    assert inspection.entries[0].name == "USER_DATA000"


def test_sekiro_key_loaded_from_env(monkeypatch):
    monkeypatch.setenv("GAMEBUDDY_SEKIRO_KEY", "00112233445566778899AABBCCDDEEFF")
    assert _load_key_from_env() == KEY_A


def test_sekiro_key_rejects_invalid_hex(monkeypatch):
    monkeypatch.setenv("GAMEBUDDY_SEKIRO_KEY", "not-hex")
    with pytest.raises(ValueError, match="hex"):
        _load_key_from_env()


def test_sekiro_key_rejects_wrong_length(monkeypatch):
    monkeypatch.setenv("GAMEBUDDY_SEKIRO_KEY", "AABB")
    with pytest.raises(ValueError, match="16 bytes"):
        _load_key_from_env()


def test_sekiro_key_accepts_spaces_and_uppercase(monkeypatch):
    monkeypatch.setenv(
        "GAMEBUDDY_SEKIRO_KEY",
        "00 11 22 33 44 55 66 77 88 99 AA BB CC DD EE FF",
    )
    assert _load_key_from_env() == KEY_A
