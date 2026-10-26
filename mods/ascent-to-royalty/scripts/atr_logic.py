"""Ascent to Royalty - pure gate logic (no game imports, covered by tests).

The game's Noble career promotes a Sim one level at a time. Before each promotion we build
a rank from the level being moved to, and list what the dynasty is still missing. The game
layer then asks the player-visible settings which kinds of requirement to enforce.

Nothing here reads the save: callers pass wealth, generation, alliances, milestones and the
crown facts in. That keeps the whole rule set testable outside the game.
"""
from collections import namedtuple

# The ten adult titles of the native Noble career, in order. Level 0 is the first rung and
# the highest level is the monarch. rank_for_level() stretches this ladder if a patch ever
# changes the number of levels, so it cannot crash.
#
# Wealth is savings (household funds, not the home), generation is 1 for the first titled
# generation, alliances is the number of native dynasty alliances. The wealth column is
# calibrated to a normal lifespan's worth of Noble pay: roughly §672/day at Knight rising to
# §2,856/day at Monarch, about §85,000 earned per generation when the career is worked
# steadily. Three generations therefore save about §255,000 for the crown, so the Monarch
# rung asks for §250,000 rather than a number no noble salary can reach.
Rank = namedtuple("Rank", "male female wealth generation alliances milestones")
RANKS = (
    Rank("Knight", "Dame", 25000, 1, 0, ()),
    Rank("Baronet", "Baronetess", 35000, 1, 0, ("heir",)),
    Rank("Baron", "Baroness", 50000, 2, 1, ("heir",)),
    Rank("Viscount", "Viscountess", 70000, 2, 1, ("heir", "career_peak")),
    Rank("Count", "Countess", 90000, 2, 2, ("heir", "career_peak")),
    Rank("Margrave", "Margravine", 110000, 3, 2, ("heir", "career_peak")),
    Rank("Marquess", "Marchioness", 130000, 3, 2, ("heir", "career_peak")),
    Rank("Duke", "Duchess", 160000, 3, 3, ("heir", "career_peak")),
    Rank("Grand Duke", "Grand Duchess", 200000, 3, 3, ("heir", "career_peak")),
    Rank("Monarch", "Monarch", 250000, 3, 4, ("heir", "career_peak")),
)

MILESTONE_NAMES = {
    "heir": "a living heir in the dynasty",
    "career_peak": "a dynasty member at the top of a career",
}

# What missing() reports. `kind` is what the settings switch on/off.
Failure = namedtuple("Failure", "kind text")

WEALTH = "wealth"
GENERATION = "generation"
ALLIANCES = "alliances"
MILESTONES = "milestones"
CROWN = "crown"
CHECKS = (WEALTH, GENERATION, ALLIANCES, MILESTONES, CROWN)


def clamp_level(level, max_level):
    return max(0, min(int(max_level), int(level)))


def is_crown(level, max_level):
    """True for the top title in this game build (the one with one holder per world)."""
    return clamp_level(level, max_level) >= int(max_level) and int(max_level) > 0


def rank_index_for_level(level, max_level):
    """Map a native career level onto our ladder.

    Level 0 is the first (Knight) rung and the highest native level is the Monarch. With the
    pack's ten levels this is one-to-one. A build with more or fewer levels spreads the
    ladder evenly, rounding to the nearest rank.
    """
    max_level = max(1, int(max_level))
    position = clamp_level(level, max_level) / float(max_level)
    return int(round(position * (len(RANKS) - 1)))


def rank_for_level(level, max_level):
    return RANKS[rank_index_for_level(level, max_level)]


def title_for(rank, female=False):
    return rank.female if female else rank.male


def rank_title(level, max_level, female=False):
    return title_for(rank_for_level(level, max_level), female)


def missing(level, max_level, wealth, generation, alliances, milestones, is_head=False,
            throne_empty=True, inherited=False, census_known=True, checks=None):
    """Everything still missing for the promotion to `level`.

    Returns a list of Failure, empty when the promotion is allowed. `checks` is the set of
    kinds to enforce (None means all).

    Inherited, married-in and claimed titles always pass: the pack's succession must keep
    working, and refusing one inside the promotion hook would make the pack believe the title
    passed when it did not. The gate is on the earned promotion path only.
    """
    level = clamp_level(level, max_level)
    crown = is_crown(level, max_level)
    if inherited:
        return []
    checks = set(CHECKS if checks is None else checks)
    rank = rank_for_level(level, max_level)
    found = []
    if WEALTH in checks and (wealth or 0) < rank.wealth:
        found.append(Failure(WEALTH, "§{} (have §{})".format(format_money(rank.wealth),
                                                              format_money(wealth or 0))))
    if GENERATION in checks and (generation or 0) < rank.generation:
        found.append(Failure(GENERATION, "generation {} (have {})".format(rank.generation, generation or 0)))
    if ALLIANCES in checks and (alliances or 0) < rank.alliances:
        found.append(Failure(ALLIANCES, "{} alliance{} (have {})".format(
            rank.alliances, "" if rank.alliances == 1 else "s", alliances or 0)))
    if MILESTONES in checks:
        known = set(milestones or ())
        for milestone in rank.milestones:
            if milestone not in known:
                found.append(Failure(MILESTONES, MILESTONE_NAMES.get(milestone, milestone)))
    if crown and CROWN in checks:
        if not census_known:
            found.append(Failure(CROWN, "a known dynasty (join the noble career first)"))
        if not is_head:
            found.append(Failure(CROWN, "the claimant must be the dynasty head"))
        if not throne_empty:
            found.append(Failure(CROWN, "the throne must be vacant (another monarch reigns)"))
    return found


def allowed(*args, **kwargs):
    return not missing(*args, **kwargs)


def failure_text(failures):
    return ", ".join(failure.text for failure in failures)


def format_money(value):
    """§1,200,000 rather than 1200000, for console lines and notifications."""
    try:
        return "{:,}".format(int(value))
    except (TypeError, ValueError):
        return str(value)
