"""Flexible University - game layer. The rules are in fu_logic.py.

What this mod changes:

Qualifications
  Dropping out no longer throws the Sim's credits away. Earned credits (and the list of
  courses already passed) are put back after EA's dropout, and a Sim who leaves with enough
  credits is recorded as holding a Certificate (one third of the degree) or an Associate
  Degree (two thirds). The records are in
  Mods/HouseRules/data/flexible_university_data.json.

  "Apply for Early Graduation" is added to the phone menu while a Sim is eligible. It asks
  for confirmation, then leaves university without EA's dropout penalty and keeps the
  credits, so the Sim can enroll again later. The cheat `houserules.flexuni.early_exit`
  opens the same dialog and is the fallback for a computer (computers are object tuning, so
  there is no safe script-only menu to add to).

Friday-anchored terms
  DegreeTracker._setup_end_of_term_alarm is replaced when it is planning a fresh term: the
  end is moved to Friday evening (default 19:00). If a term starts too late in the week to
  have `min_term_weekdays` weekdays, it is stretched into the following week instead of
  ending after two or three days. Loaded saves keep the remaining time EA saved, because the
  wrapper passes an explicit time straight through.

Fractional credits
  Before DegreeTracker.complete_term grades the term, this mod works out fractions for each
  passing course's grade and for any extra weekdays in a stretched term. Whole credits are
  added before EA's graduation check, so a bonus can be the credit that graduates the Sim.
  The remainder stays in the data file for the next term.

Cheats:
  houserules.flexuni.status [sim id]       - credits, tier, fraction, settings
  houserules.flexuni.set <setting> <value> - change one setting
  houserules.flexuni.early_exit [sim id]   - the early-graduation dialog
  houserules.flexuni.credentials [sim id]  - every qualification this Sim holds
  houserules.flexuni.schedule [sim id]     - the Friday plan for a term starting today
"""
import services
import sims4.commands
import sims4.resources
from date_and_time import create_time_span
from server_commands.argument_helpers import (OptionalSimInfoParam, OptionalTargetParam,
                                              get_optional_target)

import fu_log
import fu_state
from fu_logic import (ASSOCIATE, CERTIFICATE, DEGREE, add_fractions, better_credential,
                      credit_threshold, credential, early_exit_text, extension_credit_bonus,
                      grade_credit_bonus, plan_friday_end, qualification_tier, term_description,
                      tier_label, weekdays_in_term)
from fu_settings import DEFAULT_SETTINGS

try:
    from sims.university.degree_tracker import DegreeTracker
    from sims.university.university_enums import EnrollmentStatus, Grade
    _HAS_UNIVERSITY = True
except Exception:
    DegreeTracker = None
    EnrollmentStatus = None
    Grade = None
    _HAS_UNIVERSITY = False

# s= in tuning/EarlyGraduation.xml
EARLY_EXIT_AFFORDANCE_ID = 15053560015243968642

_installed = False


def _setting(key):
    return fu_state.setting(key)


def _tracker(sim_info):
    try:
        return getattr(sim_info, "degree_tracker", None)
    except Exception:
        return None


def _required(tracker):
    try:
        return int(tracker.CREDITS_REQUIRED)
    except Exception:
        return 14


def _credits(tracker):
    try:
        return int(tracker.current_credits or 0)
    except Exception:
        return 0


def _major_name(tracker):
    major = getattr(tracker, "_current_major", None)
    return getattr(major, "__name__", None)


def _university_name(tracker):
    university = getattr(tracker, "_current_university", None)
    return getattr(university, "__name__", None)


