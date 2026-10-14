"""Scenarios - pure logic (no game imports): reading and checking scenario files, which goals
are open, whether a goal is met, and winning or losing. scenario_main.py reads the game into
a plain "facts" dict (see FACTS below) every sim hour and hands it to evaluate().

A scenario file (Mods/BlueRabbit477/scenarios/<name>.json), phase 1:
  name, description
  start:    money (number = set to; {"add": n}), traits / remove_traits / skills
            ({"active"|"all": ...}), remove_careers (true)
  goals:    [{id, type, ..., who, requires, reward, description}]
  deadline_days, win ("all_goals" or a list of goal ids), outcomes {win, lose}
  rules:    accepted but not enforced yet (phase 2)

FACTS (built by the game layer, plain data):
  day                 days since the scenario started (float)
  money, home_value   household funds / home lot value
  household_size, children
  active              sim id the scenario started with
  sims: {sim_id: {"skills": {name: level}, "careers": [[tuning name, level]],
                  "friendship": best friendship score, "romance": best romance score,
                  "married": bool, "aspirations": [finished aspiration track names]}}
"""
import json

GOAL_TYPES = ("skill", "household_money", "home_value", "career_level", "relationship",
              "aspiration", "household_size", "day", "custom")
WHO = ("active", "any", "all")
# Relationship levels, judged on the game's -100..100 friendship / romance scores. These are
# close to where the game hands out its own bits, not the bits themselves.
RELATIONSHIP_LEVELS = {
    "friend": ("friendship", 30),
    "good_friend": ("friendship", 60),
    "best_friend": ("friendship", 90),
    "partner": ("romance", 50),
    "married": ("married", 1),
}
REWARD_KEYS = ("money", "trait", "notification")
START_KEYS = ("money", "traits", "remove_traits", "skills", "remove_careers")


class ScenarioError(ValueError):
    pass


