"""Hard Mode: life and relationships - game layer. The rules are in hardmode_life.py.

Setting: houserules.hard.set life on|off

Hooks:
- RelationshipTrack.get_decay_rate: friendship/romance tracks fade faster. EA's decay alarms
  are scheduled from this same rate, so they stay consistent.
- Strong bad moodlets: their lifetime is a small timer commodity that counts down at
  `decay_rate` per sim minute. At load we slow that timer for each matching moodlet type
  (only the timers generated for one buff, never shared commodities).
- PregnancyTracker.start_pregnancy: charges prenatal care once a pregnancy really starts.
- A daily check at 9:00 charges childcare on weekdays when every adult works full time.
- SatisfactionTracker.SATISFACTION_STORE_ITEMS: reward store prices go up.
"""
import alarms
import services
from date_and_time import create_date_and_time, create_time_span
from protocolbuffers import Consts_pb2

import hardmode_log
import hardmode_state
from hardmode_life import (PREGNANCY_COST, childcare_cost, lingering_decay_rate, lingers, relationship_decay,
                           reward_cost)


def _on():
    return hardmode_state.setting("life")


def _charge(household, amount, what):
    """Takes the money; whatever they can't pay becomes debt (when the debt module is on)."""
    if amount <= 0 or household is None:
        return
    paid = min(amount, max(0, household.funds.money))
    if paid:
        household.funds.try_remove(paid, Consts_pb2.TELEMETRY_INTERACTION_COST, None)
    short = amount - paid
    if short > 0:
        import hardmode_money_main
        hardmode_money_main.add_debt(household, short, what)
    hardmode_log.log("{}: household {} charged {} (paid {}, to debt {})".format(what, household.id, amount, paid, short))


# --- Relationships fade faster -------------------------------------------------------------
def _wrap_relationship_decay():
    from relationships.relationship_track import RelationshipTrack
    original = RelationshipTrack.get_decay_rate

    def get_decay_rate(self, use_decay_modifier=True):
        rate = original(self, use_decay_modifier=use_decay_modifier)
        try:
            if rate and _on():
                return relationship_decay(rate, type(self).__name__)
        except Exception:
            hardmode_log.log_exception("relationship decay")
        return rate

    RelationshipTrack.get_decay_rate = get_decay_rate


# --- Bad moods linger ----------------------------------------------------------------------
_original_moodlet_rates = {}   # timer commodity class -> its original decay_rate


def _apply_moodlets(enabled):
    from statistics.commodity import RuntimeCommodity
    import sims4.resources
    if enabled and not _original_moodlet_rates:
        count = 0
        for buff in services.get_instance_manager(sims4.resources.Types.BUFF).types.values():
            mood = getattr(buff, "mood_type", None)
            if mood is None or not lingers(mood.__name__, getattr(buff, "mood_weight", 0)):
                continue
            if getattr(buff, "_temporary_commodity_info", None) is None:
                continue
            commodity = buff.commodity
            if commodity is None or not issubclass(commodity, RuntimeCommodity):
                continue
            _original_moodlet_rates[commodity] = commodity.decay_rate
            commodity.decay_rate = lingering_decay_rate(commodity.decay_rate)
            count += 1
        hardmode_log.log("bad moods last longer: {} moodlet types".format(count))
    elif not enabled and _original_moodlet_rates:
        for commodity, rate in _original_moodlet_rates.items():
            commodity.decay_rate = rate
        _original_moodlet_rates.clear()
        hardmode_log.log("moodlet durations restored")


# --- Pregnancy costs money -----------------------------------------------------------------
def _wrap_pregnancy():
    from sims.pregnancy.pregnancy_tracker import PregnancyTracker
    original = PregnancyTracker.start_pregnancy

    def start_pregnancy(self, *args, **kwargs):
        was_pregnant = self.is_pregnant
        result = original(self, *args, **kwargs)
        try:
            sim_info = self._sim_info
            if _on() and not was_pregnant and self.is_pregnant and sim_info.household is not None \
                    and sim_info.household.is_active_household:
                _charge(sim_info.household, PREGNANCY_COST, "prenatal care")
                hardmode_state.notify("Prenatal care", "{} is pregnant. Doctor's visits and baby things cost §{}."
                                      .format(sim_info.first_name, PREGNANCY_COST), sim_info)
        except Exception:
            hardmode_log.log_exception("pregnancy cost")
        return result

    PregnancyTracker.start_pregnancy = start_pregnancy


