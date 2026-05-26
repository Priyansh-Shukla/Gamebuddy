"""Progression-DAG visualization with player-state overlay.

Pure functions only — no I/O. The CLI command in `gamebuddy.cli` is the
adapter that reads the context+state, calls these, and writes the output.

Three node classes:
  - observed  : in the effective boundary; rendered fully.
  - frontier  : not observed, but at least one observed node is a direct
                predecessor (via `requires` or `suggests`). Rendered as a
                masked stub when `reveal=False` — same spoiler discipline as
                the `hint`/`spoiler` split in the resume output.
  - gated     : everything else. Not rendered when `reveal=False`.

Edges are emitted only when both endpoints are rendered.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from gamebuddy.context import GameContext
from gamebuddy.filter import effective_observed
from gamebuddy.schemas import GameState, NodeId

NodeState = Literal["observed", "frontier", "gated"]

_TYPE_SHAPES: dict[str, str] = {
    "boss": "octagon",
    "area": "box",
    "item": "note",
    "skill": "parallelogram",
    "story_beat": "ellipse",
    "ending": "doublecircle",
}
_DEFAULT_SHAPE = "ellipse"

# (border, fill) per state.
_STATE_COLORS: dict[NodeState, tuple[str, str]] = {
    "observed": ("#2e7d32", "#c8e6c9"),
    "frontier": ("#ef6c00", "#ffe0b2"),
    "gated": ("#9e9e9e", "#f5f5f5"),
}


@dataclass(frozen=True)
class NodeCounts:
    observed: int
    frontier: int
    gated: int


def classify_nodes(
    context: GameContext,
    state: GameState | None,
) -> dict[NodeId, NodeState]:
    """Return a state classification for every node in the DAG."""
    if state is None:
        effective: set[NodeId] = set()
    else:
        effective = effective_observed(state.boundary, context.dag)

    result: dict[NodeId, NodeState] = {}
    for n_id in context.dag.nodes:
        if n_id in effective:
            result[n_id] = "observed"
            continue
        reqs = context.dag.requires.get(n_id, set())
        sugs = context.dag.suggests.get(n_id, set())
        if (reqs | sugs) & effective:
            result[n_id] = "frontier"
        else:
            result[n_id] = "gated"
    return result


def count(classes: dict[NodeId, NodeState]) -> NodeCounts:
    obs = sum(1 for s in classes.values() if s == "observed")
    fro = sum(1 for s in classes.values() if s == "frontier")
    gat = sum(1 for s in classes.values() if s == "gated")
    return NodeCounts(observed=obs, frontier=fro, gated=gat)


def to_dot(
    context: GameContext,
    state: GameState | None,
    *,
    reveal: bool = False,
) -> str:
    """Render the progression DAG as a Graphviz DOT graph.

    `reveal=False` (the default) preserves spoiler discipline: gated nodes are
    omitted entirely, and frontier nodes are rendered as masked stubs (type
    only, no node id). `reveal=True` is the authoring view — everything shown.
    """
    classes = classify_nodes(context, state)
    rendered: set[NodeId] = {
        n for n, c in classes.items() if c != "gated" or reveal
    }

    lines: list[str] = []
    lines.append(f'digraph "{context.meta.game_id}" {{')
    lines.append("  rankdir=LR;")
    lines.append('  node [fontname="Helvetica", fontsize=10, style="filled,rounded"];')
    lines.append('  edge [fontname="Helvetica", fontsize=9];')

    for n_id, node in context.dag.nodes.items():
        if n_id not in rendered:
            continue
        cls = classes[n_id]
        shape = _TYPE_SHAPES.get(node.type, _DEFAULT_SHAPE)
        border, fill = _STATE_COLORS[cls]
        if cls == "observed" or reveal:
            label = n_id
        else:
            label = f"? ({node.type})"
        lines.append(
            f'  "{n_id}" ['
            f'label="{label}", shape={shape}, '
            f'color="{border}", fillcolor="{fill}"'
            f"];"
        )

    for tgt, preds in context.dag.requires.items():
        if tgt not in rendered:
            continue
        for src in preds:
            if src not in rendered:
                continue
            lines.append(f'  "{src}" -> "{tgt}" [style=solid];')
    for tgt, preds in context.dag.suggests.items():
        if tgt not in rendered:
            continue
        for src in preds:
            if src not in rendered:
                continue
            lines.append(f'  "{src}" -> "{tgt}" [style=dashed, color="#888"];')

    lines.append("}")
    return "\n".join(lines) + "\n"
