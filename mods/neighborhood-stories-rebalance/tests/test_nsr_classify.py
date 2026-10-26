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
    "multiSimStoryArc_RelationshipStories_BecomingFriends": "friend_start",
    "multiSimStoryArc_RelationshipStories_FriendshipGian": "friend_gain",
    "multiSimStoryArc_RelationshipStories_FriendshipLoss": "friend_loss",
    "multiSimStoryArc_RelationshipStories_BecomingBestFriends": "friend_best",
    "multiSimStoryArc_RelationshipStories_BecomingDespised": "friend_despised",
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


def test_horse_adoption_weight_is_left_alone():
    # Horse adoption is gated by lot size and wealth in nsr_main, not by arc weight.
    assert adjust_weight(2, "adopt_horse") == 2 * BASE_SCALE
    assert adjust_weight(1, "adopt_horse") == BASE_SCALE


def test_move_out_and_move_in_weights_are_left_alone():
    # Each pass has one arc, so changing the weight cannot change the frequency.
    assert adjust_weight(1, "move_out") == BASE_SCALE
    assert adjust_weight(1, "move_in") == BASE_SCALE


def test_friendship_changes_favor_gradual_over_extreme():
    # EA: BecomingFriends 1, Gain 3, Loss 3, BestFriends 10, Despised 10.
    # New:  2, 8, 8, 4, 4 -> gradual changes dominate, extremes become rarer.
    assert adjust_weight(1, "friend_start") == 20
    assert adjust_weight(3, "friend_gain") == 80
    assert adjust_weight(3, "friend_loss") == 80
    assert adjust_weight(10, "friend_best") == 40
    assert adjust_weight(10, "friend_despised") == 40


def test_neutral_arcs_keep_their_ratios():
    # FriendshipGain 3 vs BecomingBestFriends 10 stays a 3:10 ratio.
    assert adjust_weight(3, "other") * 10 == adjust_weight(10, "other") * 3


def test_never_below_minimum():
    assert adjust_weight(1, "adopt_horse", scale=1) == 1
