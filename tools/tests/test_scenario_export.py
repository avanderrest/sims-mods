import xml.etree.ElementTree as ET

import pytest

import dbpf
import scenario_export
import scenario_icons
from scenario_export import SCENARIO_DIR, render, build


def load(name):
    return scenario_export.load_file(SCENARIO_DIR / (name + ".json"))


def test_every_rendered_file_is_well_formed_xml():
    result = render(load("rags_to_riches"))
    assert result.files
    for name, text in result.files.items():
        root = ET.fromstring(text)
        assert root.tag == "I", name
        assert root.get("n") == name


def test_instance_ids_are_name_hashes_with_high_bit():
    result = render(load("rags_to_riches"))
    for name, text in result.files.items():
        root = ET.fromstring(text)
        assert int(root.get("s")) == scenario_export.tuning_id(name)


def test_rags_to_riches_maps_its_supported_goals():
    result = render(load("rags_to_riches"))
    assert any("SituationGoalActor" in text for text in result.files.values())
    assert any("SituationGoal" in text for text in result.files.values())
    scenario = result.files["HouseRules_Scenario_Rags_to_Riches"]
    assert "NEW_HOUSEHOLD" in scenario
    # Goals are listed on the Scenario itself, as EA's own scenarios do.
    assert str(scenario_export.tuning_id("HouseRules_Scenario_Rags_to_Riches_Goal_rich")) in scenario
    assert "Skill_Painting" in "".join(result.files.values())


def test_unsupported_goal_types_are_reported_not_silently_dropped():
    result = render(load("starving_artist"))
    joined = " ".join(result.unsupported)
    assert "career_level" in joined
    assert "relationship" in joined
    assert "deadline_days" in joined


def test_rules_are_reported_as_script_only():
    result = render(load("rags_to_riches"))
    assert any("rule" in warning and "script mod only" in warning
               for warning in result.unsupported)


def test_nothing_mappable_raises_with_a_clear_message():
    scenario = {
        "name": "Nothing",
        "goals": [{"id": "custom-one", "type": "custom", "description": "tick me"}],
    }
    with pytest.raises(scenario_export.ExportError) as error:
        render(scenario)
    assert "none of this scenario's goals" in str(error.value)


def test_menu_category_and_difficulty_are_optional_but_warned():
    # legacy_starter leaves them unset, which the exporter warns about.
    result = render(load("legacy_starter"))
    assert any("menu.category" in warning for warning in result.warnings)
    assert any("menu.difficulty" in warning for warning in result.warnings)

    # rags_to_riches sets them, so the card lands in a known category.
    assert not any("menu.category" in warning
                   for warning in render(load("rags_to_riches")).warnings)

    scenario = dict(load("rags_to_riches"))
    scenario["menu"] = {"category": "Challenge", "difficulty": "HARD"}
    result = render(scenario)
    scenario_xml = result.files["HouseRules_Scenario_Rags_to_Riches"]
    assert '<E n="category">Challenge</E>' in scenario_xml
    assert '<E n="difficulty">HARD</E>' in scenario_xml


def test_build_writes_a_package_with_tuning_and_strings(tmp_path):
    out = tmp_path / "test.package"
    result, path = build(load("rags_to_riches"), out)
    assert path.exists()
    package = dbpf.Package(path)
    types = {entry.type for entry in package.entries}
    assert 0x7DF2169C in types          # snippets: Scenario, phase, outcomes
    assert 1502554343 in types          # situation goals
    assert 0x220557DA in types          # string table


def test_start_conditions_become_loot_actions():
    scenario = dict(load("rags_to_riches"))
    scenario["start"] = {
        "money": 0,
        "traits": {"active": ["trait_Ambitious"]},
        "skills": {"active": {"Painting": 2}},
    }
    result = render(scenario)
    loot = result.files["HouseRules_Scenario_Rags_to_Riches_StartLoot"]
    assert '<V t="money_loot">' in loot
    assert "<T n=\"value\">0</T>" in loot
    assert "<T n=\"trait\">trait_Ambitious</T>" in loot
    assert "<T n=\"stat\">Skill_Painting</T>" in loot


