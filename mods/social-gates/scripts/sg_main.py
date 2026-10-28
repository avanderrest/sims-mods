"""Social Gates - game layer. The rules are in sg_logic.py.

Hooks (each checks its setting every time, so the cheats switch things off immediately):

doors   - RingDoorbellSuperInteraction._try_to_be_invited_in. When a Sim visits an NPC
          household, they're only let in by someone they're friends with. Own household,
          household members, "always welcome" Sims/traits and Sims who are already inside
          are unaffected.
invites - SituationManager.create_situation for the invite-over situation, plus
          InviteOverSituation._invite_sim_in and Venue.summon_npcs as backstops. An invite
          over is declined when the host isn't a friend of the Sim they're inviting.
clubs   - Club.add_member and Club.can_sim_info_join: a new member must match a trait from
          the club's trait restrictions, a skill from its skill restrictions, or a skill
          used by one of its activities. EA's other membership criteria still apply.
          Club._validate_member_against_criteria ignores EA's fixed household-value brackets
          for player-created clubs, so gaining money never kicks anyone; our relative check
          runs when a Sim joins and when the club is edited. Existing members are
          grandfathered on load.

Cheats:
  houserules.gates.status                - every setting
  houserules.gates.set <setting> <value> - change one
  houserules.gates.check [sim id]        - the selected Sim's clubs and why they pass/fail
  houserules.gates.clubs                 - every club, its restrictions and activity skills
  houserules.gates.wealth                - the effective relative wealth ranges per club
  houserules.gates.invite <sim id>       - friendship score between the selected Sim and another
"""
import contextlib
import weakref

import services
import sims4.commands
import sims4.resources
from server_commands.argument_helpers import OptionalSimInfoParam, get_optional_target

import sg_log
import sg_state
from sg_logic import (CLUB_MEMBERS_REMOVED, club_admission, group_affordances, in_wealth_range,
                      is_friend, relative_wealth_label, relative_wealth_label_with_ranges,
                      string_key, wealth_description)
from sg_settings import DEFAULT_SETTINGS

# True while the game is loading saved clubs or re-validating members on its own. Used to
# grandfather existing members, so a household's new money can never remove them.
_sg_auto = False

# True while the club rule screen is being built for a small business. Businesses still use
# the game's fixed household-value brackets, so they keep the game's labels.
_sg_business_ui = False


@contextlib.contextmanager
def _auto_validation():
    global _sg_auto
    old = _sg_auto
    _sg_auto = True
    try:
        yield
    finally:
        _sg_auto = old


def _setting(key):
    return sg_state.setting(key)


def _net_worth(sim_info):
    if sim_info is None:
        return 0
    household = getattr(sim_info, "household", None)
    if household is None:
        return 0
    try:
        return int(household.household_net_worth())
    except Exception:
        try:
            return int(household.funds.money)
        except Exception:
            sg_log.log_exception("net worth for " + sg_state.sim_name(sim_info))
            return 0


# --- Finding the club the player is working on -----------------------------------------
def _editing_club():
    """The club led by the active household, if there is one.

    The club UI does not pass the club id to the commands that validate candidates, so this
    is how the relative wealth rule knows which leader's net worth to use. Household members
    share a net worth, so it does not matter which of them leads the club.
    """
    try:
        service = services.get_club_service()
        household = services.active_household()
        if service is None or household is None:
            return None
        member_ids = {sim_info.sim_id for sim_info in household}
        led = []
        for club in service.clubs:
            leader = getattr(club, "leader", None)
            if leader is not None and leader.sim_id in member_ids:
                led.append(club)
        # Prefer a player club: it is the one whose admission rules the mod changes.
        for club in led:
            if getattr(club, "club_seed", None) is None:
                return club
        return led[0] if led else None
    except Exception:
        sg_log.log_exception("finding the club being edited")
    return None


