"""Review API: vsmov search, review projects (prepare, split, music, notebook) and the script of a part."""
import shutil
import time
import pytest
from fastapi.testclient import TestClient
from autosub import api, config, jobs, media, pipeline, projects, review_api, store, vsmov
from autosub.models import Episode, MovieMeta, Notebook, NotebookCharacter, SubTrack
from autosub.projects import ReviewProject
from autosub.review import pace, parts
from autosub.storage import get_store, write_json
from autosub.tts.base import cache_key
from tests.fakes import FakeASR, FakeLLM, FakeTTS, fake_separate, review_llm_hook
from tests.fixtures import make_video
from tests.review_helpers import VTT_20S, ReviewRig

def engines():
    return pipeline.Engines(separate=fake_separate(), asr=lambda l, m, **kw: FakeASR(),
                            llm=lambda p, m: FakeLLM(review_llm_hook), tts=lambda n: FakeTTS())

class DownLLM:
    def generate_json(self, prompt, schema, temperature=0.3):
        raise RuntimeError("LLM hết hạn mức")

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "QUEUE", jobs.JobQueue(engines))
    monkeypatch.setattr(config, "FFMPEG_PRESET", "ultrafast")
    # 20 syllables/min for FakeTTS keeps narration short, so renders stay quick
    write_json(get_store(), pace.PACE_KEY, {cache_key("fake", "", 1.0, "", pace.PACE_SAMPLE): 20})
    with TestClient(api.app) as c:
        yield c

@pytest.fixture
def rig(client, tmp_path):
    return ReviewRig(tmp_path, seconds=125)

