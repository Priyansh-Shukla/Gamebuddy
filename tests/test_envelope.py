from datetime import datetime, timezone
from pathlib import Path

import pytest

from gamebuddy.context import load_game_context
from gamebuddy.envelope import build_envelope
from gamebuddy.filter import effective_observed, filter_entities
from gamebuddy.schemas import SCHEMA_VERSION, Boundary, GameState, Observation

FIXTURES = Path(__file__).parent / "fixtures" / "games"


@pytest.fixture
def sample():
    return load_game_context(FIXTURES, "sample")


def _state(observed: set[str], declared: str | None = None) -> GameState:
    return GameState(
        schema_version=SCHEMA_VERSION,
        game_id="sample",
        last_synced=datetime(2026, 5, 25, tzinfo=timezone.utc),
        boundary=Boundary(observed=set(observed), declared=declared),
    )


def test_loader_reads_meta(sample):
    assert sample.meta.game_id == "sample"
    assert sample.meta.title == "Sample Game"
    assert sample.meta.schema_version == 1
    assert "test fixture" in sample.meta.sources


def test_loader_reads_all_nodes_and_entities(sample):
    assert set(sample.dag.nodes.keys()) == {"a", "b", "c", "d", "e", "f"}
    assert {e.node_id for e in sample.entities} == {"a", "b", "c", "d", "e", "f"}


def test_loader_parses_edges(sample):
    assert sample.dag.requires["b"] == {"a"}
    assert sample.dag.requires["f"] == {"b", "c"}
    assert sample.dag.suggests["d"] == {"c"}


def test_dag_ancestors_via_requires_only(sample):
    assert sample.dag.ancestors("a") == set()
    assert sample.dag.ancestors("b") == {"a"}
    assert sample.dag.ancestors("d") == {"a", "b"}
    assert sample.dag.ancestors("e") == {"a", "b", "d"}
    assert sample.dag.ancestors("f") == {"a", "b", "c"}


def test_dag_ancestors_ignores_suggests(sample):
    # d suggests c, but suggests must not count as a requires-ancestor.
    assert "c" not in sample.dag.ancestors("d")


def test_empty_observed_shows_only_ungated(sample):
    eff = effective_observed(Boundary(), sample.dag)
    assert eff == set()
    eligible = {e.node_id for e in filter_entities(sample.entities, eff)}
    assert eligible == {"a"}


def test_observed_unlocks_single_gates(sample):
    eff = effective_observed(Boundary(observed={"a"}), sample.dag)
    eligible = {e.node_id for e in filter_entities(sample.entities, eff)}
    assert eligible == {"a", "b", "c"}


def test_multi_gate_requires_all_predecessors(sample):
    one_pred = effective_observed(Boundary(observed={"a", "b"}), sample.dag)
    assert "f" not in {e.node_id for e in filter_entities(sample.entities, one_pred)}

    both_pred = effective_observed(Boundary(observed={"a", "b", "c"}), sample.dag)
    eligible = {e.node_id for e in filter_entities(sample.entities, both_pred)}
    assert "f" in eligible


def test_tightly_self_gated_entity_hidden_until_observed(sample):
    """e.gates = [e] — ending content stays hidden until e itself is reached."""
    eff = effective_observed(Boundary(observed={"a", "b", "d"}), sample.dag)
    assert "e" not in {x.node_id for x in filter_entities(sample.entities, eff)}

    eff = effective_observed(Boundary(observed={"a", "b", "d", "e"}), sample.dag)
    assert "e" in {x.node_id for x in filter_entities(sample.entities, eff)}


def test_declared_expands_via_requires_ancestors(sample):
    eff = effective_observed(Boundary(declared="d"), sample.dag)
    assert eff == {"a", "b", "d"}
    eligible = {e.node_id for e in filter_entities(sample.entities, eff)}
    # a, b, d gated within {a,b,d}; c.gates=[a] ⊆ eff so c is shown too.
    # e.gates=[e] ⊄ eff, f.gates=[b,c] ⊄ eff (c missing).
    assert eligible == {"a", "b", "c", "d"}


def test_envelope_never_leaks_past_boundary(sample):
    """The load-bearing property: every entity in the envelope passes the
    gates ⊆ effective_observed check. This is the structural spoiler defense."""
    for observed in [set(), {"a"}, {"a", "b"}, {"a", "b", "c"}, {"a", "b", "c", "d"}]:
        state = _state(observed=observed)
        env = build_envelope(state, sample)
        for entity in env.entities:
            assert entity.gates <= env.effective_observed, (
                f"leak with observed={observed}: {entity.node_id} has "
                f"gates {entity.gates} but effective={env.effective_observed}"
            )


def test_envelope_passes_observations_through(sample):
    obs = Observation(
        timestamp=datetime(2026, 5, 25, tzinfo=timezone.utc),
        source="manual",
        node_id="b",
        payload={"note": "beat it"},
    )
    state = GameState(
        schema_version=SCHEMA_VERSION,
        game_id="sample",
        last_synced=datetime(2026, 5, 25, tzinfo=timezone.utc),
        boundary=Boundary(observed={"a", "b"}),
        observations=[obs],
    )
    env = build_envelope(state, sample)
    assert env.observations == [obs]


def test_envelope_carries_meta(sample):
    env = build_envelope(_state(observed=set()), sample)
    assert env.meta.game_id == "sample"
    assert env.meta.title == "Sample Game"


def test_loader_rejects_unknown_node_in_gates(tmp_path):
    game = tmp_path / "broken"
    (game / "entities").mkdir(parents=True)
    (game / "meta.md").write_text(
        "---\ngame_id: broken\ntitle: x\nschema_version: 1\n---\n",
        encoding="utf-8",
    )
    (game / "progression.yaml").write_text(
        "nodes:\n  - id: x\n    type: area\n", encoding="utf-8"
    )
    (game / "entities" / "x.md").write_text(
        "---\nnode_id: x\ntype: area\ngates: [ghost]\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ghost"):
        load_game_context(tmp_path, "broken")


def test_loader_rejects_edge_to_unknown_node(tmp_path):
    game = tmp_path / "broken"
    game.mkdir(parents=True)
    (game / "meta.md").write_text(
        "---\ngame_id: broken\ntitle: x\nschema_version: 1\n---\n",
        encoding="utf-8",
    )
    (game / "progression.yaml").write_text(
        "nodes:\n  - id: x\n    type: area\n    requires: [ghost]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ghost"):
        load_game_context(tmp_path, "broken")


def test_loader_requires_meta_game_id_match(tmp_path):
    game = tmp_path / "actual"
    game.mkdir(parents=True)
    (game / "meta.md").write_text(
        "---\ngame_id: different\ntitle: x\nschema_version: 1\n---\n",
        encoding="utf-8",
    )
    (game / "progression.yaml").write_text("nodes: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match directory"):
        load_game_context(tmp_path, "actual")