def _criteria_club(criteria):
    """The club a criteria object belongs to, falling back to the club being edited."""
    if getattr(criteria, "_sg_business", False):
        return None
    club = getattr(criteria, "_club", None)
    if isinstance(club, weakref.ReferenceType):
        club = club()
    if club is not None:
        return club
    return _editing_club()


def _relative_wealth_applies(club):
    """True when this club's household-value checks are relative to its leader."""
    if club is None or _sg_business_ui or not _setting("club_relative_wealth"):
        return False
    return getattr(club, "club_seed", None) is None or bool(_setting("club_enforce_premade"))


def _relative_labels_for(club):
    """Labels follow the same policy as the check. No club means a club being created."""
    if _sg_business_ui or not _setting("club_relative_wealth"):
        return False
    return club is None or _relative_wealth_applies(club)


def _leader_net_worth(club):
    leader = getattr(club, "leader", None) if club is not None else services.active_sim_info()
    return _net_worth(leader)


def _club_label(club):
    """The club's player-facing name. str(club) is its internal "name_id" form."""
    try:
        name = club.name
        if name is not None:
            return name
    except Exception:
        sg_log.log_exception("club name")
    return str(club)


def _friendship_score(a, b):
    """Friendship track score, or None when it can't be read. Household members count as friends."""
    if a is None or b is None:
        return None
    try:
        if a.household is not None and a.household is b.household:
            return 100.0
    except Exception:
        pass
    try:
        from relationships.relationship_track import RelationshipTrack
        return a.relationship_tracker.get_relationship_score(
            b.sim_id, RelationshipTrack.FRIENDSHIP_TRACK)
    except Exception:
        sg_log.log_exception("friendship score {} / {}".format(
            sg_state.sim_name(a), sg_state.sim_name(b)))
        return None


def _is_friend(a, b):
    try:
        threshold = int(_setting("friend_min_score"))
    except Exception:
        threshold = 20
    return is_friend(_friendship_score(a, b), threshold)


# --- Sims, traits and skills -----------------------------------------------------------
def _sim_traits(sim_info):
    try:
        return set(sim_info.trait_tracker.get_traits())
    except Exception:
        try:
            return set(sim_info.trait_tracker.equipped_traits)
        except Exception:
            sg_log.log_exception("traits for " + sg_state.sim_name(sim_info))
            return set()


def _skill_level(sim_info, skill_type):
    try:
        stat = sim_info.get_stat_instance(skill_type)
        if stat is not None:
            return stat.get_user_value()
    except Exception:
        pass
    return 0


def _skill_levels(sim_info, skill_types):
    return {skill: _skill_level(sim_info, skill) for skill in skill_types}


def _all_skill_levels(sim_info):
    """Every skill the Sim has, keyed by skill type.

    Needed for clubs whose rules are in the game's SKILL category: "any skill-based
    activity" must see skills that the club's own rules never mention, so this cannot be
    filtered down to the club's requirement list.
    """
    levels = {}
    try:
        skills = sim_info.all_skills()
    except Exception:
        sg_log.log_exception("all skills for " + sg_state.sim_name(sim_info))
        return levels
    for skill in skills:
        try:
            if not getattr(skill, "is_skill", False):
                continue
            levels[getattr(skill, "stat_type", skill)] = skill.get_user_value()
        except Exception:
            sg_log.log_exception("reading skill " + str(skill))
    return levels


def _affordance_skill(affordance):
    """The skill an interaction trains, using either of the game's two ways of saying it."""
    for getter in ("get_associated_skill", "stat_from_skill_loot_data"):
        try:
            skill = getattr(affordance, getter)()
        except Exception:
            continue
        if skill is not None:
            # Both APIs normally return a skill statistic type, but some interactions return
            # an instance; the type is the stable key.
            return getattr(skill, "stat_type", skill)
    return None


