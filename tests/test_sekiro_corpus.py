"""Validate the real Sekiro game-context corpus against the filter contract.

Smoke test that the authored package under `games/sekiro/` loads cleanly, has
1:1 node↔entity coverage, and never leaks past the boundary at a sweep of
representative progression points. Catches authoring slips (typo'd gates,
forgotten entity files, endings cross-gated on shared predecessors) that the
synthetic fixture in test_envelope.py cannot.
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from gamebuddy.context import load_game_context
from gamebuddy.envelope import build_envelope
from gamebuddy.schemas import SCHEMA_VERSION, Boundary, GameState

GAMES_DIR = Path(__file__).parent.parent / "games"


@pytest.fixture(scope="module")
def sekiro():
    return load_game_context(GAMES_DIR, "sekiro")


def _state(boundary: Boundary) -> GameState:
    return GameState(
        schema_version=SCHEMA_VERSION,
        game_id="sekiro",
        last_synced=datetime(2026, 5, 26, tzinfo=timezone.utc),
        boundary=boundary,
    )


def test_corpus_loads_and_has_one_entity_per_node(sekiro):
    node_ids = set(sekiro.dag.nodes.keys())
    entity_ids = [e.node_id for e in sekiro.entities]
    assert len(entity_ids) == len(set(entity_ids)), "duplicate entity for some node"
    assert set(entity_ids) == node_ids, (
        f"node↔entity mismatch: "
        f"nodes-without-entity={node_ids - set(entity_ids)}, "
        f"entity-without-node={set(entity_ids) - node_ids}"
    )


# Representative boundaries, declared so ancestors auto-expand. Covers fresh
# start, opening area, mid-game hub gate, late-game gate, and an endgame ending.
SWEEP_BOUNDARIES = [
    Boundary(),
    Boundary(declared="ashina_outskirts"),
    Boundary(declared="genichiro_ashina"),
    Boundary(declared="fountainhead_palace"),
    Boundary(declared="ending_purification"),
]


@pytest.mark.parametrize("boundary", SWEEP_BOUNDARIES, ids=lambda b: b.declared or "empty")
def test_envelope_never_leaks_past_boundary(sekiro, boundary):
    env = build_envelope(_state(boundary), sekiro)
    for entity in env.entities:
        assert entity.gates <= env.effective_observed, (
            f"leak at boundary declared={boundary.declared}: "
            f"{entity.node_id} has gates {entity.gates} but "
            f"effective={env.effective_observed}"
        )


def test_envelope_grows_monotonically_along_critical_path(sekiro):
    sizes = [
        len(build_envelope(_state(b), sekiro).entities)
        for b in SWEEP_BOUNDARIES
    ]
    assert sizes == sorted(sizes), (
        f"expected surface count to grow as boundary advances, got {sizes}"
    )
    assert sizes[-1] > sizes[0], "endgame boundary should surface more than empty"


def test_endings_stay_hidden_until_their_own_node_is_observed(sekiro):
    """Each ending must be gated tightly enough that reaching the final boss
    doesn't reveal which ending you got. Validates the agent's claim that
    endings self-gate per the gates contract in CLAUDE.md."""
    ending_ids = {n.node_id for n in sekiro.dag.nodes.values() if n.type == "ending"}
    assert ending_ids, "expected at least one ending node"

    # Boundary just before any ending: everything through Isshin, no ending observed.
    pre_ending = _state(Boundary(declared="isshin_sword_saint"))
    pre_env = build_envelope(pre_ending, sekiro)
    surfaced = {e.node_id for e in pre_env.entities}
    leaked = ending_ids & surfaced
    assert not leaked, (
        f"endings leaked before being observed: {leaked}. "
        "Endings must self-gate (gates contain their own node_id) so reaching "
        "the final boss does not reveal which ending the player got."
    )

    # Observing one ending must not surface the others.
    for ending in ending_ids:
        env = build_envelope(_state(Boundary(observed={ending})), sekiro)
        surfaced = {e.node_id for e in env.entities}
        siblings_leaked = (ending_ids - {ending}) & surfaced
        assert not siblings_leaked, (
            f"observing {ending} leaked sibling endings: {siblings_leaked}"
        )
