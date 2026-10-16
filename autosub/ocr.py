"""Read burnt-in subtitles inside the chosen region (RapidOCR, PP-OCR models on ONNX Runtime, CPU).

Frames are sampled every STEP seconds; consecutive frames showing the same text (allowing small OCR
slips) become one subtitle line whose start/end are the first/last frame it was seen on."""
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
import numpy as np
from . import proc
from .models import Region, Segment

STEP = 0.5            # seconds between sampled frames
MIN_SCORE = 0.75      # recognition confidence to accept a text box
MIN_FRAMES = 2        # a line must be seen on this many consecutive samples (drops flicker)

@dataclass
class Reading:
    t: float
    text: str
    score: float = 1.0

def similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.75

def merge_readings(readings: list[Reading], step: float = STEP, min_frames: int = MIN_FRAMES) -> list[Segment]:
    runs: list[list[Reading]] = []
    for rd in readings:
        text = rd.text.strip() if rd.score >= MIN_SCORE else ""
        if text and runs and runs[-1] and similar(runs[-1][-1].text, text) and rd.t - runs[-1][-1].t <= step * 1.5:
            runs[-1].append(Reading(rd.t, text, rd.score))
        elif text:
            runs.append([Reading(rd.t, text, rd.score)])
        else:
            runs.append([])
    segs: list[Segment] = []
    for run in runs:
        if len(run) < min_frames:
            continue
        best = max(set(x.text for x in run), key=lambda s: sum(x.text == s for x in run))   # most frequent reading
        segs.append(Segment(id=len(segs) + 1, start=round(run[0].t, 3), end=round(run[-1].t + step, 3), source=best))
    return segs

def _frames(video: Path, region: Region, width: int, height: int, duration: float, step: float, cancel=None):
    """Yield (t, crop as HxWx3 uint8) for the region every `step` s, via one ffmpeg pipe."""
    import subprocess
    x, y = int(region.x * width) // 2 * 2, int(region.y * height) // 2 * 2
    w, h = max(16, int(region.w * width) // 2 * 2), max(16, int(region.h * height) // 2 * 2)
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(video), "-vf", f"fps=1/{step},crop={w}:{h}:{x}:{y}",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    proc._LIVE.add(p)
    try:
        n, size = 0, w * h * 3
        while True:
            if cancel is not None and cancel.is_set():
                raise proc.Cancelled()
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            yield n * step, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            n += 1
    finally:
        p.kill(); p.wait(); proc._LIVE.discard(p)

_ENGINE: list = []

def _engine():
    if not _ENGINE:
        from rapidocr import RapidOCR
        # the user already marked where the subtitle is, so text detection is skipped: recognition alone on
        # the region crop is ~130x faster (15 ms vs 2 s per frame, measured 2026-10-16) and reads the same text
        _ENGINE.append(RapidOCR(params={"Global.log_level": "error", "Global.use_det": False, "Global.use_cls": False}))
    return _ENGINE[0]

def _read(eng, crop: np.ndarray) -> str:
    """Recognize the text in a subtitle crop: the region may hold 1-2 lines, so split on blank rows."""
    lines = []
    for band in _text_bands(crop):
        r = eng(band, use_det=False, use_cls=False)
        txt = "".join(r.txts or ()).strip()
        score = float(np.mean(r.scores)) if r.scores else 0.0
        if txt and score >= MIN_SCORE:
            lines.append(txt)
    return "".join(lines)

def _text_bands(crop: np.ndarray, min_h: int = 12) -> list[np.ndarray]:
    """Horizontal bands of the crop that contain text-like edges (one per subtitle line)."""
    gray = crop.mean(axis=2)
    edges = np.abs(np.diff(gray, axis=1)).mean(axis=1)            # per-row horizontal contrast
    thr = max(6.0, float(np.percentile(edges, 60)) * 1.4)
    rows = edges > thr
    bands, start = [], None
    for i, on in enumerate(list(rows) + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if i - start >= min_h:
                pad = max(2, (i - start) // 6)
                bands.append(crop[max(0, start - pad):min(len(crop), i + pad)])
            start = None
    return bands or [crop]

def read_subtitles(video: Path, region: Region, width: int, height: int, duration: float,
                   step: float = STEP, progress=None, cancel=None) -> list[Segment]:
    eng = _engine()
    readings, last, last_txt = [], None, ""
    total = max(1, int(duration / step))
    for i, (t, crop) in enumerate(_frames(video, region, width, height, duration, step, cancel)):
        small = crop[::4, ::4].astype(np.int16)
        if last is not None and np.abs(small - last).mean() < 2.0:
            readings.append(Reading(t, last_txt))            # frame unchanged: reuse the previous reading
        else:
            last_txt = _read(eng, crop)
            readings.append(Reading(t, last_txt))
        last = small
        if progress and i % 10 == 0:
            progress(min(1.0, i / total))
    return merge_readings(readings, step)

def available() -> bool:
    import importlib.util
    return importlib.util.find_spec("rapidocr") is not None
