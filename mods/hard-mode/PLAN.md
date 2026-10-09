# Hard Mode

**Status:** planning · **Type:** tuning plus script (settings, debt) · **Size:** medium; modular, each part can ship separately

## Goal

Make the game *harder, not grindier*: things you can do now get **gated behind requirements**, and choices have consequences. No extra clicking, no slower bars.

Each part can be switched on or off (Challenge-Junkie does this through the mailbox, and it works well), so players can pick their own difficulty.

## What players say is too easy → what we change

### 1. Careers (first priority; closest to the original idea)
- **Entry requirements:** professional careers (Doctor, Lawyer, Scientist, Engineer, Education, Politician, Business…) need a relevant degree to join, or start the sim at level 1 with a cap partway up (e.g. level 5) until they have a degree. This works with the Discover University degrees and the "Three Year Degrees + Master's" mod.
- **Gates partway up:** e.g. Astronaut level 5+ needs Rocket Science 6 *and* Fitness 5. Top levels need a degree with good grades, a master's degree, or X sim-weeks in the career.
- **Slower promotions** at the top levels only. Early levels stay quick, so that's not a grind.
- **Getting fired:** a few missed days or a very bad performance gets the sim fired, and other employers take that into account for a while.

### 2. Money
- Smaller starting funds (setting: 20k / 10k / 5k / 0).
- Bills that scale more realistically with the household's size and the home's value. A rent-like housing cost for households without their own home.
- Passive income gets diminishing returns: book royalties, paintings and crystal sales are worth less when you sell lots of them in a short time.
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
3. Money: starting funds, bills, debt.
4. Skill aptitude.
5. Life and relationships.

## Discovery tasks (after decompiling and extracting tuning)
- Career tuning: where the tests for joining a career and getting a promotion live (`careers/` in the scripts, `Career` / `CareerLevel` tuning instances).
- How Discover University stores degrees and grades on a sim (degree tracker), so we can test for them.
- The bills module (`sims/bills.py` or similar): how the amounts are calculated, and whether the multipliers are tuning or code.
- How a skill's gain rate is put together (statistic modifiers, how traits change it).

## Open questions
- Should this be one mod with modules, or a few separate mods ("Hard Mode: Careers", "Hard Mode: Money")? Separate is easier to test and publish. One is easier for a single settings menu. Possible compromise: one script core, plus separate tuning packages.
- How does it behave on existing saves where sims already have careers that wouldn't meet the new requirements? Probably grandfather them in.
