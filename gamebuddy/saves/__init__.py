"""Save-file parsing primitives for FromSoftware .sl2 files.

Two layers:
  bnd4.py    BND4 container format (header + entries + entry data)
  crypto.py  AES-128-CBC entry encryption + MD5 signature wrap/unwrap

The crypto layer takes the AES key as a parameter so it's reusable across
games (DS3, Elden Ring, Sekiro all use the same encryption scheme with
different per-game keys). Game-specific providers live in
gamebuddy/providers/<game>.py and supply their own key + field offsets.
"""
