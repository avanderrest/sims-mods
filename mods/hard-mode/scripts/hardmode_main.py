"""Hard Mode: Careers - game layer.

Rule (hardmode_careers.py): a new full-time job needs the career's skills, or a finished
degree that waives them. Checked when the player picks a job in the "Find a Job" screen,
which sends the careers.select command - so we wrap that one command. It only runs for
player choices: save loading, NPC story progression, business employees, etc. add careers
by other routes and are never touched.

Getting fired: missed work days are counted (CareerBase._collect_rewards); enough of them
gets the sim fired, and after any firing employers won't hire them for a few days.

Settings (all of Hard Mode's are in hardmode_settings.py):
  careers on|off  - evaluate the rule (hard.check, and a log line on every job pick)
  enforce on|off  - actually refuse a job pick that fails the rule.
  firing on|off   - missed days get sims fired; fired sims can't be hired for a while.

Cheats:
  houserules.hard.status                - every Hard Mode setting
  houserules.hard.set <setting> <value> - change one
  houserules.hard.careers on|off
  houserules.hard.enforce on|off
  houserules.hard.check <career> [sim]  - what the rule decides for that sim, and why
  houserules.hard.gates                 - which game careers/skills our table matched
"""
import services
import sims4.commands
import sims4.resources
from careers.career_enums import CareerCategory, CareerShiftType
from careers.career_ops import CareerOps
from server_commands import career_commands
from server_commands.argument_helpers import OptionalSimInfoParam, TunableInstanceParam, get_optional_target

import hardmode_log
import hardmode_state
from hardmode_careers import ALL_SKILLS, GATES, check_join, gate_for_career, qualification_degree_names
from hardmode_settings import DEFAULT_SETTINGS
from hardmode_work import FIRED_COOLDOWN_DAYS, MISSED_DAYS_TO_FIRE, WorkRecord

_settings = hardmode_state.settings
_ensure_loaded = hardmode_state.ensure_settings
_save = hardmode_state.save_settings
_skill_types = None  # skill name (e.g. "Logic") -> skill statistic class

_WORK_FILE = "hard_mode_work.json"
_work = None


def _work_record():
    global _work
    if _work is None:
        _work = WorkRecord(hardmode_state.load_json(_WORK_FILE, {}))
    return _work


def _resolve_skills():
    """Finds each skill in ALL_SKILLS by the end of its tuning name, preferring the adult
    skill (statistic_Skill_AdultMajor_Logic) over child/teen/toddler ones."""
    global _skill_types
    if _skill_types is None:
        found = {}
        stats = services.get_instance_manager(sims4.resources.Types.STATISTIC).types.values()
        for cls in stats:
            name = cls.__name__.lower()
            if "skill" not in name:
                continue
            for skill in ALL_SKILLS:
                if name.endswith("_" + skill.lower()):
                    best = found.get(skill)
                    if best is None or ("adult" in name and "adult" not in best.__name__.lower()):
                        found[skill] = cls
        _skill_types = found
        hardmode_log.log("skills resolved: {}".format({k: v.__name__ for k, v in sorted(found.items())}))
        unresolved = sorted(set(ALL_SKILLS) - set(found))
        if unresolved:
            hardmode_log.log("skills NOT found (their gates count as level 0): {}".format(unresolved), level="WARN")
    return _skill_types


def _skill_levels(sim_info):
    levels = {}
    for skill, skill_type in _resolve_skills().items():
        try:
            # add=False: reading must never give the sim a skill they don't have.
            stat = sim_info.get_statistic(skill_type, add=False)
            levels[skill] = int(stat.get_user_value()) if stat is not None else 0
        except Exception:
            hardmode_log.log_exception("reading skill {}".format(skill))
    levels["Fame"] = _fame_stars(sim_info)
    return levels


def _fame_stars(sim_info):
    """Celebrity star level (Get Famous); 0 without the pack or without fame."""
    try:
        from fame.fame_tuning import FameTunables
        fame_type = FameTunables.FAME_RANKED_STATISTIC
        if fame_type is None:
            return 0
        stat = sim_info.commodity_tracker.get_statistic(fame_type)  # no add: read only
        return int(stat.rank_level) if stat is not None else 0
    except Exception:
        hardmode_log.log_exception("reading fame")
        return 0


