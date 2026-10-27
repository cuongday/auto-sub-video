"""Routes of audio-story projects: shared settings, the background video (uploaded in chunks, then normalized
once), the music, one script file per request, and running the parts. Shares the helpers and the queue of
api.py (always read as api.X: tests swap QUEUE)."""
import asyncio
import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from . import api, config, media, projects, store
from .audio import background, flow
from .models import Job
from .projects import Project
from .review_api import MUSIC_EXT, MUSIC_MAX
from .storage import content_type, get_store

router = APIRouter()

CHUNK_MAX = 64 << 20                  # under Cloudflare's 100 MB request limit
SCRIPT_MAX = 20 << 20
SCRIPT_EXT = {".txt", ".docx", ".srt"}
UPLOAD_TTL = 24 * 3600                # unfinished uploads older than this are removed
_UID = re.compile(r"^[0-9a-f]{32}$")
_UP_LOCK = threading.Lock()           # read-modify-write of the upload state files
_PART_LOCK = threading.Lock()         # re-numbering of the parts

# ------------------------------------------------------------------ helpers

def _audio(pid: str) -> Project:
    p = api._project(pid)
    if p.audio is None:
        raise HTTPException(404, "Không phải truyện audio")
    return p

def _update(pid: str, fn) -> dict:
    """Change the project's audio settings under the projects lock and bump rev (parts know to rebuild)."""
    def apply(p: Project):
        fn(p.audio)
        p.audio.rev += 1
    p = projects.update(pid, apply)
    if p is None:
        raise HTTPException(404, "Không có project này")
    return api._project_view(p)

def _natural(name: str) -> list:
    """Sort key: "chuong-2" before "chuong-10"."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name.lower())]

def _parts(pid: str, all_jobs: list[Job] | None = None) -> list[Job]:
    """The project's parts in story order."""
    mine = [j for j in (all_jobs if all_jobs is not None else store.list_jobs())
            if j.project == pid and j.kind == "audio" and j.audio_part]
    return sorted(mine, key=lambda j: (_natural(j.audio_part.script_name), j.created))

def _renumber(pid: str) -> None:
    with _PART_LOCK:
        for i, j in enumerate(_parts(pid)):
            if j.audio_part.index != i and not api.QUEUE.is_active(j.id):
                j.audio_part.index = i
                store.save(j)

def part_view(job: Job, all_jobs: list[Job] | None = None) -> dict:
    """Extra fields of an audio part's view: its index (computed, so a running part saving an old copy of the
    job never shows a stale one) and the duration/characters measured by the tts step."""
    out: dict = {}
    if job.audio_part and job.project:
        ids = [j.id for j in _parts(job.project, all_jobs)]
        if job.id in ids:
            out["audio_part"] = {**job.audio_part.model_dump(mode="json"), "index": ids.index(job.id)}
    meta = job.audio_meta                     # set by parse (chars), then by tts (+ duration), with meta.json
    if meta is None and job.steps.get("parse") and job.steps["parse"].status == "done":
        meta = store.load_json(job.id, "meta.json", default=None)    # a part parsed before audio_meta existed
    out["meta"] = {"duration": meta.get("duration"), "chars": meta.get("chars")} if isinstance(meta, dict) else None
    return out

def run_parts(pid: str) -> dict:
    """Queue every part not finished, or finished but stale since a settings change, in story order."""
    queued = []
    for j in _parts(pid):
        if api.QUEUE.is_active(j.id):
            continue
        if j.state in ("done", "approved") and api._stale_from(j, store.names(j.id)) is None:
            continue
        if api.QUEUE.submit(j.id, "auto", None, True):
            queued.append(j.id)
    return {"queued": queued, "skipped": []}

# ------------------------------------------------------------------ uploads dir

def _up_dir() -> Path:
    d = config.WORK_DIR / "_uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _read(uid: str) -> dict | None:
    try:
        return json.loads((config.WORK_DIR / "_uploads" / f"{uid}.json").read_text())
    except (OSError, ValueError):
        return None

def _write(uid: str, st: dict) -> None:
    """Atomic: a reader never sees a half-written state."""
    d = _up_dir()
    tmp = d / f".{uid}.{uuid.uuid4().hex[:6]}"
    tmp.write_text(json.dumps(st))
    os.replace(tmp, d / f"{uid}.json")

