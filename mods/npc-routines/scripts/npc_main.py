"""NPC Routines phase 1 (on-lot only) - game layer. See PLAN.md for the design and
what's confirmed vs. guessed. The scheduling/data logic lives in npc_routine.py and is
pytest-tested; this file is the thin, defensive glue to the actual game.

Cheats:
  bluerabbit477.npc.on [sim_id]      - turn on routine mode for a sim (default: selected sim)
  bluerabbit477.npc.off [sim_id]
  bluerabbit477.routine.add <days> <start_hour> <length_hours> <activity> [sim_id]
      days is comma-separated day names or numbers, e.g. "mon,wed,fri" or "1,3,5"
      (0=Sunday..6=Saturday, matching the game's own clock - see npc_routine.py)
  bluerabbit477.routine.show [sim_id]
  bluerabbit477.routine.clear [sim_id]
  bluerabbit477.npc.tick                  - run the hourly check now, print what it decided
  bluerabbit477.npc.find <text>           - list real interaction names containing <text>
  bluerabbit477.npc.clubs <text>          - list club activities containing <text> and what they use
  bluerabbit477.npc.try <activity|name> [sim_id] - push it on the sim now, print the result

Everything that touches real tuning/interaction names (ACTIVITY_AFFORDANCES below) is a
best guess - there was no running game tonight to check real affordance tuning names
against. If an activity's affordance can't be resolved, we log it and skip that hour;
we never guess our way into pushing something broken.
"""
import json
import os

import alarms
import services
import sims4.commands
import zone as zone_module
from date_and_time import create_time_span
from interactions.context import InteractionContext
from interactions.priority import Priority
from server_commands.argument_helpers import OptionalSimInfoParam, get_optional_target
from sims4.resources import Types

import npc_log
from npc_routine import RoutineEntry, RoutineStore, DAY_NAMES

_ROUTINES_PATH = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts",
                               "The Sims 4", "Mods", "BlueRabbit477", "data", "npc_routines.json")

_store = RoutineStore()
_npc_mode_sim_ids = set()
_loaded = False
_alarm_handle = None

# Real interaction tuning names, confirmed in-game (2026-10-09): workout, chess, jog and
# autonomous_bookshelf_read_picker started; easel_Craft_Autonomously is what the easel offers.
# Tried in order: the first one that exists and has a target on this lot is pushed.
# Pushed at Priority.Low so a real need or the player can always pre-empt it.
ACTIVITY_AFFORDANCES = {
    "workout": ("treadmill_Workout", "generic_TreadmillWorkout"),
    # The easel_Craft_Autonomously* ones need an inspired-type buff ("doesn't have any buff in
    # whitelist", in-game 2026-10-09); easel_StartCrafting is the player's own "Paint..." choice.
    "paint": ("easel_Craft_Autonomously", "easel_StartCrafting"),
    "read": ("autonomous_bookshelf_read_picker", "book_read"),
    "chess": ("Chess_PonderMoves", "chess_ponder_moves"),
    "jog": ("terrain-jog_Autonomous", "terrain-jog"),
}

# Fallback when none of the names above work for an object (in-game: the easel and
# bookshelf offered none of them): look at the nearest object whose name contains one of
# the hints, and try its own interactions whose names contain one of the keywords.
ACTIVITY_OBJECTS = {
    "workout": (("treadmill",), ("workout",)),
    "paint": (("easel",), ("paint", "craft_autonomously")),
    "read": (("bookshelf", "book"), ("read",)),
    "chess": (("chess",), ("chess", "ponder")),
}

# Club activities (ClubInteractionGroup tuning) already say which interactions count as
# e.g. "Paint" - including club-activity mods. Matched by the group's tuning name.
ACTIVITY_CLUB_HINTS = {
    "workout": ("workout", "fitness", "exercise"),
    "paint": ("paint",),
    "read": ("read",),
    "chess": ("chess",),
    "jog": ("jog",),
}

_affordances_by_name = None  # lower-case tuning name -> interaction class, built on first use


def _affordance_by_name(name):
    # InstanceManager.get(name) hashes the name into a resource key, which doesn't match
    # EA's instance ids (in-game: get('terrain-jog') returned None although npc.find listed
    # it). So look names up in the manager's loaded classes instead.
    global _affordances_by_name
    if _affordances_by_name is None:
        types = services.get_instance_manager(Types.INTERACTION).types
        _affordances_by_name = {cls.__name__.lower(): cls for cls in types.values()}
    return _affordances_by_name.get(name.lower())