def _finished_degrees(sim_info):
    tracker = getattr(sim_info, "degree_tracker", None)
    if tracker is None:
        return []
    majors = services.get_instance_manager(sims4.resources.Types.UNIVERSITY_MAJOR)
    names = []
    for degree_id in tracker.previous_majors or ():
        degree = majors.get(degree_id)
        if degree is not None:
            names.append(degree.__name__)
    return names


def _qualifications(sim_info):
    """Flexible University Certificates and Associate Degrees for this Sim.

    They are recorded by that mod rather than as a full degree, but for the career gate
    they count exactly like one: the Sim has already proven they can do university work.
    """
    return hardmode_state.university_credentials(sim_info.sim_id)


def _evaluate(sim_info, career_type):
    """Returns (blocked, reason, details) for this sim newly joining career_type."""
    _ensure_loaded()
    is_full_time = getattr(career_type, "career_category", None) == CareerCategory.Work
    already = any(getattr(c, "guid64", None) == career_type.guid64
                  for c in sim_info.career_tracker.careers.values())
    skills = _skill_levels(sim_info)
    degrees = _finished_degrees(sim_info)
    qualifications = _qualifications(sim_info)
    # A qualification's "major" is the same degree tuning name a finished degree has, so
    # the existing per-career waiver table and "any degree" rule both keep working.
    credentials = qualification_degree_names(qualifications)
    blocked, reason = check_join(career_type.__name__, is_full_time, skills, degrees + credentials,
                                 already, enabled=_settings.get("careers"))
    details = {"career": career_type.__name__, "gate": gate_for_career(career_type.__name__),
               "full_time": is_full_time, "already_in_it": already,
               "skills": {k: v for k, v in skills.items() if v}, "finished_degrees": degrees,
               "qualifications": ["{} ({})".format(q.get("label") or q.get("tier"), q["major"])
                                  for q in qualifications]}
    return blocked, reason, details


_sim_name = hardmode_state.sim_name


def _notify(sim_info, title, text):
    hardmode_state.notify(title, text, sim_info)


# --- The job-picker hook --------------------------------------------------------------
_original_select_career = career_commands.select_career


def _is_join(reason):
    try:
        return int(reason) == int(CareerOps.JOIN_CAREER)
    except Exception:
        return False


# Same parameters AND type annotations as EA's careers.select. The command system converts
# the Find a Job screen's text arguments to numbers only for parameters annotated `int`.
# The decompiled source shows no annotations, but EA's bytecode has them (checked
# 2026-10-09); the first version of this hook copied the decompiled signature, so EA's
# function received text ids, found nothing, and every job pick silently failed.
def _select_career(sim_id: int = None, career_instance_id: int = None, track_id: int = None,
                   level: int = None, company_name_hash: int = None, reason: int = CareerOps.JOIN_CAREER,
                   schedule_shift_type: CareerShiftType = CareerShiftType.ALL_DAY, _connection=None):
    try:
        if _is_join(reason) and sim_id is not None and career_instance_id is not None:
            sim_info = services.sim_info_manager().get(int(sim_id))
            career_type = services.get_instance_manager(sims4.resources.Types.CAREER).get(int(career_instance_id))
            if sim_info is not None and career_type is not None:
                blocked, why, details = _evaluate(sim_info, career_type)
                if not blocked and details["full_time"] and not details["already_in_it"] and _settings.get("firing"):
                    left = _work_record().cooldown_left(sim_info.sim_id, hardmode_state.sim_today())
                    if left > 0:
                        blocked = True
                        why = "was fired recently; employers won't hire them for another {:.1f} sim day(s)".format(left)
                enforce = _settings.get("enforce")
                hardmode_log.log("job pick: {} -> {}: blocked={} enforce={} ({}) {}".format(
                    _sim_name(sim_info), career_type.__name__, blocked, enforce, why, details))
                if blocked and enforce:
                    _notify(sim_info, "Not qualified yet",
                            "{} can't get this job yet: {}.".format(sim_info.first_name, why))
                    return False
    except Exception:
        hardmode_log.log_exception("careers.select hook (EA's version runs as normal)")
    result = _original_select_career(sim_id, career_instance_id, track_id, level, company_name_hash,
                                     reason=reason, schedule_shift_type=schedule_shift_type,
                                     _connection=_connection)
    hardmode_log.log("careers.select passed to EA: sim={!r} career={!r} track={!r} level={!r} reason={!r} -> {!r}".format(
        sim_id, career_instance_id, track_id, level, reason, result))
    return result


