"""JSON store for player state.

Per CLAUDE.md the file is human-readable so it can be hand-edited: sets are
serialized as sorted lists, datetimes as ISO 8601, indent=2 with LF endings.

`apply_observations` is the canonical mutation: append observations, advance
`boundary.observed` for any that carry a node_id, invalidate the synthesis
cache, and bump `last_synced`.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import cast

from gamebuddy.schemas import (
    SCHEMA_VERSION,
    Boundary,
    GameState,
    Observation,
    Source,
    Suggestion,
    Summary,
)


def state_to_dict(state: GameState) -> dict:
    return {
        "schema_version": state.schema_version,
        "game_id": state.game_id,
        "last_synced": state.last_synced.isoformat(),
        "boundary": {
            "observed": sorted(state.boundary.observed),
            "declared": state.boundary.declared,
        },
        "observations": [_observation_to_dict(o) for o in state.observations],
        "synthesis_cache": (
            _summary_to_dict(state.synthesis_cache)
            if state.synthesis_cache is not None
            else None
        ),
    }


def _observation_to_dict(o: Observation) -> dict:
    return {
        "timestamp": o.timestamp.isoformat(),
        "source": o.source,
        "node_id": o.node_id,
        "payload": o.payload,
    }


def _suggestion_to_dict(s: Suggestion) -> dict:
    return {"hint": s.hint, "spoiler": s.spoiler}


def _summary_to_dict(s: Summary) -> dict:
    return {
        "where_you_are": s.where_you_are,
        "how_you_got_here": s.how_you_got_here,
        "why_youre_doing_this": s.why_youre_doing_this,
        "explore_next": [_suggestion_to_dict(x) for x in s.explore_next],
        "next_boss": _suggestion_to_dict(s.next_boss) if s.next_boss is not None else None,
        "completion": s.completion,
        "model": s.model,
        "generated_at": s.generated_at.isoformat(),
        "context_hash": s.context_hash,
    }


def state_from_dict(data: dict) -> GameState:
    ver = data["schema_version"]
    if ver != SCHEMA_VERSION:
        raise ValueError(
            f"schema_version={ver} is unsupported; this build expects "
            f"{SCHEMA_VERSION}. Add a migration before bumping."
        )
    return GameState(
        schema_version=ver,
        game_id=data["game_id"],
        last_synced=datetime.fromisoformat(data["last_synced"]),
        boundary=Boundary(
            observed=set(data["boundary"]["observed"]),
            declared=data["boundary"]["declared"],
        ),
        observations=[_observation_from_dict(o) for o in data.get("observations", [])],
        synthesis_cache=(
            _summary_from_dict(data["synthesis_cache"])
            if data.get("synthesis_cache") is not None
            else None
        ),
    )


def _observation_from_dict(d: dict) -> Observation:
    return Observation(
        timestamp=datetime.fromisoformat(d["timestamp"]),
        source=cast(Source, d["source"]),
        node_id=d["node_id"],
        payload=d["payload"],
    )


def _suggestion_from_dict(d: dict) -> Suggestion:
    return Suggestion(hint=d["hint"], spoiler=d["spoiler"])


def _summary_from_dict(d: dict) -> Summary:
    return Summary(
        where_you_are=d["where_you_are"],
        how_you_got_here=d["how_you_got_here"],
        why_youre_doing_this=d["why_youre_doing_this"],
        explore_next=[_suggestion_from_dict(x) for x in d["explore_next"]],
        next_boss=_suggestion_from_dict(d["next_boss"]) if d["next_boss"] is not None else None,
        completion=d["completion"],
        model=d["model"],
        generated_at=datetime.fromisoformat(d["generated_at"]),
        context_hash=d["context_hash"],
    )


def save_state(state: GameState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state_to_dict(state), indent=2)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def load_state(path: Path) -> GameState:
    data = json.loads(path.read_text(encoding="utf-8"))
    return state_from_dict(data)


def apply_observations(state: GameState, observations: list[Observation]) -> None:
    if not observations:
        return
    for obs in observations:
        state.observations.append(obs)
        if obs.node_id is not None:
            state.boundary.observed.add(obs.node_id)
    state.synthesis_cache = None
    state.last_synced = max(o.timestamp for o in observations)
