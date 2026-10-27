import json

import llm_tail


def test_settings_prefers_the_mods_own_settings(monkeypatch, tmp_path):
    manifest = tmp_path / "llm.json"
    manifest.write_text(json.dumps({
        "backend": "ollama",
        "backends": {"ollama": {"url": "http://manifest:1/api/generate", "model": "manifest"}},
    }), encoding="utf-8")
    brain = tmp_path / "npc_brain.json"
    brain.write_text(json.dumps({"url": "http://brain:2/api/generate", "model": "brain"}),
                     encoding="utf-8")
    monkeypatch.setattr(llm_tail, "MANIFEST", manifest)
    monkeypatch.setattr(llm_tail, "BRAIN_FILE", brain)
    assert llm_tail.settings() == ("http://brain:2/api/generate", "brain")


def test_settings_falls_back_to_the_manifest(monkeypatch, tmp_path):
    manifest = tmp_path / "llm.json"
    manifest.write_text(json.dumps({
        "backend": "lmstudio",
        "backends": {"lmstudio": {"url": "http://manifest:1/v1/chat/completions", "model": "m"}},
    }), encoding="utf-8")
    monkeypatch.setattr(llm_tail, "MANIFEST", manifest)
    monkeypatch.setattr(llm_tail, "BRAIN_FILE", tmp_path / "missing.json")
    assert llm_tail.settings() == ("http://manifest:1/v1/chat/completions", "m")


def test_settings_falls_back_to_the_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_tail, "MANIFEST", tmp_path / "missing.json")
    monkeypatch.setattr(llm_tail, "BRAIN_FILE", tmp_path / "also-missing.json")
    assert llm_tail.settings() == (llm_tail.DEFAULT_URL, llm_tail.DEFAULT_MODEL)


MESSAGES = [{"role": "user", "content": "hello"}]


def test_request_body_and_answer_for_both_server_shapes():
    ollama = "http://localhost:11434/api/generate"
    body = llm_tail.request_body(ollama, "qwen", MESSAGES)
    assert body["prompt"].endswith("hello") and body["stream"] is False
    assert body["prompt"].startswith(llm_tail.CONCISE_INSTRUCTION)
    assert llm_tail.answer_text(ollama, {"response": "hi"}) == "hi"

    openai = "http://localhost:1234/v1/chat/completions"
    body = llm_tail.request_body(openai, "local", MESSAGES)
    assert body["messages"][0] == {"role": "system", "content": llm_tail.CONCISE_INSTRUCTION}
    assert body["messages"][1:] == MESSAGES
    assert llm_tail.answer_text(openai, {"choices": [{"message": {"content": "hi"}}]}) == "hi"


def test_transcript_keeps_the_conversation_for_generate_endpoints():
    history = [{"role": "user", "content": "who paints?"},
               {"role": "assistant", "content": "Grace does."},
               {"role": "user", "content": "and then?"}]
    text = llm_tail.transcript(history)
    assert "User: who paints?" in text and "Assistant: Grace does." in text
    assert text.rstrip().endswith("User: and then?")


class FakeStream:
    def __init__(self, lines):
        self.lines = list(lines)

    def readline(self):
        return self.lines.pop(0) if self.lines else ""


def _chat_with(monkeypatch, stream, ask):
    out = []
    monkeypatch.setattr(llm_tail, "emit", out.append)
    monkeypatch.setattr(llm_tail, "settings", lambda: ("http://x", "fake-model"))
    monkeypatch.setattr(llm_tail, "ask", ask)
    llm_tail.chat(stream)
    return out


def test_chat_keeps_the_conversation_between_questions(monkeypatch):
    calls = []

    def ask(url, model, messages):
        calls.append(list(messages))
        return "answer {}".format(len(calls))

    _chat_with(monkeypatch, FakeStream(["hello\n", "   \n", "and then?\n"]), ask)

    assert len(calls) == 2
    assert calls[0] == [{"role": "user", "content": "hello"}]
    assert calls[1] == [{"role": "user", "content": "hello"},
                        {"role": "assistant", "content": "answer 1"},
                        {"role": "user", "content": "and then?"}]


def test_restart_starts_a_fresh_conversation(monkeypatch):
    calls, out = [], []

    def ask(url, model, messages):
        calls.append(list(messages))
        return "an answer"

    monkeypatch.setattr(llm_tail, "emit", out.append)
    monkeypatch.setattr(llm_tail, "settings", lambda: ("http://x", "fake-model"))
    monkeypatch.setattr(llm_tail, "ask", ask)
    llm_tail.chat(FakeStream(["first\n", "/restart\n", "second\n"]))

    assert calls[0] == [{"role": "user", "content": "first"}]
    assert calls[1] == [{"role": "user", "content": "second"}]
    assert any("Fresh conversation" in line for line in out)


