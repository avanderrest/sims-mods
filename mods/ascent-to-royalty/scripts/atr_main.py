"""Ascent to Royalty - game layer. The rules are in atr_logic.py.

Hook: NobleCareer._promote. The pack's Noble career calls it for a performance promotion,
for inheriting a promised title, and for claiming an available title. Before that happens we
check the rank being moved to against the Sim's net worth and noble friendships, and refuse
(returning None, so no promotion dialog appears) when something is missing. Inherited,
married-in and claimed titles are always let through, including a promised crown: refusing
one inside the hook would leave the pack believing the title passed when it did not. The gate
is on the earned promotion path; the pack still decides who may inherit or claim, and keeps
one holder per world.

Where the numbers come from:
- Net worth: household net worth (money plus home).
- Friendship: the Sim must be friends with the right number of people outside their own
  dynasty. It gets gradually harder: one dynasty member, then two, then a dynasty head,
  then a royal dynasty member, two royal dynasty members, a royal dynasty head, and two
  royal dynasty heads. A royal dynasty is one whose head holds any Noble title; dynasty-less
  friends do not count. The threshold is FRIEND_MIN_SCORE.
- Crown: from Grand Duke the only requirement is that no higher rank is in the region: no
  Monarch holds the throne (the pack already enforces one holder per world).

The pack is required. Without EP21 the mod loads but stays inactive and logs why.

The requirements are visible in game. The career panel's own promotion list is EA client
tuning, so it cannot be filled from a script; instead the nine requirement aspirations
attached to the Noble career levels are overridden (tuning/NobleAspiration_*.xml,
tuning/NobleSavings_*.xml and tuning/NobleFriend_*.xml) to show the same requirements.
Those rows carry no test, so the game cannot complete them on its own. The script pushes
their values (money prints as "§current / §goal", not the default 0/1) and marks the
current level's aspiration milestone complete exactly when the gate below is met, which is
also what lets EA's own auto-promotion path run. The script gate remains the authority.

The check is live, never cached: every promotion attempt re-reads net worth, the friends and
the throne. In addition, the active household's nobles are re-checked each day just before
the career hands out the day's duties (a wrapper on clear_and_request_assignments), which
refreshes the panel rows whether or not a promotion is attempted. Promotion itself still
happens on the game's end-of-day performance path.

Cheats:
  houserules.royalty.status              this Sim, its rank and the next gate
  houserules.royalty.check [sim]         what the next promotion needs, and what is missing
  houserules.royalty.requirements [sim]  every requirement for the next rank, met or not
  houserules.royalty.levels              every native noble level and its gate
  houserules.royalty.on / .off
  houserules.royalty.set <kind> on|off   enabled, notify, net_worth, friend, monarch
  houserules.royalty.panel               re-send this Sim's panel rows (ticked when met)
  houserules.royalty.friends             every friend, their dynasty, and whether it counts
  houserules.royalty.invite              summon the closest-prestige dynasty's members
  houserules.royalty.ally <sim id>       form a native dynasty alliance (testing/politics)
  houserules.royalty.grant <level>       force a native noble level, bypassing the gate
  houserules.royalty.reset               forget this dynasty's recorded progress
"""
import json
import os
import re

import services
import sims4.commands
from server_commands.argument_helpers import (OptionalSimInfoParam, OptionalTargetParam,
                                             get_optional_target)

import atr_log
from atr_logic import (CHECKS, Friend, InviteDynasty, closest_dynasty, failure_text,
                       format_money, friend_counts, friend_requirement,
                       friend_requirement_text, friend_text, is_crown, missing,
                       rank_for_level, rank_title, requirements)

_FRIEND_MIN_SCORE = 30   # the game's friendship track: at/above this is a friend

_DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts", "The Sims 4", "Mods",
                         "HouseRules", "data")
_STATE_FILE = os.path.join(_DATA_DIR, "ascent_to_royalty.json")
_DEFAULTS = {"enabled": True, "notify": True, "net_worth": True, "friend": True,
             "monarch": True}
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


def _net_worth(sim_info):
    """Household net worth (funds plus home), the same number the career panel shows."""
    household = getattr(sim_info, "household", None)
    if household is None:
        return 0
    try:
        return household.household_net_worth()
    except Exception:
        try:
            return household.household_net_worth(billable=False)
        except Exception:
            try:
                return household.funds.money
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
            "best_level": -1,
            "promotions": [],
        }
        state["dynasties"][key] = record
    return record


def _royal_dynasty(dynasty):
    """True when the dynasty's head holds a Noble title (any level above 0)."""
    if dynasty is None:
        return False
    try:
        head = dynasty.get_head_sim_info()
    except Exception:
        return False
    return head is not None and _noble_level_of(head) is not None


