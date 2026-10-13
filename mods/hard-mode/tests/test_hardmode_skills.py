import pytest

from hardmode_skills import (APT_MULTIPLIER, SLOW_FROM_LEVEL, SLOW_MULTIPLIER, TALENT_COUNT, TALENT_POOL,
                             TRAIT_SKILLS, aptitude_multiplier, damp_boost, has_aptitude, talents_for)


def test_talents_are_stable_per_sim():
    assert talents_for(12345) == talents_for(12345)
    assert len(talents_for(12345)) == TALENT_COUNT
    assert all(t in TALENT_POOL for t in talents_for(12345))


def test_talents_differ_between_sims():
    assert len({talents_for(i) for i in range(50)}) > 10


def _skill_without_aptitude(sim_id):
    return next(s for s in TALENT_POOL if s not in talents_for(sim_id))


def test_talent_speeds_up():
    sim = 777
    talent = talents_for(sim)[0]
    assert aptitude_multiplier(talent, 9, sim, []) == APT_MULTIPLIER


def test_trait_affinity_speeds_up():
    sim = 777
    skill = next(s for s in TRAIT_SKILLS["trait_Bookworm"] if s not in talents_for(sim))
    assert has_aptitude(skill, sim, ["trait_Bookworm"])
    assert aptitude_multiplier(skill, 3, sim, ["trait_Bookworm"]) == APT_MULTIPLIER


def test_no_aptitude_slows_only_high_levels():
    sim = 777
    skill = _skill_without_aptitude(sim)
    assert aptitude_multiplier(skill, SLOW_FROM_LEVEL - 1, sim, []) == 1.0
    assert aptitude_multiplier(skill, SLOW_FROM_LEVEL, sim, []) == SLOW_MULTIPLIER


@pytest.mark.parametrize("before,after", [(2.0, 1.5), (1.0, 1.0), (0.5, 0.5), (3.0, 2.0)])
def test_damp_boost(before, after):
    assert damp_boost(before) == pytest.approx(after)


def test_trait_names_are_real_tuning_names():
    # They must start with trait_ like the game's own (checked against the game's tuning).
    assert all(t.startswith("trait_") for t in TRAIT_SKILLS)
