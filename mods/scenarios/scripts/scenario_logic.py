"""Scenarios - pure logic (no game imports): reading and checking scenario files, which goals
are open, whether a goal is met, and winning or losing. scenario_main.py reads the game into
a plain "facts" dict (see FACTS below) every sim hour and hands it to evaluate().

A scenario file (Mods/HouseRules/scenarios/<name>.json), phase 1:
  name, description
  start:    money (number = set to; {"add": n}), traits / remove_traits / skills
            ({"active"|"all": ...}), remove_careers (true)
  goals:    [{id, type, ..., who, requires, reward, description}]
  deadline_days, win ("all_goals" or a list of goal ids), outcomes {win, lose}
  rules:    [{id, type, amount, penalty}] - checked every sim hour and when the game
            layer reports an event (see RULE_TYPES). Each rule breaks once per scenario.

FACTS (built by the game layer, plain data):
  day                 days since the scenario started (float)
  money, home_value   household funds / home lot value
  household_size, children
  active              sim id the scenario started with
  has_cheated         the household's own "has cheated" flag
  build_buy_spend     most spent in one Build/Buy visit since the scenario started
  travelled           the household has changed zone since the scenario started
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
RULE_TYPES = ("no_career", "no_cheats", "max_purchase", "max_money", "no_leaving_lot")
PENALTY_TYPES = ("warning", "money", "moodlet", "fail")
PENALTY_KEYS = ("type", "amount", "buff")
# Rules that need an amount in the file.
_RULE_AMOUNTS = ("max_purchase", "max_money")


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

    name = data.get("name")
    if name in (None, ""):
        errors.append("missing \"name\"")
    elif not isinstance(name, str):
        errors.append("\"name\" must be text")
    description = data.get("description")
    if description is not None and not isinstance(description, str):
        errors.append("\"description\" must be text")

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
    if "remove_careers" in start and not isinstance(start["remove_careers"], bool):
        errors.append("start.remove_careers must be true or false")
    for key in ("traits", "remove_traits"):
        _check_who_map(start.get(key), "start." + key, errors, "list")
    _check_who_map(start.get("skills"), "start.skills", errors, "map")

    goals = data.get("goals")
    if not isinstance(goals, list) or not goals:
        errors.append("\"goals\" must be a list with at least one goal")
        goals = []
    ids = set()
    for i, goal in enumerate(goals):
        if not isinstance(goal, dict):
            errors.append("goal {}: must be an object".format(i + 1))
            continue
        gid = goal.get("id")
        where = "goal {}".format(gid if isinstance(gid, str) and gid else i + 1)
        if gid in (None, ""):
            errors.append("{}: missing \"id\"".format(where))
        elif not isinstance(gid, str):
            errors.append("{}: \"id\" must be text".format(where))
        elif gid in ids:
            errors.append("{}: id used twice".format(where))
        else:
            ids.add(gid)
        _check_goal(goal, where, errors)
    for goal in goals:
        if not isinstance(goal, dict):
            continue
        for req in _requires(goal):
            if req not in ids:
                errors.append("goal {}: requires unknown goal \"{}\"".format(goal.get("id"), req))
    cycle = _requires_cycle(goals)
    if cycle:
        errors.append("goals require each other in a loop ({0}), so none of them can ever "
                      "open".format(" -> ".join(cycle)))

    win = data.get("win", "all_goals")
    if win != "all_goals":
        if not isinstance(win, list) or not win:
            errors.append("\"win\" must be \"all_goals\" or a non-empty list of goal ids")
        else:
            for gid in win:
                if not isinstance(gid, str):
                    errors.append("\"win\" entries must be goal ids")
                elif gid not in ids:
                    errors.append("\"win\": unknown goal \"{}\"".format(gid))
    deadline = data.get("deadline_days")
    if deadline is not None and (not _is_number(deadline) or deadline <= 0):
        errors.append("\"deadline_days\" must be a positive number")
    outcomes = data.get("outcomes")
    if outcomes is not None and not isinstance(outcomes, dict):
        errors.append("\"outcomes\" must be an object")
        outcomes = {}
    for outcome_name, outcome in (outcomes or {}).items():
        if outcome_name not in ("win", "lose"):
            errors.append("outcomes: unknown \"{}\" (win or lose)".format(outcome_name))
        else:
            _check_reward(outcome, "outcomes." + outcome_name, errors)
    _check_menu(data.get("menu"), errors)
    _check_rules(data.get("rules"), errors)

    if errors:
        raise ScenarioError("; ".join(errors))
    return data, warnings


def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _check_who_map(value, where, errors, kind):
    if value is None:
        return
    if not isinstance(value, dict) or any(k not in ("active", "all") for k in value):
        errors.append("{} must be {{\"active\": ..., \"all\": ...}}".format(where))
        return
    for who, entries in value.items():
        if kind == "list":
            if not isinstance(entries, list):
                errors.append("{}.{} must be a list of names".format(where, who))
                continue
            for entry in entries:
                if not isinstance(entry, str) or not entry.strip():
                    errors.append("{}.{}: entries must be names".format(where, who))
                    break
        else:
            if not isinstance(entries, dict):
                errors.append("{}.{} must be an object of name: level".format(where, who))
                continue
            for skill, level in entries.items():
                if not isinstance(skill, str) or not skill.strip() or not _is_number(level) or level < 0:
                    errors.append("{}.{}: expects \"skill\": level".format(where, who))
                    break


def _check_reward(reward, where, errors):
    if reward is None:
        return
    if not isinstance(reward, dict):
        errors.append("{}: must be an object".format(where))
        return
    for key in reward:
        if key not in REWARD_KEYS:
            errors.append("{}: unknown \"{}\" (known: {})".format(where, key, ", ".join(REWARD_KEYS)))
    if "money" in reward and not _is_number(reward["money"]):
        errors.append("{}: \"money\" must be a number".format(where))
    for key in ("trait", "notification"):
        if key in reward and not isinstance(reward[key], str):
            errors.append("{}: \"{}\" must be text".format(where, key))


def _check_penalty(penalty, where, errors):
    if not isinstance(penalty, dict):
        errors.append("{}: must be an object".format(where))
        return
    kind = penalty.get("type")
    if kind in (None, ""):
        errors.append("{}: missing \"type\" (known: {})".format(where, ", ".join(PENALTY_TYPES)))
        return
    if kind not in PENALTY_TYPES:
        errors.append("{}: unknown type \"{}\" (known: {})".format(where, kind, ", ".join(PENALTY_TYPES)))
        return
    for key in penalty:
        if key not in PENALTY_KEYS:
            errors.append("{}: unknown \"{}\" (known: {})".format(where, key, ", ".join(PENALTY_KEYS)))
    if kind == "money":
        # A fine is a negative money change, so the sign is the caller's business.
        if not _is_number(penalty.get("amount")):
            errors.append("{}: a money penalty needs an \"amount\"".format(where))
    if kind == "moodlet":
        buff = penalty.get("buff")
        if not isinstance(buff, str) or not buff.strip():
            errors.append("{}: a moodlet penalty needs a \"buff\" name".format(where))


def _check_rules(rules, errors):
    if rules is None:
        return
    if not isinstance(rules, list):
        errors.append("\"rules\" must be a list")
        return
    seen = set()
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append("rule {}: must be an object".format(i + 1))
            continue
        rid = rule.get("id")
        where = "rule {}".format(rid if isinstance(rid, str) and rid else i + 1)
        if rid is not None and (not isinstance(rid, str) or not rid.strip()):
            errors.append("{}: \"id\" must be text".format(where))
            rid = None
        rtype = rule.get("type")
        if rtype in (None, ""):
            errors.append("{}: missing \"type\" (known: {})".format(where, ", ".join(RULE_TYPES)))
            continue
        if rtype not in RULE_TYPES:
            errors.append("{}: unknown type \"{}\" (known: {})".format(where, rtype, ", ".join(RULE_TYPES)))
            continue
        rid = rid or rtype
        if rid in seen:
            errors.append("{}: id used twice".format(where))
        seen.add(rid)
        if rtype in _RULE_AMOUNTS:
            amount = rule.get("amount")
            if not _is_number(amount) or amount <= 0:
                errors.append("{}: a {} rule needs a positive \"amount\"".format(where, rtype))
        _check_penalty(rule.get("penalty") or {"type": "warning"}, where + " penalty", errors)


def _number_field(goal, key, where, errors, minimum=None):
    value = goal.get(key)
    if value in (None, ""):
        errors.append("{}: a {} goal needs \"{}\"".format(where, goal.get("type"), key))
    elif not _is_number(value):
        errors.append("{}: \"{}\" must be a number".format(where, key))
    elif minimum is not None and value < minimum:
        errors.append("{}: \"{}\" must be at least {}".format(where, key, minimum))


def _text_field(goal, key, where, errors):
    value = goal.get(key)
    if value in (None, ""):
        errors.append("{}: a {} goal needs \"{}\"".format(where, goal.get("type"), key))
    elif not isinstance(value, str):
        errors.append("{}: \"{}\" must be text".format(where, key))


def _check_goal(goal, where, errors):
    gtype = goal.get("type")
    if gtype in (None, ""):
        errors.append("{}: missing \"type\" (known: {})".format(where, ", ".join(GOAL_TYPES)))
        return
    if gtype not in GOAL_TYPES:
        errors.append("{}: unknown type \"{}\" (known: {})".format(where, gtype, ", ".join(GOAL_TYPES)))
        return
    if goal.get("who", "any") not in WHO:
        errors.append("{}: \"who\" must be one of {}".format(where, ", ".join(WHO)))
    if "description" in goal and not isinstance(goal["description"], str):
        errors.append("{}: \"description\" must be text".format(where))
    if "children" in goal and not isinstance(goal["children"], bool):
        errors.append("{}: \"children\" must be true or false".format(where))

    if gtype == "skill":
        _text_field(goal, "skill", where, errors)
        _number_field(goal, "level", where, errors, minimum=0)
    elif gtype in ("household_money", "home_value"):
        _number_field(goal, "amount", where, errors, minimum=0)
    elif gtype == "career_level":
        _number_field(goal, "level", where, errors, minimum=1)
        if goal.get("career") not in (None, "") and not isinstance(goal.get("career"), str):
            errors.append("{}: \"career\" must be text".format(where))
    elif gtype == "relationship":
        level = goal.get("level")
        if level in (None, ""):
            errors.append("{}: a relationship goal needs \"level\"".format(where))
        elif not isinstance(level, str) or level not in RELATIONSHIP_LEVELS:
            errors.append("{}: relationship level must be one of {}".format(
                where, ", ".join(RELATIONSHIP_LEVELS)))
    elif gtype == "aspiration":
        _text_field(goal, "aspiration", where, errors)
    elif gtype == "household_size":
        _number_field(goal, "amount", where, errors, minimum=1)
    elif gtype == "day":
        _number_field(goal, "day", where, errors, minimum=1)

    _check_requires(goal, where, errors)
    _check_reward(goal.get("reward"), where + " reward", errors)


def _requires(goal):
    reqs = goal.get("requires")
    return reqs if isinstance(reqs, list) else []


def _check_requires(goal, where, errors):
    reqs = goal.get("requires")
    if reqs is None:
        return
    if not isinstance(reqs, list):
        errors.append("{}: \"requires\" must be a list of goal ids".format(where))
        return
    for req in reqs:
        if not isinstance(req, str) or not req.strip():
            errors.append("{}: \"requires\" entries must be goal ids".format(where))
            return


def _requires_cycle(goals):
    """The goal ids of a requirement loop (a -> b -> a), or None. Such goals never open."""
    graph = {}
    for goal in goals:
        if isinstance(goal, dict) and isinstance(goal.get("id"), str):
            graph[goal["id"]] = [req for req in _requires(goal) if isinstance(req, str)]
    state, stack = {}, []

    def visit(node):
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, ()):
            if nxt not in graph:
                continue
            if state.get(nxt, 0) == 1:
                return stack[stack.index(nxt):] + [nxt]
            if state.get(nxt, 0) == 0:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for node in graph:
        if state.get(node, 0) == 0:
            found = visit(node)
            if found:
                return found
    return None


def _check_menu(menu, errors):
    if menu is None:
        return
    if not isinstance(menu, dict):
        errors.append("\"menu\" must be an object")
        return
    for key in ("category", "difficulty", "tagline", "icon", "template", "entry_method"):
        if key in menu and not isinstance(menu[key], str):
            errors.append("menu.{} must be text".format(key))
    if "sort_order" in menu and not _is_number(menu["sort_order"]):
        errors.append("menu.sort_order must be a number")
    entry_method = menu.get("entry_method")
    if isinstance(entry_method, str) and entry_method.upper() not in (
            "NEW_HOUSEHOLD", "EXISTING_HOUSEHOLD"):
        errors.append("menu.entry_method must be NEW_HOUSEHOLD or EXISTING_HOUSEHOLD")


# --- Progress --------------------------------------------------------------------------

def new_progress(scenario, file_name, start_day, active_sim_id):
    return {"scenario": file_name, "name": scenario["name"], "start_day": start_day,
            "active": active_sim_id, "done": [], "broken": [], "state": "running"}


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


# --- Rules -----------------------------------------------------------------------------

def rule_id(rule):
    """A rule's name in progress: its "id", or the type (so `max_money` is unique)."""
    return rule.get("id") or rule.get("type")


