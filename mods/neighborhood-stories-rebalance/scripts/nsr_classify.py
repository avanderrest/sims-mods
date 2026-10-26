"""Pure logic for Neighborhood Stories Rebalance: no game imports, so this half can be
tested with plain pytest.

Arcs are classified by their tuning name. The first in-game test (2026-10-09) showed EA's
names spell out what each arc does, e.g. simStoryArc_ChildrenStories_AdoptAHorse_Adult,
householdStoryArc_MoveOut, simStoryArc_ChildrenStories_Pregnancy.
"""

# EA's arc weights are small ints (mostly 1, a few 2/3/10) with a tuned minimum of 1, so a
# multiplier below 1 can't lower a weight of 1. Instead every weight is first scaled up by
# BASE_SCALE and the multiplier applies on top: a weight-1 child adoption stays at 1 while
# everything else becomes 10+, which makes it ~10x rarer relative to the other arcs.
# Weights are only relative within a pass, so scaling everything equally changes nothing else.
# Move-out, move-in, horse adoption and careers are left at 1.0: their passes have only one
# arc (or only one category), so changing their weights cannot change how often they happen.
# They are handled by the age-up logic and action gates in nsr_main.py instead.
BASE_SCALE = 10
MIN_WEIGHT = 1

MULTIPLIERS = {
    "adopt_child": 0.1,
    "adopt_horse": 1.0,
    "adopt_pet": 1.0,
    "move_out": 1.0,
    "move_in": 1.0,
    "pregnancy": 1.0,
    "friend_start": 2.0,
    "friend_gain": 2.667,
    "friend_loss": 2.667,
    "friend_best": 0.4,
    "friend_despised": 0.4,
    "other": 1.0,
}

# Checked in order; first match wins. Matched case-insensitively against the arc name.
_NAME_RULES = (
    ("adoptahorse", "adopt_horse"),
    ("adoptacat", "adopt_pet"),
    ("adoptadog", "adopt_pet"),
    ("adopt", "adopt_child"),  # AdoptABaby / AdoptAToddler / AdoptAChild
    ("becomingbestfriends", "friend_best"),
    ("becomingdespised", "friend_despised"),
    ("friendshipgian", "friend_gain"),  # EA's actual tuning name
    ("friendshipgain", "friend_gain"),
    ("friendshiploss", "friend_loss"),
    ("becomingfriends", "friend_start"),
    ("moveout", "move_out"),
    ("movein", "move_in"),
    ("pregnancy", "pregnancy"),
)


def classify_arc(arc_name):
    """Returns one of the keys in MULTIPLIERS for a story arc's tuning name."""
    name = (arc_name or "").lower()
    for hint, category in _NAME_RULES:
        if hint in name:
            return category
    return "other"


def adjust_weight(original_weight, category, scale=BASE_SCALE, minimum=MIN_WEIGHT):
    """Returns the new integer weight for `original_weight` (an int) given `category`."""
    multiplier = MULTIPLIERS.get(category, 1.0)
    return max(minimum, int(round(original_weight * scale * multiplier)))
