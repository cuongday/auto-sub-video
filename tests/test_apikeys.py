import pytest
from fastapi.testclient import TestClient
from autosub import api, apikeys, config, storage
from autosub.llm import LLMError, get_llm

KEY = "sk-test-0123456789abcdefWXYZ"

@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(config, "APP_SECRET", "s3cret")
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)

def test_key_is_encrypted_and_never_returned(_memory_store):
    with TestClient(api.app) as c:
        first = c.get("/api/api-keys").json()
        assert [p["id"] for p in first] == list(apikeys.PROVIDERS) and first[0]["label"] == "OpenAI"
        assert first[0]["source"] is None
        r = c.put("/api/api-keys/openai", json={"key": f"  {KEY} "}).json()[0]
        assert r["source"] == "web" and r["last4"] == "WXYZ" and r["sha256"] == apikeys.fingerprint(KEY)
        assert KEY not in c.get("/api/api-keys").text
        raw = storage.read_json(_memory_store, apikeys.KEYS, default={})
        assert KEY not in str(raw)
        assert apikeys.get("openai") == KEY
        assert c.get("/api/options").json()["engines"]["llm"]["openai"]["ok"] is True
        assert c.put("/api/api-keys/openai", json={"key": "short"}).status_code == 400
        assert c.put("/api/api-keys/gemini", json={"key": KEY}).status_code == 404
        assert c.delete("/api/api-keys/openai").json()[0]["source"] is None
        assert apikeys.get("openai") is None

def test_web_key_wins_over_env_and_secret_change(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-from-env-000000000000ENV1")
    assert apikeys.info("openai")["source"] == "env"
    apikeys.save("openai", KEY)
    assert apikeys.get("openai") == KEY
    monkeypatch.setattr(config, "APP_SECRET", "other")      # can no longer decrypt: fall back to .env
    assert apikeys.get("openai").endswith("ENV1")
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)
    assert apikeys.info("openai") == {"source": None, "last4": "", "sha256": "", "saved": None, "stale": True}

def test_openai_client_uses_saved_key():
    with pytest.raises(LLMError, match="OpenAI API key"):
        get_llm("openai").client()
    apikeys.save("openai", KEY)
    assert get_llm("openai").client().api_key == KEY
