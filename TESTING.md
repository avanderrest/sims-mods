# Manual testing steps

Only steps still to do are listed; finished steps are removed as we go. The **handy commands**
at the top of each section stay: they're for checking state any time. The logs record
everything, so you don't need to copy outputs. Just tell Claude to check the logs.

## Before you start

- Everything is installed (rebuilt 2026-10-14 after the 13 Oct test session: picker crash fixed,
  Pay Off Debt on the phone, any degree unlocks careers, new Scenarios mod). One game start covers
  all the steps below.
- New files in `Mods\HouseRules\`: `HouseRules_hard-mode.package` (the phone entry),
  `HouseRules_scenarios.ts4script`, and a `scenarios\` folder with three example scenarios.
- **Before launching the game:** double-click `start-llm.cmd` in the repo folder (for section 1,
  step 5). Wait for "Ready: ollama with qwen2.5:3b-instruct"; it's quick now that Ollama is installed.
- If the game is already open, **restart it**: mods only load at game start.
- Test in a **new save** (or a copy), not your main game. Section 2's starting-funds check
  needs a brand-new household anyway.
- **To remove everything:** delete the `Mods\HouseRules` folder.
- **Logs:** `Mods\HouseRules\logs\`, plus `lastException*.txt` in `Documents\Electronic Arts\The Sims 4\`.
- Cheats go in the cheat console (Ctrl+Shift+C).

## 0. Self-test (run this first)

Load a save in **play mode with a sim selected**, then:

- `houserules.test`: runs every suite and prints one line per check.
  ✅ A summary like "Self-test: N passed, 0 failed, M skipped". Any `[FAIL]` line says what
  went wrong; the same lines are in `Mods\HouseRules\logs\self-test.log` and the last run
  is in `data\self_test_last.json`, so just tell Claude to check them.
- `houserules.test.list`: the suites; `houserules.test hardmode` (or `actions`, `npc`, `gates`,
  `social`, `royalty`, `aspiration`, `scenarios`, `nsr`, `env`, `hello`) runs one.
  ✅ A `[SKIP]` is an honest "not applicable here" (no clubs in this save, the local LLM isn't
  running). It is not a failure.
- `houserules.test actions`: the end-to-end checks. They send the game's own commands and
  check the result, e.g. `careers.select` (what the Find a Job screen sends) for a job the
  selected sim isn't qualified for - Hard Mode must refuse it and leave the sim's career
  list unchanged; with `enforce` off the same pick must join. Also: a real inventory item's
  sell price drops with Hard Mode's `selling` on; `houserules.npc.tick` runs; the noble
  `promote()` the game calls is refused by Ascent to Royalty (this one needs a sim who is
  already in the Noble career — join it in game through a throne, the noble book, or a title;
  it is not added for the test); `clubs.add_sim_to_club_by_id`
  is refused by Social Gates; a forced unpaid bill becomes Hard Mode debt; a real job breaks
  a temporary scenario's `no_career` rule; a real friendship gain uses Social Standing's
  multiplier.
  ✅ All PASS; a `[SKIP]` means the save has no suitable sim/career/club/bill/relationship
  for that move.

The suite is safe for a save you don't mind changing: its few actions (market sale, debt,
routine entry, royal flag, a temporary job join/quit) are restored in the same run. Steps
that need a person - menus, phone entries, doorbells, watching a notification arrive - are
still in the sections below.

## 1. NPC Routines

Handy commands:
- `houserules.npc.tick`: runs the hourly check now and reports the day and hour (`day=1 (mon)`).
- `houserules.npc.brain_show`: what the LLM has been told about the selected sim.
- `py tools/llm.py status` (outside the game, in the repo folder): is the LLM running, and does it have a model? Any pulled chat model will do; the one in `llm.json` is only a preference.

1. `houserules.routine.edit` (with a sim selected): a menu opens. (On 13 Oct this crashed before
   the menu showed; fixed 2026-10-14.) Add an activity: Paint, pick two days, a start time, 2 hours.
   ✅ Each step is a list to pick from, and a notification confirms it. "Show the routine" lists it.
2. With NPC mode on and an activity due this hour, cancel it and play 1–2 in-game hours at normal speed.
   ✅ The sim goes back to it **on their own** at the next in-game hour.
3. Let the sim get hungry while NPC mode is on.
   ✅ They eat first, then go back. The routine doesn't override urgent needs.
4. Off the lot: give a household member a routine for now (`houserules.routine.add <today> <this hour> 2 workout <sim id>`
   and NPC mode on for them), then travel with someone else and leave them at home. Play an hour.
   ✅ Their Fitness goes up a little (the log says "off the lot -> Fitness +… points").
5. The local LLM (Ollama was installed on 2026-10-14). **Before starting the game**, double-click
   `start-llm.cmd` in the repo folder.
   ✅ It ends with "Ready: ollama with qwen2.5:3b-instruct". Then in the game:
   `houserules.npc.goal become a famous painter`, `houserules.npc.brain loves art and is a bit of a loner`,
   then `houserules.npc.start` (or `houserules.npc.start all`).
   ✅ The sim starts an activity within a few seconds and a notification gives the model's
   reason. It keeps deciding hourly; `houserules.npc.stop` ends it. With Ollama off you get a
   "Local LLM not running" notification and the sim falls back to their routine.
6. Clean up: "Turn NPC mode off" and "Clear the routine" in `houserules.routine.edit`.

Result:

## 2. Hard Mode

Handy commands:
- `houserules.hard.status`: every part with its on/off setting; `houserules.hard.set <part> off` switches one off straight away.
- `houserules.hard.money.status`: markup table, this household's market and debt.
- `houserules.hard.skills`: the sim's talents, trait affinities and skill gain factors (worked 13 Oct).
- `houserules.hard.check <career>`: what the career gate decides for the selected sim, and why.
- `houserules.hard.money.bill_to_debt`: turns an unpaid bill into debt now (worked 13 Oct).

1. **Starting funds:** make a new household and move in.
   ✅ A notification says they start with §… less (the setting is 10,000 instead of 20,000).
2. **Selling:** look at the sell price of something you made or caught (painting, fish, harvest, crystal)
   in the inventory. `houserules.hard.set selling off`, look again, then `... selling on`.
   ✅ With it on, the price is about half.
3. Sell several things of the same kind, then `houserules.hard.money.status`.
   ✅ That kind's price factor has dropped below 1.
4. **Markups** (if you have Get to Work, Business & Hobbies or the food stand): set a high markup and sell something.
   ✅ `houserules.hard.money.status` shows the markup table; the log has a line per stand sale.
5. **Debt repayments:** with debt (an unpaid bill + `bill_to_debt`), play past the next morning.
   ✅ `houserules.hard.money.status` shows it smaller (some is repaid each day).
6. **Paying debt off from the phone:** with debt, open the sim's phone.
   ✅ A **Pay Off Debt** entry (gone again once there's no debt). It opens a list of amounts
   (§100, §500, … and "all of it" if you can afford it); picking one shows "Debt paid" and
   `hard.money.status` shows the lower debt.
   ❌ No entry on the phone: try `houserules.hard.money.pay_debt` (same picker) and tell Claude:
   the log says whether the phone tuning loaded.
7. **Life:** open the reward store (satisfaction points).
   ✅ Prices are 1.5× the usual (e.g. a 1000 trait costs 1500).
8. Optional: a sim with **any** finished degree (e.g. Drama) can join Doctor, Astronaut, etc. with no
   skills (changed 2026-10-14: any degree unlocks all careers).
   ✅ `houserules.hard.check doctor` says "a finished degree waives the skill gate".
9. Optional, takes 3 sim days: skip work with a sim who has a job.
   ✅ After 2 missed days a warning, after 3 they're fired, and Find a Job refuses them for 3 days.

Result:

## 3. Social Standing

Handy commands:
- `houserules.social.check`: sims the selected sim knows, with their ids; `houserules.social.check <id>` for one of them.

1. Have the selected sim meet someone new and chat for a while.
   ✅ Friendship grows noticeably slower than usual, unless they're very compatible.
2. `houserules.social.check <id>` for that sim.
   ✅ Shows both sims' status (wealth, fame, title), compatibility and the friendship/romance factors.
3. `houserules.social.royal on <id>` for the other sim, then check again.
   ✅ Their status jumps and the factors drop. With Get Famous, the lower sim gets the "near a celebrity" moodlet
   while they chat.
4. `houserules.social.royal off <id>` to undo.

Result:

## 4. Aspiration Progress

Handy commands:
- `houserules.asp.status`: the selected aspiration, the level being worked on, and levels done per aspiration (worked 13 Oct).

1. Hover your aspiration and pick a goal from a **later** level, then do it (skill goals are easiest:
   `stats.set_skill_level Major_Fitness 6`, for example).
   ✅ That goal is ticked straight away with its points; once all goals of that level are done, its reward comes
   at once, but the panel stays on your current level.
2. Finish your current level.
   ✅ It skips any level you already completed.
3. Switch to another aspiration whose goals you've already done some of.
   ✅ Those are already ticked or the levels already done. The aspiration's trait only comes when every level is done.

Result:

## 5. Neighborhood Stories Rebalance

Handy commands:
- `houserules.nsr.events`: what story progression has done so far, counted by kind.
- `houserules.nsr.events_reset`: start counting from zero (e.g. a new save).
- `houserules.nsr.university`: the last age-up university enrolments (or "none yet").
- `houserules.nsr.graduates`: the last age-up graduations (or "none yet").
- `houserules.nsr.careers`: the last age-up career assignments (or "none yet").
- `houserules.nsr.splits`: the last age-up move-outs (or "none yet").
- `houserules.nsr.couples`: the last new romances and move-ins together (or "none yet").

The story weights are applied in game; only child adoption is scaled down now. Move-out,
move-in, careers and horse weights are left at default and handled by the logic above.

1. **Play for at least 2–3 sim weeks** (speed 3 is fine), with unplayed households in the world.
   Counts are saved as you go and keep adding up across sessions.
2. Afterwards: `houserules.nsr.events`, or just ask Claude to check the logs.
3. **Age-up university:** let a teen in a **Neighborhood Stories** household age up to
   young adult, ideally in a wealthy family and then in a poor one.
   ✅ `houserules.nsr.university` lists the sim, university and major, and the log says
   `age-up university: <name> enrolled in <university> / <major> (net worth §…, chance …, roll …, moved into halls|stayed home)`.
   ✅ A wealthy household should enrol much more often than a poor one (10% to 75%).
   ✅ If a hall/building has room, the sim should appear in that university lot, not the
   family home.
   ✅ A student should **not** also appear in `houserules.nsr.careers` or
   `houserules.nsr.splits` for that age-up.
4. **Age-up graduation:** with a student still enrolled and living in a hall/building,
   let them age from young adult to adult in the Neighborhood Stories household.
   ✅ `houserules.nsr.graduates` lists them, the log says
   `age-up graduation: <name> graduated ... with GPA ...`, and the sim has the degree trait.
   ✅ They move out of the hall: back to the family home if there is room, otherwise into
   a new household with no home.
5. **Age-up careers:** let a teen in a **Neighborhood Stories** household age up to young
   adult (or an adult sim age up in that household). The household must have Neighborhood
   Stories careers enabled and the sim must not be a student.
   ✅ `houserules.nsr.careers` lists a career, and the log line says
   `age-up career: <name> -> <career> (full-time|part-time, chance 73%/95%, roll …, part-time roll …)`.
   ✅ A failed roll is not a failure: the log says `no career this time` with the roll.
   ✅ Roughly 35% of young-adult jobs and 20% of adult jobs should be part-time.
   ❌ Nothing in the log at all: the age-up happened in the active household (skipped),
   the household has Neighborhood Stories careers off (log says so), the sim is a
   university student, or the sim already has a full-time career.
   The career should fit the sim: a level-10 Painter skill or Creative/Art Lover traits
   should make Painter much more likely than a career with no matching skill or trait.
6. **Age-up move-out:** let a teen in a **Neighborhood Stories** household with more than
   one member age up to young adult, with Neighborhood Stories move-outs enabled.
   ✅ `houserules.nsr.splits` lists the sim, and the log says
   `age-up move-out: <name> split into a new homeless household (chance 50%, roll …)`.
   ✅ After some time, that new household may get a home through EA's MoveIn.
   ✅ A failed roll is not a failure: the log says `staying home` with the roll.
   ✅ An **adult** age-up must never appear in this list, even if other adults live there.
   ✅ EA's own whole-household move-out should only happen for a **single adult with no
   children or partner**; families and couples should never be moved out by it.
7. **Horse adoption:** with Horse Ranch and Neighborhood Stories on, play until the
   Horse Adoption pass runs for a Neighborhood Stories household.
   ✅ A homestead on a small or poorly funded lot never gets a horse; the log says
   `horse adoption blocked ... lot WxH (N tiles), funds §...`.
   ✅ A 50×40-or-larger lot with §50,000+ only passes on the 5% roll.
   ✅ A blocked horse should not stop the household getting a cat or dog later.
8. **Romance and moving in:** with several unplayed Neighborhood Stories households, let
   sims meet and build relationships for a few sim days (speed 3). Compatible sims should
   sometimes become **Significant Others**.
   ✅ `houserules.nsr.couples` lists new romances, and the log says
   `daily romance: <name> + <name> (GOOD|AMAZING, TEEN|YOUNGADULT|ADULT|ELDER, chance …)`.
   ✅ Teen romances should be rarer than young-adult ones (40% of the chance).
   ✅ Once a couple has a romance bit, a pregnancy, or a child together, they may move in
   together; the log says `daily move-in: <name> moved in with <name> (romance|pregnant|child, chance …)`.
   ✅ Teen couples must not move in together or start a pregnancy; the mod only seeds
   EA's pregnancy arc for young-adult-or-older couples.
   ✅ A sim with their own children in the household should not be moved away from them.
   ✅ A same-sex couple with the adoption rule and a free slot may start an adoption; an
   opposite-sex couple may start a pregnancy or, more rarely, an adoption. The log says
   `daily child: <name> + <name> -> <arc> (adoption|pregnancy, chance …)`.
9. **Friendship changes:** let unplayed sims interact for several sim days.
   ✅ Most changes should be ordinary friendship gains or losses, not instant best
   friends/despised.
   ✅ The log shows `relationship arc blocked ...: best friends from friendship N` or
   `despised from friendship N` when the pair is not already close/hostile.
   ✅ Romance Start should be blocked unless the pair is GOOD or AMAZING compatible.

Result:

## 6. Scenarios (phase 1: files and goals; phase 2: rules)

Scenario files are in `Mods\HouseRules\scenarios\` (the three examples are rewritten by each
build, so copy one to a new name before editing it). Rules are enforced now: each one breaks once
per scenario, then stays broken in the progress file.

Handy commands:
- `houserules.scenario.list`: scenario files found.
- `houserules.scenario.validate <name>`: checks a file, and any trait/skill names the game doesn't have.
- `houserules.scenario.status`: goals done / open (with numbers, e.g. `4/6`) / locked, the day,
  and every rule as `[ok]` or `[broken]` with its penalty.

1. `houserules.scenario.list`, then `houserules.scenario.validate rags_to_riches`.
   ✅ Lists `full_house, rags_to_riches, starving_artist`; validate says "valid, 3 goals" with no
   notes and no unknown traits or skills.
2. Break a copy on purpose (e.g. delete a `"` in it) and validate that.
   ✅ "NOT valid" with the reason; it can't be started either.
