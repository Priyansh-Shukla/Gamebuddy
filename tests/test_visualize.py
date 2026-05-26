from datetime import datetime, timezone
from pathlib import Path

import pytest

from gamebuddy.context import load_game_context
from gamebuddy.schemas import SCHEMA_VERSION, Boundary, GameState
from gamebuddy.visualize import classify_nodes, count, to_dot

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


def test_no_state_classifies_all_gated(sample):
    classes = classify_nodes(sample, None)
    assert set(classes.values()) == {"gated"}
    assert count(classes).observed == 0


def test_observed_then_frontier(sample):
    # Observed = {a}. Direct successors b, c are on the frontier (a is in
    # their `requires`). d, e, f are gated (no observed predecessor).
    classes = classify_nodes(sample, _state({"a"}))
    assert classes["a"] == "observed"
    assert classes["b"] == "frontier"
    assert classes["c"] == "frontier"
    assert classes["d"] == "gated"
    assert classes["e"] == "gated"
    assert classes["f"] == "gated"


def test_suggests_promotes_frontier(sample):
    # Observed = {a, b}. d requires b → frontier via requires. Now observe c:
    # the existing `d suggests c` edge means d is also reachable from c via
    # a `suggests` predecessor — confirms `suggests` counts toward frontier.
    classes = classify_nodes(sample, _state({"a", "c"}))
    # d suggests c, so d is on the frontier even though d.requires == {b}
    # and b is not observed.
    assert classes["d"] == "frontier"


def test_declared_expands_observed_via_ancestors(sample):
    # declared=d pulls ancestors {a, b}; e requires d → frontier.
    classes = classify_nodes(sample, _state(set(), declared="d"))
    assert classes["a"] == "observed"
    assert classes["b"] == "observed"
    assert classes["d"] == "observed"
    assert classes["e"] == "frontier"


def test_dot_no_state_renders_only_header_when_not_reveal(sample):
    dot = to_dot(sample, None, reveal=False)
    assert dot.startswith('digraph "sample" {')
    # All nodes are gated and not revealed — no node lines.
    for n in ("a", "b", "c", "d", "e", "f"):
        assert f'"{n}" [' not in dot


def test_dot_reveal_renders_everything(sample):
    dot = to_dot(sample, None, reveal=True)
    for n in ("a", "b", "c", "d", "e", "f"):
        assert f'"{n}" [' in dot
    # `requires` edges → solid, `suggests` edges → dashed.
    assert '"a" -> "b" [style=solid];' in dot
    assert '"c" -> "d" [style=dashed' in dot


def test_dot_frontier_label_is_masked(sample):
    dot = to_dot(sample, _state({"a"}), reveal=False)
    # `a` is observed and shown with its id.
    assert 'label="a"' in dot
    # `b` is frontier: id `b` must not appear as a label, only the type.
    assert 'label="b"' not in dot
    assert 'label="? (boss)"' in dot
    # Gated nodes (d, e, f) are not rendered at all.
    assert '"d" [' not in dot
    assert '"e" [' not in dot
    assert '"f" [' not in dot


def test_dot_omits_edges_to_unrendered_nodes(sample):
    dot = to_dot(sample, _state({"a"}), reveal=False)
    # Edges into gated nodes should not appear.
    assert '"b" -> "d"' not in dot
    assert '"b" -> "f"' not in dot
    # Edges among rendered nodes should appear (a -> b, a -> c).
    assert '"a" -> "b"' in dot
    assert '"a" -> "c"' in dot


def test_dot_reveal_does_not_mask_frontier(sample):
    dot = to_dot(sample, _state({"a"}), reveal=True)
    # In reveal mode, frontier node `b` keeps its real label.
    assert 'label="b"' in dot
    assert 'label="? (boss)"' not in dot


def test_sekiro_context_renders(sample):
    # Smoke test against the real Sekiro DAG: blank state renders nothing,
    # reveal renders every node, no crashes.
    sekiro = load_game_context(Path("games"), "sekiro")
    blank = to_dot(sekiro, None, reveal=False)
    assert "digraph" in blank
    full = to_dot(sekiro, None, reveal=True)
    for n_id in sekiro.dag.nodes:
        assert f'"{n_id}" [' in full
