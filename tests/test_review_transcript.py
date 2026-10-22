from autosub.models import FilmInfo, Job, JobSettings, Segment
from autosub.models import Word
from autosub.review import transcript
from autosub.review.transcript import chunk, transcript_lang, filter_ads, parse_vtt

SAMPLE = """WEBVTT

1
00:00:06.000 --> 00:00:12.074
Nhấn phát. Phụ đề xuất hiện.
Hơn 200 ngôn ngữ. Một ứng dụng:  tryray.app

2
00:03:29.661 --> 00:03:31.333 align:start
- Bạn có thấy không? - Ừ.

3
01:02.500 --> 01:04.000
<i>Đi thôi</i>
"""

def _lines(times):
    return [Segment(id=i + 1, start=t, end=t + 5, source="x") for i, t in enumerate(times)]

def test_parse_vtt():
    ls = parse_vtt(SAMPLE)
    assert [(s.start, s.end, s.source) for s in ls] == [
        (6.0, 12.074, "Nhấn phát. Phụ đề xuất hiện. Hơn 200 ngôn ngữ. Một ứng dụng: tryray.app"),
        (62.5, 64.0, "Đi thôi"), (209.661, 211.333, "- Bạn có thấy không? - Ừ.")]
    assert [s.id for s in ls] == [1, 2, 3]

def test_filter_ads_drops_url_and_edge_credits():
    ls = parse_vtt(SAMPLE) + [Segment(id=9, start=7190, end=7192, source="Vietsub bởi nhóm ABC")]
    assert [s.source for s in filter_ads(ls, 7200)] == ["Đi thôi", "- Bạn có thấy không? - Ừ."]

def test_edge_keyword_mid_film_is_kept():
    ls = [Segment(id=1, start=3000, end=3002, source="Tôi đọc phụ đề")]
    assert len(filter_ads(ls, 7200)) == 1

def test_chunk_cuts_at_biggest_gap_in_window():
    ts = [t for t in range(0, 2000, 5) if not 700 <= t < 720]
    assert chunk(_lines(ts), 2000)[0] == (0, 710)

def test_chunk_merges_short_tail():
    assert chunk(_lines(range(0, 1000, 5)), 1000) == [(0, 1000)]

def test_chunk_cuts_at_small_gap_not_window_end():
    # 4.7 s lines, 0.3 s gaps, one 0.5 s gap after the line ending at 705.8 -> cut at its midpoint
    ls, t = [], 0.0
    while t < 1500:
        ls.append(Segment(id=len(ls) + 1, start=t, end=t + 4.7, source="x"))
        t += 5.0 if not 700 <= t < 705 else 5.2
    cut = chunk(ls, 1500)[0][1]
    assert 600 <= cut < 900 and cut != 900
    prev = max((l for l in ls if l.end < cut), key=lambda l: l.end)
    nxt = min((l for l in ls if l.start > cut), key=lambda l: l.start)
    assert prev.start == 700 and abs(cut - (prev.end + nxt.start) / 2) < 1e-9

def _job(film, lang="ko"):
    return Job(id="j", name="n", created=0, source="s", film=film, settings=JobSettings(lang=lang))

def test_transcript_lang():
    assert transcript_lang(_job(FilmInfo(subtitle="vie"))) == "vi"
    assert transcript_lang(_job(FilmInfo(subtitle="eng"))) == "en"
    assert transcript_lang(_job(FilmInfo(subtitle=None))) == "ko"
    assert transcript_lang(_job(None)) == "ko"

def test_dubbed_film_is_transcribed_in_vietnamese():
    # a "Thuyết minh" / "Lồng tiếng" server carries a Vietnamese voice track over the film, whatever its country
    from autosub import api  # noqa: F401  (review_api is loaded through the app)
    from autosub.review_api import guess_lang
    assert guess_lang(["Trung Quốc", "Hồng Kông"], "Thuyết minh #1") == "vi"
    assert guess_lang(["Hàn Quốc"], "Lồng Tiếng") == "vi"
    assert guess_lang(["Trung Quốc"], "Vietsub #1") == "zh"
    assert guess_lang(["Hàn Quốc"]) == "ko" and guess_lang(["Âu Mỹ"], "") == "en"

def test_dubbed_asr_hears_vietnamese_and_chinese(monkeypatch):
    from autosub import asr
    from autosub.asr.whisper_mixed import MixedWhisperASR, pick, windows
    monkeypatch.setattr(asr.importlib.util, "find_spec", lambda m: object())
    a = asr.get_asr("vi")
    assert isinstance(a, MixedWhisperASR) and a.languages == ("vi", "zh")
    sr = 16000
    speech = [{"start": 0, "end": 2 * sr}, {"start": int(2.5 * sr), "end": 4 * sr},   # 0.5 s pause: one window
              {"start": 10 * sr, "end": 12 * sr},                                      # long pause: a new window
              {"start": int(12.2 * sr), "end": 40 * sr}]                               # would pass 28 s: new window
    assert windows(speech) == [(0, 4 * sr), (10 * sr, 12 * sr), (int(12.2 * sr), 40 * sr)]
    assert pick({"vi": 0.1, "zh": 0.8, "en": 0.9}, ("vi", "zh")) == "zh" and pick({}, ("vi", "zh")) == "vi"

def test_mixed_transcript_lines():
    w = lambda t, s: Word(text=t, start=s, end=s + 0.3)  # noqa: E731
    lines = transcript.from_words([w("Xin", 0), w("chào.", 0.3), w("你要", 3), w("是", 3.3), w("不", 3.6), w("喜欢", 3.9),
                                  w("開始,", 9), w("向", 9.3)], "vi")
    assert [s.source for s in lines] == ["Xin chào.", "你要是不喜欢", "開始,向"]

def test_whisper_channel_outro_is_dropped():
    ls = [Segment(id=1, start=4012, end=4017, source="Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn"),
          Segment(id=2, start=2105, end=2108, source="Các bạn hãy đăng kí cho kênh lalaschool"),
          Segment(id=3, start=3000, end=3002, source="Kênh này hay quá, đăng ký đi")]
    assert [s.id for s in filter_ads(ls, 7200)] == [1]
