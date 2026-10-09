"""Neighborhood Stories Rebalance - game layer.

See PLAN.md for how this maps onto EA's code, and what's still unverified for lack of a
running game. Everything here is defensive: a wrong guess should log a line and do
nothing, never break the base game's own on_loading_screen_animation_finished.

Cheat: bluerabbit477.nsr.status - prints what the last zone load found/changed.
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
