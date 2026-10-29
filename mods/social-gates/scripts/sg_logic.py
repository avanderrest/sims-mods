"""Social Gates - pure rules (no game imports, covered by tests).

Three gates, all optional:

Friendship
  is_friend(score, threshold) - "friend" is a friendship-track score, not a bit, so it works
  for every age and pack and doesn't depend on EA's relationship-bit ids.

Clubs
  - A Sim may only join a club that has at least one restriction they match: a trait from
    its trait restrictions, a skill from its skill restrictions, or a skill used by one of
    its activities. (EA's own membership criteria still apply on top.)
  - "Household value" restrictions are relative to the club leader's household, instead of
    the game's three fixed brackets. The labels become:
      Poor    = poorer than the leader   (below leader x (1 - band))
      Average = similar to the leader    (leader x (1 - band) ... leader x (1 + band))
      Rich    = richer than the leader   (above leader x (1 + band))
    The leader is the only Sim who can edit the club, so the range follows whoever leads it.
  - Wealth is only checked when a Sim joins; it is never a reason to remove someone who is
    already a member.
  - Editing a club never removes anyone; Sims who no longer match simply stay members and
    stop being offered in the add-member picker. Close relatives, household members and
    friends are also never removed by the game's own membership checks.
  - Sims outside that circle are only offered for adding when they would enjoy at least one
    of the club's activities: their traits or Likes preferences match ACTIVITY_INTERESTS.
"""
import re

POOR = 0
AVERAGE = 1
RICH = 2

_CATEGORY_NAMES = {POOR: "Poor", AVERAGE: "Average", RICH: "Rich"}


def group_affordances(group):
    """Every interaction a ClubInteractionGroup tuning class offers.

    A club rule's `action` is the tuning class itself, not an instance, and tuning classes
    aren't iterable: the interactions live in its `affordances` and `affordance_lists`
    fields (the same way npc_main reads them).
    """
    found = set(getattr(group, "affordances", ()) or ())
    for affordance_list in getattr(group, "affordance_lists", ()) or ():
        found.update(affordance_list)
    return found


def _category(value):
    if isinstance(value, str):
        return value.strip().lower()
    return value


def category_name(value):
    key = _category(value)
    if isinstance(key, str):
        for number, name in _CATEGORY_NAMES.items():
            if name.lower() == key:
                return name
        return str(value)
    return _CATEGORY_NAMES.get(key, str(value))


def category_meaning(value):
    """What the game's three labels mean in this mod: poorer / similar / richer."""
    key = _category(value)
    if key in (POOR, "poor"):
        return "poorer than the leader"
    if key in (AVERAGE, "average"):
        return "similar to the leader"
    if key in (RICH, "rich"):
        return "richer than the leader"
    return str(value)


def is_friend(score, threshold):
    """A friendship score at or above the threshold. None/unknown is not a friend."""
    return score is not None and score >= threshold


def club_exempt(close_relative=False, same_household=False, friend=False):
    """True when a Sim is exempt from a club's interest filter and from removal.

    Close relatives, household members and friends keep their club place even when the
    club's trait, skill or wealth restrictions no longer match them, and they are always
    offered in the add-member picker. Club edits never remove anyone; this covers the
    game's own event-driven checks.
    """
    return bool(close_relative or same_household or friend)


# --- Club interest: traits and Likes that make a Sim want to join ----------------------
# Preference (Likes/Dislikes) traits all share this prefix; the suffix names the like.
_LIKE = "trait_SimPreference_Likes_"

# Every base-game personality/reward trait. The table below must cover each one somewhere,
# so a Sim with any base-game trait has at least one club activity to be interested in.
BASE_GAME_TRAITS = (
    "trait_Active", "trait_Ambitious", "trait_ArtLover", "trait_Bookworm", "trait_Bro",
    "trait_Cheerful", "trait_Childish", "trait_Clumsy", "trait_Creative", "trait_Erratic",
    "trait_Evil", "trait_FamilyOriented", "trait_Foodie", "trait_Geek", "trait_Genius",
    "trait_Gloomy", "trait_Glutton", "trait_Good", "trait_Goofball", "trait_GymRat",
    "trait_HatesChildren", "trait_HotHeaded", "trait_Jealous",
    "trait_Kleptomaniac", "trait_Lazy", "trait_Loner", "trait_LovesOutdoors",
    "trait_Materialistic", "trait_Mean", "trait_MusicLover", "trait_Neat", "trait_Noncommittal",
    "trait_Outgoing", "trait_Perfectionist", "trait_Romantic", "trait_SelfAssured",
    "trait_Slob", "trait_Snob",
)


