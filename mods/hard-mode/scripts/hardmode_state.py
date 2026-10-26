"""Hard Mode: shared game-side state - settings, saved data, the sim clock and notifications.

Everything the careers, money and skills parts share, so they don't each load their own copy.
Data files live in Mods/HouseRules/data/ (they're per computer, not per save: ids of
households and sims from different saves don't collide in practice).
"""
import json
import os

import hardmode_log
from hardmode_settings import Settings

DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts",
                        "The Sims 4", "Mods", "HouseRules", "data")
_SETTINGS_PATH = os.path.join(DATA_DIR, "hard_mode_settings.json")

settings = Settings()
_settings_loaded = False


def ensure_settings():
    global _settings_loaded
    if not _settings_loaded:
        try:
            settings.load(_SETTINGS_PATH)
        except Exception:
            hardmode_log.log_exception("loading settings")
        _settings_loaded = True
    return settings


def setting(key):
    return ensure_settings().get(key)


def save_settings():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        settings.save(_SETTINGS_PATH)
    except Exception:
        hardmode_log.log_exception("saving settings")


_FU_DATA_FILE = "flexible_university_data.json"


def university_credentials(sim_id):
    """Qualifications Flexible University recorded for a Sim.

    Read from its data file instead of importing its modules: the mods are separate
    .ts4script archives, and the JSON file is the stable contract between them. Returns []
    when Flexible University isn't installed or has nothing recorded yet.
    """
    data = load_json(_FU_DATA_FILE, {})
    try:
        entries = (data.get("credentials") or {}).get(str(sim_id)) or {}
    except AttributeError:
        return []
    return [entry for entry in entries.values()
            if isinstance(entry, dict) and entry.get("major")]


def load_json(name, default):
    path = os.path.join(DATA_DIR, name)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            if text:
                return json.loads(text)
    except Exception:
        hardmode_log.log_exception("loading " + name)
    return default


def save_json(name, data):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = os.path.join(DATA_DIR, name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, os.path.join(DATA_DIR, name))
    except Exception:
        hardmode_log.log_exception("saving " + name)


def sim_today():
    """Days since the start of this save, as a float (e.g. 12.5 = noon of day 13)."""
    import services
    return services.time_service().sim_now.absolute_days()


def sim_name(sim_info):
    return "{} {}".format(getattr(sim_info, "first_name", ""), getattr(sim_info, "last_name", "")).strip() \
        or str(getattr(sim_info, "sim_id", "?"))


def notify(title, text, sim_info=None):
    try:
        import services
        from sims4.localization import LocalizationHelperTuning
        from ui.ui_dialog_notification import UiDialogNotification
        owner = sim_info if sim_info is not None else services.active_sim_info()
        dialog = UiDialogNotification.TunableFactory().default(
            owner,
            title=lambda *_, **__: LocalizationHelperTuning.get_raw_text(title),
            text=lambda *_, **__: LocalizationHelperTuning.get_raw_text(text))
        dialog.show_dialog()
    except Exception:
        hardmode_log.log_exception("showing notification")


def pick(sim_info, title, text, options, callback):
    """A list to pick one from. options: [(label, value)]; callback(value) runs only on OK."""
    from sims4.localization import LocalizationHelperTuning
    from ui.ui_dialog_picker import ObjectPickerRow, UiDialogObjectPicker, UiObjectPicker
    raw = LocalizationHelperTuning.get_raw_text
    dialog = UiObjectPicker.TunableFactory().default(
        sim_info,
        text=lambda *_, **__: raw(text),
        title=lambda *_, **__: raw(title),
        min_selectable=1,
        # Every field must be given: built outside tuning, nothing fills in defaults.
        max_selectable=UiDialogObjectPicker._MaxSelectableStatic(number_selectable=1, exclude_previously_selected=False),
        is_sortable=False,
        picker_type=UiObjectPicker.UiObjectPickerObjectPickerType.OBJECT)
    for i, (label, value) in enumerate(options):
        dialog.add_row(ObjectPickerRow(option_id=i, name=raw(label), tag=value))

    def on_response(d):
        try:
            if d.accepted and d.get_result_tags():
                callback(d.get_result_tags()[0])
        except Exception:
            hardmode_log.log_exception("picker: {}".format(title))

    dialog.add_listener(on_response)
    dialog.show_dialog()


def tag_names(tags):
    """Game Tag values -> their tuning names (e.g. 'Func_Painting')."""
    names = []
    try:
        from tag import Tag
        for t in tags or ():
            try:
                names.append(Tag(t).name)
            except Exception:
                pass
    except Exception:
        hardmode_log.log_exception("reading tag names")
    return names
