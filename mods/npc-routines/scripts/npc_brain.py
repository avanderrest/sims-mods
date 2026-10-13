"""NPC Routines phase 4 - the optional local-LLM "brain", pure logic (no game imports).

The player writes free-text instructions for a sim ("ambitious loner, wants to become a
famous painter"). When the sim has nothing on their routine, the mod asks a local LLM
server (Ollama or LM Studio, on this computer) to pick ONE action from a numbered list.
The model can only choose from that list; anything else is ignored.

This file builds the prompt and reads the answer; npc_llm.py does the HTTP call (in a
background thread) and npc_main.py applies the choice on the game's own thread.
"""
import json
import re

NONE_ACTION = "none"   # "let the game's normal autonomy decide"

DEFAULT_URL = "http://localhost:11434/api/generate"   # Ollama's default
DEFAULT_MODEL = "llama3.2"


def build_prompt(sim, instructions, actions):
    """sim: dict with name, age, traits, mood, needs, skills, job, time (all plain text/numbers).
    actions: list of action keys; NONE_ACTION is added at the end automatically."""
    options = list(actions) + [NONE_ACTION]
    lines = [
        "You decide what a character in The Sims 4 does next. Answer with ONE number from the list",
        "and a short reason, exactly like: 2 - she wants to practise before her exhibition",
        "",
        "Character: {}".format(sim.get("name", "?")),
        "Age group: {}".format(sim.get("age", "?")),
        "Personality: {}".format(", ".join(sim.get("traits", ())) or "unknown"),
        "Mood: {}".format(sim.get("mood", "unknown")),
        "Needs (0 = desperate, 100 = fine): {}".format(
            ", ".join("{} {}".format(k, v) for k, v in sorted(sim.get("needs", {}).items())) or "unknown"),
        "Skills: {}".format(", ".join("{} {}".format(k, v) for k, v in sorted(sim.get("skills", {}).items())) or "none"),
        "Job: {}".format(sim.get("job") or "none"),
        "Time: {}".format(sim.get("time", "?")),
        "",
        "The player's description of this character: {}".format(instructions),
        "",
        "Choose one:",
    ]
    for i, action in enumerate(options, 1):
        label = "do nothing special (normal life)" if action == NONE_ACTION else action
        lines.append("{}. {}".format(i, label))
    return "\n".join(lines), options


def parse_choice(text, options):
    """Returns (action, reason) from the model's answer, or (None, None) if it didn't pick a
    valid number."""
    if not text:
        return None, None
    match = re.search(r"\b(\d{1,2})\b", text)
    if not match:
        return None, None
    number = int(match.group(1))
    if not 1 <= number <= len(options):
        return None, None
    reason = text[match.end():].lstrip(" .:-–—\n\t").rstrip()
    return options[number - 1], reason[:200]


def request_body(url, model, prompt):
    """JSON body for Ollama's /api/generate, or an OpenAI-style /v1/chat/completions server
    (LM Studio, llama.cpp, ...)."""
    if "/chat/completions" in url:
        return json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                           "temperature": 0.7, "max_tokens": 80})
    return json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.7, "num_predict": 80}})


def response_text(url, body_text):
    data = json.loads(body_text)
    if "/chat/completions" in url:
        return data["choices"][0]["message"]["content"]
    return data.get("response", "")