def _club_groups(text):
    """Club activity groups whose tuning name contains `text`, with their interactions."""
    manager = services.get_instance_manager(Types.CLUB_INTERACTION_GROUP)
    found = []
    for group in manager.types.values():
        if text.lower() not in group.__name__.lower():
            continue
        affordances = set(getattr(group, "affordances", ()) or ())
        for affordance_list in getattr(group, "affordance_lists", ()) or ():
            affordances.update(affordance_list)
        found.append((group.__name__, sorted(affordances, key=lambda a: a.__name__)))
    return sorted(found)


def _push_from_club_groups(sim, activity, report):
    affordances = []
    for hint in ACTIVITY_CLUB_HINTS.get(activity, ()):
        for group_name, group_affordances in _club_groups(hint):
            npc_log.log("  club activity {} uses: {}".format(group_name, [a.__name__ for a in group_affordances]))
            affordances.extend(a for a in group_affordances if a not in affordances)
    if not affordances:
        return False
    affordances.sort(key=lambda a: _candidate_order(a.__name__))
    _say(report, "  clubs: trying {} interactions from club activities".format(len(affordances)))
    for affordance in affordances:
        try:
            target = _find_target(sim, affordance)
            if target is None:
                continue
            context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.Low)
            result = sim.push_super_affordance(affordance, target, context)
            _say(report, "  {} on {}: result={!r}".format(affordance.__name__, target, result))
            if result:
                return True
        except Exception:
            npc_log.log_exception("pushing club interaction {}".format(affordance.__name__))
    return False


def _find_target(sim, affordance):
    """The sim itself for terrain interactions (jogging), otherwise the nearest object on
    the lot that offers this interaction (treadmill, easel, book, chess table)."""
    if affordance.__name__.lower().startswith("terrain"):
        # In-game, targeting the terrain object was refused with "Actor must match Object":
        # these interactions target the sim doing them.
        return sim
    best, best_distance = None, None
    for obj in services.object_manager().valid_objects():
        if obj is sim or not hasattr(obj, "super_affordances"):
            continue
        try:
            if affordance not in obj.super_affordances():
                continue
            distance = (obj.position - sim.position).magnitude_squared()
        except Exception:
            continue
        if best is None or distance < best_distance:
            best, best_distance = obj, distance
    return best


# Which sims are in NPC mode is saved too, so it survives restarting the game.
_NPC_MODE_PATH = os.path.join(os.path.dirname(_ROUTINES_PATH), "npc_mode.json")


def _ensure_loaded():
    global _loaded
    if not _loaded:
        _store.load(_ROUTINES_PATH)
        try:
            with open(_NPC_MODE_PATH, encoding="utf-8") as f:
                _npc_mode_sim_ids.update(int(i) for i in json.load(f))
        except (OSError, ValueError):
            pass
        _loaded = True


def _save():
    try:
        os.makedirs(os.path.dirname(_ROUTINES_PATH), exist_ok=True)
        _store.save(_ROUTINES_PATH)
    except Exception:
        npc_log.log_exception("saving routines")


def _save_npc_mode():
    try:
        os.makedirs(os.path.dirname(_NPC_MODE_PATH), exist_ok=True)
        with open(_NPC_MODE_PATH, "w", encoding="utf-8") as f:
            json.dump(sorted(_npc_mode_sim_ids), f)
    except Exception:
        npc_log.log_exception("saving NPC mode")


def _parse_days(text):
    days = []
    for part in text.split(","):
        part = part.strip().lower()
        if not part:
            continue
        if part.isdigit():
            days.append(int(part))
        elif part[:3] in DAY_NAMES:
            days.append(DAY_NAMES.index(part[:3]))
        else:
            raise ValueError("unrecognised day {!r} (use a number 0-6 or a name like 'mon')".format(part))
    return days


