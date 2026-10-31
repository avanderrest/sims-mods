"""Ascent to Royalty - pure gate logic (no game imports, covered by tests).

The game's Noble career promotes a Sim one level at a time. Before each promotion we build
a rank from the level being moved to and list what the Sim is still missing. The game layer
then asks the player-visible settings which kinds of requirement to enforce.

The rules are simple: to move up, a Noble needs the next rank's net worth and the right
number of friends outside their own dynasty. The friendship asks for more as the title
rises: ordinary dynasty members first, then dynasty heads, then members and heads of royal
dynasties. The final step (Grand Duke to Monarch) is only about the throne: there must be no
Monarch in the region.

Nothing here reads the save: callers pass net worth, the friend facts and the throne fact
in. That keeps the whole rule set testable outside the game.
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
# One friend outside the Sim's own dynasty, with the facts the friendship ladder reads.
# `head` means the friend is the head of their dynasty; `royal` means that dynasty is royal
# (its head holds a Noble title).
Friend = namedtuple("Friend", "name head royal")

NET_WORTH = "net_worth"
FRIEND = "friend"
MONARCH = "monarch"
CHECKS = (NET_WORTH, FRIEND, MONARCH)

# Friend requirement by rung of the ladder (rank_index_for_level). None means no friendship
# requirement at that rank.
#   1 Baronet: one dynasty member       2 Baron: two dynasty members
#   3 Viscount: one dynasty head        4 Count: one royal dynasty member
#   5 Margrave: two royal members       6 Marquess: one royal dynasty head
#   7 Duke: two royal dynasty heads     8 Grand Duke / 9 Monarch: no friendship requirement
FRIEND_TIERS = {
    1: ("member", 1),
    2: ("member", 2),
    3: ("head", 1),
    4: ("royal_member", 1),
    5: ("royal_member", 2),
    6: ("royal_head", 1),
    7: ("royal_head", 2),
}

# Singular and plural wording for each kind of friend.
FRIEND_WORDING = {
    "member": ("a dynasty member", "dynasty members"),
    "head": ("a dynasty head", "dynasty heads"),
    "royal_member": ("a royal dynasty member", "royal dynasty members"),
    "royal_head": ("a royal dynasty head", "royal dynasty heads"),
}



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


def friend_requirement(level, max_level):
    """(kind, count) for the promotion to `level`, or None when no friend is required."""
    return FRIEND_TIERS.get(rank_index_for_level(level, max_level))


def friend_counts(friends):
    """How many friends satisfy each kind of the friendship ladder.

    `friends` is an iterable of Friend. Everyone in it already belongs to a dynasty outside
    the Sim's own, so a dynasty member is any entry; a head also counts as a member, and a
    royal head also counts as a royal member.
    """
    counts = {"member": 0, "head": 0, "royal_member": 0, "royal_head": 0}
    for friend in friends or ():
        counts["member"] += 1
        if friend.head:
            counts["head"] += 1
            if friend.royal:
                counts["royal_head"] += 1
        if friend.royal:
            counts["royal_member"] += 1
    return counts


def friend_requirement_text(kind, count):
    """The requirement without the current count: 'friends with 2 dynasty heads'."""
    singular, plural = FRIEND_WORDING[kind]
    if count == 1:
        return "friends with {}".format(singular)
    return "friends with {} {}".format(count, plural)


def friend_text(kind, count, have):
    """The player-facing line for one kind of friend requirement."""
    return "{} (have {})".format(friend_requirement_text(kind, count), have)


def requirements(level, max_level, net_worth, friends=None, throne_empty=True,
                 inherited=False, checks=None):
    """Every requirement for the promotion to `level`, met or not.

    `net_worth` is the household's total worth; `friends` is the list of friends outside the
    Sim's own dynasty (see Friend). The friendship ladder asks for more at each rung: one
    dynasty member, two, one dynasty head, one royal dynasty member, two, one royal dynasty
    head, two. From Grand Duke to Monarch there is no friendship requirement, only the
    vacant throne.

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
    need = friend_requirement(level, max_level)
    if FRIEND in checks and need is not None:
        kind, count = need
        counts = friend_counts(friends)
        have = counts[kind]
        found.append(Requirement(FRIEND, friend_text(kind, count, have), have >= count))
    return found


def missing(level, max_level, net_worth, friends=None, throne_empty=True,
            inherited=False, checks=None):
    """Everything still missing for the promotion to `level`.

    Returns a list of Failure, empty when the promotion is allowed. `checks` is the set of
    kinds to enforce (None means all).

    Inherited, married-in and claimed titles always pass: the pack's succession must keep
    working, and refusing one inside the promotion hook would make the pack believe the title
    passed when it did not. The gate is on the earned promotion path only.
    """
    return [Failure(row.kind, row.text) for row in requirements(
        level, max_level, net_worth, friends=friends, throne_empty=throne_empty,
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


# A dynasty the host can invite from: `prestige` is the pack's dynasty prestige and
# `royal` is true when its head holds a Noble title.
InviteDynasty = namedtuple("InviteDynasty", "key prestige royal")


def closest_dynasty(host_prestige, dynasties, royal_only=False):
    """The dynasty to invite from: closest in prestige to the host's, or the lowest one.

    `dynasties` is an iterable of InviteDynasty. A host with no dynasty (`host_prestige` is
    None) has no prestige to compare with, so the lowest-prestige dynasty is chosen. With
    `royal_only` the pool is narrowed to royal dynasties first; None means there is nobody
    to invite. Ties go to the lower prestige, then the key, so the result is stable.
    """
    pool = [dynasty for dynasty in dynasties if dynasty.royal or not royal_only]
    if not pool:
        return None
    if host_prestige is None:
        return min(pool, key=lambda dynasty: (dynasty.prestige, dynasty.key))
    return min(pool, key=lambda dynasty: (
        abs(dynasty.prestige - host_prestige), dynasty.prestige, dynasty.key))
