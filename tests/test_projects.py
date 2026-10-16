import time
import pytest
from fastapi.testclient import TestClient
from autosub import api, config, jobs
from tests.test_api import engines, rel, wait
from tests.fixtures import make_video

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "QUEUE", jobs.JobQueue(engines))
    monkeypatch.setattr(config, "HOST_ROOT", tmp_path)
    with TestClient(api.app) as c:
        yield c

def new_job(c, tmp_path, name, project=None):
    src = make_video(tmp_path / name, seconds=5)
    r = c.post("/api/jobs", json={"path": rel(src, tmp_path), "project": project})
    assert r.status_code == 200, r.text
    return r.json()

def test_project_crud_and_one_per_channel(client):
    p = client.post("/api/projects", json={"name": "Kênh A", "source_url": "https://www.douyin.com/user/X"}).json()
    again = client.post("/api/projects", json={"name": "khác", "source_url": "https://www.douyin.com/user/X"}).json()
    assert again["id"] == p["id"]
    assert client.post("/api/projects", json={"name": "  "}).status_code == 400
    assert client.put(f"/api/projects/{p['id']}", json={"name": "Kênh A2"}).json()["name"] == "Kênh A2"
    assert [x["name"] for x in client.get("/api/projects").json()] == ["Kênh A2"]
    assert client.post("/api/jobs/0123456789/run", json={}).status_code == 404

def test_preset_from_a_video_applies_to_new_videos(client, tmp_path):
    pid = client.post("/api/projects", json={"name": "Kênh"}).json()["id"]
    a = new_job(client, tmp_path, "a.mp4", pid)
    s = a["settings"]
    s["region"] = {"x": 0.1, "y": 0.6, "w": 0.8, "h": 0.12}
    s["extra_regions"] = [{"x": 0.7, "y": 0.02, "w": 0.25, "h": 0.08}]
    s["cover"] = "solid"
    client.put(f"/api/jobs/{a['id']}/settings", json=s)
    pv = client.post(f"/api/projects/{pid}/preset", json={"job_id": a["id"]}).json()
    assert pv["preset_from"] == "a.mp4" and pv["preset"]["region"]["y"] == 0.6

    b = new_job(client, tmp_path, "b.mp4", pid)
    assert b["project"] == pid
    assert b["settings"]["region"] == s["region"] and b["settings"]["extra_regions"] == s["extra_regions"]
    assert b["settings"]["cover"] == "solid"
    other = new_job(client, tmp_path, "c.mp4")
    assert other["project"] is None and other["settings"]["cover"] != "solid"

    # moving an existing video into the project can take the preset too
    moved = client.put(f"/api/jobs/{other['id']}/project", json={"project": pid, "apply_preset": True}).json()
    assert moved["project"] == pid and moved["settings"]["cover"] == "solid"
    assert client.get("/api/projects").json()[0]["jobs"] == 3

    client.delete(f"/api/projects/{pid}")
    assert client.get(f"/api/jobs/{b['id']}").json()["project"] is None

def test_run_project_runs_only_new_videos_then_approve(client, tmp_path):
    pid = client.post("/api/projects", json={"name": "Kênh"}).json()["id"]
    a = new_job(client, tmp_path, "a.mp4", pid)
    b = new_job(client, tmp_path, "b.mp4", pid)
    outside = new_job(client, tmp_path, "x.mp4")
    r = client.post(f"/api/projects/{pid}/run", json={}).json()
    assert sorted(r["queued"]) == sorted([a["id"], b["id"]])
    for jid in (a["id"], b["id"]):
        wait(client, jid, {"done"})
    assert client.get(f"/api/jobs/{outside['id']}").json()["state"] == "new"
    assert client.post(f"/api/projects/{pid}/run", json={}).json()["queued"] == []   # nothing new left

    assert client.post(f"/api/jobs/{outside['id']}/approve", json={}).status_code == 409
    j = client.post(f"/api/jobs/{a['id']}/approve", json={}).json()
    assert j["state"] == "approved"
    assert client.get("/api/projects").json()[0]["counts"] == {"approved": 1, "done": 1}
    # editing an approved video sends it back to "done"
    segs = client.get(f"/api/jobs/{a['id']}/segments").json()["segments"]
    segs[0]["vi"] = "Sửa lại"
    r = client.put(f"/api/jobs/{a['id']}/segments", json=segs)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/jobs/{a['id']}").json()["state"] == "done"
    client.post(f"/api/jobs/{a['id']}/approve", json={})
    assert client.post(f"/api/jobs/{a['id']}/approve", json={"approved": False}).json()["state"] == "done"
