"""Routes of the review feature: vsmov search, review projects (prepare episodes, split, music, notebook) and
the script of a part. Shares the job helpers and the queue of api.py (always read as api.X: tests swap QUEUE)."""
import asyncio
import math
import re
import threading
import uuid
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from pydantic import BaseModel, Field
from . import api, config, proc, projects, store, vsmov, workdir
from .models import (ChunkSummary, FilmCharacter, FilmInfo, Job, JobSettings, Lang, MovieMeta, Notebook, ReviewSettings,
                     Script, ScriptBlock, Segment, SubTrack)
from .projects import Project, ReviewProject
from .review import notebook, pace, parts, script as script_mod, split, templates
from .storage import content_type, get_store

router = APIRouter()

MUSIC_EXT = {".mp3", ".m4a", ".aac", ".wav", ".ogg"}
MUSIC_MAX = 50 << 20
_NB_LOCK = threading.Lock()                # notebook read -> LLM -> save, one at a time (approvals and user edits)
_SUB_CODE = re.compile(r"[A-Za-z0-9_-]{1,16}")
_VS_TASKS: dict[str, dict] = {}            # episode downloads: id -> {project, episode, name, state, pct, job, error}
_VS_LOCK = threading.Lock()

def _vs(fn, *a):
    """vsmov results (dataclasses) as plain JSON data."""
    try:
        return jsonable_encoder(fn(*a))
    except vsmov.VsmovError as e:
        raise HTTPException(502, str(e))

# ------------------------------------------------------------------ vsmov

@router.get("/api/vsmov/home")
def vs_home(page: int = 1):
    return _vs(vsmov.latest, page)

@router.get("/api/vsmov/search")
def vs_search(q: str, page: int = 1):
    return _vs(vsmov.search, q, page)

@router.get("/api/vsmov/list")
def vs_list(kind: Literal["phim-le", "phim-bo", "the-loai", "quoc-gia"], slug: str = "", page: int = 1):
    return _vs(vsmov.listing, kind, slug, page)

@router.get("/api/vsmov/filters")
def vs_filters():
    return _vs(vsmov.filters)

@router.get("/api/vsmov/movie/{slug}")
def vs_movie(slug: str):
    return _vs(vsmov.movie, slug)

@router.get("/api/review/templates")
def review_templates():
    return {k: v for k, v in templates.load().items() if k not in ("ads", "edge_keywords")}

# ------------------------------------------------------------------ helpers

def _review(pid: str) -> Project:
    p = api._project(pid)
    if p.review is None:
        raise HTTPException(404, "Không phải dự án review")
    return p

def _part(jid: str) -> Job:
    job = api._get(jid)
    if job.kind != "review" or job.part is None:
        raise HTTPException(400, "Không phải job review")
    return job

def _film_of(p: Project, jid: str) -> Job:
    fj = api._get(jid)
    if fj.kind != "film" or fj.project != p.id:
        raise HTTPException(404, "Không có phim này trong dự án")
    return fj

def _films(pid: str, all_jobs: list[Job]) -> list[Job]:
    return sorted((j for j in all_jobs if j.kind == "film" and j.project == pid),
                  key=lambda j: (j.film.episode_index if j.film else 0, j.created))

def guess_lang(countries: list[str]) -> str:
    if any(c in ("Trung Quốc", "Đài Loan", "Hồng Kông") for c in countries):
        return "zh"
    return "ko" if "Hàn Quốc" in countries else "en"

def pick_subtitle(tracks: list[SubTrack]) -> str | None:
    codes = [t.code for t in tracks]
    return next((c for c in ("vie", "eng") if c in codes), codes[0] if codes else None)

