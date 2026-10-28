import pytest
from pydantic import ValidationError
from autosub.models import Region, JobSettings, Segment

def test_region_must_fit_frame():
    with pytest.raises(ValidationError):
        Region(x=0.5, y=0.1, w=0.6, h=0.1)
    with pytest.raises(ValidationError):
        Region(x=0.1, y=0.95, w=0.5, h=0.1)
    assert Region(x=0, y=0, w=1, h=1).w == 1

def test_settings_defaults():
    s = JobSettings()
    assert s.lang == "zh" and s.tts_engine == "edge" and s.cover == "blur_dim"

def test_segment_flags_independent():
    a, b = Segment(id=1, start=0, end=1, source="x"), Segment(id=2, start=1, end=2, source="y")
    a.flags.append("too_long")
    assert b.flags == []

def test_state_at_set_on_state_change_and_kept_otherwise(monkeypatch):
    from autosub import store
    clock = iter([100.0, 200.0, 300.0])
    monkeypatch.setattr(store.time, "time", lambda: next(clock))
    job = store.create("v.mp4")                       # created: 100 (time.time for created) ...
    first = store.load(job.id).state_at
    assert first is not None
    j = store.load(job.id)
    j.name = "renamed"; store.save(j)                 # same state: state_at unchanged
    assert store.load(job.id).state_at == first
    j = store.load(job.id)
    j.state = "queued"; store.save(j)                 # state changed: stamped anew
    after = store.load(job.id)
    assert after.state == "queued" and after.state_at > first
