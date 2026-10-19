"""Propose where to cut a film into review parts: in a silence, preferably at the end of a story event."""
import math
from ..models import ChunkSummary, Segment

MIN_GAP, MIN_PART, EVENT_NEAR, EVENT_BONUS = 1.5, 60.0, 5.0, 3.0

def propose_cuts(lines: list[Segment], duration: float, *, parts: int | None = None, minutes: float | None = None,
                 chunks: list[ChunkSummary] = ()) -> list[float]:
    n = parts or (math.ceil(duration / (minutes * 60)) if minutes else max(1, round(duration / 2700)))
    ends = [e.end for c in chunks for e in c.events]
    ls = sorted(lines, key=lambda s: s.start)
    cands: list[tuple[float, float]] = []          # (time, score)
    for a, b in zip(ls, ls[1:]):
        gap = b.start - a.end
        if gap >= MIN_GAP:
            mid = (a.end + b.start) / 2
            cands.append((mid, gap + (EVENT_BONUS if any(abs(mid - e) <= EVENT_NEAR for e in ends) else 0)))
    size, cuts = duration / n, []
    for k in range(1, n):
        target, prev = k * size, cuts[-1] if cuts else 0.0
        lo, hi = prev + MIN_PART, duration - MIN_PART * (n - k)
        ok = [c for c in cands if lo <= c[0] <= hi]
        near = [c for c in ok if abs(c[0] - target) <= 0.1 * size]
        if near:
            cut = max(near, key=lambda c: c[1])[0]
        elif ok:
            cut = min(ok, key=lambda c: abs(c[0] - target))[0]
        else:
            cut = target
        cuts.append(cut)
    return cuts
