"""The background video of an audio story: normalized once per project (silent, 1 s keyframes) so every part
loops and cuts it by stream copy, and one shared local copy that all parts read."""
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Callable
from .. import config, media, proc, projects, workdir
from ..storage import get_store

NO_BACKGROUND = "Project chưa có video nền"
CANCELLED = "Đã huỷ chuẩn hoá video nền"
_LOCK = threading.Lock()
_PID_LOCKS: dict[str, threading.Lock] = {}     # one fetch of a project's loop at a time

def task_key(pid: str) -> str:
    return f"bg:{pid}"

def pin_key(pid: str) -> str:
    """workdir.pinned() key of the project's shared dir (never evicted while pinned)."""
    return f"_projects/{pid}"

def project_dir(pid: str) -> Path:
    d = config.WORK_DIR / "_projects" / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / ".used").touch()
    return d

def _pid_lock(pid: str) -> threading.Lock:
    with _LOCK:
        return _PID_LOCKS.setdefault(pid, threading.Lock())

def _set(pid: str, **fields) -> None:
    def apply(p):
        for k, v in fields.items():
            setattr(p.audio, k, v)
    projects.update(pid, apply)

def _finish(pid: str, cancel: threading.Event | None, **fields) -> None:
    """Write the final background state. Run as the project's queued task (`cancel` is its event), the queue marks
    the task idle in the same step: whoever reads "ready"/"error" never sees the task still active."""
    from ..api import QUEUE                              # lazy: api imports the flows
    QUEUE.finish_task(task_key(pid), cancel, lambda: _set(pid, **fields))

def normalize(pid: str, cancel: threading.Event, progress: Callable[[float], None]) -> None:
    """Re-encode the uploaded background to bg_loop.mp4 (no audio, keyframe every second, same size and fps)
    and store it; the project's background_state ends "ready", or "error" with a message (written last, after
    unpinning, see _finish)."""
    final: dict = {}
    try:
        with workdir.pinned(pin_key(pid)):
            d = project_dir(pid)
            src = d / f".source-{uuid.uuid4().hex[:8]}"
            out = d / f".bg_loop-{uuid.uuid4().hex[:8]}.mp4"
            try:
                p = projects.get(pid)
                if p is None or p.audio is None or not p.audio.background:
                    raise RuntimeError(NO_BACKGROUND)
                key = p.audio.background
                if not get_store().get_file(key, src):
                    raise RuntimeError("Không tìm thấy video nền trong kho lưu trữ")
                info = media.probe(src)
                fps = str(max(1, round(info.fps)))
                proc.run_ffmpeg(["-i", str(src), "-map", "0:v:0", "-an", "-c:v", "libx264",
                                 "-preset", config.FFMPEG_PRESET, "-crf", str(config.FFMPEG_CRF), "-pix_fmt", "yuv420p",
                                 "-g", fps, "-keyint_min", fps, "-sc_threshold", "0", "-movflags", "+faststart", str(out)],
                                duration=info.duration, progress=progress, cancel=cancel)
                cur = projects.get(pid)
                if cur is None or cur.audio is None or cur.audio.background != key:
                    return                               # replaced/removed meanwhile: its own run takes over
                st = get_store()
                st.put_file(projects.bg_loop_key(pid), out)
                obj = st.stat(projects.bg_loop_key(pid))
                etag = obj.etag if obj else None
                with _pid_lock(pid):                     # becomes the shared local copy right away
                    os.replace(out, d / "bg_loop.mp4")
                    (d / "bg_loop.etag").write_text(etag or "")
                progress(1.0)
                final.update(background_state="ready", background_error=None, background_etag=etag,
                             background_info=info)
            except proc.Cancelled:
                final.update(background_state="error", background_error=CANCELLED)
                raise
            except Exception as e:
                final.update(background_state="error", background_error=f"Chuẩn hoá video nền lỗi: {e}")
                raise
            finally:
                src.unlink(missing_ok=True)
                out.unlink(missing_ok=True)
    finally:
        if final:
            _finish(pid, cancel, **final)

