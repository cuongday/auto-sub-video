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

def test_write_json_atomic(tmp_path):
    p = tmp_path / "x.json"
    store.write_json(p, {"a": 1})
    assert store.read_json(p) == {"a": 1}
    assert not list(tmp_path.glob("*.tmp"))
    assert store.read_json(tmp_path / "missing.json", default=[]) == []

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

def test_delete():
    j = store.create("a", "/a")
    store.delete(j.id)
    assert not store.job_dir(j.id).exists()