def _club_requirements(club):
    """Traits/skills/wealth from membership criteria, plus the skills the club's rules use."""
    from clubs.club_tuning import (ClubInteractionGroupCategory, ClubRuleCriteriaHouseholdValue,
                                   ClubRuleCriteriaSkill, ClubRuleCriteriaTrait)

    traits = set()
    skills = set()
    wealth = []
    for criteria in getattr(club, "membership_criteria", ()):
        if isinstance(criteria, ClubRuleCriteriaTrait):
            traits.update(criteria.traits)
        elif isinstance(criteria, ClubRuleCriteriaSkill):
            skills.update(criteria.skills)
        elif isinstance(criteria, ClubRuleCriteriaHouseholdValue):
            wealth.append(criteria.household_value)

    activity_skills = set()
    activity_any_skill = False
    for rule in getattr(club, "rules", ()):
        group = getattr(rule, "action", None)
        if group is None:
            continue
        try:
            if getattr(group, "category", None) == ClubInteractionGroupCategory.SKILL:
                activity_any_skill = True
            for affordance in group_affordances(group):
                skill = _affordance_skill(affordance)
                if skill is not None:
                    activity_skills.add(skill)
        except Exception:
            sg_log.log_exception("reading club rule " + str(group))

    return {"traits": traits, "skills": skills, "wealth": wealth,
            "activity_skills": activity_skills, "activity_any": activity_any_skill}


def _minimum_skill_level():
    try:
        from clubs.club_tuning import ClubTunables
        return int(ClubTunables.MINIMUM_CRITERIA_SKILL_LEVEL)
    except Exception:
        return 1


def _admission_result(sim_info, club):
    requirements = _club_requirements(club)
    skills = _skill_levels(sim_info, requirements["skills"] | requirements["activity_skills"])
    if requirements["activity_any"]:
        # "Any skill-based activity" means the Sim's whole skill list, not just the
        # skills this club happens to name.
        skills.update(_all_skill_levels(sim_info))
    leader = getattr(club, "leader", None)
    relative_wealth = bool(_setting("club_relative_wealth"))
    return club_admission(
        _sim_traits(sim_info), skills,
        wealth_categories=requirements["wealth"] if relative_wealth else (),
        candidate_net_worth=_net_worth(sim_info),
        leader_net_worth=_net_worth(leader),
        band=float(_setting("club_wealth_band")),
        relative_wealth=relative_wealth,
        trait_requirements=requirements["traits"],
        skill_requirements=requirements["skills"],
        activity_skills=requirements["activity_skills"],
        activity_any_skill=requirements["activity_any"],
        require_restriction=bool(_setting("club_require_restriction")),
        activity_skill_min=int(_setting("club_activity_skill_min")),
        min_skill_level=_minimum_skill_level())


# --- Doors: only friends get let in ----------------------------------------------------
def _owner_household():
    try:
        household_id = services.current_zone().lot.zone_owner_household_id
        if not household_id:
            return None
        return services.household_manager().get(household_id)
    except Exception:
        sg_log.log_exception("owner household")
        return None


def _owner_household_is_active():
    try:
        owner_id = services.current_zone().lot.zone_owner_household_id
        return bool(owner_id) and owner_id == services.active_household_id()
    except Exception:
        return False


def _always_welcome(sim, household):
    try:
        if household is not None and sim.id in household.always_welcomed_sims:
            return True
    except Exception:
        pass
    try:
        from situations.visiting.visiting_tuning import VisitingTuning
        if any(sim.sim_info.has_trait(trait) for trait in VisitingTuning.ALWAYS_WELCOME_TRAITS):
            return True
    except Exception:
        pass
    return False


def _show_door_refusal(interaction):
    """EA's "not enough relationship" notification, with a plain fallback.

    The notification is a tunable on RingDoorbellSuperInteraction in EA's scripts
    (_bad_relationship_failure_notification). If a patch renames it, we still want to
    refuse entry: an escaping exception would fall through to the original and let the
    Sim in.
    """
    try:
        dialog = interaction._bad_relationship_failure_notification(
            interaction.sim, interaction.get_resolver())
        dialog.show_dialog()
        return
    except Exception:
        sg_log.log_exception("door refusal dialog")
    try:
        sg_state.notify("Not invited in",
                        "Nobody here is close enough to let them in.",
                        getattr(interaction.sim, "sim_info", None))
    except Exception:
        sg_log.log_exception("door refusal notification")


