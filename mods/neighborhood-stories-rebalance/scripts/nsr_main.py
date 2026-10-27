"""Neighborhood Stories Rebalance - game layer.

Some of the mapping onto EA's code is still unverified for lack of a running game.
Everything here is defensive: a wrong guess should log a line and do
nothing, never break the base game's own on_loading_screen_animation_finished.

Cheats: houserules.nsr.status - prints what the last zone load found/changed.
        houserules.nsr.events - counts of story arcs started/ended (kept across sessions).
        houserules.nsr.events_reset - start the counts again.
"""
import random

import sims4.commands
import services
import zone as zone_module
from careers.career_enums import CareerCategory
from event_testing.resolver import SingleSimResolver
from interactions import ParticipantTypeSavedStoryProgressionSim
from relationships.relationship_enums import RelationshipType
from relationships.relationship_track import RelationshipTrack
from sims.aging.aging_mixin import AgingMixin
from sims.household_enums import HouseholdChangeOrigin
from sims.sim_info_types import Age
from sims.university.university_enums import UniversityHousingKickOutReason
from sims.university.university_housing_tuning import UniversityHousingTuning
from sims.university.university_tuning import University
from sims4.resources import Types
from story_progression.story_progression_actions.story_progression_action_family import (
    AddFamilyMemberStoryProgressionAction,
    MakePregnantStoryProgressionAction,
)
from story_progression.story_progression_actions.story_progression_action_moving import (
    MoveOutStoryProgressionAction,
)
from story_progression.story_progression_actions.story_progression_action_relationship import (
    RelationshipModifiedStoryProgressionAction,
)
from story_progression.story_progression_service import StoryProgressionService
from story_progression.story_progression_result import (
    StoryProgressionResult,
    StoryProgressionResultType,
)

import nsr_life
import nsr_log
from nsr_classify import classify_arc, adjust_weight

_last_summary = []  # filled in by _apply_rebalance(); read by the status cheat
_last_careers = []  # filled in by _maybe_assign_career(); read by the careers cheat
_last_splits = []  # filled in by _maybe_split_household(); read by the splits cheat
_last_university = []  # filled in by _maybe_enroll_in_university(); read by the university cheat
_last_graduates = []  # filled in by _maybe_graduate_from_university(); read by the graduates cheat
_last_romances = []  # filled in by the daily relationship step
_last_move_ins = []  # filled in by the daily move-in-together step
_last_children = []  # filled in by the daily couple child step
_applied_already = False  # guards against re-multiplying weights on every zone load


def _apply_rebalance():
    global _applied_already, _last_summary
    if _applied_already:
        nsr_log.log("skip: already applied this game session")
        return
    _applied_already = True  # set before doing the work, so a crash still prevents a retry loop

    summary = []
    service_cls = services.get_story_progression_service
    story_service = service_cls() if callable(service_cls) else None
    if story_service is None:
        nsr_log.log("could not get the story progression service; nothing changed")
        _last_summary = summary
        return

    passes = getattr(type(story_service), "STORY_PROGRESSION_PASSES", None)
    if not passes:
        nsr_log.log("STORY_PROGRESSION_PASSES was empty or missing; nothing changed")
        _last_summary = summary
        return

    # Tuned tuples are ImmutableSlots (assigning raises TypeError) and tuned lists are tuples,
    # so build changed copies with clone_with_overrides and swap the whole class attribute.
    # The service reads self.STORY_PROGRESSION_PASSES at the start of every seeding pass.
    new_passes = []
    for pass_data in passes:
        new_entries = []
        for arc_entry in getattr(pass_data, "potential_arcs", ()):
            story_arc = getattr(arc_entry, "story_arc", None)
            original_weight = getattr(arc_entry, "weight", None)
            arc_name = getattr(story_arc, "__name__", str(story_arc))
            if story_arc is None or original_weight is None:
                new_entries.append(arc_entry)
                continue
            # Classified by tuning name. Reading the arc's chapter actions instead failed in
            # the first in-game test: _initial_story_chapter is a class, and calling it builds
            # a chapter (TypeError: missing 'arc').
            category = classify_arc(arc_name)
            new_weight = adjust_weight(original_weight, category)
            new_entries.append(arc_entry.clone_with_overrides(weight=new_weight))
            summary.append({"arc": arc_name, "category": category,
                            "old_weight": original_weight, "new_weight": new_weight})
        new_passes.append(pass_data.clone_with_overrides(potential_arcs=tuple(new_entries)))

    try:
        type(story_service).STORY_PROGRESSION_PASSES = tuple(new_passes)
        applied = True
    except Exception:
        nsr_log.log_exception("replacing STORY_PROGRESSION_PASSES")
        applied = False
    for s in summary:
        s["applied"] = applied
        if not applied:
            s["new_weight"] = s["old_weight"]

    _last_summary = summary
    changed = sum(1 for s in summary if s.get("applied") and s["new_weight"] != s["old_weight"])
    nsr_log.log("checked {} story arcs; changed {} weights".format(len(summary), changed))
    for s in summary:
        nsr_log.log("  {arc}: category={category} old={old_weight} new={new_weight} applied={applied}".format(**s))


# --- Age-up careers: give a Neighborhood Stories household's new young adult a job ---------
# EA's own CareerAdd pass is a periodic, weighted-random event. This adds the missing
# age-up trigger and biases the choice towards what the sim is actually good at. It only
# runs for non-player households whose Neighborhood Stories rules allow CareerAdd.
_CAREER_ADD_ARC = "simStoryArc_CareerAdd"


def _find_story_arc(name):
    service_cls = services.get_story_progression_service
    story_service = service_cls() if callable(service_cls) else None
    passes = getattr(type(story_service), "STORY_PROGRESSION_PASSES", None) if story_service else None
    for pass_data in passes or ():
        for entry in getattr(pass_data, "potential_arcs", ()):
            arc = getattr(entry, "story_arc", None)
            if getattr(arc, "__name__", "") == name:
                return arc
    return None


def _story_progression_enabled(household):
    rule_set = getattr(household, "story_progression_rule_set", None)
    return bool(rule_set is not None and getattr(rule_set, "enabled", False))


def _story_progression_allows(household, arc):
    rule_set = getattr(household, "story_progression_rule_set", None)
    if rule_set is None:
        return False
    try:
        return bool(rule_set.verify(getattr(arc, "required_rules", None)))
    except Exception:
        return False


def _is_horse_adoption_action(action):
    arc = getattr(action, "_owner_arc", None)
    arc_name = type(arc).__name__ if arc is not None else ""
    if "horse" in arc_name.lower():
        return True
    template = getattr(action, "template", None)
    return "horse" in getattr(template, "__name__", "").lower()


def _horse_household_conditions(household):
    width = height = 0
    zone_id = getattr(household, "home_zone_id", 0)
    if zone_id:
        try:
            zone = services.get_zone(zone_id, allow_uninstantiated_zones=True)
            lot = getattr(zone, "lot", None)
            width = getattr(lot, "size_x", 0) or 0
            height = getattr(lot, "size_z", 0) or 0
        except Exception:
            pass
    funds = getattr(getattr(household, "funds", None), "money", 0) or 0
    return width, height, funds


_original_family_member_setup = AddFamilyMemberStoryProgressionAction.setup_story_progression_action


