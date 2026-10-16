import numpy as np
from autosub.lyrics import flag_lyrics, foreign_ratio, is_lyrics, levels
from autosub.models import Segment

def seg(i, a, b, text): return Segment(id=i, start=a, end=b, source=text)

def test_foreign_ratio():
    assert foreign_ratio("你今天怎么这么晚", "zh") == 0
    assert foreign_ratio("neverrappergirl,", "zh") == 1
    assert 0.5 < foreign_ratio("youknow爱有多远", "zh") < 1
    assert foreign_ratio("苹果的营销副总裁KN啊", "zh") < 0.3
    assert foreign_ratio("你好世界", "en") == 1

def test_levels_per_line():
    sr = 1000
    voice = np.concatenate([0.5 * np.ones(5000), 0.01 * np.ones(5000)]).astype(np.float32)
    music = np.concatenate([0.005 * np.ones(5000), 0.01 * np.ones(5000)]).astype(np.float32)
    (v1, m1), (v2, m2) = levels(voice, music, sr, [seg(1, 0, 4, "a"), seg(2, 6, 9, "b")])
    assert v1 - m1 > 35 and abs(v2 - m2) < 1

# values measured on real clips: (text, voice dB, music dB, expected)
REAL = [
    ("neverrarebgirl,", -34.8, -28.9, True),        # song in a Chinese vlog
    ("youknow爱有多远", -30.2, -30.1, True),
    ("wonabe", -33.1, -36.2, True),
    ("becausetheproductis", -26.4, -55.9, False),   # English interview inside a Chinese review
    ("Andsothatled", -16.0, -56.3, False),
    ("欢迎收看我的日常", -22.1, -31.9, False),        # Chinese speech over music
    ("也许这里就有答案，", -25.8, -42.7, False),
    ("我们每天不仅要面对蜥蜴的侵扰，", -23.0, -25.3, False),  # Chinese speech over loud survival-vlog music
    ("我去，", -28.5, -25.7, False),
]

def test_measured_lines():
    for text, v, m, want in REAL:
        assert is_lyrics(text, v, m, "zh") is want, text

def test_flag_lyrics_and_unflag():
    segs = [seg(1, 0, 2, "neverrarebgirl"), seg(2, 2, 4, "欢迎收看")]
    segs[1].flags = ["lyrics"]
    out = flag_lyrics(segs, [(-34.8, -28.9), (-22.1, -31.9)], "zh")
    assert out[0].flags == ["lyrics"] and out[1].flags == []
    assert flag_lyrics(segs, [], "zh") is segs
