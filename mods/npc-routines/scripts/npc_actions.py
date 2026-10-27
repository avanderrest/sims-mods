"""NPC Routines - turning the interactions on a lot into a numbered list of choices.

Pure logic (no game imports): npc_main.py walks the real objects and interactions and
hands the raw names here, this module cleans them into labels a language model can read
and drops the ones a script cannot usefully push. The LLM may only pick from the list it
is given, so this is also where the list stays small enough to be one clean prompt.
"""
import inspect
import random
import re

# How many choices the prompt may offer. A 3B model still picks reliably from ~40 numbered
# lines; more than that mostly adds noise (and prompt tokens) without adding real choice.
MAX_ACTIONS = 40
# One chatty object (a fridge, a bookshelf) can offer dozens of variants; take its best few.
MAX_PER_OBJECT = 8

# Words in a tuning name that carry no meaning for a decision. They differ only between
# implementation variants (autonomous vs the player's version, staging vs direct).
LABEL_FILLER = frozenset({"autonomous", "autonomously", "staging", "resume", "object",
                          "generic", "nonretail", "picker"})

# Words in a tuning name that mean "not an action a character would choose": menu/debug
# plumbing, containers, career/quest gimmicks, or things the script layer cannot drive.
SKIP_WORDS = frozenset({
    "debug", "cheat", "test", "carry", "put", "drop", "inventory", "teleport",
    "rabbit", "rabbithole", "spawn", "hidden", "blueprint", "cancel", "cta", "fgl",
    "select", "selection", "system", "placeholder", "unused", "deprecated", "tutorial",
    "career", "civil", "designer", "concept", "submit", "quest", "scenario", "objective",
    "ghost", "possess", "sinister", "abilities", "transform", "ray", "prototype",
    # NPC/situation-driven behaviour: the butler, pets acting up, community votes, fame
    # perks... They are real interactions, but never a choice the player would make for a sim.
    "situation", "butler", "sabotage", "misbehavior", "reaction", "stand", "vote", "policy",
    "repeal", "community", "fame", "perks", "donate", "landlord", "knock", "intensity",
    "color", "hijack", "autonomy", "npc",
    # Eco Lifestyle object upgrades ("eco upgrades siphoner shower"): pushed from here they
    # always fail their own state check, and the word "shower" made them look like hygiene.
    "upgrade", "upgrades", "eco",
    # knitting affordances that need a crafting process the object does not have
    "knit",
    # rally/ensemble interactions need a group around the sim and just queue otherwise
    "rally", "ensemble", "rallyable",
    # Cleaning interactions are tuned onto counters/tables but belong to the maid's cleaning
    # situation ("SituationRunningTest: No situation matching"), so they can never start here.
    "clean", "cleanup", "tidy", "mop", "sweep", "vacuum",
})

_PREFIXES = ("object_", "terrain-", "terrain_", "mixer_", "social_", "si_", "interaction_",
             "super_", "autonomous_", "buff_", "whim_", "goal_", "situation_goal_")

MIN_WAIT_MINUTES = 5
MAX_WAIT_MINUTES = 480
DEFAULT_WAIT_MINUTES = 60


def clean_label(tuning_name):
    """'object_tableDining_1x1' -> 'table dining 1x1', 'terrain-jog_Autonomous' -> 'jog'."""
    name = str(tuning_name or "").strip()
    lowered = name.lower()
    for prefix in _PREFIXES:
        while lowered.startswith(prefix):
            name = name[len(prefix):]
            lowered = name.lower()
    name = re.sub(r"[_\-]+", " ", name)
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    words, unique = re.sub(r"\s+", " ", name).strip().lower().split(), []
    for word in words:
        if word and word not in LABEL_FILLER and word not in unique:
            unique.append(word)
    return " ".join(unique)


def is_usable(label):
    """False for labels that read as tuning noise or that the script cannot sensibly push."""
    if not label or len(label) < 3:
        return False
    words = label.split()
    if len(words) > 7:
        return False
    return not any(word.startswith(bad) for word in words for bad in SKIP_WORDS)


