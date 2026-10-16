import pytest
from fastapi.testclient import TestClient
from autosub import api, auth, config, jobs
from tests.test_api import engines

@pytest.fixture
def locked(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "APP_PASSWORD", "mật-khẩu-1")
    monkeypatch.setattr(config, "HOST_ROOT", tmp_path)
    monkeypatch.setattr(api, "QUEUE", jobs.JobQueue(engines))
    with TestClient(api.app) as c:
        yield c

def test_off_by_default(monkeypatch):
    monkeypatch.setattr(config, "APP_PASSWORD", "")
    monkeypatch.setattr(api, "QUEUE", jobs.JobQueue(engines))
    with TestClient(api.app) as c:
        assert c.get("/api/jobs").status_code == 200
        assert c.get("/api/auth").json() == {"required": False, "ok": True}

def test_api_needs_login(locked):
    assert locked.get("/api/jobs").status_code == 401
    assert locked.get("/api/browse").status_code == 401
    assert locked.get("/api/auth").json() == {"required": True, "ok": False}
    assert locked.post("/api/auth/login", json={"password": "sai"}).status_code == 401
    r = locked.post("/api/auth/login", json={"password": "mật-khẩu-1"})
    assert r.status_code == 200 and "autosub_session" in r.cookies
    assert locked.get("/api/jobs").status_code == 200
    locked.post("/api/auth/logout")
    assert locked.get("/api/jobs").status_code == 401

def test_tokens_are_signed():
    tok = auth.make_token("k")
    assert auth.valid(tok, "k") and not auth.valid(tok, "other") and not auth.valid(tok + "x", "k")
    assert not auth.valid("", "k")
