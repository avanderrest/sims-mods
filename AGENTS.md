# Working in this repo

Sims 4 gameplay mods. Everything is built from source here; nothing is hand-edited in game.

## Commands

```
py -3.7 tools/build.py [mod …] [--no-install]   # tests, compiles, installs to Mods\HouseRules
py -m pytest tools/tests mods/*/tests -q        # the whole suite (any Python 3.8+)
```

`build.py` refuses to run outside Python 3.7 (the game loads 3.7 bytecode). Installing needs
the game closed: a running game locks `Mods\HouseRules\*` and the copy fails with
`PermissionError`.

## Tuning traps

These cost real debugging time. Each is enforced somewhere in the code — read that before
changing behaviour.

1. **A package is the source of truth, not the XML.** Every mod's `tuning/*.xml` is compiled
   into `build/<creator>_<mod>.package`. Inspect the built package with `tools/dbpf.py`
   (resource types, ids, references) rather than trusting the sources.

2. **Career/aspiration/objective tuning must be SimData** (`0x545AC67A`), not the per-type
   XML. `tools/tuning.py` compiles it with `tools/simdata.py` and ships the XML beside it,
   because a package with only one of the two did not load. EA ships these as SimData only.

3. **Tuning ids are not one convention.** Career-panel tunings use 64-bit FNV with the high
   bit set; anything the client lists (scenarios) must fit in **32 bits**, or it loads on the
   server and never appears in the UI. See `tuning_id()` in `tools/scenario_export.py` and
   `SIMDATA_GROUPS` in `tools/tuning.py`.

4. **References to other tunings are numeric instance ids, never names.** The game resolves a
   name with `Key.hash64`, which does not match the ids we put on our instances; a name is an
   `UnavailablePackSafeResourceError` at load. `scenario_export.ref()` exists for this.

5. **`TunableEnumFlags` is a list**, not a scalar: `<L n="field"><E>VALUE</E></L>`. Writing
   `<E n="field">VALUE</E>` makes the loader drop the whole tuning.

6. **No comment before the `<I>` element.** The loader expects the instance first and drops
   the resource otherwise. `tools/tuning.py` strips comments when it builds.

7. **Objective tests live in the pack's combined tuning** (`0x62E94D38`), not in per-tuning
   SimData — EA ships none with a test, and neither does any mod. So custom panel rows cannot
   tick or show `§x / §y`, and `show_progress` must stay off or the panel shows a fake `0/1`.
   See `mods/ascent-to-royalty/PANEL-TUNING.md`.

8. **EA ships no per-type XML at all** for prototypes and snippets — only SimData and combined
   tuning. To learn a class's schema, decompile an EA resource with `@s4tk/models`; that is
   how `tools/simdata.py` was written and validated (byte-identical on 1,078 EA files).

9. **Read `lastException*.txt`** in `Documents\Electronic Arts\The Sims 4\`. Tuning failures
   name the generated class and the tag that failed — that is how the numeric-reference bug
   and the flags-shape bug were found. `Mods\HouseRules\logs\` has one log per mod.

## Scenario menu

`tools/scenario_export.py` builds scenario tuning that the **server** loads correctly, and
the card now appears on the Scenarios screen. What made the difference, compared against the
working third-party packages in `Mods\HouseRules\downloaded-scenarios\` (DaleRune's):

- **A Scenario must also ship as SimData** (`0x545AC67A`, group `0x00F216E1`, same instance
  id as the snippet). The Scenarios screen is client-side and builds its cards only from
  that binary; a snippet-only Scenario loads on the server and never lists. `tools/tuning.py`
  now compiles `<I c="Scenario">` to both forms, like it already did for aspirations and
  objectives.
- The SimData schema is EA's `Scenario` (`0x6CD604F2`, 17 columns) with nested
  `TunableScenarioGoalData` / `TunableRelationshipRequirement` / `TunableScenarioRoleData` /
  `ScenarioRoleTunableInterval`. Fields only the snippet knows (screen slam, loot lists,
  start notification) are not in that schema and must not be written there.
- Enum columns are **small ints**, not names: `Challenge=3`, `EASY=3`, `INTERMEDIATE=4`,
  `HARD=5`, `NONE=6`, `NEW_HOUSEHOLD=1`, `EXISTING_HOUSEHOLD=2`. Unknown names are written as
  0 and the exporter warns, because INVALID does not list.
- A custom `ScenarioRole` is optional: DaleRune's Rivalry package ships none and uses EA's
  `273416`; we do the same.
- The card icon is an EA `ResourceKey`. `tools/scenario_icons.py` lists the game's scenario
  icons by name (path + key, no images) for the builder's picker; `menu.icon` takes one of
  those names or a raw `type:group:instance` key.
- Scenario ids must fit in **32 bits**. The high bit is *not* required: working packages have
  ids on both sides of `0x80000000` (`0x675E570C`, `0xBFDB7C9F`, `0xD77DED65`).

Other things verified in game, so don't re-derive them:

- References are numeric instance ids, never names (`Key.hash64` does not match our ids).
- `compatibility_with_scenario_entry_method` is a `TunableEnumFlags` list, not a scalar; in
  the binary it is a `Vector<Int64>` of flag values, and a trailing empty `<E/>` is the
  enum's default member (`NEW_HOUSEHOLD`).
- Goals belong **inline on the Scenario**; `_scenario_roles` (273416) must be on every goal;
  `scenario_role_data` must declare the role. Working mods ship no `ScenarioPhase` or
  `ScenarioOutcome` at all - ours were removed for the same reason (their references did not
  resolve).
- `tools/simdata.py` writes all schema headers before any column block; more than one schema
  per SimData regressed on that (covered by a test).

## Layout notes

- `ea_scripts/` — decompiled EA source, regenerated by `tools/decompile.py`, gitignored.
- `reference-mods/` — other creators' mods for comparison, gitignored.
- `references/` — format references (EA's binary template, S4TK sources), gitignored and not
  needed to build; see its README for provenance.
- `build/` — output, gitignored.
