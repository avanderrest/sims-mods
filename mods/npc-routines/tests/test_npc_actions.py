import pytest

from npc_actions import (BLACKLIST_HOURS, DEFAULT_WAIT_MINUTES, MAX_ACTIONS, MAX_PER_CATEGORY,
                         MAX_VARIANTS, MAX_WAIT_MINUTES, MIN_WAIT_MINUTES,
                         REPEAT_BLACKLIST_HOURS, actions_for_goal,
                         actions_for_needs, actions_for_wants, activity_for_goal, balance,
                         blacklist_hours, build_candidates, buff_names, category_for,
                         clamp_minutes, clean_label,
                         describe_missing, everyday_actions, examples_for, format_minutes,
                         interleave, is_action, is_chore, is_internal, is_noise_object,
                         is_phone_chat,
                         is_usable, lowest_need_actions, missing_for_goal, need_activity_for,
                         needs_a_situation, needs_arguments, next_check_minutes, pick_random,
                         primary_action, request_key, serves_satisfied, stems_for, still_failed,
                         weather_note, without_satisfied)


@pytest.mark.parametrize("name,label", [
    ("object_tableDining_1x1", "table dining 1x1"),
    ("terrain-jog_Autonomous", "jog"),
    ("easel_Craft_Autonomously", "easel craft"),
    ("autonomous_bookshelf_read_picker", "bookshelf read"),
    ("object_sleep_Sleep", "sleep"),
    ("buff_FeelingHappy", "feeling happy"),
    ("whim_PaintPainting", "paint painting"),
    ("goal_PaintMasterpiece", "paint masterpiece"),
    ("", ""),
])
def test_clean_label(name, label):
    assert clean_label(name) == label


@pytest.mark.parametrize("label", ["sleep", "read", "easel craft"])
def test_plain_actions_are_usable(label):
    assert is_usable(label)


@pytest.mark.parametrize("label", [
    "", "a", "debug reset", "inventory put away",
    "one two three four five six seven eight",
    # pack/career gimmicks that showed up as options on a normal lot
    "civil designer concept submit", "ghost powers possess", "sim ray transform wall",
    # NPC/situation behaviour that showed up too
    "situation butler sabotage stereo tv", "dog misbehavior trash can knock eat",
    "community vote policy stop repeal", "fame perks good reputation donate", "cat stand",
])
def test_tuning_noise_is_not_usable(label):
    assert not is_usable(label)


def test_build_candidates_keeps_the_first_entry_per_label_and_skips_refused_ones():
    entries = [("paint", "a", "easel"), ("read", "b", "shelf"), ("paint", "c", "other easel"),
               ("chess", "d", "table")]
    candidates = build_candidates(entries, skip={"read"})
    assert [c.label for c in candidates] == ["paint", "chess"]
    assert candidates[0].affordance == "a" and candidates[0].target == "easel"


def test_duplicate_labels_become_fallback_variants():
    entries = [("sit", "a", "sofa"), ("sit", "b", "chair"), ("sit", "c", "bench"),
               ("read", "d", "shelf")]
    candidates = build_candidates(entries)
    assert [c.label for c in candidates] == ["sit", "read"]
    # The first variant is tried first; the others are used when the game refuses it.
    assert list(candidates[0].variants()) == [("a", "sofa"), ("b", "chair"), ("c", "bench")]


def test_variants_are_capped():
    entries = [("sit", i, "somewhere") for i in range(MAX_VARIANTS + 3)]
    assert len(list(build_candidates(entries)[0].variants())) == MAX_VARIANTS


def test_build_candidates_respects_the_limit():
    entries = [("action {}".format(i), None, None) for i in range(MAX_ACTIONS + 20)]
    assert len(build_candidates(entries)) == MAX_ACTIONS


def test_interleave_takes_one_from_each_group_in_turn():
    groups = [["a1", "a2", "a3"], ["b1"], ["c1", "c2"]]
    assert interleave(groups) == ["a1", "b1", "c1", "a2", "c2", "a3"]


def test_interleave_respects_the_limit_and_empty_groups():
    assert interleave([[], ["b1", "b2"], []], limit=1) == ["b1"]
    assert interleave([]) == []


@pytest.mark.parametrize("minutes,expected", [
    (None, DEFAULT_WAIT_MINUTES),
    ("nonsense", DEFAULT_WAIT_MINUTES),
    (0, MIN_WAIT_MINUTES),
    (15, 15),
    (10 ** 6, MAX_WAIT_MINUTES),
])
def test_clamp_minutes(minutes, expected):
    assert clamp_minutes(minutes) == expected


