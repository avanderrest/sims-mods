import json

import pytest

import npc_rules
from npc_rules import (Choice, RulesStore, condition_matches, evaluate, is_nothing,
                       list_rule_files, load_ruleset, match_action, need_key,
                       normalize_ruleset, resolve_rule_file)


def _state(**overrides):
    state = {
        "needs": {"bladder": 20, "hunger": 80, "energy": 45, "hygiene": 90},
        "skills": {"painting": 4, "logic": 1},
        "mood": "Uncomfortable",
        "buffs": ["dirty surroundings", "inspired"],
        "wants": ["paint a masterpiece"],
        "activity": ["sitting"],
        "weather": "cool, raining",
        "season": "fall",
        "day": "mon",
        "hour": 14,
    }
    state.update(overrides)
    return state


def test_the_players_example_picks_the_first_matching_rule():
    ruleset = normalize_ruleset({"rules": [
        {"if": {"need": "toilet", "below": 30}, "then": {"action": "use toilet", "minutes": 20}},
        {"if": {"skill": "painting", "above": 3}, "then": {"action": "paint", "minutes": 90}},
        {"if": {"emotion": "uncomfortable"}, "then": {"action": "nothing"}},
    ]})
    choice = evaluate(ruleset, _state(), ["use toilet", "paint", "practice painting"])
    assert choice.action == "use toilet"
    assert choice.minutes == 20
    assert choice.number == 1


def test_the_first_rule_that_matches_wins_even_when_later_ones_would_too():
    ruleset = normalize_ruleset({"rules": [
        {"if": {"need": "hunger", "above": 50}, "then": {"action": "eat"}},
        {"if": {"skill": "painting", "above": 0}, "then": {"action": "paint"}},
    ]})
    choice = evaluate(ruleset, _state(), ["eat", "paint", "practice painting"])
    assert choice.action == "eat"


def test_toilet_is_the_games_bladder_need():
    assert need_key("toilet") == "bladder"
    assert need_key("Toilet_Need") == "bladder"
    assert need_key("bladder") == "bladder"
    assert condition_matches({"need": "toilet", "below": 30}, _state())


def test_below_and_above_are_strict():
    state = _state(needs={"bladder": 30}, skills={"painting": 3})
    assert not condition_matches({"need": "bladder", "below": 30}, state)
    assert condition_matches({"need": "bladder", "below": 31}, state)
    assert not condition_matches({"skill": "painting", "above": 3}, state)
    assert condition_matches({"skill": "painting", "above": 2}, state)


def test_a_missing_need_never_matches():
    assert not condition_matches({"need": "toilet", "below": 100}, _state(needs={}))


def test_emotion_reads_the_mood():
    assert condition_matches({"emotion": "uncomfortable"}, _state())
    assert condition_matches({"mood": "Uncomfortable"}, _state())
    assert condition_matches({"emotion": "uncomfortable"}, _state(mood="Very Uncomfortable"))
    assert not condition_matches({"emotion": "inspired"}, _state())
    assert not condition_matches({"emotion": "comfortable"}, _state())


def test_buffs_wants_activity_weather_and_season():
    assert condition_matches({"buff": "inspired"}, _state())
    assert condition_matches({"want": "masterpiece"}, _state())
    assert condition_matches({"activity": "sit"}, _state())
    assert condition_matches({"weather": "raining"}, _state())
    assert condition_matches({"season": "fall"}, _state())
    assert not condition_matches({"buff": "angry"}, _state())
    assert not condition_matches({"weather": "snowing"}, _state(weather=""))


def test_days_and_hours():
    assert condition_matches({"day": "mon"}, _state())
    assert condition_matches({"day": 1}, _state())          # 0 = Sunday
    assert condition_matches({"day": ["sat", "mon"]}, _state())
    assert not condition_matches({"day": "tue"}, _state())
    assert condition_matches({"hour": 14}, _state())
    assert condition_matches({"hour_from": 9, "hour_to": 17}, _state())
    assert not condition_matches({"hour_from": 15, "hour_to": 17}, _state())
    # wrapping over midnight: 22:00 -> 06:00
    assert condition_matches({"hour_from": 22, "hour_to": 6}, _state(hour=2))
    assert not condition_matches({"hour_from": 22, "hour_to": 6}, _state(hour=12))


def test_time_string_is_enough_when_day_and_hour_are_missing():
    state = {"time": "wed 07:00"}
    assert condition_matches({"day": "wed", "hour": 7}, state)


def test_any_all_and_not():
    state = _state()
    assert condition_matches({"any": [{"need": "bladder", "below": 10},
                                      {"skill": "painting", "above": 3}]}, state)
    assert not condition_matches({"all": [{"need": "bladder", "below": 10},
                                          {"skill": "painting", "above": 3}]}, state)
    assert condition_matches({"not": {"need": "bladder", "below": 10}}, state)


