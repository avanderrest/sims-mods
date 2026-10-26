"""Ascent to Royalty - game layer. The rules are in atr_logic.py.

Hook: NobleCareer._promote. The pack's Noble career calls it for a performance promotion,
for inheriting a promised title, and for claiming an available title. Before that happens we
check the rank being moved to against the dynasty's wealth, generation, alliances and
milestones, and refuse (returning None, so no promotion dialog appears) when something is
missing. Inherited, married-in and claimed titles are always let through, including a
promised crown: refusing one inside the hook would leave the pack believing the title passed
when it did not. The gate is on the earned promotion path; the pack still decides who may
inherit or claim, and keeps one holder per world.

Where the numbers come from:
- Wealth: household net worth (money plus home).
- Generation: family-tree depth below the first Sim recorded for this dynasty. It rises when
  the title passes to a descendant, and never goes back down.
- Alliances: the pack's own dynasty alliances (counted on both sides).
- Milestones: a living heir in the dynasty, and a dynasty member at the top of a non-noble
  career.
- Crown: the claimant must be the dynasty head and the world's top noble title must be vacant
  (the pack already enforces one holder per world; this only reports it).

The pack is required. Without EP21 the mod loads but stays inactive and logs why.

Cheats:
  houserules.royalty.status              this dynasty, its rank and the next gate
  houserules.royalty.check [sim]         what the next promotion needs, and what is missing
  houserules.royalty.levels              every native noble level and its gate
  houserules.royalty.on / .off
  houserules.royalty.set <kind> on|off   enabled, notify, wealth, generation, alliances,
                                         milestones, crown
  houserules.royalty.ally <sim id>       form a native dynasty alliance (testing/politics)
  houserules.royalty.grant <level>       force a native noble level, bypassing the gate
  houserules.royalty.reset               forget this dynasty's recorded progress
"""
import json
import os

import services
import sims4.commands
from server_commands.argument_helpers import OptionalSimInfoParam, get_optional_target

import atr_log
from atr_logic import (CHECKS, failure_text, format_money, missing, rank_for_level,
                       rank_title)

_DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts", "The Sims 4", "Mods",
                         "HouseRules", "data")
_STATE_FILE = os.path.join(_DATA_DIR, "ascent_to_royalty.json")
_DEFAULTS = {"enabled": True, "notify": True, "wealth": True, "generation": True,
             "alliances": True, "milestones": True, "crown": True}
_SETTING_KEYS = tuple(_DEFAULTS)

# EP21 = Royalty & Legacy. NobleCareer lives in its simulation scripts.
_ACTIVE = False
NobleCareer = None
try:
    from sims4.common import Pack, is_available_pack
    _HAS_PACK = is_available_pack(Pack.EP21)
except Exception:
    _HAS_PACK = False
if _HAS_PACK:
    try:
        from careers.noble_career import NobleCareer
        _ACTIVE = NobleCareer is not None
    except Exception:
        atr_log.log_exception("importing NobleCareer (is EP21 installed?)")
else:
    atr_log.log("EP21 Royalty & Legacy is not installed: the mod is inactive", level="WARN")

_data = None
_bypass = False
_notified = {}
_notified_day = None


# --- Saved data ------------------------------------------------------------------------
def _state():
    """Load once. The file is per computer, like the other HouseRules mods' data files."""
    global _data
    if _data is None:
        _data = {"settings": dict(_DEFAULTS), "dynasties": {}}
        try:
            if os.path.exists(_STATE_FILE):
                with open(_STATE_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if isinstance(saved, dict):
                    _data["settings"].update(saved.get("settings") or {})
                    _data["dynasties"] = saved.get("dynasties") or {}
        except Exception:
            atr_log.log_exception("loading the state file")
    return _data


def _settings():
    return _state()["settings"]


def _save():
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        tmp = _STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state(), f, indent=1, sort_keys=True)
        os.replace(tmp, _STATE_FILE)
    except Exception:
        atr_log.log_exception("saving the state file")


