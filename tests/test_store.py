import json
from datetime import datetime, timezone

import pytest

from gamebuddy.schemas import (
    SCHEMA_VERSION,
    Boundary,
    GameState,
    Observation,
    Suggestion,
    Summary,
)
from gamebuddy.store import (
    apply_observations,
    load_state,
    save_state,
    state_from_dict,
    state_to_dict,
)


def _full_state() -> GameState:
    return GameState(
        schema_version=SCHEMA_VERSION,
        game_id="sample",
        last_synced=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc),
        boundary=Boundary(observed={"a", "b"}, declared="d"),
        observations=[
            Observation(
                timestamp=datetime(2026, 5, 25, 11, 0, tzinfo=timezone.utc),
                source="manual",
                node_id="a",
                payload={"text": "reached A"},
            ),
            Observation(
                timestamp=datetime(2026, 5, 25, 11, 30, tzinfo=timezone.utc),
                source="manual",
                node_id=None,
                payload={"text": "just a note"},
            ),
        ],
        synthesis_cache=Summary(
            where_you_are="At A",
            how_you_got_here="...",
            why_youre_doing_this="...",
            explore_next=[Suggestion(hint="Explore", spoiler=None)],
            next_boss=Suggestion(hint="A boss looms.", spoiler="B"),
            completion="Main: 10%",
            model="claude-opus-4-7",
            generated_at=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc),
            context_hash="abc",
        ),
    )


def test_round_trip_in_memory():
    state = _full_state()
    d = state_to_dict(state)
    back = state_from_dict(d)
    assert back.game_id == state.game_id
    assert back.boundary.observed == state.boundary.observed
    assert back.boundary.declared == state.boundary.declared
    assert back.last_synced == state.last_synced
    assert len(back.observations) == 2
    assert back.observations[0].node_id == "a"
    assert back.observations[1].node_id is None
    assert back.synthesis_cache is not None
    assert back.synthesis_cache.next_boss is not None
    assert back.synthesis_cache.next_boss.spoiler == "B"


def test_round_trip_on_disk(tmp_path):
    state = _full_state()
    p = tmp_path / "sample.json"
    save_state(state, p)
    loaded = load_state(p)
    assert state_to_dict(loaded) == state_to_dict(state)


def test_saved_json_is_human_readable(tmp_path):
    state = _full_state()
    p = tmp_path / "sample.json"
    save_state(state, p)
    raw = p.read_text(encoding="utf-8")
    assert raw.startswith("{\n")
    assert "  \"game_id\": \"sample\"" in raw
    # sets serialized as sorted lists
    parsed = json.loads(raw)
    assert parsed["boundary"]["observed"] == ["a", "b"]


def test_saved_json_uses_lf_endings(tmp_path):
    state = _full_state()
    p = tmp_path / "sample.json"
    save_state(state, p)
    raw_bytes = p.read_bytes()
    assert b"\r\n" not in raw_bytes


def test_load_rejects_unsupported_schema_version(tmp_path):
    bad = {
        "schema_version": 999,
        "game_id": "x",
        "last_synced": "2026-05-25T00:00:00+00:00",
        "boundary": {"observed": [], "declared": None},
        "observations": [],
        "synthesis_cache": None,
    }
    p = tmp_path / "x.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        load_state(p)


def test_save_creates_parent_directory(tmp_path):
    state = _full_state()
    p = tmp_path / "nested" / "dirs" / "sample.json"
    save_state(state, p)
    assert p.exists()


def test_apply_observations_advances_observed():
    state = GameState(
        schema_version=SCHEMA_VERSION,
        game_id="x",
        last_synced=datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc),
        boundary=Boundary(observed=set()),
    )
    obs = [
        Observation(
            timestamp=datetime(2026, 5, 25, 11, 0, tzinfo=timezone.utc),
            source="manual",
            node_id="a",
            payload={"text": "got a"},
        )
    ]
    apply_observations(state, obs)
    assert state.boundary.observed == {"a"}
    assert state.last_synced == obs[0].timestamp
    assert len(state.observations) == 1


def test_apply_observations_free_text_does_not_advance():
    state = GameState(
        schema_version=SCHEMA_VERSION,
        game_id="x",
        last_synced=datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc),
        boundary=Boundary(observed={"existing"}),
    )
    obs = [
        Observation(
            timestamp=datetime(2026, 5, 25, 11, 0, tzinfo=timezone.utc),
            source="manual",
            node_id=None,
            payload={"text": "just a note"},
        )
    ]
    apply_observations(state, obs)
    assert state.boundary.observed == {"existing"}
    assert len(state.observations) == 1


def test_apply_observations_invalidates_cache():
    state = _full_state()
    assert state.synthesis_cache is not None
    apply_observations(
        state,
        [
            Observation(
                timestamp=datetime(2026, 5, 26, tzinfo=timezone.utc),
                source="manual",
                node_id=None,
                payload={"text": "note"},
            )
        ],
    )
    assert state.synthesis_cache is None


def test_apply_observations_empty_is_noop():
    state = _full_state()
    before = state_to_dict(state)
    apply_observations(state, [])
    assert state_to_dict(state) == before
