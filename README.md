# Sims 4 mods

Gameplay mods for The Sims 4, all part of the **House Rules** suite. Each one changes a
different part of the game and they can be installed separately — take only the ones you want.

All mods are **script mods**: they add behaviour the game doesn't have, without replacing
EA's files, so they keep working with EA's own settings and with most other mods.

> **Work in progress.** These mods are in active development and several features are still
> being tested in game. Grab the latest release and back up your save before using them in a save you care about.

## Install

1. Get the mod files — download them from this repo's **Releases** page, or build them from
   source (see [DEVELOPMENT.md](DEVELOPMENT.md)).
2. In `Documents\Electronic Arts\The Sims 4\Mods\`, make a folder called `HouseRules`
   (any name works, but this keeps the mods together).
3. Copy the mod files you want into that folder:
   - `HouseRules_<mod>.ts4script` for each mod
   - every `HouseRules_<mod>.package` (Hard Mode's phone menu entry and Flexible
     University's Early Graduation entry)
   - the `scenarios` folder (if you want the example Scenarios)
4. Start the game and enable mods in **Game Options → Other**:
   **Enable Custom Content and Mods** and **Script Mods Allowed**.
5. Restart the game. Script mods only load at startup.

To remove a mod, delete its files from the folder. To remove everything, delete the
`HouseRules` folder. Saves stay intact; the mods' own state lives in
`Mods\HouseRules\data\`.

The game writes a log per mod to `Mods\HouseRules\logs\`. If something goes wrong, also
check `lastException*.txt` in `Documents\Electronic Arts\The Sims 4\`.

## The mods

| Mod | What it does |
|---|---|
| [Hard Mode](#hard-mode) | Makes the game harder by gating things behind requirements: careers need skills or a degree, selling pays less, bills and debt exist, skills need talent, bad moods linger. |
| [Flexible University](#flexible-university) | Discover University without the rigid pacing: leave early with a Certificate or Associate Degree, keep the credits you earned, graduate on Friday evening, and earn fractional credits for good grades. |
| [Neighborhood Stories Rebalance](#neighborhood-stories-rebalance) | Makes EA's Neighborhood Stories follow real-life patterns: rare adoption with a same-sex route, university or a skill-matched career on age-up, realistic move-outs and relationships, and no more whole families vanishing. |
| [Social Standing](#social-standing) | Friendships and romances build at a realistic pace: compatibility sets the speed, and a big gap in wealth, fame or title makes sims act like celebrities around each other. |
| [Ascent to Royalty](#ascent-to-royalty) | The climb from knight to monarch takes savings, generations and alliances: the game's Noble career only promotes you when your dynasty has earned the next rank. |
| [Social Gates](#social-gates) | Social access means something: only friends let you into their house or accept an invite, and clubs only accept sims who fit their traits, skills or activities. |
| [Aspiration Progress](#aspiration-progress) | Aspiration goals count whenever you complete them, even before you reach that level — and a level pays out as soon as all its goals are done. |
| [Scenarios](#scenarios) | Play custom challenges from simple text files: starting conditions, goals that check themselves, and rules with penalties. Seven examples included. |
| [NPC Routines](#npc-routines) | Give sims a weekly routine (gym on Mondays, painting after work) and let the game run their lives for you. Optional local-AI brain: give a sim a goal and start it on demand. |

There are also two developer mods, not needed for normal play:
`HouseRules_hello-world.ts4script` (build pipeline check) and
`HouseRules_self-test.ts4script` (in-game diagnostics — see
[DEVELOPMENT.md](DEVELOPMENT.md#in-game-self-test)).

## Requirements

- The Sims 4 with script mods enabled. Built against a current game version; a major patch
  can break script mods until they're updated.
- **No packs are required for the core mods.** Ascent to Royalty is the exception: it needs
  **EP21 Royalty & Legacy** and stays inactive without it. Features that use another pack are
  skipped when it isn't installed:
  - **Discover University** — finishing any degree waives Hard Mode's career skill gates,
    and so does a Flexible University Certificate or Associate Degree. Without the pack, only
    the skill route exists. Flexible University needs the pack itself; it is inactive without
    it.
  - **Get Famous** — fame counts towards Social Standing, and its celebrity reactions are
    reused; without it, status still works.
  - **Lovestruck** — its chemistry score is added to Social Standing's compatibility.
  - **Get to Work / Business & Hobbies / Home Chef Hustle** — Hard Mode adjusts their shop,
    stall and stand markups.
  - **Cats & Dogs / Horse Ranch** — Hard Mode's Neighborhood Stories weights cover pet and
    horse adoption.
- Mods from other creators: no XML Injector or script library needed. If another mod replaces
  the same interaction (doorbells, invites, job picking, selling), only one can win — see
  [Conflicts](#conflicts).

## Hard Mode

Turns "too easy" into "needs a plan", without extra clicking or slower progress bars. Every
part can be switched off individually. Settings are saved in
`Mods\HouseRules\data\hard_mode_settings.json`.

- **Career entry gates.** To start a full-time career, a sim needs the career's minimum skills
  (around level 2 in the main skill), *or* any completed university degree, *or* a Flexible
  University Certificate or Associate Degree. Only entry is gated;
  promotion is still EA's own. Part-time and teen jobs are not gated.
- **Getting fired.** Missing several work days in a week, or very bad performance, gets a sim
  fired — and other employers refuse them for a few days.
- **Selling pays less.** Made and gathered things (paintings, crafts, harvests, fish, gems)
  sell for less than their listed value. The market also fills up: selling lots of one kind
  makes that kind worth less for a week, then it recovers.
- **Shop and stall markups earn less.** Big markups have diminishing returns and customers
  mind them more, so a 300% shop isn't a money printer.
- **Bills and debt.** Bills grow with household size. Unpaid bills become debt with interest
  instead of simply shutting the power off, and too much debt limits buying a home or opening
  a business. With debt, the phone gets a **Pay Off Debt** option (and the debt is paid down
  daily from household funds when possible).
- **Skill aptitude.** Each young adult gets one or two random talents, and traits give
  affinities for related skills. Without a talent or matching trait, skills slow down past
  level 7.
- **Life costs.** Relationships fade faster, strong bad moods linger, pregnancy and childbirth
  cost money, childcare costs per child, and reward-store items cost more.
- **Starting funds.** New households start with §10,000 instead of §20,000.

Commands (cheat console, Ctrl+Shift+C):

```
houserules.hard.status                 show every setting and its value
houserules.hard.set <setting> on|off   change one (start_funds takes a number)
houserules.hard.careers on|off         turn career gates on or off
houserules.hard.enforce on|off         actually refuse jobs that fail the gate (off by default: it only logs)
houserules.hard.check <career>         what the rule decides for the selected sim, and why
houserules.hard.gates                  which careers/skills the gate table matched
houserules.hard.skills                 selected sim's talents and skill factors
houserules.hard.money.status           markup table, market prices and debt
houserules.hard.money.pay_debt         pay debt early (no amount opens a picker)
houserules.hard.money.reset            forget this household's sales history and debt
```

Settings: `careers`, `enforce`, `firing`, `selling`, `markups`, `bills`, `debt`, `skills`,
`life`, `start_funds`.

## Neighborhood Stories Rebalance

Adjusts EA's own Neighborhood Stories at runtime; your per-household settings still apply.
Everything only runs for households with Neighborhood Stories on, and for the matching
sub-rule where one exists (careers, move-outs, horse adoption, pregnancy).

### At a glance

| Area | What changes |
|---|---|
| **Child adoption** | Rare globally (weight ×0.1). Same-sex couples also get a **2% daily** adoption chance with the adoption rule and a free slot. Opposite-sex couples get a **0.5% daily** adoption chance as a fuzzy edge. |
| **Horse adoption** | Only possible on a **50×40-or-larger lot** with **§50,000+**, and then only on a **5% roll**. |
| **Cat/dog adoption** | Roughly unchanged. |
| **Pregnancy** | Opposite-sex couples with a free slot get **2% daily**. Pregnancy still only needs a romance bit, not cohabitation. |
| **Career** | Age-up chance **73%** for young adults and **95%** for adults; **35% / 20%** of those jobs are part-time. Students skip this roll. EA’s daily CareerAdd still runs. |
| **University** | Teen → young adult: **10–75%** by family net worth. Enrols, picks a major from top skills, moves into university halls if there is room, and skips the career/move-out rolls. |
| **Graduation** | Young adult → adult: graduates, gets the degree trait, and moves out of halls (back home if there is room, otherwise into their own household). |
| **Move-out** | Teen → young adult: **50%** chance to split into a homeless household. EA’s old whole-household move-out is limited to a **single adult with no children or partner**. |
| **Move-in** | Couples with a romance bit, a pregnancy, or a shared child get **5% / 15% / 10% daily** to merge households. Both need the MoveIn rule on and both must be young adult or older. EA’s MoveIn also houses homeless split households. |
| **Romance start** | Unattached sims with **GOOD** or **AMAZING** compatibility: **5% / 15% daily**. Age multiplier: teen **40%**, young adult **100%**, adult **80%**, elder **30%**. EA’s Romance Start also needs GOOD/AMAZING compatibility. |
| **Friendship** | Gradual gains/losses are favoured (effective weights **2 / 8 / 8 / 4 / 4** instead of EA’s 1 / 3 / 3 / 10 / 10). Best-friend and despised jumps only happen if the pair is already close or hostile. |

### The age-up flow

```
Teen → Young Adult
  ├─ university roll (10–75% by family net worth)
  │    success → enrol, move into halls if room, skip career + move-out
  │    failure → career roll 73% (35% part-time) → move-out roll 50%
  └─

