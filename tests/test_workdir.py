import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from autosub import config, workdir
from autosub.storage import get_store

def test_fetch_and_refetch_when_changed(tmp_path):
    st = get_store()
    st.put_bytes("jobs/j1/a.txt", b"one")
    w = workdir.WorkDir("j1")
    assert w.fetch("a.txt").read_bytes() == b"one"
    st.put_bytes("jobs/j1/a.txt", b"two!")
    assert w.fetch("a.txt").read_bytes() == b"two!"
    assert w.fetch("missing.txt") is None

def test_parallel_fetches_download_once(monkeypatch):
    st = get_store()
    st.put_bytes("jobs/j3/source.mp4", b"x" * 1000)
    calls, real = [], st.get_file
    monkeypatch.setattr(st, "get_file", lambda k, p: calls.append(k) or time.sleep(0.2) or real(k, p))
    with ThreadPoolExecutor(8) as ex:
        paths = list(ex.map(lambda _: workdir.WorkDir("j3").fetch("source.mp4"), range(8)))
    assert calls == ["jobs/j3/source.mp4"] and len(set(paths)) == 1 and paths[0].read_bytes() == b"x" * 1000

def test_fetches_of_different_files_run_together(monkeypatch):
    st = get_store()
    st.put_bytes("jobs/j4/a.bin", b"a"); st.put_bytes("jobs/j4/b.bin", b"b")
    both, real = threading.Barrier(2, timeout=5), st.get_file
    monkeypatch.setattr(st, "get_file", lambda k, p: both.wait() is None or real(k, p))   # waits for the other one
    with ThreadPoolExecutor(2) as ex:
        assert [p.read_bytes() for p in ex.map(workdir.WorkDir("j4").fetch, ["a.bin", "b.bin"])] == [b"a", b"b"]

def test_push_dir_replaces_old_objects():
    w = workdir.WorkDir("j2")
    (w.local("tts")).mkdir()
    (w.local("tts") / "a.wav").write_bytes(b"a"); (w.local("tts") / "b.wav").write_bytes(b"b")
    w.push("tts")
    (w.local("tts") / "b.wav").unlink()
    w.push("tts")
    assert [o.key for o in get_store().list("jobs/j2/tts/")] == ["jobs/j2/tts/a.wav"]

def test_evict_lru_but_never_pinned(monkeypatch):
    monkeypatch.setattr(config, "WORK_MAX_BYTES", 1 << 30)   # the evict() run on unpin must not interfere
    for jid, age in (("old", 300), ("mid", 200), ("new", 0)):
        d = config.WORK_DIR / jid; d.mkdir(parents=True)
        (d / "blob").write_bytes(b"x" * 1000)
        (d / ".used").touch()
        os.utime(d / ".used", (time.time() - age, time.time() - age))
    with workdir.pinned("old"):
        removed = workdir.evict(max_bytes=2500)
        assert removed == ["mid"]                              # oldest unpinned first, stop once it fits
        assert (config.WORK_DIR / "old").exists() and (config.WORK_DIR / "new").exists()
