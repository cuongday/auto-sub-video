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

def test_several_boxes_chain_through_labels():
    boxes = [BOX, (20, 20, 400, 80)]
    f = cover_filter(boxes, "blur", "#000000")
    assert f.count("boxblur=") == 2
    assert "[0:v]split=2[base0][tmp0]" in f and "[c0]split=2[base1][tmp1]" in f
    assert f.endswith("[base1][bl1]overlay=20:20[cv]")

def test_several_boxes_solid_and_dim():
    f = cover_filter([BOX, (20, 20, 400, 80)], "solid", "#102030")
    assert f == ("[0:v]drawbox=x=96:y=864:w=1728:h=152:color=0x102030@1:t=fill,"
                 "drawbox=x=20:y=20:w=400:h=80:color=0x102030@1:t=fill[cv]")
    assert cover_filter([BOX, (20, 20, 400, 80)], "blur_dim", "#000000").count("color=black@0.45") == 2
