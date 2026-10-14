# Scenarios

**Status:** phase 1 (files and goals) built 2026-10-14, to test (TESTING.md section 6); rules (phase 2) are read but not enforced. Choices made while building: relationship goals use score thresholds (friend 30, good friend 60, best friend 90, partner 50 romance, married = has a spouse) rather than the game's bits; rewards are money, a trait and a notification (moodlets and satisfaction points later); start conditions don't join careers yet; `who` is active/any/all (roles later); collection goals later · **Type:** script (phase 3 adds a build tool that makes tuning) · **Size:** medium to large

## Goal

Create your own scenarios as a text file, then start one in the game with a cheat (Amber,
2026-10-09: "Create your own scenarios. Load from a file with a command maybe?"). A scenario has:

- **Starting conditions,** applied when it starts: money, traits, skills, careers, relationships.
- **Goals with rewards,** checked automatically while you play.
- **Rules** that hold while it runs ("no job", "no money cheats", "never spend more than §500
  at once"), with a warning or penalty when broken.

Later: an in-game builder, and an export so a scenario also appears in the game's own
Scenarios menu (decided 2026-10-09: "both, menu later"; "text file now, builder later").

## What exists already (checked 2026-10-09)

- **The game's own Scenarios** (base game, 2023; code in `ea_scripts/simulation/gameplay_scenarios/`).
  Each one is tuning: a `Scenario` snippet with roles, phases (`scenario_phase.py`), goals
  (the game's situation goals), outcomes and loot. A custom one has to be a `.package` made in
  Sims 4 Studio, and modders say that's fiddly, so few exist
  ([SimsCommunity](https://simscommunity.info/2021/11/05/modders-are-already-creating-custom-scenarios-for-the-sims-4/),
  [MustHaveMods list](https://musthavemods.com/sims-4-custom-scenarios/)). Goals are limited to
  the situation-goal types EA ships.
- **[Challenge Tracker](https://simscommunity.info/2026/04/23/the-sims-4-challenge-tracker-mod/)
  (SimMattically, 2026):** a checklist in the game's UI, with chapters, made with a website
  ("Challenge Creator"). But **you tick goals off yourself** (right-click). Its rules are text
  only, nothing is enforced, and nothing is set up for you. It's in paid early access on Patreon.

**What this mod adds that neither has:** goals that check themselves; starting conditions
that are applied for you; rules that are actually watched; scenarios as plain text files
that are easy to write, change and share; and it's free. If Challenge Tracker ever adds
automatic goals, look at this plan again.

## The scenario file

One file per scenario in `Mods/BlueRabbit477/scenarios/<name>.json`, so they can be
added or edited without rebuilding the mod. Example:

```json
{
  "name": "Rags to Riches",
  "description": "Start with nothing. Build a life without a day job.",
  "applies_to": "household",
  "start": {
    "money": 0,
    "traits": {"all": ["trait_Ambitious"]},
    "skills": {"active": {"Painting": 2}},
    "remove_careers": true
  },
  "rules": [
    {"type": "no_career", "penalty": {"type": "warning"}},
    {"type": "no_cheats", "penalty": {"type": "fail"}},
    {"type": "max_purchase", "amount": 500, "penalty": {"type": "money", "amount": -200}}
  ],
  "goals": [
    {"id": "art", "type": "skill", "skill": "Painting", "level": 6, "who": "any",
     "reward": {"money": 1000}},
    {"id": "rich", "type": "household_money", "amount": 50000,
     "reward": {"trait": "trait_Frugal"}},
    {"id": "home", "type": "home_value", "amount": 100000, "requires": ["rich"]}
  ],
  "deadline_days": 28,
  "win": "all_goals",
  "outcomes": {
    "win": {"notification": "From nothing to a fortune!", "money": 10000},
    "lose": {"notification": "Time's up. Maybe next generation."}
  }
}
```

- **who:** `active` (the sim selected when it starts), `any`/`all` household members, or a
  role name from `"roles": {"heir": "oldest_child"}` (later: by trait, by age).
- **requires:** a goal stays hidden until these goals are done. That gives chapters without a
  separate phases concept (EA's scenarios have phases; this covers most of what they're for).
- Names are the game's tuning names (`trait_Ambitious`, skills by the end of their name, as in
  Hard Mode). `bluerabbit477.scenario.validate <name>` lists anything the game doesn't recognise
  before you start.
- A file that doesn't parse, or has an unknown type, is refused with the line and reason, never
  half-started.

## Building blocks (first set)

**Starting conditions:** money (set or add), traits (add/remove), skills (set level), career
(join at level, or remove all), relationships between household members (friends, spouses,
enemies), age (later), move to lot (later).

**Goals** (all checked automatically):

| Type | Checks | How (game side) |
|---|---|---|
| `skill` | a sim reaches skill level N | skill level events, or poll the skill |
| `household_money` / `home_value` / `net_worth` | money or value at least N | `household.funds.money`, `household_net_worth()` |
| `career_level` | in career X at level N (any career if X empty) | career tracker |
| `relationship` | friend / best friend / partner / married with anyone (or a role) | relationship bits |
| `aspiration` | a whole aspiration (or one level) done | aspiration tracker |
| `household_size` | N members, or N children | household |
| `day` | survive until day N | sim clock |
| `collection` | N items of a collection | collection tracker |
| `custom` | ticked by hand with `scenario.check <goal>`, for anything we can't detect | none |

**Rules** (checked when it happens, or each sim hour):

| Type | Detects | Hook |
|---|---|---|
| `no_career` | joining a full-time career | the `careers.select` wrap Hard Mode already has |
| `no_cheats` | money or skill cheats | the game's own "has cheated" flag on the household (`_has_cheated` in `household.pyc`) |
| `max_purchase` | one Build/Buy purchase above §N | funds removed with a purchase reason |
| `max_money` | holding more than §N | hourly check |
| `no_leaving_lot` | travel | zone change |

**Penalties:** `warning` (a notification), `money` (fine), `moodlet` (a game buff by name),
`fail` (ends the scenario as lost).

**Rewards:** money, trait, moodlet (buff by tuning name), satisfaction points, a notification.

## How it works in the game

- `scenario_logic.py` (pure, tested): loading and validating the file, goal ordering
  (`requires`), deciding win/lose, rule decisions. The same file format is used by the
  later build tool, so the format is defined once.
- `scenario_main.py` (game layer): cheats, applying starting conditions, an hourly check
  plus event hooks for goals and rules, notifications.
- **Progress is saved per household** in `Mods/BlueRabbit477/data/scenarios_progress.json`
  (scenario name, start day, done goals, broken rules). It's per computer, not inside the
  save file. Saves of the same household from different points in time can disagree; see the open questions.
- Hard Mode, Social Standing and Aspiration Progress keep working alongside; Hard Mode's
  starting funds are skipped when a scenario sets its own money.

**Cheats:**
- `bluerabbit477.scenario.list`: scenario files found.
- `bluerabbit477.scenario.validate <name>`: check a file without starting it.
- `bluerabbit477.scenario.start <name>`: for the active household.
- `bluerabbit477.scenario.status`: goals done/open (with numbers, e.g. Painting 4/6), rules,
  days left.
- `bluerabbit477.scenario.check <goal>`: tick a `custom` goal.
- `bluerabbit477.scenario.quit`

## Phases

1. **Files and goals:** file format, validation, start/status/quit, starting conditions,
   goal types, rewards, win/lose. Comes with 2–3 example scenarios.
2. **Rules and penalties.**
3. **Export to the game's Scenarios menu:** a build tool turns a scenario file into
   `Scenario`/phase/goal tuning in a `.package`. Only goals that have a matching
   situation-goal type can be exported; others make the tool explain why. Needs research
   into `gameplay_scenarios/` and how Sims 4 Studio-made custom scenarios are built.
4. **In-game builder:** picker dialogs (like `routine.edit`) to make or edit a scenario, saved
   as a file.

## Open questions

- **Save files:** progress is kept in our data folder per household. If you load an older
  save of the same household, progress may be ahead of the save. Is that acceptable, or should
  progress be stored on the household inside the save (harder, phase 1.5)?
- **Generations:** should a scenario carry over to the heir when the main sim dies, e.g. a
  "role: heir" that moves to the oldest child? (Legacy-challenge style.)
- **Sharing:** just send the .json file, or also publish example scenarios with the mod?
- **Overlap with Challenge Tracker:** if you use it, should we be able to read its
  challenges? Its format isn't public yet.
