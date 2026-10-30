# Career-panel tuning

The career panel's promotion list is EA client tuning, so a script cannot fill it. Instead
this mod overrides the requirement aspirations EA attaches to the Noble career levels, so
each level's panel shows the same two requirements the script gate enforces.

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
| `HouseRules_NobleFriend_Level1` … `Level8` | `0x7F000011` … `0x7F000018` | SimData, group `0x0069453E` + XML, group 0 |
| `HouseRules_NobleMonarch` | `0x7F000021` | SimData, group `0x0069453E` + XML, group 0 |

`tuning/NobleAspiration_Level*.xml` names the objectives each level's panel lists;
`tuning/NobleSavings_Level*.xml`, `NobleFriend_Level*.xml` and `NobleMonarch_Level9.xml` are
the rows themselves (text and tooltip).

Adding a tuning class to this path means adding it to `SIMDATA_GROUPS` in `tools/tuning.py`
together with the schema the game has registered for it.

## The rows do not tick

The game stores an objective's presentation in the per-tuning SimData and its test
(`objective_test`, `objective_completion_type`, `completion_loot`) in the pack's *combined*
tuning resource (`0x62E94D38`). No package in the game — EA's or any mod's — carries an
objective test in a per-tuning SimData, and a hand-made one is not something to guess at.

So the panel rows are reminders: net worth, the dynastic friend and the vacant throne are all
shown, and none of them can ever complete. `houserules.royalty.requirements` is the authority
on what is actually met.

`aspiration_nobleCareer_Level1` keeps EA's Charisma objective alongside ours; if the panel
shows only Charisma, the aspiration override did not load.

## Checking it in game

1. `py -3.7 tools/build.py ascent-to-royalty` (installs to `Mods\HouseRules\`).
2. Restart the game, open the Noble career panel on a Sim in that career, and look at the
   promotion requirements.

If EA patches EP21 and changes the career/aspiration instance ids, the first table's ids need
updating.