Young Adult → Adult
  ├─ if still a student → graduate, get degree trait, move out of halls
  └─ career roll 95% if no full-time job (20% of jobs part-time)

Every sim day
  ├─ compatible, unattached sims may become Significant Others
  ├─ couples / pregnant / shared-child pairs may move in together
  ├─ couples with a free slot may have or adopt a child
  └─ friendship arcs prefer gradual change; extreme jumps are gated
```

Pregnancy can still happen before the couple lives together: EA’s pregnancy action only
needs a romance bit. The mod’s own child step only targets young-adult-or-older couples,
so it does not create teen pregnancies, and it does not block other mods that allow them.

Weight changes are global because `STORY_PROGRESSION_PASSES` is global, but EA’s own
candidate selection applies each household’s rule set before seeding an arc, so a
household with Neighborhood Stories off never receives these arcs.

```
houserules.nsr.status          what the last zone load found and changed
houserules.nsr.events          counts of story arcs started/ended
houserules.nsr.events_reset    start the counts again
houserules.nsr.couples         last romances, move-ins and couple children
houserules.nsr.university      last age-up university enrolments
houserules.nsr.graduates       last age-up graduations
houserules.nsr.careers         last age-up career assignments
houserules.nsr.splits          last age-up move-outs
```

## Social Standing

Two sims could become best friends in one conversation. Now it depends on who they are:

- **Compatibility sets the pace.** Shared traits and likes speed friendship up; clashing
  traits and likes (Neat vs. Slob, one sim's like being the other's dislike) slow it down.
  With Lovestruck installed, its attraction score counts too. Family and sims who already
  know each other well are unaffected.
- **Status gaps act like fame.** Wealth (household funds plus home value), celebrity stars,
  and a royal/noble title give each sim a status score. A big gap means friendship and romance
  build much more slowly for the higher-status sim, and the lower-status sim may become
  starstruck. Sims of similar status get no penalty.
- **Romance** uses the same scores on a gentler curve than friendship.

```
houserules.social.status                 show settings
houserules.social.on                     turn the mod on
houserules.social.off                    turn the mod off
houserules.social.strength <0-100>       how strong the effect is (100 = full, 0 = none)
houserules.social.check <other sim id>   scores and multipliers for the selected sim
houserules.social.royal on|off           mark a sim as royalty (for saves with no title system)
```

## Ascent to Royalty

Needs **EP21 Royalty & Legacy**; without it the mod loads but stays inactive. Royal status
becomes a family project: the pack's Noble career still supplies the titles, inheritance and
one-monarch-per-world rule, but a promotion only happens when the dynasty can pay for it.

- **Savings.** Each rank asks for liquid household funds, not the home's value. The numbers
  are sized to a normal lifespan of Noble pay: about §85,000 earned per generation, so the
  crown asks for §250,000 after roughly three generations of steady work.
- **Generations.** The mod counts family-tree depth from the first titled generation. The
  crown expects the third generation; earlier rungs expect one or two.
- **Alliances.** Native dynasty alliances count. The crown asks for four.
- **Milestones.** From Viscount upward, the dynasty needs a living heir and a member who
  reached the top of a non-noble career.
- **Marriage and inheritance skip the grind.** A spouse or child who inherits or claims a
  title reaches that rank without the savings, generation or alliance checks, as the pack
  intends. That includes a promised crown: the gate is on the earned promotion path, because
  refusing a native inheritance inside the hook would leave the pack believing the title
  passed. The pack still decides who may inherit or claim, and keeps one holder per world.
- **The earned crown** also needs the claimant to be the dynasty head and the throne to be
  vacant; the pack's exclusive-level rule enforces the vacancy.

```
houserules.royalty.status              this dynasty, its rank and the next gate
houserules.royalty.check [sim]         what the next promotion needs, and what is missing
houserules.royalty.levels              every native noble level and its gate
houserules.royalty.on / .off
houserules.royalty.set <kind> on|off   enabled, notify, wealth, generation, alliances,
                                       milestones, crown