# Things a character actually does (cleaning is not one of them: see SKIP_WORDS). Raw tuning
# names are full of internal bookkeeping
# ("immediate check policies mailbox", "change celebrity disguise", "eco upgrades completed
# display siphoner"), and a pick that cannot be started is worse than a shorter list.
ACTION_STEMS = frozenset({
    "sit", "lie", "sleep", "nap", "rest", "relax", "lounge",
    "eat", "drink", "cook", "bake", "grab", "meal", "snack", "serve",
    "shower", "bath", "wash", "toilet", "pee", "potty", "brush", "flush", "use",
    "read", "watch", "play", "dance", "paint", "draw", "sketch", "craft", "photograph",
    "practice", "practise", "write", "garden", "harvest", "weed", "water", "fish", "dig",
    "plant", "sow", "seed", "fertilize", "tend",
    "collect", "jog", "swim", "workout", "exercise", "fitness",
    "call", "chat", "talk", "social", "hug", "kiss", "pet", "feed",
    "repair", "fix",
    "bills", "homework", "meditate", "stargaze", "sing", "guitar", "piano", "violin",
    "chess", "computer", "browse", "game", "sculpt", "knit", "make",
})
MAX_ACTION_WORDS = 4


# Balancing the list: one chatty object (a fridge with eight dessert variants) must not fill
# half the options. Cap how many things of the same kind and per category get in.
MAX_PER_CATEGORY = 6
MAX_PER_ACTION = 2


# Words that merely start with an action stem ("single" -> "sing"). Object names are full of
# these, and they would make the balancing think two unrelated things are the same verb.
FALSE_ACTION_WORDS = frozenset({"single", "singles", "simple", "simpler"})


def primary_action(label):
    """The action word of a label ('fridge bake cake' -> 'bake'), longest stem wins."""
    for word in str(label or "").lower().split():
        if word in FALSE_ACTION_WORDS:
            continue
        if word in ACTION_STEMS:
            return word
        matches = [stem for stem in ACTION_STEMS if word.startswith(stem)]
        if matches:
            return max(matches, key=len)
    return None


def balance(candidates, per_category=MAX_PER_CATEGORY, per_action=MAX_PER_ACTION):
    """Keeps the list varied: at most per_category things per group and per_action per verb."""
    by_category, by_action, kept = {}, {}, []
    for candidate in candidates or ():
        category = category_for(candidate.label)
        action = primary_action(candidate.label)
        if by_category.get(category, 0) >= per_category:
            continue
        if action and by_action.get(action, 0) >= per_action:
            continue
        by_category[category] = by_category.get(category, 0) + 1
        if action:
            by_action[action] = by_action.get(action, 0) + 1
        kept.append(candidate)
    return kept


def is_action(label):
    """True when the label reads like something a person would do, not tuning bookkeeping."""
    words = str(label or "").lower().split()
    if not words or len(words) > MAX_ACTION_WORDS:
        return False
    return any(word.startswith(stem) for word in words for stem in ACTION_STEMS)


# A refused action is not refused forever: "empty trash" fails when the bin is empty and works
# later, so it comes back after this many sim hours.
BLACKLIST_HOURS = 6


def still_failed(when, now_days, hours=BLACKLIST_HOURS):
    """True while a previously refused label should stay out of the list."""
    try:
        return (float(now_days) - float(when)) * 24.0 < hours
    except (TypeError, ValueError):
        return False


MAX_VARIANTS = 4


class Candidate:
    """One thing the sim could do: the label that goes in the prompt, plus the game's own
    interactions to push it with. Several objects usually offer the same thing ("sit"), and
    each variant can have different requirements - so the extras are fallbacks, tried in
    order, instead of one variant deciding whether the whole label works."""

    __slots__ = ("label", "affordance", "target", "extras")

    def __init__(self, label, affordance=None, target=None):
        self.label = label
        self.affordance = affordance
        self.target = target
        self.extras = []

    def variants(self):
        if self.affordance is not None:
            yield self.affordance, self.target
        for affordance, target in self.extras:
            yield affordance, target

    def __repr__(self):
        return "<{} on {} ({} variant{})>".format(
            self.label, self.target, 1 + len(self.extras), "" if not self.extras else "s")


def build_candidates(entries, limit=MAX_ACTIONS, skip=()):
    """entries: iterable of (label, affordance, target), already in preference order. One
    Candidate per label; repeats become fallback variants. Unusable/refused labels are dropped."""
    skip = set(skip or ())
    by_label, candidates = {}, []
    for label, affordance, target in entries:
        if label in skip or not is_usable(label):
            continue
        existing = by_label.get(label)
        if existing is not None:
            if len(existing.extras) < MAX_VARIANTS - 1:
                existing.extras.append((affordance, target))
            continue
        candidate = Candidate(label, affordance, target)
        by_label[label] = candidate
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