def _install_door_gate():
    from situations.visiting.visiting_interactions import RingDoorbellSuperInteraction

    original = RingDoorbellSuperInteraction._try_to_be_invited_in

    def _try_to_be_invited_in(self):
        try:
            if _setting("doors") and not getattr(self, "_always_allow_greeting", False):
                if not _owner_household_is_active():
                    household = _owner_household()
                    if not _always_welcome(self.sim, household):
                        owners = self._get_owner_sim_infos()
                        if owners and not any(_is_friend(self.sim.sim_info, owner)
                                              for owner in owners):
                            names = ", ".join(sg_state.sim_name(owner) for owner in owners)
                            sg_log.log("door: {} is not a friend of {}; not letting them in".format(
                                sg_state.sim_name(self.sim.sim_info), names))
                            _show_door_refusal(self)
                            return
        except Exception:
            sg_log.log_exception("door gate")
        return original(self)

    RingDoorbellSuperInteraction._try_to_be_invited_in = _try_to_be_invited_in


# --- Invites: only friends are invited over ---------------------------------------------
def _is_invite_over_situation(situation_type):
    name = getattr(situation_type, "__name__", "")
    if "InviteOver" in name or "Invite_Over" in name:
        return True
    try:
        from situations.visiting.invite_over_situation import InviteOverSituation
        return isinstance(situation_type, type) and issubclass(situation_type, InviteOverSituation)
    except Exception:
        return False


def _purpose_is_invite_over(purpose):
    name = getattr(purpose, "name", "") or ""
    upper = name.upper()
    return "INVITE" in upper and "OVER" in upper


def _guest_list_host(guest_list):
    try:
        host = guest_list.host_sim_info
        if host is not None:
            return host
    except Exception:
        pass
    try:
        return services.active_sim_info()
    except Exception:
        return None


def _invited_sim_infos(guest_list):
    try:
        return [sim_info for sim_info in guest_list.invited_sim_infos_gen() if sim_info is not None]
    except Exception:
        return []


def _declined_invite(host, invited):
    names = ", ".join(sg_state.sim_name(sim_info) for sim_info in invited)
    sg_log.log("invite: {} is not a friend of {}; declining".format(
        names, sg_state.sim_name(host) if host is not None else "the host"))
    sg_state.notify("Invite declined",
                    "{} isn't a close enough friend to come over.".format(names), host)


