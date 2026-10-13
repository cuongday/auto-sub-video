import pytest
from autosub.llm import get_llm, LLMError
from autosub.llm.base import to_gemini_schema, to_openai_strict, with_retry
from autosub.translate import ITEMS_SCHEMA

def test_gemini_schema():
    g = to_gemini_schema(ITEMS_SCHEMA)
    assert g["type"] == "OBJECT"
    assert g["properties"]["items"]["items"]["properties"]["id"]["type"] == "INTEGER"
    assert "additionalProperties" not in str(g)

def test_openai_strict():
    o = to_openai_strict({"type": "object", "properties": {"a": {"type": "string"},
                          "b": {"type": "array", "items": {"type": "object", "properties": {"c": {"type": "integer"}}}}}})
    assert o["additionalProperties"] is False and o["required"] == ["a", "b"]
    assert o["properties"]["b"]["items"]["required"] == ["c"]

def test_retry_then_success():
    calls, sleeps = [], []
    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("429")
        return "ok"
    assert with_retry(fn, lambda e: "429" in str(e), sleep=sleeps.append) == "ok"
    assert sleeps == [2, 4]

def test_retry_gives_up_on_non_retryable():
    with pytest.raises(ValueError):
        with_retry(lambda: (_ for _ in ()).throw(ValueError("x")), lambda e: False, sleep=lambda s: None)

def test_missing_credentials(monkeypatch):
    from autosub import config
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        get_llm("openai").generate_json("hi", {"type": "object", "properties": {}})
    monkeypatch.setattr(config, "GCP_PROJECT", None)
    with pytest.raises(LLMError, match="GOOGLE_CLOUD_PROJECT"):
        get_llm("gemini").generate_json("hi", {"type": "object", "properties": {}})
    with pytest.raises(LLMError):
        get_llm("claude")

def test_gemini_disables_thinking_and_falls_back(monkeypatch):
    from google.genai import errors
    from autosub import config
    from autosub.llm.gemini import GeminiLLM, MIN_THINKING
    monkeypatch.setattr(config, "GCP_PROJECT", "p")
    budgets = []

    class Resp:
        text = '{"ok": true}'

    class Models:
        def generate_content(self, model, contents, config):
            budgets.append(config.thinking_config.thinking_budget)
            if config.thinking_config.thinking_budget == 0 and model.endswith("pro"):
                raise errors.ClientError(400, {"error": {"code": 400, "message": "does not support setting thinking_budget to 0",
                                                         "status": "INVALID_ARGUMENT"}})
            return Resp()

    for model in ("gemini-2.5-flash", "gemini-2.5-pro"):
        llm = GeminiLLM(model)
        llm._client = type("C", (), {"models": Models()})()
        assert llm.generate_json("x", {"type": "object", "properties": {}}) == {"ok": True}
    assert budgets == [0, 0, MIN_THINKING]
