# Neighborhood Stories Rebalance

**Status:** phase 1 (weights) tested in game; phase 2 (age-up careers) built, to test · **Type:** script (not tuning — see below) · **Size:** small

## Goal

Make EA's built-in Neighborhood Stories, which changes the lives of households you aren't playing, follow real-life patterns:

- **Adoption becomes rare.** Adopting a child or a horse should almost never happen. Getting a cat or dog stays fairly common.
- **Children move out more.** Young adults who still live with their parents should usually move out early in young adulthood.
- **Couples form households.** A sim who has moved out should tend to move in with a compatible, single partner, and only then have a chance of having a child.
- Births mostly come from couples living together, not from random events.
- **Young adults get a career.** When a sim in an unplayed household ages up to young
  adult or adult, there is a realistic chance they get a job that fits their skills and
  traits. This is a new event, not an EA weight change; it respects the household's
  Neighborhood Stories career rule.

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
of 1, and weights only compare arcs *within one pass*. That means re-weighting a pass with only
one arc (MoveOut, MoveIn, CareerAdd) or only one category (Horse Adoption) cannot change how
often it happens. Those are left at ×1 and handled by the phase 2 logic instead.

| Category | Multiplier |
|---|---|
| child adoption | ×0.1 |
| horse adoption | ×1 (left alone; gated by lot size and wealth below) |
| cat/dog adoption | ×1 (left alone) |
| move out | ×1 (left alone; age-up split below) |
| move in together | ×1 (left alone; EA MoveIn still houses homeless households) |
| pregnancy | ×1 (left alone) |
| friendship start | ×2 → weight 1 becomes 2 |
| friendship gain / loss | ×2.667 → weight 3 becomes 8 |
| becoming best friends / despised | ×0.4 → weight 10 becomes 4 |
| anything else | ×1 (left alone; logged either way) |

## Age-up steps (phase 2, implemented)

EA's `CareerAdd` and `MoveOut` story arcs are periodic random events; neither is tied
to the age-up moment. Phase 2 adds age-up triggers in the script. All of them hook
`AgingMixin.change_age`, run only for households whose Neighborhood Stories rule set
allows the relevant step, and log every attempt.

### University

- Only for the **Teen → Young Adult** transition, and only if Discover University is
  installed (`sim_info.degree_tracker` exists).
- The household's Neighborhood Stories setting must be on.
- The chance depends on **household net worth** (funds + home lot value + inventory), so
  wealthier families are more likely to send a young adult to university:

| Household net worth | Chance |
|---|---:|
| ≤ §25,000 | 10% |
| ≤ §50,000 | 20% |
| ≤ §100,000 | 35% |
| ≤ §200,000 | 55% |
| above §200,000 | 75% |

- On success, the mod picks a university at random and a major from the sim's top three
  skills using EA's `University.SKILL_TO_MAJOR_TUNING`, marks the degree accepted, and
  enrols them in 3 courses.
- The student is then moved into a **university hall/building** in the Discover
  University world when one has room; if none does, they stay at home.
- A student **skips the career and move-out rolls** for that age-up: university is their
  main activity, and they should not also be split into a homeless household.
- A student who is still enrolled when they age from **Young Adult to Adult** graduates
  automatically and receives the degree trait through EA's normal graduation. The grade
  used is their current GPA, or 2.0 if they have no grades yet.
- If that graduate is living in a university hall/building, they move out: back to the
  family home if it exists and has room, otherwise into a new household with no home.

### Career

- Only when a sim **ages up into Young Adult or Adult**.
- A young adult who enrolled at university that age-up is skipped; university counts as
  their main activity.
- Only when the household's own Neighborhood Stories rule set passes the `CareerAdd`
  arc's required rules.
- Only when the sim has **no full-time career** after EA's own age-up cleanup. A sim with
  only a part-time job can still get a full-time one.
- Rolls **73% for Young Adult and 95% for Adult**, aimed at roughly 70–75% employed young
  adults and 95% employed adults among non-students. A failed roll is logged and does
  nothing.
- Of the jobs assigned, **35% of Young Adult jobs and 20% of Adult jobs are part-time**
  (`CareerCategory.AdultPartTime`); the rest are full-time. University students are in
  education, not in these employment figures.
- Picks from careers that EA itself allows story progression to assign
  (`career_story_progression.joining` is set and `is_valid_career` passes), excluding
  NPC-only careers. The weight is EA's `joining` multiplier multiplied by
  `nsr_life.career_affinity`: relevant skills (level 0–10) and traits make a career more
  likely. A level-10 painter skill, for example, gives Painter a ×3 skill weight before
  traits.

### Move out

- Only for the **Teen → Young Adult** transition, never for adults. Multiple adults can
  legitimately live in one house, so an adult age-up must not split the household.
- Only when the household has more than one member and its Neighborhood Stories rule set
  passes the `MoveOut` arc's required rules.
- Rolls **50%**. A failed roll means the young adult stays in the parental home.
- On success, creates a new household with `home_zone_id = 0` and moves just that sim
  into it, leaving the parents and any siblings behind.
- EA's existing `MoveIn` pass can then house that new homeless household in an empty
  residential lot. That pass is not immediate and is gated by how many lots are empty
  (roughly 0% / 15% / 25%).
