"""NPC Routines phase 5 - JSON rule routines, pure logic (no game imports).

This is the main way to run a sim now: a JSON file lists rules, read top to bottom, and the
first one whose condition matches decides what the sim does. The optional local LLM is still
there (see npc_brain.py / npc_llm.py); it only decides for sims that have no rules loaded.

A rule file looks like this (Mods\\HouseRules\\data\\rules\\painter.json):

    {
      "name": "painter",
      "rules": [
        {"if": {"need": "toilet", "below": 30},
         "then": {"action": "use toilet", "minutes": 20}},
        {"if": {"skill": "painting", "above": 3},
         "then": {"action": "paint", "minutes": 90}},
        {"if": {"emotion": "uncomfortable"},
         "then": {"action": "nothing"}}
      ]
    }

Conditions (all keys in one condition must match, i.e. AND):
  need / skill + below / above   - a need (0-100) or skill level, compared strictly
  emotion, mood                  - the sim's current emotion, e.g. "uncomfortable"
  buff, want, activity, weather, season - a word or phrase that must appear
  day                            - "mon" (or 0-6, 0=Sunday) or a list of them
  hour, hour_from/hour_to        - the sim clock; hour_to may wrap past midnight
  any / all / not                - combine other conditions
A rule with no "if" always matches. An action that this lot does not offer is skipped, and
the next rule is tried. "nothing" leaves the sim to the game's own autonomy.

The assigned rules are saved in Mods\\HouseRules\\data\\npc_rules.json, so they survive a
restart; `houserules.npc.rules_load <file> [sim|all]` loads one from data\\rules.
"""
import json
import os
import re

from npc_actions import DEFAULT_WAIT_MINUTES, clamp_minutes
from npc_routine import DAY_NAMES

DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts",
                        "The Sims 4", "Mods", "HouseRules", "data")
STORE_PATH = os.path.join(DATA_DIR, "npc_rules.json")
RULES_DIR = os.path.join(DATA_DIR, "rules")

# What a rule can say instead of an action: the game's own autonomy decides for a while.
NOTHING_WORDS = frozenset({"nothing", "none", "do nothing", "do nothing special",
                           "do nothing special normal life", "leave it", "leave it to the game",
                           "normal life", "autonomy"})
DEFAULT_RULE_MINUTES = DEFAULT_WAIT_MINUTES

# The player writes "toilet_need", the game calls that need bladder. Same idea for a few
# other everyday names, so a rule can be written the way someone talks about the game.
NEED_ALIASES = {
    "toilet": "bladder",
    "bathroom": "bladder",
    "pee": "bladder",
    "tired": "energy",
    "sleep": "energy",
    "sleepy": "energy",
    "hungry": "hunger",
    "food": "hunger",
    "dirty": "hygiene",
    "bored": "fun",
    "entertainment": "fun",
    "lonely": "social",
}

TEXT_KEYS = frozenset({"emotion", "mood", "buff", "want", "activity", "weather", "season"})
RULE_KEYS = frozenset({"if", "then", "name", "comment", "enabled"})
THEN_KEYS = frozenset({"action", "minutes", "reason"})