def _checks():
    """The kinds of gate that are switched on."""
    settings = _settings()
    return {kind for kind in CHECKS if settings.get(kind, True)}


# --- Reading the game ------------------------------------------------------------------
def _today():
    try:
        return round(services.time_service().sim_now.absolute_days(), 2)
    except Exception:
        return 0.0


def _name(sim_info):
    return "{} {}".format(getattr(sim_info, "first_name", ""), getattr(sim_info, "last_name", "")).strip() \
        or str(getattr(sim_info, "sim_id", "?"))


def _wealth(sim_info):
    """Savings, not the home. The ladder is calibrated to Noble pay, so an expensive house
    should not buy a title; three generations of steady salary should."""
    household = getattr(sim_info, "household", None)
    if household is None:
        return 0
    try:
        return household.funds.money
    except Exception:
        try:
            return household.household_net_worth(billable=False)
        except Exception:
            return 0


def _noble_career(sim_info):
    tracker = getattr(sim_info, "career_tracker", None)
    if tracker is None:
        return None
    try:
        from kingdom.kingdom_tuning import KingdomTuning
        noble_guid = KingdomTuning.NOBLE_CAREER.guid64
    except Exception:
        noble_guid = None
    for career in getattr(tracker, "careers", {}).values():
        try:
            if noble_guid is not None and career.guid64 == noble_guid:
                return career
            if noble_guid is None and "noble" in career.__class__.__name__.lower():
                return career
        except Exception:
            continue
    return None


def _level(career):
    try:
        return int(career.level)
    except Exception:
        return int(getattr(career, "_level", 0) or 0)


def _max_level(career):
    try:
        levels = career.current_track_tuning.career_levels
        return max(0, len(levels) - 1)
    except Exception:
        return 0


def _dynasty(sim_info):
    try:
        return services.dynasty_service().get_sim_dynasty(sim_info.id)
    except Exception:
        return None


def _record_key(sim_info, dynasty):
    if dynasty is not None:
        return "dynasty:{}".format(dynasty.id)
    household = getattr(sim_info, "household", None)
    household_id = getattr(household, "id", None)
    return "household:{}".format(household_id if household_id is not None else "unknown")


def _record(sim_info, dynasty):
    state = _state()
    key = _record_key(sim_info, dynasty)
    record = state["dynasties"].get(key)
    if record is None:
        record = {
            "key": key,
            "name": (getattr(sim_info, "last_name", "") or _name(sim_info)),
            "founder_id": getattr(sim_info, "id", None),
            "founded": _today(),
            "base_depth": None,
            "generation": 1,
            "milestones": {},
            "best_level": -1,
            "promotions": [],
        }
        state["dynasties"][key] = record
    return record


def _generation(sim_info, record):
    """Family-tree depth relative to the first titled generation we recorded.

    A Sim with no family tree still counts as generation 1. The stored value only ever
    rises, so a save reload or a new head cannot reset the climb.
    """
    depth = None
    try:
        depth = sim_info.genealogy.get_generation_depth()
    except Exception:
        depth = None
    if depth is None:
        return max(1, int(record.get("generation", 1)))
    if record.get("base_depth") is None:
        record["base_depth"] = depth
    try:
        generation = max(1, int(depth) - int(record["base_depth"]) + 1)
    except (TypeError, ValueError):
        generation = 1
    record["generation"] = max(int(record.get("generation", 1)), generation)
    return record["generation"]


def _alliance_count(dynasty):
    if dynasty is None:
        return 0
    try:
        service = services.dynasty_service()
        return sum(1 for other in service.get_all_dynasties().values()
                   if other.id != dynasty.id and dynasty.is_ally(other))
    except Exception:
        atr_log.log_exception("counting dynasty alliances")
        return 0