def _friend_rows(sim_info):
    """Every friendship-qualified Sim, as (sim_info, dynasty, score, same, head, royal)."""
    tracker = getattr(sim_info, "relationship_tracker", None)
    if tracker is None:
        return []
    try:
        from relationships.relationship_track import RelationshipTrack
        track = RelationshipTrack.FRIENDSHIP_TRACK
    except Exception:
        atr_log.log_exception("reading the friendship track")
        return []
    own = _dynasty(sim_info)
    own_id = getattr(own, "id", None)
    manager = services.sim_info_manager()
    rows = []
    try:
        for other_id in tracker.target_sim_gen():
            try:
                if other_id == getattr(sim_info, "id", None):
                    continue
                score = tracker.get_relationship_score(other_id, track=track)
                if score is None or score < _FRIEND_MIN_SCORE:
                    continue
                other = manager.get(other_id)
                if other is None or getattr(other, "is_dead", False):
                    continue
                theirs = _dynasty(other)
                same = (own_id is not None and theirs is not None
                        and str(getattr(theirs, "id", None)) == str(own_id))
                head = (theirs is not None
                        and str(theirs.get_head_sim_id()) == str(getattr(other, "id", None)))
                rows.append((other, theirs, score, same, head, _royal_dynasty(theirs)))
            except Exception:
                continue
    except Exception:
        atr_log.log_exception("reading dynasty friends")
    return rows


def _has_other_dynasty(own):
    """True when there is a dynasty other than the Sim's own in the save."""
    if own is None:
        return True
    try:
        own_id = str(getattr(own, "id", None))
        return any(str(dynasty.id) != own_id
                   for dynasty in services.dynasty_service().get_all_dynasties().values())
    except Exception:
        return True


def _dynasty_friends(sim_info):
    """Friends outside the Sim's own dynasty that belong to a dynasty.

    A friend with no dynasty record no longer counts: the lowest rung asks for a dynasty
    member specifically. Kin in the Sim's own dynasty are excluded while another dynasty
    exists; when it is the only dynasty in the save, its members count too (the same
    fallback the throne's invitation uses). The facts the ladder needs (is this friend a
    dynasty head, is the dynasty royal) are read here so atr_logic stays free of game
    imports.
    """
    own = _dynasty(sim_info)
    allow_same = own is not None and not _has_other_dynasty(own)
    friends = []
    for other, theirs, _score, same, head, royal in _friend_rows(sim_info):
        if theirs is None:
            continue
        if same and not allow_same:
            continue
        friends.append(Friend(_name(other), head, royal))
    return friends


def _metrics(sim_info):
    dynasty = _dynasty(sim_info)
    record = _record(sim_info, dynasty)
    career = _noble_career(sim_info)
    max_level = _max_level(career) if career is not None else 0
    return {
        "dynasty": dynasty,
        "record": record,
        "net_worth": _net_worth(sim_info),
        "friends": _dynasty_friends(sim_info),
    }


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
        net_worth=metrics["net_worth"],
        friends=metrics["friends"],
        throne_empty=_throne_empty(sim_info, career),
        inherited=inherited,
        checks=_checks(),
    ), metrics


_PANEL_PREFIX = "HouseRules_Noble"


def _promotion_aspiration(career):
    return getattr(getattr(career, "current_level_tuning", None), "aspiration", None)


_PANEL_SAVINGS_ID = 0x7F000001
_PANEL_FRIEND_ID = 0x7F000011
_PANEL_MONARCH_ID = 0x7F000021


def _objective_by_id(instance_id):
    try:
        from sims4.resources import Types
        return services.get_instance_manager(Types.OBJECTIVE).get(instance_id)
    except Exception:
        return None


def _panel_objectives(career):
    """Our panel rows for this level's promotion, looked up by instance id.

    The career level's `aspiration` reference can still resolve to EA's copy even when the
    override is loaded (the client and the server tune separately), so the rows are not
    read from that list. The ids mirror tuning/NobleSavings_*, NobleFriend_* and
    NobleMonarch_*: the row for the promotion to rank N is LevelN.
    """
    target = _level(career) + 1
    if is_crown(target, _max_level(career)):
        ids = [_PANEL_MONARCH_ID]
    else:
        ids = []
        if target <= 8:
            ids.append(_PANEL_SAVINGS_ID + target - 1)
        if target <= 7:
            ids.append(_PANEL_FRIEND_ID + target - 1)
    return [objective for objective in (_objective_by_id(i) for i in ids)
            if objective is not None]


def _sync_promotion_milestone(sim_info, career=None, ready=None):
    """Mark the career panel's promotion task complete when the script gate is met.

    EA only auto-promotes when the current level's aspiration milestone is complete
    (`Career.evaluate_career_performance`). Our rows carry no objective test, so they can
    never complete on their own and the Sim would stay at its rank however ready the gate
    says. Completing the milestone (and our rows, so the panel ticks) closes that gap; when
    a requirement stops being met the milestone and our rows are cleared again. EA's own
    rows (Charisma on level 1) are left alone.
    """
    career = career or _noble_career(sim_info)
    if career is None:
        return None
    level = _level(career)
    max_level = _max_level(career)
    if level >= max_level:
        return None
    aspiration = _promotion_aspiration(career)
    tracker = getattr(sim_info, "aspiration_tracker", None)
    if aspiration is None or tracker is None:
        return None
    if _bypass or not _ACTIVE or not _settings().get("enabled", True):
        # The gate is off, so nothing may hold the game's own promotion path back.
        ready = True
    elif ready is None:
        found, _ = _failures(sim_info, career, min(max_level, level + 1))
        ready = not found
    server_objectives = list(getattr(aspiration, "objectives", ()) or ())
    panel_objectives = _panel_objectives(career)
    objectives = server_objectives + [o for o in panel_objectives
                                      if o not in server_objectives]
    try:
        if ready:
            changed = False
            for objective in objectives:
                if not tracker.objective_completed(objective):
                    tracker.complete_objective(objective, aspiration)
                    changed = True
            if not tracker.milestone_completed(aspiration):
                tracker.complete_milestone(aspiration, sim_info)
                changed = True
            if changed:
                tracker.send_if_dirty()
                atr_log.log("promotion task completed for {} (level {})".format(
                    _name(sim_info), level + 1))
        elif tracker.milestone_completed(aspiration):
            for objective in objectives:
                if tracker.objective_completed(objective):
                    tracker.reset_objective(objective)
            tracker.reset_milestone(aspiration)
            tracker.send_if_dirty()
            atr_log.log("promotion task reset for {} (level {})".format(
                _name(sim_info), level + 1))
    except Exception:
        atr_log.log_exception("syncing the promotion task")
    return ready


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
            "sim": _name(sim_info), "level": int(level),
            "net_worth": metrics["net_worth"],
            "friends": [friend.name for friend in metrics["friends"]],
        })
        _save()
        atr_log.log("promoted {} to noble level {} (net worth §{}, {} dynasty friend(s))".format(
            _name(sim_info), level, format_money(metrics["net_worth"]),
            len(metrics["friends"])))
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