3. With a sim selected (one with a job, ideally): `houserules.scenario.start rags_to_riches`.
   ✅ A notification lists the goals and the 28 days. The household's money is §0, the sim is Ambitious,
   has Painting 2 and no job. `scenario.status` shows `[ok] rule no job` and
   `[ok] rule spend at most §500 in one Build/Buy visit (penalty: fine of §200)`.
4. `stats.set_skill_level Major_Painting 6`, then `houserules.scenario.status` (or wait an in-game hour).
   ✅ "Goal done: art" with a §1000 reward; status shows `[x] art`, `[ ] rich - 1000/50000`, `[locked] home`.
5. `money 60000`, then `houserules.scenario.status`.
   ✅ "rich" is done and a notification says the new goal is "home"; status shows its value against 100000.
6. `houserules.scenario.quit`, then `houserules.scenario.start full_house`, then
   `houserules.scenario.check holiday`.
   ✅ The custom goal is ticked. `scenario.check married` refuses (it's not a custom goal).
7. **Warning rule:** with `rags_to_riches` running, have the sim take any job (phone or computer).
   ✅ Notification "Rule broken: no job. Penalty: a warning."; status shows `[broken] rule no job`,
   and it doesn't fire again an hour later.
8. **Fail rule:** copy `rags_to_riches` to `rules_test.json` and replace its `rules` with
   `[{"type": "no_cheats", "penalty": {"type": "fail"}}]`. Quit, start `rules_test`, then `money 1000`.
   ✅ "Rule broken: no money or skill cheats... the scenario is lost", then the file's lose outcome.
   If nothing happens, the household's "has cheated" flag didn't get set by `money`; try
   `stats.set_skill_level Major_Painting 3` and check the log.
9. **Build/Buy rule:** start `rags_to_riches`, `money 5000`, enter Build/Buy and buy more than §500
   of furniture in one visit, then exit.
   ✅ Notification and a §200 fine; status shows `[broken]` for the max-purchase rule.
10. **Leaving the lot:** make a copy with only
    `[{"type": "no_leaving_lot", "penalty": {"type": "warning"}}]`, start it, and travel anywhere.
    ✅ On arrival, "Rule broken: stay on the home lot"; status shows it broken.
11. Optional, takes 28 sim days: let a scenario run out.
    ✅ "Scenario lost: time's up" and the file's lose message.

Result:

## 7. Social Gates (new)

Built 2026-10-26. Everything is a script; there's no package/tuning for it, so a rebuild is enough.
Rules and the hook list are in `mods/social-gates/PLAN.md`.

Handy commands:
- `houserules.gates.status`: every setting and what it's set to.
- `houserules.gates.set <setting> on|off|number`: change one straight away.
- `houserules.gates.check [id]`: the selected Sim's clubs, and whether they pass each one.
- `houserules.gates.clubs`: every club's restrictions and how many activity skills were found.
- `houserules.gates.wealth`: the effective Poor/Average/Rich ranges around each club leader.
- `houserules.gates.invite <id>`: friendship score between the selected Sim and another.

1. **Doorbell:** visit an NPC household with an **acquaintance**. Knock/ring the doorbell.
   ✅ The game's "bad relationship" notification appears and you're not let in. Become friends
   (`relationships.add_score` or chat until the bar says Friend), then ring again → let in.
   A resident's family member and an "Always Welcome" Sim still get in.
2. **Invite over:** as an acquaintance, invite that Sim over.
   ✅ A notification says they aren't a close enough friend; they don't arrive. Invite a friend → normal.
   `houserules.gates.invite <their id>` shows the score and whether they count.
3. **Club admission:** make a club with a skill activity (e.g. Paint) and **no** membership criteria.
   Add a Sim with no relevant skill.
   ✅ Refused (log line `club: ... not admitted`, no notification). Add a Sim with Painting 1+
   → accepted. A Sim with a trait the club restricts should also be accepted.
   `houserules.gates.check <id>` shows the reason; `gates.clubs` shows the activity-skill count.
4. **Relative wealth:** player club with an **Average** household-value restriction and the leader on §20k.
   ✅ `gates.wealth` says "Poorer than the leader: under §10k; Similar: §10k-§30k; Richer: over §30k".
   The leader is the only sim who can edit the club, so the range follows them.
   A §15k Sim can be added; a §100k Sim is refused.
   Give an existing member §100k: they stay a member (no auto-kick).
   Edit the club (change its name, confirm): they're re-checked and removed, with a notification/log line.
5. **Reload:** save, reload, and check the member from step 4.
   ✅ Still a member (existing members are grandfathered on load).
6. **Game clubs:** with `club_enforce_premade` off (default), the premade clubs keep their members.
   Turn it on only if you want the same rules there.

Result:

## 8. Flexible University (new)

Built 2026-10-26. Needs **Discover University**. Rebuild with
`py -3.7 tools/build.py flexible-university`; it installs both
`HouseRules_flexible-university.ts4script` and `.package`, so restart the game.
The design and the known limitations are in `mods/flexible-university/PLAN.md`.

Handy commands:
- `houserules.flexuni.status [id]`: credits, qualification, banked fraction and settings.
- `houserules.flexuni.schedule [id]`: the Friday plan and the current term's end day/time.
- `houserules.flexuni.early_exit [id]`: the same confirmation dialog as the phone entry.
- `houserules.flexuni.credentials [id]`: every qualification the sim holds.
- `houserules.flexuni.set <setting> on|off|number`: change one setting.

1. **Load and log:** load a save with a university student and select them. Run
   `houserules.flexuni.status`.
   ✅ It prints the settings, `X of 14 credits` (or the game's own requirement), a tier, and
   the banked fraction. `Mods\HouseRules\logs\flexible-university.log` says
   `loaded (university discovered: True)`.
2. **Friday term end:** enroll a sim in a term starting on a **Tuesday or Wednesday** (or
   start a term and set the day with a mod/cheat). Run `houserules.flexuni.schedule`.
   ✅ The current term's end day is **5** and the time is `19:00` by default, with more days
   than EA's 5-day term. The log has a `term plan for ...` line naming the extra weekdays.
3. **Mid-term load:** save during that term, reload, and run `schedule` again.
   ✅ The remaining time is the same as before the reload (the mod passes EA's saved end
   time through instead of recomputing it).
4. **Fractional credits:** finish a term with good grades (A/B). Before the grades appear,
   the log should show `bonuses [...] -> N whole credit(s)`. The term-end dialog's credit
   count includes the bonus, and if it reaches the requirement, the normal graduation runs.
   ✅ `status` shows the leftover fraction (e.g. `banked fraction 0.35`), and a notification
   says `1 extra credit...`.
5. **Early graduation (phone):** give a student enough credits for a Certificate but not the
   full degree (`status` shows the tier). Open the Sim's phone.
   ✅ **Apply for Early Graduation** is in the phone menu. It is absent when they have too few
   credits, have the full requirement, or are not enrolled.
   Click it → the confirmation dialog names the qualification and says the credits are kept.
   Cancel → nothing changes. Repeat and OK.
   ✅ A notification says `Certificate in <major> with X of Y credits`; the Sim is no longer
   enrolled; `credentials` lists the certificate; `status` still shows the kept credits; there
   is **no** EA dropout notification and no dropout cooldown. Enroll again and check that the
   status starts from the kept credits, not 0.
6. **Plain dropout keeps credits:** earn at least one credit, then use EA's **Drop Out**.
   ✅ EA's dropout notification still appears, but `status` afterwards shows the credits and
   `credentials` shows a Certificate if the credit count reached one third. Re-enroll and
   confirm the credits are still there. (The dropout cooldown is EA's own; this is the one
   path that keeps it.)
7. **Full graduation:** finish all credits normally.
   ✅ `credentials` now shows `Degree in <major>` (replacing a weaker record for that major),
   and the banked fraction is 0.
8. **Settings:** `houserules.flexuni.set friday_schedule off`, enroll a new term, and run
   `schedule`.
   ✅ The term ends on the day EA planned (not necessarily Friday). Turn it back on.
   `set early_exit off` hides the phone entry; `set enabled off` restores EA behaviour.
9. **No pack:** if Discover University is not installed, the log says
   `Discover University is not installed; Flexible University is inactive` and every command
   reports no degree tracker. Nothing else changes.

Result:

## 9. Ascent to Royalty (new)

Built 2026-10-26. Needs **EP21 Royalty & Legacy**; without it the self-test suite says
`[SKIP]` and the mod's log says it is inactive. No package or tuning file: a rebuild is enough.
Rules are in `mods/ascent-to-royalty/PLAN.md`.

Handy commands:
- `houserules.royalty.status`: this dynasty's key, generation, savings, alliances, milestones,
  the current noble level and the next gate.
- `houserules.royalty.check [sim id]`: same report for another Sim, or the selected one.
- `houserules.royalty.levels`: the native noble ladder, with savings/generation/alliance and
  milestone requirements for every rung.
- `houserules.royalty.set <kind> on|off`: `enabled`, `notify`, `wealth`, `generation`,
  `alliances`, `milestones`, `crown`.
- `houserules.royalty.reset`: forget the recorded generation, milestones and promotions for
  this dynasty (use it to repeat a test).

1. Select a Sim in the Noble career (or knight one). `houserules.royalty.status`.
   ✅ It names the dynasty, generation 1, current savings, alliances and milestones, and says
   what the next level is missing. `houserules.royalty.levels` matches the pack's ten titles.
2. Make a normal promotion attempt (coronation duty, high performance, or the game's own
   auto-promotion) with a low balance and no alliance.
   ✅ No promotion dialog appears; a notification names the missing savings/alliance. The log
   says `blocked ... -> level ...`.
3. Meet one requirement (e.g. `money 250000` for the next rung) and try again.
   ✅ The missing list gets shorter; the promotion goes through when nothing is left, and the
   native promotion dialog/notification appears as usual. `status` shows the new level.
4. **Inheritance skips the gate:** promise the title to a spouse or child (Friendly social),
   then abdicate or let the noble die.
   ✅ The heir reaches the promised rank even with no savings or alliances. `status` shows the
   generation has risen (a descendant) or stayed the same (a spouse).
5. **The earned crown is gated:** set `houserules.royalty.set crown on`, leave the dynasty
   with low savings/alliances (or make the claimant not the dynasty head), and attempt an
   earned promotion at the top rung (coronation duty or high performance).
   ✅ No promotion; the notification/`status` names the missing savings, alliances, dynasty
   head or vacant throne. Meet them with the throne free and try again → the promotion goes
   through. A crown that is inherited or claimed is not gated this way: the pack's promise
   rules still decide who may take it.
6. **Settings:** `houserules.royalty.set generation off` and try a blocked promotion.
   ✅ That requirement disappears from the report. `set enabled off` lets every native
   promotion through; `on` restores the gate.
7. **No pack:** if EP21 is not installed, the log says
   `EP21 Royalty & Legacy is not installed: the mod is inactive`, the commands report
   inactive, and nothing else changes.

Result:
