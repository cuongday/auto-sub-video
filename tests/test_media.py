import threading
import time
import numpy as np
import pytest
import soundfile as sf
from autosub import media, proc
from tests.fixtures import make_video

@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("v") / "clip.mp4", seconds=3)

def test_probe(clip):
    info = media.probe(clip)
    assert (info.width, info.height) == (640, 360)
    assert abs(info.duration - 3) < 0.1 and info.has_audio and info.fps == 25

def test_probe_bad_file(tmp_path):
    (tmp_path / "x.mp4").write_text("nope")
    with pytest.raises(RuntimeError):
        media.probe(tmp_path / "x.mp4")

def test_frames(clip, tmp_path):
    frames = media.grab_frames(clip, tmp_path / "frames", 3.0)
    assert [f.name for f in frames] == [f"f{i}.jpg" for i in range(6)] and all(f.stat().st_size > 0 for f in frames)

def test_extract_and_16k(clip, tmp_path):
    progress = []
    wav = media.extract_audio(clip, tmp_path / "a.wav", duration=3.0, progress=progress.append)
    assert sf.info(wav).samplerate == 44100 and sf.info(wav).channels == 2
    w16 = media.to_16k_mono(wav, tmp_path / "a16.wav")
    assert sf.info(w16).samplerate == 16000 and sf.info(w16).channels == 1
    assert progress and progress[-1] > 0.9
    assert not list(tmp_path.glob("*.tmp*"))

def test_decode_and_atempo(clip, tmp_path):
    wav = media.extract_audio(clip, tmp_path / "a.wav")
    pcm = media.decode_mono(wav)
    assert abs(len(pcm) / 44100 - 3) < 0.05 and pcm.dtype == np.float32
    fast = media.atempo(wav, tmp_path / "f.wav", 1.5)
    assert abs(sf.info(fast).duration - 2.0) < 0.05

def test_cancel_kills_process():
    ev = threading.Event()
    threading.Timer(0.3, ev.set).start()
    t0 = time.time()
    with pytest.raises(proc.Cancelled):
        proc.run(["sleep", "10"], cancel=ev)
    assert time.time() - t0 < 3

def test_error_has_tail():
    with pytest.raises(RuntimeError, match="lỗi"):
        proc.run_ffmpeg(["-i", "/nonexistent.mp4", "/tmp/x.mp4"])
