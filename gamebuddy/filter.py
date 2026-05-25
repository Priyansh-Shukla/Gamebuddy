"""Boundary computation and entity filtering — the spoiler defense.

Contract: an entity is eligible for the synthesis prompt iff its `gates` are
a subset of the effective boundary. The model literally cannot mention what
it never received.

`declared` is treated as additive: effective = observed ∪ ancestors_inclusive(declared).
This matches the literal `∪` in DESIGN.md. The "clipped to the smaller" phrase
there is ambiguous; revisit if v2 (blind run) needs a restrictive reading.
"""
from __future__ import annotations

from gamebuddy.context import Entity, ProgressionDAG
from gamebuddy.schemas import Boundary, NodeId


def effective_observed(boundary: Boundary, dag: ProgressionDAG) -> set[NodeId]:
    eff = set(boundary.observed)
    if boundary.declared is not None:
        eff.add(boundary.declared)
        eff |= dag.ancestors(boundary.declared)
    return eff


def filter_entities(entities: list[Entity], effective: set[NodeId]) -> list[Entity]:
    return [e for e in entities if e.gates <= effective]
