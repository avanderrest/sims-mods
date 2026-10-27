import pytest

from nsr_life import (
    CAREER_CHANCE,
    HORSE_MIN_FUNDS,
    HORSE_MIN_LOT_AREA,
    MOVE_OUT_CHANCE,
    MOVE_IN_TOGETHER_CHANCE,
    MAX_DAILY_MOVE_INS,
    MAX_DAILY_ROMANCES,
    PART_TIME_SHARE,
    CHILD_CHANCE,
    ROMANCE_AGE_MULTIPLIER,
    ROMANCE_BIT_CHANCE,
    SAME_SEX_ADOPTION_CHANCE,
    OPPOSITE_SEX_ADOPTION_CHANCE,
    OPPOSITE_SEX_PREGNANCY_CHANCE,
    EA_PREGNANCY_ALLOW_CHANCE,
    UNIVERSITY_CHANCE_BY_NET_WORTH,
    career_affinity,
    career_chance,
    child_chance,
    choose_career,
    gender_can_be_pregnant,
    horse_household_ok,
    move_in_chance,
    move_out_chance,
    part_time_share,
    romance_bit_chance,
    should_allow_ea_pregnancy,
    should_allow_horse_adoption,
    should_assign_career,
    should_adopt_same_sex,
    should_enroll_in_university,
    should_move_in_together,
    should_move_out,
    should_start_child,
    should_start_romance,
    should_take_part_time,
    simple_compatibility,
    university_chance,
)


def test_career_chances_are_realistic_and_age_specific():
    assert 0 < career_chance("YOUNGADULT") < 1
    assert 0 < career_chance("ADULT") < 1
    assert career_chance("TEEN") == 0.0
    assert career_chance(None) == 0.0
    assert CAREER_CHANCE["YOUNGADULT"] == 0.73
    assert 0.70 <= CAREER_CHANCE["YOUNGADULT"] <= 0.75
    assert CAREER_CHANCE["ADULT"] == 0.95


def test_unknown_career_is_neutral():
    assert career_affinity("career_Adult_SecretAgent", {}, []) == 1.0
    assert career_affinity("something_modded", None, None) == 1.0


def test_matching_skill_makes_a_career_more_likely():
    low = career_affinity("career_Adult_Painter", {"Major_Painting": 0}, [])
    high = career_affinity("career_Adult_Painter", {"Major_Painting": 10}, [])
    assert low == 1.0
    assert high == 3.0


def test_skill_scales_with_level_and_is_capped():
    half = career_affinity("career_Adult_Painter", {"Major_Painting": 5}, [])
    above_ten = career_affinity("career_Adult_Painter", {"Major_Painting": 20}, [])
    assert half == 2.0
    assert above_ten == 3.0


def test_matching_trait_makes_a_career_more_likely():
    neutral = career_affinity("career_Adult_Writer", {}, [])
    creative = career_affinity("career_Adult_Writer", {}, ["trait_Creative"])
    bookworm = career_affinity("career_Adult_Writer", {}, ["trait_Bookworm"])
    both = career_affinity("career_Adult_Writer", {}, ["Creative", "Bookworm"])
    assert neutral == 1.0
    assert creative == 1.5
    assert bookworm == 2.0
    assert both == 3.0


def test_skills_and_traits_combine():
    score = career_affinity(
        "career_Adult_Painter",
        {"Major_Painting": 10},
        ["trait_Creative", "trait_ArtLover"],
    )
    assert score == 3.0 * 2.0 * 1.5


def test_choose_career_respects_weights():
    candidates = [("painter", 1.0), ("writer", 3.0)]
    assert choose_career(candidates, rng=lambda: 0.0) == "painter"
    assert choose_career(candidates, rng=lambda: 0.99) == "writer"
    # 0.3 * total = 1.2, so it lands in the writer slice.
    assert choose_career(candidates, rng=lambda: 0.3) == "writer"


def test_choose_career_ignores_non_positive_weights_and_empty_lists():
    assert choose_career([], rng=lambda: 0.5) is None
    assert choose_career([("bad", 0)], rng=lambda: 0.5) is None
    assert choose_career([("ok", 2), ("bad", 0)], rng=lambda: 0.5) == "ok"


