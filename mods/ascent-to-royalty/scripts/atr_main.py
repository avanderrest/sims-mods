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
- Friendship: the Sim must be friends with someone outside their own dynasty. Rank is not
  consulted - a default save has barely any titled sims. Friendship is the game's friendship
  track; the threshold is FRIEND_MIN_SCORE.
- Crown: from Grand Duke the only requirement is that no higher rank is in the region: no
  Monarch holds the throne (the pack already enforces one holder per world).

The pack is required. Without EP21 the mod loads but stays inactive and logs why.

The requirements are visible in game. The career panel's own promotion list is EA client
tuning, so it cannot be filled from a script; instead the nine requirement aspirations
attached to the Noble career levels are overridden (tuning/NobleAspiration_*.xml,
tuning/NobleSavings_*.xml and tuning/NobleFriend_*.xml) to show the same two requirements.
Those rows are display only: the game cannot test net worth, a friend's noble rank or a
vacant throne from a career objective, so they never complete on their own. The values are
pushed to the panel (money prints as "§current / §goal", not the default 0/1); the script
gate below is the authority.

The check is live, never cached: every promotion attempt re-reads net worth, the friend and
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
  houserules.royalty.invite              summon the nobles at or below this Sim's rank
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
from atr_logic import (CHECKS, failure_text, format_money, is_crown, missing, noble_guests,
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


def _dynasty_friend(sim_info):
    """The name of a friend outside the Sim's own dynasty, or None.

    Rank is deliberately not consulted: a default save has barely any titled sims. Only kin
    in one's *own* dynasty are excluded - a friend who belongs to no dynasty at all counts,
    which is what makes this reachable (the pack's noble NPCs have no dynasty record).
    """
    tracker = getattr(sim_info, "relationship_tracker", None)
    if tracker is None:
        return None
    try:
        from relationships.relationship_track import RelationshipTrack
        track = RelationshipTrack.FRIENDSHIP_TRACK
    except Exception:
        atr_log.log_exception("reading the friendship track")
        return None
    own = _dynasty(sim_info)
    own_id = getattr(own, "id", None)
    manager = services.sim_info_manager()
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
                if own_id is not None and theirs is not None                         and str(getattr(theirs, "id", None)) == str(own_id):
                    continue   # same family: not an outside alliance
                return _name(other)
            except Exception:
                continue
    except Exception:
        atr_log.log_exception("reading dynasty friends")
    return None


def _metrics(sim_info):
    dynasty = _dynasty(sim_info)
    record = _record(sim_info, dynasty)
    career = _noble_career(sim_info)
    max_level = _max_level(career) if career is not None else 0
    return {
        "dynasty": dynasty,
        "record": record,
        "net_worth": _net_worth(sim_info),
        "dynasty_friend": _dynasty_friend(sim_info),
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
        dynasty_friend=metrics["dynasty_friend"],
        throne_empty=_throne_empty(sim_info, career),
        inherited=inherited,
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
            "sim": _name(sim_info), "level": int(level),
            "net_worth": metrics["net_worth"], "friend": metrics["dynasty_friend"],
        })
        _save()
        atr_log.log("promoted {} to noble level {} (net worth §{}, dynasty friend {})".format(
            _name(sim_info), level, format_money(metrics["net_worth"]),
            metrics["dynasty_friend"]))
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


# --- Inviting fellow nobles ------------------------------------------------------------
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


def _sims_by_rank(sim_info, level):
    """Every other noble in the save, as [(sim_info, level)]; noble_guests trims the list."""
    rows = []
    manager = getattr(services, "sim_info_manager", None)
    if manager is None:
        return rows
    for other in manager().values():
        if other is sim_info:
            continue
        try:
            other_level = _noble_level_of(other)
        except Exception:
            continue
        if other_level:
            rows.append((other, other_level))
    return noble_guests(rows, level)


