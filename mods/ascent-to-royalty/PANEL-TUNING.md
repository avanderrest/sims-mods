# Career-panel tuning

The career panel's promotion list is EA client tuning, so a script cannot fill it. Instead
this mod overrides the requirement aspirations EA attaches to the Noble career levels, so
each level's panel shows the same requirements the script gate enforces.

None of this needs Sims 4 Studio. `tools/build.py` compiles `tuning/` into the package.

## Shipping both forms

The build writes each tuning twice, and that is what works in game (checked 2026-10-30):
the binary **SimData** resource (`0x545AC67A`, group `0x00B6465D` for aspirations and
`0x0069453E` for objectives) and the per-type **XML** beside it (`0x28B64675` / `0x69453E`,
group 0). Sims 4 Studio and the working tuning mods ship both; EA's own packages carry only
the SimData.

Two earlier attempts failed, both of which shipped only one of the two: an XML-only build
whose files began with a `<!-- comment -->` (the loader expects the instance element first,
so it drops the resource), and a SimData-only build. Which of the two the panel actually
reads is not settled — don't remove either half without testing in game.

`tools/simdata.py` writes that binary form. It is a port of the writer in Sims 4 Toolkit
(`@s4tk/models`, MIT), and its output is byte-identical to EA's own resources: the tests pin
two of EA's files, and during development it reproduced all 1,078 aspiration/objective
resources in the installed game byte for byte.

## What the build produces

| Tuning | Instance id | Resource |
|---|---:|---|
| `aspiration_nobleCareer_Level1` … `Level9` | 466307–466313, 466329, 466306 | SimData, group `0x00B6465D` + XML, group 0 |
| `HouseRules_NobleSavings_Level1` … `Level8` | `0x7F000001` … `0x7F000008` | SimData, group `0x0069453E` + XML, group 0 |
| `HouseRules_NobleFriend_Level1` … `Level7` | `0x7F000011` … `0x7F000017` | SimData, group `0x0069453E` + XML, group 0 |
| `HouseRules_NobleMonarch` | `0x7F000021` | SimData, group `0x0069453E` + XML, group 0 |

`tuning/NobleAspiration_Level*.xml` names the objectives each level's panel lists;
`tuning/NobleSavings_Level*.xml`, `NobleFriend_Level*.xml` and `NobleMonarch_Level9.xml` are
the rows themselves (text and tooltip).

Adding a tuning class to this path means adding it to `SIMDATA_GROUPS` in `tools/tuning.py`
together with the schema the game has registered for it.

## The rows carry no test; the script completes them

The game stores an objective's presentation in the per-tuning SimData and its test
(`objective_test`, `objective_completion_type`, `completion_loot`) in the pack's *combined*
tuning resource (`0x62E94D38`). No package in the game — EA's or any mod's — carries an
objective test in a per-tuning SimData, and a hand-made one is not something to guess at.

So the rows cannot complete on their own: net worth, the dynastic friendships and the vacant
throne are all shown, but no objective test ever fires. `houserules.royalty.requirements` is
the authority on what is actually met.

Two things make the panel behave anyway. The script pushes the current values (money rows
print `§current / §goal`, friendship rows `current / required`, the throne row shows no
count), and `_sync_promotion_milestone` completes the current level's aspiration milestone
exactly when the gate reports ready, clearing it again if a requirement stops being met. The
milestone completion matters beyond the panel: `Career.evaluate_career_performance` only
auto-promotes when the promotion aspiration is complete, so without it a Sim whose gate is
ready would never be promoted. `houserules.royalty.panel` re-pushes on demand.

The rows are looked up **by instance id** (`_panel_objectives` in `atr_main.py`), not read
from `career.current_level_tuning.aspiration`: in game the server can resolve that reference
to EA's copy even while the client shows our override, and then a push driven by that list
finds nothing. Ids per promotion rank N: savings `0x7F000000 + N` (up to Level8), friend
`0x7F000010 + N` (up to Level7), crown `0x7F000021`.

EA's throne has two options here. **Claim Lost Career Rank** (`sI_NobleCareer_ClaimCareerRank`)
is the inheritance path: it needs one of EA's "no promise" buffs, so it stays grey unless a
title was lost. The normal one, **Claim Noble Promotion** (`sI_NobleCareer_EarlyPromotion`),
runs `testSet_NobleCareer_CompletedPromotionalRequirements`, which checks that the
**original EA objectives** for the level (Charisma, Swordsmanship, …) are completed — even
though our aspiration override hides them from the panel. `_sync_promotion_milestone`
therefore completes both our rows and the objectives of the server's aspiration when the
gate passes, and clears both again when it stops passing. Without that the throne option
stays grey however ticked the panel looks. EA also requires career performance ≥ 85.

EA re-sends the rows itself on load and when a Sim is selected, so pushing once is not
enough: `CareerTracker.activate_career_aspirations` and `AspirationTracker.update_objective`
are wrapped. The latter is the single funnel for every goal value the client receives, so
any refresh gets our values instead of `objective.goal_value()`'s default of 1.

The push goes through `AspirationTracker.update_objective` with `from_init=True` — EA's own
`force_send_objective_update` does the same. Without that flag the tracker drops the dirty
rows and the panel keeps the default `0/1`.

`aspiration_nobleCareer_Level1` keeps EA's Charisma objective alongside ours; if the panel
shows only Charisma, the aspiration override did not load.

## Checking it in game

1. `py -3.7 tools/build.py ascent-to-royalty` (installs to `Mods\HouseRules\`).
2. Restart the game, open the Noble career panel on a Sim in that career, and look at the
   promotion requirements.

If EA patches EP21 and changes the career/aspiration instance ids, the first table's ids need
updating.