def test_should_assign_career_uses_the_roll():
    assert should_assign_career("YOUNGADULT", 0.0)
    assert should_assign_career("YOUNGADULT", 0.72)
    assert not should_assign_career("YOUNGADULT", 0.73)
    assert not should_assign_career("YOUNGADULT", 0.9)
    assert should_assign_career("ADULT", 0.94)
    assert not should_assign_career("ADULT", 0.95)
    assert should_assign_career("YOUNGADULT", 0.99, chance=1.0)


def test_move_out_only_applies_to_young_adults():
    assert 0 < move_out_chance("YOUNGADULT") < 1
    assert move_out_chance("ADULT") == 0.0
    assert move_out_chance("TEEN") == 0.0
    assert move_out_chance(None) == 0.0
    assert MOVE_OUT_CHANCE == {"YOUNGADULT": 0.5}


def test_should_move_out_uses_the_roll_and_never_adults():
    assert should_move_out("YOUNGADULT", 0.0)
    assert should_move_out("YOUNGADULT", 0.49)
    assert not should_move_out("YOUNGADULT", 0.5)
    assert not should_move_out("ADULT", 0.0)
    assert not should_move_out("ADULT", 0.1)


def test_horse_household_needs_both_land_and_money():
    assert HORSE_MIN_LOT_AREA == 2000
    assert HORSE_MIN_FUNDS == 50000
    assert horse_household_ok(50, 40, 50000)
    assert horse_household_ok(64, 64, 100000)
    assert not horse_household_ok(40, 30, 100000)   # large-ish, but too small
    assert not horse_household_ok(64, 64, 49999)    # big lot, not enough money
    assert not horse_household_ok(0, 0, 1000000)    # no home lot


def test_horse_adoption_is_rare_even_when_eligible():
    # Eligible households still have to pass a 5% roll on top of EA's pass chance.
    assert should_allow_horse_adoption(64, 64, 100000, 0.0)
    assert should_allow_horse_adoption(50, 40, 50000, 0.049)
    assert not should_allow_horse_adoption(50, 40, 50000, 0.05)
    assert not should_allow_horse_adoption(50, 40, 50000, 0.9)


def test_horse_adoption_is_impossible_on_small_or_poor_lots():
    assert not should_allow_horse_adoption(30, 20, 1000000, 0.0)
    assert not should_allow_horse_adoption(64, 64, 1000, 0.0)
    assert not should_allow_horse_adoption(0, 0, 0, 0.0)


def test_university_chance_rises_with_family_wealth():
    assert university_chance(0) == 0.10
    assert university_chance(25000) == 0.10
    assert university_chance(25001) == 0.20
    assert university_chance(50000) == 0.20
    assert university_chance(100000) == 0.35
    assert university_chance(200000) == 0.55
    assert university_chance(1000000) == 0.75
    assert UNIVERSITY_CHANCE_BY_NET_WORTH[0] == (25000, 0.10)


def test_university_chance_is_monotonic():
    chances = [university_chance(w) for w in (0, 30000, 60000, 120000, 300000)]
    assert chances == sorted(chances)


def test_should_enroll_in_university_uses_wealth_and_roll():
    assert should_enroll_in_university(0, 0.09)
    assert not should_enroll_in_university(0, 0.10)
    assert should_enroll_in_university(1000000, 0.74)
    assert not should_enroll_in_university(1000000, 0.75)
    assert should_enroll_in_university(0, 0.9, chance=1.0)


def test_part_time_share_is_higher_for_young_adults():
    assert part_time_share("YOUNGADULT") == 0.35
    assert part_time_share("ADULT") == 0.20
    assert part_time_share("TEEN") == 0.0
    assert PART_TIME_SHARE == {"YOUNGADULT": 0.35, "ADULT": 0.20}


def test_should_take_part_time_uses_the_roll():
    assert should_take_part_time("YOUNGADULT", 0.0)
    assert should_take_part_time("YOUNGADULT", 0.34)
    assert not should_take_part_time("YOUNGADULT", 0.35)
    assert should_take_part_time("ADULT", 0.19)
    assert not should_take_part_time("ADULT", 0.20)
    assert not should_take_part_time("TEEN", 0.0)


def test_simple_compatibility_uses_shared_and_clashing_traits():
    assert simple_compatibility(["trait_Creative"], ["trait_Creative"]) == "GOOD"
    assert simple_compatibility(
        ["trait_Creative", "trait_Bookworm"], ["trait_Creative", "trait_Bookworm"]
    ) == "AMAZING"
    assert simple_compatibility(["trait_Neat"], ["trait_Slob"]) == "BAD"
    assert simple_compatibility(["trait_Creative"], ["trait_Active"]) == "NEUTRAL"
    assert simple_compatibility([], []) == "NEUTRAL"


