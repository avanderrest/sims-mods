"""Self-test checks - one suite per mod, plus environment checks.

Run in game after loading a save with a selected sim:

    houserules.test              all suites
    houserules.test hardmode     one suite (comma-separated for several)
    houserules.test.list         what can run

Checks never change the save permanently: the few that do something (add a debt, record a
sale, add a test routine entry, mark the sim royal for a moment, join a career for one
moment) put the previous state back in a finally block. The save is assumed disposable,
but a repeated test run should still start from the same state.

The `actions` suite is the end-to-end one: it sends the real command the game sends
(careers.select when a Sim is hired, houserules.npc.tick for the hourly routine check)
and then checks the world and the mod log, instead of calling the logic functions.

Everything game-specific is imported inside the check that needs it. If a mod isn't
installed, its "modules loaded" check fails with a clear message instead of the whole
harness failing at startup.
"""
import json
import os

import selftest_live as live
from selftest_core import CheckFailed, Registry, SkipCheck

REGISTRY = Registry()


def _assert(condition, message):
    if not condition:
        raise CheckFailed(message)


# ======================================================================================
# Environment: the game, the save and the folders every mod writes to
# ======================================================================================
env = REGISTRY.suite("env", "Game, save and folders")


@env.check("in play mode")
def _play_mode(_context):
    household = live.require_household()
    zone = live.current_zone()
    if zone is None:
        raise CheckFailed("there is no current zone")
    return "zone {}, household {}".format(getattr(zone, "zone_id", "?"), getattr(household, "name", "?"))


@env.check("sim selected")
def _selected_sim(_context):
    sim_info = live.require_sim()
    instance = None
    try:
        instance = sim_info.get_sim_instance()
    except Exception:
        pass
    if instance is None:
        raise CheckFailed("{} is selected but not on this lot".format(live.sim_name(sim_info)))
    return live.sim_name(sim_info)


@env.check("game clock readable")
def _clock(_context):
    now = live.sim_now()
    if now is None:
        raise CheckFailed("the time service is not available")
    return str(now)


@env.check("data folder writable")
def _data_folder(_context):
    return live.ensure_dir(live.DATA_DIR, "data")


@env.check("logs folder writable")
def _logs_folder(_context):
    return live.ensure_dir(live.LOGS_DIR, "logs")


@env.check("no lastException since start")
def _last_exceptions(_context):
    paths = live.new_last_exceptions()
    if paths:
        raise CheckFailed("{} from this session, newest: {} ({})".format(
            len(paths), os.path.basename(paths[-1]), live.first_line(paths[-1])))
    return "none"


@env.check("no errors in mod logs since start")
def _log_errors(_context):
    lines = live.error_log_lines_since_start()
    if lines:
        raise CheckFailed("{} error line(s); last: {}".format(len(lines), lines[-1]))
    return "none"


# ======================================================================================
# hello-world: the build/install pipeline
# ======================================================================================
hello = REGISTRY.suite("hello", "hello-world pipeline check")


@hello.check("module loaded")
def _hello_module(_context):
    live.require_module("houserules_hello")
    return "loaded"


# ======================================================================================
# Hard Mode
# ======================================================================================
hardmode = REGISTRY.suite("hardmode", "Hard Mode: careers, money, skills, life, debt")


@hardmode.check("modules loaded")
def _hard_modules(_context):
    live.require_modules("hardmode_main", "hardmode_money_main", "hardmode_skills_main", "hardmode_life_main")
    return "4 game modules"


@hardmode.check("hooks installed")
def _hard_hooks(_context):
    markers = ("careers.select hook installed", "firing hooks installed", "money hooks installed",
               "skill aptitude hooks installed", "life hooks installed")
    missing = [marker for marker in markers if not live.logged_any_session("hard-mode", marker)]
    if missing:
        raise CheckFailed("not logged: {} (see {})".format(", ".join(missing), live.log_path("hard-mode")))
    return "{} install markers".format(len(markers))


@hardmode.check("settings load")
def _hard_settings(_context):
    state = live.require_module("hardmode_state")
    settings_module = live.import_optional("hardmode_settings")
    settings = state.ensure_settings()
    missing = [key for key in settings_module.DEFAULT_SETTINGS if key not in settings.values]
    if missing:
        raise CheckFailed("settings missing: {}".format(", ".join(missing)))
    return "{} settings, start_funds {}".format(len(settings.values), settings.get("start_funds"))


@hardmode.check("career gate logic")
def _hard_career_logic(_context):
    careers = live.import_optional("hardmode_careers")
    cases = (
        # (career, full-time, skills, degrees, already there, expected blocked)
        ("career_Adult_Doctor", True, {}, [], False, True),
        ("career_Adult_Doctor", True, {"Logic": 2}, [], False, False),
        ("career_Adult_Doctor", True, {}, ["biology_degree"], False, False),
        ("career_Adult_Doctor", True, {}, [], True, False),
        ("career_Adult_Barista", False, {}, [], False, False),
    )
    for career, full_time, skills, degrees, already, expected in cases:
        blocked, why = careers.check_join(career, full_time, skills, degrees, already)
        if blocked != expected:
            raise CheckFailed("{}: expected blocked={}, got {} ({})".format(career, expected, blocked, why))
    return "{} known cases".format(len(cases))


@hardmode.check("career gate reads a real sim")
def _hard_career_live(_context):
    import services
    import sims4.resources
    from careers.career_enums import CareerCategory

    main = live.require_module("hardmode_main")
    careers = live.import_optional("hardmode_careers")
    sim_info = live.require_sim()
    found = None
    for career in services.get_instance_manager(sims4.resources.Types.CAREER).types.values():
        if getattr(career, "career_category", None) == CareerCategory.Work \
                and careers.gate_for_career(career.__name__):
            found = career
            break
    if found is None:
        raise SkipCheck("this game has no gated full-time career")
    blocked, why, details = main._evaluate(sim_info, found)
    _assert(isinstance(blocked, bool), "evaluate() did not return a blocked flag")
    _assert(isinstance(details, dict) and details.get("gate"), "evaluate() found no gate for {}".format(found.__name__))
    return "{} -> {} ({})".format(found.__name__, "BLOCKED" if blocked else "allowed", why)


@hardmode.check("career skills resolve")
def _hard_skills_resolve(_context):
    main = live.require_module("hardmode_main")
    careers = live.import_optional("hardmode_careers")
    found = main._resolve_skills()
    # Acting comes with Get Famous; the rest are base-game skills.
    required = [skill for skill in careers.ALL_SKILLS if skill != "Acting"]
    missing = [skill for skill in required if skill not in found]
    if missing:
        raise CheckFailed("not found in this game: {}".format(", ".join(missing)))
    return "{} of {} skills found".format(len(found), len(careers.ALL_SKILLS))


