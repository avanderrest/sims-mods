"""Compiles a mod's tuning XML into a .package, so pie-menu and phone entries can be made
without Sims 4 Studio. Used by build.py:

  mods/<name>/tuning/*.xml  -> tuning instances in build/<creator>_<name>.package
  mods/<name>/text/*.txt    -> string-table entries in the same package (one string per
                               line; use these for labels a script shows itself)

Each XML file is one tuning instance in the game's own format (<I c=... i="interaction" n=... s=...>).
Text shown in the game is written inline as {{string:Pay Off Debt}}: the build turns each one
into a string-table key (a hash of the text) and adds the text to a string table, copied
into every game language so it shows whatever language the game is set to.

Aspiration and objective tuning is the exception: the career panel only reads the binary
SimData resource (0x545AC67A), never the per-type XML, so those two classes are compiled by
simdata.py into SimData bytes. EA ships them the same way - its own packages contain no
ASPIRATION/OBJECTIVE XML at all - and the resource's group is the tuning type's group id
(0xB6465D for aspirations, 0x69453E for objectives), not the pack group.

Scenario snippets get the same treatment, into the scenario group 0x00F216E1: the Scenarios
screen is client-side and reads only that binary, so a snippet-only scenario never lists.
Both forms ship, as EA's own scenario packages do.

Every other file declares its pack group with <!-- group: 0x00B6465D --> (default 0).

See AGENTS.md for the tuning traps (ids, references, comment placement) before changing any
of this.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import dbpf
import simdata

# Tuning resource types, by the i="..." attribute of the instance.
# The last three are also used by tools/scenario_export.py for the Scenarios menu.
TUNING_TYPES = {
    "interaction": 0xE882D22F,
    "snippet": 0x7DF2169C,
    "situation_goal": 1502554343,   # Types.SITUATION_GOAL
    "action": 209137191,            # Types.ACTION (LootActions)
    "aspiration": 683034229,        # Types.ASPIRATION
    "objective": 6899006,           # Types.OBJECTIVE
}
STBL_TYPE = 0x220557DA
STBL_GROUP = 0x80000000
SIMDATA_TYPE = 0x545AC67A   # the game's SimData container for tuning instances
LOCALES = range(0x00, 0x13)   # every language code the game uses (English is 0x00)

# Tuning classes that only load from SimData, and the resource group each one uses.
# (EA's own packages file aspirations under 00B6465D and objectives under 0069453E.)
SIMDATA_GROUPS = {
    "aspiration": 0x00B6465D,
    "objective": 0x0069453E,
}

# The schemas the game has registered for those two classes. A schema hash is part of the
# file format; these values are EA's.
ASPIRATION_SCHEMA_HASH = 0x8CAF3605
OBJECTIVE_SCHEMA_HASH = 0x484467E3
OBJECTIVE_AGE_LIST = 0xC1A03855   # the "all ages" variant EA uses on objectives

# Scenarios are the same story: the Scenarios screen is client-side and builds its cards
# from the client binary export, so a Scenario that ships only the snippet never lists.
# EA's own files keep the whole scenario in one SimData (groups and schema hashes below).
SCENARIO_GROUP = 0x00F216E1
SCENARIO_SCHEMA_HASH = 0x6CD604F2
SCENARIO_GOAL_SCHEMA_HASH = 0xC665ED5C
SCENARIO_RELATIONSHIP_SCHEMA_HASH = 0x41A09068
SCENARIO_ROLE_SCHEMA_HASH = 0xD206A6AD
SCENARIO_INTERVAL_SCHEMA_HASH = 0xD55764F8

# Enum values as the client binary stores them (small ints, not hashes). Only the values
# EA's own scenarios use are known; an unknown name is written as 0 (INVALID) and the
# exporter warns, because a card in the INVALID category does not list.
SCENARIO_CATEGORY_VALUES = {"Challenge": 3}
SCENARIO_DIFFICULTY_VALUES = {"EASY": 3, "INTERMEDIATE": 4, "HARD": 5}
SCENARIO_ENTRY_METHOD_VALUES = {"NEW_HOUSEHOLD": 1, "EXISTING_HOUSEHOLD": 2}
SCENARIO_RELATIONSHIP_TYPE_VALUES = {"NONE": 6}

_STRING = re.compile(r"\{\{string:(.+?)\}\}")
_INSTANCE = re.compile(r'<I\b[^>]*\bi="([^"]+)"[^>]*\bs="(\d+)"')
_CLASS = re.compile(r'<I\b[^>]*\bc="([^"]+)"')
_GROUP = re.compile(r"<!--\s*group\s*:\s*(0x[0-9A-Fa-f]+|[0-9A-Fa-f]+)\s*-->")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def fnv32(text):
    h = 0x811C9DC5
    for b in text.lower().encode("utf-8"):
        h = (h * 0x01000193) & 0xFFFFFFFF
        h ^= b
    return h


def fnv64(text):
    h = 0xCBF29CE484222325
    for b in text.lower().encode("utf-8"):
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
        h ^= b
    return h


def string_key(text):
    return fnv32(text)


def stbl(strings):
    """A string table (STBL version 5) for {key: text}."""
    import struct
    entries = bytearray()
    total = 0
    for key, text in sorted(strings.items()):
        data = text.encode("utf-8")
        entries += struct.pack("<IBH", key, 0, len(data)) + data
        total += len(data) + 1
    return b"STBL" + struct.pack("<HBQHI", 5, 0, len(strings), 0, total) + bytes(entries)


def read_texts(mod_dir):
    """Plain strings from mods/<name>/text/*.txt: one per line, blank and # lines skipped.

    These become string-table entries without a tuning instance, for text that a script
    shows through a localized string (rather than an XML tunable).
    """
    texts = []
    for f in sorted((Path(mod_dir) / "text").glob("*.txt")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                texts.append(line)
    return texts


def _string_key_of(text, strings):
    """A tuning that stores text as a localization key: {{string:...}} becomes a key and a
    string-table entry; a bare number is taken to already be a key."""
    text = (text or "").strip()
    match = _STRING.fullmatch(text)
    if match:
        value = match.group(1)
        key = string_key(value)
        strings[key] = value
        return key
    return int(text, 0)


def _first_child(root, name):
    for child in root:
        if child.get("n") == name:
            return child
    return None


def _value_of(node, default=None):
    if node is None:
        return default
    return (node.text or "").strip()


def _simdata_bytes(root, type_name, strings):
    """Compiles one tuning instance to the binary SimData the career panel reads.

    Only non-default columns are stored, exactly like EA's files: an aspiration is just its
    objective list, an objective is its display strings plus the two presentation flags.
    """
    name = root.get("n")
    if type_name == "aspiration":
        schema = simdata.Schema("AspirationCareer", ASPIRATION_SCHEMA_HASH,
                                [simdata.Column("objectives", simdata.VECTOR)])
        listed = root.findall("./L[@n='objectives']/T") or root.findall("L/T")
        row = {"objectives": simdata.VectorCell([
            simdata.Value(simdata.TABLESETREFERENCE, int((node.text or "0").strip(), 0))
            for node in listed])}
    else:
        # Column order is ASCII order of the names; the writer turns that into row offsets.
        schema = simdata.Schema("Objective", OBJECTIVE_SCHEMA_HASH, [
            simdata.Column("display_age_list", simdata.VARIANT),
            simdata.Column("display_text", simdata.LOCKEY),
            simdata.Column("satisfaction_points", simdata.INT32),
            simdata.Column("show_progress", simdata.BOOL),
            simdata.Column("tooltip", simdata.LOCKEY),
        ])
        display_text = _first_child(root, "display_text")
        tooltip = _first_child(root, "tooltip")
        if display_text is None or tooltip is None:
            raise ValueError("an objective needs display_text and tooltip")
        # No test means goal_value() is its default of 1, which the panel would render as a
        # misleading "0/1". Leave the count off unless a tuning opts in.
        progress = _value_of(_first_child(root, "show_progress"), "False")
        row = {
            "display_age_list": simdata.VariantCell(OBJECTIVE_AGE_LIST),
            "display_text": simdata.Value(simdata.LOCKEY, _string_key_of(display_text.text, strings)),
            "satisfaction_points": simdata.Value(
                simdata.INT32, int(_value_of(_first_child(root, "satisfaction_points"), "0"))),
            "show_progress": simdata.Value(simdata.BOOL, progress.lower() in ("1", "true")),
            "tooltip": simdata.Value(simdata.LOCKEY, _string_key_of(tooltip.text, strings)),
        }
    # EA and Sims 4 Studio both put 0x8D in the header's unused field; mirror that.
    model = simdata.SimData([schema], [simdata.Instance(name, schema, row)], unused=0x8D)
    return simdata.write(model)


def _child_text(node, name):
    return _value_of(_first_child(node, name), "")


def _int_child(node, name, default=0):
    text = _child_text(node, name)
    return int(text, 0) if text else default


def _lockey_cell(node, name, strings):
    text = _child_text(node, name)
    return simdata.Value(simdata.LOCKEY, _string_key_of(text, strings) if text else 0)


def _ref_cell(node, name):
    text = _child_text(node, name)
    return simdata.Value(simdata.TABLESETREFERENCE, int(text, 0) if text else 0)


def _enum_cell(node, name, values, code=simdata.INT64):
    return simdata.Value(code, values.get(_child_text(node, name), 0))


def _bool_cell(node, name, default):
    text = _child_text(node, name) or default
    return simdata.Value(simdata.BOOL, text.lower() in ("1", "true"))


def _resource_key_cell(node, name):
    text = _child_text(node, name)
    if not text:
        return simdata.Value(simdata.RESOURCEKEY, (0, 0, 0))
    parts = text.split(":")
    if len(parts) != 3:
        raise ValueError("{} is not a resource key: {}".format(name, text))
    return simdata.Value(simdata.RESOURCEKEY, tuple(int(part, 16) for part in parts))


def _scenario_simdata_bytes(root, strings):
    """Compiles a Scenario snippet to the client binary the Scenarios screen reads.

    The Scenarios screen is client-side and builds its cards from SimData, not from the
    snippet: a Scenario shipped as XML alone loads on the server and never lists. EA's own
    scenario files carry this SimData in group 0x00F216E1, with the instance id of the
    snippet. Only the columns in EA's Scenario schema are written - fields the snippet has
    but the client does not know (`screen_slam_scenario_completed`, the loot lists, the
    start notification) are deliberately left out.

    Enum columns hold small ints, not names; see SCENARIO_*_VALUES above.
    """
    goal_schema = simdata.Schema("TunableScenarioGoalData", SCENARIO_GOAL_SCHEMA_HASH, [
        simdata.Column("goal_description_text", simdata.LOCKEY),
        simdata.Column("goal_title_text", simdata.LOCKEY),
        simdata.Column("required_pack", simdata.INT64),
        simdata.Column("situation_goal", simdata.TABLESETREFERENCE),
        simdata.Column("visible_in_load_dialog", simdata.BOOL),
    ])
    relationship_schema = simdata.Schema(
        "TunableRelationshipRequirement", SCENARIO_RELATIONSHIP_SCHEMA_HASH, [
            simdata.Column("household_requirement_text", simdata.LOCKEY),
            simdata.Column("relationship_type", simdata.INT64),
            simdata.Column("subject_role", simdata.TABLESETREFERENCE),
            simdata.Column("target_role", simdata.TABLESETREFERENCE),
        ])
    role_schema = simdata.Schema("TunableScenarioRoleData", SCENARIO_ROLE_SCHEMA_HASH, [
        simdata.Column("role", simdata.TABLESETREFERENCE),
        simdata.Column("role_traits", simdata.VECTOR),
        simdata.Column("sim_count", simdata.OBJECT),
    ])
    interval_schema = simdata.Schema(
        "ScenarioRoleTunableInterval", SCENARIO_INTERVAL_SCHEMA_HASH, [
            simdata.Column("lower_bound", simdata.INT32),
            simdata.Column("upper_bound", simdata.INT32),
        ])
    # Column order is ASCII order of the names, which is how EA assigns the row offsets.
    scenario_schema = simdata.Schema("Scenario", SCENARIO_SCHEMA_HASH, [
        simdata.Column("category", simdata.INT64),
        simdata.Column("compatibility_with_scenario_entry_method", simdata.VECTOR),
        simdata.Column("compatible_premade_household_templates", simdata.VECTOR),
        simdata.Column("difficulty", simdata.INT64),
        simdata.Column("goals", simdata.VECTOR),
        simdata.Column("household_money", simdata.INT32),
        simdata.Column("icon", simdata.RESOURCEKEY),
        simdata.Column("properties", simdata.VECTOR),
        simdata.Column("relationship_requirements", simdata.VECTOR),
        simdata.Column("reward_icon", simdata.RESOURCEKEY),
        simdata.Column("reward_text", simdata.LOCKEY),
        simdata.Column("scenario_description", simdata.LOCKEY),
        simdata.Column("scenario_name", simdata.LOCKEY),
        simdata.Column("scenario_role_data", simdata.VECTOR),
        simdata.Column("scenario_tags", simdata.VECTOR),
        simdata.Column("tagline_text", simdata.LOCKEY),
        simdata.Column("ui_sort_order", simdata.INT32),
    ])

    def items(name):
        node = _first_child(root, name)
        return list(node) if node is not None else []

    entry_methods = []
    for node in items("compatibility_with_scenario_entry_method"):
        name = (node.text or "").strip()
        # An empty <E/> is the enum's default member, which is NEW_HOUSEHOLD.
        value = SCENARIO_ENTRY_METHOD_VALUES.get(name, 1 if not name else 0)
        if value not in entry_methods:
            entry_methods.append(value)

    templates = []
    for node in items("compatible_premade_household_templates"):
        text = (node.text or "").strip()
        if text:
            templates.append(simdata.Value(simdata.TABLESETREFERENCE, int(text, 0)))

    goals = [simdata.ObjectCell(goal_schema, {
        "goal_description_text": _lockey_cell(goal, "goal_description_text", strings),
        "goal_title_text": _lockey_cell(goal, "goal_title_text", strings),
        "required_pack": _ref_cell(goal, "required_pack"),
        "situation_goal": _ref_cell(goal, "situation_goal"),
        # The tunable defaults to True; the client uses it to hide a goal row.
        "visible_in_load_dialog": _bool_cell(goal, "visible_in_load_dialog", "True"),
    }) for goal in items("goals")]

    roles = [simdata.ObjectCell(role_schema, {
        "role": _ref_cell(role, "role"),
        # role_traits is not exported yet; an empty vector is what EA writes for none.
        "role_traits": simdata.VectorCell([]),
        "sim_count": simdata.ObjectCell(interval_schema, {
            "lower_bound": simdata.Value(
                simdata.INT32, _int_child(_first_child(role, "sim_count"), "lower_bound", 1)),
            "upper_bound": simdata.Value(
                simdata.INT32, _int_child(_first_child(role, "sim_count"), "upper_bound", 1)),
        }),
    }) for role in items("scenario_role_data")]

    relationships = [simdata.ObjectCell(relationship_schema, {
        "household_requirement_text": _lockey_cell(
            requirement, "household_requirement_text", strings),
        "relationship_type": _enum_cell(
            requirement, "relationship_type", SCENARIO_RELATIONSHIP_TYPE_VALUES),
        "subject_role": _ref_cell(requirement, "subject_role"),
        "target_role": _ref_cell(requirement, "target_role"),
    }) for requirement in items("relationship_requirements")]

    tags = [simdata.Value(simdata.TABLESETREFERENCE, int((node.text or "0").strip(), 0))
            for node in items("scenario_tags")]

    row = {
        "category": _enum_cell(root, "category", SCENARIO_CATEGORY_VALUES),
        "compatibility_with_scenario_entry_method": simdata.VectorCell(
            [simdata.Value(simdata.INT64, value) for value in entry_methods]),
        "compatible_premade_household_templates": simdata.VectorCell(templates),
        "difficulty": _enum_cell(root, "difficulty", SCENARIO_DIFFICULTY_VALUES),
        "goals": simdata.VectorCell(goals),
        "household_money": simdata.Value(simdata.INT32, _int_child(root, "household_money")),
        "icon": _resource_key_cell(root, "icon"),
        "properties": simdata.VectorCell([]),
        "relationship_requirements": simdata.VectorCell(relationships),
        "reward_icon": _resource_key_cell(root, "reward_icon"),
        "reward_text": _lockey_cell(root, "reward_text", strings),
        "scenario_description": _lockey_cell(root, "scenario_description", strings),
        "scenario_name": _lockey_cell(root, "scenario_name", strings),
        "scenario_role_data": simdata.VectorCell(roles),
        "scenario_tags": simdata.VectorCell(tags),
        "tagline_text": _lockey_cell(root, "tagline_text", strings),
        "ui_sort_order": simdata.Value(simdata.INT32, _int_child(root, "ui_sort_order")),
    }
    model = simdata.SimData(
        [scenario_schema, goal_schema, relationship_schema, role_schema, interval_schema],
        [simdata.Instance(root.get("n"), scenario_schema, row)],
        # EA's scenario SimData leaves the header's unused field at 0 (careers use 0x8D).
        unused=0)
    return simdata.write(model)


def compile_xml(text, strings):
    """Replaces {{string:...}} with string keys (collecting them in `strings`).
    Returns the resources to write, as (resource type, group, instance id, bytes).

    Career tunings produce two: the binary SimData the panel reads, and the per-type
    XML alongside it, which is how Sims 4 Studio and other tuning mods ship them."""
    def to_key(match):
        key = string_key(match.group(1))
        strings[key] = match.group(1)
        return "0x{:08X}".format(key)
    group_match = _GROUP.search(text)
    group = int(group_match.group(1), 16) if group_match else 0
    # Comments must not be the first node: the tuning loader expects the instance element
    # first (S4S fails on a leading comment), so drop them from the built resource.
    text = _COMMENT.sub("", text)
    m = _INSTANCE.search(text)
    if m is None or m.group(1) not in TUNING_TYPES:
        raise ValueError("no <I i=... s=...> instance of a known type ({})".format(", ".join(TUNING_TYPES)))
    type_name, instance = m.group(1), int(m.group(2))
    class_match = _CLASS.search(text)
    if class_match is not None and class_match.group(1) == "Scenario":
        try:
            root = ET.fromstring(text.strip())
        except ET.ParseError as e:
            raise ValueError("not valid XML: {}".format(e))
        return [
            (SIMDATA_TYPE, SCENARIO_GROUP, instance, _scenario_simdata_bytes(root, strings)),
            (TUNING_TYPES[type_name], 0, instance, _STRING.sub(to_key, text).encode("utf-8")),
        ]
    if type_name in SIMDATA_GROUPS:
        try:
            root = ET.fromstring(text.strip())
        except ET.ParseError as e:
            raise ValueError("not valid XML: {}".format(e))
        return [
            (SIMDATA_TYPE, SIMDATA_GROUPS[type_name], instance,
             _simdata_bytes(root, type_name, strings)),
            (TUNING_TYPES[type_name], 0, instance, _STRING.sub(to_key, text).encode("utf-8")),
        ]
    return [(TUNING_TYPES[type_name], group, instance, _STRING.sub(to_key, text).encode("utf-8"))]


def build_package(mod_dir, out_file, package_name):
    files = sorted((Path(mod_dir) / "tuning").glob("*.xml"))
    texts = read_texts(mod_dir)
    if not files and not texts:
        return False
    strings = {string_key(text): text for text in texts}
    resources = []
    for f in files:
        try:
            resources.extend(compile_xml(f.read_text(encoding="utf-8"), strings))
        except ValueError as e:
            raise SystemExit("{}: {}".format(f, e))
    if strings:
        table = stbl(strings)
        base = fnv64(package_name) & 0x00FFFFFFFFFFFFFF
        resources += [(STBL_TYPE, STBL_GROUP, (locale << 56) | base, table) for locale in LOCALES]
    dbpf.write_package(out_file, resources)
    return True