def _patched_family_member_setup(self, **kwargs):
    try:
        if _is_horse_adoption_action(self):
            sim_info = getattr(getattr(self, "_owner_arc", None), "sim_info", None)
            household = getattr(sim_info, "household", None)
            if household is None:
                return StoryProgressionResult(
                    StoryProgressionResultType.FAILED_TESTS,
                    "Horse adoption needs a Neighborhood Stories household.")
            if not _story_progression_enabled(household):
                nsr_log.log("horse adoption blocked for {}: story progression is off".format(
                    getattr(sim_info, "full_name", "sim")))
                return StoryProgressionResult(
                    StoryProgressionResultType.FAILED_TESTS,
                    "Horse adoption needs Neighborhood Stories to be on.")
            owner_arc = getattr(self, "_owner_arc", None)
            if not _story_progression_allows(household, owner_arc):
                nsr_log.log("horse adoption blocked for {}: the household's horse rule is off".format(
                    getattr(sim_info, "full_name", "sim")))
                return StoryProgressionResult(
                    StoryProgressionResultType.FAILED_TESTS,
                    "Horse adoption is disabled for this household.")
            width, height, funds = _horse_household_conditions(household)
            roll = random.random()
            if not nsr_life.should_allow_horse_adoption(width, height, funds, roll):
                nsr_log.log("horse adoption blocked for {}: lot {}x{} ({} tiles), "
                            "funds {}, roll {:.3f}".format(
                                getattr(sim_info, "full_name", "sim"), width, height,
                                width * height, funds, roll))
                return StoryProgressionResult(
                    StoryProgressionResultType.FAILED_TESTS,
                    "Horse adoption needs a large lot and high household funds.")
    except Exception:
        nsr_log.log_exception("horse adoption gate")
    return _original_family_member_setup(self, **kwargs)


AddFamilyMemberStoryProgressionAction.setup_story_progression_action = _patched_family_member_setup


def _has_romantic_relationship(sim_info):
    if getattr(sim_info, "spouse_sim_id", None) or getattr(sim_info, "fiance_sim_id", None):
        return True
    romance_track = getattr(RelationshipTrack, "ROMANCE_TRACK", None)
    tracker = getattr(sim_info, "relationship_tracker", None)
    if romance_track is None or tracker is None:
        return False
    threshold = getattr(RelationshipTrack, "ROMANCE_TRACK_FILTER_THRESHOLD", 1)
    try:
        threshold = float(threshold)
    except Exception:
        threshold = 1.0
    try:
        for relationship in tracker:
            try:
                score = relationship.get_track_score(sim_info.sim_id, romance_track)
            except Exception:
                score = 0
            if score is not None and score >= threshold:
                return True
    except Exception:
        pass
    return False


def _household_is_lone_childless_adult(household):
    """True for exactly one adult with no children and no romantic relationship."""
    try:
        members = list(household)
    except Exception:
        return False
    if len(members) != 1:
        return False
    sim_info = members[0]
    age = getattr(sim_info, "age", None)
    if age is not None and age <= Age.TEEN:
        return False
    return not _has_romantic_relationship(sim_info)


_SIGNIFICANT_OTHER_BIT = None
_MOVE_IN_ARC = "householdStoryArc_MoveIn"


def _significant_other_bit():
    global _SIGNIFICANT_OTHER_BIT
    if _SIGNIFICANT_OTHER_BIT is not None:
        return _SIGNIFICANT_OTHER_BIT
    try:
        manager = services.get_instance_manager(Types.RELATIONSHIP_BIT)
        for bit in manager.types.values():
            if getattr(bit, "__name__", "") == "romantic-Significant_Other":
                _SIGNIFICANT_OTHER_BIT = bit
                break
        if _SIGNIFICANT_OTHER_BIT is None:
            _SIGNIFICANT_OTHER_BIT = manager.get(15825)
    except Exception:
        pass
    return _SIGNIFICANT_OTHER_BIT


def _has_romance_with(sim_info, other_id):
    if getattr(sim_info, "spouse_sim_id", None) == other_id:
        return True
    if getattr(sim_info, "fiance_sim_id", None) == other_id:
        return True
    bit = _significant_other_bit()
    if bit is None:
        return False
    try:
        return bool(sim_info.relationship_tracker.has_bit(other_id, bit))
    except Exception:
        return False


def _has_romance_with_other(sim_info, other_id):
    """True if the sim is married/engaged/dating someone other than other_id."""
    spouse = getattr(sim_info, "spouse_sim_id", None)
    fiance = getattr(sim_info, "fiance_sim_id", None)
    if spouse and spouse != other_id:
        return True
    if fiance and fiance != other_id:
        return True
    bit = _significant_other_bit()
    romance_track = getattr(RelationshipTrack, "ROMANCE_TRACK", None)
    threshold = getattr(RelationshipTrack, "ROMANCE_TRACK_FILTER_THRESHOLD", 1)
    try:
        threshold = float(threshold)
    except Exception:
        threshold = 1.0
    tracker = getattr(sim_info, "relationship_tracker", None)
    if tracker is None:
        return False
    try:
        for relationship in tracker:
            target_id = relationship.get_other_sim_id(sim_info.sim_id)
            if target_id == other_id:
                continue
            if bit is not None and tracker.has_bit(target_id, bit):
                return True
            if romance_track is not None:
                try:
                    if relationship.get_track_score(sim_info.sim_id, romance_track) >= threshold:
                        return True
                except Exception:
                    pass
    except Exception:
        pass
    return False


def _compatibility_level_name(sim_info_a, sim_info_b, relationship):
    try:
        level = relationship.get_compatibility_level()
        if level is not None:
            return getattr(level, "name", str(level))
    except Exception:
        pass
    return nsr_life.simple_compatibility(
        _trait_names(sim_info_a), _trait_names(sim_info_b))


def _find_relationship(sim_info_a, sim_info_b):
    try:
        for relationship in sim_info_a.relationship_tracker:
            if relationship.get_other_sim_id(sim_info_a.sim_id) == sim_info_b.sim_id:
                return relationship
    except Exception:
        pass
    return None