def _install_invite_gate():
    from situations.situation_manager import SituationManager

    original_create = SituationManager.create_situation

    def create_situation(self, situation_type, guest_list=None, *args, **kwargs):
        try:
            if _setting("invites") and guest_list is not None and _is_invite_over_situation(situation_type):
                host = _guest_list_host(guest_list)
                active = services.active_sim_info()
                # Only decide this for an invite the player is sending. If the game is
                # creating the situation for an NPC who invited the player, the invite-over
                # backstop below checks the NPC as the host instead.
                if host is not None and active is not None and host.sim_id == active.sim_id:
                    invited = _invited_sim_infos(guest_list)
                    if invited and not all(_is_friend(host, sim_info) for sim_info in invited):
                        _declined_invite(host, [sim_info for sim_info in invited
                                                if not _is_friend(host, sim_info)])
                        return None
        except Exception:
            sg_log.log_exception("invite gate")
        return original_create(self, situation_type, guest_list, *args, **kwargs)

    SituationManager.create_situation = create_situation

    from situations.visiting.invite_over_situation import InviteOverSituation

    original_invite_in = InviteOverSituation._invite_sim_in

    def _invite_sim_in(self):
        try:
            invited = getattr(self, "_invited_sim", None)
            host = getattr(self, "initiating_sim_info", None)
            # Only the player's own invites are gated: an NPC inviting the player over is
            # the NPC's decision, not an acceptance the player is waiting on.
            if (_setting("invites") and invited is not None and host is not None
                    and host.is_selectable):
                if not _is_friend(host, invited.sim_info):
                    _declined_invite(host, [invited.sim_info])
                    self._self_destruct()
                    return
        except Exception:
            sg_log.log_exception("invite backstop")
        return original_invite_in(self)

    InviteOverSituation._invite_sim_in = _invite_sim_in

    try:
        from venues.venue_tuning import Venue

        original_summon = Venue.summon_npcs

        def summon_npcs(self, npc_infos, purpose, host_sim_info=None):
            try:
                if (_setting("invites") and host_sim_info is not None
                        and host_sim_info.is_selectable and _purpose_is_invite_over(purpose)):
                    invited = [sim_info for sim_info in (npc_infos or ()) if sim_info is not None]
                    if invited and not all(_is_friend(host_sim_info, sim_info) for sim_info in invited):
                        _declined_invite(host_sim_info,
                                         [sim_info for sim_info in invited if not _is_friend(host_sim_info, sim_info)])
                        return
            except Exception:
                sg_log.log_exception("summon invite gate")
            return original_summon(self, npc_infos, purpose, host_sim_info)

        Venue.summon_npcs = summon_npcs
    except Exception:
        sg_log.log_exception("wrapping venue summons")


# --- Clubs: admission, relative wealth and grandfathering ------------------------------
def _club_gate_active(club):
    try:
        if not _setting("clubs") or _sg_auto:
            return False
        if getattr(club, "member_ids", None) is not None:
            return False  # loading saved members
        if getattr(club, "club_seed", None) is not None and not _setting("club_enforce_premade"):
            return False  # the game's own clubs are left alone by default
        return True
    except Exception:
        sg_log.log_exception("club gate check")
        return False


