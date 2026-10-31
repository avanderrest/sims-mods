import pytest

import atr_logic as logic


def friend(name, head=False, royal=False):
    return logic.Friend(name, head, royal)


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
    failures = logic.missing(1, 9, net_worth=0, friends=[])
    kinds = {failure.kind for failure in failures}
    assert kinds == {logic.NET_WORTH, logic.FRIEND}
    assert "§35,000" in logic.failure_text(failures)
    assert "a dynasty member" in logic.failure_text(failures)


def test_a_ready_promotion_has_no_failures():
    rank = logic.rank_for_level(1, 9)
    assert logic.missing(1, 9, net_worth=rank.net_worth,
                         friends=[friend("Alice")]) == []


def test_friendship_ladder_by_rank():
    expected = {
        1: ("member", 1),
        2: ("member", 2),
        3: ("head", 1),
        4: ("royal_member", 1),
        5: ("royal_member", 2),
        6: ("royal_head", 1),
        7: ("royal_head", 2),
        8: None,
        9: None,
    }
    for level, need in expected.items():
        assert logic.friend_requirement(level, 9) == need


def test_member_tier_needs_the_right_number():
    rank = logic.rank_for_level(2, 9)
    one = [friend("Alice")]
    assert [row.kind for row in logic.missing(2, 9, rank.net_worth, one)] == [logic.FRIEND]
    assert logic.missing(2, 9, rank.net_worth, [friend("A"), friend("B")]) == []


def test_head_tier_needs_a_dynasty_head():
    rank = logic.rank_for_level(3, 9)
    member = [friend("Alice")]
    assert [row.kind for row in logic.missing(3, 9, rank.net_worth, member)] == [logic.FRIEND]
    assert logic.missing(3, 9, rank.net_worth, [friend("Alice", head=True)]) == []


def test_royal_member_tier_needs_a_royal_dynasty():
    rank = logic.rank_for_level(4, 9)
    ordinary = [friend("Alice")]
    assert [row.kind for row in logic.missing(4, 9, rank.net_worth, ordinary)] == [logic.FRIEND]
    assert logic.missing(4, 9, rank.net_worth, [friend("Alice", royal=True)]) == []


def test_royal_head_tier_needs_a_royal_dynasty_head():
    rank = logic.rank_for_level(6, 9)
    royal_member = [friend("Alice", royal=True)]
    assert [row.kind for row in logic.missing(6, 9, rank.net_worth, royal_member)] == [
        logic.FRIEND]
    assert logic.missing(6, 9, rank.net_worth,
                         [friend("Alice", head=True, royal=True)]) == []


def test_grand_duke_has_no_friendship_requirement():
    rank = logic.rank_for_level(8, 9)
    rows = logic.requirements(8, 9, rank.net_worth, [])
    assert [row.kind for row in rows] == [logic.NET_WORTH]
    assert [row.kind for row in logic.missing(8, 9, rank.net_worth, [])] == []


def test_friend_counts_treat_heads_as_members_and_royal_heads_as_royal_members():
    counts = logic.friend_counts([
        friend("member"),
        friend("head", head=True),
        friend("royal", royal=True),
        friend("royal head", head=True, royal=True),
    ])
    assert counts == {"member": 4, "head": 2, "royal_member": 2, "royal_head": 1}


def test_friend_text_names_the_requirement_and_current_count():
    failures = logic.missing(2, 9, net_worth=0, friends=[])
    assert "friends with 2 dynasty members (have 0)" in failures[-1].text
    found = logic.requirements(2, 9, net_worth=0, friends=[friend("Alice")])
    assert "friends with 2 dynasty members (have 1)" in found[-1].text


def test_checks_switch_a_requirement_off():
    failures = logic.missing(1, 9, net_worth=0, friends=[],
                             checks=(logic.NET_WORTH,))
    assert {failure.kind for failure in failures} == {logic.NET_WORTH}
    assert logic.missing(1, 9, net_worth=0, friends=[], checks=()) == []


def test_inherited_peerage_is_always_allowed():
    assert logic.missing(6, 9, net_worth=0, friends=[], inherited=True) == []


def test_inherited_titles_skip_the_gate_even_for_a_crown():
    assert logic.missing(9, 9, net_worth=0, friends=[], throne_empty=False,
                         inherited=True) == []


def test_the_crown_only_needs_no_higher_rank_in_the_region():
    rows = logic.requirements(9, 9, net_worth=0, friends=[], throne_empty=True)
    assert [row.kind for row in rows] == [logic.MONARCH]
    assert rows[0].met
    blocked = logic.requirements(9, 9, net_worth=0, friends=[], throne_empty=False)
    assert [row.kind for row in blocked] == [logic.MONARCH]
    assert not blocked[0].met
    assert "no Monarch in the region" in blocked[0].text


def test_crown_gate_can_be_switched_off():
    assert logic.missing(9, 9, net_worth=0, friends=[], throne_empty=False,
                         checks=(logic.NET_WORTH,)) == []


def test_requirements_list_the_whole_gate_with_progress():
    rank = logic.rank_for_level(4, 9)
    rows = logic.requirements(4, 9, net_worth=rank.net_worth, friends=[])
    assert [row.kind for row in rows] == [logic.NET_WORTH, logic.FRIEND]
    assert rows[0].met
    assert not rows[1].met


def test_requirements_match_missing():
    rank = logic.rank_for_level(3, 9)
    rows = logic.requirements(3, 9, net_worth=0, friends=[])
    assert [logic.Failure(row.kind, row.text) for row in rows if not row.met] == \
        logic.missing(3, 9, net_worth=0, friends=[])


def test_money_formatting():
    assert logic.format_money(1200000) == "1,200,000"
    assert logic.format_money(None) == "None"


def test_closest_dynasty_picks_the_closest_prestige():
    options = [
        logic.InviteDynasty("low", 10, False),
        logic.InviteDynasty("near", 90, False),
        logic.InviteDynasty("high", 200, False),
    ]
    assert logic.closest_dynasty(100, options).key == "near"


def test_closest_dynasty_without_a_host_dynasty_picks_the_lowest():
    options = [
        logic.InviteDynasty("high", 200, False),
        logic.InviteDynasty("low", 10, False),
        logic.InviteDynasty("mid", 90, False),
    ]
    assert logic.closest_dynasty(None, options).key == "low"


def test_closest_dynasty_royal_only_filters_first():
    options = [
        logic.InviteDynasty("ordinary", 100, False),
        logic.InviteDynasty("royal", 300, True),
    ]
    assert logic.closest_dynasty(100, options, royal_only=True).key == "royal"
    assert logic.closest_dynasty(100, options, royal_only=False).key == "ordinary"


def test_closest_dynasty_returns_none_when_no_royal_dynasty_exists():
    options = [logic.InviteDynasty("ordinary", 100, False)]
    assert logic.closest_dynasty(100, options, royal_only=True) is None


def test_closest_dynasty_ties_go_to_the_lower_prestige():
    options = [
        logic.InviteDynasty("up", 110, False),
        logic.InviteDynasty("down", 90, False),
    ]
    assert logic.closest_dynasty(100, options).key == "down"
