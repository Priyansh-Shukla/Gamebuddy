"""Synthesis envelope: the structured input handed to the model.

`build_envelope(state, context)` returns an `Envelope` containing only entities
whose gates are within the player's effective boundary, plus their observations.
The envelope is a dataclass so synthesis can format it as it sees fit while the
filter contract stays testable in isolation (see DESIGN.md envelope tests).
"""
from __future__ import annotations

from dataclasses import dataclass

from gamebuddy.context import Entity, GameContext, MetaInfo
from gamebuddy.filter import effective_observed, filter_entities
from gamebuddy.schemas import GameState, NodeId, Observation


@dataclass
class Envelope:
    meta: MetaInfo
    effective_observed: set[NodeId]
    entities: list[Entity]
    observations: list[Observation]


def build_envelope(state: GameState, context: GameContext) -> Envelope:
    effective = effective_observed(state.boundary, context.dag)
    eligible = filter_entities(context.entities, effective)
    return Envelope(
        meta=context.meta,
        effective_observed=effective,
        entities=eligible,
        observations=list(state.observations),
    )
