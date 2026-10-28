"""NPC Routines phase 1 (on-lot only) - game layer. The design is described in README.md;
some affordance names are still guesses. The scheduling/data logic lives in npc_routine.py
and is pytest-tested; this file is the thin, defensive glue to the actual game.

Cheats:
  houserules.npc.on [sim_id]      - turn on routine mode for a sim (default: selected sim)
  houserules.npc.off [sim_id]
  houserules.routine.add <days> <start_hour> <length_hours> <activity> [sim_id]
      days is comma-separated day names or numbers, e.g. "mon,wed,fri" or "1,3,5"
      (0=Sunday..6=Saturday, matching the game's own clock - see npc_routine.py)
  houserules.routine.show [sim_id]
  houserules.routine.clear [sim_id]
  houserules.npc.tick                  - run the hourly check now, print what it decided
  houserules.npc.actions [sim_id]      - what the LLM is offered for this sim right now
  houserules.npc.checks <text> [sim_id] - why an interaction is (not) offered, filter by filter
  houserules.npc.find <text>           - list real interaction names containing <text>
  houserules.npc.clubs <text>          - list club activities containing <text> and what they use
  houserules.npc.try <activity|name> [sim_id] - push it on the sim now, print the result
  houserules.npc.rules_list            - rule files in Mods/HouseRules/data/rules
  houserules.npc.rules_load <file> [sim|all] - load a JSON rule routine (the main way to run)
  houserules.npc.rules_show [sim_id]   - the rules assigned to a sim, and what would fire now
  houserules.npc.rules_test [sim_id]   - evaluate the rules without doing anything
  houserules.npc.rules_clear [sim|all] - remove the rules (back to routine/LLM)

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
from clock import ClockSpeedMode, interval_in_real_seconds
from date_and_time import create_time_span
from interactions.context import InteractionContext
from interactions.priority import Priority
from server_commands.argument_helpers import OptionalSimInfoParam, get_optional_target
from sims4.resources import Types

import npc_llm
import npc_log
import npc_rules
from npc_actions import (MAX_ACTIONS, MAX_PER_OBJECT, SATISFIED_NEED, actions_for_goal,
                         actions_for_needs, actions_for_wants, activity_for_goal,
                         balance, blacklist_hours, build_candidates, buff_names,
                         category_rank, clamp_minutes,
                         clean_label, describe_missing, everyday_actions, examples_for,
                         format_minutes, interleave,
                         is_action, is_chore, is_internal, is_noise_object,
                         is_phone_chat, is_usable,
                         lowest_need_actions, missing_for_goal, need_activity_for,
                         NEED_ACTIVITIES, needs_a_situation, needs_arguments,
                         next_check_minutes, pick_random, request_key,
                         serves_satisfied, stems_for, still_failed, without_satisfied)
from npc_brain import NONE_ACTION, REQUEST_ACTION, build_prompt, prompt_summary
from npc_offlot import ACTIVITY_SKILLS, offlot_points
from npc_routine import ACTIVITIES, DAY_NAMES, RoutineEntry, RoutineStore

_ROUTINES_PATH = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts",
                               "The Sims 4", "Mods", "HouseRules", "data", "npc_routines.json")
_RULES_PATH = os.path.join(os.path.dirname(_ROUTINES_PATH), "npc_rules.json")

_store = RoutineStore()
_rules_store = npc_rules.RulesStore()
_npc_mode_sim_ids = set()
_loaded = False
_alarm_handle = None
_zone = None
_next_ask = {}          # sim id -> absolute day before which we do not ask again
ASK_COOLDOWN_MINUTES = 30   # never ask the same sim twice inside this window
FAILED_WAIT_MINUTES = 10    # retry this soon when nothing the model picked could be started
_poll_left = 0          # remaining answer-poll attempts
POLL_SECONDS = 2        # how often to look for the answer: the first choice should not wait
_llm_error_notified = False
_candidates = {}        # sim id -> the [Candidate] list the pending answer refers to
_retries_left = {}      # sim id -> how many times a refused choice may be re-asked at once
_active_task = {}       # sim id -> the affordance we pushed (None if we pushed none)
_task_deadline = {}     # sim id -> absolute day when the chosen time is over
_task_started = {}      # sim id -> absolute day when we pushed it (for the stuck watchdog)
_start_checks = {}      # sim id -> [label, checks left]: did the push actually start?
_needed = {}            # sim id -> what the goal needs but the lot cannot do (for the ask)
_ask_turns = {}         # sim id -> how many decisions so far (for a regular goal turn)
_pressing_seen = {}     # sim id -> (pressing needs, absolute day of the last interrupt)
URGENT_INTERRUPT_MINUTES = 30
GOAL_TURN_EVERY = 3     # every Nth decision offers only goal actions, if any exist
_needed_examples = {}   # sim id -> concrete objects that would fix it
MAX_OBJECTS_SHOWN = 20  # the prompt lists the nearest objects; the gap check sees all
_failed_actions = {}    # sim id -> {label: (when refused, how many times)}
_wake_handles = {}      # sim id -> alarm that asks again when its chosen wait is over
_last_request = {}      # sim id -> (what it asked for, absolute day), so it is not repeated
_logged = {}            # (kind, sim id) -> last message, so unchanged states log once
REQUEST_COOLDOWN_HOURS = 1
# A queued interaction that never actually starts is stuck: after this long, pick again.
STUCK_MINUTES = 15
# A pressing need needs a few real choices, or the model falls back to "do nothing".
MIN_NEED_CHOICES = 3
# How long to leave a need we started ourselves (a shower, a meal) alone before looking again.
NEED_ACTIVITY_MINUTES = 15

# Real interaction tuning names, confirmed in-game (2026-10-09): workout, chess, jog and
# autonomous_bookshelf_read_picker started; easel_Craft_Autonomously is what the easel offers.
# Tried in order: the first one that exists and has a target on this lot is pushed.
# Pushed at Priority.Low so a real need or the player can always pre-empt it.
ACTIVITY_AFFORDANCES = {
    "workout": ("treadmill_Workout", "generic_TreadmillWorkout"),
    # Painting, in order of preference:
    #   easel_PracticePainting     - the plain "Practice Painting" interaction, no mood gate
    #   easel_Craft_Autonomously*  - the Inspired-only variant ("doesn't have any buff in
    #                                whitelist", in-game 2026-10-09)
    #   easel_StartCrafting        - the player's own "Paint..." menu (a picker)
    # (The Easel_Canvas_Paint_* / canvas_PaintPainting_Staging_* ones are crafting staging
    # steps: pushing them directly fails for want of crafting_process and phase.)
    "paint": ("easel_PracticePainting", "easel_Craft_Autonomously", "easel_StartCrafting"),
    "read": ("autonomous_bookshelf_read_picker", "book_read"),
    "chess": ("Chess_PonderMoves", "chess_ponder_moves"),
    "jog": ("terrain-jog_Autonomous", "terrain-jog"),
}

# Fallback when none of the names above work for an object (in-game: the easel and
# bookshelf offered none of them): look at the nearest object whose name contains one of
# the hints, and try its own interactions whose names contain one of the keywords.
ACTIVITY_OBJECTS = {
    "workout": (("treadmill",), ("workout",)),
    "paint": (("easel",), ("practice", "paint", "craft_autonomously")),
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


def _is_pushable(sim, affordance):
    """The same filters the candidate list applies. Tuning data is not a curated list: it
    includes crafting staging steps (placemat_ColorPicture_Staging) and internal variants.
    Pushing a staging step makes the game log a desync, so those must be skipped."""
    label = clean_label(affordance.__name__)
    if not is_usable(label) or not is_action(label):
        return False
    if _needs_arguments(affordance):
        return False
    if is_internal(getattr(affordance, "debug", False),
                   getattr(affordance, "cheat", False),
                   getattr(affordance, "visible", True)):
        return False
    return _passes_its_own_tests(sim, affordance)


def _push_from_club_groups(sim, activity, report):
    affordances = []
    for hint in ACTIVITY_CLUB_HINTS.get(activity, ()):
        for group_name, group_affordances in _club_groups(hint):
            npc_log.log("  club activity {} uses: {}".format(group_name, [a.__name__ for a in group_affordances]))
            affordances.extend(a for a in group_affordances if a not in affordances)
    if not affordances:
        return False
    total = len(affordances)
    affordances = [a for a in affordances if _is_pushable(sim, a)]
    if not affordances:
        _say(report, "  clubs: none of {} interactions can be pushed from here".format(total),
             level="WARN")
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
            _rules_store.load(_RULES_PATH)
        except Exception:
            npc_log.log_exception("loading npc_rules.json")
        try:
            with open(_NPC_MODE_PATH, encoding="utf-8") as f:
                _npc_mode_sim_ids.update(int(i) for i in json.load(f))
        except (OSError, ValueError):
            pass
        # A fresh game session: the brain has not been started yet, whatever last session left.
        npc_llm.reset_active()
        _loaded = True


def _save():
    try:
        os.makedirs(os.path.dirname(_ROUTINES_PATH), exist_ok=True)
        _store.save(_ROUTINES_PATH)
    except Exception:
        npc_log.log_exception("saving routines")


def _save_rules():
    try:
        _rules_store.save(_RULES_PATH)
    except Exception:
        npc_log.log_exception("saving the JSON rules")


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


def _say(report, message, level="INFO", once=None):
    if once is not None:
        # While a task runs the same situation is re-checked every few sim minutes; logging
        # "549 interactions left out" and "Social 17, nothing addresses it" every time made
        # the log ~700 KB per game day. Only a change is worth a line.
        if _logged.get(once) == (message, level):
            return
        _logged[once] = (message, level)
    npc_log.log(message, level=level)
    if report is not None:
        try:
            report(message)
        except Exception:
            # Console output is cosmetic and can fail when the tick runs without a live
            # client connection (e.g. a self-test invoking houserules.npc.tick) - the line
            # is already in the log, so never let it break the tick.
            pass


def _push_activity(sim, activity, report=None):
    """Tries each interaction name for `activity` (a routine key, or from npc.try a raw
    interaction name) until the game accepts one. Returns True if one was pushed."""
    if activity in NEED_ACTIVITY_NAMES:
        # A need served with the lot's own objects (shower, sink, fridge): the names are
        # found on the objects themselves, so there is nothing to look up here.
        return _push_need_activity(sim, activity, report) is not None
    if activity in EVERYDAY_ACTIVITY_NAMES:
        return _push_everyday(sim, activity, report) is not None
    if activity in PHONE_ACTIVITIES:
        if activity == "chat on the phone":
            return _push_phone(sim, report) is not None
        return _invite_someone_over(sim, report)
    for affordance_name in ACTIVITY_AFFORDANCES.get(activity, (activity,)):
        try:
            affordance = _affordance_by_name(affordance_name)
            if affordance is None:
                _say(report, "  {}: no interaction with this name".format(affordance_name), level="WARN")
                continue
            if _needs_arguments(affordance):
                _say(report, "  {}: needs a crafting process and phase".format(affordance_name),
                     level="WARN")
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
            _say(report, "  {}: error - see the log".format(affordance_name), level="WARN")
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
    return _push_matching_object(sim, hints, keywords, report) is not None


def _push_matching_object(sim, hints, keywords, report):
    """Pushes the nearest object's own interaction that matches `keywords`. Returns the
    affordance that started, or None."""
    objects = _nearby_objects(sim, hints)
    if not objects:
        _say(report, "  fallback: no object with {} in its name on this lot".format(hints), level="WARN")
        return None
    for obj in objects:
        try:
            offered = list(obj.super_affordances())
        except Exception:
            npc_log.log_exception("listing interactions on {}".format(obj))
            continue
        # The full list goes to the log so the right name can be added to ACTIVITY_AFFORDANCES.
        npc_log.log("  {} offers {} interactions: {}".format(obj, len(offered), sorted(a.__name__ for a in offered)))
        candidates = sorted((a for a in offered
                             if any(k in a.__name__.lower() for k in keywords)
                             and not _needs_arguments(a)),
                            key=lambda a: _candidate_order(a.__name__))
        _say(report, "  fallback: {} has {} matching: {}".format(obj, len(candidates), [a.__name__ for a in candidates]))
        for affordance in candidates:
            try:
                context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.Low)
                result = sim.push_super_affordance(affordance, obj, context)
                _say(report, "  {} on {}: result={!r}".format(affordance.__name__, obj, result))
                if result:
                    return affordance
            except Exception:
                npc_log.log_exception("pushing {} on {}".format(affordance.__name__, obj))
    return None


# Where the object that serves a pressing need lives, and which of its own interactions
# counts. Everything else about the need is handled by npc_actions (which need, and why);
# this is the same "find it on the object" path as the activity fallbacks above, and it
# exists because the filtered candidate list can come up empty while the shower is right
# there (2026-10-27: Hygiene 0 for three sim days, "nothing here addresses it").
NEED_OBJECT_HINTS = {
    "shower": (("shower", "bathtub", "tub"), ("shower", "bathe", "bath")),
    "wash hands": (("sink",), ("wash", "hand")),
    "brush teeth": (("sink", "mirror"), ("brush", "teeth")),
    "toilet": (("toilet",), ("toilet", "pee", "use")),
    "eat": (("fridge", "stove", "counter"), ("cook", "grab", "eat", "meal", "serve")),
    "sleep": (("bed",), ("sleep", "nap")),
}

NEED_ACTIVITY_NAMES = frozenset(activity for _need, activity in NEED_ACTIVITIES)

# Everyday jobs, pushed the same way as a need (nearest matching object, then that object's
# own interaction). The names are matched against the object's interactions, not a tuning
# name, so a pack's variant is found too. npc_actions.EVERYDAY_NEEDS decides when the prompt
# offers them (the fridge/mailbox/computer has to be on the lot).
EVERYDAY_OBJECTS = {
    "put food in fridge": (("fridge",), ("leftover", "store", "put away")),
    "pay bills": (("mailbox",), ("bill", "pay")),
    "chat on the computer": (("computer",), ("chat", "social")),
}

EVERYDAY_ACTIVITY_NAMES = frozenset(EVERYDAY_OBJECTS)

# Social is the one need no object can serve: it needs another sim, and other sims are
# deliberately not in the object list (their interactions are not this sim's own choices).
SOCIAL_WORDS = ("chat", "talk", "joke", "gossip", "hug", "kiss", "complain", "confide",
                "conversation", "ask about", "catch up", "mischief", "deep")


def _nearby_sims(sim, limit=3):
    found = []
    for obj in services.object_manager().valid_objects():
        if obj is sim or not hasattr(obj, "sim_info") or not hasattr(obj, "super_affordances"):
            continue
        try:
            found.append(((obj.position - sim.position).magnitude_squared(), obj))
        except Exception:
            continue
    found.sort(key=lambda pair: pair[0])
    return [obj for _, obj in found[:limit]]


def _push_social(sim, report=None):
    """Start a conversation with the nearest sim. Returns the affordance, or None."""
    for other in _nearby_sims(sim):
        try:
            offered = list(other.super_affordances())
        except Exception:
            npc_log.log_exception("listing interactions on {}".format(other))
            continue
        candidates = sorted((a for a in offered
                             if any(word in a.__name__.lower() for word in SOCIAL_WORDS)
                             and _is_pushable(sim, a)),
                            key=lambda a: _candidate_order(a.__name__))
        _say(report, "  social: {} has {} usable: {}".format(
            other, len(candidates), [a.__name__ for a in candidates]))
        for affordance in candidates:
            try:
                context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.Low)
                result = sim.push_super_affordance(affordance, other, context)
                _say(report, "  {} on {}: result={!r}".format(
                    affordance.__name__, other, result))
                if result:
                    return affordance
            except Exception:
                npc_log.log_exception("pushing {} on {}".format(affordance.__name__, other))
    _say(report, "  social: nothing to talk to nearby", level="WARN")
    return None


def _push_need_activity(sim, activity, report=None):
    """Serve a pressing need ourselves. Returns the affordance that started, or None."""
    if activity == "chat":
        # Someone here, otherwise call someone: Social is the one need no object serves.
        return _push_social(sim, report) or _push_phone(sim, report)
    hints, keywords = NEED_OBJECT_HINTS.get(activity, ((), ()))
    if not hints:
        return None
    return _push_matching_object(sim, hints, keywords, report)


# Sitting alone is what the phone and an invitation are for; both are offered when nobody
# else is on the lot (see _ask_llm), and "chat" for a pressing Social need tries them too.
PHONE_ACTIVITIES = frozenset({"chat on the phone", "invite someone over"})


def _push_phone(sim, report=None):
    """Call or text someone with the sim's phone. Returns the affordance, or None.

    The phone is not an object on the lot - its interactions live on the sim
    (sim.potential_phone_interactions in sims/sim.py). The "who?" ones are pickers, which
    would open a menu and pause the game, so only direct ones are pushed; when none
    matches, the full list goes to the log so the right name can be added to PHONE_WORDS."""
    try:
        context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.Low)
        aops = list(sim.potential_phone_interactions(context))
    except Exception:
        npc_log.log_exception("listing the sim's phone interactions")
        return None
    usable = []
    for aop in aops:
        if not is_phone_chat(getattr(aop.affordance, "__name__", "")):
            continue
        try:
            if not aop.test(context):
                continue
        except Exception:
            continue
        usable.append(aop)
    if usable:
        npc_log.log("  phone: {} usable: {}".format(
            len(usable), [aop.affordance.__name__ for aop in usable]))
    else:
        # The full list goes to the log so the right name can be added to PHONE_WORDS.
        npc_log.log("  phone: {} interactions, none direct: {}".format(
            len(aops), sorted({getattr(aop.affordance, "__name__", "?") for aop in aops})))
    usable.sort(key=lambda aop: _candidate_order(aop.affordance.__name__))
    for aop in usable:
        target = aop.target if aop.target is not None else sim
        try:
            result = sim.push_super_affordance(aop.affordance, target, context)
            _say(report, "  phone {} on {}: result={!r}".format(
                aop.affordance.__name__, target, result))
            if result:
                return aop.affordance
        except Exception:
            npc_log.log_exception(
                "pushing the phone interaction {}".format(aop.affordance.__name__))
    _say(report, "  phone: no direct call/chat interaction (the names are in the log)",
         level="WARN")
    return None


def _invite_someone_over(sim, report=None):
    """Ask a friend over. True when the venue was asked to summon them.

    The phone's own "Invite Over" is a picker (a menu that pauses the game and needs the
    player), so this does what the game does once that picker is answered:
    venue_service.summon_npcs - the same call career_base.py's invite_over makes. The sim
    with the highest relationship that is not in this household is asked."""
    sim_info = getattr(sim, "sim_info", None)
    if sim_info is None:
        return False
    try:
        household = getattr(sim_info, "household", None)
        household_ids = {info.sim_id for info in household.sim_info_gen()}
        target_id = sim_info.relationship_tracker.get_highest_rel_score_sim(
            blacklist_sim_ids=household_ids)
    except Exception:
        npc_log.log_exception("finding someone to invite over")
        return False
    if target_id in (None, getattr(sim_info, "sim_id", None)):
        _say(report, "  invite: no friend to ask over", level="WARN")
        return False
    target_info = services.sim_info_manager().get(target_id)
    if target_info is None:
        return False
    if target_info.get_sim_instance() is not None:
        _say(report, "  invite: {} is already here".format(
            getattr(target_info, "first_name", "someone")))
        return False
    try:
        from venues.venue_constants import NPCSummoningPurpose
        venue = services.current_zone().venue_service.active_venue
        venue.summon_npcs((target_info,), NPCSummoningPurpose.DEFAULT, sim_info)
    except Exception:
        npc_log.log_exception("inviting {} over".format(target_info))
        return False
    _say(report, "  invite: asked {} over".format(
        getattr(target_info, "first_name", "a friend")))
    return True


def _push_everyday(sim, activity, report=None):
    """An everyday job (put food in the fridge, pay the bills, chat on the computer).
    Returns the affordance that started, or None."""
    hints, keywords = EVERYDAY_OBJECTS.get(activity, ((), ()))
    if not hints:
        return None
    return _push_matching_object(sim, hints, keywords, report)


def _run_tick(report=None, quiet=False):
    """quiet is for the while-busy rechecks: they run every few sim minutes, so their
    "still doing it" lines would otherwise fill the log."""
    _ensure_loaded()
    if _game_paused():
        if not quiet:
            _say(report, "tick: the game is paused - nothing to do")
        return
    _apply_llm_answers(report)
    if not _npc_mode_sim_ids:
        if not quiet:
            _say(report, "tick: no sims in NPC mode")
        return
    now = services.time_service().sim_timeline.now
    day, hour = now.day(), now.hour()
    if not quiet:
        _say(report, "tick: day={} ({}) hour={} npc_sims={}".format(
            day, DAY_NAMES[day], hour, sorted(_npc_mode_sim_ids)))
    sim_info_manager = services.sim_info_manager()
    for sim_id in list(_npc_mode_sim_ids):
        routine = _store.get(sim_id)
        activity = routine.due_activity(day, hour)
        sim_info = sim_info_manager.get(sim_id)
        sim = sim_info.get_sim_instance() if sim_info is not None else None
        # JSON rules decide first: they are the main way to run a sim now. The LLM only
        # takes a sim that has no rules loaded. When no rule matches, the hourly routine
        # below still applies (so a rules file can cover only part of the day).
        ruleset = _rules_store.get(sim_id)
        if sim is not None and ruleset:
            if not _may_ask(sim_id, now):
                continue
            if _should_keep_waiting(sim_id, now) and not _urgent_interrupt(sim_id, sim_info, now):
                if not quiet:
                    _say(report, "  sim {}: still doing it - checking again soon".format(sim_id))
                _reschedule_check(sim_id)
                continue
            if _apply_rules(sim_info, ruleset, report):
                continue
        # A goal makes the LLM decide the hour, even when a routine entry is due: the player
        # asked for that sim to work towards the goal. Descriptions alone keep the old rule
        # (the routine wins, the LLM only fills idle hours).
        if sim is not None and npc_llm.goal_for(sim_id):
            if _may_ask(sim_id, now):
                if _should_keep_waiting(sim_id, now) and not _urgent_interrupt(sim_id, sim_info, now):
                    if not quiet:
                        _say(report, "  sim {}: still doing it - checking again soon".format(sim_id))
                    _reschedule_check(sim_id)
                else:
                    _ask_llm(sim_info, report)
            continue
        if activity is None:
            if not quiet:
                _say(report, "  sim {}: nothing due ({} routine entries)".format(
                    sim_id, len(routine.entries)))
            if sim is not None and npc_llm.instructions_for(sim_id) and _may_ask(sim_id, now):
                if _should_keep_waiting(sim_id, now) and not _urgent_interrupt(sim_id, sim_info, now):
                    if not quiet:
                        _say(report, "  sim {}: still doing it - checking again soon".format(sim_id))
                    _reschedule_check(sim_id)
                else:
                    _ask_llm(sim_info, report)
            continue
        if sim is None:
            # Not on the loaded lot: phase 3, give them a share of what they'd have learned.
            if sim_info is not None:
                _offlot_hour(sim_info, activity, report)
            continue
        _push_activity(sim, activity, report)


# --- Phase 3: off-lot results -------------------------------------------------------------
_skill_types = None


def _skill_type(short_name):
    """Adult skill statistic whose tuning name ends with _<short_name> (Fitness -> ..._Fitness)."""
    global _skill_types
    if _skill_types is None:
        found = {}
        wanted = {s.lower(): s for s in ACTIVITY_SKILLS.values() if s}
        for cls in services.get_instance_manager(Types.STATISTIC).types.values():
            name = cls.__name__.lower()
            if "skill" not in name:
                continue
            short = wanted.get(name.rsplit("_", 1)[-1])
            if short and (short not in found or ("adult" in name and "adult" not in found[short].__name__.lower())):
                found[short] = cls
        _skill_types = found
        npc_log.log("off-lot skills: {}".format({k: v.__name__ for k, v in found.items()}))
    return _skill_types.get(short_name)


def _offlot_hour(sim_info, activity, report):
    try:
        tracker = getattr(sim_info, "career_tracker", None)
        if tracker is not None and tracker.currently_at_work:
            _say(report, "  sim {}: {!r} due but at work".format(sim_info.sim_id, activity))
            return
        short = ACTIVITY_SKILLS.get(activity)
        skill_type = _skill_type(short) if short else None
        if skill_type is None:
            _say(report, "  sim {}: {!r} off the lot (no skill to train)".format(sim_info.sim_id, activity))
            return
        stat = sim_info.get_statistic(skill_type, add=True)
        if stat is None:
            return
        level = stat.get_user_value()
        start = skill_type.convert_from_user_value(level)
        next_start = skill_type.convert_from_user_value(min(level + 1, skill_type.max_level))
        max_points = skill_type.convert_from_user_value(skill_type.max_level)
        points = offlot_points(activity, next_start - start, stat.get_value(), max_points)
        if points > 0:
            stat.add_value(points)
        _say(report, "  sim {}: {!r} off the lot -> {} +{:.0f} points (level {})".format(
            sim_info.sim_id, activity, short, points, level))
    except Exception:
        npc_log.log_exception("off-lot results for sim {}".format(sim_info.sim_id))


# --- Phase 4: local LLM brain -------------------------------------------------------------
# Below this a need counts as uncomfortable, and the prompt is told to deal with it first.
PRESSING_NEED = 30

_PREFIXES = ("trait_", "statistic_skill_adultmajor_", "statistic_skill_adultminor_",
             "statistic_skill_", "mood_", "motive_", "commodity_motive_")

# Current weather, from the game's WeatherType flags. Temperature first, so "cool, raining"
# reads naturally instead of "raining, cool".
_WEATHER_LABELS = {
    "Freezing": "freezing", "Cold": "cold", "Cool": "cool", "Warm": "warm",
    "Hot": "hot", "Burning": "burning",
    "AnyRain": "raining", "AnySnow": "snowing", "AnyLightning": "thunder and lightning",
    "Max_Rain_Accumulation": "puddles", "Max_Snow_Accumulation": "deep snow",
}
_WEATHER_TEMPERATURES = frozenset(("freezing", "cold", "cool", "warm", "hot", "burning"))


def _clean(name):
    for prefix in _PREFIXES:
        if name.lower().startswith(prefix):
            return name[len(prefix):]
    return name


def _weather():
    """Current weather in plain words ('cool, raining'), or '' when weather isn't available."""
    try:
        service = services.weather_service()
        if service is None:
            return ""
        names = [getattr(t, "name", str(t)) for t in service.get_current_weather_types()]
    except Exception:
        npc_log.log_exception("reading the weather")
        return ""
    labels = {_WEATHER_LABELS[name] for name in names if name in _WEATHER_LABELS}
    return ", ".join(sorted(labels, key=lambda label: (label not in _WEATHER_TEMPERATURES, label)))