# --- Daily check, before the day's duties ------------------------------------------------
_ASSIGNMENTS_ATTR = "_ascent_to_royalty_original_assignments"


def _in_active_household(sim_info):
    """Only the household the player is playing is re-checked every day."""
    try:
        household = services.active_household()
        return household is not None and getattr(sim_info, "household", None) is household
    except Exception:
        return False


def _daily_check(sim_info):
    """Re-read the gate and refresh the panel before the career hands out duties.

    Nothing is cached. Net worth, the outside-dynasty friend and a vacant throne are read
    again, so a row met yesterday unticks if the money was spent or the friend is gone.
    Promotion stays on the game's end-of-day performance path; this only makes sure the
    player sees an up-to-date check each day even when no promotion is attempted.
    """
    career = _noble_career(sim_info)
    if career is None:
        return
    _push_panel_status(sim_info)
    max_level = _max_level(career)
    level = _level(career)
    if level >= max_level:
        atr_log.log("daily check {}: already holds the crown".format(_name(sim_info)))
        return
    target = min(max_level, level + 1)
    found, _ = _failures(sim_info, career, target)
    atr_log.log("daily check {} -> level {}: {}".format(
        _name(sim_info), target,
        "missing " + failure_text(found) if found else "ready"))


def _wrap_assignments():
    """Run the check just before clear_and_request_assignments() gives the day's duties."""
    current = NobleCareer.clear_and_request_assignments
    if getattr(current, _ASSIGNMENTS_ATTR, None) is not None:
        return   # already wrapped (module reloaded)

    def clear_and_request_assignments(self, *args, **kwargs):
        try:
            if _ACTIVE and not _bypass and _in_active_household(self.sim_info):
                _daily_check(self.sim_info)
        except Exception:
            atr_log.log_exception("daily noble check before duties")
        return current(self, *args, **kwargs)

    setattr(clear_and_request_assignments, _ASSIGNMENTS_ATTR, current)
    NobleCareer.clear_and_request_assignments = clear_and_request_assignments
    atr_log.log("daily noble check armed before duty handout")


# --- Inviting dignitaries ------------------------------------------------------------
_INVITE_AFFORDANCE_ID = 16404971447273659384   # fnv64(name) with the high bit set
_INVITE_GUESTS = 3   # a gathering: two or three people, not an empty hall


def _noble_level_of(sim_info):
    """The Sim's Noble career level, or None when they hold no title."""
    career = _noble_career(sim_info)
    if career is None:
        return None
    try:
        level = _level(career)
    except Exception:
        atr_log.log_exception("reading a noble level")
        return None
    return level or None


def _dynasty_prestige(dynasty):
    """The pack's total dynasty prestige, or None when the Sim has no dynasty."""
    if dynasty is None:
        return None
    try:
        stat = dynasty.get_total_prestige_stat()
        if stat is not None:
            return float(stat.get_value())
    except Exception:
        pass
    try:
        return float(getattr(dynasty, "_total_prestige", 0) or 0)
    except Exception:
        return 0.0


def _invite_options(sim_info):
    """(own dynasty, own prestige, InviteDynasty list, dynasty by key).

    The Sim's own dynasty is left out when there is another one to call; it is used only
    when it is the sole dynasty in the save. A Sim with no dynasty has no prestige to
    compare, so every dynasty is a candidate and the lowest-prestige one wins.
    """
    service = services.dynasty_service()
    own = _dynasty(sim_info)
    own_key = str(own.id) if own is not None else None
    options = []
    by_key = {}
    for dynasty in service.get_all_dynasties().values():
        key = str(dynasty.id)
        if own_key is not None and key == own_key:
            continue
        if not _living_members(dynasty, sim_info):
            continue
        options.append(InviteDynasty(key, _dynasty_prestige(dynasty),
                                     _royal_dynasty(dynasty)))
        by_key[key] = dynasty
    if not options and own is not None and _living_members(own, sim_info):
        key = str(own.id)
        options.append(InviteDynasty(key, _dynasty_prestige(own), _royal_dynasty(own)))
        by_key[key] = own
    return own, _dynasty_prestige(own), options, by_key