def _activity(keywords, traits, likes=(), like_prefixes=()):
    return {"keywords": keywords, "traits": traits,
            "likes": tuple(_LIKE + name for name in likes),
            "like_prefixes": like_prefixes}


# Each activity a club can have a rule for, with the words its tuning name or skill uses,
# a few traits that would enjoy it, and at least one matching Like preference. Packs add
# extra entries; a Like/trait the player does not own simply never matches.
ACTIVITY_INTERESTS = {
    "painting": _activity(
        ("paint", "canvas", "easel"),
        ("trait_Creative", "trait_ArtLover", "trait_Perfectionist"),
        ("Activities_Painting",)),
    "photography": _activity(
        ("photo", "camera"),
        ("trait_ArtLover", "trait_Creative", "trait_Geek"),
        ("Activities_Photography",)),
    "writing": _activity(
        ("writ", "novel", "author"),
        ("trait_Bookworm", "trait_Creative", "trait_Gloomy", "trait_Perfectionist"),
        ("Activities_Writing",)),
    "reading": _activity(
        ("read", "book", "librar"),
        ("trait_Bookworm", "trait_Genius", "trait_Gloomy", "trait_Loner"),
        ("Activities_Writing", "Communication_Stories")),
    "programming": _activity(
        ("program", "comput", "coding"),
        ("trait_Geek", "trait_Genius", "trait_Loner"),
        ("Activities_Programming",)),
    "video_gaming": _activity(
        ("video game", "videogame", "gaming", "gamer", "arcade"),
        ("trait_Childish", "trait_Geek", "trait_Genius", "trait_Goofball"),
        ("Activities_VideoGaming",)),
    "cooking": _activity(
        ("cook", "culinary", "stove", "recipe"),
        ("trait_Creative", "trait_Foodie", "trait_Glutton", "trait_Neat"),
        ("Activities_Cooking",)),
    "baking": _activity(
        ("bak", "cupcake", "cake", "pastry"),
        ("trait_Foodie", "trait_Glutton", "trait_Neat", "trait_Perfectionist"),
        ("Activities_Baking",)),
    "grill": _activity(
        ("grill", "barbecue", "bbq"),
        ("trait_Bro", "trait_Foodie", "trait_LovesOutdoors"),
        ("Activities_Cooking",)),
    "mixology": _activity(
        ("mixolog", "bartend", "bar drink", "cocktail"),
        ("trait_Foodie", "trait_Insider", "trait_MusicLover", "trait_Outgoing"),
        ("Activities_Mixology",)),
    "fitness": _activity(
        ("fitness", "workout", "work out", "working out", "exercise", "gym", "weight"),
        ("trait_Active", "trait_Ambitious", "trait_GymRat", "trait_SelfAssured"),
        ("Activities_Fitness",)),
    "swimming": _activity(
        ("swim", "pool"),
        ("trait_Active", "trait_Childish", "trait_LovesOutdoors"),
        ("Activities_Fitness",)),
    "dancing": _activity(
        ("danc",),
        ("trait_Childish", "trait_DanceMachine", "trait_MusicLover", "trait_Outgoing"),
        ("Activities_Dancing",)),
    "singing": _activity(
        ("sing", "karaoke"),
        ("trait_Creative", "trait_MusicLover", "trait_Outgoing"),
        ("Activities_Singing",)),
    "guitar": _activity(
        ("guitar",),
        ("trait_Creative", "trait_MusicLover"),
        ("Activities_Guitar",)),
    "piano": _activity(
        ("piano",),
        ("trait_Creative", "trait_MusicLover", "trait_Perfectionist", "trait_Snob"),
        ("Activities_Piano",)),
    "violin": _activity(
        ("violin",),
        ("trait_Creative", "trait_MusicLover", "trait_Perfectionist"),
        ("Activities_Violin",)),
    "pipe_organ": _activity(
        ("pipe organ", "pipeorgan"),
        ("trait_Creative", "trait_Gloomy", "trait_MusicLover"),
        ("Activities_PipeOrgan",)),
    "listening_music": _activity(
        ("listen to music", "stereo", "radio", "music"),
        ("trait_DanceMachine", "trait_Gloomy", "trait_Lazy", "trait_MusicLover"),
        like_prefixes=(_LIKE + "Music_",)),
    "dj": _activity(
        ("dj", "deejay", "disc jockey"),
        ("trait_DanceMachine", "trait_Insider", "trait_MusicLover", "trait_Outgoing"),
        ("Activities_DJMixing",)),
    "comedy": _activity(
        ("comedy", "joke", "funny", "standup"),
        ("trait_Cheerful", "trait_Erratic", "trait_Goofball", "trait_Insider", "trait_Outgoing"),
        ("Activities_Comedy",)),
    "mischief": _activity(
        ("mischief", "prank", "trick"),
        ("trait_Evil", "trait_Goofball", "trait_HotHeaded", "trait_Kleptomaniac", "trait_Mean"),
        ("Activities_Mischief",)),
    "sabotage": _activity(
        ("sabotage",),
        ("trait_Evil", "trait_HotHeaded", "trait_Kleptomaniac", "trait_Mean"),
        ("Activities_Mischief",)),
    "swipe": _activity(
        ("swipe", "steal"),
        ("trait_Evil", "trait_HotHeaded", "trait_Kleptomaniac"),
        ("Activities_Mischief",)),
    "fighting": _activity(
        ("fight", "brawl"),
        ("trait_Active", "trait_Evil", "trait_HotHeaded", "trait_Mean"),
        ("Activities_Mischief", "Communication_Arguments")),
    "mean": _activity(
        ("mean", "insult", "rude"),
        ("trait_Evil", "trait_HatesChildren", "trait_HotHeaded", "trait_Jealous", "trait_Mean"),
        ("Activities_Mischief", "Communication_Arguments")),
    "friendly": _activity(
        ("friendly", "socialize", "chat", "be nice"),
        ("trait_Cheerful", "trait_FamilyOriented", "trait_Good", "trait_Insider",
         "trait_Outgoing", "trait_SelfAssured"),
        ("Communication_Compliments", "Communication_SmallTalk")),
    "romantic": _activity(
        ("roman", "kiss", "flirt", "woohoo", "date"),
        ("trait_Jealous", "trait_Noncommittal", "trait_Romantic", "trait_SelfAssured"),
        ("Communication_Flirtation",)),
    "chess": _activity(
        ("chess",),
        ("trait_Ambitious", "trait_Bookworm", "trait_Genius", "trait_Loner",
         "trait_Perfectionist"),
        ("Communication_DeepThoughts", "Activities_Debating")),
    "card_games": _activity(
        ("card game", "cards", "poker"),
        ("trait_Bro", "trait_Childish", "trait_Goofball", "trait_Insider"),
        ("Activities_VideoGaming", "Communication_Jokes")),
    "darts": _activity(
        ("dart",),
        ("trait_Bro", "trait_Clumsy", "trait_Goofball", "trait_Insider"),
        ("Communication_Jokes",)),
    "foosball": _activity(
        ("foosball",),
        ("trait_Active", "trait_Bro", "trait_Insider", "trait_Outgoing"),
        ("Activities_VideoGaming", "Communication_Jokes")),
    "pub_games": _activity(
        ("pub game", "pool table", "pool game", "table game"),
        ("trait_Bro", "trait_Foodie", "trait_Goofball", "trait_Insider"),
        ("Activities_Mixology", "Communication_Jokes")),
    "bowling": _activity(
        ("bowl",),
        ("trait_Active", "trait_Bro", "trait_Clumsy", "trait_Goofball"),
        ("Activities_Bowling",)),
    "basketball": _activity(
        ("basketball",),
        ("trait_Active", "trait_Ambitious", "trait_Bro", "trait_SelfAssured"),
        ("Activities_Fitness",)),
    "soccer": _activity(
        ("soccer", "football"),
        ("trait_Active", "trait_Bro", "trait_Outgoing"),
        ("Activities_Fitness",)),
    "physical_games": _activity(
        ("physical game", "tag", "race", "hide and seek"),
        ("trait_Active", "trait_Bro", "trait_Childish", "trait_Goofball"),
        ("Activities_Fitness",)),
    "llama_game": _activity(
        ("llama",),
        ("trait_Childish", "trait_Goofball", "trait_Insider"),
        ("Activities_VideoGaming", "Communication_Jokes")),
    "puzzles": _activity(
        ("puzzle", "jigsaw"),
        ("trait_Bookworm", "trait_Genius", "trait_Perfectionist"),
        ("Communication_DeepThoughts", "Activities_VideoGaming")),
    "tv": _activity(
        ("tv", "television", "movie", "watch"),
        ("trait_Childish", "trait_Goofball", "trait_Lazy", "trait_Slob"),
        ("Communication_Jokes", "Communication_Stories")),
    "cleaning": _activity(
        ("clean", "tidy", "mop", "vacuum"),
        ("trait_Active", "trait_Neat", "trait_Perfectionist"),
        ("Activities_Handiness",)),
    "handiness": _activity(
        ("handiness", "repair", "fix", "upgrade", "tinker"),
        ("trait_Genius", "trait_Geek", "trait_Neat", "trait_Perfectionist"),
        ("Activities_Handiness",)),
    "gardening": _activity(
        ("garden", "plant", "weed", "tend"),
        ("trait_Foodie", "trait_LovesOutdoors", "trait_Neat"),
        ("Activities_Gardening",)),
    "fishing": _activity(
        ("fish", "angler"),
        ("trait_Foodie", "trait_Gloomy", "trait_Loner", "trait_LovesOutdoors"),
        ("Activities_Fishing",)),
    "frog_hunting": _activity(
        ("frog",),
        ("trait_Childish", "trait_Geek", "trait_LovesOutdoors"),
        ("Activities_Fishing", "Activities_Gardening")),
    "hiking": _activity(
        ("hik",),
        ("trait_Active", "trait_Adventurous", "trait_LovesOutdoors"),
        ("Activities_Fitness", "Activities_RockClimbing")),
    "rock_climbing": _activity(
        ("rock climb", "climb", "climbing wall"),
        ("trait_Active", "trait_Adventurous", "trait_Ambitious", "trait_LovesOutdoors"),
        ("Activities_RockClimbing",)),
    "skiing": _activity(
        ("skiing", "ski slope", "ski lift", "ski run", "skiresort"),
        ("trait_Active", "trait_Adventurous", "trait_LovesOutdoors"),
        ("Activities_Skiing",)),
    "snowboarding": _activity(
        ("snowboard",),
        ("trait_Active", "trait_Adventurous", "trait_Bro", "trait_LovesOutdoors"),
        ("Activities_Snowboarding",)),
    "sledding": _activity(
        ("sled",),
        ("trait_Childish", "trait_Goofball", "trait_LovesOutdoors", "trait_Outgoing"),
        ("Activities_Skiing",)),
    "bonfire": _activity(
        ("bonfire", "campfire", "fire pit"),
        ("trait_Childish", "trait_Insider", "trait_LovesOutdoors", "trait_Outgoing"),
        ("Communication_Stories", "Activities_Cooking")),
    "hot_tub": _activity(
        ("hot tub", "jacuzzi"),
        ("trait_Lazy", "trait_Materialistic", "trait_Romantic"),
        ("Activities_Wellness",)),
    "maze": _activity(
        ("maze", "hedge"),
        ("trait_Childish", "trait_Goofball", "trait_LovesOutdoors"),
        ("Communication_Stories", "Activities_Gardening")),
    "science": _activity(
        ("microscope", "telescope", "science", "experiment"),
        ("trait_Geek", "trait_Genius", "trait_Perfectionist"),
        ("Communication_DeepThoughts", "Activities_Programming")),
    "robotics": _activity(
        ("robot",),
        ("trait_Geek", "trait_Genius", "trait_Perfectionist"),
        ("Activities_Robotics",)),
    "rocket_science": _activity(
        ("rocket",),
        ("trait_Ambitious", "trait_Geek", "trait_Genius"),
        ("Activities_RocketScience",)),
    "wellness": _activity(
        ("wellness", "yoga", "meditat", "massage"),
        ("trait_Active", "trait_Lazy", "trait_Romantic", "trait_SelfAssured"),
        ("Activities_Wellness",)),
    "woodworking": _activity(
        ("woodwork", "wood work", "carpent", "saw"),
        ("trait_Creative", "trait_LovesOutdoors", "trait_Neat", "trait_Perfectionist"),
        ("Activities_Handiness",)),
    "knitting": _activity(
        ("knit",),
        ("trait_Creative", "trait_FamilyOriented", "trait_Loner", "trait_Neat"),
        ("Activities_Knitting",)),
    "cross_stitch": _activity(
        ("cross stitch", "crossstitch", "embroidery"),
        ("trait_Creative", "trait_Neat", "trait_Perfectionist"),
        ("Activities_CrossStitch",)),
    "acting": _activity(
        ("acting", "perform", "drama"),
        ("trait_Creative", "trait_Goofball", "trait_Outgoing", "trait_SelfAssured", "trait_Snob"),
        ("Activities_Acting",)),
    "debate": _activity(
        ("debate", "speech", "argue"),
        ("trait_Ambitious", "trait_Genius", "trait_Outgoing", "trait_SelfAssured"),
        ("Activities_Debating",)),
    "research": _activity(
        ("research", "study"),
        ("trait_Bookworm", "trait_Genius", "trait_Geek"),
        ("Activities_Debating", "Communication_DeepThoughts")),
    "homework": _activity(
        ("homework", "home work"),
        ("trait_Ambitious", "trait_Bookworm", "trait_Childish", "trait_Genius"),
        ("Activities_Writing", "Communication_DeepThoughts")),
    "playground": _activity(
        ("playground", "swing set"),
        ("trait_Active", "trait_Childish", "trait_Goofball", "trait_Outgoing"),
        ("Activities_Fitness",)),
    "toys": _activity(
        ("toy", "doll", "block"),
        ("trait_Childish", "trait_FamilyOriented", "trait_Goofball"),
        ("Communication_Stories", "Communication_Jokes")),
    "puppet": _activity(
        ("puppet",),
        ("trait_Childish", "trait_Creative", "trait_FamilyOriented", "trait_Goofball"),
        ("Communication_Stories", "Communication_Jokes")),
    "closet": _activity(
        ("closet",),
        ("trait_Childish", "trait_Goofball", "trait_Loner"),
        ("Communication_Stories",)),
    "water_slide": _activity(
        ("water slide", "lawn slide", "slip and slide"),
        ("trait_Active", "trait_Childish", "trait_Goofball", "trait_Outgoing"),
        ("Activities_Fitness",)),
    "costumes": _activity(
        ("costume", "dress up", "cosplay"),
        ("trait_Childish", "trait_Goofball", "trait_Outgoing"),
        ("Communication_Jokes",)),
    "sleep": _activity(
        ("sleep", "nap", "bed"),
        ("trait_Gloomy", "trait_Lazy", "trait_Loner", "trait_Slob"),
        ("Activities_Wellness",)),
    "bathe": _activity(
        ("bathe", "shower", "bath", "tub"),
        ("trait_Lazy", "trait_Neat", "trait_Romantic"),
        ("Activities_Wellness",)),
    "browse_web": _activity(
        ("browse", "web", "internet"),
        ("trait_Childish", "trait_Geek", "trait_Lazy", "trait_Loner"),
        ("Activities_Programming", "Communication_Stories")),
    "try_on_outfits": _activity(
        ("outfit", "wardrobe", "dresser", "mirror"),
        ("trait_DanceMachine", "trait_Materialistic", "trait_Snob"),
        ("Communication_Compliments",)),
    "view_art": _activity(
        ("view art", "artwork", "gallery", "museum"),
        ("trait_ArtLover", "trait_Creative", "trait_Materialistic", "trait_Snob"),
        ("Activities_Painting",)),
    "coffee": _activity(
        ("coffee", "espresso", "cafe"),
        ("trait_Foodie", "trait_Insider", "trait_Lazy", "trait_Snob"),
        ("Activities_Mixology", "Activities_Cooking")),
    "bar_drinks": _activity(
        ("bar drink", "bar drinks", "drink bar", "pub drink"),
        ("trait_Foodie", "trait_Glutton", "trait_Insider", "trait_Outgoing"),
        ("Activities_Mixology",)),
    "eat": _activity(
        ("eat", "eating", "meal", "food"),
        ("trait_Foodie", "trait_Glutton", "trait_Lazy", "trait_Slob"),
        ("Activities_Cooking",)),
    "spells": _activity(
        ("spell", "cauldron", "magic"),
        ("trait_Evil", "trait_Genius", "trait_Good"),
        ("Activities_Mischief",)),
    "vampire": _activity(
        ("plasma", "vampire"),
        ("trait_Evil", "trait_MusicLover", "trait_SelfAssured"),
        ("Activities_Mischief",)),
    "alien_powers": _activity(
        ("alien",),
        ("trait_Evil", "trait_Geek", "trait_Genius"),
        ("Activities_Mischief",)),
    "ghost_possess": _activity(
        ("possess",),
        ("trait_Evil", "trait_Goofball", "trait_Mean"),
        ("Activities_Mischief",)),
    "bear_roar": _activity(
        ("roar", "bear"),
        ("trait_Childish", "trait_Goofball", "trait_Outgoing"),
        ("Communication_Jokes",)),
    "conservation": _activity(
        ("conserv", "recycl", "litter", "trash"),
        ("trait_Good", "trait_LovesOutdoors", "trait_Neat"),
        ("Activities_Gardening",)),
    "diving": _activity(
        ("dive", "snorkel"),
        ("trait_Active", "trait_Adventurous", "trait_LovesOutdoors"),
        ("Activities_Fitness",)),
    "excavation": _activity(
        ("excavat", "digging", "dig site"),
        ("trait_Adventurous", "trait_Ambitious", "trait_Genius", "trait_LovesOutdoors"),
        ("Activities_Fishing",)),
    "skating": _activity(
        ("skat",),
        ("trait_Active", "trait_Childish", "trait_Goofball"),
        ("Activities_Fitness",)),
    "juice_fizzing": _activity(
        ("juice", "fizz"),
        ("trait_Creative", "trait_Foodie", "trait_Perfectionist"),
        ("Activities_Mixology",)),
    "fabrication": _activity(
        ("fabricat", "maker"),
        ("trait_Creative", "trait_Geek", "trait_Perfectionist"),
        ("Activities_Handiness",)),
    "flower_arranging": _activity(
        ("flower",),
        ("trait_Creative", "trait_LovesOutdoors", "trait_Neat"),
        ("Activities_Gardening",)),
    "herbalism": _activity(
        ("herbal",),
        ("trait_Genius", "trait_Loner", "trait_LovesOutdoors"),
        ("Activities_Gardening",)),
    "media_production": _activity(
        ("media", "record video", "stream"),
        ("trait_Creative", "trait_Geek", "trait_Outgoing"),
        ("Activities_MediaProduction",)),
    "tarot": _activity(
        ("tarot",),
        ("trait_Genius", "trait_Goofball", "trait_MusicLover"),
        ("Communication_Stories", "Activities_Mischief")),
    "voidcritters": _activity(
        ("voidcritter",),
        ("trait_Childish", "trait_Geek", "trait_Goofball"),
        ("Activities_VideoGaming",)),
}


