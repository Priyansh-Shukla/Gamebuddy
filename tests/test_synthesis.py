from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from gamebuddy.context import load_game_context
from gamebuddy.envelope import build_envelope
from gamebuddy.schemas import SCHEMA_VERSION, Boundary, GameState, Observation
from gamebuddy.synthesis import (
    SUMMARY_SCHEMA,
    SUMMARY_TOOL,
    SUMMARY_TOOL_NAME,
    SynthesisClient,
    SynthesisError,
    context_hash,
    render_user_prompt,
)

FIXTURES = Path(__file__).parent / "fixtures" / "games"


def _state(observed=frozenset(), observations=()):
    return GameState(
        schema_version=SCHEMA_VERSION,
        game_id="sample",
        last_synced=datetime(2026, 5, 25, tzinfo=timezone.utc),
        boundary=Boundary(observed=set(observed)),
        observations=list(observations),
    )


@pytest.fixture
def envelope():
    ctx = load_game_context(FIXTURES, "sample")
    return build_envelope(_state(observed={"a", "b"}), ctx)


def test_schema_strict_invariants():
    """All keys appear in required, additionalProperties is false."""
    assert SUMMARY_SCHEMA["additionalProperties"] is False
    assert set(SUMMARY_SCHEMA["properties"].keys()) == set(SUMMARY_SCHEMA["required"])
    sugg = SUMMARY_SCHEMA["properties"]["explore_next"]["items"]
    assert sugg["additionalProperties"] is False
    assert set(sugg["properties"].keys()) == set(sugg["required"])


def test_summary_tool_definition():
    assert SUMMARY_TOOL["name"] == SUMMARY_TOOL_NAME
    assert SUMMARY_TOOL["input_schema"] == SUMMARY_SCHEMA
    assert SUMMARY_TOOL["strict"] is True


def test_render_user_prompt_includes_entities(envelope):
    prompt = render_user_prompt(envelope)
    # Eligible entities (a, b, c — all have gates ⊆ {a, b}) appear.
    assert 'node_id="a"' in prompt
    assert 'node_id="b"' in prompt
    assert 'node_id="c"' in prompt
    # Out-of-scope entities (d gated on b — wait, b IS observed, but gates=[b]
    # so d is eligible. e/f are not.) — verify our envelope is what we expect.
    eligible_ids = {e.node_id for e in envelope.entities}
    for nid in eligible_ids:
        assert f'node_id="{nid}"' in prompt
    for nid in {"e", "f"} - eligible_ids:
        assert f'node_id="{nid}"' not in prompt


def test_render_user_prompt_no_leak_for_filtered_entity():
    """Bodies of filtered-out entities must not appear in the prompt."""
    ctx = load_game_context(FIXTURES, "sample")
    env = build_envelope(_state(observed=set()), ctx)  # only 'a' eligible
    prompt = render_user_prompt(env)
    # entity e's body contains the word "ending" — should not appear with
    # observed = {} (where only entity a is eligible).
    assert "Boss D" not in prompt
    assert "The ending." not in prompt
    assert "Item F" not in prompt


def test_render_user_prompt_includes_observations():
    ctx = load_game_context(FIXTURES, "sample")
    obs = Observation(
        timestamp=datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc),
        source="manual",
        node_id="a",
        payload={"text": "starting out"},
    )
    env = build_envelope(_state(observed={"a"}, observations=[obs]), ctx)
    prompt = render_user_prompt(env)
    assert "source=manual" in prompt
    assert "node=a" in prompt
    assert "starting out" in prompt


def test_render_user_prompt_handles_empty_boundary():
    ctx = load_game_context(FIXTURES, "sample")
    env = build_envelope(_state(observed=set()), ctx)
    prompt = render_user_prompt(env)
    assert "(none — player has not reached any tracked nodes)" in prompt
    assert "(no observations logged)" in prompt


def test_context_hash_deterministic(envelope):
    a = context_hash(envelope, "claude-opus-4-7")
    b = context_hash(envelope, "claude-opus-4-7")
    assert a == b


def test_context_hash_changes_with_observed(envelope):
    ctx = load_game_context(FIXTURES, "sample")
    h1 = context_hash(build_envelope(_state(observed={"a"}), ctx), "claude-opus-4-7")
    h2 = context_hash(build_envelope(_state(observed={"a", "b"}), ctx), "claude-opus-4-7")
    assert h1 != h2


def test_context_hash_changes_with_model(envelope):
    h1 = context_hash(envelope, "claude-opus-4-7")
    h2 = context_hash(envelope, "claude-sonnet-4-6")
    assert h1 != h2


