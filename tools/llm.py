"""Installs and starts the local LLM server for NPC Routines' brain (Ollama or LM Studio).

What to install is declared in llm.json at the repo root, like npm's package.json:

  py tools/llm.py install   - install the backend (winget) and download its model; run once
  py tools/llm.py start     - start the server if it isn't running, load the model, and point
                              the mod at it (Mods/HouseRules/data/npc_brain.json)
  py tools/llm.py status    - is it running, and is the model there?
  add --backend lmstudio to any of them to use the other one for that run

start-llm.cmd in the repo root runs "install" if needed, then "start" - double-click it
before launching the game.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from config import MODS_DIR, ROOT, CREATOR

MANIFEST = ROOT / "llm.json"
BRAIN_FILE = MODS_DIR / CREATOR / "data" / "npc_brain.json"
SERVER_LOG = ROOT / "build" / "llm-server.log"
START_TIMEOUT = 60

# Where the installers put the CLIs; winget doesn't refresh this shell's PATH.
_KNOWN_PATHS = {
    "ollama": [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"],
    "lms": [Path.home() / ".lmstudio" / "bin" / "lms.exe"],
}
_LMSTUDIO_APP = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "LM Studio" / "LM Studio.exe"
DOWNLOAD_URLS = {
    "ollama": "https://ollama.com/download",
    "lmstudio": "https://lmstudio.ai",
}


def load_manifest(backend=None):
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception as e:
        sys.exit("Can't read {} ({}). Restore that file from the repository, then try again."
                 .format(MANIFEST, e))
    name = backend or data.get("backend")
    if name not in data.get("backends", {}):
        sys.exit("llm.json has no backend '{}' (has: {}). Check the 'backend' entry."
                 .format(name, ", ".join(data.get("backends", {})) or "none"))
    return name, data["backends"][name]


def find_exe(name):
    found = shutil.which(name)
    if found:
        return found
    for path in _KNOWN_PATHS.get(name, ()):
        if path.exists():
            return str(path)
    return None


def run(*args):
    print("  > " + " ".join(str(a) for a in args))
    return subprocess.call([str(a) for a in args])


def get_json(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def server_root(url):
    """http://localhost:11434/api/generate -> http://localhost:11434"""
    return url.split("/api/")[0].split("/v1/")[0]


def models_on_server(name, conf):
    """Model names the running server knows, or None if it isn't answering."""
    root = server_root(conf["url"])
    if name == "ollama":
        data = get_json(root + "/api/tags")
        return None if data is None else [m["name"] for m in data.get("models", [])]
    data = get_json(root + "/v1/models")
    return None if data is None else [m["id"] for m in data.get("data", [])]


def has_model(names, model):
    # Ollama adds ":latest" when the tag is left out ("qwen2.5:14b" -> "qwen2.5:14b:latest").
    return any(n == model or n.split(":")[0] == model for n in names or ())


def choose_model(names, configured):
    """The model to use: the configured one if it's there, otherwise any chat model the server has.
    Embedding-only models can't answer, so they're skipped. None if the server has nothing usable."""
    if has_model(names, configured):
        return configured
    usable = [n for n in names or () if "embed" not in n.lower()]
    return usable[0] if usable else None


def wait_for_server(name, conf):
    for _ in range(START_TIMEOUT):
        if models_on_server(name, conf) is not None:
            return True
        time.sleep(1)
    return False


def spawn_detached(*args):
    SERVER_LOG.parent.mkdir(exist_ok=True)
    log = open(str(SERVER_LOG), "ab")
    flags = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: outlives this window
    subprocess.Popen([str(a) for a in args], stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                     creationflags=flags if os.name == "nt" else 0)


# --- install ---------------------------------------------------------------------------

def install(name, conf):
    exe = find_exe("ollama" if name == "ollama" else "lms")
    if exe is None and not (name == "lmstudio" and _LMSTUDIO_APP.exists()):
        print("Installing {} with winget...".format(name))
        winget = shutil.which("winget")
        if winget is None:
            sys.exit("winget isn't available, so {} can't be installed automatically.\n"
                     "Install it by hand from {} , then run this again."
                     .format(name, DOWNLOAD_URLS.get(name, "")))
        if run(winget, "install", "--id", conf["winget"], "-e",
               "--accept-package-agreements", "--accept-source-agreements") != 0:
            sys.exit("winget couldn't install {}. Install it by hand from {} , then run this again."
                     .format(name, DOWNLOAD_URLS.get(name, "")))
    else:
        print("{} is already installed.".format(name))

    if name == "lmstudio" and find_exe("lms") is None:
        # The lms CLI only appears after LM Studio has been opened once.
        sys.exit("LM Studio is installed. Open it once (so it sets up its 'lms' command), close it, "
                 "then run this again to download the model.")

    start_server(name, conf)
    download_model(name, conf)
    print("Done. Next time just run: py tools/llm.py start")