houserules.royalty.ally <sim id>       form a native dynasty alliance (testing/politics)
houserules.royalty.grant <level>       force a noble level, bypassing the gate (testing)
houserules.royalty.reset               forget this dynasty's recorded progress
```

Progress and settings are saved in `Mods\HouseRules\data\ascent_to_royalty.json`.

## Social Gates

Makes social access mean something, without adding clicks:

- **Houses are private.** Ringing a doorbell only gets you in if someone in the household is
  your friend. Family, household members, and sims with an "always welcome" trait or status
  still get in.
- **Invite over means something.** A sim declines your invite unless you're friends.
- **Clubs only accept sims who fit.** A sim must match at least one of the club's trait
  restrictions, skill restrictions, or the skills its activities train. The club leader is
  exempt, and premade clubs are left alone by default.
- **Club wealth is relative.** The game's fixed `Poor` / `Average` / `Rich` household-value
  brackets become **poorer than**, **similar to**, or **richer than the club leader**. By
  default "similar" means between half and 1.5× the leader's household net worth. The leader
  is the only sim who can edit the club, so the bracket follows whoever leads it.
- **Money never auto-kicks you.** Getting richer can't silently remove a member; membership is
  only re-checked when the club is edited.

Settings are saved in `Mods\HouseRules\data\social_gates.json`.

```
houserules.gates.status                 show settings
houserules.gates.set <setting> on|off   change a setting
houserules.gates.check [sim id]         selected sim's clubs, pass/fail and why
houserules.gates.clubs                  clubs, their criteria and activity skills
houserules.gates.wealth                 effective Poor/Average/Rich ranges per club
```

Settings: `doors`, `invites`, `clubs`, `club_require_restriction`, `club_relative_wealth`,
`club_wealth_band`, `club_activity_skill_min`, `club_enforce_premade`, `club_enforce_on_edit`,
`friend_min_score`.

## Flexible University

Discover University, with the pacing left to you. Needs **Discover University**; without the
pack the mod stays inactive.

- **Leaving early keeps what you earned.** Dropping out no longer wipes the credits or the
  courses you already passed. Enough credits also earns a **Certificate** (one third of the
  degree) or an **Associate Degree** (two thirds), recorded in the mod's data file.
- **Apply for Early Graduation from the phone.** While a sim has enough credits for a
  qualification but not the full degree, the phone gets **Apply for Early Graduation**.
  Confirming leaves university with the qualification, keeps the credits for a later
  enrollment, and skips EA's dropout cooldown. The cheat opens the same dialog.
- **Terms end on Friday evening.** Final grades, the term-end dialog and graduation land at
  19:00 on Friday, so the weekend is free. A term that starts late in the week is stretched
  into the next week instead of ending after two or three days.
- **Fractions add up.** Strong grades earn part of a credit (A-range 0.25, B 0.15, C 0.05) and
  a stretched term earns a little more. Fractions accumulate and become whole credits, so a
  good student sometimes gets a credit the game would not have given.

Thresholds follow the game's own credit requirement. The current game asks for 14 credits,
so Certificate is 5 and Associate is 10; on a 12-credit degree they become the example's 4
and 8. All of it is adjustable in `Mods\HouseRules\data\flexible_university.json`.

```
houserules.flexuni.status [sim id]       credits, qualification, banked fraction, settings
houserules.flexuni.set <setting> <value> change a setting
houserules.flexuni.early_exit [sim id]   the early-graduation dialog
houserules.flexuni.credentials [sim id]  every qualification the sim holds
houserules.flexuni.schedule [sim id]     the Friday plan for a term starting today
```

Settings: `enabled`, `early_exit`, `preserve_credits`, `fractional_credits`,
`friday_schedule`, `friday_end_hour`, `min_term_weekdays`, `certificate_fraction`,
`associate_fraction`, `extension_credit_per_weekday`, `extension_credit_cap`, and the three
`grade_bonus_*` bands.

**Limitations:** qualifications are tracked by the mod rather than as a trait or full degree,
and there is no career-level head start (Hard Mode does accept a Certificate or Associate
Degree for its career skill gates); computers are object tuning, so the phone is the in-game
menu and the cheat is the fallback. A term already in progress when the mod loads
keeps its saved end date. See [PLAN.md](mods/flexible-university/PLAN.md) for why.

## Aspiration Progress

Aspiration goals count **whenever you achieve them**, not only while the matching aspiration
or level is selected. Examples:

- A level-1 *Bestselling Author* who writes a bestseller has that level-3 goal ticked already
  when they get there.
- A *Renaissance Sim* who masters cooking has that *Master Chef* goal done if they switch later.

As soon as every goal of any level is complete — even a future level or a different
aspiration's level — that level pays out its satisfaction points and reward straight away.
The aspiration's reward trait is still only given when the whole aspiration is finished.
Completed goals are remembered when switching aspirations, and child/teen aspirations work too.

```
houserules.asp.status [sim]   levels already done ahead of the sim's position
houserules.asp.on             turn the mod on
houserules.asp.off            turn the mod off
```

## Scenarios

Custom challenges as plain JSON files in `Mods\HouseRules\scenarios\`. You can write your
own or edit the included examples:

- **Rags to Riches** — start with nothing and no job; paint your way to a §50,000 fortune and a
  §100,000 home within 28 days, spending no more than §500 at once.
- **Starving Artist** — §500 to your name; practise painting, join the Painter career, reach
  level 5 and make a good friend within 42 days.
- **Full House** — marry, raise two children, save §20,000 and keep the household afloat for a
  month.
- **Legacy Founder** — one young adult and §1,800 on an empty lot; reach career level 10, own a
  §75,000 home and have an heir within 28 days.
- **The Black Widow** — §2,000 and Charisma 3; marry three different sims and collect §100,000
  within 42 days.
- **Full House: Foster Care** — one adult and seven children; get all seven to grade A and save
  §30,000 within 28 days.
- **Off-the-Grid Survival** — no money and an empty lot; master Gardening and Fishing, then
  build a §35,000 off-grid home within 35 days.

A scenario can set starting conditions (money, traits, skills, careers), define goals with
rewards (skill levels, money, home value, relationships, careers, household size, a day count)
and rules that are actually watched (no career, no money cheats, maximum single purchase) with
warnings or penalties when broken. Goals can depend on earlier goals, which gives chapters
without a separate phase system.

```
houserules.scenario.list              scenario files found
houserules.scenario.validate <name>   check a file, and every trait/skill name in it
houserules.scenario.start <name>      start it for the active household
houserules.scenario.status            goals done/open with numbers, days left
houserules.scenario.check <goal>      tick a custom goal by hand
```

Progress is saved in `Mods\HouseRules\data\scenarios_progress.json`.

### Building scenarios outside the game

There is a local builder for the JSON files, with a form, validation and the menu export:

```
py -3.7 tools/scenario_builder.py
```

It opens `http://127.0.0.1:8765/`. Pick an example or start a new scenario, edit the start,
goals, rules and outcomes, then **Save** (writes `Mods\HouseRules\scenarios\<name>.json`) or
**Export .package**. The export builds tuning for the game's own **Scenarios** screen and copies
the `.package` into `Mods\HouseRules\`. The page also has a raw JSON view for anything the form
does not cover.

The menu export is deliberately partial:

- Only `skill`, `household_money`, `home_value`, `household_size` and `day` goals have a
  matching game goal; `career_level`, `relationship`, `aspiration` and `custom` are reported as
  not exported.
- Rules and `deadline_days` are enforced by the script mod, not by the menu entry.
- Goal rewards of money and traits are exported; reward notifications stay with the script.
- Starting money, traits and skills are exported; `remove_careers` is not.
- `menu.category` and `menu.difficulty` in the JSON (or the two fields on the page) must be EA
  enum names; leave them empty if you only use the cheat-driven script version.

The `.package` path means a menu scenario and the script scenario can coexist: start from the
Scenarios screen or use `houserules.scenario.start`. The script mod's rules and custom goals
still apply once it is running.

## NPC Routines

Hand a sim over to the game while defining *what kind of life* they lead, not just "keep your
needs up":

- Give an NPC-mode sim a weekly schedule — "gym Mon/Wed/Fri at 18:00, paint after work, chess
  on Sunday" — and the mod pushes the right activity at the right time.
- It only steps in at low priority, so hunger, exhaustion or your own commands win. Normal
  autonomy fills the gaps.
- Starter activities: workout, paint, read, chess, jog. Any real interaction name also works
  (`houserules.npc.find <text>` helps you find one).
- Routines cover sims on the loaded lot. You can also give a sim a free-text personality and
  let an optional local LLM choose activities from a fixed list (it never invents actions).
- Give a sim a **goal** (`houserules.npc.goal <text>`) and the LLM decides their hours from
  that goal instead of their routine. It does not run on its own: start it with
  `houserules.npc.start` (`houserules.npc.start all` for the whole household), which asks
  straight away; after that it keeps deciding hourly until `houserules.npc.stop`. If the LLM
  isn't running you get one notification and the sim uses their routine instead of idling.

The AI part is optional and works entirely on your computer through
[Ollama](https://ollama.com) or LM Studio. Without it running, routines still work. Default
address: `http://localhost:11434/api/generate` with model `qwen2.5:3b-instruct`.

