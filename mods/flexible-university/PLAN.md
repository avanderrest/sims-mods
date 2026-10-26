# Flexible University

**Status:** built 2026-10-26, **not yet tested in a running game**. Script hooks and the
phone menu entry are installed; the pure rules have pytest coverage. · **Type:** script +
one interaction tuning · **Size:** medium · **Requires:** Discover University (EP08)

## Goal

Remove Discover University's rigid pacing without adding clicks:

- **Leaving early is no longer a loss.** Dropping out keeps the credits and passed courses
  a Sim already earned. A Sim who leaves with enough credits also gets a qualification:
  a **Certificate** at one third of the degree and an **Associate Degree** at two thirds.
- **Early graduation is a choice.** While a Sim has enough credits for a qualification (but
  not the full degree), the phone gets **Apply for Early Graduation**. Confirming leaves
  university with the qualification, without the dropout cooldown, and keeps the credits for
  a later enrollment. The same dialog is available as a cheat (the fallback for a computer).
- **A term always ends on Friday evening.** Final grades, the term-end dialog and the
  graduation that follows all land on Friday evening (default 19:00), leaving the weekend
  free. A term that starts too late in the week is stretched into the following week rather
  than ending after two or three days.
- **Credits can be fractional.** A strong grade earns part of a credit, and the extra
  weekdays of a stretched term earn a little more. Fractions accumulate across terms and
  turn into whole credits, so a good student sometimes finishes a term with a credit the
  game would not have given.

## How it works

All hooks are in `scripts/fu_main.py`; everything testable is in `scripts/fu_logic.py`.

### Qualifications

`DegreeTracker.dropout` is wrapped. EA's own dropout still runs (notification, housing,
organization cleanup), then the wrapper puts `_current_credits` and `_previous_courses` back
and records a qualification in
`Mods/HouseRules/data/flexible_university_data.json`:

```json
{"fractions": {"<sim id>": 0.35},
 "credentials": {"<sim id>": {"Biology": {"tier": "certificate", "label": "Certificate",
                                          "major": "Biology", "university": "Foxbury",
                                          "credits": 5, "required": 14, "day": 42}}}}
```

Thresholds are **fractions of the game's own `DegreeTracker.CREDITS_REQUIRED`**, not fixed
numbers. The decompiled class currently defaults to **14 credits** (the example snippet
assumed 12), so the tiers are 5 and 10; on a 12-credit degree they would be 4 and 8, the
example's numbers. `certificate_fraction` and `associate_fraction` change them.

A full graduation records a `degree` credential and clears the banked fraction.

### Early graduation

Eligibility is checked in `_eligibility`: the Sim must have a current major, enough credits
for Certificate/Associate, and fewer than the full requirement. The phone entry is added to
`Sim.potential_phone_interactions` only while that is true (the same hook Hard Mode uses for
Pay Off Debt). The tuning is `tuning/EarlyGraduation.xml`, an `ImmediateSuperInteraction`
whose `do_command` runs `houserules.flexuni.early_exit_phone`; its instance id must stay in
sync with `EARLY_EXIT_AFFORDANCE_ID` in `fu_main.py`.

The dialog is EA's `UiDialogOkCancel` with OK/Cancel. On OK, `_leave_with_credential` does what
dropout does *except* the penalty:

- remove the degree-info career slot and the enrolled course careers,
- set the enrollment status to `NONE` (which also refreshes caches and the career panel),
- clear the major/university, knowledge of the major, term alarms and scholarships,
- **keep** `_current_credits`, `_previous_courses`, GPA totals and accepted degrees.

Because `EnrollmentStatus.NONE` allows enrollment, the Sim can apply again at any time and
`enroll()` sees the kept credits, so the next term starts where they left off. There is no
dropout cooldown and no EA dropout notification.

**Computers:** the tuning is a phone interaction. Computers are object tuning, not a script
class with a per-Sim menu hook we can safely inject into, so the cheat opens the same dialog
instead of a computer menu. This is the one place the build falls short of "phone/computer".

### Friday-anchored terms

`DegreeTracker._setup_end_of_term_alarm` is wrapped:

- An explicit `time_till_end_term` (what `load()` passes) goes straight through. A term
  already in progress keeps exactly the time EA saved; the mod never moves a save's end date.
- A fresh term computes `plan_friday_end(start_day, min_term_weekdays)` and sets the alarm to
  the resulting Friday at `friday_end_hour`. `fu_logic` counts weekdays from the start day
  to the candidate Friday inclusive:
  - Monday start -> Friday same week (5 weekdays, no stretch).
  - Tuesday/Wednesday/Thursday start -> Friday of the next week (7-9 weekdays).
  - Friday start -> the following Friday (6 weekdays).
  - Saturday/Sunday start -> the coming Friday (5 weekdays).

`weekdays_in_term` is the single source of truth for both the alarm and the bonus, so the two
cannot drift apart.