def _resolve_sim_id(opt_sim, _connection):
    # .sim_id is confirmed real (sims/sim_info.py uses it throughout, e.g. its own __repr__).
    # target_type must be passed explicitly: get_optional_target() only resolves "no id given"
    # to the right kind of object via this argument - it does NOT look at the caller's own
    # OptionalSimInfoParam type annotation, so without this it would silently fall back to
    # OptionalTargetParam's default (a Sim, not a SimInfo - confirmed by reading both classes).
    sim_info = get_optional_target(opt_sim, _connection, target_type=OptionalSimInfoParam)
    return sim_info.sim_id if sim_info is not None else None


def _say(report, message, level="INFO"):
    npc_log.log(message, level=level)
    if report is not None:
        report(message)


def _push_activity(sim, activity, report=None):
    """Tries each interaction name for `activity` (a routine key, or from npc.try a raw
    interaction name) until the game accepts one. Returns True if one was pushed."""
    for affordance_name in ACTIVITY_AFFORDANCES.get(activity, (activity,)):
        try:
            affordance = _affordance_by_name(affordance_name)
            if affordance is None:
                _say(report, "  {}: no interaction with this name".format(affordance_name), level="WARN")
                continue
            target = _find_target(sim, affordance)
            if target is None:
                _say(report, "  {}: nothing on this lot offers it".format(affordance_name), level="WARN")
                continue
            context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.Low)
            result = sim.push_super_affordance(affordance, target, context)
            # Falsy with a reason when the game refuses the push, so log what it said.
            _say(report, "  {} on {}: result={!r}".format(affordance_name, target, result))
            if result:
                return True
        except Exception:
            npc_log.log_exception("pushing {!r} for activity {!r} on sim {}".format(
                affordance_name, activity, getattr(sim, "id", "?")))
            if report is not None:
                report("  {}: error - see the log".format(affordance_name))
    if activity in ACTIVITY_CLUB_HINTS and _push_from_club_groups(sim, activity, report):
        return True
    if activity in ACTIVITY_OBJECTS and _push_from_nearby_object(sim, activity, report):
        return True
    _say(report, "could not start {!r} for sim {}".format(activity, sim.id), level="WARN")
    return False


def _nearby_objects(sim, hints, limit=3):
    found = []
    for obj in services.object_manager().valid_objects():
        if obj is sim:
            continue
        label = str(obj).lower()
        if not any(h in label for h in hints):
            continue
        try:
            found.append(((obj.position - sim.position).magnitude_squared(), obj))
        except Exception:
            continue
    found.sort(key=lambda pair: pair[0])
    return [obj for _, obj in found[:limit]]


def _candidate_order(name):
    # Autonomous variants need no menu choice; picker-style ones may open a menu, so last.
    lower = name.lower()
    return (0 if "autonom" in lower else 2 if "picker" in lower else 1, lower)


def _push_from_nearby_object(sim, activity, report):
    hints, keywords = ACTIVITY_OBJECTS[activity]
    objects = _nearby_objects(sim, hints)
    if not objects:
        _say(report, "  fallback: no object with {} in its name on this lot".format(hints), level="WARN")
        return False
    for obj in objects:
        try:
            offered = list(obj.super_affordances())
        except Exception:
            npc_log.log_exception("listing interactions on {}".format(obj))
            continue
        # The full list goes to the log so the right name can be added to ACTIVITY_AFFORDANCES.
        npc_log.log("  {} offers {} interactions: {}".format(obj, len(offered), sorted(a.__name__ for a in offered)))
        candidates = sorted((a for a in offered if any(k in a.__name__.lower() for k in keywords)),
                            key=lambda a: _candidate_order(a.__name__))
        _say(report, "  fallback: {} has {} matching: {}".format(obj, len(candidates), [a.__name__ for a in candidates]))
        for affordance in candidates:
            try:
                context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.Low)
                result = sim.push_super_affordance(affordance, obj, context)
                _say(report, "  {} on {}: result={!r}".format(affordance.__name__, obj, result))
                if result:
                    return True
            except Exception:
                npc_log.log_exception("pushing {} on {}".format(affordance.__name__, obj))
    return False


