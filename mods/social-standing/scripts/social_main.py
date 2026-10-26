"""Social Standing - game layer. The rules are in social_logic.py.

Hook: RelationshipService.add_relationship_score. Every relationship gain from socials
(the StatisticAddRelationship loot EA's interactions use) goes through it. For a positive
change on a friendship or romance track between two teen-or-older humans, we multiply the
increment by our factor. Setting, lowering and decay never go through it, so they're untouched.

Where the numbers come from:
- Compatibility: shared/clashing personality traits (our list + every pair the game itself
  marks as conflicting), shared/opposed likes and dislikes, same age group, and Lovestruck's
  own compatibility score if that pack is installed.
- Status: household money + home value (log scale), Get Famous stars, the game's noble
  career rank (a title), and an optional "royal" flag set by cheat.
- Starstruck: when the gap is big, the lower-status sim gets Get Famous's "near a
  celebrity" moodlet (only with Get Famous; once per pair per sim day).

Cheats:
  houserules.social.status                - settings
  houserules.social.on / .off
  houserules.social.strength <0-100>      - 100 = full effect, 0 = none
  houserules.social.check <other sim id>  - both scores and the multipliers, for the selected sim
  houserules.social.royal on|off [sim]    - mark a sim as royalty (for saves without a title system)
"""
import os

import services
import sims4.commands
import sims4.resources
from server_commands.argument_helpers import OptionalSimInfoParam, get_optional_target

import social_log
from social_logic import (clash_pairs, compatibility, friendship_multiplier, is_starstruck, romance_multiplier,
                          status)

_DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts", "The Sims 4", "Mods",
                         "HouseRules", "data")
_SETTINGS_FILE = os.path.join(_DATA_DIR, "social_standing.json")
_DEFAULTS = {"enabled": True, "strength": 100, "royal": []}
_settings = None


def _get_settings():
    global _settings
    if _settings is None:
        import json
        _settings = dict(_DEFAULTS)
        try:
            if os.path.exists(_SETTINGS_FILE):
                with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                    _settings.update(json.load(f))
        except Exception:
            social_log.log_exception("loading settings")
    return _settings


def _save_settings():
    import json
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(_settings, f)
    except Exception:
        social_log.log_exception("saving settings")


def _now_hours():
    return services.time_service().sim_now.absolute_hours()


# --- Status ----------------------------------------------------------------------------
_status_cache = {}   # sim_id -> (hour, status, parts)


def _fame_stars(sim_info):
    try:
        from fame.fame_tuning import FameTunables
        fame_type = FameTunables.FAME_RANKED_STATISTIC
        if fame_type is None:
            return 0
        stat = sim_info.commodity_tracker.get_statistic(fame_type)
        return int(stat.rank_level) if stat is not None else 0
    except Exception:
        return 0


def _noble_level(sim_info):
    try:
        kingdom = services.kingdom_service()
        if kingdom is None:
            return 0
        return kingdom.get_noble_career_user_level(sim_info.sim_id) or 0
    except Exception:
        return 0


def _wealth(sim_info):
    household = sim_info.household
    if household is None:
        return 0
    try:
        return household.household_net_worth(billable=False)
    except Exception:
        return household.funds.money


def _status(sim_info):
    hour = _now_hours()
    cached = _status_cache.get(sim_info.sim_id)
    if cached is not None and hour - cached[0] < 1:
        return cached[1], cached[2]
    royal = sim_info.sim_id in set(_get_settings().get("royal", []))
    parts = {"wealth": _wealth(sim_info), "fame": _fame_stars(sim_info), "noble": _noble_level(sim_info),
             "royal": royal}
    value = status(parts["wealth"], parts["fame"], parts["noble"], parts["royal"])
    _status_cache[sim_info.sim_id] = (hour, value, parts)
    _prune(_status_cache, hour, 1)
    return value, parts