def part_view(job: Job, all_jobs: list[Job] | None = None) -> dict:
    """Extra fields of a review job's view: its film's state, whether the previous part is approved, stale notebook."""
    all_jobs = store.list_jobs() if all_jobs is None else all_jobs
    film = next((j for j in all_jobs if j.id == job.part.film_job), None)
    prev = next((j for j in all_jobs if j.kind == "review" and j.project == job.project and j.part
                 and j.part.index == job.part.index - 1), None)
    p = projects.get(job.project) if job.project else None
    return {"film_state": film.state if film else None,
            "prev_approved": prev is None or prev.state == "approved",    # no part before (deleted): not blocked
            "notebook_stale": job.steps["script"].status == "done" and bool(p and p.review)
                              and notebook.is_stale(p.review.notebook, job.part)}

def check_run(job: Job) -> None:
    """A part's script is written the first time only once its film is ready and the part before is approved."""
    if store.exists(job.id, "script.json"):
        return
    v = part_view(job)
    if v["film_state"] not in ("done", "approved"):
        raise HTTPException(409, "Phim chưa chuẩn bị xong")
    if not v["prev_approved"]:
        raise HTTPException(409, f"Phần {job.part.index - 1} chưa được duyệt")

# ------------------------------------------------------------------ episode download (thread, like Douyin)

def _emit(tid: str) -> None:
    api.QUEUE.emit({"type": "vsmov", "task": tid})

def _fetch_subs(w: workdir.WorkDir, tracks: list[SubTrack], embed_url: str) -> list[SubTrack]:
    out: list[SubTrack] = []
    for t in tracks:
        if not _SUB_CODE.fullmatch(t.code) or any(o.code == t.code for o in out):
            continue                        # the code names a file: never trust it as a path
        try:
            text = vsmov.fetch_subtitle(t.url, embed_url)
        except vsmov.VsmovError:
            continue                        # one missing subtitle never stops the episode (ASR is the fallback)
        name = f"subs/{t.code}.vtt"
        w.local(name).parent.mkdir(parents=True, exist_ok=True)
        w.local(name).write_text(text, encoding="utf-8")
        w.push(name)
        out.append(t)
    return out

def _prepare(tid: str, pid: str, index: int) -> None:
    row = _VS_TASKS[tid]
    row["state"] = "running"
    _emit(tid)
    job = None
    try:
        p = _review(pid)
        movie, ep = p.review.movie, p.review.episodes[index]
        job = store.create(f"{movie.name} · {ep.name}", "source.mp4", kind="film")
        job.settings = JobSettings.model_validate(p.review.job_settings) if p.review.job_settings else JobSettings()
        job.settings.separate, job.settings.lang = False, guess_lang(movie.countries)
        job.film = FilmInfo(episode=ep, episode_index=index)
        job.project = pid                   # shows in the project (and blocks a second prepare) while downloading
        store.save(job)
        with workdir.pinned(job.id):
            w = workdir.WorkDir(job.id)

            def progress(x: float):
                if round(x * 100) != round(row["pct"] * 100):
                    row["pct"] = round(x, 3)
                    _emit(tid)
            embed = vsmov.download(ep.embed, w.local("source.mp4"), progress=progress, workers=config.VSMOV_WORKERS)
            job.film.subtitles = _fetch_subs(w, embed.subtitles, ep.embed)
            job.film.subtitle = pick_subtitle(job.film.subtitles)
            job = api._init_job(job, w.local("source.mp4"))
        api.QUEUE.submit(job.id, "auto")
        row.update(state="done", pct=1, job=job.id)
    except Exception as e:  # noqa: BLE001
        if job is not None:
            try:
                store.delete(job.id)
            except Exception:  # noqa: BLE001  (storage down: the row still reports the real error)
                pass
        row.update(state="error", error=str(getattr(e, "detail", e)))
    _emit(tid)

