import pytest
from fastapi.testclient import TestClient
from autosub import api, asr as asr_mod, jobs, segmenter
from tests.test_api import engines

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "QUEUE", jobs.JobQueue(engines))
    with TestClient(api.app) as c:
        yield c

def test_get_asr_ko_uses_whisper_with_korean(monkeypatch):
    monkeypatch.setattr(asr_mod, "available", lambda lang: (True, ""))
    a = asr_mod.get_asr("ko")
    assert a.language == "ko" and a.model == "large-v3-turbo"

def test_ko_text_len_counts_spaces():
    assert segmenter.text_len("안녕 하세요", "ko") == 6

def test_options_lists_korean(client):
    assert client.get("/api/options").json()["asr"]["ko"]
