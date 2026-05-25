"""BND4 container parsing.

BND4 is FromSoftware's general-purpose file-container format (used since
Dark Souls 2). An .sl2 file is one BND4 with eleven entries: ten USERDATA
slots plus a settings entry. Each entry's data is independently encrypted
(see crypto.py).

Layout:

    Header (64 bytes, "BND4")
    For each entry:
        Entry header (32 bytes) at the front of the file
    For each entry:
        Entry data (`EntrySize` bytes) at `EntryDataOffset`
        Entry name (null-terminated, possibly UTF-16) at `EntryNameOffset`

Field layouts are derived from SL2Bonfire's BonfireCore source
(github.com/mi5hmash/SL2Bonfire). Several "magic" bytes in the header are
not fully understood by the community; we read them for fidelity but
don't validate them beyond the file signature.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

BND4_SIGNATURE = b"BND4"
HEADER_SIZE = 0x40
ENTRY_HEADER_SIZE = 0x20
ENTRY_HEADER_PADDING = 0xFFFFFFFF_00000050  # expected `PaddingHeader` value


class Bnd4ParseError(ValueError):
    pass


@dataclass
class Bnd4Header:
    file_count: int
    data_offset: int
    is_unicode: bool


@dataclass
class Bnd4EntryHeader:
    size: int
    data_offset: int
    name_offset: int
    footer_length: int


@dataclass
class Bnd4Entry:
    name: str
    data: bytes            # raw entry bytes including MD5 + IV + ciphertext + footer
    header: Bnd4EntryHeader


@dataclass
class Bnd4File:
    header: Bnd4Header
    entries: list[Bnd4Entry]


def parse(data: bytes) -> Bnd4File:
    if len(data) < HEADER_SIZE:
        raise Bnd4ParseError(f"file too short for BND4 header: {len(data)} < {HEADER_SIZE}")
    if data[:4] != BND4_SIGNATURE:
        raise Bnd4ParseError(f"missing BND4 signature, got {data[:4]!r}")

    file_count = struct.unpack_from("<I", data, 0x0C)[0]
    data_offset = struct.unpack_from("<I", data, 0x28)[0]
    is_unicode = bool(data[0x30])
    header = Bnd4Header(
        file_count=file_count,
        data_offset=data_offset,
        is_unicode=is_unicode,
    )

    entry_header_block_end = HEADER_SIZE + ENTRY_HEADER_SIZE * file_count
    if entry_header_block_end > len(data):
        raise Bnd4ParseError(
            f"entry header block ({entry_header_block_end} bytes) exceeds file length "
            f"({len(data)})"
        )

    entries: list[Bnd4Entry] = []
    for i in range(file_count):
        off = HEADER_SIZE + i * ENTRY_HEADER_SIZE
        padding = struct.unpack_from("<Q", data, off)[0]
        if padding != ENTRY_HEADER_PADDING:
            raise Bnd4ParseError(
                f"entry {i}: bad padding header 0x{padding:016X} "
                f"(expected 0x{ENTRY_HEADER_PADDING:016X})"
            )
        size, _m1, data_off, name_off, footer_len, _m2 = struct.unpack_from(
            "<IIIIII", data, off + 8
        )
        eh = Bnd4EntryHeader(
            size=size,
            data_offset=data_off,
            name_offset=name_off,
            footer_length=footer_len,
        )
        if data_off + size > len(data):
            raise Bnd4ParseError(
                f"entry {i}: data range [{data_off}, {data_off + size}) exceeds file"
            )
        entry_bytes = data[data_off : data_off + size]
        name = _read_name(data, name_off, is_unicode)
        entries.append(Bnd4Entry(name=name, data=entry_bytes, header=eh))
    return Bnd4File(header=header, entries=entries)


def _read_name(data: bytes, offset: int, is_unicode: bool) -> str:
    if offset == 0:
        return ""
    if is_unicode:
        end = data.find(b"\x00\x00", offset)
        # align to even boundary so the null is the actual UTF-16 terminator
        while end != -1 and (end - offset) % 2 != 0:
            end = data.find(b"\x00\x00", end + 1)
        if end == -1:
            end = len(data)
        return data[offset:end].decode("utf-16-le", errors="replace")
    end = data.find(b"\x00", offset)
    if end == -1:
        end = len(data)
    return data[offset:end].decode("shift_jis", errors="replace")
