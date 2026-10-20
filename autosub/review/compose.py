"""Assemble a review video: film shots framed to 16:9 or 9:16 (no original audio), an optional looped music bed,
the narration subtitles (+ the title on 9:16) and the final concat that follows the narration's length."""
from pathlib import Path
from .. import proc, render
from ..models import Region, ReviewSettings, Segment, SubStyle, VideoInfo
from ..subtitles import build_ass, region_px

OUT = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
FPS = 30

def layout(aspect: str, review: ReviewSettings | None = None) -> dict:
    """Subtitle and title regions of the output frame (9:16: the film sits in the middle, title above, subs below);
    the part's own boxes win when set."""
    if aspect == "9:16":
        out = {"subs": Region(x=0.05, y=0.69, w=0.90, h=0.11), "title": Region(x=0.06, y=0.20, w=0.88, h=0.12)}
    else:
        out = {"subs": Region(x=0.05, y=0.80, w=0.90, h=0.14), "title": None}
    if review:
        out["subs"] = review.sub_region or out["subs"]
        out["title"] = out["title"] and (review.title_region or out["title"])
    return out

def frame_filter(aspect: str, info: VideoInfo, cover_boxes: list[tuple[int, int, int, int]], cover: str) -> str:
    """[0:v] -> [v]: cover regions (source coordinates), then fit the frame (16:9 letterbox, 9:16 blurred background)."""
    W, H = OUT[aspect]
    head, src = (render.cover_filter(cover_boxes, cover, "#000000") + ";", "[cv]") if cover_boxes else ("", "[0:v]")
    src += f"fps={FPS},tpad=stop_mode=clone:stop=-1"      # a shot ending at the film's last frame still gets every frame
    if aspect == "16:9":
        return head + (f"{src},scale={W}:{H}:force_original_aspect_ratio=decrease,"
                       f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[v]")
    return head + (f"{src},split=2[bg][fg];"
                   f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:2,eq=brightness=-0.12[b];"
                   f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease[f];[b][f]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")

def frame_counts(durations: list[float]) -> list[int]:
    """Frames of each shot on the FPS grid of the output timeline, so the joined picture never drifts from the audio."""
    out, t = [], 0.0
    for d in durations:
        out.append(round((t + d) * FPS) - round(t * FPS))
        t += d
    return out

def render_shot(src: Path, start: float, frames: int, out: Path, aspect: str, info: VideoInfo, cover_boxes, cover: str,
                cancel=None) -> Path:
    """`frames` output frames of the film from `start`, framed for `aspect`, no audio."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".tmp.mp4")
    proc.run_ffmpeg(["-ss", f"{start:.3f}", "-t", f"{frames / FPS + 1:.3f}", "-i", str(src), "-frames:v", str(frames),
                     "-filter_complex", frame_filter(aspect, info, cover_boxes, cover), "-map", "[v]", "-an",
                     *render._encode_args(), str(tmp)], cancel=cancel)
    tmp.replace(out)
    return out

def preview_frame(src: Path, t: float, out: Path, aspect: str, info: VideoInfo, cover_boxes, cover: str,
                  ass: Path | None) -> Path:
    """One output frame of the film at t, framed for `aspect`, with `ass` (in out's dir, cue times on the same
    clock as t_ass = 0) burnt in: what the render would show at that point."""
    out = Path(out)
    work = out.parent
    graph = frame_filter(aspect, info, cover_boxes, cover)
    if ass:
        render._link_fonts(work)
        graph = graph[:-3] + f"[fr];[fr]ass={Path(ass).name}:fontsdir=fonts[v]"
    tmp = work / (out.stem + ".tmp.jpg")
    proc.run_ffmpeg(["-ss", f"{max(0.0, t):.3f}", "-i", str(Path(src).resolve()), "-frames:v", "1",
                     "-filter_complex", graph, "-map", "[v]", "-q:v", "3", tmp.name], cwd=work)
    tmp.replace(out)
    return out

def music_bed(music: Path, out_wav: Path, duration: float, cancel=None) -> Path:
    """The music looped to `duration`, loudness-normalized, with a 2 s fade-out."""
    out_wav = Path(out_wav)
    tmp = out_wav.with_name(out_wav.stem + ".tmp.wav")
    proc.run_ffmpeg(["-stream_loop", "-1", "-i", str(music), "-t", f"{duration:.3f}",
                     "-af", f"loudnorm=I=-16,afade=t=out:st={max(0.0, duration - 2):.3f}:d=2",
                     "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(tmp)], cancel=cancel)
    tmp.replace(out_wav)
    return out_wav

def build_review_ass(lines: list[Segment], aspect: str, style: SubStyle, title: str | None,
                     review: ReviewSettings | None = None) -> str:
    """Narration subtitles; with a title (9:16, not turned off) also a `Title` style 1.4x larger, the whole video."""
    W, H = OUT[aspect]
    lay = layout(aspect, review)
    ass = build_ass(lines, W, H, lay["subs"], style)
    if not (title and lay["title"]) or (review and not review.show_title):
        return ass
    x, y, w, h = region_px(lay["title"], W, H)
    default = next(l for l in ass.splitlines() if l.startswith("Style: Default,"))
    f = default.split(",")
    f[0], f[2], f[19], f[20] = "Style: Title", str(round(int(f[2]) * 1.4)), str(x), str(W - (x + w))
    return (ass.replace(default, default + "\n" + ",".join(f), 1)
            + f"Dialogue: 1,0:00:00.00,9:59:59.99,Title,,0,0,0,,{{\\pos({x + w // 2},{y + h // 2})}}{title}\n")

def finalize(shots: list[Path], audio: Path, ass: Path | None, out: Path, duration: float, progress=None,
             cancel=None) -> Path:
    """Concat the shots under `audio`, cut to `duration`. ass (burnt in) must live in out's dir."""
    out = Path(out)
    work = out.parent
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{Path(p).resolve().as_posix()}'\n" for p in shots), encoding="utf-8")
    if ass:
        render._link_fonts(work)
        video = ["-vf", f"ass={Path(ass).name}:fontsdir=fonts", *render._encode_args()]
    else:
        video = ["-c:v", "copy"]
    tmp = work / (out.stem + ".tmp.mp4")
    proc.run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst.resolve()), "-i", str(Path(audio).resolve()),
                     "-map", "0:v", "-map", "1:a", *video, "-c:a", "aac", "-b:a", "192k", "-t", f"{duration:.3f}",
                     "-movflags", "+faststart", tmp.name], duration=duration, progress=progress, cancel=cancel, cwd=work)
    tmp.replace(out)
    return out