# --- Childcare -----------------------------------------------------------------------------
_childcare_alarm = None


def _start_childcare_alarm(zone):
    global _childcare_alarm
    if _childcare_alarm is not None:
        alarms.cancel_alarm(_childcare_alarm)
    now = services.time_service().sim_now
    first = now.time_till_next_day_time(create_date_and_time(hours=9), rollover_same_time=True)
    _childcare_alarm = alarms.add_alarm(zone, first, lambda _: _childcare_day(), repeating=True,
                                        repeating_time_span=create_time_span(days=1))


def _childcare_day():
    try:
        if not _on():
            return
        household = services.active_household()
        if household is None:
            return
        from careers.career_enums import CareerCategory
        from sims.sim_info_types import Age
        young = adults = working = 0
        for sim_info in household.sim_info_gen():
            if not sim_info.is_human:
                continue
            if sim_info.age in (Age.BABY, Age.TODDLER) or getattr(Age, "INFANT", None) == sim_info.age:
                young += 1
            elif sim_info.age in (Age.YOUNGADULT, Age.ADULT, Age.ELDER):
                adults += 1
                if any(getattr(c, "career_category", None) == CareerCategory.Work
                       for c in sim_info.career_tracker.careers.values()):
                    working += 1
        cost = childcare_cost(young, adults, working, services.time_service().sim_now.day())
        if cost:
            _charge(household, cost, "childcare")
            hardmode_state.notify("Childcare", "Daycare for {} little one(s) while everyone works: §{}.".format(young, cost))
    except Exception:
        hardmode_log.log_exception("childcare")


# --- Reward store prices -------------------------------------------------------------------
_original_store = None


def _apply_store(enabled):
    global _original_store
    from satisfaction.satisfaction_tracker import SatisfactionTracker
    if enabled and _original_store is None:
        original = SatisfactionTracker.SATISFACTION_STORE_ITEMS
        changed = {}
        for reward, data in original.items():
            try:
                changed[reward] = data.clone_with_overrides(cost=reward_cost(data.cost))
            except Exception:
                changed[reward] = data
        _original_store = original
        SatisfactionTracker.SATISFACTION_STORE_ITEMS = type(original)(changed)
        hardmode_log.log("reward store prices raised for {} items".format(len(changed)))
    elif not enabled and _original_store is not None:
        SatisfactionTracker.SATISFACTION_STORE_ITEMS = _original_store
        _original_store = None
        hardmode_log.log("reward store prices restored")


# --- Install ---------------------------------------------------------------------------------
for _name, _fn in (("relationship decay", _wrap_relationship_decay), ("pregnancy", _wrap_pregnancy)):
    try:
        _fn()
    except Exception:
        hardmode_log.log_exception("installing the {} hook".format(_name))


def on_zone_loaded(zone):
    on = _on()
    for name, fn in (("moodlets", lambda: _apply_moodlets(on)), ("reward store", lambda: _apply_store(on)),
                     ("childcare alarm", lambda: _start_childcare_alarm(zone))):
        try:
            fn()
        except Exception:
            hardmode_log.log_exception(name)


import zone as _zone_module

_original_on_loading_screen_animation_finished = _zone_module.Zone.on_loading_screen_animation_finished


def _patched_on_loading_screen_animation_finished(self, *args, **kwargs):
    result = _original_on_loading_screen_animation_finished(self, *args, **kwargs)
    try:
        on_zone_loaded(self)
    except Exception:
        hardmode_log.log_exception("life: zone load hook")
    return result


_zone_module.Zone.on_loading_screen_animation_finished = _patched_on_loading_screen_animation_finished
hardmode_log.log("life hooks installed")