def _relationship_change_gate(action):
    """Stop extreme friendship jumps and romance starts that do not fit the current pair."""
    arc = getattr(action, "_owner_arc", None)
    sim_info_a = getattr(arc, "sim_info", None)
    if sim_info_a is None or arc is None:
        return None
    try:
        other_id = arc.retrieve_participant(
            ParticipantTypeSavedStoryProgressionSim.SavedStoryProgressionSim1)
    except Exception:
        other_id = None
    sim_info_b = services.sim_info_manager().get(other_id) if other_id else None
    if sim_info_b is None:
        return None

    arc_name = type(arc).__name__.lower()
    friendship = None
    if "becomingbestfriends" in arc_name or "becomingdespised" in arc_name:
        try:
            friendship = sim_info_a.relationship_tracker.get_relationship_score(
                sim_info_b.sim_id, RelationshipTrack.FRIENDSHIP_TRACK)
        except Exception:
            friendship = None
    if "becomingbestfriends" in arc_name and friendship is not None and friendship < 50:
        nsr_log.log("relationship arc blocked for {} + {}: best friends from friendship {}".format(
            getattr(sim_info_a, "full_name", "sim"),
            getattr(sim_info_b, "full_name", "sim"), friendship))
        return StoryProgressionResult(
            StoryProgressionResultType.FAILED_TESTS,
            "Cannot become best friends without an existing close friendship.")
    if "becomingdespised" in arc_name and friendship is not None and friendship > -20:
        nsr_log.log("relationship arc blocked for {} + {}: despised from friendship {}".format(
            getattr(sim_info_a, "full_name", "sim"),
            getattr(sim_info_b, "full_name", "sim"), friendship))
        return StoryProgressionResult(
            StoryProgressionResultType.FAILED_TESTS,
            "Cannot become despised without an already hostile relationship.")
    if "romancestart" in arc_name:
        relationship = _find_relationship(sim_info_a, sim_info_b)
        if relationship is not None:
            level = _compatibility_level_name(sim_info_a, sim_info_b, relationship)
            if str(level).upper() not in ("GOOD", "AMAZING"):
                nsr_log.log("romance start blocked for {} + {}: compatibility {}".format(
                    getattr(sim_info_a, "full_name", "sim"),
                    getattr(sim_info_b, "full_name", "sim"), level))
                return StoryProgressionResult(
                    StoryProgressionResultType.FAILED_TESTS,
                    "Romance needs GOOD or AMAZING compatibility.")
    return None


_original_relationship_run = RelationshipModifiedStoryProgressionAction._run_story_progression_action


def _patched_relationship_run(self):
    try:
        blocked = _relationship_change_gate(self)
        if blocked is not None:
            return blocked
    except Exception:
        nsr_log.log_exception("relationship change gate")
    return _original_relationship_run(self)


RelationshipModifiedStoryProgressionAction._run_story_progression_action = _patched_relationship_run


def _can_form_romance(sim_info_a, sim_info_b):
    try:
        if sim_info_a.age < Age.TEEN or sim_info_b.age < Age.TEEN:
            return False
    except Exception:
        pass
    try:
        if not sim_info_a.incest_prevention_test(sim_info_b):
            return False
    except Exception:
        pass
    return True


def _younger_age_name(sim_info_a, sim_info_b):
    try:
        younger = min(sim_info_a.age, sim_info_b.age)
        return getattr(younger, "name", str(younger))
    except Exception:
        return None


def _add_significant_other(sim_info_a, sim_info_b):
    bit = _significant_other_bit()
    if bit is None:
        return False
    try:
        sim_info_a.relationship_tracker.add_relationship_bit(sim_info_b.sim_id, bit)
        sim_info_b.relationship_tracker.add_relationship_bit(sim_info_a.sim_id, bit)
        return True
    except Exception:
        nsr_log.log_exception("adding a Significant Other bit")
        return False


def _is_pregnant(sim_info):
    tracker = getattr(sim_info, "pregnancy_tracker", None)
    return bool(tracker is not None and getattr(tracker, "is_pregnant", False))


def _children_in_household(sim_info):
    try:
        children = set(sim_info.get_relations(RelationshipType.DESCENDANT))
        members = {member.sim_id for member in sim_info.household}
    except Exception:
        return set()
    return children & members


def _shared_child_in_household(sim_info_a, sim_info_b):
    try:
        shared = (set(sim_info_a.get_relations(RelationshipType.DESCENDANT))
                  & set(sim_info_b.get_relations(RelationshipType.DESCENDANT)))
    except Exception:
        return None
    manager = services.sim_info_manager()
    if manager is None:
        return None
    for child_id in shared:
        child = manager.get(child_id)
        if child is None:
            continue
        if child.household is sim_info_a.household or child.household is sim_info_b.household:
            return child
    return None


def _move_in_allowed(household):
    arc = _find_story_arc(_MOVE_IN_ARC)
    return arc is not None and _story_progression_allows(household, arc)


def _move_plan(sim_info_a, sim_info_b):
    household_a = getattr(sim_info_a, "household", None)
    household_b = getattr(sim_info_b, "household", None)
    if household_a is None or household_b is None or household_a is household_b:
        return None
    if not (_story_progression_enabled(household_a) and _story_progression_enabled(household_b)):
        return None
    if not (_move_in_allowed(household_a) and _move_in_allowed(household_b)):
        return None
    try:
        if sim_info_a.age < Age.YOUNGADULT or sim_info_b.age < Age.YOUNGADULT:
            return None
    except Exception:
        pass

    def plan(reason, mover, target, child=None):
        if mover is None or target is None or mover.household is target:
            return None
        if not target.can_add_sim_info(mover):
            return None
        left_behind = _children_in_household(mover)
        if child is not None:
            left_behind.discard(child.sim_id)
        if left_behind:
            return None
        return (reason, mover, target)

    if _is_pregnant(sim_info_a):
        return plan("pregnant", sim_info_b, household_a) or plan(
            "pregnant", sim_info_a, household_b)
    if _is_pregnant(sim_info_b):
        return plan("pregnant", sim_info_a, household_b) or plan(
            "pregnant", sim_info_b, household_a)

    child = _shared_child_in_household(sim_info_a, sim_info_b)
    if child is not None:
        if child.household is household_a:
            return plan("child", sim_info_b, household_a, child)
        if child.household is household_b:
            return plan("child", sim_info_a, household_b, child)

    if _has_romance_with(sim_info_a, sim_info_b.sim_id) or _has_romance_with(
            sim_info_b, sim_info_a.sim_id):
        return plan("romance", sim_info_b, household_a) or plan(
            "romance", sim_info_a, household_b)
    return None


def _daily_romance_step():
    manager = services.sim_info_manager()
    if manager is None:
        return
    romanced = set()
    started = 0
    for sim_info_a in list(manager.get_all()):
        household_a = getattr(sim_info_a, "household", None)
        if household_a is None or not _story_progression_enabled(household_a):
            continue
        if sim_info_a.sim_id in romanced:
            continue
        try:
            relationships = list(sim_info_a.relationship_tracker)
        except Exception:
            continue
        for relationship in relationships:
            try:
                other_id = relationship.get_other_sim_id(sim_info_a.sim_id)
            except Exception:
                continue
            sim_info_b = manager.get(other_id)
            if sim_info_b is None or sim_info_b.sim_id <= sim_info_a.sim_id:
                continue
            if sim_info_b.sim_id in romanced:
                continue
            household_b = getattr(sim_info_b, "household", None)
            if household_b is None or not _story_progression_enabled(household_b):
                continue
            if _has_romance_with(sim_info_a, sim_info_b.sim_id):
                continue
            if (_has_romance_with_other(sim_info_a, sim_info_b.sim_id)
                    or _has_romance_with_other(sim_info_b, sim_info_a.sim_id)):
                continue
            if not _can_form_romance(sim_info_a, sim_info_b):
                continue
            level = _compatibility_level_name(sim_info_a, sim_info_b, relationship)
            age_name = _younger_age_name(sim_info_a, sim_info_b)
            chance = nsr_life.romance_bit_chance(level, age_name)
            if chance <= 0 or random.random() >= chance:
                continue
            if _add_significant_other(sim_info_a, sim_info_b):
                romanced.add(sim_info_a.sim_id)
                romanced.add(sim_info_b.sim_id)
                line = "{} + {} ({}, {}, chance {:.1%})".format(
                    getattr(sim_info_a, "full_name", "sim"),
                    getattr(sim_info_b, "full_name", "sim"), level, age_name, chance)
                _last_romances.append(line)
                del _last_romances[:-50]
                nsr_log.log("daily romance: " + line)
                started += 1
                if started >= nsr_life.MAX_DAILY_ROMANCES:
                    nsr_log.log("daily romance: daily cap of {} reached".format(
                        nsr_life.MAX_DAILY_ROMANCES))
                    return
                break