def _install_club_gates():
    from clubs.club import Club
    from clubs.club_service import ClubService
    from clubs.club_tuning import ClubRuleCriteriaHouseholdValue

    original_add_member = Club.add_member

    def add_member(self, member, distribute=True):
        try:
            if (member is not None and self.leader is not member and _club_gate_active(self)):
                ok, reason = _admission_result(member, self)
                if not ok:
                    sg_log.log("club: {} not admitted to {}: {}".format(
                        sg_state.sim_name(member), str(self), reason))
                    return False
        except Exception:
            sg_log.log_exception("club add_member gate")
        return original_add_member(self, member, distribute)

    Club.add_member = add_member

    original_can_join = Club.can_sim_info_join

    def can_sim_info_join(self, new_sim_info):
        try:
            if (new_sim_info is not None and self.leader is not new_sim_info
                    and _club_gate_active(self)):
                ok, reason = _admission_result(new_sim_info, self)
                if not ok:
                    sg_log.log("club: {} cannot join {}: {}".format(
                        sg_state.sim_name(new_sim_info), str(self), reason))
                    return False
        except Exception:
            sg_log.log_exception("club can_join gate")
        return original_can_join(self, new_sim_info)

    Club.can_sim_info_join = can_sim_info_join

    # For player-created clubs, wealth is ours to check (relative to the leader). Skipping
    # EA's bracket test is what stops money changes from removing existing members.
    original_validate_criteria = Club._validate_member_against_criteria

    def _validate_member_against_criteria(self, member, criteria, update_if_invalid=False):
        try:
            if (_setting("club_relative_wealth")
                    and isinstance(criteria, ClubRuleCriteriaHouseholdValue)
                    and (getattr(self, "club_seed", None) is None or _setting("club_enforce_premade"))):
                return True
        except Exception:
            sg_log.log_exception("club wealth validation skip")
        return original_validate_criteria(self, member, criteria, update_if_invalid)

    Club._validate_member_against_criteria = _validate_member_against_criteria

    # Remember which club a saved criterion belongs to, so the UI's own candidate checks
    # (which use criteria.test_sim_info) can use the same leader-relative range as the gate.
    original_add_criteria = Club.add_membership_criteria

    def add_membership_criteria(self, criteria):
        try:
            if isinstance(criteria, ClubRuleCriteriaHouseholdValue):
                criteria._club = weakref.ref(self)
        except Exception:
            sg_log.log_exception("attaching club to wealth criteria")
        return original_add_criteria(self, criteria)

    Club.add_membership_criteria = add_membership_criteria

    original_test_sim_info = ClubRuleCriteriaHouseholdValue.test_sim_info

    def test_sim_info(self, sim_info):
        try:
            club = _criteria_club(self)
            if not getattr(self, "_sg_business", False) and _relative_wealth_applies(club):
                if sim_info is not None and sim_info is getattr(club, "leader", None):
                    return True
                return in_wealth_range(
                    self.household_value, _net_worth(sim_info),
                    _net_worth(getattr(club, "leader", None)),
                    float(_setting("club_wealth_band")))
        except Exception:
            sg_log.log_exception("club wealth test")
        return original_test_sim_info(self, sim_info)

    ClubRuleCriteriaHouseholdValue.test_sim_info = test_sim_info

    original_loaded = Club.on_all_households_and_sim_infos_loaded

    def on_all_households_and_sim_infos_loaded(self, client):
        with _auto_validation():
            return original_loaded(self, client)

    Club.on_all_households_and_sim_infos_loaded = on_all_households_and_sim_infos_loaded

    original_update = ClubService.update_club_from_data

    def update_club_from_data(self, club_data):
        result = original_update(self, club_data)
        try:
            if _setting("clubs") and _setting("club_enforce_on_edit"):
                club = self.get_club_by_id(club_data.club_id)
                if (club is not None and club.leader is not None
                        and (getattr(club, "club_seed", None) is None or _setting("club_enforce_premade"))):
                    removed = []
                    for member in tuple(club.members):
                        if member is club.leader:
                            continue
                        ok, reason = _admission_result(member, club)
                        if not ok:
                            removed.append((sg_state.sim_name(member), reason))
                            club.remove_member(member)
                    if removed:
                        sg_log.log("club edit: {} removed {}".format(str(club), removed))
                        sg_state.notify(
                            "Club members removed",
                            _localized_string(
                                CLUB_MEMBERS_REMOVED, _club_label(club),
                                "; ".join("{} ({})".format(name, reason)
                                          for name, reason in removed[:3])),
                            services.active_sim_info())
        except Exception:
            sg_log.log_exception("club edit re-check")
        return result

    ClubService.update_club_from_data = update_club_from_data


# --- Cheats ----------------------------------------------------------------------------
def _setting_text(key, settings):
    value = settings.get(key)
    if settings.is_switch(key):
        return "on" if value else "off"
    return str(value)