def interleave(groups, limit=MAX_ACTIONS):
    """Round-robin several entry lists instead of concatenating them, so one chatty object
    (a fridge, a bookshelf) cannot crowd the rest of the lot out of a short list."""
    out, index = [], 0
    while len(out) < limit:
        added = False
        for group in groups:
            if index < len(group):
                out.append(group[index])
                added = True
                if len(out) >= limit:
                    break
        if not added:
            break
        index += 1
    return out


def clamp_minutes(minutes):
    """The LLM's chosen wait, kept sane (it can say anything)."""
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return DEFAULT_WAIT_MINUTES
    return max(MIN_WAIT_MINUTES, min(MAX_WAIT_MINUTES, minutes))


def format_minutes(minutes):
    minutes = int(minutes)
    if minutes < 60:
        return "{} min".format(minutes)
    hours, rest = divmod(minutes, 60)
    return "{}h".format(hours) if not rest else "{}h {}m".format(hours, rest)


# While an action we started is running, look again this often: a dig site takes a few
# minutes, so waiting the full hour the model asked for would leave the sim idle.
CHECK_MINUTES = 5


def next_check_minutes(remaining_minutes, check=CHECK_MINUTES):
    """How long to wait before looking at a running action again (never past its deadline)."""
    try:
        remaining = int(remaining_minutes)
    except (TypeError, ValueError):
        return check
    return max(1, min(check, remaining))


def request_key(text):
    """A stable key for "the same wish", so 'An easel.' and 'easel' count as one request
    instead of letting rephrasing slip past the once-an-hour reminder limit."""
    words = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return " ".join(w for w in words if w not in ("a", "an", "the", "some", "more", "please"))


# Prompt categories, in the order they are shown. A label joins the first group with a
# matching word. The point is to let a small model focus on a handful of related choices at
# a time, not to reproduce the game's own menu taxonomy.
CATEGORIES = (
    ("Hygiene and toilet", frozenset({
        "toilet", "pee", "shower", "bath", "wash", "sink", "brush", "flush", "hygiene"})),
    ("Eat and drink", frozenset({
        "eat", "drink", "cook", "meal", "snack", "fridge", "stove", "coffee", "tea", "bar",
        "cake", "dessert", "food", "grill", "microwave", "juice", "water", "serving", "serve"})),
    ("Rest and comfort", frozenset({
        "sleep", "nap", "bed", "sofa", "couch", "sit", "lie", "relax", "lounge", "rest"})),
    ("Fun and hobbies", frozenset({
        "tv", "watch", "read", "book", "game", "chess", "play", "paint", "easel", "draw",
        "craft", "music", "guitar", "piano", "dance", "stereo", "sketch", "photograph"})),
    ("Skills and work", frozenset({
        "write", "practice", "practise", "skill", "homework", "workout", "fitness", "exercise",
        "repair", "upgrade", "garden"})),
    ("Social", frozenset({
        "call", "chat", "talk", "social", "hug", "kiss", "invite", "greet", "group", "phone",
        "text", "joke"})),
    ("Outside", frozenset({
        "jog", "swim", "fish", "plant", "outdoors", "outdoor", "stargaze"})),
)
OTHER_CATEGORY = "Other"
CATEGORY_ORDER = {name: index for index, (name, _keywords) in enumerate(CATEGORIES)}


