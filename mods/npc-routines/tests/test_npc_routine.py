import pytest
from npc_routine import RoutineEntry, Routine, RoutineStore, ACTIVITIES


def test_valid_entry_round_trips_through_dict():
    e = RoutineEntry(days=[1, 3, 5], start_hour=18, length_hours=2, activity="workout")
    d = e.to_dict()
    e2 = RoutineEntry.from_dict(d)
    assert e2.days == [1, 3, 5]
    assert e2.start_hour == 18
    assert e2.length_hours == 2
    assert e2.activity == "workout"


@pytest.mark.parametrize("bad_kwargs", [
    dict(days=[1], start_hour=18, length_hours=2, activity="not-a-real-activity"),
    dict(days=[1], start_hour=24, length_hours=2, activity="workout"),
    dict(days=[1], start_hour=-1, length_hours=2, activity="workout"),
    dict(days=[1], start_hour=18, length_hours=0, activity="workout"),
    dict(days=[1], start_hour=18, length_hours=25, activity="workout"),
    dict(days=[], start_hour=18, length_hours=2, activity="workout"),
    dict(days=[7], start_hour=18, length_hours=2, activity="workout"),
])
def test_invalid_entries_are_rejected(bad_kwargs):
    with pytest.raises(ValueError):
        RoutineEntry(**bad_kwargs)


def test_covers_within_same_day():
    e = RoutineEntry(days=[2], start_hour=18, length_hours=2, activity="paint")  # Tue 18:00-20:00
    assert not e.covers(2, 17)
    assert e.covers(2, 18)
    assert e.covers(2, 19)
    assert not e.covers(2, 20)
    assert not e.covers(1, 18)  # wrong day


def test_covers_wraps_past_midnight():
    e = RoutineEntry(days=[5], start_hour=23, length_hours=3, activity="read")  # Fri 23:00 -> Sat 02:00
    assert e.covers(5, 23)
    assert not e.covers(5, 22)
    assert e.covers(6, 0)
    assert e.covers(6, 1)
    assert not e.covers(6, 2)
    assert not e.covers(0, 0)  # Sunday, unrelated


def test_due_activity_returns_none_when_nothing_matches():
    routine = Routine()
    routine.add(RoutineEntry([1], 9, 1, "jog"))
    assert routine.due_activity(1, 8) is None
    assert routine.due_activity(2, 9) is None


def test_due_activity_returns_the_matching_entrys_activity():
    routine = Routine()
    routine.add(RoutineEntry([1], 9, 1, "jog"))
    assert routine.due_activity(1, 9) == "jog"


def test_due_activity_first_match_wins_on_overlap():
    routine = Routine()
    routine.add(RoutineEntry([1], 9, 2, "jog"))
    routine.add(RoutineEntry([1], 9, 2, "chess"))  # overlaps; added second
    assert routine.due_activity(1, 9) == "jog"


def test_routine_list_round_trip():
    routine = Routine([RoutineEntry([0, 6], 10, 1, "chess")])
    items = routine.to_list()
    routine2 = Routine.from_list(items)
    assert routine2.due_activity(0, 10) == "chess"
    assert routine2.due_activity(6, 10) == "chess"


def test_routine_store_get_creates_empty_routine_on_first_access():
    store = RoutineStore()
    assert not store.has(123)
    routine = store.get(123)
    assert routine.entries == []
    assert store.has(123)


def test_routine_store_remove():
    store = RoutineStore()
    store.get(123).add(RoutineEntry([1], 9, 1, "jog"))
    store.remove(123)
    assert not store.has(123)


def test_routine_store_json_round_trip():
    store = RoutineStore()
    store.get(111).add(RoutineEntry([1, 2], 9, 1, "jog"))
    store.get(222).add(RoutineEntry([5], 20, 2, "paint"))
    text = store.to_json()
    store2 = RoutineStore.from_json(text)
    assert store2.get(111).due_activity(1, 9) == "jog"
    assert store2.get(222).due_activity(5, 20) == "paint"


def test_routine_store_load_from_missing_file_is_a_noop(tmp_path):
    store = RoutineStore()
    store.load(str(tmp_path / "does-not-exist.json"))
    assert store.sim_ids() == []


def test_routine_store_load_from_empty_file_is_a_noop(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")
    store = RoutineStore()
    store.load(str(path))
    assert store.sim_ids() == []


def test_routine_store_save_then_load_round_trip(tmp_path):
    path = str(tmp_path / "routines.json")
    store = RoutineStore()
    store.get(999).add(RoutineEntry([3], 14, 1, "read"))
    store.save(path)

    store2 = RoutineStore()
    store2.load(path)
    assert store2.get(999).due_activity(3, 14) == "read"


def test_every_activity_name_is_a_plain_lowercase_word():
    # Guards against typos sneaking into ACTIVITIES that cheat parsing wouldn't catch.
    for activity in ACTIVITIES:
        assert activity == activity.lower()
        assert activity.isalpha()


def test_all_day_entry_covers_every_hour_of_its_day():
    # 24 hours = all day (in-game 2026-10-09, "0 24 chess" was rejected when the limit was 23).
    e = RoutineEntry(days=[1], start_hour=0, length_hours=24, activity="chess")
    assert all(e.covers(1, h) for h in range(24))
    assert not e.covers(2, 0)