def _dynasty_sims(sim_info, dynasty):
    """Every Sim whose milestones count for this dynasty."""
    if dynasty is not None:
        manager = services.sim_info_manager()
        found = []
        for sim_id in dynasty.get_members():
            member = manager.get(sim_id)
            if member is not None and not getattr(member, "is_dead", False):
                found.append(member)
        if found:
            return found
    household = getattr(sim_info, "household", None)
    if household is not None:
        try:
            return [member for member in household.sim_info_gen()
                    if not getattr(member, "is_dead", False)]
        except Exception:
            pass
    return [sim_info]


def _has_heir(sim_info, dynasty):
    try:
        head = dynasty.get_head_sim_info() if dynasty is not None else None
    except Exception:
        head = None
    head = head or sim_info
    try:
        for child in head.genealogy.get_child_sim_infos_gen():
            if child is None or getattr(child, "is_dead", False):
                continue
            if dynasty is None or dynasty.is_member(child.id):
                return True
    except Exception:
        atr_log.log_exception("looking for an heir")
    return False


def _has_career_peak(sim_info, dynasty):
    """A dynasty member at the top level of a non-noble career."""
    try:
        from kingdom.kingdom_tuning import KingdomTuning
        noble_guid = KingdomTuning.NOBLE_CAREER.guid64
    except Exception:
        noble_guid = None
    for member in _dynasty_sims(sim_info, dynasty):
        tracker = getattr(member, "career_tracker", None)
        if tracker is None:
            continue
        for career in getattr(tracker, "careers", {}).values():
            try:
                if noble_guid is not None and career.guid64 == noble_guid:
                    continue
                levels = career.current_track_tuning.career_levels
                if levels and career.level >= len(levels) - 1:
                    return True
            except Exception:
                continue
    return False


def _milestones(sim_info, record, dynasty):
    known = record.setdefault("milestones", {})
    if "heir" not in known and _has_heir(sim_info, dynasty):
        known["heir"] = _today()
        atr_log.log("milestone for {}: heir".format(_name(sim_info)))
    if "career_peak" not in known and _has_career_peak(sim_info, dynasty):
        known["career_peak"] = _today()
        atr_log.log("milestone for {}: career_peak".format(_name(sim_info)))
    return set(known)


def _metrics(sim_info):
    dynasty = _dynasty(sim_info)
    record = _record(sim_info, dynasty)
    return {
        "dynasty": dynasty,
        "record": record,
        "wealth": _wealth(sim_info),
        "generation": _generation(sim_info, record),
        "alliances": _alliance_count(dynasty),
        "milestones": _milestones(sim_info, record, dynasty),
    }


def _is_head(sim_info, dynasty):
    if dynasty is None:
        return False
    try:
        return dynasty.get_head_sim_id() == sim_info.id
    except Exception:
        return False


def _throne_empty(sim_info, career):
    try:
        service = services.kingdom_service()
        neighborhood_id = service.get_sim_neighborhood_id(sim_info)
        return service.is_level_empty(neighborhood_id, _max_level(career))
    except Exception:
        # Let the pack's own exclusive-level check decide if we cannot read the kingdom.
        return True


def _is_inherited(reason):
    try:
        from careers.career_enums import CareerPromotionReason
        return reason in (CareerPromotionReason.KINGDOM_INHERIT_PROMISED_SIM,
                          CareerPromotionReason.KINGDOM_CLAIM_TITLE)
    except Exception:
        return False


# --- The gate --------------------------------------------------------------------------
def _failures(sim_info, career, target, inherited=False):
    metrics = _metrics(sim_info)
    return missing(
        target, _max_level(career),
        wealth=metrics["wealth"],
        generation=metrics["generation"],
        alliances=metrics["alliances"],
        milestones=metrics["milestones"],
        is_head=_is_head(sim_info, metrics["dynasty"]),
        throne_empty=_throne_empty(sim_info, career),
        inherited=inherited,
        census_known=metrics["dynasty"] is not None,
        checks=_checks(),
    ), metrics


