# Hard Mode

**Status:** all phases built 2026-10-09. Career gates work in game; money (selling, markups, stands, bills, debt, starting funds), firing, skill aptitude and life (relationship decay, lingering bad moods, pregnancy and childcare costs, reward store prices) are to test - TESTING.md section 2. Not built: minimum home size for children, rent for households without a home. · **Type:** script · **Size:** medium

## Goal

Make the game *harder, not grindier*: things you can do now get **gated behind requirements**, and choices have consequences. No extra clicking, no slower bars.

Each part can be switched on or off (Challenge-Junkie does this through the mailbox, and it works well), so players can pick their own difficulty.

## What players say is too easy → what we change

### 1. Careers (first priority; closest to the original idea)
- **Entry requirements: skills *or* a degree** (Amber, 2026-10-09). To join a full-time career, a sim needs the career's minimum skill levels, **unless they have a relevant degree**, which waives the skill gate. So there are two routes in: study, or teach yourself. These are **entry gates only**: they decide who can start a career at level 1, so they're low, about level 2 in the main skill (Amber, 2026-10-09). Moving up is left to the game's own promotion requirements. Current numbers (in `hardmode_careers.py`):

  | Career | Skill gate (without a degree) | Degree that waives it |
  |---|---|---|
  | Doctor | Logic 2 | Biology |
  | Scientist | Logic 2 + Handiness 1 | Physics / Biology |
  | Astronaut | Fitness 2 + Logic 1 | Physics |
  | Engineer | Handiness 2 | Physics / Computer Science |
  | Law | Charisma 2 + Logic 1 | History / Psychology |
  | Education | Logic 2 or Charisma 2 | any degree |
  | Politician (activist) | Charisma 2 | Communications / History |
  | Business | Charisma 2 | Economics |
  | Tech Guru | Programming 2 | Computer Science |
  | Writer | Writing 2 | Language & Literature |
  | Painter | Painting 2 | Fine Art |
  | Culinary | Cooking 2 | Culinary Arts |
  | Entertainer | Comedy 2 or any instrument 2 | Drama / Fine Art |
  | Actor (Get Famous) | Acting 2 **or** 1 celebrity star | Drama |
  | Secret Agent | Fitness 1 + Charisma 1 | Psychology |
  | Athlete | Fitness 2 | none (skills only) |
  | Criminal | Mischief 2 | none (skills only) |

  Only full careers (`CareerCategory.Work`) are gated; teen and part-time jobs, side hustles and volunteering stay open. The table lives in one place in the code so it's easy to rebalance, and careers from packs you don't own are skipped. Degrees come from Discover University; the "Three Year Degrees + Master's" mod works too. Without Discover University, only the skill route exists.
  - **Built 2026-10-09** (`hardmode_careers.py`, tested): skill groups (all needed; alternatives within a group), degree waivers matched against *finished* degrees (`degree_tracker.previous_majors`; the earlier `accepted_degrees` was degrees a sim was only *accepted onto*). Careers, skills and degrees are matched by tuning name in the game; `bluerabbit477.hard.gates` shows what matched.
  - **Enforcement hook:** EA's `careers.select` command, which the Find a Job screen sends when the player picks a job. It's re-registered with an identical signature; it evaluates the rule, logs every pick, and when `enforce` is on refuses a failing pick with a notification. Every other `add_career` route (loading saves, NPC story progression, businesses, fixups) bypasses it. `enforce` is off by default until tested in the game.
- **Getting fired:** a few missed days or a very bad performance gets the sim fired, and other employers take that into account for a while.

### 2. Money
**Selling is the biggest money problem** (Amber, 2026-10-09): selling things is far too easy a source of money. This comes first in the money phase.

- **Lower sale prices, per kind of item.** Things you make or gather (paintings, crafted items,
  harvests, crystals and gems, collectibles, fish) sell for a fraction of their listed value,
  like selling to a shop rather than to a buyer. Example starting point: ×0.5 for made or
  gathered items, ×0.7 for second-hand furniture, ×1 for everything else. Each item type's
  multiplier is a setting, using object tags to tell the kinds apart.
- **The market fills up:** each item kind sold in the same sim-week gets cheaper (e.g. −10%
  per sale, down to a floor of ×0.3). The price recovers over the following days. Mass-producing
  one thing stops paying off, and a varied household does better. The sale history is kept per
  household.
