"""Pure logic for Hard Mode's on/off settings. No game imports."""
import json
import os

# careers: the rule is evaluated (hard.check, and the log when someone picks a job).
# enforce: picking a job that fails the rule is actually refused. Off until tested in-game.
# selling: made/gathered items sell for less, and each kind's market fills up.
# markups: shop/stall/restaurant/stand markups earn less and less, customers mind more.
# bills: bills grow with household size.
# debt: unpaid bills become debt instead of utilities being shut off (up to a credit limit).
DEFAULT_SETTINGS = {"careers": True, "enforce": False, "selling": True,
                    "markups": True, "bills": True, "debt": True}


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
        if isinstance(DEFAULT_SETTINGS[key], bool):
            self.values[key] = bool(value)
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