def _living_members(dynasty, sim_info):
    """The dynasty's living members, most senior Noble first, excluding the host."""
    members = []
    try:
        manager = services.sim_info_manager()
        for sim_id in dynasty.get_members():
            if sim_id == getattr(sim_info, "id", None):
                continue
            member = manager.get(sim_id)
            if member is None or getattr(member, "is_dead", False):
                continue
            members.append(member)
    except Exception:
        atr_log.log_exception("gathering dynasty members")
    members.sort(key=lambda member: (-(_noble_level_of(member) or 0), _name(member)))
    return members


def _summon(sim_infos, host_sim_info):
    """Bring sims to the current lot as guests. False when there is no venue to bring them to.

    The venue's DEFAULT summoning (venue.summon_npcs) lets the venue decide what to do: on
    some lots that spawns the Sim without putting them in a situation, so they walk to the
    lot, find nothing holding them there and go straight home again - and one shared
    situation means the extra guests never show. The game's own visit situation (the one
    "ask to hang out" and "invite in" use) is made once per guest instead, so each of them
    is held on the lot for the visit's full duration.
    """
    venue = services.get_current_venue()
    if venue is None:
        return False
    manager = services.get_zone_situation_manager()
    unplaced = []
    placed = 0
    for sim_info in sim_infos:
        situation_id = None
        try:
            situation_id = manager.create_visit_situation(sim_info)
        except Exception:
            atr_log.log_exception("summoning {}".format(_name(sim_info)))
        if situation_id is None:
            unplaced.append(sim_info)
        else:
            placed += 1
    atr_log.log("summon: {} visit situation(s) for {} sim(s)".format(placed, len(sim_infos)))
    if not unplaced:
        return True
    # No visit situation for these (a venue without one, or a busy manager). The venue's
    # own summoning is the backstop: it at least spawns them on the lot.
    try:
        from venues.venue_constants import NPCSummoningPurpose
        venue.summon_npcs(tuple(unplaced), NPCSummoningPurpose.DEFAULT, host_sim_info)
        atr_log.log("summon: venue fallback for {}".format(
            ", ".join(_name(sim_info) for sim_info in unplaced)))
    except Exception:
        atr_log.log_exception("falling back to the venue's summoning")
    return placed > 0


def invite_dignitaries(sim_info):
    """Calls two or three people from the dynasty closest in prestige to the host.

    At Count (level 4) and above only royal dynasties are considered: a royal dynasty is
    one whose head holds a Noble title. A host with no dynasty has no prestige to compare,
    so the lowest-prestige dynasty is called instead. The host's own dynasty is not called
    unless it is the only one in the save. Sims are never invented - if the chosen dynasty
    has nobody living to come, the message says so.
    """
    career = _noble_career(sim_info)
    if career is None:
        return 0, "Only a noble can invite dignitaries."
    level = _level(career)
    own, host_prestige, options, by_key = _invite_options(sim_info)
    royal_only = level >= 4
    chosen = closest_dynasty(host_prestige, options, royal_only=royal_only)
    if chosen is None:
        if royal_only:
            return 0, "There is no royal dynasty to invite from."
        return 0, "There is no dynasty to invite from."
    dynasty = by_key[chosen.key]
    guests = _living_members(dynasty, sim_info)[:_INVITE_GUESTS]
    if not guests:
        return 0, "There is nobody living in {} to invite.".format(
            getattr(dynasty, "name", None) or "that dynasty")
    if not _summon(guests, sim_info):
        return 0, "You need to be on a lot to invite anyone."
    names = ", ".join(_name(guest) for guest in guests)
    if own is None:
        reason = "the lowest-prestige dynasty"
    else:
        reason = "closest in prestige to yours ({} vs {})".format(
            int(chosen.prestige), int(host_prestige or 0))
    atr_log.log("invited {} from {} for {} ({})".format(
        names, getattr(dynasty, "name", None) or chosen.key, _name(sim_info), reason))
    return len(guests), "Invited {} from {} ({}).".format(
        names, getattr(dynasty, "name", None) or "a dynasty", reason)


_THRONE_INTERACTION = 471359   # EP21's generic_Throne: every throne runs it
_throne_logged = False


def _is_throne(obj):
    """EP21's thrones, matched by their tuning name or by the throne interaction they all run.

    The name test alone is brittle (the object definitions are named things like
    object_NobleCareer_ThroneG...), so the interaction is the real signal.
    """
    definition = getattr(obj, "definition", None)
    name = getattr(definition, "name", None) or ""
    if "throne" in str(name).lower():
        return True
    for affordance in getattr(obj, "_super_affordances", ()) or ():
        if getattr(affordance, "guid64", None) == _THRONE_INTERACTION:
            return True
    return False


def _invite_affordance():
    from sims4.resources import Types
    return services.get_instance_manager(Types.INTERACTION).get(_INVITE_AFFORDANCE_ID)


_gate_test_class = None


def _noble_career_test():
    """A test instance that only passes for a Sim in the Noble career.

    The affordance is installed on every throne, so without this a commoner would see
    Invite Dignitaries and get the refusal only after clicking it.
    """
    global _gate_test_class
    if _gate_test_class is None:
        from event_testing.results import TestResult
        from event_testing.test_base import BaseTest
        from interactions import ParticipantType

        class InNobleCareerTest(BaseTest):
            def get_expected_args(self):
                return {"subjects": ParticipantType.Actor}

            def __call__(self, subjects=(), **kwargs):
                if not isinstance(subjects, (tuple, list)):
                    subjects = (subjects,)
                for subject in subjects or ():
                    try:
                        if subject is not None and _noble_career(subject) is not None:
                            return TestResult.TRUE
                    except Exception:
                        continue
                return TestResult(False, "Only a noble can invite dignitaries.",
                                  tooltip=(self.tooltip))

        _gate_test_class = InNobleCareerTest
    return _gate_test_class()


