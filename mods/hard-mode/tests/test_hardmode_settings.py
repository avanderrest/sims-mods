import pytest
from hardmode_settings import Settings, DEFAULT_SETTINGS


def test_defaults():
    s = Settings()
    assert s.get("careers") == DEFAULT_SETTINGS["careers"]


def test_set_and_get():
    s = Settings()
    s.set("careers", False)
    assert s.get("careers") is False


def test_set_unknown_key_raises():
    s = Settings()
    with pytest.raises(KeyError):
        s.set("not_a_real_setting", True)


def test_constructor_ignores_unknown_keys_from_loaded_data():
    s = Settings({"careers": False, "future_setting_we_dont_know_about_yet": 123})
    assert s.get("careers") is False
    assert "future_setting_we_dont_know_about_yet" not in s.values


def test_json_round_trip():
    s = Settings({"careers": False})
    s2 = Settings.from_json(s.to_json())
    assert s2.get("careers") is False


def test_load_from_missing_file_is_a_noop(tmp_path):
    s = Settings()
    s.load(str(tmp_path / "missing.json"))
    assert s.get("careers") is True


def test_load_from_empty_file_is_a_noop(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")
    s = Settings()
    s.load(str(path))
    assert s.get("careers") is True


def test_save_then_load_round_trip(tmp_path):
    path = str(tmp_path / "settings.json")
    s = Settings()
    s.set("careers", False)
    s.save(path)

    s2 = Settings()
    s2.load(path)
    assert s2.get("careers") is False


def test_numeric_setting_stays_a_number():
    s = Settings()
    s.set("start_funds", "5000")
    assert s.get("start_funds") == 5000
    assert not s.is_switch("start_funds")
    assert s.is_switch("selling")