@hardmode.check("money hooks installed")
def _hard_money_hooks(_context):
    from sims.sim_info import SimInfo

    money = live.require_module("hardmode_money_main")
    if not money._installed:
        raise CheckFailed("the money hooks were never installed (zone load hook did not run?)")
    if not getattr(SimInfo.get_item_sell_price_modifier, "_houserules", False):
        raise CheckFailed("SimInfo.get_item_sell_price_modifier is not wrapped")
    return "sell price, funds, loot, business, bills and phone hooks"


@hardmode.check("market ledger round-trip")
def _hard_market(_context):
    money = live.require_module("hardmode_money_main")
    state = live.require_module("hardmode_state")
    money_module = live.import_optional("hardmode_money")
    ledger = money._get_ledger()
    # A key of our own, so a real household's market history is never touched.
    key = "_self_test"
    today = state.sim_today()
    kind = "paintings_art"
    ledger.data.pop(key, None)
    before_factor = ledger.saturation(key, kind, today)
    try:
        money._record_sale(key, kind, 1200, "self-test")
        after_factor = ledger.saturation(key, kind, today)
        # At the floor another sale can't lower it further, so accept that too.
        if not (after_factor < before_factor or after_factor <= money_module.SATURATION_FLOOR):
            raise CheckFailed("price factor did not drop ({} -> {})".format(before_factor, after_factor))
    finally:
        ledger.data.pop(key, None)
        state.save_json(money._LEDGER_FILE, ledger.to_dict())
    return "{} x{:.2f} -> x{:.2f} (test entry removed)".format(kind, before_factor, after_factor)


@hardmode.check("debt round-trip")
def _hard_debt(_context):
    money = live.require_module("hardmode_money_main")
    state = live.require_module("hardmode_state")
    household = live.require_household()
    key = str(household.id)
    debts = money._get_debts()
    before = debts.get(key, 0)
    try:
        money.add_debt(household, 137, "self-test")
        after = debts.get(key, 0)
        if after != before + 137:
            raise CheckFailed("debt was {} -> {}, expected {}".format(before, after, before + 137))
    finally:
        if before:
            debts[key] = before
        else:
            debts.pop(key, None)
        state.save_json(money._DEBT_FILE, debts)
    return "§{} -> §{} -> §{} (restored)".format(before, after, before)


@hardmode.check("Pay Off Debt tuning loaded")
def _hard_phone(_context):
    money = live.require_module("hardmode_money_main")
    affordance = live.require_tuning("INTERACTION", money.PAY_DEBT_AFFORDANCE_ID, "Pay Off Debt")
    return getattr(affordance, "__name__", "interaction") + " (package installed)"


@hardmode.check("skill aptitude hooks")
def _hard_skill_hooks(_context):
    from statistics.skill import Skill

    skills_main = live.require_module("hardmode_skills_main")
    skills = live.import_optional("hardmode_skills")
    if Skill.get_statistic_multiplier_increase is not skills_main.get_statistic_multiplier_increase:
        raise CheckFailed("Skill.get_statistic_multiplier_increase is not wrapped")
    sim_info = live.require_sim()
    talents = skills.talents_for(sim_info.sim_id)
    _assert(len(talents) == skills.TALENT_COUNT, "expected {} talents, got {}".format(skills.TALENT_COUNT, talents))
    _assert(skills.aptitude_multiplier(talents[0], 0, sim_info.sim_id, ()) == skills.APT_MULTIPLIER,
            "a talent does not get the aptitude multiplier")
    return "{} talents for {}".format(", ".join(talents), live.sim_name(sim_info))


@hardmode.check("skill factor on a real skill")
def _hard_skill_factor(_context):
    skills_main = live.require_module("hardmode_skills_main")
    sim_info = live.require_sim()
    skill_type = live.find_skill("Logic")
    if skill_type is None:
        raise CheckFailed("Logic skill not found in this game")
    skill = sim_info.get_statistic(skill_type, add=False)
    added = skill is None
    if added:
        # Set one up so the check runs on every save instead of skipping.
        skill = sim_info.get_statistic(skill_type, add=True)
    if skill is None:
        raise CheckFailed("could not add a Logic skill instance")
    try:
        factor = skills_main._factor(skill)
        _assert(isinstance(factor, float) and factor > 0, "factor was {!r}".format(factor))
        return "Logic {} -> x{:.2f}".format(skill.get_user_value(), factor)
    finally:
        if added:
            try:
                sim_info.remove_statistic(skill_type)
            except Exception:
                pass


@hardmode.check("life logic")
def _hard_life_logic(_context):
    life = live.import_optional("hardmode_life")
    _assert(life.reward_cost(1000) == 1500, "reward_cost(1000) was {}".format(life.reward_cost(1000)))
    _assert(life.childcare_cost(2, 2, 2, 2) == 120, "childcare_cost(2,2,2,weekday) was {}".format(
        life.childcare_cost(2, 2, 2, 2)))
    _assert(life.relationship_decay(1.0, "Friendship") == 1.5, "friendship decay was not 1.5x")
    _assert(life.lingers("Mood_Sad", 2), "a strong sad mood does not linger")
    return "reward store x1.5, childcare, decay and moods"


@hardmode.check("reward store prices raised")
def _hard_store(_context):
    settings = live.require_module("hardmode_state").ensure_settings()
    if not settings.get("life"):
        raise SkipCheck("Hard Mode's life setting is off")
    life_main = live.require_module("hardmode_life_main")
    if life_main._original_store is None:
        raise CheckFailed("the reward store prices were not raised at zone load")
    from satisfaction.satisfaction_tracker import SatisfactionTracker
    changed = SatisfactionTracker.SATISFACTION_STORE_ITEMS
    life = live.import_optional("hardmode_life")
    checked = 0
    for reward, data in list(life_main._original_store.items())[:300]:
        new = changed.get(reward)
        if new is None or int(new.cost) != life.reward_cost(int(data.cost)):
            raise CheckFailed("{} costs {!r}, expected {}".format(
                getattr(reward, "__name__", reward), getattr(new, "cost", None), life.reward_cost(int(data.cost))))
        checked += 1
    return "{} items at x1.5".format(checked)


# ======================================================================================
# Actions: really do the thing, then check what the mod did about it
# ======================================================================================
actions = REGISTRY.suite("actions", "End-to-end: real commands, real results")


def _gated_careers_blocked_for(sim_info):
    """[(career, why)] for gated full-time careers this Sim could not get right now."""
    import services
    import sims4.resources
    from careers.career_enums import CareerCategory

    main = live.require_module("hardmode_main")
    careers = live.import_optional("hardmode_careers")
    blocked_careers = []
    manager = services.get_instance_manager(sims4.resources.Types.CAREER)
    for career in manager.types.values():
        if getattr(career, "career_category", None) != CareerCategory.Work:
            continue
        if careers.gate_for_career(getattr(career, "__name__", "")) is None:
            continue
        if getattr(career, "start_track", None) is None or getattr(career, "guid64", None) is None:
            continue
        try:
            blocked, why, details = main._evaluate(sim_info, career)
        except Exception:
            continue
        if blocked and not details.get("already_in_it"):
            blocked_careers.append((career, why))
    return blocked_careers


