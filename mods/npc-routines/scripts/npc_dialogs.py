"""NPC Routines phase 2 - an in-game routine editor made of the game's own picker dialogs,
plus the cheats for phase 4 (the local-LLM brain).

A real "NPC Routine..." entry in a sim's pie menu needs an interaction defined in tuning
(a .package made in Sims 4 Studio). Until then, one cheat opens the editor:

  houserules.routine.edit [sim]   - menu: add an activity / show / clear / NPC mode on-off
      Add: activity -> days (pick several) -> start time -> how long

Local LLM (optional; needs Ollama or LM Studio running on this computer):
  houserules.npc.start [name|all]        - start the LLM brain (default: selected sim)
  houserules.npc.stop [name|all]         - stop it again
  houserules.npc.goal <text...>          - what this sim is working towards
  houserules.npc.goal_clear [sim]
  houserules.npc.brain <text...> [sim]   - what this sim is like / wants (free text)
  houserules.npc.brain_clear [sim]
  houserules.npc.brain_show [sim]        - shows the goal and the description
  houserules.npc.llm <url> <model>       - default http://localhost:11434/api/generate qwen2.5:3b-instruct
  houserules.npc.llm_test [sim]          - ask now; the answer is applied a few seconds later
  houserules.npc.actions [sim]           - what the brain is offered for this sim right now
  houserules.npc.think [sim]             - show the last prompt and answer (and thinking, if any)
  houserules.npc.reasoning on|off        - ask a thinking model for its working too (needs qwen3 etc.)

JSON rules (the main way to run a sim):
  houserules.npc.rules_list              - rule files in Mods\HouseRules\data\rules
  houserules.npc.rules_load <file> [sim|all] - load rules/painter.json onto a sim (or everyone)
  houserules.npc.rules_pick [sim]        - same, from a menu of the files in data/rules
  houserules.npc.rules_show [sim]        - the rules assigned to a sim, and what would fire now
  houserules.npc.rules_test [sim]        - evaluate without doing anything
  houserules.npc.rules_clear [sim|all]   - remove them (the sim goes back to routine/LLM)
"""
import json

import services
import sims4.commands
from server_commands.argument_helpers import OptionalSimInfoParam, get_optional_target
from sims4.localization import LocalizationHelperTuning
from ui.ui_dialog_picker import ObjectPickerRow, UiDialogObjectPicker, UiObjectPicker

import npc_llm
import npc_log
import npc_main
import npc_rules
from npc_routine import ACTIVITIES, DAY_NAMES, RoutineEntry

_DAY_LABELS = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
_LENGTHS = (1, 2, 3, 4, 6, 8, 12, 24)


def _raw(text):
    return LocalizationHelperTuning.get_raw_text(text)


def _pick(sim_info, title, text, options, callback, multi=False):
    """options: [(label, value)]. callback(list_of_values) runs only if the player clicks OK."""
    dialog = UiObjectPicker.TunableFactory().default(
        sim_info,
        text=lambda *_, **__: _raw(text),
        title=lambda *_, **__: _raw(title),
        min_selectable=1,
        # Built directly, not from tuning, so every field must be given: AutoFactoryInit fills in
        # only what's passed (exclude_previously_selected missing crashed the picker, 2026-10-13).
        max_selectable=UiDialogObjectPicker._MaxSelectableStatic(
            number_selectable=len(options) if multi else 1, exclude_previously_selected=False),
        is_sortable=False,
        picker_type=UiObjectPicker.UiObjectPickerObjectPickerType.OBJECT)
    for i, (label, value) in enumerate(options):
        dialog.add_row(ObjectPickerRow(option_id=i, name=_raw(label), tag=value))

    def on_response(d):
        try:
            if d.accepted:
                callback(d.get_result_tags())
        except Exception:
            npc_log.log_exception("routine editor: {}".format(title))

    dialog.add_listener(on_response)
    dialog.show_dialog()


def _hour_label(h):
    return "{}:00 ({})".format(h, "{} {}".format(h % 12 or 12, "am" if h < 12 else "pm"))


