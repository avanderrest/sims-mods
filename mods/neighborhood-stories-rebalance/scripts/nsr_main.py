"""Neighborhood Stories Rebalance - game layer.

See PLAN.md for how this maps onto EA's code, and what's still unverified for lack of a
running game. Everything here is defensive: a wrong guess should log a line and do
nothing, never break the base game's own on_loading_screen_animation_finished.

Cheats: bluerabbit477.nsr.status - prints what the last zone load found/changed.
        bluerabbit477.nsr.events - counts of story arcs started/ended (kept across sessions).
        bluerabbit477.nsr.events_reset - start the counts again.
"""
import sims4.commands
import services
import zone as zone_module

import nsr_log
from nsr_classify import classify_arc, adjust_weight

_last_summary = []  # filled in by _apply_rebalance(); read by the status cheat
_applied_already = False  # guards against re-multiplying weights on every zone load


def _apply_rebalance():
    global _applied_already, _last_summary
    if _applied_already:
        nsr_log.log("skip: already applied this game session")
        return
    _applied_already = True  # set before doing the work, so a crash still prevents a retry loop

    summary = []
    service_cls = services.get_story_progression_service
    story_service = service_cls() if callable(service_cls) else None
    if story_service is None:
        nsr_log.log("could not get the story progression service; nothing changed")
        _last_summary = summary
        return

    passes = getattr(type(story_service), "STORY_PROGRESSION_PASSES", None)
    if not passes:
        nsr_log.log("STORY_PROGRESSION_PASSES was empty or missing; nothing changed")
        _last_summary = summary
        return

    # Tuned tuples are ImmutableSlots (assigning raises TypeError) and tuned lists are tuples,
    # so build changed copies with clone_with_overrides and swap the whole class attribute.
    # The service reads self.STORY_PROGRESSION_PASSES at the start of every seeding pass.
    new_passes = []
    for pass_data in passes:
        new_entries = []
        for arc_entry in getattr(pass_data, "potential_arcs", ()):
            story_arc = getattr(arc_entry, "story_arc", None)
            original_weight = getattr(arc_entry, "weight", None)
            arc_name = getattr(story_arc, "__name__", str(story_arc))
            if story_arc is None or original_weight is None:
                new_entries.append(arc_entry)
                continue
            # Classified by tuning name. Reading the arc's chapter actions instead failed in
            # the first in-game test: _initial_story_chapter is a class, and calling it builds
            # a chapter (TypeError: missing 'arc').
            category = classify_arc(arc_name)
            new_weight = adjust_weight(original_weight, category)
            new_entries.append(arc_entry.clone_with_overrides(weight=new_weight))
            summary.append({"arc": arc_name, "category": category,
                            "old_weight": original_weight, "new_weight": new_weight})
        new_passes.append(pass_data.clone_with_overrides(potential_arcs=tuple(new_entries)))

    try:
        type(story_service).STORY_PROGRESSION_PASSES = tuple(new_passes)
        applied = True
    except Exception:
        nsr_log.log_exception("replacing STORY_PROGRESSION_PASSES")
        applied = False
    for s in summary:
        s["applied"] = applied
        if not applied:
            s["new_weight"] = s["old_weight"]

    _last_summary = summary
    changed = sum(1 for s in summary if s.get("applied") and s["new_weight"] != s["old_weight"])
    nsr_log.log("checked {} story arcs; changed {} weights".format(len(summary), changed))
    for s in summary:
        nsr_log.log("  {arc}: category={category} old={old_weight} new={new_weight} applied={applied}".format(**s))


_original_on_loading_screen_animation_finished = zone_module.Zone.on_loading_screen_animation_finished


def _patched_on_loading_screen_animation_finished(self, *args, **kwargs):
    result = _original_on_loading_screen_animation_finished(self, *args, **kwargs)
    try:
        _apply_rebalance()
    except Exception:
        nsr_log.log_exception("on_loading_screen_animation_finished hook")
    return result


