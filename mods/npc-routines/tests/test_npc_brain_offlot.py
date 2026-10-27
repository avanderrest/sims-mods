import json

import pytest

from npc_brain import (NONE_ACTION, REQUEST_ACTION, build_prompt, clean_reason, parse_answer,
                      prompt_summary, request_body, response_text, response_thinking)
from npc_offlot import OFFLOT_SHARE_PER_HOUR, offlot_points


# --- off-lot results ---

def test_offlot_points_share_of_a_level():
    assert offlot_points("paint", level_points=1000, current_points=0, max_points=10000) == \
        pytest.approx(1000 * OFFLOT_SHARE_PER_HOUR)


def test_offlot_points_scale_with_hours():
    one = offlot_points("workout", 1000, 0, 10000, hours=1)
    assert offlot_points("workout", 1000, 0, 10000, hours=3) == pytest.approx(3 * one)


def test_offlot_points_capped_at_max():
    assert offlot_points("chess", 1000, 9990, 10000) == 10


def test_reading_trains_no_skill():
    assert offlot_points("read", 1000, 0, 10000) == 0


def test_maxed_skill_gets_nothing():
    assert offlot_points("jog", 0, 10000, 10000) == 0


# --- LLM prompt and answers ---

SIM = {"name": "Mira Lee", "age": "adult", "traits": ["Creative", "Loner"], "mood": "Inspired",
       "needs": {"Hunger": 80}, "skills": {"Painting": 4}, "job": None, "time": "mon 10:00"}


def test_prompt_lists_numbered_actions_plus_request_and_none():
    prompt, options = build_prompt(SIM, "wants to be a famous painter", ["paint", "read"])
    assert options == ["paint", "read", REQUEST_ACTION, NONE_ACTION]
    assert "1. paint" in prompt and "2. read" in prompt and "4." in prompt
    assert "wants to be a famous painter" in prompt
    assert "Creative, Loner" in prompt
    assert "Goal to work towards" not in prompt


def test_prompt_lists_the_objects_on_the_lot_first():
    prompt, _ = build_prompt(SIM, "wants to be a famous painter", ["paint"],
                             objects=["easel", "bookshelf"])
    assert "You have access to: easel, bookshelf" in prompt
    assert prompt.index("You have access to") < prompt.index("Character:")


def test_follow_up_prompt_has_no_request_option():
    # After the model asked for an object, it is asked again without that escape hatch.
    prompt, options = build_prompt(SIM, "wants to be a famous painter", ["paint"],
                                   allow_request=False)
    assert options == ["paint", NONE_ACTION]
    assert REQUEST_ACTION not in prompt


def test_prompt_asks_for_a_wait_after_the_choice():
    prompt, _ = build_prompt(SIM, "wants to be a famous painter", ["paint"])
    assert "how many minutes to do it for" in prompt
    assert "5 to 480" in prompt


def test_prompt_includes_the_emotion_detail_and_wants():
    sim = dict(SIM, mood_intensity=2, buffs=["inspired", "dirty surroundings"],
               wants=["paint a masterpiece"])
    prompt, _ = build_prompt(sim, "wants to be a famous painter", ["paint"])
    assert "Mood: Inspired (intensity 2)" in prompt
    assert "Currently feeling: inspired, dirty surroundings" in prompt
    assert "Wants right now: paint a masterpiece" in prompt


def test_prompt_omits_emotion_detail_and_wants_when_there_are_none():
    prompt, _ = build_prompt(SIM, "wants to be a famous painter", ["paint"])
    assert "Mood: Inspired" in prompt
    assert "intensity" not in prompt
    assert "Currently feeling" not in prompt
    assert "Wants right now" not in prompt


def test_prompt_groups_the_options_by_category():
    prompt, options = build_prompt(SIM, "wants to be a famous painter",
                                   ["fridge cook", "bed nap", "tv watch"])
    assert "Eat and drink:" in prompt
    assert "Rest and comfort:" in prompt
    assert "Fun and hobbies:" in prompt
    assert "Always available:" in prompt
    # Numbering stays global, so the answer maps straight onto options.
    assert "  1. fridge cook" in prompt
    assert "  2. bed nap" in prompt
    assert "  3. tv watch" in prompt
    assert options == ["fridge cook", "bed nap", "tv watch", REQUEST_ACTION, NONE_ACTION]
    assert prompt.index("Eat and drink:") < prompt.index("Rest and comfort:") < \
        prompt.index("Fun and hobbies:")