# --- Compatibility ---------------------------------------------------------------------
# The cache key includes each sim's profile (age, personality traits, likes, dislikes), so
# a trait gained, a preference changed or an age-up invalidates the pair's entry at once.
# Lovestruck's own score is not in the key; it can drift for up to the cache lifetime.
COMPAT_CACHE_HOURS = 6
CACHE_LIMIT = 4096
_compat_cache = {}   # (id_a, id_b, profile_a, profile_b) -> (hour, score)
_extra_clashes = None


def _game_clashes():
    """Every pair of personality traits the game forbids on one sim (Neat/Slob ...)."""
    global _extra_clashes
    if _extra_clashes is None:
        pairs = set()
        try:
            from traits.trait_type import TraitType
            manager = services.get_instance_manager(sims4.resources.Types.TRAIT)
            if manager is not None:
                traits = [t for t in manager.types.values()
                          if getattr(t, 'trait_type', None) == TraitType.PERSONALITY]
                for t in traits:
                    for other in getattr(t, 'conflicting_traits', ()) or ():
                        pairs.add((t.__name__, other.__name__))
        except Exception:
            social_log.log_exception("reading trait conflicts")
        _extra_clashes = clash_pairs(pairs)
        social_log.log("trait clashes known: {}".format(len(_extra_clashes)))
    return _extra_clashes


def _likes(sim_info):
    from traits.trait_type import TraitType
    tracker = sim_info.trait_tracker
    likes = {getattr(t, "preference_item", t) for t in tracker.get_preferences((TraitType.LIKE,))}
    dislikes = {getattr(t, "preference_item", t) for t in tracker.get_preferences((TraitType.DISLIKE,))}
    return likes, dislikes


def _profile(sim_info):
    """Everything the compatibility score is built from: cheap to read, hashable."""
    traits = tuple(sorted(t.__name__ for t in sim_info.trait_tracker.personality_traits))
    likes, dislikes = _likes(sim_info)
    return (sim_info.age, traits, frozenset(likes), frozenset(dislikes))


def _lovestruck_score(a, b):
    try:
        from sims4.common import Pack, is_available_pack
        if not is_available_pack(Pack.EP13):
            return None
        return services.relationship_service().get_compatibility_score(a.sim_id, b.sim_id)
    except Exception:
        return None


def _prune(cache, hour, max_age_hours):
    """Drop expired entries once the cache gets big, so long saves don't grow forever."""
    if len(cache) < 512:
        return
    for key in [k for k, v in cache.items() if hour - v[0] >= max_age_hours]:
        cache.pop(key, None)
    if len(cache) > CACHE_LIMIT:
        cache.clear()


def _compatibility(a, b):
    profile_a, profile_b = _profile(a), _profile(b)
    if a.sim_id <= b.sim_id:
        key = (a.sim_id, b.sim_id, profile_a, profile_b)
    else:
        key = (b.sim_id, a.sim_id, profile_b, profile_a)
    hour = _now_hours()
    cached = _compat_cache.get(key)
    if cached is not None and hour - cached[0] < COMPAT_CACHE_HOURS:
        return cached[1]
    score = compatibility(profile_a[1], profile_b[1], profile_a[2], profile_a[3], profile_b[2], profile_b[3],
                          same_age=profile_a[0] == profile_b[0], clashes=_game_clashes(),
                          ea_score=_lovestruck_score(a, b))
    _compat_cache[key] = (hour, score)
    _prune(_compat_cache, hour, COMPAT_CACHE_HOURS)
    return score


def _is_family(a, b):
    try:
        if b.sim_id in set(a.genealogy.get_family_sim_ids_gen()):
            return True
        return a.household_id is not None and a.household_id == b.household_id
    except Exception:
        return False


def _friendship_score(a, b):
    try:
        return services.relationship_service().get_relationship_score(a.sim_id, b.sim_id) or 0
    except Exception:
        return 0


def _eligible(sim_info):
    return sim_info is not None and sim_info.is_human and sim_info.is_teen_or_older


def _apply_strength(multiplier):
    strength = max(0, min(100, int(_get_settings().get("strength", 100)))) / 100.0
    return 1.0 + (multiplier - 1.0) * strength


