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


def track_is_selectable(track):
    """True when the player could pick this aspiration track at all.

    Two kinds of track are not selectable and must never be completed ahead of time:
    - `is_hidden_unlockable`: EA says these are "never able to be selected in CAS, even if
      unlocked" (they are assigned by gameplay, e.g. scenarios).
    - `override_traits`: EA uses this tunable for the FTUE/tutorial tracks (Settling In,
      the tutorial's Style/Painter/Athlete/Culinary milestones).
    A track with neither is a normal aspiration: selected or not, its levels count.
    """
    if getattr(track, "is_hidden_unlockable", False):
        return False
    if getattr(track, "override_traits", None):
        return False
    # Belt and braces: the tutorial tracks are named FTUE_* (FTUE_Style, FTUE_Painter...).
    if str(getattr(track, "__name__", "") or "").upper().startswith("FTUE"):
        return False
    return True


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
