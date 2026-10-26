"""Pure logic for Hard Mode's career gate. No game imports - hardmode_main.py turns real
sims/careers into the plain names and numbers used here.

Rule (design note, 2026-10-09): to newly join a gated full-time career a sim needs the career's
minimum skills, UNLESS they have finished a degree that waives it. Since 2026-10-14 ANY
finished degree waives every gate (ANY_DEGREE_UNLOCKS_ALL); Flexible University's
Certificate and Associate Degree count the same way. The per-career degrees in GATES are
kept so that can be switched back. Sims already in the career are never blocked
(grandfathered), and careers not in GATES aren't gated at all.

Names are matched against the game's tuning names in hardmode_main.py:
- career keys are matched case-insensitively as a substring of the career tuning name
  (e.g. "astronaut" -> "astronaut", "business" -> "adult_business");
- skill names are the end of the skill's tuning name (statistic_Skill_AdultMajor_Logic -> Logic);
- degree keys are matched as a substring of the degree tuning name.
"""

ANY_DEGREE = "*"

# Design note, 2026-10-14: "any degree unlocks all careers". False = only the degrees in GATES.
ANY_DEGREE_UNLOCKS_ALL = True

# career key -> (requirements, degrees that waive them)
# requirements: a list of groups that must ALL be met; each group is a list of
# (skill, level) alternatives of which ANY one is enough.
#
# Entry gates: they only decide who can START a career at level 1, so they're low - about
# level 2 in the career's main skill (design note, 2026-10-09). Moving up is left to the game's
# own promotion requirements.
GATES = {
    "doctor": ([[("Logic", 2)]], ("biology",)),
    "scientist": ([[("Logic", 2)], [("Handiness", 1)]], ("physics", "biology")),
    "astronaut": ([[("Fitness", 2)], [("Logic", 1)]], ("physics",)),
    "engineer": ([[("Handiness", 2)]], ("physics", "computerscience")),
    "law": ([[("Charisma", 2)], [("Logic", 1)]], ("history", "psychology")),
    "education": ([[("Logic", 2), ("Charisma", 2)]], (ANY_DEGREE,)),
    "activist": ([[("Charisma", 2)]], ("communications", "history")),  # Politician
    "business": ([[("Charisma", 2)]], ("economics",)),
    "techguru": ([[("Programming", 2)]], ("computerscience",)),
    "writer": ([[("Writing", 2)]], ("language", "literature")),
    "painter": ([[("Painting", 2)]], ("fineart",)),
    "culinary": ([[("HomestyleCooking", 2)]], ("culinary",)),
    # career_Adult_Active_ActorCareer (Get Famous). "Fame" is the celebrity star level
    # (0-5), read by the game layer, not a skill. Key is "actorcareer" so it can't match
    # names that merely contain "actor".
    "actorcareer": ([[("Acting", 2), ("Fame", 1)]], ("drama",)),
    "entertainer": ([[("Comedy", 2), ("Guitar", 2), ("Piano", 2), ("Violin", 2)]], ("drama", "fineart")),
    "secretagent": ([[("Fitness", 1)], [("Charisma", 1)]], ("psychology",)),
    "athlet": ([[("Fitness", 2)]], ()),  # career_Adult_Athletic
    "criminal": ([[("Mischief", 2)]], ()),
}

# Requirement names that are not skills: the game layer supplies their levels itself.
NON_SKILLS = ("Fame",)

ALL_SKILLS = sorted({skill for reqs, _ in GATES.values() for group in reqs for skill, _ in group}
                    - set(NON_SKILLS))


def gate_for_career(career_name):
    """The GATES key for a career tuning name, or None if that career isn't gated.
    Longest key wins, so a name matching two keys picks the more specific one."""
    name = (career_name or "").lower().replace("_", "")
    matches = [key for key in GATES if key in name]
    return max(matches, key=len) if matches else None


def qualification_degree_names(credentials):
    """Flexible University credential rows -> degree tuning names for degree_waives().

    Certificate and Associate Degree records use the same major tuning name as a finished
    degree, so they satisfy both the "any degree" rule and the per-career waiver table.
    """
    return [c["major"] for c in credentials or ()
            if isinstance(c, dict) and c.get("major")]


def degree_waives(gate_key, finished_degree_names):
    """True if one of the finished degrees (tuning names) waives this career's skill gate."""
    waivers = GATES[gate_key][1]
    names = [d.lower().replace("_", "") for d in finished_degree_names]
    if ANY_DEGREE_UNLOCKS_ALL or ANY_DEGREE in waivers:
        return bool(names)
    return any(w in n for w in waivers for n in names)


def missing_skills(gate_key, skill_levels):
    """skill_levels: {skill name: level}. Returns the requirement groups not met, each as
    a readable string like 'Logic 5 (has 3)' or 'Comedy 2 or Guitar 3 (has none)'."""
    missing = []
    for group in GATES[gate_key][0]:
        if any(skill_levels.get(skill, 0) >= level for skill, level in group):
            continue
        need = " or ".join("{} {}".format(skill, level) for skill, level in group)
        has = ", ".join("{} {}".format(s, skill_levels[s]) for s, _ in group if skill_levels.get(s))
        missing.append("{} (has {})".format(need, has or "none"))
    return missing


def check_join(career_name, is_full_time, skill_levels, finished_degree_names,
               already_employed_here, enabled=True):
    """Returns (blocked, reason). Never blocks when disabled, already employed, not a
    full-time career, or not a gated career."""
    if not enabled:
        return False, "Hard Mode careers setting is off"
    if already_employed_here:
        return False, "already in this career (grandfathered)"
    if not is_full_time:
        return False, "not a full-time career (part-time, teen and side jobs aren't gated)"
    gate_key = gate_for_career(career_name)
    if gate_key is None:
        return False, "this career has no skill gate"
    if degree_waives(gate_key, finished_degree_names):
        return False, "a finished degree or university qualification waives the skill gate"
    missing = missing_skills(gate_key, skill_levels)
    if missing:
        return True, "needs " + "; ".join(missing) + (
            " - or any finished degree or qualification" if ANY_DEGREE_UNLOCKS_ALL
            else " - or a relevant degree")
    return False, "skill requirements met"
