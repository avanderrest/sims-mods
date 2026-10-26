"""Template for a tiny per-mod file logger. Not built or shipped itself.

Every mod's scripts/ folder gets loaded into one shared Python namespace (all the
.ts4script files sit side by side in Mods/HouseRules/), so two mods both naming a
module "log.py" would collide - whichever loads first wins and the other mod's
logging silently breaks. The fix: copy this file into each mod as scripts/<mod>_log.py
(unique name) and set MOD_NAME below to that mod's folder name.

Logging must never be able to crash the game, so every function here swallows its
own errors.
"""
import datetime
import os

MOD_NAME = "template"  # change to the mod's folder name in mods/, e.g. "hard-mode"

# Matches tools/config.py's MODS_DIR + CREATOR, but this file runs inside the game's
# own Python (can't import our build-time config), so the path is written out in full.
LOG_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts",
                        "The Sims 4", "Mods", "HouseRules", "logs")


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
