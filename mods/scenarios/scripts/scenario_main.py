"""Scenarios - game layer (phase 1 goals, phase 2 rules). Rules are decided in scenario_logic.py.

Scenario files: Mods/HouseRules/scenarios/<name>.json (examples are installed there by the
build; edit or add files without rebuilding). Progress per household:
Mods/HouseRules/data/scenarios_progress.json.

Every sim hour (and right after starting, and on scenario.status) the household is read into a
plain "facts" dict and scenario_logic.evaluate() decides which goals are done and whether the
scenario is won or lost. Rewards and outcomes are applied here.

Cheats:
  houserules.scenario.list              - scenario files found
  houserules.scenario.validate <name>   - check a file (and every trait/skill name in it)
  houserules.scenario.start <name>      - start it for the active household, with the
                                             selected sim as the "active" sim
  houserules.scenario.status            - goals done/open with numbers, days left
  houserules.scenario.check <goal>      - tick a custom goal by hand
  houserules.scenario.quit
"""
import json
import os

import alarms
import build_buy
import services
import sims4.commands
import sims4.resources
import zone as zone_module
from date_and_time import create_time_span
from protocolbuffers import Consts_pb2

import scenario_log
from scenario_logic import (ScenarioError, broken_rules, describe_goal, describe_rule, evaluate, goal_by_id,
                            new_progress, open_goals, parse, penalty_of, penalty_text, rule_by_id, rule_id)

_ROOT = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts", "The Sims 4", "Mods", "HouseRules")
SCENARIO_DIR = os.path.join(_ROOT, "scenarios")
_PROGRESS_PATH = os.path.join(_ROOT, "data", "scenarios_progress.json")

_progress = None      # {household_id: progress dict}
_alarm_handle = None
_CHILD_AGES = ("BABY", "INFANT", "TODDLER", "CHILD")
# max_purchase: what the household has at the start of a Build/Buy visit, and the most it
# has spent in one visit (per household id). Build/Buy itself happens in the game's C++,
# so the visit's spend is the closest we can see to a purchase.
_build_buy_start_money = None
_build_buy_spend = {}


# --- Files ---------------------------------------------------------------------------

def scenario_files():
    try:
        return sorted(f[:-5] for f in os.listdir(SCENARIO_DIR) if f.lower().endswith(".json"))
    except OSError:
        return []


def load_scenario(name):
    """Returns (scenario, warnings); raises ScenarioError if missing or broken."""
    path = os.path.join(SCENARIO_DIR, name if name.lower().endswith(".json") else name + ".json")
    if not os.path.exists(path):
        raise ScenarioError("no file {} (have: {})".format(path, ", ".join(scenario_files()) or "none"))
    with open(path, "r", encoding="utf-8") as f:
        return parse(f.read())


def _all_progress():
    global _progress
    if _progress is None:
        _progress = {}
        try:
            if os.path.exists(_PROGRESS_PATH):
                with open(_PROGRESS_PATH, "r", encoding="utf-8") as f:
                    _progress = json.load(f)
        except Exception:
            scenario_log.log_exception("loading scenarios_progress.json")
    return _progress


def _save_progress():
    try:
        os.makedirs(os.path.dirname(_PROGRESS_PATH), exist_ok=True)
        tmp = _PROGRESS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_all_progress(), f, indent=1)
        os.replace(tmp, _PROGRESS_PATH)
    except Exception:
        scenario_log.log_exception("saving scenarios_progress.json")


def _current(household):
    """(progress, scenario) for this household's running scenario, or (None, None)."""
    progress = _all_progress().get(str(household.id))
    if progress is None:
        return None, None
    try:
        scenario, _ = load_scenario(progress["scenario"])
    except Exception as e:
        scenario_log.log("household {}: can't load its scenario {}: {}".format(household.id, progress["scenario"], e),
                         level="WARN")
        return progress, None
    return progress, scenario


# --- Game names ----------------------------------------------------------------------

def _find(types, name, prefer=None):
    """A tuning class by name: exact (any case) first, else the one whose name ends with
    _<name>, preferring names containing `prefer` (e.g. adult skills over child ones)."""
    want = name.lower()
    ends = []
    for cls in types:
        cname = cls.__name__.lower()
        if cname == want:
            return cls
        if cname.endswith("_" + want):
            ends.append(cls)
    if prefer:
        ends.sort(key=lambda c: prefer not in c.__name__.lower())
    return ends[0] if ends else None