# Take the annotations from EA's own function too, in case a patch changes them.
_select_career.__annotations__.update(getattr(_original_select_career, "__annotations__", {}) or {})

try:
    sims4.commands.Command("careers.select", command_type=sims4.commands.CommandType.Live)(_select_career)
    hardmode_log.log("careers.select hook installed")
except Exception:
    hardmode_log.log_exception("installing careers.select hook")


# --- Getting fired ---------------------------------------------------------------------
# EA's CareerBase._collect_rewards runs once at the end of every work day of a player sim
# (also for days they never showed up: time_at_work is 0 then). We count the day as missed
# when they were there for less than half of it; enough missed days -> fired. Every firing
# (ours or the game's own, for bad performance) goes through CareerBase._fire, which we
# wrap only to remember the date for the "employers won't hire you yet" cooldown.
from careers.career_base import CareerBase

_original_collect_rewards = CareerBase._collect_rewards
_original_fire = CareerBase._fire


def _collect_rewards(self, time_at_work, *args, **kwargs):
    share = None
    try:
        if _settings.get("firing") and getattr(self, "career_category", None) == CareerCategory.Work                 and self._sim_info.is_selectable:
            hours = self.get_current_work_duration_in_hours()
            share = (time_at_work / hours) if hours else 1.0
    except Exception:
        hardmode_log.log_exception("reading the work day")
    result = _original_collect_rewards(self, time_at_work, *args, **kwargs)
    if share is not None:
        try:
            _after_work_day(self, share)
        except Exception:
            hardmode_log.log_exception("counting a missed work day")
    return result


def _after_work_day(career, share):
    import alarms
    from date_and_time import create_time_span
    sim_info = career._sim_info
    record = _work_record()
    today = hardmode_state.sim_today()
    fire = record.record_day(sim_info.sim_id, type(career).__name__, share, today)
    missed = record.missed_days(sim_info.sim_id, type(career).__name__, today)
    hardmode_state.save_json(_WORK_FILE, record.to_dict())
    hardmode_log.log("work day: {} {} at work {:.0%}, missed days this week: {}{}".format(
        _sim_name(sim_info), type(career).__name__, share, missed, " -> FIRED" if fire else ""))
    if fire:
        # Fire a moment later, after the game has finished closing the work day.
        alarms.add_alarm(career, create_time_span(minutes=5), lambda _: _fire_now(career))
    elif missed == MISSED_DAYS_TO_FIRE - 1 and share < 1:
        _notify(sim_info, "Warning from work",
                "{} has missed {} work days this week. One more and they'll be fired.".format(
                    sim_info.first_name, missed))


def _fire_now(career):
    try:
        sim_info = career._sim_info
        if career.guid64 not in sim_info.career_tracker.careers:
            return
        hardmode_log.log("firing {} from {} for missed work".format(_sim_name(sim_info), type(career).__name__))
        _notify(sim_info, "Fired",
                "{} missed too many work days and has been fired. Other employers won't hire them for {} days."
                .format(sim_info.first_name, FIRED_COOLDOWN_DAYS))
        career.fire()
    except Exception:
        hardmode_log.log_exception("firing for missed work")


def _fire(self, *args, **kwargs):
    try:
        sim_info = self._sim_info
        if sim_info.is_selectable and getattr(self, "career_category", None) == CareerCategory.Work:
            _work_record().record_fired(sim_info.sim_id, type(self).__name__, hardmode_state.sim_today())
            hardmode_state.save_json(_WORK_FILE, _work_record().to_dict())
            hardmode_log.log("{} was fired from {}".format(_sim_name(sim_info), type(self).__name__))
    except Exception:
        hardmode_log.log_exception("recording a firing")
    return _original_fire(self, *args, **kwargs)


CareerBase._collect_rewards = _collect_rewards
CareerBase._fire = _fire
hardmode_log.log("firing hooks installed")


# --- Cheats --------------------------------------------------------------------------
def _set_from_cheat(key, state, output):
    if state not in ("on", "off"):
        output("Usage: houserules.hard.{} on|off".format(key))
        return
    _ensure_loaded()
    _settings.set(key, state == "on")
    _save()
    output("Hard Mode: {} is now {}.".format(key, state))