def start_prepare(p: Project, index: int) -> dict:
    ep = p.review.episodes[index]
    with _VS_LOCK:
        busy = any(t["project"] == p.id and t["episode"] == ep.slug and t["state"] in ("queued", "running")
                   for t in _VS_TASKS.values())
        films = [j for j in _films(p.id, store.list_jobs()) if j.film and j.film.episode and j.film.episode.slug == ep.slug]
        # a download cut short by a restart leaves a film job with no video and no task: dead, prepare again
        dead = [] if busy else [j for j in films if j.state == "new" and not store.exists(j.id, j.source)]
        if busy or len(films) > len(dead):
            raise HTTPException(409, "Tập này đã được chuẩn bị")
        for j in dead:
            store.delete(j.id)
        for k in [k for k, t in _VS_TASKS.items() if t["project"] == p.id and t["episode"] == ep.slug]:
            del _VS_TASKS[k]                # the failed attempt's row: the new one replaces it
        tid = uuid.uuid4().hex[:8]
        _VS_TASKS[tid] = {"id": tid, "project": p.id, "episode": ep.slug, "name": ep.name, "state": "queued", "pct": 0,
                          "job": None, "error": None}
    threading.Thread(target=_prepare, args=(tid, p.id, index), daemon=True).start()
    return _VS_TASKS[tid]

# ------------------------------------------------------------------ projects

class VsProjectIn(BaseModel):
    slug: str
    server: str = ""

@router.post("/api/review/projects")
def create_vsmov_project(body: VsProjectIn):
    if not body.slug.strip():
        raise HTTPException(400, "Thiếu phim")
    url = "vsmov:" + body.slug.strip()
    if same := projects.find_by_source(url):
        return api._project_view(same)      # one project per movie
    d = _vs(vsmov.movie, body.slug.strip())
    server = body.server or d["default_server"]
    eps = next((s["episodes"] for s in d["servers"] if s["name"] == server), None)
    if not eps:
        raise HTTPException(400, "Phim chưa có nguồn" if not d["servers"] else "Không có server này")
    p = projects.create(d["meta"]["name"] or body.slug, url, kind="review",
                        review=ReviewProject(source="vsmov", movie=d["meta"], server=server, episodes=eps))
    start_prepare(p, 0)                     # single movie: the film; series: episode 1 (later ones when needed)
    return api._project_view(p)

@router.post("/api/review/projects/upload")
async def create_upload_project(file: UploadFile, lang: Lang = Form("zh")):
    name = Path(file.filename or "phim.mp4").name
    ext = Path(name).suffix.lower()
    if ext not in api.VIDEO_EXT:
        raise HTTPException(400, "Định dạng video không hỗ trợ")
    job = store.create(name, "source" + ext, uploaded=True, kind="film")
    job.settings.separate, job.settings.lang, job.film = False, lang, FilmInfo()
    dest = workdir.WorkDir(job.id).local(job.source)
    with dest.open("wb") as f:
        while chunk := await file.read(8 << 20):
            f.write(chunk)
    job = await asyncio.to_thread(api._init_job, job, dest)
    stem = Path(name).stem
    p = projects.create(stem, kind="review", review=ReviewProject(source="upload", movie=MovieMeta(name=stem)))
    job.project = p.id
    store.save(job)
    api.QUEUE.submit(job.id, "auto")
    return api._project_view(p)

@router.get("/api/review/projects/{pid}")
def review_project(pid: str):
    p = _review(pid)
    all_jobs = store.list_jobs()
    ps = sorted((j for j in all_jobs if j.kind == "review" and j.project == pid), key=lambda j: j.part.index)
    return {"project": api._project_view(p, all_jobs), "films": [api._view(j, all_jobs) for j in _films(pid, all_jobs)],
            "parts": [api._view(j, all_jobs) for j in ps],
            "tasks": [t for t in _VS_TASKS.values() if t["project"] == pid]}

@router.post("/api/review/projects/{pid}/episodes/{slug}/prepare")
def prepare_episode(pid: str, slug: str):
    p = _review(pid)
    index = next((i for i, e in enumerate(p.review.episodes) if e.slug == slug), None)
    if index is None:
        raise HTTPException(404, "Không có tập này")
    return start_prepare(p, index)

