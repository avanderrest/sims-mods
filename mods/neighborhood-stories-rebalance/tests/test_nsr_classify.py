from nsr_classify import classify_arc, adjust_weight, MULTIPLIERS, BASE_SCALE

# The real arc names logged by the first in-game test, 2026-10-09.
REAL_ARCS = {
    "simStoryArc_ChildrenStories_Pregnancy": "pregnancy",
    "simStoryArc_ChildrenStories_AdoptABaby": "adopt_child",
    "simStoryArc_ChildrenStories_AdoptAToddler": "adopt_child",
    "simStoryArc_ChildrenStories_AdoptAChild": "adopt_child",
    "simStoryArc_AccidentalDeath": "other",
    "householdStoryArc_MoveIn": "move_in",
    "simStoryArc_ChildrenStories_AdoptACat": "adopt_pet",
    "simStoryArc_ChildrenStories_AdoptADog_Small": "adopt_pet",
    "simStoryArc_ChildrenStories_AdoptADog_Big": "adopt_pet",
    "householdStoryArc_MoveOut": "move_out",
    "simStoryArc_CareerAdd": "other",
    "simStoryArc_CareerRemove": "other",
    "simStoryArc_CareerRetire": "other",
    "simStoryArc_ChildrenStories_AdoptAHorse_Child": "adopt_horse",
    "simStoryArc_ChildrenStories_AdoptAHorse_Adult": "adopt_horse",
    "simStoryArc_ChildrenStories_AdoptAHorse_Elder": "adopt_horse",
    "multiSimStoryArc_RelationshipStories_BecomingFriends": "other",
    "multiSimStoryArc_RelationshipStories_RomanceRelationshipStart": "other",
}


def test_classifies_every_real_arc_name():
    for name, expected in REAL_ARCS.items():
        assert classify_arc(name) == expected, name


def test_unknown_or_missing_name_is_other():
    assert classify_arc("someModdedArc") == "other"
    assert classify_arc(None) == "other"


def test_every_category_has_a_multiplier():
    assert set(REAL_ARCS.values()) <= set(MULTIPLIERS)


def test_weight_one_child_adoption_becomes_ten_times_rarer_than_neutral_arcs():
    child = adjust_weight(1, "adopt_child")
    neutral = adjust_weight(1, "other")
    assert child == 1 and neutral == BASE_SCALE


def test_horse_adoption_twenty_times_rarer():
    # Real horse weights were 2 and 1: both end up at the floor of 1, vs 20 and 10 if neutral.
    assert adjust_weight(2, "adopt_horse") == 1
    assert adjust_weight(1, "adopt_horse") == 1


def test_move_out_and_move_in_go_up_relative_to_neutral():
    assert adjust_weight(1, "move_out") == 30
    assert adjust_weight(1, "move_in") == 20


def test_neutral_arcs_keep_their_ratios():
    # FriendshipGain 3 vs BecomingBestFriends 10 stays a 3:10 ratio.
    assert adjust_weight(3, "other") * 10 == adjust_weight(10, "other") * 3


def test_never_below_minimum():
    assert adjust_weight(1, "adopt_horse", scale=1) == 1
