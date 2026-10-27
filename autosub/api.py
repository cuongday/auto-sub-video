import asyncio
import json
import queue
import re
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import soundfile as sf
from . import apikeys, auth, browse, checks, config, douyin, eta, glossary, jobs, media, pipeline, projects, prune, render, store, translate, voices, workdir
from .storage import StorageError, content_type, get_store
from .models import STEPS, Job, JobSettings, Segment, TranslationContext, default_region
from .fonts import FONTS
from .timing import slots

QUEUE = jobs.JobQueue()

@asynccontextmanager
async def lifespan(_app):
    workdir.clear_all()
    try:
        await asyncio.to_thread(get_store().ensure_bucket)  # type: ignore[attr-defined]
        jobs.reset_interrupted()
    except (StorageError, AttributeError) as e:
        print(f"[auto-sub] storage not ready at startup: {e}", flush=True)
    QUEUE.start()
    yield

app = FastAPI(title="Auto-Sub", lifespan=lifespan)

_OPEN = {"/api/auth", "/api/auth/login", "/api/auth/logout"}

@app.middleware("http")
async def _require_login(request: Request, call_next):
    if config.APP_PASSWORD and request.url.path.startswith("/api/") and request.url.path not in _OPEN:
        if not auth.valid(request.cookies.get(auth.COOKIE, ""), config.APP_PASSWORD):
            return JSONResponse({"detail": "Cần đăng nhập"}, status_code=401)
    return await call_next(request)

@app.get("/api/auth")
def auth_status(request: Request):
    if not config.APP_PASSWORD:
        return {"required": False, "ok": True}
    return {"required": True, "ok": auth.valid(request.cookies.get(auth.COOKIE, ""), config.APP_PASSWORD)}

class LoginIn(BaseModel):
    password: str

@app.post("/api/auth/login")
def auth_login(body: LoginIn):
    if not config.APP_PASSWORD:
        return {"ok": True}
    if not auth.check_password(body.password, config.APP_PASSWORD):
        raise HTTPException(401, "Sai mật khẩu")
    r = JSONResponse({"ok": True})
    r.set_cookie(auth.COOKIE, auth.make_token(config.APP_PASSWORD), max_age=auth.MAX_AGE, httponly=True, samesite="lax")
    return r

@app.post("/api/auth/logout")
def auth_logout():
    r = JSONResponse({"ok": True})
    r.delete_cookie(auth.COOKIE)
    return r
_JID = re.compile(r"^[a-f0-9]{10}$")
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv", ".m4v", ".ts"}

def _engines() -> pipeline.Engines:
    return QUEUE.engines_factory()

def _get(jid: str) -> Job:
    if not _JID.match(jid):
        raise HTTPException(404, "Không tìm thấy job")
    try:
        return store.load(jid)
    except KeyError:
        raise HTTPException(404, "Không tìm thấy job")

def _idle(job: Job) -> None:
    if QUEUE.is_active(job.id):
        raise HTTPException(409, "Job đang chạy hoặc đang chờ trong hàng đợi")

def _unapprove(job: Job) -> None:
    """Changing an approved video means it needs checking again."""
    if job.state == "approved":
        job.state = "done"

def _view(job: Job, all_jobs: list[Job] | None = None) -> dict:
    present = store.names(job.id)
    d = job.model_dump(mode="json")
    d["frames"] = sorted(n.split("/", 1)[1] for n in present if n.startswith("frames/f") and n.endswith(".jpg"))
    d["files"] = {n: n in present for n in ("output.mp4", "output_softsub.mp4", "subs.srt", "subs.ass", "voice.wav",
                                            "preview.mp4")}
    d["stale_from"] = None if QUEUE.is_active(job.id) else _stale_from(job, present)
    flow = pipeline.flow_for(job)
    d["flow"] = {"steps": flow.steps, "review_stop": flow.review_stop}
    if job.kind == "review" and job.part:
        d.update(review_api.part_view(job, all_jobs))
    return d

@app.get("/api/jobs/{jid}/eta")
def job_eta(jid: str, step: str | None = None, pct: float = 0.0):
    """Remaining seconds for the job, from this machine's past step timings."""
    return eta.estimate(_get(jid), current=step, pct=max(0.0, min(1.0, pct)))

@app.post("/api/jobs/{jid}/softsub")
async def make_softsub(jid: str):
    """Build output_softsub.mp4: the rendered video plus the Vietnamese SRT as a toggleable track."""
    job = _get(jid)
    _idle(job)

    def run():
        with workdir.pinned(jid):
            w = workdir.WorkDir(jid)
            video, srt = w.fetch("output.mp4"), w.fetch("subs.srt")
            if video is None or srt is None:
                raise HTTPException(400, "Chưa có video thành phẩm")
            render.soft_subtitles(video, srt, w.local("output_softsub.mp4"))
            w.push("output_softsub.mp4")
    await asyncio.to_thread(run)
    return {"ok": True}

@app.get("/api/jobs/{jid}/storage")
def job_storage(jid: str):
    _get(jid)
    sizes = store.object_sizes(jid)
    return {"total": sum(sizes.values()), "reclaimable": prune.reclaimable(jid)}

@app.post("/api/jobs/{jid}/prune")
def prune_job(jid: str):
    job = _get(jid)
    _idle(job)
    freed = prune.prune(jid)
    workdir.remove(jid)
    return {"freed": freed, **job_storage(jid)}