def test_entry_method_is_written_as_an_enum_flags_list():
    # Scenario.compatibility_with_scenario_entry_method is a TunableEnumFlags. Writing it as
    # a single <E> makes the tuning fail to load, and the scenario never reaches the menu.
    root = ET.fromstring(render(load("rags_to_riches")).files["HouseRules_Scenario_Rags_to_Riches"])
    node = root.find("L[@n='compatibility_with_scenario_entry_method']")
    assert node is not None
    # EA's own scenarios carry the entry method plus a trailing empty entry.
    assert [entry.text for entry in node][0] == "NEW_HOUSEHOLD"


def test_tuning_references_are_instance_ids_that_exist_in_the_package():
    # The game resolves a name reference with its own hash, which does not match our
    # instances' ids, so every reference must be written as an id - and that id must be one
    # of the tunings we ship. Otherwise the Scenario fails to finalize at load time and the
    # card never reaches the menu.
    import re
    result = render(load("rags_to_riches"))
    instance_ids = {re.search(r's="(\d+)"', xml).group(1) for xml in result.files.values()}
    referenced = set()
    for xml in result.files.values():
        referenced |= set(re.findall(
            r'<T n="(?:starting_phase|outcome_on_cancel|outcome_on_validation_failed|'
            r'situation_goal|loot_action|scenario_outcome)">(\d+)</T>', xml))
    assert referenced
    assert referenced <= instance_ids


def test_built_package_carries_the_client_binary_for_the_scenario(tmp_path):
    # The Scenarios screen builds its cards from SimData, not from the snippet: this is the
    # difference between our packages and the third-party scenarios that do list.
    out = tmp_path / "test.package"
    _, path = build(load("rags_to_riches"), out)
    package = dbpf.Package(path)
    import scenario_export as se
    import tuning

    scenario_id = se.tuning_id("HouseRules_Scenario_Rags_to_Riches")
    simdata_entries = [entry for entry in package.entries
                       if entry.type == tuning.SIMDATA_TYPE]
    assert [(entry.group, entry.instance) for entry in simdata_entries] == [
        (tuning.SCENARIO_GROUP, scenario_id)]
    # Same instance as the Scenario snippet, so the client pairs them up.
    assert any(entry.type == 0x7DF2169C and entry.instance == scenario_id
               for entry in package.entries)

    # Every goal the Scenario declares is in the binary as a reference to a goal we ship.
    data = package.read(simdata_entries[0])
    goal_ids = {entry.instance for entry in package.entries
                if entry.type == tuning.TUNING_TYPES["situation_goal"]}
    assert goal_ids
    for goal_id in goal_ids:
        assert goal_id.to_bytes(8, "little") in data


def test_card_icon_defaults_to_eas_toddler_icon():
    xml = render(load("rags_to_riches")).files["HouseRules_Scenario_Rags_to_Riches"]
    assert xml.count('<T n="icon"') == 1
    assert r"headline_Scenario_TooManyToddlers.png" in xml
    assert "9df478041f06b167" in xml


def test_card_icon_can_be_a_name_from_the_picklist():
    scenario = dict(load("rags_to_riches"))
    scenario["menu"] = dict(scenario.get("menu") or {}, icon="scenario_RomCom")
    xml = render(scenario).files["HouseRules_Scenario_Rags_to_Riches"]
    assert xml.count('<T n="icon"') == 1
    assert r"InGame\UI\Icons\Scenarios\scenario_RomCom.png" in xml
    assert "8cb8d475ca2dc10b" in xml


def test_card_icon_accepts_a_raw_resource_key():
    scenario = dict(load("rags_to_riches"))
    scenario["menu"] = dict(scenario.get("menu") or {},
                            icon="2f7d0004:00000000:0123456789abcdef")
    xml = render(scenario).files["HouseRules_Scenario_Rags_to_Riches"]
    assert "2f7d0004:00000000:0123456789abcdef" in xml


def test_unknown_card_icon_name_names_the_problem():
    scenario = dict(load("rags_to_riches"))
    scenario["menu"] = dict(scenario.get("menu") or {}, icon="scenario_NotAnIcon")
    with pytest.raises(scenario_export.ExportError) as error:
        render(scenario)
    assert "scenario_NotAnIcon" in str(error.value)


def test_every_listed_icon_has_a_name_path_and_key():
    names = [icon["name"] for icon in scenario_icons.ICONS]
    assert len(names) == len(set(names))
    for icon in scenario_icons.ICONS:
        assert "Icons\\Scenarios" in icon["path"], icon
        assert icon["key"].startswith("2f7d0004:"), icon