def _notify(title, text, owner=None):
    if not _settings().get("notify", True):
        return
    try:
        from sims4.localization import LocalizationHelperTuning
        from ui.ui_dialog_notification import UiDialogNotification
        owner = owner or services.active_sim_info()
        dialog = UiDialogNotification.TunableFactory().default(
            owner,
            title=lambda *_, **__: LocalizationHelperTuning.get_raw_text(title),
            text=lambda *_, **__: LocalizationHelperTuning.get_raw_text(text))
        dialog.show_dialog()
    except Exception:
        atr_log.log_exception("showing a notification")


def _tell_blocked(sim_info, career, target, failures):
    """One notification per Sim, target and Sim day, so auto-promotion cannot spam."""
    global _notified_day
    day = int(_today())
    if day != _notified_day:
        _notified.clear()
        _notified_day = day
    key = (getattr(sim_info, "id", None), target)
    if key in _notified:
        return
    _notified[key] = True
    rank = rank_title(target, _max_level(career), getattr(sim_info, "is_female", False))
    text = "{} cannot become {} yet. The dynasty still needs: {}.".format(
        _name(sim_info), rank, failure_text(failures))
    atr_log.log("blocked {} -> level {} ({}): {}".format(_name(sim_info), target, rank,
                                                         failure_text(failures)))
    _notify("Ascent to Royalty", text, sim_info)


def _record_promotion(sim_info, level):
    """Remember a promotion that actually happened (the native dialog already showed)."""
    try:
        metrics = _metrics(sim_info)
        record = metrics["record"]
        record["best_level"] = max(int(record.get("best_level", -1)), int(level))
        record.setdefault("promotions", []).append({
            "day": _today(), "sim_id": getattr(sim_info, "id", None),
            "sim": _name(sim_info), "level": int(level), "generation": metrics["generation"],
        })
        _save()
        atr_log.log("promoted {} to noble level {} (generation {}, {} allies)".format(
            _name(sim_info), level, metrics["generation"], metrics["alliances"]))
    except Exception:
        atr_log.log_exception("recording a promotion")


def _allow(sim_info, career, levels_to_promote, reason):
    if _bypass or not _ACTIVE or not _settings().get("enabled", True):
        return True
    target = min(_max_level(career), _level(career) + max(1, int(levels_to_promote or 1)))
    found, _ = _failures(sim_info, career, target, inherited=_is_inherited(reason))
    if not found:
        return True
    _tell_blocked(sim_info, career, target, found)
    return False


# --- Hook ------------------------------------------------------------------------------
_ORIGINAL_ATTR = "_ascent_to_royalty_original"


def _no_gate(self, *args, **kwargs):
    return None


if _ACTIVE:
    _current = NobleCareer._promote
    _original = getattr(_current, _ORIGINAL_ATTR, _current)

    def _promote(self, levels_to_promote=1, allow_branch_popup_for_npc=False, reason=None):
        """Pass-through wrapper: the pack's signature is left intact."""
        try:
            if not _allow(self.sim_info, self, levels_to_promote, reason):
                return None
        except Exception:
            atr_log.log_exception("noble promotion gate")
        before = _level(self)
        result = _original(self, levels_to_promote=levels_to_promote,
                           allow_branch_popup_for_npc=allow_branch_popup_for_npc, reason=reason)
        try:
            after = _level(self)
            if after > before:
                _record_promotion(self.sim_info, after)
        except Exception:
            atr_log.log_exception("recording a promotion outcome")
        return result

    setattr(_promote, _ORIGINAL_ATTR, _original)
    NobleCareer._promote = _promote
    atr_log.log("noble promotion gate installed")
else:
    _promote = _no_gate