def test_prompt_has_the_season_but_no_weather_line():
    # Weather only appears on the outdoor option itself ("jog in the rain").
    sim = dict(SIM, activity=["tv watch"], weather="cool, raining", season="fall")
    prompt, _ = build_prompt(sim, "wants to be a famous painter", ["paint"])
    assert "Currently doing: tv watch" in prompt
    assert "Season: fall" in prompt
    assert "Weather:" not in prompt
    assert "weather" not in prompt.lower()


def test_prompt_names_who_else_is_around():
    sim = dict(SIM, nearby=["Bruno (dog)", "Alice (visitor or service npc)"])
    prompt, _ = build_prompt(sim, "wants to be a famous painter", ["paint"])
    assert "Nearby: Bruno (dog), Alice (visitor or service npc)" in prompt


def test_prompt_includes_the_goal():
    prompt, _ = build_prompt(SIM, "wants to be a famous painter", ["paint"],
                             goal="open a gallery before her 40th birthday")
    assert "Goal to work towards: open a gallery before her 40th birthday" in prompt


def test_prompt_ignores_an_empty_goal():
    prompt, _ = build_prompt(SIM, "wants to be a famous painter", ["paint"], goal="")
    assert "Goal to work towards" not in prompt


@pytest.mark.parametrize("answer,expected", [
    ("1 90 - she wants to practise", ("paint", 90, "she wants to practise")),
    ("2 15 snack", ("read", 15, "snack")),
    ("1", ("paint", 60, "")),
    ("I choose 1. Practice makes perfect.", ("paint", 60, "Practice makes perfect.")),
    ("4 - just relax", (NONE_ACTION, 60, "just relax")),
    ("3 30 - needs an easel", (REQUEST_ACTION, 30, "needs an easel")),
])
def test_parse_answer_choice_minutes_reason(answer, expected):
    options = ["paint", "read", REQUEST_ACTION, NONE_ACTION]
    assert parse_answer(answer, options) == expected


@pytest.mark.parametrize("answer", ["", "paint please", "9 - out of range", "0"])
def test_parse_answer_rejects_invalid(answer):
    options = ["paint", "read", REQUEST_ACTION, NONE_ACTION]
    assert parse_answer(answer, options) == (None, None, None)


@pytest.mark.parametrize("answer,minutes", [
    ("1 1 - too short", 5),
    ("1 9999 - far too long", 480),
    ("1 0 - never", 5),
])
def test_parse_answer_clamps_the_wait(answer, minutes):
    assert parse_answer(answer, ["paint"])[1] == minutes


def test_ollama_request_and_response():
    url = "http://localhost:11434/api/generate"
    body = json.loads(request_body(url, "llama3.2", "hi"))
    assert body["prompt"] == "hi" and body["stream"] is False
    assert "think" not in body
    assert response_text(url, json.dumps({"response": "1 - ok"})) == "1 - ok"


def test_thinking_is_requested_and_read():
    url = "http://localhost:11434/api/generate"
    body = json.loads(request_body(url, "qwen3:4b", "hi", think=True))
    assert body["think"] is True
    assert response_thinking(url, json.dumps({"response": "", "thinking": "weighing options"})) == \
        "weighing options"
    assert response_thinking(url, json.dumps({"response": "1 - ok"})) == ""


def test_openai_style_request_and_response():
    url = "http://localhost:1234/v1/chat/completions"
    body = json.loads(request_body(url, "local", "hi"))
    assert body["messages"][0]["content"] == "hi"
    answer = {"choices": [{"message": {"content": "2 - ok"}}]}
    assert response_text(url, json.dumps(answer)) == "2 - ok"


def test_prompt_points_out_a_goal_the_lot_cannot_serve():
    prompt, _ = build_prompt(SIM, "wants to be a famous painter", ["sit", "tv watch"],
                             goal="become a famous painter",
                             missing=["painting (e.g. an easel, a sketchpad)"])
    assert "Nothing on this lot can be used for painting (e.g. an easel, a sketchpad)." in prompt
    assert "Ask the player for something you could use." in prompt
    assert "is there anything here I could paint with?" in prompt


def test_prompt_summary_leaves_out_the_option_list():
    prompt, _ = build_prompt(SIM, "wants to be a famous painter", ["sit", "tv watch"],
                             goal="become a famous painter")
    summary = prompt_summary(prompt)
    assert "Character: Mira Lee" in summary
    assert "Goal to work towards: become a famous painter" in summary
    assert "1. sit" not in summary and "Always available" not in summary
    assert len(summary) < len(prompt)


