import subprocess
import numpy as np
import pytest
from autosub import config, media
from autosub.models import Segment, SubStyle
from autosub.review import compose
from tests.fixtures import make_video

@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(config, "FFMPEG_PRESET", "ultrafast")

def gray(path, t, w, h):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w)

def fps(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout.strip()
    n, d = r.split("/")
    return float(n) / float(d)

def shot(tmp_path, size, aspect, boxes=()):
    src = make_video(tmp_path / f"src{size[0]}x{size[1]}.mp4", seconds=4, size=size)
    return compose.render_shot(src, 1, 2, tmp_path / "shot.mp4", aspect, media.probe(src), list(boxes), "blur")

def test_layout():
    assert compose.layout("16:9")["title"] is None and compose.layout("16:9")["subs"].y == 0.80
    assert compose.layout("9:16")["title"].y == 0.20 and compose.layout("9:16")["subs"].y == 0.69

def test_shot_9x16_from_landscape(tmp_path):
    out = shot(tmp_path, (640, 360), "9:16")
    info = media.probe(out)
    assert (info.width, info.height, info.has_audio) == (1080, 1920, False)
    assert abs(info.duration - 2) < 0.1 and fps(out) == 30

def test_shot_16x9_from_portrait(tmp_path):
    out = shot(tmp_path, (360, 640), "16:9")
    info = media.probe(out)
    assert (info.width, info.height) == (1920, 1080)
    f = gray(out, 1, 1920, 1080)
    assert f[540, 100] < 20 and f[540, 960] > 20        # pillarbox, not stretched

def test_shot_9x16_from_portrait(tmp_path):
    info = media.probe(shot(tmp_path, (360, 640), "9:16"))
    assert (info.width, info.height) == (1080, 1920)

def test_shot_with_cover_box(tmp_path):
    info = media.probe(shot(tmp_path, (640, 360), "16:9", [(0, 290, 640, 64)]))
    assert (info.width, info.height) == (1920, 1080)

def test_music_bed_loops_and_fades(tmp_path):
    music = tmp_path / "m.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=3", str(music)], check=True)
    out = compose.music_bed(music, tmp_path / "bed.wav", 10)
    pcm, sr = media.decode_mono(out, 44100), 44100
    assert abs(len(pcm) / sr - 10) < 0.05
    rms = lambda a: float(np.sqrt(np.mean(a ** 2)))  # noqa: E731
    assert rms(pcm[-int(0.2 * sr):]) < rms(pcm[:2 * sr]) / 10
    assert rms(pcm[int(5 * sr):int(7 * sr)]) > rms(pcm[:2 * sr]) / 2     # looped, not silent after 3 s

def test_review_ass_has_title_and_subs():
    lines = [Segment(id=0, start=0, end=2, source="", vi="Lời đọc đầu tiên")]
    ass = compose.build_review_ass(lines, "9:16", SubStyle(), "Phim\\NPHẦN 2")
    assert "Style: Title" in ass and "PHẦN 2" in ass and "Lời đọc đầu tiên" in ass
    default = next(l for l in ass.splitlines() if l.startswith("Style: Default,")).split(",")
    title = next(l for l in ass.splitlines() if l.startswith("Style: Title,")).split(",")
    assert int(title[2]) == round(int(default[2]) * 1.4)
    only_title = compose.build_review_ass([], "9:16", SubStyle(), "Phim\\NPHẦN 2")
    assert "PHẦN 2" in only_title and only_title.count("Dialogue:") == 1
    assert "Title" not in compose.build_review_ass(lines, "16:9", SubStyle(), None)

def _audio(path, seconds):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}", str(path)],
                   check=True)
    return path

def test_finalize_duration_follows_audio(tmp_path):
    src = make_video(tmp_path / "src.mp4", seconds=5, size=(320, 180))
    info = media.probe(src)
    work = tmp_path / "job"; work.mkdir()
    shots = [compose.render_shot(src, t, 2, work / f"shots/{i}.mp4", "16:9", info, [], "blur")
             for i, t in enumerate((0, 2.5))]
    audio = _audio(work / "mix.wav", 3.5)
    out = compose.finalize(shots, audio, None, work / "output.mp4", 3.5)
    o = media.probe(out)
    assert o.has_audio and abs(o.duration - 3.5) < 0.15 and (o.width, o.height) == (1920, 1080)
    (work / "subs.ass").write_text(compose.build_review_ass(
        [Segment(id=0, start=0, end=3, source="", vi="Xin chào")], "16:9", SubStyle(), None), encoding="utf-8")
    out = compose.finalize(shots, audio, work / "subs.ass", work / "output.mp4", 3.5)
    o = media.probe(out)
    assert o.has_audio and abs(o.duration - 3.5) < 0.15