def _eligibility(tracker):
    """(ok, reason, tier, credits, required). Everything the dialog and phone need."""
    if not _setting("enabled") or not _setting("early_exit"):
        return False, "Flexible University's early exit is off", None, 0, 0
    if tracker is None:
        return False, "This Sim has no university degree tracker", None, 0, 0
    credits = _credits(tracker)
    required = _required(tracker)
    tier = qualification_tier(credits, required, float(_setting("certificate_fraction")),
                              float(_setting("associate_fraction")))
    if getattr(tracker, "_current_major", None) is None:
        return False, "This Sim is not enrolled in a degree", tier, credits, required
    if tier is None:
        return False, "{} of {} credits - a Certificate needs {}".format(
            credits, required,
            credit_threshold(required, float(_setting("certificate_fraction")))), \
            tier, credits, required
    if tier == DEGREE:
        return False, "This Sim has enough credits for the full degree - let the term finish", \
            tier, credits, required
    return True, "Ready to leave with {}".format(tier_label(tier)), tier, credits, required


# --- Friday-anchored terms --------------------------------------------------------------
def _setup_end_of_term_alarm(self, time_till_end_term=None):
    """Replace DegreeTracker's own end-of-term alarm with a Friday-evening one.

    An explicit time means a saved term being restored, so it is left exactly as EA saved it;
    shortening or moving a save's last days would be worse than a mid-week finish.
    """
    original = _setup_end_of_term_alarm._original
    if time_till_end_term is not None or not _setting("enabled") \
            or not _setting("friday_schedule"):
        return original(self, time_till_end_term)
    try:
        now = services.time_service().sim_now
        start = self._term_started_time
        if start is None:
            start = now
        plan = plan_friday_end(start.day(), int(_setting("min_term_weekdays")))
        end_hour = max(0, min(23, int(_setting("friday_end_hour"))))
        minutes = end_hour * 60 - (start.hour() * 60 + start.minute())
        end = start + create_time_span(days=plan["days"], minutes=minutes)
        span = end - now
        if span.in_ticks() <= 0:
            # The clock moved past the planned end while the term was being set up. Give it a
            # full extra week rather than setting an alarm in the past.
            span = end + create_time_span(days=7) - now
        fu_log.log("term plan for {}: {} (start day {}, now {})".format(
            fu_state.sim_name(self._sim_info), term_description(plan, end_hour),
            start.day(), now.day()))
        return original(self, time_till_end_term=span)
    except Exception:
        fu_log.log_exception("planning the end of term")
        return original(self, time_till_end_term)


# --- Fractional credits -----------------------------------------------------------------
def _extra_weekdays(tracker):
    """Extra weekdays in this term, from the actual start and end times."""
    start = getattr(tracker, "_term_started_time", None)
    handle = getattr(tracker, "_end_of_term_handle", None)
    if start is None or handle is None:
        return 0
    try:
        end = handle.finishing_time
        days = int((end - start).in_days())
    except Exception:
        return 0
    return max(0, weekdays_in_term(start.day(), days) - int(_setting("min_term_weekdays")))


def _grade_of(tracker, career_guid, course_info):
    grade = getattr(course_info, "final_grade", None)
    if grade is None or grade == Grade.UNKNOWN:
        grade = tracker.get_grade(tracker.get_grade_performance(career_guid))
    return grade


def _apply_credit_bonus(tracker):
    """Add whole credits earned from fractions before EA grades the term.

    Returns (whole credits added, new fraction). The fraction is saved by _complete_term
    after EA's own grading, so a crash between the two keeps the fraction rather than losing
    it (the added whole credits are part of the save either way).
    """
    if not _setting("enabled") or not _setting("fractional_credits"):
        return 0, fu_state.fraction(tracker._sim_info.id)
    sim_info = tracker._sim_info
    if not getattr(sim_info, "is_selectable", False):
        return 0, fu_state.fraction(sim_info.id)
    bonuses = []
    passed = 0
    for career_guid, course_info in list(getattr(tracker, "_course_infos", {}).items()):
        try:
            grade = _grade_of(tracker, career_guid, course_info)
            gp = tracker.GRADE_INFO[grade].gp_value
            if gp < tracker.COURSE_GRADE_FAIL_THRESHOLD:
                continue
            passed += 1
            bonuses.append(grade_credit_bonus(
                gp,
                float(_setting("grade_bonus_high_threshold")), float(_setting("grade_bonus_high")),
                float(_setting("grade_bonus_mid_threshold")), float(_setting("grade_bonus_mid")),
                float(_setting("grade_bonus_low_threshold")), float(_setting("grade_bonus_low"))))
        except Exception:
            fu_log.log_exception("grading a course for fractional credits")
    extra = _extra_weekdays(tracker) if _setting("friday_schedule") and passed else 0
    if extra:
        bonuses.append(extension_credit_bonus(
            extra, float(_setting("extension_credit_per_weekday")),
            float(_setting("extension_credit_cap"))))
    sim_id = sim_info.id
    banked = fu_state.fraction(sim_id)
    whole, remainder = add_fractions(banked, bonuses)
    if whole:
        tracker._current_credits += whole
    if bonuses:
        fu_log.log("{}: bonuses {} + banked {} -> {} whole credit(s), {} kept (extra weekdays {})"
                   .format(fu_state.sim_name(sim_info), [round(b, 2) for b in bonuses],
                           round(banked, 2), whole, remainder, extra))
    return whole, remainder