def download_model(name, conf):
    model = conf["model"]
    if has_model(models_on_server(name, conf), model) or (name == "lmstudio" and _lms_has(model)):
        print("Model {} is already downloaded.".format(model))
        return
    print("Downloading {} (a few GB, this takes a while)...".format(model))
    if name == "ollama":
        code = run(find_exe("ollama"), "pull", model)
    else:
        code = run(find_exe("lms"), "get", model, "--yes")
    if code != 0:
        sys.exit("Downloading {} failed. Check the internet connection and free disk space "
                 "(a few GB per model), then run: py tools/llm.py install".format(model))


def _lms_has(model):
    try:
        out = subprocess.run([find_exe("lms"), "ls"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             universal_newlines=True, timeout=30).stdout
        return model in out
    except Exception:
        return False


# --- start -----------------------------------------------------------------------------

def start_server(name, conf):
    if models_on_server(name, conf) is not None:
        print("{} is already running at {}.".format(name, server_root(conf["url"])))
        return
    if name == "ollama":
        exe = find_exe("ollama")
        if exe is None:
            sys.exit("Ollama isn't installed. Run: py tools/llm.py install")
        print("Starting Ollama (log: {})...".format(SERVER_LOG))
        spawn_detached(exe, "serve")
    else:
        exe = find_exe("lms")
        if exe is None:
            sys.exit("LM Studio's 'lms' command isn't there. Run: py tools/llm.py install --backend lmstudio")
        print("Starting LM Studio's server...")
        run(exe, "server", "start")
    if not wait_for_server(name, conf):
        sys.exit("{} didn't answer within {}s.\n"
                 "Check that port {} is free, then run: py tools/llm.py start\n"
                 "Server log: {}".format(name, START_TIMEOUT,
                                         server_root(conf["url"]).rsplit(":", 1)[-1], SERVER_LOG))


def start(name, conf):
    start_server(name, conf)
    names = models_on_server(name, conf)
    model = choose_model(names, conf["model"])
    if model is None:
        sys.exit("No model is downloaded ({}). Run: py tools/llm.py install".format(conf["model"]))
    if model != conf["model"]:
        print("{} isn't pulled; using {} instead.".format(conf["model"], model))
    if name == "ollama":
        # Load it into memory now, so the first in-game question doesn't wait on it.
        print("Loading {}...".format(model))
        _post(server_root(conf["url"]) + "/api/generate", {"model": model, "keep_alive": "60m"})
    elif not has_model(names, model):
        print("Loading {}...".format(model))
        if run(find_exe("lms"), "load", model, "--yes") != 0:
            sys.exit("Couldn't load {}. Run: py tools/llm.py install --backend lmstudio".format(model))
    point_mod_at(conf, model)
    print("Ready: {} with {}. Start the game (or, if it's already running, type the cheat below).".format(
        name, model))
    print("  houserules.npc.llm {} {}".format(conf["url"], model))


def _post(url, body, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
    except Exception as e:
        print("  (warming up the model failed: {}; the game will load it on first use)".format(e))


def point_mod_at(conf, model):
    """Writes url/model into the mod's settings, keeping each sim's instructions. The mod reads
    this file once per game start; a running game needs the houserules.npc.llm cheat instead."""
    data = {"sims": {}}
    if BRAIN_FILE.exists():
        data.update(json.loads(BRAIN_FILE.read_text(encoding="utf-8")))
    if data.get("url") == conf["url"] and data.get("model") == model:
        return
    data["url"], data["model"] = conf["url"], model
    BRAIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    BRAIN_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print("Pointed the mod at it ({}).".format(BRAIN_FILE))


def status(name, conf):
    names = models_on_server(name, conf)
    installed = find_exe("ollama" if name == "ollama" else "lms") is not None
    print("backend:   {}".format(name))
    print("installed: {}".format("yes" if installed else "no  -> py tools/llm.py install"))
    print("running:   {}".format("no  -> py tools/llm.py start" if names is None else
                                 "yes, at " + server_root(conf["url"])))
    model = choose_model(names, conf["model"])
    if names is not None:
        if model is None:
            print("model:     none pulled -> py tools/llm.py install")
        elif model == conf["model"]:
            print("model:     {} ready".format(model))
        else:
            print("model:     {} not pulled; will use {}".format(conf["model"], model))
    if BRAIN_FILE.exists():
        brain = json.loads(BRAIN_FILE.read_text(encoding="utf-8"))
        print("mod uses:  {} {}".format(brain.get("url"), brain.get("model")))
    return 0 if model is not None else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("install", "start", "status"))
    parser.add_argument("--backend", help="ollama or lmstudio (default: the one in llm.json)")
    args = parser.parse_args()
    name, conf = load_manifest(args.backend)
    if args.command == "install":
        install(name, conf)
    elif args.command == "start":
        start(name, conf)
    else:
        sys.exit(status(name, conf))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        sys.exit("Unexpected error: {}: {}.\n"
                 "Run 'py tools/llm.py status' for details, or check llm.json and the paths "
                 "in tools/config.py.".format(type(e).__name__, e))