def _dynasty_guests(sim_info):
    """Kin from the Sim's dynasty, used when there is no other noble to call.

    With the pack's noble NPCs not in the save yet there may be nobody at or below the
    Sim's rank, so the invitation falls back to their dynasty. If the Sim belongs to no
    dynasty, every dynasty is considered.
    """
    members = []
    try:
        service = services.dynasty_service()
        own = _dynasty(sim_info)
        dynasties = [own] if own is not None else list(service.get_all_dynasties().values())
        seen = set()
        for dynasty in dynasties:
            for sim_id in dynasty.get_members():
                if sim_id == sim_info.id or sim_id in seen:
                    continue
                member = service and services.sim_info_manager().get(sim_id)
                if member is None:
                    continue
                seen.add(sim_id)
                members.append((member, _noble_level_of(member)))
    except Exception:
        atr_log.log_exception("gathering dynasty members")
    return members


def _summon(sim_infos, host_sim_info):
    """Bring sims to the current lot. False when there is no venue to bring them to."""
    venue = services.get_current_venue()
    if venue is None:
        return False
    from venues.venue_constants import NPCSummoningPurpose
    venue.summon_npcs(tuple(sim_infos), NPCSummoningPurpose.DEFAULT, host_sim_info)
    return True


def invite_fellow_nobles(sim_info):
    """Calls two or three people to the lot. Returns (count, message).

    Rank comes first: the most senior nobles at or below the Sim's own rank, highest rank
    first, and a higher-ranked noble never answers a lower one. If that is not enough to
    make a gathering, the Sim's dynasty fills the rest (never anyone above the Sim's rank),
    which is what makes this useful before the pack's noble NPCs exist in a save. Sims are
    never invented - if the save has nobody to call, it says so.
    """
    level = _noble_level_of(sim_info)
    if level is None:
        return 0, "Only a noble can invite fellow nobles."
    # Rank decides first: the most senior nobles at or below the Sim's own rank, then
    # dynasty kin only to fill the room. A dynasty member above the Sim's rank never comes,
    # and a titled one is already in the noble list.
    nobles = sorted(_sims_by_rank(sim_info, level), key=lambda pair: -(pair[1] or 0))
    guests = list(nobles[:_INVITE_GUESTS])
    chosen = {guest.id for guest, _ in guests}
    if len(guests) < _INVITE_GUESTS:
        for member, member_level in _dynasty_guests(sim_info):
            if len(guests) >= _INVITE_GUESTS:
                break
            if member.id in chosen:
                continue
            if member_level is not None and member_level > level:
                continue
            chosen.add(member.id)
            guests.append((member, member_level))
    if not guests:
        return 0, "There is no other noble at your rank or below, and no dynasty to call on."
    if not _summon([guest for guest, _ in guests], sim_info):
        return 0, "You need to be on a lot to invite anyone."
    nobles_called = sum(1 for guest, _ in guests if _noble_level_of(guest) is not None)
    names = ", ".join(_name(guest) for guest, _ in guests)
    atr_log.log("invited {} for {} ({} noble(s), {} dynasty)".format(
        names, _name(sim_info), nobles_called, len(guests) - nobles_called))
    if len(guests) == 1:
        return 1, "Only {} could come: {}. There is nobody else at your rank or below.".format(
            names, "a noble" if nobles_called else "a dynasty member")
    return len(guests), "Invited {} ({} noble(s), {} from your dynasty).".format(
        names, nobles_called, len(guests) - nobles_called)


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


