from hardmode_work import FIRED_COOLDOWN_DAYS, MISSED_DAYS_TO_FIRE, WorkRecord


def test_full_day_is_not_missed():
    rec = WorkRecord()
    assert rec.record_day(1, "Doctor", 1.0, today=1) is False
    assert rec.missed_days(1, "Doctor", 1) == 0


def test_enough_missed_days_fire():
    rec = WorkRecord()
    results = [rec.record_day(1, "Doctor", 0.0, today=d) for d in range(MISSED_DAYS_TO_FIRE)]
    assert results[-1] is True
    assert not any(results[:-1])


def test_old_missed_days_are_forgotten():
    rec = WorkRecord()
    rec.record_day(1, "Doctor", 0.0, today=1)
    rec.record_day(1, "Doctor", 0.0, today=2)
    assert rec.record_day(1, "Doctor", 0.0, today=20) is False
    assert rec.missed_days(1, "Doctor", 20) == 1


def test_missed_days_are_per_career():
    rec = WorkRecord()
    rec.record_day(1, "Doctor", 0.0, today=1)
    rec.record_day(1, "Doctor", 0.0, today=2)
    assert rec.record_day(1, "Writer", 0.0, today=3) is False


def test_cooldown_after_firing():
    rec = WorkRecord()
    assert rec.cooldown_left(1, today=5) == 0
    rec.record_fired(1, "Doctor", today=5)
    assert rec.cooldown_left(1, today=5) == FIRED_COOLDOWN_DAYS
    assert rec.cooldown_left(1, today=5 + FIRED_COOLDOWN_DAYS) == 0


def test_round_trip():
    rec = WorkRecord()
    rec.record_day(1, "Doctor", 0.2, today=1)
    rec.record_fired(2, "Writer", today=3)
    copy = WorkRecord(rec.to_dict())
    assert copy.missed_days(1, "Doctor", 1) == 1
    assert copy.cooldown_left(2, 3) == FIRED_COOLDOWN_DAYS
