import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from gamebuddy.cli import cli
from gamebuddy.schemas import Suggestion, Summary
from gamebuddy.store import load_state

FIXTURES = Path(__file__).parent / "fixtures" / "games"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Point the CLI at an isolated tmp_path: real `sample` game context, empty data dir."""
    games = tmp_path / "games"
    games.mkdir()
    shutil.copytree(FIXTURES / "sample", games / "sample")
    data = tmp_path / "data"
    monkeypatch.setenv("GAMEBUDDY_GAMES_DIR", str(games))
    monkeypatch.setenv("GAMEBUDDY_DATA_DIR", str(data))
    return tmp_path


def test_status_with_no_games(env):
    result = CliRunner().invoke(cli, ["status"])
    assert result.exit_code == 0
    assert "No tracked games" in result.output


def test_log_node_id_advances_observed(env):
    result = CliRunner().invoke(cli, ["log", "sample", "a"])
    assert result.exit_code == 0, result.output
    assert "Logged node `a`" in result.output
    state = load_state(env / "data" / "games" / "sample.json")
    assert state.boundary.observed == {"a"}
    assert state.observations[0].node_id == "a"


def test_log_free_text_does_not_advance(env):
    result = CliRunner().invoke(cli, ["log", "sample", "took", "a", "tough", "fight"])
    assert result.exit_code == 0, result.output
    assert "Logged note" in result.output
    state = load_state(env / "data" / "games" / "sample.json")
    assert state.boundary.observed == set()
    assert state.observations[0].node_id is None
    assert state.observations[0].payload["text"] == "took a tough fight"


def test_log_accumulates_observations(env):
    runner = CliRunner()
    runner.invoke(cli, ["log", "sample", "a"])
    runner.invoke(cli, ["log", "sample", "b"])
    state = load_state(env / "data" / "games" / "sample.json")
    assert state.boundary.observed == {"a", "b"}
    assert len(state.observations) == 2


def test_status_after_log_lists_game(env):
    runner = CliRunner()
    runner.invoke(cli, ["log", "sample", "a"])
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0
    assert "sample" in result.output


def test_log_unknown_game_errors(env):
    result = CliRunner().invoke(cli, ["log", "nonexistent", "a"])
    assert result.exit_code != 0


# ---- resume -----------------------------------------------------------------


def _canned_summary(context_hash: str = "abc") -> Summary:
    return Summary(
        where_you_are="Dilapidated Temple",
        how_you_got_here="You cleared the outskirts.",
        why_youre_doing_this="To find the Mortal Blade.",
        explore_next=[
            Suggestion(hint="The western valley calls.", spoiler="Mortal Blade is there."),
            Suggestion(hint="Worth revisiting Hirata.", spoiler=None),
        ],
        next_boss=Suggestion(hint="A castle defender awaits.", spoiler="Genichiro Ashina"),
        completion="Main: ~25%",
        model="claude-opus-4-7",
        generated_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
        context_hash=context_hash,
    )


class _FakeClient:
    """Stands in for SynthesisClient — no API call."""
    def __init__(self, summary: Summary, *, model: str = "claude-opus-4-7"):
        self._summary = summary
        self.model = model
        self.called = 0

    def synthesize(self, envelope, *, precomputed_hash=None):
        self.called += 1
        s = self._summary
        if precomputed_hash is not None:
            s.context_hash = precomputed_hash
        return s


def test_resume_dry_run_prints_prompt_without_calling_api(env, monkeypatch):
    """--dry-run must not construct or call the synthesis client."""
    def boom(*a, **kw):
        raise AssertionError("SynthesisClient should not be constructed during --dry-run")

    monkeypatch.setattr("gamebuddy.cli.SynthesisClient", boom)
    result = CliRunner().invoke(cli, ["resume", "sample", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "<game_context>" in result.output
    assert "<player_observations>" in result.output


def test_resume_calls_synthesis_and_prints_sections(env, monkeypatch):
    fake = _FakeClient(_canned_summary())
    monkeypatch.setattr("gamebuddy.cli.SynthesisClient", lambda: fake)

    result = CliRunner().invoke(cli, ["resume", "sample"])
    assert result.exit_code == 0, result.output
    assert fake.called == 1
    assert "WHERE YOU ARE" in result.output
    assert "Dilapidated Temple" in result.output
    assert "EXPLORE NEXT" in result.output
    assert "NEXT BOSS" in result.output
    assert "COMPLETION" in result.output


def test_resume_hides_spoilers_by_default(env, monkeypatch):
    fake = _FakeClient(_canned_summary())
    monkeypatch.setattr("gamebuddy.cli.SynthesisClient", lambda: fake)

    result = CliRunner().invoke(cli, ["resume", "sample"])
    assert "[hidden — use --reveal]" in result.output
    assert "Genichiro Ashina" not in result.output
    assert "Mortal Blade is there." not in result.output


def test_resume_reveal_shows_spoilers(env, monkeypatch):
    fake = _FakeClient(_canned_summary())
    monkeypatch.setattr("gamebuddy.cli.SynthesisClient", lambda: fake)

    result = CliRunner().invoke(cli, ["resume", "sample", "--reveal"])
    assert "Genichiro Ashina" in result.output
    assert "Mortal Blade is there." in result.output
    assert "[hidden — use --reveal]" not in result.output


def test_resume_writes_synthesis_cache(env, monkeypatch):
    fake = _FakeClient(_canned_summary())
    monkeypatch.setattr("gamebuddy.cli.SynthesisClient", lambda: fake)

    CliRunner().invoke(cli, ["resume", "sample"])
    state = load_state(env / "data" / "games" / "sample.json")
    assert state.synthesis_cache is not None
    assert state.synthesis_cache.where_you_are == "Dilapidated Temple"


def test_resume_uses_cache_on_second_call(env, monkeypatch):
    fake = _FakeClient(_canned_summary())
    monkeypatch.setattr("gamebuddy.cli.SynthesisClient", lambda: fake)

    runner = CliRunner()
    runner.invoke(cli, ["resume", "sample"])
    assert fake.called == 1
    runner.invoke(cli, ["resume", "sample"])
    assert fake.called == 1, "second call should hit the cache, not the API"


def test_resume_invalidates_cache_after_log(env, monkeypatch):
    fake = _FakeClient(_canned_summary())
    monkeypatch.setattr("gamebuddy.cli.SynthesisClient", lambda: fake)

    runner = CliRunner()
    runner.invoke(cli, ["resume", "sample"])
    assert fake.called == 1
    runner.invoke(cli, ["log", "sample", "a"])  # observation invalidates cache
    runner.invoke(cli, ["resume", "sample"])
    assert fake.called == 2


def test_resume_unknown_game_errors(env, monkeypatch):
    monkeypatch.setattr(
        "gamebuddy.cli.SynthesisClient",
        lambda: (_ for _ in ()).throw(AssertionError("should not be reached")),
    )
    result = CliRunner().invoke(cli, ["resume", "nonexistent"])
    assert result.exit_code != 0


# ---- onboard ----------------------------------------------------------------


class _FakeOnboarder:
    """Stand-in for gamebuddy.cli.Onboarder during tests."""
    last_kwargs = None

    def __init__(self, **kwargs):
        _FakeOnboarder.last_kwargs = kwargs
        self._target = kwargs["target_dir"]

    def run(self):
        # Pretend we wrote one file
        f = self._target / "meta.md"
        f.write_text("ok", encoding="utf-8")
        return [f]


def test_onboard_refuses_when_target_has_files(tmp_path, monkeypatch):
    monkeypatch.setenv("GAMEBUDDY_GAMES_DIR", str(tmp_path / "games"))
    existing = tmp_path / "games" / "newgame"
    existing.mkdir(parents=True)
    (existing / "meta.md").write_text("existing", encoding="utf-8")

    monkeypatch.setattr("gamebuddy.cli.Onboarder", _FakeOnboarder)
    result = CliRunner().invoke(cli, ["onboard", "newgame"])
    assert result.exit_code != 0
    assert "already contains files" in result.output


def test_onboard_proceeds_with_force(tmp_path, monkeypatch):
    monkeypatch.setenv("GAMEBUDDY_GAMES_DIR", str(tmp_path / "games"))
    existing = tmp_path / "games" / "newgame"
    existing.mkdir(parents=True)
    (existing / "meta.md").write_text("existing", encoding="utf-8")

    monkeypatch.setattr("gamebuddy.cli.Onboarder", _FakeOnboarder)
    result = CliRunner().invoke(cli, ["onboard", "newgame", "--force"])
    assert result.exit_code == 0, result.output
    assert "Wrote 1 files" in result.output


def test_onboard_creates_target_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GAMEBUDDY_GAMES_DIR", str(tmp_path / "games"))
    monkeypatch.setattr("gamebuddy.cli.Onboarder", _FakeOnboarder)
    result = CliRunner().invoke(cli, ["onboard", "freshgame"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "games" / "freshgame").is_dir()
    assert _FakeOnboarder.last_kwargs["game_id"] == "freshgame"
