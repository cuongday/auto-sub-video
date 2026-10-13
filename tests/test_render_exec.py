import subprocess
import numpy as np
from autosub import media, render
from autosub.models import JobSettings, Region, Segment
from autosub.subtitles import build_ass
from tests.fixtures import make_video

def frame(path, t, w=640, h=360):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(np.int16)

def test_render_covers_region_only(tmp_path):
    src = make_video(tmp_path / "src.mp4", seconds=3)
    info = media.probe(src)
    work = tmp_path / "job"; work.mkdir()
    audio = media.silent_audio(work / "mix.wav", info.duration)
    st = JobSettings(region=Region(x=0.0, y=0.8, w=1.0, h=0.18), cover="blur_dim")
    ass = work / "subs.ass"
    ass.write_text(build_ass([Segment(id=1, start=0, end=3, source="", vi="Xin chào")], 640, 360, st.region, st.style))
    out = render.render_video(src, audio, ass, work / "output.mp4", info, st)
    out_info = media.probe(out)
    assert abs(out_info.duration - 3) < 0.15 and out_info.has_audio
    a, b = frame(src, 1.5), frame(out, 1.5)
    inside = np.abs(a[292:356] - b[292:356]).mean()
    outside = np.abs(a[:270] - b[:270]).mean()
    assert inside > 8 and outside < 3, (inside, outside)

def test_preview(tmp_path):
    src = make_video(tmp_path / "src.mp4", seconds=3)
    info = media.probe(src)
    work = tmp_path / "job"; work.mkdir()
    out = render.preview(src, work / "preview.mp4", info, JobSettings(cover="solid"), t=10, seconds=2)
    assert abs(media.probe(out).duration - 2) < 0.15

def test_dangling_fonts_link_is_replaced(tmp_path):
    work = tmp_path / "job"; work.mkdir()
    (work / "fonts").symlink_to(tmp_path / "gone", target_is_directory=True)
    render._link_fonts(work)
    assert (work / "fonts" / "BeVietnamPro-SemiBold.ttf").exists()
