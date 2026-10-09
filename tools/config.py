"""Shared paths and settings for the tools in this folder.

Override any path with an environment variable of the same name if the
defaults don't match this machine.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Prefix put on every built file so our mods are easy to spot in the Mods folder.
CREATOR = os.environ.get("S4_CREATOR", "BlueRabbit477")


def _game_dir():
    if os.environ.get("S4_GAME_DIR"):
        return Path(os.environ["S4_GAME_DIR"])
    try:
        import winreg
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Maxis\The Sims 4",
                                     0, winreg.KEY_READ | view)
                return Path(winreg.QueryValueEx(key, "Install Dir")[0])
            except OSError:
                continue
    except ImportError:
        pass
    return Path(r"C:\Program Files\EA Games\The Sims 4")


GAME_DIR = _game_dir()
MODS_DIR = Path(os.environ.get(
    "S4_MODS_DIR",
    Path.home() / "Documents" / "Electronic Arts" / "The Sims 4" / "Mods"))

# EA's compiled game scripts.
EA_SCRIPT_ZIPS = [
    GAME_DIR / "Data" / "Simulation" / "Gameplay" / "base.zip",
    GAME_DIR / "Data" / "Simulation" / "Gameplay" / "core.zip",
    GAME_DIR / "Data" / "Simulation" / "Gameplay" / "simulation.zip",
    GAME_DIR / "Game" / "Bin" / "Python" / "generated.zip",
]

EA_SCRIPTS_DIR = ROOT / "ea_scripts"
BUILD_DIR = ROOT / "build"
MODS_SRC_DIR = ROOT / "mods"
