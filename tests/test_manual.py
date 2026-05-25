from datetime import datetime, timezone
from pathlib import Path

from gamebuddy.context import load_game_context
from gamebuddy.providers.manual import ManualProvider

FIXTURES = Path(__file__).parent / "fixtures" / "games"


def test_known_node_id_carries_node_id():
    ctx = load_game_context(FIXTURES, "sample")
    fixed = datetime(2026, 5, 25, tzinfo=timezone.utc)
    obs = ManualProvider(ctx.dag, "a", now=fixed).collect()
    assert len(obs) == 1
    assert obs[0].node_id == "a"
    assert obs[0].source == "manual"
    assert obs[0].timestamp == fixed
    assert obs[0].payload == {"text": "a"}


def test_unknown_text_becomes_free_text_note():
    ctx = load_game_context(FIXTURES, "sample")
    obs = ManualProvider(ctx.dag, "this is just a free-form note").collect()
    assert obs[0].node_id is None
    assert obs[0].payload == {"text": "this is just a free-form note"}


def test_whitespace_is_stripped():
    ctx = load_game_context(FIXTURES, "sample")
    obs = ManualProvider(ctx.dag, "  a  ").collect()
    assert obs[0].node_id == "a"


def test_default_now_is_utc():
    ctx = load_game_context(FIXTURES, "sample")
    obs = ManualProvider(ctx.dag, "x").collect()
    assert obs[0].timestamp.tzinfo is not None
