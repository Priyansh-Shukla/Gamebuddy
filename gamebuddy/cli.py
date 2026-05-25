"""GameBuddy CLI."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import click

from gamebuddy.context import load_game_context
from gamebuddy.paths import data_dir, games_dir, state_path
from gamebuddy.providers.manual import ManualProvider
from gamebuddy.schemas import SCHEMA_VERSION, Boundary, GameState
from gamebuddy.store import apply_observations, load_state, save_state


@click.group()
def cli() -> None:
    """Spoiler-safe session recall for singleplayer games."""


@cli.command()
def status() -> None:
    """List tracked games, oldest first."""
    games = data_dir() / "games"
    if not games.is_dir():
        click.echo("No tracked games yet. Use `gamebuddy log <game> <node-or-text>` to start.")
        return
    rows: list[tuple[str, datetime]] = []
    for f in sorted(games.glob("*.json")):
        try:
            state = load_state(f)
        except Exception as exc:
            click.echo(f"  {f.name}: <unreadable: {exc}>", err=True)
            continue
        rows.append((state.game_id, state.last_synced))
    if not rows:
        click.echo("No tracked games yet.")
        return
    rows.sort(key=lambda r: r[1])
    now = datetime.now(tz=timezone.utc)
    for gid, ts in rows:
        click.echo(f"  {gid:20s}  {ts.isoformat()}  ({_humanize(now - ts)} ago)")


@cli.command()
@click.argument("game")
@click.argument("text", nargs=-1, required=True)
def log(game: str, text: tuple[str, ...]) -> None:
    """Add a manual annotation for GAME.

    If TEXT matches a known node id, advances the observed boundary; otherwise
    it's a free-text note.
    """
    context = load_game_context(games_dir(), game)
    joined = " ".join(text).strip()
    observations = ManualProvider(context.dag, joined).collect()

    path = state_path(game)
    state = _load_or_init(path, game)
    apply_observations(state, observations)
    save_state(state, path)

    obs = observations[0]
    if obs.node_id is not None:
        click.echo(
            f"Logged node `{obs.node_id}` for {game}. "
            f"Observed: {sorted(state.boundary.observed)}"
        )
    else:
        click.echo(f"Logged note for {game}: {joined!r}")


def _load_or_init(path: Path, game_id: str) -> GameState:
    if path.exists():
        return load_state(path)
    return GameState(
        schema_version=SCHEMA_VERSION,
        game_id=game_id,
        last_synced=datetime.now(tz=timezone.utc),
        boundary=Boundary(),
    )


def _humanize(td: timedelta) -> str:
    s = int(td.total_seconds())
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"