def _run_tick(report=None):
    _ensure_loaded()
    if not _npc_mode_sim_ids:
        _say(report, "tick: no sims in NPC mode")
        return
    now = services.time_service().sim_timeline.now
    day, hour = now.day(), now.hour()
    _say(report, "tick: day={} ({}) hour={} npc_sims={}".format(day, DAY_NAMES[day], hour, sorted(_npc_mode_sim_ids)))
    sim_info_manager = services.sim_info_manager()
    for sim_id in list(_npc_mode_sim_ids):
        routine = _store.get(sim_id)
        activity = routine.due_activity(day, hour)
        if activity is None:
            _say(report, "  sim {}: nothing due ({} routine entries)".format(sim_id, len(routine.entries)))
            continue
        sim_info = sim_info_manager.get(sim_id)
        sim = sim_info.get_sim_instance() if sim_info is not None else None
        if sim is None:
            # Not on the loaded lot right now - phase 3 territory.
            _say(report, "  sim {}: {!r} due but the sim isn't on this lot".format(sim_id, activity))
            continue
        _push_activity(sim, activity, report)


def _tick(*_args, **_kwargs):
    try:
        _run_tick()
    except Exception:
        npc_log.log_exception("npc routine tick")


def _start_alarm(zone):
    # Re-created on every zone load rather than guarded to "once": an alarm's owner is
    # held by weakref (alarms.py), so an alarm owned by a previous zone may already be
    # dead by the time we get here after a zone transition. Cancelling unconditionally
    # and re-creating, owned by the current zone, avoids having to reason about exactly
    # when that weakref dies.
    global _alarm_handle
    if _alarm_handle is not None:
        try:
            alarms.cancel_alarm(_alarm_handle)
        except Exception:
            pass
        _alarm_handle = None
    try:
        # The time service isn't up yet at module-import time (game startup, before any
        # save is loaded) - add_alarm() would silently no-op then. This must run on zone
        # load instead, same hook point and pattern as neighborhood-stories-rebalance.
        _alarm_handle = alarms.add_alarm(zone, create_time_span(hours=1), _tick, repeating=True)
        if _alarm_handle is None:
            npc_log.log("add_alarm returned None - time service likely not ready yet", level="WARN")
        else:
            npc_log.log("hourly alarm (re)started")
    except Exception:
        npc_log.log_exception("starting the hourly alarm")


_original_on_loading_screen_animation_finished = zone_module.Zone.on_loading_screen_animation_finished


def _patched_on_loading_screen_animation_finished(self, *args, **kwargs):
    result = _original_on_loading_screen_animation_finished(self, *args, **kwargs)
    try:
        _ensure_loaded()
        _start_alarm(self)
    except Exception:
        npc_log.log_exception("on_loading_screen_animation_finished hook")
    return result


zone_module.Zone.on_loading_screen_animation_finished = _patched_on_loading_screen_animation_finished


