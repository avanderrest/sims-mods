# Development notes

How this repo is built, tested and installed. For what the mods do, see [README.md](README.md).

## Mod status

| Mod | Plan | Status |
|---|---|---|
| Neighborhood Stories Rebalance | [PLAN](mods/neighborhood-stories-rebalance/PLAN.md) | weights tested in game; age-up steps, daily romance/move-in/child, relationship gating and horse gate built, to test |
| NPC Routines (+ local LLM) | [PLAN](mods/npc-routines/PLAN.md) | phase 1 works in game; phases 2-4 built, to test |
| Hard Mode | [PLAN](mods/hard-mode/PLAN.md) | career gates work in game; money, firing, skills, life built, to test |
| Flexible University | [PLAN](mods/flexible-university/PLAN.md) | built 2026-10-26, to test |
| Social Standing | [PLAN](mods/social-standing/PLAN.md) | built, to test |
| Ascent to Royalty | [PLAN](mods/ascent-to-royalty/PLAN.md) | built 2026-10-26, needs EP21, to test |
| Aspiration Progress | [PLAN](mods/aspiration-progress/PLAN.md) | built, to test |
| Scenarios | [PLAN](mods/scenarios/PLAN.md) | phases 1-2 (files, goals, rules) built, to test |
| Social Gates | [PLAN](mods/social-gates/PLAN.md) | built, to test |
| Self-test | [PLAN](mods/self-test/PLAN.md) | built 2026-10-26, to run in game |
| hello-world | `mods/hello-world/` | pipeline test, working |

**First time testing any of this?** Go through [TESTING.md](TESTING.md) in order — it has the
exact steps and what each outcome means, including for the parts that were built without a
running game overnight and haven't been checked against the real thing yet.

## Layout

```
mods/<name>/scripts/   Python source  -> compiled into <creator>_<name>.ts4script
mods/<name>/tuning/    tuning XML compiled into <creator>_<name>.package by the build
mods/<name>/package/   .package files made in Sims 4 Studio (tuning, strings)
mods/<name>/tests/     pytest tests for scripts/ that have no game imports (pure logic)
mods/<name>/install/   copied into Mods/<creator>/ as-is (e.g. the example scenario files)
mods/<name>/PLAN.md    design and status
tools/                 decompile and build scripts (config in tools/config.py)
tools/dbpf.py          reads the game's .package files (real tuning names: tags, traits, buffs), writes ours
tools/tuning.py        mods/<name>/tuning/*.xml -> <creator>_<name>.package (pie-menu/phone entries; run by build.py)
tools/scenario_export.py  scenario JSON -> Scenario/phase/goal tuning -> .package (game Scenarios menu)
tools/scenario_builder.py local web builder for scenario JSON (form + JSON, validate/save/export)
tools/llm.py           installs/starts the local LLM for NPC Routines' brain, as declared in llm.json
tools/llm_tail.py      follows the NPC log so the brain's prompts/answers/reasoning show live
start-llm.cmd          double-click before playing: installs Ollama + model the first time, starts it,
                       then follows the log
tools/pyc_outline.py   outlines an EA .pyc the decompilers couldn't recover
tools/templates/       mod_log_template.py - copy into a new mod as scripts/<mod>_log.py
ea_scripts/            EA's decompiled game code, for reading only (git-ignored)
build/                 build output (git-ignored)
```

Each mod that has both game-facing code and testable logic splits them into two files: one
with no game imports (`<mod>_classify.py`, `<mod>_careers.py`, `..._routine.py`, …) that pytest
can cover, and a thin `<mod>_main.py` that's the only place touching `sims4`/`services`/etc. and
can't be unit-tested — see TESTING.md for how to check that part by hand.

At runtime, each mod keeps its own state in `Mods/HouseRules/data/<mod>.json` and its own log
at `Mods/HouseRules/logs/<mod>.log` (not committed here - they only exist in the installed
Mods folder).

## Setup

- **Python 3.7** (the game's version) is installed for this user. Run all tools with `py -3.7`.
  A virtual environment doesn't work here because of the spaces in the user folder path, so the tools are installed directly into that Python.
- Decompilers: `decompyle3`, `uncompyle6`. Also installed: `pytest` (run by `tools/build.py`).
- **Sims 4 Studio** 3.2.6.5 (Star) in `C:\Program Files (x86)\Sims 4 Studio` (for editing tuning and making `.package` files).
- In the game: **Game Options → Other → Enable Custom Content and Mods + Script Mods Allowed**.

## Commands

```sh
py -3.7 tools/decompile.py           # after each game patch: refreshes ea_scripts/
py -3.7 tools/build.py               # runs pytest on every mod's tests/, then builds+installs all mods
py -3.7 tools/build.py hard-mode     # only one mod
py -3.7 tools/build.py --no-install  # build (and test) only, skip copying to Mods/
```

A failing test stops the build — nothing gets installed until it's fixed.

### In-game self-test

After loading a save with a sim selected, run the checks from the cheat console (Ctrl+Shift+C):

```
houserules.test              every suite (env, hello, actions, hardmode, aspiration, social, royalty, gates, scenarios, nsr, npc)
houserules.test hardmode     one suite, or several comma-separated
houserules.test.list         the suites and how many checks each has
```

Each check prints `[PASS]`, `[FAIL]` or `[SKIP]` with a reason. Results also go to
`Mods/HouseRules/logs/self-test.log` and `Mods/HouseRules/data/self_test_last.json`.
The checks that act on the save (a market sale, a §137 debt, a routine entry, a royal flag,
a temporary job join) undo themselves; see [mods/self-test/PLAN.md](mods/self-test/PLAN.md).

Restart the game after installing; script mods only load at startup.
Check that the pipeline works: build, start the game, press Ctrl+Shift+C, type `houserules.hello`.

## Useful references

- [Getting Started with Python Scripting](https://sims4studio.com/thread/15145) (Andrew, Sims 4 Studio forums): the standard script-mod tutorial
- [Studio's Tuning Editor: mini-tutorial & documentation](https://sims4studio.com/thread/29778/studios-tuning-editor-tutorial-documentation): editing tuning in Sims 4 Studio
- [Lot 51 TDESC browser](https://tdesc.lot51.cc): documents every tuning field
- [Lot 51 – Learn to Mod The Sims 4](https://lot51.cc/resources): collection of modding guides and tools
- [XML Injector](https://scumbumbomods.com/xml-injector) (Scumbumbo / Triplis): add to EA tuning without overwriting it
- [Sims 4 Community Library](https://github.com/ColonolNutty/Sims4CommunityLibrary) (ColonolNutty): helper library for script mods
- [Better Exceptions](https://www.curseforge.com/sims4/mods/better-exceptions) (TwistedMexi): readable error reports while testing
