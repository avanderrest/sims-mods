"""The Scenarios screen's card icons, by name, with the package path and resource key.

Names and keys only: the images are EA's and are not shipped here. A tuning references one
by its resource key (and, for readability in Sims 4 Studio, the package path). Extracted from
the game's combined tuning (`Data/Simulation/SimulationDeltaBuild0.package`, resource type
0x62E94D38), whose string table stores each path next to its key; the pairs were checked
against the icons the third-party scenario packages reference (`scenario_RomCom` and
`headline_Scenario_TooManyToddlers` match).

Keep this list to what the game ships: an icon plays whatever its path says, so a name from
another mod is not resolvable here, and a raw key can still be passed through instead.
"""

ICONS = [
    {"name": "Scenario_FrogCollection",
     "path": r"InGame\UI\Icons\Scenarios\Scenario_FrogCollection.png",
     "key": "2f7d0004:00000000:efc5eecf58a60fd8"},
    {"name": "headline_Scenario_FindingLove",
     "path": r"InGame\UI\Icons\Scenarios\headline_Scenario_FindingLove.png",
     "key": "2f7d0004:00000000:ce00a95044b88874"},
    {"name": "headline_Scenario_LivingWithEnemies",
     "path": r"InGame\UI\Icons\Scenarios\headline_Scenario_LivingWithEnemies.png",
     "key": "2f7d0004:00000000:4484360cad40dc72"},
    {"name": "headline_Scenario_MakingMoney",
     "path": r"InGame\UI\Icons\Scenarios\headline_Scenario_MakingMoney.png",
     "key": "2f7d0004:00000000:77ce7849101ff60a"},
    {"name": "headline_Scenario_TooManyToddlers",
     "path": r"InGame\UI\Icons\Scenarios\headline_Scenario_TooManyToddlers.png",
     "key": "2f7d0004:00000000:9df478041f06b167"},
    {"name": "headline_Scenario_VeryWellRounded",
     "path": r"InGame\UI\Icons\Scenarios\headline_Scenario_VeryWellRounded.png",
     "key": "2f7d0004:00000000:94e6ecdcfbbbf750"},
    {"name": "scenario_ExploreTheNight",
     "path": r"InGame\UI\Icons\Scenarios\scenario_ExploreTheNight.png",
     "key": "2f7d0004:00000000:b2b9d1bed2d0d16a"},
    {"name": "scenario_ExtraterrestrialResearcher",
     "path": r"InGame\UI\Icons\Scenarios\scenario_ExtraterrestrialResearcher.png",
     "key": "2f7d0004:00000000:26a5b050e719b971"},
    {"name": "scenario_InheritanceForIdiots",
     "path": r"InGame\UI\Icons\Scenarios\scenario_InheritanceForIdiots.png",
     "key": "2f7d0004:00000000:c209ade9342b4093"},
    {"name": "scenario_NewInTown",
     "path": r"InGame\UI\Icons\Scenarios\scenario_NewInTown.png",
     "key": "2f7d0004:00000000:1ff161fbc6a13379"},
    {"name": "scenario_NoSkillsNoProblem",
     "path": r"InGame\UI\Icons\Scenarios\scenario_NoSkillsNoProblem.png",
     "key": "2f7d0004:00000000:438ded7d187980f1"},
    {"name": "scenario_ParentingPredicaments",
     "path": r"InGame\UI\Icons\Scenarios\scenario_ParentingPredicaments.png",
     "key": "2f7d0004:00000000:f242941b97797833"},
    {"name": "scenario_PlantSim",
     "path": r"InGame\UI\Icons\Scenarios\scenario_PlantSim.png",
     "key": "2f7d0004:00000000:513c0c7fdeff219e"},
    {"name": "scenario_ProudParent",
     "path": r"InGame\UI\Icons\Scenarios\scenario_ProudParent.png",
     "key": "2f7d0004:00000000:37c1cb3ce92f6a54"},
    {"name": "scenario_RomCom",
     "path": r"InGame\UI\Icons\Scenarios\scenario_RomCom.png",
     "key": "2f7d0004:00000000:8cb8d475ca2dc10b"},
    {"name": "scenario_StuckInTheirShadow",
     "path": r"InGame\UI\Icons\Scenarios\scenario_StuckInTheirShadow.png",
     "key": "2f7d0004:00000000:439a669bfeb161dd"},
    {"name": "scenario_SuperRichSuperVillain",
     "path": r"InGame\UI\Icons\Scenarios\scenario_SuperRichSuperVillain.png",
     "key": "2f7d0004:00000000:5fd292a22b6d6537"},
    {"name": "scenario_TeenCaretaker",
     "path": r"InGame\UI\Icons\Scenarios\scenario_TeenCaretaker.png",
     "key": "2f7d0004:00000000:9b8f8c2557701f4e"},
    {"name": "scenario_Troublemaker",
     "path": r"InGame\UI\Icons\Scenarios\scenario_Troublemaker.png",
     "key": "2f7d0004:00000000:26442fe777902db5"},
    {"name": "scenario_UnluckyChef",
     "path": r"InGame\UI\Icons\Scenarios\scenario_UnluckyChef.png",
     "key": "2f7d0004:00000000:1514e346c9cbafb9"},
    {"name": "scenario_bestFriendsForever",
     "path": r"InGame\UI\Icons\Scenarios\scenario_bestFriendsForever.png",
     "key": "2f7d0004:00000000:0d76ff1edc753990"},
    {"name": "scenario_cookout",
     "path": r"InGame\UI\Icons\Scenarios\scenario_cookout.png",
     "key": "2f7d0004:00000000:77631268c25d1052"},
    {"name": "scenario_retailstress",
     "path": r"InGame\UI\Icons\Scenarios\scenario_retailstress.png",
     "key": "2f7d0004:00000000:66c1f10d512af36b"},
]

DEFAULT_NAME = "headline_Scenario_TooManyToddlers"


class IconError(ValueError):
    pass


def by_name(name):
    for icon in ICONS:
        if icon["name"] == name:
            return icon
    raise IconError("unknown scenario icon {!r} (known: {})".format(
        name, ", ".join(icon["name"] for icon in ICONS)))


def resolve(value):
    """(path, key) for an icon name, or a raw `type:group:instance` key.

    Empty means EA's default card icon. A raw key has no path, which the tuning does not
    need - the game resolves the key - but the path is nice to have in Sims 4 Studio.
    """
    text = (value or "").strip()
    if not text:
        text = DEFAULT_NAME
    if text.count(":") == 2:
        return "", text
    icon = by_name(text)
    if not icon["key"]:
        raise IconError("scenario icon {!r} has no resource key in the list".format(text))
    return icon["path"], icon["key"]
