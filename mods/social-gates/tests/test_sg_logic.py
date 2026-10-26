import pytest
from sg_logic import (admission_check, category_meaning, category_name, club_admission,
                      group_affordances, in_wealth_range, is_friend, wealth_bounds,
                      wealth_description)


def test_is_friend():
    assert is_friend(20, 20)
    assert is_friend(80, 20)
    assert not is_friend(19, 20)
    assert not is_friend(None, 20)


def test_wealth_bounds_relative_to_leader():
    # 50% band around a §20,000 household: average is §10,000-§30,000.
    assert wealth_bounds(0, 20000, 0.5) == (0, 9999)
    assert wealth_bounds(1, 20000, 0.5) == (10000, 30000)
    assert wealth_bounds(2, 20000, 0.5) == (30001, None)


def test_wealth_bounds_accept_names_and_ints():
    assert wealth_bounds("Average", 10000, 0.5) == wealth_bounds(1, 10000, 0.5)
    assert wealth_bounds("rich", 10000, 0.5) == wealth_bounds(2, 10000, 0.5)


def test_wealth_bounds_without_leader():
    assert wealth_bounds(1, 0, 0.5) is None
    assert wealth_bounds(1, None, 0.5) is None


def test_in_wealth_range_boundaries():
    assert in_wealth_range(1, 10000, 20000, 0.5)
    assert in_wealth_range(1, 30000, 20000, 0.5)
    assert not in_wealth_range(1, 9999, 20000, 0.5)
    assert not in_wealth_range(1, 30001, 20000, 0.5)
    assert in_wealth_range(0, 9999, 20000, 0.5)
    assert in_wealth_range(2, 30001, 20000, 0.5)


def test_in_wealth_range_without_leader_is_permissive():
    assert in_wealth_range(1, 999999, 0, 0.5)


def test_wealth_band_can_be_zero():
    assert wealth_bounds(1, 10000, 0) == (10000, 10000)
    assert not in_wealth_range(1, 9999, 10000, 0)


def test_wealth_description():
    text = wealth_description(20000, 0.5)
    assert "Poorer than the leader: under 10,000" in text
    assert "Similar: 10,000-30,000" in text
    assert "Richer: over 30,000" in text
    assert wealth_description(0).startswith("no leader")


def test_admission_requires_a_restriction_by_default():
    ok, reason = admission_check({"bookworm"}, {}, (), (), ())
    assert not ok
    assert "no trait, skill or activity" in reason


def test_admission_can_be_off_for_unrestricted_clubs():
    ok, reason = admission_check({"bookworm"}, {}, (), (), (), require_restriction=False)
    assert ok


def test_admission_trait_match():
    ok, reason = admission_check({"bookworm", "cheerful"}, {}, ("bookworm",), ())
    assert ok and "trait" in reason


def test_admission_skill_match_uses_level():
    ok, _ = admission_check(set(), {"writing": 2}, (), ("writing",), min_skill_level=2)
    assert ok
    ok, _ = admission_check(set(), {"writing": 1}, (), ("writing",), min_skill_level=2)
    assert not ok


def test_admission_activity_skill_match():
    ok, reason = admission_check(set(), {"painting": 2}, (), (), ("painting",),
                                 activity_skill_min=1)
    assert ok and "activity" in reason


def test_admission_activity_can_match_any_skill():
    ok, _ = admission_check(set(), {"fitness": 1}, (), (), (), activity_any_skill=True,
                            activity_skill_min=1)
    assert ok


def test_admission_or_across_kinds():
    # A skill match is enough even if the trait restriction does not match.
    ok, _ = admission_check({"cheerful"}, {"writing": 3}, ("bookworm",), ("writing",))
    assert ok


def test_admission_rejects_when_nothing_matches():
    ok, reason = admission_check({"cheerful"}, {"writing": 0}, ("bookworm",), ("writing",),
                                 ("painting",))
    assert not ok
    assert "does not match" in reason


def test_club_admission_wealth_failure():
    ok, reason = club_admission({"bookworm"}, {}, wealth_categories=(1,),
                                candidate_net_worth=100000, leader_net_worth=20000, band=0.5,
                                trait_requirements=("bookworm",))
    assert not ok
    assert "outside" in reason


def test_club_admission_wealth_pass():
    ok, _ = club_admission({"bookworm"}, {}, wealth_categories=(1,),
                           candidate_net_worth=20000, leader_net_worth=20000, band=0.5,
                           trait_requirements=("bookworm",))
    assert ok


def test_club_admission_skips_wealth_when_relative_off():
    ok, _ = club_admission({"bookworm"}, {}, wealth_categories=(1,),
                           candidate_net_worth=100000, leader_net_worth=20000, band=0.5,
                           relative_wealth=False, trait_requirements=("bookworm",))
    assert ok


def test_category_name():
    assert category_name(0) == "Poor"
    assert category_name("average") == "Average"
    assert category_name(2) == "Rich"


def test_category_meaning():
    assert category_meaning(0) == "poorer than the leader"
    assert category_meaning("Average") == "similar to the leader"
    assert category_meaning(2) == "richer than the leader"


# --- club activity groups (rule.action is the tuning class, not an instance) ---
class _Group:
    affordances = ("paint", "read")
    affordance_lists = (("paint", "chess"), ("write",))


def test_group_affordances_reads_tuning_fields():
    assert group_affordances(_Group) == {"paint", "read", "chess", "write"}


def test_group_affordances_tolerates_missing_fields():
    # A club rule without an activity, or a future tuning shape: no crash, no interactions.
    assert group_affordances(object) == set()
    assert group_affordances(type("_Empty", (), {"affordances": None})) == set()