# --- The hook --------------------------------------------------------------------------
from relationships.relationship_service import RelationshipService
from relationships.relationship_track import RelationshipTrack
from singletons import DEFAULT

# Remember the real method on our own wrapper, so reloading this module (or another copy of
# it) reuses the original instead of wrapping our wrapper and recursing forever.
_ORIGINAL_ATTR = "_social_standing_original"
_current = RelationshipService.add_relationship_score
_original_add = getattr(_current, _ORIGINAL_ATTR, _current)


def _track_kind(track):
    """'friendship' / 'romance' for the game's own tracks, else None (nothing is touched)."""
    if track is DEFAULT:
        try:
            from relationships.global_relationship_tuning import RelationshipGlobalTuning
            track = RelationshipGlobalTuning.REL_INSPECTOR_TRACK
        except Exception:
            return None
    for known, kind in ((getattr(RelationshipTrack, "FRIENDSHIP_TRACK", None), "friendship"),
                        (getattr(RelationshipTrack, "ROMANCE_TRACK", None), "romance")):
        if known is not None and track is known:
            return kind
    # Packs and other mods can pass their own track classes: go by name as a fallback.
    name = (getattr(track, "__name__", None) or type(track).__name__).lower()
    if "friendship" in name:
        return "friendship"
    if "romance" in name:
        return "romance"
    return None


def add_relationship_score(self, sim_id_a, sim_id_b, increment, *args, **kwargs):
    """Pass-through wrapper: EA's signature (and any mod that changes it) is left intact."""
    try:
        if increment and increment > 0 and _get_settings().get("enabled"):
            track = args[0] if args else kwargs.get("track", DEFAULT)
            kind = _track_kind(track)
            if kind is not None:
                increment = increment * _multiplier_for(sim_id_a, sim_id_b, kind)
    except Exception:
        social_log.log_exception("relationship gain")
    return _original_add(self, sim_id_a, sim_id_b, increment, *args, **kwargs)


setattr(add_relationship_score, _ORIGINAL_ATTR, _original_add)
_starstruck_given = {}  # (lower id, higher id) -> sim day
_starstruck_day = None


def _multiplier_for(sim_id_a, sim_id_b, kind):
    manager = services.sim_info_manager()
    a, b = manager.get(sim_id_a), manager.get(sim_id_b)
    if not (_eligible(a) and _eligible(b)):
        return 1.0
    status_a, _ = _status(a)
    status_b, _ = _status(b)
    gap = status_a - status_b
    family = _is_family(a, b)
    compat = _compatibility(a, b)
    if kind == "friendship":
        mult = friendship_multiplier(compat, gap, family, _friendship_score(a, b))
    else:
        mult = romance_multiplier(compat, gap, family)
    if not family:
        _maybe_starstruck(a, status_a, b, status_b)
    return _apply_strength(mult)


