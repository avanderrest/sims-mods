"""Pure logic for the life-cycle part of Neighborhood Stories Rebalance.

No game imports, so pytest can cover the decisions. nsr_main.py turns the chosen
names into real sims/careers: this module only decides *whether* a sim should get
a job on age-up, and *which* job fits their skills and traits.

The aim is to nudge unplayed households through a realistic sequence:
  age up -> maybe a career -> maybe move out -> maybe a relationship -> maybe a child.
Only the career step is implemented so far; the constants here are the knobs for
the rest when they are added.
"""
import random


# A young adult who has just left the teen stage is more likely to still be
# looking for work than an adult who has had time to settle. These are chances
# per age-up, not guarantees.
CAREER_CHANCE = {
    # Among non-students. University students are in education, not unemployed, and are
    # handled by the university branch instead.
    "YOUNGADULT": 0.73,  # target: ~70-75% employed
    "ADULT": 0.95,       # target: ~95% employed
}


# Wealthier families are much more likely to send a young adult to university. Net worth
# includes household funds and the home lot value, so a rich family in a cheap house and
# a modest family in an expensive house both land in the right band. The last entry is
# the catch-all for anything above the previous threshold.
UNIVERSITY_CHANCE_BY_NET_WORTH = (
    (25000, 0.10),
    (50000, 0.20),
    (100000, 0.35),
    (200000, 0.55),
    (None, 0.75),
)


# Share of assigned jobs that should be part-time. Real-world youth employment is much
# more part-time than adult employment; students are in education, not in this figure.
PART_TIME_SHARE = {
    "YOUNGADULT": 0.35,
    "ADULT": 0.20,
}


# Daily chances for the relationship side of Neighborhood Stories. Compatibility levels
# mirror EA's CompatLevel; GOOD/AMAZING are the only ones that can start a romance.
ROMANCE_BIT_CHANCE = {
    "GOOD": 0.05,
    "AMAZING": 0.15,
}

# Teens date, but steady relationships form less often than for young adults; older
# adults also pair up less often. The multiplier applies to the base chance above.
ROMANCE_AGE_MULTIPLIER = {
    "TEEN": 0.4,
    "YOUNGADULT": 1.0,
    "ADULT": 0.8,
    "ELDER": 0.3,
}
MOVE_IN_TOGETHER_CHANCE = {
    "romance": 0.05,
    "child": 0.10,
    "pregnant": 0.15,
}

# Same-sex couples cannot conceive through EA's pregnancy action, so they adopt. Opposite-
# sex couples mostly conceive, with a small adoption chance as the real-life fuzzy edge.
SAME_SEX_ADOPTION_CHANCE = 0.02
# Pregnancy is much rarer than it used to be: the old 2% chance was applied every time EA
# seeded story arcs (not once per day), which made whole neighbourhoods pregnant. The
# daily step is now guarded to once per sim day, and this is the chance for that one roll.
OPPOSITE_SEX_PREGNANCY_CHANCE = 0.005
OPPOSITE_SEX_ADOPTION_CHANCE = 0.005
CHILD_CHANCE = {
    "same_sex_adoption": SAME_SEX_ADOPTION_CHANCE,
    "opposite_sex_pregnancy": OPPOSITE_SEX_PREGNANCY_CHANCE,
    "opposite_sex_adoption": OPPOSITE_SEX_ADOPTION_CHANCE,
}

# EA's own Pregnancy story arc still runs on top of the daily step. Gate it as well: only
# this share of EA's pregnancy actions is allowed to start. Male sims are never allowed to
# be the pregnant sim, whatever the game's own filter says.
EA_PREGNANCY_ALLOW_CHANCE = 0.2

# The daily steps run over every household, so without a cap one lucky run can add several
# romances or move-ins in the same minute (the 2026-10-27 log had 4 romances and 2 move-ins
# at 09:00:36). These caps keep a day's changes readable and stop whole neighbourhoods
# reshuffling at once.
MAX_DAILY_ROMANCES = 2
MAX_DAILY_MOVE_INS = 1