def _stale_from(job: Job, present: set[str]) -> str | None:
    """First step whose inputs changed since it last ran (None: everything is up to date)."""
    ctx = pipeline.Ctx(job=job, work=_LazyWork(job.id), engines=pipeline.Engines())
    flow = pipeline.flow_for(job)
    for step in flow.steps:
        try:
            if not pipeline._fresh(ctx, step, flow.step_hash(ctx, step), present):
                return step
        except Exception:  # noqa: BLE001
            return step
    return None

class _LazyWork:
    """Enough of WorkDir for step hashes (they only stat objects) without creating a scratch dir."""
    def __init__(self, jid: str):
        self.jid, self.store = jid, get_store()

    def key(self, name: str) -> str:
        return workdir.job_prefix(self.jid) + name

# ------------------------------------------------------------------ meta

@app.get("/api/health")
def health(llm: str | None = None, model: str = ""):
    out = {"checks": checks.run_checks(), "engines": checks.engines()}
    if llm:
        out["llm_test"] = checks.test_llm(llm, model)
    return out

@app.get("/api/options")
def options():
    pack = lambda ms: [{"id": m, "label": label} for m, label in ms]  # noqa: E731
    return {
        "asr": {k: pack(v) for k, v in config.ASR_MODELS.items()},
        "llm": {"gemini": {"default": config.GEMINI_MODEL, "models": pack(config.GEMINI_MODELS)},
                "openai": {"default": config.OPENAI_MODEL, "models": pack(config.OPENAI_MODELS)}},
        "tts": {"edge": pack(config.EDGE_VOICES)},
        "engines": checks.engines(),
        "steps": STEPS,
        "fonts": [{"id": f.id, "label": f.label, "family": f.family, "weight": f.css_weight, "file": f.file}
                  for f in FONTS],
        "defaults": JobSettings().model_dump(mode="json"),
    }

VOICE_SAMPLE = "Xin chào các bạn, hôm nay mình sẽ giới thiệu một chiếc điện thoại gập rất thú vị."

class VoiceSampleIn(BaseModel):
    engine: Literal["edge", "vieneu"]
    voice: str = ""
    rate: float = 1.0
    text: str | None = None

@app.post("/api/tts/sample")
async def voice_sample(body: VoiceSampleIn):
    """Speak a sample sentence with the given voice/rate (cached), to compare voices before running."""
    from .tts import cached_synthesize
    engine = _engines().tts(body.engine)
    text = (body.text or VOICE_SAMPLE).strip()[:300]
    try:
        path = await asyncio.to_thread(cached_synthesize, engine, text, body.voice, round(body.rate, 3), None)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"TTS lỗi: {e}")
    media_type = "audio/mpeg" if path.suffix == ".mp3" else "audio/wav"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})

# ------------------------------------------------------------------ cloned voices (VieNeu)

@app.get("/api/voices/custom")
def list_custom_voices():
    return [dict(v.__dict__, id=v.id) for v in voices.list_voices()]

@app.post("/api/voices/custom")
async def create_custom_voice(request: Request):
    """multipart: name, file (audio/video upload) | path (host file), gender, note, start, length, overwrite."""
    form = await request.form()
    name = str(form.get("name") or "").strip()
    up, host_path = form.get("file"), str(form.get("path") or "").strip()
    tmp_dir = config.WORK_DIR / "_voices"; tmp_dir.mkdir(parents=True, exist_ok=True)
    src = None
    try:
        if hasattr(up, "filename") and up is not None:
            src = tmp_dir / f"upload-{abs(hash(name))}{Path(up.filename or 'a.wav').suffix.lower()}"
            src.write_bytes(await up.read())
        elif host_path:
            try:
                src = browse.resolve(host_path)
            except browse.BrowseError as e:
                raise HTTPException(400, str(e))
        else:
            raise HTTPException(400, "Thiếu file giọng mẫu")
        try:
            v = await asyncio.to_thread(
                voices.create, name, src, gender=str(form.get("gender") or ""), note=str(form.get("note") or ""),
                start=float(form.get("start") or 0), length=float(form["length"]) if form.get("length") else None,
                overwrite=str(form.get("overwrite") or "") in ("1", "true"))
        except voices.VoiceError as e:
            raise HTTPException(400, str(e))
        except RuntimeError as e:
            raise HTTPException(400, f"Không đọc được file âm thanh: {e}")
    finally:
        if src is not None and src.parent == tmp_dir:
            src.unlink(missing_ok=True)
    return dict(v.__dict__, id=v.id)

@app.delete("/api/voices/custom/{name}")
def delete_custom_voice(name: str):
    if voices.get(name) is None:
        raise HTTPException(404, "Không có giọng này")
    voices.delete(name)
    return {"ok": True}

@app.get("/api/voices/custom/{name}/ref.wav")
def custom_voice_ref(name: str):
    st = get_store()
    k = f"voices/{name}/ref.wav"
    info = st.stat(k)
    if info is None:
        raise HTTPException(404, "Không có giọng này")
    return StreamingResponse(st.open_range(k, 0, None), media_type="audio/wav",
                             headers={"Content-Length": str(info.size), "Cache-Control": "no-cache"})