# What a goal needs, so the prompt can point out when the lot cannot serve it (a painter with
# no easel). Not a game database: the stems only decide whether *something* on the lot can do
# it, and the examples are plural on purpose - packs add their own objects (sketchpads,
# activity tables, murals), so the model is told "e.g. an easel" and may name anything.
GOAL_HINTS = (
    (("paint", "painter", "artist"), "painting",
     ("paint", "draw", "easel", "sketch", "mural")),
    (("write", "writer", "author", "novelist"), "writing", ("write", "computer", "type")),
    (("cook", "chef", "bak"), "cooking", ("cook", "bake")),
    (("mixolog", "bartend"), "mixology", ("mix", "bar", "drink")),
    (("fish",), "fishing", ("fish",)),
    (("garden", "gardener"), "gardening", ("garden", "harvest", "weed", "plant")),
    (("fit", "workout", "athlet", "muscl"), "working out",
     ("workout", "exercise", "jog", "swim")),
    (("read", "book"), "reading", ("read",)),
    (("program", "coder", "hacker"), "programming", ("program", "computer", "hack")),
    (("piano",), "piano", ("piano",)),
    (("guitar",), "guitar", ("guitar",)),
    (("violin",), "violin", ("violin",)),
    (("sing", "singer"), "singing", ("sing", "karaoke", "microphone")),
    (("photo", "photograph"), "photography", ("photo", "camera")),
    (("wellness", "yoga", "medit"), "wellness", ("medit", "yoga", "massage")),
    (("woodwork", "carpent"), "woodworking", ("woodwork", "workbench", "craft")),
    (("knit",), "knitting", ("knit",)),
    (("chess",), "chess", ("chess",)),
)

# A few things that would do; never a requirement (the mod cannot buy them either).
GOAL_EXAMPLES = {
    "painting": ("an easel", "a sketchpad", "an activity table"),
    "writing": ("a computer", "a notebook", "a typewriter"),
    "cooking": ("a stove", "a fridge", "a counter"),
    "mixology": ("a bar",),
    "fishing": ("a fishing spot", "bait"),
    "gardening": ("a planter box", "a garden plot"),
    "working out": ("a treadmill", "workout equipment"),
    "reading": ("a bookshelf",),
    "programming": ("a computer",),
    "piano": ("a piano",),
    "guitar": ("a guitar",),
    "violin": ("a violin",),
    "singing": ("a microphone", "a karaoke machine"),
    "photography": ("a camera", "a tripod"),
    "wellness": ("a yoga mat", "a meditation stool"),
    "woodworking": ("a workbench",),
    "knitting": ("knitting needles",),
    "chess": ("a chess table",),
}


# Actions that happen outside, so the weather is worth spelling out in the option.
# Prefix-matched: "fishing" and "gardening" count for "fish"/"garden".
OUTDOOR_STEMS = ("jog", "swim", "fish", "dig", "collect", "garden", "harvest", "plant",
                 "stargaze", "weed", "water")


WEATHER_TEMPERATURES = {
    "freezing": "freezing", "cold": "cold", "cool": "cool",
    "warm": "warm", "hot": "hot", "burning": "scorching",
}


def weather_note(label, weather):
    """' in the cold rain', ' in the snow', ' in the sun' - for outdoor actions only.

    Detail on the action, not a general weather report: "jog in the cold rain" lets the model
    read the conditions without being handed "the weather" as a problem to solve.
    """
    text = str(weather or "").lower()
    if not text:
        return ""
    words = str(label or "").lower().split()
    if not any(word.startswith(stem) for word in words for stem in OUTDOOR_STEMS):
        return ""
    parts = text.replace(",", " ").split()
    temperature = next((name for key, name in WEATHER_TEMPERATURES.items() if key in parts), "")
    if "rain" in text:
        condition = "rain"
    elif "snow" in text:
        condition = "snow"
    else:
        condition = ""
    if condition:
        return " in the {} {}".format(temperature, condition) if temperature \
            else " in the " + condition
    if temperature == "freezing":
        return " in the freezing cold"
    if temperature in ("hot", "scorching"):
        return " in the heat"
    if temperature == "warm":
        return " in the sun"
    return ""


def stems_for(name):
    """The action words belonging to a goal gap ('painting' -> paint/draw/easel/sketch/mural)."""
    for _keywords, hint, stems in GOAL_HINTS:
        if hint == name:
            return stems
    return ()


def missing_for_goal(goal, actions, objects=()):
    """Things the goal is about that this lot cannot do at all. Both the viable actions and
    the objects on the lot count: an easel whose paint interaction needs inspired mood is not
    a missing easel, and asking the player for one would be wrong."""
    text = str(goal or "").lower()
    haystack = " ".join(str(item).lower() for item in list(actions or ()) + list(objects or ()))
    missing = []
    for keywords, name, stems in GOAL_HINTS:
        if not any(keyword in text for keyword in keywords):
            continue
        if not any(stem in haystack for stem in stems) and name not in missing:
            missing.append(name)
    return missing