@sims4.commands.Command("houserules.hard.careers", command_type=sims4.commands.CommandType.Live)
def hard_careers(state: str, _connection=None):
    _set_from_cheat("careers", state, sims4.commands.CheatOutput(_connection))


@sims4.commands.Command("houserules.hard.enforce", command_type=sims4.commands.CommandType.Live)
def hard_enforce(state: str, _connection=None):
    _set_from_cheat("enforce", state, sims4.commands.CheatOutput(_connection))


@sims4.commands.Command("houserules.hard.status", command_type=sims4.commands.CommandType.Live)
def hard_status(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    _ensure_loaded()
    parts = []
    for key in DEFAULT_SETTINGS:
        value = _settings.get(key)
        parts.append("{} = {}".format(key, ("on" if value else "off") if _settings.is_switch(key) else value))
    output("Hard Mode: " + ", ".join(parts))
    output("Change one with: houserules.hard.set <setting> on|off (start_funds takes a number)")


@sims4.commands.Command("houserules.hard.set", command_type=sims4.commands.CommandType.Live)
def hard_set(key: str = "", value: str = "", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    _ensure_loaded()
    if key not in DEFAULT_SETTINGS:
        output("Settings: {}".format(", ".join(DEFAULT_SETTINGS)))
        return
    try:
        if _settings.is_switch(key):
            if value not in ("on", "off"):
                output("Usage: houserules.hard.set {} on|off".format(key))
                return
            _settings.set(key, value == "on")
        else:
            _settings.set(key, int(value))
    except ValueError:
        output("{} needs a number".format(key))
        return
    _save()
    hardmode_log.log("setting {} = {}".format(key, _settings.get(key)))
    output("Hard Mode: {} is now {}.".format(key, value))


@sims4.commands.Command("houserules.hard.check", command_type=sims4.commands.CommandType.Live)
def hard_check(career_type: TunableInstanceParam(sims4.resources.Types.CAREER),
               opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    if career_type is None:
        output("Unknown career (use the same names as careers.promote).")
        return
    sim_info = get_optional_target(opt_sim, _connection, target_type=OptionalSimInfoParam)
    if sim_info is None:
        output("No sim found (select one or pass a sim id).")
        return
    try:
        blocked, why, details = _evaluate(sim_info, career_type)
    except Exception:
        hardmode_log.log_exception("hard.check")
        output("Something went wrong - see the log.")
        return
    hardmode_log.log("hard.check {}: blocked={} ({}) {}".format(_sim_name(sim_info), blocked, why, details))
    output("{} -> {}: {}".format(sim_info.first_name, career_type.__name__, "BLOCKED" if blocked else "allowed"))
    output("  why: {}".format(why))
    output("  gate: {} | full-time: {} | already in it: {}".format(
        details["gate"], details["full_time"], details["already_in_it"]))
    output("  skills: {}".format(details["skills"] or "none"))
    output("  finished degrees: {}".format(details["finished_degrees"] or "none"))
    if details["qualifications"]:
        output("  Flexible University qualifications: {}".format(", ".join(details["qualifications"])))


@sims4.commands.Command("houserules.hard.gates", command_type=sims4.commands.CommandType.Live)
def hard_gates(_connection=None):
    """Which full-time careers in this game matched a gate, and which skills were found."""
    output = sims4.commands.CheatOutput(_connection)
    try:
        careers = services.get_instance_manager(sims4.resources.Types.CAREER).types.values()
        matched = {}
        ungated = []
        for career in careers:
            if getattr(career, "career_category", None) != CareerCategory.Work:
                continue
            key = gate_for_career(career.__name__)
            if key is None:
                ungated.append(career.__name__)
            else:
                matched.setdefault(key, []).append(career.__name__)
        skills = _resolve_skills()
    except Exception:
        hardmode_log.log_exception("hard.gates")
        output("hard.gates failed - see the log.")
        return
    lines = ["{}: {}".format(k, sorted(matched.get(k, [])) or "NO CAREER MATCHED") for k in sorted(GATES)]
    lines.append("full-time careers with no gate: {}".format(sorted(ungated)))
    lines.append("skills found: {}".format(sorted(skills)))
    for line in lines:
        output(line)
        hardmode_log.log("hard.gates " + line)
