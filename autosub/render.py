"""ffmpeg filter graph: cover the old subtitle region, then burn the new ASS subtitles."""
import shutil
from pathlib import Path
from . import config, proc
from .models import JobSettings, Segment, VideoInfo
from .subtitles import build_ass, region_px

def cover_filter(box: tuple[int, int, int, int], cover: str, color: str) -> str:
    x, y, w, h = box
    rect = f"x={x}:y={y}:w={w}:h={h}"
    if cover == "solid":
        return f"[0:v]drawbox={rect}:color=0x{color.lstrip('#')}@1:t=fill[cv]"
    r = max(2, min(20, min(w, h) // 4))
    rc = max(1, r // 2)
    f = (f"[0:v]split=2[base][tmp];[tmp]crop={w}:{h}:{x}:{y},"
         f"boxblur=luma_radius={r}:luma_power=3:chroma_radius={rc}:chroma_power=3[bl];"
         f"[base][bl]overlay={x}:{y}")
    if cover == "blur_dim":
        f += f",drawbox={rect}:color=black@0.45:t=fill"
    return f + "[cv]"

def build_filter(box, cover: str, color: str, ass_name: str = "subs.ass", fonts_dir: str = "fonts") -> str:
    return cover_filter(box, cover, color) + f";[cv]ass={ass_name}:fontsdir={fonts_dir}[v]"

def _link_fonts(work_dir: Path) -> None:
    # ffmpeg runs inside the job dir so filter paths stay relative (no filtergraph escaping)
    link = work_dir / "fonts"
    if not link.exists():
        try:
            link.symlink_to(config.FONTS_DIR, target_is_directory=True)
        except OSError:
            shutil.copytree(config.FONTS_DIR, link)

def _graph(info: VideoInfo, settings: JobSettings, ass_name: str) -> str:
    box = region_px(settings.region, info.width, info.height)
    graph = build_filter(box, settings.cover, settings.cover_color, ass_name=ass_name, fonts_dir="fonts")
    if info.width % 2 or info.height % 2:
        graph = graph[:-3] + ",scale=trunc(iw/2)*2:trunc(ih/2)*2[v]"
    return graph

def _encode_args() -> list[str]:
    return ["-c:v", "libx264", "-preset", config.FFMPEG_PRESET, "-crf", str(config.FFMPEG_CRF), "-pix_fmt", "yuv420p"]

def render_video(src, audio: Path, ass_path: Path, out: Path, info: VideoInfo, settings: JobSettings,
                 progress=None, cancel=None) -> Path:
    """Burn cover + subtitles into src and replace its audio with `audio`. ass_path must live in out's dir."""
    work = Path(out).parent
    _link_fonts(work)
    tmp = work / (Path(out).stem + ".tmp.mp4")
    args = ["-i", str(src), "-i", str(audio), "-filter_complex", _graph(info, settings, Path(ass_path).name),
            "-map", "[v]", "-map", "1:a", *_encode_args(), "-c:a", "aac", "-b:a", "192k",
            "-t", f"{info.duration:.3f}", "-movflags", "+faststart", tmp.name]
    proc.run_ffmpeg(args, duration=info.duration, progress=progress, cancel=cancel, cwd=work)
    tmp.replace(out)
    return Path(out)

SAMPLE_TEXT = "Đây là phụ đề tiếng Việt mẫu để xem thử vị trí và cỡ chữ"

def preview(src, out: Path, info: VideoInfo, settings: JobSettings, t: float, segments: list[Segment] | None = None,
            cancel=None, seconds: float = 5.0) -> Path:
    """Short clip from t with cover + subtitles (job segments if any, else a sample line) and original audio."""
    work = Path(out).parent
    _link_fonts(work)
    t = max(0.0, min(t, max(0.0, info.duration - seconds)))
    shifted = [s.model_copy(update={"start": s.start - t, "end": s.end - t}) for s in (segments or [])
               if s.end > t and s.start < t + seconds and s.vi.strip()]
    if not shifted:
        shifted = [Segment(id=1, start=0, end=seconds, source="", vi=SAMPLE_TEXT)]
    ass = work / "preview.ass"
    ass.write_text(build_ass(shifted, info.width, info.height, settings.region, settings.style), encoding="utf-8")
    tmp = work / (Path(out).stem + ".tmp.mp4")
    args = ["-ss", f"{t:.3f}", "-t", f"{seconds:.3f}", "-i", str(src),
            "-filter_complex", _graph(info, settings, ass.name), "-map", "[v]", "-map", "0:a?",
            *_encode_args(), "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", tmp.name]
    proc.run_ffmpeg(args, duration=seconds, cancel=cancel, cwd=work)
    tmp.replace(out)
    return Path(out)
