"""The career-panel overrides: EA's original rows plus ours.

The aspiration overrides replace EP21's promotion aspirations, so the panel only lists what
the XML names. These pin the split: EA's base-pack requirement(s) for the level stay in the
list (Charisma and, where the pack asks for it, Swordsmanship), followed by the rows the
script's gate adds (net worth, friends, the vacant throne).

The EA ids are the ones EP21's `aspiration_nobleCareer_Level*` resources reference; the
Swordsmanship objectives are `career_Skill_Swordsmanship_Level{2,3,4,5}` = 475845, 475846,
475843, 475844.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

TUNING = Path(__file__).resolve().parents[1] / "tuning"

# EA's original objectives per promotion rank 1..9.
EA_OBJECTIVES = {
    1: [26463],                     # Charisma 2
    2: [26464, 475845],             # Charisma 3, Swordsmanship 2
    3: [26465],                     # Charisma 4
    4: [26466, 475846],             # Charisma 5, Swordsmanship 3
    5: [26467],                     # Charisma 5
    6: [26468, 475843],             # Charisma 7, Swordsmanship 4
    7: [26470],                     # Charisma 8
    8: [202047],                    # Charisma 9
    9: [26472, 475844],             # Charisma 10, Swordsmanship 5
}

# The gate's rows: savings 0x7F000001 + N, friend 0x7F000011 + N, crown 0x7F000021.
OUR_OBJECTIVES = {
    1: [0x7F000001, 0x7F000011],
    2: [0x7F000002, 0x7F000012],
    3: [0x7F000003, 0x7F000013],
    4: [0x7F000004, 0x7F000014],
    5: [0x7F000005, 0x7F000015],
    6: [0x7F000006, 0x7F000016],
    7: [0x7F000007, 0x7F000017],
    8: [0x7F000008],
    9: [0x7F000021],
}


def objectives(level):
    path = TUNING / "NobleAspiration_Level{}.xml".format(level)
    root = ET.parse(str(path)).getroot()
    return [int(node.text) for node in root.find("L[@n='objectives']")]


def test_every_aspiration_lists_ea_rows_before_ours():
    for level in range(1, 10):
        assert objectives(level) == EA_OBJECTIVES[level] + OUR_OBJECTIVES[level], level
