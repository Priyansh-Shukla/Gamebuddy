"""Build three Sekiro player-state checkpoints for the demo.

Runs `gamebuddy log` for each node in three growing phases, snapshotting the
JSON between phases so we can render each as a separate map/journal/envelope.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKING = ROOT / "demo" / "states" / "working"
SNAPSHOTS = ROOT / "demo" / "states"

os.environ["GAMEBUDDY_DATA_DIR"] = str(WORKING)
os.environ["GAMEBUDDY_GAMES_DIR"] = str(ROOT / "games")

if WORKING.exists():
    shutil.rmtree(WORKING)

from gamebuddy.cli import cli

PHASES = {
    "early": [
        "prologue_genichiro",
        "lose_arm",
        "kusabimaru",
        "shinobi_prosthetic",
        "ashina_outskirts",
        "chained_ogre",
    ],
    "mid": [
        "gyoubu_oniwa",
        "hirata_estate",
        "juzou_the_drunkard",
        "lady_butterfly",
        "ashina_castle",
        "blazing_bull",
        "genichiro_ashina",
        "mushin_arts",
    ],
    "late": [
        "senpou_temple",
        "armored_warrior",
        "folding_screen_monkeys",
        "mortal_blade",
        "sunken_valley",
        "snake_eyes_shirahagi",
        "long_arm_centipede_giraffe",
        "ashina_depths",
        "mibu_village",
        "corrupted_monk",
        "fountainhead_palace",
        "true_corrupted_monk",
        "divine_dragon",
        "owl_iron_code_choice",
    ],
}

for phase, nodes in PHASES.items():
    print(f"\n=== Phase: {phase} ===")
    for node in nodes:
        cli(["log", "sekiro", node], standalone_mode=False)
    snap = SNAPSHOTS / f"sekiro-{phase}.json"
    shutil.copy(WORKING / "games" / "sekiro.json", snap)
    print(f"  -> snapshot: {snap.relative_to(ROOT)}")

print("\nDone.")
