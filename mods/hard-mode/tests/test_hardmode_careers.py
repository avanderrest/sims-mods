import hardmode_careers
from hardmode_careers import (GATES, ALL_SKILLS, gate_for_career, degree_waives,
                              missing_skills, check_join)


def test_gate_matches_real_career_tuning_names():
    # Career names Amber confirmed from careers.promote.
    assert gate_for_career("astronaut") == "astronaut"
    assert gate_for_career("adult_business") == "business"
    assert gate_for_career("SecretAgent") == "secretagent"
    assert gate_for_career("TechGuru") == "techguru"
    assert gate_for_career("adult_writer") == "writer"
    assert gate_for_career("adult_active_scientist") == "scientist"
    assert gate_for_career("activist") == "activist"
    assert gate_for_career("Painter") == "painter"
    assert gate_for_career("Entertainer") == "entertainer"


def test_gate_matches_names_seen_in_game():
    # From bluerabbit477.hard.gates, 2026-10-09.
    assert gate_for_career("career_Adult_Athletic") == "athlet"
    assert gate_for_career("careers_Adult_Activist") == "activist"
    assert gate_for_career("career_Adult_Active_Doctor") == "doctor"
    assert gate_for_career("careers_Adult_Law") == "law"
    assert gate_for_career("careers_Adult_Engineer") == "engineer"
    assert gate_for_career("career_Adult_Active_ActorCareer") == "actorcareer"
    assert gate_for_career("career_Adult_Contractor") is None


def test_actor_needs_acting_or_fame():
    assert check_join("career_Adult_Active_ActorCareer", True, {}, [], False)[0] is True
    assert check_join("career_Adult_Active_ActorCareer", True, {"Acting": 2}, [], False)[0] is False
    assert check_join("career_Adult_Active_ActorCareer", True, {"Fame": 1}, [], False)[0] is False
    assert check_join("career_Adult_Active_ActorCareer", True, {"Acting": 1}, [], False)[0] is True
    assert check_join("career_Adult_Active_ActorCareer", True, {}, ["degree_Drama"], False)[0] is False


def test_fame_is_not_looked_up_as_a_skill():
    assert "Fame" not in ALL_SKILLS and "Acting" in ALL_SKILLS


def test_ungated_careers():
    assert gate_for_career("PartTime_Babysitter") is None
    assert gate_for_career("adult_Detective") is None
    assert gate_for_career(None) is None


def test_missing_skills_reports_what_is_short():
    assert missing_skills("astronaut", {"Logic": 1, "Fitness": 1}) == ["Fitness 2 (has Fitness 1)"]
    assert missing_skills("astronaut", {}) == ["Fitness 2 (has none)", "Logic 1 (has none)"]
    assert missing_skills("astronaut", {"Logic": 1, "Fitness": 2}) == []


def test_any_alternative_in_a_group_is_enough():
    assert missing_skills("entertainer", {"Piano": 2}) == []
    assert missing_skills("entertainer", {"Piano": 1}) == ["Comedy 2 or Guitar 2 or Piano 2 or Violin 2 (has Piano 1)"]
    assert missing_skills("education", {"Charisma": 2}) == []


def test_any_degree_unlocks_all_careers():
    assert degree_waives("doctor", ["degree_Drama"])
    assert degree_waives("athlet", ["degree_Biology"])
    assert not degree_waives("doctor", [])
    assert check_join("astronaut", True, {}, ["degree_Drama"], False)[0] is False
    assert "any finished degree" in check_join("astronaut", True, {}, [], False)[1]


def test_degree_waivers_per_career(monkeypatch):
    monkeypatch.setattr(hardmode_careers, "ANY_DEGREE_UNLOCKS_ALL", False)
    assert degree_waives("doctor", ["degree_Biology"])
    assert not degree_waives("doctor", ["degree_Drama"])
    assert degree_waives("techguru", ["Degree_Computer_Science"])
    assert degree_waives("education", ["degree_Drama"])  # any degree
    assert not degree_waives("education", [])
    assert not degree_waives("athlet", ["degree_Biology"])  # skills only


def test_blocks_new_join_without_skills_or_degree():
    blocked, reason = check_join("astronaut", True, {}, [], False)
    assert blocked
    assert "Fitness 2" in reason and "Logic 1" in reason


def test_allows_with_skills():
    assert check_join("astronaut", True, {"Logic": 1, "Fitness": 2}, [], False)[0] is False


def test_allows_with_matching_degree_even_without_skills():
    assert check_join("astronaut", True, {}, ["degree_Physics"], False)[0] is False


def test_wrong_degree_does_not_waive_per_career(monkeypatch):
    monkeypatch.setattr(hardmode_careers, "ANY_DEGREE_UNLOCKS_ALL", False)
    assert check_join("astronaut", True, {}, ["degree_Drama"], False)[0] is True


def test_grandfathered_part_time_ungated_and_disabled_never_block():
    assert check_join("astronaut", True, {}, [], already_employed_here=True)[0] is False
    assert check_join("astronaut", False, {}, [], False)[0] is False
    assert check_join("adult_Detective", True, {}, [], False)[0] is False
    assert check_join("astronaut", True, {}, [], False, enabled=False)[0] is False


def test_every_gate_is_well_formed():
    for key, (reqs, waivers) in GATES.items():
        assert reqs, key
        for group in reqs:
            assert group and all(isinstance(level, int) and level > 0 for _, level in group), key
    assert "Logic" in ALL_SKILLS and "HomestyleCooking" in ALL_SKILLS


def test_entry_gates_stay_low():
    # Gates are for level 1 of a career only (Amber, 2026-10-09).
    for key, (reqs, _) in GATES.items():
        for group in reqs:
            for skill, level in group:
                assert level <= 2, (key, skill, level)