- EA's old whole-household `MoveOut` arc is separately restricted: it only runs for a
  **single adult** household (exactly one member, teen or older, no spouse, fiancé or
  romance track). That makes it behave like one unencumbered person moving out rather
  than a family disappearing.

### Horse adoption

Horse adoption is gated where the horse is actually created, not by arc weight:

- The household's home lot must be at least **2000 tiles** (50×40; 64×64 also passes).
- Household funds must be at least **§50,000**.
- Even when both pass, the action is allowed only on a **5% roll**, on top of EA's own
  Horse Adoption pass chance. A rich household on a small lot, or a large lot with no
  money, can never get a horse. Homeless households are excluded because they have no lot.

This makes horses genuinely rare while still possible for a large, wealthy household.

`nsr_life.py` is the pure decision layer and is covered by pytest. The game layer lives
in `nsr_main.py` and has the cheats `houserules.nsr.university`,
`houserules.nsr.graduates`, `houserules.nsr.careers`, `houserules.nsr.splits` and
`houserules.nsr.couples` for the last outcomes.

## Daily relationship and move-in logic

This part is not tied to age-up. It runs once per sim day, after EA's story-progression
pass, and only for households with Neighborhood Stories on.

- **Starting a romance:** if two sims are both unattached, at least teen, not related, and
  have **GOOD** or **AMAZING** compatibility, the mod rolls a daily chance to add the
  `romantic-Significant_Other` bit. The base chance is **5%** for GOOD and **15%** for
  AMAZING, multiplied by age: **Teen 0.4**, Young Adult 1.0, Adult 0.8, Elder 0.3.
  Compatibility uses EA's Lovestruck level when it exists; otherwise a coarse fallback
  based on shared and clashing personality traits is used.
- **Pregnancy is left to EA.** The mod never starts a pregnancy itself, and does not
  block the pregnancy action, so mods that allow teen pregnancy keep working. The
  move-in-together step still requires both sims to be at least young adult.
- **Moving in together:** pairs in different households with a romance bit, a pregnancy,
  or a child together roll a daily chance to merge households: **5%** romance-only,
  **10%** shared child, **15%** pregnancy. Both households must allow the `MoveIn` rule,
  the target household must have room, and a sim is never moved away from their own
  children in the source household (except when moving into the shared child's household).
- If the mover's old household becomes empty, it is cleaned up. The move-in uses EA's
  normal household switch, so relationships and family ties stay intact.
- **Couples have children through one shared daily step.** With the relevant rule on and
  a free household slot:
  - same-sex couples roll **2% per day** for one of EA's child-adoption arcs;
  - opposite-sex couples roll **2% per day** for EA's pregnancy arc;
  - opposite-sex couples also get a **0.5% per day** adoption chance as the fuzzy edge
    of real life.
  This sits on top of the now-rare general child-adoption weight.
- **EA's own relationship arcs are gated by the current relationship:** Becoming Best
  Friends needs friendship ≥ 50, Becoming Despised needs friendship ≤ −20, and Romance
  Start needs GOOD or AMAZING compatibility. This stops the 99%-daily pass from jumping
  strangers straight to best friends or enemies.
- Friendship Changes weights now favour gradual movement: BecomingFriends 2, Gain 8,
  Loss 8, BecomingBestFriends 4, BecomingDespised 4 (instead of 1/3/3/10/10).



Every change is deliberately limited to households that have Neighborhood Stories on, and
to the matching per-household rule where one exists:

| Change | Gate |
|---|---|
| child adoption weight | global tuning, but EA only offers the arc to households whose rule set allows it |
| horse adoption | overall Neighborhood Stories on **and** the household's horse-adoption rule |
| age-up career | overall on **and** the `CareerAdd` rule |
| age-up move-out | overall on **and** the `MoveOut` rule |
| EA whole-household move-out | overall on + `MoveOut` rule + single adult, no children/partner |
| age-up university | overall on (there is no university-specific rule) |
| age-up graduation | overall on |
| daily new romance | overall on for both households |
| EA friendship/romance arcs | overall on + current friendship score or GOOD/AMAZING compatibility |
| daily move-in together | overall on + `MoveIn` rule for both households + both at least Young Adult |
| daily couple child | overall on + adoption or pregnancy rule + free household slot |
| household with Neighborhood Stories off | never touched |
| matching rule disabled (careers, move-outs, horse) | that change is skipped |

The weight table itself is global because `STORY_PROGRESSION_PASSES` is global; EA's
candidate selection calls `rule_set.verify(arc.required_rules)` before seeding an arc, so
a household with Neighborhood Stories off, or with that category disabled, never receives
the arc.

**Still not implemented:** pregnancy does not require cohabitation. The daily move-in
logic can bring a couple together, but EA's pregnancy action still only needs a romance
bit, so a pregnancy can happen before they share a household.

## Steps

1. ~~Discovery~~ (done above, from source — not yet from a live game; re-check once the game can run).
2. **Built:** `nsr_classify.py` (pure logic: no game imports, pytest-covered) + `nsr_main.py`
   (hooks `zone.Zone.on_loading_screen_animation_finished`, applies the multipliers once per game
   session — guarded so re-loading a save doesn't compound the multiplier — and logs everything
   it did/couldn't do to `Mods/HouseRules/logs/neighborhood-stories-rebalance.log`).
3. Cheat `houserules.nsr.status` prints the last run's findings (arc name, category, old
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