def test_prompt_says_what_to_prioritise():
    prompt, _ = build_prompt(SIM, "wants to be a famous painter", ["fetch water", "clean counter"])
    assert "How to choose, most important first:" in prompt
    assert "A need below 30" in prompt
    assert "Working towards the goal." in prompt
    assert "A current want." in prompt


def test_prompt_names_the_pressing_needs():
    sim = dict(SIM, pressing=["Hunger 12", "Bladder 27"])
    prompt, _ = build_prompt(sim, "x", ["fridge cook"])
    assert "Pressing needs: Hunger 12, Bladder 27" in prompt


def test_prompt_has_no_pressing_line_when_needs_are_fine():
    prompt, _ = build_prompt(SIM, "x", ["fridge cook"])
    assert "Pressing needs" not in prompt


def test_a_blocked_goal_keeps_the_whole_list():
    # The mod asks the player itself, so the model still gets everything to choose from.
    prompt, options = build_prompt(SIM, "wants to be a famous painter", ["sit", "tv watch"],
                                   goal="become a famous painter",
                                   missing=["painting (e.g. an easel)"])
    assert options == [REQUEST_ACTION, "sit", "tv watch", NONE_ACTION]
    assert "Needs the player:" in prompt
    assert "Rest and comfort:" in prompt


def test_a_blocked_goal_still_offers_actions_when_a_need_is_urgent():
    sim = dict(SIM, pressing=["Hunger 12"])
    prompt, options = build_prompt(sim, "wants to be a famous painter",
                                   ["fridge cook", "sit"], goal="become a famous painter",
                                   missing=["painting"])
    assert options[0] == REQUEST_ACTION
    assert "fridge cook" in options and "sit" in options


def test_the_follow_up_after_asking_does_not_ask_again():
    prompt, options = build_prompt(SIM, "wants to be a famous painter", ["fridge cook"],
                                   goal="become a famous painter", missing=["painting"],
                                   allow_request=False)
    assert REQUEST_ACTION not in options
    assert "The player has been asked for it" in prompt
    assert "ask-the-player option" not in prompt


def test_no_description_line_when_the_player_gave_none():
    prompt, _ = build_prompt(SIM, None, ["sit"])
    assert "The player's description of this character" not in prompt
    assert "(not given)" not in prompt

    prompt, _ = build_prompt(SIM, "loves art", ["sit"])
    assert "The player's description of this character: loves art" in prompt


def test_carrying_is_shown():
    sim = dict(SIM, inventory=["tomato", "potato"])
    prompt, _ = build_prompt(sim, "x", ["plant", "sit"])
    assert "Carrying: tomato, potato" in prompt


def test_a_blocked_goal_still_allows_a_want_it_can_do():
    sim = dict(SIM, wants=["plant something"])
    prompt, options = build_prompt(sim, "x", ["plant veg", "sit"],
                                   goal="become a famous painter", missing=["painting"])
    assert options == [REQUEST_ACTION, "plant veg", "sit", NONE_ACTION]


@pytest.mark.parametrize("answer,reason", [
    ("13 60 - wants to paint. Do not explain further.",
     "wants to paint."),
    ("13 60 - wants to paint. DO NOT EXPLAIN FURTHER", "wants to paint."),
    ("13 60 - read a book", "read a book"),
])
def test_instruction_text_is_stripped_from_the_reason(answer, reason):
    assert parse_answer(answer, ["x"] * 13)[2] == reason


def test_clean_reason_leaves_normal_text_alone():
    assert clean_reason("she wants to practise") == "she wants to practise"


def test_prompt_says_when_the_goal_is_blocked_but_present():
    prompt, _ = build_prompt(SIM, "x", ["sit"], goal="become a famous painter",
                             missing=[], blocked=["painting (e.g. an easel)"])
    assert "Nothing here can be used for painting (e.g. an easel) right now" in prompt
    assert "Work on a want" in prompt


def test_a_pressing_need_tells_the_model_not_to_do_nothing():
    sim = dict(SIM, pressing=["Hygiene 0"])
    prompt, _ = build_prompt(sim, "", ["shower", "read"])
    assert "Pressing needs: Hygiene 0" in prompt
    assert "do not pick 'do nothing'" in prompt


def test_without_a_pressing_need_there_is_no_such_instruction():
    prompt, _ = build_prompt(SIM, "", ["shower", "read"])
    assert "do not pick 'do nothing'" not in prompt