def _set_hard_settings(**values):
    """Change Hard Mode settings and return what they were (so a check can put them back)."""
    state = live.require_module("hardmode_state")
    settings = state.ensure_settings()
    before = {key: settings.get(key) for key in values}
    for key, value in values.items():
        settings.set(key, value)
    state.save_settings()
    return before


def _restore_hard_settings(before):
    state = live.require_module("hardmode_state")
    settings = state.ensure_settings()
    for key, value in before.items():
        settings.set(key, value)
    state.save_settings()


@actions.check("job pick is refused by Hard Mode")
def _action_hard_job_blocked(_context):
    """Does what the Find a Job screen does: sends careers.select and watches the Sim."""
    sim_info = live.require_sim()
    tracker = sim_info.career_tracker
    before_careers = set(tracker.careers)
    mark = live.log_mark("hard-mode")
    before_settings = _set_hard_settings(careers=True, enforce=True)
    try:
        candidates = _gated_careers_blocked_for(sim_info)
        if not candidates:
            raise SkipCheck("no gated full-time career would be blocked for this sim")
        career, why = candidates[0]
        live.run_command("careers.select {} {} {} 0 0 0".format(
            sim_info.sim_id, career.guid64, career.start_track.guid64))
        picked = live.wait_for(lambda: bool([
            line for line in live.log_since(mark, "hard-mode")
            if "job pick:" in line and career.__name__ in line]))
        after_careers = set(tracker.careers)
        if after_careers != before_careers:
            raise CheckFailed("{} joined {} despite the gate".format(
                live.sim_name(sim_info), career.__name__))
        if not picked:
            raise CheckFailed("the job pick was not logged by Hard Mode (see {})".format(
                live.log_path("hard-mode")))
        lines = live.log_since(mark, "hard-mode")
        refused = [line for line in lines
                   if "job pick:" in line and career.__name__ in line
                   and "blocked=True" in line and "enforce=True" in line]
        if not refused:
            raise CheckFailed("the job pick was passed to EA instead of being refused: {}".format(
                [line for line in lines if "job pick:" in line][-1:]))
    finally:
        _restore_hard_settings(before_settings)
    return "{} -> {} refused ({})".format(live.sim_name(sim_info), career.__name__, why)


@actions.check("job pick goes through when enforcement is off")
def _action_hard_job_allowed(_context):
    """Proves the refusal above was Hard Mode's switch, not EA failing to hire."""
    sim_info = live.require_sim()
    tracker = sim_info.career_tracker
    mark = live.log_mark("hard-mode")
    before_settings = _set_hard_settings(careers=True, enforce=False)
    cleanup = None
    career = None
    # EA quits quittable careers of the same category when joining a new one. If the sim
    # already has a job, that would silently destroy it - so stub it out for this join and
    # the test can run on any save instead of skipping.
    original_quit = tracker.quit_quittable_careers
    tracker.quit_quittable_careers = lambda *args, **kwargs: None
    try:
        candidates = []
        for candidate, why in _gated_careers_blocked_for(sim_info):
            try:
                if candidate.is_valid_career(sim_info=sim_info, from_join=True):
                    candidates.append((candidate, why))
            except Exception:
                continue
        if not candidates:
            raise CheckFailed("no gated full-time career this sim could take with enforcement off")
        career, why = candidates[0]
        live.run_command("careers.select {} {} {} 0 0 0".format(
            sim_info.sim_id, career.guid64, career.start_track.guid64))
        joined = live.wait_for(lambda: career.guid64 in tracker.careers)
        if not joined:
            raise CheckFailed("{} did not get {} with enforcement off".format(
                live.sim_name(sim_info), career.__name__))
        lines = live.log_since(mark, "hard-mode")
        if not any("job pick:" in line and career.__name__ in line and "blocked=True" in line
                   and "enforce=False" in line for line in lines):
            raise CheckFailed("Hard Mode did not log the rule for the allowed pick")
    finally:
        try:
            del tracker.quit_quittable_careers
        except Exception:
            pass
        try:
            if career is not None and career.guid64 in tracker.careers:
                tracker.remove_career(career.guid64, post_quit_msg=False)
        except Exception as e:
            cleanup = "{}: {}".format(type(e).__name__, e)
        _restore_hard_settings(before_settings)
    if cleanup:
        raise CheckFailed("the test career could not be removed again: {}".format(cleanup))
    return "{} joined {} with enforce off (then quit it again)".format(
        live.sim_name(sim_info), career.__name__)


def _sellable_inventory_item(sim_info):
    money = live.require_module("hardmode_money_main")
    instance = sim_info.get_sim_instance()
    if instance is None:
        return None, None
    inventory = getattr(instance, "inventory_component", None)
    if inventory is None:
        return None, None
    for item in inventory:
        try:
            kind = money._kind_for_tags(money._tags_of(item))
        except Exception:
            continue
        if kind:
            return item, kind
    return None, None


def _sellable_lot_object(sim_info):
    """Any sellable object on the lot, for saves with nothing in the sim's inventory."""
    import services

    money = live.require_module("hardmode_money_main")
    for obj in list(services.object_manager().valid_objects()):
        if getattr(obj, "is_sim", False) or obj is sim_info.get_sim_instance():
            continue
        try:
            kind = money._kind_for_tags(money._tags_of(obj))
            if kind:
                return obj, kind
        except Exception:
            continue
    return None, None


@actions.check("sell price drops for a real item")
def _action_hard_sell_price(_context):
    sim_info = live.require_sim()
    item, kind = _sellable_inventory_item(sim_info)
    if item is None:
        item, kind = _sellable_lot_object(sim_info)
    if item is None:
        raise CheckFailed("no sellable item in {}'s inventory or on the lot".format(
            live.sim_name(sim_info)))
    before_settings = _set_hard_settings(selling=False)
    try:
        normal = float(sim_info.get_item_sell_price_modifier(item))
        _restore_hard_settings(before_settings)
        before_settings = _set_hard_settings(selling=True)
        discounted = float(sim_info.get_item_sell_price_modifier(item))
    finally:
        _restore_hard_settings(before_settings)
    if not discounted < normal:
        raise CheckFailed("the real sell price did not drop for {} (x{:.2f} -> x{:.2f})".format(
            kind, normal, discounted))
    return "{} x{:.2f} -> x{:.2f} with selling on".format(kind, normal, discounted)


@actions.check("NPC tick runs through its command")
def _action_npc_tick(_context):
    live.require_module("npc_main")
    mark = live.log_mark("npc-routines")
    live.run_command("houserules.npc.tick")
    found = live.wait_for(lambda: any(
        "tick:" in line for line in live.log_since(mark, "npc-routines")))
    if not found:
        raise CheckFailed("houserules.npc.tick wrote nothing to {}".format(
            live.log_path("npc-routines")))
    line = next(line for line in live.log_since(mark, "npc-routines") if "tick:" in line)
    return line.split("tick:", 1)[1].strip()[:100]