def _gate_invite_affordance(affordance):
    """Add the noble-career test to the affordance, once."""
    try:
        from event_testing.tests import TestList
        existing = tuple(getattr(affordance, "test_globals", ()) or ())
        if _gate_test_class is not None and any(
                isinstance(test, _gate_test_class) for test in existing):
            return
        affordance.test_globals = TestList(existing + (_noble_career_test(),))
        atr_log.log("throne: Invite Dignitaries is now limited to the Noble career")
    except Exception:
        atr_log.log_exception("gating Invite Dignitaries on the Noble career")


def _install_throne_affordance():
    """Adds Invite Dignitaries to every throne definition.

    Wrapping ScriptObject.potential_interactions turned out not to be on the path the pie
    menu takes for a throne, so the affordance is put on the tuning instead: the same place
    EA's own super affordances live, which the menu reads either way.
    """
    affordance = _invite_affordance()
    if affordance is None:
        atr_log.log("throne: Invite Dignitaries tuning not loaded (is the package installed?)")
        return
    _gate_invite_affordance(affordance)
    manager = services.definition_manager()
    patched = []
    for cls in getattr(manager, "types", {}).values():
        name = str(getattr(cls, "__name__", ""))
        if "throne" not in name.lower() or "light" in name.lower():
            continue
        try:
            existing = tuple(getattr(cls, "_super_affordances", ()) or ())
            if affordance in existing:
                continue
            cls._super_affordances = existing + (affordance,)
            patched.append(name)
        except Exception:
            atr_log.log_exception("adding the throne affordance to {}".format(name))
    # Objects already on the lot were built before the tuning changed.
    try:
        for obj in services.object_manager().values():
            definition = getattr(obj, "definition", None)
            if "throne" in str(getattr(definition, "__name__", "")).lower():
                existing = tuple(getattr(obj, "_super_affordances", ()) or ())
                if affordance not in existing:
                    obj._super_affordances = existing + (affordance,)
    except Exception:
        atr_log.log_exception("adding the throne affordance to objects on the lot")
    atr_log.log("throne: Invite Dignitaries added to {} definition(s): {}".format(
        len(patched), ", ".join(patched[:3]) or "none"))
    try:
        commands = [getattr(extra, "command", None)
                    for extra in getattr(affordance, "basic_extras", ())]
        atr_log.log("throne: affordance {} extras commands: {}".format(
            getattr(affordance, "__name__", affordance), commands))
    except Exception:
        atr_log.log_exception("reading the affordance's extras")