def _complete_term(self):
    bonus = 0
    remainder = None
    try:
        bonus, remainder = _apply_credit_bonus(self)
    except Exception:
        fu_log.log_exception("adding fractional credits")
    try:
        result = _complete_term._original(self)
    finally:
        if remainder is not None and getattr(self, "_enrollment_status", None) \
                != EnrollmentStatus.GRADUATED:
            try:
                fu_state.set_fraction(self._sim_info.id, remainder)
            except Exception:
                fu_log.log_exception("saving the fractional credit remainder")
    try:
        if bonus and getattr(self._sim_info, "is_selectable", False):
            fu_state.notify(
                "Flexible University",
                "{} extra credit{} from grades and the term's extra days. {} of {} credits now."
                .format(bonus, "" if bonus == 1 else "s", _credits(self), _required(self)),
                self._sim_info)
    except Exception:
        fu_log.log_exception("showing the credit notification")
    return result


# --- Leave with a qualification ---------------------------------------------------------
def _record_credential(sim_info, tier, major, university, credits, required, sim_day=None):
    if tier not in (CERTIFICATE, ASSOCIATE, DEGREE) or not major:
        return None
    entry = credential(tier, major, university, credits, required,
                       _sim_day() if sim_day is None else sim_day)
    old = fu_state.credential_for(sim_info.id, major)
    chosen = better_credential(old, entry)
    fu_state.set_credential(sim_info.id, major, chosen)
    fu_log.log("{} holds {} in {} ({} credits)".format(
        fu_state.sim_name(sim_info), chosen.get("label"), major, chosen.get("credits")))
    return chosen


def _sim_day():
    try:
        return int(services.time_service().sim_now.absolute_days())
    except Exception:
        return None


def _snapshot(tracker):
    return {
        "credits": _credits(tracker),
        "courses": list(getattr(tracker, "_previous_courses", ()) or ()),
        "major": _major_name(tracker),
        "university": _university_name(tracker),
    }


def _leave_with_credential(tracker, snapshot):
    """Leave university like dropout, but without the penalty and without clearing credits.

    EA's dropout clears the credits and passed courses; this keeps both so a later enrollment
    starts where it left off. The public status setter is used for its caches/career refresh.
    """
    sim_info = tracker._sim_info
    tracker._remove_degree_info_slot()
    tracker.drop_enrolled_courses()
    tracker.set_enrollment_status(EnrollmentStatus.NONE)
    tracker._current_university = None
    tracker._current_major = None
    tracker._current_credits = snapshot["credits"]
    tracker._previous_courses[:] = snapshot["courses"]
    tracker.remove_sim_knowlege()
    tracker._reset_term_alarm()
    tracker.clear_scholarships()
    tracker.is_immune_to_kickout = False
    tracker._show_reenrollment_dialog_on_spin_up = False
    tracker._show_reenrollment_dialog_on_next_turn = False
    return sim_info


