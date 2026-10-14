"""Scenarios: a tiny file logger (from tools/templates/mod_log_template.py). Writes to
Mods/BlueRabbit477/logs/scenarios.log and never raises.
"""
import datetime
import os

MOD_NAME = "scenarios"

# Matches tools/config.py's MODS_DIR + CREATOR, but this file runs inside the game's
# own Python (can't import our build-time config), so the path is written out in full.
LOG_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts",
                        "The Sims 4", "Mods", "BlueRabbit477", "logs")


def log(message, level="INFO"):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        line = "{} [{}] {}: {}\n".format(
            datetime.datetime.now().isoformat(timespec="seconds"), level, MOD_NAME, message)
        with open(os.path.join(LOG_DIR, MOD_NAME + ".log"), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def log_exception(context):
    try:
        import traceback
        log(context + "\n" + traceback.format_exc(), level="ERROR")
    except Exception:
        pass
