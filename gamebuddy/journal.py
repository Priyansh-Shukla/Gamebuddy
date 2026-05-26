"""HTML journal view — cards per observed/frontier node.

Inspired by the Outer Wilds Ship Log: shows what you've discovered and what
leads (rumors) you have outstanding, organized as a card grid. The map
command (`gamebuddy map`) is the spatial complement.

Pure function. `to_html(context, state, *, reveal=False)` returns a complete
HTML document string and reuses `classify_nodes` from `visualize` so the two
views always agree on which nodes are observed / frontier / gated.

Spoiler discipline matches the map view: gated nodes are omitted, frontier
cards use stable "Rumor #N" handles so their identity stays masked while
cross-references remain stable.
"""
from __future__ import annotations

import html
import re

from gamebuddy.context import GameContext
from gamebuddy.schemas import GameState, NodeId
from gamebuddy.visualize import classify_nodes, count

_CSS = """\
body { font-family: -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif;
       background: #0d1117; color: #c9d1d9; margin: 0; padding: 24px; line-height: 1.5; }
header { margin-bottom: 24px; }
h1 { margin: 0 0 4px; font-size: 22px; }
.stats { color: #8b949e; font-size: 14px; margin: 0; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }
.card { border: 1px solid #30363d; border-radius: 8px; padding: 16px; background: #161b22; }
.card.observed { border-color: #2ea043; }
.card.frontier { border-color: #d29922; }
.card.gated { border-color: #6e7681; opacity: 0.75; }
.badge { display: inline-block; font-size: 10px; padding: 2px 8px; border-radius: 10px;
         background: #21262d; color: #8b949e; text-transform: uppercase; letter-spacing: 0.6px; }
.card.observed .badge { background: #1f3a25; color: #7ee787; }
.card.frontier .badge { background: #4d2f10; color: #f0883e; }
.title { font-size: 16px; font-weight: 600; margin: 8px 0; }
.card.frontier .title { color: #f0883e; font-style: italic; }
.body { font-size: 14px; color: #c9d1d9; }
.body p { margin: 0 0 8px; }
.leads { margin-top: 12px; font-size: 12px; color: #8b949e;
         border-top: 1px solid #21262d; padding-top: 10px; }
.leads ul { margin: 4px 0 0; padding-left: 18px; }
.leads li.frontier { color: #f0883e; }
.leads li.observed { color: #7ee787; }
.empty { color: #8b949e; font-style: italic; }
.notice { color: #8b949e; font-style: italic; padding: 24px;
          border: 1px dashed #30363d; border-radius: 8px; text-align: center; }
"""


def _humanize_id(node_id: NodeId) -> str:
    return node_id.replace("_", " ").title()


def _first_paragraph(body: str) -> str:
    body = body.strip()
    if not body:
        return ""
    para = body.split("\n\n", 1)[0]
    return re.sub(r"\s+", " ", para).strip()


def to_html(
    context: GameContext,
    state: GameState | None,
    *,
    reveal: bool = False,
) -> str:
    classes = classify_nodes(context, state)
    counts = count(classes)
    entities = {e.node_id: e for e in context.entities}

    frontier_sorted = sorted(n for n, c in classes.items() if c == "frontier")
    rumor_handle: dict[NodeId, str] = {
        n: f"Rumor #{i + 1}" for i, n in enumerate(frontier_sorted)
    }

    def display_title(node_id: NodeId) -> str:
        cls = classes[node_id]
        if cls == "observed" or reveal:
            return _humanize_id(node_id)
        if cls == "frontier":
            node_type = context.dag.nodes[node_id].type
            return f"{rumor_handle[node_id]} — {node_type}"
        return _humanize_id(node_id)

    def render_card(node_id: NodeId) -> str:
        cls = classes[node_id]
        node = context.dag.nodes[node_id]
        entity = entities.get(node_id)

        succ_req = sorted(
            t for t, preds in context.dag.requires.items() if node_id in preds
        )
        succ_sug = sorted(
            t for t, preds in context.dag.suggests.items() if node_id in preds
        )

        def lead_item(target: NodeId, soft: bool) -> str | None:
            tcls = classes.get(target, "gated")
            if tcls == "gated" and not reveal:
                return None
            label = display_title(target)
            soft_mark = " <em>(soft)</em>" if soft else ""
            return f'<li class="{tcls}">{html.escape(label)}{soft_mark}</li>'

        lead_items = [
            li for li in (
                [lead_item(t, soft=False) for t in succ_req]
                + [lead_item(t, soft=True) for t in succ_sug]
            )
            if li is not None
        ]
        leads_html = (
            '<div class="leads"><strong>Leads to:</strong>'
            f'<ul>{"".join(lead_items)}</ul></div>'
            if lead_items
            else ""
        )

        if cls == "observed" or reveal:
            body_text = _first_paragraph(entity.body) if entity else ""
            body_html = (
                f"<p>{html.escape(body_text)}</p>"
                if body_text
                else '<p class="empty">No detail authored.</p>'
            )
        else:
            preds_all = (
                context.dag.requires.get(node_id, set())
                | context.dag.suggests.get(node_id, set())
            )
            sources = sorted(
                _humanize_id(p) for p in preds_all if classes.get(p) == "observed"
            )
            body_html = (
                f'<p class="empty">Rumored from: '
                f'{html.escape(", ".join(sources))}.</p>'
                if sources
                else '<p class="empty">Rumored.</p>'
            )

        return (
            f'<div class="card {cls}">'
            f'<span class="badge">{html.escape(node.type)} · {cls}</span>'
            f'<div class="title">{html.escape(display_title(node_id))}</div>'
            f'<div class="body">{body_html}</div>'
            f"{leads_html}"
            "</div>"
        )

    order: list[NodeId] = (
        [n for n in sorted(context.dag.nodes) if classes[n] == "observed"]
        + [n for n in sorted(context.dag.nodes) if classes[n] == "frontier"]
    )
    if reveal:
        order += [n for n in sorted(context.dag.nodes) if classes[n] == "gated"]

    parts: list[str] = []
    parts.append("<!doctype html>")
    parts.append('<html><head><meta charset="utf-8">')
    parts.append(f"<title>{html.escape(context.meta.title)} — Journal</title>")
    parts.append(f"<style>{_CSS}</style>")
    parts.append("</head><body>")
    parts.append("<header>")
    parts.append(f"<h1>{html.escape(context.meta.title)} — Journal</h1>")
    stats_line = (
        f"Observed: {counts.observed} · Frontier: {counts.frontier} · "
        f"Gated: {counts.gated}"
    )
    if reveal:
        stats_line += " · reveal mode"
    parts.append(f'<p class="stats">{stats_line}</p>')
    parts.append("</header>")

    if not order:
        parts.append(
            '<div class="notice">Nothing logged yet. Use '
            "<code>gamebuddy log &lt;game&gt; &lt;node-or-text&gt;</code> "
            "to record your first observation.</div>"
        )
    else:
        parts.append('<div class="grid">')
        for n in order:
            parts.append(render_card(n))
        parts.append("</div>")

    parts.append("</body></html>")
    return "\n".join(parts) + "\n"
