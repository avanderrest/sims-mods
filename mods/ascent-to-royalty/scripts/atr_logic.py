"""Ascent to Royalty - pure gate logic (no game imports, covered by tests).

The game's Noble career promotes a Sim one level at a time. Before each promotion we build
a rank from the level being moved to and list what the Sim is still missing. The game layer
then asks the player-visible settings which kinds of requirement to enforce.

The rules are simple: to move up, a Noble needs the next rank's net worth and a friendship
with someone at their current rank or above. The final step (Grand Duke to Monarch) is only
about the throne: there must be no Monarch in the region.

Nothing here reads the save: callers pass net worth, the highest friend rank and the throne
fact in. That keeps the whole rule set testable outside the game.
"""
from collections import namedtuple

# The ten adult titles of the native Noble career, in order. Level 0 is the first rung and
# the highest level is the Monarch. rank_for_level() stretches this ladder if a patch ever
# changes the number of levels, so it cannot crash.
#
# net_worth is the household net worth (funds plus home) asked for on the way to that rank.
# The numbers follow the old savings ladder so existing saves keep a familiar climb; the
# Monarch number is unused because the crown is decided by the throne, not by wealth.
Rank = namedtuple("Rank", "male female net_worth")
RANKS = (
    Rank("Knight", "Dame", 25000),
    Rank("Baronet", "Baronetess", 35000),
    Rank("Baron", "Baroness", 50000),
    Rank("Viscount", "Viscountess", 70000),
    Rank("Count", "Countess", 90000),
    Rank("Margrave", "Margravine", 110000),
    Rank("Marquess", "Marchioness", 130000),
    Rank("Duke", "Duchess", 160000),
    Rank("Grand Duke", "Grand Duchess", 200000),
    Rank("Monarch", "Monarch", 250000),
)

# What missing() reports. `kind` is what the settings switch on/off.
Failure = namedtuple("Failure", "kind text")
# What requirements() reports: the same text, whether it is already met, and the kind.
Requirement = namedtuple("Requirement", "kind text met")

NET_WORTH = "net_worth"
FRIEND = "friend"
MONARCH = "monarch"
CHECKS = (NET_WORTH, FRIEND, MONARCH)


def clamp_level(level, max_level):
    return max(0, min(int(max_level), int(level)))


def is_crown(level, max_level):
    """True for the top title in this game build (the one with one holder per world)."""
    return clamp_level(level, max_level) >= int(max_level) and int(max_level) > 0


def rank_index_for_level(level, max_level):
    """Map a native career level onto our ladder.

    Level 0 is the first (Knight) rung and the highest native level is the Monarch. With the
    pack's ten levels this is one-to-one. A build with more or fewer levels spreads the
    ladder evenly, rounding to the nearest rank.
    """
    max_level = max(1, int(max_level))
    position = clamp_level(level, max_level) / float(max_level)
    return int(round(position * (len(RANKS) - 1)))


def rank_for_level(level, max_level):
    return RANKS[rank_index_for_level(level, max_level)]


def title_for(rank, female=False):
    return rank.female if female else rank.male


def rank_title(level, max_level, female=False):
    return title_for(rank_for_level(level, max_level), female)


def friend_title(friend_rank, female=False):
    """Title for a rank index, or None when the Sim has no noble friend."""
    if friend_rank is None or int(friend_rank) < 0:
        return None
    index = min(len(RANKS) - 1, int(friend_rank))
    return title_for(RANKS[index], female)


def requirements(level, max_level, net_worth, dynasty_friend, throne_empty=True,
                 inherited=False, checks=None):
    """Every requirement for the promotion to `level`, met or not.

    `net_worth` is the household's total worth; `dynasty_friend` is the name of a friend
    outside the Sim's own dynasty (None when there is none). Rank no longer enters the
    friendship rule: too few sims in a default save hold a title, and a friend from outside
    the family is an alliance worth having. For the crown the only requirement is that no higher rank
    (another Monarch) is in the region.

    This is the player-facing view (the career panel and the requirements command list all
    of these); the gate itself only needs missing(). `checks` is the set of kinds to include
    (None means all). Inherited, married-in and claimed titles have no requirements at all.
    """
    level = clamp_level(level, max_level)
    if inherited:
        return []
    checks = set(CHECKS if checks is None else checks)
    found = []
    if is_crown(level, max_level):
        if MONARCH in checks:
            found.append(Requirement(MONARCH, "no Monarch in the region", bool(throne_empty)))
        return found
    rank = rank_for_level(level, max_level)
    if NET_WORTH in checks:
        have = net_worth or 0
        found.append(Requirement(NET_WORTH, "§{} net worth (have §{})".format(
            format_money(rank.net_worth), format_money(have)), have >= rank.net_worth))
    if FRIEND in checks:
        found.append(Requirement(
            FRIEND,
            "a friend outside your dynasty (have: {})".format(dynasty_friend or "none"),
            bool(dynasty_friend)))
    return found


def missing(level, max_level, net_worth, dynasty_friend, throne_empty=True,
            inherited=False, checks=None):
    """Everything still missing for the promotion to `level`.

    Returns a list of Failure, empty when the promotion is allowed. `checks` is the set of
    kinds to enforce (None means all).

    Inherited, married-in and claimed titles always pass: the pack's succession must keep
    working, and refusing one inside the promotion hook would make the pack believe the title
    passed when it did not. The gate is on the earned promotion path only.
    """
    return [Failure(row.kind, row.text) for row in requirements(
        level, max_level, net_worth, dynasty_friend, throne_empty=throne_empty,
        inherited=inherited, checks=checks) if not row.met]


def allowed(*args, **kwargs):
    return not missing(*args, **kwargs)


def failure_text(failures):
    return ", ".join(failure.text for failure in failures)


def format_money(value):
    """§1,200,000 rather than 1200000, for console lines and notifications."""
    try:
        return "{:,}".format(int(value))
    except (TypeError, ValueError):
        return str(value)


def noble_guests(nobles, my_level):
    """The nobles who answer a summon from a Sim at `my_level`: that rank or below.

    `nobles` is an iterable of (sim_info, level). A higher-ranked noble does not answer a
    lower one, so a Duke's invitation reaches Dukes, Marquesses and everyone beneath them,
    while a Knight's reaches only Knights. Commoners (no level) are never included.
    """
    if not my_level:
        return []
    return [(sim_info, level) for sim_info, level in nobles
            if level is not None and 0 < level <= my_level]