@pytest.mark.parametrize("minutes,text", [(45, "45 min"), (60, "1h"), (90, "1h 30m")])
def test_format_minutes(minutes, text):
    assert format_minutes(minutes) == text


@pytest.mark.parametrize("remaining,wait", [
    (1, 1), (3, 3), (5, 5), (10, 5), (60, 5),      # a short task is checked sooner than 5 min
    (0, 1), (-3, 1),                               # past the deadline: look now-ish
    (None, 5), ("nonsense", 5),
])
def test_next_check_minutes(remaining, wait):
    assert next_check_minutes(remaining) == wait


@pytest.mark.parametrize("text,key", [
    ("An easel.", "easel"),
    ("the easel", "easel"),
    ("Some more paint", "paint"),
    ("", ""),
    (None, ""),
])
def test_request_key_ignores_filler_words(text, key):
    assert request_key(text) == key


@pytest.mark.parametrize("label,category", [
    ("fridge cook", "Eat and drink"),
    ("toilet use", "Hygiene and toilet"),
    ("bed single nap", "Rest and comfort"),
    ("tv watch", "Fun and hobbies"),
    ("treadmill workout", "Skills and work"),
    ("call a friend", "Social"),
    ("jog", "Outside"),
    ("something odd", "Other"),
])
def test_category_for(label, category):
    assert category_for(label) == category


@pytest.mark.parametrize("label", [
    "sit", "bed single nap", "fridge cook group dessert", "tv watch public access",
    "mirror practice speech", "collection dig site", "gardening harvest unit low",
    "toilet use", "shower take",
])
def test_life_actions_are_offered(label):
    assert is_action(label)


@pytest.mark.parametrize("label", [
    "immediate check policies mailbox", "change celebrity disguise",
    "empty trash outdoor update", "empty trash",
    "door apartment route to then check mail", "fire replace burnt",
    "eco upgrades completed display siphoner", "collect trash update compostables toilet",
    "tv pick channel",
])
def test_bookkeeping_is_not_an_action(label):
    assert not is_action(label)


def test_a_refused_action_comes_back_after_a_few_hours():
    now = 1.0
    assert still_failed(now - 0.05, now)          # ~1.2 hours ago: still hidden
    assert not still_failed(now - BLACKLIST_HOURS / 24.0 - 0.01, now)
    assert not still_failed(None, now)


@pytest.mark.parametrize("strikes,hours", [
    (None, BLACKLIST_HOURS), (1, BLACKLIST_HOURS), (2, REPEAT_BLACKLIST_HOURS),
    (7, REPEAT_BLACKLIST_HOURS), ("nonsense", BLACKLIST_HOURS),
])
def test_a_repeatedly_refused_action_stays_out_longer(strikes, hours):
    assert blacklist_hours(strikes) == hours


def test_a_goal_with_nothing_to_do_it_with_is_reported_missing():
    actions = ["sit", "fridge cook", "bed single nap", "tv watch public access"]
    assert missing_for_goal("become a famous painter", actions) == ["painting"]
    assert missing_for_goal("become a famous painter", actions + ["easel paint"]) == []
    assert missing_for_goal("write a novel", actions) == ["writing"]
    assert missing_for_goal("become a master mixologist", actions) == ["mixology"]
    assert missing_for_goal("learn to play the piano", actions) == ["piano"]
    assert missing_for_goal("learn to play the piano", actions + ["piano practice"]) == []
    assert missing_for_goal("adopt a cat", actions) == []                  # unknown goal: say nothing
    assert missing_for_goal("", actions) == []
    assert missing_for_goal(None, actions) == []


@pytest.mark.parametrize("missing,described", [
    (["painting"], ["painting (e.g. an easel, a sketchpad, an activity table)"]),
    (["writing", "chess"], ["writing (e.g. a computer, a notebook, a typewriter)",
                            "chess (e.g. a chess table)"]),
    (["something else"], ["something else (anything that would allow it)"]),
    ([], []),
])
def test_describe_missing_gives_a_concrete_example(missing, described):
    assert describe_missing(missing) == described


@pytest.mark.parametrize("missing,examples", [
    (["gardening (e.g. a planter box, a garden plot)"], []),
    (["gardening"], ["a planter box", "a garden plot"]),
    (["painting", "chess"], ["an easel", "a sketchpad", "an activity table", "a chess table"]),
    ([], []),
])
def test_examples_for_the_notification(missing, examples):
    assert examples_for(missing) == examples


