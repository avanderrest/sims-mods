# NPC Routines (with optional local-LLM brain)

**Status:** planning · **Type:** script mod (`.ts4script`) plus a little tuning · **Size:** large; build in phases

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

### Phase 1: Routine engine (MVP, on-lot)
- A routine is a list of entries: `days, start time, length, activity`. An activity is either an interaction to push on an object type ("use treadmill", "paint at easel"), a skill to train, or a venue to travel to.
- Stored as a JSON file next to the mod in the Mods folder, keyed by sim ID. Edited via cheat commands at first (`bluerabbit477.routine.add <day> <hour> <activity>`), with a picker UI later.
- An in-game alarm every sim-hour looks at each NPC-mode sim on the lot. If a routine entry is due and they aren't busy with something urgent, the mod pushes the interaction.
- Commands: `bluerabbit477.npc.on` / `bluerabbit477.npc.off` for the selected sim, and `bluerabbit477.routine.show`.

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
- `ea_scripts/simulation/clubs/`: how gatherings and club activities get pushed.
- How to push an interaction from script (`sim.push_super_affordance`, `InteractionContext`, priorities).
- Alarms (`alarms.add_alarm`) and zone load/unload hooks, to start and stop the engine.
- How `situations` keep NPCs doing things (a possible alternative to pushing interactions directly).
- Look at how SimsAIChat / Sims AI Chat do their HTTP calls inside the game. Same idea, different purpose.

## Open questions
- Is a routine per sim, or per household with exceptions?
- What happens when a routine conflicts with a job or school? Jobs win, probably.
- Should NPC mode be allowed on the sim you're actively controlling, or only on other household members?