# Fallback compatibility for saves without Lovestruck. EA's own compatibility level is
# used when it exists; these pairs are only the coarse fallback.
CLASHING_TRAITS = {frozenset(pair) for pair in (
    ("trait_Neat", "trait_Slob"), ("trait_Good", "trait_Evil"),
    ("trait_Loner", "trait_Outgoing"), ("trait_Cheerful", "trait_Gloomy"),
    ("trait_Lazy", "trait_Active"), ("trait_Snob", "trait_Goofball"),
    ("trait_FamilyOriented", "trait_HatesChildren"), ("trait_Mean", "trait_Good"),
    ("trait_HotHeaded", "trait_Calm"), ("trait_Bookworm", "trait_Bro"),
)}


# Only a sim who has just become a young adult is considered for splitting out of
# the parental home. Adults are not: a house can legitimately contain several adults
# who live together, and moving them out would be wrong.
MOVE_OUT_CHANCE = {
    "YOUNGADULT": 0.5,
}


# Horse adoption is not reduced through arc weights: the Horse Adoption pass has only
# horse arcs, so re-weighting them cannot make horses rarer. Instead the game layer
# rejects the action unless the household has room and money, then applies this chance
# on top of EA's own pass chance. 50x40 tiles is the smallest "large" residential lot.
HORSE_MIN_LOT_AREA = 2000
HORSE_MIN_FUNDS = 50000
HORSE_ADOPTION_MULTIPLIER = 0.05


# Which skills and traits make a career a better fit. Career names are matched
# case-insensitively as substrings, so this works with base-game and pack careers
# (career_Adult_Painter, career_Adult_Doctor, ...) without hard-coding every pack.
# A skill at level 10 gets the full multiplier; level 0 leaves it at 1.0.
CAREER_AFFINITIES = {
    "painter": {
        "skills": {"major_painting": 3.0, "major_photography": 1.5},
        "traits": {"creative": 2.0, "artlover": 1.5},
    },
    "writer": {
        "skills": {"major_writing": 3.0},
        "traits": {"bookworm": 2.0, "creative": 1.5},
    },
    "culinary": {
        "skills": {"major_cooking": 2.5, "major_gourmetcooking": 2.5, "major_mixology": 1.5},
        "traits": {"foodie": 2.0},
    },
    "athletic": {
        "skills": {"major_fitness": 3.0},
        "traits": {"active": 2.0},
    },
    "techguru": {
        "skills": {"major_programming": 3.0, "major_handiness": 1.5},
        "traits": {"genius": 2.0},
    },
    "scientist": {
        "skills": {"major_logic": 3.0, "major_programming": 1.5},
        "traits": {"genius": 2.0},
    },
    "astronaut": {
        "skills": {"major_fitness": 1.5, "major_logic": 1.5, "major_handiness": 1.5},
        "traits": {"active": 1.5, "genius": 1.5},
    },
    "secretagent": {
        "skills": {"major_logic": 2.0, "major_charisma": 1.5, "major_fitness": 1.5},
        "traits": {"genius": 1.5},
    },
    "business": {
        "skills": {"major_charisma": 3.0},
        "traits": {"ambitious": 2.0, "outgoing": 1.5},
    },
    "criminal": {
        "skills": {"major_mischief": 3.0, "major_fitness": 1.5},
        "traits": {"evil": 2.0, "kleptomaniac": 1.5},
    },
    "entertainer": {
        "skills": {"major_comedy": 2.5, "major_music": 2.5, "major_charisma": 1.5},
        "traits": {"goofball": 2.0, "creative": 1.5},
    },
    "styleinfluencer": {
        "skills": {"major_charisma": 2.0, "major_photography": 1.5},
        "traits": {"ambitious": 1.5, "outgoing": 1.5},
    },
    "doctor": {
        "skills": {"major_logic": 3.0, "major_charisma": 1.5},
        "traits": {"genius": 2.0, "ambitious": 1.5},
    },
    "detective": {
        "skills": {"major_logic": 2.5, "major_fitness": 1.5, "major_charisma": 1.5},
        "traits": {"genius": 2.0, "ambitious": 1.5},
    },
    "actor": {
        "skills": {"major_charisma": 2.5, "major_comedy": 2.0, "major_fitness": 1.5},
        "traits": {"outgoing": 2.0, "creative": 1.5},
    },
    "politician": {
        "skills": {"major_charisma": 3.0},
        "traits": {"outgoing": 2.0, "ambitious": 1.5},
    },
    "engineer": {
        "skills": {"major_handiness": 2.5, "major_programming": 2.0, "major_logic": 1.5},
        "traits": {"genius": 2.0},
    },
    "gardener": {
        "skills": {"major_gardening": 3.0},
        "traits": {"lovesoutdoors": 2.0, "greenfiend": 1.5},
    },
    "teacher": {
        "skills": {"major_charisma": 2.0, "major_logic": 1.5},
        "traits": {"familyoriented": 2.0, "bookworm": 1.5},
    },
    "veterinarian": {
        "skills": {"major_logic": 2.0, "major_fitness": 1.5},
        "traits": {"doglover": 2.0, "catlover": 2.0},
    },
    "lawyer": {
        "skills": {"major_logic": 2.5, "major_charisma": 2.0},
        "traits": {"ambitious": 2.0},
    },
    "interiordesigner": {
        "skills": {"major_painting": 2.0, "major_charisma": 1.5},
        "traits": {"creative": 2.0, "artlover": 1.5},
    },
    "critic": {
        "skills": {"major_writing": 2.5, "major_painting": 1.5, "major_photography": 1.5},
        "traits": {"creative": 2.0, "bookworm": 1.5},
    },
    "socialmedia": {
        "skills": {"major_charisma": 2.0, "major_programming": 1.5, "major_photography": 1.5},
        "traits": {"outgoing": 2.0, "ambitious": 1.5},
    },
}


