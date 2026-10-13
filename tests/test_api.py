import time
import pytest
from fastapi.testclient import TestClient
from autosub import api, jobs, pipeline
from tests.fakes import FakeASR, FakeLLM, FakeTTS, fake_separate
from tests.fixtures import make_video

def engines():
    return pipeline.Engines(separate=fake_separate(), asr=lambda l, m: FakeASR(), llm=lambda p, m: FakeLLM(),
                            tts=lambda n: FakeTTS())

@pytest.fixture
def client(monkeypatch):
    q = jobs.JobQueue(engines)
    monkeypatch.setattr(api, "QUEUE", q)
    with TestClient(api.app) as c:
        yield c

def wait(c, jid, states, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/jobs/{jid}").json()
        if j["state"] in states:
            return j
        time.sleep(0.1)
    raise AssertionError(j["state"])

def test_full_flow(client, tmp_path):
    src = make_video(tmp_path / "clip.mp4", seconds=5)
    r = client.post("/api/jobs", json={"path": str(src)})
    assert r.status_code == 200, r.text
    j = r.json(); jid = j["id"]
    assert j["info"]["width"] == 640 and len(j["frames"]) == 6
    assert client.get(f"/api/jobs/{jid}/files/frames/f0.jpg").status_code == 200
    assert client.get(f"/api/jobs/{jid}/files/../../etc/passwd").status_code == 404

    s = j["settings"]; s["cover"] = "solid"; s["region"] = {"x": 0, "y": 0.8, "w": 1, "h": 0.2}
    assert client.put(f"/api/jobs/{jid}/settings", json=s).json()["settings"]["cover"] == "solid"
    assert client.put(f"/api/jobs/{jid}/settings", json={**s, "region": {"x": 0.5, "y": 0, "w": 0.9, "h": 0.1}}).status_code == 422

    assert client.post(f"/api/jobs/{jid}/run", json={"mode": "review"}).status_code == 200
    wait(client, jid, {"awaiting_review"})
    data = client.get(f"/api/jobs/{jid}/segments").json()
    segs = data["segments"]
    assert len(segs) == 3 and len(data["slots"]) == 3
    assert client.get(f"/api/jobs/{jid}/context").json()["summary"]

    bad = [dict(segs[0], start=2, end=1)]
    assert client.put(f"/api/jobs/{jid}/segments", json=bad).status_code == 422
    segs[0]["vi"] = "Đã sửa"
    assert client.put(f"/api/jobs/{jid}/segments", json=segs).status_code == 200
    assert client.get(f"/api/jobs/{jid}").json()["segments_edited"]

    r = client.post(f"/api/jobs/{jid}/segments/1/preview-tts")
    assert r.status_code == 200 and float(r.headers["x-duration"]) > 0

    r = client.post(f"/api/jobs/{jid}/retranslate", json={"ids": [2]})
    assert r.json()["segments"][0]["vi"] == "Đã sửa"

    assert client.post(f"/api/jobs/{jid}/run", json={"mode": "review", "from_step": "translate"}).status_code == 409
    assert client.post(f"/api/jobs/{jid}/run", json={"mode": "review", "from_step": "tts"}).status_code == 200
    j = wait(client, jid, {"done", "error"})
    assert j["state"] == "done" and j["files"]["output.mp4"]
    r = client.get(f"/api/jobs/{jid}/files/output.mp4?download=1")
    assert r.status_code == 200 and "clip.vi.mp4" in r.headers["content-disposition"]
    assert "Đã sửa" in client.get(f"/api/jobs/{jid}/files/subs.srt").text

    assert client.post(f"/api/jobs/{jid}/preview-render", json={"t": 1}).status_code == 200
    assert client.delete(f"/api/jobs/{jid}").status_code == 200
    assert client.get(f"/api/jobs/{jid}").status_code == 404

def test_portrait_gets_portrait_region(client, tmp_path):
    src = make_video(tmp_path / "tall.mp4", seconds=2, size=(360, 640))
    j = client.post("/api/jobs", json={"path": str(src)}).json()
    assert (j["info"]["width"], j["info"]["height"]) == (360, 640)
    assert j["settings"]["region"]["y"] == 0.78
    land = client.post("/api/jobs", json={"path": str(make_video(tmp_path / "w.mp4", seconds=2))}).json()
    assert land["settings"]["region"]["y"] == 0.8

def test_bad_path(client):
    assert client.post("/api/jobs", json={"path": "/nope.mp4"}).status_code == 400

def test_upload(client, tmp_path):
    src = make_video(tmp_path / "up.mp4", seconds=2)
    r = client.post("/api/jobs", files={"file": ("up.mp4", src.read_bytes(), "video/mp4")})
    assert r.status_code == 200 and r.json()["uploaded"]

def test_options_and_health(client):
    o = client.get("/api/options").json()
    assert "gemini" in o["llm"] and o["asr"]["en"][0]["id"] == "large-v3-turbo"
    h = client.get("/api/health").json()
    assert any(c["name"] == "ffmpeg" and c["ok"] for c in h["checks"])

def test_voice_sample_and_voices(client):
    r = client.post("/api/tts/sample", json={"engine": "edge", "voice": "v", "rate": 1.2})
    assert r.status_code == 200 and len(r.content) > 1000
    assert client.get("/api/tts/edge/voices").json()[0]["id"] == "v"

def test_presets(client):
    from autosub.models import JobSettings
    s = JobSettings(lang="en").model_dump(mode="json")
    assert "phim" in client.post("/api/presets", json={"name": "phim", "settings": s}).json()
    assert client.delete("/api/presets/phim").json() == {}
