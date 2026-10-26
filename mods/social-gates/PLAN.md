# Social Gates

**Status:** built 2026-10-26. Doors/greetings, invite over, club admission, relative club wealth and the no-auto-kick rule are in `scripts/sg_main.py`; rules are in `sg_logic.py` with pytest coverage. To test in game (TESTING.md section 7). · **Type:** script · **Size:** medium

## Goal

Make social access mean something, without adding clicks:

- **Houses are private.** A Sim is only let in by a household they're friends with. Knocking/ringing the doorbell fails for acquaintances and strangers. Family, household members and Sims with an "always welcome" trait/status still get in.
- **Invite over means something.** A Sim won't accept ("come over") unless the host is a friend.
- **Clubs are for people who fit them.** A Sim only joins a club when they match at least one of its:
  - trait restrictions (they have one of the traits),
  - skill restrictions (they have one of the skills at the game's club minimum), or
  - activity skills (they have some skill that one of the club's activities trains).
- **Club money ranges are relative.** The game's three household-value brackets are fixed, small and absolute. We read them as:
  - `Poor` = **poorer than the club leader**,
  - `Average` = **similar to the club leader**,
  - `Rich` = **richer than the club leader**.
  The "similar" band is a setting (`club_wealth_band`, default `0.5` = between half and 1.5× the leader's household). The leader is the only sim who can edit the club, so the range is anchored to whoever leads it.
- **Money never auto-kicks.** Gaining money must not silently remove a member. Existing members are re-checked only when the club is **edited** (and on load they're grandfathered). This is what EA does today: `ClubService.handle_event` re-validates on `SimoleonsEarned`/`OnExitBuildBuy` and removes failing members. The mod skips EA's fixed wealth test for player-created clubs and runs its own relative check only at join/edit.

## How it works

### Friendship

`is_friend(score, threshold)` against the friendship relationship track (not a relationship-bit id), with `friend_min_score` default `20` (the game's "Friend" level). Household members always count. This avoids the example snippet's hard-coded bit ids, which don't match the game's tuning names (`friendship-friend`, `friendship-good_friends`, …).

### Doors

Hook: `RingDoorbellSuperInteraction._try_to_be_invited_in`.
When a player Sim rings an NPC household's doorbell, they're only let in if **any** resident is a friend. Otherwise EA's own "bad relationship" notification (`_bad_relationship_failure_notification`, verified in EA's `visiting_interactions.py`) is shown and the greeting doesn't happen; if that tunable is ever missing, a plain notification is shown instead of letting the Sim in. Own-lot, household members, `always_welcomed_sims`, and `VisitingTuning.ALWAYS_WELCOME_TRAITS` bypass the gate.

### Invite over

Hooks:
- `SituationManager.create_situation` for the invite-over situation (`Situation_InviteOver`). This blocks before the invited Sim spawns.
- `InviteOverSituation._invite_sim_in` as a backstop.
- `Venue.summon_npcs` when the purpose is an invite-over purpose, as a second backstop for versions/paths that summon directly.

If the host isn't a friend of the invited Sim, the invite is declined with a notification and the situation is not created / the Sim isn't let in. Only invites the **player** sends are gated; an NPC inviting the player over is left to the game.

### Clubs

Hooks:
- `Club.add_member` and `Club.can_sim_info_join`: apply the trait/skill/activity admission rule. The leader is exempt.
- `Club._validate_member_against_criteria`: for player-created clubs (and premade clubs only if `club_enforce_premade`), ignore EA's `HouseholdValue` bracket test when `club_relative_wealth` is on. This is the key to "money never kicks"; our own relative check runs on join/edit instead.
- `Club.on_all_households_and_sim_infos_loaded`: sets a grandfather flag, so saved members are never re-checked on load.
- `ClubService.update_club_from_data`: after any club edit, re-check every non-leader member against the whole rule and remove anyone who fails. This is the **only** time existing members are re-checked.

Activity skills come from each club rule's `ClubInteractionGroup`; for each affordance we ask `get_associated_skill()` / `stat_from_skill_loot_data()`. If the group is in the game's `SKILL` category but no specific skill can be read, any skill at the minimum level counts — and "any skill" means the Sim's **whole** skill list (`SimInfo.all_skills()`), not just the skills the club names.

EA's own membership criteria (age, gender, career, fame, relationship, club membership, …) still apply on top. The trait/skill/activity rule is an **additional OR gate**: a Sim must match at least one of those kinds of restrictions, but the game still enforces the criteria it knows about.

Premade clubs are left alone by default (`club_enforce_premade = off`), because removing their seeded members can leave the club empty or leaderless. Turn it on to apply the same rules to them.

### Settings

Stored in `Mods/HouseRules/data/social_gates.json`.

| Setting | Default | Meaning |
|---|---|---|
| `doors` | on | Only friends let you in |
| `invites` | on | Only friends accept an invite over |
| `clubs` | on | Club admission checks run |
| `club_require_restriction` | on | A club with no trait/skill/activity restriction accepts nobody |
| `club_relative_wealth` | on | Wealth brackets are relative to the leader |
| `club_wealth_band` | 0.5 | Half-width of the "Average" band (fraction of leader net worth) |
| `club_activity_skill_min` | 1 | Skill level that counts as "has the activity's skill" |
| `club_enforce_premade` | off | Apply club admission to the game's own clubs too |
| `club_enforce_on_edit` | on | Re-check members when the club is edited |
| `friend_min_score` | 20 | Friendship score that counts as a friend |

Cheats:

```
houserules.gates.status
houserules.gates.set <setting> on|off|number
houserules.gates.check [sim id]      # selected Sim's clubs, pass/fail and why
houserules.gates.clubs               # clubs, criteria and activity skills
houserules.gates.wealth              # effective Poor/Average/Rich ranges per club
houserules.gates.invite <sim id>     # friendship score with the selected Sim
```

## Things to check in game

1. **Doorbell:** visit an NPC household as an acquaintance → not let in (EA "bad relationship" notification). Become friends → let in. Check a household member and an "always welcome" Sim still get in.
2. **Invite over:** invite an acquaintance over → declined notification, they don't arrive. Invite a friend → normal.
3. **Club admission:** make a club with a skill activity (e.g. Painting) and no membership criteria. Try to add a Sim with no relevant skill → refused. Add a Sim with Painting → accepted. Add a Sim with a trait the club restricts → accepted even without the skill.
4. **Relative wealth:** make a player club with an `Average` household-value restriction. The leader is on §20k → §10k-§30k passes, §100k fails. Give an existing member §100k → **not** kicked. Edit the club (change its name and confirm) → they're re-checked and removed. Check the log/notification.
5. **Load:** save and reload with a member whose money changed → still a member.
6. **Premade clubs:** with `club_enforce_premade` off, existing premade club members are untouched.

## Open questions / later

- Should the door gate also **lock** NPC doors, not just refuse the doorbell greeting? The player can still walk into an unlocked house if they don't knock. A door-lock layer would be more thorough but risks blocking service NPCs, party guests and club gatherings. Not done yet.
- Should the leader be exempt from club restrictions? Currently yes (so creating a club with criteria you don't meet doesn't lock you out).
- Should `Poor`/`Average`/`Rich` keep their names? They're the game's UI strings; we can't add a new criteria category without a UI mod, so the labels stay and the meaning becomes relative.
- The activity-skill reader depends on the game exposing an associated skill for the interaction. The cheat output counts how many activity skills were found, so it's visible if a pack's activities don't expose one.