@app.get("/api/tts/{engine}/voices")
def tts_voices(engine: Literal["edge", "vieneu"]):
    try:
        return _engines().tts(engine).voices()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"Không tải được danh sách giọng: {e}")

# ------------------------------------------------------------------ jobs

class PathIn(BaseModel):
    path: str                 # relative to the mounted host folder (from the file browser)
    project: str | None = None

def _init_job(job: Job, local_video: Path) -> Job:
    """Probe the video, store it as jobs/<id>/<source> and grab the setup frames."""
    w = workdir.WorkDir(job.id)
    try:
        job.info = media.probe(local_video)
        job.settings.region = default_region(job.info.width, job.info.height)
        dest = w.local(job.source)
        if local_video.resolve() != dest.resolve():
            shutil.copyfile(local_video, dest)
        w.push(job.source)
        media.grab_frames(dest, w.local("frames"), job.info.duration)
        w.push("frames")
    except Exception as e:  # noqa: BLE001
        store.delete(job.id)
        raise HTTPException(503 if isinstance(e, StorageError) else 400, str(e))
    job.steps["probe"].status = "done"
    store.save(job)
    return job

@app.post("/api/jobs")
async def create_job(request: Request):
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/"):
        form = await request.form()
        up = form.get("file")
        if not isinstance(up, UploadFile) and not hasattr(up, "filename"):
            raise HTTPException(400, "Thiếu file")
        name = Path(up.filename or "video.mp4").name
        if Path(name).suffix.lower() not in VIDEO_EXT:
            raise HTTPException(400, "Định dạng video không hỗ trợ")
        project = _project_or_none(str(form.get("project") or "") or None)
        job = store.create(name, "source" + Path(name).suffix.lower(), uploaded=True)
        dest = workdir.WorkDir(job.id).local(job.source)
        with dest.open("wb") as f:
            while chunk := await up.read(8 << 20):
                f.write(chunk)
    else:
        body = PathIn.model_validate(await request.json())
        try:
            p = browse.video_file(body.path)
        except browse.BrowseError as e:
            raise HTTPException(400, str(e))
        project = _project_or_none(body.project)
        job = store.create(Path(body.path).name, "source" + p.suffix.lower())
        dest = p
    job = await asyncio.to_thread(_init_job, job, dest)
    if project:
        job = _join_project(job, project)
    return _view(job)

@app.get("/api/jobs")
def list_jobs():
    all_jobs = store.list_jobs()
    return [_view(j, all_jobs) for j in all_jobs]

@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    return _view(_get(jid))

@app.delete("/api/jobs/{jid}")
def delete_job(jid: str):
    job = _get(jid)
    _idle(job)
    store.delete(jid)
    if job.kind == "review" and job.project:
        review_api.forget_part(job)
    return {"ok": True}

@app.put("/api/jobs/{jid}/settings")
def put_settings(jid: str, settings: JobSettings):
    job = _get(jid)
    _idle(job)
    job.settings = settings
    _unapprove(job)
    store.save(job)
    return _view(job)

@app.post("/api/jobs/{jid}/ref-audio")
async def upload_ref(jid: str, request: Request):
    job = _get(jid)
    _idle(job)
    form = await request.form()
    up = form.get("file")
    if up is None:
        raise HTTPException(400, "Thiếu file")
    w = workdir.WorkDir(jid)
    raw = w.local("ref_upload" + Path(up.filename or "a.wav").suffix.lower())
    raw.write_bytes(await up.read())
    out = w.local("ref.wav")
    try:
        await asyncio.to_thread(media.to_16k_mono, raw, out)
        await asyncio.to_thread(w.push, "ref.wav")
    except StorageError as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"File giọng mẫu không hợp lệ: {e}")
    finally:
        raw.unlink(missing_ok=True)
    job.settings.ref_audio = "ref.wav"
    store.save(job)
    return _view(job)

class RunIn(BaseModel):
    mode: Literal["review", "auto"] = "review"
    from_step: str | None = None
    confirm: bool = False

@app.post("/api/jobs/{jid}/run")
def run_job(jid: str, body: RunIn):
    job = _get(jid)
    _idle(job)
    flow = pipeline.flow_for(job)
    if body.from_step and body.from_step not in flow.steps:
        raise HTTPException(400, "Bước không hợp lệ")
    if job.segments_edited and not body.confirm and _would_rerun_text(job, body.from_step):
        raise HTTPException(409, "NEEDS_CONFIRM: chạy lại sẽ ghi đè phụ đề đã sửa")
    if job.kind == "review" and job.part:
        review_api.check_run(job)
    QUEUE.submit(jid, body.mode, body.from_step, body.confirm)
    return _view(store.load(jid))

def _would_rerun_text(job: Job, from_step: str | None) -> bool:
    """Would this run redo a step that overwrites the user's edited text?"""
    flow = pipeline.flow_for(job)
    if not flow.overwrites or flow.review_stop is None:
        return False
    last = flow.steps.index(flow.review_stop)            # text is edited at review; later steps only read it
    if from_step:
        return flow.steps.index(from_step) <= last
    ctx = pipeline.Ctx(job=job, work=_LazyWork(job.id), engines=_engines())
    present = store.names(job.id)
    for step in flow.steps[:last + 1]:
        if not pipeline._fresh(ctx, step, flow.step_hash(ctx, step), present):
            return True
    return False

@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    _get(jid)
    return {"ok": QUEUE.cancel(jid)}

