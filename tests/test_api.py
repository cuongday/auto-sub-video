import time
import pytest
from fastapi.testclient import TestClient
from autosub import api, config, jobs, pipeline
from tests.fakes import FakeASR, FakeLLM, FakeTTS, fake_separate
from tests.fixtures import make_video

def engines():
    return pipeline.Engines(separate=fake_separate(), asr=lambda l, m: FakeASR(), llm=lambda p, m: FakeLLM(),
                            tts=lambda n: FakeTTS())

@pytest.fixture
def client(monkeypatch, tmp_path):
    q = jobs.JobQueue(engines)
    monkeypatch.setattr(api, "QUEUE", q)
    monkeypatch.setattr(config, "HOST_ROOT", tmp_path)       # test videos are made under tmp_path
    with TestClient(api.app) as c:
        yield c

def rel(p, tmp_path):
    return str(p.relative_to(tmp_path))

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
    r = client.post("/api/jobs", json={"path": rel(src, tmp_path)})
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
    j = client.post("/api/jobs", json={"path": rel(src, tmp_path)}).json()
    assert (j["info"]["width"], j["info"]["height"]) == (360, 640)
    assert j["settings"]["region"]["y"] == 0.78
    land = client.post("/api/jobs", json={"path": rel(make_video(tmp_path / "w.mp4", seconds=2), tmp_path)}).json()
    assert land["settings"]["region"]["y"] == 0.8

def test_file_range_requests(client, tmp_path):
    src = make_video(tmp_path / "r.mp4", seconds=2)
    jid = client.post("/api/jobs", json={"path": rel(src, tmp_path)}).json()["id"]
    full = client.get(f"/api/jobs/{jid}/files/source")
    assert full.status_code == 200 and full.content == src.read_bytes()
    assert full.headers["accept-ranges"] == "bytes"
    part = client.get(f"/api/jobs/{jid}/files/source", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == src.read_bytes()[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{src.stat().st_size}"
    tail = client.get(f"/api/jobs/{jid}/files/source", headers={"Range": "bytes=-50"})
    assert tail.status_code == 206 and tail.content == src.read_bytes()[-50:]
    assert client.get(f"/api/jobs/{jid}/files/source", headers={"Range": "bytes=999999999-"}).status_code == 416

def test_storage_down_returns_503(client, monkeypatch):
    from autosub import storage
    class Down(storage.MemoryStore):
        def list(self, prefix):
            raise storage.StorageError("connection refused")
    storage.set_store(Down())
    r = client.get("/api/jobs")
    assert r.status_code == 503 and "MinIO" in r.json()["detail"]

def test_bad_path(client):
    assert client.post("/api/jobs", json={"path": "nope.mp4"}).status_code == 400
    assert client.post("/api/jobs", json={"path": "../../etc/passwd"}).status_code == 400

def test_browse_and_video_dir_setting(client, tmp_path):
    (tmp_path / "Phim" / "Tap1").mkdir(parents=True)
    make_video(tmp_path / "Phim" / "a.mp4", seconds=1)
    r = client.get("/api/browse", params={"path": "Phim"}).json()
    assert [d["name"] for d in r["dirs"]] == ["Tap1"] and [f["path"] for f in r["files"]] == ["Phim/a.mp4"]
    assert client.get("/api/browse", params={"path": ".."}).status_code == 400
    assert client.get("/api/app-settings").json() == {"video_dir": "", "browse_available": True}
    assert client.put("/api/app-settings", json={"video_dir": "Phim/Tap1"}).json()["video_dir"] == "Phim/Tap1"
    assert client.put("/api/app-settings", json={"video_dir": "Phim/a.mp4"}).status_code == 400
    assert client.put("/api/app-settings", json={"video_dir": "../x"}).status_code == 400
    assert client.get("/api/app-settings").json()["video_dir"] == "Phim/Tap1"
    jid = client.post("/api/jobs", json={"path": "Phim/a.mp4"}).json()["id"]
    assert client.get(f"/api/jobs/{jid}").json()["name"] == "a.mp4"

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
