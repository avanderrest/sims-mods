"""Flexible University's settings. Pure logic (no game imports), so pytest can cover it."""
import json
import os

# enabled: every hook checks this; off means the game behaves exactly as EA made it.
# early_exit: offer "Apply for Early Graduation" on the phone and award a qualification
#        when a Sim drops out.
# preserve_credits: credits (and passed courses) survive dropping out.
# fractional_credits: strong grades and extra weekdays earn fractional credits.
# friday_schedule: anchor a term's end to Friday evening.
# friday_end_hour: the hour (24h) exams/graduation land on. 19 = 7pm.
# min_term_weekdays: the fewest weekdays a term may have. A start later in the week is
#        stretched into the next week rather than ending after two or three days.
# certificate_fraction / associate_fraction: tier thresholds, as fractions of the game's
#        credit requirement. 1/3 and 2/3 of 12 credits are the example's 4 and 8.
# extension_credit_per_weekday / extension_credit_cap: fractional credits for the extra
#        weekdays of a stretched term.
# grade_bonus_*: fractional credits for a strong course grade, keyed on the game's grade
#        point value (A+ = 4.3, A = 4.0, B = 3.0, C = 2.0, D = 1.0).
DEFAULT_SETTINGS = {
    "enabled": True,
    "early_exit": True,
    "preserve_credits": True,
    "fractional_credits": True,
    "friday_schedule": True,
    "friday_end_hour": 19,
    "min_term_weekdays": 5,
    "certificate_fraction": 0.33,
    "associate_fraction": 0.66,
    "extension_credit_per_weekday": 0.1,
    "extension_credit_cap": 0.5,
    "grade_bonus_high_threshold": 3.7,
    "grade_bonus_high": 0.25,
    "grade_bonus_mid_threshold": 3.0,
    "grade_bonus_mid": 0.15,
    "grade_bonus_low_threshold": 2.0,
    "grade_bonus_low": 0.05,
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
            self.values[key] = _as_bool(value)
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


def _as_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "on", "true", "yes")
    return bool(value)
