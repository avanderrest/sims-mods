"""Hard Mode: life and relationships - pure logic (no game imports, covered by tests).

- Friendships and romances fade RELATIONSHIP_DECAY_MULTIPLIER times faster without contact.
- Strong bad moods (grief, embarrassment, stress...) last MOOD_LINGER times longer.
- A pregnancy costs PREGNANCY_COST (prenatal care), straight away.
- Childcare: on weekdays, if every adult in the household has a full-time job, each baby,
  infant or toddler costs CHILDCARE_PER_CHILD a day.
- Reward-store items (satisfaction points) cost REWARD_PRICE_MULTIPLIER times as much.
"""

RELATIONSHIP_DECAY_MULTIPLIER = 1.5

MOOD_LINGER = 1.5
STRONG_MOOD_WEIGHT = 2
NEGATIVE_MOODS = frozenset({"Mood_Sad", "Mood_Angry", "Mood_Embarrassed", "Mood_Tense", "Mood_Stressed",
                            "Mood_Uncomfortable", "Mood_Scared", "Mood_Depressed"})

PREGNANCY_COST = 1500
CHILDCARE_PER_CHILD = 60
REWARD_PRICE_MULTIPLIER = 1.5

WEEKDAYS = (1, 2, 3, 4, 5)   # game days: 0 = Sunday


def lingers(mood_name, mood_weight):
    """Is this a strong bad mood whose moodlet should last longer?"""
    return mood_name in NEGATIVE_MOODS and (mood_weight or 0) >= STRONG_MOOD_WEIGHT


def lingering_decay_rate(decay_rate):
    """A moodlet's timer runs down at decay_rate; slowing it makes the moodlet last longer."""
    return decay_rate / MOOD_LINGER


def relationship_decay(rate, track_name):
    """Faster fading for long-term friendship and romance tracks only."""
    name = (track_name or "").lower()
    if "shortterm" in name or "short_term" in name:
        return rate
    if "friendship" in name or "romance" in name:
        return rate * RELATIONSHIP_DECAY_MULTIPLIER
    return rate


def childcare_cost(young_children, adults, adults_working, game_day):
    """Daily childcare bill for a household."""
    if young_children <= 0 or adults <= 0 or adults_working < adults or game_day not in WEEKDAYS:
        return 0
    return young_children * CHILDCARE_PER_CHILD


def reward_cost(cost):
    return int(round(cost * REWARD_PRICE_MULTIPLIER))
