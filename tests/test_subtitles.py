from autosub.models import Region, Segment, SubStyle
from autosub.subtitles import region_px, auto_font_size, build_ass, build_srt, ass_color

def test_region_px_even_and_clamped():
    assert region_px(Region(x=0.05, y=0.8, w=0.9, h=0.14), 1920, 1080) == (96, 864, 1728, 152)
    x, y, w, h = region_px(Region(x=0.333, y=0.5, w=0.667, h=0.5), 1081, 1921)
    assert all(v % 2 == 0 for v in (x, y, w, h)) and x + w <= 1081 and y + h <= 1921

def test_auto_font():
    assert auto_font_size(152) == 58 and auto_font_size(10) == 14

def test_ass_color():
    assert ass_color("#FF8000") == "&H000080FF"

def test_build_ass():
    segs = [Segment(id=1, start=1.5, end=3.25, source="a", vi="Xin chào {bạn}\nnhé"),
            Segment(id=2, start=4, end=5, source="b", vi="")]
    ass = build_ass(segs, 1920, 1080, Region(x=0.05, y=0.8, w=0.9, h=0.14), SubStyle())
    assert "PlayResX: 1920" in ass and "PlayResY: 1080" in ass
    assert "Be Vietnam Pro SemiBold,58," in ass
    assert ",5,96,96,0,1" in ass                      # alignment 5, MarginL, MarginR, MarginV, encoding
    assert "Dialogue: 0,0:00:01.50,0:00:03.25,Default,,0,0,0,,{\\pos(960,940)}Xin chào ｛bạn｝\\Nnhé" in ass
    assert ass.count("Dialogue:") == 1

def test_build_srt():
    segs = [Segment(id=1, start=61.5, end=63.0, source="a", vi="Một"), Segment(id=2, start=64, end=65, source="b", vi="Hai")]
    assert build_srt(segs) == "1\n00:01:01,500 --> 00:01:03,000\nMột\n\n2\n00:01:04,000 --> 00:01:05,000\nHai\n"
