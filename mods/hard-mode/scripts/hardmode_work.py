"""Hard Mode: getting fired - pure logic (no game imports, covered by tests).

- A work day counts as missed when the sim was at work for less than MISSED_DAY_SHARE of it
  (taking a day off with paid time off counts as present: the game pays it as a full day).
- MISSED_DAYS_TO_FIRE missed days within MISSED_DAYS_WINDOW sim days gets the sim fired.
- After being fired (by us or by the game), other employers won't hire the sim for
  FIRED_COOLDOWN_DAYS sim days.
"""

MISSED_DAY_SHARE = 0.5
MISSED_DAYS_TO_FIRE = 3
MISSED_DAYS_WINDOW = 7
FIRED_COOLDOWN_DAYS = 3


class WorkRecord:
    """{sim_id: {"missed": {career_name: [sim_day, ...]}, "fired_on": sim_day or None}}"""

    def __init__(self, data=None):
        self.data = {}
        for sim_id, rec in (data or {}).items():
            self.data[str(sim_id)] = {
                "missed": {k: [float(d) for d in v] for k, v in rec.get("missed", {}).items()},
                "fired_on": rec.get("fired_on"),
            }

    def _rec(self, sim_id):
        return self.data.setdefault(str(sim_id), {"missed": {}, "fired_on": None})

    def record_day(self, sim_id, career, share_at_work, today):
        """Records one finished work day. Returns True when this sim should now be fired."""
        if share_at_work >= MISSED_DAY_SHARE:
            return False
        days = self._rec(sim_id)["missed"].setdefault(career, [])
        days.append(float(today))
        days[:] = [d for d in days if today - d < MISSED_DAYS_WINDOW]
        return len(days) >= MISSED_DAYS_TO_FIRE

    def missed_days(self, sim_id, career, today):
        days = self.data.get(str(sim_id), {}).get("missed", {}).get(career, [])
        return len([d for d in days if today - d < MISSED_DAYS_WINDOW])

    def record_fired(self, sim_id, career, today):
        rec = self._rec(sim_id)
        rec["fired_on"] = float(today)
        rec["missed"].pop(career, None)

    def cooldown_left(self, sim_id, today):
        """Sim days until employers will hire this sim again (0 = no cooldown)."""
        fired_on = self.data.get(str(sim_id), {}).get("fired_on")
        if fired_on is None:
            return 0
        left = FIRED_COOLDOWN_DAYS - (today - fired_on)
        return max(0.0, left)

    def to_dict(self):
        return self.data