def find_trait(name):
    return _find(services.get_instance_manager(sims4.resources.Types.TRAIT).types.values(), name)


def find_skill(name):
    stats = [c for c in services.get_instance_manager(sims4.resources.Types.STATISTIC).types.values()
             if "skill" in c.__name__.lower()]
    return _find(stats, name, prefer="adult")


def _skill_short_name(cls):
    return cls.__name__.rsplit("_", 1)[-1]


def unknown_names(scenario):
    """Trait and skill names in the file that the game doesn't have (packs not owned, typos)."""
    traits, skills = set(), set()
    start = scenario.get("start", {})
    for key in ("traits", "remove_traits"):
        for names in (start.get(key) or {}).values():
            traits.update(names)
    for levels in (start.get("skills") or {}).values():
        skills.update(levels)
    for goal in scenario["goals"]:
        if goal["type"] == "skill":
            skills.add(goal["skill"])
        for reward in (goal.get("reward") or {},):
            if reward.get("trait"):
                traits.add(reward["trait"])
    for outcome_ in (scenario.get("outcomes") or {}).values():
        if outcome_ and outcome_.get("trait"):
            traits.add(outcome_["trait"])
    return ([t for t in sorted(traits) if find_trait(t) is None],
            [s for s in sorted(skills) if find_skill(s) is None])


# --- Reading the household ------------------------------------------------------------

def _sim_facts(sim_info, tracks):
    facts = {"skills": {}, "careers": [], "friendship": 0, "romance": 0, "married": False, "aspirations": []}
    try:
        facts["skills"] = {_skill_short_name(type(s)): int(s.get_user_value()) for s in sim_info.all_skills()}
    except Exception:
        scenario_log.log_exception("reading skills")
    try:
        facts["careers"] = [[type(c).__name__, int(c.user_level)] for c in sim_info.career_tracker.careers.values()]
    except Exception:
        scenario_log.log_exception("reading careers")
    try:
        from relationships.relationship_track import RelationshipTrack
        service = services.relationship_service()
        for target_id in sim_info.relationship_tracker.target_sim_gen():
            for key, track in (("friendship", RelationshipTrack.FRIENDSHIP_TRACK),
                               ("romance", RelationshipTrack.ROMANCE_TRACK)):
                score = service.get_relationship_score(sim_info.sim_id, target_id, track=track) or 0
                facts[key] = max(facts[key], score)
        facts["married"] = sim_info.spouse_sim_id is not None
    except Exception:
        scenario_log.log_exception("reading relationships")
    try:
        tracker = sim_info.aspiration_tracker
        if tracker is not None:
            for track, levels in tracks:
                if levels and all(tracker.milestone_completed(level) for level in levels):
                    facts["aspirations"].append(track.__name__)
    except Exception:
        scenario_log.log_exception("reading aspirations")
    return facts


def read_facts(household, progress):
    tracks = []
    try:
        for track in services.get_instance_manager(sims4.resources.Types.ASPIRATION_TRACK).types.values():
            tracks.append((track, [level for _, level in (track.get_aspirations() or ())]))
    except Exception:
        scenario_log.log_exception("listing aspiration tracks")
    members = list(household.sim_info_gen())
    children = sum(1 for s in members if getattr(getattr(s, "age", None), "name", "") in _CHILD_AGES)
    return {
        "day": services.time_service().sim_now.absolute_days() - progress["start_day"],
        "money": household.funds.money,
        "home_value": household.get_home_lot_value() or 0,
        "household_size": len(members),
        "children": children,
        "active": progress.get("active"),
        "has_cheated": bool(getattr(household, "_has_cheated", False)),
        "build_buy_spend": _build_buy_spend.get(household.id, 0),
        "travelled": bool(progress.get("travelled")),
        "sims": {s.sim_id: _sim_facts(s, tracks) for s in members},
    }


# --- Applying things -----------------------------------------------------------------

def notify(title, text):
    try:
        from sims4.localization import LocalizationHelperTuning
        from ui.ui_dialog_notification import UiDialogNotification
        raw = LocalizationHelperTuning.get_raw_text
        dialog = UiDialogNotification.TunableFactory().default(
            services.active_sim_info(), title=lambda *_, **__: raw(title), text=lambda *_, **__: raw(text))
        dialog.show_dialog()
    except Exception:
        scenario_log.log_exception("showing notification")


