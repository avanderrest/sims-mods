"""NPC Routines phase 4 - talking to a local LLM server, off the game's thread.

ask() starts a background thread that POSTs the prompt and puts the answer in a queue.
take_answers() is called from the hourly tick (the game's own thread) to collect them -
game state must only ever be touched from that thread. If the server isn't running, the
request just fails quietly and the sim falls back to their routine / normal autonomy.

Settings and per-sim instructions live in Mods/BlueRabbit477/data/npc_brain.json:
  {"url": ..., "model": ..., "sims": {sim_id: "free-text instructions"}}
"""
import json
import os
import queue
import threading
import urllib.request

import npc_log
from npc_brain import DEFAULT_MODEL, DEFAULT_URL, parse_choice, request_body, response_text

_PATH = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts", "The Sims 4", "Mods",
                     "BlueRabbit477", "data", "npc_brain.json")
TIMEOUT_SECONDS = 60

_data = None
_answers = queue.Queue()
_pending = set()          # sim ids with a request in flight
_lock = threading.Lock()


def data():
    global _data
    if _data is None:
        _data = {"url": DEFAULT_URL, "model": DEFAULT_MODEL, "sims": {}}
        try:
            if os.path.exists(_PATH):
                with open(_PATH, "r", encoding="utf-8") as f:
                    _data.update(json.load(f))
        except Exception:
            npc_log.log_exception("loading npc_brain.json")
    return _data


def save():
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(data(), f, indent=1)
    except Exception:
        npc_log.log_exception("saving npc_brain.json")


def instructions_for(sim_id):
    return data()["sims"].get(str(sim_id))


def set_instructions(sim_id, text):
    if text:
        data()["sims"][str(sim_id)] = text
    else:
        data()["sims"].pop(str(sim_id), None)
    save()


def is_pending(sim_id):
    with _lock:
        return sim_id in _pending


def ask(sim_id, prompt, options):
    """Starts one request for this sim unless one is already running."""
    with _lock:
        if sim_id in _pending:
            return False
        _pending.add(sim_id)
    url, model = data()["url"], data()["model"]
    thread = threading.Thread(target=_worker, args=(sim_id, url, model, prompt, options), daemon=True)
    thread.start()
    return True


def _worker(sim_id, url, model, prompt, options):
    # Runs off the game's thread: only HTTP and the queue here, never game objects.
    action, reason, error = None, None, None
    try:
        body = request_body(url, model, prompt).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            text = response_text(url, resp.read().decode("utf-8"))
        action, reason = parse_choice(text, options)
        if action is None:
            error = "no valid choice in the answer: {!r}".format(text[:200])
    except Exception as e:
        error = "{}: {}".format(type(e).__name__, e)
    finally:
        with _lock:
            _pending.discard(sim_id)
    _answers.put((sim_id, action, reason, error))


def take_answers():
    answers = []
    while True:
        try:
            answers.append(_answers.get_nowait())
        except queue.Empty:
            return answers