# --- Royalty ---------------------------------------------------------------------------
def _set_royalty_settings(**values):
    main = live.require_module("atr_main")
    settings = main._settings()
    before = {key: settings.get(key) for key in values}
    for key, value in values.items():
        settings[key] = value
    main._save()
    return before


def _restore_royalty_settings(before):
    main = live.require_module("atr_main")
    main._settings().update(before)
    main._save()


@actions.check("noble promotion is refused by Ascent to Royalty")
def _action_royalty_promotion(_context):
    """Calls the same promote() the game calls; the gate must leave the rank alone."""
    main = live.require_module("atr_main")
    if not getattr(main, "_ACTIVE", False):
        raise SkipCheck("EP21 Royalty & Legacy is not installed; the mod is inactive")
    sim_info = live.require_sim()
    career = main._noble_career(sim_info)
    if career is None:
        raise SkipCheck("{} is not in the Noble career (join it in game through a throne, "
                        "the noble book, or a title)".format(live.sim_name(sim_info)))
    current = main._level(career)
    target = min(main._max_level(career), current + 1)
    if target <= current:
        raise SkipCheck("{} is already at the top noble rank".format(live.sim_name(sim_info)))
    failures, _ = main._failures(sim_info, career, target)
    if not failures:
        raise SkipCheck("every requirement for noble level {} is already met".format(target))
    # The gate remembers who it told today; forget this Sim so the action writes its line.
    try:
        main._notified.pop((getattr(sim_info, "id", None), target), None)
    except Exception:
        pass
    before_settings = _set_royalty_settings(enabled=True, notify=False)
    mark = live.log_mark("ascent-to-royalty")
    try:
        career.promote()
        logged = live.wait_for(lambda: any(
            "blocked " in line for line in live.log_since(mark, "ascent-to-royalty")))
        after = main._level(career)
        if after != current:
            try:
                career.demote()
            except Exception:
                pass
            raise CheckFailed("{} was promoted to level {} despite the gate".format(
                live.sim_name(sim_info), after))
        if not logged:
            raise CheckFailed("no 'blocked' line was written (see {})".format(
                live.log_path("ascent-to-royalty")))
    finally:
        _restore_royalty_settings(before_settings)
    return "{}: level {} kept, {} requirement(s) missing ({})".format(
        live.sim_name(sim_info), current, len(failures), main.failure_text(failures)[:80])


# --- Social Gates ----------------------------------------------------------------------
def _set_gate_settings(**values):
    state = live.require_module("sg_state")
    settings = state.ensure_settings()
    before = {key: settings.get(key) for key in values}
    for key, value in values.items():
        settings.set(key, value)
    state.save_settings()
    return before


def _restore_gate_settings(before):
    state = live.require_module("sg_state")
    settings = state.ensure_settings()
    for key, value in before.items():
        settings.set(key, value)
    state.save_settings()


@actions.check("club admission is refused by Social Gates")
def _action_gates_club(_context):
    import services

    main = live.require_module("sg_main")
    sim_info = live.require_sim()
    service = services.get_club_service()
    if service is None:
        raise SkipCheck("no club service in this game")
    before_settings = _set_gate_settings(clubs=True, club_enforce_premade=True)
    try:
        candidates = []
        for club in service.clubs:
            if not main._club_gate_active(club):
                continue
            if getattr(club, "leader", None) is sim_info:
                continue
            members = list(getattr(club, "members", ()) or ())
            if any(m.sim_id == sim_info.sim_id for m in members):
                continue
            try:
                if len(members) >= club.get_member_cap():
                    continue
            except Exception:
                continue
            try:
                ok, reason = main._admission_result(sim_info, club)
            except Exception:
                continue
            if not ok:
                candidates.append((club, reason))
        if not candidates:
            raise CheckFailed("no club this sim would be refused from")
        club, reason = candidates[0]
        before_count = len(club.members)
        mark = live.log_mark("social-gates")
        cleanup = None
        try:
            live.run_command("clubs.add_sim_to_club_by_id {} {}".format(
                sim_info.sim_id, club.club_id))
            logged = live.wait_for(lambda: any(
                "not admitted to" in line for line in live.log_since(mark, "social-gates")))
            after_members = list(getattr(club, "members", ()) or ())
            joined = any(m.sim_id == sim_info.sim_id for m in after_members)
            if joined or len(after_members) != before_count:
                raise CheckFailed("{} was added to {} despite the gate".format(
                    live.sim_name(sim_info), getattr(club, "name", club.club_id)))
            if not logged:
                raise CheckFailed("no 'not admitted' line was written (see {})".format(
                    live.log_path("social-gates")))
        finally:
            try:
                if any(m.sim_id == sim_info.sim_id for m in getattr(club, "members", ()) or ()):
                    club.remove_member(sim_info, distribute=False)
            except Exception as e:
                cleanup = "{}: {}".format(type(e).__name__, e)
        if cleanup:
            raise CheckFailed("the test membership could not be removed: {}".format(cleanup))
    finally:
        _restore_gate_settings(before_settings)
    return "{} refused by {} ({})".format(
        live.sim_name(sim_info), getattr(club, "name", club.club_id), reason)


# --- Hard Mode: a real unpaid bill ------------------------------------------------------
@actions.check("a real unpaid bill becomes debt")
def _action_hard_bill_to_debt(_context):
    import services

    money = live.require_module("hardmode_money_main")
    money_module = live.import_optional("hardmode_money")
    state = live.require_module("hardmode_state")
    household = live.require_household()
    bills = getattr(household, "bills_manager", None)
    if bills is None:
        raise CheckFailed("this household has no bills manager")

    # Force a bill exactly as the game would deliver one. The console command that does this
    # is Automation type, so it silently does nothing when cheats are off - call the manager.
    if bills.current_payment_owed is None:
        previous_notifications = bills.bill_notifications_enabled
        bills.bill_notifications_enabled = False
        try:
            bills.allow_bill_delivery()
        finally:
            bills.bill_notifications_enabled = previous_notifications
        live.wait_for(lambda: bills.current_payment_owed is not None)
    owed = bills.current_payment_owed
    if not owed or owed <= 0:
        raise CheckFailed("the game did not produce a bill for this household")
    limit = money_module.credit_limit(household.get_home_lot_value() or 0)
    expected, accepted = money_module.bill_to_debt(0, owed, limit)
    if not accepted:
        raise CheckFailed("bill §{} is above this household's credit limit §{}".format(owed, limit))

    key = str(household.id)
    debts = money._get_debts()
    before_debt = debts.get(key, 0)
    mark = live.log_mark("hard-mode")
    try:
        debts[key] = 0
        state.save_json(money._DEBT_FILE, debts)
        live.run_command("houserules.hard.money.bill_to_debt")
        live.wait_for(lambda: money._get_debts().get(key, 0) == expected)
        after_debt = money._get_debts().get(key, 0)
        if after_debt != expected:
            raise CheckFailed("debt was §{}, expected §{} for a §{} bill".format(
                after_debt, expected, owed))
        lines = live.log_since(mark, "hard-mode")
        if not any("unpaid bill of" in line and "accepted=True" in line for line in lines):
            raise CheckFailed("the bill conversion was not logged (see {})".format(
                live.log_path("hard-mode")))
    finally:
        if before_debt:
            debts[key] = before_debt
        else:
            debts.pop(key, None)
        state.save_json(money._DEBT_FILE, debts)
    return "§{} bill -> §{} debt (late fee included); debt restored to §{}".format(
        owed, expected, before_debt)