# --- Reporting and cheats --------------------------------------------------------------
def _summary_lines(sim_info):
    career = _noble_career(sim_info)
    metrics = _metrics(sim_info)
    record = metrics["record"]
    lines = [
        "Ascent to Royalty: {} (EP21 {})".format(
            "on" if _settings().get("enabled", True) else "off",
            "found" if _ACTIVE else "not installed - inactive"),
        "Dynasty: {} [{}], generation {}, wealth §{}, alliances {}".format(
            record.get("name") or "?", record["key"], metrics["generation"],
            format_money(metrics["wealth"]), metrics["alliances"]),
        "Milestones: {}".format(", ".join(sorted(metrics["milestones"])) or "none yet"),
    ]
    if career is None:
        lines.append("Selected Sim is not in the Noble career.")
        return lines
    max_level = _max_level(career)
    current = _level(career)
    rank = rank_for_level(current, max_level)
    lines.append("Noble level {}/{} ({})".format(current, max_level, rank_title(current, max_level)))
    if current >= max_level:
        lines.append("This Sim already holds the crown. The throne stays subject to the gate on succession.")
        return lines
    target = current + 1
    found, _ = _failures(sim_info, career, target)
    nxt = rank_for_level(target, max_level)
    lines.append("Next: {} (level {})".format(rank_title(target, max_level), target))
    if found:
        lines.append("  missing: " + failure_text(found))
    else:
        lines.append("  ready: nothing is missing")
    if is_crown(target, max_level):
        lines.append("  crown: head={}, throne vacant={}".format(
            _is_head(sim_info, metrics["dynasty"]), _throne_empty(sim_info, career)))
    return lines


def _active_sim_or_output(output):
    sim_info = services.active_sim_info()
    if sim_info is None:
        output("No selected Sim. Load a save and select one first.")
    return sim_info


def _opt_sim(opt_sim, connection):
    sim_info = get_optional_target(opt_sim, connection, target_type=OptionalSimInfoParam)
    if sim_info is None:
        sim_info = services.active_sim_info()
    return sim_info