@router.delete("/api/review/projects/{pid}")
def delete_review_project(pid: str):
    """The whole project: its parts, its films (the downloaded videos) and the music. Refused while one runs."""
    p = _review(pid)
    with _VS_LOCK:
        mine = [j for j in store.list_jobs() if j.project == pid]
        if any(api.QUEUE.is_active(j.id) for j in mine) or any(
                t["project"] == pid and t["state"] in ("queued", "running") for t in _VS_TASKS.values()):
            raise HTTPException(409, "Dự án đang có việc chạy hoặc chờ, hãy chờ xong hoặc huỷ trước khi xoá")
        projects.delete(pid)
        for k in [k for k, t in _VS_TASKS.items() if t["project"] == pid]:
            del _VS_TASKS[k]
    for j in mine:
        store.delete(j.id)
    if p.review.music:
        get_store().delete(p.review.music)
    return {"ok": True}

class ProjectSettingsIn(BaseModel):
    settings: ReviewSettings
    job_settings: JobSettings | None = None          # None: keep
    parts_per_episode: Literal[1, 2] | None = None    # None: keep

# what only the voice-over, assembly and render read: reaches every idle part (spec 7.4: set once per project)
RENDER_FIELDS = {"aspect", "subtitles", "music_db", "music_duck", "cover_regions", "cover"}
RENDER_JOB_FIELDS = {"tts_engine", "tts_voice", "tts_rate", "style"}

@router.put("/api/review/projects/{pid}/settings")
def put_project_settings(pid: str, body: ProjectSettingsIn):
    """Shared settings: all of them go to parts whose script is not written yet; the voice, subtitle style and
    render fields also go to parts already scripted (not running), which then only redo voice/assembly/render."""
    p = _review(pid)
    p.review.settings = body.settings
    if body.job_settings is not None:
        p.review.job_settings = body.job_settings.model_copy(update={"ref_audio": None}).model_dump(mode="json")
    if body.parts_per_episode is not None:
        p.review.parts_per_episode = body.parts_per_episode
    projects.save(p)
    for j in parts.parts_of(pid):
        if api.QUEUE.is_active(j.id):
            continue
        before = (j.review.model_copy(deep=True), j.settings.model_copy(deep=True))
        if j.steps["script"].status != "done":
            j.review = body.settings.model_copy(deep=True)
            if body.job_settings is not None:     # a part keeps its own uploaded voice sample
                j.settings = body.job_settings.model_copy(update={"ref_audio": j.settings.ref_audio}, deep=True)
        else:
            j.review = ReviewSettings.model_validate({**j.review.model_dump(),
                                                     **body.settings.model_dump(include=RENDER_FIELDS)})
            if body.job_settings is not None:
                j.settings = JobSettings.model_validate({**j.settings.model_dump(),
                                                         **body.job_settings.model_dump(include=RENDER_JOB_FIELDS)})
        if (j.review, j.settings) != before:
            api._unapprove(j)
            store.save(j)
    return api._project_view(p)

class SplitIn(BaseModel):
    film_job: str
    parts: int | None = Field(None, ge=1, le=100)
    minutes: float | None = None

@router.post("/api/review/projects/{pid}/split")
def propose_split(pid: str, body: SplitIn):
    if body.minutes is not None and not 0 < body.minutes <= 600:    # also NaN/inf (a pydantic 422 would echo them)
        raise HTTPException(422, "Số phút mỗi phần không hợp lệ")
    fj = _film_of(_review(pid), body.film_job)
    if fj.state not in ("done", "approved"):
        raise HTTPException(409, "Phim chưa chuẩn bị xong")
    lines = [Segment.model_validate(s) for s in store.load_json(fj.id, "transcript.json", default=[])]
    chunks = [ChunkSummary.model_validate(c) for c in store.load_json(fj.id, "summary.json", default={}).get("chunks", [])]
    return {"cuts": split.propose_cuts(lines, fj.info.duration, parts=body.parts, minutes=body.minutes, chunks=chunks)}