def _do_early_exit(sim_info):
    tracker = _tracker(sim_info)
    ok, reason, tier, credits, required = _eligibility(tracker)
    if not ok:
        fu_log.log("early exit refused for {}: {}".format(fu_state.sim_name(sim_info), reason))
        fu_state.notify("Early graduation", reason, sim_info)
        return False
    snapshot = _snapshot(tracker)
    _record_credential(sim_info, tier, snapshot["major"], snapshot["university"],
                       credits, required)
    _leave_with_credential(tracker, snapshot)
    text = early_exit_text(tier, credits, required, snapshot["major"])
    fu_log.log("{} left university: {}".format(fu_state.sim_name(sim_info), text))
    fu_state.notify("Early graduation", text, sim_info)
    return True


def _dropout(self):
    snapshot = _snapshot(self)
    try:
        return _dropout._original(self)
    finally:
        try:
            if _setting("enabled") and _setting("preserve_credits") \
                    and getattr(self._sim_info, "is_selectable", False):
                self._current_credits = snapshot["credits"]
                self._previous_courses[:] = snapshot["courses"]
        except Exception:
            fu_log.log_exception("preserving credits after dropout")
        try:
            if _setting("enabled") and _setting("early_exit") \
                    and getattr(self._sim_info, "is_selectable", False):
                tier = qualification_tier(snapshot["credits"], _required(self),
                                          float(_setting("certificate_fraction")),
                                          float(_setting("associate_fraction")))
                if tier in (CERTIFICATE, ASSOCIATE):
                    chosen = _record_credential(
                        self._sim_info, tier, snapshot["major"], snapshot["university"],
                        snapshot["credits"], _required(self))
                    if chosen and getattr(self._sim_info, "is_selectable", False):
                        fu_state.notify(
                            "Flexible University",
                            "{} kept {} credits and was awarded {}".format(
                                fu_state.sim_name(self._sim_info), snapshot["credits"],
                                chosen.get("label")),
                            self._sim_info)
                elif snapshot["credits"] and getattr(self._sim_info, "is_selectable", False):
                    fu_state.notify(
                        "Flexible University",
                        "{} kept {} credits and can enroll again when ready.".format(
                            fu_state.sim_name(self._sim_info), snapshot["credits"]),
                        self._sim_info)
        except Exception:
            fu_log.log_exception("awarding a qualification after dropout")


def _graduate(self, gpa=None):
    snapshot = _snapshot(self)
    required = _required(self)
    result = _graduate._original(self, gpa)
    try:
        if _setting("enabled"):
            fu_state.clear_fraction(self._sim_info.id)
            if getattr(self._sim_info, "is_selectable", False):
                _record_credential(self._sim_info, DEGREE, snapshot["major"],
                                   snapshot["university"], required, required)
    except Exception:
        fu_log.log_exception("recording the full degree")
    return result


# --- Phone entry ------------------------------------------------------------------------
def _wrap_phone():
    from sims.sim import Sim
    original = Sim.potential_phone_interactions
    if getattr(original, "_fu_wrapped", False):
        return

    def potential_phone_interactions(self, context, **kwargs):
        yield from original(self, context, **kwargs)
        try:
            sim_info = getattr(self, "sim_info", None)
            if sim_info is None or not getattr(sim_info, "is_selectable", False):
                return
            ok, _, _, _, _ = _eligibility(_tracker(sim_info))
            if not ok:
                return
            affordance = services.get_instance_manager(
                sims4.resources.Types.INTERACTION).get(EARLY_EXIT_AFFORDANCE_ID)
            if affordance is None:
                fu_log.log("phone: Early Graduation tuning not loaded "
                           "(is HouseRules_flexible-university.package installed?)")
                return
            yield from affordance.potential_interactions(self, context, **kwargs)
        except Exception:
            fu_log.log_exception("adding Early Graduation to the phone")

    potential_phone_interactions._fu_wrapped = True
    Sim.potential_phone_interactions = potential_phone_interactions