# --- Scenarios: a real action breaks a rule ---------------------------------------------
def _valid_career_for(sim_info):
    import services
    import sims4.resources

    for career in services.get_instance_manager(sims4.resources.Types.CAREER).types.values():
        if getattr(career, "start_track", None) is None or getattr(career, "guid64", None) is None:
            continue
        try:
            if career.is_valid_career(sim_info=sim_info, from_join=True):
                return career
        except Exception:
            continue
    return None


@actions.check("a real job breaks a scenario's no-career rule")
def _action_scenario_rule(_context):
    import services

    main = live.require_module("scenario_main")
    logic = live.import_optional("scenario_logic")
    household = live.require_household()
    sim_info = live.require_sim()
    progress, _ = main._current(household)
    if progress is not None and progress.get("state") == "running":
        raise SkipCheck("this household is already playing a scenario")
    employed = any(getattr(s, "career_tracker", None) and s.career_tracker.careers
                   for s in household.sim_info_gen())
    career = None
    if not employed:
        career = _valid_career_for(sim_info)
        if career is None:
            raise CheckFailed("no career this sim could join")

    name = "_self_test_rule"
    path = os.path.join(main.SCENARIO_DIR, name + ".json")
    key = str(household.id)
    saved_progress = main._all_progress().get(key)
    mark = live.log_mark("scenarios")
    # careers.select is Live (careers.add_career is Cheat, so it silently does nothing when
    # cheats are off and houserules.test was run without them). Hard Mode's job gate would
    # refuse this join, so switch its enforcement off for the moment and put it back after.
    try:
        before_settings = _set_hard_settings(careers=True, enforce=False)
    except CheckFailed:
        before_settings = None
    try:
        scenario_data = {
            "name": "Self-test rule",
            "description": "Temporary scenario used by houserules.test actions.",
            "goals": [{"id": "never", "type": "household_money", "amount": 999999999}],
            "rules": [{"type": "no_career", "penalty": {"type": "warning"}}],
        }
        os.makedirs(main.SCENARIO_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(scenario_data, f)
        scenario, _warnings = logic.parse(json.dumps(scenario_data))
        now = live.sim_now()
        if now is None:
            raise SkipCheck("the time service is not available")
        running = logic.new_progress(scenario, name, now.absolute_days(), sim_info.sim_id)
        main._all_progress()[key] = running
        if not employed:
            live.run_command("careers.select {} {} {} 0 0 0".format(
                sim_info.sim_id, career.guid64, career.start_track.guid64))
            joined = live.wait_for(lambda: career.guid64 in sim_info.career_tracker.careers)
            if not joined:
                raise CheckFailed("{} could not take {} for the test".format(
                    live.sim_name(sim_info), career.__name__))
        main.check(household)
        broken = list(running.get("broken") or ())
        if "no_career" not in broken:
            raise CheckFailed("the no_career rule did not break (broken: {})".format(broken))
        if not any("rule no_career broken" in line for line in live.log_since(mark, "scenarios")):
            raise CheckFailed("the broken rule was not logged (see {})".format(
                live.log_path("scenarios")))
    finally:
        try:
            if career is not None and career.guid64 in sim_info.career_tracker.careers:
                sim_info.career_tracker.remove_career(career.guid64, post_quit_msg=False)
        except Exception:
            pass
        try:
            if saved_progress is None:
                main._all_progress().pop(key, None)
            else:
                main._all_progress()[key] = saved_progress
            main._save_progress()
        except Exception:
            pass
        try:
            os.remove(path)
        except OSError:
            pass
        if before_settings is not None:
            try:
                _restore_hard_settings(before_settings)
            except Exception:
                pass
    if employed:
        return "household already employed -> no_career flagged (existing careers untouched)"
    return "{} joined {} -> no_career rule broken (career and progress restored)".format(
        live.sim_name(sim_info), career.__name__)


# --- Social Standing: a real relationship gain ------------------------------------------
@actions.check("relationship gain uses the Social Standing multiplier")
def _action_social_gain(_context):
    import services
    from relationships.relationship_track import RelationshipTrack

    main = live.require_module("social_main")
    a = live.require_sim()
    if not main._eligible(a):
        raise SkipCheck("{} is not a teen-or-older human".format(live.sim_name(a)))
    manager = services.sim_info_manager()
    track = RelationshipTrack.FRIENDSHIP_TRACK

    before_settings = dict(main._get_settings())
    try:
        settings = main._get_settings()
        settings["enabled"] = True
        settings["strength"] = 100
        royal = set(settings.get("royal") or ())
        settings["royal"] = sorted(royal | {a.sim_id})
        main._save_settings()
        main._status_cache.pop(a.sim_id, None)

        pair = None
        for target_id in list(a.relationship_tracker.target_sim_gen()):
            b = manager.get(target_id)
            if b is None or b.sim_id == a.sim_id or not main._eligible(b):
                continue
            if getattr(a, "age", None) != getattr(b, "age", None):
                continue
            try:
                if main._is_family(a, b):
                    continue
            except Exception:
                continue
            before = services.relationship_service().get_relationship_score(
                a.sim_id, b.sim_id, track)
            if before is None or before > 70:
                continue
            main._status_cache.pop(b.sim_id, None)
            try:
                multiplier = main._multiplier_for(a.sim_id, b.sim_id, "friendship")
            except Exception:
                continue
            if abs(multiplier - 1.0) > 0.05:
                pair = (b, before, multiplier)
                break
        if pair is None:
            raise SkipCheck("no non-family relationship with a different multiplier in this save")
        b, before, multiplier = pair
        delta = 10.0
        after = None
        try:
            services.relationship_service().add_relationship_score(
                a.sim_id, b.sim_id, delta, track)
            after = services.relationship_service().get_relationship_score(
                a.sim_id, b.sim_id, track)
        finally:
            try:
                if after is not None and after > before:
                    services.relationship_service().add_relationship_score(
                        a.sim_id, b.sim_id, before - after, track)
            except Exception:
                pass
        actual = (after or 0) - before
        expected = delta * multiplier
        if abs(actual - expected) > 0.5:
            raise CheckFailed("gain was {:.2f}, expected {:.2f} (x{:.2f})".format(
                actual, expected, multiplier))
        if abs(actual - delta) <= 0.05:
            raise CheckFailed("the gain was not changed from the raw {:.1f}".format(delta))
    finally:
        main._get_settings().update(before_settings)
        main._save_settings()
        main._status_cache.clear()
    return "{} + {}: {:.2f} instead of {:.1f} (x{:.2f}, score restored)".format(
        live.sim_name(a), live.sim_name(b), actual, delta, multiplier)


# ======================================================================================
# Aspiration Progress
# ======================================================================================
aspiration = REGISTRY.suite("aspiration", "Aspiration Progress")


@aspiration.check("modules and hook loaded")
def _asp_modules(_context):
    live.require_modules("asp_main", "asp_logic")
    return "loaded"


@aspiration.check("hooks installed")
def _asp_hooks(_context):
    from aspirations.aspirations import AspirationTracker

    asp = live.require_module("asp_main")
    if AspirationTracker.complete_milestone is not asp.complete_milestone:
        raise CheckFailed("AspirationTracker.complete_milestone is not wrapped")
    if AspirationTracker._should_handle_event is not asp._should_handle_event:
        raise CheckFailed("AspirationTracker._should_handle_event is not wrapped")
    return live.require_logged("aspiration-progress", "aspiration hooks installed", "aspiration hooks")


@aspiration.check("aspiration tracks and levels found")
def _asp_tracks(_context):
    asp = live.require_module("asp_main")
    tracks, index = asp._load_tracks()
    _assert(tracks, "no aspiration tracks were found")
    _assert(index, "no aspiration levels were indexed")
    level_count = sum(len(levels) for _, levels in tracks)
    return "{} tracks, {} levels".format(len(tracks), level_count)


@aspiration.check("levels registered for events")
def _asp_registered(_context):
    live.require_logged("aspiration-progress", "aspiration levels for events", "the level registration")
    return "registered at zone load"


@aspiration.check("settings readable")
def _asp_settings(_context):
    asp = live.require_module("asp_main")
    enabled = asp._enabled()
    _assert(isinstance(enabled, bool), "_enabled() was {!r}".format(enabled))
    return "on" if enabled else "off"


@aspiration.check("reads the selected sim")
def _asp_live(_context):
    asp = live.require_module("asp_main")
    sim_info = live.require_sim()
    tracker = getattr(sim_info, "aspiration_tracker", None)
    if tracker is None:
        raise CheckFailed("{} has no aspiration tracker".format(live.sim_name(sim_info)))
    asp._catch_up(sim_info)
    active = getattr(tracker, "_active_aspiration", None)
    return "{} (working on {})".format(live.sim_name(sim_info), getattr(active, "__name__", "nothing"))


@aspiration.check("ordering logic")
def _asp_logic(_context):
    logic = live.import_optional("asp_logic")
    done = {"b"}
    _assert(logic.first_incomplete(["a", "b", "c"], lambda lv: lv in done) == "a",
            "first_incomplete did not return the first unfinished level")
    _assert(logic.ahead_of(["a", "b", "c"], lambda lv: lv in done) == ["b"],
            "ahead_of did not report the level already done ahead of the current one")
    _assert(logic.all_complete(["b"], lambda lv: lv in done), "all_complete missed a finished set")
    return "first_incomplete, ahead_of, all_complete"


# ======================================================================================
# Social Standing
# ======================================================================================
social = REGISTRY.suite("social", "Social Standing")


@social.check("module and hook loaded")
def _social_modules(_context):
    from relationships.relationship_service import RelationshipService

    main = live.require_module("social_main")
    if RelationshipService.add_relationship_score is not main.add_relationship_score:
        raise CheckFailed("RelationshipService.add_relationship_score is not wrapped")
    return live.require_logged("social-standing", "relationship hook installed", "the relationship hook")


@social.check("compatibility and status logic")
def _social_logic(_context):
    logic = live.import_optional("social_logic")
    _assert(logic.compatibility([], []) == 0.0, "two blank profiles were not 0 compatibility")
    _assert(logic.compatibility(["trait_Neat"], ["trait_Slob"]) < 0, "Neat/Slob was not a clash")
    _assert(logic.status_gap_multiplier(logic.GAP_FREE) == 1.0, "a gap at the free limit was penalised")
    _assert(logic.friendship_multiplier(0.0, 0.0) == logic.compatibility_multiplier(0.0),
            "friendship multiplier did not equal the compatibility multiplier")
    _assert(logic.friendship_multiplier(0.0, 0.0, family=True) == 1.0, "family did not bypass the penalty")
    return "compatibility, gap, friendship and family"


@social.check("reads the selected sim")
def _social_live(_context):
    main = live.require_module("social_main")
    sim_info = live.require_sim()
    status, parts = main._status(sim_info)
    _assert(isinstance(status, float), "_status returned {!r}".format(status))
    return "{}: {:.2f} ({})".format(live.sim_name(sim_info), status, parts)


@social.check("royal flag round-trip")
def _social_royal(_context):
    main = live.require_module("social_main")
    sim_info = live.require_sim()
    settings = main._get_settings()
    before = sorted(settings.get("royal", ()))
    without = [sim_id for sim_id in before if sim_id != sim_info.sim_id]
    try:
        settings["royal"] = without
        main._save_settings()
        main._status_cache.pop(sim_info.sim_id, None)
        normal, _ = main._status(sim_info)
        settings["royal"] = sorted(set(before) | {sim_info.sim_id})
        main._save_settings()
        main._status_cache.pop(sim_info.sim_id, None)
        raised, _ = main._status(sim_info)
        if raised <= normal:
            raise CheckFailed("marking the sim royal did not raise their status ({} -> {})".format(normal, raised))
    finally:
        settings["royal"] = before
        main._save_settings()
        main._status_cache.pop(sim_info.sim_id, None)
    return "status {:.2f} -> {:.2f} (restored, royal back to {})".format(normal, raised, before)


# ======================================================================================
# Social Gates
# ======================================================================================
gates = REGISTRY.suite("gates", "Social Gates")


@gates.check("modules loaded")
def _gates_modules(_context):
    live.require_modules("sg_main", "sg_logic", "sg_settings", "sg_state")
    return live.require_logged("social-gates", "loaded", "the install log line")


@gates.check("settings load")
def _gates_settings(_context):
    state = live.require_module("sg_state")
    settings_module = live.import_optional("sg_settings")
    settings = state.ensure_settings()
    missing = [key for key in settings_module.DEFAULT_SETTINGS if key not in settings.values]
    if missing:
        raise CheckFailed("settings missing: {}".format(", ".join(missing)))
    return "{} settings (doors {}, clubs {}, invites {})".format(
        len(settings.values), settings.get("doors"), settings.get("clubs"), settings.get("invites"))


@gates.check("friends and wealth bands")
def _gates_logic(_context):
    logic = live.import_optional("sg_logic")
    _assert(logic.is_friend(20, 20), "exactly at the threshold did not count as a friend")
    _assert(not logic.is_friend(None, 20), "an unknown score counted as a friend")
    low, high = logic.wealth_bounds(logic.AVERAGE, 20000, 0.5)
    _assert((low, high) == (10000, 30000), "Average around 20k was {}-{}".format(low, high))
    _assert(not logic.in_wealth_range(logic.AVERAGE, 5000, 20000, 0.5), "5k passed the Average band")
    ok, _ = logic.club_admission({"trait_Creative"}, {}, trait_requirements={"trait_Creative"})
    _assert(ok, "a matching trait did not pass admission")
    ok, _ = logic.club_admission({"trait_Slob"}, {}, trait_requirements={"trait_Creative"})
    _assert(not ok, "a non-matching trait passed admission")
    return "friend threshold, relative wealth, admission"


@gates.check("club checks on a real sim")
def _gates_live(_context):
    import services

    main = live.require_module("sg_main")
    sim_info = live.require_sim()
    service = services.get_club_service()
    if service is None:
        raise SkipCheck("no club service in this game")
    clubs = list(service.clubs)
    if not clubs:
        raise SkipCheck("this save has no clubs")
    checked = []
    for club in clubs:
        ok, reason = main._admission_result(sim_info, club)
        _assert(isinstance(ok, bool) and isinstance(reason, str),
                "admission for {} returned {!r}".format(getattr(club, "name", "?"), (ok, reason)))
        checked.append(ok)
    return "{} clubs checked ({} would pass)".format(len(checked), sum(1 for ok in checked if ok))


# ======================================================================================
# Scenarios
# ======================================================================================
scenarios = REGISTRY.suite("scenarios", "Scenarios")


@scenarios.check("modules loaded")
def _scenario_modules(_context):
    live.require_modules("scenario_main", "scenario_logic")
    return "loaded"


@scenarios.check("scenario files valid")
def _scenario_files(_context):
    main = live.require_module("scenario_main")
    logic = live.import_optional("scenario_logic")
    names = main.scenario_files()
    if not names:
        raise CheckFailed("no scenario files in {}".format(main.SCENARIO_DIR))
    broken = []
    for name in names:
        path = os.path.join(main.SCENARIO_DIR, name + ".json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                logic.parse(f.read())
        except Exception as e:
            broken.append("{}: {}".format(name, e))
    if broken:
        raise CheckFailed("; ".join(broken))
    return "{} valid: {}".format(len(names), ", ".join(names))


@scenarios.check("reads household facts")
def _scenario_live(_context):
    main = live.require_module("scenario_main")
    household = live.require_household()
    sim_info = live.require_sim()
    now = live.sim_now()
    if now is None:
        raise SkipCheck("the time service is not available")
    progress = {"start_day": now.absolute_days(), "active": sim_info.sim_id, "travelled": False}
    facts = main.read_facts(household, progress)
    for key in ("day", "money", "home_value", "household_size", "sims"):
        _assert(key in facts, "read_facts() left out {}".format(key))
    return "{} sims, §{}, home §{}".format(facts["household_size"], facts["money"], facts["home_value"])


@scenarios.check("running scenario checks cleanly")
def _scenario_running(_context):
    main = live.require_module("scenario_main")
    household = live.require_household()
    progress, scenario = main._current(household)
    if progress is None:
        return "no scenario running"
    if scenario is None:
        raise CheckFailed("progress exists for {}, but its file cannot be loaded".format(progress.get("scenario")))
    main.check(household)
    return "{}: {}".format(scenario.get("name", progress.get("scenario")), progress.get("state"))


@scenarios.check("goal and outcome logic")
def _scenario_logic(_context):
    logic = live.import_optional("scenario_logic")
    scenario = {"goals": [{"id": "rich", "type": "household_money", "amount": 100}], "win": "all_goals"}
    progress = {"state": "running", "done": [], "broken": []}
    facts = {"money": 150, "day": 1, "household_size": 1, "sims": {}}
    newly, outcome = logic.evaluate(scenario, progress, facts)
    _assert(newly == ["rich"], "the money goal was not completed: {}".format(newly))
    _assert(outcome == "won", "the scenario was not won: {}".format(outcome))
    scenario["deadline_days"] = 5
    scenario["goals"] = [{"id": "rich", "type": "household_money", "amount": 500}]
    _, lost = logic.evaluate(scenario, progress, dict(facts, day=5))
    _assert(lost == "lost", "a passed deadline did not lose: {}".format(lost))
    return "goal done, win, deadline loss"


# ======================================================================================
# Neighborhood Stories Rebalance
# ======================================================================================
nsr = REGISTRY.suite("nsr", "Neighborhood Stories Rebalance")


@nsr.check("module and hooks loaded")
def _nsr_modules(_context):
    import story_progression.story_progression_telemetry as telemetry
    import story_progression.story_progression_tracker as tracker

    main = live.require_module("nsr_main")
    if tracker.BaseStoryProgressionTracker.add_arc is not main._patched_add_arc:
        raise CheckFailed("BaseStoryProgressionTracker.add_arc is not wrapped")
    if telemetry.send_arc_complete_telemetry is not main._patched_arc_complete:
        raise CheckFailed("send_arc_complete_telemetry is not wrapped")
    return "arc start and arc end hooks"


@nsr.check("weights applied")
def _nsr_weights(_context):
    main = live.require_module("nsr_main")
    classify = live.import_optional("nsr_classify")
    if not main._applied_already:
        raise CheckFailed("the rebalance has not run yet (load a save first)")
    if not main._last_summary:
        raise CheckFailed("the rebalance ran but found no story arcs (see the nsr log)")
    wrong = []
    categories = set()
    for entry in main._last_summary:
        categories.add(entry["category"])
        expected = classify.adjust_weight(entry["old_weight"], entry["category"])
        if entry["new_weight"] != expected or not entry.get("applied"):
            wrong.append("{}: {} -> {}, expected {}".format(
                entry["arc"], entry["old_weight"], entry["new_weight"], expected))
    if wrong:
        raise CheckFailed("; ".join(wrong[:3]))
    return "{} arcs, categories {}".format(len(main._last_summary), ", ".join(sorted(categories)))


@nsr.check("event tally readable")
def _nsr_tally(_context):
    main = live.require_module("nsr_main")
    events = live.import_optional("nsr_events")
    tally = main._tally if main._tally is not None else events.EventTally.load(main._EVENTS_PATH)
    lines = tally.summary_lines()
    detail = "{} events{}".format(len(tally.events), (" (" + "; ".join(lines) + ")") if lines else "")
    if any(event.get("result") == "FAILED_ACTION" for event in tally.events):
        detail += (" - FAILED_ACTION is EA's own result for an arc whose action could not run"
                   " (no valid sim/track); it is not a mod error")
    return detail


@nsr.check("arc classification")
def _nsr_classify(_context):
    classify = live.import_optional("nsr_classify")
    cases = {"simStoryArc_ChildrenStories_Pregnancy": "pregnancy",
             "householdStoryArc_MoveOut": "move_out",
             "simStoryArc_ChildrenStories_AdoptAHorse_Adult": "adopt_horse",
             "simStoryArc_Whatever": "other"}
    for name, expected in cases.items():
        got = classify.classify_arc(name)
        _assert(got == expected, "{} classified as {}, expected {}".format(name, got, expected))
    _assert(classify.adjust_weight(1, "move_out") == 10, "move_out weight was not x10")
    _assert(classify.adjust_weight(1, "adopt_child") == 1,
            "child adoption did not stay at the minimum weight")
    return "{} arcs plus weights".format(len(cases))


@nsr.check("pregnancy gate and daily guard installed")
def _nsr_pregnancy_gate(_context):
    import story_progression.story_progression_actions.story_progression_action_family as family

    main = live.require_module("nsr_main")
    life = live.import_optional("nsr_life")
    if family.MakePregnantStoryProgressionAction.setup_story_progression_action is not \
            main._patched_make_pregnant_setup:
        raise CheckFailed("EA's pregnancy action is not wrapped")
    if not life.gender_can_be_pregnant("FEMALE") or life.gender_can_be_pregnant("MALE"):
        raise CheckFailed("the gender gate does not allow only female sims")
    if life.EA_PREGNANCY_ALLOW_CHANCE >= 1.0:
        raise CheckFailed("EA's pregnancy gate is not reducing anything")
    if not hasattr(main, "_last_couple_day"):
        raise CheckFailed("the once-per-day guard is missing")
    if life.MAX_DAILY_MOVE_INS > 1 or life.MAX_DAILY_ROMANCES > 2:
        raise CheckFailed("the daily romance/move-in caps are missing")
    return "female-only, EA gate {:.0%}, once per day, romance<={} move-in<={}".format(
        life.EA_PREGNANCY_ALLOW_CHANCE, life.MAX_DAILY_ROMANCES, life.MAX_DAILY_MOVE_INS)


# ======================================================================================
# NPC Routines (and the optional local LLM)
# ======================================================================================
npc = REGISTRY.suite("npc", "NPC Routines and the local LLM")


@npc.check("modules loaded")
def _npc_modules(_context):
    live.require_modules("npc_main", "npc_routine", "npc_llm", "npc_brain")
    live.require_module("npc_main")._ensure_loaded()
    return "4 modules, routine store loaded"


@npc.check("routine round-trip")
def _npc_routine(_context):
    main = live.require_module("npc_main")
    routine_module = live.import_optional("npc_routine")
    sim_info = live.require_sim()
    sim_id = sim_info.sim_id
    store = main._store
    had = store.has(sim_id)
    before = store.get(sim_id).to_list()
    day, hour = 2, 3
    try:
        store.get(sim_id).add(routine_module.RoutineEntry([day], hour, 1, "paint"))
        due = store.get(sim_id).due_activity(day, hour)
        if due != "paint":
            raise CheckFailed("the test entry was not due (got {!r})".format(due))
    finally:
        if had:
            store.get(sim_id).entries = [routine_module.RoutineEntry.from_dict(d) for d in before]
        else:
            store.remove(sim_id)
        main._save()
    return "entry due and removed again ({} before)".format(len(before))


@npc.check("local LLM reachable")
def _npc_llm(_context):
    llm = live.require_module("npc_llm")
    brain = llm.data()
    url = str(brain.get("url") or "")
    model = str(brain.get("model") or "")
    if "/api/" not in url:
        raise CheckFailed("{} is not an Ollama-style server".format(url or "no URL"))
    base = url.split("/api/")[0]
    # urllib in the game's Python fails with "[Errno 0] Error" (it picks up a Windows proxy
    # that doesn't apply to localhost), so probe with a plain HTTP connection instead.
    import http.client
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(base)
        host = parts.hostname or "localhost"
        if host == "localhost":
            # The game's Python cannot always resolve "localhost" (getaddrinfo fails with
            # "[Errno 0] Error"); the literal loopback address needs no DNS lookup.
            host = "127.0.0.1"
        connection = http.client.HTTPConnection(host, parts.port or 80, timeout=3)
        try:
            connection.request("GET", "/api/tags")
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
    except Exception as e:
        raise SkipCheck("Ollama isn't running ({}: {}); start start-llm.cmd before playing".format(
            type(e).__name__, e))
    names = [str(item.get("name", "")) for item in payload.get("models", ())]
    # Any chat model will do; only the name in the mod's settings is a preference.
    if any(name == model or name.split(":")[0] == model for name in names):
        return "{} with {}".format(base, model)
    usable = [name for name in names if "embed" not in name.lower()]
    if not usable:
        raise CheckFailed("no model is pulled (models: {})".format(", ".join(names) or "none"))
    return "{} with {} (configured {} isn't pulled)".format(base, usable[0], model)


# ======================================================================================
# Ascent to Royalty
# ======================================================================================
royalty = REGISTRY.suite("royalty", "Ascent to Royalty (EP21)")


@royalty.check("module and promotion gate loaded")
def _royalty_modules(_context):
    main = live.require_module("atr_main")
    if not getattr(main, "_ACTIVE", False):
        raise SkipCheck("EP21 Royalty & Legacy is not installed; the mod is inactive")
    from careers.noble_career import NobleCareer
    if NobleCareer._promote is not main._promote:
        raise CheckFailed("NobleCareer._promote is not wrapped")
    return live.require_logged("ascent-to-royalty", "noble promotion gate installed", "the promotion gate")


@royalty.check("gate logic")
def _royalty_logic(_context):
    logic = live.import_optional("atr_logic")
    _assert(logic.rank_for_level(0, 9).male == "Knight", "level 0 is not the Knight rung")
    _assert(logic.rank_for_level(9, 9).male == "Monarch", "the top level is not the Monarch rung")
    _assert(logic.missing(9, 9, 0, 0, 0, ()), "an empty dynasty passed the crown gate")
    _assert(logic.missing(6, 9, 0, 0, 0, (), inherited=True) == [],
            "inherited peerage was gated")
    return "rank ladder, crown gate and inherited-peerage bypass"


@royalty.check("reads the selected sim")
def _royalty_live(_context):
    main = live.require_module("atr_main")
    sim_info = live.require_sim()
    career = main._noble_career(sim_info)
    if career is None:
        raise SkipCheck("{} is not in the Noble career (join it in game through a throne, "
                        "the noble book, or a title)".format(live.sim_name(sim_info)))
    level, maximum = main._level(career), main._max_level(career)
    _assert(0 <= level <= maximum, "level {} is outside 0..{}".format(level, maximum))
    return "{}: level {}/{}".format(live.sim_name(sim_info), level, maximum)
