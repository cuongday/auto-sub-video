from autosub import config
from autosub.fonts import FONTS, DEFAULT_FONT, get_font
from autosub.models import Region, Segment, SubStyle
from autosub.subtitles import build_ass

def test_every_font_file_is_bundled():
    for f in FONTS:
        assert (config.FONTS_DIR / f.file).is_file(), f.file
    assert get_font(DEFAULT_FONT).family == "Be Vietnam Pro SemiBold"

def test_unknown_font_falls_back_to_default():
    assert get_font("Comic Sans").id == DEFAULT_FONT

def test_ass_uses_family_and_bold_flag():
    seg = [Segment(id=1, start=0, end=1, source="", vi="Xin chào")]
    reg = Region()
    ass = build_ass(seg, 1920, 1080, reg, SubStyle(font="montserrat"))
    assert "Style: Default,Montserrat,58," in ass and ",-1,0,0,0,100,100," in ass   # Bold=-1
    ass = build_ass(seg, 1920, 1080, reg, SubStyle(font="pacifico", color="#FFD400"))
    assert "Style: Default,Pacifico,58,&H0000D4FF," in ass and ",0,0,0,0,100,100," in ass
