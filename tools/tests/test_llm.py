import llm


def test_has_model_accepts_omitted_latest_tag():
    assert llm.has_model(["qwen2.5:latest"], "qwen2.5")          # Ollama adds the tag
    assert llm.has_model(["qwen2.5:14b-instruct-q4_K_M"], "qwen2.5:14b-instruct-q4_K_M")
    assert not llm.has_model(["qwen3:14b"], "qwen2.5:14b")


def test_choose_model_prefers_the_configured_one():
    assert llm.choose_model(["qwen3:14b", "qwen2.5:14b"], "qwen2.5:14b") == "qwen2.5:14b"


def test_choose_model_falls_back_to_any_chat_model():
    assert llm.choose_model(["nomic-embed-text:latest", "qwen3:14b"], "qwen2.5:14b") == "qwen3:14b"


def test_choose_model_none_without_a_usable_model():
    assert llm.choose_model([], "qwen2.5:14b") is None
    assert llm.choose_model(None, "qwen2.5:14b") is None
    assert llm.choose_model(["nomic-embed-text:latest"], "qwen2.5:14b") is None