### Fractional credits

`DegreeTracker.complete_term` is wrapped. **Before** EA grades the term, `_apply_credit_bonus`:

1. For every course that will pass (`gp_value >= COURSE_GRADE_FAIL_THRESHOLD`), adds the grade
   bonus from `grade_credit_bonus` (A-range 0.25, B-range 0.15, C-range 0.05).
2. Adds `extension_credit_bonus(extra_weekdays)` for a term stretched by the Friday anchor
   (0.1 per extra weekday, capped at 0.5). Only if at least one course passed: a term with
   nothing but failures shouldn't pay for the extra days.
3. Adds the Sim's banked fraction and splits the total into whole credits plus a remainder.
4. Adds the whole credits to `_current_credits` and saves the remainder.

Adding before EA's own check matters: if the bonus is the credit that reaches
`CREDITS_REQUIRED`, EA's normal graduation path runs instead of the mod inventing one. The
whole credit is also included in the term-end dialog's credit count. A notification reports
the bonus.

Only selectable Sims get grade/extension bonuses and credit preservation, so the mod does not
silently rewrite every NPC student's progress.

## Settings

Stored in `Mods/HouseRules/data/flexible_university.json`.

| Setting | Default | Meaning |
|---|---|---|
| `enabled` | on | Master switch; off restores EA behaviour everywhere |
| `early_exit` | on | Phone entry, early-exit dialog and dropout qualifications |
| `preserve_credits` | on | Credits/passed courses survive a plain dropout |
| `fractional_credits` | on | Grade and extra-day fractions |
| `friday_schedule` | on | Anchor the end of a fresh term to Friday evening |
| `friday_end_hour` | 19 | Hour (24h) exams/graduation land on |
| `min_term_weekdays` | 5 | Fewest weekdays a term may have |
| `certificate_fraction` | 0.33 | Certificate threshold, as a fraction of the degree |
| `associate_fraction` | 0.66 | Associate Degree threshold |
| `extension_credit_per_weekday` | 0.1 | Fraction per extra weekday |
| `extension_credit_cap` | 0.5 | Most a stretched term can add |
| `grade_bonus_high_threshold` / `grade_bonus_high` | 3.7 / 0.25 | A-range |
| `grade_bonus_mid_threshold` / `grade_bonus_mid` | 3.0 / 0.15 | B-range |
| `grade_bonus_low_threshold` / `grade_bonus_low` | 2.0 / 0.05 | C-range |

Cheats:

```
houserules.flexuni.status [sim id]       credits, tier, banked fraction, settings
houserules.flexuni.set <setting> <value> change one
houserules.flexuni.early_exit [sim id]   the same dialog as the phone entry
houserules.flexuni.credentials [sim id]  every qualification the Sim holds
houserules.flexuni.schedule [sim id]     the Friday plan for a term starting today
```

## Deliberate simplifications / open questions

- **No custom trait or buff.** Qualifications live in the mod's data file. The example
  snippet's `Trait_University_Certificate_HNC` / `Trait_University_Associate_HND` names do not
  exist in the game, and creating traits would mean a new tuning type and a lot of unverified
  tuning. Hard Mode's career gate now reads these records from the data file (2026-10-26), so a
  Certificate or Associate Degree waives its skill gates; the mods still don't import each
  other.
- **No career-level head start.** The example's `career_starting_level` (3 / 5) is not
  implemented: EA gives the full degree's career benefit through graduation loot, and there is
  no safe script-only hook that tells a *player-initiated* career join apart from the dozen
  load/fixup/story-progression callers of `CareerTracker.add_career` (the same finding as
  Hard Mode's PLAN). Doing it blindly could change existing careers on load.
- **Early exit has no cooldown.** It is a custom leave path, so it never starts EA's dropout
  cooldown; a plain dropout still uses EA's own cooldown.
- **The example's day numbers were wrong.** It used Monday = 0 / Friday = 4. The game's
  `DateAndTime.day()` is Sunday = 0 / Friday = 5; `fu_logic` follows the game.
- **12 vs 14 credits.** The example hard-coded 12. The decompiled `CREDITS_REQUIRED` default
  is 14, so thresholds scale from whatever the installed game says.
- **Existing in-progress terms are not moved.** Only terms planned after the mod loads are
  anchored, and a loaded save's remaining time is preserved.

## Files

```
scripts/fu_logic.py     qualifications, Friday plan, fractions, credential merge (pytest)
scripts/fu_settings.py  defaults and typed get/set (pytest)
scripts/fu_state.py     data file, settings file, notifications
scripts/fu_main.py      DegreeTracker hooks, phone injection, dialog, cheats
scripts/fu_log.py       logs/flexible-university.log
tuning/EarlyGraduation.xml  phone interaction
tests/test_fu_logic.py  pytest for fu_logic.py and fu_settings.py
```
