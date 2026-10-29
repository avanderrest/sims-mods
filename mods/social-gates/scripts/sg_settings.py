"""Pure logic for Social Gates' on/off settings. No game imports."""
import json
import os

# doors: a Sim can only be let in (ring doorbell / greet) by a household they are
#        friends with. Family, household members and always-welcome Sims still get in.
# invites: an invite over is only accepted from a friend.
# clubs: club admission checks run at all.
# club_require_restriction: a Sim may only join a club if it has a trait from a trait
#        restriction, a skill from a skill restriction, or a skill used by a club activity.
#        Sims who fail these checks are hidden from the add-member picker instead of being
#        auto-removed after joining.
# club_interest: non-exempt Sims are only shown in the add-member picker (and allowed to
#        join) when their traits or Likes match one of the club's activities.
# club_relative_wealth: the "household value" criteria are read as poorer than / similar
#        to / richer than the club leader (the only sim who can edit the club), instead of
#        the game's three fixed brackets.
# club_wealth_band: how wide "similar" is, as a fraction of the leader's net worth.
#        0.5 = between half and 1.5x the leader's household.
# club_activity_skill_min: how much of an activity's skill counts as "has it".
# club_enforce_premade: also apply club admission to the game's own clubs (off by default).
# friend_min_score: friendship score (0-100) from which a Sim counts as a friend.
DEFAULT_SETTINGS = {
    "doors": True,
    "invites": True,
    "clubs": True,
    "club_require_restriction": True,
    "club_relative_wealth": True,
    "club_wealth_band": 0.5,
    "club_activity_skill_min": 1,
    "club_enforce_premade": False,
    "club_interest": True,
    "friend_min_score": 20,
}


class Settings:
    def __init__(self, values=None):
        self.values = dict(DEFAULT_SETTINGS)
        if values:
            self.values.update({k: v for k, v in values.items() if k in DEFAULT_SETTINGS})

    def get(self, key):
        return self.values.get(key, DEFAULT_SETTINGS.get(key))

    def set(self, key, value):
        if key not in DEFAULT_SETTINGS:
            raise KeyError(key)
        default = DEFAULT_SETTINGS[key]
        if isinstance(default, bool):
            self.values[key] = bool(value)
        elif isinstance(default, float):
            self.values[key] = float(value)
        else:
            self.values[key] = int(value)

    def is_switch(self, key):
        return isinstance(DEFAULT_SETTINGS.get(key), bool)

    def to_json(self):
        return json.dumps(self.values)

    @classmethod
    def from_json(cls, text):
        return cls(json.loads(text))

    def load(self, path):
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            return
        self.values = self.__class__.from_json(text).values

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
