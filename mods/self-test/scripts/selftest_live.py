"""Self-test harness - live game helpers.

Everything that touches the running game lives here (and in selftest_checks.py). The
helpers are deliberately small and defensive: the checks in selftest_checks.py must be
able to say "I couldn't read that" instead of taking the game down.

Paths match the other mods: data in Mods/HouseRules/data/, logs in
Mods/HouseRules/logs/ (inside the user's The Sims 4 folder).
"""
import datetime
import glob
import importlib
import os
import sys
import time

from selftest_core import CheckFailed, SkipCheck

# Captured when the game imports this mod, i.e. at startup, so "since start" means
# "this session" for log lines and for lastException files.
START_TIME = time.time()
START_STAMP = datetime.datetime.now().isoformat(timespec="seconds")

DOCS_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts", "The Sims 4")
MOD_ROOT = os.path.join(DOCS_DIR, "Mods", "HouseRules")
DATA_DIR = os.path.join(MOD_ROOT, "data")
LOGS_DIR = os.path.join(MOD_ROOT, "logs")
SCENARIO_DIR = os.path.join(MOD_ROOT, "scenarios")


# --- Loading ---------------------------------------------------------------------------
def module_loaded(name):
    return name in sys.modules


def require_module(name):
    loaded = sys.modules.get(name)
    if loaded is None:
        raise CheckFailed("module {} is not loaded (is its mod installed?)".format(name))
    return loaded


def import_optional(name):
    try:
        return importlib.import_module(name)
    except Exception as e:
        raise CheckFailed("could not import {}: {}: {}".format(name, type(e).__name__, e))


def require_modules(*names):
    missing = [name for name in names if name not in sys.modules]
    if missing:
        raise CheckFailed("not loaded: {} (is the mod installed?)".format(", ".join(missing)))
    return [sys.modules[name] for name in names]


# --- Game state ------------------------------------------------------------------------
def active_sim():
    try:
        import services
        return services.active_sim_info()
    except Exception as e:
        raise CheckFailed("could not ask the game for the active sim: {}: {}".format(type(e).__name__, e))


def require_sim():
    sim_info = active_sim()
    if sim_info is None:
        raise SkipCheck("no selected sim - load a save and select a sim first")
    return sim_info


def active_household():
    try:
        import services
        return services.active_household()
    except Exception as e:
        raise CheckFailed("could not ask the game for the active household: {}: {}".format(
            type(e).__name__, e))


def require_household():
    household = active_household()
    if household is None:
        raise SkipCheck("no active household - load a save first")
    return household


def sim_name(sim_info):
    if sim_info is None:
        return "?"
    return "{} {}".format(getattr(sim_info, "first_name", ""), getattr(sim_info, "last_name", "")).strip() \
        or str(getattr(sim_info, "sim_id", "?"))


def sim_id(sim_info):
    return getattr(sim_info, "sim_id", None)


def current_zone():
    try:
        import services
        return services.current_zone()
    except Exception:
        return None


def sim_now():
    try:
        import services
        return services.time_service().sim_now
    except Exception:
        return None


def run_command(command_line):
    """Run a real console command, exactly as typing it would.

    This is how the action checks press the game's own buttons: they call the same
    command the menu/phone/cheat console calls, then check what changed. Commands are
    Live (not cheat-only), so they run even when cheats are off.
    """
    try:
        import sims4.commands
    except Exception as e:
        raise CheckFailed("could not reach the game's command system: {}: {}".format(
            type(e).__name__, e))
    try:
        sims4.commands.execute(command_line, 0)
    except Exception as e:
        raise CheckFailed("command {!r} failed: {}: {}".format(
            command_line, type(e).__name__, e))
    return command_line


def log_mark(mod):
    """A position in a mod log, so a check can look only at what an action just wrote."""
    return len(log_text_since_start(mod))


def log_since(mark, mod):
    return log_text_since_start(mod)[mark:]


