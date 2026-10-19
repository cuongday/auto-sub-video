import re

from ..models import Job, Segment, Word
from ..segmenter import build_segments
from .templates import ad_patterns, edge_keywords

_TS = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})"
_CUE = re.compile(rf"{_TS}\s*-->\s*{_TS}")
_TAG = re.compile(r"<[^>]*>")
EDGE_S = 120
MIN_TAIL_S = 120

def _secs(h, m, s, ms) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

def parse_vtt(text: str) -> list[Segment]:
    out: list[Segment] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        rows = block.strip().split("\n")
        for i, row in enumerate(rows):
            m = _CUE.search(row)
            if not m:
                continue
            g = m.groups()
            body = " ".join(_TAG.sub("", " ".join(rows[i + 1:])).split())
            if body:
                out.append(Segment(id=0, start=_secs(*g[:4]), end=_secs(*g[4:]), source=body))
            break
    out.sort(key=lambda s: s.start)
    for i, s in enumerate(out, 1):
        s.id = i
    return out

def filter_ads(lines: list[Segment], duration: float) -> list[Segment]:
    pats, keys = ad_patterns(), [k.lower() for k in edge_keywords()]
    out = []
    for s in lines:
        if any(p.search(s.source) for p in pats):
            continue
        if (s.start < EDGE_S or s.end > duration - EDGE_S) and any(k in s.source.lower() for k in keys):
            continue
        out.append(s)
    for i, s in enumerate(out, 1):
        s.id = i
    return out

def from_words(words: list[Word], lang: str) -> list[Segment]:
    return build_segments(words, lang)

def chunk(lines: list[Segment], duration: float, min_s: float = 600, max_s: float = 900) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    start = 0.0
    while duration - start > max_s:
        lo, hi = start + min_s, start + max_s
        best, cut = 0.0, hi
        for a, b in zip(lines, lines[1:]):
            mid = (a.end + b.start) / 2
            if lo <= mid <= hi and b.start - a.end > best:
                best, cut = b.start - a.end, mid
        out.append((start, cut))
        start = cut
    if out and duration - start < MIN_TAIL_S:
        out[-1] = (out[-1][0], duration)
    else:
        out.append((start, duration))
    return out

def transcript_lang(job: Job) -> str:
    code = job.film.subtitle if job.film else None
    return {"vie": "vi", "eng": "en"}.get(code) or job.settings.lang
