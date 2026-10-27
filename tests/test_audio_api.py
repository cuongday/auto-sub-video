"""HTTP API of audio-story projects: settings, chunked background upload, music, scripts, run."""
import json
import os
import threading
import time
import pytest
from fastapi.testclient import TestClient
from autosub import api, config, jobs, projects, store
from autosub.audio import background
from autosub.storage import get_store
from tests.test_api import engines
from tests.fixtures import make_video
from tests.test_jobs import GATES, audio_flow, wait_for  # noqa: F401  (fixture)

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "QUEUE", jobs.JobQueue(engines))
    monkeypatch.setattr(config, "HOST_ROOT", tmp_path)
    monkeypatch.setattr(config, "FFMPEG_PRESET", "ultrafast")
    with TestClient(api.app) as c:
        yield c

def new_audio(c, name="Truyện"):
    r = c.post("/api/projects", json={"name": name, "kind": "audio"})
    assert r.status_code == 200, r.text
    return r.json()

def script(c, pid, name, text="Một câu. Hai câu.", run=0):
    return c.post(f"/api/projects/{pid}/audio/scripts?run={run}", files={"file": (name, text.encode(), "text/plain")})

def upload_bg(c, pid, data: bytes, name="nen.mp4", order=None, resend=None):
    r = c.post(f"/api/projects/{pid}/audio/background/start", json={"name": name, "size": len(data)})
    assert r.status_code == 200, r.text
    uid = r.json()["upload_id"]
    n = len(data)
    cuts = [0, n // 3, 2 * n // 3, n]
    pieces = [(cuts[i], data[cuts[i]:cuts[i + 1]]) for i in range(3)]
    for i in (order or [0, 1, 2]) + ([resend] if resend is not None else []):
        off, chunk = pieces[i]
        r = c.put(f"/api/projects/{pid}/audio/background/{uid}?offset={off}", content=chunk)
        assert r.status_code == 200, r.text
    return uid, r.json()

def test_create_audio_project_and_settings(client):
    p = new_audio(client)
    assert p["kind"] == "audio" and p["audio"]["music_volume"] == 0.15 and p["audio"]["rev"] == 0
    r = client.put(f"/api/projects/{p['id']}/audio",
                   json={"engine": "edge", "voice": "vi-VN-HoaiMyNeural", "rate": 1.1, "music_volume": 0.3})
    assert r.status_code == 200, r.text
    a = r.json()["audio"]
    assert a["rev"] == 1 and a["voice"] == "vi-VN-HoaiMyNeural" and a["rate"] == 1.1 and a["music_volume"] == 0.3
    assert client.put(f"/api/projects/{p['id']}/audio", json={"music_volume": 2}).status_code == 422
    assert client.put(f"/api/projects/{p['id']}/audio", json={}).json()["audio"]["rev"] == 1
    sub = client.post("/api/projects", json={"name": "Phụ đề"}).json()
    assert sub["kind"] == "sub"
    assert client.put(f"/api/projects/{sub['id']}/audio", json={"rate": 1.0}).status_code == 404

def test_chunked_background_upload(client, tmp_path):
    pid = new_audio(client)["id"]
    data = make_video(tmp_path / "bg.mp4", seconds=2, size=(320, 180), with_text=False).read_bytes()
    uid, last = upload_bg(client, pid, data, order=[2, 0, 1], resend=1)
    assert last["received"] == len(data)
    r = client.post(f"/api/projects/{pid}/audio/background/{uid}/finish")
    assert r.status_code == 200, r.text
    a = r.json()["audio"]
    assert a["background"] == projects.bg_key(pid, ".mp4") and a["rev"] == 1
    assert a["background_state"] in ("processing", "ready") and a["background_info"]["width"] == 320
    wait_for(lambda: projects.get(pid).audio.background_state != "processing", timeout=60)
    assert projects.get(pid).audio.background_state == "ready"
    assert get_store().get_bytes(projects.bg_key(pid, ".mp4")) == data
    assert not (config.WORK_DIR / "_uploads" / uid).exists()        # data gone once stored
    assert client.post(f"/api/projects/{pid}/audio/background/{uid}/finish").json()["audio"]["rev"] == 1  # idempotent
    # the preview streams bg_loop.mp4 with Range
    r = client.get(f"/api/projects/{pid}/audio/background", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100
    assert r.content == get_store().get_bytes(projects.bg_loop_key(pid))[:100]
    # a new background in another format replaces the old original
    uid, _ = upload_bg(client, pid, data, name="nen2.mkv")
    assert client.post(f"/api/projects/{pid}/audio/background/{uid}/finish").status_code == 200
    assert projects.get(pid).audio.background == projects.bg_key(pid, ".mkv")
    wait_for(lambda: not api.QUEUE.is_active(background.task_key(pid)), timeout=60)
    assert get_store().stat(projects.bg_key(pid, ".mp4")) is None
    assert projects.get(pid).audio.background_state == "ready"

def test_finish_returns_before_storing(client, tmp_path, audio_flow):  # noqa: F811
    """finish only probes and queues: the 1 GB transfer to MinIO happens in the audio lane."""
    pid = new_audio(client)["id"]
    blockers = [script(client, pid, f"p{i}.txt", run=1).json()["id"] for i in range(2)]
    wait_for(lambda: all(store.load(j).state == "running" for j in blockers))    # both audio slots taken
    data = make_video(tmp_path / "bg.mp4", seconds=1, size=(160, 90), with_text=False).read_bytes()
    uid, _ = upload_bg(client, pid, data)
    r = client.post(f"/api/projects/{pid}/audio/background/{uid}/finish")
    assert r.status_code == 200 and r.json()["audio"]["background_state"] == "processing"
    assert get_store().stat(projects.bg_key(pid, ".mp4")) is None
    assert (config.WORK_DIR / "_uploads" / uid).exists()
    assert client.post(f"/api/projects/{pid}/audio/background/{uid}/finish").status_code == 200
    assert client.put(f"/api/projects/{pid}/audio/background/{uid}?offset=0", content=b"x").status_code == 409
    for j in blockers:
        GATES.setdefault(j, threading.Event()).set()
    wait_for(lambda: projects.get(pid).audio.background_state == "ready", timeout=60)
    assert get_store().get_bytes(projects.bg_key(pid, ".mp4")) == data

def test_store_failure_keeps_upload_and_retry_finishes(client, tmp_path, monkeypatch):
    pid = new_audio(client)["id"]
    data = make_video(tmp_path / "bg.mp4", seconds=1, size=(160, 90), with_text=False).read_bytes()
    uid, _ = upload_bg(client, pid, data)
    st = get_store()
    real, fails = st.put_file, []

    def flaky(key, path):
        if key.endswith("/background.mp4") and not fails:
            fails.append(key)
            raise RuntimeError("MinIO tạm lỗi")
        return real(key, path)
    monkeypatch.setattr(st, "put_file", flaky)
    assert client.post(f"/api/projects/{pid}/audio/background/{uid}/finish").status_code == 200
    wait_for(lambda: projects.get(pid).audio.background_state != "processing", timeout=30)
    a = projects.get(pid).audio
    assert a.background_state == "error" and "MinIO" in a.background_error
    assert (config.WORK_DIR / "_uploads" / uid).exists()
    r = client.post(f"/api/projects/{pid}/audio/background/{uid}/finish")     # retry: no chunks sent again
    assert r.status_code == 200
    wait_for(lambda: projects.get(pid).audio.background_state != "processing", timeout=60)
    assert projects.get(pid).audio.background_state == "ready"
    assert st.get_bytes(projects.bg_key(pid, ".mp4")) == data and not (config.WORK_DIR / "_uploads" / uid).exists()

def test_chunk_over_64mb_413(client):
    pid = new_audio(client)["id"]
    uid = client.post(f"/api/projects/{pid}/audio/background/start",
                      json={"name": "a.mp4", "size": 100 << 20}).json()["upload_id"]

    def body():                                   # no Content-Length: the limit is checked while streaming
        piece = b"\0" * (1 << 20)
        for _ in range(65):
            yield piece
    r = client.put(f"/api/projects/{pid}/audio/background/{uid}?offset=0", content=body())
    assert r.status_code == 413

def test_finish_missing_bytes_400(client):
    pid = new_audio(client)["id"]
    uid = client.post(f"/api/projects/{pid}/audio/background/start", json={"name": "a.mp4", "size": 100}).json()["upload_id"]
    assert client.put(f"/api/projects/{pid}/audio/background/{uid}?offset=0", content=b"x" * 60).json()["received"] == 60
    assert client.put(f"/api/projects/{pid}/audio/background/{uid}?offset=80", content=b"x" * 30).status_code == 413
    assert client.post(f"/api/projects/{pid}/audio/background/{uid}/finish").status_code == 400
    assert client.put(f"/api/projects/{pid}/audio/background/{'g' * 32}?offset=0", content=b"x").status_code == 404
    assert client.put(f"/api/projects/{pid}/audio/background/{'0' * 32}?offset=0", content=b"x").status_code == 404

def test_start_too_large_413(client):
    pid = new_audio(client)["id"]
    r = client.post(f"/api/projects/{pid}/audio/background/start",
                    json={"name": "a.mp4", "size": config.AUDIO_BG_MAX_BYTES + 1})
    assert r.status_code == 413
    r = client.post(f"/api/projects/{pid}/audio/background/start", json={"name": "a.pdf", "size": 10})
    assert r.status_code == 400

def test_old_uploads_cleaned_on_new_start(client):
    pid = new_audio(client)["id"]
    old = client.post(f"/api/projects/{pid}/audio/background/start", json={"name": "a.mp4", "size": 10}).json()["upload_id"]
    up = config.WORK_DIR / "_uploads"
    t = time.time() - 25 * 3600
    for f in up.iterdir():
        os.utime(f, (t, t))
    client.post(f"/api/projects/{pid}/audio/background/start", json={"name": "b.mp4", "size": 10})
    assert not (up / old).exists() and not (up / f"{old}.json").exists()

def test_upload_scripts_rejects_bad_files(client):
    pid = new_audio(client)["id"]
    r = script(client, pid, "a.pdf")
    assert r.status_code == 400 and ".txt" in r.json()["detail"]
    assert script(client, pid, "big.txt", "x" * (21 << 20)).status_code == 413
    r = script(client, pid, "chuong-1.txt")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["kind"] == "audio" and j["name"] == "chuong-1" and j["project"] == pid and j["state"] == "new"
    assert j["audio_part"] == {"script_name": "chuong-1.txt", "script_kind": "txt", "index": 0}

def test_upload_three_scripts_two_run(client, audio_flow):  # noqa: F811
    pid = new_audio(client)["id"]
    ids = [script(client, pid, f"p{i}.txt", run=1).json()["id"] for i in range(3)]
    st = lambda: [store.load(j).state for j in ids]  # noqa: E731
    wait_for(lambda: st().count("running") == 2, timeout=10)
    assert st().count("queued") == 1
    def release():
        for j in ids:
            GATES.setdefault(j, threading.Event()).set()
        return all(s == "done" for s in st())
    wait_for(release, timeout=20)

def test_natural_order(client):
    pid = new_audio(client)["id"]
    a = script(client, pid, "chuong-10.txt").json()["id"]
    b = script(client, pid, "chuong-2.txt").json()["id"]
    assert store.load(a).audio_part.index == 1 and store.load(b).audio_part.index == 0

def test_run_project_queues_unfinished_and_stale_parts(client, audio_flow):  # noqa: F811
    pid = new_audio(client)["id"]
    a = script(client, pid, "b.txt").json()["id"]
    b = script(client, pid, "a.txt").json()["id"]
    r = client.post(f"/api/projects/{pid}/run", json={})
    assert r.json()["queued"] == [b, a]                 # part order
    for j in (a, b):
        GATES.setdefault(j, threading.Event()).set()
    wait_for(lambda: all(store.load(j).state == "done" for j in (a, b)), timeout=20)
    assert client.post(f"/api/projects/{pid}/run", json={}).json()["queued"] == []

def test_view_has_meta(client):
    pid = new_audio(client)["id"]
    jid = script(client, pid, "a.txt").json()["id"]
    assert client.get(f"/api/jobs/{jid}").json()["meta"] is None
    store.save_json(jid, "meta.json", {"duration": 12.5, "chars": 600000, "lines": []})
    j = store.load(jid); j.steps["tts"].status = "done"; store.save(j)
    assert client.get(f"/api/jobs/{jid}").json()["meta"] == {"duration": 12.5, "chars": 600000}

def test_music_upload_and_delete(client):
    pid = new_audio(client)["id"]
    r = client.post(f"/api/projects/{pid}/audio/music", files={"file": ("m.mp3", b"ID3abc", "audio/mpeg")})
    assert r.status_code == 200 and r.json()["audio"]["music"] == projects.music_key(pid, ".mp3")
    assert r.json()["audio"]["rev"] == 1
    assert client.get(f"/api/projects/{pid}/audio/music").content == b"ID3abc"
    assert client.post(f"/api/projects/{pid}/audio/music", files={"file": ("m.pdf", b"x")}).status_code == 400
    r = client.delete(f"/api/projects/{pid}/audio/music")
    assert r.json()["audio"]["music"] is None and r.json()["audio"]["rev"] == 2
    assert get_store().stat(projects.music_key(pid, ".mp3")) is None
    assert client.get(f"/api/projects/{pid}/audio/music").status_code == 404

def test_bulk_delete_refused_while_background_normalizes(client, monkeypatch):
    pid = new_audio(client)["id"]
    monkeypatch.setattr(api.QUEUE, "is_active", lambda k: k == background.task_key(pid))
    r = client.post("/api/projects/delete", json={"ids": [pid]})
    assert r.status_code == 409
    monkeypatch.undo()
    d = config.WORK_DIR / "_projects" / pid
    d.mkdir(parents=True)
    r = client.post("/api/projects/delete", json={"ids": [pid]})
    assert r.status_code == 200 and not d.exists()

def test_startup_resumes_processing_background(monkeypatch, tmp_path):
    p = projects.create("T", kind="audio")
    q = projects.create("U", kind="audio")
    r = projects.create("V", kind="audio")
    key = projects.bg_key(p.id, ".mp4")
    get_store().put_bytes(key, b"video")
    for x, k in ((p, key), (q, projects.bg_key(q.id, ".mp4")), (r, projects.bg_key(r.id, ".mkv"))):
        projects.update(x.id, lambda y, k=k: (setattr(y.audio, "background", k),
                                              setattr(y.audio, "background_state", "processing")))
    started = []
    monkeypatch.setattr(background, "start", lambda pid, local=None: started.append((pid, local and local.name)) or True)
    up = config.WORK_DIR / "_uploads"
    up.mkdir(parents=True)
    (up / ("a" * 32)).write_bytes(b"x"); (up / ("a" * 32 + ".json")).write_text(json.dumps({}))
    # r's finished upload, never stored in MinIO: resumed from disk and kept despite its age
    (up / ("c" * 32)).write_bytes(b"local")
    (up / ("c" * 32 + ".json")).write_text(json.dumps({"pid": r.id, "name": "n.mkv", "size": 5, "received": [[0, 5]],
                                                       "finished": True, "key": projects.bg_key(r.id, ".mkv")}))
    t = time.time() - 25 * 3600
    for f in up.iterdir():
        os.utime(f, (t, t))
    (up / ("b" * 32)).write_bytes(b"fresh")
    monkeypatch.setattr(api, "QUEUE", jobs.JobQueue(engines))
    with TestClient(api.app):
        pass
    assert sorted(started) == sorted([(p.id, None), (r.id, "c" * 32)])
    assert projects.get(q.id).audio.background_state == "error"
    assert sorted(f.name for f in up.iterdir()) == ["b" * 32, "c" * 32, "c" * 32 + ".json"]
