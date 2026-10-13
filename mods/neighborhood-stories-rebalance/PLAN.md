# Neighborhood Stories Rebalance

**Status:** phase 1 built, untested in-game · **Type:** script (not tuning — see below) · **Size:** small

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

## How it works in the game (confirmed by reading the decompiled scripts, 2026-10-09 overnight)

`StoryProgressionService` (`story_progression_service.py`) has a class-level tunable
`STORY_PROGRESSION_PASSES`: a list of passes, each with `potential_arcs` — a **weighted list**
of `(story_arc, weight)` pairs (`weight` is an int, tunable minimum **1**), plus per-demographic
`chance_of_occurrence` percentages. This is a code-visible structure, not something we can read
out of the decompiled `.py` files as numbers (the actual XML tuning values live in the game's
packed data files, which need Sims 4 Studio to extract — we didn't have a running game tonight to
check it that way). **So this is a script mod, not a `.package`**: we read and adjust the already
tuning-loaded Python objects at runtime instead of editing XML.

Each `story_arc` resolves (via its first `StoryChapter`) to a list of `actions`. The action
*type* tells us what the arc actually does — confirmed in `story_progression_chapter.py`:

- `SimStoryChapter.actions` variants: `add_family_member` → `AddFamilyMemberStoryProgressionAction`
  (adoption — children, cats, dogs *and* horses all use this one action with a different
  `template` tunable each time, so we must also look at the action's `template` reference, not
  just its class), `pregnancy` → `MakePregnantStoryProgressionAction`, plus career/death/relationship actions we leave alone.
- `HouseholdStoryChapter.actions` variants: `move_in` → `MoveInStoryProgressionAction`,
  `move_out` → `MoveOutStoryProgressionAction`.

So: walk `STORY_PROGRESSION_PASSES` → `potential_arcs` → each arc's initial chapter's `actions`,
classify by action class (and, for adoption, by the `template` name: anything containing "horse"
→ horse, "cat"/"dog"/"pet" → pet, else → child), and scale `weight` for the matching entries.

**What we could *not* confirm tonight, for lack of a running game:**
- The actual tuning instance names and current weight numbers (needs Sims 4 Studio against a
  loaded game, or a save).
- Whether `action_factory.factory` is really the right attribute to read the action class from a
  resolved `TunableVariant` — the code does `.TunableFactory()` which matches this pattern from
  other tuning classes we've seen, but we have no running game to check it against. The script
  below tries a few attribute names and logs which one worked (or that none did), rather than
  guessing silently.
- Whether the resolved `TunableTuple` entries (the `(story_arc, weight)` pairs) are actually
  mutable at runtime. The script checks this and logs it rather than assuming.

## Multipliers (phase 1, implemented)

See `scripts/nsr_classify.py` for the actual numbers. Weight is an integer with a tunable floor
of 1, so a weight of 1 can only ever be *left at 1*, not pushed to 0 — a true "almost never" for
horse adoption isn't reachable this way if EA's base weight is already low. Noted as a limitation
until we can check real numbers.

| Category | Multiplier |
|---|---|
| child adoption | ×0.1 |
| horse adoption | ×0.05 (and see the floor-of-1 limitation above) |
| cat/dog adoption | ×1 (left alone) |
| move out | ×3 |
| move in together | ×2 |
| pregnancy | ×1 (left alone — out of scope this round) |
| anything else | ×1 (left alone; logged either way) |

## Steps

1. ~~Discovery~~ (done above, from source — not yet from a live game; re-check once the game can run).
2. **Built:** `nsr_classify.py` (pure logic: no game imports, pytest-covered) + `nsr_main.py`
   (hooks `zone.Zone.on_loading_screen_animation_finished`, applies the multipliers once per game
   session — guarded so re-loading a save doesn't compound the multiplier — and logs everything
   it did/couldn't do to `Mods/BlueRabbit477/logs/neighborhood-stories-rebalance.log`).
3. Cheat `bluerabbit477.nsr.status` prints the last run's findings (arc name, category, old
   weight, new weight) — **this is the fast way to check the mechanism itself works**, no need to
   wait sim-weeks for an adoption to or not happen. Do this first.
4. **Still to do, once it can be checked against a real game:** confirm the attribute-name
   guesses above against real tuning objects; confirm actual current weights are sane to multiply
   (if EA's own weights are already tiny ints, these multipliers may round to no change — see the
   floor-of-1 note); consider also touching `chance_of_occurrence` (not done tonight, lower
   confidence); the slower, true test — a save with ~10 unplayed households sped through 2-3
   sim-weeks, counting actual events.
5. Publish (CurseForge / Mod The Sims) with a compatibility note about MCCC story progression — later.

## Out of scope

- Replacing MCCC's story progression. Users who run MCCC's version should turn one of the two off.
- Changing the in-game settings UI.
