"""Follow the NPC Routines log so the LLM's work is visible while the game runs - and chat with
the model yourself by typing into this window.

start-llm.cmd runs this after starting the server. Each hourly decision shows the prompt
sent to the model, its raw answer, and - for a thinking model with
`houserules.npc.reasoning on` - the reasoning it returned before the answer.

Anything you type is a message in a conversation with the same local model; follow-up
questions keep the context. `/restart` (or `/clear`) forgets the conversation and starts a
fresh one, `/help` lists the commands. `/goal <text>` sets what the last sim seen in the log
works towards - it writes the mod's own file, which the game re-reads at its next decision.
Use `houserules.npc.brain` in game for a sim's description.

The model follows the game: it is loaded as soon as The Sims 4 is running and unloaded a
minute after the game closes (a launcher restarting it doesn't count), so nothing sits in your
memory/VRAM while you aren't playing, and `houserules.npc.start` never waits on a cold load.

  py -3 tools/llm_tail.py [--last N] [--no-chat] [--no-watch]

Close the window (or Ctrl+C) to stop following; the model server keeps running.
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.request

from config import CREATOR, MODS_DIR, ROOT
import llm as llm_server

LOG_PATH = MODS_DIR / CREATOR / "logs" / "npc-routines.log"
BRAIN_FILE = MODS_DIR / CREATOR / "data" / "npc_brain.json"
MANIFEST = ROOT / "llm.json"

DEFAULT_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:3b-instruct"
TIMEOUT_SECONDS = 120

CONCISE_INSTRUCTION = "Answer concisely, in as few sentences as possible."

# Turns kept in the conversation, so the prompt cannot grow without bound.
MAX_HISTORY = 12

# The last sim the game logged about ("tick: ... npc_sims=[123]", "LLM for sim 123"), so
# /goal can name one without you typing an id.
SIM_ID_PATTERN = re.compile(r"(?:npc_sims=\[|sim )(\d{6,})")
_last_sim = None


def note_sim(line):
    """Remember which sim the log is currently about."""
    global _last_sim
    match = SIM_ID_PATTERN.search(line or "")
    if match:
        _last_sim = match.group(1)


def brain_data():
    """The mod's own file (Mods/HouseRules/data/npc_brain.json): settings, goals, sims."""
    try:
        data = json.loads(BRAIN_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data.get("goals"), dict):
        data["goals"] = {}
    if not isinstance(data.get("sims"), dict):
        data["sims"] = {}
    return data


def write_brain_data(data):
    """Write it atomically - the game may be reading the file at any moment."""
    BRAIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = BRAIN_FILE.with_name(BRAIN_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(BRAIN_FILE))


def set_goal(sim_id, text):
    """Set (or clear) a sim's goal in the file the mod reads."""
    data = brain_data()
    if text:
        data["goals"][str(sim_id)] = text
    else:
        data["goals"].pop(str(sim_id), None)
    write_brain_data(data)
    return data["goals"].get(str(sim_id))


def goal_command(rest):
    """/goal [sim_id] [text|clear] - the goal the mod's brain works towards."""
    sim_id, text = _last_sim, (rest or "").strip()
    words = text.split(None, 1)
    if words and words[0].isdigit() and len(words[0]) >= 6:
        sim_id = words[0]
        text = words[1] if len(words) > 1 else ""
    if sim_id is None:
        emit("[goal] I have not seen a sim in the log yet. Start the game and use\n"
             "[goal] houserules.npc.start, then try again - or type /goal <sim_id> <text>.\n\n")
        return
    if text.lower() in ("clear", "none", "off"):
        set_goal(sim_id, "")
        emit("[goal] Cleared the goal for sim {}.\n\n".format(sim_id))
        return
    if not text:
        current = brain_data()["goals"].get(str(sim_id))
        emit("[goal] sim {}: {}\n"
             "[goal] /goal <text> sets it; /goal clear removes it.\n\n".format(
                 sim_id, current or "(no goal)"))
        return
    set_goal(sim_id, text)
    emit("[goal] sim {} now works towards: {}\n"
         "[goal] The game reads it at its next decision (no restart). It needs\n"
         "[goal] houserules.npc.start in game - the goal alone does not start the brain.\n\n"
         .format(sim_id, text))


# Two things write here: the log tail and the answers to what you type.
_print_lock = threading.Lock()

# The game's Python picks up a Windows proxy that does not apply to localhost; the same empty
# ProxyHandler the mod uses keeps that out of the way.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def emit(text):
    """Write to the console with the current code page, replacing anything it can't show."""
    try:
        data = text.encode(sys.stdout.encoding or "utf-8", "replace")
        with _print_lock:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
    except Exception:
        pass


