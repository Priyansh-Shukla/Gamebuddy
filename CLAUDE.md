# CLAUDE.md — Game Buddy

> Context file for Claude Code. Read this first. Keep it updated as the project evolves.

## What this project is

A personal "game buddy" that tracks singleplayer game progress across multiple
titles and helps me resume after long breaks — telling me where I left off and
planning a **spoiler-free** path for the next session.

The core problem: I play several singleplayer games at once, take work/life breaks,
and forget where I was. Manual logging fails because I forget to log. So the system
pulls progress signals automatically where it can, and lets me annotate where it can't.

## Architecture (the important part)

A tiered **signal hierarchy**. Each game uses the best available signal:

1. **SaveFileProvider** (best) — parses a game's save files into normalized
   observations. One parser per supported game. Deterministic, no guessing.
2. **ScreenshotProvider** (universal fallback) — captures screen on hotkey (and
   optionally on interval), runs OCR / vision extraction. Anchored on text-heavy
   screens (quest log, map, journal) where signal is highest.
3. **ManualProvider** (always available) — I just type what I did.

All providers emit a normalized **Observation** (see src/providers/base.py).
The **synthesis layer** (src/synthesis/) takes new observations + existing game
state, updates the state, and produces the spoiler-safe summary + next-session plan.
The **store** (src/store/) persists per-game state as JSON under data/games/.

```
collector (providers) --> Observation[] --> synthesis (Anthropic API) --> GameState --> store
                                                       |
                                                       v
                                          spoiler-safe summary + next plan
```

## The spoiler rule (non-negotiable design constraint)

The synthesis layer MUST NEVER surface information beyond my current progress point.
- "What's next" guidance is phrased as gentle direction ("there's an objective marker
  northeast of your last save"), never plot reveals.
- Each GameState carries a `spoiler_boundary` describing how far I've explicitly chosen
  to know. Synthesis never reads or reasons past it.
- Save files are GOOD for spoiler-safety: they tell us exactly how far I've progressed,
  so the boundary is precise.

## Conventions

- Python 3.11+. Type hints everywhere. `dataclasses` for schemas.
- Providers are pluggable: subclass `Provider`, implement `collect() -> list[Observation]`.
- Adding a new game = add a save parser under src/providers/saves/<game>.py OR rely on
  screenshot/manual. Never hardcode game logic into the synthesis layer.
- Secrets (ANTHROPIC_API_KEY) come from env, never committed.
- State files are human-readable JSON so I can hand-edit them.

## Current status

- [x] Project scaffold + schemas
- [x] ManualProvider
- [x] Store (JSON per game)
- [x] Subnautica save provider — STUB (format parsing not yet implemented)
- [ ] Synthesis layer wired to Anthropic API
- [ ] ScreenshotProvider (capture + vision extraction)
- [ ] Subnautica save parser — real implementation
- [ ] CLI entrypoint

## Commands

```bash
# install deps
pip install -r requirements.txt

# run tests
python -m pytest tests/ -v

# log a manual session (once CLI is built)
python -m src.cli log subnautica "Repaired the Aurora, building a Seamoth next"

# ask where I left off
python -m src.cli resume subnautica
```

## First games to support

Subnautica (active — best first target: singleplayer, parseable Unity saves),
then Cyberpunk 2077 (community save tooling exists), then broaden via screenshots.
Don't Starve Together is co-op/server-side — lower priority, fuzzier "progress".

## Notes for the agent

- When implementing the Subnautica save parser, DON'T guess the binary format from
  memory — inspect a real save file and/or check community tooling/docs first.
- Keep the synthesis prompt's spoiler constraint explicit and tested.
- This is a personal project on a personal machine/account — not GS infrastructure.
