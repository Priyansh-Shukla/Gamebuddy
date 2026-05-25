"""Runtime paths.

Defaults are project-relative (`./games`, `./data`) — fine for a personal tool
run from the repo. `GAMEBUDDY_GAMES_DIR` and `GAMEBUDDY_DATA_DIR` override.
"""
from __future__ import annotations

import os
from pathlib import Path


def games_dir() -> Path:
    return Path(os.environ.get("GAMEBUDDY_GAMES_DIR", "games"))


def data_dir() -> Path:
    return Path(os.environ.get("GAMEBUDDY_DATA_DIR", "data"))


def state_path(game_id: str) -> Path:
    return data_dir() / "games" / f"{game_id}.json"