def settings():
    """The url/model to use for typed questions: the mod's own settings first (that is what
    the game uses), then llm.json, then the defaults."""
    url, model = DEFAULT_URL, DEFAULT_MODEL
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        conf = data["backends"][data["backend"]]
        url, model = conf.get("url", url), conf.get("model", model)
    except Exception:
        pass
    try:
        brain = json.loads(BRAIN_FILE.read_text(encoding="utf-8"))
        url = brain.get("url") or url
        model = brain.get("model") or model
    except Exception:
        pass
    return url, model


def _loopback_url(url):
    """localhost -> 127.0.0.1: this Python cannot always resolve the name."""
    return url.replace("://localhost:", "://127.0.0.1:").replace("://localhost/", "://127.0.0.1/")


def transcript(messages):
    """The conversation as one prompt, for servers that only take a single text."""
    if len(messages) == 1:
        return CONCISE_INSTRUCTION + "\n\n" + messages[0]["content"]
    lines = [CONCISE_INSTRUCTION,
             "Continue this conversation; reply with only the next Assistant line.", ""]
    for message in messages:
        who = "User" if message.get("role") == "user" else "Assistant"
        lines.append("{}: {}".format(who, message.get("content", "")))
    return "\n".join(lines)


def request_body(url, model, messages):
    """Ollama's /api/generate or an OpenAI-style /v1/chat/completions body, like the mod.
    messages is the whole conversation: [{"role": "user"/"assistant", "content": ...}]."""
    if "/chat/completions" in url:
        return {"model": model,
                "messages": [{"role": "system", "content": CONCISE_INSTRUCTION}] + messages,
                "temperature": 0.7, "max_tokens": 200}
    # /api/generate has no message list, so the conversation is sent as a transcript.
    return {"model": model, "prompt": transcript(messages), "stream": False,
            "options": {"temperature": 0.7, "num_predict": 200, "num_ctx": 4096}}


def answer_text(url, payload):
    if "/chat/completions" in url:
        return payload["choices"][0]["message"]["content"]
    return payload.get("response", "")


