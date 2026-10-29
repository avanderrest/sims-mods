import pytest
from sg_logic import (ACTIVITY_INTERESTS, BASE_GAME_TRAITS, admission_check, category_meaning,
                      category_name, club_admission, club_exempt, group_affordances,
                      in_wealth_range, interest_keys, interest_match, is_friend,
                      relative_wealth_label, relative_wealth_label_with_ranges, string_key,
                      wealth_bounds, wealth_description)


def test_is_friend():
    assert is_friend(20, 20)
    assert is_friend(80, 20)
    assert not is_friend(19, 20)
    assert not is_friend(None, 20)


def test_club_exempts_family_household_and_friends():
    assert not club_exempt()
    assert club_exempt(close_relative=True)
    assert club_exempt(same_household=True)
    assert club_exempt(friend=True)
    assert club_exempt(close_relative=False, same_household=True, friend=False)


def test_every_activity_has_keywords_traits_and_a_like():
    for key, info in ACTIVITY_INTERESTS.items():
        assert info["keywords"], key
        assert info["traits"], key
        assert info["likes"] or info["like_prefixes"], key


def test_every_base_game_trait_is_covered_somewhere():
    covered = set()
    for info in ACTIVITY_INTERESTS.values():
        covered.update(info["traits"])
    assert set(BASE_GAME_TRAITS) <= covered


def test_interest_keys_read_activity_and_skill_tuning_names():
    assert interest_keys(["clubInteractionGroup_SkillBuilding_Painting"]) == {"painting"}
    assert "fitness" in interest_keys(["skill_Fitness"])
    assert "comedy" in interest_keys(["clubInteractionGroup_Social_TellJokes"])
    assert interest_keys([]) == set()


def test_interest_match_uses_traits_and_likes():
    ok, reason = interest_match({"painting"}, ["trait_Creative"])
    assert ok and "painting" in reason
    ok, _ = interest_match({"painting"}, ["trait_SimPreference_Likes_Activities_Painting"])
    assert ok
    ok, _ = interest_match({"painting"}, ["trait_Bookworm"])
    assert not ok
    # A Like from one category matches a club activity from the same interest.
    ok, _ = interest_match({"listening_music"}, ["trait_SimPreference_Likes_Music_Pop"])
    assert ok
    # Unknown/empty activities never hide anyone.
    assert interest_match(set(), ["trait_Bookworm"])[0]


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


def test_relative_wealth_labels_follow_the_categories():
    assert relative_wealth_label(0) == "Poorer than the club leader"
    assert relative_wealth_label(1) == "Similar to the club leader"
    assert relative_wealth_label(2) == "Richer than the club leader"
    assert relative_wealth_label("Average") == "Similar to the club leader"
    assert relative_wealth_label("rich") == "Richer than the club leader"
    assert relative_wealth_label(99) is None


def test_relative_wealth_labels_can_include_the_leader_ranges():
    poor = relative_wealth_label_with_ranges(0, 20000, 0.5)
    assert poor == ("Poorer than the club leader (under \u00a7{0.Number})", (10000,))
    average = relative_wealth_label_with_ranges(1, 20000, 0.5)
    assert average == ("Similar to the club leader (\u00a7{0.Number}-\u00a7{1.Number})",
                       (10000, 30000))
    rich = relative_wealth_label_with_ranges(2, 20000, 0.5)
    assert rich == ("Richer than the club leader (\u00a7{0.Number} or more)", (30001,))
    assert relative_wealth_label_with_ranges(1, 0) is None
    assert relative_wealth_label_with_ranges(1, None) is None
    assert relative_wealth_label_with_ranges(99, 20000) is None


def test_every_label_is_shipped_in_the_string_table_source():
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "text" / "club_wealth_labels.txt"
    shipped = {line.strip() for line in source.read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.startswith("#")}
    for category in (0, 1, 2):
        assert relative_wealth_label(category) in shipped
        ranged = relative_wealth_label_with_ranges(category, 20000, 0.5)
        assert ranged[0] in shipped


def test_string_key_matches_the_build_tool_hash():
    # tools/tuning.py hashes the same text this way when it writes the string table.
    assert string_key("Poorer than the club leader") == 0xCC353BC7
    assert string_key("Similar to the club leader") == 0xFF5BD321
    assert string_key("Richer than the club leader") == 0x3BFBEF79
    assert string_key("Poorer than the club leader (under \u00a7{0.Number})") == \
        string_key("poorer than the club leader (under \u00a7{0.number})")
    assert string_key("Same Text") == string_key("same text")


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


def test_admission_interest_satisfies_the_restriction():
    # A Sim who likes painting but has never painted still fits a painting club.
    ok, reason = admission_check(set(), {}, (), (), ("painting",), interested=True)
    assert ok and "interested" in reason
    ok, _ = admission_check(set(), {}, (), (), ("painting",), interested=False)
    assert not ok


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