def _season():
    """The current season ('fall'), or '' when seasons aren't available."""
    try:
        service = services.season_service()
        season = service.season if service is not None else None
    except Exception:
        return ""
    name = getattr(season, "name", "")
    return name.lower() if name else ""


def _current_activity(sim):
    """What the sim is doing right now - so the model does not queue more of the same."""
    names = []
    try:
        for interaction in sim.si_state.sis_actor_gen():
            name = type(interaction).__name__
            if name and name not in names:
                names.append(name)
    except Exception:
        pass
    if not names:
        try:
            running = sim.queue.running
            if running is not None:
                names.append(type(running).__name__)
        except Exception:
            pass
    labels = []
    for name in names:
        label = clean_label(name)
        # Posture/reaction entries ("sim stand", "rain start reaction") say nothing about
        # what the sim is actually busy with.
        if not label or label in labels or not is_usable(label):
            continue
        labels.append(label)
    return labels[:3]


def _nearby(sim):
    """Who else is on the lot: pets, household members, visitors and service NPCs (a butler,
    a nanny, a repairman). Tells the model who is around without offering socials as actions."""
    try:
        household = services.active_household()
    except Exception:
        household = None
    found = []
    for obj in services.object_manager().valid_objects():
        if obj is sim or not hasattr(obj, "sim_info"):
            continue
        info = obj.sim_info
        try:
            distance = (obj.position - sim.position).magnitude_squared()
        except Exception:
            distance = float("inf")
        name = getattr(info, "first_name", "") or "someone"
        if getattr(info, "is_pet", False):
            species = getattr(getattr(info, "species", None), "name", "")
            kind = species.lower() if species else "pet"
        elif household is not None and getattr(info, "household", None) is household:
            kind = "household"
        else:
            kind = "visitor or service npc"
        found.append((distance, "{} ({})".format(name, kind)))
    found.sort(key=lambda pair: pair[0])
    return [label for _, label in found[:5]]


