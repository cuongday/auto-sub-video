import pytest
from pydantic import ValidationError
from autosub.models import JobSettings, Region
from autosub.render import cover_boxes
from autosub.models import VideoInfo

INFO = VideoInfo(width=1920, height=1080, duration=10, fps=25, has_audio=True)

def test_default_has_no_extra_regions():
    assert JobSettings().extra_regions == []

def test_max_five_extra_regions():
    with pytest.raises(ValidationError):
        JobSettings(extra_regions=[Region(x=0, y=0, w=0.1, h=0.1)] * 6)

def test_cover_boxes_main_first_then_extras():
    st = JobSettings(region=Region(x=0.05, y=0.8, w=0.9, h=0.14), extra_regions=[Region(x=0, y=0, w=0.2, h=0.1)])
    assert cover_boxes(st, INFO) == [(96, 864, 1728, 152), (0, 0, 384, 108)]
