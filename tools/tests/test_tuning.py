import struct

import dbpf
import tuning


def read_stbl(data):
    assert data[:4] == b"STBL"
    _, _, count, _, _ = struct.unpack_from("<HBQHI", data, 4)
    pos = 21
    strings = {}
    for _ in range(count):
        key, _, length = struct.unpack_from("<IBH", data, pos)
        pos += 7
        strings[key] = data[pos:pos + length].decode("utf-8")
        pos += length
    return strings


def test_text_only_mod_builds_an_english_string_table(tmp_path):
    mod = tmp_path / "labels"
    (mod / "text").mkdir(parents=True)
    (mod / "text" / "labels.txt").write_text(
        "# a comment\n\nPoorer than the club leader\nSimilar to the club leader\n",
        encoding="utf-8")
    out = tmp_path / "out.package"

    assert tuning.build_package(mod, out, "Test_labels")
    package = dbpf.Package(out)
    tables = [entry for entry in package.entries if entry.type == tuning.STBL_TYPE]
    assert len(tables) == len(tuning.LOCALES)
    strings = read_stbl(package.read(tables[0]))
    assert strings[tuning.string_key("Poorer than the club leader")] == "Poorer than the club leader"
    assert strings[tuning.string_key("Similar to the club leader")] == "Similar to the club leader"
    assert len(strings) == 2


def test_mod_without_tuning_or_text_is_not_built(tmp_path):
    mod = tmp_path / "empty"
    mod.mkdir()
    assert not tuning.build_package(mod, tmp_path / "out.package", "Test_empty")


def test_text_and_tuning_share_the_package(tmp_path):
    mod = tmp_path / "mixed"
    (mod / "tuning").mkdir(parents=True)
    (mod / "text").mkdir()
    (mod / "text" / "labels.txt").write_text("A label\n", encoding="utf-8")
    (mod / "tuning" / "test.xml").write_text(
        '<I c="TestInteraction" i="interaction" n="Test" s="12345">'
        '<T n="pie_menu_name">{{string:A label}}</T></I>',
        encoding="utf-8")
    out = tmp_path / "out.package"

    assert tuning.build_package(mod, out, "Test_mixed")
    package = dbpf.Package(out)
    assert len([entry for entry in package.entries if entry.type == tuning.STBL_TYPE]) == len(tuning.LOCALES)
    strings = read_stbl(package.read(next(
        entry for entry in package.entries if entry.type == tuning.STBL_TYPE)))
    assert strings[tuning.string_key("A label")] == "A label"


def test_aspiration_override_is_compiled_to_simdata(tmp_path):
    # The career panel only reads the binary SimData resource; the group is the tuning type's.
    mod = tmp_path / "simdata"
    (mod / "tuning").mkdir(parents=True)
    (mod / "tuning" / "aspiration.xml").write_text(
        '<I c="AspirationCareer" i="aspiration" n="aspiration_nobleCareer_Level2" s="466308">'
        '<L n="objectives"><T>2130706434</T><T>2130706450</T></L></I>',
        encoding="utf-8")
    out = tmp_path / "out.package"

    assert tuning.build_package(mod, out, "Test_simdata")
    package = dbpf.Package(out)
    entries = [entry for entry in package.entries if entry.instance == 466308]
    # Both forms ship, as they do in Sims 4 Studio packages: the SimData the panel reads
    # and the per-type XML next to it.
    assert sorted((entry.type, entry.group) for entry in entries) == [
        (tuning.TUNING_TYPES["aspiration"], 0),
        (tuning.SIMDATA_TYPE, tuning.SIMDATA_GROUPS["aspiration"]),
    ]
    simdata_entry = next(entry for entry in entries if entry.type == tuning.SIMDATA_TYPE)
    data = package.read(simdata_entry)
    assert data[:4] == b"DATA"
    assert b"aspiration_nobleCareer_Level2" in data
    # both objective ids are stored as 8-byte table-set references
    assert struct.pack("<Q", 2130706434) in data
    assert struct.pack("<Q", 2130706450) in data