def _inventory(sim_info):
    """What the sim is carrying - seeds and produce make planting sensible, food makes eating
    sensible, and the model cannot guess that from the needs alone."""
    try:
        inventory = sim_info.inventory
        if inventory is None:
            return []
    except Exception:
        return []
    names = []
    try:
        for obj in inventory:
            label = clean_label(str(obj).split(":")[0])
            if label and label not in names:
                names.append(label)
    except Exception:
        npc_log.log_exception("reading the inventory")
    return names[:10]


def _buffs(sim_info):
    """What the sim is currently feeling (the mood's ingredients), in plain words."""
    try:
        return buff_names(list(sim_info.Buffs))
    except Exception:
        npc_log.log_exception("reading the sim's buffs")
        return []


def _wants(sim_info):
    """The sim's current wants (whims in the game's terms), e.g. 'paint a masterpiece'."""
    tracker = getattr(sim_info, "whim_tracker", None)
    if tracker is None:
        return []
    wants = []
    try:
        for slot in tracker.slots_gen():
            if slot.is_empty():
                continue
            # The whim's tuned goal is specific ("Goal_PaintPainting"); the goal *instance's*
            # class name is a generic base ("SituationGoalActor") and tells the model nothing.
            whim = getattr(slot, "whim", None)
            goal = getattr(whim, "goal", None) if whim is not None else None
            name = getattr(goal, "__name__", None)
            if not name and whim is not None:
                name = getattr(whim, "__name__", None)
            label = clean_label(name) if name else ""
            if label and label not in wants and "situation" not in label:
                wants.append(label)
    except Exception:
        npc_log.log_exception("reading the sim's wants")
    return wants[:4]


