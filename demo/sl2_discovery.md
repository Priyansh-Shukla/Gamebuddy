# The Sekiro `.sl2` Discovery

A short field note from building the save-file provider for v1.

## The assumption

Every FromSoftware Souls-family game I'd touched stored saves the same way:
a BND4 archive of "entries," each entry wrapped as

```
[16-byte MD5 of plaintext] [16-byte IV] [AES-CBC ciphertext]
```

DS2, DS3, Dark Souls Remastered, Elden Ring — all share that layout. The keys
are different per game (DS3's was extracted by the modding community years
ago via Cheat Engine; the same playbook had been used for Elden Ring). So
the plan for Sekiro was: find the key, drop it into `crypto.py`, decrypt,
parse.

I'd built the framework around that. `gamebuddy/saves/crypto.py` wraps the
AES-CBC dance. A `SekiroSaveProvider` skeleton held a `key` constructor
argument and a `GAMEBUDDY_SEKIRO_KEY` env var. The work item on my todo list
was literally "extract Sekiro AES key via debugger."

## The discovery

Before going down the debugger rabbit hole, I opened a real `.sl2` from my
own Sekiro save in a hex editor, looking for the IV pattern I knew from DS3.

It wasn't there. The bytes following each 16-byte prefix looked too
*orderly* to be ciphertext — long runs of `00`, recognizable string-ish
ASCII fragments, no high-entropy noise.

Three checks settled it:

1. **MD5 round-trip.** `md5(entry[16:])` produced exactly `entry[:16]` on
   every USERDATA entry of the file. If the body were ciphertext, the MD5
   would have been computed over the plaintext, not the ciphertext — so the
   match would only happen if the body *is* the plaintext.

2. **Entropy.** I measured Shannon entropy of an entry body: roughly
   **0.3 bits per byte**. Random ciphertext is ~8 bits/byte. AES-CBC output
   on real saves is indistinguishable from random.

3. **Find the Steam ID.** My Steam ID is `76561198864564167` — a known
   constant I could grep for. It sat in plaintext at body offset `0x33ED4`
   of every character slot. In an encrypted save it would be impossible to
   find without decrypting.

Sekiro `.sl2` slots are **not encrypted**. Each USERDATA entry is just
`[MD5(16)][plaintext body]`. The MD5 is a tamper check, not part of any
encryption scheme.

## Why I didn't already know this

No public source documents this layout. The two community references I
checked both *imply* Sekiro is encrypted:

- **SoulsFormatsNEXT** (the canonical .NET library for FromSoft save
  formats) ships `SL2Decryptor.cs` with branches for `DS2`, `DS3`, `BB`,
  `DSR`, `ER` — but no `SEKIRO` branch. I had read that as "not yet
  implemented." It actually means "doesn't need one."
- **SL2Bonfire** (a save editor) documents using Cheat Engine to extract
  AES keys per game. There's no Sekiro entry in their key list, which
  again I'd read as "still to do."

The community had quietly known that Sekiro saves are plaintext but nobody
had written it down in a place I found. The library shape made the opposite
look more likely.

## What changed

Commit [`42ee58a`](https://github.com/Briggasonic/Gamebuddy/commit/42ee58a):

- Added `gamebuddy/saves/sekiro_slot.py` with `wrap(body)` / `unwrap(entry)`.
  Forty-nine lines including the docstring. Hashes a buffer; that's it.
- Deleted the key plumbing from `providers/sekiro.py` — the
  `GAMEBUDDY_SEKIRO_KEY` env var, the `key=` constructor arg, the
  `_load_key_from_env` helper. Three pieces of dead API surface.
- Kept `gamebuddy/saves/crypto.py` (AES-CBC) for DS3 / Elden Ring later.
- Committed my real `.sl2` as `tests/fixtures/sekiro_S0000.sl2` to pin the
  layout in real-save tests.

The v1 finish line moved closer by one whole human-loop task. The remaining
step for the save provider is offset discovery — which bytes in the 1 MiB
slot body are sen, prayer beads, etc. — which is a save-diff exercise
(snapshot, change one thing, snapshot, diff), not a cryptographic one.

## The lesson

I almost spent two hours on Cheat Engine for a key that doesn't exist,
because the surrounding tooling was *shaped like* there was a key. The
opening move on any binary format should be a five-minute look at the
actual bytes — entropy, structure, recognizable strings, length patterns —
*before* committing to a parsing plan informed by sibling-game lore.