def _maybe_starstruck(a, status_a, b, status_b):
    global _starstruck_day
    if is_starstruck(status_a, status_b):
        low, high = a, b
    elif is_starstruck(status_b, status_a):
        low, high = b, a
    else:
        return
    day = int(_now_hours() // 24)
    if day != _starstruck_day:
        # The guard is only "once per pair per day", so yesterday's entries are dead weight.
        _starstruck_given.clear()
        _starstruck_day = day
    key = (low.sim_id, high.sim_id)
    if _starstruck_given.get(key) == day:
        return
    _starstruck_given[key] = day
    buff = _starstruck_buff()
    if buff is None:
        return  # Get Famous not installed
    try:
        low.add_buff_from_op(buff, buff_reason=None)
        social_log.log("{} is starstruck by {}".format(_name(low), _name(high)))
    except Exception:
        social_log.log_exception("starstruck buff")


_buff = False


def _starstruck_buff():
    """Get Famous's "near a celebrity" moodlet, or None without that pack."""
    global _buff
    if _buff is False:
        _buff = None
        for cls in services.get_instance_manager(sims4.resources.Types.BUFF).types.values():
            if cls.__name__ == "buff_Celebrity_NearCelebrity":
                _buff = cls
                break
        social_log.log("starstruck moodlet: {}".format(_buff.__name__ if _buff else "not found (no Get Famous)"))
    return _buff


def _name(sim_info):
    return "{} {}".format(sim_info.first_name, sim_info.last_name).strip()


RelationshipService.add_relationship_score = add_relationship_score
social_log.log("relationship hook installed")


# --- Cheats ----------------------------------------------------------------------------
@sims4.commands.Command("houserules.social.status", command_type=sims4.commands.CommandType.Live)
def social_status(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    s = _get_settings()
    output("Social Standing: {}, strength {}%, sims marked royal: {}".format(
        "on" if s.get("enabled") else "off", s.get("strength"), len(s.get("royal", []))))


@sims4.commands.Command("houserules.social.on", command_type=sims4.commands.CommandType.Live)
def social_on(_connection=None):
    _get_settings()["enabled"] = True
    _save_settings()
    sims4.commands.CheatOutput(_connection)("Social Standing is on.")


@sims4.commands.Command("houserules.social.off", command_type=sims4.commands.CommandType.Live)
def social_off(_connection=None):
    _get_settings()["enabled"] = False
    _save_settings()
    sims4.commands.CheatOutput(_connection)("Social Standing is off.")


@sims4.commands.Command("houserules.social.strength", command_type=sims4.commands.CommandType.Live)
def social_strength(value: int = 100, _connection=None):
    _get_settings()["strength"] = max(0, min(100, value))
    _save_settings()
    sims4.commands.CheatOutput(_connection)("Social Standing strength: {}%".format(_get_settings()["strength"]))


@sims4.commands.Command("houserules.social.royal", command_type=sims4.commands.CommandType.Live)
def social_royal(state: str = "on", opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = get_optional_target(opt_sim, _connection, target_type=OptionalSimInfoParam)
    if sim_info is None or state not in ("on", "off"):
        output("Usage: houserules.social.royal on|off [sim id]")
        return
    royal = set(_get_settings().get("royal", []))
    (royal.add if state == "on" else royal.discard)(sim_info.sim_id)
    _get_settings()["royal"] = sorted(royal)
    _save_settings()
    _status_cache.pop(sim_info.sim_id, None)
    output("{} is {} royal.".format(_name(sim_info), "now" if state == "on" else "no longer"))


@sims4.commands.Command("houserules.social.check", command_type=sims4.commands.CommandType.Live)
def social_check(other_sim_id: int = 0, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    me = services.active_sim_info()
    other = services.sim_info_manager().get(other_sim_id) if other_sim_id else None
    if other is None:
        try:
            sim = services.get_active_sim()
            ids = [i for i in sim.sim_info.relationship_tracker.target_sim_gen()] if sim else []
            output("Pass the other sim's id. Sims the selected sim knows: " + ", ".join(
                "{} ({})".format(_name(services.sim_info_manager().get(i)), i)
                for i in ids[:15] if services.sim_info_manager().get(i) is not None))
        except Exception:
            output("Pass the other sim's id: houserules.social.check <sim id>")
        return
    try:
        s_me, p_me = _status(me)
        s_other, p_other = _status(other)
        compat = _compatibility(me, other)
        family = _is_family(me, other)
        friendship = _friendship_score(me, other)
        lines = [
            "{}: status {:.2f} {}".format(_name(me), s_me, p_me),
            "{}: status {:.2f} {}".format(_name(other), s_other, p_other),
            "compatibility {:.2f}, family {}, friendship now {:.0f}".format(compat, family, friendship),
            "friendship gain x{:.2f}, romance gain x{:.2f} (strength {}%)".format(
                _apply_strength(friendship_multiplier(compat, s_me - s_other, family, friendship)),
                _apply_strength(romance_multiplier(compat, s_me - s_other, family)), _get_settings().get("strength")),
        ]
    except Exception:
        social_log.log_exception("social.check")
        output("social.check failed - see the log.")
        return
    for line in lines:
        output(line)
        social_log.log("social.check " + line)
