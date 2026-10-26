"""Make each mod's scripts/ importable so `python -m pytest` works from the repo root.

tools/build.py puts every mod's scripts/ on PYTHONPATH when it runs the tests; this does
the same for running pytest by hand.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

for scripts in sorted((ROOT / "mods").glob("*/scripts")):
    if scripts.is_dir() and str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