# Goals that map onto the curated activities in npc_main.ACTIVITY_AFFORDANCES - the same
# names `houserules.npc.try <activity>` pushes, which are known to start in game.
GOAL_ACTIVITIES = {
    "paint": ("paint", "draw", "easel", "sketch", "artist", "painter"),
    "read": ("read", "book", "novel", "write", "novelist", "writer"),
    "chess": ("chess",),
    "jog": ("jog", "jogger"),
    "workout": ("workout", "exercise", "fit", "athlet", "muscl"),
}


def activity_for_goal(goal):
    """The curated activity a goal is about ('become a famous painter' -> 'paint'), or None."""
    text = str(goal or "").lower()
    for activity, words in GOAL_ACTIVITIES.items():
        if any(word in text for word in words):
            return activity
    return None


def actions_for_goal(goal, actions, limit=8):
    """Actions that could work towards the goal (painting -> paint/draw/easel/...)."""
    text = str(goal or "").lower()
    stems = set()
    for keywords, _name, hint_stems in GOAL_HINTS:
        if any(keyword in text for keyword in keywords):
            stems.update(hint_stems)
    if not stems:
        return []
    matches = []
    for action in actions or ():
        label = str(action).lower()
        if label in matches:
            continue
        if any(stem in label for stem in stems):
            matches.append(action)
            if len(matches) >= limit:
                break
    return matches


def describe_missing(missing):
    """'painting' -> 'painting (e.g. an easel, a sketchpad, an activity table)'. The examples
    are suggestions for the model and the player, not a shopping list."""
    described = []
    for name in missing or ():
        examples = GOAL_EXAMPLES.get(name)
        if examples:
            described.append("{} (e.g. {})".format(name, ", ".join(examples)))
        else:
            described.append("{} (anything that would allow it)".format(name))
    return described


def actions_for_wants(wants, actions, limit=4):
    """Actions whose label matches a word of a current want ("plant something" -> things with
    'plant'). Used so a blocked goal does not stop the sim doing what they actually want."""
    words = {word for want in wants or ()
             for word in re.findall(r"[a-z]+", str(want).lower()) if len(word) > 3}
    if not words:
        return []
    matches = []
    for action in actions or ():
        label = str(action).lower()
        if label in matches:
            continue
        if any(word in label for word in words):
            matches.append(action)
        if len(matches) >= limit:
            break
    return matches


# What to do about a pressing need, by the word in its name. These are words that say what
# the *action* does. Object words are left out on purpose: "sink" made "sink start crafting"
# (an Eco Lifestyle crafting process, not washing) count as hygiene and pushed the real
# washing actions off the list, which is how a sim spent three days at Hygiene 0.
NEED_ACTIONS = (
    ("hunger", ("eat", "cook", "meal", "snack", "food", "grill", "bake", "grab", "serve")),
    ("thirst", ("drink", "juice", "coffee", "tea")),
    ("bladder", ("toilet", "pee", "potty")),
    ("energy", ("sleep", "nap", "bed", "rest")),
    ("hygiene", ("shower", "bath", "wash", "brush")),
    ("social", ("chat", "talk", "call", "hug", "kiss", "social")),
    ("fun", ("play", "watch", "read", "game", "tv", "dance", "music")),
    ("comfort", ("sit", "lie", "relax", "lounge")),
)

# The curated activity that serves each need when the lot's own interaction list has nothing
# that does (or only things that cannot start). The game layer pushes these the same way it
# pushes a routine activity: nearest object that matches, then that object's own interaction.
# "chat" targets another sim instead of an object.
NEED_ACTIVITIES = (
    ("hygienehands", "wash hands"),
    ("hygieneoral", "brush teeth"),
    ("hygiene", "shower"),
    ("bladder", "toilet"),
    ("hunger", "eat"),
    ("energy", "sleep"),
    ("social", "chat"),
)


def need_activity_for(entry):
    """'HygieneHands 0' -> 'wash hands'. The longest need name wins, so HygieneHands is not
    mistaken for Hygiene. None when the need has no curated activity."""
    name = str(entry or "").lower().split()
    name = name[0] if name else ""
    best, found = None, None
    for need, activity in NEED_ACTIVITIES:
        if name.startswith(need) and (best is None or len(need) > len(best)):
            best, found = need, activity
    return found