def _daily_move_in_step():
    manager = services.sim_info_manager()
    household_manager = services.household_manager()
    if manager is None or household_manager is None:
        return
    handled = set()
    moved = 0
    for sim_info_a in list(manager.get_all()):
        if sim_info_a.sim_id in handled:
            continue
        try:
            relationships = list(sim_info_a.relationship_tracker)
        except Exception:
            continue
        for relationship in relationships:
            try:
                other_id = relationship.get_other_sim_id(sim_info_a.sim_id)
            except Exception:
                continue
            sim_info_b = manager.get(other_id)
            if sim_info_b is None or sim_info_b.sim_id <= sim_info_a.sim_id:
                continue
            if sim_info_b.sim_id in handled:
                continue
            plan = _move_plan(sim_info_a, sim_info_b)
            if plan is None:
                continue
            reason, mover, target = plan
            chance = nsr_life.move_in_chance(reason)
            if chance <= 0 or random.random() >= chance:
                continue
            source = mover.household
            try:
                household_manager.switch_sim_from_household_to_target_household(
                    mover, source, target, destroy_if_empty_household=True,
                    reason=HouseholdChangeOrigin.UNKNOWN)
                try:
                    target.save_data()
                except Exception:
                    pass
            except Exception:
                nsr_log.log_exception("daily move-in: moving {}".format(
                    getattr(mover, "full_name", "sim")))
                continue
            handled.add(sim_info_a.sim_id)
            handled.add(sim_info_b.sim_id)
            line = "{} moved in with {} ({}, chance {:.0%})".format(
                getattr(mover, "full_name", "sim"),
                getattr(sim_info_a if mover is sim_info_b else sim_info_b,
                        "full_name", "sim"), reason, chance)
            _last_move_ins.append(line)
            del _last_move_ins[:-50]
            nsr_log.log("daily move-in: " + line)
            moved += 1
            if moved >= nsr_life.MAX_DAILY_MOVE_INS:
                nsr_log.log("daily move-in: daily cap of {} reached".format(
                    nsr_life.MAX_DAILY_MOVE_INS))
                return
            break


_CHILD_ADOPTION_ARCS = (
    "simStoryArc_ChildrenStories_AdoptABaby",
    "simStoryArc_ChildrenStories_AdoptAToddler",
    "simStoryArc_ChildrenStories_AdoptAChild",
)


_PREGNANCY_ARC = "simStoryArc_ChildrenStories_Pregnancy"


def _couple_in_household(household):
    members = []
    try:
        for member in household:
            age = getattr(member, "age", None)
            if age is not None and age >= Age.YOUNGADULT:
                members.append(member)
    except Exception:
        return None
    for index, sim_info_a in enumerate(members):
        for sim_info_b in members[index + 1:]:
            if (_has_romance_with(sim_info_a, sim_info_b.sim_id)
                    or _has_romance_with(sim_info_b, sim_info_a.sim_id)):
                same_sex = getattr(sim_info_a, "gender", None) == getattr(
                    sim_info_b, "gender", None)
                return (sim_info_a, sim_info_b, same_sex)
    return None


def _gender_name(sim_info):
    gender = getattr(sim_info, "gender", None)
    return getattr(gender, "name", str(gender) if gender is not None else "")


def _pregnancy_capable(sim_info):
    # EA's pregnancy_tracker.is_pregnancy_supported only checks the species, so male sims
    # pass it too. This mod only ever makes female sims pregnant.
    if not nsr_life.gender_can_be_pregnant(_gender_name(sim_info)):
        return False
    tracker = getattr(sim_info, "pregnancy_tracker", None)
    return bool(tracker is not None and getattr(tracker, "is_pregnancy_supported", False))


_original_make_pregnant_setup = \
    MakePregnantStoryProgressionAction.setup_story_progression_action


def _patched_make_pregnant_setup(self, **kwargs):
    """Gate EA's own Pregnancy arc: female sims only, and only sometimes.

    EA's pregnancy arc can be attached to any adult in a household, and its
    pregnancy_tracker reports every human as pregnancy-capable regardless of gender. That
    is how male sims ended up pregnant. It also ran at full strength alongside this mod's
    daily child step, so almost every adult couple conceived. Blocking here stops both.
    """
    try:
        sim_info = getattr(getattr(self, "_owner_arc", None), "sim_info", None)
        if sim_info is not None:
            name = getattr(sim_info, "full_name", "sim")
            gender_name = _gender_name(sim_info)
            if not nsr_life.gender_can_be_pregnant(gender_name):
                nsr_log.log("pregnancy blocked for {}: {} sims do not get pregnant".format(
                    name, gender_name.lower() or "male"))
                return StoryProgressionResult(
                    StoryProgressionResultType.FAILED_TESTS,
                    "Only female sims can become pregnant.")
            roll = random.random()
            if not nsr_life.should_allow_ea_pregnancy(roll, gender_name):
                nsr_log.log("pregnancy blocked for {}: rare-pregnancy gate (roll {:.3f})".format(
                    name, roll))
                return StoryProgressionResult(
                    StoryProgressionResultType.FAILED_TESTS,
                    "Pregnancy is rare in this neighbourhood.")
    except Exception:
        nsr_log.log_exception("pregnancy gate")
    return _original_make_pregnant_setup(self, **kwargs)


MakePregnantStoryProgressionAction.setup_story_progression_action = \
    _patched_make_pregnant_setup


def _allowed_child_arc(household, adopter, arc_names):
    tracker = getattr(adopter, "story_progression_tracker", None)
    if tracker is None:
        return None
    for arc_name in arc_names:
        arc = _find_story_arc(arc_name)
        if arc is None or not _story_progression_allows(household, arc):
            continue
        try:
            if tracker.can_add_arc(arc):
                return arc
        except Exception:
            continue
    return None


