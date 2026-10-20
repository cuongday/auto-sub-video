"""Local scratch copy of a job's objects. Every file here also exists in object storage
(push after writing, fetch before reading); the dir can be wiped at any time."""
import json
import os
import shutil
import threading
import time
from pathlib import Path
from . import config
from .storage import Store, get_store

_LOCK = threading.Lock()
_PINNED: dict[str, int] = {}          # job ids in use: never evicted
_MANIFEST = ".etags.json"             # key -> etag of the local copy
_MLOCK = threading.Lock()             # manifest read-modify-write
# ponytail: one small lock per object key ever fetched, never freed; refcount them if keys grow without bound
_FETCHING: dict[str, threading.Lock] = {}   # object key -> lock: one download at a time per key

def job_prefix(jid: str) -> str:
    return f"jobs/{jid}/"

class WorkDir:
    """Scratch dir for one job, kept in sync with jobs/<id>/ in the store."""

    def __init__(self, jid: str, store: Store | None = None):
        self.jid = jid
        self.store = store or get_store()
        self.path = config.WORK_DIR / jid
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / ".used").touch()

    # ---- manifest of local copies
    def _manifest(self) -> dict:
        try:
            return json.loads((self.path / _MANIFEST).read_text())
        except (OSError, ValueError):
            return {}

    def _remember(self, name: str, etag: str | None) -> None:
        self._update({name: etag})

    def _update(self, etags: dict) -> None:
        with _MLOCK:                          # parallel fetches of a job never drop each other's entries
            m = self._manifest()
            for name, etag in etags.items():
                if etag is None:
                    m.pop(name, None)
                else:
                    m[name] = etag
            tmp = self.path / f"{_MANIFEST}.tmp"
            tmp.write_text(json.dumps(m))
            os.replace(tmp, self.path / _MANIFEST)   # a reader never sees a half-written manifest

    def key(self, name: str) -> str:
        return job_prefix(self.jid) + name

    def local(self, name: str) -> Path:
        return self.path / name

    # ---- sync
    def fetch(self, name: str) -> Path | None:
        """Local path of `name`, downloaded if missing or stale. None if not in the store."""
        p = self.local(name)
        info = self.store.stat(self.key(name))
        if info is None:
            return None
        with _LOCK:
            lock = _FETCHING.setdefault(self.key(name), threading.Lock())
        with lock:                            # parallel callers wait for the first download, then reuse it
            if not (p.exists() and self._manifest().get(name) == info.etag):
                self.store.get_file(self.key(name), p)
                self._remember(name, info.etag)
        return p

    def fetch_dir(self, name: str) -> Path:
        """Download every object under jobs/<id>/<name>/ (e.g. tts/)."""
        prefix = self.key(name.rstrip("/") + "/")
        m, got = self._manifest(), {}
        for o in self.store.list(prefix):
            rel = o.key[len(job_prefix(self.jid)):]
            p = self.local(rel)
            if not (p.exists() and m.get(rel) == o.etag):
                self.store.get_file(o.key, p)
                got[rel] = o.etag
        self._update(got)
        d = self.local(name); d.mkdir(parents=True, exist_ok=True)
        return d

    def push(self, name: str) -> None:
        """Upload a local file (or every file under a local dir) to the store."""
        p = self.local(name)
        if p.is_dir():
            self.store.delete_prefix(self.key(name.rstrip("/") + "/"))
            for f in sorted(p.rglob("*")):
                if f.is_file():
                    rel = str(f.relative_to(self.path))
                    self.store.put_file(self.key(rel), f)
                    info = self.store.stat(self.key(rel))
                    self._remember(rel, info.etag if info else None)
            return
        self.store.put_file(self.key(name), p)
        info = self.store.stat(self.key(name))
        self._remember(name, info.etag if info else None)

    def drop(self, name: str) -> None:
        """Delete from both the store and the local copy."""
        self.store.delete(self.key(name))
        self.local(name).unlink(missing_ok=True)
        self._remember(name, None)

def remove(jid: str) -> None:
    shutil.rmtree(config.WORK_DIR / jid, ignore_errors=True)

class pinned:
    """Context manager: the job's scratch dir is not evicted while in use."""
    def __init__(self, jid: str):
        self.jid = jid

    def __enter__(self):
        with _LOCK:
            _PINNED[self.jid] = _PINNED.get(self.jid, 0) + 1
        return self

    def __exit__(self, *exc):
        with _LOCK:
            _PINNED[self.jid] -= 1
            if _PINNED[self.jid] <= 0:
                del _PINNED[self.jid]
        evict()

def _size(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())

def evict(max_bytes: int | None = None) -> list[str]:
    """Remove least recently used job dirs until the scratch area fits the limit."""
    limit = config.WORK_MAX_BYTES if max_bytes is None else max_bytes
    root = config.WORK_DIR
    if not root.exists():
        return []
    dirs = []
    for d in root.iterdir():
        if d.is_dir():
            used = d / ".used"
            dirs.append((used.stat().st_mtime if used.exists() else 0.0, d, _size(d)))
    total = sum(s for _, _, s in dirs)
    removed = []
    for _, d, s in sorted(dirs):
        if total <= limit:
            break
        with _LOCK:
            if d.name in _PINNED:
                continue
        shutil.rmtree(d, ignore_errors=True)
        total -= s
        removed.append(d.name)
    return removed

def clear_all() -> None:
    """On startup nothing in scratch is trusted (it is only a cache)."""
    if config.WORK_DIR.exists():
        for d in config.WORK_DIR.iterdir():
            shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink(missing_ok=True)

def touch(jid: str) -> None:
    p = config.WORK_DIR / jid / ".used"
    if p.exists():
        p.touch()

__all__ = ["WorkDir", "pinned", "evict", "remove", "clear_all", "touch", "job_prefix", "time"]