@sims4.commands.Command("houserules.gates.status", command_type=sims4.commands.CommandType.Live)
def gates_status(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    settings = sg_state.ensure_settings()
    output("Social Gates: " + ", ".join(
        "{} = {}".format(key, _setting_text(key, settings)) for key in DEFAULT_SETTINGS))
    output("Change one with: houserules.gates.set <setting> on|off|number")


@sims4.commands.Command("houserules.gates.set", command_type=sims4.commands.CommandType.Live)
def gates_set(key: str = "", value: str = "", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    settings = sg_state.ensure_settings()
    if key not in DEFAULT_SETTINGS:
        output("Settings: {}".format(", ".join(DEFAULT_SETTINGS)))
        return
    try:
        if settings.is_switch(key):
            if value.lower() not in ("on", "off", "true", "false", "1", "0"):
                output("Usage: houserules.gates.set {} on|off".format(key))
                return
            settings.set(key, value.lower() in ("on", "true", "1"))
        elif isinstance(DEFAULT_SETTINGS[key], float):
            settings.set(key, float(value))
        else:
            settings.set(key, int(value))
    except ValueError:
        output("{} needs a number".format(key))
        return
    sg_state.save_settings()
    sg_log.log("setting {} = {}".format(key, settings.get(key)))
    output("Social Gates: {} is now {}.".format(key, _setting_text(key, settings)))


@sims4.commands.Command("houserules.gates.check", command_type=sims4.commands.CommandType.Live)
def gates_check(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = get_optional_target(opt_sim, _connection, target_type=OptionalSimInfoParam)
    if sim_info is None:
        output("No sim found (select one or pass a sim id).")
        return
    club_service = services.get_club_service()
    if club_service is None:
        output("No club service.")
        return
    output("{}: household net worth {}, friend threshold {}".format(
        sg_state.sim_name(sim_info), _net_worth(sim_info), _setting("friend_min_score")))
    clubs = list(club_service.clubs)
    if not clubs:
        output("No clubs.")
        return
    for club in clubs:
        reqs = _club_requirements(club)
        ok, reason = _admission_result(sim_info, club)
        member = sim_info in club.members
        output("{}: {}{} - {}".format(
            str(club), "member" if member else "not a member",
            " (leader)" if club.leader is sim_info else "",
            "passes" if ok else "FAILS") + ": " + reason)
        output("  traits {} / skills {} / wealth {} / activity skills {}".format(
            len(reqs["traits"]), len(reqs["skills"]), len(reqs["wealth"]),
            len(reqs["activity_skills"]) + (1 if reqs["activity_any"] else 0)))


@sims4.commands.Command("houserules.gates.clubs", command_type=sims4.commands.CommandType.Live)
def gates_clubs(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    club_service = services.get_club_service()
    if club_service is None:
        output("No club service.")
        return
    for club in club_service.clubs:
        reqs = _club_requirements(club)
        output("{} ({}): {} members, leader {}, {} trait(s), {} skill(s), {} wealth, "
               "{} activity skill(s){}".format(
                   str(club), "game club" if club.club_seed is not None else "player club",
                   len(club.members), sg_state.sim_name(club.leader) if club.leader else "none",
                   len(reqs["traits"]), len(reqs["skills"]), len(reqs["wealth"]),
                   len(reqs["activity_skills"]),
                   " + any skill-based activity" if reqs["activity_any"] else ""))


@sims4.commands.Command("houserules.gates.wealth", command_type=sims4.commands.CommandType.Live)
def gates_wealth(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    club_service = services.get_club_service()
    if club_service is None:
        output("No club service.")
        return
    band = float(_setting("club_wealth_band"))
    for club in club_service.clubs:
        if club.leader is None:
            continue
        area = "game club (not enforced)" if club.club_seed is not None and not _setting("club_enforce_premade") \
            else "player club"
        output("{} [{}]: {:,} -> {}".format(
            str(club), area, _net_worth(club.leader), wealth_description(_net_worth(club.leader), band)))


@sims4.commands.Command("houserules.gates.invite", command_type=sims4.commands.CommandType.Live)
def gates_invite(other_sim_id: int = 0, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    actor = services.active_sim_info()
    other = services.sim_info_manager().get(other_sim_id) if other_sim_id else None
    if actor is None or other is None:
        output("Usage: houserules.gates.invite <other sim id> (with an active sim).")
        return
    score = _friendship_score(actor, other)
    output("{} -> {}: friendship {}, friend threshold {}, {}".format(
        sg_state.sim_name(actor), sg_state.sim_name(other),
        "unknown" if score is None else score, _setting("friend_min_score"),
        "friends" if _is_friend(actor, other) else "not friends"))


# --- Club labels: say "relative to the leader" in the rule screen -----------------------
def _localized_string(text, *tokens):
    """A LocalizedString the game localizes from the string table built from text/*.txt."""
    from protocolbuffers.Localization_pb2 import LocalizedString
    localized = LocalizedString()
    localized.hash = string_key(text)
    if tokens:
        from sims4.localization import create_tokens
        create_tokens(localized.tokens, *tokens)
    return localized


def _relative_wealth_name(category, club, with_ranges):
    """The label for a household-value option, including its current § range if possible."""
    if not _relative_labels_for(club):
        return None
    if with_ranges:
        ranged = relative_wealth_label_with_ranges(
            category, _leader_net_worth(club), float(_setting("club_wealth_band")))
        if ranged is not None:
            template, tokens = ranged
            return _localized_string(template, *tokens)
    label = relative_wealth_label(category)
    return _localized_string(label) if label else None


def _install_club_labels():
    """Relabel the club rule screen's household-value options.

    The game's names ("Poor: Less than 10,000") state fixed ranges, but under
    club_relative_wealth the club check compares against the club leader. The choices show
    the leader's current § range; a saved criterion keeps the short label so it cannot go
    stale when the leader's household value changes. The options keep their enum values and
    icons, and small-business rules keep the game's wording and brackets.
    """
    from clubs.club_service import ClubService
    from clubs.club_tuning import ClubRuleCriteriaHouseholdValue

    original_populate = ClubRuleCriteriaHouseholdValue._populate_criteria_info

    def populate_criteria_info(cls, criteria_info, household_value):
        result = original_populate(criteria_info, household_value)
        try:
            name = _relative_wealth_name(household_value, _editing_club(), with_ranges=True)
            if name is not None:
                criteria_info.name = name
        except Exception:
            sg_log.log_exception("club wealth label")
        return result

    ClubRuleCriteriaHouseholdValue._populate_criteria_info = classmethod(populate_criteria_info)

    original_save = ClubRuleCriteriaHouseholdValue.save

    def save(self, club_criteria):
        result = original_save(self, club_criteria)
        try:
            infos = getattr(club_criteria, "criteria_infos", None)
            if infos:
                name = None
                if not getattr(self, "_sg_business", False):
                    name = _relative_wealth_name(self.household_value, _criteria_club(self),
                                                 with_ranges=False)
                if name is not None:
                    infos[0].name = name
                else:
                    original_populate(infos[0], self.household_value)
        except Exception:
            sg_log.log_exception("club wealth saved label")
        return result

    ClubRuleCriteriaHouseholdValue.save = save

    original_send = ClubService.send_club_building_info

    def send_club_building_info(is_business=False):
        global _sg_business_ui
        # Kept until the next screen opens: the validation commands that follow use it too.
        _sg_business_ui = bool(is_business)
        return original_send(is_business)

    ClubService.send_club_building_info = staticmethod(send_club_building_info)
    sg_log.log("club labels: household value reads as poorer/similar/richer than the leader")


def _install_business_criteria_marker():
    """Mark small-business criteria, so club labels and relative wealth never touch them."""
    try:
        from small_business.small_business_manager import SmallBusinessManager
    except Exception:
        return  # pack not installed
    original = SmallBusinessManager._load_specific_criteria

    def load_specific_criteria(self, criteria_data):
        criteria = original(self, criteria_data)
        try:
            if criteria is not None:
                criteria._sg_business = True
        except Exception:
            pass
        return criteria

    SmallBusinessManager._load_specific_criteria = load_specific_criteria


def _install():
    try:
        _install_door_gate()
    except Exception:
        sg_log.log_exception("installing door gate")
    try:
        _install_invite_gate()
    except Exception:
        sg_log.log_exception("installing invite gate")
    try:
        _install_club_gates()
    except Exception:
        sg_log.log_exception("installing club gates")
    try:
        _install_club_labels()
    except Exception:
        sg_log.log_exception("installing club labels")
    try:
        _install_business_criteria_marker()
    except Exception:
        sg_log.log_exception("installing business criteria marker")
    sg_log.log("loaded")


_install()