def open_editor(sim_info):
    npc_main._ensure_loaded()
    sim_id = sim_info.sim_id
    on = sim_id in npc_main._npc_mode_sim_ids
    options = [("Add an activity", "add"), ("Show the routine", "show"), ("Clear the routine", "clear"),
               ("Load a JSON rule routine", "rules"),
               ("Turn NPC mode {}".format("off" if on else "on"), "toggle")]
    _pick(sim_info, "NPC Routine: {}".format(sim_info.first_name),
          "NPC mode is {}. What would you like to do?".format("ON" if on else "off"),
          options, lambda picked: _menu_choice(sim_info, picked[0]))


def _menu_choice(sim_info, choice):
    sim_id = sim_info.sim_id
    if choice == "add":
        _pick(sim_info, "Activity", "What should {} do?".format(sim_info.first_name),
              [(a.capitalize(), a) for a in sorted(ACTIVITIES)],
              lambda picked: _choose_days(sim_info, picked[0]))
    elif choice == "show":
        routine = npc_main._store.get(sim_id)
        text = "\n".join(str(e) for e in routine.entries) or "No activities yet."
        npc_main._notify(sim_info, "{}'s routine".format(sim_info.first_name), text)
    elif choice == "clear":
        npc_main._store.get(sim_id).clear()
        npc_main._save()
        npc_log.log("routine editor: cleared sim {}".format(sim_id))
        npc_main._notify(sim_info, "Routine cleared", "{} has no routine activities now.".format(sim_info.first_name))
    elif choice == "rules":
        _choose_rule_file(sim_info)
    elif choice == "toggle":
        if sim_id in npc_main._npc_mode_sim_ids:
            npc_main._npc_mode_sim_ids.discard(sim_id)
        else:
            npc_main._npc_mode_sim_ids.add(sim_id)
        npc_main._save_npc_mode()
        on = sim_id in npc_main._npc_mode_sim_ids
        npc_log.log("routine editor: NPC mode {} for sim {}".format("on" if on else "off", sim_id))
        npc_main._notify(sim_info, "NPC mode {}".format("on" if on else "off"),
                         "{} {} follow their routine.".format(sim_info.first_name, "will now" if on else "won't"))


def _choose_days(sim_info, activity):
    _pick(sim_info, "Days", "On which days? (pick as many as you like)",
          [(label, d) for d, label in enumerate(_DAY_LABELS)],
          lambda days: _choose_start(sim_info, activity, sorted(days)), multi=True)


def _choose_start(sim_info, activity, days):
    _pick(sim_info, "Start time", "When does {} start?".format(activity),
          [(_hour_label(h), h) for h in range(24)],
          lambda picked: _choose_length(sim_info, activity, days, picked[0]))


def _choose_length(sim_info, activity, days, start):
    _pick(sim_info, "How long", "For how many hours?",
          [("{} hour{}".format(n, "" if n == 1 else "s") if n < 24 else "All day", n) for n in _LENGTHS],
          lambda picked: _add_entry(sim_info, activity, days, start, picked[0]))


def _add_entry(sim_info, activity, days, start, length):
    entry = RoutineEntry(days, start, length, activity)
    npc_main._store.get(sim_info.sim_id).add(entry)
    npc_main._save()
    npc_log.log("routine editor: sim {} added {}".format(sim_info.sim_id, entry))
    npc_main._notify(sim_info, "Routine updated", "Added: {} on {} from {}:00 for {} hour(s).{}".format(
        activity, ", ".join(DAY_NAMES[d] for d in entry.days), start, length,
        "" if sim_info.sim_id in npc_main._npc_mode_sim_ids else " (NPC mode is off - turn it on to use it.)"))


def _target(opt_sim, _connection):
    return get_optional_target(opt_sim, _connection, target_type=OptionalSimInfoParam)


