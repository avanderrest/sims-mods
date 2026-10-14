import json

import pytest

from scenario_logic import (ScenarioError, describe_goal, evaluate, goal_value, new_progress, open_goals,
                            outcome, parse, validate)

RAGS = {
    "name": "Rags to Riches",
    "start": {"money": 0, "traits": {"all": ["trait_Ambitious"]}, "skills": {"active": {"Painting": 2}},
              "remove_careers": True},
    "rules": [{"type": "no_career"}],
    "goals": [
        {"id": "art", "type": "skill", "skill": "Painting", "level": 6, "reward": {"money": 1000}},
        {"id": "rich", "type": "household_money", "amount": 50000},
        {"id": "home", "type": "home_value", "amount": 100000, "requires": ["rich"]},
    ],
    "deadline_days": 28,
}


def facts(**kw):
    base = {"day": 0, "money": 0, "home_value": 0, "household_size": 1, "children": 0, "active": 1,
            "sims": {1: {"skills": {}, "careers": [], "friendship": 0, "romance": 0, "married": False,
                         "aspirations": []}}}
    base.update(kw)
    return base


def test_example_file_is_valid_and_warns_about_rules():
    scenario, warnings = parse(json.dumps(RAGS))
    assert scenario["name"] == "Rags to Riches"
    assert any("phase 2" in w for w in warnings)


@pytest.mark.parametrize("change, message", [
    ({"name": ""}, "name"),
    ({"goals": []}, "goals"),
    ({"goals": [{"id": "a", "type": "fly"}]}, "unknown type"),
    ({"goals": [{"id": "a", "type": "skill", "level": 3}]}, "\"skill\""),
    ({"goals": [{"id": "a", "type": "day", "day": 3, "requires": ["b"]}]}, "requires unknown"),
    ({"goals": [{"id": "a", "type": "day", "day": 3}, {"id": "a", "type": "day", "day": 4}]}, "twice"),
    ({"goals": [{"id": "a", "type": "relationship", "level": "soulmate"}]}, "relationship level"),
    ({"start": {"cash": 5}}, "unknown \"cash\""),
    ({"deadline_days": -1}, "deadline"),
    ({"win": ["nope"]}, "win"),
])
def test_broken_files_are_refused_with_the_reason(change, message):
    data = dict(RAGS, **change)
    with pytest.raises(ScenarioError) as e:
        validate(data)
    assert message in str(e.value)


def test_bad_json_is_refused():
    with pytest.raises(ScenarioError):
        parse("{not json")


def test_requires_hides_goals_until_done():
    assert [g["id"] for g in open_goals(RAGS, [])] == ["art", "rich"]
    assert [g["id"] for g in open_goals(RAGS, ["rich"])] == ["art", "home"]


def test_evaluate_ticks_goals_and_chains_requirements():
    progress = new_progress(RAGS, "rags", 0, 1)
    f = facts(money=60000, home_value=150000)
    newly, result = evaluate(RAGS, progress, f)
    assert newly == ["rich", "home"]
    assert result is None


def test_win_when_all_goals_done_and_lose_after_deadline():
    assert outcome(RAGS, ["art", "rich", "home"], day=3) == "won"
    assert outcome(RAGS, ["art"], day=28) == "lost"
    assert outcome(RAGS, ["art"], day=27.9) is None
    assert outcome(dict(RAGS, win=["art"]), ["art"], day=1) == "won"


def test_finished_scenario_is_not_evaluated():
    progress = dict(new_progress(RAGS, "rags", 0, 1), state="won")
    assert evaluate(RAGS, progress, facts(money=10 ** 6)) == ([], None)


def test_who_any_all_active():
    f = facts(active=1, sims={1: {"skills": {"Painting": 2}}, 2: {"skills": {"painting": 7}}})
    goal = {"id": "g", "type": "skill", "skill": "Painting", "level": 6}
    assert goal_value(goal, f) == (7, 6)
    assert goal_value(dict(goal, who="all"), f) == (2, 6)
    assert goal_value(dict(goal, who="active"), f) == (2, 6)


def test_career_relationship_aspiration_size_day():
    f = facts(day=10.5, household_size=4, children=2, sims={1: {
        "careers": [["career_Adult_Painter", 5]], "friendship": 65, "romance": 10, "married": True,
        "aspirations": ["Track_Nature_A"]}})
    assert goal_value({"type": "career_level", "career": "painter", "level": 4}, f) == (5, 4)
    assert goal_value({"type": "career_level", "level": 4}, f) == (5, 4)          # any career
    assert goal_value({"type": "career_level", "career": "doctor", "level": 1}, f) == (0, 1)
    assert goal_value({"type": "relationship", "level": "good_friend"}, f) == (65, 60)
    assert goal_value({"type": "relationship", "level": "partner"}, f) == (10, 50)
    assert goal_value({"type": "relationship", "level": "married"}, f) == (1, 1)
    assert goal_value({"type": "aspiration", "aspiration": "track_nature_a"}, f) == (1, 1)
    assert goal_value({"type": "household_size", "amount": 3}, f) == (4, 3)
    assert goal_value({"type": "household_size", "amount": 3, "children": True}, f) == (2, 3)
    assert goal_value({"type": "day", "day": 10}, f) == (10, 10)


def test_custom_goals_are_never_met_automatically():
    scenario = dict(RAGS, goals=[{"id": "c", "type": "custom"}])
    assert evaluate(scenario, new_progress(scenario, "x", 0, 1), facts(money=10 ** 9)) == ([], None)


def test_describe_goal_shows_progress():
    goal = {"id": "art", "type": "skill", "skill": "Painting", "level": 6}
    assert describe_goal(goal, facts(sims={1: {"skills": {"Painting": 4}}})) == "art: Painting level 6 - 4/6"
    assert describe_goal(dict(goal, description="Become a painter")) == "art: Become a painter"


def test_shipped_example_scenarios_are_valid():
    from pathlib import Path
    files = sorted((Path(__file__).resolve().parent.parent / "install" / "scenarios").glob("*.json"))
    assert files
    for f in files:
        parse(f.read_text(encoding="utf-8"))
