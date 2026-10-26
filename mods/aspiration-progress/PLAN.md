# Aspiration Progress

**Status:** built 2026-10-09 (`scripts/asp_main.py`), to test in game - TESTING.md section 4 · **Type:** script · **Size:** small to medium

## Goal

**Why:** aspirations are tedious as they are. A sim often already did a goal before reaching
its level, and has to do it all over again (Amber, 2026-10-09). This mod is about less
pointless repetition, not about difficulty, so it doesn't conflict with Hard Mode.

Goals (aspiration objectives) count **whenever you achieve them**, not only when they belong to
the aspiration and level you currently have selected (Amber, 2026-10-09). Examples:

- A sim on level 1 of *Bestselling Author* writes a bestseller (a level 3 goal). It's ticked off
  already when they reach level 3.
- A sim on *Renaissance Sim* masters cooking, a goal of *Master Chef*. If they switch to *Master
  Chef* later, that goal is already done.

## How the game does it now (EA's code, `aspirations/aspirations.py`)

- The aspiration tracker only listens for the **active** milestone's goals:
  `_activate_aspiration` calls `aspiration.register_callbacks(...)` for that one milestone, and
  `process_test_events_for_aspiration` re-checks it when it becomes active.
- `_should_handle_event` filters events for full aspirations (`aspiration_in_sequence`), so
  events for other milestones are dropped even if something were listening.
- Completed goals are stored per goal in the tracker (`reset_milestone` clears them again), and
  `complete_milestone` gives the milestone's reward and moves to the next one.

## Plan

1. **Listen to every goal:** when a sim's tracker starts, also register callbacks for the
   milestones of every aspiration track the sim could have (sim's age; packs installed).
2. **Record goals of non-active milestones** as done (relax `_should_handle_event` for them).
3. **Pay out straight away** (Amber, 2026-10-09: "you get them as soon as you do the goal").
   In the game, satisfaction points and rewards belong to a **level** (milestone), not to single
   goals. So as soon as every goal of any level is done, even a future level or another
   aspiration's level, that level pays out at once: its satisfaction points and reward, plus
   the usual notification. Carefully: EA's `complete_milestone` also moves the sim's current
   aspiration forward, so for a non-active level we give the reward and points and mark it
   complete **without** moving the sim's current position.
4. **Skip on arrival:** when the sim reaches a level that's already complete (next level, or
   switching aspiration), it's skipped and never paid twice. If only some of its goals were
   done early, those show as ticked (the game re-checks goals on activation:
   `process_test_events_for_aspiration`).
5. **Don't wipe recorded goals** when switching aspirations (check what `reset_milestone` /
   switching does to stored goals).
6. **The aspiration's trait comes only when the whole aspiration is complete** (Amber,
   2026-10-09). Finishing the last level early pays that level's satisfaction points, but the
   aspiration's reward trait is held back until **every** level of that aspiration is done,
   in whatever order. Check how EA gives the trait (track completion vs. the final milestone's
   reward) so it can't slip through when the final level is completed out of order.
7. **All ages:** child and teen aspirations too (Amber, 2026-10-09), not only adult ones. Each
   sim tracks the aspirations available to their own age.
8. Cheat `houserules.asp.status`: lists goals already done for milestones you haven't reached.

## Open questions

- Some goals are "do X *while* on this aspiration" or count things over time (e.g. "earn §10,000").
  Count only from when the mod is installed, or from the save's history? (The game may already
  track some of these as totals.)
- Anything else a level unlocks that's only meant after earlier levels: check for anything that
  breaks when it's given early.