@sims4.commands.Command("houserules.royalty.status", command_type=sims4.commands.CommandType.Live)
def royalty_status(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _active_sim_or_output(output)
    if sim_info is None:
        return
    try:
        lines = _summary_lines(sim_info)
    except Exception:
        atr_log.log_exception("royalty.status")
        output("royalty.status failed - see the log.")
        return
    for line in lines:
        output(line)
        atr_log.log("status " + line)


@sims4.commands.Command("houserules.royalty.check", command_type=sims4.commands.CommandType.Live)
def royalty_check(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _opt_sim(opt_sim, _connection)
    if sim_info is None:
        output("No Sim found (select one or pass a sim id).")
        return
    try:
        for line in _summary_lines(sim_info):
            output(line)
            atr_log.log("check " + line)
    except Exception:
        atr_log.log_exception("royalty.check")
        output("royalty.check failed - see the log.")


@sims4.commands.Command("houserules.royalty.levels", command_type=sims4.commands.CommandType.Live)
def royalty_levels(_connection=None):
    """The native noble ladder and the gate on each rung."""
    output = sims4.commands.CheatOutput(_connection)
    try:
        from kingdom.kingdom_tuning import KingdomTuning
        track = KingdomTuning.NOBLE_CAREER_TRACK
        levels = track.career_levels
        max_level = len(levels) - 1
    except Exception:
        atr_log.log_exception("reading the noble career track")
        output("The noble career track could not be read (is EP21 installed?).")
        return
    output("Noble levels ({}):".format(len(levels)))
    for level in range(len(levels)):
        rank = rank_for_level(level, max_level)
        output("  {}: {} - §{} | generation {} | {} alliance{} | {}".format(
            level, rank_title(level, max_level), format_money(rank.wealth), rank.generation,
            rank.alliances, "" if rank.alliances == 1 else "s",
            ", ".join(rank.milestones) or "no milestones"))
        atr_log.log("levels {}: {} §{} gen {} allies {}".format(
            level, rank_title(level, max_level), rank.wealth, rank.generation, rank.alliances))


@sims4.commands.Command("houserules.royalty.set", command_type=sims4.commands.CommandType.Live)
def royalty_set(key: str = "", value: str = "", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    if key not in _SETTING_KEYS:
        output("Settings: {}".format(", ".join(_SETTING_KEYS)))
        return
    if value not in ("on", "off"):
        output("Usage: houserules.royalty.set {} on|off".format(key))
        return
    _settings()[key] = value == "on"
    _save()
    atr_log.log("setting {} = {}".format(key, value))
    output("Ascent to Royalty: {} is now {}.".format(key, value))


@sims4.commands.Command("houserules.royalty.on", command_type=sims4.commands.CommandType.Live)
def royalty_on(_connection=None):
    _settings()["enabled"] = True
    _save()
    sims4.commands.CheatOutput(_connection)("Ascent to Royalty is on.")


@sims4.commands.Command("houserules.royalty.off", command_type=sims4.commands.CommandType.Live)
def royalty_off(_connection=None):
    _settings()["enabled"] = False
    _save()
    sims4.commands.CheatOutput(_connection)("Ascent to Royalty is off.")


@sims4.commands.Command("houserules.royalty.ally", command_type=sims4.commands.CommandType.Live)
def royalty_ally(opt_sim: OptionalSimInfoParam = None, _connection=None):
    """Form a native dynasty alliance with another Sim's dynasty (testing / politics)."""
    output = sims4.commands.CheatOutput(_connection)
    me = services.active_sim_info()
    other = _opt_sim(opt_sim, _connection)
    if me is None or other is None or other.id == me.id:
        output("Usage: select a Sim, then houserules.royalty.ally <other sim id>.")
        return
    mine, theirs = _dynasty(me), _dynasty(other)
    if mine is None or theirs is None:
        output("Both Sims need a native dynasty (EP21).")
        return
    try:
        services.dynasty_service().add_alliance(mine, theirs)
    except Exception:
        atr_log.log_exception("forming an alliance")
        output("The alliance could not be formed - see the log.")
        return
    atr_log.log("alliance: {} <-> {}".format(_name(me), _name(other)))
    output("Alliance formed: dynasty {} and dynasty {}.".format(mine.id, theirs.id))


@sims4.commands.Command("houserules.royalty.grant", command_type=sims4.commands.CommandType.Live)
def royalty_grant(level: int = 0, _connection=None):
    """Force a native noble level, bypassing the gate. For testing and recovery."""
    global _bypass
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _active_sim_or_output(output)
    if sim_info is None:
        return
    career = _noble_career(sim_info)
    if career is None:
        output("The selected Sim is not in the Noble career.")
        return
    maximum = _max_level(career)
    target = max(0, min(maximum, int(level)))
    difference = target - _level(career)
    if difference == 0:
        output("Already at noble level {}.".format(target))
        return
    _bypass = True
    try:
        services.kingdom_service().change_noble_career_level(sim_info.id, target, difference)
    except Exception:
        try:
            (career.promote if difference > 0 else career.demote)(abs(difference))
        except Exception:
            atr_log.log_exception("royalty.grant")
            output("The level could not be changed - see the log.")
            _bypass = False
            return
    finally:
        _bypass = False
    output("{} is now noble level {}.".format(_name(sim_info), target))
    atr_log.log("grant: {} -> level {}".format(_name(sim_info), target))


@sims4.commands.Command("houserules.royalty.reset", command_type=sims4.commands.CommandType.Live)
def royalty_reset(_connection=None):
    """Forget this dynasty's recorded generation, milestones and promotions."""
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _active_sim_or_output(output)
    if sim_info is None:
        return
    dynasty = _dynasty(sim_info)
    key = _record_key(sim_info, dynasty)
    removed = _state()["dynasties"].pop(key, None)
    _save()
    atr_log.log("reset {}".format(key))
    output("Progress for {} {}.".format(key, "cleared" if removed else "was not recorded"))


atr_log.log("ascent_to_royalty loaded: {}".format("active" if _ACTIVE else "inactive (no EP21)"))