def _describe(sim_info):
    desc = {"name": "{} {}".format(sim_info.first_name, sim_info.last_name).strip(),
            "age": getattr(sim_info.age, "name", str(sim_info.age)).lower()}
    try:
        desc["traits"] = [_clean(t.__name__) for t in sim_info.trait_tracker.personality_traits]
    except Exception:
        desc["traits"] = []
    try:
        desc["mood"] = _clean(sim_info.get_mood().__name__)
    except Exception:
        pass
    try:
        intensity = int(sim_info.get_mood_intensity())
        if intensity > 0:
            desc["mood_intensity"] = intensity
    except Exception:
        pass
    desc["buffs"] = _buffs(sim_info)
    desc["inventory"] = _inventory(sim_info)
    desc["wants"] = _wants(sim_info)
    desc["weather"] = _weather()
    desc["season"] = _season()
    sim = sim_info.get_sim_instance()
    if sim is not None:
        desc["activity"] = _current_activity(sim)
        desc["nearby"] = _nearby(sim)
    needs = {}
    try:
        for stat in sim_info.commodity_tracker:
            name = type(stat).__name__
            if name.lower().startswith(("motive_", "commodity_motive_")) and "visible" not in name.lower():
                needs[_clean(name)] = int((stat.get_value() + 100) / 2)
    except Exception:
        pass
    desc["needs"] = needs
    desc["pressing"] = ["{} {}".format(name, value)
                        for name, value in sorted(needs.items(), key=lambda item: item[1])
                        if value < PRESSING_NEED]
    try:
        desc["skills"] = {_clean(type(s).__name__): s.get_user_value()
                          for s in sim_info.all_skills() if s.get_user_value() > 0}
    except Exception:
        desc["skills"] = {}
    try:
        desc["job"] = ", ".join(type(c).__name__ for c in sim_info.career_tracker.careers.values())
    except Exception:
        pass
    now = services.time_service().sim_timeline.now
    desc["day"] = DAY_NAMES[now.day()]
    desc["hour"] = now.hour()
    desc["time"] = "{} {}:00".format(DAY_NAMES[now.day()], now.hour())
    return desc


def _affordances_of(obj):
    try:
        return sorted(obj.super_affordances(), key=lambda a: _candidate_order(a.__name__))
    except Exception:
        npc_log.log_exception("listing interactions on {}".format(obj))
        return []


def _terrain_affordances(sim):
    """Jogging and friends live on the sim itself and target the sim, not an object."""
    try:
        return [a for a in sim.super_affordances() if a.__name__.lower().startswith("terrain")]
    except Exception:
        npc_log.log_exception("listing the sim's own interactions")
        return []


def _objects_by_distance(sim):
    found = []
    for obj in services.object_manager().valid_objects():
        if obj is sim or not hasattr(obj, "super_affordances"):
            continue
        if hasattr(obj, "sim_info"):
            # Other sims and pets are objects too. Their interactions (social mixers, pet
            # misbehaviour, butler duties) are not things this sim picks from a list.
            continue
        try:
            found.append(((obj.position - sim.position).magnitude_squared(), obj))
        except Exception:
            found.append((float("inf"), obj))
    found.sort(key=lambda pair: pair[0])
    return [obj for _, obj in found]


def _recently_failed(sim_id):
    """Labels the game refused recently. They come back after BLACKLIST_HOURS, because many
    refusals are about state (an empty bin, a dirty counter) rather than the action itself;
    a label refused more than once stays out longer (see blacklist_hours)."""
    try:
        now = float(services.time_service().sim_timeline.now.absolute_days())
    except Exception:
        now = 0.0
    return {label for label, (when, strikes) in _failed_actions.get(sim_id, {}).items()
            if still_failed(when, now, hours=blacklist_hours(strikes))}


def _record_failure(sim_id, label):
    """Remember a refusal for this sim, counting repeats. The count only resets when the
    brain is stopped for the sim, so a chronic offender keeps its longer blacklist after the
    short window expires."""
    try:
        now = float(services.time_service().sim_timeline.now.absolute_days())
    except Exception:
        now = 0.0
    previous = _failed_actions.get(sim_id, {}).get(label)
    strikes = (previous[1] + 1) if previous else 1
    _failed_actions.setdefault(sim_id, {})[label] = (now, strikes)


def _object_label(obj):
    """The tuning name without its instance id: 'object_tableDining_1x1:0x020c...'."""
    return clean_label(str(obj).split(":")[0])


# Crafting interactions are built from a crafting process; pushing the bare staging step
# ("counter make food basic") fails. The check lives in npc_actions so the filters applied to
# the candidate list are exactly the ones applied to the fallback paths below.
_needs_arguments = needs_arguments


def _passes_its_own_tests(sim, affordance, target=None):
    """False when the game's own tests say this interaction would not be offered - a full bin,
    a buff whitelist, a zone rule, a situation that is not running.

    The cheap early tests skip anything they cannot judge, so nothing that needs a real super
    interaction (pickers, crafting menus) is thrown out on a false negative."""
    try:
        tests = []
        for test_list in (getattr(affordance, "test_globals", None),
                          getattr(affordance, "tests", None)):
            tests.extend(type(test).__name__ for test in (test_list or ()))
        if needs_a_situation(tests):
            return False      # e.g. "clean counter" only inside the maid's situation
    except Exception:
        npc_log.log_exception("reading the tests for {}".format(affordance.__name__))
    try:
        from event_testing.resolver import AffordanceResolver
        resolver = AffordanceResolver(affordance, sim)
        # test_globals and tests only. test_autonomous holds the gates for *autonomy* picks
        # (an Inspired-only variant); applying it here hid ordinary actions like painting and
        # cooking from the list. A mood gate is still caught when the push is refused.
        for tests in (getattr(affordance, "test_globals", None),
                      getattr(affordance, "tests", None)):
            if tests is not None and not tests.run_tests(
                    resolver, skip_safe_tests=False, search_for_tooltip=False):
                return False
    except Exception:
        npc_log.log_exception("checking the requirements for {}".format(affordance.__name__))
    # Deliberately no full affordance.test() here. The game runs it with a real super
    # interaction; without one it rejects pickers ("Paint...", "Cook...") that actually work,
    # which hid painting and cooking from the list. A wrong interaction is caught at push time
    # instead (refused -> other variants on that object -> blacklisted for a few hours).
    return True


def _explain_blocked(sim, blocked_names):
    """Log why the thing the goal is about cannot be started: one line per matching
    interaction, with the filter that rejected it. Read this with `npc.checks <text>`."""
    stems = set()
    for described in blocked_names:
        stems.update(stems_for(described.split(" (")[0]))
    if not stems:
        return
    shown = 0
    for obj in _objects_by_distance(sim):
        for affordance in _affordances_of(obj):
            name = affordance.__name__.lower()
            if not any(stem in name for stem in stems):
                continue
            label = clean_label(affordance.__name__)
            reasons = []
            if not is_usable(label):
                reasons.append("label filtered")
            if not is_action(label):
                reasons.append("not a life action")
            if _needs_arguments(affordance):
                reasons.append("needs arguments we cannot supply")
            if is_internal(getattr(affordance, "debug", False),
                           getattr(affordance, "cheat", False),
                           getattr(affordance, "visible", True)):
                reasons.append("debug/cheat/hidden")
            if not _passes_its_own_tests(sim, affordance, obj):
                reasons.append("fails its own tests")
            npc_log.log("  {} on {}: {}".format(
                affordance.__name__, obj, "; ".join(reasons) or "OK - offered"))
            shown += 1
            if shown >= 12:
                return


def _collect_candidates(sim):
    """Everything on this lot the sim could do: one entry per readable label, nearest first.
    Returns (candidates, object labels) - the prompt shows both, so the model can tell what
    it actually has to work with instead of inventing actions."""
    groups, object_labels = [], []
    skipped = 0
    for obj in _objects_by_distance(sim):
        label = _object_label(obj)
        if label and label not in object_labels and not is_noise_object(label):
            object_labels.append(label)
        # Drop the noise before taking this object's share, otherwise unusable variants
        # (pickers, hidden, career gimmicks) eat the quota and hide the real actions.
        group = []
        for affordance in _affordances_of(obj):
            label = clean_label(affordance.__name__)
            if not is_usable(label) or not is_action(label):
                continue
            if _needs_arguments(affordance):
                skipped += 1
                continue
            if is_internal(getattr(affordance, "debug", False),
                           getattr(affordance, "cheat", False),
                           getattr(affordance, "visible", True)):
                skipped += 1
                continue
            if not _passes_its_own_tests(sim, affordance, obj):
                skipped += 1
                continue
            group.append((label, affordance, obj))
            if len(group) >= MAX_PER_OBJECT:
                break
        if group:
            groups.append(group)
    if skipped:
        _say(None, "  left out {} interactions that fail their own requirements right now"
             .format(skipped), once=("skipped", getattr(sim, "id", None)))
    terrain = [(clean_label(a.__name__), a, sim) for a in _terrain_affordances(sim)]
    if terrain:
        groups.append(terrain)
    entries = interleave(groups) if groups else []
    candidates = build_candidates(entries, limit=MAX_ACTIONS, skip=_recently_failed(sim.id))
    if not candidates:
        # No usable object interactions on this lot: fall back to the starter activities so
        # the brain still has something to choose from.
        candidates = build_candidates(((a, None, None) for a in sorted(ACTIVITIES)),
                                      limit=MAX_ACTIONS)
    # One chatty object must not dominate: cap how many of the same kind/category get in.
    candidates = balance(candidates)
    # Keep the option numbers ascending inside the prompt's category groups (stable, so the
    # nearest object still wins within a group). Chores come last of all.
    candidates.sort(key=lambda candidate: (category_rank(candidate.label),
                                           is_chore(candidate.label)))
    return candidates, object_labels


