"""Follow the NPC Routines log so the LLM's work is visible while the game runs.

start-llm.cmd runs this after starting the server. Each hourly decision shows the prompt
sent to the model, its raw answer, and - for a thinking model with
`houserules.npc.reasoning on` - the reasoning it returned before the answer.

  py -3 tools/llm_tail.py [--last N]

Close the window (or Ctrl+C) to stop following; the model server keeps running.
"""
import argparse
import os
import sys
import time

from config import CREATOR, MODS_DIR

LOG_PATH = MODS_DIR / CREATOR / "logs" / "npc-routines.log"


def emit(text):
    """Write to the console with the current code page, replacing anything it can't show."""
    try:
        data = text.encode(sys.stdout.encoding or "utf-8", "replace")
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    except Exception:
        pass


def follow(path, last=10, poll=0.5):
    while not path.exists():
        emit("Waiting for {} (start the game and use houserules.npc.start)...\n".format(path))
        time.sleep(2)
    with open(str(path), "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
        for line in lines[-max(0, last):]:
            emit(line)
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if line:
                emit(line)
            else:
                time.sleep(poll)


def main(argv):
    parser = argparse.ArgumentParser(description="Show the NPC brain's prompts and answers live.")
    parser.add_argument("--last", type=int, default=10,
                        help="lines of earlier log to show first (default 10)")
    args = parser.parse_args(argv)
    emit("Watching {}\nClose this window to stop (the model server keeps running).\n\n".format(
        LOG_PATH))
    try:
        follow(LOG_PATH, last=args.last)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
