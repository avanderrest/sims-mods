"""Tally of Neighborhood Stories events, so the rebalance can be checked with numbers.
Pure logic: no game imports. nsr_main.py feeds it from two hooks:
  started - an arc was seeded on a sim or household (BaseStoryProgressionTracker.add_arc)
  ended   - an arc finished, with EA's result string, e.g. SUCCESS or ERROR

Saved as JSON, so counts survive restarting the game.
"""
import json
import os

from nsr_classify import classify_arc


class EventTally:
    def __init__(self, events=None):
        self.events = list(events or [])

    def add(self, kind, arc_name, when=None, result=None):
        event = {"kind": kind, "arc": arc_name, "category": classify_arc(arc_name)}
        if when is not None:
            event["when"] = when
        if result is not None:
            event["result"] = result
        self.events.append(event)
        return event

    def summary(self):
        """{category: {"started": n, "ended": {result: n}}}, categories sorted."""
        out = {}
        for e in self.events:
            row = out.setdefault(e["category"], {"started": 0, "ended": {}})
            if e["kind"] == "started":
                row["started"] += 1
            elif e["kind"] == "ended":
                result = e.get("result", "?")
                row["ended"][result] = row["ended"].get(result, 0) + 1
        return dict(sorted(out.items()))

    def summary_lines(self):
        lines = []
        for category, row in self.summary().items():
            ended = ", ".join("{} {}".format(n, r) for r, n in sorted(row["ended"].items())) or "none"
            lines.append("{}: started {}, ended: {}".format(category, row["started"], ended))
        return lines

    def clear(self):
        self.events = []

    def save(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.events, f)

    @classmethod
    def load(cls, path):
        try:
            with open(path, encoding="utf-8") as f:
                return cls(json.load(f))
        except (OSError, ValueError):
            return cls()
