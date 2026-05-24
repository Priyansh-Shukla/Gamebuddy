"""Player-state and synthesis schemas.

These types are the contract between providers, the prompt builder, the
synthesis layer, and the JSON store. Keep them flat and JSON-friendly
(modulo set/datetime, which the store will encode).

`SCHEMA_VERSION` is the on-disk player-state version, independent of the
package version. Bump when the GameState shape changes; ship a migration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

SCHEMA_VERSION = 1

NodeId = str
Source = Literal["save", "manual", "screenshot"]


@dataclass
class Boundary:
    observed: set[NodeId] = field(default_factory=set)
    declared: NodeId | None = None


@dataclass
class Observation:
    timestamp: datetime
    source: Source
    node_id: NodeId | None
    payload: dict


@dataclass
class Suggestion:
    hint: str
    spoiler: str | None = None


@dataclass
class Summary:
    where_you_are: str
    how_you_got_here: str
    why_youre_doing_this: str
    explore_next: list[Suggestion]
    next_boss: Suggestion | None
    # Omitted for blind runs (v2+) where scope itself is a spoiler.
    completion: str | None
    model: str
    generated_at: datetime
    # Hash of the game-context subset that fed synthesis; cache invalidates
    # when this changes (see DESIGN.md cache invalidation rules).
    context_hash: str


@dataclass
class GameState:
    schema_version: int
    game_id: str
    last_synced: datetime
    boundary: Boundary
    observations: list[Observation] = field(default_factory=list)
    synthesis_cache: Summary | None = None
