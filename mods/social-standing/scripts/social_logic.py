"""Social Standing - pure logic (no game imports, covered by tests).

Friendship gain between two sims is multiplied by:
  compatibility_multiplier(compatibility)  - great matches click fast, everyone else is slow
  x status_gap_multiplier(gap)             - a big gap in wealth/fame/title slows it down
unless they're family or already know each other well (friendship >= KNOWN_WELL).

Romance gain gets a gentler compatibility curve (enemies can still fall in love, just much
more slowly) times the same status-gap multiplier.
"""
import math

# --- Compatibility (-1 .. +1) ---------------------------------------------------------
SHARED_TRAIT = 0.25
CLASHING_TRAIT = 0.35
SHARED_LIKE = 0.15
OPPOSED_LIKE = 0.20
SAME_AGE = 0.10
EA_WEIGHT = 0.5   # with Lovestruck installed, its own compatibility counts for half

# Pairs of personality traits that clash between two different sims (on top of the pairs
# the game itself forbids on one sim, which the game layer adds).
CLASHING_TRAITS = (
    ("trait_Neat", "trait_Slob"), ("trait_Good", "trait_Evil"), ("trait_Loner", "trait_Outgoing"),
    ("trait_Cheerful", "trait_Gloomy"), ("trait_Lazy", "trait_Active"), ("trait_Snob", "trait_Goofball"),
    ("trait_FamilyOriented", "trait_HatesChildren"), ("trait_Mean", "trait_Good"),
    ("trait_HotHeaded", "trait_Calm"), ("trait_Bookworm", "trait_Bro"),
)


def clash_pairs(extra_pairs=()):
    return {frozenset(p) for p in tuple(CLASHING_TRAITS) + tuple(extra_pairs)}


def compatibility(traits_a, traits_b, likes_a=(), dislikes_a=(), likes_b=(), dislikes_b=(),
                  same_age=False, clashes=None, ea_score=None):
    """Compatibility from -1 (awful) to +1 (amazing).

    traits_*: personality trait names. likes_*/dislikes_*: preference keys (anything hashable
    that's equal for the same liked thing). ea_score: Lovestruck's own score (-100..100) if any.
    """
    traits_a, traits_b = set(traits_a), set(traits_b)
    clashes = clash_pairs() if clashes is None else clashes
    score = SHARED_TRAIT * len(traits_a & traits_b)
    score -= CLASHING_TRAIT * sum(1 for a in traits_a for b in traits_b if frozenset((a, b)) in clashes)
    likes_a, likes_b, dislikes_a, dislikes_b = set(likes_a), set(likes_b), set(dislikes_a), set(dislikes_b)
    score += SHARED_LIKE * (len(likes_a & likes_b) + len(dislikes_a & dislikes_b))
    score -= OPPOSED_LIKE * (len(likes_a & dislikes_b) + len(likes_b & dislikes_a))
    if same_age:
        score += SAME_AGE
    score = max(-1.0, min(1.0, score))
    if ea_score is not None:
        score = (1 - EA_WEIGHT) * score + EA_WEIGHT * max(-1.0, min(1.0, ea_score / 100.0))
    return score


# (compatibility, multiplier) points, interpolated in between.
COMPATIBILITY_CURVE = ((-1.0, 0.1), (-0.5, 0.15), (0.0, 0.4), (0.5, 1.0), (1.0, 1.0))


def _interpolate(points, x):
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def compatibility_multiplier(score):
    return _interpolate(COMPATIBILITY_CURVE, score)


# Romance is less picky than friendship (enemies can still fall in love), so it gets its
# own, higher curve. Even -1 compatibility leaves some gain, unlike friendship.
ROMANCE_COMPATIBILITY_CURVE = ((-1.0, 0.25), (-0.5, 0.4), (0.0, 0.7), (0.5, 1.0), (1.0, 1.0))


def romance_compatibility_multiplier(score):
    return _interpolate(ROMANCE_COMPATIBILITY_CURVE, score)


# --- Status ---------------------------------------------------------------------------
FAME_PER_STAR = 0.8          # one celebrity star ~ 6x the wealth
NOBLE_PER_LEVEL = 0.6        # each rank of the game's noble career
ROYAL_FLAG = 2.5             # a sim marked royal by cheat ~ 300x the wealth
GAP_FREE = 0.75              # gaps up to this (about 5.6x the wealth) don't matter
GAP_SLOPE = 0.35
GAP_FLOOR = 0.3
CELEBRITY_GAP = 1.5          # from this gap on, the lower-status sim gets starstruck


def status(wealth, fame_stars=0, noble_level=0, royal=False):
    """A sim's social standing on a log scale: +1 per 10x the wealth (household money plus
    home), plus fame and title."""
    return (math.log10(max(1.0, float(wealth))) + FAME_PER_STAR * fame_stars
            + NOBLE_PER_LEVEL * (noble_level or 0) + (ROYAL_FLAG if royal else 0))


def status_gap_multiplier(gap):
    gap = abs(gap)
    if gap <= GAP_FREE:
        return 1.0
    return max(GAP_FLOOR, 1.0 - GAP_SLOPE * (gap - GAP_FREE))


# --- Putting it together --------------------------------------------------------------
KNOWN_WELL = 60   # friendship score from which sims already know each other well


def friendship_multiplier(compat, gap, family=False, current_friendship=0):
    if family or current_friendship >= KNOWN_WELL:
        return 1.0
    return compatibility_multiplier(compat) * status_gap_multiplier(gap)


def romance_multiplier(compat, gap, family=False):
    if family:
        return 1.0
    return romance_compatibility_multiplier(compat) * status_gap_multiplier(gap)


def is_starstruck(status_self, status_other):
    """The lower-status sim reacts like they've met a celebrity."""
    return status_other - status_self >= CELEBRITY_GAP
