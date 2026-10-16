from autosub.ocr import Reading, merge_readings, similar

def r(t, text, score=0.95): return Reading(t=t, text=text, score=score)

def test_similar():
    assert similar("欢迎收看我的日常", "欢迎收看我的日常")
    assert similar("欢迎收看我的日常", "欢迎收看我的日當")          # one OCR slip
    assert not similar("欢迎收看", "然后这个是表弟的摩托车")
    assert not similar("", "a")

def test_merge_runs_into_lines_with_timing():
    rs = [r(0.0, ""), r(0.5, "欢迎收看我的日常"), r(1.0, "欢迎收看我的日常"), r(1.5, "欢迎收看我的日當"),
          r(2.0, ""), r(2.5, "然后"), r(3.0, "然后"), r(3.5, "")]
    segs = merge_readings(rs, step=0.5)
    assert [(s.source, s.start, s.end) for s in segs] == [("欢迎收看我的日常", 0.5, 2.0), ("然后", 2.5, 3.5)]
    assert [s.id for s in segs] == [1, 2]

def test_drops_low_confidence_and_single_frame_flicker():
    rs = [r(0, "噪"), r(0.5, "真的字幕", 0.4), r(1.0, "真的字幕"), r(1.5, "真的字幕"), r(2.0, "")]
    segs = merge_readings(rs, step=0.5, min_frames=2)
    assert [s.source for s in segs] == ["真的字幕"]

def test_ends_at_video_end():
    segs = merge_readings([r(0, "a字幕"), r(0.5, "a字幕")], step=0.5)
    assert segs[0].end == 1.0

def test_pipeline_ocr_source(tmp_path, monkeypatch):
    from autosub import ocr, store
    from autosub.models import Segment as S
    from tests.test_pipeline import Rig
    rig = Rig(tmp_path)
    monkeypatch.setattr(ocr, "read_subtitles", lambda *a, **k: [S(id=1, start=0.5, end=2.0, source="字幕一"),
                                                               S(id=2, start=2.5, end=4.0, source="字幕二")])
    job = store.load(rig.job.id); job.settings.text_source = "ocr"; store.save(job)
    job = rig.run(mode="review")
    segs = store.load_segments(job.id)
    assert [(s.source, s.start, s.end) for s in segs] == [("字幕一", 0.5, 2.0), ("字幕二", 2.5, 4.0)]
    assert rig.asr.calls == 0 and segs[0].vi.startswith("VI ")