def _normalize(text):
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(text))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def interest_keys(texts):
    """Activity keys whose keywords appear in the club's activity or skill tuning names."""
    words = " ".join(_normalize(text) for text in texts if text)
    if not words.strip():
        return set()
    padded = " " + words + " "
    return {key for key, info in ACTIVITY_INTERESTS.items()
            if any((" " + keyword) in padded for keyword in info["keywords"])}


def interest_match(activity_keys, trait_names):
    """(ok, reason): would a Sim with these traits/Likes enjoy any of the club's activities?"""
    keys = set(activity_keys or ())
    if not keys:
        return True, "the club has no mapped activities"
    traits = set(trait_names or ())
    for key in keys:
        info = ACTIVITY_INTERESTS.get(key)
        if info is None:
            continue
        if traits.intersection(info["traits"]) or traits.intersection(info["likes"]):
            return True, "interested in {}".format(key)
        for prefix in info["like_prefixes"]:
            if any(trait.startswith(prefix) for trait in traits):
                return True, "likes the kind of thing {}".format(key)
    return False, "none of the club's activities match their traits or likes"


# --- Club wealth labels ----------------------------------------------------------------
_RELATIVE_LABELS = {
    POOR: "Poorer than the club leader",
    AVERAGE: "Similar to the club leader",
    RICH: "Richer than the club leader",
}

