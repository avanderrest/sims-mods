"""Aspiration Progress - pure logic (no game imports, covered by tests).

The game's aspiration "levels" are milestones; a track (an aspiration like Bestselling
Author) is an ordered list of them. These helpers decide what to do when any level of any
track gets completed, in whatever order.
"""


def first_incomplete(levels_in_order, is_completed):
    """The level the sim should be working on: the first one not done yet, or None when
    every level is done. Completed levels are skipped, wherever they are."""
    for level in levels_in_order:
        if not is_completed(level):
            return level
    return None


def all_complete(levels, is_completed):
    levels = list(levels)
    return bool(levels) and all(is_completed(level) for level in levels)


def index_tracks(tracks):
    """tracks: iterable of (track, [level, ...]) -> {level: [track, ...]} (a level can in
    principle belong to more than one track)."""
    index = {}
    for track, levels in tracks:
        for level in levels:
            index.setdefault(level, []).append(track)
    return index


def tracks_to_finish(level, index, is_completed):
    """Tracks that the completion of `level` has just finished (every level now done)."""
    return [track for track in index.get(level, ())
            if all_complete([lv for lv, tracks in index.items() if track in tracks], is_completed)]


def ahead_of(levels_in_order, is_completed):
    """Levels the sim hasn't reached yet in this track but already completed - for the
    status cheat."""
    current = first_incomplete(levels_in_order, is_completed)
    if current is None:
        return []
    order = list(levels_in_order)
    start = order.index(current)
    return [lv for lv in order[start + 1:] if is_completed(lv)]
