"""Aspiration Progress - game layer. The ordering rules are in asp_logic.py.

How EA's aspirations work (aspirations/aspirations.py, event_testing/event_data_tracker.py):
- A level (milestone) only hears about the game's events while it's registered with the
  event manager, and EA registers only the sim's *active* level. Registration is per level,
  not per sim, and the manager is cleared on every zone load.
- A goal (objective) pays its satisfaction points the moment it completes
  (AspirationTracker.complete_objective). A level pays its reward when all its goals are done
  (complete_milestone). The aspiration's trait is the track reward, which EA only gives once
  every level of the track is complete (_check_and_complete_aspiration_track).
- Selecting an aspiration skips levels that are already complete; switching never resets goals.

What this mod changes:
1. On every zone load, every level of every aspiration track (child ones too) is registered,
   so goals count whenever they happen. Goals of levels you haven't reached count from the
   game's own lifetime totals (EA only resets a goal's count when its level becomes active).
2. Levels flagged to only listen while active (do_not_register_events_on_load) listen anyway.
3. complete_milestone, for aspiration levels: pays the level's reward straight away, and if
   the level belongs to the selected aspiration, moves the sim to the first level that isn't
   complete yet (EA moves to "the level after the one just finished", which would skip
   unfinished levels when a later one is done first). A track finished out of order - even
   one not selected - gives its trait once every level is done.

Cheats:
  houserules.asp.status [sim]  - levels already done ahead of where the sim is
  houserules.asp.on / .off
"""
import json
import os

import services
import sims4.commands
import sims4.resources
from aspirations.aspiration_types import AspriationType
from aspirations.aspirations import AspirationTracker
from event_testing.event_data_tracker import EventDataTracker
from event_testing.test_events import TestEvent
from server_commands.argument_helpers import OptionalSimInfoParam, get_optional_target

import asp_log
from asp_logic import ahead_of, all_complete, first_incomplete, index_tracks

_SETTINGS_FILE = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts", "The Sims 4", "Mods",
                              "HouseRules", "data", "aspiration_progress.json")
_settings = None


def _enabled():
    global _settings
    if _settings is None:
        _settings = {"enabled": True}
        try:
            if os.path.exists(_SETTINGS_FILE):
                with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                    _settings.update(json.load(f))
        except Exception:
            asp_log.log_exception("loading settings")
    return _settings.get("enabled", True)


def _set_enabled(value):
    _enabled()
    _settings["enabled"] = bool(value)
    try:
        os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(_settings, f)
    except Exception:
        asp_log.log_exception("saving settings")


# --- Tracks and levels ------------------------------------------------------------------
_tracks = None      # [(track, [level, ...] in order), ...]
_index = None       # level -> [track, ...]


def _load_tracks():
    global _tracks, _index
    if _tracks is None:
        tracks = []
        for track in services.get_instance_manager(sims4.resources.Types.ASPIRATION_TRACK).types.values():
            try:
                levels = [level for _, level in (track.get_aspirations() or ())]
            except Exception:
                levels = []
            levels = [lv for lv in levels if getattr(lv, "aspiration_type", None) == AspriationType.FULL_ASPIRATION]
            if levels:
                tracks.append((track, levels))
        _tracks = tracks
        _index = index_tracks(tracks)
        asp_log.log("aspiration tracks found: {} ({} levels)".format(len(_tracks), len(_index)))
    return _tracks, _index


def _register_all_levels():
    _, index = _load_tracks()
    done = 0
    for level in index:
        try:
            level.register_callbacks()
            done += 1
        except Exception:
            asp_log.log_exception("registering {}".format(level.__name__))
    asp_log.log("registered {} aspiration levels for events".format(done))


# --- EA overrides -------------------------------------------------------------------------
_original_should_handle = AspirationTracker._should_handle_event
_original_complete = AspirationTracker.complete_milestone


def _should_handle_event(self, milestone, event, resolver):
    result = _original_should_handle(self, milestone, event, resolver)
    if result or not _enabled():
        return result
    try:
        if milestone.aspiration_type == AspriationType.FULL_ASPIRATION and milestone.do_not_register_events_on_load \
                and EventDataTracker._should_handle_event(self, milestone, event, resolver):
            return True
    except Exception:
        asp_log.log_exception("_should_handle_event")
    return result


def complete_milestone(self, aspiration, sim_info):
    if not _enabled() or getattr(aspiration, "aspiration_type", None) != AspriationType.FULL_ASPIRATION:
        return _original_complete(self, aspiration, sim_info)
    if not aspiration.is_valid_for_sim(sim_info):
        return
    # From here on this replaces EA's branch for aspiration levels (see the module docstring).
    EventDataTracker.complete_milestone(self, aspiration, sim_info)
    if aspiration.reward is not None:
        aspiration.reward.give_reward(sim_info)
    active_track = self.active_track
    in_active = active_track is not None and aspiration in active_track.aspirations.values()
    try:
        _after_level_complete(self, aspiration, sim_info, active_track, in_active)
    except Exception:
        asp_log.log_exception("after completing {}".format(aspiration.__name__))
    services.get_event_manager().process_event(TestEvent.UnlockEvent, sim_info=sim_info, unlocked=aspiration)
    services.get_event_manager().process_event(TestEvent.MilestoneCompleted, sim_info=sim_info)