def _may_ask(sim_id, now):
    """True when this sim may be sent to the LLM now. The wait after an answer is what
    usually holds it back; ASK_COOLDOWN_MINUTES covers the request in flight."""
    return float(now.absolute_days()) >= _next_ask.get(sim_id, 0)


def _matches(interaction, affordance):
    """Is this running interaction the one we pushed? isinstance alone misses the cases where
    the game wraps it in another class (the queue shows "shower_TakeShower" while the pushed
    affordance is a wrapper), so the tuning name is compared too."""
    try:
        if isinstance(interaction, affordance):
            return True
    except TypeError:
        pass
    return type(interaction).__name__ == getattr(affordance, "__name__", "")


def _task_is_actually_running(sim_id):
    """True only when it is running, not merely queued (a rallyable interaction can sit in
    the queue for ever without the sim ever starting it)."""
    affordance = _active_task.get(sim_id)
    if affordance is None:
        return False
    sim_info = services.sim_info_manager().get(sim_id)
    sim = sim_info.get_sim_instance() if sim_info is not None else None
    if sim is None:
        return False
    try:
        return any(_matches(interaction, affordance)
                   for interaction in sim.si_state.sis_actor_gen())
    except Exception:
        npc_log.log_exception("checking whether sim {} started it".format(sim_id))
        return False


def _task_is_running(sim_id):
    """True while the interaction we pushed is queued or running for the sim."""
    affordance = _active_task.get(sim_id)
    if affordance is None:
        return False
    sim_info = services.sim_info_manager().get(sim_id)
    sim = sim_info.get_sim_instance() if sim_info is not None else None
    if sim is None:
        return False
    try:
        if any(isinstance(interaction, affordance)
               for interaction in sim.si_state.sis_actor_gen()):
            return True
    except Exception:
        npc_log.log_exception("checking whether sim {} is still busy".format(sim_id))
    try:
        # Enqueued counts: a sim walking to the fridge has accepted the interaction.
        for interaction in sim.queue:
            queued_affordance = getattr(interaction, "affordance", None)
            if _matches(interaction, affordance) or queued_affordance is affordance:
                return True
    except Exception:
        npc_log.log_exception("checking sim {}'s queue".format(sim_id))
    return False


# Pushing an interaction only enqueues it. The game can still drop it (a broken object, a test
# that no longer holds), so look a few times over the next seconds and move on if it never
# appears. One second apart catches interactions that start and finish almost immediately.
START_CHECK_SECONDS = 1
START_CHECK_ATTEMPTS = 5


def _schedule_start_check(sim_id, label):
    if _zone is None:
        return
    _start_checks[sim_id] = [label, START_CHECK_ATTEMPTS]
    _add_start_check_alarm(sim_id)


def _add_start_check_alarm(sim_id, seconds=START_CHECK_SECONDS):
    if _zone is None:
        return
    try:
        alarms.add_alarm_real_time(_zone, interval_in_real_seconds(seconds),
                                   lambda *_args, **_kwargs: _check_started(sim_id))
    except Exception:
        npc_log.log_exception("scheduling the start check")


def _check_started(sim_id):
    state = _start_checks.get(sim_id)
    if state is None:
        return
    if _game_paused():
        _add_start_check_alarm(sim_id)      # time is frozen; look again after unpausing
        return
    label, left = state
    if _task_is_running(sim_id):
        _start_checks.pop(sim_id, None)
        return
    if left <= 1:
        _start_checks.pop(sim_id, None)
        _never_started(sim_id, label)
        return
    state[1] = left - 1
    _add_start_check_alarm(sim_id)


def _try_any_candidate(sim, sim_id, report=None):
    """Last resort when nothing the model picked could be started: start the first candidate
    that works, so the sim is not left standing for the failed-wait. Returns True if one did."""
    tried = 0
    refused = _recently_failed(sim_id)
    for candidate in _candidates.get(sim_id, ()):
        if candidate.affordance is None or candidate.label in refused:
            continue
        tried += 1
        ok, pushed = _push_candidate(sim, candidate, report)
        if ok:
            _active_task[sim_id] = pushed
            try:
                _task_started[sim_id] = float(
                    services.time_service().sim_timeline.now.absolute_days())
            except Exception:
                pass
            _schedule_start_check(sim_id, candidate.label)
            _say(report, "  sim {}: nothing from the model worked - started {!r} instead".format(
                sim_id, candidate.label))
            return True
        if tried >= 4:
            break
    return False


def _never_started(sim_id, label):
    """The push was accepted but the sim never picked it up: treat it like a refusal."""
    _say(None, "  sim {}: {!r} never started - trying something else".format(sim_id, label),
         level="WARN")
    _record_failure(sim_id, label)
    _active_task.pop(sim_id, None)
    _task_deadline.pop(sim_id, None)
    sim_info = services.sim_info_manager().get(sim_id)
    if sim_info is None:
        return
    left = _retries_left.get(sim_id, 0)
    if left > 0:
        _ask_llm(sim_info, None, allow_request=False, retries=left - 1)
    else:
        _defer(sim_id, FAILED_WAIT_MINUTES)


def _pressing_now(sim_info):
    """Needs below the pressing threshold right now (they change while a task runs)."""
    try:
        return _describe(sim_info).get("pressing") or []
    except Exception:
        npc_log.log_exception("reading the pressing needs")
        return []


def _urgent_interrupt(sim_id, sim_info, now):
    """True when a need has become urgent while the sim is busy, so waiting is wrong.

    Napping with Energy 100 is fine; napping while Bladder falls to 20 is not. Interrupting
    every five minutes for the same unmet need would thrash, so the same set of pressing needs
    interrupts at most every URGENT_INTERRUPT_MINUTES."""
    pressing = _pressing_now(sim_info)
    if not pressing:
        return False
    now_days = float(now.absolute_days())
    previous = _pressing_seen.get(sim_id)
    if previous is not None and previous[0] == pressing:
        if (now_days - previous[1]) * 1440.0 < URGENT_INTERRUPT_MINUTES:
            return False
    _pressing_seen[sim_id] = (pressing, now_days)
    _say(None, "  sim {}: {} while busy - re-deciding".format(sim_id, ", ".join(pressing)))
    return True


def _should_keep_waiting(sim_id, now):
    """Our action is still running and its chosen time is not up: wait, don't pick a new one.

    A task that has only been *queued* for STUCK_MINUTES is not busy, it is stuck - pick again
    instead of waiting out the model's hour."""
    if _active_task.get(sim_id) is None:
        return False
    now_days = float(now.absolute_days())
    if now_days >= _task_deadline.get(sim_id, 0):
        return False
    if _task_is_actually_running(sim_id):
        return True
    if not _task_is_running(sim_id):
        return False        # it is gone entirely: nothing is keeping the sim busy
    queued_for = (now_days - _task_started.get(sim_id, now_days)) * 1440.0
    if queued_for >= STUCK_MINUTES:
        _say(None, "  sim {}: never got going - choosing something else".format(sim_id),
             level="WARN")
        return False
    return True


def _defer(sim_id, minutes):
    """Do not ask this sim again for `minutes`. While an action we started is running, look
    again every few minutes instead: if it finishes early, the sim gets a new choice then
    rather than sitting idle until the deadline."""
    try:
        now = services.time_service().sim_timeline.now
    except Exception:
        npc_log.log_exception("recording the LLM wait")
        return
    now_days = float(now.absolute_days())
    _task_deadline[sim_id] = now_days + minutes / 1440.0
    wait = minutes
    if _active_task.get(sim_id) is not None:
        wait = next_check_minutes(minutes)
    _next_ask[sim_id] = now_days + wait / 1440.0
    _schedule_wake(sim_id, wait)


def _reschedule_check(sim_id):
    """Still busy: look again in a few minutes, but never past the deadline the model set."""
    try:
        now_days = float(services.time_service().sim_timeline.now.absolute_days())
    except Exception:
        return
    remaining = int(round((_task_deadline.get(sim_id, now_days) - now_days) * 1440))
    wait = next_check_minutes(remaining)
    _next_ask[sim_id] = now_days + wait / 1440.0
    _schedule_wake(sim_id, wait, say=False)


def _schedule_wake(sim_id, minutes, say=True):
    if _zone is None:
        return
    _cancel_wake(sim_id)
    try:
        _wake_handles[sim_id] = alarms.add_alarm(
            _zone, create_time_span(minutes=minutes), _wake)
        if say:
            _say(None, "sim {}: next LLM choice in {}".format(sim_id, format_minutes(minutes)),
                 once=("wake", sim_id))
    except Exception:
        npc_log.log_exception("scheduling the next LLM choice")


def _cancel_wake(sim_id):
    handle = _wake_handles.pop(sim_id, None)
    if handle is not None:
        try:
            alarms.cancel_alarm(handle)
        except Exception:
            npc_log.log_exception("cancelling the next LLM choice")


def _wake(*_args, **_kwargs):
    _tick(quiet=True)