zone_module.Zone.on_loading_screen_animation_finished = _patched_on_loading_screen_animation_finished


@sims4.commands.Command("bluerabbit477.nsr.status", command_type=sims4.commands.CommandType.Live)
def nsr_status(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    if not _applied_already:
        output("Neighborhood Stories Rebalance: not applied yet - load a save first.")
        return
    if not _last_summary:
        output("Neighborhood Stories Rebalance: ran, but found no story arcs to look at (see the log).")
        return
    output("Neighborhood Stories Rebalance: {} arcs checked".format(len(_last_summary)))
    for s in _last_summary:
        output("  {arc}: {category}  weight {old_weight} -> {new_weight}{note}".format(
            note="" if s.get("applied") else " (unchanged)", **s))
    output("Full detail in Mods/BlueRabbit477/logs/neighborhood-stories-rebalance.log")


# --- Event tally: which story arcs actually start and how they end ---------------------
# Counts are kept in Mods/BlueRabbit477/data/nsr_events.json so they build up across play
# sessions. Both hooks only record; they always call EA's original first and return its result.
import os

import story_progression.story_progression_telemetry as sp_telemetry
import story_progression.story_progression_tracker as sp_tracker
from story_progression.story_progression_result import STORY_PROGRESSION_RESULT_TYPE_STRINGS

from nsr_events import EventTally

_EVENTS_PATH = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts",
                            "The Sims 4", "Mods", "BlueRabbit477", "data", "nsr_events.json")
_tally = None


def _record(kind, arc_name, result=None):
    global _tally
    try:
        if _tally is None:
            _tally = EventTally.load(_EVENTS_PATH)
        try:
            when = str(services.time_service().sim_now)
        except Exception:
            when = None
        _tally.add(kind, arc_name, when=when, result=result)
        _tally.save(_EVENTS_PATH)
        nsr_log.log("event {}: {}{}".format(kind, arc_name, " ({})".format(result) if result else ""))
    except Exception:
        nsr_log.log_exception("recording {} event for {}".format(kind, arc_name))


_original_add_arc = sp_tracker.BaseStoryProgressionTracker.add_arc


def _patched_add_arc(self, new_arc, **kwargs):
    result = _original_add_arc(self, new_arc, **kwargs)
    if result:
        _record("started", getattr(new_arc, "__name__", str(new_arc)))
    return result


sp_tracker.BaseStoryProgressionTracker.add_arc = _patched_add_arc

# The tracker calls this through the module whenever an arc ends, with how it ended.
_original_arc_complete = sp_telemetry.send_arc_complete_telemetry


def _patched_arc_complete(chapter, result_type):
    try:
        _record("ended", type(chapter.arc).__name__,
                result=STORY_PROGRESSION_RESULT_TYPE_STRINGS.get(result_type, str(result_type)))
    except Exception:
        nsr_log.log_exception("arc complete hook")
    return _original_arc_complete(chapter, result_type)


sp_telemetry.send_arc_complete_telemetry = _patched_arc_complete


@sims4.commands.Command("bluerabbit477.nsr.events", command_type=sims4.commands.CommandType.Live)
def nsr_events(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    tally = _tally if _tally is not None else EventTally.load(_EVENTS_PATH)
    if not tally.events:
        output("No Neighborhood Stories events recorded yet. They're picked once per sim day.")
        return
    output("Neighborhood Stories events recorded so far ({} total):".format(len(tally.events)))
    for line in tally.summary_lines():
        output("  " + line)


@sims4.commands.Command("bluerabbit477.nsr.events_reset", command_type=sims4.commands.CommandType.Live)
def nsr_events_reset(_connection=None):
    global _tally
    _tally = EventTally()
    _tally.save(_EVENTS_PATH)
    sims4.commands.CheatOutput(_connection)("Neighborhood Stories event counts reset.")