def test_context_hash_changes_with_observations(envelope):
    ctx = load_game_context(FIXTURES, "sample")
    obs = Observation(
        timestamp=datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc),
        source="manual",
        node_id="a",
        payload={"text": "x"},
    )
    h1 = context_hash(envelope, "claude-opus-4-7")
    env2 = build_envelope(_state(observed={"a", "b"}, observations=[obs]), ctx)
    h2 = context_hash(env2, "claude-opus-4-7")
    assert h1 != h2


# ---- synthesize() with a mocked client ----------------------------------


def _tool_use_block(payload):
    return SimpleNamespace(type="tool_use", name="return_summary", input=payload)


def _fake_response(payload):
    return SimpleNamespace(content=[_tool_use_block(payload)])


class _FakeAnthropic:
    def __init__(self, response_payload):
        self.response_payload = response_payload
        self.last_call_kwargs = None
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return _fake_response(self.response_payload)


def test_synthesize_returns_summary(envelope):
    payload = {
        "where_you_are": "Dilapidated Temple",
        "how_you_got_here": "You cleared the outskirts and reached the castle.",
        "why_youre_doing_this": "Kuro asked for the Mortal Blade.",
        "explore_next": [
            {"hint": "Try the western valley.", "spoiler": None},
            {"hint": "There's a path you haven't taken.", "spoiler": "Leads to the Sunken Valley."},
        ],
        "next_boss": {"hint": "A castle defender awaits.", "spoiler": "Genichiro Ashina"},
        "completion": "Main: ~25%",
    }
    fake = _FakeAnthropic(payload)
    client = SynthesisClient(client=fake, model="claude-opus-4-7")
    summary = client.synthesize(envelope)

    assert summary.where_you_are == "Dilapidated Temple"
    assert len(summary.explore_next) == 2
    assert summary.explore_next[0].spoiler is None
    assert summary.explore_next[1].spoiler == "Leads to the Sunken Valley."
    assert summary.next_boss is not None
    assert summary.next_boss.spoiler == "Genichiro Ashina"
    assert summary.model == "claude-opus-4-7"
    assert summary.context_hash == context_hash(envelope, "claude-opus-4-7")


def test_synthesize_uses_correct_request_shape(envelope):
    fake = _FakeAnthropic({
        "where_you_are": "x",
        "how_you_got_here": "x",
        "why_youre_doing_this": "x",
        "explore_next": [],
        "next_boss": None,
        "completion": None,
    })
    SynthesisClient(client=fake, model="claude-opus-4-7").synthesize(envelope)

    kw = fake.last_call_kwargs
    assert kw["model"] == "claude-opus-4-7"
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["tool_choice"] == {"type": "tool", "name": "return_summary"}
    assert kw["tools"][0]["name"] == "return_summary"
    assert kw["tools"][0]["strict"] is True
    # No banned-on-4.7 sampling params
    assert "temperature" not in kw
    assert "top_p" not in kw
    assert "top_k" not in kw
    # System prompt present
    assert "GameBuddy" in kw["system"]


def test_synthesize_uses_precomputed_hash(envelope):
    fake = _FakeAnthropic({
        "where_you_are": "x",
        "how_you_got_here": "x",
        "why_youre_doing_this": "x",
        "explore_next": [],
        "next_boss": None,
        "completion": None,
    })
    client = SynthesisClient(client=fake, model="claude-opus-4-7")
    summary = client.synthesize(envelope, precomputed_hash="precomputed")
    assert summary.context_hash == "precomputed"


def test_synthesize_handles_null_next_boss(envelope):
    fake = _FakeAnthropic({
        "where_you_are": "early game",
        "how_you_got_here": "you just started",
        "why_youre_doing_this": "explore",
        "explore_next": [],
        "next_boss": None,
        "completion": None,
    })
    summary = SynthesisClient(client=fake).synthesize(envelope)
    assert summary.next_boss is None
    assert summary.completion is None


def test_synthesize_errors_if_tool_not_called(envelope):
    """If the model returns plain text instead of calling the tool, raise."""
    class _NoToolResponse:
        content = [SimpleNamespace(type="text", text="I'm not calling the tool")]

    class _Bad:
        messages = SimpleNamespace(create=lambda **_: _NoToolResponse())

    with pytest.raises(SynthesisError, match="return_summary"):
        SynthesisClient(client=_Bad()).synthesize(envelope)


def test_default_model_overridable_by_env(monkeypatch, envelope):
    monkeypatch.setenv("GAMEBUDDY_MODEL", "claude-sonnet-4-6")
    fake = _FakeAnthropic({
        "where_you_are": "x",
        "how_you_got_here": "x",
        "why_youre_doing_this": "x",
        "explore_next": [],
        "next_boss": None,
        "completion": None,
    })
    client = SynthesisClient(client=fake)
    assert client.model == "claude-sonnet-4-6"