class PartsIn(BaseModel):
    film_job: str
    cuts: list[float]

@router.put("/api/review/projects/{pid}/parts")
def put_parts(pid: str, body: PartsIn):
    p = _review(pid)
    fj = _film_of(p, body.film_job)
    if fj.info is None:
        raise HTTPException(409, "Phim chưa chuẩn bị xong")
    if not all(map(math.isfinite, body.cuts)):   # checked here: pydantic's 422 would echo NaN and fail to encode
        raise HTTPException(422, "Điểm cắt không hợp lệ")
    if any(api.QUEUE.is_active(j.id) for j in parts.parts_of(pid) if j.part.film_job == fj.id):
        raise HTTPException(409, "Có phần đang chạy, hãy chờ hoặc huỷ trước khi chia lại")
    try:
        parts.create_parts(fj, body.cuts)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return api._project_view(p)

@router.post("/api/review/projects/{pid}/music")
async def upload_music(pid: str, file: UploadFile):
    p = _review(pid)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in MUSIC_EXT:
        raise HTTPException(400, "Định dạng nhạc không hỗ trợ (mp3, m4a, aac, wav, ogg)")
    data = await file.read(MUSIC_MAX + 1)
    if len(data) > MUSIC_MAX:
        raise HTTPException(413, f"File nhạc quá lớn (tối đa {MUSIC_MAX >> 20} MB)")
    key = projects.music_key(pid, ext)
    await asyncio.to_thread(get_store().put_bytes, key, data)
    if p.review.music and p.review.music != key:
        get_store().delete(p.review.music)
    p.review.music = key
    projects.save(p)
    return api._project_view(p)

@router.get("/api/review/projects/{pid}/music")
def get_music(pid: str):
    """The background music, for the player on the project page (small file: no Range needed)."""
    key = _review(pid).review.music
    data = get_store().get_bytes(key) if key else None
    if data is None:
        raise HTTPException(404, "Chưa có nhạc nền")
    return Response(data, media_type=content_type(key), headers={"Cache-Control": "no-cache"})

@router.delete("/api/review/projects/{pid}/music")
def delete_music(pid: str):
    p = _review(pid)
    if p.review.music:
        get_store().delete(p.review.music)
    p.review.music = None
    projects.save(p)
    return api._project_view(p)

@router.get("/api/review/projects/{pid}/notebook")
def get_notebook(pid: str):
    return _review(pid).review.notebook.model_dump(mode="json")

@router.put("/api/review/projects/{pid}/notebook")
def put_notebook(pid: str, body: Notebook):
    """The user's edit of the notebook; renamed characters are renamed in the films' character lists too, and keep
    their old name as an alias (the chunk summaries still use it)."""
    # ponytail: a rename is a name changed at the same position (lists of equal length) where neither name is in
    # the other list, so reorders never rename. Add character ids if users delete+add and rename in one save
    with _NB_LOCK:
        p = _review(pid)
        old = p.review.notebook
        if body.rev != old.rev:
            raise HTTPException(409, "Sổ tay đã thay đổi, tải lại rồi sửa tiếp")
        before, after = {c.name for c in old.characters}, {c.name for c in body.characters}
        renames = {o.name: n.name for o, n in zip(old.characters, body.characters)
                   if len(old.characters) == len(body.characters) and o.name not in after and n.name not in before}
        back = {v: k for k, v in renames.items()}
        for c in body.characters:
            if c.name in back and back[c.name] not in c.aliases:
                c.aliases.append(back[c.name])
        p.review.notebook = notebook.apply_user_edit(old, body)
        projects.save(p)
    if renames:
        for fj in _films(pid, store.list_jobs()):
            chars = store.load_json(fj.id, "characters.json")
            if chars and any(c.get("name") in renames for c in chars):
                store.save_json(fj.id, "characters.json", [_renamed(c, renames) for c in chars])
    return p.review.notebook.model_dump(mode="json")

