"""Cancellable child processes (ffmpeg, demucs) with captured output."""
import collections
import subprocess
import threading
from typing import Callable

class Cancelled(Exception):
    pass

_LIVE: set[subprocess.Popen] = set()
_LOCK = threading.Lock()

def kill_all() -> None:
    with _LOCK:
        live = list(_LIVE)
    for p in live:
        try:
            p.kill()
        except OSError:
            pass

def run(cmd: list[str], *, cwd=None, cancel: threading.Event | None = None,
        on_line: Callable[[str], None] | None = None, stdout_lines: bool = False) -> str:
    """Run cmd; feed each line of stderr (or stdout if stdout_lines) to on_line.
    Returns the tail of stderr. Raises Cancelled if cancel is set, RuntimeError on non-zero exit."""
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, errors="replace", bufsize=1)
    with _LOCK:
        _LIVE.add(p)
    tail: collections.deque[str] = collections.deque(maxlen=20)

    def pump(stream, feed):
        for line in stream:
            line = line.rstrip("\r\n")
            if stream is p.stderr:
                tail.append(line)
            if feed and on_line:
                on_line(line)

    t_out = threading.Thread(target=pump, args=(p.stdout, stdout_lines), daemon=True)
    t_err = threading.Thread(target=pump, args=(p.stderr, not stdout_lines), daemon=True)
    t_out.start(); t_err.start()
    watcher_stop = threading.Event()
    if cancel is not None:
        def watch():
            while not watcher_stop.is_set():
                if cancel.wait(0.2):
                    try:
                        p.kill()
                    except OSError:
                        pass
                    return
        threading.Thread(target=watch, daemon=True).start()
    try:
        rc = p.wait()
        t_out.join(); t_err.join()
    finally:
        watcher_stop.set()
        with _LOCK:
            _LIVE.discard(p)
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if rc != 0:
        raise RuntimeError(f"{cmd[0]} lỗi (mã {rc}):\n" + "\n".join(tail))
    return "\n".join(tail)

def run_ffmpeg(args: list[str], *, duration: float | None = None, progress: Callable[[float], None] | None = None,
               cancel: threading.Event | None = None, cwd=None) -> None:
    """ffmpeg with -progress parsing; progress receives 0..1 relative to duration."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats", *args]

    def on_line(line: str):
        if progress and duration and line.startswith("out_time_us="):
            try:
                us = int(line.split("=", 1)[1])
            except ValueError:
                return
            progress(min(1.0, max(0.0, us / 1e6 / duration)))

    run(cmd, cwd=cwd, cancel=cancel, on_line=on_line, stdout_lines=True)