def wait_for(fn, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if r := fn():
            return r
        time.sleep(0.1)
    raise AssertionError("timeout")

def wait(c, jid, states):
    return wait_for(lambda: (j := c.get(f"/api/jobs/{jid}").json())["state"] in states and j)

def done(c, jid):
    j = wait(c, jid, {"done", "error", "awaiting_review"})
    assert j["state"] == "done", j.get("error")
    return j

def detail(c, pid):
    return c.get(f"/api/review/projects/{pid}").json()

@pytest.fixture
def fake_vsmov(monkeypatch, tmp_path):
    clip = make_video(tmp_path / "ep.mp4", seconds=20, size=(320, 180))
    state = {"type": "single", "countries": ["Hàn Quốc"], "fail": False,
             "episodes": [Episode(name="Full", slug="full", embed="https://e/full")]}

    def movie(slug):
        meta = MovieMeta(slug=slug, name="Phim A", type=state["type"], countries=state["countries"])
        eps = state["episodes"]
        return vsmov.MovieDetail(meta, [vsmov.Server("4K", eps), vsmov.Server("Vietsub #1", eps)], "Vietsub #1")

    def download(embed, dest, progress=None, cancel=None, workers=8):
        if state["fail"]:
            raise vsmov.VsmovError("Tải đoạn 3/9 lỗi")
        shutil.copyfile(clip, dest)
        if progress:
            progress(1.0)
        return vsmov.Embed("https://e", "h", "https://e/m.m3u8",
                           [SubTrack(code="eng", url="https://e/eng.vtt"), SubTrack(code="vie", url="https://e/vie.vtt"),
                            SubTrack(code="../x", url="https://e/x.vtt")])

    monkeypatch.setattr(vsmov, "movie", movie)
    monkeypatch.setattr(vsmov, "download", download)
    monkeypatch.setattr(vsmov, "fetch_subtitle", lambda url, embed: VTT_20S)
    return state

def test_upload_project_prepares_and_splits(client, tmp_path):
    src = make_video(tmp_path / "phim.mp4", seconds=125, size=(320, 180))
    r = client.post("/api/review/projects/upload", data={"lang": "en"},
                    files={"file": ("phim.mp4", src.read_bytes(), "video/mp4")})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["kind"] == "review" and p["review"]["source"] == "upload" and p["review"]["movie"]["name"] == "phim"
    film = detail(client, p["id"])["films"][0]
    assert film["kind"] == "film" and film["settings"]["lang"] == "en" and film["settings"]["separate"] is False
    done(client, film["id"])
    base = f"/api/review/projects/{p['id']}"
    cuts = client.post(f"{base}/split", json={"film_job": film["id"], "parts": 2}).json()["cuts"]
    assert len(cuts) == 1 and 60 <= cuts[0] <= 65
    assert client.put(f"{base}/parts", json={"film_job": film["id"], "cuts": [5]}).status_code == 409
    assert client.put(f"{base}/parts", json={"film_job": film["id"], "cuts": cuts}).status_code == 200
    d = detail(client, p["id"])
    assert [j["name"] for j in d["parts"]] == ["phim · Phần 1", "phim · Phần 2"]
    assert d["parts"][0]["film_state"] == "done" and d["parts"][0]["prev_approved"] is True
    assert d["parts"][1]["prev_approved"] is False and d["parts"][1]["notebook_stale"] is False

    rs = {**p["review"]["settings"], "minutes": 2}
    js = {**film["settings"], "tts_rate": 1.2}
    r = client.put(f"{base}/settings", json={"settings": rs, "job_settings": js, "parts_per_episode": 1})
    assert r.status_code == 200 and r.json()["review"]["settings"]["minutes"] == 2
    for j in detail(client, p["id"])["parts"]:
        assert j["review"]["minutes"] == 2 and j["settings"]["tts_rate"] == 1.2

def test_part2_blocked_until_part1_approved(client, rig):
    p1, p2 = parts.create_parts(store.load(rig.film.id), [62.0])
    r = client.post(f"/api/jobs/{p1.id}/run", json={"mode": "review"})
    assert r.status_code == 409 and r.json()["detail"] == "Phim chưa chuẩn bị xong"
    rig.film_done()
    r = client.post(f"/api/jobs/{p2.id}/run", json={"mode": "review"})
    assert r.status_code == 409 and r.json()["detail"] == "Phần 1 chưa được duyệt"
    v = client.get(f"/api/jobs/{p2.id}").json()
    assert v["prev_approved"] is False and v["film_state"] == "done"

    assert client.post(f"/api/jobs/{p1.id}/run", json={"mode": "auto"}).status_code == 200
    done(client, p1.id)
    api.QUEUE.engines_factory = lambda: pipeline.Engines(llm=lambda p, m: DownLLM())
    r = client.post(f"/api/jobs/{p1.id}/approve", json={})
    assert r.status_code == 502 and "sổ tay" in r.json()["detail"]
    assert client.get(f"/api/jobs/{p1.id}").json()["state"] == "done"
    api.QUEUE.engines_factory = engines
    assert client.post(f"/api/jobs/{p1.id}/approve", json={}).json()["state"] == "approved"
    nb = client.get(f"/api/review/projects/{rig.project.id}/notebook").json()
    assert [(e["job"], e["index"]) for e in nb["entries"]] == [(p1.id, 1)]

    assert client.get(f"/api/jobs/{p2.id}").json()["prev_approved"] is True
    assert client.post(f"/api/jobs/{p2.id}/run", json={"mode": "review"}).status_code == 200
    assert wait(client, p2.id, {"awaiting_review", "error"})["state"] == "awaiting_review"

def test_script_edit_marks_block_and_unapproves(client, rig):
    rig.film_done()
    jid = parts.create_parts(store.load(rig.film.id), [])[0].id
    client.post(f"/api/jobs/{jid}/run", json={"mode": "auto"})
    done(client, jid)
    assert client.post(f"/api/jobs/{jid}/approve", json={}).json()["state"] == "approved"

    s = client.get(f"/api/jobs/{jid}/script").json()
    assert s["target"] == 60 and s["estimate"] > 0 and len(s["blocks"]) == 4
    blocks = s["blocks"]
    blocks[1]["text"] = "Lời mở đầu do tôi viết."
    r = client.put(f"/api/jobs/{jid}/script", json=blocks)
    assert r.status_code == 200 and [b["edited"] for b in r.json()["blocks"]] == [False, True, False, False]
    j = client.get(f"/api/jobs/{jid}").json()
    assert j["state"] == "done" and j["segments_edited"]
    assert client.put(f"/api/jobs/{jid}/script", json=blocks + [blocks[0]]).status_code == 422

    b = client.post(f"/api/jobs/{jid}/script/blocks/1/rewrite", json={"instruction": "ngắn hơn"}).json()
    assert b["text"] == "Viết lại" and b["edited"]
    assert client.get(f"/api/jobs/{jid}/script").json()["blocks"][0]["text"] == "Viết lại"
    assert client.post(f"/api/jobs/{jid}/script/blocks/99/rewrite", json={}).status_code == 404

    v = client.put(f"/api/jobs/{jid}/review-settings", json={**j["review"], "aspect": "16:9"}).json()
    assert v["review"]["aspect"] == "16:9"
    assert client.post(f"/api/jobs/{jid}/script/rewrite").status_code == 200
    assert wait(client, jid, {"awaiting_review", "error"})["state"] == "awaiting_review"
    texts = [b["text"] for b in client.get(f"/api/jobs/{jid}/script").json()["blocks"]]
    assert "Lời mở đầu do tôi viết." in texts and "Viết lại" in texts

def test_reapprove_part1_marks_part2_stale(client, rig):
    rig.film_done()
    p1, p2 = parts.create_parts(store.load(rig.film.id), [62.0])
    client.post(f"/api/jobs/{p1.id}/run", json={"mode": "auto"})
    done(client, p1.id)
    client.post(f"/api/jobs/{p1.id}/approve", json={})
    client.post(f"/api/jobs/{p2.id}/run", json={"mode": "review"})
    assert wait(client, p2.id, {"awaiting_review", "error"})["state"] == "awaiting_review"
    assert client.get(f"/api/jobs/{p2.id}").json()["notebook_stale"] is False
    before = store.load_json(p2.id, "script.json")

    blocks = client.get(f"/api/jobs/{p1.id}/script").json()["blocks"]
    blocks[2]["text"] += " Thêm một câu."
    client.put(f"/api/jobs/{p1.id}/script", json=blocks)
    assert client.get(f"/api/jobs/{p1.id}").json()["state"] == "done"
    # part 2 already has a script: it renders while part 1 is unapproved
    assert client.post(f"/api/jobs/{p2.id}/run", json={"mode": "auto"}).status_code == 200
    done(client, p2.id)
    assert client.post(f"/api/jobs/{p1.id}/approve", json={}).json()["state"] == "approved"
    assert client.get(f"/api/jobs/{p2.id}").json()["notebook_stale"] is True
    assert store.load_json(p2.id, "script.json") == before

def test_project_run_cannot_skip_the_order(client, rig):
    rig.film_done()
    p1, p2 = parts.create_parts(store.load(rig.film.id), [62.0])
    r = client.post(f"/api/projects/{rig.project.id}/run", json={"states": ["new"], "apply_preset": False}).json()
    assert set(r["queued"]) == {p1.id, p2.id}
    j2 = wait(client, p2.id, {"error", "done", "awaiting_review"})
    assert j2["state"] == "error" and "Phần 1 chưa được duyệt" in j2["error"]
    assert not store.exists(p2.id, "script.json")
    done(client, p1.id)

class EditingLLM(FakeLLM):
    """Answers like the fake, but the user edits the part's script while the notebook is being updated."""
    def __init__(self, jid):
        super().__init__(review_llm_hook)
        self.jid = jid

    def generate_json(self, prompt, schema, temperature=0.3):
        if "entry" in schema["properties"]:
            s = store.load_json(self.jid, "script.json")
            s["blocks"][0]["text"] = "Sửa trong lúc duyệt"
            store.save_json(self.jid, "script.json", s)
        return super().generate_json(prompt, schema, temperature)

def test_approve_rejects_part_changed_during_notebook_update(client, rig):
    rig.film_done()
    jid = parts.create_parts(store.load(rig.film.id), [])[0].id
    client.post(f"/api/jobs/{jid}/run", json={"mode": "auto"})
    done(client, jid)
    api.QUEUE.engines_factory = lambda: pipeline.Engines(llm=lambda p, m: EditingLLM(jid))
    r = client.post(f"/api/jobs/{jid}/approve", json={})
    assert r.status_code == 409
    assert client.get(f"/api/jobs/{jid}").json()["state"] == "done"
    assert client.get(f"/api/review/projects/{rig.project.id}/notebook").json()["entries"] == []

def test_bad_numbers_rejected(client, rig):
    rig.film_done()
    jid = parts.create_parts(store.load(rig.film.id), [])[0].id
    base = f"/api/review/projects/{rig.project.id}"
    body = '{"film_job": "%s", "cuts": [NaN]}' % rig.film.id
    assert client.put(f"{base}/parts", content=body, headers={"content-type": "application/json"}).status_code == 422
    body = '{"film_job": "%s", "minutes": Infinity}' % rig.film.id
    assert client.post(f"{base}/split", content=body, headers={"content-type": "application/json"}).status_code == 422
    assert client.get(f"/api/jobs/{jid}/thumb", params={"t": "nan"}).status_code == 400

def test_notebook_rename_updates_film_characters(client, rig):
    rig.film_done()
    p = projects.get(rig.project.id)
    p.review.notebook = Notebook(characters=[NotebookCharacter(name="Tiểu Minh", role="nhân vật chính")], rev=1)
    projects.save(p)
    url = f"/api/review/projects/{p.id}/notebook"
    nb = client.get(url).json()
    nb["characters"][0]["name"] = "Minh Nhỏ"
    out = client.put(url, json=nb).json()
    assert out["rev"] == 2 and out["shared_rev"] == 2 and out["characters"][0]["name"] == "Minh Nhỏ"
    assert [c["name"] for c in store.load_json(rig.film.id, "characters.json")] == ["Minh Nhỏ"]
    assert client.put(url, json=nb).status_code == 409                     # stale copy (rev 1)
    assert client.put(url, json=nb).json()["detail"] == "Sổ tay đã thay đổi, tải lại rồi sửa tiếp"

def test_notebook_reorder_is_not_a_rename(client, rig):
    rig.film_done()
    store.save_json(rig.film.id, "characters.json", [{"name": n, "aliases": [], "role": ""} for n in ("An", "Bình", "Chi")])
    p = projects.get(rig.project.id)
    p.review.notebook = Notebook(characters=[NotebookCharacter(name=n) for n in ("An", "Bình", "Chi")], rev=1)
    projects.save(p)
    url = f"/api/review/projects/{p.id}/notebook"
    nb = client.get(url).json()
    nb["characters"] = [nb["characters"][i] for i in (1, 0, 2)]           # Bình, An, Chi: reorder only
    nb = client.put(url, json=nb).json()
    names = lambda: [c["name"] for c in store.load_json(rig.film.id, "characters.json")]  # noqa: E731
    assert names() == ["An", "Bình", "Chi"]
    nb["characters"] = [nb["characters"][i] for i in (1, 0, 2)]           # back to An, Bình, Chi ...
    nb["characters"][2]["name"] = "Chi Pu"                                # ... and Chi renamed
    client.put(url, json=nb)
    assert names() == ["An", "Bình", "Chi Pu"]

def test_vsmov_project_one_per_slug_and_prepare(client, fake_vsmov):
    m = client.get("/api/vsmov/movie/phim-a").json()
    assert m["meta"]["name"] == "Phim A" and m["default_server"] == "Vietsub #1"
    assert "ads" not in client.get("/api/review/templates").json()
    a = client.post("/api/review/projects", json={"slug": "phim-a", "server": ""}).json()
    b = client.post("/api/review/projects", json={"slug": "phim-a", "server": ""}).json()
    assert a["id"] == b["id"] and a["source_url"] == "vsmov:phim-a" and a["review"]["server"] == "Vietsub #1"
    task = wait_for(lambda: (t := detail(client, a["id"])["tasks"]) and t[0]["state"] in ("done", "error") and t[0])
    assert task["state"] == "done", task["error"]
    assert len(detail(client, a["id"])["tasks"]) == 1
    film = client.get(f"/api/jobs/{task['job']}").json()
    assert film["name"] == "Phim A · Full" and film["project"] == a["id"]
    assert film["film"]["subtitle"] == "vie" and [s["code"] for s in film["film"]["subtitles"]] == ["eng", "vie"]
    assert film["settings"]["lang"] == "ko" and film["settings"]["separate"] is False
    assert store.exists(film["id"], "subs/vie.vtt") and store.exists(film["id"], "subs/eng.vtt")
    assert client.post(f"/api/review/projects/{a['id']}/episodes/full/prepare").status_code == 409
    done(client, film["id"])

def test_vsmov_download_error_removes_job(client, fake_vsmov):
    fake_vsmov["fail"] = True
    a = client.post("/api/review/projects", json={"slug": "phim-b", "server": "4K"}).json()
    task = wait_for(lambda: (t := detail(client, a["id"])["tasks"]) and t[0]["state"] in ("done", "error") and t[0])
    assert task["state"] == "error" and "Tải đoạn" in task["error"]
    assert detail(client, a["id"])["films"] == [] and store.list_jobs() == []

def test_series_next_episode_prepared_after_last_part_approved(client, fake_vsmov):
    fake_vsmov.update(type="series", countries=["Trung Quốc"],
                      episodes=[Episode(name="Tập 1", slug="tap-1", embed="https://e/1"),
                                Episode(name="Tập 2", slug="tap-2", embed="https://e/2")])
    p = client.post("/api/review/projects", json={"slug": "bo-a", "server": ""}).json()
    rs = {**p["review"]["settings"], "minutes": 1}
    assert client.put(f"/api/review/projects/{p['id']}/settings", json={"settings": rs}).status_code == 200
    film1 = wait_for(lambda: detail(client, p["id"])["films"])[0]
    assert film1["settings"]["lang"] == "zh"
    done(client, film1["id"])
    part = detail(client, p["id"])["parts"][0]
    assert part["review"]["minutes"] == 1
    client.post(f"/api/jobs/{part['id']}/run", json={"mode": "auto"})
    done(client, part["id"])
    assert len(detail(client, p["id"])["tasks"]) == 1
    assert client.post(f"/api/jobs/{part['id']}/approve", json={}).json()["state"] == "approved"
    films = wait_for(lambda: len(f := detail(client, p["id"])["films"]) == 2 and f)
    assert films[1]["name"] == "Phim A · Tập 2" and films[1]["film"]["episode_index"] == 1
    done(client, films[1]["id"])

def test_vsmov_search_routes(client, monkeypatch):
    card = vsmov.Card("phim-a", "Phim A", "Film A", 2024, "p.jpg", "t.jpg", 7.5)
    monkeypatch.setattr(vsmov, "search", lambda q, page: vsmov.Page([card], page, 3))
    r = client.get("/api/vsmov/search", params={"q": "phim", "page": 2}).json()
    assert r == {"items": [{"slug": "phim-a", "name": "Phim A", "origin_name": "Film A", "year": 2024, "poster": "p.jpg",
                            "thumb": "t.jpg", "rating": 7.5}], "page": 2, "total_pages": 3}

    def down(page):
        raise vsmov.VsmovError("Không kết nối được vsmov: timeout")
    monkeypatch.setattr(vsmov, "latest", down)
    r = client.get("/api/vsmov/home")
    assert r.status_code == 502 and "vsmov" in r.json()["detail"]

def test_music_upload_rejects_other_types(client, monkeypatch):
    p = projects.create("Phim", kind="review", review=ReviewProject(source="upload", movie=MovieMeta(name="Phim")))
    url = f"/api/review/projects/{p.id}/music"
    assert client.post(url, files={"file": ("virus.exe", b"MZ", "application/octet-stream")}).status_code == 400
    r = client.post(url, files={"file": ("nhac.mp3", b"ID3fake", "audio/mpeg")})
    key = projects.music_key(p.id, ".mp3")
    assert r.status_code == 200 and r.json()["review"]["music"] == key
    assert get_store().get_bytes(key) == b"ID3fake"
    got = client.get(url)
    assert got.status_code == 200 and got.content == b"ID3fake" and got.headers["content-type"] == "audio/mpeg"
    assert client.delete(url).json()["review"]["music"] is None and get_store().get_bytes(key) is None
    assert client.get(url).status_code == 404
    monkeypatch.setattr(review_api, "MUSIC_MAX", 4)
    assert client.post(url, files={"file": ("nhac.mp3", b"ID3fake", "audio/mpeg")}).status_code == 413

def test_thumb_returns_jpeg(client, rig, tmp_path):
    jid = parts.create_parts(store.load(rig.film.id), [])[0].id
    r = client.get(f"/api/jobs/{jid}/thumb", params={"t": 1.5})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
    assert store.exists(rig.film.id, "thumbs/15.jpg")
    (tmp_path / "t.jpg").write_bytes(r.content)
    assert media.probe(tmp_path / "t.jpg").width == 160
