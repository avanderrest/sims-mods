import pytest

import atr_logic as logic


def test_ladder_maps_first_and_last_levels():
    assert logic.rank_for_level(0, 9).male == "Knight"
    assert logic.rank_for_level(9, 9).male == "Monarch"
    assert logic.rank_title(9, 9, female=True) == "Monarch"


def test_ladder_is_monotonic_and_survives_a_different_level_count():
    titles = [logic.rank_for_level(level, 5).male for level in range(6)]
    assert titles[0] == "Knight"
    assert titles[-1] == "Monarch"
    assert len(set(titles)) == len(titles)
    assert logic.rank_for_level(99, 9).male == "Monarch"
    assert logic.rank_for_level(-3, 9).male == "Knight"


def test_crown_is_the_top_level_only():
    assert not logic.is_crown(8, 9)
    assert logic.is_crown(9, 9)
    assert not logic.is_crown(0, 0)


def test_wealth_generation_and_alliances_are_reported():
    failures = logic.missing(4, 9, wealth=0, generation=0, alliances=0, milestones=())
    kinds = {failure.kind for failure in failures}
    assert kinds == {logic.WEALTH, logic.GENERATION, logic.ALLIANCES, logic.MILESTONES}
    assert "§90,000" in logic.failure_text(failures)


def test_a_ready_promotion_has_no_failures():
    rank = logic.rank_for_level(4, 9)
    assert logic.missing(4, 9, rank.wealth, rank.generation, rank.alliances, rank.milestones) == []


def test_milestones_are_required_until_recorded():
    rank = logic.rank_for_level(3, 9)
    failures = logic.missing(3, 9, rank.wealth, rank.generation, rank.alliances, ())
    assert [failure.text for failure in failures] == [
        logic.MILESTONE_NAMES["heir"], logic.MILESTONE_NAMES["career_peak"]]
    assert logic.missing(3, 9, rank.wealth, rank.generation, rank.alliances, ("heir", "career_peak")) == []


def test_checks_switch_a_gate_off():
    failures = logic.missing(9, 9, 0, 0, 0, (), checks=(logic.WEALTH,))
    assert {failure.kind for failure in failures} == {logic.WEALTH}
    assert logic.missing(9, 9, 0, 0, 0, (), checks=()) == []


def test_inherited_peerage_is_always_allowed():
    assert logic.missing(6, 9, 0, 0, 0, (), is_head=False, throne_empty=False, inherited=True) == []


def test_inherited_titles_skip_the_gate_even_for_a_crown():
    assert logic.missing(9, 9, 0, 0, 0, (), is_head=False, throne_empty=False, inherited=True) == []


def test_earned_crown_is_gated_on_head_and_a_vacant_throne():
    rank = logic.RANKS[-1]
    failures = logic.missing(9, 9, rank.wealth, rank.generation, rank.alliances,
                             rank.milestones, is_head=True, throne_empty=True)
    assert failures == []
    blocked = logic.missing(9, 9, rank.wealth, rank.generation, rank.alliances,
                            rank.milestones, is_head=False, throne_empty=False)
    assert {failure.kind for failure in blocked} == {logic.CROWN}
    assert len(blocked) == 2


def test_crown_needs_a_known_dynasty():
    rank = logic.RANKS[-1]
    failures = logic.missing(9, 9, rank.wealth, rank.generation, rank.alliances,
                             rank.milestones, is_head=True, throne_empty=True, census_known=False)
    assert failures and all(failure.kind == logic.CROWN for failure in failures)


def test_crown_gate_can_be_switched_off_but_the_rest_stays():
    failures = logic.missing(9, 9, 0, 0, 0, (), is_head=False, throne_empty=False,
                             checks=(logic.WEALTH,))
    assert {failure.kind for failure in failures} == {logic.WEALTH}


def test_money_formatting():
    assert logic.format_money(1200000) == "1,200,000"
    assert logic.format_money(None) == "None"