### Running the AI brain

1. Double-click `start-llm.cmd` before playing. The first time it installs Ollama and the
   model (about 2 GB), then starts the server; later runs just start it. If Ollama's tray app
   is already running, the server is up and the script only confirms it. The window then
   **follows the brain's log**, so every prompt, answer and (for a thinking model) its
   reasoning appears live while you play. Close it to stop watching; the server keeps running.
2. In game, give the selected sim a goal (and optionally a personality), then start the brain:
   ```
   houserules.npc.goal become a famous painter
   houserules.npc.brain loves art and is a bit of a loner
   houserules.npc.start            (or: houserules.npc.start all)
   ```
3. It asks straight away, then keeps deciding once an hour. `houserules.npc.stop` ends it;
   the goal and description are saved for next time.
4. `houserules.npc.think` shows the last prompt and full answer (the `start-llm.cmd` window
   shows them live). `qwen2.5:3b-instruct` has no hidden chain-of-thought; to see actual
   reasoning, switch to a thinking model (e.g.
   `houserules.npc.llm http://localhost:11434/api/generate qwen3:4b`) and turn on
   `houserules.npc.reasoning on`.

The model only ever picks from the mod's list of activities, and the brain runs in the
background so the game doesn't freeze. If the server can't be reached you get one
notification and the sim falls back to their routine instead of standing idle. The default
`qwen2.5:3b-instruct` is deliberately small so most of your GPU stays with the game; change
it with `houserules.npc.llm <url> <model>`.

