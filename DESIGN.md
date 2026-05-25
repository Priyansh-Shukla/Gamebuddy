# GameBuddy — Design Document

> Decisions made during initial design sessions (2026-05-25). Update as decisions evolve.

---

## Problem Statement

Playing multiple singleplayer games with limited time leads to long breaks and
lost context. Manual logging fails because you forget to log. GameBuddy answers
one question well in v1:

- **Where was I?** — Re-immerse the user in a specific game's story, state, and
  next steps without requiring them to remember anything.

A second question — **What should I play today?** — is acknowledged but deferred
past v1. `gamebuddy status` will list games sorted by staleness; ranked
recommendation comes later.

---

## Design Principles

1. **Structural over prompt-level constraints.** Spoiler safety is enforced by
   what data reaches the model, not by asking it nicely.
2. **Save file is the source of truth.** Deterministic, no hallucination,
   precise progress signal.
3. **Game context is ours; player state is theirs.** Clean separation. Game
   context ships with the app; player state lives only on the user's machine.
4. **One game at a time.** Depth over breadth. A well-supported game beats a
   shallow library.
5. **Personal tool first.** Optimize for the developer's own use; distribution
   concerns deferred.

---

## Architecture

### Two Knowledge Stores

| Store | Owner | Location | Contents |
|---|---|---|---|
| **Game context** | Developer (us) | Repo (`games/<title>/`) | Wiki-sourced MD files + progression DAG |
| **Player state** | User | Local (`data/games/<title>.json`) | Save-derived observations + boundary + cached resume |

These never mix. Game context is version-controlled and shipped. Player state
is never persisted off-machine — it is transmitted to Anthropic's API only as
synthesis input, under Anthropic's API terms, and otherwise lives only locally.

### Signal Hierarchy (Providers)

Player state is built from observations. Each game uses the best available
signal:

1. **SaveFileProvider** (preferred) — deterministic parser, one per game.
2. **ScreenshotProvider** (v2+ fallback) — hotkey or interval capture, OCR /
   vision extraction. Not in v1.
3. **ManualProvider** (always available) — user types what happened.

All providers emit a normalized `Observation`. Providers are pluggable:
subclass `Provider`, implement `collect() -> list[Observation]`. Adding a game
means adding a save parser, not touching synthesis.

### Synthesis Layer

- **One-shot Anthropic API call.** Not an agentic loop.
- **Tool-use is scoped:** **data-fetching** tools (web search, web fetch,
  file read, MCP, etc.) are banned at synthesis time — any tool that can
  reach external content during a resume is a spoiler vector. Allowed at
  **authoring time** (onboarding fetches wikis), where there is no player
  to spoil.
- **Structured output via forced `tool_use` is allowed at synthesis** — a
  single tool whose `input_schema` *is* the `Summary` shape, with
  `tool_choice={"type":"tool","name":"return_summary"}`. The tool fetches
  nothing; it's a typed container for the model's response. This honors
  the spoiler-vector intent of the rule while giving us reliable
  structured output without prompt-level JSON parsing fragility.
- Input: filtered game-context entries + player observations, both clipped to
  the spoiler boundary (see Spoiler Model).
- Output: structured resume sections (see Resume Output Format).
- Default model: **Claude Opus 4.7** (`claude-opus-4-7`). Overridable via env
  for cheaper iteration. Cost is acceptable for an on-demand personal tool.
- Prompt caching may help if game context dominates the prompt, but the
  Anthropic prompt cache TTL (5 min, 1 hr extended) won't bridge play sessions
  hours/days apart. Treat as a possible optimization, not load-bearing.

---

## Spoiler Model

### Progression as a Directed Acyclic Graph

Every supported game ships a progression DAG in `games/<title>/progression.yaml`:

- **Nodes** = progression entities. Typed: `boss`, `area`, `idol`/`checkpoint`,
  `item`, `skill`, `story_beat`, `ending`.
- **Edges** = relationships between nodes:
  - `requires` — hard prerequisite (you cannot reach B without A).
  - `suggests` — soft narrative ordering (B is normally encountered after A
    but not gated). Used for "what's next" hints, not for safety filtering.

The DAG generalizes across game shapes:
- Linear games → degenerate chain.
- Open-world → wide parallel DAG with many independent branches.
- Multi-ending → DAG with disjoint terminal branches; observing prerequisites
  of one ending does not unlock another's content.

### Two-Field Boundary

```python
observed: set[NodeId]   # what the save (or manual log) proves reached
declared: NodeId | None # explicit user override — most distant node user is
                        # OK knowing about; everything not reachable backward
                        # from it is hidden
```

Synthesis uses the more conservative of the two:

- If `declared` is `None`, boundary = `observed`.
- If `declared` is set, boundary = `observed ∪ ancestors(declared)` clipped to
  the smaller of the two implied sets.

