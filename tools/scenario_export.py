"""Compile a scenario JSON file into tuning for the game's own Scenarios menu.

The script mod (mods/scenarios) reads the JSON directly and does the real work: starting
conditions, goals, rules and penalties. This exporter is the bridge to the menu: it writes a
`Scenario` snippet, one `ScenarioPhase`, one `ScenarioGoal` per mappable goal, `ScenarioOutcome`
snippets and the loot actions for starting money/traits/skills, then builds them into a
`.package` with tools/tuning.py.

Only what the game's situation-goal tuning can express is exported. Everything else (rules,
deadlines, custom goals) is reported in `warnings` and stays with the script mod. References
to EA tuning are written by *name* (`Skill_Painting`, `trait_Ambitious`), which the game
resolves with the same name hash it uses for instance ids.
"""
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import config
import tuning

SCENARIO_DIR = config.MODS_SRC_DIR / "scenarios" / "install" / "scenarios"
LOGIC_PATH = config.MODS_SRC_DIR / "scenarios" / "scripts" / "scenario_logic.py"

# Resource type ids from the game's sims4/resources.py.
TYPE_SNIPPET = "snippet"
TYPE_SITUATION_GOAL = "situation_goal"
TYPE_ACTION = "action"

_SAFE = re.compile(r"[^A-Za-z0-9_]")


class ExportError(ValueError):
    pass


class ExportResult:
    def __init__(self, files, warnings=None, unsupported=None):
        self.files = files
        self.warnings = list(warnings or ())
        self.unsupported = list(unsupported or ())


