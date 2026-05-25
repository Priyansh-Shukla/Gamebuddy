"""One-shot synthesis: envelope -> Summary via the Anthropic API.

Uses forced tool_use as an output schema (see DESIGN.md): a single tool
whose `input_schema` matches the Summary shape, with `tool_choice` pinned
to that tool. The tool fetches nothing — it's a typed container for the
model's response. The "no tools at synthesis time" rule bans data-fetching
tools (spoiler vectors), not output-shaping tools.

The prompt builder and `context_hash` are pure functions so they're tested
without hitting the API. `--dry-run` on the CLI uses them directly.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from gamebuddy.envelope import Envelope
from gamebuddy.schemas import Suggestion, Summary

DEFAULT_MODEL = "claude-opus-4-7"
SUMMARY_TOOL_NAME = "return_summary"

_SUGGESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "hint": {
            "type": "string",
            "description": "Safe to show by default; must not reveal plot or future content.",
        },
        "spoiler": {
            "type": ["string", "null"],
            "description": "Specific plot/lore/details; revealed only under --reveal. Null if no spoiler-level content.",
        },
    },
    "required": ["hint", "spoiler"],
    "additionalProperties": False,
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "where_you_are": {
            "type": "string",
            "description": "Location, last checkpoint/idol, immediate context.",
        },
        "how_you_got_here": {
            "type": "string",
            "description": "Narrative of 2-3 most recent major progress points.",
        },
        "why_youre_doing_this": {
            "type": "string",
            "description": "Story/lore reason for current objectives; the re-immersion layer.",
        },
        "explore_next": {
            "type": "array",
            "items": _SUGGESTION_SCHEMA,
            "description": "Area or activity suggestions with hint/spoiler split.",
        },
        "next_boss": {
            "anyOf": [{"type": "null"}, _SUGGESTION_SCHEMA],
            "description": "Next boss with hint/spoiler split. Null if too early or no boss in scope.",
        },
        "completion": {
            "type": ["string", "null"],
            "description": "Progress signal like 'Main: 25%'. Null for blind playthroughs.",
        },
    },
    "required": [
        "where_you_are",
        "how_you_got_here",
        "why_youre_doing_this",
        "explore_next",
        "next_boss",
        "completion",
    ],
    "additionalProperties": False,
}

SUMMARY_TOOL = {
    "name": SUMMARY_TOOL_NAME,
    "description": "Return the structured re-immersion briefing for the player.",
    "input_schema": SUMMARY_SCHEMA,
    "strict": True,
}

SYSTEM_PROMPT = """You are GameBuddy, a re-immersion briefing assistant for singleplayer game players returning to a game after time away.

Produce a structured briefing using the return_summary tool. Honor the player's progress boundary: reference only the game-context entries provided in the prompt. Do not invent facts, extrapolate beyond observed progress, or reference content not present in the input.