# ------------------------------------------------------------------ review data

@app.get("/api/jobs/{jid}/context")
def get_context(jid: str):
    _get(jid)
    ctx = store.load_context(jid)
    return (ctx or TranslationContext()).model_dump(mode="json")

@app.put("/api/jobs/{jid}/context")
def put_context(jid: str, ctx: TranslationContext):
    _idle(_get(jid))
    store.save_context(jid, ctx)
    return ctx.model_dump(mode="json")

@app.get("/api/jobs/{jid}/segments")
def get_segments(jid: str):
    job = _get(jid)
    segs = store.load_segments(jid)
    sl = slots(segs, job.info.duration) if job.info and segs else []
    return {"segments": [s.model_dump(mode="json") for s in segs], "slots": sl}

def _validate(segs: list[Segment], duration: float) -> None:
    ids = set()
    prev_start = -1.0
    for s in segs:
        if s.id in ids:
            raise HTTPException(422, f"Trùng id {s.id}")
        ids.add(s.id)
        if s.start < 0 or s.end <= s.start:
            raise HTTPException(422, f"Câu {s.id}: thời gian không hợp lệ")
        if s.start < prev_start:
            raise HTTPException(422, f"Câu {s.id}: sai thứ tự thời gian")
        if duration and s.start >= duration:
            raise HTTPException(422, f"Câu {s.id}: bắt đầu sau khi video kết thúc")
        prev_start = s.start

@app.put("/api/jobs/{jid}/segments")
def put_segments(jid: str, segs: list[Segment]):
    job = _get(jid)
    _idle(job)
    _validate(segs, job.info.duration if job.info else 0)
    store.save_segments(jid, segs)
    job.segments_edited = True
    _unapprove(job)
    store.save(job)
    return get_segments(jid)

class RetranslateIn(BaseModel):
    ids: list[int] | None = None

@app.post("/api/jobs/{jid}/retranslate")
async def retranslate(jid: str, body: RetranslateIn):
    job = _get(jid)
    _idle(job)
    segs = store.load_segments(jid)
    if not segs:
        raise HTTPException(400, "Chưa có phụ đề")
    st = job.settings
    llm = _engines().llm(st.llm_provider, st.llm_model)
    ctx = store.load_context(jid) or TranslationContext()
    sl = slots(segs, job.info.duration)
    ids = set(body.ids) if body.ids else {s.id for s in segs}
    try:
        out = await asyncio.to_thread(translate.translate_ids, llm, segs, sl, ctx, st.lang, st.translator_notes, ids)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, str(e))
    store.save_segments(jid, out)
    job.segments_edited = True
    store.save(job)
    return get_segments(jid)

@app.post("/api/jobs/{jid}/segments/{sid}/preview-tts")
async def preview_tts(jid: str, sid: int):
    _get(jid)
    if not any(s.id == sid for s in store.load_segments(jid)):
        raise HTTPException(404, "Không có câu này")
    try:
        path = await asyncio.to_thread(pipeline.preview_tts, jid, sid, _engines())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"TTS lỗi: {e}")
    return FileResponse(path, media_type="audio/wav", headers={"X-Duration": f"{sf.info(path).duration:.3f}",
                                                                "Cache-Control": "no-store"})

class PreviewIn(BaseModel):
    t: float = 0.0

@app.post("/api/jobs/{jid}/preview-render")
async def preview_render(jid: str, body: PreviewIn):
    job = _get(jid)

    def run():
        with workdir.pinned(jid):
            w = workdir.WorkDir(jid)
            src = w.fetch(job.source)
            if src is None:
                raise RuntimeError("Không tìm thấy video gốc trong kho lưu trữ")
            render.preview(src, w.local("preview.mp4"), job.info, job.settings, body.t, store.load_segments(jid))
            w.push("preview.mp4")

    try:
        await asyncio.to_thread(run)
    except StorageError as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, str(e))
    return {"ok": True}

_FILES = re.compile(r"^(frames/f\d+\.jpg|source|output\.mp4|output_softsub\.mp4|subs\.srt|subs\.ass|voice\.wav|preview\.mp4|preview\.jpg|ref\.wav|log\.txt)$")

_RANGE = re.compile(r"bytes=(\d*)-(\d*)$")

@app.get("/api/jobs/{jid}/files/{name:path}")
def get_file(jid: str, name: str, request: Request, download: bool = False):
    """Stream an object from storage; supports Range so the browser can seek in videos."""
    job = _get(jid)
    if not _FILES.match(name):
        raise HTTPException(404, "Không có file")
    obj = job.source if name == "source" else name
    st = get_store()
    k = workdir.job_prefix(jid) + obj
    try:
        info = st.stat(k)
    except StorageError as e:
        raise HTTPException(503, str(e))
    if info is None:
        raise HTTPException(404, "Không có file")
    size = info.size
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-cache", "ETag": f'"{info.etag}"'}
    if download:
        stem = Path(job.name).stem
        fname = f"{stem}.voice.wav" if name == "voice.wav" else f"{stem}.vi{Path(obj).suffix}"
        from urllib.parse import quote
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(fname)}"
    ctype = content_type(obj)
    rng = request.headers.get("range")
    m = _RANGE.match(rng.strip()) if rng else None
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            start = int(m.group(1))
            end = min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
        else:                                  # suffix range: last N bytes
            start, end = max(0, size - int(m.group(2))), size - 1
        if start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)})
        return StreamingResponse(st.open_range(k, start, end - start + 1), status_code=206, media_type=ctype,
                                 headers=headers)
    if size == 0:
        return Response(b"", media_type=ctype, headers=headers)
    headers["Content-Length"] = str(size)
    return StreamingResponse(st.open_range(k, 0, None), media_type=ctype, headers=headers)