def _after_level_complete(tracker, aspiration, sim_info, active_track, in_active):
    if aspiration.screen_slam is not None:
        if in_active:
            aspiration.screen_slam.send_screen_slam_message(sim_info, sim_info, aspiration.display_name,
                                                            active_track.display_text)
        else:
            aspiration.screen_slam.send_screen_slam_message(sim_info, sim_info, aspiration.display_name)
    aspiration.apply_on_complete_loot_actions(sim_info)
    _, index = _load_tracks()
    tracks = list(index.get(aspiration, ()))
    if in_active and active_track not in tracks:
        tracks.append(active_track)
    for track in tracks:
        levels = [level for _, level in track.get_aspirations()]
        if all_complete(levels, tracker.milestone_completed):
            tracker._check_and_complete_aspiration_track(track, aspiration.guid64, sim_info)
            asp_log.log("{}: finished the whole aspiration {}".format(_name(sim_info), track.__name__))
    if in_active:
        levels = [level for _, level in active_track.get_aspirations()]
        next_level = first_incomplete(levels, tracker.milestone_completed)
        if next_level is None:
            tracker._active_aspiration = None
            tracker._send_tracker_to_client()
        elif next_level is not tracker._active_aspiration:
            tracker._activate_aspiration(next_level)
        try:
            tracker._write_telemetry_complete_milestone(sim_info.get_sim_instance(), aspiration)
        except Exception:
            pass
        asp_log.log("{}: completed {} (selected aspiration); now on {}".format(
            _name(sim_info), aspiration.__name__, next_level.__name__ if next_level else "nothing - all done"))
    else:
        tracker._send_tracker_to_client()
        asp_log.log("{}: completed {} early (aspiration {})".format(
            _name(sim_info), aspiration.__name__, ", ".join(t.__name__ for t in tracks) or "?"))


def _name(sim_info):
    return "{} {}".format(sim_info.first_name, sim_info.last_name).strip()


AspirationTracker._should_handle_event = _should_handle_event
AspirationTracker.complete_milestone = complete_milestone
asp_log.log("aspiration hooks installed")


# --- Zone load ------------------------------------------------------------------------------
def _catch_up(sim_info):
    """Re-test every level's goals for one sim, so goals already met before the mod (or before
    this level existed for them) are picked up."""
    tracker = sim_info.aspiration_tracker
    if tracker is None:
        return
    _, index = _load_tracks()
    manager = services.get_event_manager()
    for level in index:
        manager.register_single_event(level, TestEvent.UpdateObjectiveData)
    try:
        manager.process_test_events_for_objective_updates(sim_info)
    finally:
        for level in index:
            manager.unregister_single_event(level, TestEvent.UpdateObjectiveData)


def on_zone_loaded():
    if not _enabled():
        return
    _register_all_levels()
    household = services.active_household()
    if household is None:
        return
    for sim_info in household.sim_info_gen():
        try:
            _catch_up(sim_info)
        except Exception:
            asp_log.log_exception("catching up {}".format(_name(sim_info)))


import zone as _zone_module

_original_on_loading_screen_animation_finished = _zone_module.Zone.on_loading_screen_animation_finished


def _patched_on_loading_screen_animation_finished(self, *args, **kwargs):
    result = _original_on_loading_screen_animation_finished(self, *args, **kwargs)
    try:
        on_zone_loaded()
    except Exception:
        asp_log.log_exception("zone load hook")
    return result


_zone_module.Zone.on_loading_screen_animation_finished = _patched_on_loading_screen_animation_finished


# --- Cheats -----------------------------------------------------------------------------------
@sims4.commands.Command("houserules.asp.status", command_type=sims4.commands.CommandType.Live)
def asp_status(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = get_optional_target(opt_sim, _connection, target_type=OptionalSimInfoParam)
    if sim_info is None or sim_info.aspiration_tracker is None:
        output("No sim found (select one or pass a sim id).")
        return
    try:
        tracker = sim_info.aspiration_tracker
        tracks, _ = _load_tracks()
        lines = ["Aspiration Progress is {}. {}: selected aspiration {}, working on {}".format(
            "on" if _enabled() else "off", _name(sim_info),
            tracker.active_track.__name__ if tracker.active_track else "none",
            tracker._active_aspiration.__name__ if tracker._active_aspiration else "nothing")]
        for track, levels in tracks:
            done = [lv for lv in levels if tracker.milestone_completed(lv)]
            if not done:
                continue
            early = ahead_of(levels, tracker.milestone_completed)
            lines.append("{}: {}/{} levels done{}".format(
                track.__name__, len(done), len(levels),
                "; done ahead: " + ", ".join(lv.__name__ for lv in early) if early else ""))
    except Exception:
        asp_log.log_exception("asp.status")
        output("asp.status failed - see the log.")
        return
    for line in lines:
        output(line)
        asp_log.log("asp.status " + line)


@sims4.commands.Command("houserules.asp.on", command_type=sims4.commands.CommandType.Live)
def asp_on(_connection=None):
    _set_enabled(True)
    sims4.commands.CheatOutput(_connection)("Aspiration Progress is on (takes full effect after the next load).")


@sims4.commands.Command("houserules.asp.off", command_type=sims4.commands.CommandType.Live)
def asp_off(_connection=None):
    _set_enabled(False)
    sims4.commands.CheatOutput(_connection)("Aspiration Progress is off (takes full effect after the next load).")