Spoiler discipline:
- `hint` text is shown by default and must not reveal plot, lore, or future content
- `spoiler` text contains the specific reveal; shown only when the player opts in via --reveal
- Set spoiler to null when a suggestion has no plot-level reveal"""


def render_user_prompt(envelope: Envelope) -> str:
    """Build the user-message body for synthesis. Pure function."""
    lines: list[str] = []
    lines.append(f"Game: {envelope.meta.title} ({envelope.meta.game_id})")
    lines.append("")
    if envelope.meta.body.strip():
        lines.append("<game_overview>")
        lines.append(envelope.meta.body.strip())
        lines.append("</game_overview>")
        lines.append("")

    lines.append("<effective_observed>")
    if envelope.effective_observed:
        lines.append(", ".join(sorted(envelope.effective_observed)))
    else:
        lines.append("(none — player has not reached any tracked nodes)")
    lines.append("</effective_observed>")
    lines.append("")

    lines.append("<game_context>")
    lines.append("The following entries are the entire scope of game content available to you.")
    lines.append("Do not introduce facts not present in these entries.")
    if not envelope.entities:
        lines.append("(no entities in scope yet)")
    for entity in sorted(envelope.entities, key=lambda e: e.node_id):
        lines.append(f'<entity node_id="{entity.node_id}" type="{entity.type}">')
        lines.append(entity.body.strip())
        lines.append("</entity>")
    lines.append("</game_context>")
    lines.append("")

    lines.append("<player_observations>")
    if not envelope.observations:
        lines.append("(no observations logged)")
    for obs in envelope.observations:
        node = obs.node_id or "—"
        text = obs.payload.get("text", "") if isinstance(obs.payload, dict) else ""
        lines.append(
            f"- {obs.timestamp.isoformat()} source={obs.source} node={node} text={text!r}"
        )
    lines.append("</player_observations>")
    lines.append("")

    lines.append("<instructions>")
    lines.append("Call the return_summary tool with the briefing.")
    lines.append("- Ground every claim in the entries above.")
    lines.append("- Set next_boss to null if the player is too early or no boss content is in scope.")
    lines.append("- Set completion to null when no progress signal implies scope (blind runs).")
    lines.append("</instructions>")
    return "\n".join(lines)


def context_hash(envelope: Envelope, model: str) -> str:
    """Deterministic hash of synthesis inputs. Drives cache invalidation."""
    h = hashlib.sha256()
    h.update(model.encode())
    h.update(envelope.meta.game_id.encode())
    h.update(envelope.meta.body.encode())
    for nid in sorted(envelope.effective_observed):
        h.update(b"\x00observed:")
        h.update(nid.encode())
    for entity in sorted(envelope.entities, key=lambda e: e.node_id):
        h.update(b"\x00entity:")
        h.update(entity.node_id.encode())
        h.update(b"|type=")
        h.update(entity.type.encode())
        for gate in sorted(entity.gates):
            h.update(b"|gate=")
            h.update(gate.encode())
        h.update(b"|body=")
        h.update(entity.body.encode())
    for obs in envelope.observations:
        h.update(b"\x00obs:")
        h.update(obs.timestamp.isoformat().encode())
        h.update(b"|src=")
        h.update(obs.source.encode())
        h.update(b"|node=")
        h.update((obs.node_id or "").encode())
        h.update(b"|payload=")
        h.update(json.dumps(obs.payload, sort_keys=True).encode())
    return h.hexdigest()


class SynthesisError(RuntimeError):
    pass


class SynthesisClient:
    """Wraps the Anthropic SDK call. Inject `client` for tests."""

    def __init__(self, *, client=None, model: str | None = None) -> None:
        self._model = model or os.environ.get("GAMEBUDDY_MODEL", DEFAULT_MODEL)
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self._client = client

    @property
    def model(self) -> str:
        return self._model

    def synthesize(self, envelope: Envelope, *, precomputed_hash: str | None = None) -> Summary:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=[SUMMARY_TOOL],
            tool_choice={"type": "tool", "name": SUMMARY_TOOL_NAME},
            messages=[{"role": "user", "content": render_user_prompt(envelope)}],
        )
        return _parse_response(
            response,
            envelope=envelope,
            model=self._model,
            precomputed_hash=precomputed_hash,
        )


def _parse_response(response, *, envelope: Envelope, model: str, precomputed_hash: str | None) -> Summary:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == SUMMARY_TOOL_NAME:
            data = block.input
            return Summary(
                where_you_are=data["where_you_are"],
                how_you_got_here=data["how_you_got_here"],
                why_youre_doing_this=data["why_youre_doing_this"],
                explore_next=[
                    Suggestion(hint=s["hint"], spoiler=s["spoiler"])
                    for s in data["explore_next"]
                ],
                next_boss=(
                    Suggestion(hint=data["next_boss"]["hint"], spoiler=data["next_boss"]["spoiler"])
                    if data["next_boss"] is not None
                    else None
                ),
                completion=data["completion"],
                model=model,
                generated_at=datetime.now(tz=timezone.utc),
                context_hash=precomputed_hash if precomputed_hash is not None else context_hash(envelope, model),
            )
    raise SynthesisError(f"Model did not call the {SUMMARY_TOOL_NAME} tool")