def _change_money(household, amount):
    amount = int(amount)
    if amount > 0:
        household.funds.add(amount, Consts_pb2.TELEMETRY_INTERACTION_REWARD, None)
    elif amount < 0:
        household.funds.try_remove(min(-amount, household.funds.money), Consts_pb2.TELEMETRY_INTERACTION_COST, None)


def _sims_named(household, active_sim_info, key):
    return list(household.sim_info_gen()) if key == "all" else [active_sim_info]


def apply_start(scenario, household, active_sim_info):
    start = scenario.get("start", {})
    log = []
    money = start.get("money")
    if money is not None:
        delta = money["add"] if isinstance(money, dict) else money - household.funds.money
        _change_money(household, delta)
        log.append("money {:+d}".format(int(delta)))
    if start.get("remove_careers"):
        for sim_info in household.sim_info_gen():
            for uid in list(sim_info.career_tracker.careers):
                sim_info.career_tracker.remove_career(uid, post_quit_msg=False)
        log.append("careers removed")
    for key, adding in (("remove_traits", False), ("traits", True)):
        for who, names in (start.get(key) or {}).items():
            for sim_info in _sims_named(household, active_sim_info, who):
                for name in names:
                    trait = find_trait(name)
                    if trait is None:
                        log.append("trait {} not found".format(name))
                    elif adding and not sim_info.has_trait(trait):
                        sim_info.add_trait(trait)
                    elif not adding and sim_info.has_trait(trait):
                        sim_info.remove_trait(trait)
    for who, levels in (start.get("skills") or {}).items():
        for sim_info in _sims_named(household, active_sim_info, who):
            for name, level in levels.items():
                skill = find_skill(name)
                if skill is None:
                    log.append("skill {} not found".format(name))
                    continue
                level = max(0, min(int(level), skill.max_level))
                sim_info.get_statistic(skill, add=True).set_value(skill.convert_from_user_value(level))
    scenario_log.log("start conditions for household {}: {}".format(household.id, "; ".join(log) or "none"))


def apply_reward(reward, household, active_sim_info):
    if not reward:
        return []
    said = []
    if reward.get("money"):
        _change_money(household, reward["money"])
        said.append("§{:+d}".format(int(reward["money"])))
    if reward.get("trait"):
        trait = find_trait(reward["trait"])
        if trait is not None and active_sim_info is not None:
            active_sim_info.add_trait(trait)
            said.append("trait {}".format(getattr(trait, "__name__", reward["trait"])))
    if reward.get("notification"):
        said.insert(0, reward["notification"])
    return said


def find_buff(name):
    return _find(services.get_instance_manager(sims4.resources.Types.BUFF).types.values(), name)


def apply_penalty(penalty, household, active_sim_info):
    """Applies a rule's penalty. Returns what was done, for the notification and the log."""
    kind = penalty.get("type", "warning")
    if kind == "money":
        _change_money(household, penalty["amount"])
        return "§{:+d}".format(int(penalty["amount"]))
    if kind == "moodlet":
        buff = find_buff(penalty["buff"])
        if buff is None:
            return "moodlet {} not found".format(penalty["buff"])
        if active_sim_info is not None:
            active_sim_info.add_buff_from_op(buff, buff_reason=None)
        return "moodlet {}".format(getattr(buff, "__name__", penalty["buff"]))
    if kind == "fail":
        return "the scenario is lost"
    return ""


def _active_sim_info(progress):
    sim_info = services.sim_info_manager().get(progress.get("active")) if progress.get("active") else None
    return sim_info or services.active_sim_info()


