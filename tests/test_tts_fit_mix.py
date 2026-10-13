import numpy as np
import soundfile as sf
from autosub import media
from autosub.fit import fit_segment
from autosub.mix import SR, build_voice_track, mix
from autosub.models import Segment
from autosub.tts import cached_synthesize
from tests.fakes import FakeTTS

def seg(text): return Segment(id=1, start=0, end=1, source="x", vi=text)

def dur(p): return sf.info(p).duration

def test_cache_hit(tmp_path, _memory_store):
    tts = FakeTTS()
    a = cached_synthesize(tts, "xin chào", "v", 1.0, None, tmp_path / "l1")
    b = cached_synthesize(tts, "xin chào", "v", 1.0, None, tmp_path / "l1")
    c = cached_synthesize(tts, "xin chào", "v", 1.2, None, tmp_path / "l1")
    assert a == b != c and len(tts.calls) == 2
    assert not [p for p in (tmp_path / "l1").iterdir() if p.name.startswith(".tmp")]
    assert len(_memory_store.list("tts-cache/")) == 2

def test_cache_shared_through_store(tmp_path):
    """A fresh scratch dir (other container / after restart) reuses the stored cache."""
    tts = FakeTTS()
    cached_synthesize(tts, "xin chào", "v", 1.0, None, tmp_path / "first")
    p = cached_synthesize(tts, "xin chào", "v", 1.0, None, tmp_path / "second")
    assert len(tts.calls) == 1 and p.parent == tmp_path / "second" and p.exists()

def test_fit_fits_without_speedup(tmp_path):
    r = fit_segment(FakeTTS(), seg("a" * 10), 2.0, "v", 1.0, None, tmp_path / "s.wav", tmp_path / "c")   # 0.8 s
    assert r.speed == 1.0 and not r.overflow and abs(r.duration - 0.86) < 0.05
    assert sf.info(r.path).samplerate == SR

def test_fit_uses_native_rate(tmp_path):
    tts = FakeTTS()
    r = fit_segment(tts, seg("a" * 25), 1.8, "v", 1.0, None, tmp_path / "s.wav", tmp_path / "c")        # 2.0 s
    assert tts.calls[-1][1] > 1.0 and not r.overflow and r.duration <= 1.8 + 0.02
    assert 1.05 < r.speed <= 1.35

def test_fit_atempo_when_no_native_rate(tmp_path):
    tts = FakeTTS(); tts.native_rate = False
    r = fit_segment(tts, seg("a" * 25), 1.8, "v", 1.0, None, tmp_path / "s.wav", tmp_path / "c")
    assert len(tts.calls) == 1 and r.duration <= 1.82 and not r.overflow

def test_fit_overflow(tmp_path):
    r = fit_segment(FakeTTS(), seg("a" * 50), 1.0, "v", 1.0, None, tmp_path / "s.wav", tmp_path / "c")  # 4 s
    assert r.overflow and abs(r.speed - 1.35) < 0.02

def test_voice_track_placement(tmp_path):
    p = tmp_path / "a.wav"
    sf.write(p, np.full(SR // 2, 0.5, np.float32), SR)
    track = build_voice_track([(1.0, p), (2.9, p)], duration=3.0)
    assert len(track) == 3 * SR
    assert np.all(track[: SR - 1] == 0)
    assert abs(track[SR + SR // 4] - 0.5) < 1e-6
    assert track[-1] != 0           # second clip is truncated at the end, not dropped

def test_mix(tmp_path):
    p = tmp_path / "a.wav"
    sf.write(p, 0.3 * np.sin(np.arange(SR) / 10).astype(np.float32), SR)
    raw = tmp_path / "raw.wav"
    sf.write(raw, build_voice_track([(0.5, p)], 3.0), SR)
    bg = media.silent_audio(tmp_path / "bg.wav", 3.0)
    mix(raw, bg, tmp_path / "voice.wav", tmp_path / "mix.m4a", -6.0, 3.0)
    assert abs(media.probe_audio_duration(tmp_path / "mix.m4a") - 3.0) < 0.1
    assert abs(dur(tmp_path / "voice.wav") - 3.0) < 0.05
