"""Narration of a review script: split blocks into sentences (one TTS call each) and into subtitle lines."""
import re
from ..models import Segment
from .pace import syllables

SENT_GAP = 0.15     # silence between two sentences of a block (seconds)
BLOCK_GAP = 0.35    # silence between two blocks
MAX_SYLLABLES = 30

_END = re.compile(r"(?<=[.!?…])(?=\s)|\n+")

def _split_long(s: str) -> list[str]:
    """Cut a sentence over MAX_SYLLABLES at the comma nearest its middle, recursively."""
    n = syllables(s)
    if n <= MAX_SYLLABLES:
        return [s]
    cuts = [m.end() for m in re.finditer(r",\s", s)]
    if not cuts:
        return [s]
    i = min(cuts, key=lambda c: abs(syllables(s[:c]) - n / 2))
    return _split_long(s[:i].strip()) + _split_long(s[i:].strip())

def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _END.split(text) if p and p.strip()]
    return [q for p in parts for q in _split_long(p)]

def subtitle_lines(text: str, start: float, dur: float, max_chars: int = 48) -> list[Segment]:
    """Greedy word wrap; time shared by character count; lines touch, the last ends at start + dur."""
    lines: list[str] = []
    for w in text.split():
        if lines and len(lines[-1]) + 1 + len(w) <= max_chars:
            lines[-1] += " " + w
        else:
            lines.append(w)
    total = sum(len(l) for l in lines) or 1
    out, t, done = [], start, 0
    for i, l in enumerate(lines):
        done += len(l)
        end = start + dur if i == len(lines) - 1 else start + dur * done / total
        out.append(Segment(id=i, start=t, end=end, source="", vi=l))
        t = end
    return out