def check(household, report=None):
    """Evaluates the household's scenario once; applies rewards and the outcome."""
    progress, scenario = _current(household)
    if progress is None or scenario is None or progress.get("state") != "running":
        return
    facts = read_facts(household, progress)
    newly, result = evaluate(scenario, progress, facts)
    active = _active_sim_info(progress)
    for gid in newly:
        goal = goal_by_id(scenario, gid)
        progress["done"].append(gid)
        said = apply_reward(goal.get("reward"), household, active)
        scenario_log.log("household {}: goal {} done ({})".format(household.id, gid, said))
        unlocked = [g for g in open_goals(scenario, progress["done"]) if gid in g.get("requires", ())]
        text = "Goal done: {}".format(describe_goal(goal))
        if said:
            text += "\nReward: " + ", ".join(said)
        if unlocked:
            text += "\nNew goal: " + "; ".join(describe_goal(g) for g in unlocked)
        notify(scenario["name"], text)
    broken = broken_rules(scenario, progress, facts)
    lost_by_rule = False
    for rid in broken:
        rule = rule_by_id(scenario, rid)
        progress.setdefault("broken", []).append(rid)
        penalty = penalty_of(rule)
        said = apply_penalty(penalty, household, active)
        scenario_log.log("household {}: rule {} broken ({}); penalty {}".format(
            household.id, rid, describe_rule(rule), said or "none"))
        text = "Rule broken: {}.\nPenalty: {}.".format(describe_rule(rule), penalty_text(rule))
        if said and penalty["type"] != "fail":
            text += " " + said + "."
        notify(scenario["name"], text)
        if penalty["type"] == "fail" and result != "won":
            result = "lost"
            lost_by_rule = True
    if result is not None and progress.get("state") == "running":
        progress["state"] = result
        said = apply_reward((scenario.get("outcomes") or {}).get("win" if result == "won" else "lose"),
                            household, active)
        scenario_log.log("household {}: scenario {} {} on day {:.1f}".format(household.id, scenario["name"], result,
                                                                           facts["day"]))
        if result == "won":
            lost_text = "You won!"
        elif lost_by_rule and progress["state"] == "lost":
            lost_text = "Scenario lost: a rule was broken."
        else:
            lost_text = "Scenario lost: time's up."
        notify(scenario["name"], lost_text + ("\n" + ", ".join(said) if said else ""))
    if newly or broken or result:
        _save_progress()
    if report is not None:
        report(progress, scenario, facts)


def _tick(_handle=None):
    try:
        household = services.active_household()
        if household is not None:
            check(household)
    except Exception:
        scenario_log.log_exception("hourly scenario check")


def _start_alarm(zone):
    # Re-created on every zone load (owned by the current zone), as in npc_main.py.
    global _alarm_handle
    if _alarm_handle is not None:
        try:
            alarms.cancel_alarm(_alarm_handle)
        except Exception:
            pass
    _alarm_handle = alarms.add_alarm(zone, create_time_span(hours=1), _tick, repeating=True)


def _note_zone_load(zone):
    """no_leaving_lot: a different zone than the one the scenario started in means travel."""
    household = services.active_household()
    if household is None:
        return
    progress = _all_progress().get(str(household.id))
    if not progress or progress.get("state") != "running":
        return
    zone_id = getattr(zone, "id", None)
    if zone_id is None:
        return
    if "zone_id" not in progress:
        progress["zone_id"] = zone_id
        _save_progress()
    elif progress["zone_id"] != zone_id:
        if not progress.get("travelled"):
            progress["travelled"] = True
            _save_progress()
        check(household)


_original_on_loading_screen_animation_finished = zone_module.Zone.on_loading_screen_animation_finished


def _patched_on_loading_screen_animation_finished(self, *args, **kwargs):
    result = _original_on_loading_screen_animation_finished(self, *args, **kwargs)
    try:
        _start_alarm(self)
    except Exception:
        scenario_log.log_exception("zone load hook")
    try:
        _note_zone_load(self)
    except Exception:
        scenario_log.log_exception("zone load: travel check")
    _log_menu_tuning()
    return result


zone_module.Zone.on_loading_screen_animation_finished = _patched_on_loading_screen_animation_finished


# --- Build/Buy (max_purchase) ---------------------------------------------------------

def _on_build_buy_enter():
    global _build_buy_start_money
    try:
        household = services.active_household()
        _build_buy_start_money = (household.id, household.funds.money) if household is not None else None
    except Exception:
        _build_buy_start_money = None
        scenario_log.log_exception("build/buy enter")


def _on_build_buy_exit():
    global _build_buy_start_money
    start, _build_buy_start_money = _build_buy_start_money, None
    if start is None:
        return
    household_id, money = start
    try:
        household = services.household_manager().get(household_id) or services.active_household()
        if household is None:
            return
        spend = max(0, money - household.funds.money)
        if spend > _build_buy_spend.get(household_id, 0):
            _build_buy_spend[household_id] = spend
        if spend:
            scenario_log.log("household {}: build/buy visit spent §{}".format(household_id, spend))
            check(household)
    except Exception:
        scenario_log.log_exception("build/buy exit")


