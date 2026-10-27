import json
import threading

import llm_tail


def test_model_wanted_follows_the_game(monkeypatch):
    monkeypatch.setattr(llm_tail.llm_server, "game_running", lambda: True)
    assert llm_tail.model_wanted() is True        # warm for the whole session

    monkeypatch.setattr(llm_tail.llm_server, "game_running", lambda: False)
    assert llm_tail.model_wanted() is False       # nothing loaded while the game is closed


def _run_watch(monkeypatch, states, **kwargs):
    stop = threading.Event()

    def wanted():
        try:
            return next(states)
        except StopIteration:
            stop.set()
            return False

    monkeypatch.setattr(llm_tail, "model_wanted", wanted)
    seen = []
    llm_tail.watch_brain(seen.append, poll=0, stop=stop, **kwargs)
    return seen


def test_watch_brain_waits_when_the_game_is_not_running_yet(monkeypatch):
    # Starting start-llm.cmd and then the game must not unload anything on the way in.
    assert _run_watch(monkeypatch, iter([False, False, False])) == []


def test_watch_brain_loads_when_the_game_starts(monkeypatch):
    assert _run_watch(monkeypatch, iter([False, True, True])) == [True]


def test_watch_brain_unloads_once_the_game_has_been_gone_a_while(monkeypatch):
    states = iter([True, True, False, False, False, False, False, False])
    assert _run_watch(monkeypatch, states, gone_after=0) == [True, False]


def test_watch_brain_ignores_a_short_gap(monkeypatch):
    # A launcher restarting the process must not reload the model.
    states = iter([True, False, True, True])
    assert _run_watch(monkeypatch, states, gone_after=60) == [True]


def test_brain_start_loads_and_brain_stop_unloads(monkeypatch):
    calls = []
    monkeypatch.setattr(llm_tail, "settings",
                        lambda: ("http://localhost:11434/api/generate", "m"))
    monkeypatch.setattr(llm_tail, "emit", lambda text: None)
    monkeypatch.setattr(llm_tail.llm_server, "load",
                        lambda name, conf, model, say=None: calls.append(("load", name, model)))
    monkeypatch.setattr(llm_tail.llm_server, "unload",
                        lambda name, conf, model, say=None: calls.append(("unload", name, model)))

    llm_tail._model_changed(True)
    llm_tail._model_changed(False)

    assert calls == [("load", "ollama", "m"), ("unload", "ollama", "m")]


def test_watch_brain_survives_a_failing_callback(monkeypatch):
    states = iter([True])
    stop = threading.Event()

    def wanted():
        try:
            return next(states)
        except StopIteration:
            stop.set()
            return True

    monkeypatch.setattr(llm_tail, "model_wanted", wanted)
    out = []
    monkeypatch.setattr(llm_tail, "emit", out.append)

    def boom(wanted):
        raise RuntimeError("no model")

    llm_tail.watch_brain(boom, poll=0, stop=stop)
    assert any("could not react" in line for line in out)
