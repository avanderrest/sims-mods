import json

import npc_llm


def _state(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_mark_active_records_who_the_brain_is_working_for(monkeypatch, tmp_path):
    path = tmp_path / "npc_brain_state.json"
    monkeypatch.setattr(npc_llm, "_STATE_PATH", str(path))
    monkeypatch.setattr(npc_llm, "_active", set())

    npc_llm.mark_active(111)
    npc_llm.mark_active(222)
    assert _state(path)["sims"] == [111, 222]
    assert npc_llm.active_ids() == [111, 222]

    npc_llm.mark_active(111, False)
    assert _state(path)["sims"] == [222]
    assert not path.with_suffix(".json.tmp").exists()     # written atomically


def test_reset_active_clears_what_a_previous_session_left(monkeypatch, tmp_path):
    path = tmp_path / "npc_brain_state.json"
    monkeypatch.setattr(npc_llm, "_STATE_PATH", str(path))
    monkeypatch.setattr(npc_llm, "_active", set())

    npc_llm.mark_active(333)
    npc_llm.reset_active()

    assert _state(path)["sims"] == []
    assert npc_llm.active_ids() == []


def test_state_write_failures_are_swallowed(monkeypatch, tmp_path):
    # A logger-only module: a bad path must never break a decision.
    monkeypatch.setattr(npc_llm, "_STATE_PATH", str(tmp_path / "no" / "such" / "dir" / "x.json"))
    monkeypatch.setattr(npc_llm, "_active", set())
    npc_llm.mark_active(444)      # does not raise
    assert npc_llm.active_ids() == [444]


def test_has_answers_tracks_the_queue():
    npc_llm.take_answers()                 # start clean
    assert npc_llm.has_answers() is False
    npc_llm._answers.put((1, "sit", 60, "wants to sit", None))
    assert npc_llm.has_answers() is True
    npc_llm.take_answers()
    assert npc_llm.has_answers() is False


def _brain(tmp_path, goals):
    path = tmp_path / "npc_brain.json"
    path.write_text(json.dumps({"goals": goals, "sims": {}}), encoding="utf-8")
    return path


def test_a_goal_written_by_the_console_is_read_without_a_restart(monkeypatch, tmp_path):
    import os
    path = _brain(tmp_path, {"111": "become a painter"})
    monkeypatch.setattr(npc_llm, "_PATH", str(path))
    monkeypatch.setattr(npc_llm, "_data", None)
    monkeypatch.setattr(npc_llm, "_data_mtime", None)
    os.utime(str(path), (1000.0, 1000.0))
    assert npc_llm.goal_for(111) == "become a painter"

    # start-llm.cmd's /goal rewrites the file while the game is running.
    path.write_text(json.dumps({"goals": {"111": "become a chef"}, "sims": {}}), encoding="utf-8")
    os.utime(str(path), (2000.0, 2000.0))
    assert npc_llm.goal_for(111) == "become a chef"


def test_an_unchanged_file_is_not_re_read(monkeypatch, tmp_path):
    import os
    path = _brain(tmp_path, {})
    monkeypatch.setattr(npc_llm, "_PATH", str(path))
    monkeypatch.setattr(npc_llm, "_data", None)
    monkeypatch.setattr(npc_llm, "_data_mtime", None)
    os.utime(str(path), (3000.0, 3000.0))
    calls = []
    monkeypatch.setattr(npc_llm, "_load", lambda: (calls.append(1), {"sims": {}, "goals": {}})[1])
    npc_llm.data()
    npc_llm.data()
    assert len(calls) == 1


def test_a_broken_file_does_not_break_a_decision(monkeypatch, tmp_path):
    path = tmp_path / "npc_brain.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(npc_llm, "_PATH", str(path))
    monkeypatch.setattr(npc_llm, "_data", None)
    monkeypatch.setattr(npc_llm, "_data_mtime", None)
    assert npc_llm.goal_for(111) is None
    assert npc_llm.instructions_for(111) is None