def rule_by_id(scenario, rid):
    for rule in scenario.get("rules") or ():
        if rule_id(rule) == rid:
            return rule
    return None


def penalty_of(rule):
    return rule.get("penalty") or {"type": "warning"}


def rule_met(rule, facts):
    """Whether this rule has been broken, judged on the facts alone."""
    rtype = rule.get("type")
    if rtype == "no_career":
        return any(s.get("careers") for s in facts.get("sims", {}).values())
    if rtype == "no_cheats":
        return bool(facts.get("has_cheated"))
    if rtype == "max_money":
        return facts.get("money", 0) > rule["amount"]
    if rtype == "max_purchase":
        return facts.get("build_buy_spend", 0) > rule["amount"]
    if rtype == "no_leaving_lot":
        return bool(facts.get("travelled"))
    return False


def broken_rules(scenario, progress, facts):
    """Ids of rules broken now that hadn't been broken yet (each breaks once)."""
    already = set(progress.get("broken") or ())
    return [rule_id(rule) for rule in scenario.get("rules") or ()
            if rule_id(rule) not in already and rule_met(rule, facts)]


def describe_rule(rule):
    rtype = rule.get("type")
    return {
        "no_career": "no job",
        "no_cheats": "no money or skill cheats",
        "max_purchase": "spend at most §{} in one Build/Buy visit".format(rule.get("amount")),
        "max_money": "hold at most §{}".format(rule.get("amount")),
        "no_leaving_lot": "stay on the home lot",
    }.get(rtype, rtype)


def penalty_text(rule):
    penalty = penalty_of(rule)
    kind = penalty["type"]
    if kind == "money":
        return "fine of §{}".format(abs(int(penalty["amount"])))
    if kind == "moodlet":
        return "moodlet {}".format(penalty["buff"])
    if kind == "fail":
        return "the scenario is lost"
    return "a warning"


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
