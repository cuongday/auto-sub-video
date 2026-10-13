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
