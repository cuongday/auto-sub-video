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

def normalize(pid: str, cancel: threading.Event, progress: Callable[[float], None]) -> None:
    """Re-encode the uploaded background to bg_loop.mp4 (no audio, keyframe every second, same size and fps)
    and store it; the project's background_state ends "ready", or "error" with a message."""
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
                return                                   # replaced/removed meanwhile: its own run takes over
            st = get_store()
            st.put_file(projects.bg_loop_key(pid), out)
            obj = st.stat(projects.bg_loop_key(pid))
            etag = obj.etag if obj else None
            with _pid_lock(pid):                         # becomes the shared local copy right away
                os.replace(out, d / "bg_loop.mp4")
                (d / "bg_loop.etag").write_text(etag or "")
            _set(pid, background_state="ready", background_error=None, background_etag=etag, background_info=info)
            progress(1.0)
        except proc.Cancelled:
            _set(pid, background_state="error", background_error="Đã huỷ chuẩn hoá video nền")
            raise
        except Exception as e:
            _set(pid, background_state="error", background_error=f"Chuẩn hoá video nền lỗi: {e}")
            raise
        finally:
            src.unlink(missing_ok=True)
            out.unlink(missing_ok=True)

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

def start(pid: str) -> bool:
    """Queue the normalization in the audio lane (state "processing"). A run already going is cancelled first."""
    from ..api import QUEUE                              # lazy: api imports the flows
    key = task_key(pid)
    if QUEUE.is_active(key):
        QUEUE.cancel(key)
        deadline = time.time() + 15
        while QUEUE.is_active(key) and time.time() < deadline:
            time.sleep(0.1)
    _set(pid, background_state="processing", background_error=None)
    ok = QUEUE.submit_task(key, lambda cancel, progress: normalize(pid, cancel, progress))
    if not ok:
        _set(pid, background_state="error", background_error="Không xếp hàng được việc chuẩn hoá video nền")
    return ok
