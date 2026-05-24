# CLAUDE.md — GameBuddy

> Operating manual for Claude Code. Read first. Update as decisions evolve.
> For full design rationale see [DESIGN.md](DESIGN.md).

## What this project is

A personal "game buddy" for resuming singleplayer games after long breaks. Tells
you where you left off and plans a **spoiler-safe** next session. Pulls progress
from save files where possible; falls back to screenshots (later) and manual
notes.

## Architecture (the short version)

**Two knowledge stores, never mixed:**

| Store | Owner | Location | Contents |
|---|---|---|---|
| Game context | Us (in repo) | `games/<title>/` | Wiki-sourced MD files per game |
| Player state | User (local) | `data/games/<title>.json` | Save-derived progress + annotations |

**Signal hierarchy** for player state:
1. `SaveFileProvider` — preferred, deterministic, one parser per game
2. `ScreenshotProvider` — universal fallback (v2+, not v1)
3. `ManualProvider` — always available

All providers emit a normalized `Observation`. Synthesis is a **one-shot
Anthropic API call** — no agentic loops, no tool-use at synthesis time (any
tool that can fetch external data during a resume is a spoiler vector).
Tool-use **is** allowed at **onboarding** (wiki/walkthrough fetches), where
there's no player to spoil.

The synthesis call receives observations + game-context entries filtered to
the player's progression boundary, and returns a structured resume. Default
model: `claude-opus-4-7` (overridable via env).

## The spoiler rule (non-negotiable)

Spoiler safety is enforced **structurally**, not by asking the model nicely:
synthesis only ever receives observations and game-context entries inside the
player's progression boundary. The model cannot leak what it was never given.

**Progression is a DAG** (per `games/<title>/progression.yaml`). Typed nodes
(boss, area, item, story_beat, ending, …), `requires` and `suggests` edges.
Generalizes linear games, open-world, and multi-ending.

`GameState` carries a two-field boundary:
- `observed: set[NodeId]` — what the save (or manual log) proves reached.
- `declared: NodeId | None` — explicit user override; most distant node the
  user is OK knowing about.

**Filter mechanism:** every game-context entity MD has frontmatter declaring
its `gates: [node_id, ...]`. An entity is eligible for the synthesis prompt
iff `gates ⊆ observed`. Plain set-subset check at prompt-build time.

**Spoiler-gated output:** each "what's next" suggestion has a `hint` layer
(safe) and a `spoiler` layer (plot content). Spoilers are hidden by default;
`gamebuddy resume <game> --reveal` opts in for that invocation.

## Conventions

- Python 3.11+. Type hints everywhere. `dataclasses` for schemas.
- Providers are pluggable: subclass `Provider`, implement `collect() -> list[Observation]`.
- Adding a game = add a save parser + game-context MD files. Never hardcode
  game logic into the synthesis layer.
- `ANTHROPIC_API_KEY` from env. Never committed.
- Player state JSON is human-readable so it can be hand-edited.
- CLI-first, on-demand. No daemon, no background process in v1.

## Current status

Pre-scaffold. Only `CLAUDE.md` and `DESIGN.md` exist. Nothing built yet.

**v1 target: Sekiro** (developer's own second playthrough — full spoiler
tolerance, used to validate synthesis quality before blind testing on v2
Subnautica).

v1 scope:
- [ ] Project scaffold + schemas (`Observation`, `Boundary`, `GameState`, with `schema_version`)
- [ ] `ManualProvider`
- [ ] JSON store (per game)
- [ ] Sekiro game-context: `meta.md`, `progression.yaml` (DAG), entity MDs with `gates` frontmatter
- [ ] Sekiro save parser (`.sl2` — inspect real file, use community tooling, don't guess the binary format)
- [ ] Prompt builder + envelope tests
- [ ] Synthesis layer wired to Anthropic API (one-shot, no tools)
- [ ] CLI: `onboard`, `sync`, `resume` (with `--reveal`), `status`, `log`

## Commands (planned — not yet implemented)

```bash
# install
pip install -r requirements.txt

# tests
python -m pytest tests/ -v

# CLI (once built)
gamebuddy onboard sekiro          # fetch wiki, build game context
gamebuddy sync sekiro             # read save, update player state
gamebuddy resume sekiro           # synthesize and print session briefing
gamebuddy status                  # all tracked games, last played
gamebuddy log sekiro "<note>"     # manual annotation
```

## Notes for the agent

- **Design-first**: for substantial new work, discuss the approach before
  writing code. Open design questions still live in DESIGN.md.
- **Don't guess binary save formats.** Inspect a real file, check community
  tooling/docs (e.g. soulsmodding wiki for `.sl2`).
- **Envelope tests are the spoiler defense.** The prompt builder is a pure
  function; given a fixture `GameState` + game-context, assert the built
  envelope contains zero entities whose `gates` are not a subset of
  `observed`. Prompt-level instructions are not the defense.
- **Filtering uses `gates ⊆ observed`.** Don't reach for graph traversal
  during synthesis — the DAG is consulted at authoring time (and for the
  `declared`→ancestors expansion); the per-entity check at prompt time is
  set-subset.