def wait_for(predicate, timeout=1.5, interval=0.05):
    """Poll until predicate() is true (commands can take a moment to land), then report."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


# --- Tuning ----------------------------------------------------------------------------
def tuning_instance(resource_type, identifier):
    try:
        import services
        import sims4.resources
        manager = services.get_instance_manager(getattr(sims4.resources.Types, resource_type))
        return manager.get(identifier)
    except Exception as e:
        raise CheckFailed("could not look up {} {}: {}: {}".format(
            resource_type, identifier, type(e).__name__, e))


def require_tuning(resource_type, identifier, what):
    instance = tuning_instance(resource_type, identifier)
    if instance is None:
        raise CheckFailed("{} tuning is not loaded".format(what))
    return instance


# --- Files: data, logs, last exceptions ------------------------------------------------
def ensure_dir(path, what):
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".self_test_probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        with open(probe, encoding="utf-8") as f:
            text = f.read()
        os.remove(probe)
    except Exception as e:
        raise CheckFailed("{} ({}) is not writable: {}: {}".format(path, what, type(e).__name__, e))
    if text != "ok":
        raise CheckFailed("{} ({}) did not read back what was written".format(path, what))
    return path


def log_path(mod):
    return os.path.join(LOGS_DIR, mod + ".log")


def log_text_since_start(mod):
    path = log_path(mod)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        raise CheckFailed("could not read {}: {}: {}".format(path, type(e).__name__, e))
    return [line.rstrip() for line in lines if line[:19] >= START_STAMP]


def logged_since_start(mod, needle):
    return any(needle in line for line in log_text_since_start(mod))


def logged_any_session(mod, needle):
    """True when a log line contains `needle`. Used for install markers: the line is only
    written when the hook is installed, and the last one for a hook is its latest attempt.
    (Script mods load in an order we don't control, so 'since self-test imported' can't be
    used for lines written during startup.)"""
    path = log_path(mod)
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return any(needle in line for line in f)
    except Exception as e:
        raise CheckFailed("could not read {}: {}: {}".format(path, type(e).__name__, e))


def require_logged(mod, needle, what):
    if not logged_any_session(mod, needle):
        raise CheckFailed("{} was not logged by {} (see {})".format(what, mod, log_path(mod)))
    return "logged"


def error_log_lines_since_start(exclude=("self-test",)):
    problems = []
    try:
        names = sorted(os.listdir(LOGS_DIR))
    except OSError:
        return problems
    for name in names:
        if not name.endswith(".log") or name[:-4] in exclude:
            continue
        for line in log_text_since_start(name[:-4]):
            if "[ERROR]" in line:
                problems.append(line)
    return problems


def new_last_exceptions():
    """lastException*.txt files written since the game started."""
    found = []
    for path in glob.glob(os.path.join(DOCS_DIR, "lastException*.txt")):
        try:
            if os.path.getmtime(path) >= START_TIME - 2:
                found.append(path)
        except OSError:
            pass
    return sorted(found)


def first_line(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip():
                    return line.strip()[:200]
    except Exception:
        pass
    return "(could not read it)"


# --- Game objects used by several checks ------------------------------------------------
def traits_of(sim_info):
    try:
        return [t.__name__ for t in sim_info.trait_tracker.equipped_traits]
    except Exception:
        try:
            return [t.__name__ for t in sim_info.trait_tracker.get_traits()]
        except Exception:
            return []


def skill_level(sim_info, skill_type):
    """Read-only: add=False, so a check can never level a skill up."""
    try:
        stat = sim_info.get_statistic(skill_type, add=False)
        return int(stat.get_user_value()) if stat is not None else 0
    except Exception:
        return 0


def find_skill(name):
    """The game's skill statistic class whose name ends with `name` (adult skill preferred)."""
    import services
    import sims4.resources
    wanted = name.lower()
    best = None
    for cls in services.get_instance_manager(sims4.resources.Types.STATISTIC).types.values():
        lowered = cls.__name__.lower()
        if not lowered.endswith("_" + wanted) or "skill" not in lowered:
            continue
        if best is None or ("adult" in lowered and "adult" not in best.__name__.lower()):
            best = cls
    return best


def read_json(path, default=None):
    import json
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            if text:
                return json.loads(text)
    except Exception:
        pass
    return default


def save_json(path, data):
    import json
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception as e:
        raise CheckFailed("could not write {}: {}: {}".format(path, type(e).__name__, e))
