"""The checks module must import without a game and register the expected suites/actions."""
import selftest_checks


def test_every_suite_is_registered():
    names = selftest_checks.REGISTRY.names()
    for expected in ("env", "hello", "actions", "hardmode", "aspiration", "social",
                     "royalty", "gates", "scenarios", "nsr", "npc"):
        assert expected in names


def test_the_action_suite_keeps_the_end_to_end_checks():
    suite = selftest_checks.REGISTRY.selected("actions")[0]
    descriptions = [description for description, _check in suite.checks]
    assert descriptions == [
        "job pick is refused by Hard Mode",
        "job pick goes through when enforcement is off",
        "sell price drops for a real item",
        "NPC tick runs through its command",
        "noble promotion is refused by Ascent to Royalty",
        "club admission is refused by Social Gates",
        "a real unpaid bill becomes debt",
        "a real job breaks a scenario's no-career rule",
        "relationship gain uses the Social Standing multiplier",
    ]