def _renamed(c: dict, renames: dict[str, str]) -> dict:
    name = c.get("name")
    if name not in renames:
        return c
    aliases = c.get("aliases") or []
    return {**c, "name": renames[name], "aliases": aliases if name in aliases else [*aliases, name]}

# ------------------------------------------------------------------ script of a part

def _load_script(jid: str) -> Script:
    return Script.model_validate(store.load_json(jid, "script.json", default={}))

def _script_view(job: Job) -> dict:
    s, st = _load_script(job.id), job.settings
    ref = workdir.WorkDir(job.id).fetch(st.ref_audio) if st.ref_audio else None
    spm = pace.measure_spm(api._engines().tts(st.tts_engine), st.tts_voice, st.tts_rate, ref)
    return {"blocks": [b.model_dump(mode="json") for b in s.blocks], "estimate": round(script_mod.estimate_seconds(s, spm), 1),
            "target": job.review.minutes * 60}

@router.get("/api/jobs/{jid}/script")
def get_script(jid: str):
    return _script_view(_part(jid))

def _edited(job: Job) -> None:
    job.segments_edited = True               # a re-run of `script` needs confirming; edited blocks are kept
    job.warnings = [w for w in job.warnings if not w.startswith(script_mod.SHORT_WARNING)]   # the user set the length
    api._unapprove(job)
    store.save(job)

@router.put("/api/jobs/{jid}/script")
def put_script(jid: str, blocks: list[ScriptBlock]):
    job = _part(jid)
    api._idle(job)
    if len({b.id for b in blocks}) != len(blocks):
        raise HTTPException(422, "Trùng id khối")
    times = [x for b in blocks for x in (b.source_start, b.source_end, *(v for c in b.scenes for v in (c.start, c.end)))
             if x is not None]
    if not all(map(math.isfinite, times)) or any(c.end <= c.start for b in blocks for c in b.scenes):
        raise HTTPException(422, "Cảnh có thời gian không hợp lệ")
    old = {b.id: b for b in _load_script(jid).blocks}
    changed = lambda b: b.id not in old or (old[b.id].text, old[b.id].scenes) != (b.text, b.scenes)  # noqa: E731
    out = [b.model_copy(update={"edited": b.edited or changed(b)}) for b in blocks]
    store.save_json(jid, "script.json", Script(blocks=out).model_dump(mode="json"))
    _edited(job)
    return _script_view(job)

@router.post("/api/jobs/{jid}/script/rewrite")
def rewrite_script(jid: str):
    job = _part(jid)
    api._idle(job)
    check_run(job)
    api.QUEUE.submit(jid, "review", "script", True)
    return api._view(store.load(jid))

class BlockRewriteIn(BaseModel):
    instruction: str = ""

@router.post("/api/jobs/{jid}/script/blocks/{bid}/rewrite")
async def rewrite_block(jid: str, bid: int, body: BlockRewriteIn):
    job = _part(jid)
    api._idle(job)
    s, st = _load_script(jid), job.settings
    if not any(x.id == bid for x in s.blocks):
        raise HTTPException(404, f"Không tìm thấy khối {bid}")
    llm = api._engines().llm(st.llm_provider, st.llm_model)
    try:
        movie = parts.project_of(job).review.movie
    except KeyError:
        movie = MovieMeta(name=job.name)
    try:
        b = await asyncio.to_thread(script_mod.rewrite_block, llm, s, bid, body.instruction, meta=movie,
                                    settings=job.review, part=job.part)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, str(e))
    job = api._get(jid)                      # the job or its script may have changed during the LLM call
    api._idle(job)
    s = _load_script(jid)
    if not any(x.id == bid for x in s.blocks):
        raise HTTPException(409, "Kịch bản vừa thay đổi, hãy thử lại")
    s.blocks = [b if x.id == bid else x for x in s.blocks]
    store.save_json(jid, "script.json", s.model_dump(mode="json"))
    _edited(job)
    return b.model_dump(mode="json")

