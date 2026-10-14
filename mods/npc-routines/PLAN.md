# NPC Routines (with optional local-LLM brain)

**Status:** phase 1 works in game; phase 2 (editor via `routine.edit` dialogs - a pie-menu entry still needs a .package), phase 3 (off-lot skill gain) and phase 4 (local LLM, `npc_llm.py`) built 2026-10-09, to test. 13 Oct test: `routine.edit` crashed in the picker (`_MaxSelectableStatic` built without `exclude_previously_selected`; fixed 2026-10-14); the LLM was never reached because no server was running, so `start-llm.cmd` / `tools/llm.py` + `llm.json` now install and start one. A pie-menu entry can now be made without Sims 4 Studio (`tools/tuning.py`, first used for Hard Mode's phone entry) · **Type:** script mod (`.ts4script`) plus a little tuning · **Size:** large; build in phases

## Goal

Hand a sim over to the game, while defining *what kind of life* they lead and not just "keep your needs up". Examples:

- "Gym Mon/Wed/Fri evenings, paints after work, sees friends at the bar on Saturday, family dinner on Sunday."
- Later: "She's ambitious and a bit of a loner; wants to become a famous painter" as free text, with a local LLM picking her activities.

## Key constraint to design around

The Sims 4 only fully simulates sims who are **on the loaded lot**. Sims in other households, or away from the lot, are simulated loosely: some jobs, Neighborhood Stories, and that's it. So "NPC mode" means two different things:

1. **On-lot autopilot:** the sim is in your active household or on the current lot, but you don't control them. We can push real interactions (paint, work out, travel along with the group). **This is the MVP.**
2. **Off-lot life:** the household isn't the one being played. Nothing is actually running, so we'd *simulate the results*: each sim-day, give the sim the skill gain, relationship changes and money their routine would have produced. **This is phase 3.**

## What we reuse

- **Clubs:** they already have "activities" (the club rules), and you have several club-activity mods installed (Rex, icemunmun, ClaudiaSharon). One option is "a routine = a club with a schedule", reusing EA's club gathering code.
- **Autonomy:** we don't replace it. We push the scheduled interaction at the right time, and let normal autonomy handle needs in between. An urgent need (hunger, bladder, exhaustion) beats the routine.

## Phases

### Phase 1: Routine engine (MVP, on-lot) — built 2026-10-09 overnight, untested in-game
- `scripts/npc_routine.py`: the routine data model (`RoutineEntry`, `Routine`, `RoutineStore`)
  and the "what should be happening right now" lookup. Pure Python, no game imports, 21 pytest
  tests (entry validation, same-day and past-midnight coverage, overlap rules, JSON round-trips,
  missing/empty-file loading).
- `scripts/npc_main.py`: the game layer. Hooks `zone.Zone.on_loading_screen_animation_finished`
  to load the routines file and (re-)start an hourly alarm; each tick, for every NPC-mode sim
  that's actually on the loaded lot (`sim_info.get_sim_instance()`), looks up the due activity and
  pushes its interaction at `Priority.Low`. Routines persist to
  `Mods/BlueRabbit477/data/npc_routines.json`.
- Commands, all working on the selected sim by default (`OptionalTargetParam`/`get_optional_target`,
  same pattern as EA's own `clubs.add_sim_to_club`): `bluerabbit477.npc.on` / `.npc.off`,
  `bluerabbit477.routine.add <days> <start_hour> <length_hours> <activity>` (days: `mon,wed,fri`
  or `1,3,5`), `bluerabbit477.routine.show`, `bluerabbit477.routine.clear`.
- Five starter activities: workout, paint, read, chess, jog. The affordance tuning name for each
  is an unverified guess — see "what's confirmed vs. still a guess" above.
- **Not yet checked against a real game** — see TESTING.md section 3 for exactly what to try and
  what each outcome would mean.

### Phase 2: In-game UI
- An "NPC Routine…" option when you click a sim, with a picker of activity types and a days/time grid (using EA's picker dialogs).

### Phase 3: Off-lot results
- When the sim isn't loaded, apply their routine's results once per sim-day, scaled down (e.g. half the skill gain they'd get when on the lot).

### Phase 4: Local LLM brain (optional, idea 1.2)
- The player writes free-text instructions per sim. Every few sim-hours, or when the sim is idle, the mod builds a prompt containing: the sim's traits, mood, needs, skills, job, relationships, the time and day, the instructions, and a **numbered list of allowed actions**. The local LLM (Ollama / LM Studio on `localhost`) answers with one action number and a short reason.
- The HTTP call runs in a background thread so the game never freezes. The answer is put in a queue, and the next in-game alarm applies it on the game's main thread, since the game's state may only be touched from there.
- Safety: the model can only choose from the list we give it. Anything else is ignored, and we fall back to the routine or normal autonomy. If the LLM server isn't running, the mod just uses routines.
- Optional: show the reason in a notification ("Mira is going to the gym because she wants to feel confident before her date").

## Discovery tasks (after decompiling)
- ~~`ea_scripts/simulation/clubs/`: how gatherings and club activities get pushed.~~ Didn't end
  up needing clubs for phase 1 — pushing the interaction directly turned out simpler; clubs are
  still worth a look for phase 2 (grouping several sims onto one scheduled activity together).
- ~~How to push an interaction from script~~ **Confirmed, 2026-10-09 overnight**, from real code
  (not guessed): `sim.push_super_affordance(affordance, target, context)`
  (`sims/sim.py`), where `affordance` can be a string tuning name (resolved via
  `services.get_instance_manager(Types.INTERACTION).get(name)`) and
  `context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.Low)`
  (`interactions/context.py`, `interactions/priority.py`). Pattern copied from
  `pregnancy_interactions.py:354`, a real EA call site doing the same thing.
  **Deliberately pushed at `Priority.Low`** — confirmed from `interactions/priority.py` that
  `Low < High < Critical` — so the engine's own priority system lets a real need or the player
  pre-empt our routine, instead of us hand-rolling a needs-urgency check.
- ~~Alarms~~ **Confirmed:** `alarms.add_alarm(owner, time_span, callback, repeating=True)`
  (`simulation/alarms.py`). Two things that weren't obvious and would have been bugs if we
  hadn't checked: (1) `owner` is held by **weakref** — it can't be created before some object is
  guaranteed alive, and anything we pick can go away later; (2) calling `add_alarm` at
  **module-import time doesn't work** — that happens at game startup, before `time_service()`
  has a `sim_timeline`, so it would silently return `None`. Fixed by starting (and, every time,
  first cancelling and re-creating) the alarm from the same `on_loading_screen_animation_finished`
  zone-load hook `neighborhood-stories-rebalance` uses, owned by the `Zone` instance itself.
- How `situations` keep NPCs doing things: not needed for phase 1 (direct interaction push was
  enough); worth a look for phase 2/3.
- Look at how SimsAIChat / Sims AI Chat do their HTTP calls inside the game: still open, for phase 4.

**A real bug caught on re-reading (fixed, not just noted):** every cheat's "default to the
selected sim" relies on `server_commands.argument_helpers`. There are actually **two** similar
classes there - `OptionalTargetParam` (generic; resolves "no id given" to `client.active_sim`,
which is a **`Sim` game object**, and resolves a given id via the **object manager**, which only
has currently-instanced objects) and `OptionalSimInfoParam` (built specifically for sims;
resolves "no id given" to `client.active_sim_info`, and a given id via `sim_info_manager()`).
All of this code calls `.sim_id`, `.degree_tracker`, `.career_tracker` — `SimInfo` members, not
`Sim` members — so it needed `OptionalSimInfoParam`, and originally used the wrong one. **Also
not obvious:** `get_optional_target()`'s fallback-when-no-id-given construction is controlled by
its own separate `target_type=` argument, which defaults to plain `OptionalTargetParam`
regardless of what the caller's cheat parameter was annotated with — so fixing the annotation
alone would not have fixed the "no id given" case; `target_type=OptionalSimInfoParam` has to be
passed explicitly at the `get_optional_target(...)` call site too. Both are fixed now in
`npc_main.py`.

## What's confirmed vs. still a guess (2026-10-09 overnight, no running game to check against)

**Confirmed from reading the decompiled source** (see above), plus one more found while
double-checking everything: `sims4/commands.py`'s own `_parse_arg` explicitly special-cases
`arg_type is int` (`int(arg_value, base=0)`) and falls through to `arg_type(arg_value)` for
anything else (covers plain `str`) — so the bare `int`/`str` type annotations on every cheat
parameter in `npc_main.py` (`start_hour: int`, `length_hours: int`, `activity: str`, `days: str`)
really are supported, not a guess. `push_super_affordance`,
`InteractionContext`, `Priority`, `alarms.add_alarm` and its weakref/timing gotchas,
`services.get_active_sim()` / `get_optional_target` for cheat sim-targeting,
`DateAndTime.day()`/`.hour()` — **`day()` is 0=Sunday..6=Saturday**, confirmed from the
`__format__` method's day-name table; this does *not* match Python's own `weekday()`, and
getting it wrong would have made routines silently run on the wrong day. `npc_routine.py`
uses this same convention throughout and says so.

**Still a guess, isolated into one small table (`ACTIVITY_AFFORDANCES` in `npc_main.py`):**
the actual tuning instance *names* for the five starter activities (workout, paint, read,
chess, jog). These are tuning data, not Python, so there's no way to read the real names out of
the decompiled scripts — same blocker as Neighborhood Stories Rebalance's weights. If a name is
wrong, `_push_activity()` logs it and does nothing else; it can never push something broken.

**A second guess stacked on the first, caught on a later re-read and not just assumed away:**
`_push_activity` pushes every activity with `target=None`. `push_super_affordance`'s real
signature (confirmed: `sim.py`) takes `(super_affordance, target, context, **kwargs)`, and most
of these five activities almost certainly need the actual nearby object as target (the
treadmill, the easel, the chessboard) rather than a self-targeted push — `target=None` is likely
wrong for at least workout/paint/chess, maybe right for jog. There's a confirmed real way to find
a nearby object by tag (`services.object_manager().get_objects_with_tags_gen(...)`, seen used
for exactly this purpose in `university_career_tuning.py`), but using it needs real tag names we
don't have either, for the same reason as the affordance names — adding that search blind would
just be a third guess on top, not a fix. Left as `target=None` with a loud comment, on purpose.
**So fixing this mod for real needs two things checked against a running game, not one:** the
affordance name *and* what (if anything) it needs as a target — see TESTING.md section 3.

## Open questions
- Is a routine per sim, or per household with exceptions? **Decided for phase 1: per sim** —
  `RoutineStore` is keyed by sim id. Simpler, and a household view can be built on top later.
- What happens when a routine conflicts with a job or school? **Not handled yet** — phase 1 pushes
  the activity regardless. The job/school interaction itself should normally win on priority
  since autonomy/rabbit-holes run above `Priority.Low`, but this is unverified; worth an explicit
  check once the game can run, not just an assumption.
- Should NPC mode be allowed on the sim you're actively controlling, or only on other household
  members? **Not restricted in phase 1** — `npc.on` works on whatever `get_optional_target`
  resolves to, including the selected sim. Worth deciding once we can see what that feels like
  in practice; easy to add a check later if it turns out to fight the player.
