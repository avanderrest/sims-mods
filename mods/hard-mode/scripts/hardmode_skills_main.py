"""Hard Mode: skill aptitude - game layer. The rules are in hardmode_skills.py.

Skill gain is continuous: while a sim practises, the skill's value rises at
  rate = (sum of the interaction's gain modifiers) x (multipliers from moods, buffs, traits)
which EA computes in ContinuousStatistic._get_change_rate_without_decay. One-off gains
(BaseStatistic.add_value) use get_statistic_multiplier_increase(). We override both on the
Skill class only: the multiplier is damped (moods help less) and our aptitude factor applied.
Child/toddler skills only get the damping; aptitude is for adult skills.

Cheat: bluerabbit477.hard.skills [sim] - the sim's talents, trait affinities and current factors.
"""
import sims4.commands
from server_commands.argument_helpers import OptionalSimInfoParam, get_optional_target
from statistics.skill import Skill

import hardmode_log
import hardmode_state
from hardmode_skills import TALENT_POOL, TRAIT_SKILLS, aptitude_multiplier, damp_boost, talents_for

_KNOWN = {s.lower(): s for s in TALENT_POOL}
for _skills in TRAIT_SKILLS.values():
    for _s in _skills:
        _KNOWN.setdefault(_s.lower(), _s)


def _skill_short_name(skill_cls):
    """statistic_Skill_AdultMajor_Logic -> 'Logic' (only for adult skills we know)."""
    name = skill_cls.__name__
    if "adult" not in name.lower():
        return None
    return _KNOWN.get(name.rsplit("_", 1)[-1].lower())


def _trait_names(sim_info):
    try:
        return [t.__name__ for t in sim_info.trait_tracker.equipped_traits]
    except Exception:
        return []


def _factor(skill):
    """(damped multiplier part is done by the caller) aptitude factor for this skill instance."""
    tracker = getattr(skill, "_tracker", None)
    sim_info = getattr(tracker, "owner", None) if tracker is not None else None
    if sim_info is None or not getattr(sim_info, "is_sim", False):
        return 1.0
    short = _skill_short_name(type(skill))
    if short is None:
        return 1.0
    level = skill.get_user_value()
    return aptitude_multiplier(short, level, sim_info.sim_id, _trait_names(sim_info))


_original_rate = Skill._get_change_rate_without_decay
_original_increase = Skill.get_statistic_multiplier_increase


def _get_change_rate_without_decay(self):
    try:
        if hardmode_state.setting("skills") and self._statistic_modifier > 0:
            speed = self.get_tick_relative_to_age_speed_multiplier()
            return self._statistic_modifier * damp_boost(self._statistic_multiplier_increase) * speed * _factor(self)
    except Exception:
        hardmode_log.log_exception("skill gain rate")
    return _original_rate(self)


def get_statistic_multiplier_increase(self):
    value = _original_increase(self)
    try:
        if hardmode_state.setting("skills"):
            return damp_boost(value) * _factor(self)
    except Exception:
        hardmode_log.log_exception("skill gain multiplier")
    return value


Skill._get_change_rate_without_decay = _get_change_rate_without_decay
Skill.get_statistic_multiplier_increase = get_statistic_multiplier_increase
hardmode_log.log("skill aptitude hooks installed")


@sims4.commands.Command("bluerabbit477.hard.skills", command_type=sims4.commands.CommandType.Live)
def hard_skills(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = get_optional_target(opt_sim, _connection, target_type=OptionalSimInfoParam)
    if sim_info is None:
        output("No sim found (select one or pass a sim id).")
        return
    try:
        traits = _trait_names(sim_info)
        lines = ["{}: talents {}".format(hardmode_state.sim_name(sim_info), ", ".join(talents_for(sim_info.sim_id)))]
        affinities = sorted({s for t in traits for s in TRAIT_SKILLS.get(t, ())})
        lines.append("trait affinities: {}".format(", ".join(affinities) or "none"))
        skills = []
        for skill in sim_info.all_skills():
            short = _skill_short_name(type(skill))
            if short is None:
                continue
            skills.append("{} {} x{:.2f}".format(short, skill.get_user_value(), _factor(skill)))
        lines.append("skills (level, gain factor): {}".format(", ".join(skills) or "none yet"))
    except Exception:
        hardmode_log.log_exception("hard.skills")
        output("hard.skills failed - see the log.")
        return
    for line in lines:
        output(line)
        hardmode_log.log("hard.skills " + line)
