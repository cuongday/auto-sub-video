from autosub.render import build_filter, cover_filter

BOX = (96, 864, 1728, 152)

def test_blur():
    f = cover_filter(BOX, "blur", "#000000")
    assert f.startswith("[0:v]split=2[base][tmp];[tmp]crop=1728:152:96:864,boxblur=")
    assert f.endswith("[base][bl]overlay=96:864[cv]")

def test_blur_dim_adds_box():
    f = cover_filter(BOX, "blur_dim", "#000000")
    assert "overlay=96:864,drawbox=x=96:y=864:w=1728:h=152:color=black@0.45:t=fill[cv]" in f

def test_solid():
    assert cover_filter(BOX, "solid", "#102030") == "[0:v]drawbox=x=96:y=864:w=1728:h=152:color=0x102030@1:t=fill[cv]"

def test_full_graph_burns_ass():
    f = build_filter(BOX, "blur", "#000000", ass_name="subs.ass", fonts_dir="fonts")
    assert f.endswith(";[cv]ass=subs.ass:fontsdir=fonts[v]")
