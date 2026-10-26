import pytest
from sg_settings import DEFAULT_SETTINGS, Settings


def test_defaults():
    s = Settings()
    assert s.get("doors") is True
    assert s.get("club_wealth_band") == 0.5


def test_set_switch_and_number():
    s = Settings()
    s.set("doors", False)
    s.set("club_wealth_band", 0.75)
    s.set("friend_min_score", 35)
    assert s.get("doors") is False
    assert s.get("club_wealth_band") == 0.75
    assert s.get("friend_min_score") == 35


def test_set_unknown_key_raises():
    s = Settings()
    with pytest.raises(KeyError):
        s.set("not_a_real_setting", True)


def test_constructor_ignores_unknown_keys_from_loaded_data():
    s = Settings({"doors": False, "future_setting": 123})
    assert s.get("doors") is False
    assert "future_setting" not in s.values


def test_json_round_trip():
    s = Settings({"doors": False, "club_wealth_band": 0.25})
    s2 = Settings.from_json(s.to_json())
    assert s2.get("doors") is False
    assert s2.get("club_wealth_band") == 0.25


def test_load_from_missing_file_is_a_noop(tmp_path):
    s = Settings()
    s.load(str(tmp_path / "missing.json"))
    assert s.get("doors") is True


def test_load_from_empty_file_is_a_noop(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")
    s = Settings()
    s.load(str(path))
    assert s.get("doors") is True


def test_save_and_load(tmp_path):
    path = str(tmp_path / "settings.json")
    s = Settings({"invites": False})
    s.save(path)
    s2 = Settings()
    s2.load(path)
    assert s2.get("invites") is False


def test_switches():
    s = Settings()
    assert s.is_switch("doors") is True
    assert s.is_switch("friend_min_score") is False