- **How (confirmed in EA's code, 2026-10-09):** nearly every way of selling asks one function
  for the price multiplier: `get_item_sell_price_modifier(item)` on the sim's buff component.
  That covers selling from the inventory (`inventory_commands.py`), sell pickers
  (`picker_interaction.py`), harvested crops (`gardening_component_crop_plant.py`), sell
  payouts (`money_payout.py`, `loot_ops.py`, `destruction.py`), dragging to sell
  (`server/client.py`), and the price **shown** in the inventory (`inventory_storage.py`). So one
  hook changes both the money and the price the player sees. It's EA's own mechanism for trait
  and buff sell bonuses, so ours multiplies in alongside theirs. Still to work out: the exact
  wrapping technique, because component methods are copied onto the sim class when the game starts.
- **Shop and stall markups** (Amber, 2026-10-09): Get to Work retail and the Business & Hobbies
  stalls allow up to 300% markup, which is far too profitable. Real shops can't charge triple
  without losing most of their customers.
  - **How it works now (EA's code):** both businesses price items through one function,
    `BusinessManager.get_value_with_markup` (`SmallBusinessManager` is a subclass and doesn't
    override it). Customers barely react. Retail picks its customer mix from a list keyed by the
    markup level (`RetailZoneDirector.customer_situations`). Stalls lower satisfaction per sale
    through `SmallBusinessTuning.MARKUP_AND_SATISFACTION_MAPPING`.
  - **Plan:**
    1. **Diminishing markup income.** Wrap `get_value_with_markup` so extra markup earns less and
       less. Example: the first +50% counts in full, the next +50% counts half, and anything above
       +100% counts a quarter. So 300% markup ends up at about +125%, not +200%. This one hook
       covers both businesses.
    2. **Customers react to price.** Make the satisfaction penalty in
       `MARKUP_AND_SATISFACTION_MAPPING` much steeper at high markups: unhappy customers leave
       bad reviews and the stall's reputation drops. This can be done like Neighborhood Stories:
       build an edited copy of the mapping and swap it in. Retail's customer mix at high markup
       could shift toward browsers who don't buy (that one is tuning on the zone director, so harder).
  - **Market stands / sales tables** (Amber: the pizza-and-waffles stand, most likely Home Chef
    Hustle, but you can sell anything on it). These run on EA's sales-table ("yard sale")
    system (`YardSaleSituation`), not the business manager. A customer's purchase pays out
    through a loot operation: `DestroyTargetObjectsLootOp._get_object_value` (`loot_ops.py:886`),
    which pays **item value × award multiplier × tested multipliers × sell-price modifier**. The
    stand's price setting is most likely one of those multipliers. Plan: wrap `_get_object_value`
    on that class and on `DestroyObjectsFromInventoryLootOp`, and when it's a sell action, apply
    the same diminishing-markup curve to everything above ×1, plus the item-kind reduction
    above. **First confirm in the game:** log every sale with each multiplier separately, to see
    which one carries the stand's price setting.
  - In-game check: `bluerabbit477.hard.money.status` prints the effective markup for each markup
    level, and the log records every shop, stall and stand sale (listed price → what was earned,
    with each multiplier).
- Smaller starting funds (setting: 20k / 10k / 5k / 0).
- Bills that scale more realistically with the household's size and the home's value. A rent-like housing cost for households without their own home.
- Book royalties and other passive income get the same "market fills up" treatment, so they're worth less when lots arrive in a short time.
- **Debt** instead of "can't pay, so the power goes off": unpaid bills build up debt with interest. Too much debt means a credit score that blocks buying a house or setting up a business, and eventually repossession. (Script.)

### 3. Skills
- **Aptitude:** traits give each sim a skill ceiling or a speed multiplier. For example, a Bookworm sim levels Writing faster, and a sim without a relevant trait slows down past level 7. Each sim gets 1–2 random "talents" at young adult.
- Less impact from moods: being inspired or focused gives a smaller boost.

### 4. Life, needs and relationships (later)
- Strong bad moods linger longer (grief, embarrassment, stress at work).
- Relationships fade faster without contact (EA's decay rate goes up).
- Pregnancy and adoption cost money and need a certain minimum home size. Childcare costs when both parents work.
- Weaker reward-store traits, or a higher price for them.

## Building it

- **Tuning** (Sims 4 Studio + XML Injector): career join tests, level requirements, salaries, bill multipliers, skill gain modifiers, mood buff strengths, relationship decay. Wherever possible we *add tests* to existing tuning instead of overwriting whole files, for compatibility.
- **Script:**
  - Settings storage and a settings menu (start with cheat commands like `bluerabbit477.hard.careers on`, then a mailbox interaction with a menu).
  - Debt, credit score, getting fired, diminishing returns on passive income: these need state and logic that tuning alone can't do.
  - Reading the settings at load time, and switching modules on or off.

## Phase order
1. **Career gates** (tuning-heavy, very visible): the MVP.
2. Settings menu (script), so career gates can be turned on and off.
3. Money: **selling first** (lower sale prices per item kind, the market filling up, shop and
   stall markups), then starting funds, bills, debt.
4. Skill aptitude.
5. Life and relationships.

## Discovery tasks (after decompiling and extracting tuning) — done 2026-10-09 overnight

**Confirmed from reading the decompiled source:**
- `sims4/commands.py`'s `_parse_arg` confirms bare `str`/`int` cheat parameter annotations (used
  by `.hard.careers on|off`) are genuinely supported, not a guess - same finding as npc-routines.
- A real bug, also shared with npc-routines and fixed the same way: `.hard.check`'s sim-targeting
  was using `OptionalTargetParam` (resolves to a `Sim` game object / object-manager lookup) where
  it needed `OptionalSimInfoParam` (resolves to `SimInfo`, which is what `.degree_tracker` and
  `.career_tracker` actually live on) - see npc-routines/PLAN.md for the full explanation,
  including the separate `target_type=` gotcha on `get_optional_target()`. Fixed in `hardmode_main.py`.
- `CareerCategory` enum (`career_enums.py`): `Work` (a full adult career), vs `TeenPartTime`,
  `Volunteer`, `AdultPartTime`, `UniversityCourse`, `TeenSideHustle`, `WorkFromHome`, `School`.
  Phase 1's rule gates `CareerCategory.Work` specifically, so teen jobs, side hustles and
  volunteering are untouched.
- `sim_info.degree_tracker.accepted_degrees` (`sims/university/degree_tracker.py`) exists and
  is readable. Phase 1 only checks it's non-empty (any degree at all) — matching a degree to a
  *specific* career would need a per-career-to-degree tuning map, which is tuning data we have
  no way to read without a running game. Noted as a simplification, not forgotten.
- A sim's current careers are iterable via `sim_info.career_tracker` (confirmed used this way at
  `careers/career_base.py:456`), each with `.guid64` and `.career_category` — enough to check
  "is this sim already employed in this exact career" (the grandfather clause).

**Three real hook points exist for actually *blocking* a join. We looked at all three — the
third, found later in the night while there was still time, looks genuinely promising, but
still wasn't something to commit to without a running game to check it against, so phase 1
stops short of enforcing anything regardless:**

1. `CareerBase.is_career_available` (`careers/career_base.py:451`, a `@flexmethod` — works as
   both a classmethod and instance method) — EA's own check for whether a career is visible/
   joinable, built on a tunable test set (`career_availablity_tests`). **Risk:** this almost
   certainly runs very often (every time the career panel renders, every tooltip) — a mistake in
   wrapping a `@flexmethod` correctly could break career availability for every sim, not just
   fail safely once. High blast radius for an untested change.
2. `CareerTracker.add_career` (`careers/career_tracker.py:144`) — the method that actually adds
   a career to a sim. Lower call frequency, closer to "the moment of joining," which is
   appealing. **Risk:** its signature takes `show_confirmation_dialog`, `show_join_msg` and
   other flags whose exact meaning we could only guess at (no running game to check against) —
   and it's plausible this same method also runs when a **save loads and restores an existing
   career**, not only on a genuine new player-initiated join. If that guess is wrong and we
   blocked unconditionally, a sim could silently lose an existing career on every load. That's
   real, unrecoverable data loss for the player's actual sims, not just a mod misbehaving - too
   severe to risk on an unverified reading of a decompiled method signature.
   **This risk is now confirmed real, not hypothetical:** grepping every call site of
   `add_career` across the whole decompiled codebase (`careers/career_ops.py`,
   `careers/career_gig.py`, `careers/school/school_tuning.py`, `sims/university/degree_tracker.py`,
   `sims/fixup/sim_info_career_fixup_action.py`, `world/premade_sim_fixup_helper.py`,
   `business/business_employee_manager.py`, `kingdom/kingdom_service.py`,
   `story_progression/story_progression_actions/story_progression_action_career.py`, and more)
   turned up over a dozen call sites, several of which are explicitly fixup/repair/migration
   code or the game's own NPC-career-assignment story progression — confirming this one method
   really is shared by many things that must never be blocked, not just player-initiated joins.
   Ruled out for good, not just for tonight.
3. **Found later, more promising:** `CareerLootOp._apply_to_career` (`careers/career_ops.py:245`)
   is the method that actually applies a career-related Loot operation — the mechanism EA's own
   "join this career" interactions use to take effect once the interaction completes. It
   dispatches on `op.operation_type`, with a dedicated `CareerLootOp.OP_JOIN` branch (line ~277)
   that is the one that calls `add_career` *specifically for a player-driven join* — other branches
   handle promote/demote/fire/quit/etc. separately, and none of the other-call-sites-of-`add_career`
   found above go through this method at all (they call `add_career` directly, bypassing it). A
   wrapper here could check `operations` for `OP_JOIN` specifically and only then apply our gate -
   much narrower than hook 2, and Loot ops fire once per completed interaction (far less often
   than hook 1). **Still not implemented** - this is one method inside a bigger "Loot" framework
   we haven't otherwise explored tonight (how `BaseLootOperation` subclasses get invoked, whether
   wrapping an instance method here is as mechanically safe as wrapping a module-level function),
   and there was no running game left to check any of it against. This is the strongest lead for
   next time, not a confirmed answer.
   **Update, same night, a bit later:** checked the mechanical-safety question above -
   `CareerLootOp` (`interactions/utils/loot_ops.py`) is a `HasTunableSingletonFactory`, so
   wrapping its `_apply_to_career` method is the exact same class-method-wrapping technique
   already used (twice, successfully) elsewhere tonight, not a new kind of risk. And because the
   other `add_career` call sites bypass this method entirely, gating only on
   `operation_type == OP_JOIN` here structurally can't catch any of the fixup/business/kingdom/
   story-progression cases that ruled out hook 2 - that failure mode doesn't apply here by
   construction, not by a guess. What's still unverified, and is exactly where to start next
   time: (a) the full body of `_apply_to_career`/its caller, to confirm returning early cleanly
   aborts just the career part; (b) whether a career-join interaction's *other* loot ops (money,
   notifications, …) still fire even if we block the career one - if so, the player could see a
   "congratulations on your new job" message for a job they were just refused, which is a real
   but non-destructive rough edge, not a safety issue; (c) what to show the player instead
   (a notification explaining the degree requirement, rather than a silent no-op).

**Decision: phase 1 ships read-only regardless.** `hardmode_main.py` reads real sim/career/degree
data via the confirmed APIs above and reports what the rule *would* decide — it never calls
`add_career`, never touches `is_career_available` or `CareerLootOp`, never blocks anything. The
next session with a running game should: load a save, try `bluerabbit477.hard.check <career>
[sim]` against a few real sims and careers to sanity-check the read-only logic, then look at
hook 3 above first — it's the one worth pursuing — before wiring up real enforcement.

- Still open: the bills module (money phase) and how skill gain rate is put together (skills
  phase) — not reached tonight, left for a later session.

## Open questions
- Should this be one mod with modules, or a few separate mods ("Hard Mode: Careers", "Hard Mode: Money")? Separate is easier to test and publish. One is easier for a single settings menu. Possible compromise: one script core, plus separate tuning packages.
- How does it behave on existing saves where sims already have careers that wouldn't meet the new requirements? **Decided:** grandfathered — `hardmode_careers.should_block_join` takes
  `already_employed_here` and always returns `False` (never blocks) when true. Confirmed by test
  (`test_grandfathers_sims_already_employed_in_the_career`).
