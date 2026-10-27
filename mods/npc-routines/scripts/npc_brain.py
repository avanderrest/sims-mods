"""NPC Routines phase 4 - the optional local-LLM "brain", pure logic (no game imports).

The player writes free-text instructions for a sim ("ambitious loner, wants to become a
famous painter"). When the sim has nothing on their routine, the mod asks a local LLM
server (Ollama or LM Studio, on this computer) to pick ONE action from a numbered list of
what is actually available on the lot, and how long to do it for. The model can only choose
from that list; anything else is ignored.

This file builds the prompt and reads the answer; npc_llm.py does the HTTP call (in a
background thread) and npc_main.py applies the choice on the game's own thread.
"""
import json
import re

from npc_actions import (CATEGORIES, OTHER_CATEGORY, DEFAULT_WAIT_MINUTES, MAX_WAIT_MINUTES,
                         MIN_WAIT_MINUTES, category_for, clamp_minutes, weather_note)

NONE_ACTION = "none"   # "let the game's normal autonomy decide"
# The mod cannot buy or place objects, so the model gets one way to say what the lot is
# missing; the player is told about it in a notification.
REQUEST_ACTION = "ask the player for an object that would help"

# The numbered list starts here, so the log can show the situation without the whole list.
LIST_HEADING = "Choose one numbered option:"

DEFAULT_URL = "http://localhost:11434/api/generate"   # Ollama's default
DEFAULT_MODEL = "qwen2.5:3b-instruct"


def _option_groups(options, request_first=False):
    """The numbered options, grouped for reading: heading -> [(number, label)]. Numbers are
    the position in `options`, so the answer still maps straight onto it."""
    always = [(number, action) for number, action in enumerate(options, 1)
              if action in (REQUEST_ACTION, NONE_ACTION)]
    groups = {}
    for number, action in enumerate(options, 1):
        if action in (REQUEST_ACTION, NONE_ACTION):
            continue
        groups.setdefault(category_for(action), []).append((number, action))
    ordered = []
    if request_first:
        ask = [pair for pair in always if pair[1] == REQUEST_ACTION]
        if ask:
            ordered.append(("Needs the player", ask))
    for name, _keywords in CATEGORIES:
        if name in groups:
            ordered.append((name, groups.pop(name)))
    if OTHER_CATEGORY in groups:
        ordered.append((OTHER_CATEGORY, groups.pop(OTHER_CATEGORY)))
    rest = [pair for pair in always if not (request_first and pair[1] == REQUEST_ACTION)]
    if rest:
        ordered.append(("Always available", rest))
    return ordered


def prompt_summary(prompt):
    """The prompt without the numbered options: what the log shows each time. The full prompt
    is still available through `houserules.npc.think`."""
    head, _separator, _list = str(prompt or "").partition("\n" + LIST_HEADING)
    return head.rstrip()