def test_objective_is_compiled_with_its_display_strings(tmp_path):
    mod = tmp_path / "objective"
    (mod / "tuning").mkdir(parents=True)
    (mod / "tuning" / "objective.xml").write_text(
        '<I c="Objective" i="objective" n="HouseRules_Test" s="24680">'
        '<T n="display_text">{{string:Be friends with a Duke}}</T>'
        '<T n="tooltip">{{string:Shown by the panel only}}</T></I>',
        encoding="utf-8")
    out = tmp_path / "out.package"

    assert tuning.build_package(mod, out, "Test_objective")
    package = dbpf.Package(out)
    entry = next(entry for entry in package.entries
                 if entry.instance == 24680 and entry.type == tuning.SIMDATA_TYPE)
    assert entry.group == tuning.SIMDATA_GROUPS["objective"]
    data = package.read(entry)
    assert b"HouseRules_Test" in data
    # columns are written in the ASCII order of their names
    columns = [b"display_age_list", b"display_text", b"satisfaction_points",
               b"show_progress", b"tooltip"]
    positions = [data.index(name) for name in columns]
    assert positions == sorted(positions)

    strings = read_stbl(package.read(next(
        entry for entry in package.entries if entry.type == tuning.STBL_TYPE)))
    assert strings[tuning.string_key("Be friends with a Duke")] == "Be friends with a Duke"
    assert strings[tuning.string_key("Shown by the panel only")] == "Shown by the panel only"


def test_scenario_is_compiled_to_the_client_binary(tmp_path):
    # The Scenarios screen is client-side: it reads the Scenario's SimData, in the scenario
    # group, under the snippet's instance id. Snippet-only scenarios never list.
    import struct

    mod = tmp_path / "scenario"
    (mod / "tuning").mkdir(parents=True)
    (mod / "tuning" / "scenario.xml").write_text(
        '<I c="Scenario" i="snippet" m="gameplay_scenarios.scenario" n="HouseRules_Test"'
        ' s="2147483649">'
        '<L n="compatibility_with_scenario_entry_method">'
        '<E>NEW_HOUSEHOLD</E><E /></L>'
        '<T n="scenario_name">{{string:My scenario}}</T>'
        '<L n="scenario_tags"><T>273404</T></L>'
        '<L n="scenario_role_data"><U><T n="role">273416</T>'
        '<U n="sim_count"><T n="lower_bound">1</T><T n="upper_bound">4</T></U></U></L>'
        '<L n="goals"><U><T n="goal_title_text">{{string:Finish it}}</T>'
        '<T n="situation_goal">2147483650</T></U></L>'
        '<E n="category">Challenge</E><E n="difficulty">HARD</E></I>',
        encoding="utf-8")
    out = tmp_path / "out.package"

    assert tuning.build_package(mod, out, "Test_scenario")
    package = dbpf.Package(out)
    entries = [entry for entry in package.entries if entry.instance == 2147483649]
    assert sorted((entry.type, entry.group) for entry in entries) == [
        (tuning.SIMDATA_TYPE, tuning.SCENARIO_GROUP),
        (tuning.TUNING_TYPES["snippet"], 0),
    ]
    data = package.read(next(
        entry for entry in entries if entry.type == tuning.SIMDATA_TYPE))
    assert data[:4] == b"DATA"
    # EA's schema hashes, so the client recognises the tables.
    for schema_hash in (tuning.SCENARIO_SCHEMA_HASH, tuning.SCENARIO_GOAL_SCHEMA_HASH,
                        tuning.SCENARIO_ROLE_SCHEMA_HASH, tuning.SCENARIO_INTERVAL_SCHEMA_HASH):
        assert struct.pack("<I", schema_hash) in data
    # The goal reference is the instance id the snippet points at.
    assert struct.pack("<Q", 2147483650) in data

    # Enum columns hold the client's small ints (Challenge=3, HARD=5), not the names.
    table_header = 8 + struct.unpack_from("<i", data, 8)[0]
    row = table_header + 20 + struct.unpack_from("<i", data, table_header + 20)[0]
    assert struct.unpack_from("<Q", data, row)[0] == 3        # category
    assert struct.unpack_from("<Q", data, row + 24)[0] == 5   # difficulty