# ------------------------------------------------------------------ shared glossary

@app.get("/api/glossary")
def get_glossary():
    return glossary.load()

@app.put("/api/glossary")
def put_glossary(body: dict):
    return glossary.save(body)

@app.post("/api/jobs/{jid}/glossary/promote")
def promote_glossary(jid: str):
    """Add this job's characters and terms to the shared glossary."""
    _get(jid)
    ctx = store.load_context(jid)
    if ctx is None:
        raise HTTPException(400, "Job chưa có bối cảnh dịch")
    return glossary.add_from(ctx)

# ------------------------------------------------------------------ batch

class BatchIn(BaseModel):
    paths: list[str] = []                 # host files (relative to HOST_ROOT) to turn into new jobs
    job_ids: list[str] = []               # existing jobs to (re)run
    preset: str | None = None
    project: str | None = None            # put new jobs in this project (its preset applies when no preset is given)
    run: bool = True                      # queue each job in auto mode (straight to the final video)

def _apply_preset(job: Job, preset: dict) -> Job:
    """Preset settings on top of the job's own; the per-video cover region is kept unless the preset sets one."""
    merged = {**job.settings.model_dump(mode="json"), **{k: v for k, v in preset.items() if k != "region"}}
    if preset.get("region") and preset["region"] != JobSettings().region.model_dump(mode="json"):
        merged["region"] = preset["region"]
    job.settings = JobSettings.model_validate(merged)
    store.save(job)
    return job

@app.post("/api/batch")
async def batch(body: BatchIn):
    preset = store.load_presets().get(body.preset) if body.preset else None
    if body.preset and preset is None:
        raise HTTPException(400, f"Không có preset {body.preset!r}")
    project = _project_or_none(body.project)
    results = []
    for rel in body.paths:
        try:
            p = browse.video_file(rel)
            job = store.create(Path(rel).name, "source" + p.suffix.lower())
            job = await asyncio.to_thread(_init_job, job, p)
            if project:
                job = _join_project(job, project, apply_preset=preset is None)
            results.append({"path": rel, "ok": True, "job": job.id})
        except (browse.BrowseError, HTTPException) as e:
            results.append({"path": rel, "ok": False, "error": str(getattr(e, "detail", e))})
    results += [{"job": jid, "ok": True} for jid in body.job_ids]
    for r in results:
        if not r["ok"]:
            continue
        try:
            job = _get(r["job"])
            if preset:
                job = _apply_preset(job, preset)
            if body.run and not QUEUE.is_active(job.id):
                QUEUE.submit(job.id, "auto", None, True)
        except HTTPException as e:
            r.update(ok=False, error=str(e.detail))
    return {"results": results}

# ------------------------------------------------------------------ Douyin

_DY_LOGIN: list[douyin.Login] = []
_DY_TASKS: dict[str, dict] = {}            # download batches: id -> {items: [{id,title,state,pct,job,error}]}

class DyLinkIn(BaseModel):
    url: str

@app.post("/api/douyin/lookup")
async def douyin_lookup(body: DyLinkIn):
    """A video link -> that video; a channel link -> its videos (first page only unless logged in)."""
    try:
        kind, val = await asyncio.to_thread(douyin.resolve, body.url)
        if kind == "video":
            it = await asyncio.to_thread(douyin.video_info, val)
            return {"kind": "video", "items": [it.public()], "complete": True, "logged_in": douyin.logged_in()}
        ch = await asyncio.to_thread(douyin.channel, val)
        return {"kind": "channel", "name": ch["name"], "items": [i.public() for i in ch["items"]],
                "complete": ch["complete"], "logged_in": ch["logged_in"], "sec_uid": val}
    except douyin.DouyinError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001  (browser / network)
        raise HTTPException(502, f"Không đọc được Douyin: {e}")

class DyDownloadIn(BaseModel):
    ids: list[str]
    titles: dict[str, str] = {}
    preset: str | None = None             # apply this preset to every created job
    project: str | None = None            # put the new jobs in this project (its preset applies when no preset is given)

def _dy_items(ids: list[str]) -> dict[str, "douyin.VideoItem | douyin.DouyinError"]:
    """Video details, from the lookup cache when fresh; the rest in one browser session."""
    out = {i: it for i in ids if (it := douyin.cached(i))}
    missing = [i for i in ids if i not in out]
    if missing:
        out.update(douyin.videos_info(missing))
    return out

def _dy_one(task_id: str, row: dict, it, preset: dict | None, project: "projects.Project | None" = None):
    row["state"] = "running"
    QUEUE.emit({"type": "douyin", "task": task_id})
    try:
        if isinstance(it, Exception):
            raise it
        name = douyin.safe_name(it.title or row.get("title", ""), it.id)
        job = store.create(name, "source.mp4")
        w = workdir.WorkDir(job.id)
        try:
            douyin.download(it, w.local("source.mp4"), progress=lambda p, r=row: r.update(pct=round(p, 3)))
        except Exception:
            store.delete(job.id)
            raise
        job = _init_job(job, w.local("source.mp4"))
        if project:
            job = _join_project(job, project, apply_preset=preset is None)
        if preset:
            job = _apply_preset(job, preset)
        row.update(state="done", pct=1, job=job.id)
    except Exception as e:  # noqa: BLE001
        row.update(state="error", error=str(getattr(e, "detail", e)))
    QUEUE.emit({"type": "douyin", "task": task_id})

