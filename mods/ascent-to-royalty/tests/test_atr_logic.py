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


def test_net_worth_and_friendship_are_reported():
    failures = logic.missing(1, 9, net_worth=0, dynasty_friend=None)
    kinds = {failure.kind for failure in failures}
    assert kinds == {logic.NET_WORTH, logic.FRIEND}
    assert "§35,000" in logic.failure_text(failures)
    assert "a friend outside your dynasty" in logic.failure_text(failures)


def test_a_ready_promotion_has_no_failures():
    rank = logic.rank_for_level(1, 9)
    assert logic.missing(1, 9, net_worth=rank.net_worth, dynasty_friend="Alice") == []


def test_any_friend_in_a_dynasty_satisfies_the_requirement():
    rank = logic.rank_for_level(3, 9)
    missing = logic.missing(3, 9, net_worth=rank.net_worth, dynasty_friend=None)
    assert [failure.kind for failure in missing] == [logic.FRIEND]
    assert logic.missing(3, 9, net_worth=rank.net_worth, dynasty_friend="Alice") == []


def test_friend_text_names_the_friend():
    failures = logic.missing(2, 9, net_worth=0, dynasty_friend=None)
    assert "have: none" in failures[-1].text
    found = logic.requirements(2, 9, net_worth=0, dynasty_friend="Alice")
    assert "have: Alice" in found[-1].text


def test_checks_switch_a_requirement_off():
    failures = logic.missing(1, 9, net_worth=0, dynasty_friend=None,
                             checks=(logic.NET_WORTH,))
    assert {failure.kind for failure in failures} == {logic.NET_WORTH}
    assert logic.missing(1, 9, net_worth=0, dynasty_friend=None,
                         checks=()) == []


def test_inherited_peerage_is_always_allowed():
    assert logic.missing(6, 9, net_worth=0, dynasty_friend=None,
                         inherited=True) == []


def test_inherited_titles_skip_the_gate_even_for_a_crown():
    assert logic.missing(9, 9, net_worth=0, dynasty_friend=None,
                         throne_empty=False, inherited=True) == []


def test_the_crown_only_needs_no_higher_rank_in_the_region():
    rows = logic.requirements(9, 9, net_worth=0, dynasty_friend=None,
                              throne_empty=True)
    assert [row.kind for row in rows] == [logic.MONARCH]
    assert rows[0].met
    blocked = logic.requirements(9, 9, net_worth=0, dynasty_friend=None,
                                 throne_empty=False)
    assert [row.kind for row in blocked] == [logic.MONARCH]
    assert not blocked[0].met
    assert "no Monarch in the region" in blocked[0].text


def test_crown_gate_can_be_switched_off():
    assert logic.missing(9, 9, net_worth=0, dynasty_friend=None,
                         throne_empty=False, checks=(logic.NET_WORTH,)) == []


def test_requirements_list_the_whole_gate_with_progress():
    rank = logic.rank_for_level(4, 9)
    rows = logic.requirements(4, 9, net_worth=rank.net_worth, dynasty_friend=None)
    assert [row.kind for row in rows] == [logic.NET_WORTH, logic.FRIEND]
    assert rows[0].met
    assert not rows[1].met


def test_requirements_match_missing():
    rank = logic.rank_for_level(3, 9)
    rows = logic.requirements(3, 9, net_worth=0, dynasty_friend=None)
    assert [logic.Failure(row.kind, row.text) for row in rows if not row.met] == \
        logic.missing(3, 9, net_worth=0, dynasty_friend=None)


def test_money_formatting():
    assert logic.format_money(1200000) == "1,200,000"
    assert logic.format_money(None) == "None"


def test_noble_guests_are_at_your_rank_or_below():
    nobles = [("duke", 8), ("knight", 1), ("marquess", 7), ("commoner", None), ("monarch", 10)]
    assert logic.noble_guests(nobles, 8) == [("duke", 8), ("knight", 1), ("marquess", 7)]
    assert logic.noble_guests(nobles, 1) == [("knight", 1)]
    # A rank nobody else holds still invites nobody above it.
    assert logic.noble_guests(nobles, 9) == [("duke", 8), ("knight", 1), ("marquess", 7)]


def test_noble_guests_ignores_untitled_and_zero_levels():
    assert logic.noble_guests([("x", 0), ("y", None)], 9) == []
    assert logic.noble_guests([("x", 3)], 0) == []