def _forget(sim_id):
    """Forget everything the brain holds for a sim (stopping it, or it left NPC mode)."""
    _next_ask.pop(sim_id, None)
    _candidates.pop(sim_id, None)
    _retries_left.pop(sim_id, None)
    _active_task.pop(sim_id, None)
    _task_deadline.pop(sim_id, None)
    _task_started.pop(sim_id, None)
    _start_checks.pop(sim_id, None)
    _needed.pop(sim_id, None)
    _needed_examples.pop(sim_id, None)
    _ask_turns.pop(sim_id, None)
    _pressing_seen.pop(sim_id, None)
    _failed_actions.pop(sim_id, None)
    _last_request.pop(sim_id, None)
    for key in [k for k in _logged if k[1] == sim_id]:
        _logged.pop(key, None)
    _cancel_wake(sim_id)
    npc_llm.mark_active(sim_id, False)


def _evaluate_rules(sim_info, ruleset):
    """(choice, notes, candidates) for the lot as it is right now, without pushing anything.

    `available` is what the lot offers plus the curated activity keys the game layer knows
    how to start (paint, shower, pay bills...), minus anything the game recently refused."""
    sim = sim_info.get_sim_instance()
    if sim is None:
        return None, [], []
    candidates, _objects = _collect_candidates(sim)
    refused = _recently_failed(sim.id)
    available = [c.label for c in candidates]
    extra = (sorted(ACTIVITIES) + sorted(NEED_ACTIVITY_NAMES)
             + sorted(EVERYDAY_ACTIVITY_NAMES) + sorted(PHONE_ACTIVITIES))
    for label in extra:
        if label not in refused and label not in available:
            available.append(label)
    notes = []
    choice = npc_rules.evaluate(ruleset, _describe(sim_info), available, notes)
    return choice, notes, candidates


def _apply_rules(sim_info, ruleset, report=None):
    """Let the JSON rules decide for this sim. Returns True when a rule handled the sim;
    False when nothing matched, so the routine/LLM below still gets its turn."""
    sim_id = sim_info.sim_id
    try:
        choice, notes, candidates = _evaluate_rules(sim_info, ruleset)
        for note in notes:
            npc_log.log("rules for sim {}: {}".format(sim_id, note))
        if choice is None:
            if not notes:
                _say(report, "  sim {}: no rule matches right now".format(sim_id))
            return False
        # A new choice replaces whatever we were watching.
        _active_task.pop(sim_id, None)
        _task_deadline.pop(sim_id, None)
        _candidates[sim_id] = candidates
        name = ruleset.get("name") or ruleset.get("source") or "rules"
        if choice.action is None:
            _say(report, "  sim {}: {} rule {} says do nothing for {} ({})".format(
                sim_id, name, choice.number, format_minutes(choice.minutes),
                choice.reason or "leave it to the game"))
            _defer(sim_id, choice.minutes)
            return True
        _say(report, "  sim {}: {} rule {} -> {} for {} ({})".format(
            sim_id, name, choice.number, choice.action, format_minutes(choice.minutes),
            choice.reason or "no reason given"))
        if _do_action(sim_info, sim_id, choice.action, choice.reason, report):
            _defer(sim_id, choice.minutes)
            return True
        # The game refused it. A candidate label is already blacklisted by the push; a
        # curated activity is not, so remember that here. The next decision skips both.
        if not any(candidate.label == choice.action for candidate in candidates):
            _record_failure(sim_id, choice.action)
        _say(report, "  sim {}: the game would not start {!r} - checking again soon".format(
            sim_id, choice.action), level="WARN")
        _defer(sim_id, FAILED_WAIT_MINUTES)
        return True
    except Exception:
        npc_log.log_exception("applying the JSON rules for sim {}".format(sim_id))
        return False


def _ask_llm(sim_info, report, allow_request=True, retries=3):
    sim_id = sim_info.sim_id
    if npc_llm.is_pending(sim_id):
        _say(report, "  sim {}: waiting for the LLM's answer".format(sim_id))
        return
    if _game_paused():
        # Nothing to decide while time is frozen; come back shortly after it runs again.
        _say(report, "  sim {}: the game is paused - will ask when it runs".format(sim_id))
        _next_ask.pop(sim_id, None)
        _schedule_wake(sim_id, 1)
        return
    try:
        sim = sim_info.get_sim_instance()
        candidates, objects = _collect_candidates(sim) if sim is not None else ([], [])
        actions = [c.label for c in candidates]
        if not actions:
            _say(report, "  sim {}: nothing on this lot to choose from".format(sim_id), level="WARN")
            return
        # A new choice replaces whatever we were watching.
        _active_task.pop(sim_id, None)
        _task_deadline.pop(sim_id, None)
        desc = _describe(sim_info)
        goal = npc_llm.goal_for(sim_id)
        all_actions = list(actions)
        # Judge the goal against everything the lot offers, before any narrowing below.
        # Two different things: something the lot does not have at all (ask the player), and
        # something it has but cannot start right now (tell the model, work on the wants).
        missing_names = missing_for_goal(goal, actions, objects)
        blocked_names = missing_for_goal(goal, actions) if not missing_names else []
        needed = describe_missing(missing_names)
        blocked = describe_missing(blocked_names)
        if blocked_names:
            _explain_blocked(sim, blocked_names)
        _needed[sim_id] = needed
        _needed_examples[sim_id] = examples_for(missing_names)
        if missing_names:
            # Ask the player ourselves (once an hour per gap); the model then just picks
            # something ordinary to do.
            _ask_for_goal(sim_info, goal, missing_names, report)
        if desc.get("pressing"):
            # The lowest need comes before everything else: offer only what addresses it, so
            # the model cannot pick something else.
            entry, urgent = lowest_need_actions(desc["pressing"], actions)
            if urgent:
                _say(report, "  sim {}: lowest need is {} - only that".format(sim_id, entry))
                actions = urgent
                # ... but a need is not served by a one-item list: the model then picks the
                # "do nothing" line (2026-10-27: 39 of 61 decisions). Put the reliable
                # self-care action in front and top the list up when it is still thin.
                activity = need_activity_for(entry)
                if activity and activity not in actions:
                    actions = [activity] + actions
                if len(actions) < MIN_NEED_CHOICES:
                    actions = actions + [a for a in all_actions if a not in actions]
            else:
                # Nothing on the lot matched the need. The game's own autonomy left Hygiene at
                # 0 for three sim days, so try the need ourselves before handing it over.
                activity = need_activity_for(entry)
                pushed = _push_need_activity(sim, activity, report) if activity else None
                if pushed is not None:
                    _say(report, "  sim {}: nothing offered for {} - started {!r} ourselves"
                         .format(sim_id, entry, activity), level="WARN",
                         once=("pressing", sim_id))
                    _active_task[sim_id] = pushed
                    try:
                        _task_started[sim_id] = float(
                            services.time_service().sim_timeline.now.absolute_days())
                    except Exception:
                        pass
                    _schedule_start_check(sim_id, activity)
                    _defer(sim_id, NEED_ACTIVITY_MINUTES)
                    return
                if activity == "chat" and _invite_someone_over(sim, report):
                    # Nobody to talk to and the phone had nothing direct: ask a friend over.
                    _say(report, "  sim {}: nobody to talk to - invited someone over"
                         .format(sim_id), level="WARN", once=("pressing", sim_id))
                    _defer(sim_id, NEED_ACTIVITY_MINUTES)
                    return
                _say(report, "  sim {}: {} and nothing here addresses it - leaving it to the "
                             "game".format(sim_id, ", ".join(desc["pressing"])), level="WARN",
                     once=("pressing", sim_id))
                _defer(sim_id, FAILED_WAIT_MINUTES)
                return
        else:
            # Nothing urgent: a shower when hygiene is 98 or food when hunger is full is a
            # wasted pick, so those options are removed outright (the game's own autonomy
            # still handles them if they become relevant).
            full = {name.lower() for name, value in desc["needs"].items()
                    if value >= SATISFIED_NEED}
            actions = without_satisfied(actions, full)
        # Offer the curated activity for the goal (what `houserules.npc.try paint` pushes and
        # which is known to start), even if the dynamic list filtered every variant of it.
        # Not while a need is pressing: that list is about the need.
        goal_activity = activity_for_goal(goal)
        if goal_activity and goal_activity not in actions and not desc.get("pressing"):
            actions = [goal_activity] + actions
        if not desc.get("pressing"):
            # The prompt tells the model a current want is priority 3, so the want's own
            # actions have to be in the list (they were only ever mentioned in the text).
            wants = actions_for_wants(desc.get("wants"), actions)
            if wants:
                actions = [a for a in wants if a not in actions] + actions
            # Everyday jobs the lot has an object for (fridge, mailbox, computer), last in
            # the list: there when the model wants them, never ahead of a need/goal/want.
            everyday = [a for a in everyday_actions(objects) if a not in actions]
            if everyday:
                actions = actions + everyday
            if not desc.get("nearby"):
                # Nobody else on the lot: reaching out is the social option. The phone's own
                # "who?" menu is a picker, so both go through the direct paths in
                # _push_phone / _invite_someone_over.
                for label in sorted(PHONE_ACTIVITIES):
                    if label not in actions:
                        actions.append(label)
        turn = _ask_turns.get(sim_id, 0) + 1
        _ask_turns[sim_id] = turn
        if goal and not desc.get("pressing") and turn % GOAL_TURN_EVERY == 0:
            # A small model will happily spend every hour on fishing and collecting. Every few
            # decisions, offer only what moves the goal forward.
            goal_actions = actions_for_goal(goal, actions)
            if goal_actions:
                _say(report, "  sim {}: goal turn ({} options)".format(sim_id, len(goal_actions)))
                actions = goal_actions
        if not actions:
            # Everything left only served needs that are already fine: let the game's own
            # autonomy run instead of spending a model call on "do nothing".
            _say(report, "  sim {}: nothing worth doing right now".format(sim_id))
            _defer(sim_id, FAILED_WAIT_MINUTES)
            return
        prompt, options = build_prompt(
            desc, npc_llm.instructions_for(sim_id),
            actions, goal=goal, objects=objects[:MAX_OBJECTS_SHOWN],
            allow_request=allow_request and not missing_names, missing=needed,
            blocked=blocked)
        # Tell the start-llm watcher a model is wanted now (it loads it if it isn't running).
        _logged.pop(("wake", sim_id), None)     # a real decision is always worth its line
        npc_llm.mark_active(sim_id)
        npc_llm.ask(sim_id, prompt, options)
        _candidates[sim_id] = candidates
        _retries_left[sim_id] = retries
        # Hold the sim back until the answer is in, then until the answer's own wait is over.
        now = services.time_service().sim_timeline.now
        _next_ask[sim_id] = float(now.absolute_days()) + ASK_COOLDOWN_MINUTES / 1440.0
        # Log the situation, not every option: the list is one `npc.actions` away, and this
        # line is repeated every decision. The full prompt stays in npc.think.
        npc_log.log("asked the LLM for sim {} ({} options):\n{}".format(
            sim_id, len(options), prompt_summary(prompt)))
        _say(report, "  sim {}: asked the LLM what to do ({} options)".format(sim_id, len(options)))
        _schedule_answer_poll()
        # Safety net: the real-time poll does not tick while the game is paused (Buy/Build
        # mode), so also wake on the sim clock. It fires shortly after unpausing even if the
        # poll alarm was lost.
        _schedule_wake(sim_id, 1, say=False)
    except Exception:
        npc_log.log_exception("asking the LLM for sim {}".format(sim_id))


