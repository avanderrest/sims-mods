from asp_logic import (ahead_of, all_complete, first_incomplete, index_tracks,
                       track_is_selectable, tracks_to_finish)

LEVELS = ["L1", "L2", "L3", "L4"]


def done(*names):
    return lambda level: level in names


def test_first_incomplete_in_order():
    assert first_incomplete(LEVELS, done()) == "L1"
    assert first_incomplete(LEVELS, done("L1")) == "L2"


def test_completed_levels_are_skipped_wherever_they_are():
    # Level 3 was done early: finishing level 2 goes straight to level 4.
    assert first_incomplete(LEVELS, done("L1", "L2", "L3")) == "L4"
    # Level 3 done early doesn't skip unfinished level 1.
    assert first_incomplete(LEVELS, done("L3")) == "L1"


def test_all_done():
    assert first_incomplete(LEVELS, done(*LEVELS)) is None
    assert all_complete(LEVELS, done(*LEVELS))
    assert not all_complete(LEVELS, done("L1", "L2", "L4"))
    assert not all_complete([], done())


class _Track:
    def __init__(self, name="Track_Author", hidden=False, override_traits=()):
        self.__name__ = name
        self.is_hidden_unlockable = hidden
        self.override_traits = override_traits


def test_only_tracks_a_player_can_pick_are_selectable():
    assert track_is_selectable(_Track())
    assert not track_is_selectable(_Track(hidden=True))
    # EA uses override_traits for the FTUE/tutorial tracks (Settling In, the tutorial's
    # Style/Painter/Athlete/Culinary milestones).
    assert not track_is_selectable(_Track(override_traits=("trait_FTUE",)))
    assert track_is_selectable(_Track(override_traits=()))
    assert not track_is_selectable(_Track(name="FTUE_Style"))
    assert not track_is_selectable(_Track(name="FTUE_Athlete"))


def test_index_and_finished_tracks():
    index = index_tracks([("Author", ["A1", "A2"]), ("Chef", ["C1", "C2"])])
    assert index["A1"] == ["Author"]
    assert tracks_to_finish("A2", index, done("A1", "A2")) == ["Author"]
    assert tracks_to_finish("A2", index, done("A2")) == []


def test_ahead_of():
    assert ahead_of(LEVELS, done("L1", "L3", "L4")) == ["L3", "L4"]
    assert ahead_of(LEVELS, done("L1")) == []
    assert ahead_of(LEVELS, done(*LEVELS)) == []
