r"""Sekiro save file provider.

INCOMPLETE: pending field-offset discovery.

Sekiro stores save slots as plaintext bodies with a 16-byte MD5 prefix
(see `gamebuddy/saves/sekiro_slot.py`). There is no AES key to recover —
unlike DS2/DS3/DSR/Elden Ring, Sekiro slot data is not encrypted.

What's left before `collect()` works: the byte offsets within the 1 MiB
slot body for the fields we care about (memories, prayer beads, gourd
seeds, skills, sculptor's idols, sen). These are not in public
documentation. Discover them by diffing two real saves before/after a
single state change (e.g. pick up a prayer bead → save → diff). Fill in
`_SLOT_FIELDS` below once known.

The `inspect()` method works today and confirms the BND4 + MD5 framing.

Default save path (Windows): %APPDATA%\Sekiro\<SteamID>\S0000.sl2
A Sekiro `.sl2` contains 12 entries: USER_DATA000..009 are the ten
character slots (1 MiB each), USER_DATA010 is the profile/global
progress, USER_DATA011 is settings.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gamebuddy.providers import Provider
from gamebuddy.saves import bnd4, sekiro_slot
from gamebuddy.schemas import Observation

PLAYER_SLOT_COUNT = 10


# Fill in once discovered by save-diffing.
# Format: dict of {field_name: (body_offset_in_bytes, struct_format)}
_SLOT_FIELDS: dict[str, tuple[int, str]] = {
    # "sen":            (0x00000000, "<I"),
    # "prayer_beads":   (0x00000000, "B"),
    # "gourd_seeds":    (0x00000000, "B"),
    # ... pending real-file diffing
}


@dataclass
class SaveInspection:
    """Structural info about a .sl2 file (no decryption needed — Sekiro isn't encrypted)."""
    entry_count: int
    entries: list[bnd4.Bnd4Entry]


class SekiroSaveProvider(Provider):
    """Reads a Sekiro .sl2 and emits observations.

    Currently a stub: `collect()` raises until `_SLOT_FIELDS` is filled
    in. `inspect()` works today.
    """

    def __init__(self, save_path: Path) -> None:
        self._path = save_path

    def inspect(self) -> SaveInspection:
        data = self._path.read_bytes()
        bnd = bnd4.parse(data)
        return SaveInspection(entry_count=len(bnd.entries), entries=bnd.entries)

    def collect(self) -> list[Observation]:
        if not _SLOT_FIELDS:
            raise NotImplementedError(
                "Sekiro field offsets not yet known. See _SLOT_FIELDS in "
                "gamebuddy/providers/sekiro.py — fill in by diffing a real "
                "save before/after game state changes."
            )
        # Skeleton of the intended flow — completed when _SLOT_FIELDS is filled:
        #   data = self._path.read_bytes()
        #   bnd = bnd4.parse(data)
        #   for i, entry in enumerate(bnd.entries[:PLAYER_SLOT_COUNT]):
        #       body = sekiro_slot.unwrap(entry.data)
        #       # extract fields per _SLOT_FIELDS, emit Observations
        raise NotImplementedError("unreachable until _SLOT_FIELDS is populated")