@pytest.mark.parametrize("label", ["plant", "plant veg", "sow seeds", "garden plant"])
def test_planting_is_an_action(label):
    assert is_action(label)


def test_actions_for_wants_matches_the_want_words():
    actions = ["plant veg", "fridge cook", "tv watch public access", "counter clean"]
    assert actions_for_wants(["plant something"], actions) == ["plant veg"]
    assert actions_for_wants(["get focused"], actions) == []
    assert actions_for_wants([], actions) == []


def test_actions_for_needs_starts_with_the_lowest_need():
    actions = ["fridge cook", "toilet use", "bed single nap", "tv watch public access"]
    assert actions_for_needs(["Bladder 12", "Hunger 28"], actions) == ["toilet use", "fridge cook"]
    assert actions_for_needs(["Hunger 12"], actions) == ["fridge cook"]
    assert actions_for_needs(["Fun 20"], actions) == ["tv watch public access"]
    assert actions_for_needs([], actions) == []


@pytest.mark.parametrize("label,chore", [
    ("counter clean", True), ("bookshelf clean up", True), ("mop floor", True),
    ("fridge cook", False), ("plant veg", False), ("tv watch public access", False),
])
def test_chores_are_marked_so_they_sort_last(label, chore):
    assert is_chore(label) is chore


@pytest.mark.parametrize("tests,needs", [
    (["SituationRunningTest"], True),
    (["TestList", "SituationRunningTest", "BuffTest"], True),
    (["BuffTest", "ObjectStateTest"], False),
    ([], False),
])
def test_interactions_that_wait_for_a_situation_are_detected(tests, needs):
    assert needs_a_situation(tests) is needs


@pytest.mark.parametrize("debug,cheat,visible,internal", [
    (False, False, True, False),
    (True, False, True, True),
    (False, True, True, True),
    (False, False, False, True),      # hidden from the pie menu
])
def test_internal_interactions_are_detected(debug, cheat, visible, internal):
    assert is_internal(debug, cheat, visible) is internal


def _candidate(label):
    from npc_actions import Candidate
    return Candidate(label)


def test_balance_caps_the_same_verb():
    labels = ["fridge bake cake", "fridge bake pie", "fridge bake bread", "fridge bake fish"]
    kept = balance([_candidate(label) for label in labels])
    assert [c.label for c in kept] == ["fridge bake cake", "fridge bake pie"]


def test_balance_caps_a_category_but_keeps_other_groups():
    labels = ["fridge cook a", "fridge bake b", "fridge meal c", "fridge snack d",
              "fridge food e", "fridge grill f", "fridge eat g",
              "bed single nap", "tv watch public access"]
    kept = [c.label for c in balance([_candidate(label) for label in labels])]
    assert len([label for label in kept if label.startswith("fridge")]) == MAX_PER_CATEGORY
    assert "bed single nap" in kept and "tv watch public access" in kept


def test_primary_action_is_the_verb():
    assert primary_action("fridge bake cake") == "bake"
    assert primary_action("bed single nap") == "nap"
    assert primary_action("something odd") is None


def test_an_easel_on_the_lot_means_painting_is_not_missing():
    # Its paint interaction can be mood-gated, but the object is there: do not ask for one.
    assert missing_for_goal("become a famous painter", ["sit"], ["easel"]) == []
    assert missing_for_goal("become a famous painter", ["sit"], ["sofa"]) == ["painting"]


@pytest.mark.parametrize("label", ["crafting knitting", "knit scarf"])
def test_knitting_without_a_crafting_process_is_not_offered(label):
    assert not is_usable(label)


@pytest.mark.parametrize("label,satisfied,expected", [
    ("shower take", {"hygiene"}, True),
    ("fridge cook", {"hygiene"}, False),
    ("fridge cook", {"hunger"}, True),
    ("bed single nap", {"energy"}, True),
    ("sit", {"hygiene"}, False),          # comfort still useful when hygiene is full
    ("tv watch public access", {"hygiene"}, False),
])
def test_actions_that_only_serve_a_full_need(label, satisfied, expected):
    assert serves_satisfied(label, satisfied) is expected


def test_full_needs_remove_their_options_entirely():
    actions = ["shower take", "fridge cook", "tv watch public access", "sit"]
    assert without_satisfied(actions, {"hygiene"}) == [
        "fridge cook", "tv watch public access", "sit"]
    assert without_satisfied(actions, {"hygiene", "hunger", "comfort"}) == [
        "tv watch public access"]
    assert without_satisfied(actions, {"hygiene", "hunger", "fun", "comfort"}) == []
    assert without_satisfied(actions, set()) == actions