@sims4.commands.Command("bluerabbit477.npc.on", command_type=sims4.commands.CommandType.Live)
def npc_on(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_id = _resolve_sim_id(opt_sim, _connection)
    if sim_id is None:
        output("No sim found (select one or pass a sim id).")
        return
    _ensure_loaded()
    _npc_mode_sim_ids.add(sim_id)
    _save_npc_mode()
    output("NPC routine mode on for sim {}.".format(sim_id))
    npc_log.log("npc.on sim {} (routine entries: {})".format(sim_id, len(_store.get(sim_id).entries)))


@sims4.commands.Command("bluerabbit477.npc.off", command_type=sims4.commands.CommandType.Live)
def npc_off(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_id = _resolve_sim_id(opt_sim, _connection)
    if sim_id is None:
        output("No sim found (select one or pass a sim id).")
        return
    _ensure_loaded()
    _npc_mode_sim_ids.discard(sim_id)
    _save_npc_mode()
    output("NPC routine mode off for sim {}.".format(sim_id))
    npc_log.log("npc.off sim {}".format(sim_id))


@sims4.commands.Command("bluerabbit477.routine.add", command_type=sims4.commands.CommandType.Live)
def routine_add(days: str, start_hour: int, length_hours: int, activity: str,
                opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_id = _resolve_sim_id(opt_sim, _connection)
    if sim_id is None:
        output("No sim found (select one or pass a sim id).")
        return
    try:
        day_list = _parse_days(days)
        entry = RoutineEntry(day_list, start_hour, length_hours, activity)
    except ValueError as e:
        output("Could not add that entry: {}".format(e))
        npc_log.log("routine.add rejected {!r} {} {} {!r}: {}".format(days, start_hour, length_hours, activity, e), level="WARN")
        return
    _ensure_loaded()
    _store.get(sim_id).add(entry)
    _save()
    output("Added {} for sim {}.".format(entry, sim_id))
    npc_log.log("routine.add sim {}: {}".format(sim_id, entry))


@sims4.commands.Command("bluerabbit477.routine.show", command_type=sims4.commands.CommandType.Live)
def routine_show(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_id = _resolve_sim_id(opt_sim, _connection)
    if sim_id is None:
        output("No sim found (select one or pass a sim id).")
        return
    _ensure_loaded()
    routine = _store.get(sim_id)
    if not routine.entries:
        output("Sim {} has no routine entries. NPC mode is {}.".format(
            sim_id, "ON" if sim_id in _npc_mode_sim_ids else "off"))
        return
    output("Routine for sim {} (NPC mode {}):".format(sim_id, "ON" if sim_id in _npc_mode_sim_ids else "off"))
    for entry in routine.entries:
        output("  {}".format(entry))


@sims4.commands.Command("bluerabbit477.npc.tick", command_type=sims4.commands.CommandType.Live)
def npc_tick(_connection=None):
    """Runs the hourly check right now and prints what it decided."""
    output = sims4.commands.CheatOutput(_connection)
    try:
        _run_tick(report=output)
    except Exception:
        npc_log.log_exception("npc.tick")
        output("npc.tick failed - see the log.")


@sims4.commands.Command("bluerabbit477.npc.find", command_type=sims4.commands.CommandType.Live)
def npc_find(text: str, _connection=None):
    """Lists interaction tuning names containing `text`, to find the real names for
    ACTIVITY_AFFORDANCES. Also written to the log, since the console only shows so much."""
    output = sims4.commands.CheatOutput(_connection)
    try:
        needle = text.lower()
        names = sorted(cls.__name__ for cls in services.get_instance_manager(Types.INTERACTION).types.values()
                       if needle in cls.__name__.lower())
    except Exception:
        npc_log.log_exception("npc.find")
        output("npc.find failed - see the log.")
        return
    npc_log.log("npc.find {!r}: {} matches: {}".format(text, len(names), names))
    output("{} interactions contain {!r}{}".format(len(names), text, " (first 40 shown; all are in the log)" if len(names) > 40 else ""))
    for name in names[:40]:
        output("  " + name)


@sims4.commands.Command("bluerabbit477.npc.clubs", command_type=sims4.commands.CommandType.Live)
def npc_clubs(text: str, _connection=None):
    """Lists club activities whose tuning name contains `text`, and the interactions each uses."""
    output = sims4.commands.CheatOutput(_connection)
    try:
        groups = _club_groups(text)
    except Exception:
        npc_log.log_exception("npc.clubs")
        output("npc.clubs failed - see the log.")
        return
    output("{} club activities contain {!r}".format(len(groups), text))
    for group_name, affordances in groups:
        names = [a.__name__ for a in affordances]
        npc_log.log("npc.clubs {}: {}".format(group_name, names))
        output("  {}: {}".format(group_name, ", ".join(names[:8]) + (" ..." if len(names) > 8 else "")))


@sims4.commands.Command("bluerabbit477.npc.try", command_type=sims4.commands.CommandType.Live)
def npc_try(activity: str, opt_sim: OptionalSimInfoParam = None, _connection=None):
    """Pushes an activity key (jog, paint, ...) or a raw interaction name on the selected sim
    right now, with no target object, and prints what the game said."""
    output = sims4.commands.CheatOutput(_connection)
    sim_info = get_optional_target(opt_sim, _connection, target_type=OptionalSimInfoParam)
    sim = sim_info.get_sim_instance() if sim_info is not None else None
    if sim is None:
        output("No sim on this lot (select one who is here).")
        return
    _push_activity(sim, activity, report=output)


@sims4.commands.Command("bluerabbit477.routine.clear", command_type=sims4.commands.CommandType.Live)
def routine_clear(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_id = _resolve_sim_id(opt_sim, _connection)
    if sim_id is None:
        output("No sim found (select one or pass a sim id).")
        return
    _ensure_loaded()
    _store.get(sim_id).clear()
    _save()
    output("Cleared routine for sim {}.".format(sim_id))
    npc_log.log("routine.clear sim {}".format(sim_id))
