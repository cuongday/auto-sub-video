from autosub.models import FilmInfo, Job, JobSettings, Segment
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
