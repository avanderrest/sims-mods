from nsr_events import EventTally


def test_counts_starts_and_end_results_per_category():
    t = EventTally()
    t.add("started", "simStoryArc_ChildrenStories_AdoptABaby")
    t.add("started", "householdStoryArc_MoveOut")
    t.add("started", "householdStoryArc_MoveOut")
    t.add("ended", "householdStoryArc_MoveOut", result="SUCCESS")
    t.add("ended", "householdStoryArc_MoveOut", result="ERROR")
    s = t.summary()
    assert s["adopt_child"] == {"started": 1, "ended": {}}
    assert s["move_out"] == {"started": 2, "ended": {"SUCCESS": 1, "ERROR": 1}}


def test_summary_lines_are_readable():
    t = EventTally()
    t.add("started", "simStoryArc_ChildrenStories_AdoptACat")
    t.add("ended", "simStoryArc_ChildrenStories_AdoptACat", result="SUCCESS")
    assert t.summary_lines() == ["adopt_pet: started 1, ended: 1 SUCCESS"]


def test_save_and_load_round_trip(tmp_path):
    path = str(tmp_path / "data" / "events.json")
    t = EventTally()
    t.add("started", "householdStoryArc_MoveIn", when="day 3 08:00")
    t.save(path)
    loaded = EventTally.load(path)
    assert loaded.events == t.events


def test_load_missing_or_broken_file_gives_empty_tally(tmp_path):
    assert EventTally.load(str(tmp_path / "nope.json")).events == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert EventTally.load(str(bad)).events == []


def test_clear():
    t = EventTally()
    t.add("started", "householdStoryArc_MoveIn")
    t.clear()
    assert t.summary() == {}