def _ask_now(sim_info, report=None):
    """Ask straight away (after a new goal/description), ignoring the rate limit."""
    _next_ask.pop(sim_info.sim_id, None)
    _ask_llm(sim_info, report)


def _schedule_answer_poll(seconds=2, attempts=30):
    """Apply the answer on the game's thread shortly after the request finishes, instead of
    waiting up to an hour for the next tick. Retries while the request is still in flight."""
    global _poll_left
    _poll_left = max(_poll_left, attempts)
    _add_poll_alarm(seconds)


def _add_poll_alarm(seconds):
    zone = _zone
    if zone is None:
        try:
            zone = services.current_zone()
        except Exception:
            zone = None
    if zone is None:
        npc_log.log("no zone for the LLM answer poll", level="WARN")
        return
    try:
        # Real time, not sim time: this only waits for the local server to answer, and it
        # must keep ticking the same way whether the game is paused or on 3x speed.
        alarms.add_alarm_real_time(zone, interval_in_real_seconds(seconds), _poll_answers)
    except Exception:
        npc_log.log_exception("scheduling the LLM answer poll")


def _game_paused():
    """True while the player has the game paused: sim time is frozen, so nothing should be
    decided or pushed until it runs again."""
    try:
        clock = services.game_clock_service()
        return clock is not None and clock.clock_speed == ClockSpeedMode.PAUSED
    except Exception:
        npc_log.log_exception("reading the clock speed")
        return False


def _poll_answers(*_args, **_kwargs):
    global _poll_left
    try:
        _apply_llm_answers()
    except Exception:
        npc_log.log_exception("applying the LLM's answer")
        _poll_left = 0
        return
    # Keep polling while a request is running *or* an answer is waiting: the worker can finish
    # between the drain above and this check, and stopping then would leave the answer
    # unapplied until the next sim-time tick (an hour).
    if _poll_left > 0 and (npc_llm.pending_ids() or npc_llm.has_answers()):
        _poll_left -= 1
        _add_poll_alarm(POLL_SECONDS)
    else:
        _poll_left = 0


def _apply_llm_answers(report=None):
    # No pause check here: an answer already in flight is queued on the sim and simply starts
    # when the game runs again. Holding it meant going into Buy/Build mode looked like a hang.
    for sim_id, action, minutes, reason, error in npc_llm.take_answers():
        sim_info = services.sim_info_manager().get(sim_id)
        if error:
            _say(report, "LLM for sim {}: {}".format(sim_id, error), level="WARN")
            if sim_info is not None:
                _warn_llm_down(sim_info, error)
            # Never leave the sim standing around: the routine is still a valid answer, and
            # without one a random real option is better than an hour of nothing.
            if not (sim_info is not None and _random_fallback(sim_info, sim_id, report)):
                _fall_back_to_routine(sim_id, report)
            _defer(sim_id, ASK_COOLDOWN_MINUTES)
            continue
        minutes = clamp_minutes(minutes)
        _say(report, "LLM for sim {}: {} for {} ({})".format(
            sim_id, action, format_minutes(minutes), reason))
        if sim_info is not None:
            if action == REQUEST_ACTION:
                _request_object(sim_info, reason, report)
                # Asking is not doing: ask again straight away, with the request option
                # removed, so the sim picks something they can actually do right now.
                _ask_llm(sim_info, report, allow_request=False,
                         retries=_retries_left.get(sim_id, 1))
                continue
            if action not in (None, NONE_ACTION):
                if not _do_action(sim_info, sim_id, action, reason, report):
                    # The game refused it (e.g. a butler duty tuned onto the TV): that label
                    # is now on the refused list, so asking again picks a real action instead
                    # of leaving the sim standing.
                    left = _retries_left.get(sim_id, 0)
                    if left > 0:
                        _say(report, "  sim {}: asking again, without that option".format(sim_id))
                        _ask_llm(sim_info, report, allow_request=False, retries=left - 1)
                        continue
                    # Nothing worked: start something ourselves; only wait if even that fails.
                    sim = sim_info.get_sim_instance() if sim_info is not None else None
                    if sim is not None and _try_any_candidate(sim, sim_id, report):
                        _defer(sim_id, minutes)
                    else:
                        _defer(sim_id, FAILED_WAIT_MINUTES)
                    continue
        # The model said how long this should last; ask again when it is over.
        _defer(sim_id, minutes)


def _do_action(sim_info, sim_id, action, reason, report=None):
    sim = sim_info.get_sim_instance()
    if sim is None:
        return False
    candidate = next((c for c in _candidates.get(sim_id, ()) if c.label == action), None)
    pushed = None
    if candidate is not None:
        ok, pushed = _push_candidate(sim, candidate, report)
        if not ok:
            # "fishing bait hook" needs bait; the same spot can still just be fished. Before
            # bothering the model again, try what else that object offers.
            other = _try_other_on_same_object(sim, sim_id, candidate, report)
            if other is not None:
                candidate, ok, pushed = other
                action = candidate.label
        if ok:
            _active_task[sim_id] = pushed
            try:
                _task_started[sim_id] = float(
                    services.time_service().sim_timeline.now.absolute_days())
            except Exception:
                pass
    elif action in ACTIVITIES or action in NEED_ACTIVITY_NAMES \
            or action in EVERYDAY_ACTIVITY_NAMES or action in PHONE_ACTIVITIES:
        ok = _push_activity(sim, action, report)
        if ok:
            _active_task[sim_id] = None
    else:
        _say(report, "  sim {}: chose {!r}, which is not on this lot any more".format(
            sim_id, action), level="WARN")
        ok = False
    if ok:
        if pushed is not None:
            _schedule_start_check(sim_id, action)
        if reason and npc_llm.data().get("notify", True):
            _notify(sim_info, "{} is going to {}".format(sim_info.first_name, action), reason)
    else:
        # Try the routine so the sim is not left standing around.
        _fall_back_to_routine(sim_id, report)
    return ok


def _try_other_on_same_object(sim, sim_id, failed, report=None):
    """The game refused one interaction on an object; try the other things that object
    offers (bait hook -> plain fishing, a picker -> the direct version). Returns
    (candidate, ok, pushed) for the first one that starts, or None."""
    target = failed.target
    for candidate in _candidates.get(sim_id, ()):
        if candidate is failed or candidate.affordance is None or candidate.target is not target:
            continue
        if candidate.label in _recently_failed(sim_id):
            continue
        ok, pushed = _push_candidate(sim, candidate, report)
        if ok:
            _say(report, "  sim {}: that object offers {!r} instead - taking it".format(
                sim_id, candidate.label))
            return candidate, ok, pushed
    return None


def _push_candidate(sim, candidate, report=None):
    """Pushes one of the interactions offered to the LLM, trying the label's other variants
    when the first is refused (sitting on one sofa can need a buff another does not).

    Returns (pushed, affordance) - the affordance is what `_task_is_running` watches for."""
    if candidate.affordance is None:     # a starter activity, used when the lot offers nothing
        return _push_activity(sim, candidate.label, report), None
    for index, (affordance, target) in enumerate(candidate.variants()):
        if _needs_arguments(affordance):
            # A variant can be a crafting staging step ("counter make food basic"): the game
            # accepts the push and then fails to instantiate it, which writes a desync to
            # lastException. Never try those.
            continue
        try:
            context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.Low)
            result = sim.push_super_affordance(affordance, target, context)
            _say(report, "  {} on {}: result={!r}".format(
                candidate.label, target, result) + ("" if index == 0 else " (variant {})".format(index + 1)))
            if result:
                return True, affordance
        except Exception:
            npc_log.log_exception("pushing {} on {}".format(candidate.label, target))
    # Every variant was refused: keep it out of the next prompt for a while.
    _record_failure(sim.id, candidate.label)
    return False, None


def _pronoun(sim_info):
    """she/he, for the notification; 'they' when the game does not say."""
    try:
        gender = getattr(getattr(sim_info, "gender", None), "name", "").upper()
        return {"MALE": "he", "FEMALE": "she"}.get(gender, "they")
    except Exception:
        return "they"


def _request_text(sim_info, need):
    """'Grace wants to gather plants for her garden. Do you have a planter box she could use?'"""
    wish = (need or "").strip().rstrip(".")
    first = getattr(sim_info, "first_name", "") or "They"
    if wish and not wish.lower().startswith(first.lower()):
        wish = "{} {}".format(first, wish)
    body = (wish + ".") if wish else "{} needs something this lot does not have.".format(first)
    examples = _needed_examples.get(sim_info.sim_id) or []
    if examples:
        return "{} Do you have {} {} could use?".format(body, examples[0], _pronoun(sim_info))
    return "{} Is there anything you could add for that?".format(body)


