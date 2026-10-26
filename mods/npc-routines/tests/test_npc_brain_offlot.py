import json

import pytest

from npc_brain import (NONE_ACTION, build_prompt, parse_choice, request_body, response_text,
                      response_thinking)
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


def test_prompt_lists_numbered_actions_plus_none():
    prompt, options = build_prompt(SIM, "wants to be a famous painter", ["paint", "read"])
    assert options == ["paint", "read", NONE_ACTION]
    assert "1. paint" in prompt and "2. read" in prompt and "3." in prompt
    assert "wants to be a famous painter" in prompt
    assert "Creative, Loner" in prompt
    assert "Goal to work towards" not in prompt


def test_prompt_includes_the_goal():
    prompt, _ = build_prompt(SIM, "wants to be a famous painter", ["paint"],
                             goal="open a gallery before her 40th birthday")
    assert "Goal to work towards: open a gallery before her 40th birthday" in prompt


def test_prompt_ignores_an_empty_goal():
    prompt, _ = build_prompt(SIM, "wants to be a famous painter", ["paint"], goal="")
    assert "Goal to work towards" not in prompt


@pytest.mark.parametrize("answer,expected", [
    ("1 - she wants to practise", ("paint", "she wants to practise")),
    ("2", ("read", "")),
    ("I choose 1. Practice makes perfect.", ("paint", "Practice makes perfect.")),
    ("3 - just relax", (NONE_ACTION, "just relax")),
])
def test_parse_choice(answer, expected):
    assert parse_choice(answer, ["paint", "read", NONE_ACTION]) == expected


@pytest.mark.parametrize("answer", ["", "paint please", "7 - out of range", "0"])
def test_parse_choice_rejects_invalid(answer):
    assert parse_choice(answer, ["paint", "read", NONE_ACTION]) == (None, None)


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