# Objects whose own name reads as a noun, not a thing to do: they fill the "you have access
# to" line with plumbing the model cannot use ("prototype", "puddle small", "fire ash").
JUNK_OBJECT_WORDS = frozenset({
    "prototype", "puddle", "attractor", "collectibles", "fairy", "jig", "ash", "spawners",
    "carry", "wing", "proxy", "marker", "trigger",
})


def is_noise_object(label):
    """True for objects worth leaving out of the prompt's list of what is on the lot."""
    words = str(label or "").lower().split()
    if not words:
        return True
    return any(word.startswith(bad) for word in words for bad in JUNK_OBJECT_WORDS)


CHORE_STEMS = ("clean", "tidy", "mop", "sweep", "vacuum")


def is_internal(debug=False, cheat=False, visible=True):
    """Interactions a normal sim never gets from a menu: debug/cheat tuning, or hidden ones.
    (`visible` is the game's own "shows in the pie menu" flag.)"""
    return bool(debug) or bool(cheat) or visible is False


# Crafting interactions are built from a crafting process; pushing the bare staging step
# ("counter make food basic", "placemat_ColorPicture_Staging") raises inside the game's
# interaction factory and writes a desync to lastException. Only these are skipped - an
# interaction that takes some other required argument is left in, because the game may fill
# it in when pushing.
STAGING_ARGUMENTS = frozenset({"crafting_process", "phase"})


def needs_arguments(affordance):
    """True for interactions that cannot be created without arguments we don't have.

    Check the whole class hierarchy, not just type(affordance).__init__: a tuned interaction
    often overrides __init__(self, *args, **kwargs) with nothing required while the keywords
    live on a base class (CraftingPhaseSuperInteractionMixin). Looking only at the leaf missed
    exactly the staging classes that fail with "missing 2 required keyword-only arguments:
    'crafting_process' and 'phase'" in the game."""
    name = getattr(affordance, "__name__", affordance)
    if "staging" in str(name).lower():
        return True
    for cls in getattr(affordance, "__mro__", (affordance,)):
        try:
            parameters = inspect.signature(cls.__init__).parameters
        except Exception:
            continue
        required = {name for name, parameter in parameters.items()
                    if name not in ("self", "cls")
                    and parameter.kind == parameter.KEYWORD_ONLY
                    and parameter.default is parameter.empty}
        if required & STAGING_ARGUMENTS:
            return True
    return False


def needs_a_situation(test_names):
    """True when an interaction's tests wait for a running situation (the maid's cleaning
    situation, a restaurant, a venue event). Those can never be started from here, even if
    every other requirement is met."""
    return any("situation" in str(name).lower() for name in test_names or ())


def is_chore(label):
    """Cleaning/tidying: fine after cooking or when something is dirty, but the last thing to
    offer. The game's own autonomy also does it, so it must not outrank a goal or a want."""
    return any(word.startswith(stem) for word in str(label or "").lower().split()
               for stem in CHORE_STEMS)


# At or above this a need is fine: an action that only serves it is a waste of a choice.
SATISFIED_NEED = 80


def serves_satisfied(label, satisfied):
    """True when the label's action only serves needs from `satisfied` (already full)."""
    action = primary_action(label)
    if action is None:
        return False
    return any(need in satisfied and action in stems for need, stems in NEED_ACTIONS)


# Treats: fine as an option, but not what a hungry sim should live on.
TREAT_WORDS = ("cake", "dessert", "cookie", "pie", "sweet", "pastry", "muffin", "donut")


def is_treat(label):
    return any(word.startswith(treat) for word in str(label or "").lower().split()
               for treat in TREAT_WORDS)


def without_treats(actions):
    """The non-treat options, unless they are the only ones there are."""
    plain = [action for action in actions or () if not is_treat(action)]
    return plain or list(actions or ())


def lowest_need_actions(pressing, actions):
    """Actions for the single lowest pressing need, falling back to the next one if nothing
    on the lot addresses it. `pressing` is ordered lowest-first (see _describe).

    Returns (need entry, actions) or (None, [])."""
    for entry in pressing or ():
        matches = actions_for_needs([entry], actions)
        if matches:
            if str(entry).lower().startswith("hunger"):
                matches = without_treats(matches)
            return entry, matches
    return None, []


def without_satisfied(actions, satisfied):
    """The actions minus those that only serve needs that are already fine (>= 80%)."""
    if not satisfied:
        return list(actions or ())
    return [action for action in actions or () if not serves_satisfied(action, satisfied)]


