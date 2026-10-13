"""NPC Routines phase 3 - off-lot results, pure logic (no game imports, covered by tests).

The game only really simulates sims on the loaded lot. When a routine says a sim is
painting but they're somewhere else (another lot, or their household isn't the one being
played), nothing happens. So for every such hour the sim gets a share of what they would
have learned: OFFLOT_SHARE_PER_HOUR of a skill level per hour, about half of what
practising on the lot gives at low levels.
"""

# Activity -> the adult skill it trains (by the end of the skill's tuning name). Reading
# has no skill of its own.
ACTIVITY_SKILLS = {
    "workout": "Fitness",
    "jog": "Fitness",
    "paint": "Painting",
    "chess": "Logic",
    "read": None,
}

OFFLOT_SHARE_PER_HOUR = 0.08


def offlot_points(activity, level_points, current_points, max_points, hours=1):
    """Skill points to add for `hours` of `activity` off the lot.

    level_points: points between the start of the sim's current level and the next one.
    Never goes past max_points. Returns 0 for activities without a skill."""
    if ACTIVITY_SKILLS.get(activity) is None or level_points <= 0:
        return 0.0
    gain = level_points * OFFLOT_SHARE_PER_HOUR * hours
    return max(0.0, min(gain, max_points - current_points))