@sims4.commands.Command("houserules.routine.edit", command_type=sims4.commands.CommandType.Live)
def routine_edit(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _target(opt_sim, _connection)
    if sim_info is None:
        output("No sim found (select one or pass a sim id).")
        return
    try:
        open_editor(sim_info)
    except Exception:
        npc_log.log_exception("routine.edit")
        output("routine.edit failed - see the log.")


# --- Phase 4 cheats ---------------------------------------------------------------------------
def _household_sims():
    household = services.active_household()
    return list(household.sim_info_gen()) if household is not None else []


def _matching_sims(words):
    """Selected sim by default, every household sim for "all", else match by name or id."""
    sims = _household_sims()
    if not words:
        sim_info = services.active_sim_info()
        return [sim_info] if sim_info is not None else []
    text = " ".join(str(w) for w in words).strip().lower()
    if text == "all":
        return sims
    if text.isdigit():
        return [sim for sim in sims if str(sim.sim_id) == text]
    matches = []
    for sim_info in sims:
        first = (getattr(sim_info, "first_name", "") or "").lower()
        last = (getattr(sim_info, "last_name", "") or "").lower()
        full = (first + " " + last).strip()
        if text in (first, full) or (len(text) >= 3 and text in full):
            matches.append(sim_info)
    return matches


@sims4.commands.Command("houserules.npc.start", command_type=sims4.commands.CommandType.Live)
def npc_start(*words, _connection=None):
    """Start the LLM brain: selected sim by default, a sim name, or "all" in the household."""
    output = sims4.commands.CheatOutput(_connection)
    sims = _matching_sims(words)
    if not sims:
        output("No matching sim. Usage: houserules.npc.start [name|all] "
               "(default: the selected sim)")
        return
    npc_main._ensure_loaded()
    available = npc_llm.reachable()
    started, needs_text = [], []
    for sim_info in sims:
        npc_main._npc_mode_sim_ids.add(sim_info.sim_id)
        if not (npc_llm.goal_for(sim_info.sim_id) or npc_llm.instructions_for(sim_info.sim_id)):
            needs_text.append(sim_info.first_name)
            continue
        # This is the switch the start-llm watcher waits for: only now does a model get used.
        npc_llm.mark_active(sim_info.sim_id)
        if not available:
            continue
        npc_main._ask_now(sim_info, output)
        started.append(sim_info.first_name)
    npc_main._save_npc_mode()
    if not available:
        output("The local LLM isn't reachable - start start-llm.cmd. NPC mode is on; "
               "routines will be used until it is running.")
    if started:
        output("Started the LLM for {}; the answer is applied in a few seconds.".format(
            ", ".join(started)))
    if needs_text:
        output("No goal or description yet for {} - set one with houserules.npc.goal.".format(
            ", ".join(needs_text)))


@sims4.commands.Command("houserules.npc.stop", command_type=sims4.commands.CommandType.Live)
def npc_stop(*words, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sims = _matching_sims(words)
    if not sims:
        output("No matching sim. Usage: houserules.npc.stop [name|all]")
        return
    npc_main._ensure_loaded()
    for sim_info in sims:
        npc_main._npc_mode_sim_ids.discard(sim_info.sim_id)
        npc_main._forget(sim_info.sim_id)
    npc_main._save_npc_mode()
    output("Stopped the LLM for {}.".format(", ".join(s.first_name for s in sims)))


@sims4.commands.Command("houserules.npc.brain", command_type=sims4.commands.CommandType.Live)
def npc_brain(*words, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = services.active_sim_info()
    if sim_info is None or not words:
        output("Usage: houserules.npc.brain <what this sim is like and wants> (for the selected sim)")
        return
    text = " ".join(str(w) for w in words)
    npc_llm.set_instructions(sim_info.sim_id, text)
    npc_log.log("npc.brain sim {}: {}".format(sim_info.sim_id, text))
    output("Saved for {}: {}".format(sim_info.first_name, text))
    output("Start it with houserules.npc.start (or start all).")


@sims4.commands.Command("houserules.npc.goal", command_type=sims4.commands.CommandType.Live)
def npc_goal(*words, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = services.active_sim_info()
    if sim_info is None or not words:
        output("Usage: houserules.npc.goal <what this sim is working towards> (for the selected sim)")
        return
    text = " ".join(str(w) for w in words)
    npc_llm.set_goal(sim_info.sim_id, text)
    npc_log.log("npc.goal sim {}: {}".format(sim_info.sim_id, text))
    output("Goal for {}: {}".format(sim_info.first_name, text))
    output("Start it with houserules.npc.start (or start all).")


@sims4.commands.Command("houserules.npc.goal_clear", command_type=sims4.commands.CommandType.Live)
def npc_goal_clear(opt_sim: OptionalSimInfoParam = None, _connection=None):
    sim_info = _target(opt_sim, _connection)
    if sim_info is not None:
        npc_llm.set_goal(sim_info.sim_id, None)
        sims4.commands.CheatOutput(_connection)("Cleared {}'s goal.".format(sim_info.first_name))


@sims4.commands.Command("houserules.npc.brain_clear", command_type=sims4.commands.CommandType.Live)
def npc_brain_clear(opt_sim: OptionalSimInfoParam = None, _connection=None):
    sim_info = _target(opt_sim, _connection)
    if sim_info is not None:
        npc_llm.set_instructions(sim_info.sim_id, None)
        sims4.commands.CheatOutput(_connection)("Cleared {}'s description.".format(sim_info.first_name))


@sims4.commands.Command("houserules.npc.brain_show", command_type=sims4.commands.CommandType.Live)
def npc_brain_show(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _target(opt_sim, _connection)
    if sim_info is None:
        return
    d = npc_llm.data()
    output("LLM: {} model {} (reasoning {})".format(
        d["url"], d["model"], "on" if d.get("think") else "off"))
    output("{} goal: {}".format(sim_info.first_name, npc_llm.goal_for(sim_info.sim_id) or "(none)"))
    output("{}: {}".format(sim_info.first_name, npc_llm.instructions_for(sim_info.sim_id) or "(no description)"))


@sims4.commands.Command("houserules.npc.think", command_type=sims4.commands.CommandType.Live)
def npc_think(opt_sim: OptionalSimInfoParam = None, _connection=None):
    """Show the last prompt and answer - and the model's reasoning, for a thinking model."""
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _target(opt_sim, _connection)
    if sim_info is None:
        return
    last = npc_llm.last_for(sim_info.sim_id)
    if not last:
        output("No LLM answer for {} yet. Start it with houserules.npc.start.".format(
            sim_info.first_name))
        return
    output("{} - {} (model {})".format(
        sim_info.first_name, last.get("when", "?"), npc_llm.data()["model"]))
    output("Prompt:")
    for line in (last.get("prompt") or "").splitlines():
        output("  " + line)
    output("Answer: {}".format(last.get("answer") or "(nothing)"))
    if last.get("thinking"):
        output("Thinking:")
        for line in last["thinking"].splitlines():
            output("  " + line)
    if last.get("error"):
        output("Error: {}".format(last["error"]))
    output("(also in the npc-routines log)")


@sims4.commands.Command("houserules.npc.reasoning", command_type=sims4.commands.CommandType.Live)
def npc_reasoning(state: str = "", _connection=None):
    """Turn on a thinking model's working (needs a model that supports it, e.g. qwen3)."""
    output = sims4.commands.CheatOutput(_connection)
    d = npc_llm.data()
    state = (state or "").strip().lower()
    if state not in ("on", "off"):
        output("Reasoning is {}. Use: houserules.npc.reasoning on|off "
               "(only thinking models, e.g. qwen3, return it)".format(
                   "on" if d.get("think") else "off"))
        return
    d["think"] = state == "on"
    npc_llm.save()
    output("Reasoning {}.".format(
        "on - use a thinking model such as qwen3" if d["think"] else "off"))


@sims4.commands.Command("houserules.npc.llm", command_type=sims4.commands.CommandType.Live)
def npc_llm_settings(url: str = "", model: str = "", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    d = npc_llm.data()
    if url:
        d["url"] = url
    if model:
        d["model"] = model
    npc_llm.save()
    output("LLM: {} model {}".format(d["url"], d["model"]))


@sims4.commands.Command("houserules.npc.llm_test", command_type=sims4.commands.CommandType.Live)
def npc_llm_test(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _target(opt_sim, _connection)
    if sim_info is None or not (npc_llm.instructions_for(sim_info.sim_id)
                                or npc_llm.goal_for(sim_info.sim_id)):
        output("Select a sim and give them a goal or description first: "
               "houserules.npc.goal <text> / houserules.npc.brain <text>")
        return
    if not npc_llm.reachable():
        output("The local LLM isn't reachable - start start-llm.cmd.")
        return
    npc_main._ask_now(sim_info, output)
    output("Asked. The answer is applied in a few seconds.")


# --- JSON rules -----------------------------------------------------------------------------
def _rule_line(number, rule):
    """One rule as a readable line: '2. skill painting above 3 -> paint (90 min)'."""
    when = "always" if not rule.get("if") else json.dumps(rule["if"], sort_keys=True)
    then = rule.get("then") or {}
    line = "  {}. {} -> {}".format(number, when, then.get("action", "?"))
    if then.get("minutes"):
        line += " ({})".format(npc_main.format_minutes(then["minutes"]))
    if then.get("reason"):
        line += " - " + then["reason"]
    return line


@sims4.commands.Command("houserules.npc.rules_list", command_type=sims4.commands.CommandType.Live)
def npc_rules_list(_connection=None):
    r"""The rule files in Mods\HouseRules\data\rules (use the short name with rules_load)."""
    output = sims4.commands.CheatOutput(_connection)
    names = npc_rules.list_rule_files()
    output("Rule files in {}:".format(npc_rules.RULES_DIR))
    for name in names:
        output("  " + name)
    if not names:
        output("  (none - put a .json file there, e.g. painter.json)")


@sims4.commands.Command("houserules.npc.rules_load", command_type=sims4.commands.CommandType.Live)
def npc_rules_load(*words, _connection=None):
    """houserules.npc.rules_load <file> [sim|all] - load a JSON rule routine onto a sim."""
    output = sims4.commands.CheatOutput(_connection)
    words = [str(word) for word in words if str(word).strip()]
    if not words:
        output("Usage: houserules.npc.rules_load <file> [sim|all]")
        npc_rules_list(_connection)
        return
    filename = words[0]
    sims = _matching_sims(words[1:])
    if not sims:
        output("No matching sim. Name one, use 'all', or select a sim first.")
        return
    ruleset, error = _assign_rules(sims, filename)
    if error:
        output("Could not load {}: {}".format(filename, error))
        return
    output("Loaded {} rules from {} for {}.".format(
        len(ruleset["rules"]), ruleset.get("source") or filename,
        ", ".join(sim_info.first_name for sim_info in sims)))
    for number, rule in enumerate(ruleset["rules"], 1):
        output(_rule_line(number, rule))


def _assign_rules(sims, filename):
    """Load a rule file and assign it to these sims. Returns (ruleset, error message)."""
    try:
        path = npc_rules.resolve_rule_file(filename)
        ruleset = npc_rules.load_ruleset(path)
    except (OSError, ValueError) as e:
        npc_log.log("rules.load failed for {!r}: {}".format(filename, e), level="WARN")
        return None, e
    npc_main._ensure_loaded()
    for sim_info in sims:
        npc_main._rules_store.assign(sim_info.sim_id, ruleset)
        npc_main._npc_mode_sim_ids.add(sim_info.sim_id)
        npc_main._forget(sim_info.sim_id)      # a new rule set starts from a clean slate
    npc_main._save_rules()
    npc_main._save_npc_mode()
    npc_log.log("rules.load {} for sims {}".format(
        ruleset.get("source") or filename, [s.sim_id for s in sims]))
    return ruleset, None


@sims4.commands.Command("houserules.npc.rules_pick", command_type=sims4.commands.CommandType.Live)
def npc_rules_pick(opt_sim: OptionalSimInfoParam = None, _connection=None):
    """Pick a JSON rule file from a menu and load it onto this sim (no typing)."""
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _target(opt_sim, _connection)
    if sim_info is None:
        output("No sim found (select one or pass a sim id).")
        return
    _choose_rule_file(sim_info)


def _choose_rule_file(sim_info):
    """The JSON files in data\\rules, as a picker - one is loaded onto the sim."""
    names = npc_rules.list_rule_files()
    if not names:
        npc_main._notify(sim_info, "No rule files",
                         "Put a .json file in {} and try again.".format(npc_rules.RULES_DIR))
        return
    _pick(sim_info, "Rule routine: {}".format(sim_info.first_name),
          "Which JSON file should run {}?".format(sim_info.first_name),
          [(name, name) for name in names],
          lambda picked: _loaded_rule_notice(sim_info, picked[0]))


def _loaded_rule_notice(sim_info, filename):
    ruleset, error = _assign_rules([sim_info], filename)
    if error:
        npc_main._notify(sim_info, "Could not load {}".format(filename), str(error))
        return
    npc_main._notify(sim_info, "Rules loaded",
                     "{} now follows {} ({} rules).".format(
                         sim_info.first_name, ruleset.get("name") or filename,
                         len(ruleset["rules"])))


@sims4.commands.Command("houserules.npc.rules_show", command_type=sims4.commands.CommandType.Live)
def npc_rules_show(opt_sim: OptionalSimInfoParam = None, _connection=None):
    """The JSON rules assigned to this sim, plus the rule that would fire right now."""
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _target(opt_sim, _connection)
    if sim_info is None:
        return
    npc_main._ensure_loaded()
    ruleset = npc_main._rules_store.get(sim_info.sim_id)
    if not ruleset:
        output("{} has no JSON rules. Load some with houserules.npc.rules_load <file>. "
               "The LLM (goal/description) decides instead.".format(sim_info.first_name))
        return
    output("{}: {} ({} rules from {})".format(
        sim_info.first_name, ruleset.get("name") or "rules",
        len(ruleset["rules"]), ruleset.get("source") or "npc_rules.json"))
    for number, rule in enumerate(ruleset["rules"], 1):
        output(_rule_line(number, rule))
    npc_rules_choice(sim_info, ruleset, output)


@sims4.commands.Command("houserules.npc.rules_test", command_type=sims4.commands.CommandType.Live)
def npc_rules_test(opt_sim: OptionalSimInfoParam = None, _connection=None):
    """Evaluate the sim's rules now and print the choice, without doing anything."""
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _target(opt_sim, _connection)
    if sim_info is None:
        return
    npc_main._ensure_loaded()
    ruleset = npc_main._rules_store.get(sim_info.sim_id)
    if not ruleset:
        output("{} has no JSON rules. Load some with houserules.npc.rules_load <file>.".format(
            sim_info.first_name))
        return
    npc_rules_choice(sim_info, ruleset, output)


def npc_rules_choice(sim_info, ruleset, output):
    """Print what the rules decide for the sim right now (shared by show/test)."""
    try:
        choice, notes, _candidates = npc_main._evaluate_rules(sim_info, ruleset)
    except Exception:
        npc_log.log_exception("evaluating the JSON rules")
        output("Could not evaluate the rules - see the log.")
        return
    for note in notes:
        output("  " + note)
    if choice is None:
        output("No rule matches right now{} - the routine (and then the LLM) still applies."
               .format("" if not notes else " (unavailable actions above)"))
        return
    output("Now: rule {} -> {} for {}{}".format(
        choice.number, choice.action or "do nothing", npc_main.format_minutes(choice.minutes),
        " ({})".format(choice.reason) if choice.reason else ""))


@sims4.commands.Command("houserules.npc.rules_clear", command_type=sims4.commands.CommandType.Live)
def npc_rules_clear(*words, _connection=None):
    """Remove the JSON rules from a sim (default: selected), or from all with 'all'."""
    output = sims4.commands.CheatOutput(_connection)
    sims = _matching_sims(words)
    if not sims:
        output("No matching sim. Name one, use 'all', or select a sim first.")
        return
    npc_main._ensure_loaded()
    for sim_info in sims:
        npc_main._rules_store.remove(sim_info.sim_id)
        npc_main._forget(sim_info.sim_id)
    npc_main._save_rules()
    output("Cleared the JSON rules for {}.".format(
        ", ".join(sim_info.first_name for sim_info in sims)))