def _install_throne_affordance():
    """Adds Invite Fellow Nobles to every throne definition.

    Wrapping ScriptObject.potential_interactions turned out not to be on the path the pie
    menu takes for a throne, so the affordance is put on the tuning instead: the same place
    EA's own super affordances live, which the menu reads either way.
    """
    affordance = _invite_affordance()
    if affordance is None:
        atr_log.log("throne: Invite Fellow Nobles tuning not loaded (is the package installed?)")
        return
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
    atr_log.log("throne: Invite Fellow Nobles added to {} definition(s): {}".format(
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


def _panel_row(sim_info, objective, career=None):
    """The value the panel should show for one of our rows, or None for EA's own rows.

    Returns (current, goal, is_money, show_progress). The career is looked up only for our
    rows, so the game's own objectives are untouched.
    """
    name = str(getattr(objective, "__name__", ""))
    match = _PANEL_SAVINGS.match(name)
    is_ours = name.startswith("HouseRules_Noble")
    if match is None and not is_ours:
        return None
    if career is None:
        career = _noble_career(sim_info)
    if match is not None:
        if career is None:
            return None
        rank = rank_for_level(int(match.group(1)), _max_level(career))
        return (min(int(_net_worth(sim_info)), int(rank.net_worth)), int(rank.net_worth),
                True, True)
    if name.startswith("HouseRules_NobleFriend"):
        return (1 if _dynasty_friend(sim_info) else 0), 1, False, False
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
    tracker = getattr(sim_info, "aspiration_tracker", None)
    aspiration = getattr(career.current_level_tuning, "aspiration", None)
    if tracker is None or aspiration is None:
        atr_log.log("panel status not pushed for {}: {} aspiration, {} tracker".format(
            _name(sim_info), "no" if aspiration is None else "found",
            "no" if tracker is None else "found"))
        return 0
    pushed = 0
    rows = []
    for objective in getattr(aspiration, "objectives", ()) or ():
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
    friend = metrics["dynasty_friend"] or "none"
    lines = [
        "Ascent to Royalty: {} (EP21 {})".format(
            "on" if _settings().get("enabled", True) else "off",
            "found" if _ACTIVE else "not installed - inactive"),
        "Dynasty: {} [{}], net worth §{}, friend in a dynasty: {}".format(
            record.get("name") or "?", record["key"], format_money(metrics["net_worth"]), friend),
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
        dynasty_friend=metrics["dynasty_friend"],
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
            next_gate = "§{} net worth, a friend at {} or above".format(
                format_money(rank_for_level(level + 1, max_level).net_worth),
                rank_title(level, max_level))
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
    output("{} own dynasty: {} [{}]".format(
        _name(sim_info), getattr(own, "name", None) or "none", own_id or "-"))
    tracker = getattr(sim_info, "relationship_tracker", None)
    if tracker is None:
        output("No relationship tracker.")
        return
    try:
        from relationships.relationship_track import RelationshipTrack
        track = RelationshipTrack.FRIENDSHIP_TRACK
    except Exception:
        atr_log.log_exception("reading the friendship track")
        return
    manager = services.sim_info_manager()
    rows = 0
    for other_id in tracker.target_sim_gen():
        if other_id == getattr(sim_info, "id", None):
            continue
        score = tracker.get_relationship_score(other_id, track=track)
        if score is None or score < _FRIEND_MIN_SCORE:
            continue
        other = manager.get(other_id)
        if other is None:
            continue
        theirs = _dynasty(other)
        theirs_id = str(getattr(theirs, "id", None)) if theirs is not None else None
        relation = "no dynasty"
        if theirs is not None:
            relation = "SAME dynasty" if (own_id is not None and theirs_id == own_id) else "other dynasty"
        output("  {}: score {}, {} [{}] -> {}".format(
            _name(other), int(score), getattr(theirs, "name", None) or "none",
            theirs_id or "-", "counts" if relation != "SAME dynasty" else "excluded"))
        rows += 1
    if not rows:
        output("No friends at {}+ on the friendship track.".format(_FRIEND_MIN_SCORE))
    atr_log.log("friends check for {}: {} qualifying rows".format(_name(sim_info), rows))


@sims4.commands.Command("houserules.royalty.invite", command_type=sims4.commands.CommandType.Live)
def royalty_invite(opt_sim: OptionalTargetParam = None, _interaction_id: float = None, _connection=None):
    """Run by the throne's Invite Fellow Nobles, and usable from the console.

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
        count, message = invite_fellow_nobles(sim_info)
        output(message)
        _notify("Invite Fellow Nobles", message, sim_info)
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
