"""Pure logic for NPC Routines phase 1: the routine data model and "what should be
happening right now" lookup. No game imports - see npc_main.py for the game layer,
which is the only part that touches the real clock, sims or interactions.

Day numbering matches the game's own DateAndTime.day(): 0=Sunday .. 6=Saturday
(confirmed in ea_scripts/simulation/date_and_time.py's __format__ method, which maps
day() to ('Su',' M','Tu',' W','Th',' F','Sa')) - NOT Python's weekday(). Getting this
wrong would silently run routines on the wrong day, so it's called out here loudly.
"""
import json

DAY_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")

# Activity keys this phase understands. The matching affordance (the actual interaction
# to push) is a game-layer concern - see ACTIVITY_AFFORDANCES in npc_main.py, which is
# the one part of this mod we could not verify without a running game (needs real tuning
# instance names). Keeping that mapping out of this file means it can change without
# touching anything tested here.
ACTIVITIES = frozenset({"workout", "paint", "read", "chess", "jog"})


class RoutineEntry:
    def __init__(self, days, start_hour, length_hours, activity):
        if activity not in ACTIVITIES:
            raise ValueError("unknown activity: {!r} (must be one of {})".format(activity, sorted(ACTIVITIES)))
        days = sorted(set(days))
        if not days or any(not (0 <= d <= 6) for d in days):
            raise ValueError("days must be a non-empty list of ints 0-6 (0=Sunday)")
        if not (0 <= start_hour <= 23):
            raise ValueError("start_hour must be 0-23")
        if not (1 <= length_hours <= 24):  # 24 = all day
            raise ValueError("length_hours must be 1-24")
        self.days = days
        self.start_hour = start_hour
        self.length_hours = length_hours
        self.activity = activity

    def covers(self, day, hour):
        """True if this entry should be active at the given day (0-6) and hour (0-23).
        Handles entries that run past midnight into the next day."""
        for d in self.days:
            if day == d:
                offset = hour - self.start_hour
            elif day == (d + 1) % 7:
                offset = hour - self.start_hour + 24
            else:
                continue
            if 0 <= offset < self.length_hours:
                return True
        return False

    def to_dict(self):
        return {"days": self.days, "start_hour": self.start_hour,
                "length_hours": self.length_hours, "activity": self.activity}

    @classmethod
    def from_dict(cls, d):
        return cls(d["days"], d["start_hour"], d["length_hours"], d["activity"])

    def __repr__(self):
        day_str = ",".join(DAY_NAMES[d] for d in self.days)
        return "<{} {}:00 +{}h {}>".format(day_str, self.start_hour, self.length_hours, self.activity)


class Routine:
    def __init__(self, entries=None):
        self.entries = list(entries or [])

    def add(self, entry):
        self.entries.append(entry)

    def clear(self):
        self.entries = []

    def due_activity(self, day, hour):
        """Returns the activity key that should be happening right now, or None if no
        entry covers this hour. If entries overlap, the first one added wins."""
        for entry in self.entries:
            if entry.covers(day, hour):
                return entry.activity
        return None

    def to_list(self):
        return [e.to_dict() for e in self.entries]

    @classmethod
    def from_list(cls, items):
        return cls(RoutineEntry.from_dict(d) for d in items)


class RoutineStore:
    """Holds one Routine per sim id, with JSON load/save. Takes a path so tests can
    point it at a temp file instead of the real Mods folder."""

    def __init__(self):
        self._routines = {}

    def get(self, sim_id):
        return self._routines.setdefault(sim_id, Routine())

    def has(self, sim_id):
        return sim_id in self._routines

    def remove(self, sim_id):
        self._routines.pop(sim_id, None)

    def sim_ids(self):
        return list(self._routines.keys())

    def to_json(self):
        return json.dumps({str(sim_id): r.to_list() for sim_id, r in self._routines.items()})

    @classmethod
    def from_json(cls, text):
        store = cls()
        for sim_id_str, items in json.loads(text).items():
            store._routines[int(sim_id_str)] = Routine.from_list(items)
        return store

    def load(self, path):
        import os
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            return
        loaded = self.__class__.from_json(text)
        self._routines = loaded._routines

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