def build_prompt(sim, instructions, actions, goal=None, objects=None, allow_request=True,
                 missing=None, blocked=None):
    """sim: dict with name, age, traits, mood, needs, skills, job, time (all plain text/numbers),
    plus optional mood_intensity, buffs, wants (whims), activity (what they are doing now),
    weather and season.
    actions: list of thing labels the sim could do right now; NONE_ACTION is added last.
    goal: what the sim is currently working towards (optional, free text).
    objects: names of the objects on the lot, so the model knows what it has to work with.
    allow_request: off for the follow-up question after an object request, so the model has
    to pick something to actually do now.
    missing: things the goal is about that this lot cannot do at all (e.g. "painting"), so
    the model asks the player instead of picking something unrelated.
    blocked: things the goal is about that the lot *has* but that cannot be started right now
    (an easel while the sim is not in the mood for it)."""
    requests_the_player = bool(missing) and allow_request
    # The whole list stays available: when the goal is blocked the mod has already asked the
    # player itself (see npc_main), so the model is free to pick something useful meanwhile.
    options = list(actions)
    if allow_request:
        options = ([REQUEST_ACTION] + options) if missing else (options + [REQUEST_ACTION])
    options = options + [NONE_ACTION]
    mood = sim.get("mood", "unknown")
    intensity = sim.get("mood_intensity")
    if isinstance(intensity, int) and intensity > 0:
        mood = "{} (intensity {})".format(mood, intensity)
    # The answer format comes first: when it sat under the numbered list, the model copied the
    # "10 for a quick snack" example as if it were an option. The toolbox goes up here too, so
    # the model reads what it has before it reads who the sim is.
    lines = [
        "You decide what a character in The Sims 4 does next.",
        "Pick one option from the list at the end, then how many minutes to do it for",
        "({} to {}), then one short sentence of reason (at most 15 words, nothing else).".format(
            MIN_WAIT_MINUTES, MAX_WAIT_MINUTES),
        "Answer like: 2 90 - she wants to practise before her exhibition",
        "Use 10 minutes for a quick snack, 60 for a normal activity, 480 for sleeping.",
    ]
    if allow_request:
        lines += [
            "If the goal needs something the list does not offer, choose the option to ask the",
            "player instead of an unrelated action, and say what you would use it for - like",
            "\"is there anything here I could paint with?\"",
        ]
    lines += [
        "How to choose, most important first:",
        "1. A need below 30 (very uncomfortable) - deal with that first.",
    ]
    if allow_request:
        lines += [
            "2. Working towards the goal. If the goal needs something this list does not offer,",
            "   working on it means the ask-the-player option - take that one.",
        ]
    else:
        lines.append("2. Working towards the goal as best you can with what is here.")
    lines += [
        "3. A current want.",
        "4. Anything else that fits the time of day and mood.",
        "",
    ]
    if sim.get("pressing"):
        # Without this the model answered "do nothing special (normal life)" while a need
        # sat at 0 (2026-10-27), even when the list had a shower on it.
        lines += [
            "A need listed as pressing is below 30: deal with it and do not pick 'do nothing'",
            "while one of them is that low.",
            "",
        ]
    if objects:
        lines.append("You have access to: {}".format(", ".join(objects)))
        lines.append("")
    lines += [
        "Character: {}".format(sim.get("name", "?")),
        "Age group: {}".format(sim.get("age", "?")),
        "Personality: {}".format(", ".join(sim.get("traits", ())) or "unknown"),
        "Mood: {}".format(mood),
    ]
    if sim.get("pressing"):
        lines.append("Pressing needs: {}".format(", ".join(sim["pressing"])))
    if sim.get("buffs"):
        lines.append("Currently feeling: {}".format(", ".join(sim["buffs"])))
    if sim.get("activity"):
        lines.append("Currently doing: {}".format(", ".join(sim["activity"])))
    if sim.get("nearby"):
        lines.append("Nearby: {}".format(", ".join(sim["nearby"])))
    if sim.get("inventory"):
        lines.append("Carrying: {}".format(", ".join(sim["inventory"])))
    lines += [
        "Needs (0 = desperate, 100 = fine): {}".format(
            ", ".join("{} {}".format(k, v) for k, v in sorted(sim.get("needs", {}).items())) or "unknown"),
        "Skills: {}".format(", ".join("{} {}".format(k, v) for k, v in sorted(sim.get("skills", {}).items())) or "none"),
        "Job: {}".format(sim.get("job") or "none"),
        "Time: {}".format(sim.get("time", "?")),
    ]
    # No general "Weather:" line on purpose: it made the weather look like a problem. The
    # outdoor options say it themselves ("jog in the rain").
    if sim.get("season"):
        lines.append("Season: {}".format(sim["season"]))
    lines.append("")
    if goal:
        lines.append("Goal to work towards: {}".format(goal))
    if missing:
        lines.append("Nothing on this lot can be used for {}.".format(", ".join(missing)))
        lines.append("Ask the player for something you could use." if allow_request else
                     "The player has been asked for it; meanwhile choose something else useful.")
    elif blocked:
        lines.append("Nothing here can be used for {} right now - the things are there, but "
                     "the sim cannot start them as they are.".format(", ".join(blocked)))
        lines.append("Work on a want (getting focused may help) or something useful instead.")
    if sim.get("wants"):
        lines.append("Wants right now: {}".format(", ".join(sim["wants"])))
    if instructions:
        lines.append("The player's description of this character: {}".format(instructions))
    lines += [
        "",
        LIST_HEADING,
    ]
    for heading, members in _option_groups(options, request_first=requests_the_player):
        lines.append("{}:".format(heading))
        for number, action in members:
            if action == NONE_ACTION:
                label = "do nothing special (normal life)"
            elif action == REQUEST_ACTION:
                label = action
            else:
                label = action + weather_note(action, sim.get("weather"))
            lines.append("  {}. {}".format(number, label))
    return "\n".join(lines), options


# Instruction phrases a model sometimes copies into its answer; they must not end up in the
# in-game notification.
BOILERPLATE = ("do not explain further", "don't explain further", "do not explain",
               "no explanation needed", "nothing else")


def clean_reason(reason):
    """The reason without any instruction text the model echoed back."""
    text = str(reason or "")
    lowered = text.lower()
    for phrase in BOILERPLATE:
        index = lowered.find(phrase)
        if index != -1:
            text = text[:index]
            lowered = text.lower()
    return text.strip(" ;:,-–—")


def parse_answer(text, options):
    """Returns (action, minutes, reason) from the model's answer, or (None, None, None) if it
    didn't pick a valid number. Minutes is None when the model left them out; the caller
    clamps/defaults it."""
    if not text:
        return None, None, None
    match = re.search(r"\b(\d{1,2})\b", text)
    if not match:
        return None, None, None
    number = int(match.group(1))
    if not 1 <= number <= len(options):
        return None, None, None
    rest = text[match.end():]
    # The wait is written right after the choice ("3 90 - ..."). A dash there means the model
    # used the older "3 - reason" shape, so fall back to the default wait.
    minutes_match = re.match(r"\s+(\d{1,4})\b", rest)
    if minutes_match:
        minutes = clamp_minutes(minutes_match.group(1))
        reason = rest[minutes_match.end():]
    else:
        minutes = DEFAULT_WAIT_MINUTES
        reason = rest
    reason = clean_reason(reason.lstrip(" .,:;-–—\n\t"))
    return options[number - 1], minutes, reason[:200]


def request_body(url, model, prompt, think=False):
    """JSON body for Ollama's /api/generate, or an OpenAI-style /v1/chat/completions server
    (LM Studio, llama.cpp, ...). think asks a reasoning model to return its working too."""
    if "/chat/completions" in url:
        return json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                           "temperature": 0.7, "max_tokens": 64})
    # num_ctx is small on purpose: the prompt is a few hundred tokens, and Ollama's 32k
    # default reserves several GB of KV cache, which pushes layers off a 16 GB card onto the
    # CPU.
    body = {"model": model, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.7, "num_predict": 64, "num_ctx": 2048}}
    if think:
        body["think"] = True
    return json.dumps(body)


def response_text(url, body_text):
    data = json.loads(body_text)
    if "/chat/completions" in url:
        return data["choices"][0]["message"]["content"]
    return data.get("response", "")


def response_thinking(url, body_text):
    """A reasoning model's working, when it returned one (empty for ordinary models)."""
    try:
        data = json.loads(body_text)
    except Exception:
        return ""
    if "/chat/completions" in url:
        return data["choices"][0]["message"].get("reasoning_content") or ""
    return data.get("thinking") or ""
