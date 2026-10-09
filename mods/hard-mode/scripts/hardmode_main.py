"""Hard Mode: Careers - game layer.

Rule (hardmode_careers.py): a new full-time job needs the career's skills, or a finished
degree that waives them. Checked when the player picks a job in the "Find a Job" screen,
which sends the careers.select command - so we wrap that one command. It only runs for
player choices: save loading, NPC story progression, business employees, etc. add careers
by other routes and are never touched.

Two settings (bluerabbit477.hard.*):
  careers on|off  - evaluate the rule (hard.check, and a log line on every job pick)
  enforce on|off  - actually refuse a job pick that fails the rule. Default OFF, so a
                    first test only logs what it *would* do.

Cheats:
  bluerabbit477.hard.status
  bluerabbit477.hard.careers on|off
  bluerabbit477.hard.enforce on|off
  bluerabbit477.hard.check <career> [sim]  - what the rule decides for that sim, and why
  bluerabbit477.hard.gates                 - which game careers/skills our table matched
"""
import os

import services
import sims4.commands
import sims4.resources
from careers.career_enums import CareerCategory, CareerShiftType
from careers.career_ops import CareerOps
from server_commands import career_commands
from server_commands.argument_helpers import OptionalSimInfoParam, TunableInstanceParam, get_optional_target

import hardmode_log
from hardmode_careers import ALL_SKILLS, GATES, check_join, gate_for_career
from hardmode_settings import Settings

_SETTINGS_PATH = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts",
                              "The Sims 4", "Mods", "BlueRabbit477", "data", "hard_mode_settings.json")

_settings = Settings()
_loaded = False
_skill_types = None  # skill name (e.g. "Logic") -> skill statistic class


def _ensure_loaded():
    global _loaded
    if not _loaded:
        try:
            _settings.load(_SETTINGS_PATH)
        except Exception:
            hardmode_log.log_exception("loading settings")
        _loaded = True


def _save():
    try:
        os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
        _settings.save(_SETTINGS_PATH)
    except Exception:
        hardmode_log.log_exception("saving settings")


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


def _evaluate(sim_info, career_type):
    """Returns (blocked, reason, details) for this sim newly joining career_type."""
    _ensure_loaded()
    is_full_time = getattr(career_type, "career_category", None) == CareerCategory.Work
    already = any(getattr(c, "guid64", None) == career_type.guid64
                  for c in sim_info.career_tracker.careers.values())
    skills = _skill_levels(sim_info)
    degrees = _finished_degrees(sim_info)
    blocked, reason = check_join(career_type.__name__, is_full_time, skills, degrees, already,
                                 enabled=_settings.get("careers"))
    details = {"career": career_type.__name__, "gate": gate_for_career(career_type.__name__),
               "full_time": is_full_time, "already_in_it": already,
               "skills": {k: v for k, v in skills.items() if v}, "finished_degrees": degrees}
    return blocked, reason, details


def _sim_name(sim_info):
    return "{} {}".format(getattr(sim_info, "first_name", ""), getattr(sim_info, "last_name", "")).strip() or str(sim_info.sim_id)


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
        hardmode_log.log_exception("showing notification")


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


# --- Cheats --------------------------------------------------------------------------
def _set_from_cheat(key, state, output):
    if state not in ("on", "off"):
        output("Usage: bluerabbit477.hard.{} on|off".format(key))
        return
    _ensure_loaded()
    _settings.set(key, state == "on")
    _save()
    output("Hard Mode: {} is now {}.".format(key, state))


@sims4.commands.Command("bluerabbit477.hard.careers", command_type=sims4.commands.CommandType.Live)
def hard_careers(state: str, _connection=None):
    _set_from_cheat("careers", state, sims4.commands.CheatOutput(_connection))


@sims4.commands.Command("bluerabbit477.hard.enforce", command_type=sims4.commands.CommandType.Live)
def hard_enforce(state: str, _connection=None):
    _set_from_cheat("enforce", state, sims4.commands.CheatOutput(_connection))


@sims4.commands.Command("bluerabbit477.hard.status", command_type=sims4.commands.CommandType.Live)
def hard_status(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    _ensure_loaded()
    output("Hard Mode: careers = {}, enforce = {}".format(
        "on" if _settings.get("careers") else "off", "on" if _settings.get("enforce") else "off"))
    output("(enforce off: job picks are only logged, never refused)")


@sims4.commands.Command("bluerabbit477.hard.check", command_type=sims4.commands.CommandType.Live)
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


@sims4.commands.Command("bluerabbit477.hard.gates", command_type=sims4.commands.CommandType.Live)
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
