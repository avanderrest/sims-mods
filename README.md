# Sims 4 mods

Functional (gameplay) mods for The Sims 4.

| Mod | Plan | Type |
|---|---|---|
| Neighborhood Stories Rebalance | [PLAN](mods/neighborhood-stories-rebalance/PLAN.md) | tuning |
| NPC Routines (+ local LLM) | [PLAN](mods/npc-routines/PLAN.md) | script |
| Hard Mode | [PLAN](mods/hard-mode/PLAN.md) | tuning + script |
| hello-world | `mods/hello-world/` | pipeline test |

## Layout

```
mods/<name>/scripts/   Python source  -> compiled into <creator>_<name>.ts4script
mods/<name>/package/   .package files made in Sims 4 Studio (tuning, strings)
mods/<name>/PLAN.md    design and status
tools/                 decompile and build scripts (config in tools/config.py)
ea_scripts/            EA's decompiled game code, for reading only (git-ignored)
build/                 build output (git-ignored)
```

## Setup 

- **Python 3.7** (the game's version) is installed for this user. Run all tools with `py -3.7`.
  A virtual environment doesn't work here because of the spaces in the user folder path, so the tools are installed directly into that Python.
- Decompilers: `decompyle3`, `uncompyle6`.
- **Sims 4 Studio** 3.2.6.5 (Star) in `C:\Program Files (x86)\Sims 4 Studio` (for editing tuning and making `.package` files).
- In the game: **Game Options → Other → Enable Custom Content and Mods + Script Mods Allowed**.

## Commands

```sh
py -3.7 tools/decompile.py           # after each game patch: refreshes ea_scripts/
py -3.7 tools/build.py               # build all mods and copy them to Mods/BlueRabbit477/
py -3.7 tools/build.py hard-mode     # only one mod
py -3.7 tools/build.py --no-install  # build only
```

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