def _normalise(name):
    name = (name or "").lower()
    if name.startswith("trait_"):
        name = name[len("trait_"):]
    return name


def career_chance(age_name):
    """Probability of trying to assign a career for a sim who just became this age."""
    return CAREER_CHANCE.get(str(age_name or "").upper(), 0.0)


def university_chance(net_worth):
    """Probability of university enrolment at young-adult age-up, by family net worth."""
    worth = max(0, net_worth or 0)
    for threshold, chance in UNIVERSITY_CHANCE_BY_NET_WORTH:
        if threshold is None or worth <= threshold:
            return chance
    return UNIVERSITY_CHANCE_BY_NET_WORTH[-1][1]


def move_out_chance(age_name):
    """Probability of splitting a sim out of the parental home at this age-up.

    Deliberately 0 for adults: several adults can share a house, and they are not
    "children leaving home". Only the transition to young adult is considered.
    """
    return MOVE_OUT_CHANCE.get(str(age_name or "").upper(), 0.0)


def career_affinity(career_name, skills=None, traits=None):
    """How well a career fits a set of skills {name: level} and trait names.

    1.0 means neutral, above 1.0 means a better fit. Skills scale linearly: a
    level-10 sim gets the full skill multiplier, level 0 none of it. Matching
    traits multiply their factor in full. Unknown careers stay neutral.
    """
    key = _normalise(career_name)
    skill_levels = {_normalise(name): level for name, level in (skills or {}).items()}
    trait_names = {_normalise(name) for name in (traits or ())}

    score = 1.0
    for hint, rule in CAREER_AFFINITIES.items():
        if hint not in key:
            continue
        for skill_name, factor in rule.get("skills", {}).items():
            level = max(0.0, min(float(skill_levels.get(skill_name, 0)), 10.0))
            score *= 1.0 + (level / 10.0) * (factor - 1.0)
        for trait_name, factor in rule.get("traits", {}).items():
            if trait_name in trait_names:
                score *= factor
    return score


def choose_career(candidates, rng=None):
    """Pick one (career_name, weight) pair by weight; None if nothing is eligible.

    `rng` is a zero-argument callable returning [0, 1), so tests can be
    deterministic without touching global random state.
    """
    weighted = [(name, weight) for name, weight in (candidates or ()) if weight > 0]
    if not weighted:
        return None
    rng = rng or random.random
    target = rng() * sum(weight for _, weight in weighted)
    for name, weight in weighted:
        target -= weight
        if target < 0:
            return name
    return weighted[-1][0]