# --- Dialog -----------------------------------------------------------------------------
def _on_early_exit_response(sim_info, dialog):
    try:
        if getattr(dialog, "accepted", False):
            _do_early_exit(sim_info)
    except Exception:
        fu_log.log_exception("handling the early-graduation confirmation")


def _show_early_exit_dialog(sim_info):
    tracker = _tracker(sim_info)
    ok, reason, tier, credits, required = _eligibility(tracker)
    if not ok:
        fu_state.notify("Early graduation", reason, sim_info)
        return
    try:
        from sims4.localization import LocalizationHelperTuning
        from ui.ui_dialog import UiDialogOkCancel
    except Exception:
        fu_log.log_exception("importing the early-graduation dialog")
        fu_state.notify(
            "Early graduation",
            "Could not open the confirmation dialog. Use houserules.flexuni.early_exit.",
            sim_info)
        return
    text = "Leave university now with {}? {}".format(
        tier_label(tier), early_exit_text(tier, credits, required, _major_name(tracker)))
    try:
        dialog = UiDialogOkCancel.TunableFactory().default(
            sim_info,
            title=lambda *_, **__: LocalizationHelperTuning.get_raw_text("Early graduation"),
            text=lambda *_, **__: LocalizationHelperTuning.get_raw_text(text))
        dialog.show_dialog(on_response=lambda d: _on_early_exit_response(sim_info, d))
    except Exception:
        fu_log.log_exception("showing the early-graduation dialog")
        fu_state.notify(
            "Early graduation",
            "Could not open the confirmation dialog. Use houserules.flexuni.early_exit.",
            sim_info)


# --- Cheats -----------------------------------------------------------------------------
@sims4.commands.Command("houserules.flexuni.status",
                        command_type=sims4.commands.CommandType.Live)
