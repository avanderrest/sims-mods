"""Flexible University: settings, saved data and notifications.

Data lives in Mods/HouseRules/data/ (per computer, like the other mods here). It is keyed
by sim id, so it follows a Sim between saves only as far as the id does - the same convention
Hard Mode and Social Gates use.

Everything here swallows its own errors: a mod must never crash the game.
"""
import json
import os

import fu_log
from fu_settings import Settings

DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts",
                        "The Sims 4", "Mods", "HouseRules", "data")
_SETTINGS_PATH = os.path.join(DATA_DIR, "flexible_university.json")
_DATA_FILE = "flexible_university_data.json"

settings = Settings()
_settings_loaded = False
_data = None


def ensure_settings():
    global _settings_loaded
    if not _settings_loaded:
        try:
            settings.load(_SETTINGS_PATH)
        except Exception:
            fu_log.log_exception("loading settings")
        _settings_loaded = True
    return settings


def setting(key):
    return ensure_settings().get(key)


def save_settings():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        settings.save(_SETTINGS_PATH)
    except Exception:
        fu_log.log_exception("saving settings")


# --- Saved data -------------------------------------------------------------------------
def _ensure_data():
    global _data
    if _data is None:
        _data = load_json(_DATA_FILE, {})
        if not isinstance(_data, dict):
            _data = {}
        _data.setdefault("fractions", {})
        _data.setdefault("credentials", {})
    return _data


def _save_data():
    save_json(_DATA_FILE, _ensure_data())


def fraction(sim_id):
    return float(_ensure_data()["fractions"].get(str(sim_id), 0.0) or 0.0)


def set_fraction(sim_id, value):
    _ensure_data()["fractions"][str(sim_id)] = round(float(value), 4)
    _save_data()


def clear_fraction(sim_id):
    if str(sim_id) in _ensure_data()["fractions"]:
        _ensure_data()["fractions"].pop(str(sim_id), None)
        _save_data()


def credentials(sim_id):
    return dict(_ensure_data()["credentials"].get(str(sim_id), {}))


def credential_for(sim_id, major):
    return credentials(sim_id).get(str(major))


def set_credential(sim_id, major, entry):
    if not major:
        return
    _ensure_data()["credentials"].setdefault(str(sim_id), {})[str(major)] = entry
    _save_data()


def all_credentials():
    return dict(_ensure_data()["credentials"])


# --- Files ------------------------------------------------------------------------------
def load_json(name, default):
    path = os.path.join(DATA_DIR, name)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            if text:
                return json.loads(text)
    except Exception:
        fu_log.log_exception("loading " + name)
    return default


def save_json(name, data):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = os.path.join(DATA_DIR, name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, os.path.join(DATA_DIR, name))
    except Exception:
        fu_log.log_exception("saving " + name)


# --- Text -------------------------------------------------------------------------------
def sim_name(sim_info):
    return "{} {}".format(getattr(sim_info, "first_name", ""),
                          getattr(sim_info, "last_name", "")).strip() \
        or str(getattr(sim_info, "sim_id", getattr(sim_info, "id", "?")))


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
        fu_log.log_exception("showing notification")
