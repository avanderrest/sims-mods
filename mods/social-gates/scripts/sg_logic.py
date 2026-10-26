"""Social Gates - pure rules (no game imports, covered by tests).

Three gates, all optional:

Friendship
  is_friend(score, threshold) - "friend" is a friendship-track score, not a bit, so it works
  for every age and pack and doesn't depend on EA's relationship-bit ids.

Clubs
  - A Sim may only join a club that has at least one restriction they match: a trait from
    its trait restrictions, a skill from its skill restrictions, or a skill used by one of
    its activities. (EA's own membership criteria still apply on top.)
  - "Household value" restrictions are relative to the club leader's household, instead of
    the game's three fixed brackets. The labels become:
      Poor    = poorer than the leader   (below leader x (1 - band))
      Average = similar to the leader    (leader x (1 - band) ... leader x (1 + band))
      Rich    = richer than the leader   (above leader x (1 + band))
    The leader is the only Sim who can edit the club, so the range follows whoever leads it.
  - Wealth is only checked when a Sim joins or when the club is edited; it is never a
    reason to remove someone who is already a member.
"""
POOR = 0
AVERAGE = 1
RICH = 2

_CATEGORY_NAMES = {POOR: "Poor", AVERAGE: "Average", RICH: "Rich"}


def group_affordances(group):
    """Every interaction a ClubInteractionGroup tuning class offers.

    A club rule's `action` is the tuning class itself, not an instance, and tuning classes
    aren't iterable: the interactions live in its `affordances` and `affordance_lists`
    fields (the same way npc_main reads them).
    """
    found = set(getattr(group, "affordances", ()) or ())
    for affordance_list in getattr(group, "affordance_lists", ()) or ():
        found.update(affordance_list)
    return found


def _category(value):
    if isinstance(value, str):
        return value.strip().lower()
    return value


def category_name(value):
    key = _category(value)
    if isinstance(key, str):
        for number, name in _CATEGORY_NAMES.items():
            if name.lower() == key:
                return name
        return str(value)
    return _CATEGORY_NAMES.get(key, str(value))


def category_meaning(value):
    """What the game's three labels mean in this mod: poorer / similar / richer."""
    key = _category(value)
    if key in (POOR, "poor"):
        return "poorer than the leader"
    if key in (AVERAGE, "average"):
        return "similar to the leader"
    if key in (RICH, "rich"):
        return "richer than the leader"
    return str(value)


def is_friend(score, threshold):
    """A friendship score at or above the threshold. None/unknown is not a friend."""
    return score is not None and score >= threshold


# --- Relative household value ----------------------------------------------------------
def wealth_bounds(category, leader_net_worth, band=0.5):
    """(low, high) inclusive bounds for one category, relative to the leader; high can be None.

    Returns None when there is no usable leader net worth (the game layer then leaves EA's
    own fixed brackets alone).
    """
    if leader_net_worth is None or leader_net_worth <= 0:
        return None
    band = max(0.0, float(band))
    low = max(0, int(round(leader_net_worth * (1.0 - band))))
    high = int(round(leader_net_worth * (1.0 + band)))
    key = _category(category)
    if key in (POOR, "poor"):
        return (0, max(0, low - 1))
    if key in (AVERAGE, "average"):
        return (low, high)
    if key in (RICH, "rich"):
        return (high + 1, None)
    return None


def in_wealth_range(category, candidate_net_worth, leader_net_worth, band=0.5):
    """True if the candidate fits the category's relative band. Unknown category: True."""
    bounds = wealth_bounds(category, leader_net_worth, band)
    if bounds is None:
        return True
    low, high = bounds
    if candidate_net_worth < low:
        return False
    if high is not None and candidate_net_worth > high:
        return False
    return True


def wealth_description(leader_net_worth, band=0.5):
    """Human-readable bounds for the three categories, for the cheat/log output."""
    if leader_net_worth is None or leader_net_worth <= 0:
        return "no leader net worth; using the game's fixed brackets"
    band = max(0.0, float(band))
    low = max(0, int(round(leader_net_worth * (1.0 - band))))
    high = int(round(leader_net_worth * (1.0 + band)))
    return "Poorer than the leader: under {:,}; Similar: {:,}-{:,}; Richer: over {:,}".format(
        low, low, high, high)


# --- Club admission -------------------------------------------------------------------
def admission_check(sim_traits, sim_skills, trait_requirements=(), skill_requirements=(),
                    activity_skills=(), activity_any_skill=False, require_restriction=True,
                    activity_skill_min=1, min_skill_level=1):
    """(ok, reason) for the trait/skill/activity part of joining a club.

    sim_traits/sim_skills use whatever keys the game layer has (trait and skill tuning
    classes). A Sim passes by matching *any one* of the three kinds of restriction.
    """
    traits = set(sim_traits or ())
    skills = dict(sim_skills or {})
    wanted_traits = set(trait_requirements or ())
    wanted_skills = set(skill_requirements or ())
    activity_skills = set(activity_skills or ())

    trait_match = bool(wanted_traits & traits)
    skill_match = any(skills.get(skill, 0) >= min_skill_level for skill in wanted_skills)
    activity_match = any(skills.get(skill, 0) >= activity_skill_min for skill in activity_skills)
    if activity_any_skill and not activity_match:
        activity_match = any(level >= activity_skill_min for level in skills.values())

    has_restrictions = bool(wanted_traits or wanted_skills or activity_skills or activity_any_skill)
    if not has_restrictions:
        if require_restriction:
            return False, "the club has no trait, skill or activity restrictions to match"
        return True, "the club has no restrictions"

    if not (trait_match or skill_match or activity_match):
        parts = []
        if wanted_traits:
            parts.append("{} trait(s)".format(len(wanted_traits)))
        if wanted_skills:
            parts.append("{} skill(s)".format(len(wanted_skills)))
        if activity_skills or activity_any_skill:
            parts.append("its activities")
        return False, "does not match any of the club's {}".format(" / ".join(parts))

    matched = [name for name, ok in (("trait", trait_match), ("skill", skill_match),
                                     ("activity", activity_match)) if ok]
    return True, "matches a club {}".format(" and ".join(matched))


def club_admission(sim_traits, sim_skills, wealth_categories=(), candidate_net_worth=0,
                   leader_net_worth=0, band=0.5, relative_wealth=True, **kwargs):
    """The whole admission rule: trait/skill/activity match plus relative wealth.

    Returns (ok, reason). The game layer still runs EA's other membership criteria.
    """
    ok, reason = admission_check(sim_traits, sim_skills, **kwargs)
    if not ok:
        return ok, reason
    if relative_wealth and wealth_categories and leader_net_worth and leader_net_worth > 0:
        for category in wealth_categories:
            if not in_wealth_range(category, candidate_net_worth, leader_net_worth, band):
                bounds = wealth_bounds(category, leader_net_worth, band)
                low, high = bounds
                wanted = "{} ({:,}-{:,})".format(category_meaning(category), low, high) if high is not None \
                    else "{} ({:,}+)".format(category_meaning(category), low)
                return False, "household net worth {:,} is outside the club's {} range".format(
                    candidate_net_worth, wanted)
    return True, reason
