import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from gamebuddy.cli import cli
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