def _dy_worker(task_id: str, preset: dict | None, project: "projects.Project | None" = None):
    from concurrent.futures import ThreadPoolExecutor
    task = _DY_TASKS[task_id]
    try:
        items = _dy_items([r["id"] for r in task["items"]])
    except Exception as e:  # noqa: BLE001  (browser / network)
        items = {r["id"]: e for r in task["items"]}
    with ThreadPoolExecutor(max(1, config.DOUYIN_WORKERS)) as pool:
        for row in task["items"]:
            pool.submit(_dy_one, task_id, row, items.get(row["id"]) or douyin.DouyinError(douyin._NO_INFO), preset, project)
    task["done"] = True
    QUEUE.emit({"type": "douyin", "task": task_id})

@app.post("/api/douyin/download")
def douyin_download(body: DyDownloadIn):
    if not body.ids:
        raise HTTPException(400, "Chưa chọn video nào")
    preset = store.load_presets().get(body.preset) if body.preset else None
    project = _project_or_none(body.project)
    import threading, uuid
    tid = uuid.uuid4().hex[:8]
    _DY_TASKS[tid] = {"id": tid, "done": False, "project": project.id if project else None,
                      "items": [{"id": i, "title": body.titles.get(i, ""), "state": "queued", "pct": 0, "job": None,
                                 "error": None} for i in dict.fromkeys(body.ids)]}
    threading.Thread(target=_dy_worker, args=(tid, preset, project), daemon=True).start()
    return _DY_TASKS[tid]

class DyPrepareIn(BaseModel):
    ids: list[str]

@app.post("/api/douyin/prepare")
def douyin_prepare(body: DyPrepareIn):
    """Make sure the lookup cache has fresh play links for these videos (one browser for all the misses),
    so /api/douyin/file can start every download at once."""
    items = _dy_items(list(dict.fromkeys(body.ids)))
    return {i: (None if isinstance(it, douyin.VideoItem) else str(it)) for i, it in items.items()}

@app.get("/api/douyin/file/{aweme_id}")
def douyin_file(aweme_id: str, title: str = ""):
    """The original video, streamed from Douyin's CDN, for saving straight to the user's computer."""
    if not re.fullmatch(r"\d{15,22}", aweme_id):
        raise HTTPException(404, "Không có video")
    try:
        it = douyin.cached(aweme_id) or douyin.video_info(aweme_id)
        try:
            r, total = douyin.open_stream(it)
        except douyin.DouyinError:
            it = douyin.video_info(aweme_id)            # cached links expired: ask Douyin again
            r, total = douyin.open_stream(it)
    except douyin.DouyinError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Không đọc được Douyin: {e}")
    from urllib.parse import quote
    name = douyin.safe_name(it.title or title, it.id)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}", "X-Filename": quote(name)}
    if total:
        headers["Content-Length"] = str(total)

    def body():
        with r:
            while chunk := r.read(1 << 20):
                yield chunk
    return StreamingResponse(body(), media_type="video/mp4", headers=headers)

@app.get("/api/douyin/download/{tid}")
def douyin_download_status(tid: str):
    if tid not in _DY_TASKS:
        raise HTTPException(404, "Không có lượt tải này")
    return _DY_TASKS[tid]

@app.get("/api/douyin/session")
def douyin_session():
    login = _DY_LOGIN[0] if _DY_LOGIN else None
    return {"logged_in": douyin.logged_in(), "login": None if login is None else
            {"state": login.state, "qr": login.qr, "error": login.error}}

@app.post("/api/douyin/login")
def douyin_login():
    if _DY_LOGIN and _DY_LOGIN[0].state in ("starting", "waiting"):
        return douyin_session()
    _DY_LOGIN[:] = [douyin.Login()]
    return douyin_session()

@app.delete("/api/douyin/session")
def douyin_logout():
    if _DY_LOGIN:
        _DY_LOGIN[0].cancel()
    _DY_LOGIN.clear()
    douyin.clear_session()
    return douyin_session()

# ------------------------------------------------------------------ host folder browser

@app.get("/api/browse")
def browse_dir(path: str = ""):
    try:
        return browse.list_dir(path)
    except browse.BrowseError as e:
        raise HTTPException(400, str(e))

class AppSettingsIn(BaseModel):
    video_dir: str | None = None
    auto_prune: bool | None = None
    vieneu_device: Literal["auto", "cpu", "cuda"] | None = None

@app.get("/api/app-settings")
def get_app_settings():
    s = store.load_app_settings()
    video_dir = s.get("video_dir", "")
    try:
        if video_dir:
            browse.resolve(video_dir)
    except browse.BrowseError:
        video_dir = ""                     # folder gone or mount changed: fall back to the root
    return {"video_dir": video_dir, "browse_available": browse.available(), "auto_prune": bool(s.get("auto_prune")),
            "vieneu_device": s.get("vieneu_device") or config.VIENEU_DEVICE}