```
houserules.routine.edit [sim]                menu: add an activity / show / clear / NPC mode on-off
houserules.npc.on [sim]                      turn routine mode on
houserules.npc.off [sim]                     turn routine mode off
houserules.routine.add <days> <start> <hours> <activity>
                                                e.g. houserules.routine.add mon,wed,fri 18 2 workout
houserules.routine.show [sim]                show the sim's routine
houserules.routine.clear [sim]               clear the sim's routine
houserules.npc.tick                          run the hourly check now
houserules.npc.find <text>                   list real interaction names containing text
houserules.npc.start [name|all]              start the LLM brain (default: selected sim)
houserules.npc.stop [name|all]               stop it again
houserules.npc.goal <text...>                what this sim is working towards
houserules.npc.goal_clear [sim]              forget the goal
houserules.npc.brain <text...> [sim]         what this sim is like / wants (free text)
houserules.npc.brain_show [sim]              show the goal and the description
houserules.npc.brain_clear [sim]             forget the description
houserules.npc.llm <url> <model>             point the mod at your local LLM
houserules.npc.llm_test [sim]                ask the LLM now (applied a few seconds later)
houserules.npc.think [sim]                   show the last prompt and answer (and reasoning)
houserules.npc.reasoning on|off              ask a thinking model for its working too
```