def _daily_couple_child_step():
    household_manager = services.household_manager()
    if household_manager is None:
        return
    for household in list(household_manager.values()):
        if not _story_progression_enabled(household):
            continue
        try:
            if household.free_slot_count <= 0:
                continue
        except Exception:
            continue
        try:
            if any(_is_pregnant(member) for member in household):
                continue
        except Exception:
            pass
        couple = _couple_in_household(household)
        if couple is None:
            continue
        sim_info_a, sim_info_b, same_sex = couple

        if same_sex:
            if not nsr_life.should_start_child("same_sex_adoption", random.random()):
                continue
            kind = "adoption"
            adopter = random.choice((sim_info_a, sim_info_b))
            arcs = _CHILD_ADOPTION_ARCS
        else:
            kind = None
            adopter = None
            arcs = ()
            if nsr_life.should_start_child("opposite_sex_pregnancy", random.random()):
                capable = [sim for sim in (sim_info_a, sim_info_b) if _pregnancy_capable(sim)]
                if capable:
                    kind = "pregnancy"
                    adopter = random.choice(capable)
                    arcs = (_PREGNANCY_ARC,)
            if kind is None and nsr_life.should_start_child(
                    "opposite_sex_adoption", random.random()):
                kind = "adoption"
                adopter = random.choice((sim_info_a, sim_info_b))
                arcs = _CHILD_ADOPTION_ARCS
            if kind is None:
                continue

        arc = _allowed_child_arc(household, adopter, arcs)
        if arc is None:
            continue
        try:
            result = adopter.story_progression_tracker.add_arc(arc)
        except Exception:
            nsr_log.log_exception("daily child: adding {} to {}".format(
                getattr(arc, "__name__", arc), getattr(adopter, "full_name", "sim")))
            continue
        if not result:
            continue
        chance = nsr_life.child_chance(
            "same_sex_adoption" if same_sex else
            ("opposite_sex_pregnancy" if kind == "pregnancy" else "opposite_sex_adoption"))
        line = "{} + {} -> {} ({}, chance {:.1%})".format(
            getattr(sim_info_a, "full_name", "sim"),
            getattr(sim_info_b, "full_name", "sim"),
            getattr(arc, "__name__", arc), kind, chance)
        _last_children.append(line)
        del _last_children[:-50]
        nsr_log.log("daily child: " + line)


def _sim_day():
    # absolute_days(), not day(): day() is the weekday (0-6), which repeats every week.
    try:
        return int(services.time_service().sim_now.absolute_days())
    except Exception:
        return None


_last_couple_day = None


def _daily_couple_logic():
    """Run the couple steps once per sim day, not on every story-arc seed.

    EA calls seed_new_story_arcs_gen far more often than once a day. Running a 2% pregnancy
    roll on every call is what made entire neighbourhoods pregnant, so the day is checked
    here (the steps are meant to be daily, as their names say). If the clock is unreadable,
    fall back to the old behaviour rather than skipping the step permanently.
    """
    global _last_couple_day
    day = _sim_day()
    if day is not None and day == _last_couple_day:
        return
    _daily_romance_step()
    _daily_move_in_step()
    _daily_couple_child_step()
    if day is not None:
        _last_couple_day = day


_original_seed_new_story_arcs = StoryProgressionService.seed_new_story_arcs_gen


def _patched_seed_new_story_arcs(self, timeline=None, debug_seed_all_arcs=False):
    yield from _original_seed_new_story_arcs(
        self, timeline=timeline, debug_seed_all_arcs=debug_seed_all_arcs)
    try:
        _daily_couple_logic()
    except Exception:
        nsr_log.log_exception("daily couple logic")


StoryProgressionService.seed_new_story_arcs_gen = _patched_seed_new_story_arcs


_original_move_out_setup = MoveOutStoryProgressionAction.setup_story_progression_action


def _patched_move_out_setup(self, **kwargs):
    try:
        arc = getattr(self, "_owner_arc", None)
        household = getattr(arc, "household", None)
        if household is None:
            return StoryProgressionResult(
                StoryProgressionResultType.FAILED_TESTS,
                "Move out needs a household.")
        if not _story_progression_enabled(household) or not _story_progression_allows(household, arc):
            nsr_log.log("move out blocked for {}: story progression or the move-out rule is off".format(
                getattr(household, "name", "household")))
            return StoryProgressionResult(
                StoryProgressionResultType.FAILED_TESTS,
                "Move out is disabled for this household.")
        if not _household_is_lone_childless_adult(household):
            nsr_log.log("move out blocked for {}: not a single adult with no children or partner".format(
                getattr(household, "name", "household")))
            return StoryProgressionResult(
                StoryProgressionResultType.FAILED_TESTS,
                "Move out only applies to a single adult with no children or partner.")
    except Exception:
        nsr_log.log_exception("move-out gate")
    return _original_move_out_setup(self, **kwargs)


MoveOutStoryProgressionAction.setup_story_progression_action = _patched_move_out_setup


def _skill_levels(sim_info):
    levels = {}
    tracker = getattr(sim_info, "commodity_tracker", None)
    if tracker is None:
        return levels
    for stat in tracker.get_all_commodities():
        if not getattr(stat, "is_skill", False):
            continue
        stat_type = getattr(stat, "stat_type", None)
        name = getattr(stat_type, "__name__", None) or type(stat).__name__
        try:
            levels[name] = stat.get_user_value()
        except Exception:
            continue
    return levels


def _trait_names(sim_info):
    tracker = getattr(sim_info, "trait_tracker", None)
    if tracker is None:
        return []
    return [type(trait).__name__ for trait in tracker]


def _career_candidates(sim_info, part_time=False):
    career_service = services.get_career_service()
    if career_service is None:
        return []
    resolver = SingleSimResolver(sim_info)
    skills = _skill_levels(sim_info)
    traits = _trait_names(sim_info)
    tracker = getattr(sim_info, "career_tracker", None)
    categories = ((CareerCategory.AdultPartTime,) if part_time
                  else (CareerCategory.Work, CareerCategory.WorkFromHome))
    candidates = []
    for career in career_service.get_career_list():
        name = getattr(career, "__name__", str(career))
        if "npc" in name.lower():
            continue
        if getattr(career, "career_category", None) not in categories:
            continue
        joining = getattr(getattr(career, "career_story_progression", None), "joining", None)
        if joining is None:
            continue
        try:
            if not career.is_valid_career(sim_info=sim_info):
                continue
        except Exception:
            continue
        career_uid = getattr(career, "guid64", None)
        if career_uid is not None and tracker is not None and tracker.has_career_by_uid(career_uid):
            continue
        try:
            base_weight = joining.get_multiplier(resolver)
        except Exception:
            continue
        if base_weight is None or base_weight <= 0:
            continue
        affinity = nsr_life.career_affinity(name, skills, traits)
        candidates.append((career, base_weight * affinity, name))
    return candidates


def _household_net_worth(household):
    try:
        return household.household_net_worth()
    except Exception:
        try:
            return getattr(getattr(household, "funds", None), "money", 0) or 0
        except Exception:
            return 0


def _choose_university_major(sim_info):
    try:
        mapping = getattr(University, "SKILL_TO_MAJOR_TUNING", None)
        tracker = getattr(sim_info, "commodity_tracker", None)
        if mapping and tracker:
            scored = []
            for skill in mapping.keys():
                try:
                    scored.append((tracker.get_value(skill), skill))
                except Exception:
                    scored.append((0, skill))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            top = scored[:3]
            if top:
                skill = random.choice(top)[1]
                majors = list(mapping[skill])
                if majors:
                    return random.choice(majors)
    except Exception:
        nsr_log.log_exception("choosing a university major")
    return University.choose_random_major()