@app.put("/api/app-settings")
def put_app_settings(body: AppSettingsIn):
    values = {}
    if body.video_dir is not None:
        try:
            d = browse.resolve(body.video_dir)
        except browse.BrowseError as e:
            raise HTTPException(400, str(e))
        if not d.is_dir():
            raise HTTPException(400, "Không phải thư mục")
        values["video_dir"] = browse.rel_of(d)
    if body.auto_prune is not None:
        values["auto_prune"] = body.auto_prune
    if body.vieneu_device is not None:
        values["vieneu_device"] = body.vieneu_device
    store.save_app_settings(values)
    if body.vieneu_device is not None and "autosub.tts.vieneu_tts" in sys.modules:
        sys.modules["autosub.tts.vieneu_tts"].reset_pool()      # next line is built on the new device
    return get_app_settings()

# ------------------------------------------------------------------ API keys (encrypted, never sent back)

class ApiKeyIn(BaseModel):
    key: str

def _provider(provider: str) -> str:
    if provider not in apikeys.PROVIDERS:
        raise HTTPException(404, "Không hỗ trợ nhà cung cấp này")
    return provider

@app.get("/api/api-keys")
def get_api_keys():
    return apikeys.listing()

@app.put("/api/api-keys/{provider}")
def put_api_key(provider: str, body: ApiKeyIn):
    try:
        apikeys.save(_provider(provider), body.key)
    except apikeys.KeyStoreError as e:
        raise HTTPException(400, str(e))
    return get_api_keys()

@app.delete("/api/api-keys/{provider}")
def delete_api_key(provider: str):
    apikeys.clear(_provider(provider))
    return get_api_keys()

@app.get("/api/gpu")
def gpu_status():
    """What the VieNeu device setting resolves to on this machine (probes CUDA once)."""
    from . import gpu
    s = store.load_app_settings()
    requested = s.get("vieneu_device") if s.get("vieneu_device") in gpu.DEVICES else config.VIENEU_DEVICE
    device, note = gpu.resolve(requested)
    return {"requested": requested, "device": device, "note": note, "cuda": gpu.cuda_info()}

# ------------------------------------------------------------------ presets

@app.get("/api/fonts/{name}")
def font_file(name: str):
    """Bundled subtitle fonts, so the browser preview uses the same typeface as the render."""
    f = next((f for f in FONTS if f.file == name), None)
    if f is None:
        raise HTTPException(404, "Không có font")
    return FileResponse(config.FONTS_DIR / f.file, media_type="font/ttf",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})

@app.get("/api/presets")
def get_presets():
    return store.load_presets()

class PresetIn(BaseModel):
    name: str
    settings: JobSettings

@app.post("/api/presets")
def add_preset(body: PresetIn):
    s = body.settings.model_dump(mode="json")
    s["ref_audio"] = None
    store.save_preset(body.name.strip()[:60] or "preset", s)
    return store.load_presets()

@app.delete("/api/presets/{name}")
def del_preset(name: str):
    store.delete_preset(name)
    return store.load_presets()

# ------------------------------------------------------------------ projects

def _project_or_none(pid: str | None) -> "projects.Project | None":
    if not pid:
        return None
    p = projects.get(pid)
    if p is None:
        raise HTTPException(404, "Không có project này")
    return p

def _project(pid: str) -> "projects.Project":
    p = _project_or_none(pid)
    assert p is not None
    return p

def _join_project(job: Job, project: "projects.Project", apply_preset: bool = True) -> Job:
    job.project = project.id
    store.save(job)
    if apply_preset and project.preset and job.state == "new":
        job = _apply_preset(job, project.preset)
    return job

def _project_view(p: "projects.Project", all_jobs: list[Job] | None = None) -> dict:
    mine = [j for j in (all_jobs if all_jobs is not None else store.list_jobs()) if j.project == p.id]
    counts: dict[str, int] = {}
    for j in mine:
        counts[j.state] = counts.get(j.state, 0) + 1
    return {**p.model_dump(mode="json"), "jobs": len(mine), "counts": counts}

class ProjectIn(BaseModel):
    name: str
    source_url: str = ""

@app.get("/api/projects")
def list_projects():
    all_jobs = store.list_jobs()
    return [_project_view(p, all_jobs) for p in projects.list_projects()]

@app.post("/api/projects")
def create_project(body: ProjectIn):
    if not body.name.strip():
        raise HTTPException(400, "Cần tên project")
    if body.source_url and (same := projects.find_by_source(body.source_url)):
        return _project_view(same)          # one project per channel
    return _project_view(projects.create(body.name, body.source_url))

@app.put("/api/projects/{pid}")
def update_project(pid: str, body: ProjectIn):
    p = _project(pid)
    if not body.name.strip():
        raise HTTPException(400, "Cần tên project")
    p.name, p.source_url = body.name.strip()[:80], body.source_url.strip()
    projects.save(p)
    return _project_view(p)

@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    """Removes the project only; its videos stay, without a project."""
    _project(pid)
    for j in store.list_jobs():
        if j.project == pid:
            j.project = None
            store.save(j)
    projects.delete(pid)
    return {"ok": True}

def delete_project_assets(p: "projects.Project") -> None:
    """Everything the project keeps in the store under projects/{pid}/ (the music of a review project, ...)."""
    get_store().delete_prefix(f"projects/{p.id}/")