try:
    build_buy.register_build_buy_enter_callback(_on_build_buy_enter)
    build_buy.register_build_buy_exit_callback(_on_build_buy_exit)
except Exception:
    scenario_log.log_exception("installing build/buy callbacks")


# --- Cheats --------------------------------------------------------------------------

def _say(output, line):
    output(line)
    scenario_log.log(line)


@sims4.commands.Command("houserules.scenario.list", command_type=sims4.commands.CommandType.Live)
def scenario_list(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    names = scenario_files()
    _say(output, "Scenarios in {}: {}".format(SCENARIO_DIR, ", ".join(names) if names else "none"))


@sims4.commands.Command("houserules.scenario.validate", command_type=sims4.commands.CommandType.Live)
def scenario_validate(name: str = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    if not name:
        output("Usage: houserules.scenario.validate <name>  (see houserules.scenario.list)")
        return
    try:
        scenario, warnings = load_scenario(name)
        traits, skills = unknown_names(scenario)
    except ScenarioError as e:
        _say(output, "{}: NOT valid - {}".format(name, e))
        return
    except Exception:
        scenario_log.log_exception("scenario.validate")
        output("Failed - see the log.")
        return
    _say(output, "{}: valid, {} goals.".format(name, len(scenario["goals"])))
    for w in warnings:
        _say(output, "  note: " + w)
    if traits:
        _say(output, "  traits the game doesn't have: " + ", ".join(traits))
    if skills:
        _say(output, "  skills the game doesn't have: " + ", ".join(skills))


@sims4.commands.Command("houserules.scenario.start", command_type=sims4.commands.CommandType.Live)
def scenario_start(name: str = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    household = services.active_household()
    active = services.active_sim_info()
    if not name or household is None or active is None:
        output("Usage: houserules.scenario.start <name>, with a sim selected (see houserules.scenario.list)")
        return
    try:
        scenario, warnings = load_scenario(name)
        running = _all_progress().get(str(household.id))
        if running and running.get("state") == "running":
            output("This household is already playing {}. houserules.scenario.quit first.".format(running["name"]))
            return
        today = services.time_service().sim_now.absolute_days()
        progress = new_progress(scenario, name[:-5] if name.lower().endswith(".json") else name, today, active.sim_id)
        try:
            progress["zone_id"] = services.current_zone().id
        except Exception:
            scenario_log.log_exception("recording the starting zone")
        _build_buy_spend.pop(household.id, None)
        apply_start(scenario, household, active)
        _all_progress()[str(household.id)] = progress
        _save_progress()
        scenario_log.log("household {} started {} with {} as the active sim".format(
            household.id, scenario["name"], active.sim_id))
        lines = [scenario.get("description", "")] + ["Goals:"] + \
                ["- " + describe_goal(g) for g in open_goals(scenario, [])]
        if scenario.get("deadline_days"):
            lines.append("You have {} days.".format(scenario["deadline_days"]))
        notify(scenario["name"], "\n".join(l for l in lines if l))
        for w in warnings:
            _say(output, "note: " + w)
        output("Started {}.".format(scenario["name"]))
        check(household)
    except ScenarioError as e:
        _say(output, "{}: can't start - {}".format(name, e))
    except Exception:
        scenario_log.log_exception("scenario.start")
        output("Failed - see the log.")


def _menu_tuning_lines():
    """What the game makes of the exported menu tuning, as lines to print or log.

    The Scenarios screen is client-side, so this is the server's view: if the Scenario
    instance is missing here, the package never loaded and no UI change can help.
    """
    lines = []
    try:
        from sims4.resources import Types
        manager = services.get_instance_manager(Types.SNIPPET)
    except Exception as error:
        return ["Snippet manager unavailable: {}".format(error)]
    found = []
    for cls in manager.types.values():
        if str(getattr(cls, "__name__", "")).startswith("HouseRules_Scenario"):
            found.append(cls)
    if not found:
        return ["No HouseRules_Scenario snippet loaded: the package or its tuning is rejected."]
    for cls in found:
        goals = getattr(cls, "goals", ()) or ()
        lines.append("{}: {} goal(s), entry method {}".format(
            cls.__name__, len(goals),
            getattr(cls, "compatibility_with_scenario_entry_method", "?")))
        for goal in goals:
            situation_goal = getattr(goal, "situation_goal", None)
            lines.append("   goal: situation_goal {}".format(
                "loaded" if situation_goal is not None else "MISSING"))
            if situation_goal is not None:
                try:
                    test = getattr(situation_goal, "_goal_test", None)
                    lines.append("      test: {}".format("ok" if test is not None else "none"))
                except Exception as error:
                    lines.append("      test error: {}".format(error))
    return lines


def _log_menu_tuning():
    try:
        for line in _menu_tuning_lines():
            scenario_log.log("tuning: " + line)
    except Exception:
        scenario_log.log_exception("checking the menu tuning")


@sims4.commands.Command("houserules.scenario.tuning", command_type=sims4.commands.CommandType.Live)
def scenario_tuning(_connection=None):
    """Prints and logs what the game made of the exported menu tuning."""
    output = sims4.commands.CheatOutput(_connection)
    for line in _menu_tuning_lines():
        output(line)
        try:
            scenario_log.log("tuning: " + line)
        except Exception:
            pass


@sims4.commands.Command("houserules.scenario.status", command_type=sims4.commands.CommandType.Live)
def scenario_status(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    household = services.active_household()
    if household is None:
        output("No active household.")
        return

    def report(progress, scenario, facts):
        _say(output, "{} ({}), day {:.1f}{}".format(
            scenario["name"], progress["state"], facts["day"],
            " of {}".format(scenario["deadline_days"]) if scenario.get("deadline_days") else ""))
        done = progress["done"]
        for goal in scenario["goals"]:
            if goal["id"] in done:
                _say(output, "  [x] " + describe_goal(goal))
            elif goal in open_goals(scenario, done):
                _say(output, "  [ ] " + describe_goal(goal, facts))
            else:
                _say(output, "  [locked] {} (after {})".format(goal["id"], ", ".join(goal.get("requires", ()))))
        broken = set(progress.get("broken") or ())
        for rule in scenario.get("rules") or ():
            _say(output, "  [{}] rule {} (penalty: {})".format(
                "broken" if rule_id(rule) in broken else "ok", describe_rule(rule), penalty_text(rule)))

    try:
        progress, scenario = _current(household)
        if progress is None:
            output("No scenario running for this household. houserules.scenario.list shows what's there.")
            return
        if scenario is None:
            output("This household's scenario file ({}) can't be loaded - see the log.".format(progress["scenario"]))
            return
        if progress["state"] == "running":
            check(household, report)
        else:
            report(progress, scenario, read_facts(household, progress))
    except Exception:
        scenario_log.log_exception("scenario.status")
        output("Failed - see the log.")


@sims4.commands.Command("houserules.scenario.check", command_type=sims4.commands.CommandType.Live)
def scenario_check(goal_id: str = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    household = services.active_household()
    try:
        progress, scenario = _current(household) if household is not None else (None, None)
        if scenario is None or progress.get("state") != "running":
            output("No scenario running.")
            return
        goal = goal_by_id(scenario, goal_id or "")
        if goal is None or goal["type"] != "custom":
            output("Only custom goals are ticked by hand: {}".format(
                ", ".join(g["id"] for g in scenario["goals"] if g["type"] == "custom") or "this scenario has none"))
            return
        if goal_id not in [g["id"] for g in open_goals(scenario, progress["done"])]:
            output("{} is already done or still locked.".format(goal_id))
            return
        progress["done"].append(goal_id)
        said = apply_reward(goal.get("reward"), household, _active_sim_info(progress))
        scenario_log.log("household {}: custom goal {} ticked ({})".format(household.id, goal_id, said))
        _save_progress()
        output("Ticked {}.{}".format(goal_id, " Reward: " + ", ".join(said) if said else ""))
        check(household)   # unlocks what it required, and wins if it was the last goal
    except Exception:
        scenario_log.log_exception("scenario.check")
        output("Failed - see the log.")


@sims4.commands.Command("houserules.scenario.quit", command_type=sims4.commands.CommandType.Live)
def scenario_quit(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    household = services.active_household()
    if household is None or _all_progress().pop(str(household.id), None) is None:
        output("No scenario to quit.")
        return
    _build_buy_spend.pop(household.id, None)
    _save_progress()
    scenario_log.log("household {}: scenario quit".format(household.id))
    output("Scenario stopped. Nothing it gave or took is undone.")
