# Ascent to Royalty

**Status:** built 2026-10-26, to test in game · **Type:** script only, needs **EP21 Royalty & Legacy** · **Size:** medium

## Goal

Royal status should be earned over a family's history, not handed out when a career bar fills
up. A wealthy commoner earns a knighthood; their descendants climb the peerage; the crown is
won through wealth, a grown dynasty and political alliances — never simply inherited.

The pack already supplies the setting: a Noble career, real titles, one top-ranked Sim per
world, title inheritance and dynasty alliances/rivalries. Ascent to Royalty adds the missing
*pace*: a promotion is only allowed when the household has the money, the generations and the
allies for that rank.

## How it works

`NobleCareer._promote` is wrapped. Before the game promotes a Sim, the mod checks the rank
being moved to:

| Rank | Savings | Generation | Alliances | Milestones |
|---|---|---|---|---|
| Knight (entry) | §25,000 | 1 | 0 | – |
| Baronet | §35,000 | 1 | 0 | an heir |
| Baron | §50,000 | 2 | 1 | an heir |
| Viscount | §70,000 | 2 | 1 | heir, career peak |
| Count | §90,000 | 2 | 2 | heir, career peak |
| Margrave | §110,000 | 3 | 2 | heir, career peak |
| Marquess | §130,000 | 3 | 2 | heir, career peak |
| Duke | §160,000 | 3 | 3 | heir, career peak |
| Grand Duke | §200,000 | 3 | 3 | heir, career peak |
| Monarch | §250,000 | 3 | 4 | heir, career peak |

- **Savings** are the household's liquid funds, not the home, so an expensive house cannot
  buy a title. The numbers are calibrated to a normal lifespan of Noble pay: about §672/day
  at Knight rising to §2,856/day at Monarch, roughly §85,000 earned per generation when the
  career is worked steadily. Three generations therefore save about §255,000 for the crown,
  so the top rung asks for §250,000.
- **Generation** is the family-tree depth below the first Sim the mod recorded for that
  dynasty. It rises when the title passes to a descendant. Target: a crown in about three
  generations, not "next Tuesday".
- **Alliances** are the pack's own dynasty alliances (the ally count is taken on both sides).
- **An heir** means a living descendant of the dynasty head is a dynasty member.
- **A career peak** means a dynasty member reached the top level of a non-noble career.
- The **Monarch** row additionally requires the claimant to be the **dynasty head** and the
  world's top noble title to be **vacant**.

Inherited, married-in and claimed titles are treated differently: they pass freely, so an
heir or spouse who inherits a title reaches that rank without the savings/generation/alliance
grind — including a promised crown. This is deliberate. Refusing a native inheritance inside
the promotion hook would not create a succession crisis; it would leave the pack believing
the title had passed, and the title could vanish. The gate therefore applies to the *earned*
promotion path. The pack still decides who may inherit or claim, and keeps one holder per
world.

The pack's native level count is read at runtime. Its ten levels are mapped one-to-one onto
the ten ranks above, so a patch that adds a title does not break the mod.

### Settings

Kept in `Mods/HouseRules/data/ascent_to_royalty.json`:

- `enabled` — the whole mod.
- `notify` — a notification when a promotion is refused.
- `wealth`, `generation`, `alliances`, `milestones`, `crown` — switch one kind of gate off.
  `crown` controls only the "dynasty head + vacant throne" part; the other kind of gate still
  applies to the crown.

### Cheats

```
houserules.royalty.status            this dynasty: rank, generation, wealth, allies, milestones
houserules.royalty.check [sim]       what the next promotion needs, and what is missing
houserules.royalty.levels            the native career levels and each gate
houserules.royalty.on / .off
houserules.royalty.set <kind> on|off
houserules.royalty.ally <sim id>     form a native dynasty alliance (testing/politics)
houserules.royalty.grant <level>     force a native noble level, bypassing the gate (testing)
houserules.royalty.reset             forget this dynasty's recorded progress
```

## Why EP21 instead of the example script

The supplied example (`REGIONAL_MONARCHS`, placeholder trait IDs, `royalty.*` commands)
predates the pack. EP21 already has per-world exclusive titles, inheritance, dynasty
alliances, favor and a native noble career. Building a second registry would fight it and
would need custom traits that the repo cannot ship without a package. So the mod uses the
native systems and only adds the missing progression gate.

## Open questions

- Should knighthood (joining the career) also need the Knight row? Currently joining is left
  to the pack's own "Request Knighthood" interaction; the first gate is the promotion after it.
- Are three generations too slow for a normal save? The `generation` switch can turn that gate
  off without touching the others.
- Should the mod also require native favor (Commoner/Royalty alignment) or a Grand Ball? The
  pack exposes both; not used yet because favor is an alignment rather than a score.
- Native alliance formation may be rare in some saves. `houserules.royalty.ally` is the
  escape hatch; if testing shows it is needed in normal play, add a proper interaction later.

## Steps

1. Discovery of EP21's noble career, kingdom service and dynasty service. Done.
2. Pure gate logic with pytest. Done.
3. `NobleCareer._promote` hook, per-dynasty state, commands. Done.
4. Self-test suite and manual test steps. Done.
5. In-game verification (needs a save with a noble career).
