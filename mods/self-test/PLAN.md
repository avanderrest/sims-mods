# Self-test (in-game test suite)

**Status:** built 2026-10-26. Pytest for the runner passes; the game-facing checks are
built and installed but **have not been run in a running game yet**. · **Type:** script · **Size:** small

## Goal

The manual steps in [TESTING.md](../../TESTING.md) take a long time and need a human to
watch for notifications and menus. This mod gives the parts that can be checked
automatically one entry point in the cheat console:

```
houserules.test              run every suite
houserules.test hardmode     one suite (comma-separated for several)
houserules.test.list         list the suites
```

Each check prints `[PASS]`, `[FAIL]` or `[SKIP]` with a short explanation. The same lines
go to `Mods/HouseRules/logs/self-test.log`, and the last run is also written to
`Mods/HouseRules/data/self_test_last.json` (so Claude can read the result without you
copying the console).

## Suites

| Suite | What it checks |
|---|---|
| `env` | a save is loaded, a sim is selected and on the lot, data/log folders writable, no `lastException` or mod-log `[ERROR]` this session |
| `hello` | hello-world module and command (the build pipeline) |
| `actions` | end-to-end moves: send the real `careers.select` command the Find a Job screen sends and check Hard Mode refused it (and lets it through with `enforce` off), check a real inventory item's sell price drops, run `houserules.npc.tick`, call the noble `promote()` the game calls and check Ascent to Royalty blocks it, add the selected sim to a real club and check Social Gates refuses, force a real unpaid bill and check Hard Mode turns it into debt, add a real job and check a scenario's `no_career` rule breaks, make a real friendship gain and check Social Standing's multiplier applied |
| `hardmode` | all modules and install markers, settings, career gate logic and a real career/sim, skill lookup, money hooks, a market-sale round-trip, a debt round-trip, Pay Off Debt tuning, skill aptitude on a real skill, life/reward-store rules |
| `aspiration` | hooks, tracks/levels found and registered, settings, reading the selected sim's aspiration, ordering logic |
| `social` | relationship hook, compatibility/status logic, a real sim's status, royal-flag round-trip |
| `gates` | modules/install log, settings, friend/wealth/admission logic, every real club against the selected sim |
| `scenarios` | example files validate, household facts can be read, a running scenario checks cleanly, goal/win/deadline logic |
| `nsr` | arc-start/end hooks, weights really applied (compared with `adjust_weight`), event tally, classification |
| `npc` | modules and routine store, routine add/read/remove round-trip, command registration, local LLM reachable and the model pulled |

## Safety

The suite is meant for a save you don't mind changing, and the checks that do something
put the previous state back in a `finally` block:

- a market sale is recorded under the private key `"_self_test"` and removed;
- §137 is added to the active household's debt and then removed;
- one routine entry is added to the selected sim and then removed;
- the selected sim is marked royal for one status reading and then restored;
- `actions` sends real commands: the job-pick test only runs when the sim has no career,
  joins one with `enforce` off and quits it again in a `finally`; `npc.tick` has no effect
  when nobody is in NPC mode; the royalty test only runs when a requirement is missing and
  demotes/restores if the gate ever lets a promotion through; the club test only picks a
  player club (not a premade); the bill test only runs when there is no unpaid bill, forces
  one and leaves it cleared; the scenario test uses a temporary scenario file and restores
  the household's progress; the relationship test adds a gain and subtracts it again;
- `aspiration._catch_up` and `scenario.check` only do what the game does on every load/hour.

Nothing else is written except `logs/self-test.log` and `data/self_test_last.json`.

## Files

```
scripts/selftest_core.py    checks, suites, PASS/FAIL/SKIP runner, summary/report (no game imports)
scripts/selftest_live.py    paths, active sim/household, commands, logs, tuning, lastException
scripts/selftest_checks.py  the suites above
scripts/selftest_main.py    the three cheat commands
scripts/selftest_log.py     logs/self-test.log
tests/test_selftest_core.py pytest for the runner
```
