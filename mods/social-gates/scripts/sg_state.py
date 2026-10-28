"""Social Gates: shared game-side state - settings, saved data and notifications.

Data lives in Mods/HouseRules/data/ (per computer, like the other mods here).
Everything here swallows its own errors: a mod must never crash the game.
"""
import json
import os

import sg_log
from sg_settings import Settings

DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Electronic Arts",
                        "The Sims 4", "Mods", "HouseRules", "data")
_SETTINGS_PATH = os.path.join(DATA_DIR, "social_gates.json")

settings = Settings()
_settings_loaded = False


def ensure_settings():
    global _settings_loaded
    if not _settings_loaded:
        try:
            settings.load(_SETTINGS_PATH)
        except Exception:
            sg_log.log_exception("loading settings")
        _settings_loaded = True
    return settings


def setting(key):
    return ensure_settings().get(key)


def save_settings():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        settings.save(_SETTINGS_PATH)
    except Exception:
        sg_log.log_exception("saving settings")


def load_json(name, default):
    path = os.path.join(DATA_DIR, name)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            if text:
                return json.loads(text)
    except Exception:
        sg_log.log_exception("loading " + name)
    return default


def save_json(name, data):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = os.path.join(DATA_DIR, name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, os.path.join(DATA_DIR, name))
    except Exception:
        sg_log.log_exception("saving " + name)


def sim_name(sim_info):
    return "{} {}".format(getattr(sim_info, "first_name", ""), getattr(sim_info, "last_name", "")).strip() \
        or str(getattr(sim_info, "sim_id", "?"))


def notify(title, text, sim_info=None):
    try:
        import services
        from sims4.localization import LocalizationHelperTuning
        from ui.ui_dialog_notification import UiDialogNotification

        def _as_localized(value):
            # A caller can pass a localized string (with tokens) or plain text.
            if isinstance(value, str):
                return LocalizationHelperTuning.get_raw_text(value)
            return value

        owner = sim_info if sim_info is not None else services.active_sim_info()
        dialog = UiDialogNotification.TunableFactory().default(
            owner,
            title=lambda *_, **__: _as_localized(title),
            text=lambda *_, **__: _as_localized(text))
        dialog.show_dialog()
    except Exception:
        sg_log.log_exception("showing notification")