def _move_to_university_housing(sim_info, original_home_zone_id):
    """Move an enrolled NPC into a university hall/building lot, if there is room."""
    try:
        zones = list(UniversityHousingTuning.get_university_housing_zone_ids())
    except Exception:
        zones = []
    if not zones:
        nsr_log.log("age-up university: no university housing zones available; staying home")
        return False
    if original_home_zone_id in zones:
        return False

    household_manager = services.household_manager()
    persistence_service = services.get_persistence_service()
    account = getattr(sim_info, "account", None)
    if account is None:
        try:
            account = services.get_first_client().account
        except Exception:
            account = None
    if account is None or household_manager is None or persistence_service is None:
        return False

    random.shuffle(zones)
    source_household = getattr(sim_info, "household", None)
    if source_household is None:
        return False

    for zone_id in zones:
        try:
            target_id = persistence_service.get_household_id_from_zone_id(zone_id)
            target = household_manager.get(target_id) if target_id else None
            if target is not None:
                if getattr(target, "is_player_household", False) or getattr(target, "is_active_household", False):
                    continue
                target_home = getattr(target, "home_zone_id", 0)
                if target_home not in (0, zone_id):
                    continue
                if target_home == 0:
                    target.set_household_lot_ownership(zone_id)
            else:
                target = household_manager.create_household(account, starting_funds=0)
                target.name = (getattr(sim_info, "last_name", None)
                               or getattr(sim_info, "full_name", "University household"))
                target.set_household_lot_ownership(zone_id)
                target.save_data()

            if not target.can_add_sim_info(sim_info):
                continue
            household_manager.switch_sim_from_household_to_target_household(
                sim_info,
                source_household,
                target,
                destroy_if_empty_household=False,
                reason=HouseholdChangeOrigin.UNKNOWN,
            )
            if original_home_zone_id:
                try:
                    sim_info.degree_tracker.set_kickout_info(
                        original_home_zone_id, UniversityHousingKickOutReason.MOVED)
                except Exception:
                    pass
            try:
                target.save_data()
            except Exception:
                pass
            nsr_log.log("age-up university: {} moved into university housing zone {}".format(
                getattr(sim_info, "full_name", "sim"), zone_id))
            return True
        except Exception:
            nsr_log.log_exception("age-up university: moving into university housing")
            continue
    nsr_log.log("age-up university: no university housing zone had room; staying home")
    return False


def _maybe_enroll_in_university(sim_info, new_age, current_age):
    # University entry is a young-adult step, not an adult one. It competes with the
    # career roll: a student is not also given a full-time job that age-up.
    if new_age != Age.YOUNGADULT:
        return False
    try:
        if current_age is not None and int(new_age) <= int(current_age):
            return False
    except Exception:
        pass

    household = getattr(sim_info, "household", None)
    if household is None:
        return False

    degree_tracker = getattr(sim_info, "degree_tracker", None)
    if degree_tracker is None:
        return False
    try:
        if degree_tracker.is_current_student():
            return False
    except Exception:
        pass
    try:
        if not degree_tracker.allowed_to_enroll:
            return False
    except Exception:
        pass

    if not _story_progression_enabled(household):
        nsr_log.log("age-up university: story progression is off for {}".format(
            getattr(household, "name", "household")))
        return False

    net_worth = _household_net_worth(household)
    chance = nsr_life.university_chance(net_worth)
    roll = random.random()
    who = getattr(sim_info, "full_name", "sim")
    if not nsr_life.should_enroll_in_university(net_worth, roll):
        nsr_log.log("age-up university: {} rolled {:.2f} against {:.0%} "
                    "(net worth §{}); not enrolling".format(who, roll, chance, net_worth))
        return False

    university = University.choose_random_university()
    major = _choose_university_major(sim_info)
    if university is None or major is None:
        nsr_log.log("age-up university: no university or major available; skipped")
        return False

    original_home_zone_id = getattr(household, "home_zone_id", 0)
    try:
        degree_tracker.process_acceptance(send_telemetry=False)
        if not degree_tracker.is_accepted_degree(university, major):
            degree_tracker.set_accepted_degree(university, major)
        degree_tracker.enroll(major, university, 3, [])
    except Exception:
        nsr_log.log_exception("age-up university: enrolling {}".format(who))
        return False

    moved_in = _move_to_university_housing(sim_info, original_home_zone_id)
    _last_university.append(
        "{} -> {} / {} (net worth §{}, chance {:.0%}, roll {:.2f}{})".format(
            who, getattr(university, "__name__", university),
            getattr(major, "__name__", major), net_worth, chance, roll,
            ", moved into halls" if moved_in else ", stayed home"))
    del _last_university[:-50]
    nsr_log.log("age-up university: {} enrolled in {} / {} (net worth §{}, "
                "chance {:.0%}, roll {:.2f}, {})".format(
                    who, getattr(university, "__name__", university),
                    getattr(major, "__name__", major), net_worth, chance, roll,
                    "moved into halls" if moved_in else "stayed home"))
    return True


def _move_out_of_university_housing(sim_info, destination_zone_id):
    """After graduating, move a student out of a university hall/building."""
    try:
        zones = tuple(UniversityHousingTuning.get_university_housing_zone_ids())
    except Exception:
        zones = ()
    household = getattr(sim_info, "household", None)
    if household is None or getattr(household, "home_zone_id", 0) not in zones:
        return False

    household_manager = services.household_manager()
    persistence_service = services.get_persistence_service()
    account = getattr(sim_info, "account", None)
    if account is None:
        try:
            account = services.get_first_client().account
        except Exception:
            account = None
    if household_manager is None or persistence_service is None or account is None:
        return False

    target = None
    if destination_zone_id:
        try:
            target_id = persistence_service.get_household_id_from_zone_id(destination_zone_id)
            candidate = household_manager.get(target_id) if target_id else None
            if (candidate is not None and candidate is not household
                    and not getattr(candidate, "is_active_household", False)
                    and not getattr(candidate, "is_player_household", False)
                    and candidate.can_add_sim_info(sim_info)):
                target = candidate
        except Exception:
            target = None

    created = False
    if target is None:
        try:
            target = household_manager.create_household(account, starting_funds=0)
            target.name = (getattr(sim_info, "last_name", None)
                           or getattr(sim_info, "full_name", "Graduate household"))
            target.save_data()
            created = True
        except Exception:
            nsr_log.log_exception("age-up graduation: creating a household for {}".format(
                getattr(sim_info, "full_name", "sim")))
            return False

    try:
        household_manager.switch_sim_from_household_to_target_household(
            sim_info,
            household,
            target,
            destroy_if_empty_household=False,
            reason=HouseholdChangeOrigin.UNKNOWN,
        )
        try:
            household.destroy_household_if_empty()
        except Exception:
            pass
        try:
            target.save_data()
        except Exception:
            pass
        nsr_log.log("age-up graduation: {} moved out of university housing into {}".format(
            getattr(sim_info, "full_name", "sim"),
            "the family home" if not created else "a new household"))
        return True
    except Exception:
        nsr_log.log_exception("age-up graduation: moving out of university housing")
        try:
            if created:
                target.destroy_household_if_empty()
        except Exception:
            pass
        return False


