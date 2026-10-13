"""Hard Mode: skill aptitude - pure logic (no game imports, covered by tests).

Every sim is good at some things and not others:
- **Talents:** each sim has TALENT_COUNT talent skills, picked at random but fixed per sim
  (seeded by the sim's id, so nothing needs saving and it never changes).
- **Trait affinity:** some traits make related skills come naturally (TRAIT_SKILLS).
- A skill with a talent or trait affinity is learned faster (APT_MULTIPLIER). Without one,
  learning slows down from SLOW_FROM_LEVEL (SLOW_MULTIPLIER): anyone can get decent at
  anything, but mastering it takes a gift.
- Mood boosts count for less: any skill-gain boost from moods, buffs and traits is damped
  to BOOST_SHARE of its size (a x2 boost becomes x1.5).
"""
import random

TALENT_COUNT = 2
APT_MULTIPLIER = 1.25
SLOW_FROM_LEVEL = 7
SLOW_MULTIPLIER = 0.6
BOOST_SHARE = 0.5

# Adult skills talents are drawn from (by the end of their tuning name).
TALENT_POOL = ("Charisma", "Comedy", "Fishing", "Fitness", "Gardening", "GourmetCooking", "Guitar",
               "Handiness", "HomestyleCooking", "Logic", "Mischief", "Mixology", "Painting", "Photography",
               "Piano", "Programming", "RocketScience", "Singing", "Violin", "Writing", "Baking",
               "Dancing", "DJMixing", "Herbalism", "Acting", "Knitting", "Woodworking")

# trait tuning name -> skills it helps. Traits from packs you don't have are just never found.
TRAIT_SKILLS = {
    "trait_Active": ("Fitness", "Dancing"),
    "trait_GymRat": ("Fitness",),
    "trait_Bookworm": ("Writing",),
    "trait_Creative": ("Painting", "Writing", "Photography", "Knitting", "Woodworking"),
    "trait_ArtLover": ("Painting", "Photography"),
    "trait_Genius": ("Logic", "RocketScience", "Programming"),
    "trait_Geek": ("Programming", "VideoGaming", "RocketScience"),
    "trait_Foodie": ("HomestyleCooking", "GourmetCooking", "Baking"),
    "trait_Goofball": ("Comedy",),
    "trait_Outgoing": ("Charisma",),
    "trait_SelfAssured": ("Charisma",),
    "trait_MusicLover": ("Guitar", "Piano", "Violin", "Singing", "DJMixing"),
    "trait_LovesOutdoors": ("Gardening", "Fishing", "Herbalism"),
    "trait_Evil": ("Mischief",),
    "trait_Mean": ("Mischief",),
    "trait_Perfectionist": ("Painting", "Writing", "Woodworking"),
    "trait_Ambitious": ("Charisma", "Logic"),
}


def talents_for(sim_id, pool=TALENT_POOL, count=TALENT_COUNT):
    """The sim's talent skills: random, but always the same for the same sim."""
    rng = random.Random(int(sim_id))
    return tuple(sorted(rng.sample(list(pool), min(count, len(pool)))))


def has_aptitude(skill, sim_id, trait_names):
    if skill in talents_for(sim_id):
        return True
    return any(skill in TRAIT_SKILLS.get(t, ()) for t in trait_names)


def aptitude_multiplier(skill, level, sim_id, trait_names):
    """Multiplier on this sim's skill gain for `skill` at `level` (0-10)."""
    if has_aptitude(skill, sim_id, trait_names):
        return APT_MULTIPLIER
    if level >= SLOW_FROM_LEVEL:
        return SLOW_MULTIPLIER
    return 1.0


def damp_boost(multiplier, share=BOOST_SHARE):
    """Shrinks a boost (above 1) towards 1. Penalties (below 1) are left as they are."""
    if multiplier <= 1.0:
        return multiplier
    return 1.0 + (multiplier - 1.0) * share