Routines are saved in `Mods\HouseRules\data\npc_routines.json`.

## Conflicts

These mods don't overwrite EA files, but they do hook interactions, so:

- Two mods that replace the same interaction can't both apply. Most likely overlaps: doorbells
  and invite-over (Social Gates), job picking (Hard Mode), selling and prices (Hard Mode), and
  aspiration goal tracking (Aspiration Progress).
- Hard Mode changes shop and stall markups; a mod that changes pricing will fight it.
- Neighborhood Stories Rebalance changes the story-arc weights in memory. A mod that replaces
  EA's story progression entirely won't be affected, and won't be affected *by* it either.
- Social Standing and Hard Mode both touch relationship speed, by design: Hard Mode makes all
  relationships fade faster, Social Standing slows how fast they build between badly matched
  sims. They don't need each other and can be used alone.
- Flexible University hooks the university degree tracker (`complete_term`, the end-of-term
  alarm, dropout and graduation). A mod that replaces or hooks those methods will fight it;
  it doesn't change the credit requirement or the course list.
- Ascent to Royalty hooks the pack's `NobleCareer._promote`, so a mod that replaces the Noble
  career outright will bypass it. It does not change the career's levels, pay or interactions,
  and it leaves the pack's own title inheritance alone; the gate applies to earned promotions.

If a mod doesn't seem to do anything, check its log in `Mods\HouseRules\logs\` first —
they name what was found and what was skipped.

## License and reuse

These mods are shared for the community to use:

- **Download and play for free.** Anyone is welcome to download the mods and use them in
  their own game, and to include them in their mods folder or share links to this page.
- **Changes and add-ons are welcome with credit.** You can edit, extend or build on these
  mods for personal use or to publish your own version, as long as you credit this project
  (a link to this repo) and say what you changed.
- **No wholesale copying.** Please don't re-upload the mods unchanged, or copy them into
  your own project, and present them as your own work — including uploads to mod
  sites (I'll add to them once tested further). If in doubt, ask first.

Back up your saves and use at your own risk, as with any script mod.