def normalize_text(value):
    """'Toilet_Need' -> 'toilet need': lower case, no underscores/dashes, one space."""
    text = re.sub(r"[_\-]+", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().lower()


def normalize_key(value):
    """Like normalize_text, but for JSON keys: 'Hour_From' -> 'hour_from'."""
    return normalize_text(value).replace(" ", "_")


def _strip_suffix(text, suffix):
    return text[:-len(suffix)].strip() if text.endswith(suffix) else text


def need_key(value):
    """The need name the game uses ('toilet' -> 'bladder')."""
    key = normalize_text(value)
    key = _strip_suffix(key, " need")
    return NEED_ALIASES.get(key, key)


def _skill_key(value):
    key = normalize_text(value)
    key = _strip_suffix(key, " skill")
    if key.startswith("skill "):
        key = key[len("skill "):]
    return key


def _lookup(mapping, key):
    """Case/underscore-insensitive lookup in a state dict (needs, skills)."""
    for name, value in (mapping or {}).items():
        if normalize_text(name) == key:
            return value
    return None


def _as_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _words(text):
    return normalize_text(text).split()


def _word_matches(rule_word, label_word):
    """'paint' matches 'painting', 'toilet' matches 'toilets' - but short words only exact."""
    if rule_word == label_word:
        return True
    if len(rule_word) >= 3 and label_word.startswith(rule_word):
        return True
    if len(label_word) >= 3 and rule_word.startswith(label_word):
        return True
    return False


def _words_contain(haystack_words, needle_words):
    return all(any(_word_matches(needle, word) for word in haystack_words)
               for needle in needle_words)


def is_nothing(action):
    words = re.sub(r"[^a-z0-9 ]+", " ", normalize_text(action))
    return re.sub(r"\s+", " ", words).strip() in NOTHING_WORDS


def match_action(action, available):
    """The entry in `available` that means `action`, or None.

    Exact labels win first. Otherwise every word of the rule's action has to appear in the
    label ('use toilet' -> 'toilet use'), and failing that the label may be a shorter way of
    saying the same thing ('use toilet' -> the curated activity 'toilet')."""
    wanted = normalize_text(action)
    if not wanted:
        return None
    for label in available or ():
        if normalize_text(label) == wanted:
            return label
    wanted_words = _words(wanted)
    candidates = []
    for order, label in enumerate(available or ()):
        label_words = _words(label)
        if not label_words:
            continue
        if _words_contain(label_words, wanted_words):
            candidates.append((0, len(label_words), order, label))
        elif _words_contain(wanted_words, label_words):
            candidates.append((1, len(label_words), order, label))
    if not candidates:
        return None
    return min(candidates)[3]


# --- conditions ---------------------------------------------------------------------------

def _day_index(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return value if 0 <= value <= 6 else None
    text = normalize_text(value)
    if text.isdigit():
        number = int(text)
        return number if 0 <= number <= 6 else None
    name = text[:3]
    return DAY_NAMES.index(name) if name in DAY_NAMES else None


def _state_day(state):
    day = _day_index(state.get("day")) if state.get("day") is not None else None
    if day is not None:
        return day
    match = re.match(r"\s*([a-z]{3})", str(state.get("time") or ""))
    return _day_index(match.group(1)) if match else None


def _state_hour(state):
    hour = state.get("hour")
    if isinstance(hour, int) and not isinstance(hour, bool):
        return hour
    match = re.search(r"(\d{1,2}):\d{2}", str(state.get("time") or ""))
    return int(match.group(1)) if match else None


def _text_contains(state_text, wanted):
    return normalize_text(wanted) in normalize_text(state_text)


def condition_matches(condition, state):
    """True when every part of one rule's `if` holds for this sim."""
    condition = condition or {}
    # Hour ranges are one condition, not two independent ones.
    if "hour_from" in condition or "hour_to" in condition:
        hour = _state_hour(state)
        if hour is None:
            return False
        start = int(condition.get("hour_from", 0))
        end = int(condition.get("hour_to", 24))
        if start <= end:
            if not start <= hour < end:
                return False
        elif not (hour >= start or hour < end):     # e.g. 22 -> 6
            return False
    for key, value in condition.items():
        key = normalize_text(key)
        if key in ("below", "above", "hour from", "hour to"):
            continue
        if key == "any":
            if not any(condition_matches(part, state) for part in value):
                return False
        elif key == "all":
            if not all(condition_matches(part, state) for part in value):
                return False
        elif key == "not":
            if condition_matches(value, state):
                return False
        elif key == "need":
            have = _lookup(state.get("needs"), need_key(value))
            have = _as_number(have)
            if have is None:
                return False
            if "below" in condition and not have < float(condition["below"]):
                return False
            if "above" in condition and not have > float(condition["above"]):
                return False
        elif key == "skill":
            have = _lookup(state.get("skills"), _skill_key(value))
            have = _as_number(have)
            if have is None:
                return False
            if "below" in condition and not have < float(condition["below"]):
                return False
            if "above" in condition and not have > float(condition["above"]):
                return False
        elif key in ("emotion", "mood"):
            mood = normalize_text(state.get("mood"))
            wanted = _words(value)
            if not mood or not wanted or not _words_contain(mood.split(), wanted):
                return False
        elif key == "buff":
            if not any(_text_contains(buff, value) for buff in state.get("buffs") or ()):
                return False
        elif key == "want":
            if not any(_text_contains(want, value) for want in state.get("wants") or ()):
                return False
        elif key == "activity":
            if not any(_text_contains(activity, value)
                       for activity in state.get("activity") or ()):
                return False
        elif key in ("weather", "season"):
            if not _text_contains(state.get(key) or "", value):
                return False
        elif key == "day":
            wanted = value if isinstance(value, (list, tuple)) else [value]
            wanted_days = {_day_index(day) for day in wanted}
            if _state_day(state) not in wanted_days:
                return False
        elif key == "hour":
            wanted = value if isinstance(value, (list, tuple)) else [value]
            if _state_hour(state) not in {int(hour) for hour in wanted}:
                return False
        else:       # validation rejects unknown keys; be forgiving when reading anyway
            return False
    return True


# --- choices ------------------------------------------------------------------------------

class Choice:
    """One rule's answer: what to do (None = let the game decide), for how long, and why."""

    __slots__ = ("action", "minutes", "reason", "number", "rule_action", "rule")

    def __init__(self, action, minutes, reason, number, rule_action, rule):
        self.action = action          # a label/activity from what the lot offers, or None
        self.minutes = minutes
        self.reason = reason
        self.number = number          # 1-based rule number, for the log
        self.rule_action = rule_action
        self.rule = rule

    def __repr__(self):
        return "<rule {}: {} for {}>".format(self.number, self.action or "nothing", self.minutes)


def _minutes_for(then):
    return clamp_minutes(then.get("minutes", DEFAULT_RULE_MINUTES))


def evaluate(ruleset, state, available, notes=None):
    """The first usable rule, or None.

    `ruleset` is a normalised ruleset (see normalize_ruleset) or a plain list of rules.
    `available` is every label/activity the lot offers right now. A rule whose condition
    matches but whose action cannot be started here is skipped, so a later rule can still
    handle the situation; `notes` (a list) receives why.
    """
    rules = ruleset.get("rules", ()) if isinstance(ruleset, dict) else ruleset
    for number, rule in enumerate(rules or (), 1):
        if rule.get("enabled", True) is False:
            continue
        if not condition_matches(rule.get("if"), state):
            continue
        then = rule.get("then") or {}
        if isinstance(then, str):
            then = {"action": then}
        rule_action = then.get("action", "")
        if is_nothing(rule_action):
            return Choice(None, _minutes_for(then), then.get("reason", ""), number,
                          rule_action, rule)
        action = match_action(rule_action, available)
        if action is None:
            if notes is not None:
                notes.append("rule {} matches, but {!r} is not on this lot".format(
                    number, rule_action))
            continue
        return Choice(action, _minutes_for(then), then.get("reason", ""), number,
                      rule_action, rule)
    return None


# --- validation / loading -----------------------------------------------------------------

def _validate_condition(condition, where):
    if condition is None:
        return
    if not isinstance(condition, dict):
        raise ValueError("{}: must be an object".format(where))
    for key, value in condition.items():
        name = normalize_key(key)
        if name in ("below", "above"):
            continue
        if name in ("hour_from", "hour_to"):
            if not isinstance(value, int) or not 0 <= value <= 24:
                raise ValueError("{}.{}: must be an hour 0-24".format(where, key))
        elif name in ("need", "skill"):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("{}.{}: must be a name".format(where, key))
            if "below" not in condition and "above" not in condition:
                raise ValueError("{}.{}: needs 'below' or 'above'".format(where, key))
            for bound in ("below", "above"):
                if bound in condition and _as_number(condition[bound]) is None:
                    raise ValueError("{}.{}: must be a number".format(where, bound))
        elif name in TEXT_KEYS:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("{}.{}: must be a word or phrase".format(where, key))
        elif name == "day":
            days = value if isinstance(value, (list, tuple)) else [value]
            if not days or any(_day_index(day) is None for day in days):
                raise ValueError("{}.day: use day names (mon) or numbers 0-6".format(where))
        elif name == "hour":
            hours = value if isinstance(value, (list, tuple)) else [value]
            if not hours or any(not isinstance(h, int) or not 0 <= h <= 23 for h in hours):
                raise ValueError("{}.hour: use hours 0-23".format(where))
        elif name in ("any", "all"):
            if not isinstance(value, (list, tuple)) or not value:
                raise ValueError("{}.{}: must be a non-empty list".format(where, key))
            for index, part in enumerate(value, 1):
                _validate_condition(part, "{}.{}[{}]".format(where, key, index))
        elif name == "not":
            _validate_condition(value, where + ".not")
        else:
            raise ValueError("{}: unknown condition {!r}".format(where, key))


def _validate_then(then, where):
    if isinstance(then, str):
        then = {"action": then}
    if not isinstance(then, dict):
        raise ValueError("{}: must be an object like {{\"action\": \"paint\"}}".format(where))
    unknown = sorted(set(then) - THEN_KEYS)
    if unknown:
        raise ValueError("{}: unknown key(s) {}".format(where, ", ".join(unknown)))
    action = then.get("action")
    if not isinstance(action, str) or not action.strip():
        raise ValueError("{}: needs an 'action'".format(where))
    if "minutes" in then:
        minutes = _as_number(then["minutes"])
        if minutes is None or minutes <= 0:
            raise ValueError("{}.minutes: must be a positive number".format(where))
    if "reason" in then and not isinstance(then["reason"], str):
        raise ValueError("{}.reason: must be text".format(where))
    return then


def normalize_ruleset(data, source=""):
    """Validate a parsed JSON ruleset and return {'name', 'source', 'rules'}.

    Accepts a list of rules, or an object with a "rules" list. Raises ValueError with the
    rule number for anything the engine cannot run, so a typo is reported instead of
    silently doing nothing."""
    if isinstance(data, list):
        data = {"rules": data}
    if not isinstance(data, dict):
        raise ValueError("the file must contain an object with a 'rules' list")
    unknown = sorted(key for key in data
                     if key not in ("name", "description", "rules", "comment", "source")
                     and not key.startswith("_"))
    if unknown:
        raise ValueError("unknown key(s) at the top: {}".format(", ".join(unknown)))
    rules = data.get("rules")
    if not isinstance(rules, list):
        raise ValueError("the file needs a 'rules' list")
    clean = []
    for number, rule in enumerate(rules, 1):
        where = "rule {}".format(number)
        if not isinstance(rule, dict):
            raise ValueError("{}: must be an object".format(where))
        unknown = sorted(set(rule) - RULE_KEYS)
        if unknown:
            raise ValueError("{}: unknown key(s) {}".format(where, ", ".join(unknown)))
        _validate_condition(rule.get("if"), where + ".if")
        if "then" not in rule:
            raise ValueError("{}: needs a 'then'".format(where))
        clean.append({"if": rule.get("if") or {},
                      "then": _validate_then(rule["then"], where + ".then"),
                      "enabled": rule.get("enabled", True),
                      "name": rule.get("name", ""),
                      "comment": rule.get("comment", "")})
    return {"name": str(data.get("name") or ""),
            "description": str(data.get("description") or ""),
            "source": source,
            "rules": clean}


def load_ruleset(path, source=None):
    """Read and validate one rule file. Raises ValueError for anything unusable."""
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except ValueError as e:
            raise ValueError("{} is not valid JSON: {}".format(path, e))
    return normalize_ruleset(data, source=source or os.path.basename(path))


def resolve_rule_file(name, rules_dir=None):
    """Find a rule file: `painter` or `painter.json` in data\\rules, or a full path."""
    rules_dir = rules_dir or RULES_DIR
    text = str(name or "").strip().strip('"')
    if not text:
        raise ValueError("no rule file given")
    if os.path.isabs(text) or os.sep in text or (os.altsep and os.altsep in text):
        if not text.lower().endswith(".json") and os.path.exists(text + ".json"):
            text += ".json"
        if not os.path.exists(text):
            raise ValueError("no such file: {}".format(text))
        return text
    candidate = os.path.join(rules_dir, text if text.lower().endswith(".json")
                             else text + ".json")
    if not os.path.exists(candidate):
        available = list_rule_files(rules_dir)
        raise ValueError("no {}.json in {} (found: {})".format(
            text, rules_dir, ", ".join(available) or "nothing"))
    return candidate


def list_rule_files(rules_dir=None):
    """The rule files in data\\rules, by short name, so `rules_list` can show them."""
    folder = rules_dir or RULES_DIR
    try:
        names = sorted(os.path.splitext(name)[0] for name in os.listdir(folder)
                       if name.lower().endswith(".json"))
    except OSError:
        return []
    return names


# --- per-sim store ------------------------------------------------------------------------

class RulesStore:
    """One ruleset per sim id, saved as JSON so a loaded routine survives a restart."""

    def __init__(self):
        self._rules = {}

    def get(self, sim_id):
        return self._rules.get(str(sim_id))

    def has(self, sim_id):
        return str(sim_id) in self._rules

    def assign(self, sim_id, ruleset):
        self._rules[str(sim_id)] = ruleset

    def remove(self, sim_id):
        self._rules.pop(str(sim_id), None)

    def sim_ids(self):
        return [int(sim_id) if str(sim_id).isdigit() else sim_id
                for sim_id in self._rules]

    def to_json(self):
        return json.dumps({"sims": self._rules}, indent=1)

    @classmethod
    def from_json(cls, text):
        store = cls()
        try:
            data = json.loads(text)
        except ValueError:
            return store
        sims = data.get("sims", data) if isinstance(data, dict) else {}
        if not isinstance(sims, dict):
            return store
        for sim_id, ruleset in sims.items():
            try:
                normalized = normalize_ruleset(ruleset)
            except ValueError:
                continue        # one broken entry must not take the others down
            normalized["source"] = str(
                (ruleset.get("source") if isinstance(ruleset, dict) else "") or "")
            store.assign(sim_id, normalized)
        return store

    def load(self, path):
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if text:
            loaded = self.__class__.from_json(text)
            self._rules = loaded._rules

    def save(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        os.replace(tmp, path)