def local_loop(pid: str) -> Path:
    """Local path of the project's bg_loop.mp4, shared by its parts; downloaded again when the stored object
    changed (ETag). Callers should hold workdir.pinned(pin_key(pid)) while they read it."""
    key = projects.bg_loop_key(pid)
    with _pid_lock(pid):
        d = project_dir(pid)
        dst, tag = d / "bg_loop.mp4", d / "bg_loop.etag"
        info = get_store().stat(key)
        if info is None:
            raise RuntimeError(NO_BACKGROUND)
        if dst.exists() and tag.exists() and tag.read_text() == info.etag:
            return dst
        tmp = d / f".bg_loop-{uuid.uuid4().hex[:8]}.mp4"
        try:
            if not get_store().get_file(key, tmp):
                raise RuntimeError(NO_BACKGROUND)
            os.replace(tmp, dst)                         # a part already reading the old file keeps its inode
            tag.write_text(info.etag)
        finally:
            tmp.unlink(missing_ok=True)
        return dst

def local_etag(pid: str) -> str | None:
    """ETag of the local copy last returned by local_loop."""
    tag = config.WORK_DIR / "_projects" / pid / "bg_loop.etag"
    return tag.read_text() if tag.exists() else None

def store_original(pid: str, key: str, local: Path, cancel: threading.Event | None = None) -> bool:
    """Put the uploaded file `local` (the project's background_upload) in storage as the original background
    `key`, drop originals with another extension, then remove the local file. False when the project's
    background was replaced meanwhile (another key or another upload). On failure the state is "error" and the
    upload stays on disk, so a retry needs no new upload."""
    st = get_store()

    def current() -> bool:                               # still the project's background, from this very upload
        cur = projects.get(pid)
        return bool(cur and cur.audio and cur.audio.background == key and cur.audio.background_upload == local.name)
    try:
        if not current():                                # a newer upload took over: never overwrite its object
            return False
        st.put_file(key, local)
        if not current():
            cur = projects.get(pid)
            if cur is None or cur.audio is None or cur.audio.background != key:
                st.delete(key)                           # another key now: ours is an orphan
            return False
        for o in st.list(f"projects/{pid}/background"):
            if o.key != key:
                st.delete(o.key)
    except Exception as e:
        _finish(pid, cancel, background_state="error", background_error=f"Lưu video nền vào kho lưu trữ lỗi: {e}")
        raise
    local.unlink(missing_ok=True)                        # only once stored
    def clear(p):
        if p.audio.background_upload == local.name:
            p.audio.background_upload = None
    projects.update(pid, clear)
    return True

def start(pid: str, local_upload: Path | None = None) -> bool:
    """Queue the normalization in the audio lane (state "processing"). A run already going is cancelled first.
    With `local_upload` (a finished chunked upload), the task first stores it as the project's current
    background key (store_original), so the HTTP request that finished the upload returns right away."""
    from ..api import QUEUE                              # lazy: api imports the flows
    key = task_key(pid)
    if QUEUE.is_active(key):
        QUEUE.cancel(key)
        deadline = time.time() + 15
        while QUEUE.is_active(key) and time.time() < deadline:
            time.sleep(0.1)
    p = projects.get(pid)
    bg = p.audio.background if p and p.audio else None
    _set(pid, background_state="processing", background_error=None)

    def task(cancel, progress):
        if local_upload is not None and bg and not store_original(pid, bg, local_upload, cancel):
            return
        normalize(pid, cancel, progress)
    ok = QUEUE.submit_task(key, task)
    if not ok:
        _set(pid, background_state="error", background_error="Không xếp hàng được việc chuẩn hoá video nền")
    return ok

def cancel(pid: str) -> bool:
    """Stop the project's store/normalize task (queued or running); the state becomes "error" (CANCELLED), so
    parts waiting for it stop waiting and the user can retry. False if no task is queued or running."""
    from ..api import QUEUE
    key = task_key(pid)
    if not QUEUE.cancel(key):
        return False
    deadline = time.time() + 15
    while QUEUE.is_active(key) and time.time() < deadline:
        time.sleep(0.1)
    def apply(p):                                        # a queued task never ran: nothing else says it stopped
        if p.audio.background_state == "processing":
            p.audio.background_state, p.audio.background_error = "error", CANCELLED
    projects.update(pid, apply)
    return True