# Ranged variants, used in the club rule screen when the leader's household value is known.
# {0.Number}/{1.Number} are localization tokens filled by the game layer.
_RELATIVE_RANGES = {
    POOR: "Poorer than the club leader (under \u00a7{0.Number})",
    AVERAGE: "Similar to the club leader (\u00a7{0.Number}-\u00a7{1.Number})",
    RICH: "Richer than the club leader (\u00a7{0.Number} or more)",
}


def _relative_key(category):
    key = _category(category)
    if isinstance(key, str):
        for number, name in _CATEGORY_NAMES.items():
            if name.lower() == key:
                return number
    return key


def relative_wealth_label(category):
    """The club rule screen label for a household-value category, or None if unknown.

    The game's own labels state fixed ranges. Under `club_relative_wealth` those ranges are
    relative to the club leader, so the club UI uses these labels instead.
    """
    return _RELATIVE_LABELS.get(_relative_key(category))


def relative_wealth_label_with_ranges(category, leader_net_worth, band=0.5):
    """(label, tokens) with the leader-relative range filled in, or None if unknown.

    The label is a localization template; tokens are the numbers for its
    {0.Number}/{1.Number} placeholders. None when there is no usable leader net worth (the
    game layer then shows the plain label above).
    """
    key = _relative_key(category)
    if key not in _RELATIVE_RANGES or leader_net_worth is None or leader_net_worth <= 0:
        return None
    bounds = wealth_bounds(key, leader_net_worth, band)
    if bounds is None:
        return None
    low, high = bounds
    if key == POOR:
        # "under X" is the first value that is not Poor any more.
        return _RELATIVE_RANGES[POOR], (high + 1,)
    if key == AVERAGE:
        return _RELATIVE_RANGES[AVERAGE], (low, high)
    return _RELATIVE_RANGES[RICH], (low,)


