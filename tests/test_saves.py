"""Tests for the .sl2 save-format framework.

These cover the BND4 container, the AES-CBC crypto layer (for DS2/DS3/DSR/
Elden Ring), and Sekiro's plaintext+MD5 slot framing. All synthetic — no
real save file needed. Sekiro field offsets are the one remaining gap;
they need a real save and a controlled state change to diff.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from gamebuddy.providers.sekiro import SekiroSaveProvider
from gamebuddy.saves import bnd4, crypto, sekiro_slot

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


# ---- sekiro_slot: MD5-prefixed plaintext framing ---------------------------


def test_sekiro_slot_wrap_unwrap_round_trip():
    body = b"plaintext slot body, no AES on Sekiro"
    wrapped = sekiro_slot.wrap(body)
    assert len(wrapped) == sekiro_slot.MD5_LEN + len(body)
    assert wrapped[: sekiro_slot.MD5_LEN] == hashlib.md5(body).digest()
    assert sekiro_slot.unwrap(wrapped) == body


def test_sekiro_slot_unwrap_rejects_tampered_body():
    wrapped = bytearray(sekiro_slot.wrap(b"contents"))
    wrapped[-1] ^= 0xFF
    with pytest.raises(sekiro_slot.SlotError, match="MD5"):
        sekiro_slot.unwrap(bytes(wrapped))


def test_sekiro_slot_unwrap_rejects_too_short():
    with pytest.raises(sekiro_slot.SlotError, match="too short"):
        sekiro_slot.unwrap(b"\x00" * 8)


# ---- Sekiro provider stub --------------------------------------------------


def test_sekiro_provider_collect_errors_without_field_offsets(tmp_path):
    fake_save = tmp_path / "S0000.sl2"
    fake_save.write_bytes(b"\x00" * 0x40)  # contents don't matter; collect bails first
    provider = SekiroSaveProvider(fake_save)
    with pytest.raises(NotImplementedError, match="field offsets"):
        provider.collect()


def test_sekiro_provider_inspect_works_on_md5_wrapped_entry(tmp_path):
    """inspect() only parses BND4 — should work on a well-formed file."""
    body = b"opaque slot body"
    wrapped = sekiro_slot.wrap(body)
    blob = _build_bnd4([("USER_DATA000", wrapped, 0)])
    save_path = tmp_path / "S0000.sl2"
    save_path.write_bytes(blob)

    inspection = SekiroSaveProvider(save_path).inspect()
    assert inspection.entry_count == 1
    assert inspection.entries[0].name == "USER_DATA000"
    # Round-trip through sekiro_slot too, to assert end-to-end shape:
    recovered = sekiro_slot.unwrap(inspection.entries[0].data)
    assert recovered == body


# ---- Real-save fixture: lock in the empirical Sekiro layout ----------------
#
# tests/fixtures/sekiro_S0000.sl2 is a real save copied from the developer's
# %APPDATA%\Sekiro\<SteamID>\S0000.sl2. It anchors the discovery that Sekiro
# entries are plaintext bodies with an MD5 prefix.

FIXTURE_SAVE = Path(__file__).parent / "fixtures" / "sekiro_S0000.sl2"
# Body-relative offset where the Steam ID (u64 LE) sits in each occupied slot.
STEAM_ID_BODY_OFFSET = 0x33ED4


def test_real_save_has_expected_bnd4_shape():
    bnd = bnd4.parse(FIXTURE_SAVE.read_bytes())
    assert len(bnd.entries) == 12
    # 10 character slots + 2 trailing entries (profile/global, settings)
    for i in range(10):
        assert bnd.entries[i].name == f"USER_DATA{i:03}"
        assert bnd.entries[i].header.size == 0x100010  # 16 (MD5) + 1 MiB body
    assert bnd.entries[10].name == "USER_DATA010"
    assert bnd.entries[11].name == "USER_DATA011"


def test_real_save_every_entry_md5_verifies():
    """Confirms the empirical claim: every USERDATA entry is [MD5][body] with no AES."""
    bnd = bnd4.parse(FIXTURE_SAVE.read_bytes())
    for entry in bnd.entries:
        body = sekiro_slot.unwrap(entry.data)  # raises if MD5 mismatch
        assert len(body) == len(entry.data) - sekiro_slot.MD5_LEN


def test_real_save_steam_id_in_plaintext_at_known_offset():
    """The Steam ID is sitting in plaintext at body offset 0x33ED4 in occupied slots.

    This is the strongest local proof that slot bodies are not encrypted — a
    known-plaintext sanity check that the layout assumption is correct.
    """
    bnd = bnd4.parse(FIXTURE_SAVE.read_bytes())
    occupied_slots = []
    for i in range(10):
        body = sekiro_slot.unwrap(bnd.entries[i].data)
        sid = int.from_bytes(body[STEAM_ID_BODY_OFFSET : STEAM_ID_BODY_OFFSET + 8], "little")
        if sid != 0:
            occupied_slots.append((i, sid))

    assert len(occupied_slots) >= 1, "expected at least one occupied character slot"
    # All occupied slots should report the same Steam ID (same player).
    sids = {sid for _, sid in occupied_slots}
    assert len(sids) == 1, f"slots disagree on Steam ID: {occupied_slots}"