def _in_use(uid: str, st: dict) -> bool:
    """A finished upload whose project is still storing/normalizing it (the task reads the file)."""
    if not st.get("finished") and not st.get("finishing"):
        return False
    p = projects.get(st.get("pid", ""))
    return bool(p and p.audio and p.audio.background_state == "processing" and p.audio.background_upload == uid) \
        or bool(st.get("finishing"))

def clean_uploads(pid: str | None = None) -> None:
    """Remove uploads older than UPLOAD_TTL (but not one still being stored), or every upload of project `pid`."""
    d = config.WORK_DIR / "_uploads"
    if not d.exists():
        return
    now = time.time()
    with _UP_LOCK:
        uids = {f.name.removesuffix(".json") for f in d.iterdir() if not f.name.startswith(".")}
        gone = []
        for uid in uids:
            st = _read(uid)
            if pid is not None:
                old = st is not None and st.get("pid") == pid
            else:
                times = [f.stat().st_mtime for f in (d / uid, d / f"{uid}.json") if f.exists()]
                old = (not times or now - max(times) > UPLOAD_TTL) and not (st and _in_use(uid, st))
            if old:
                gone.append(uid)
        for uid in gone:                          # both files of each upload, chosen before deleting any
            (d / uid).unlink(missing_ok=True)
            (d / f"{uid}.json").unlink(missing_ok=True)
        for f in d.glob(".*"):                    # temp state files of an interrupted write
            if now - f.stat().st_mtime > 60:
                f.unlink(missing_ok=True)

def _state(pid: str, uid: str) -> dict:
    st = _read(uid) if _UID.match(uid) else None
    if st is None or st.get("pid") != pid:
        raise HTTPException(404, "Không tìm thấy phiên tải lên (có thể đã quá 24 giờ)")
    return st

def _covered(ranges: list[list[int]]) -> int:
    return sum(e - s for s, e in ranges)

def _merge(ranges: list[list[int]], start: int, end: int) -> list[list[int]]:
    out: list[list[int]] = []
    for s, e in sorted([*ranges, [start, end]]):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out

def _upload_of(p: Project) -> Path | None:
    """The local file of the finished upload that became the project's background (recorded by finish), if it
    is still on disk: exactly that upload, never another finished upload of the same project and format."""
    uid = p.audio.background_upload
    if not uid or not _UID.match(uid):
        return None
    f = config.WORK_DIR / "_uploads" / uid
    st = _read(uid)
    return f if st and st.get("finished") and st.get("pid") == p.id and f.exists() else None

def _restart(p: Project) -> bool:
    """Store (from the local upload) and normalize the project's background again; False if no copy is left."""
    local = _upload_of(p)
    if local is not None:
        return background.start(p.id, local)
    if p.audio.background_upload:                 # never stored, and its file is gone: the stored object is older
        return False
    if p.audio.background and get_store().stat(p.audio.background) is not None:
        return background.start(p.id)
    return False

def resume_backgrounds() -> None:
    """At startup: a background cut off by the restart is stored/normalized again (or marked failed)."""
    for p in projects.list_projects():
        if p.audio is None or p.audio.background_state != "processing":
            continue
        if not _restart(p):
            projects.update(p.id, lambda x: (setattr(x.audio, "background_state", "error"), setattr(
                x.audio, "background_error", "Không tìm thấy video nền, hãy tải lên lại")))

# ------------------------------------------------------------------ settings

class AudioSettingsIn(BaseModel):
    engine: Literal["edge", "vieneu"] | None = None
    voice: str | None = None
    rate: float | None = Field(None, ge=0.5, le=2.0)
    music_volume: float | None = Field(None, ge=0, le=1)

@router.put("/api/projects/{pid}/audio")
def put_audio_settings(pid: str, body: AudioSettingsIn):
    _audio(pid)
    fields = body.model_dump(exclude_none=True)
    if not fields:
        return api._project_view(api._project(pid))
    return _update(pid, lambda a: [setattr(a, k, v) for k, v in fields.items()])

# ------------------------------------------------------------------ background (chunked upload)

class BgStartIn(BaseModel):
    name: str
    size: int = Field(gt=0)