def test_romance_bit_chance_only_applies_to_good_and_amazing():
    assert ROMANCE_BIT_CHANCE == {"GOOD": 0.05, "AMAZING": 0.15}
    assert romance_bit_chance("GOOD") == 0.05
    assert romance_bit_chance("AMAZING") == 0.15
    assert romance_bit_chance("NEUTRAL") == 0.0
    assert romance_bit_chance("BAD") == 0.0
    assert should_start_romance("AMAZING", 0.14)
    assert not should_start_romance("AMAZING", 0.15)
    assert not should_start_romance("NEUTRAL", 0.0)


def test_romance_chance_is_lower_for_teens_and_elders():
    assert ROMANCE_AGE_MULTIPLIER == {
        "TEEN": 0.4, "YOUNGADULT": 1.0, "ADULT": 0.8, "ELDER": 0.3}
    assert romance_bit_chance("GOOD", "TEEN") == pytest.approx(0.02)
    assert romance_bit_chance("AMAZING", "TEEN") == pytest.approx(0.06)
    assert romance_bit_chance("GOOD", "YOUNGADULT") == pytest.approx(0.05)
    assert romance_bit_chance("GOOD", "ADULT") == pytest.approx(0.04)
    assert romance_bit_chance("GOOD", "ELDER") == pytest.approx(0.015)
    assert should_start_romance("GOOD", 0.01, age_name="TEEN")
    assert not should_start_romance("GOOD", 0.021, age_name="TEEN")


def test_move_in_together_chances_by_reason():
    assert MOVE_IN_TOGETHER_CHANCE == {"romance": 0.05, "child": 0.10, "pregnant": 0.15}
    assert move_in_chance("romance") == 0.05
    assert move_in_chance("child") == 0.10
    assert move_in_chance("pregnant") == 0.15
    assert move_in_chance("other") == 0.0
    assert should_move_in_together("pregnant", 0.14)
    assert not should_move_in_together("pregnant", 0.15)


def test_same_sex_adoption_chance():
    assert SAME_SEX_ADOPTION_CHANCE == 0.02
    assert should_adopt_same_sex(0.019)
    assert not should_adopt_same_sex(0.02)


def test_child_chances_for_same_and_opposite_sex_couples():
    assert CHILD_CHANCE == {
        "same_sex_adoption": 0.02,
        "opposite_sex_pregnancy": 0.005,
        "opposite_sex_adoption": 0.005,
    }
    assert OPPOSITE_SEX_PREGNANCY_CHANCE == 0.005
    assert OPPOSITE_SEX_ADOPTION_CHANCE == 0.005
    assert child_chance("same_sex_adoption") == 0.02
    assert child_chance("opposite_sex_pregnancy") == 0.005
    assert child_chance("opposite_sex_adoption") == 0.005
    assert child_chance("other") == 0.0
    assert should_start_child("same_sex_adoption", 0.019)
    assert not should_start_child("same_sex_adoption", 0.02)
    assert should_start_child("opposite_sex_adoption", 0.004)
    assert not should_start_child("opposite_sex_adoption", 0.005)


def test_only_female_sims_can_be_pregnant():
    assert gender_can_be_pregnant("FEMALE")
    assert gender_can_be_pregnant("Gender.FEMALE")
    assert not gender_can_be_pregnant("MALE")
    assert not gender_can_be_pregnant("Gender.MALE")
    assert not gender_can_be_pregnant(None)


def test_ea_pregnancy_gate_is_female_only_and_rare():
    assert EA_PREGNANCY_ALLOW_CHANCE == 0.2
    assert should_allow_ea_pregnancy(0.19, "FEMALE")
    assert not should_allow_ea_pregnancy(0.2, "FEMALE")
    assert not should_allow_ea_pregnancy(0.0, "MALE")
    assert not should_allow_ea_pregnancy(0.0, None)


def test_daily_romance_and_move_in_caps_are_small():
    # One lucky pass over every household used to add four romances and two move-ins at
    # once; these caps keep a single day's changes readable.
    assert MAX_DAILY_ROMANCES == 2
    assert MAX_DAILY_MOVE_INS == 1