def should_assign_career(age_name, roll, chance=None):
    """True when the age-up career roll passes. `chance` overrides the age default."""
    if chance is None:
        chance = career_chance(age_name)
    return roll < chance


def part_time_share(age_name):
    """Share of assigned jobs that should be part-time for this age."""
    return PART_TIME_SHARE.get(str(age_name or "").upper(), 0.0)


def should_take_part_time(age_name, roll, share=None):
    """True when the next assigned job should be part-time."""
    if share is None:
        share = part_time_share(age_name)
    return roll < share


def simple_compatibility(traits_a, traits_b):
    """Coarse GOOD/AMAZING/NEUTRAL/BAD fallback when EA compatibility is unavailable."""
    a, b = set(traits_a or ()), set(traits_b or ())
    clashes = sum(1 for x in a for y in b if frozenset((x, y)) in CLASHING_TRAITS)
    if clashes:
        return "BAD"
    shared = len(a & b)
    if shared >= 2:
        return "AMAZING"
    if shared >= 1:
        return "GOOD"
    return "NEUTRAL"


def romance_bit_chance(level_name, age_name=None):
    base = ROMANCE_BIT_CHANCE.get(str(level_name or "").upper(), 0.0)
    if age_name is None:
        return base
    multiplier = ROMANCE_AGE_MULTIPLIER.get(str(age_name or "").upper(), 1.0)
    return base * multiplier


def should_start_romance(level_name, roll, chance=None, age_name=None):
    if chance is None:
        chance = romance_bit_chance(level_name, age_name)
    return roll < chance


def move_in_chance(reason):
    return MOVE_IN_TOGETHER_CHANCE.get(str(reason or ""), 0.0)


def should_move_in_together(reason, roll, chance=None):
    if chance is None:
        chance = move_in_chance(reason)
    return roll < chance


def should_adopt_same_sex(roll, chance=SAME_SEX_ADOPTION_CHANCE):
    return roll < chance


def child_chance(kind):
    return CHILD_CHANCE.get(str(kind or ""), 0.0)


def should_start_child(kind, roll, chance=None):
    if chance is None:
        chance = child_chance(kind)
    return roll < chance


def gender_can_be_pregnant(gender_name):
    """Only female sims get pregnant in this mod, even if the game allows male pregnancy."""
    return str(gender_name or "").strip().upper() in ("FEMALE", "GENDER.FEMALE")


def should_allow_ea_pregnancy(roll, gender_name, chance=EA_PREGNANCY_ALLOW_CHANCE):
    """Gate EA's own Pregnancy arc: female sim only, and only `chance` of the time."""
    return gender_can_be_pregnant(gender_name) and roll < chance


def should_enroll_in_university(net_worth, roll, chance=None):
    """True when the age-up university roll passes. `chance` overrides the wealth curve."""
    if chance is None:
        chance = university_chance(net_worth)
    return roll < chance


def should_move_out(age_name, roll, chance=None):
    """True when the age-up move-out roll passes. `chance` overrides the age default."""
    if chance is None:
        chance = move_out_chance(age_name)
    return roll < chance


def horse_household_ok(lot_width, lot_height, funds):
    """A horse is only plausible on a large lot with enough money for its upkeep."""
    area = (lot_width or 0) * (lot_height or 0)
    return area >= HORSE_MIN_LOT_AREA and (funds or 0) >= HORSE_MIN_FUNDS


def should_allow_horse_adoption(lot_width, lot_height, funds, roll,
                                chance=HORSE_ADOPTION_MULTIPLIER):
    """Gate a Horse Adoption arc before it creates the horse.

    Both conditions matter: a rich household on a small lot has nowhere to keep a
    horse, and a large lot with no money cannot afford one. Even when both pass,
    EA's own pass chance is multiplied by `chance` so it stays rare.
    """
    if not horse_household_ok(lot_width, lot_height, funds):
        return False
    return roll < chance
