import xml.etree.ElementTree as ET

import pytest

import dbpf
import scenario_export
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
    assert "HouseRules_Scenario_Rags_to_Riches_Phase" in scenario
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
    result = render(load("rags_to_riches"))
    assert any("menu.category" in warning for warning in result.warnings)
    scenario = dict(load("rags_to_riches"))
    scenario["menu"] = {"category": "CHALLENGE", "difficulty": "HARD"}
    result = render(scenario)
    scenario_xml = result.files["HouseRules_Scenario_Rags_to_Riches"]
    assert '<E n="category">CHALLENGE</E>' in scenario_xml
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