def _wrap_zone_load():
    """Runs the throne patch once a save has loaded.

    Called at script load, the interaction lookup fails: tuning is still being loaded
    incrementally, so manager.get() returns None and the affordance would never be added.
    """
    from zone import Zone
    current = Zone.on_loading_screen_animation_finished
    original = getattr(current, _ORIGINAL_ATTR, current)

    def on_loading_screen_animation_finished(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        try:
            _install_throne_affordance()
            _log_panel_tuning()
            active = services.active_sim_info()
            if active is not None:
                _push_panel_status(active)
        except Exception:
            atr_log.log_exception("installing the throne affordance after the zone loaded")
        return result

    setattr(on_loading_screen_animation_finished, _ORIGINAL_ATTR, original)
    Zone.on_loading_screen_animation_finished = on_loading_screen_animation_finished
    atr_log.log("throne patch armed for zone load")


# --- Career panel status ---------------------------------------------------------------
_PANEL_SAVINGS = re.compile(r"HouseRules_NobleSavings_Level(\d+)$")
_PANEL_FRIEND = re.compile(r"HouseRules_NobleFriend_Level(\d+)$")


def _panel_row(sim_info, objective, career=None):
    """The value the panel should show for one of our rows, or None for EA's own rows.

    Returns (current, goal, is_money, show_progress). The career is looked up only for our
    rows, so the game's own objectives are untouched.
    """
    name = str(getattr(objective, "__name__", ""))
    savings = _PANEL_SAVINGS.match(name)
    friend = _PANEL_FRIEND.match(name)
    is_ours = name.startswith(_PANEL_PREFIX)
    if savings is None and friend is None and not is_ours:
        return None
    if career is None:
        career = _noble_career(sim_info)
    if savings is not None:
        if career is None:
            return None
        rank = rank_for_level(int(savings.group(1)), _max_level(career))
        return (min(int(_net_worth(sim_info)), int(rank.net_worth)), int(rank.net_worth),
                True, True)
    if friend is not None:
        if career is None:
            return None
        need = friend_requirement(int(friend.group(1)), _max_level(career))
        if need is None:
            return None
        kind, count = need
        have = friend_counts(_dynasty_friends(sim_info))[kind]
        return min(have, count), count, False, True
    if name.startswith("HouseRules_NobleMonarch"):
        if career is None:
            return None
        return (1 if _throne_empty(sim_info, career) else 0), 1, False, False
    return None


def _push_panel_status(sim_info):
    """Tells the client what the panel's rows should read, and returns how many it pushed.

    The career panel draws its requirement rows from GoalsStatusUpdate, which is built from
    objective state - not from a test. A row with no test therefore sits at the default
    0/1. Pushing the values ourselves ticks the row when the requirement is met, and for
    money prints "§current / §goal" instead of a bare count. Nothing here touches the gate:
    atr_logic still decides promotions.
    """
    career = _noble_career(sim_info)
    if career is None:
        return 0
    # Keep the game's promotion task in step with the gate before sending its values.
    _sync_promotion_milestone(sim_info, career)
    tracker = getattr(sim_info, "aspiration_tracker", None)
    aspiration = getattr(career.current_level_tuning, "aspiration", None)
    if tracker is None or aspiration is None:
        atr_log.log("panel status not pushed for {}: {} aspiration, {} tracker".format(
            _name(sim_info), "no" if aspiration is None else "found",
            "no" if tracker is None else "found"))
        return 0
    pushed = 0
    rows = []
    objectives = _panel_objectives(career) or list(
        getattr(aspiration, "objectives", ()) or ())
    for objective in objectives:
        values = _panel_row(sim_info, objective, career)
        if values is None:
            continue   # EA's own rows (Charisma) are the game's business
        current, goal, is_money, progress = values
        try:
            # from_init=True is what makes the tracker send these values. EA's own
            # force_send_objective_update() does the same; without it the dirty rows are
            # dropped and the panel keeps its default 0/1.
            tracker.update_objective(objective, current, goal, is_money, progress,
                                     from_init=True)
            rows.append("{}={}/{}".format(
                getattr(objective, "__name__", objective), current, goal))
            pushed += 1
        except Exception:
            atr_log.log_exception("pushing panel status for {}".format(
                getattr(objective, "__name__", objective)))
    if not pushed:
        atr_log.log("panel status pushed nothing for {}: objectives are {}".format(
            _name(sim_info), [str(getattr(o, "__name__", o)) for o in objectives]))
    if pushed:
        try:
            tracker.send_if_dirty()
        except Exception:
            atr_log.log_exception("sending panel status")
        atr_log.log("panel status pushed for {}: {}".format(
            _name(sim_info), ", ".join(rows)))
    return pushed


# --- Keep the panel rows right when the game refreshes them -----------------------------
# EA sends the requirement rows itself on selection and load: CareerTracker.
# activate_career_aspirations() runs when the Sim is instantiated, and
# AspirationTracker.update_objective() is the single funnel for every goal value the
# client receives. Substituting our values there means no refresh can put the panel back
# to its default 0/1, whichever path triggered it.
_UPDATE_OBJECTIVE_ATTR = "_ascent_to_royalty_original_update_objective"
_CAREER_ACTIVATION_ATTR = "_ascent_to_royalty_original_activate_career_aspirations"
_CAREER_RESEND_ATTR = "_ascent_to_royalty_original_resend_career_data"


def _wrap_objective_updates():
    from aspirations.aspirations import AspirationTracker
    current = AspirationTracker.update_objective
    if getattr(current, _UPDATE_OBJECTIVE_ATTR, None) is not None:
        return   # already wrapped (module reloaded)

    def update_objective(self, objective, current_value, objective_value, is_money,
                         show_progress, *args, **kwargs):
        try:
            sim_info = getattr(self, "owner_sim_info", None)
            if sim_info is not None:
                values = _panel_row(sim_info, objective)
                if values is not None:
                    current_value, objective_value, is_money, show_progress = values
        except Exception:
            atr_log.log_exception("panel row values")
        return current(self, objective, current_value, objective_value, is_money,
                       show_progress, *args, **kwargs)

    setattr(update_objective, _UPDATE_OBJECTIVE_ATTR, current)
    AspirationTracker.update_objective = update_objective
    atr_log.log("panel row values hooked")


def _wrap_career_activation():
    from careers.career_tracker import CareerTracker
    current = CareerTracker.activate_career_aspirations
    if getattr(current, _CAREER_ACTIVATION_ATTR, None) is not None:
        return

    def activate_career_aspirations(self, *args, **kwargs):
        result = current(self, *args, **kwargs)
        try:
            sim_info = getattr(self, "_sim_info", None)
            if sim_info is not None:
                _push_panel_status(sim_info)
        except Exception:
            atr_log.log_exception("pushing panel status after career activation")
        return result

    setattr(activate_career_aspirations, _CAREER_ACTIVATION_ATTR, current)
    CareerTracker.activate_career_aspirations = activate_career_aspirations
    atr_log.log("panel status pushed after career activation")


def _wrap_career_resend():
    """The career panel asks for this when it opens (and on selection)."""
    from careers.career_tracker import CareerTracker
    current = CareerTracker.resend_career_data
    if getattr(current, _CAREER_RESEND_ATTR, None) is not None:
        return

    def resend_career_data(self, *args, **kwargs):
        result = current(self, *args, **kwargs)
        try:
            sim_info = getattr(self, "_sim_info", None)
            if sim_info is not None:
                _push_panel_status(sim_info)
        except Exception:
            atr_log.log_exception("pushing panel status after resending career data")
        return result

    setattr(resend_career_data, _CAREER_RESEND_ATTR, current)
    CareerTracker.resend_career_data = resend_career_data
    atr_log.log("panel status pushed after career resend")


# --- Reporting and cheats --------------------------------------------------------------
def _summary_lines(sim_info):
    career = _noble_career(sim_info)
    metrics = _metrics(sim_info)
    record = metrics["record"]
    counts = friend_counts(metrics["friends"])
    lines = [
        "Ascent to Royalty: {} (EP21 {})".format(
            "on" if _settings().get("enabled", True) else "off",
            "found" if _ACTIVE else "not installed - inactive"),
        "Dynasty: {} [{}], net worth §{}, friends: {} outside, {} heads, {} royal".format(
            record.get("name") or "?", record["key"], format_money(metrics["net_worth"]),
            counts["member"], counts["head"], counts["royal_member"]),
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
    lines.append("Next: {} (level {})".format(rank_title(target, max_level), target))
    if found:
        lines.append("  missing: " + failure_text(found))
    else:
        lines.append("  ready: nothing is missing")
    if is_crown(target, max_level):
        lines.append("  crown: throne vacant={}".format(_throne_empty(sim_info, career)))
    return lines


_KIND_LABELS = {"net_worth": "Net worth", "friend": "Friendship", "monarch": "Monarchy"}


def _requirement_lines(sim_info):
    """The next rank and every requirement for it, met or not.

    The gate only reports what is missing (missing()); this is the player-facing list shown
    by houserules.royalty.requirements and in the career panel.
    """
    career = _noble_career(sim_info)
    if career is None:
        return ["The selected Sim is not in the Noble career."]
    max_level = _max_level(career)
    current = _level(career)
    if current >= max_level:
        return ["{} already holds the crown (level {}).".format(_name(sim_info), current)]
    target = min(max_level, current + 1)
    metrics = _metrics(sim_info)
    rows = requirements(
        target, max_level,
        net_worth=metrics["net_worth"],
        friends=metrics["friends"],
        throne_empty=_throne_empty(sim_info, career),
        checks=_checks(),
    )
    lines = ["{}: {} (level {})".format(
        _name(sim_info), rank_title(target, max_level, getattr(sim_info, "is_female", False)),
        target)]
    for row in rows:
        lines.append("  [{}] {}: {}".format("met" if row.met else "needs",
                                            _KIND_LABELS.get(row.kind, row.kind), row.text))
    still = [row for row in rows if not row.met]
    if not rows:
        lines.append("  no requirements (the gate is switched off).")
    elif not still:
        lines.append("  ready: every requirement is met.")
    else:
        lines.append("  still needed: " + ", ".join(
            "{} {}".format(_KIND_LABELS.get(row.kind, row.kind), row.text) for row in still))
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


@sims4.commands.Command("houserules.royalty.requirements", command_type=sims4.commands.CommandType.Live)
def royalty_requirements(opt_sim: OptionalSimInfoParam = None, _connection=None):
    """Every requirement for the next rank, met or not."""
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _opt_sim(opt_sim, _connection)
    if sim_info is None:
        output("No Sim found (select one or pass a sim id).")
        return
    try:
        for line in _requirement_lines(sim_info):
            output(line)
            atr_log.log("requirements " + line)
    except Exception:
        atr_log.log_exception("royalty.requirements")
        output("royalty.requirements failed - see the log.")


@sims4.commands.Command("houserules.royalty.tuning", command_type=sims4.commands.CommandType.Live)
def royalty_tuning(_connection=None):
    """Diagnostic: the aspiration the career panel is using, and whether our tuning loaded."""
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _active_sim_or_output(output)
    if sim_info is None:
        return
    career = _noble_career(sim_info)
    if career is None:
        output("The selected Sim is not in the Noble career.")
        return
    try:
        aspiration = getattr(career.current_level_tuning, "aspiration", None)
        output("level {} aspiration: {}".format(
            _level(career), "none" if aspiration is None else getattr(aspiration, "guid64", "?")))
        for objective in getattr(aspiration, "objectives", ()) or ():
            test = getattr(objective, "objective_test", None)
            output("  objective {} {} (test: {})".format(
                getattr(objective, "guid64", "?"), objective, type(test).__name__))
        from sims4.resources import Types
        for name, type_ in (("aspiration", Types.ASPIRATION), ("objective", Types.OBJECTIVE)):
            manager = services.get_instance_manager(type_)
            ids = {getattr(cls, "guid64", None) for cls in manager.types.values()}
            output("{} manager: {} instances; 0x7F000001={} 0x7F000011={} 0x7F000021={}".format(
                name, len(ids), 0x7F000001 in ids, 0x7F000011 in ids, 0x7F000021 in ids))
    except Exception:
        atr_log.log_exception("royalty.tuning")
        output("royalty.tuning failed - see the log.")


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
        if level >= max_level:
            next_gate = "no promotion (the crown)"
        elif is_crown(level + 1, max_level):
            next_gate = "no Monarch in the region"
        else:
            need = friend_requirement(level + 1, max_level)
            friend_line = (friend_requirement_text(*need) if need is not None
                           else "no friendship requirement")
            next_gate = "§{} net worth, {}".format(
                format_money(rank_for_level(level + 1, max_level).net_worth), friend_line)
        output("  {}: {} - {}".format(level, rank_title(level, max_level), next_gate))
        atr_log.log("levels {}: {} -> {}".format(level, rank_title(level, max_level), next_gate))


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


@sims4.commands.Command("houserules.royalty.panel", command_type=sims4.commands.CommandType.Live)
def royalty_panel(_connection=None):
    """Re-sends this Sim's requirement rows to the career panel."""
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _active_sim_or_output(output)
    if sim_info is None:
        return
    pushed = _push_panel_status(sim_info)
    output("Panel rows updated: {}.".format(pushed) if pushed
           else "This Sim has no Noble career panel to update.")


@sims4.commands.Command("houserules.royalty.friends", command_type=sims4.commands.CommandType.Live)
def royalty_friends(_connection=None):
    """Why the dynasty-friend requirement is or isn't met, friend by friend."""
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _active_sim_or_output(output)
    if sim_info is None:
        return
    own = _dynasty(sim_info)
    own_id = str(getattr(own, "id", None)) if own is not None else None
    allow_same = own is not None and not _has_other_dynasty(own)
    output("{} own dynasty: {} [{}]{}".format(
        _name(sim_info), getattr(own, "name", None) or "none", own_id or "-",
        " (only dynasty in the save)" if allow_same else ""))
    rows = _friend_rows(sim_info)
    counts = friend_counts(_dynasty_friends(sim_info))
    for other, theirs, score, same, head, royal in rows:
        theirs_id = str(getattr(theirs, "id", None)) if theirs is not None else None
        if same:
            relation = "own dynasty, counts (only dynasty)" if allow_same else \
                "excluded (own dynasty)"
        elif theirs is None:
            relation = "excluded (no dynasty)"
        else:
            tags = ["member"]
            if head:
                tags.append("head")
            if royal:
                tags.append("royal")
            relation = ", ".join(tags)
        output("  {}: score {}, {} [{}] -> {}".format(
            _name(other), int(score), getattr(theirs, "name", None) or "none",
            theirs_id or "-", relation))
    if not rows:
        output("No friends at {}+ on the friendship track.".format(_FRIEND_MIN_SCORE))
    output("Counts: {} members, {} heads, {} royal members, {} royal heads".format(
        counts["member"], counts["head"], counts["royal_member"], counts["royal_head"]))
    atr_log.log("friends check for {}: {} qualifying rows, {}".format(
        _name(sim_info), len(rows), counts))


@sims4.commands.Command("houserules.royalty.invite", command_type=sims4.commands.CommandType.Live)
def royalty_invite(opt_sim: OptionalTargetParam = None, _interaction_id: float = None, _connection=None):
    """Run by the throne's Invite Dignitaries, and usable from the console.

    A do_command element passes the participant target and an interaction id; a bare
    (_connection) signature raises inside the command and the pie-menu click looks dead.
    """
    output = sims4.commands.CheatOutput(_connection)
    atr_log.log("royalty.invite invoked")
    try:
        target = get_optional_target(opt_sim, _connection)
        sim_info = getattr(target, "sim_info", target) or services.active_sim_info()
        if sim_info is None:
            output("No selected Sim.")
            return
        count, message = invite_dignitaries(sim_info)
        output(message)
        _notify("Invite Dignitaries", message, sim_info)
    except Exception:
        atr_log.log_exception("houserules.royalty.invite")


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
    """Forget this dynasty's recorded promotions."""
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


if _ACTIVE:
    try:
        _wrap_objective_updates()
    except Exception:
        atr_log.log_exception("hooking panel row values")
    try:
        _wrap_career_activation()
    except Exception:
        atr_log.log_exception("hooking career activation")
    try:
        _wrap_career_resend()
    except Exception:
        atr_log.log_exception("hooking career resend")
    try:
        _wrap_assignments()
    except Exception:
        atr_log.log_exception("arming the daily noble check")
    try:
        _wrap_zone_load()
    except Exception:
        atr_log.log_exception("arming the throne patch")

atr_log.log("ascent_to_royalty loaded: {}".format("active" if _ACTIVE else "inactive (no EP21)"))


# --- Panel tuning diagnostic ------------------------------------------------------------
# The career panel's Savings row comes from tuning/NobleAspiration_Level*.xml and
# tuning/NobleSavings_Level*.xml. Log whether those instances reached the game, so a build
# that ignores XML tuning is visible in the log rather than only as a missing row.
_NOBLE_ASPIRATION_LEVEL1 = 0x71D83
_NOBLE_NET_WORTH_LEVEL1 = 2130706433
_panel_tuning_logged = False


def _log_panel_tuning():
    """Log once, after a save has loaded: at script load the managers are still filling."""
    global _panel_tuning_logged
    if not _ACTIVE or _panel_tuning_logged:
        return
    _panel_tuning_logged = True
    try:
        from sims4.resources import Types

        def find(manager, instance_id):
            for cls in manager.types.values():
                if getattr(cls, "guid64", None) == instance_id:
                    return cls
            return None

        aspiration = find(services.get_instance_manager(Types.ASPIRATION), _NOBLE_ASPIRATION_LEVEL1)
        objective = find(services.get_instance_manager(Types.OBJECTIVE), _NOBLE_NET_WORTH_LEVEL1)
        objectives = getattr(aspiration, "objectives", None) if aspiration is not None else None
        atr_log.log("panel tuning: aspiration {}, {} objective(s); net-worth objective {}".format(
            "missing" if aspiration is None else "found",
            "?" if objectives is None else len(objectives),
            "missing" if objective is None else "found"))
    except Exception:
        atr_log.log_exception("checking the career-panel tuning")