def actions_for_needs(pressing, actions, limit=8):
    """Actions that address pressing needs, lowest need first. `pressing` is the prompt's
    ["Hunger 12", ...] list; anything that matches no need is left out."""
    chosen = []
    for entry in pressing or ():
        words = str(entry).lower().split()
        name = words[0] if words else ""
        # startswith: "HygieneHands" is the washing-hands need, "Hunger" plain hunger.
        stems = next((stems for need, stems in NEED_ACTIONS if name.startswith(need)), ())
        for action in actions or ():
            label = str(action).lower()
            if action in chosen:
                continue
            if any(stem in label for stem in stems):
                chosen.append(action)
                if len(chosen) >= limit:
                    return chosen
    return chosen


def examples_for(missing):
    """Concrete things that would fix each gap, flattened and de-duplicated, for the
    notification ("Do you have a planter box she could use?")."""
    examples = []
    for name in missing or ():
        for example in GOAL_EXAMPLES.get(name, ()):
            if example not in examples:
                examples.append(example)
    return examples


def category_for(label):
    """Which prompt group a thing label belongs to."""
    words = str(label or "").lower().split()
    for name, keywords in CATEGORIES:
        if any(word.startswith(keyword) for word in words for keyword in keywords):
            return name
    return OTHER_CATEGORY


def category_rank(label):
    """Sort key: the order the groups appear in the prompt, with 'Other' last."""
    return CATEGORY_ORDER.get(category_for(label), len(CATEGORIES))


# --- when the model is not there -------------------------------------------------------

def pick_random(choices, rng=None):
    """One of `choices` at random, for when the local model is not running or did not
    answer. The sim still only does something the lot offers (the list is the same one the
    prompt would have had), just chosen without a model. None when there is nothing."""
    usable = [choice for choice in choices or () if choice is not None]
    if not usable:
        return None
    return (rng or random).choice(usable)


# --- what a sim is feeling -------------------------------------------------------------

def buff_names(buffs, limit=8):
    """Plain words for the buffs a sim is feeling ("burning up", "dirty surroundings").

    `sim_info.Buffs` yields base `Buff` instances, so type(buff).__name__ is always "Buff"
    (2026-10-27: every prompt said "Currently feeling: buff", which hid an overheating sim
    from the model). The tuning that names the buff is on `buff.buff_type` - the same field
    EA's own scripts read (ea_scripts/simulation/autonomy/autonomy_component.py).
    """
    names = []
    for buff in buffs or ():
        tuning = getattr(buff, "buff_type", None) or buff
        name = getattr(tuning, "__name__", None) or type(buff).__name__
        label = clean_label(name)
        if len(label) < 4 or "hidden" in label or label in names:
            continue
        names.append(label)
    return names[:limit]


# --- everyday jobs ---------------------------------------------------------------------

# Jobs that are one interaction on one object, and that a sim only does when something is
# there to do them with ("pay bills" needs the mailbox). The object words are matched against
# the cleaned object names on the lot, so the prompt offers them only where they can work.
EVERYDAY_NEEDS = (
    ("put food in fridge", ("fridge",)),
    ("pay bills", ("mailbox",)),
    ("chat on the computer", ("computer",)),
)


def everyday_actions(objects):
    """The everyday jobs this lot has an object for, in a stable order."""
    words = set()
    for label in objects or ():
        words.update(str(label).lower().split())
    return [label for label, hints in EVERYDAY_NEEDS if any(hint in words for hint in hints)]


# --- the phone -------------------------------------------------------------------------

# In The Sims 4 the phone is not an object on the lot: its interactions live on the sim
# (sim.potential_phone_interactions). Most of the interesting ones ask "who?" through a
# picker, which opens a menu and pauses the game - useless for autonomy - so only direct
# call/chat/text interactions are pushed.
PHONE_WORDS = ("call", "chat", "talk", "text", "gossip")
PHONE_SKIP_WORDS = ("picker", "debug", "cheat", "hidden", "staging", "select")


def is_phone_chat(name):
    """True for a phone interaction this mod can start without asking the player who."""
    lower = str(name or "").lower()
    if not lower or any(bad in lower for bad in PHONE_SKIP_WORDS):
        return False
    return any(word in lower for word in PHONE_WORDS)