@router.put("/api/jobs/{jid}/review-settings")
def put_review_settings(jid: str, body: ReviewSettings):
    job = _part(jid)
    api._idle(job)
    job.review = body
    api._unapprove(job)
    store.save(job)
    return api._view(job)

@router.get("/api/jobs/{jid}/thumb")
def thumb(jid: str, t: float = 0.0):
    """A 160 px wide frame of the film at t seconds (for the scene strip), cached in the film job."""
    if not math.isfinite(t):
        raise HTTPException(400, "Thời điểm không hợp lệ")
    job = api._get(jid)
    fj = api._get(job.part.film_job) if job.kind == "review" and job.part else job
    if fj.info:
        t = min(t, max(0.0, fj.info.duration - 0.1))
    t = max(0.0, t)
    name, st = f"thumbs/{round(t * 10)}.jpg", get_store()
    data = st.get_bytes(store.key(fj.id, name))
    if data is None:
        with workdir.pinned(fj.id):
            w = workdir.WorkDir(fj.id)
            src = w.fetch(fj.source)
            if src is None:
                raise HTTPException(404, "Không tìm thấy video gốc của phim")
            out = w.local(name)
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                proc.run_ffmpeg(["-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", "-vf", "scale=160:-2",
                                       "-q:v", "4", str(out)])
            except RuntimeError as e:
                raise HTTPException(500, str(e))
            w.push(name)
            data = out.read_bytes()
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})

def forget_part(job: Job) -> None:
    """After a part is deleted: later parts move up (no gap left to block them), its notebook entry goes."""
    parts._reindex(job.project)
    with _NB_LOCK:
        p = projects.get(job.project)
        if p and p.review and any(e.job == job.id for e in p.review.notebook.entries):
            p.review.notebook.entries = [e for e in p.review.notebook.entries if e.job != job.id]
            projects.save(p)

# ------------------------------------------------------------------ approval (called by api.approve_job)

def approve_part(job: Job) -> Job:
    """Fold the finished part into the project notebook (LLM), then mark it approved; returns the saved job.
    The part is re-read after the LLM call: edited, re-run or queued meanwhile -> 409 and the notebook is kept."""
    with _NB_LOCK:
        try:
            p = parts.project_of(job)
        except KeyError:                    # project gone: nothing to record
            p = None
        if p is not None:
            fj = store.load(job.part.film_job)
            chars = [FilmCharacter.model_validate(c) for c in store.load_json(fj.id, "characters.json", default=[])]
            script, st = _load_script(job.id), job.settings
            try:
                nb = notebook.record_part(api._engines().llm(st.llm_provider, st.llm_model), p.review.notebook,
                                          job_id=job.id, index=job.part.index,
                                          range_label=notebook.range_label(job.part, fj.film), script=script,
                                          film_characters=chars)
            except Exception as e:  # noqa: BLE001
                raise HTTPException(502, f"Không cập nhật được sổ tay dự án: {e}")
        job = api._get(job.id)
        api._idle(job)
        if job.state != "done" or (p is not None and _load_script(job.id) != script):
            raise HTTPException(409, "Phần này vừa được sửa hoặc chạy lại, hãy duyệt lại")
        if p is not None:
            p = parts.project_of(job)       # keep other project changes made during the call
            p.review.notebook = nb
            projects.save(p)
        job.state = "approved"
        store.save(job)
    if p is not None:
        _next_episode(job, p, fj)
    return job

def _next_episode(job: Job, p: Project, fj: Job) -> None:
    """Series: approving the last part of an episode starts downloading the next one."""
    if not parts.is_series(p) or not fj.film:
        return
    same = [j.part.index for j in parts.parts_of(p.id) if j.part.film_job == fj.id]
    nxt = fj.film.episode_index + 1
    if job.part.index == max(same, default=job.part.index) and nxt < len(p.review.episodes):
        try:
            start_prepare(p, nxt)
        except HTTPException:
            pass                            # already prepared or downloading
