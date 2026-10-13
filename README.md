# Sims 4 mods

Functional (gameplay) mods for The Sims 4.

| Mod | Plan | Status |
|---|---|---|
| Neighborhood Stories Rebalance | [PLAN](mods/neighborhood-stories-rebalance/PLAN.md) | weights confirmed in game; event counting to test |
| NPC Routines (+ local LLM) | [PLAN](mods/npc-routines/PLAN.md) | phase 1 works in game; phases 2-4 built, to test |
| Hard Mode | [PLAN](mods/hard-mode/PLAN.md) | career gates work in game; money, firing, skills, life built, to test |
| Social Standing | [PLAN](mods/social-standing/PLAN.md) | built, to test |
| Aspiration Progress | [PLAN](mods/aspiration-progress/PLAN.md) | built, to test |
| Scenarios | [PLAN](mods/scenarios/PLAN.md) | planning |
| hello-world | `mods/hello-world/` | pipeline test, working |

**First time testing any of this?** Go through [TESTING.md](TESTING.md) in order — it has the
exact steps and what each outcome means, including for the parts that were built without a
running game overnight and haven't been checked against the real thing yet.

## Layout

```
mods/<name>/scripts/   Python source  -> compiled into <creator>_<name>.ts4script
mods/<name>/package/   .package files made in Sims 4 Studio (tuning, strings)
mods/<name>/tests/     pytest tests for scripts/ that have no game imports (pure logic)
mods/<name>/PLAN.md    design and status
tools/                 decompile and build scripts (config in tools/config.py)
tools/dbpf.py          reads the game's .package files (real tuning names: tags, traits, buffs)
tools/pyc_outline.py   outlines an EA .pyc the decompilers couldn't recover
tools/templates/       mod_log_template.py - copy into a new mod as scripts/<mod>_log.py
ea_scripts/            EA's decompiled game code, for reading only (git-ignored)
build/                 build output (git-ignored)
```

Each mod that has both game-facing code and testable logic splits them into two files: one
with no game imports (`<mod>_classify.py`, `<mod>_careers.py`, `..._routine.py`, …) that pytest
can cover, and a thin `<mod>_main.py` that's the only place touching `sims4`/`services`/etc. and
can't be unit-tested — see TESTING.md for how to check that part by hand.

At runtime, each mod keeps its own state in `Mods/BlueRabbit477/data/<mod>.json` and its own log
at `Mods/BlueRabbit477/logs/<mod>.log` (not committed here - they only exist in the installed
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

Restart the game after installing; script mods only load at startup.
Check that the pipeline works: build, start the game, press Ctrl+Shift+C, type `bluerabbit477.hello`.

## Useful references

- [Getting Started with Python Scripting](https://sims4studio.com/thread/15145) (Andrew, Sims 4 Studio forums): the standard script-mod tutorial
- [Studio's Tuning Editor: mini-tutorial & documentation](https://sims4studio.com/thread/29778/studios-tuning-editor-tutorial-documentation): editing tuning in Sims 4 Studio
- [Lot 51 TDESC browser](https://tdesc.lot51.cc): documents every tuning field
- [Lot 51 – Learn to Mod The Sims 4](https://lot51.cc/resources): collection of modding guides and tools
- [XML Injector](https://scumbumbomods.com/xml-injector) (Scumbumbo / Triplis): add to EA tuning without overwriting it
- [Sims 4 Community Library](https://github.com/ColonolNutty/Sims4CommunityLibrary) (ColonolNutty): helper library for script mods
- [Better Exceptions](https://www.curseforge.com/sims4/mods/better-exceptions) (TwistedMexi): readable error reports while testing