Manual logs (`gamebuddy log`) can advance `observed` by naming a node ID; free-
text notes don't move the boundary but are passed as additional observation
context.

### Structural Filter (the mechanism)

Each game-context entity file declares its gates in frontmatter:

```yaml
---
node_id: genichiro_fight
type: boss
gates: [ashina_castle_unlocked]
---
# Genichiro Ashina
...content...
```

A file is **eligible** for the synthesis prompt iff `gates ⊆ observed`.
This is a set-subset check at prompt-build time — no graph traversal needed
during the API call. The model literally cannot mention what it never received.

This is the mechanism behind Principle 1. It is the load-bearing part of the
spoiler model.

### Hint / Spoiler Output Split

Suggestions are emitted in two layers:

```
Hint:    "Exploring the western valley could benefit your current build."
Spoiler: "The Mortal Blade is located there, required for the Purification
          ending."
```

The CLI hides spoilers by default and prints a placeholder. `gamebuddy resume
<game> --reveal` shows the spoiler layer for that invocation. No persistence;
the user opts in per-run.

For "blind" runs (Subnautica v2), `--reveal` should also be controllable per-
section (e.g. `--reveal next-boss`), to be specified once we have real usage.

---

## Game Context Layout

```
games/sekiro/
  meta.md              # title, save path/format, parser name, wiki source(s)
  progression.yaml     # the DAG: nodes + edges
  entities/
    bosses/genichiro.md
    bosses/ape.md
    areas/ashina_castle.md
    items/mortal_blade.md
    endings/purification.md
  schema_version: 1    # captured in meta.md; see Versioning
```

- `meta.md` is the only file the synthesis layer always reads.
- `progression.yaml` is consulted by the filterer (to expand `declared` into
  ancestor sets, and to compute the "frontier" for next-step hints).
- Entity files are pulled in selectively, only those whose gates are
  satisfied by `observed ∪ ancestors(declared)`.

### Onboarding Workflow

External tools are explicitly **allowed** here — there is no player to spoil
at authoring time.

```
1. gamebuddy onboard <game>
2. Tool-using LLM fetches relevant wiki / walkthrough pages
   (WebFetch, WebSearch). Source(s) declared in resulting meta.md.
3. LLM drafts: meta.md, progression.yaml (nodes + edges), entity MD files
   with gate frontmatter.
4. Developer reviews, edits, commits.
5. Game is live.
```

Authoring cost is real — Sekiro is tractable (~100 nodes); dialogue-heavy
games (Disco Elysium) would be painful. Drafting is automated; review is not.

**Licensing / redistribution of wiki-derived content is deferred** — not a
v1 concern since the repo is personal. Revisit before any public distribution.

---

## Player State Schema

```python
@dataclass
class Boundary:
    observed: set[NodeId]
    declared: NodeId | None

@dataclass
class Observation:
    timestamp: datetime
    source: Literal["save", "manual", "screenshot"]
    node_id: NodeId | None       # if the observation maps to a DAG node
    payload: dict                # raw provider data (save fields, user text)

@dataclass
class GameState:
    schema_version: int
    game_id: str
    last_synced: datetime
    boundary: Boundary
    observations: list[Observation]
    synthesis_cache: Summary | None
```

### Cache Invalidation

`synthesis_cache` is invalidated when **any** of:
- new observations are added,
- `declared` changes,
- the game-context schema or DAG file changes (tracked via content hash in
  the cache entry).

### Observation Growth

The `observations` list grows unboundedly. v1 ignores this. Future scope:
periodic rollup — old observations whose node IDs are dominated by later
observations get archived; the live list stays bounded.

### Schema Versioning

Both game-context files (`meta.md` frontmatter `schema_version`) and player
state JSON (`schema_version` field) carry an integer version. Migrations land
as scripts under `migrations/`. v1 ships as schema_version=1; we bump when
the shape changes.

---

## Sessions

Sessions are not first-class. `last_synced` is the only timestamp the system
needs. If a game's save parser exposes total playtime, that's surfaced in
`status` output; otherwise `status` shows time since last sync. No explicit
session-start / session-end commands.

---

## CLI Commands (v1)

```bash
gamebuddy onboard <game>            # external-tools allowed; drafts game-context files
gamebuddy sync <game>               # read save file, update player state
gamebuddy resume <game>             # synthesize and print briefing (spoilers hidden)
gamebuddy resume <game> --reveal    # reveal spoiler layer for this invocation
gamebuddy status                    # all games, sorted by staleness
gamebuddy log <game> <node|text>    # manual annotation; advances `observed` if a node ID
```

No daemon, no background process in v1. On-demand only.

