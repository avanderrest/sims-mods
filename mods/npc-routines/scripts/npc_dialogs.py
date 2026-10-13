"""NPC Routines phase 2 - an in-game routine editor made of the game's own picker dialogs,
plus the cheats for phase 4 (the local-LLM brain).

A real "NPC Routine..." entry in a sim's pie menu needs an interaction defined in tuning
(a .package made in Sims 4 Studio). Until then, one cheat opens the editor:

  bluerabbit477.routine.edit [sim]   - menu: add an activity / show / clear / NPC mode on-off
      Add: activity -> days (pick several) -> start time -> how long

Local LLM (optional; needs Ollama or LM Studio running on this computer):
  bluerabbit477.npc.brain <text...> [sim]  - what this sim is like / wants (free text)
  bluerabbit477.npc.brain_clear [sim]
  bluerabbit477.npc.brain_show [sim]
  bluerabbit477.npc.llm <url> <model>      - default http://localhost:11434/api/generate llama3.2
  bluerabbit477.npc.llm_test [sim]         - ask now; the answer is used at the next hourly tick
"""
import services
import sims4.commands
from server_commands.argument_helpers import OptionalSimInfoParam, get_optional_target
from sims4.localization import LocalizationHelperTuning
from ui.ui_dialog_picker import ObjectPickerRow, UiDialogObjectPicker, UiObjectPicker

import npc_llm
import npc_log
import npc_main
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
        max_selectable=UiDialogObjectPicker._MaxSelectableStatic(number_selectable=len(options) if multi else 1),
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


@sims4.commands.Command("bluerabbit477.routine.edit", command_type=sims4.commands.CommandType.Live)
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
@sims4.commands.Command("bluerabbit477.npc.brain", command_type=sims4.commands.CommandType.Live)
def npc_brain(*words, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = services.active_sim_info()
    if sim_info is None or not words:
        output("Usage: bluerabbit477.npc.brain <what this sim is like and wants> (for the selected sim)")
        return
    text = " ".join(str(w) for w in words)
    npc_llm.set_instructions(sim_info.sim_id, text)
    npc_log.log("npc.brain sim {}: {}".format(sim_info.sim_id, text))
    output("Saved for {}: {}".format(sim_info.first_name, text))
    output("The LLM is asked when NPC mode is on and nothing is on their routine.")


@sims4.commands.Command("bluerabbit477.npc.brain_clear", command_type=sims4.commands.CommandType.Live)
def npc_brain_clear(opt_sim: OptionalSimInfoParam = None, _connection=None):
    sim_info = _target(opt_sim, _connection)
    if sim_info is not None:
        npc_llm.set_instructions(sim_info.sim_id, None)
        sims4.commands.CheatOutput(_connection)("Cleared {}'s description.".format(sim_info.first_name))


@sims4.commands.Command("bluerabbit477.npc.brain_show", command_type=sims4.commands.CommandType.Live)
def npc_brain_show(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _target(opt_sim, _connection)
    if sim_info is None:
        return
    d = npc_llm.data()
    output("LLM: {} model {}".format(d["url"], d["model"]))
    output("{}: {}".format(sim_info.first_name, npc_llm.instructions_for(sim_info.sim_id) or "(no description)"))


@sims4.commands.Command("bluerabbit477.npc.llm", command_type=sims4.commands.CommandType.Live)
def npc_llm_settings(url: str = "", model: str = "", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    d = npc_llm.data()
    if url:
        d["url"] = url
    if model:
        d["model"] = model
    npc_llm.save()
    output("LLM: {} model {}".format(d["url"], d["model"]))


@sims4.commands.Command("bluerabbit477.npc.llm_test", command_type=sims4.commands.CommandType.Live)
def npc_llm_test(opt_sim: OptionalSimInfoParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    sim_info = _target(opt_sim, _connection)
    if sim_info is None or not npc_llm.instructions_for(sim_info.sim_id):
        output("Select a sim and give them a description first: bluerabbit477.npc.brain <text>")
        return
    npc_main._ask_llm(sim_info, output)
    output("Asked. Run bluerabbit477.npc.tick in a moment to apply the answer (or wait for the hourly tick).")