def ask(url, model, messages, timeout=TIMEOUT_SECONDS):
    body = json.dumps(request_body(url, model, messages)).encode("utf-8")
    request = urllib.request.Request(_loopback_url(url), data=body,
                                     headers={"Content-Type": "application/json"})
    with _opener.open(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return answer_text(url, payload)


def _banner(url, model):
    return ("[chat] Type a message and press Enter; the answer appears here. Follow-ups keep\n"
            "[chat] the conversation, so you can ask \"and then what?\".\n"
            "[chat] This does not affect any sim - /goal sets one, houserules.npc.brain the rest.\n"
            "[chat] /restart starts a fresh conversation (chat only); /help for commands.\n"
            "[chat] Model: {} at {}\n\n".format(model, url))


def _command(text, history):
    """Handles a /command typed into the chat. True when the line was a command."""
    command = text.split()[0].lower()
    if command in ("/restart", "/clear", "/new"):
        history.clear()
        emit("[chat] Fresh conversation.\n\n")
        return True
    if command == "/goal":
        goal_command(text[len(command):])
        return True
    if command == "/help":
        emit("[chat] /restart (or /clear) forgets this conversation and starts fresh. It has\n"
             "[chat] nothing to do with the sims: the brain rebuilds their context on every\n"
             "[chat] decision anyway. To change what a sim does:\n"
             "[chat]   /goal <text>            what the last sim seen in the log works towards\n"
             "[chat]   /goal <sim_id> <text>   the same, for a sim you name\n"
             "[chat]   /goal                    show it; /goal clear removes it\n"
             "[chat] In game, to make it decide right now:\n"
             "[chat]   houserules.npc.start        (ask now, ignoring the wait)\n"
             "[chat]   houserules.npc.actions      (what it would be offered right now)\n"
             "[chat]   houserules.npc.think        (the last prompt and answer)\n"
             "[chat] Anything else you type is a message to the model.\n\n")
        return True
    if command.startswith("/"):
        emit("[chat] Unknown command {}. Use /restart or /help.\n\n".format(command))
        return True
    return False


def chat(stream):
    """A conversation with the model, one line at a time, until the console closes. Runs on
    its own thread so the log keeps following while a question is being answered."""
    url, model = settings()
    emit("\n" + _banner(url, model))
    history = []
    while True:
        try:
            line = stream.readline()
        except Exception:
            return
        if not line:
            return
        prompt = line.strip()
        if not prompt:
            continue
        if _command(prompt, history):
            continue
        emit("[chat] you: {}\n".format(prompt))
        history.append({"role": "user", "content": prompt})
        del history[:-MAX_HISTORY]       # keep the prompt bounded
        try:
            answer = ask(url, model, history)
        except Exception as e:
            history.pop()      # the turn never happened; do not remember it
            emit("[chat] the model did not answer ({}). Is start-llm.cmd / Ollama running?\n\n"
                 .format(e))
            continue
        answer = (answer or "").strip()
        history.append({"role": "assistant", "content": answer})
        del history[:-MAX_HISTORY]       # keep the prompt bounded
        emit("[chat] model: {}\n\n".format(answer or "(empty answer)"))


GAME_POLL_SECONDS = 10
# Only unload after the game has been gone this long: launching the game (or a launcher that
# restarts the process) must not throw the model out of memory on the way in.
GAME_GONE_SECONDS = 60


def model_wanted():
    """True while a model should be kept in memory: for the whole time The Sims 4 runs, so
    `houserules.npc.start` is instant instead of waiting on a cold load. Nothing loads while
    the game is closed."""
    return bool(llm_server.game_running())


def _model_changed(wanted):
    """The game started or closed: load the model for play, unload it to free the GPU."""
    url, model = settings()
    name = llm_server.backend_for(url)
    conf = {"url": url, "model": model}
    say = lambda text: emit("  " + text + "\n")
    if wanted:
        emit("\n[brain] The Sims 4 is running - keeping {} loaded for quick decisions.\n".format(model))
        llm_server.load(name, conf, model, say=say)
        return
    emit("\n[brain] The Sims 4 isn't running - unloading {} to free memory/VRAM.\n"
         "[brain] It loads again when the game starts.\n".format(model))
    llm_server.unload(name, conf, model, say=say)


def watch_brain(on_change, poll=GAME_POLL_SECONDS, stop=None, gone_after=GAME_GONE_SECONDS):
    """Loads the model when the game appears, and unloads it only after the game has been
    gone for gone_after seconds. Runs on its own thread so typing and the log keep working.

    Nothing happens before the game has been seen at all: starting start-llm.cmd and then the
    game must not unload or reload anything on the way in."""
    previous = None
    gone = 0
    while stop is None or not stop.is_set():
        try:
            running = model_wanted()
        except Exception:
            running = False
        if running:
            gone = 0
            wanted = True
        elif previous is True:
            gone += poll
            wanted = False if gone >= gone_after else True
        else:
            wanted = previous      # still waiting for the game: nothing loaded to unload
        if wanted is not None and wanted != previous:
            previous = wanted
            try:
                on_change(wanted)
            except Exception as e:
                emit("[brain] could not react to the game's state: {}\n".format(e))
        if stop is None:
            time.sleep(poll)
        else:
            stop.wait(poll)


def follow(path, last=0, poll=0.5):
    while not path.exists():
        emit("Waiting for {} (start the game and use houserules.npc.start)...\n".format(path))
        time.sleep(2)
    with open(str(path), "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
        if last > 0 and lines:
            emit("\n[log] earlier lines from the previous session (not live):\n")
            for line in lines[-last:]:
                emit(line)
            emit("[log] live from here on.\n\n")
        elif lines:
            emit("\n[log] earlier lines from the previous session are not shown "
                 "(use --last N to see the last N).\n\n")
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if line:
                note_sim(line)
                emit(line)
            else:
                time.sleep(poll)


def main(argv):
    parser = argparse.ArgumentParser(description="Show the NPC brain's prompts and answers live.")
    parser.add_argument("--last", type=int, default=0,
                        help="lines of the previous session's log to show first (default 0)")
    parser.add_argument("--no-chat", action="store_true",
                        help="only follow the log; ignore what is typed (the old behaviour)")
    parser.add_argument("--no-watch", action="store_true",
                        help="don't load/unload the model as The Sims 4 starts and closes")
    args = parser.parse_args(argv)
    emit("Watching {}\nClose this window to stop (the model server keeps running).\n".format(
        LOG_PATH))
    if not args.no_chat:
        threading.Thread(target=chat, args=(sys.stdin,), daemon=True).start()
    if not args.no_watch:
        threading.Thread(target=watch_brain, args=(_model_changed,), daemon=True).start()
    try:
        follow(LOG_PATH, last=args.last)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
