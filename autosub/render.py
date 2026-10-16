"""ffmpeg filter graph: cover the old subtitle region, then burn the new ASS subtitles."""
import shutil
from pathlib import Path
from . import config, proc
from .models import JobSettings, Segment, VideoInfo
from .subtitles import build_ass, region_px

def cover_filter(boxes, cover: str, color: str) -> str:
    """Cover one box or a list of boxes, from [0:v] to [cv]."""
    if boxes and isinstance(boxes[0], int):
        boxes = [boxes]
    rects = [f"x={x}:y={y}:w={w}:h={h}" for x, y, w, h in boxes]
    if cover == "solid":
        return "[0:v]" + ",".join(f"drawbox={r}:color=0x{color.lstrip('#')}@1:t=fill" for r in rects) + "[cv]"
    if len(boxes) == 1:
        x, y, w, h = boxes[0]
        r = max(2, min(20, min(w, h) // 4)); rc = max(1, r // 2)
        f = (f"[0:v]split=2[base][tmp];[tmp]crop={w}:{h}:{x}:{y},"
             f"boxblur=luma_radius={r}:luma_power=3:chroma_radius={rc}:chroma_power=3[bl];"
             f"[base][bl]overlay={x}:{y}")
        if cover == "blur_dim":
            f += f",drawbox={rects[0]}:color=black@0.45:t=fill"
        return f + "[cv]"
    parts, src = [], "[0:v]"
    for i, ((x, y, w, h), rect) in enumerate(zip(boxes, rects)):
        r = max(2, min(20, min(w, h) // 4)); rc = max(1, r // 2)
        dst = "[cv]" if i == len(boxes) - 1 else f"[c{i}]"
        step = (f"{src}split=2[base{i}][tmp{i}];[tmp{i}]crop={w}:{h}:{x}:{y},"
                f"boxblur=luma_radius={r}:luma_power=3:chroma_radius={rc}:chroma_power=3[bl{i}];"
                f"[base{i}][bl{i}]overlay={x}:{y}")
        if cover == "blur_dim":
            step += f",drawbox={rect}:color=black@0.45:t=fill"
        parts.append(step + dst)
        src = dst
    return ";".join(parts)

def cover_boxes(settings: JobSettings, info: VideoInfo) -> list[tuple[int, int, int, int]]:
    """Pixel boxes to cover: the subtitle region first, then the extra regions."""
    return [region_px(r, info.width, info.height) for r in [settings.region, *settings.extra_regions]]

def build_filter(box, cover: str, color: str, ass_name: str = "subs.ass", fonts_dir: str = "fonts") -> str:
    return cover_filter(box, cover, color) + f";[cv]ass={ass_name}:fontsdir={fonts_dir}[v]"

def _link_fonts(work_dir: Path) -> None:
    # ffmpeg runs inside the job dir so filter paths stay relative (no filtergraph escaping)
    link = work_dir / "fonts"
    if link.is_symlink() and not link.exists():
        link.unlink()                    # dangling: job dir moved to another machine/container
    if not link.exists():
        try:
            link.symlink_to(config.FONTS_DIR, target_is_directory=True)
        except OSError:
            shutil.copytree(config.FONTS_DIR, link)

def _graph(info: VideoInfo, settings: JobSettings, ass_name: str) -> str:
    graph = build_filter(cover_boxes(settings, info), settings.cover, settings.cover_color, ass_name=ass_name,
                         fonts_dir="fonts")
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

def soft_subtitles(video: Path, srt: Path, out: Path, cancel=None) -> Path:
    """Copy of `video` with the SRT added as a selectable Vietnamese subtitle track (no re-encode)."""
    tmp = Path(out).with_name(Path(out).stem + ".tmp.mp4")
    proc.run_ffmpeg(["-i", str(video), "-i", str(srt), "-map", "0", "-map", "1", "-c", "copy", "-c:s", "mov_text",
                     "-metadata:s:s:0", "language=vie", "-metadata:s:s:0", "title=Tiếng Việt",
                     "-movflags", "+faststart", str(tmp)], cancel=cancel)
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
