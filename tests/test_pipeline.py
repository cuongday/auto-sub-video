import threading
import pytest
from autosub import pipeline, store, media
from autosub.models import Region
from autosub.proc import Cancelled
from tests.fakes import FakeASR, FakeLLM, FakeTTS, fake_separate, ids_in
from tests.fixtures import make_video

class Rig:
    def __init__(self, tmp_path, seconds=6):
        self.src = make_video(tmp_path / "src.mp4", seconds=seconds)
        self.sep_calls = []
        self.asr = FakeASR()
        self.llm = FakeLLM()
        self.tts = FakeTTS()
        self.engines = pipeline.Engines(separate=fake_separate(self.sep_calls), asr=lambda lang, model: self.asr,
                                        llm=lambda p, m: self.llm, tts=lambda name: self.tts)
        self.job = store.create("src.mp4", str(self.src))

    def run(self, **kw):
        return pipeline.run(self.job.id, engines=self.engines, **kw)

@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)

def test_review_stops_after_translate(rig):
    job = rig.run(mode="review")
    assert job.state == "awaiting_review"
    assert job.steps["translate"].status == "done" and job.steps["tts"].status == "pending"
    segs = store.load_segments(job.id)
    assert len(segs) == 3 and segs[0].vi.startswith("VI ")
    assert store.load_context(job.id).summary
    assert (store.job_dir(job.id) / "frames" / "f5.jpg").exists()

def test_render_after_review_skips_cached_steps(rig):
    rig.run(mode="review")
    llm_calls = len(rig.llm.prompts)
    job = rig.run(mode="review", from_step="tts")
    assert job.state == "done"
    assert len(rig.sep_calls) == 1 and rig.asr.calls == 1 and len(rig.llm.prompts) == llm_calls
    d = store.job_dir(job.id)
    out = media.probe(d / "output.mp4")
    assert abs(out.duration - 6) < 0.2 and out.has_audio
    assert "VI " in (d / "subs.srt").read_text()
    assert all(s.speed is not None for s in store.load_segments(job.id))

def test_auto_runs_to_end(rig):
    job = rig.run(mode="auto")
    assert job.state == "done" and all(s.status == "done" for s in job.steps.values())

def test_change_voice_reruns_from_tts_only(rig):
    rig.run(mode="auto")
    n_tts = len(rig.tts.calls)
    job = store.load(rig.job.id); job.settings.tts_voice = "other"; store.save(job)
    rig.run(mode="auto")
    assert len(rig.tts.calls) > n_tts and len(rig.sep_calls) == 1 and rig.asr.calls == 1

def test_change_region_reruns_render_only(rig):
    rig.run(mode="auto")
    n_tts, n_llm = len(rig.tts.calls), len(rig.llm.prompts)
    job = store.load(rig.job.id); job.settings.region = Region(x=0, y=0, w=0.5, h=0.2); store.save(job)
    before = store.load(rig.job.id).steps["mix"].seconds
    job = rig.run(mode="auto")
    assert len(rig.tts.calls) == n_tts and len(rig.llm.prompts) == n_llm
    assert job.steps["mix"].seconds == before

def test_edited_text_rerenders_changed_lines_only(rig):
    rig.run(mode="auto")
    segs = store.load_segments(rig.job.id); segs[0].vi = "Câu đã sửa"; store.save_segments(rig.job.id, segs)
    job = store.load(rig.job.id); job.segments_edited = True; store.save(job)
    n = len(rig.tts.calls)
    rig.run(mode="auto")
    assert [t for t, _ in rig.tts.calls[n:]] == ["Câu đã sửa"]

def test_needs_confirm_when_overwriting_edits(rig):
    rig.run(mode="review")
    job = store.load(rig.job.id); job.segments_edited = True; job.settings.llm_model = "other"; store.save(job)
    with pytest.raises(pipeline.NeedsConfirm):
        rig.run(mode="review")
    job = rig.run(mode="review", confirm=True)
    assert job.state == "awaiting_review" and not job.segments_edited

def test_cancel(rig):
    ev = threading.Event(); ev.set()
    with pytest.raises(Cancelled):
        rig.run(mode="auto", cancel=ev)
    assert store.load(rig.job.id).state == "cancelled"

def test_error_records_step(rig):
    rig.engines.asr = lambda lang, model: (_ for _ in ()).throw(RuntimeError("no model"))
    with pytest.raises(RuntimeError):
        rig.run(mode="auto")
    job = store.load(rig.job.id)
    assert job.state == "error" and job.steps["asr"].status == "error" and "no model" in job.error

def test_tts_failure_in_review_returns_to_review(rig):
    rig.run(mode="review")
    rig.tts.fail_on = "今天"
    job = rig.run(mode="review", from_step="tts")
    assert job.state == "awaiting_review" and job.warnings
    assert any("tts_failed" in s.flags for s in store.load_segments(job.id))

def test_tts_failure_in_auto_errors_at_tts_and_retry_recovers(rig):
    rig.tts.fail_on = "今天"
    with pytest.raises(RuntimeError, match="TTS lỗi"):
        rig.run(mode="auto")
    job = store.load(rig.job.id)
    assert job.steps["tts"].status == "error" and job.steps["fit"].status == "pending"
    rig.tts.fail_on = None
    n = len(rig.tts.calls)
    job = rig.run(mode="auto", from_step="tts")
    assert job.state == "done"
    assert len(rig.tts.calls) - n == 1            # only the failed line is synthesized again

def test_auto_shortens_overflow(rig):
    def hook(prompt, schema):
        if "RÚT GỌN" in prompt:
            return {"items": [{"id": i, "vi": "ngắn"} for i in ids_in(prompt)]}
        if "items" in schema["properties"]:
            return {"items": [{"id": i, "vi": "câu này dài lắm " * 6} for i in ids_in(prompt)]}
        return None
    rig.llm.hook = hook
    rig.run(mode="auto")
    segs = store.load_segments(rig.job.id)
    assert any(s.vi == "ngắn" for s in segs)

def test_no_speech(rig):
    rig.asr.text = ""
    job = rig.run(mode="review")
    assert job.state == "awaiting_review" and store.load_segments(job.id) == []