def test_an_unavailable_action_is_skipped_for_the_next_rule():
    ruleset = normalize_ruleset({"rules": [
        {"if": {"need": "toilet", "below": 30}, "then": {"action": "use toilet"}},
        {"if": {"skill": "painting", "above": 3}, "then": {"action": "paint"}},
    ]})
    notes = []
    choice = evaluate(ruleset, _state(), ["practice painting"], notes)
    assert choice.action == "practice painting"
    assert choice.number == 2
    assert "not on this lot" in notes[0]


def test_nothing_leaves_it_to_the_game():
    ruleset = normalize_ruleset({"rules": [
        {"if": {"emotion": "uncomfortable"}, "then": {"action": "nothing", "minutes": 45}},
    ]})
    choice = evaluate(ruleset, _state(), ["eat"])
    assert isinstance(choice, Choice)
    assert choice.action is None
    assert choice.minutes == 45
    assert is_nothing("do nothing") and is_nothing("Do Nothing Special (normal life)")


def test_minutes_are_defaulted_and_clamped():
    ruleset = normalize_ruleset({"rules": [
        {"if": {"need": "toilet", "below": 100}, "then": {"action": "toilet"}},
        {"if": {"emotion": "uncomfortable"}, "then": {"action": "sleep", "minutes": 5000}},
    ]})
    first = evaluate(ruleset, _state(), ["toilet"])
    assert first.minutes == npc_rules.DEFAULT_RULE_MINUTES
    second = evaluate(normalize_ruleset({"rules": [
        {"if": {"emotion": "uncomfortable"}, "then": {"action": "sleep", "minutes": 5000}},
    ]}), _state(), ["sleep"])
    assert second.minutes == 480


def test_an_always_rule_needs_no_condition():
    ruleset = normalize_ruleset({"rules": [{"then": "sleep"}]})
    assert evaluate(ruleset, _state(), ["sleep"]).action == "sleep"


def test_match_action_understands_the_everyday_phrasings():
    assert match_action("use toilet", ["toilet use"]) == "toilet use"
    assert match_action("use toilet", ["toilet"]) == "toilet"
    assert match_action("paint", ["practice painting"]) == "practice painting"
    assert match_action("paint", ["paint", "practice painting"]) == "paint"
    assert match_action("water the plants", ["water plants"]) == "water plants"
    assert match_action("paint", ["chess"]) is None


@pytest.mark.parametrize("bad,message", [
    ({"not_rules": []}, "rules"),
    ({"rules": [{"if": {"nope": 1}, "then": "sleep"}]}, "unknown condition"),
    ({"rules": [{"if": {"need": "toilet"}, "then": "toilet"}]}, "below"),
    ({"rules": [{"then": {}}]}, "action"),
    ({"rules": [{"then": {"action": "sleep", "minutes": 0}}]}, "positive"),
    ({"rules": [{"then": "sleep", "surprise": 1}]}, "unknown key"),
    ({"rules": [{"if": {"day": "funday"}, "then": "sleep"}]}, "day"),
])
def test_a_typo_is_reported(bad, message):
    with pytest.raises(ValueError) as error:
        normalize_ruleset(bad)
    assert message in str(error.value)


def test_a_rule_file_round_trips_and_reports_its_source(tmp_path):
    path = tmp_path / "painter.json"
    path.write_text(json.dumps({"name": "painter", "rules": [{"then": "paint"}]}),
                    encoding="utf-8")
    ruleset = load_ruleset(str(path))
    assert ruleset["name"] == "painter"
    assert ruleset["source"] == "painter.json"
    assert ruleset["rules"][0]["then"]["action"] == "paint"


def test_a_broken_json_file_says_so(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError) as error:
        load_ruleset(str(path))
    assert "not valid JSON" in str(error.value)


def test_rule_files_are_found_by_short_name(tmp_path):
    (tmp_path / "painter.json").write_text('{"rules": []}', encoding="utf-8")
    assert list_rule_files(str(tmp_path)) == ["painter"]
    assert resolve_rule_file("painter", str(tmp_path)) == str(tmp_path / "painter.json")
    assert resolve_rule_file("painter.json", str(tmp_path)) == str(tmp_path / "painter.json")
    with pytest.raises(ValueError) as error:
        resolve_rule_file("missing", str(tmp_path))
    assert "painter" in str(error.value)


def test_the_store_saves_what_a_sim_runs_and_skips_a_broken_entry(tmp_path):
    path = tmp_path / "npc_rules.json"
    store = RulesStore()
    store.assign(111, normalize_ruleset({"rules": [{"then": "sleep"}]}))
    store.save(str(path))

    loaded = RulesStore()
    loaded.load(str(path))
    assert loaded.has(111)
    assert loaded.get(111)["rules"][0]["then"]["action"] == "sleep"
    assert not path.with_name("npc_rules.json.tmp").exists()
    path.write_text(json.dumps({"sims": {"111": {"rules": [{"then": "eat"}]},
                                         "222": {"rules": [{"if": {"nope": 1}, "then": "x"}]}}}),
                    encoding="utf-8")
    loaded = RulesStore()
    loaded.load(str(path))
    assert loaded.get(111)["rules"][0]["then"]["action"] == "eat"
    assert loaded.get(222) is None

    loaded.remove(111)
    assert not loaded.has(111)