def test_history_is_bounded(monkeypatch):
    calls = []

    def ask(url, model, messages):
        calls.append(list(messages))
        return "an answer"

    monkeypatch.setattr(llm_tail, "emit", lambda text: None)
    monkeypatch.setattr(llm_tail, "settings", lambda: ("http://x", "fake-model"))
    monkeypatch.setattr(llm_tail, "ask", ask)
    llm_tail.chat(FakeStream("question {}\n".format(i) for i in range(20)))

    assert len(calls[-1]) <= llm_tail.MAX_HISTORY
    assert calls[-1][-1]["content"] == "question 19"


def test_chat_keeps_going_when_the_model_is_not_running(monkeypatch):
    def ask(url, model, messages):
        raise OSError("connection refused")

    out = _chat_with(monkeypatch, FakeStream(["hello\n", "still there?\n"]), ask)
    assert sum("did not answer" in line for line in out) == 2


def test_a_failed_turn_is_not_remembered(monkeypatch):
    calls = []

    def ask(url, model, messages):
        calls.append(list(messages))
        if len(calls) == 1:
            raise OSError("down")
        return "fine"

    _chat_with(monkeypatch, FakeStream(["first\n", "second\n"]), ask)
    assert calls[1] == [{"role": "user", "content": "second"}]


def test_chat_stops_when_the_console_closes(monkeypatch):
    def ask(url, model, messages):
        return "unused"

    out = _chat_with(monkeypatch, FakeStream([]), ask)
    assert any("Type a message" in line for line in out)


def test_an_unknown_command_is_explained_not_sent_to_the_model(monkeypatch):
    out, asked = [], []
    monkeypatch.setattr(llm_tail, "emit", out.append)
    monkeypatch.setattr(llm_tail, "settings", lambda: ("http://x", "fake-model"))
    monkeypatch.setattr(llm_tail, "ask",
                        lambda url, model, messages: asked.append(messages) or "an answer")

    llm_tail.chat(FakeStream(["/nope\n"]))

    assert asked == []
    assert any("Unknown command /nope" in line for line in out)


def _goal_setup(monkeypatch, tmp_path):
    brain = tmp_path / "npc_brain.json"
    monkeypatch.setattr(llm_tail, "BRAIN_FILE", brain)
    out = []
    monkeypatch.setattr(llm_tail, "emit", out.append)
    return brain, out


def test_goal_sets_it_for_the_last_sim_seen_in_the_log(monkeypatch, tmp_path):
    brain, out = _goal_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(llm_tail, "_last_sim", "147518596888723484")

    assert llm_tail._command("/goal become a famous painter", []) is True

    assert json.loads(brain.read_text(encoding="utf-8"))["goals"] == {
        "147518596888723484": "become a famous painter"}
    assert any("now works towards" in line for line in out)


def test_goal_can_name_the_sim_itself(monkeypatch, tmp_path):
    brain, _out = _goal_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(llm_tail, "_last_sim", None)

    llm_tail._command("/goal 999999999999 become a chef", [])

    assert json.loads(brain.read_text(encoding="utf-8"))["goals"] == {
        "999999999999": "become a chef"}


def test_goal_without_a_sim_seen_explains_and_writes_nothing(monkeypatch, tmp_path):
    brain, out = _goal_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(llm_tail, "_last_sim", None)

    llm_tail._command("/goal paint", [])

    assert not brain.exists()
    assert any("have not seen a sim" in line for line in out)


def test_goal_alone_shows_it_and_clear_removes_it(monkeypatch, tmp_path):
    brain, out = _goal_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(llm_tail, "_last_sim", "111")
    brain.write_text(json.dumps({"goals": {"111": "paint"}, "sims": {}}), encoding="utf-8")

    llm_tail._command("/goal", [])
    assert any("sim 111: paint" in line for line in out)

    llm_tail._command("/goal clear", [])
    assert json.loads(brain.read_text(encoding="utf-8"))["goals"] == {}


def test_the_last_sim_comes_from_the_log_lines(monkeypatch):
    monkeypatch.setattr(llm_tail, "_last_sim", None)
    llm_tail.note_sim("tick: day=1 (mon) hour=12 npc_sims=[147518596888723484, 1141687802722387483]")
    assert llm_tail._last_sim == "147518596888723484"

    llm_tail.note_sim("LLM for sim 1141687802722387483: none for 1h")
    assert llm_tail._last_sim == "1141687802722387483"

    llm_tail.note_sim("object_sinkCounterFC_01:0x020c1761dd570d31")   # not a sim
    assert llm_tail._last_sim == "1141687802722387483"


def test_goal_writes_atomically(monkeypatch, tmp_path):
    brain, _out = _goal_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(llm_tail, "_last_sim", "111")
    llm_tail._command("/goal paint", [])
    assert not brain.with_name(brain.name + ".tmp").exists()
