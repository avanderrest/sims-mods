"""NPC Routines phase 4 - talking to a local LLM server, off the game's thread.

ask() starts a background thread that POSTs the prompt and puts the answer in a queue.
take_answers() is called from the hourly tick (the game's own thread) to collect them -
game state must only ever be touched from that thread. If the server isn't running, the
request just fails quietly and the sim falls back to their routine / normal autonomy.

Settings and per-sim instructions live in Mods/HouseRules/data/npc_brain.json:
  {"url": ..., "model": ..., "sims": {sim_id: "free-text instructions"}}
"""
import json
import os
import queue
import threading
import time
import urllib.request
import http.client
from urllib.parse import urlsplit

import npc_log
from npc_brain import DEFAULT_MODEL, DEFAULT_URL, parse_answer, request_body, response_text, response_thinking

_PATH = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts", "The Sims 4", "Mods",
                     "HouseRules", "data", "npc_brain.json")
# Which sims the brain is actually working for this session. start-llm.cmd's watcher reads
# this file to keep the model loaded only while somebody needs it.
_STATE_PATH = os.path.join(os.path.dirname(_PATH), "npc_brain_state.json")
TIMEOUT_SECONDS = 60

# The game's Python picks up a Windows proxy that does not apply to localhost, which makes
# urlopen fail with "[Errno 0] Error". An opener with an empty ProxyHandler talks to the
# local server directly.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_data = None
_data_mtime = None
_answers = queue.Queue()
_pending = set()          # sim ids with a request in flight
_last = {}                # sim id -> {"prompt", "answer", "thinking", "action", "minutes", "reason", "error", "when"}
_active = set()           # sim ids the brain is deciding for -> npc_brain_state.json
_lock = threading.Lock()


def _load():
    loaded = {"url": DEFAULT_URL, "model": DEFAULT_MODEL, "sims": {}, "goals": {},
              "think": False}
    try:
        if os.path.exists(_PATH):
            with open(_PATH, "r", encoding="utf-8") as f:
                loaded.update(json.load(f))
    except Exception:
        npc_log.log_exception("loading npc_brain.json")
    loaded.setdefault("sims", {})
    loaded.setdefault("goals", {})
    return loaded


def _file_mtime():
    try:
        return os.path.getmtime(_PATH)
    except OSError:
        return None


def data():
    """The brain's settings and per-sim text.

    Re-read when the file changed on disk: start-llm.cmd writes goals into this same file
    (`/goal`), and the game has to pick one up at the next decision instead of after a
    restart."""
    global _data, _data_mtime
    mtime = _file_mtime()
    if _data is None or (mtime is not None and mtime != _data_mtime):
        _data = _load()
        _data_mtime = mtime
    return _data


def save():
    global _data_mtime
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        tmp = _PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data(), f, indent=1)
        os.replace(tmp, _PATH)     # a reader (or start-llm.cmd) never sees half a file
        _data_mtime = _file_mtime()
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


def goal_for(sim_id):
    return data()["goals"].get(str(sim_id))


def set_goal(sim_id, text):
    if text:
        data()["goals"][str(sim_id)] = text
    else:
        data()["goals"].pop(str(sim_id), None)
    save()


def is_pending(sim_id):
    with _lock:
        return sim_id in _pending


# --- brain state, for the start-llm watcher ----------------------------------------------

def mark_active(sim_id, on=True):
    """Record that the brain is (or is no longer) deciding for this sim, and save it where
    start-llm.cmd can see it: the model is only kept loaded while someone needs it."""
    if on:
        _active.add(sim_id)
    else:
        _active.discard(sim_id)
    _write_state()


def reset_active():
    """A new game session: nothing has been started yet, so clear last session's state."""
    _active.clear()
    _write_state()


def active_ids():
    return sorted(_active)


def _write_state():
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        tmp = _STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"sims": sorted(_active), "when": time.strftime("%Y-%m-%dT%H:%M:%S")}, f)
        os.replace(tmp, _STATE_PATH)     # replace, so a watcher never reads half a file
    except Exception:
        npc_log.log_exception("writing the brain state")


def pending_ids():
    with _lock:
        return set(_pending)


def last_for(sim_id):
    """The most recent prompt/answer for this sim, so the player can see what it decided."""
    with _lock:
        return dict(_last.get(str(sim_id)) or {})


def ask(sim_id, prompt, options):
    """Starts one request for this sim unless one is already running."""
    with _lock:
        if sim_id in _pending:
            return False
        _pending.add(sim_id)
    url, model = data()["url"], data()["model"]
    think = bool(data().get("think", False))
    thread = threading.Thread(target=_worker, args=(sim_id, url, model, prompt, options, think),
                              daemon=True)
    thread.start()
    return True


def _loopback_url(url):
    """localhost -> 127.0.0.1: the game's Python cannot always resolve the name."""
    return url.replace("://localhost:", "://127.0.0.1:").replace("://localhost/", "://127.0.0.1/")


def reachable(url=None, timeout=3):
    """Quick check that the server answers. Uses a direct HTTP connection (no proxy, no DNS)."""
    target = _loopback_url(url or data()["url"])
    try:
        parts = urlsplit(target)
        connection = http.client.HTTPConnection(parts.hostname or "127.0.0.1",
                                                parts.port or 80, timeout=timeout)
        try:
            path = "/api/tags" if "/api/" in parts.path else (parts.path or "/")
            connection.request("GET", path)
            return connection.getresponse().status in (200, 404, 405)
        finally:
            connection.close()
    except Exception:
        return False


def _worker(sim_id, url, model, prompt, options, think=False):
    # Runs off the game's thread: only HTTP and the queue here, never game objects.
    action, minutes, reason, error = None, None, None, None
    text, reasoning = "", ""
    try:
        body = request_body(url, model, prompt, think=think).encode("utf-8")
        req = urllib.request.Request(_loopback_url(url), data=body,
                                     headers={"Content-Type": "application/json"})
        with _opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
            payload = resp.read().decode("utf-8")
        text = response_text(url, payload)
        reasoning = response_thinking(url, payload)
        action, minutes, reason = parse_answer(text, options)
        if action is None:
            error = "no valid choice in the answer: {!r}".format(text[:200])
        npc_log.log("LLM answer for sim {}: {!r}".format(sim_id, text))
        if reasoning:
            npc_log.log("LLM thinking for sim {}: {!r}".format(sim_id, reasoning[:2000]))
    except Exception as e:
        error = "{}: {}".format(type(e).__name__, e)
    finally:
        with _lock:
            _pending.discard(sim_id)
            _last[str(sim_id)] = {"prompt": prompt, "answer": text, "thinking": reasoning,
                                  "action": action, "minutes": minutes, "reason": reason,
                                  "error": error, "when": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _answers.put((sim_id, action, minutes, reason, error))


def has_answers():
    """True when an answer is waiting to be applied (the poll must not stop before it is)."""
    return not _answers.empty()


def take_answers():
    answers = []
    while True:
        try:
            answers.append(_answers.get_nowait())
        except queue.Empty:
            return answers
