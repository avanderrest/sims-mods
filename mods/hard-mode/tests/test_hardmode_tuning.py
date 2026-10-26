"""The phone entry's tuning: the class must exist in the game, and DoCommand must run our
command with the Sim's id.

The tuning is plain XML compiled into HouseRules_hard-mode.package by tools/tuning.py,
so this reads the source file rather than the package.
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import tuning  # noqa: E402  (tools/tuning.py: fnv64 is the id the game hashes from n=)

TUNING_FILE = Path(__file__).resolve().parents[1] / "tuning" / "PayOffDebt.xml"
INSTANCE = "HouseRules_HardMode_PayOffDebt"
COMMAND = "houserules.hard.money.pay_debt_phone"


def _instance():
    return ET.parse(str(TUNING_FILE)).getroot()


def test_phone_entry_uses_a_real_base_class():
    # CommandSuperInteraction does not exist in the game (it silently drops the tuning).
    node = _instance()
    assert node.tag == "I"
    assert node.get("c") == "ImmediateSuperInteraction"
    assert node.get("m") == "interactions.base.immediate_interaction"
    assert node.get("i") == "interaction"
    assert node.get("n") == INSTANCE


def test_phone_entry_id_matches_the_hash_the_script_looks_up():
    expected = tuning.fnv64(INSTANCE) | (1 << 63)
    assert int(_instance().get("s")) == expected


def test_phone_entry_runs_the_command_with_the_sims_id():
    node = _instance()
    extras = node.find("L[@n='basic_extras']")
    assert extras is not None
    runs = extras.findall("V[@t='do_command']")
    assert len(runs) == 1
    assert runs[0].find("T[@n='command']").text == COMMAND
    arguments = runs[0].findall("L[@n='arguments']/V[@t='participant']")
    assert len(arguments) == 1
    assert arguments[0].find("E[@n='argument']").text == "Actor"


def test_phone_entry_has_its_menu_text():
    node = _instance()
    assert node.find("T[@n='display_name']").text == "{{string:Pay Off Debt}}"
