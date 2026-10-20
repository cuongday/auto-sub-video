import time
from autosub import store
from autosub.models import Segment, TranslationContext, Character

def test_create_load_roundtrip():
    j = store.create("clip.mp4", "/tmp/clip.mp4")
    assert store.load(j.id) == j
    assert set(j.steps) == set(store.STEPS)

def test_list_newest_first():
    a = store.create("a", "/a"); time.sleep(0.01); b = store.create("b", "/b")
    assert [j.id for j in store.list_jobs()] == [b.id, a.id]

def test_json_documents():
    j = store.create("a")
    store.save_json(j.id, "x.json", {"a": 1})
    assert store.load_json(j.id, "x.json") == {"a": 1}
    assert store.load_json(j.id, "missing.json", default=[]) == []
    assert "x.json" in store.names(j.id)

def test_segments_context_roundtrip():
    j = store.create("a", "/a")
    segs = [Segment(id=1, start=0, end=1.5, source="你好", vi="Xin chào")]
    store.save_segments(j.id, segs)
    assert store.load_segments(j.id) == segs
    assert store.load_context(j.id) is None
    ctx = TranslationContext(summary="s", characters=[Character(name="A", vi_name="A", addressing="ta/ngươi")])
    store.save_context(j.id, ctx)
    assert store.load_context(j.id) == ctx

def test_presets():
    store.save_preset("phim", {"lang": "zh"})
    assert store.load_presets() == {"phim": {"lang": "zh"}}
    store.delete_preset("phim")
    assert store.load_presets() == {}

def test_delete(_memory_store):
    j = store.create("a", "/a")
    store.save_json(j.id, "x.json", 1)
    store.delete(j.id)
    assert _memory_store.list(f"jobs/{j.id}/") == []
    try:
        store.load(j.id); raise AssertionError("still there")
    except KeyError:
        pass

def test_list_jobs_memo_sees_own_changes(_memory_store, monkeypatch):
    a = store.create("a")
    calls = []
    real = _memory_store.list
    monkeypatch.setattr(_memory_store, "list", lambda prefix: calls.append(prefix) or real(prefix))
    assert [j.id for j in store.list_jobs()] == [a.id] and [j.id for j in store.list_jobs()] == [a.id]
    assert len(calls) == 1                                   # second call reuses the listing
    store.list_jobs()[0].name = "changed by a caller"
    assert store.list_jobs()[0].name == "a"                  # callers get their own copies
    a.name = "renamed"; store.save(a)
    assert store.list_jobs()[0].name == "renamed"            # save drops the memo
    b = store.create("b")
    assert {j.id for j in store.list_jobs()} == {a.id, b.id}
    store.delete(a.id)
    assert [j.id for j in store.list_jobs()] == [b.id]       # delete drops it too
    monkeypatch.setattr(store, "LIST_TTL", 0)
    n = len(calls); store.list_jobs(); store.list_jobs()
    assert len(calls) == n + 2                               # expired: listed again