def _maybe_graduate_from_university(sim_info, new_age, current_age):
    # Any student who ages up from young adult to adult finishes their degree.
    if new_age != Age.ADULT:
        return False
    try:
        if current_age is not None and int(new_age) <= int(current_age):
            return False
    except Exception:
        pass

    household = getattr(sim_info, "household", None)
    if household is None:
        return False
    if not _story_progression_enabled(household):
        nsr_log.log("age-up graduation: story progression is off for {}".format(
            getattr(household, "name", "household")))
        return False

    degree_tracker = getattr(sim_info, "degree_tracker", None)
    if degree_tracker is None:
        return False
    try:
        if not degree_tracker.is_current_student():
            return False
    except Exception:
        return False

    who = getattr(sim_info, "full_name", "sim")
    destination_zone_id = getattr(degree_tracker, "kickout_destination_zone", 0) or 0
    try:
        gpa = degree_tracker.get_gpa()
        if gpa is None or gpa <= 0:
            gpa = 2.0
        major = degree_tracker.get_major()
        degree_tracker.drop_enrolled_courses()
        degree_tracker.graduate(gpa=gpa)
    except Exception:
        nsr_log.log_exception("age-up graduation: graduating {}".format(who))
        return False

    moved_out = _move_out_of_university_housing(sim_info, destination_zone_id)
    _last_graduates.append("{} graduated (GPA {:.2f}{})".format(
        who, gpa, ", moved out of halls" if moved_out else ""))
    del _last_graduates[:-50]
    nsr_log.log("age-up graduation: {} graduated from {} with GPA {:.2f}{}".format(
        who, getattr(major, "__name__", major), gpa,
        ", moved out of halls" if moved_out else ""))
    return True


def _has_full_time_career(sim_info):
    tracker = getattr(sim_info, "career_tracker", None)
    if tracker is None:
        return False
    for career in tracker:
        if getattr(career, "career_category", None) in (CareerCategory.Work,
                                                        CareerCategory.WorkFromHome):
            return True
    return False


def _maybe_assign_career(sim_info, new_age, current_age):
    if new_age not in (Age.YOUNGADULT, Age.ADULT):
        return
    try:
        if current_age is not None and int(new_age) <= int(current_age):
            return
    except Exception:
        pass

    household = getattr(sim_info, "household", None)
    if household is None:
        return

    tracker = getattr(sim_info, "career_tracker", None)
    if tracker is None or _has_full_time_career(sim_info):
        return

    arc = _find_story_arc(_CAREER_ADD_ARC)
    if arc is None:
        nsr_log.log("age-up career: CareerAdd arc not found; skipped")
        return
    if not _story_progression_allows(household, arc):
        nsr_log.log("age-up career: story progression is off for {}".format(
            getattr(household, "name", "household")))
        return

    age_name = getattr(new_age, "name", str(new_age))
    chance = nsr_life.career_chance(age_name)
    roll = random.random()
    who = getattr(sim_info, "full_name", "sim")
    if not nsr_life.should_assign_career(age_name, roll):
        nsr_log.log("age-up career: {} rolled {:.2f} against {:.0%}; no career this time".format(
            who, roll, chance))
        return

    part_time_roll = random.random()
    part_time = nsr_life.should_take_part_time(age_name, part_time_roll)
    candidates = _career_candidates(sim_info, part_time=part_time)
    if not candidates and part_time:
        nsr_log.log("age-up career: {} had no part-time careers; using full-time".format(who))
        part_time = False
        candidates = _career_candidates(sim_info, part_time=False)
    if not candidates:
        nsr_log.log("age-up career: {} had no eligible careers".format(who))
        return

    chosen_name = nsr_life.choose_career(
        [(name, weight) for _, weight, name in candidates], rng=random.random)
    chosen = next((career for career, _, name in candidates if name == chosen_name), None)
    if chosen is None:
        return

    job_kind = "part-time" if part_time else "full-time"
    try:
        new_career = chosen(sim_info)
        tracker.add_career(
            new_career,
            user_level_override=1,
            give_skipped_rewards=False,
            show_join_msg=False,
            post_quit_msg=False,
            show_icon_override_picker=False,
        )
    except Exception:
        nsr_log.log_exception("age-up career: adding {} to {}".format(chosen_name, who))
        return

    _last_careers.append("{} -> {} ({}, chance {:.0%}, roll {:.2f})".format(
        who, chosen_name, job_kind, chance, roll))
    del _last_careers[:-50]
    nsr_log.log("age-up career: {} -> {} ({}, chance {:.0%}, roll {:.2f}, "
                "part-time roll {:.2f}, {} candidates)".format(
                    who, chosen_name, job_kind, chance, roll, part_time_roll,
                    len(candidates)))


_MOVE_OUT_ARC = "householdStoryArc_MoveOut"


def _maybe_split_household(sim_info, new_age, current_age):
    # Only the teen -> young adult transition. Adults may legitimately share a
    # house with other adults, so they are never split out by this step.
    if new_age != Age.YOUNGADULT:
        return
    try:
        if current_age is not None and int(new_age) <= int(current_age):
            return
    except Exception:
        pass

    household = getattr(sim_info, "household", None)
    if household is None:
        return
    try:
        if len(household) <= 1:
            return
    except Exception:
        return

    arc = _find_story_arc(_MOVE_OUT_ARC)
    if arc is None:
        nsr_log.log("age-up move-out: MoveOut arc not found; skipped")
        return
    if not _story_progression_allows(household, arc):
        nsr_log.log("age-up move-out: story progression is off for {}".format(
            getattr(household, "name", "household")))
        return

    age_name = getattr(new_age, "name", str(new_age))
    chance = nsr_life.move_out_chance(age_name)
    roll = random.random()
    who = getattr(sim_info, "full_name", "sim")
    if not nsr_life.should_move_out(age_name, roll):
        nsr_log.log("age-up move-out: {} rolled {:.2f} against {:.0%}; staying home".format(
            who, roll, chance))
        return

    account = getattr(sim_info, "account", None)
    if account is None:
        try:
            account = services.get_first_client().account
        except Exception:
            account = None
    if account is None:
        nsr_log.log("age-up move-out: no account for {}; skipped".format(who))
        return

    household_manager = services.household_manager()
    if household_manager is None:
        nsr_log.log("age-up move-out: no household manager; skipped")
        return

    new_household = household_manager.create_household(account, starting_funds=0)
    new_household.name = (getattr(sim_info, "last_name", None)
                          or getattr(sim_info, "full_name", "New household"))
    try:
        new_household.save_data()
        household_manager.switch_sim_from_household_to_target_household(
            sim_info,
            household,
            new_household,
            destroy_if_empty_household=False,
            reason=HouseholdChangeOrigin.UNKNOWN,
        )
    except Exception:
        nsr_log.log_exception("age-up move-out: splitting {} out".format(who))
        try:
            new_household.destroy_household_if_empty()
        except Exception:
            pass
        return

    try:
        new_household.save_data()
    except Exception:
        nsr_log.log("age-up move-out: could not save the new household for {}".format(who))

    _last_splits.append("{} -> own household (chance {:.0%}, roll {:.2f})".format(
        who, chance, roll))
    del _last_splits[:-50]
    nsr_log.log("age-up move-out: {} split into a new homeless household "
                "(chance {:.0%}, roll {:.2f})".format(who, chance, roll))


_original_change_age = AgingMixin.change_age


def _patched_change_age(self, new_age, current_age):
    result = _original_change_age(self, new_age, current_age)
    enrolled = False
    try:
        enrolled = _maybe_enroll_in_university(self, new_age, current_age)
    except Exception:
        nsr_log.log_exception("age-up university enrolment")
    try:
        _maybe_graduate_from_university(self, new_age, current_age)
    except Exception:
        nsr_log.log_exception("age-up graduation")
    if not enrolled:
        try:
            _maybe_assign_career(self, new_age, current_age)
        except Exception:
            nsr_log.log_exception("age-up career assignment")
        try:
            _maybe_split_household(self, new_age, current_age)
        except Exception:
            nsr_log.log_exception("age-up move-out")
    return result