def test_hygiene_hands_counts_as_the_hygiene_need():
    actions = ["sink wash hands", "toilet use sitting", "tv watch public access"]
    assert actions_for_needs(["HygieneHands 20"], actions) == ["sink wash hands"]


def test_stems_for_a_goal_gap():
    assert "easel" in stems_for("painting")
    assert "write" in stems_for("writing")
    assert stems_for("unknown") == ()


@pytest.mark.parametrize("label,weather,note", [
    ("jog", "cool, puddles, raining", " in the cool rain"),
    ("jog", "cold, snowing", " in the cold snow"),
    ("fishing bait hook", "freezing, raining", " in the freezing rain"),
    ("collection dig site", "cold, snowing", " in the cold snow"),
    ("jog", "freezing", " in the freezing cold"),
    ("jog", "hot", " in the heat"),
    ("jog", "warm", " in the sun"),
    ("sit", "cool, raining", ""),
    ("fridge cook", "warm", ""),
    ("jog", "", ""),
])
def test_outdoor_actions_say_what_the_weather_is(label, weather, note):
    assert weather_note(label, weather) == note


@pytest.mark.parametrize("goal,actions,expected", [
    ("become a famous painter",
     ["easel start crafting", "fridge cook", "jog"], ["easel start crafting"]),
    ("become a famous painter", ["fridge cook", "jog"], []),
    ("write a novel", ["computer write", "sit"], ["computer write"]),
    ("", ["easel start crafting"], []),
])
def test_actions_for_goal(goal, actions, expected):
    assert actions_for_goal(goal, actions) == expected


@pytest.mark.parametrize("pressing,actions,entry,matches", [
    # the lowest need wins when both have options
    (["Bladder 12", "Hunger 28"], ["toilet use", "fridge cook", "sit"],
     "Bladder 12", ["toilet use"]),
    # ... and the next one is used when the lowest has nothing on the lot
    (["Bladder 12", "Hunger 28"], ["fridge cook", "sit"], "Hunger 28", ["fridge cook"]),
    # nothing addresses any of them: the lowest need is still named, so the caller can
    # start its own self-care instead of losing which need was urgent
    (["Bladder 12", "Hunger 28"], ["sit"], "Bladder 12", []),
    ([], ["toilet use"], None, []),
])
def test_the_lowest_need_is_prioritised(pressing, actions, entry, matches):
    assert lowest_need_actions(pressing, actions) == (entry, matches)


@pytest.mark.parametrize("name,label", [
    ("fridge_QuickMeal_Picker", "fridge quick meal"),
    ("easel_StartCrafting_Picker", "easel start crafting"),
])
def test_picker_is_dropped_from_the_label_not_the_action(name, label):
    assert clean_label(name) == label
    assert is_usable(label)


def test_a_hungry_sim_is_not_offered_only_cake():
    actions = ["fridge bake cake", "fridge grab quick meal", "fridge cook"]
    assert lowest_need_actions(["Hunger 12"], actions) == (
        "Hunger 12", ["fridge grab quick meal", "fridge cook"])


def test_cake_is_still_offered_when_it_is_all_there_is():
    assert lowest_need_actions(["Hunger 12"], ["fridge bake cake"]) == (
        "Hunger 12", ["fridge bake cake"])


@pytest.mark.parametrize("goal,activity", [
    ("become a famous painter", "paint"),
    ("write a novel", "read"),
    ("become a grandmaster at chess", "chess"),
    ("get fit", "workout"),
    ("adopt a cat", None),
    ("", None),
])
def test_activity_for_goal(goal, activity):
    assert activity_for_goal(goal) == activity


class _CraftingBase:
    def __init__(self, *args, crafting_process, phase, **kwargs):
        pass


class _TunedStaging(_CraftingBase):
    # Tuning classes often hide the required keywords behind their own generic constructor;
    # the required arguments are still there on the base class.
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class _PlainInteraction:
    def __init__(self, *args, **kwargs):
        pass


class counter_MakeFood_Basic_Staging(_PlainInteraction):
    pass


class _OptionalPhase(_PlainInteraction):
    def __init__(self, *args, phase=None, **kwargs):
        super().__init__(*args, **kwargs)


@pytest.mark.parametrize("affordance", [_CraftingBase, _TunedStaging,
                                        counter_MakeFood_Basic_Staging])
