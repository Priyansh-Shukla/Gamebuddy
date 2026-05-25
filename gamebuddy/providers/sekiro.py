r"""Sekiro save file provider.

INCOMPLETE: pending real-file verification.

Two things must be filled in by inspecting a real .sl2 file before this
provider can emit observations:

1. **The AES-128-CBC key.** Sekiro uses a different key than Dark Souls 3
   (`FD464D695E69A39A10E319A7ACE8B7FA`) and Dark Souls Remastered
   (`0123456789ABCDEFFEDCBA9876543210`). The community save editors (e.g.
   SL2Bonfire) have it but ship it inside an encrypted profile blob, not
   plaintext source. Easiest paths to recovery:
     - Run a known good save editor under a debugger and read the key
       constant out of memory as it decrypts an entry.
     - Use the `inspect()` method below on a real save to confirm the
       BND4 layer works, then brute-force the AES setup against a known
       block of plaintext (e.g. the Steam ID at slot-offset 0x34164).
   Once known, set it via the `GAMEBUDDY_SEKIRO_KEY` env var as a 32-char
   hex string, or pass `key=` to the constructor.

2. **Field offsets within the decrypted slot payload.** The CLAUDE.md
   target fields are: memories, prayer beads, gourd seeds, skills,
   sculptor's idols, sen. Each is a value at a fixed offset within the
   1 MB decrypted slot. These are not in public documentation — find them
   by diffing two save files (e.g. before/after picking up a prayer
   bead). Fill in `_SLOT_FIELDS` below once known.

The `inspect()` method works *without* a key — it parses the BND4
container only. Use it to confirm the save file is well-formed.

Default save path (Windows): %APPDATA%\Sekiro\<SteamID>\S0000.sl2
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from gamebuddy.providers import Provider
from gamebuddy.saves import bnd4, crypto
from gamebuddy.schemas import Observation


def _load_key_from_env() -> bytes | None:
    raw = os.environ.get("GAMEBUDDY_SEKIRO_KEY")
    if raw is None:
        return None
    raw = raw.strip().replace(" ", "")
    try:
        key = bytes.fromhex(raw)
    except ValueError as exc:
        raise ValueError(
            "GAMEBUDDY_SEKIRO_KEY must be a 32-character hex string"
        ) from exc
    if len(key) != 16:
        raise ValueError(
            f"GAMEBUDDY_SEKIRO_KEY must decode to 16 bytes, got {len(key)}"
        )
    return key


# Fill in once known and verified against a real save.
# Format: dict of {field_name: (slot_offset_in_bytes, struct_format)}
_SLOT_FIELDS: dict[str, tuple[int, str]] = {
    # "sen":               (0x00000000, "<I"),
    # "prayer_beads":      (0x00000000, "B"),
    # "gourd_seeds":       (0x00000000, "B"),
    # ... pending real-file inspection
}


@dataclass
class SaveInspection:
    """Structural info about a .sl2 file (no decryption needed)."""
    entry_count: int
    entries: list[bnd4.Bnd4Entry]


class SekiroSaveProvider(Provider):
    """Reads a Sekiro .sl2 and emits observations.

    Currently a stub: `collect()` raises until the key and field offsets
    are filled in. `inspect()` works today and is useful to confirm a save
    file is well-formed.
    """

    def __init__(self, save_path: Path, *, key: bytes | None = None) -> None:
        self._path = save_path
        self._key = key if key is not None else _load_key_from_env()

    def inspect(self) -> SaveInspection:
        data = self._path.read_bytes()
        bnd = bnd4.parse(data)
        return SaveInspection(entry_count=len(bnd.entries), entries=bnd.entries)

    def collect(self) -> list[Observation]:
        if self._key is None:
            raise NotImplementedError(
                "Sekiro AES key not set. Set GAMEBUDDY_SEKIRO_KEY or pass key="
                " to SekiroSaveProvider. See gamebuddy/providers/sekiro.py."
            )
        if not _SLOT_FIELDS:
            raise NotImplementedError(
                "Sekiro field offsets not yet known. See _SLOT_FIELDS in "
                "gamebuddy/providers/sekiro.py — fill in by diffing a real "
                "save before/after game state changes."
            )
        # Skeleton of the intended flow — completed when _SLOT_FIELDS is filled:
        #   data = self._path.read_bytes()
        #   bnd = bnd4.parse(data)
        #   for i, entry in enumerate(bnd.entries[:10]):  # 10 player slots
        #       plaintext = crypto.unwrap(
        #           entry.data, key=self._key,
        #           footer_length=entry.header.footer_length,
        #       )
        #       # extract fields per _SLOT_FIELDS, emit Observations
        raise NotImplementedError("unreachable until _SLOT_FIELDS is populated")