def load_logic():
    """Import the mod's pure logic module without putting it on sys.path permanently."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("scenario_logic", str(LOGIC_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_file(path):
    path = Path(path)
    logic = load_logic()
    data, _ = logic.parse(path.read_text(encoding="utf-8"))
    return data


def validate(data):
    return load_logic().validate(data)


def slugify(text):
    slug = _SAFE.sub("_", text or "").strip("_")
    slug = re.sub(r"_+", "_", slug)
    if not slug:
        raise ExportError("scenario has no usable name to build tuning names from")
    return slug


def tuning_id(name):
    """Instance id for our own tuning: the game hashes names with the high bit set."""
    return tuning.fnv64(name) | (1 << 63)


def loc(text):
    return "{{string:%s}}" % text


def _line(level, text):
    return "  " * level + text


def _t(level, name, value):
    return _line(level, "<T n=%s>%s</T>" % (quoteattr(name), value))


def _e(level, name, value):
    return _line(level, "<E n=%s>%s</E>" % (quoteattr(name), value))


def _instance(cls, rtype, module, name, body):
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             '<I c=%s i=%s m=%s n=%s s="%d">' % (
                 quoteattr(cls), quoteattr(rtype), quoteattr(module),
                 quoteattr(name), tuning_id(name))]
    lines.extend(body)
    lines.append("</I>")
    return "\n".join(lines) + "\n"


def _display(level, title, tooltip=None):
    lines = [_line(level, '<V n="_display_data" t="enabled">'),
             _line(level + 1, '<U n="enabled">'),
             _t(level + 2, "instance_display_name", loc(title))]
    if tooltip:
        lines.append(_t(level + 2, "instance_display_tooltip", loc(tooltip)))
    lines += [_line(level + 1, "</U>"), _line(level, "</V>")]
    return lines


def _threshold(level, name, value):
    return [_line(level, "<U n=%s>" % quoteattr(name)),
            _t(level + 1, "value", value),
            _e(level + 1, "comparison", "GREATER_OR_EQUAL"),
            _line(level, "</U>")]


def _skill_name(skill):
    skill = (skill or "").strip()
    if not skill:
        raise ExportError("a skill goal needs a skill name")
    if skill.startswith(("Skill_", "statistic_")):
        return skill
    return "Skill_" + skill.replace(" ", "")


def _goal_display_text(goal):
    kind = goal.get("type")
    if kind == "skill":
        return "Reach {0} level {1}".format(goal.get("skill"), goal.get("level"))
    if kind == "household_money":
        return "Have §{0:,} in the household".format(int(goal.get("amount", 0)))
    if kind == "home_value":
        return "Own a home worth §{0:,}".format(int(goal.get("amount", 0)))
    if kind == "household_size":
        return "Have {0} sims in the household".format(goal.get("amount"))
    if kind == "day":
        return "Reach day {0}".format(goal.get("day"))
    return goal.get("description") or str(goal.get("id"))


def _goal_body(goal, warnings, unsupported):
    kind = goal.get("type")
    if kind == "skill":
        if goal.get("who", "any") not in ("active", "any"):
            unsupported.append(
                'goal "{0}": menu tracking follows the active sim only (who = {1})'.format(
                    goal.get("id"), goal.get("who")))
        level = int(goal.get("level", 0))
        return [
            '<V n="_goal_test" t="skill_test">',
            '  <U n="skill_test">',
            '    <E n="subject">Actor</E>',
            '    <T n="skill">%s</T>' % escape(_skill_name(goal.get("skill"))),
            '    <V n="skill_range" t="threshold">',
            '      <U n="threshold">',
            '        <U n="skill_threshold">',
            '          <T n="value">%d</T>' % level,
            '          <E n="comparison">GREATER_OR_EQUAL</E>',
            '        </U>',
            '      </U>',
            '    </V>',
            '    <T n="use_effective_skill_level">False</T>',
            '  </U>',
            '</V>',
        ]
    if kind in ("household_money", "home_value"):
        amount = int(goal.get("amount", 0))
        context = "total_cash" if kind == "household_money" else "property_only"
        subject = [] if context == "total_cash" else [
            '    <T n="allow_inactive_lot_value">False</T>']
        return [
            '<V n="_goal_test" t="simoleons">',
            '  <U n="simoleons">',
            '    <V n="value_context" t="%s">' % context,
            '      <U n="%s">' % context,
            '        <E n="subject">Actor</E>',
        ] + subject + [
            '      </U>',
            '    </V>',
            '    <U n="value_threshold">',
            '      <T n="value">%d</T>' % amount,
            '      <E n="comparison">GREATER_OR_EQUAL</E>',
            '    </U>',
            '  </U>',
            '</V>',
        ]
    if kind == "household_size":
        if goal.get("children"):
            unsupported.append(
                'goal "{0}": children-only household size has no simple menu test'.format(
                    goal.get("id")))
            return None
        amount = int(goal.get("amount", 0))
        return [
            '<V n="_goal_test" t="household_size">',
            '  <U n="household_size">',
            '    <E n="participant">Actor</E>',
            '    <V n="test_type" t="actual_size">',
            '      <U n="actual_size">',
            '        <U n="count">',
            '          <T n="value">%d</T>' % amount,
            '          <E n="comparison">GREATER_OR_EQUAL</E>',
            '        </U>',
            '      </U>',
            '    </V>',
            '  </U>',
            '</V>',
        ]
    unsupported.append('goal "{0}": type "{1}" has no menu equivalent'.format(
        goal.get("id"), kind))
    return None


def _goal_instance(name, goal, warnings, unsupported):
    display_title = _goal_display_text(goal)
    if goal.get("type") == "day":
        body = [_t(1, "duration", int(float(goal.get("day", 1)) * 24))]
        body += _display(1, display_title)
        return _instance("SituationGoalTime", TYPE_SITUATION_GOAL,
                         "situations.situation_goal_time", name, body)

    goal_body = _goal_body(goal, warnings, unsupported)
    if goal_body is None:
        return None
    body = [_line(1, line) for line in goal_body]
    body += _display(1, display_title)
    return _instance("SituationGoalActor", TYPE_SITUATION_GOAL,
                     "situations.situation_goal_actor", name, body)


def _loot_op(level, op):
    """One entry of a LootActions `loot_actions` list."""
    kind = op[0]
    if kind == "money":
        return [_line(level, '<V t="money_loot">'),
                _line(level + 1, '<U n="money_loot">'),
                _line(level + 2, '<V n="amount" t="literal">'),
                _line(level + 3, '<U n="literal">'),
                _t(level + 4, "value", op[1]),
                _line(level + 3, "</U>"),
                _line(level + 2, "</V>"),
                _line(level + 1, "</U>"),
                _line(level, "</V>")]
    if kind in ("trait_add", "trait_remove"):
        return [_line(level, '<V t="%s">' % kind),
                _line(level + 1, '<U n="%s">' % kind),
                _t(level + 2, "trait", escape(op[1])),
                _line(level + 1, "</U>"),
                _line(level, "</V>")]
    if kind == "skill":
        return [_line(level, '<V t="statistics">'),
                _line(level + 1, '<V n="statistics" t="statistic_set">'),
                _line(level + 2, '<U n="statistic_set">'),
                _t(level + 3, "stat", escape(_skill_name(op[1]))),
                _t(level + 3, "value", int(op[2])),
                _line(level + 2, "</U>"),
                _line(level + 1, "</V>"),
                _line(level, "</V>")]
    raise ExportError("unknown loot operation: {}".format(kind))


def _loot_instance(name, ops):
    body = ['  <L n="loot_actions">']
    for op in ops:
        body += _loot_op(2, op)
    body.append("  </L>")
    return _instance("LootActions", TYPE_ACTION, "interactions.utils.loot", name, body)


def _scenario_loot_list(level, name, loot_name):
    return [_line(level, "<L n=%s>" % quoteattr(name)),
            _line(level + 1, "<U>"),
            _line(level + 2, '<U n="scenario_loot">'),
            _t(level + 3, "loot_action", escape(loot_name)),
            _line(level + 2, "</U>"),
            _line(level + 1, "</U>"),
            _line(level, "</L>")]


def _reward_ops(reward, warnings):
    ops = []
    if not reward:
        return ops
    if reward.get("money") is not None:
        ops.append(("money", int(reward["money"])))
    if reward.get("trait"):
        ops.append(("trait_add", reward["trait"]))
    if reward.get("notification"):
        warnings.append("reward notification is shown by the script mod, not the menu")
    return ops


def _start_ops(start, warnings, unsupported):
    ops = []
    money = start.get("money")
    if isinstance(money, dict):
        unsupported.append('start.money {"add": ...} cannot be applied by the menu exporter')
    elif money is not None:
        ops.append(("money", int(money)))
    for trait in _who_values(start.get("traits")):
        ops.append(("trait_add", trait))
    for trait in _who_values(start.get("remove_traits")):
        ops.append(("trait_remove", trait))
    for skill, level in _skill_values(start.get("skills")):
        ops.append(("skill", skill, level))
    if start.get("remove_careers"):
        unsupported.append("start.remove_careers has no menu loot equivalent")
    return ops


def _who_values(value):
    if not value:
        return []
    values = []
    for key in ("active", "all"):
        values.extend(value.get(key) or ())
    return values


def _skill_values(value):
    if not value:
        return []
    values = []
    for key in ("active", "all"):
        values.extend((value.get(key) or {}).items())
    return values


def _start_notification(title, text):
    body = ['  <V n="scenario_start_notification" t="literal">',
            '    <U n="literal">',
            '      <U n="value">',
            '        <V n="title" t="enabled">',
            _t(5, "enabled", loc(title)),
            '        </V>',
            '        <V n="text" t="single">',
            _t(5, "single", loc(text)),
            '        </V>',
            '      </U>',
            '    </U>',
            '  </V>']
    return body


def _menu_option(menu, key, warnings):
    value = (menu or {}).get(key)
    if value is None:
        return None
    value = str(value)
    if not re.match(r"^[A-Za-z0-9_]+$", value):
        warnings.append('menu.{0} is not an enum name: {1!r}'.format(key, value))
        return None
    return value


def render(scenario, slug=None):
    warnings, unsupported = [], []
    slug = slug or slugify(scenario.get("name"))
    base = "HouseRules_Scenario_" + slug
    menu = scenario.get("menu") or {}
    files = {}

    win_outcome = base + "_Win"
    lose_outcome = base + "_Lose"
    phase_name = base + "_Phase"

    win_text = (scenario.get("outcomes") or {}).get("win", {}) or {}
    lose_text = (scenario.get("outcomes") or {}).get("lose", {}) or {}
    win_ops = _reward_ops(win_text, warnings)
    lose_ops = _reward_ops(lose_text, warnings)

    loot_files = {}
    if win_ops:
        loot_files[win_outcome + "_Loot"] = _loot_instance(win_outcome + "_Loot", win_ops)
    if lose_ops:
        loot_files[lose_outcome + "_Loot"] = _loot_instance(lose_outcome + "_Loot", lose_ops)

    def outcome_xml(name, outcome, loot_name):
        body = [_t(1, "visible", "True"),
                _line(1, '<U n="scenario_outcome_loot">')]
        body += _scenario_loot_list(2, "loots", loot_name) if loot_name else ['    <L n="loots"/>']
        body += [_line(1, "</U>"),
                 _t(1, "outcome_title_text", loc("Scenario complete")),
                 _t(1, "outcome_description_text", loc(outcome.get("notification") or "Well done."))]
        return _instance("ScenarioOutcome", TYPE_SNIPPET,
                         "gameplay_scenarios.scenario_outcomes", name, body)

    files[win_outcome] = outcome_xml(win_outcome, win_text,
                                     win_outcome + "_Loot" if win_ops else None)
    files[lose_outcome] = outcome_xml(lose_outcome, lose_text,
                                      lose_outcome + "_Loot" if lose_ops else None)
    files.update(loot_files)

    start = scenario.get("start") or {}
    start_ops = _start_ops(start, warnings, unsupported)
    start_loot_name = None
    if start_ops:
        start_loot_name = base + "_StartLoot"
        files[start_loot_name] = _loot_instance(start_loot_name, start_ops)

    phase_goals = []
    for goal in scenario.get("goals") or ():
        goal_name = base + "_Goal_" + slugify(str(goal.get("id")))
        goal_xml = _goal_instance(goal_name, goal, warnings, unsupported)
        if goal_xml is None:
            continue
        files[goal_name] = goal_xml
        reward_ops = _reward_ops(goal.get("reward"), warnings)
        goal_loot_name = None
        if reward_ops:
            goal_loot_name = goal_name + "_Loot"
            files[goal_loot_name] = _loot_instance(goal_loot_name, reward_ops)
        phase_goals.append((goal_name, goal_loot_name))

    if not phase_goals:
        raise ExportError(
            "none of this scenario's goals can be exported to the menu; "
            "see the warnings for the types that have no equivalent")

    body = ['  <T n="phase_objective">%s</T>' % loc(scenario.get("description") or scenario.get("name")),
            '  <L n="goals">']
    for goal_name, goal_loot_name in phase_goals:
        body += ['    <U>',
                 '      <L n="goal_sequence">',
                 '        <U>',
                 '          <U n="goal">',
                 '            <T n="situation_goal">%s</T>' % escape(goal_name),
                 '            <E n="required_pack">BASE_GAME</E>',
                 '            <T n="mandatory">True</T>',
                 '            <T n="hidden">False</T>']
        if goal_loot_name:
            body += _scenario_loot_list(6, "goal_loot", goal_loot_name)
        else:
            body += ['            <L n="goal_loot"/>']
        body += ['            <L n="loot_on_instantiate"/>',
                 '          </U>',
                 '        </U>',
                 '      </L>',
                 '    </U>']
    body += ['  </L>',
             '  <U n="phase_fallback_output">',
             '    <U n="output">',
             '      <T n="scenario_outcome">%s</T>' % escape(win_outcome),
             '      <U n="output_loot">',
             '        <L n="loots"/>',
             '      </U>',
             '    </U>',
             '  </U>',
             '  <L n="phase_outputs"/>',
             '  <L n="terminators"/>']
    files[phase_name] = _instance("ScenarioPhase", TYPE_SNIPPET,
                                  "gameplay_scenarios.scenario_phase", phase_name, body)

    scenario_body = [
        '  <E n="compatibility_with_scenario_entry_method">NEW_HOUSEHOLD</E>',
        _t(1, "scenario_name", loc(scenario.get("name") or base)),
        _t(1, "scenario_description", loc(scenario.get("description") or "")),
        _t(1, "tagline_text", loc(menu.get("tagline") or scenario.get("description") or "")),
        '  <L n="scenario_tags"/>',
    ]
    if menu.get("icon"):
        scenario_body.append(_t(1, "icon", escape(str(menu["icon"]))))
    scenario_body += [
        '  <L n="scenario_role_data"/>',
        '  <L n="relationship_requirements"/>',
        _t(1, "starting_phase", escape(phase_name)),
        '  <L n="terminators"/>',
        _t(1, "outcome_on_cancel", escape(lose_outcome)),
        _t(1, "outcome_on_validation_failed", escape(lose_outcome)),
        '  <U n="loot_on_end"/>',
        '  <L n="goals"/>',
        _t(1, "household_money", int(start.get("money")) if isinstance(start.get("money"), (int, float)) else 20000),
        '  <L n="loot_on_scenario_start">',
        '    <U>',
        '      <E n="Enum Entry">NEW_HOUSEHOLD</E>',
        '      <U n="Loots">',
        '        <L n="household_loot">',
    ]
    if start_loot_name:
        scenario_body.append(_line(5, "<T>%s</T>" % escape(start_loot_name)))
    scenario_body += [
        '        </L>',
        '        <L n="rel_loot"/>',
        '      </U>',
        '    </U>',
        '  </L>',
        '  <U n="loot_on_scenario_end">',
        '    <L n="household_loot_on_successful_completion"/>',
        '  </U>',
    ]
    scenario_body += _start_notification(
        scenario.get("name") or base, "Your scenario has started.")
    scenario_body += [_t(1, "ui_sort_order", int(menu.get("sort_order", 100)))]

    templates = []
    if menu.get("template"):
        templates.append(str(menu["template"]))
    scenario_body.append('  <L n="compatible_premade_household_templates">')
    for template in templates:
        scenario_body.append(_line(2, "<T>%s</T>" % escape(template)))
    scenario_body.append('  </L>')

    category = _menu_option(menu, "category", warnings)
    difficulty = _menu_option(menu, "difficulty", warnings)
    if category:
        scenario_body.append(_e(1, "category", category))
    else:
        warnings.append("menu.category is not set: the card may show under an unknown category")
    if difficulty:
        scenario_body.append(_e(1, "difficulty", difficulty))
    else:
        warnings.append("menu.difficulty is not set: the card may show as unknown difficulty")

    files[base] = _instance("Scenario", TYPE_SNIPPET,
                            "gameplay_scenarios.scenario", base, scenario_body)

    if scenario.get("deadline_days"):
        unsupported.append("deadline_days is not enforced by the game's menu scenarios")
    for rule in scenario.get("rules") or ():
        unsupported.append('rule "{0}" ({1}) is enforced by the script mod only'.format(
            rule.get("id") or rule.get("type"), rule.get("type")))

    return ExportResult(files, warnings, unsupported)


def build(scenario, out_path, slug=None, package_name=None):
    """Render and build the .package. Returns (ExportResult, out_path)."""
    result = render(scenario, slug=slug)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tuning_dir = Path(tmp) / "tuning"
        tuning_dir.mkdir()
        for name, xml in result.files.items():
            (tuning_dir / (name + ".xml")).write_text(xml, encoding="utf-8")
        tuning.build_package(tmp, out_path, package_name or out_path.stem)
    return result, out_path


def export_file(path, out_path=None, slug=None):
    scenario = load_file(path)
    out_path = Path(out_path) if out_path else (
        config.BUILD_DIR / ("{}_{}.package".format(config.CREATOR, slug or slugify(scenario["name"]))))
    return build(scenario, out_path, slug=slug)