@router.post("/api/projects/{pid}/audio/background/start")
def bg_start(pid: str, body: BgStartIn):
    _audio(pid)
    ext = Path(body.name).suffix.lower()
    if ext not in api.VIDEO_EXT:
        raise HTTPException(400, f"Định dạng video không hỗ trợ ({', '.join(sorted(e[1:] for e in api.VIDEO_EXT))})")
    if body.size > config.AUDIO_BG_MAX_BYTES:
        raise HTTPException(413, f"Video nền quá lớn (tối đa {config.AUDIO_BG_MAX_BYTES / (1 << 30):g} GB)")
    clean_uploads()
    uid = uuid.uuid4().hex
    d = _up_dir()
    with open(d / uid, "wb") as f:
        f.truncate(body.size)                       # sparse: chunks land at their offset
    _write(uid, {"pid": pid, "name": body.name, "size": body.size, "received": []})
    return {"upload_id": uid, "chunk_size": CHUNK_MAX}

@router.put("/api/projects/{pid}/audio/background/{upload_id}")
async def bg_chunk(pid: str, upload_id: str, request: Request, offset: int = 0):
    with _UP_LOCK:
        st = _state(pid, upload_id)
    if st.get("finished") or st.get("finishing"):
        raise HTTPException(409, "Phiên tải lên này đã hoàn tất")
    limit = min(CHUNK_MAX, st["size"] - offset)
    too_big = HTTPException(413, f"Mảnh quá lớn hoặc vượt kích thước file (tối đa {CHUNK_MAX >> 20} MB mỗi mảnh)")
    if offset < 0 or limit <= 0 or int(request.headers.get("content-length") or 0) > limit:
        raise too_big
    path = config.WORK_DIR / "_uploads" / upload_id
    try:
        f = await asyncio.to_thread(open, path, "r+b")
    except FileNotFoundError:
        raise HTTPException(404, "Không tìm thấy phiên tải lên (có thể đã quá 24 giờ)") from None
    n = 0
    try:                                            # streamed straight to disk, never held in memory
        await asyncio.to_thread(f.seek, offset)
        async for piece in request.stream():
            n += len(piece)
            if n > limit:
                raise too_big
            await asyncio.to_thread(f.write, piece)
    finally:
        await asyncio.to_thread(f.close)
    with _UP_LOCK:
        st = _state(pid, upload_id)
        if n:
            st["received"] = _merge(st["received"], offset, offset + n)
            _write(upload_id, st)
    return {"received": _covered(st["received"])}

@router.post("/api/projects/{pid}/audio/background/{upload_id}/finish")
def bg_finish(pid: str, upload_id: str):
    """Check the upload is complete, probe it, make it the project's background (state "processing") and queue
    the task that stores it in MinIO and normalizes it. Quick (no 1 GB transfer in the request) and idempotent:
    called again it re-queues that task if it failed. The upload is claimed under _UP_LOCK first, so two
    concurrent calls never start two tasks (the second gets 409 while the first is still probing)."""
    _audio(pid)
    with _UP_LOCK:
        st = _state(pid, upload_id)
        if st.get("finishing"):
            raise HTTPException(409, "Video nền này đang được hoàn tất, hãy chờ")
        if not st.get("finished"):
            if st["received"] != [[0, st["size"]]]:
                raise HTTPException(400, f"Video nền chưa tải lên đủ ({_covered(st['received'])}/{st['size']} byte)")
            st["finishing"] = True
            _write(upload_id, st)
    path = config.WORK_DIR / "_uploads" / upload_id
    if st.get("finished"):
        p = api._project(pid)
        if p.audio.background == st["key"] and p.audio.background_upload in (None, upload_id) \
                and p.audio.background_state == "error" \
                and not api.QUEUE.is_active(background.task_key(pid)):
            _restart(p)
        return api._project_view(api._project(pid))

    def unclaim():
        with _UP_LOCK:
            cur = _read(upload_id)
            if cur is not None:
                cur.pop("finishing", None)
                _write(upload_id, cur)
    try:
        info = media.probe(path)
    except Exception:  # noqa: BLE001
        unclaim()
        raise HTTPException(400, "Không đọc được video nền, hãy kiểm tra lại file") from None
    key = projects.bg_key(pid, Path(st["name"]).suffix.lower())

    def apply(a):
        a.background, a.background_info, a.background_upload = key, info, upload_id
        a.background_state, a.background_error = "processing", None
    try:
        _update(pid, apply)
    except BaseException:
        unclaim()
        raise
    d = config.WORK_DIR / "_uploads"
    with _UP_LOCK:
        st = _read(upload_id) or st
        st.pop("finishing", None)
        st.update(finished=True, key=key)
        _write(upload_id, st)
        for f in list(d.glob("*.json")):          # older finished uploads of this project: superseded now
            other = _read(f.stem)                 # (a task still reading one keeps its open file)
            if f.stem != upload_id and other and other.get("pid") == pid and other.get("finished"):
                (d / f.stem).unlink(missing_ok=True)
                f.unlink(missing_ok=True)
    background.start(pid, path)
    return api._project_view(api._project(pid))

