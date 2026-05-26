"""Render maps, journals, and envelopes for the three demo checkpoints.

For each checkpoint (early/mid/late) and each reveal flag (masked/reveal),
emit:
  - demo/maps/sekiro-<phase>-<view>.svg   (and a 'gated' authoring SVG at full DAG)
  - demo/journals/sekiro-<phase>-<view>.html (masked only by default + late reveal)
  - demo/envelopes/sekiro-<phase>.txt   (dry-run prompt body)

Pure Python: shells out to `dot` for SVG; otherwise uses gamebuddy modules
directly so the same code paths the CLI uses produce the outputs.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["GAMEBUDDY_GAMES_DIR"] = str(ROOT / "games")

from gamebuddy.context import load_game_context
from gamebuddy.envelope import build_envelope
from gamebuddy.journal import to_html
from gamebuddy.store import load_state
from gamebuddy.synthesis import render_user_prompt
from gamebuddy.visualize import classify_nodes, count, to_dot

# Prepend Graphviz to PATH for this process.
GV_BIN = r"C:\Program Files\Graphviz\bin"
if GV_BIN not in os.environ.get("PATH", ""):
    os.environ["PATH"] = GV_BIN + os.pathsep + os.environ["PATH"]

DOT = shutil.which("dot") or os.path.join(GV_BIN, "dot.exe")
assert Path(DOT).exists(), f"dot not found at {DOT}"

MAPS = ROOT / "demo" / "maps"
JOURNALS = ROOT / "demo" / "journals"
ENVELOPES = ROOT / "demo" / "envelopes"
for d in (MAPS, JOURNALS, ENVELOPES):
    d.mkdir(parents=True, exist_ok=True)

context = load_game_context(ROOT / "games", "sekiro")

PHASES = ["early", "mid", "late"]


def render_svg(dot_source: str, out: Path) -> None:
    subprocess.run(
        [DOT, "-Tsvg", "-o", str(out)],
        input=dot_source,
        text=True,
        check=True,
        capture_output=True,
    )


for phase in PHASES:
    state = load_state(ROOT / "demo" / "states" / f"sekiro-{phase}.json")
    classes = classify_nodes(context, state)
    counts = count(classes)
    print(f"\n[{phase}] observed={counts.observed} frontier={counts.frontier} gated={counts.gated}")

    # Map — masked (player view) and reveal (authoring view)
    for reveal in (False, True):
        view = "reveal" if reveal else "masked"
        svg_out = MAPS / f"sekiro-{phase}-{view}.svg"
        render_svg(to_dot(context, state, reveal=reveal), svg_out)
        print(f"  map  -> {svg_out.relative_to(ROOT)}")

    # Journal — masked at all phases, reveal at late only
    for reveal in (False, *([True] if phase == "late" else [])):
        view = "reveal" if reveal else "masked"
        html_out = JOURNALS / f"sekiro-{phase}-{view}.html"
        html_out.write_text(to_html(context, state, reveal=reveal), encoding="utf-8")
        print(f"  jrnl -> {html_out.relative_to(ROOT)}")

    # Envelope dry-run (the literal prompt body that would be sent)
    envelope = build_envelope(state, context)
    body = render_user_prompt(envelope)
    env_out = ENVELOPES / f"sekiro-{phase}.txt"
    header = (
        f"# Sekiro envelope @ {phase} checkpoint\n"
        f"# observed={counts.observed} frontier={counts.frontier} gated={counts.gated}\n"
        f"# entities in envelope: {len(envelope.entities)}\n"
        f"# observations: {len(envelope.observations)}\n"
        f"# --- prompt body below this line ---\n\n"
    )
    env_out.write_text(header + body, encoding="utf-8")
    print(f"  env  -> {env_out.relative_to(ROOT)}  ({len(envelope.entities)} entities)")

# Also: empty-state map to dramatize "nothing observed yet"
print("\n[bare] no state")
svg_out = MAPS / "sekiro-bare-masked.svg"
render_svg(to_dot(context, None, reveal=False), svg_out)
print(f"  map  -> {svg_out.relative_to(ROOT)}")
svg_out = MAPS / "sekiro-bare-reveal.svg"
render_svg(to_dot(context, None, reveal=True), svg_out)
print(f"  map  -> {svg_out.relative_to(ROOT)}")

print("\nDone.")
