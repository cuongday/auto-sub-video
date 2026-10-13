import asyncio
import json
import queue
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import soundfile as sf
from . import checks, config, jobs, media, pipeline, render, store, translate
from .models import STEPS, Job, JobSettings, Segment, TranslationContext, default_region
from .timing import slots

QUEUE = jobs.JobQueue()

@asynccontextmanager
async def lifespan(_app):
    jobs.reset_interrupted()
    QUEUE.start()
    yield

app = FastAPI(title="Auto-Sub", lifespan=lifespan)
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

def _view(job: Job) -> dict:
    d = job.model_dump(mode="json")
    d["frames"] = sorted(p.name for p in (store.job_dir(job.id) / "frames").glob("f*.jpg"))
    d["files"] = {n: (store.job_dir(job.id) / n).exists()
                  for n in ("output.mp4", "subs.srt", "subs.ass", "voice.wav", "preview.mp4")}
    d["stale_from"] = None if QUEUE.is_active(job.id) else _stale_from(job)
    return d

def _stale_from(job: Job) -> str | None:
    """First step whose inputs changed since it last ran (None: everything is up to date)."""
    ctx = pipeline.Ctx(job=job, dir=store.job_dir(job.id), engines=pipeline.Engines())
    for step in STEPS:
        try:
            if not pipeline._fresh(ctx, step, pipeline.step_hash(ctx, step)):
                return step
        except Exception:  # noqa: BLE001
            return step
    return None

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
        "defaults": JobSettings().model_dump(mode="json"),
    }

@app.get("/api/tts/{engine}/voices")
def tts_voices(engine: Literal["edge", "vieneu"]):
    try:
        return _engines().tts(engine).voices()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"Không tải được danh sách giọng: {e}")

# ------------------------------------------------------------------ jobs

class PathIn(BaseModel):
    path: str

def _init_job(job: Job) -> Job:
    try:
        job.info = media.probe(job.source)
        job.settings.region = default_region(job.info.width, job.info.height)
        media.grab_frames(job.source, store.job_dir(job.id) / "frames", job.info.duration)
    except Exception as e:  # noqa: BLE001
        store.delete(job.id)
        raise HTTPException(400, str(e))
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
        job = store.create(name, "", uploaded=True)
        dest = store.job_dir(job.id) / ("source" + Path(name).suffix.lower())
        with dest.open("wb") as f:
            while chunk := await up.read(8 << 20):
                f.write(chunk)
        job.source = str(dest)
    else:
        body = PathIn.model_validate(await request.json())
        p = Path(body.path).expanduser()
        if not p.is_file():
            raise HTTPException(400, f"Không tìm thấy file: {p}")
        job = store.create(p.name, str(p.resolve()))
    job = await asyncio.to_thread(_init_job, job)
    return _view(job)

@app.get("/api/jobs")
def list_jobs():
    return [_view(j) for j in store.list_jobs()]

@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    return _view(_get(jid))

@app.delete("/api/jobs/{jid}")
def delete_job(jid: str):
    job = _get(jid)
    _idle(job)
    store.delete(jid)
    return {"ok": True}

@app.put("/api/jobs/{jid}/settings")
def put_settings(jid: str, settings: JobSettings):
    job = _get(jid)
    _idle(job)
    job.settings = settings
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
    raw = store.job_dir(jid) / ("ref_upload" + Path(up.filename or "a.wav").suffix.lower())
    raw.write_bytes(await up.read())
    out = store.job_dir(jid) / "ref.wav"
    try:
        await asyncio.to_thread(media.to_16k_mono, raw, out)
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
    if body.from_step and body.from_step not in STEPS:
        raise HTTPException(400, "Bước không hợp lệ")
    if job.segments_edited and not body.confirm:
        start = STEPS.index(body.from_step) if body.from_step else 0
        if start <= STEPS.index("translate") and _would_rerun_text(job, body.from_step):
            raise HTTPException(409, "NEEDS_CONFIRM: chạy lại sẽ ghi đè phụ đề đã sửa")
    QUEUE.submit(jid, body.mode, body.from_step, body.confirm)
    return _view(store.load(jid))

def _would_rerun_text(job: Job, from_step: str | None) -> bool:
    if from_step and STEPS.index(from_step) <= STEPS.index("translate"):
        return True
    ctx = pipeline.Ctx(job=job, dir=store.job_dir(job.id), engines=_engines())
    for step in STEPS[:STEPS.index("translate") + 1]:
        if not pipeline._fresh(ctx, step, pipeline.step_hash(ctx, step)):
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
    out = store.job_dir(jid) / "preview.mp4"
    try:
        await asyncio.to_thread(render.preview, job.source, out, job.info, job.settings, body.t,
                                store.load_segments(jid))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, str(e))
    return {"ok": True}

_FILES = re.compile(r"^(frames/f\d+\.jpg|source|output\.mp4|subs\.srt|subs\.ass|voice\.wav|preview\.mp4|ref\.wav|log\.txt)$")

@app.get("/api/jobs/{jid}/files/{name:path}")
def get_file(jid: str, name: str, download: bool = False):
    job = _get(jid)
    if not _FILES.match(name):
        raise HTTPException(404, "Không có file")
    path = Path(job.source) if name == "source" else store.job_dir(jid) / name
    if not path.is_file():
        raise HTTPException(404, "Không có file")
    headers = {"Cache-Control": "no-cache"}
    if download:
        stem = Path(job.name).stem
        return FileResponse(path, filename=f"{stem}.vi{path.suffix}" if name != "voice.wav" else f"{stem}.voice.wav",
                            headers=headers)
    return FileResponse(path, headers=headers)

# ------------------------------------------------------------------ presets

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

# ------------------------------------------------------------------ frontend

if config.FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="frontend")