class ProjectsDeleteIn(BaseModel):
    ids: list[str]

@app.post("/api/projects/delete")
def delete_projects(body: ProjectsDeleteIn):
    """Several projects together with all their videos. Refused (409) while any of them is running or queued."""
    ids = list(dict.fromkeys(body.ids))
    ps = [_project(pid) for pid in ids]
    with review_api._VS_LOCK:
        mine = [j for j in store.list_jobs() if j.project in ids]
        busy = [{"id": j.id, "name": j.name} for j in mine if QUEUE.is_active(j.id)]
        by_id = {p.id: p for p in ps}
        for pid in {t["project"] for t in review_api._VS_TASKS.values()
                    if t["project"] in ids and t["state"] in ("queued", "running")}:
            busy.append({"id": pid, "name": by_id[pid].name})
        if busy:
            raise HTTPException(409, detail={
                "message": "Có việc đang chạy hoặc chờ, hãy chờ xong hoặc huỷ trước khi xoá", "busy": busy})
        for k in [k for k, t in review_api._VS_TASKS.items() if t["project"] in ids]:
            del review_api._VS_TASKS[k]
    for p in ps:                          # the project record first: a failure below leaves loose videos, not a half-emptied project
        projects.delete(p.id)
    for j in mine:
        store.delete(j.id)
        workdir.remove(j.id)
    for p in ps:
        delete_project_assets(p)
    return {"deleted_projects": len(ps), "deleted_jobs": len(mine)}

class ProjectPresetIn(BaseModel):
    job_id: str

@app.post("/api/projects/{pid}/preset")
def save_project_preset(pid: str, body: ProjectPresetIn):
    """Take the subtitle position, covered regions, style and voice of a video as the project's preset."""
    p = _project(pid)
    job = _get(body.job_id)
    s = job.settings.model_dump(mode="json")
    s["ref_audio"] = None                  # a per-job upload; cloned voices (custom:<name>) carry over
    p.preset, p.preset_from = s, job.name
    projects.save(p)
    return _project_view(p)

@app.delete("/api/projects/{pid}/preset")
def clear_project_preset(pid: str):
    p = _project(pid)
    p.preset, p.preset_from = None, None
    projects.save(p)
    return _project_view(p)

class ProjectRunIn(BaseModel):
    states: list[str] = ["new"]           # which videos to run: not run yet by default
    apply_preset: bool = True             # put the project preset on them first

@app.post("/api/projects/{pid}/run")
def run_project(pid: str, body: ProjectRunIn):
    """Queue every video of the project in one of `states` in auto mode (straight to the final video)."""
    p = _project(pid)
    queued, skipped = [], []
    for j in reversed(store.list_jobs()):  # oldest first
        if j.project != pid or j.state not in body.states or QUEUE.is_active(j.id):
            continue
        if not j.info:
            skipped.append(j.id); continue
        if body.apply_preset and p.preset:
            j = _apply_preset(j, p.preset)
        if QUEUE.submit(j.id, "auto", None, True):
            queued.append(j.id)
    return {"queued": queued, "skipped": skipped}

class JobProjectIn(BaseModel):
    project: str | None = None
    apply_preset: bool = False

@app.put("/api/jobs/{jid}/project")
def set_job_project(jid: str, body: JobProjectIn):
    job = _get(jid)
    _idle(job)
    project = _project_or_none(body.project)
    if project is None:
        job.project = None
        store.save(job)
        return _view(job)
    job.project = project.id
    store.save(job)
    if body.apply_preset and project.preset:
        job = _apply_preset(job, project.preset)
        _unapprove(job); store.save(job)
    return _view(job)

class ApproveIn(BaseModel):
    approved: bool = True

@app.post("/api/jobs/{jid}/approve")
async def approve_job(jid: str, body: ApproveIn):
    """Mark a finished video as checked by the user (or take that back). Approving a review part updates the
    project notebook first (an LLM call): when that fails the part stays unapproved."""
    job = _get(jid)
    _idle(job)
    if body.approved:
        if job.state != "done":
            raise HTTPException(409, "Chỉ duyệt được video đã xong")
        if job.kind == "review" and job.part:
            job = await asyncio.to_thread(review_api.approve_part, job)
        job.state = "approved"
    elif job.state == "approved":
        job.state = "done"
    store.save(job)
    QUEUE.emit({"type": "state", "job": jid, "state": job.state})
    return _view(job)

# ------------------------------------------------------------------ events

@app.get("/api/events")
async def events():
    q = QUEUE.subscribe()

    async def gen():
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    ev = await asyncio.to_thread(q.get, True, 15)
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": ping\n\n"
        finally:
            QUEUE.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

@app.exception_handler(pipeline.NeedsConfirm)
async def _needs_confirm(_req, exc):
    return JSONResponse({"detail": f"NEEDS_CONFIRM: {exc}"}, status_code=409)

@app.exception_handler(StorageError)
async def _storage_down(_req, exc):
    return JSONResponse({"detail": f"Không kết nối được kho lưu trữ MinIO: {exc}"}, status_code=503)

# ------------------------------------------------------------------ review phim

from . import review_api  # noqa: E402  (its routes use the helpers above)
app.include_router(review_api.router)

# ------------------------------------------------------------------ frontend

if config.FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="frontend")
