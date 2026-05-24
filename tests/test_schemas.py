from dataclasses import asdict
from datetime import datetime, timezone

from gamebuddy import SCHEMA_VERSION
from gamebuddy.schemas import (
    Boundary,
    GameState,
    Observation,
    Suggestion,
    Summary,
)


def test_schema_version_is_int():
    assert isinstance(SCHEMA_VERSION, int)
    assert SCHEMA_VERSION >= 1


def test_boundary_defaults_empty():
    b = Boundary()
    assert b.observed == set()
    assert b.declared is None


def test_boundary_with_values():
    b = Boundary(observed={"a", "b"}, declared="c")
    assert b.observed == {"a", "b"}
    assert b.declared == "c"


def test_observation_construction():
    ts = datetime.now(tz=timezone.utc)
    obs = Observation(
        timestamp=ts,
        source="manual",
        node_id="genichiro",
        payload={"note": "beat him"},
    )
    assert obs.source == "manual"
    assert obs.node_id == "genichiro"
    assert obs.payload == {"note": "beat him"}


def test_observation_without_node():
    obs = Observation(
        timestamp=datetime.now(tz=timezone.utc),
        source="manual",
        node_id=None,
        payload={"text": "free-form note"},
    )
    assert obs.node_id is None


def test_suggestion_hint_only():
    s = Suggestion(hint="Try the western valley.")
    assert s.spoiler is None


def test_suggestion_with_spoiler():
    s = Suggestion(hint="A tough fight awaits.", spoiler="Genichiro Ashina")
    assert s.spoiler == "Genichiro Ashina"


def test_summary_full():
    s = Summary(
        where_you_are="Dilapidated Temple",
        how_you_got_here="You cleared the Outskirts and reached the Castle gate.",
        why_youre_doing_this="Kuro asked you to find the Mortal Blade.",
        explore_next=[Suggestion(hint="The western valley may help.")],
        next_boss=Suggestion(hint="Castle defender.", spoiler="Genichiro"),
        completion="Main story: ~25%",
        model="claude-opus-4-7",
        generated_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
        context_hash="abc123",
    )
    assert s.next_boss is not None
    assert s.next_boss.spoiler == "Genichiro"
    assert s.completion is not None


def test_summary_blind_run_omits_completion():
    s = Summary(
        where_you_are="An underwater base",
        how_you_got_here="...",
        why_youre_doing_this="...",
        explore_next=[],
        next_boss=None,
        completion=None,
        model="claude-opus-4-7",
        generated_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
        context_hash="def456",
    )
    assert s.completion is None
    assert s.next_boss is None


def test_gamestate_minimal():
    state = GameState(
        schema_version=SCHEMA_VERSION,
        game_id="sekiro",
        last_synced=datetime.now(tz=timezone.utc),
        boundary=Boundary(observed={"ashina_outskirts"}),
    )
    assert state.observations == []
    assert state.synthesis_cache is None


def test_gamestate_asdict_preserves_structure():
    state = GameState(
        schema_version=SCHEMA_VERSION,
        game_id="sekiro",
        last_synced=datetime(2026, 5, 25, tzinfo=timezone.utc),
        boundary=Boundary(observed={"a", "b"}, declared="c"),
        observations=[
            Observation(
                timestamp=datetime(2026, 5, 25, tzinfo=timezone.utc),
                source="manual",
                node_id="a",
                payload={"k": "v"},
            )
        ],
    )
    d = asdict(state)
    assert d["game_id"] == "sekiro"
    assert d["boundary"]["declared"] == "c"
    assert d["boundary"]["observed"] == {"a", "b"}
    assert d["observations"][0]["payload"] == {"k": "v"}
    assert d["synthesis_cache"] is None
