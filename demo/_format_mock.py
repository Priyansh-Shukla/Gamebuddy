"""Run the subagent's mock JSON through gamebuddy's own _format_summary.

Uses the real code path so the output is byte-identical to what `gamebuddy
resume sekiro` would print after a successful Anthropic API call.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from gamebuddy.cli import _format_summary
from gamebuddy.schemas import Suggestion, Summary

ROOT = Path(__file__).resolve().parent.parent
mock = json.loads((ROOT / "demo" / "synthesis-late-mock.json").read_text(encoding="utf-8"))

summary = Summary(
    where_you_are=mock["where_you_are"],
    how_you_got_here=mock["how_you_got_here"],
    why_youre_doing_this=mock["why_youre_doing_this"],
    explore_next=[Suggestion(hint=s["hint"], spoiler=s["spoiler"]) for s in mock["explore_next"]],
    next_boss=(
        Suggestion(hint=mock["next_boss"]["hint"], spoiler=mock["next_boss"]["spoiler"])
        if mock["next_boss"]
        else None
    ),
    completion=mock["completion"],
    model="subagent-mock (claude-opus, via Agent tool)",
    generated_at=datetime.now(tz=timezone.utc),
    context_hash="mocked",
)

for reveal in (False, True):
    name = "reveal" if reveal else "masked"
    out = ROOT / "demo" / f"resume-late-{name}.txt"
    out.write_text(_format_summary(summary, reveal=reveal), encoding="utf-8")
    print(f"-> {out.relative_to(ROOT)}")