**Save-file safety:** `sync` should be run with the game closed, or read a
copy. Mid-write reads are a real risk for games that write saves continuously.
The Sekiro parser will document this; later we may snapshot before parsing.

---

## Resume Output Format

Defined against Sekiro as the canonical example. Narrative-first, not
mechanical.

```
WHERE YOU ARE
[Location] — [last idol / checkpoint]

HOW YOU GOT HERE
[Narrative of 2-3 most recent major progress points]

WHY YOU'RE DOING THIS
[Story / lore reason for current objectives — re-immersion layer]

EXPLORE NEXT
[Area suggestion with story rationale — frontier walk over `suggests` edges]

NEXT BOSS                                            (spoiler-gated)
[Boss name + location + approach hint]

COMPLETION
[Main story: X%] [Optional bosses: X/Y] [Skills: X/Y]
```

`COMPLETION` is itself a spoiler for blind playthroughs (it implies scope).
For Subnautica v2 and other blind runs, this section is omitted or replaced
with a fuzzy signal ("early game", "mid game").

---

## Testing Strategy

The spoiler boundary is the non-negotiable property. It deserves direct tests:

- **Envelope tests** — given a fixture `GameState` with observed = {A, B} and
  a fixture game context, assert the prompt envelope built for synthesis
  contains no entity whose gates aren't a subset of {A, B}. Pure-function,
  no API call.
- **Golden-file resume tests** — record-and-compare against checked-in
  outputs for a small set of fixture states. Drift is intentional review,
  not silent.
- **Parser tests** — fixture save files (anonymized as needed) → expected
  `Observation` lists.

Synthesis quality is tested experientially during Sekiro v1 — the developer's
own playthrough is the validation set.

---

## Development Roadmap

### v1 — Sekiro

**Goal:** prove the full pipeline works for one game end-to-end.

- Sekiro game-context files (wiki-sourced via onboarding flow, reviewed)
- Sekiro save parser (`.sl2` binary — inspect real file, use community
  tooling / soulsmodding wiki; do not guess format)
  - Key fields: memories, prayer beads, gourd seeds, skills, sculptor's idols, sen
- Synthesis layer wired to Anthropic API (one-shot, no tools)
- Structural filterer + envelope tests
- CLI: `onboard`, `sync`, `resume`, `status`, `log`
- Resume output matches the format above

**Test condition:** developer is on second playthrough (new game, not NG+).
Full spoiler tolerance. Used to validate synthesis quality before the blind
v2 test.

### v2 — Subnautica

**Goal:** validate spoiler safety under real conditions (developer is blind).

- Subnautica game-context files
- Subnautica save parser (Unity game — parseable, community tooling exists)
- Spoiler boundary tested against real stakes; `COMPLETION` section omitted
- Resume output without scope-implying metrics

**Test condition:** developer is actively playing blind. Any spoiler leak is
a real failure.

### v3 — Second game type + generalization

After two games are working, assess what's actually game-specific vs.
generalizable. Harden `meta.md` schema, document "how to add a new game".
Candidate: Cyberpunk 2077 (community save tooling exists).

---

## Future Scope (not planned, not forgotten)

- **ScreenshotProvider** — for games without parseable saves. Hotkey or
  interval capture, OCR / vision extraction. Provider slot already exists.
- **Background daemon** — `gamebuddy watch <game>` as an intermediate step
  before a full system-tray daemon.
- **Conversational interface** — chat loop during/after sessions. Requires
  persisting in-conversation discoveries, not just holding them in context.
- **Steam / Epic integration** — pull playtime + last-played for the "what
  should I play today" ranking. Save analysis remains richer for content.
- **Recommendation layer** — answers the deferred Problem #1.
- **Observation rollup** — bound the per-game observation list.
- **Co-op support** — Don't Starve Together class of games. Co-op breaks the
  single-boundary model; requires per-player boundaries on shared state.
- **Community distribution** — open the game-context library for
  contributions. Triggers the deferred licensing/redistribution question.

---

## Explicitly Deferred (requires architectural rethink)

- **Streaming overlays** — fundamentally different latency model.
- **Mobile companion** — needs server + sync; breaks local-first.
- **Competitive / live-service multiplayer** — "progress" not well-defined.

---

## Open Questions

Decisions to make as Sekiro v1 hits reality:

- **Granularity of the Sekiro DAG.** Per-boss is obvious; per-idol may be
  excessive. Bias toward fewer nodes initially.
- **Per-section `--reveal` flags.** Whether `--reveal next-boss` vs a single
  `--reveal` is worth the surface area.
- **Manual node IDs vs free text.** Whether `gamebuddy log sekiro genichiro`
  should require an exact node ID or accept fuzzy matching.
- **Cache hash strategy.** Hashing the relevant subset of game context vs.
  the whole directory.

Concerns raised during development go here; resolutions land in the
appropriate section above.