def parse(text):
    """JSON text -> (scenario, warnings). Raises ScenarioError with every problem found, so a
    broken file is refused as a whole rather than half-started."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ScenarioError("not valid JSON: {}".format(e))
    return validate(data)


def validate(data):
    errors, warnings = [], []
    if not isinstance(data, dict):
        raise ScenarioError("the file must be one JSON object {...}")
    if not data.get("name"):
        errors.append("missing \"name\"")

    start = data.get("start", {})
    if not isinstance(start, dict):
        errors.append("\"start\" must be an object")
        start = {}
    for key in start:
        if key not in START_KEYS:
            errors.append("start: unknown \"{}\" (known: {})".format(key, ", ".join(START_KEYS)))
    money = start.get("money")
    if money is not None and not _is_number(money) and not (isinstance(money, dict) and _is_number(money.get("add"))):
        errors.append("start.money must be a number or {\"add\": number}")
    for key in ("traits", "remove_traits", "skills"):
        _check_who_map(start.get(key), "start." + key, errors)

    goals = data.get("goals")
    if not isinstance(goals, list) or not goals:
        errors.append("\"goals\" must be a list with at least one goal")
        goals = []
    ids = set()
    for i, goal in enumerate(goals):
        where = "goal {}".format(goal.get("id") if isinstance(goal, dict) and goal.get("id") else i + 1)
        if not isinstance(goal, dict):
            errors.append("{}: must be an object".format(where))
            continue
        gid = goal.get("id")
        if not gid:
            errors.append("{}: missing \"id\"".format(where))
        elif gid in ids:
            errors.append("{}: id used twice".format(where))
        ids.add(gid)
        _check_goal(goal, where, errors)
    for goal in goals:
        if isinstance(goal, dict):
            for req in goal.get("requires", ()):
                if req not in ids:
                    errors.append("goal {}: requires unknown goal \"{}\"".format(goal.get("id"), req))

    win = data.get("win", "all_goals")
    if win != "all_goals" and not (isinstance(win, list) and all(w in ids for w in win)):
        errors.append("\"win\" must be \"all_goals\" or a list of goal ids")
    deadline = data.get("deadline_days")
    if deadline is not None and (not _is_number(deadline) or deadline <= 0):
        errors.append("\"deadline_days\" must be a positive number")
    for name, outcome in (data.get("outcomes") or {}).items():
        if name not in ("win", "lose"):
            errors.append("outcomes: unknown \"{}\" (win or lose)".format(name))
        else:
            _check_reward(outcome, "outcomes." + name, errors)
    if data.get("rules"):
        warnings.append("rules aren't checked yet (that's phase 2): they're shown, not enforced")

    if errors:
        raise ScenarioError("; ".join(errors))
    return data, warnings


def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _check_who_map(value, where, errors):
    if value is None:
        return
    if not isinstance(value, dict) or any(k not in ("active", "all") for k in value):
        errors.append("{} must be {{\"active\": ..., \"all\": ...}}".format(where))


def _check_reward(reward, where, errors):
    if reward is None:
        return
    if not isinstance(reward, dict):
        errors.append("{}: must be an object".format(where))
        return
    for key in reward:
        if key not in REWARD_KEYS:
            errors.append("{}: unknown \"{}\" (known: {})".format(where, key, ", ".join(REWARD_KEYS)))


def _check_goal(goal, where, errors):
    gtype = goal.get("type")
    if gtype not in GOAL_TYPES:
        errors.append("{}: unknown type \"{}\" (known: {})".format(where, gtype, ", ".join(GOAL_TYPES)))
        return
    if goal.get("who", "any") not in WHO:
        errors.append("{}: \"who\" must be one of {}".format(where, ", ".join(WHO)))
    need = {"skill": ("skill", "level"), "household_money": ("amount",), "home_value": ("amount",),
            "career_level": ("level",), "relationship": ("level",), "aspiration": ("aspiration",),
            "household_size": ("amount",), "day": ("day",)}.get(gtype, ())
    for key in need:
        if goal.get(key) in (None, ""):
            errors.append("{}: a {} goal needs \"{}\"".format(where, gtype, key))
    if gtype == "relationship" and goal.get("level") not in RELATIONSHIP_LEVELS:
        errors.append("{}: relationship level must be one of {}".format(where, ", ".join(RELATIONSHIP_LEVELS)))
    _check_reward(goal.get("reward"), where + " reward", errors)


# --- Progress --------------------------------------------------------------------------

def new_progress(scenario, file_name, start_day, active_sim_id):
    return {"scenario": file_name, "name": scenario["name"], "start_day": start_day,
            "active": active_sim_id, "done": [], "state": "running"}


def goal_by_id(scenario, gid):
    for goal in scenario["goals"]:
        if goal["id"] == gid:
            return goal
    return None


def is_unlocked(goal, done):
    return all(req in done for req in goal.get("requires", ()))


def open_goals(scenario, done):
    """Goals not done yet whose required goals are all done (the ones shown and checked)."""
    return [g for g in scenario["goals"] if g["id"] not in done and is_unlocked(g, done)]


def _sims_for(goal, facts):
    who = goal.get("who", "any")
    sims = facts.get("sims", {})
    if who == "active":
        sim = sims.get(facts.get("active"))
        return [sim] if sim is not None else []
    return list(sims.values())


def _combine(goal, values):
    if not values:
        return 0
    return min(values) if goal.get("who", "any") == "all" else max(values)


def goal_value(goal, facts):
    """(current, target) for a goal. Custom goals are never met here (ticked by hand)."""
    gtype = goal["type"]
    if gtype == "skill":
        skill = goal["skill"].lower()
        values = [max([lv for name, lv in s.get("skills", {}).items() if name.lower() == skill] or [0])
                  for s in _sims_for(goal, facts)]
        return _combine(goal, values), goal["level"]
    if gtype == "household_money":
        return facts.get("money", 0), goal["amount"]
    if gtype == "home_value":
        return facts.get("home_value", 0), goal["amount"]
    if gtype == "career_level":
        want = (goal.get("career") or "").lower().replace("_", "")
        values = [max([lv for name, lv in s.get("careers", ()) if want in name.lower().replace("_", "")] or [0])
                  for s in _sims_for(goal, facts)]
        return _combine(goal, values), goal["level"]
    if gtype == "relationship":
        kind, target = RELATIONSHIP_LEVELS[goal["level"]]
        values = [(1 if s.get("married") else 0) if kind == "married" else s.get(kind, 0)
                  for s in _sims_for(goal, facts)]
        return _combine(goal, values), target
    if gtype == "aspiration":
        want = goal["aspiration"].lower()
        values = [1 if any(want == a.lower() for a in s.get("aspirations", ())) else 0
                  for s in _sims_for(goal, facts)]
        return _combine(goal, values), 1
    if gtype == "household_size":
        return facts.get("children" if goal.get("children") else "household_size", 0), goal["amount"]
    if gtype == "day":
        return int(facts.get("day", 0)), goal["day"]
    return 0, 1   # custom


def goal_met(goal, facts):
    if goal["type"] == "custom":
        return False
    current, target = goal_value(goal, facts)
    return current >= target


def evaluate(scenario, progress, facts):
    """One check. Returns (newly done goal ids, outcome) where outcome is "won", "lost" or
    None. Goals unlocked by a goal done in this same check are checked straight away too.
    Doesn't change `progress`: the caller records what it applied."""
    if progress.get("state") != "running":
        return [], None
    done = list(progress.get("done", ()))
    newly = []
    changed = True
    while changed:
        changed = False
        for goal in open_goals(scenario, done):
            if goal_met(goal, facts):
                done.append(goal["id"])
                newly.append(goal["id"])
                changed = True
    return newly, outcome(scenario, done, facts.get("day", 0))


def outcome(scenario, done, day):
    win = scenario.get("win", "all_goals")
    needed = [g["id"] for g in scenario["goals"]] if win == "all_goals" else win
    if all(gid in done for gid in needed):
        return "won"
    deadline = scenario.get("deadline_days")
    if deadline is not None and day >= deadline:
        return "lost"
    return None


def describe_goal(goal, facts=None):
    """One line for the status / notifications, e.g. 'art: Painting 4/6 (any sim)'."""
    if goal.get("description"):
        text = goal["description"]
    else:
        gtype = goal["type"]
        text = {
            "skill": lambda: "{} level {}".format(goal["skill"], goal["level"]),
            "household_money": lambda: "§{} in the bank".format(goal["amount"]),
            "home_value": lambda: "a home worth §{}".format(goal["amount"]),
            "career_level": lambda: "{} level {}".format(goal.get("career") or "any career", goal["level"]),
            "relationship": lambda: goal["level"].replace("_", " "),
            "aspiration": lambda: "finish the aspiration {}".format(goal["aspiration"]),
            "household_size": lambda: "{} {}".format(goal["amount"], "children" if goal.get("children") else "household members"),
            "day": lambda: "reach day {}".format(goal["day"]),
            "custom": lambda: "(tick it yourself)",
        }[gtype]()
    who = goal.get("who", "any")
    if goal["type"] in ("skill", "career_level", "relationship", "aspiration") and who != "any":
        text += " ({} sim{})".format("the starting" if who == "active" else "every", "" if who == "active" else "s")
    if facts is not None and goal["type"] not in ("custom",):
        current, target = goal_value(goal, facts)
        if goal["type"] not in ("aspiration",) and not (goal["type"] == "relationship" and goal["level"] == "married"):
            text += " - {}/{}".format(int(current), target)
    return "{}: {}".format(goal["id"], text)
