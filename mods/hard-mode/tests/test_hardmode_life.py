import pytest

from hardmode_life import (CHILDCARE_PER_CHILD, MOOD_LINGER, RELATIONSHIP_DECAY_MULTIPLIER, childcare_cost,
                           lingering_decay_rate, lingers, relationship_decay, reward_cost)


def test_strong_bad_moods_linger():
    assert lingers("Mood_Sad", 3)
    assert lingers("Mood_Embarrassed", 2)
    assert not lingers("Mood_Sad", 1)        # mild
    assert not lingers("Mood_Happy", 3)      # good moods unchanged
    assert not lingers("Mood_Sad", None)


def test_lingering_timer_runs_slower():
    assert lingering_decay_rate(1.0) == pytest.approx(1.0 / MOOD_LINGER)


@pytest.mark.parametrize("name,changed", [
    ("LTR_Friendship_Main", True), ("LTR_Romance_Main", True),
    ("ShortTerm_Friendship", False), ("LTR_SimToPet_Friendship_Main", True), ("Some_Other_Track", False),
])
def test_relationship_decay(name, changed):
    expected = -1.0 * RELATIONSHIP_DECAY_MULTIPLIER if changed else -1.0
    assert relationship_decay(-1.0, name) == pytest.approx(expected)


def test_childcare_only_when_everyone_works_on_weekdays():
    assert childcare_cost(2, adults=2, adults_working=2, game_day=1) == 2 * CHILDCARE_PER_CHILD
    assert childcare_cost(2, adults=2, adults_working=1, game_day=1) == 0   # someone's home
    assert childcare_cost(2, adults=2, adults_working=2, game_day=0) == 0   # Sunday
    assert childcare_cost(0, adults=2, adults_working=2, game_day=1) == 0
    assert childcare_cost(1, adults=0, adults_working=0, game_day=1) == 0


def test_reward_cost():
    assert reward_cost(1000) == 1500