def flexuni_status(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = get_optional_target(opt_sim, _connection, target_type=OptionalSimInfoParam) \
        or services.active_sim_info()
    output("Flexible University settings: {}".format(
        ", ".join("{}={}".format(k, fu_state.setting(k)) for k in sorted(DEFAULT_SETTINGS))))
    if sim_info is None:
        output("No Sim: pass a sim id or select one.")
        return
    tracker = _tracker(sim_info)
    if tracker is None:
        output("{}: no degree tracker (is Discover University installed?)".format(
            fu_state.sim_name(sim_info)))
        return
    credits, required = _credits(tracker), _required(tracker)
    tier = qualification_tier(credits, required, float(_setting("certificate_fraction")),
                              float(_setting("associate_fraction")))
    output("{}: {} of {} credits -> {}; banked fraction {}; major {}".format(
        fu_state.sim_name(sim_info), credits, required, tier_label(tier) if tier else "none",
        fu_state.fraction(sim_info.id), _major_name(tracker) or "none"))
    plan = plan_friday_end(services.time_service().sim_now.day(),
                           int(_setting("min_term_weekdays")))
    output("If a term started today: {} (extra weekday credits cap {})".format(
        term_description(plan, max(0, min(23, int(_setting("friday_end_hour"))))),
        _setting("extension_credit_cap")))


@sims4.commands.Command("houserules.flexuni.set", command_type=sims4.commands.CommandType.Live)
def flexuni_set(key: str = "", value: str = "", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    if not key:
        for name in sorted(DEFAULT_SETTINGS):
            output("{} = {}".format(name, fu_state.setting(name)))
        return
    try:
        fu_state.settings.set(key, value)
        fu_state.save_settings()
        fu_log.log("setting {} = {}".format(key, fu_state.setting(key)))
        output("{} = {}".format(key, fu_state.setting(key)))
    except KeyError:
        output("Unknown setting {}. Use houserules.flexuni.status for the list.".format(key))
    except Exception:
        fu_log.log_exception("setting {}".format(key))
        output("Could not set {} to {}. on/off or a number, please.".format(key, value))


@sims4.commands.Command("houserules.flexuni.early_exit",
                        command_type=sims4.commands.CommandType.Live)
def flexuni_early_exit(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = get_optional_target(opt_sim, _connection, target_type=OptionalSimInfoParam) \
        or services.active_sim_info()
    if sim_info is None:
        output("No Sim: pass a sim id or select one.")
        return
    ok, reason, _, _, _ = _eligibility(_tracker(sim_info))
    if not ok:
        output("{}: {}".format(fu_state.sim_name(sim_info), reason))
        return
    _show_early_exit_dialog(sim_info)


@sims4.commands.Command("houserules.flexuni.early_exit_phone",
                        command_type=sims4.commands.CommandType.Live)
def flexuni_early_exit_phone(opt_sim: OptionalTargetParam = None, _interaction_id: float = None,
                             _connection=None):
    """Run by the phone's "Apply for Early Graduation" with the Sim's id."""
    try:
        sim = get_optional_target(opt_sim, _connection)
        sim_info = getattr(sim, "sim_info", sim) or services.active_sim_info()
        if sim_info is None:
            return
        fu_log.log("phone: Early Graduation for {}".format(fu_state.sim_name(sim_info)))
        _show_early_exit_dialog(sim_info)
    except Exception:
        fu_log.log_exception("flexuni.early_exit_phone")


@sims4.commands.Command("houserules.flexuni.credentials",
                        command_type=sims4.commands.CommandType.Live)
def flexuni_credentials(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = get_optional_target(opt_sim, _connection, target_type=OptionalSimInfoParam) \
        or services.active_sim_info()
    if sim_info is None:
        output("No Sim: pass a sim id or select one.")
        return
    records = fu_state.credentials(sim_info.id)
    if not records:
        output("{}: no qualifications yet.".format(fu_state.sim_name(sim_info)))
        return
    for major, entry in sorted(records.items()):
        output("{}: {} in {} ({} of {} credits, day {})".format(
            fu_state.sim_name(sim_info), entry.get("label"), major, entry.get("credits"),
            entry.get("required"), entry.get("day")))


@sims4.commands.Command("houserules.flexuni.schedule",
                        command_type=sims4.commands.CommandType.Live)
def flexuni_schedule(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = get_optional_target(opt_sim, _connection, target_type=OptionalSimInfoParam) \
        or services.active_sim_info()
    now = services.time_service().sim_now
    plan = plan_friday_end(now.day(), int(_setting("min_term_weekdays")))
    output("Now: day {} {:02d}:{:02d}. A term starting today would be: {}".format(
        now.day(), now.hour(), now.minute(),
        term_description(plan, max(0, min(23, int(_setting("friday_end_hour")))))))
    tracker = _tracker(sim_info) if sim_info is not None else None
    if tracker is not None and getattr(tracker, "_end_of_term_handle", None) is not None:
        handle = tracker._end_of_term_handle
        end = handle.finishing_time
        days = int(round(handle.get_remaining_time().in_days()))
        output("{}: current term ends day {} (Friday = 5) at {:02d}:{:02d}, about {} day(s) from now."
               .format(fu_state.sim_name(sim_info), end.day(), end.hour(), end.minute(), days))


# --- Install ----------------------------------------------------------------------------
def _install():
    global _installed
    if _installed:
        return
    _installed = True
    if not _HAS_UNIVERSITY:
        fu_log.log("Discover University is not installed; Flexible University is inactive")
        return
    for name, replacement in (
            ("_setup_end_of_term_alarm", _setup_end_of_term_alarm),
            ("complete_term", _complete_term),
            ("dropout", _dropout),
            ("graduate", _graduate)):
        try:
            original = getattr(DegreeTracker, name)
            if getattr(original, "_fu_wrapped", False):
                continue
            replacement._original = original
            replacement._fu_wrapped = True
            setattr(DegreeTracker, name, replacement)
        except Exception:
            fu_log.log_exception("installing the {} hook".format(name))
    try:
        _wrap_phone()
    except Exception:
        fu_log.log_exception("installing the phone hook")
    fu_log.log("loaded (university discovered: {})".format(_HAS_UNIVERSITY))


_install()
