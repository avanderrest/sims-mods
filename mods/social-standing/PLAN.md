# Social Standing

**Status:** built 2026-10-09 (`scripts/social_main.py`): compatibility, status (wealth, fame, the game's noble career rank as the title, plus a `social.royal` flag), friendship/romance multipliers, Get Famous starstruck moodlet. Not built: our own moodlets without Get Famous (needs a .package) and status-based autonomy. To test · **Type:** script, plus a little tuning · **Size:** medium

## Goal

Two sims who've just met can become good friends after one conversation. Change that:

- **Compatibility sets the pace.** Sims who are a great match (similar personalities, shared likes, good chemistry) still click quickly. Everyone else takes a lot longer.
- **Status gaps act like fame.** When one sim is much wealthier than the other, or has a royal title, they should behave the way the game treats celebrities:
  - The lower-status sim may be starstruck, nervous or eager to please.
  - The higher-status sim is harder to get close to: friendship builds slowly, and they may be aloof or brush the other sim off.
  - Sims of similar status get no penalty from status.

## How it would work

### 1. Compatibility score (−1 … +1) for every pair of sims

Calculated from what the game already tracks:
- **Traits:** shared or complementary traits add points (two Bookworms, Cheerful + Goofball); clashing ones take points away (Neat + Slob, Good + Evil, Loner + Outgoing).
- **Likes and dislikes** (base game: music, activities, colours): shared likes add points; one sim's like being the other's dislike takes points away.
- **Lovestruck chemistry / attraction**, if that pack is installed. It's the game's own compatibility measure, so it weighs more.
- **Same age group or career** gives a small bonus.

Pure logic, so it can be unit-tested with pytest.

### 2. Status score for each sim

- **Wealth:** household money plus home value, on a log scale, so £10k → £100k is the same step as £100k → £1M.
- **Fame:** Get Famous fame level, if that pack is installed.
- **Royal title:** see the open questions; the base game has no royalty as far as we know.
- **Possibly** career level and reputation as smaller extras.

Status gap = the difference between the two sims' scores.

### 3. Friendship gain multiplier

Each social interaction's friendship gain is multiplied by a value worked out from both scores:

| Situation | Multiplier (to tune) |
|---|---|
| Great compatibility, similar status | ×1.0 (as now) |
| Average compatibility | ×0.4 |
| Poor compatibility | ×0.15 |
| Big status gap, gain for the **higher**-status sim | extra ×0.3 |
| Big status gap, gain for the **lower**-status sim | normal, but romance and "close friend" levels gated until the higher one warms up |

Friends who already know each other well, or family members, get no slow-down.

### 4. Celebrity-style behaviour for high-status sims (phase 2)

- If Get Famous is installed, reuse its celebrity reactions (starstruck, asking for an autograph, fan behaviour) and trigger them by status, not only by fame.
- Without Get Famous: our own moodlets: *Starstruck* (lower-status sim, nervous, with a chance of awkward socials) and *Unimpressed* (higher-status sim, less inclined to chat).
- The higher-status sim's autonomy prefers chatting with sims of similar status.

## Steps

1. **Discovery:**
   - Where friendship gain is applied: the loot that changes the relationship track, or the track's own gain modifiers. Can a buff or modifier scale friendship gain *per pair of sims*? (`ea_scripts/simulation/relationships/`.)
   - How Get Famous's fame and celebrity reactions are triggered (`fame` / `celebrity` code), and whether we can trigger them without fame.
   - How likes/dislikes and Lovestruck chemistry are stored on a sim.
2. **Compatibility + status logic**, pure Python with tests.
3. **Friendship multiplier:** the game layer, plus a cheat `houserules.social.check` that prints both scores and the multiplier for the selected sim and the sim they're talking to. That's the fast way to test it in the game.
4. Celebrity-style moodlets and behaviour (phase 2).
5. Settings via cheats (on/off; slider for how strong the effect is).

## Open questions

- **Royal title:** where does it come from? The base game has no royals that we know of. Options: support a popular royalty mod (which one do you use?), add our own "Royal" trait as a simple flag, or both.
- Should wealth count only the household's money, or the home and its contents too?
- ~~Should status also affect romance (a wealthy sim is pickier), or only friendship?~~ Decided
  2026-10-26: both get the status gap; romance also gets compatibility, on a gentler curve
  than friendship (`ROMANCE_COMPATIBILITY_CURVE`).
- Overlaps with Hard Mode ("relationships build too fast"). Is this part of Hard Mode or its own mod? For now it's its own mod, since its theme is social standing, not difficulty.
