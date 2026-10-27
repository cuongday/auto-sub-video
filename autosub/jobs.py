"""Job queue with two lanes; events fan out to SSE subscribers.

- main lane: sub/film/review jobs, one at a time (CPU-bound); cancel kills every child process.
- audio lane: audio-story jobs and background tasks (submit_task), AUDIO_WORKERS at a time; each has its own
  cancel event, so cancelling one never touches the others' processes (proc.run kills only its own child)."""
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable
from . import config, pipeline, proc, store

AUDIO_KINDS = {"audio"}

@dataclass
class Request:
    jid: str
    mode: str
    from_step: str | None = None
    confirm: bool = False

@dataclass
class Task:
    """An arbitrary callable run in the audio lane: fn(cancel_event, progress(pct)). Not a stored job."""
    key: str
    fn: Callable[[threading.Event, Callable[[float], None]], None]

class JobQueue:
    def __init__(self, engines_factory=pipeline.Engines, audio_workers: int | None = None):
        self.engines_factory = engines_factory
        self._lock = threading.Lock()
        self._subs: list[queue.Queue] = []
        # main lane
        self._q: "queue.Queue[Request]" = queue.Queue()
        self._pending: list[str] = []
        self.current: str | None = None
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        # audio lane
        self.audio_workers = max(1, audio_workers if audio_workers is not None else config.AUDIO_WORKERS)
        self._aq: "queue.Queue[Request | Task]" = queue.Queue()
        self._apending: list[str] = []
        self._running: dict[str, threading.Event] = {}
        self._athreads: list[threading.Thread] = []

    # ---- events
    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def emit(self, ev: dict) -> None:
        ev.setdefault("t", time.time())
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(ev)
            except queue.Full:
                pass

    # ---- queue
    def start(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, daemon=True, name="autosub-jobs")
                self._thread.start()
            self._athreads = [t for t in self._athreads if t.is_alive()]
            while len(self._athreads) < self.audio_workers:
                t = threading.Thread(target=self._audio_loop, daemon=True,
                                     name=f"autosub-audio-{len(self._athreads)}")
                self._athreads.append(t)
                t.start()

    def _active_locked(self, key: str) -> bool:
        return key == self.current or key in self._pending or key in self._apending or key in self._running

    def is_active(self, jid: str) -> bool:
        with self._lock:
            return self._active_locked(jid)

    def running(self) -> set[str]:
        """Ids/keys running right now, in both lanes."""
        with self._lock:
            return set(self._running) | ({self.current} if self.current else set())

    def submit(self, jid: str, mode: str, from_step: str | None = None, confirm: bool = False) -> bool:
        job = store.load(jid)
        audio = job.kind in AUDIO_KINDS
        with self._lock:
            if self._active_locked(jid):
                return False
            (self._apending if audio else self._pending).append(jid)
        job.state, job.mode, job.error = "queued", mode, None
        store.save(job)
        (self._aq if audio else self._q).put(Request(jid, mode, from_step, confirm))
        self.emit({"type": "state", "job": jid, "state": "queued"})
        self.start()
        return True

    def submit_task(self, key: str, fn: Callable[[threading.Event, Callable[[float], None]], None]) -> bool:
        """Run fn(cancel_event, progress) in the audio lane; False if `key` is already queued/running."""
        with self._lock:
            if self._active_locked(key):
                return False
            self._apending.append(key)
        self._aq.put(Task(key, fn))
        self.start()
        return True

    def cancel(self, jid: str) -> bool:
        with self._lock:
            queued = jid in self._pending or jid in self._apending
            ev = self._running.get(jid)
            if jid in self._pending:
                self._pending.remove(jid)
            elif jid in self._apending:
                self._apending.remove(jid)
            elif ev is None and jid != self.current:
                return False
        if queued:                               # emit() takes the lock: never call it while holding it
            try:
                job = store.load(jid)
            except KeyError:                     # a submit_task key, not a stored job
                self.emit({"type": "task", "key": jid, "state": "cancelled"})
                return True
            job.state = "cancelled"; store.save(job)
            self.emit({"type": "state", "job": jid, "state": "cancelled"})
            return True
        if ev is not None:                       # audio lane: stop only this one (proc.run kills its own child)
            ev.set()
            return True
        self._cancel.set()
        proc.kill_all()
        return True

    def _loop(self) -> None:
        while True:
            req = self._q.get()
            with self._lock:
                if req.jid not in self._pending:
                    continue                      # cancelled while queued
                self._pending.remove(req.jid)
                self.current = req.jid
                self._cancel = threading.Event()
                cancel = self._cancel
            try:
                self._run(req, cancel)
            finally:
                with self._lock:
                    self.current = None

    def _audio_loop(self) -> None:
        while True:
            item = self._aq.get()
            key = item.key if isinstance(item, Task) else item.jid
            with self._lock:
                if key not in self._apending:
                    continue                      # cancelled while queued
                self._apending.remove(key)
                cancel = self._running[key] = threading.Event()
            try:
                if isinstance(item, Task):
                    self._run_task(item, cancel)
                else:
                    self._run(item, cancel)
            except Exception:  # noqa: BLE001  (a worker thread must never die)
                pass
            finally:
                with self._lock:
                    self._running.pop(key, None)

    def _run_task(self, task: Task, cancel: threading.Event) -> None:
        key = task.key
        last = {"t": 0.0}

        def progress(pct: float):
            now = time.time()
            if pct in (0.0, 1.0) or now - last["t"] > 0.25:
                last["t"] = now
                self.emit({"type": "task_progress", "key": key, "pct": round(float(pct), 3)})

        self.emit({"type": "task", "key": key, "state": "running"})
        try:
            task.fn(cancel, progress)
        except proc.Cancelled:
            self.emit({"type": "task", "key": key, "state": "cancelled"})
        except Exception as e:  # noqa: BLE001
            self.emit({"type": "task", "key": key, "state": "error", "error": str(e) or type(e).__name__})
        else:
            self.emit({"type": "task", "key": key, "state": "cancelled" if cancel.is_set() else "done"})

    def _run(self, req: Request, cancel: threading.Event) -> None:
        jid = req.jid
        last = {"t": 0.0}

        def progress(step, pct):
            now = time.time()
            if pct in (0.0, 1.0) or now - last["t"] > 0.25:
                last["t"] = now
                self.emit({"type": "progress", "job": jid, "step": step, "pct": round(pct, 3)})

        def log(msg):
            self.emit({"type": "log", "job": jid, "msg": msg})

        self.emit({"type": "state", "job": jid, "state": "running"})
        try:
            job = pipeline.run(jid, mode=req.mode, from_step=req.from_step, confirm=req.confirm,
                               engines=self.engines_factory(), progress=progress, log=log, cancel=cancel)
            self.emit({"type": "state", "job": jid, "state": job.state})
        except proc.Cancelled:
            self.emit({"type": "state", "job": jid, "state": "cancelled"})
        except pipeline.NeedsConfirm as e:
            job = store.load(jid); job.state, job.error = "awaiting_review", str(e); store.save(job)
            self.emit({"type": "state", "job": jid, "state": job.state, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            try:
                job = store.load(jid)
                if job.state != "error":
                    job.state, job.error = "error", str(e); store.save(job)
            except Exception:  # noqa: BLE001
                pass
            self.emit({"type": "state", "job": jid, "state": "error", "error": str(e)})

def reset_interrupted() -> None:
    """After a restart, jobs left running/queued are marked interrupted."""
    for job in store.list_jobs():
        if job.state in ("running", "queued"):
            job.state, job.current_step = "interrupted", None
            for s in job.steps.values():
                if s.status == "running":
                    s.status = "pending"
            store.save(job)
