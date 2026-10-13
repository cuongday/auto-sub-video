"""Single worker queue: jobs run one at a time (CPU-bound); events fan out to SSE subscribers."""
import queue
import threading
import time
from dataclasses import dataclass
from . import pipeline, proc, store

@dataclass
class Request:
    jid: str
    mode: str
    from_step: str | None = None
    confirm: bool = False

class JobQueue:
    def __init__(self, engines_factory=pipeline.Engines):
        self.engines_factory = engines_factory
        self._q: "queue.Queue[Request]" = queue.Queue()
        self._pending: list[str] = []
        self._lock = threading.Lock()
        self._subs: list[queue.Queue] = []
        self.current: str | None = None
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

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
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, daemon=True, name="autosub-jobs")
            self._thread.start()

    def is_active(self, jid: str) -> bool:
        with self._lock:
            return jid == self.current or jid in self._pending

    def submit(self, jid: str, mode: str, from_step: str | None = None, confirm: bool = False) -> bool:
        with self._lock:
            if jid == self.current or jid in self._pending:
                return False
            self._pending.append(jid)
        job = store.load(jid)
        job.state, job.mode, job.error = "queued", mode, None
        store.save(job)
        self._q.put(Request(jid, mode, from_step, confirm))
        self.emit({"type": "state", "job": jid, "state": "queued"})
        self.start()
        return True

    def cancel(self, jid: str) -> bool:
        with self._lock:
            queued = jid in self._pending
            if queued:
                self._pending.remove(jid)
            elif jid != self.current:
                return False
        if queued:                               # emit() takes the lock: never call it while holding it
            job = store.load(jid); job.state = "cancelled"; store.save(job)
            self.emit({"type": "state", "job": jid, "state": "cancelled"})
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
            try:
                self._run(req)
            finally:
                with self._lock:
                    self.current = None

    def _run(self, req: Request) -> None:
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
                               engines=self.engines_factory(), progress=progress, log=log, cancel=self._cancel)
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
