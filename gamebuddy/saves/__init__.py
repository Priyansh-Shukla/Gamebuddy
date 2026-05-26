"""Save-file parsing primitives for FromSoftware .sl2 files.

Three layers:
  bnd4.py         BND4 container format (header + entries + entry data)
  crypto.py       AES-128-CBC + MD5 wrap/unwrap (DS2/DS3/DSR/Elden Ring)
  sekiro_slot.py  MD5-only wrap/unwrap (Sekiro — *not* AES-encrypted)

Sekiro is the odd one out: its `.sl2` entries are stored as plaintext
bodies with an MD5 prefix, verified by inspecting a real save file. The
other Souls games use AES-CBC with a per-game key; that path is in
crypto.py and parametric on the key. Game-specific providers live in
gamebuddy/providers/<game>.py and pick the right unwrap path.
"""
