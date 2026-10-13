from autosub.models import Word
from autosub.segmenter import build_segments, join_words, text_len

def zh(chars: str, start=0.0, step=0.25, gaps: dict | None = None):
    """One Word per char; gaps={index: extra_seconds_before_char}."""
    out, t = [], start
    for i, c in enumerate(chars):
        t += (gaps or {}).get(i, 0)
        out.append(Word(text=c, start=t, end=t + step)); t += step
    return out

def test_split_on_sentence_punctuation():
    segs = build_segments(zh("你好吗。我很好！"), "zh")
    assert [s.source for s in segs] == ["你好吗。", "我很好！"]
    assert segs[0].start == 0 and segs[1].start == 1.0
    assert [s.id for s in segs] == [1, 2]

def test_split_on_pause_en():
    words = [Word(text="hello", start=0, end=0.5), Word(text="there", start=0.5, end=1.1),
             Word(text="general", start=2.0, end=2.6), Word(text="kenobi", start=2.6, end=3.3)]
    segs = build_segments(words, "en")
    assert [s.source for s in segs] == ["hello there", "general kenobi"]

def test_long_chunk_splits_at_comma():
    text = "今天天气非常好，我们一起去公园散步吧然后吃饭。"   # 23 chars > 20
    segs = build_segments(zh(text, step=0.2), "zh")
    assert len(segs) == 2
    assert segs[0].source.endswith("，")
    assert all(text_len(s.source, "zh") <= 20 for s in segs)

def test_long_duration_splits():
    words = [Word(text=f"w{i}", start=i * 0.8, end=i * 0.8 + 0.7) for i in range(10)]   # 7.9 s
    segs = build_segments(words, "en")
    assert len(segs) >= 2
    assert all(s.end - s.start <= 6.0 for s in segs)

def test_short_chunk_merges_into_previous():
    segs = build_segments(zh("我们走吧。好。", step=0.2), "zh")
    assert [s.source for s in segs] == ["我们走吧。好。"]

def test_short_not_merged_across_big_gap():
    segs = build_segments(zh("我们走吧。好。", step=0.2, gaps={5: 1.0}), "zh")
    assert len(segs) == 2

def test_empty():
    assert build_segments([], "zh") == []

def test_join_words():
    ws = [Word(text="Hello", start=0, end=1), Word(text=",", start=1, end=1), Word(text="world", start=1, end=2)]
    assert join_words(ws, "en") == "Hello, world"
    assert join_words(zh("你好"), "zh") == "你好"
