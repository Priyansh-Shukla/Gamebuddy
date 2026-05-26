# GameBuddy demo

A visual walkthrough of GameBuddy v1, built around Sekiro: Shadows Die Twice.

**Live (rendered):** https://priyansh-shukla.github.io/Gamebuddy/demo/ — opens like a website. SVG maps, HTML journals, and links all work in the browser. Best entry point.

**Local:** clone the repo and open [`index.html`](index.html) in any browser.

## What's in here

| File / dir | What it is |
|---|---|
| [`index.html`](index.html) | The walkthrough. Start here. |
| [`maps/`](maps/) | Eight progression-DAG SVGs: masked (player view) vs reveal (authoring view) across bare / early / mid / late checkpoints. Rendered via Graphviz. |
| [`journals/`](journals/) | Four Ship-Log-style HTML journals showing observed and frontier nodes as card grids. Late checkpoint included in both masked and reveal views. |
| [`envelopes/`](envelopes/) | Three `--dry-run` prompt bodies — the literal input that synthesis would send to the model. The structural spoiler proof: endgame entities never appear in early/mid envelopes. |
| [`states/`](states/) | The three checkpoint player-state JSONs. Inputs to every other artifact above. |
| [`resume-late-masked.txt`](resume-late-masked.txt) / [`resume-late-reveal.txt`](resume-late-reveal.txt) | Subagent-mocked synthesis briefing for the late state, formatted through gamebuddy's own `_format_summary`. |
| [`synthesis-late-mock.json`](synthesis-late-mock.json) | The raw JSON the mock subagent returned. Conforms to `SUMMARY_SCHEMA` from `gamebuddy/synthesis.py`. |
| [`sl2_discovery.md`](sl2_discovery.md) | Field note: how the Sekiro save-format assumption (AES like every other FromSoft game) turned out to be wrong, and what changed. |
| `_build_states.py`, `_render_artifacts.py`, `_format_mock.py` | Reproducer scripts. Regenerate everything if the DAG or entity files change. |

## What it demonstrates

- **Structural spoiler filter.** Same code, same data, two `reveal` boolean values — the masked map view omits gated nodes entirely; the reveal view shows all 49. Compare any `*-masked.svg` to its `*-reveal.svg` pair.
- **Envelope growth.** As the player progresses, the prompt envelope grows from 8 → 15 → 30 entities. The gated region shrinks. The model literally receives more game-context as you play; nothing is held back by prompt instructions.
- **End-to-end one-shot synthesis.** The mock briefing in `resume-late-*.txt` is what `gamebuddy resume --reveal` would print after a real Anthropic API call — produced by handing the envelope to a fresh Opus subagent with all tools disabled.

## Regenerating

The artifacts are committed because they're the demo. To rebuild them after changing the DAG or entity MDs:

```bash
# In the repo root:
py -3 demo/_build_states.py        # rebuild the three state JSONs
py -3 demo/_render_artifacts.py    # rebuild maps + journals + envelopes
```

Requires Graphviz (`dot` on PATH) for SVG/PNG output.
