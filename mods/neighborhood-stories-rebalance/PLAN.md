# Neighborhood Stories Rebalance

**Status:** planning · **Type:** mostly tuning (`.package`), possibly a small script · **Size:** small; good first mod

## Goal

Make EA's built-in Neighborhood Stories, which changes the lives of households you aren't playing, follow real-life patterns:

- **Adoption becomes rare.** Adopting a child or a horse should almost never happen. Getting a cat or dog stays fairly common.
- **Children move out more.** Young adults who still live with their parents should usually move out early in young adulthood.
- **Couples form households.** A sim who has moved out should tend to move in with a compatible, single partner, and only then have a chance of having a child.
- Births mostly come from couples living together, not from random events.

We change the existing system's numbers rather than replace it, so EA's per-household Neighborhood Stories settings keep working.

## Real-world reference points (rough targets, not exact)

| Event | Real-world anchor | Target in game |
|---|---|---|
| Leaving the parental home | EU average age ~26, Netherlands ~23–24 (Eurostat) | Most young adults move out within the first third of the young-adult stage |
| Adopting a child | Very rare: a few per 1,000 households in a lifetime | About 1/10 to 1/20 of the current weight |
| Adopting a horse | Rare, needs land and money | Close to 0, and only for households with money and space |
| Getting a cat or dog | About half of households have a pet | Roughly unchanged, maybe slightly up |
| Moving in together | Most people cohabit before or instead of marrying | Higher weight once both sims are single, have a romantic relationship and live alone or with roommates |
| First child | Mostly couples who live together, in their late 20s to early 30s | Requires a couple living together |

The age anchors need converting to the game's lifespan setting (Normal / Long), since the young-adult stage covers roughly ages 18 to the early 30s.

## How it works in the game (to confirm after decompiling)

1. Search `ea_scripts/simulation/` for `story_progression`. The newer Neighborhood Stories code (patch 121 and later) defines arcs/chapters/actions there. Note which tuning classes they use.
2. In Sims 4 Studio, extract the matching tuning XML and find the instances for: adopt child, adopt pet, adopt horse, move out, move in together, have baby.
3. Write down each one's weights, chances, cooldowns and tests in a table here.

**Open question:** are the weights fixed tuning values, or calculated in Python? If they're tuning, this whole mod is a `.package`. If they're code, we add a small script that injects the changed values.

## Steps

1. **Discovery** (see above). Record the current values.
2. **Write the changes** as XML Injector snippets where possible, so we don't overwrite whole EA files and stay compatible with other mods. Fall back to overriding the tuning only where a snippet can't reach.
3. **Separate horse and pet adoption** if they share one "adopt" weight.
4. **Make young adults move out more:** raise the move-out weight for young adults living with a parent, and maybe add a test that it only applies when they have a job or money.
5. **Testing:** set up a test save with ~10 unplayed households. Speed through 2–3 sim-weeks on ultra speed, then count events. The game logs Neighborhood Stories events in the phone's notifications, and we could add a small debug script that writes them to a file.
6. Publish (CurseForge / Mod The Sims) with a compatibility note about MCCC story progression.

## Out of scope

- Replacing MCCC's story progression. Users who run MCCC's version should turn one of the two off.
- Changing the in-game settings UI.