@router.post("/api/projects/{pid}/audio/background/cancel")
def bg_cancel(pid: str):
    """Stop storing/normalizing the background; its state becomes "error" ("Đã huỷ ..."), retried with finish."""
    _audio(pid)
    if not background.cancel(pid):
        raise HTTPException(409, "Không có việc chuẩn hoá video nền nào đang chạy")
    return api._project_view(api._project(pid))

@router.get("/api/projects/{pid}/audio/background")
def get_background(pid: str, request: Request):
    """The normalized background for the preview player (Range: it can be large); the original until ready."""
    a = _audio(pid).audio
    st = get_store()
    for key in ([projects.bg_loop_key(pid)] if a.background_state == "ready" else []) + [a.background]:
        info = st.stat(key) if key else None
        if info is not None:
            return api.stream_object(key, info.size, content_type(key), request,
                                     {"Cache-Control": "no-cache", "ETag": f'"{info.etag}"'})
    raise HTTPException(404, "Chưa có video nền")

# ------------------------------------------------------------------ music

@router.post("/api/projects/{pid}/audio/music")
async def upload_music(pid: str, file: UploadFile):
    p = _audio(pid)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in MUSIC_EXT:
        raise HTTPException(400, "Định dạng nhạc không hỗ trợ (mp3, m4a, aac, wav, ogg)")
    data = await file.read(MUSIC_MAX + 1)
    if len(data) > MUSIC_MAX:
        raise HTTPException(413, f"File nhạc quá lớn (tối đa {MUSIC_MAX >> 20} MB)")
    key = projects.music_key(pid, ext)
    await asyncio.to_thread(get_store().put_bytes, key, data)
    if p.audio.music and p.audio.music != key:
        get_store().delete(p.audio.music)
    return _update(pid, lambda a: setattr(a, "music", key))

@router.get("/api/projects/{pid}/audio/music")
def get_music(pid: str):
    key = _audio(pid).audio.music
    data = get_store().get_bytes(key) if key else None
    if data is None:
        raise HTTPException(404, "Chưa có nhạc nền")
    return Response(data, media_type=content_type(key), headers={"Cache-Control": "no-cache"})

@router.delete("/api/projects/{pid}/audio/music")
def delete_music(pid: str):
    p = _audio(pid)
    if p.audio.music:
        get_store().delete(p.audio.music)
    return _update(pid, lambda a: setattr(a, "music", None))

# ------------------------------------------------------------------ scripts

@router.post("/api/projects/{pid}/audio/scripts")
async def upload_script(pid: str, file: UploadFile, run: int = 0):
    """One script file -> one part (job). run=1 queues it right away."""
    _audio(pid)
    name = Path(file.filename or "").name
    if Path(name).suffix.lower() not in SCRIPT_EXT:
        raise HTTPException(400, f"Không nhận file {name or '?'}: chỉ nhận kịch bản .txt, .docx hoặc .srt")
    data = await file.read(SCRIPT_MAX + 1)
    if len(data) > SCRIPT_MAX:
        raise HTTPException(413, f"Kịch bản {name} quá lớn (tối đa {SCRIPT_MAX >> 20} MB)")
    try:
        job = await asyncio.to_thread(flow.new_part, pid, name, data, 0)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await asyncio.to_thread(_renumber, pid)
    if run:
        api.QUEUE.submit(job.id, "auto")
    return api._view(store.load(job.id))

def cleanup_project(pid: str) -> None:
    """Local leftovers of a deleted project: the shared background copy and unfinished uploads."""
    shutil.rmtree(config.WORK_DIR / "_projects" / pid, ignore_errors=True)
    clean_uploads(pid)
