from pathlib import Path
from types import SimpleNamespace

import pytest

from gamebuddy.onboard import (
    OnboardError,
    Onboarder,
    WRITE_FILE_TOOL,
    _validate_relative_path,
)


# ---- path validation --------------------------------------------------------


def test_validate_rejects_empty():
    with pytest.raises(OnboardError, match="empty"):
        _validate_relative_path("")


def test_validate_rejects_absolute_posix():
    with pytest.raises(OnboardError, match="absolute"):
        _validate_relative_path("/etc/passwd")


def test_validate_rejects_parent_traversal():
    with pytest.raises(OnboardError, match=r"\.\."):
        _validate_relative_path("../escape.md")


def test_validate_rejects_nested_parent_traversal():
    with pytest.raises(OnboardError, match=r"\.\."):
        _validate_relative_path("entities/../../etc/passwd")


def test_validate_accepts_nested_relative():
    p = _validate_relative_path("entities/bosses/genichiro.md")
    assert p == Path("entities/bosses/genichiro.md")


def test_write_file_schema_is_strict():
    schema = WRITE_FILE_TOOL["input_schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"].keys()) == set(schema["required"])


# ---- agentic loop with mocked client ----------------------------------------


def _block_text(text: str):
    return SimpleNamespace(type="text", text=text)


def _block_tool_use(use_id: str, name: str, input_data: dict):
    return SimpleNamespace(type="tool_use", id=use_id, name=name, input=input_data)


def _msg(content: list, stop_reason: str):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class _FakeStream:
    """Stand-in for client.messages.stream(...) context manager."""

    def __init__(self, response):
        self._response = response
        self.text_stream = (
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get_final_message(self):
        return self._response


class _FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.last_call_kwargs = None

    def stream(self, **kwargs):
        self.last_call_kwargs = kwargs
        if not self._responses:
            raise AssertionError("ran out of canned responses")
        return _FakeStream(self._responses.pop(0))


class _FakeAnthropic:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def test_run_writes_files_and_returns_paths(tmp_path):
    target = tmp_path / "fake_game"
    target.mkdir()
    responses = [
        _msg(
            [
                _block_text("Drafting meta and one entity.\n"),
                _block_tool_use("u1", "write_file", {"path": "meta.md", "content": "meta body"}),
                _block_tool_use(
                    "u2",
                    "write_file",
                    {"path": "entities/areas/a.md", "content": "area body"},
                ),
            ],
            stop_reason="tool_use",
        ),
        _msg([_block_text("Done.")], stop_reason="end_turn"),
    ]
    onboarder = Onboarder(
        game_id="fake_game",
        target_dir=target,
        client=_FakeAnthropic(responses),
    )
    written = onboarder.run()

    assert len(written) == 2
    assert (target / "meta.md").read_text(encoding="utf-8") == "meta body"
    assert (target / "entities" / "areas" / "a.md").read_text(encoding="utf-8") == "area body"


def test_run_streams_text_via_output_callable(tmp_path):
    target = tmp_path / "fake_game"
    target.mkdir()
    responses = [
        _msg([_block_text("hello "), _block_text("world")], stop_reason="end_turn"),
    ]
    captured: list[str] = []
    Onboarder(
        game_id="fake_game",
        target_dir=target,
        client=_FakeAnthropic(responses),
        output=captured.append,
    ).run()
    joined = "".join(captured)
    assert "hello " in joined
    assert "world" in joined


def test_run_continues_on_pause_turn(tmp_path):
    """pause_turn means server-side tool iteration limit — resend, no client action."""
    target = tmp_path / "fake_game"
    target.mkdir()
    responses = [
        _msg([_block_text("searching...")], stop_reason="pause_turn"),
        _msg(
            [_block_tool_use("u1", "write_file", {"path": "meta.md", "content": "body"})],
            stop_reason="tool_use",
        ),
        _msg([_block_text("done")], stop_reason="end_turn"),
    ]
    written = Onboarder(
        game_id="fake_game",
        target_dir=target,
        client=_FakeAnthropic(responses),
    ).run()
    assert len(written) == 1


def test_run_returns_error_tool_result_on_bad_path(tmp_path):
    """A bad path should return is_error tool_result, not crash the run."""
    target = tmp_path / "fake_game"
    target.mkdir()
    responses = [
        _msg(
            [_block_tool_use("u1", "write_file", {"path": "/etc/passwd", "content": "x"})],
            stop_reason="tool_use",
        ),
        _msg([_block_text("ok")], stop_reason="end_turn"),
    ]
    fake = _FakeAnthropic(responses)
    written = Onboarder(
        game_id="fake_game",
        target_dir=target,
        client=fake,
    ).run()

    assert written == []
    # the second turn's messages include the error tool_result
    sent_messages = fake.messages.last_call_kwargs["messages"]
    last_user = [m for m in sent_messages if m["role"] == "user"][-1]
    assert any(
        block.get("is_error") for block in last_user["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    )


def test_run_errors_on_max_rounds(tmp_path):
    target = tmp_path / "fake_game"
    target.mkdir()
    # loop forever — each round just emits one write and never ends
    looper = [
        _msg(
            [_block_tool_use(f"u{i}", "write_file", {"path": f"x{i}.md", "content": "."})],
            stop_reason="tool_use",
        )
        for i in range(10)
    ]
    onboarder = Onboarder(
        game_id="fake_game",
        target_dir=target,
        client=_FakeAnthropic(looper),
        max_rounds=3,
    )
    with pytest.raises(OnboardError, match="max rounds"):
        onboarder.run()


def test_request_includes_required_tools(tmp_path):
    target = tmp_path / "fake_game"
    target.mkdir()
    fake = _FakeAnthropic([_msg([_block_text("done")], stop_reason="end_turn")])
    Onboarder(game_id="fake_game", target_dir=target, client=fake).run()
    kw = fake.messages.last_call_kwargs
    tool_names = {t.get("name") or t.get("type") for t in kw["tools"]}
    assert "web_search" in tool_names
    assert "web_fetch" in tool_names
    assert "write_file" in tool_names
    assert "GameBuddy onboarding author" in kw["system"]
    # Opus 4.7 contract — no sampling params
    assert "temperature" not in kw
    assert "top_p" not in kw
    assert "top_k" not in kw


def test_write_creates_parent_directories(tmp_path):
    target = tmp_path / "fake_game"
    target.mkdir()
    responses = [
        _msg(
            [
                _block_tool_use(
                    "u1",
                    "write_file",
                    {"path": "entities/bosses/nested/path/x.md", "content": "deep"},
                )
            ],
            stop_reason="tool_use",
        ),
        _msg([_block_text("done")], stop_reason="end_turn"),
    ]
    Onboarder(
        game_id="fake_game",
        target_dir=target,
        client=_FakeAnthropic(responses),
    ).run()
    assert (target / "entities" / "bosses" / "nested" / "path" / "x.md").exists()