def string_key(text):
    """The 32-bit key the game's string tables use for `text`.

    Same FNV-1a hash as tools/tuning.py, so a label here resolves the text shipped in
    mods/social-gates/text/.
    """
    value = 0x811C9DC5
    for byte in text.lower().encode("utf-8"):
        value = (value * 0x01000193) & 0xFFFFFFFF
        value ^= byte
    return value


# --- Relative household value ----------------------------------------------------------
def wealth_bounds(category, leader_net_worth, band=0.5):
    """(low, high) inclusive bounds for one category, relative to the leader; high can be None.

    Returns None when there is no usable leader net worth (the game layer then leaves EA's
    own fixed brackets alone).
    """
    if leader_net_worth is None or leader_net_worth <= 0:
        return None
    band = max(0.0, float(band))
    low = max(0, int(round(leader_net_worth * (1.0 - band))))
    high = int(round(leader_net_worth * (1.0 + band)))
    key = _category(category)
    if key in (POOR, "poor"):
        return (0, max(0, low - 1))
    if key in (AVERAGE, "average"):
        return (low, high)
    if key in (RICH, "rich"):
        return (high + 1, None)
    return None


def in_wealth_range(category, candidate_net_worth, leader_net_worth, band=0.5):
    """True if the candidate fits the category's relative band. Unknown category: True."""
    bounds = wealth_bounds(category, leader_net_worth, band)
    if bounds is None:
        return True
    low, high = bounds
    if candidate_net_worth < low:
        return False
    if high is not None and candidate_net_worth > high:
        return False
    return True


