import pytest

from social_logic import (GAP_FLOOR, KNOWN_WELL, clash_pairs, compatibility, compatibility_multiplier,
                          friendship_multiplier, is_starstruck, romance_multiplier, status, status_gap_multiplier)


def test_shared_traits_raise_compatibility():
    assert compatibility(["trait_Bookworm", "trait_Creative"], ["trait_Bookworm", "trait_Creative"]) == pytest.approx(0.5)


def test_clashing_traits_lower_compatibility():
    assert compatibility(["trait_Neat"], ["trait_Slob"]) < 0


def test_game_conflicts_count_as_clashes():
    clashes = clash_pairs([("trait_Foo", "trait_Bar")])
    assert compatibility(["trait_Foo"], ["trait_Bar"], clashes=clashes) < 0


def test_likes_and_dislikes():
    assert compatibility([], [], likes_a={"jazz"}, likes_b={"jazz"}) > 0
    assert compatibility([], [], likes_a={"jazz"}, dislikes_b={"jazz"}) < 0


def test_compatibility_is_clamped():
    many = ["t{}".format(i) for i in range(20)]
    assert compatibility(many, many) == 1.0


def test_lovestruck_score_is_blended_in():
    ours_only = compatibility(["trait_Neat"], ["trait_Neat"])
    blended = compatibility(["trait_Neat"], ["trait_Neat"], ea_score=-100)
    assert blended < ours_only


@pytest.mark.parametrize("score,mult", [(1.0, 1.0), (0.5, 1.0), (0.0, 0.4), (-0.5, 0.15), (-1.0, 0.1)])
def test_compatibility_multiplier(score, mult):
    assert compatibility_multiplier(score) == pytest.approx(mult)


def test_compatibility_multiplier_interpolates():
    assert 0.4 < compatibility_multiplier(0.25) < 1.0


def test_status_is_log_wealth_plus_fame_and_title():
    assert status(10000) == pytest.approx(4.0)
    assert status(100000) - status(10000) == pytest.approx(1.0)
    assert status(10000, fame_stars=1) > status(10000)
    assert status(10000, noble_level=3) > status(10000, noble_level=1)
    assert status(10000, royal=True) > status(10000)
    assert status(0) == 0


def test_similar_status_no_penalty():
    assert status_gap_multiplier(0.5) == 1.0
    assert status_gap_multiplier(-0.5) == 1.0


def test_big_status_gap_slows_down():
    assert status_gap_multiplier(2.0) < 1.0
    assert status_gap_multiplier(-2.0) == status_gap_multiplier(2.0)
    assert status_gap_multiplier(50) == GAP_FLOOR


def test_family_and_old_friends_unaffected():
    assert friendship_multiplier(-1.0, 5.0, family=True) == 1.0
    assert friendship_multiplier(-1.0, 5.0, current_friendship=KNOWN_WELL) == 1.0


def test_friendship_combines_both():
    assert friendship_multiplier(0.0, 2.0) == pytest.approx(0.4 * status_gap_multiplier(2.0))


def test_romance_only_cares_about_status():
    assert romance_multiplier(0.0) == 1.0
    assert romance_multiplier(3.0) < 1.0
    assert romance_multiplier(3.0, family=True) == 1.0


def test_starstruck_only_for_the_lower_sim():
    assert is_starstruck(4.0, 6.0)
    assert not is_starstruck(6.0, 4.0)
    assert not is_starstruck(4.0, 4.5)
