import llm


def test_tasklist_detects_the_game():
    assert llm._tasklist_has_game('"TS4_x64.exe","1234","Console","1","1,234 K"\r\n')
    assert llm._tasklist_has_game('"notepad.exe","1"\r\n"TS4.exe","2"\r\n')
    assert not llm._tasklist_has_game('"notepad.exe","1"\r\n"chrome.exe","2"\r\n')
    assert not llm._tasklist_has_game("")


def test_backend_for_depends_on_the_url_shape():
    assert llm.backend_for("http://localhost:11434/api/generate") == "ollama"
    assert llm.backend_for("http://localhost:1234/v1/chat/completions") == "lmstudio"


OLLAMA = {"url": "http://localhost:11434/api/generate", "model": "m"}
LMSTUDIO = {"url": "http://localhost:1234/v1/chat/completions", "model": "m"}


def test_load_keeps_the_model_in_memory(monkeypatch):
    sent = []
    monkeypatch.setattr(llm, "_post", lambda url, body, **kwargs: sent.append(body))
    llm.load("ollama", OLLAMA, "m")

    assert sent == [{"model": "m", "keep_alive": "60m"}]


def test_unload_does_nothing_when_no_model_is_loaded(monkeypatch):
    sent = []
    monkeypatch.setattr(llm, "get_json", lambda *args, **kwargs: {"models": []})
    monkeypatch.setattr(llm, "_post", lambda *args, **kwargs: sent.append(args))
    llm.unload("ollama", OLLAMA, "m")

    assert sent == []


def test_unload_asks_ollama_to_drop_the_model(monkeypatch):
    sent, said = [], []
    monkeypatch.setattr(llm, "get_json", lambda *args, **kwargs: {"models": [{"name": "m"}]})
    monkeypatch.setattr(llm, "_post", lambda url, body, **kwargs: sent.append(body))
    llm.unload("ollama", OLLAMA, "m", say=said.append)

    assert sent == [{"model": "m", "keep_alive": 0}]
    assert said == ["Model unloaded."]


def test_unload_without_the_lms_cli_is_quiet(monkeypatch):
    monkeypatch.setattr(llm, "find_exe", lambda name: None)
    llm.unload("lmstudio", LMSTUDIO, "m")       # must not raise