def test_crafting_staging_needs_arguments(affordance):
    assert needs_arguments(affordance)


@pytest.mark.parametrize("affordance", [_PlainInteraction, _OptionalPhase])
def test_ordinary_interactions_need_no_arguments(affordance):
    assert not needs_arguments(affordance)


# --- the 2026-10-27 log: Hygiene 0 for three sim days -------------------------------

def test_an_object_upgrade_is_not_a_hygiene_action():
    # "eco upgrades siphoner shower" was offered as hygiene and always failed its state
    # check, which left the sim with a one-item list (and then "do nothing").
    assert not is_usable("eco upgrades siphoner shower")
    assert not is_usable("eco upgrades siphoner bath tub")


def test_the_sink_crafting_process_does_not_count_as_washing():
    # "sink start crafting" matched hygiene because of the object word, and is not a wash.
    assert actions_for_needs(["Hygiene 0", "HygieneHands 0"], ["sink start crafting"]) == []
    assert actions_for_needs(["Hygiene 0"], ["sink wash hands"]) == ["sink wash hands"]


def test_the_hygiene_list_from_the_log_keeps_the_real_wash():
    entries = [("eco upgrades siphoner shower", None, None),
               ("sink start crafting", None, None),
               ("shower take", None, None)]
    labels = [c.label for c in build_candidates(entries)]
    assert labels == ["sink start crafting", "shower take"]
    assert lowest_need_actions(["Hygiene 0"], labels) == ("Hygiene 0", ["shower take"])


@pytest.mark.parametrize("entry,activity", [
    ("HygieneHands 0", "wash hands"),
    ("HygieneOral 4", "brush teeth"),
    ("Hygiene 0", "shower"),
    ("Bladder 12", "toilet"),
    ("Hunger 15", "eat"),
    ("Energy 8", "sleep"),
    ("Social 6", "chat"),
    ("Fun 20", None),
    ("Comfort 20", None),
    ("", None),
])
def test_each_pressing_need_has_an_activity_that_serves_it(entry, activity):
    assert need_activity_for(entry) == activity


@pytest.mark.parametrize("label,noise", [
    ("prototype", True),
    ("puddle small", True),
    ("fire ash", True),
    ("default jig", True),
    ("attractor point", True),
    ("shower sc1x1 01", False),
    ("fridge low 01", False),
    ("", True),
])
def test_objects_that_are_not_things_to_do_are_noise(label, noise):
    assert is_noise_object(label) is noise


# --- LLM fallback, buffs, everyday jobs ------------------------------------------------

def test_pick_random_has_nothing_to_pick_from_an_empty_list():
    assert pick_random([]) is None
    assert pick_random(None) is None


def test_pick_random_only_ever_returns_an_offered_choice():
    choices = ["sit", "read", "cook"]
    assert {pick_random(choices) for _ in range(50)} <= set(choices)
    assert pick_random(["only"]) == "only"


class Buff:
    """What the game's BuffComponent yields: the base class, whose type name is 'Buff'."""


class buff_BurningUp:
    pass


class buff_DirtySurroundings:
    pass


class buff_Grumpy:
    pass


def test_buffs_are_read_from_the_tuning_not_the_base_class():
    # 2026-10-27: every prompt said "Currently feeling: buff", hiding overheating from the model.
    burning, dirty = Buff(), Buff()
    burning.buff_type, dirty.buff_type = buff_BurningUp, buff_DirtySurroundings
    assert buff_names([burning, dirty]) == ["burning up", "dirty surroundings"]


def test_a_buff_without_a_tuning_uses_its_own_class_name():
    assert buff_names([buff_Grumpy()]) == ["grumpy"]
    assert buff_names([]) == []


def test_everyday_jobs_need_their_object_on_the_lot():
    assert everyday_actions(["fridge low 01", "mailbox", "computer low 01"]) == [
        "put food in fridge", "pay bills", "chat on the computer"]
    assert everyday_actions(["sit dining sc 01", "bed double sc 01"]) == []
    assert everyday_actions([]) == []


@pytest.mark.parametrize("name,chat", [
    ("phone_ChatWith", True),
    ("phone_CallSomeone", True),
    ("phone_TextSomeone", True),
    ("phone_CallPicker", False),          # asks "who?": a menu that pauses the game
    ("phone_InviteOverPicker", False),
    ("phone_BrowseWeb", False),
    ("phone_DebugDump", False),
    ("", False),
])
def test_only_direct_phone_interactions_are_used(name, chat):
    assert is_phone_chat(name) is chat