def _ask_for_goal(sim_info, goal, missing, report=None):
    """The goal cannot be worked on with anything here: ask the player for it directly,
    instead of leaving it to the model to pick the ask option (it usually does not)."""
    need = "wants to work on the goal{}, but nothing on this lot can be used for {}".format(
        " ({})".format(goal) if goal else "", ", ".join(missing))
    _request_object(sim_info, need, report, key="goal:" + ",".join(sorted(missing)))


def _request_object(sim_info, reason, report=None, key=None):
    """Ask the player for something this lot does not have."""
    need = (reason or "").strip() or "something this lot does not have"
    # The model's reason often repeats the option label ("ask the player for an easel...");
    # the log line already says "asks the player for", so don't say it twice.
    lowered = need.lower()
    for prefix in ("asks the player for ", "ask the player for "):
        if lowered.startswith(prefix):
            need = need[len(prefix):].lstrip()
            break
    if need.lower().startswith(("wants to ", "needs ")):
        # "wants to work on the goal, but nothing here..." already reads as a sentence.
        _say(report, "  sim {}: {}".format(sim_info.sim_id, need), level="WARN")
    else:
        _say(report, "  sim {}: asks the player for {}".format(sim_info.sim_id, need),
             level="WARN")
    if not npc_llm.data().get("notify", True):
        return
    try:
        now = float(services.time_service().sim_timeline.now.absolute_days())
    except Exception:
        now = 0.0
    previous = _last_request.get(sim_info.sim_id)
    key = key or request_key(need)
    if previous is not None and previous[0] == key and now - previous[1] < REQUEST_COOLDOWN_HOURS / 24.0:
        return      # same wish, asked less than an hour ago: don't nag the player
    _last_request[sim_info.sim_id] = (key, now)
    try:
        _notify(sim_info, "{} asks for something".format(sim_info.first_name),
                _request_text(sim_info, need))
    except Exception:
        npc_log.log_exception("asking the player for an object")


def _warn_llm_down(sim_info, error):
    """Tell the player once per session why nothing is happening, instead of failing silently."""
    global _llm_error_notified
    if _llm_error_notified:
        return
    _llm_error_notified = True
    try:
        _notify(sim_info, "Local LLM not running",
                "The NPC brain could not reach it ({}). Start start-llm.cmd; sims use their "
                "routines until then.".format(error))
    except Exception:
        npc_log.log_exception("warning that the LLM is down")


def _random_fallback(sim_info, sim_id, report=None):
    """The model is not answering: do one of the things it was offered, picked at random.
    A sim whose brain is down should still live - a random real option beats an hour of
    standing there, which is all that used to happen when no routine was due.

    True when a candidate was chosen (pushing it falls back to the routine itself)."""
    candidates = [candidate for candidate in _candidates.get(sim_id, ())
                  if candidate.label not in _recently_failed(sim_id)]
    chosen = pick_random(candidates)
    if chosen is None:
        return False
    _say(report, "  sim {}: no answer from the model - doing {!r} at random".format(
        sim_id, chosen.label), level="WARN", once=("random", sim_id))
    _do_action(sim_info, sim_id, chosen.label, "", report)
    return True


def _fall_back_to_routine(sim_id, report=None):
    try:
        if sim_id not in _npc_mode_sim_ids:
            return
        now = services.time_service().sim_timeline.now
        activity = _store.get(sim_id).due_activity(now.day(), now.hour())
        if activity is None:
            return
        sim_info = services.sim_info_manager().get(sim_id)
        sim = sim_info.get_sim_instance() if sim_info is not None else None
        if sim is not None:
            _push_activity(sim, activity, report)
        elif sim_info is not None:
            _offlot_hour(sim_info, activity, report)
    except Exception:
        npc_log.log_exception("falling back to the routine")


def _notify(sim_info, title, text):
    try:
        from sims4.localization import LocalizationHelperTuning
        from ui.ui_dialog_notification import UiDialogNotification
        dialog = UiDialogNotification.TunableFactory().default(
            sim_info,
            title=lambda *_, **__: LocalizationHelperTuning.get_raw_text(title),
            text=lambda *_, **__: LocalizationHelperTuning.get_raw_text(text))
        dialog.show_dialog()
    except Exception:
        npc_log.log_exception("showing notification")


def _tick(*_args, quiet=False, **_kwargs):
    try:
        _run_tick(quiet=quiet)
    except Exception:
        npc_log.log_exception("npc routine tick")


def _start_alarm(zone):
    global _alarm_handle, _zone
    _zone = zone
    # Wake alarms belong to the previous zone (and its weakref may already be dead).
    _wake_handles.clear()
    # Re-created on every zone load rather than guarded to "once": an alarm's owner is
    # held by weakref (alarms.py), so an alarm owned by a previous zone may already be
    # dead by the time we get here after a zone transition. Cancelling unconditionally
    # and re-creating, owned by the current zone, avoids having to reason about exactly
    # when that weakref dies.
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


@sims4.commands.Command("houserules.npc.on", command_type=sims4.commands.CommandType.Live)
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


@sims4.commands.Command("houserules.npc.off", command_type=sims4.commands.CommandType.Live)
def npc_off(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_id = _resolve_sim_id(opt_sim, _connection)
    if sim_id is None:
        output("No sim found (select one or pass a sim id).")
        return
    _ensure_loaded()
    _npc_mode_sim_ids.discard(sim_id)
    _forget(sim_id)
    _save_npc_mode()
    output("NPC routine mode off for sim {}.".format(sim_id))
    npc_log.log("npc.off sim {}".format(sim_id))


@sims4.commands.Command("houserules.routine.add", command_type=sims4.commands.CommandType.Live)
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


@sims4.commands.Command("houserules.routine.show", command_type=sims4.commands.CommandType.Live)
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


@sims4.commands.Command("houserules.npc.tick", command_type=sims4.commands.CommandType.Live)
def npc_tick(_connection=None):
    """Runs the hourly check right now and prints what it decided."""
    output = sims4.commands.CheatOutput(_connection)
    try:
        _run_tick(report=output)
    except Exception:
        npc_log.log_exception("npc.tick")
        output("npc.tick failed - see the log.")


@sims4.commands.Command("houserules.npc.find", command_type=sims4.commands.CommandType.Live)
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


@sims4.commands.Command("houserules.npc.clubs", command_type=sims4.commands.CommandType.Live)
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


@sims4.commands.Command("houserules.npc.try", command_type=sims4.commands.CommandType.Live)
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


@sims4.commands.Command("houserules.npc.actions", command_type=sims4.commands.CommandType.Live)
def npc_actions(opt_sim: OptionalSimInfoParam = None, _connection=None):
    """What the LLM is offered for this sim right now, and the objects on the lot."""
    output = sims4.commands.CheatOutput(_connection)
    sim_info = get_optional_target(opt_sim, _connection, target_type=OptionalSimInfoParam)
    sim = sim_info.get_sim_instance() if sim_info is not None else None
    if sim is None:
        output("No sim on this lot (select one who is here).")
        return
    try:
        candidates, objects = _collect_candidates(sim)
    except Exception:
        npc_log.log_exception("npc.actions")
        output("npc.actions failed - see the log.")
        return
    output("On the lot: {}".format(", ".join(objects[:MAX_OBJECTS_SHOWN]) or "nothing"))
    output("{} choices for {}:".format(len(candidates), sim_info.first_name))
    for i, candidate in enumerate(candidates, 1):
        output("  {}. {}".format(i, candidate.label))
    everyday = everyday_actions(objects)
    if everyday:
        output("Everyday jobs (offered after a need, goal or want): {}".format(
            ", ".join(everyday)))
    output("  {}. {}".format(len(candidates) + 1, REQUEST_ACTION))
    output("  {}. do nothing special (normal life)".format(len(candidates) + 2))


@sims4.commands.Command("houserules.npc.checks", command_type=sims4.commands.CommandType.Live)
def npc_checks(text: str, opt_sim: OptionalSimInfoParam = None, _connection=None):
    """Why an interaction is or is not offered: every filter, for names containing <text>
    (e.g. houserules.npc.checks easel)."""
    output = sims4.commands.CheatOutput(_connection)
    sim_info = get_optional_target(opt_sim, _connection, target_type=OptionalSimInfoParam)
    sim = sim_info.get_sim_instance() if sim_info is not None else None
    if sim is None:
        output("No sim on this lot (select one who is here).")
        return
    needle = text.lower()
    shown = 0
    output("Codes: label filtered = reads as tuning noise; not a life action = no action word "
           "or too long; needs arguments = we cannot create it; debug/cheat/hidden = not for "
           "players; fails its own tests = the game says not right now.")
    try:
        for obj in _objects_by_distance(sim):
            for affordance in _affordances_of(obj):
                if needle not in affordance.__name__.lower():
                    continue
                label = clean_label(affordance.__name__)
                reasons = []
                if not is_usable(label):
                    reasons.append("label filtered")
                if not is_action(label):
                    reasons.append("not a life action")
                if _needs_arguments(affordance):
                    reasons.append("needs arguments we cannot supply")
                if is_internal(getattr(affordance, "debug", False),
                               getattr(affordance, "cheat", False),
                               getattr(affordance, "visible", True)):
                    reasons.append("debug/cheat/hidden")
                if not _passes_its_own_tests(sim, affordance, obj):
                    reasons.append("fails its own tests")
                _say(output, "  {} on {}: {}".format(
                    affordance.__name__, obj, "; ".join(reasons) or "OK - offered"))
                shown += 1
                if shown >= 25:
                    _say(output, "  ... stopping after 25")
                    return
    except Exception:
        npc_log.log_exception("npc.checks")
        output("npc.checks failed - see the log.")
        return
    if not shown:
        output("Nothing on this lot offers an interaction containing {!r}.".format(text))


@sims4.commands.Command("houserules.routine.clear", command_type=sims4.commands.CommandType.Live)
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