AgingMixin.change_age = _patched_change_age


_original_on_loading_screen_animation_finished = zone_module.Zone.on_loading_screen_animation_finished


def _patched_on_loading_screen_animation_finished(self, *args, **kwargs):
    result = _original_on_loading_screen_animation_finished(self, *args, **kwargs)
    try:
        _apply_rebalance()
    except Exception:
        nsr_log.log_exception("on_loading_screen_animation_finished hook")
    return result


zone_module.Zone.on_loading_screen_animation_finished = _patched_on_loading_screen_animation_finished


@sims4.commands.Command("houserules.nsr.status", command_type=sims4.commands.CommandType.Live)
def nsr_status(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    if not _applied_already:
        output("Neighborhood Stories Rebalance: not applied yet - load a save first.")
        return
    if not _last_summary:
        output("Neighborhood Stories Rebalance: ran, but found no story arcs to look at (see the log).")
        return
    output("Neighborhood Stories Rebalance: {} arcs checked".format(len(_last_summary)))
    for s in _last_summary:
        output("  {arc}: {category}  weight {old_weight} -> {new_weight}{note}".format(
            note="" if s.get("applied") else " (unchanged)", **s))
    output("Full detail in Mods/HouseRules/logs/neighborhood-stories-rebalance.log")


@sims4.commands.Command("houserules.nsr.splits", command_type=sims4.commands.CommandType.Live)
def nsr_splits(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    if not _last_splits:
        output("No age-up move-outs yet. They happen when a teen in a household with "
               "Neighborhood Stories on becomes a young adult.")
        return
    output("Neighborhood Stories age-up move-outs ({}):".format(len(_last_splits)))
    for line in _last_splits:
        output("  " + line)
    output("Full detail in Mods/HouseRules/logs/neighborhood-stories-rebalance.log")


@sims4.commands.Command("houserules.nsr.couples", command_type=sims4.commands.CommandType.Live)
def nsr_couples(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    if not _last_romances and not _last_move_ins and not _last_children:
        output("No Neighborhood Stories romances, move-ins or couple children yet. "
               "They are checked once per sim day.")
        return
    output("Neighborhood Stories relationships:")
    if _last_romances:
        output("  New romances ({}):".format(len(_last_romances)))
        for line in _last_romances:
            output("    " + line)
    if _last_move_ins:
        output("  Moved in together ({}):".format(len(_last_move_ins)))
        for line in _last_move_ins:
            output("    " + line)
    if _last_children:
        output("  Couple children ({}):".format(len(_last_children)))
        for line in _last_children:
            output("    " + line)
    output("Full detail in Mods/HouseRules/logs/neighborhood-stories-rebalance.log")


@sims4.commands.Command("houserules.nsr.graduates", command_type=sims4.commands.CommandType.Live)
def nsr_graduates(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    if not _last_graduates:
        output("No age-up graduations yet. A young adult in a household with Neighborhood "
               "Stories on who is still studying graduates when they become an adult.")
        return
    output("Neighborhood Stories age-up graduations ({}):".format(len(_last_graduates)))
    for line in _last_graduates:
        output("  " + line)
    output("Full detail in Mods/HouseRules/logs/neighborhood-stories-rebalance.log")


@sims4.commands.Command("houserules.nsr.university", command_type=sims4.commands.CommandType.Live)
def nsr_university(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    if not _last_university:
        output("No age-up university enrolments yet. They happen when a young adult in "
               "a household with Neighborhood Stories on ages up and the wealth roll passes.")
        return
    output("Neighborhood Stories age-up university enrolments ({}):".format(len(_last_university)))
    for line in _last_university:
        output("  " + line)
    output("Full detail in Mods/HouseRules/logs/neighborhood-stories-rebalance.log")


@sims4.commands.Command("houserules.nsr.careers", command_type=sims4.commands.CommandType.Live)
def nsr_careers(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    if not _last_careers:
        output("No age-up careers assigned yet. They happen when a household with "
               "Neighborhood Stories on has a young adult or adult age up.")
        return
    output("Neighborhood Stories age-up careers ({}):".format(len(_last_careers)))
    for line in _last_careers:
        output("  " + line)
    output("Full detail in Mods/HouseRules/logs/neighborhood-stories-rebalance.log")
# Counts are kept in Mods/HouseRules/data/nsr_events.json so they build up across play
# sessions. Both hooks only record; they always call EA's original first and return its result.
import os

import story_progression.story_progression_telemetry as sp_telemetry
import story_progression.story_progression_tracker as sp_tracker
from story_progression.story_progression_result import STORY_PROGRESSION_RESULT_TYPE_STRINGS

from nsr_events import EventTally

_EVENTS_PATH = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts",
                            "The Sims 4", "Mods", "HouseRules", "data", "nsr_events.json")
_tally = None


def _record(kind, arc_name, result=None):
    global _tally
    try:
        if _tally is None:
            _tally = EventTally.load(_EVENTS_PATH)
        try:
            when = str(services.time_service().sim_now)
        except Exception:
            when = None
        _tally.add(kind, arc_name, when=when, result=result)
        _tally.save(_EVENTS_PATH)
        nsr_log.log("event {}: {}{}".format(kind, arc_name, " ({})".format(result) if result else ""))
    except Exception:
        nsr_log.log_exception("recording {} event for {}".format(kind, arc_name))


_original_add_arc = sp_tracker.BaseStoryProgressionTracker.add_arc


def _patched_add_arc(self, new_arc, **kwargs):
    result = _original_add_arc(self, new_arc, **kwargs)
    if result:
        _record("started", getattr(new_arc, "__name__", str(new_arc)))
    return result


sp_tracker.BaseStoryProgressionTracker.add_arc = _patched_add_arc

# The tracker calls this through the module whenever an arc ends, with how it ended.
_original_arc_complete = sp_telemetry.send_arc_complete_telemetry


def _patched_arc_complete(chapter, result_type):
    try:
        _record("ended", type(chapter.arc).__name__,
                result=STORY_PROGRESSION_RESULT_TYPE_STRINGS.get(result_type, str(result_type)))
    except Exception:
        nsr_log.log_exception("arc complete hook")
    return _original_arc_complete(chapter, result_type)


sp_telemetry.send_arc_complete_telemetry = _patched_arc_complete


@sims4.commands.Command("houserules.nsr.events", command_type=sims4.commands.CommandType.Live)
def nsr_events(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    tally = _tally if _tally is not None else EventTally.load(_EVENTS_PATH)
    if not tally.events:
        output("No Neighborhood Stories events recorded yet. They're picked once per sim day.")
        return
    output("Neighborhood Stories events recorded so far ({} total):".format(len(tally.events)))
    for line in tally.summary_lines():
        output("  " + line)


@sims4.commands.Command("houserules.nsr.events_reset", command_type=sims4.commands.CommandType.Live)
def nsr_events_reset(_connection=None):
    global _tally
    _tally = EventTally()
    _tally.save(_EVENTS_PATH)
    sims4.commands.CheatOutput(_connection)("Neighborhood Stories event counts reset.")