def wealth_description(leader_net_worth, band=0.5):
    """Human-readable bounds for the three categories, for the cheat/log output."""
    if leader_net_worth is None or leader_net_worth <= 0:
        return "no leader net worth; using the game's fixed brackets"
    band = max(0.0, float(band))
    low = max(0, int(round(leader_net_worth * (1.0 - band))))
    high = int(round(leader_net_worth * (1.0 + band)))
    return "Poorer than the leader: under {:,}; Similar: {:,}-{:,}; Richer: over {:,}".format(
        low, low, high, high)


# --- Club admission -------------------------------------------------------------------
def admission_check(sim_traits, sim_skills, trait_requirements=(), skill_requirements=(),
                    activity_skills=(), activity_any_skill=False, require_restriction=True,
                    activity_skill_min=1, min_skill_level=1, interested=False):
    """(ok, reason) for the trait/skill/activity part of joining a club.

    sim_traits/sim_skills use whatever keys the game layer has (trait and skill tuning
    classes). A Sim passes by matching *any one* of the three kinds of restriction, or by
    being `interested` in one of the club's activities (their traits or Likes fit it).
    """
    traits = set(sim_traits or ())
    skills = dict(sim_skills or {})
    wanted_traits = set(trait_requirements or ())
    wanted_skills = set(skill_requirements or ())
    activity_skills = set(activity_skills or ())

    if interested:
        return True, "is interested in the club's activities"

    trait_match = bool(wanted_traits & traits)
    skill_match = any(skills.get(skill, 0) >= min_skill_level for skill in wanted_skills)
    activity_match = any(skills.get(skill, 0) >= activity_skill_min for skill in activity_skills)
    if activity_any_skill and not activity_match:
        activity_match = any(level >= activity_skill_min for level in skills.values())

    has_restrictions = bool(wanted_traits or wanted_skills or activity_skills or activity_any_skill)
    if not has_restrictions:
        if require_restriction:
            return False, "the club has no trait, skill or activity restrictions to match"
        return True, "the club has no restrictions"

    if not (trait_match or skill_match or activity_match):
        parts = []
        if wanted_traits:
            parts.append("{} trait(s)".format(len(wanted_traits)))
        if wanted_skills:
            parts.append("{} skill(s)".format(len(wanted_skills)))
        if activity_skills or activity_any_skill:
            parts.append("its activities")
        return False, "does not match any of the club's {}".format(" / ".join(parts))

    matched = [name for name, ok in (("trait", trait_match), ("skill", skill_match),
                                     ("activity", activity_match)) if ok]
    return True, "matches a club {}".format(" and ".join(matched))


def club_admission(sim_traits, sim_skills, wealth_categories=(), candidate_net_worth=0,
                   leader_net_worth=0, band=0.5, relative_wealth=True, interested=False,
                   **kwargs):
    """The whole admission rule: trait/skill/activity match plus relative wealth.

    Returns (ok, reason). The game layer still runs EA's other membership criteria.
    """
    ok, reason = admission_check(sim_traits, sim_skills, interested=interested, **kwargs)
    if not ok:
        return ok, reason
    if relative_wealth and wealth_categories and leader_net_worth and leader_net_worth > 0:
        for category in wealth_categories:
            if not in_wealth_range(category, candidate_net_worth, leader_net_worth, band):
                bounds = wealth_bounds(category, leader_net_worth, band)
                low, high = bounds
                wanted = "{} ({:,}-{:,})".format(category_meaning(category), low, high) if high is not None \
                    else "{} ({:,}+)".format(category_meaning(category), low)
                return False, "household net worth {:,} is outside the club's {} range".format(
                    candidate_net_worth, wanted)
    return True, reason
