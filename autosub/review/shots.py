"""Film shots for a review video: real scene cuts (ffmpeg `scene` score) and a deterministic plan that fills each
script block's narration with 2-6 s straight-cut shots of the film (no slow motion)."""
import bisect
import re
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from .. import proc

MIN_SHOT, MAX_SHOT, MIN_LAST = 2.0, 6.0, 1.0
SAME = 0.05                                  # starts closer than this count as the same shot
RANGE = 30.0                                 # a scene this long is a stretch of story, not a moment
_PTS = re.compile(r"pts_time:\s*(-?[\d.]+)")

@dataclass(frozen=True)
class BlockNeed:
    id: int
    duration: float                          # narration seconds to cover
    scenes: list[tuple[float, float]]
    source: tuple[float, float] | None
    weights: list[float] | None = None       # sentence times: one per scene splits the block by them

@dataclass(frozen=True)
class Shot:
    block: int
    start: float                             # source seconds
    end: float

def detect_cuts(src: Path, start: float, end: float, cancel: threading.Event | None = None) -> list[float]:
    """Film seconds of hard scene changes inside [start, end]."""
    cuts: list[float] = []

    def on_line(line: str):
        if "showinfo" in line and (m := _PTS.search(line)):
            cuts.append(round(start + float(m.group(1)), 3))

    proc.run(["ffmpeg", "-hide_banner", "-nostdin", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(src),
              "-vf", "scale=320:-2,select='gt(scene,0.3)',showinfo", "-an", "-f", "null", "-"],
             on_line=on_line, cancel=cancel)
    return sorted(cuts)

def _snap(a: float, cuts: list[float], lo: float, hi: float) -> float:
    """a moved to the nearest real cut within 1 s, kept inside [lo, hi]."""
    i = bisect.bisect_left(cuts, a - 1)
    near = [c for c in cuts[i:i + 64] if abs(c - a) <= 1]
    return min(max(min(near, key=lambda c: abs(c - a)) if near else a, lo), hi)

def _pieces(start: float, length: float, cuts: list[float], lo: float, hi: float) -> list[list[float]]:
    """Footage [start, start + length] cut into 2-6 s shots, at real cuts where they fit; each keeps its region."""
    out, x, end = [], start, start + length
    while end - x > MAX_SHOT:
        i = bisect.bisect_left(cuts, x + MIN_SHOT)
        top = min(x + MAX_SHOT, end - MIN_SHOT)
        y = cuts[i] if i < len(cuts) and cuts[i] <= top else x + min(MAX_SHOT, end - x - MIN_SHOT)
        out.append([x, y, lo, hi])
        x = y
    return out + [[x, end, lo, hi]]

def _lens(b: BlockNeed) -> list[float]:
    """Footage lengths of a block without scenes: its sentence times, short sentences gathered until MIN_SHOT."""
    ws = [max(0.0, w) for w in b.weights or []]
    if sum(ws) <= 0:
        return [e - s for s, e, *_ in _pieces(0, b.duration, [], 0, 0)]
    out: list[float] = []
    for w in ws:
        n = b.duration * w / sum(ws)
        if out and out[-1] < MIN_SHOT:       # the open entry is still too short: it takes this sentence too
            out[-1] += n
        else:
            out.append(n)
    if len(out) > 1 and out[-1] < MIN_SHOT:  # a too-short tail joins the entry before
        tail = out.pop()
        out[-1] += tail
    return out

def _plan_block(b: BlockNeed, part: tuple[float, float], window: tuple[float, float], stretch: tuple[float, float],
                cuts: list[float]) -> list[Shot]:
    p0, p1 = part
    w0, w1 = window
    if b.duration <= 0:
        return []
    if p1 - p0 < MIN_SHOT:
        raise RuntimeError("Phần phim quá ngắn để cắt cảnh")
    need = b.duration - 1e-6                     # float noise never adds a shot
    same = lambda x, y: abs(x[0] - y[0]) < SAME  # noqa: E731

    # 1. scenes in narration order (never re-sorted), snapped to a real cut within 1 s, each with its share of the
    # narration: its sentence's time when there is one sentence per scene, else equal shares. A scene under MIN_SHOT
    # from a kept one, or with under MIN_SHOT to tell, gives its share to the scene before
    ws = [max(0.0, w) for w in b.weights or []]
    if len(ws) != len(b.scenes) or sum(ws) <= 0:
        ws = [1.0] * len(b.scenes)
    kept: list[list[float]] = []             # [start, share, scene end]
    for (a, e), w in zip(b.scenes, ws):
        s = _snap(min(max(a, p0), p1 - MIN_SHOT), cuts, p0, p1 - MIN_SHOT)
        d = b.duration * w / sum(ws)
        if kept and (d < MIN_SHOT - 1e-9 or any(abs(s - k[0]) < MIN_SHOT for k in kept)):
            kept[-1][1] += d
        else:
            kept.append([s, d, min(max(e, p0), p1)])
    if len(kept) > 1 and kept[0][1] < MIN_SHOT - 1e-9:   # a too-short first scene gives its share to the next
        first = kept.pop(0)
        kept[0][1] += first[1]
    # 2. each scene's footage runs forward from it, up to the next scene ahead in film time or the end of the window;
    # what does not fit carries to the next scene, the last one slides back (never into the footage before it)
    runs, carry = [], 0.0                    # [start, length, region lo, region hi]
    for i, (s, d, e) in enumerate(kept):
        lo, hi = min(w0, s), min(p1, max(w1, e, s + MIN_SHOT))
        top = min([hi] + [k[0] for k in kept if k[0] > s])
        todo = d + carry
        if i < len(kept) - 1:
            runs.append([s, min(todo, top - s), lo, hi])
        else:
            lo = max([lo] + [r[0] + r[1] for r in runs if r[0] < s])
            start = max(lo, min(s, top - todo))
            runs.append([start, min(todo, top - start), lo, hi])
        carry = todo - runs[-1][1]
    # 3. no scenes: one run per sentence (2-6 s pieces without sentence times), spread evenly over the stretch
    if not kept:
        a, z = stretch
        if z - a < b.duration - 1e-6:        # stretch shorter than the block: all of it, then reuse
            runs, carry = [[a, z - a, a, z]], b.duration - (z - a)
        else:
            lens = _lens(b)
            gap = (z - a - b.duration) / (len(lens) - 1 or 2)
            t = a if len(lens) > 1 else a + gap
            for n in lens:
                runs.append([_snap(t, cuts, runs[-1][0] + runs[-1][1] if runs else a, z - n), n, a, z])
                t += n + gap
    shots = [sh for r in runs for sh in _pieces(r[0], r[1], cuts, r[2], r[3])]
    # 4. the window has no footage left to tell: reuse shots, never the same one twice in a row
    if carry > 1e-6:
        if len(shots) == 1:                  # one shot fills the window: alternate it with another framing of it
            alts = [[w0, min(w1, w0 + MAX_SHOT)], [max(w0, w1 - MAX_SHOT), w1], [w1 - MIN_SHOT, w1]]
            shots.append(next((x for x in alts if not same(x, shots[0])), alts[0]) + [w0, w1])
        pool, i = list(shots), 0
        # ponytail: a window under MIN_SHOT + SAME has no second framing and repeats back to back (parts are >= 60 s)
        alternate = any(not same(x, pool[0]) for x in pool)
        while sum(e - s for s, e, *_ in shots) < need:
            sh = pool[i % len(pool)]
            i += 1
            if alternate and same(sh, shots[-1]):
                continue
            shots.append(list(sh))
    # 5. cut the last shot to the exact duration; a too-short last shot borrows from the one before
    # (a block shorter than MIN_LAST gets one shot of its own length: accepted)
    out, acc = [], 0.0
    for s, e, lo, hi in shots:
        if acc + e - s >= need:
            out.append([s, s + b.duration - acc, lo, hi])
            break
        out.append([s, e, lo, hi])
        acc += e - s
    if len(out) > 1 and (d := MIN_LAST - (out[-1][1] - out[-1][0])) > 0:
        prev, last = out[-2], out[-1]
        if prev[1] - prev[0] - d >= MIN_SHOT:
            prev[1] -= d
            last[1] += d
            if last[1] > last[3]:
                last[0], last[1] = last[0] - (last[1] - last[3]), last[3]
        else:                                # prev is under MIN_SHOT + MIN_LAST: it absorbs the last shot
            n = prev[1] - prev[0] + last[1] - last[0]
            start = min(prev[0], prev[3] - n)
            if start >= min(prev[2], w0):    # else the window is too short to merge: keep the short last shot
                out.pop()
                prev[0], prev[1] = start, start + n
    return [Shot(b.id, s, e) for s, e, *_ in out]

def _span(b: BlockNeed, part: tuple[float, float]) -> tuple[float, float] | None:
    """The film the block tells: its source range, else its scenes, inside the part."""
    p0, p1 = part
    a, z = b.source or (min((s for s, _ in b.scenes), default=p1), max((e for _, e in b.scenes), default=p0))
    a, z = max(a, p0), min(z, p1)
    return (a, z) if z > a else None

def plan_shots(blocks: list[BlockNeed], part: tuple[float, float], cuts: list[float],
               window: tuple[float, float] | None = None) -> list[Shot]:
    """Shots covering each block's narration, in block order. Scenes keep their times inside the part; all other
    footage comes from the window (the part's dialogue). Pure: same input, same plan."""
    cuts = sorted(cuts)
    w0, w1 = window or part
    w0, w1 = max(w0, part[0]), min(w1, part[1])
    if w1 - w0 < MIN_SHOT:
        w0, w1 = part
    spans = [_span(b, part) for b in blocks]
    out = []
    for i, b in enumerate(blocks):
        prev = next((s for s in reversed(spans[:i]) if s), None)
        nxt = next((s for s in spans[i + 1:] if s), None)
        # the block's stretch of film: scenes that are whole ranges (the script's fallback scene = the source range)
        # are spread over like no scenes; else its source range; else the footage next to the blocks around it
        if b.scenes and all(e - a >= RANGE or (a, e) == b.source for a, e in b.scenes):
            a, z = min(a for a, _ in b.scenes), max(e for _, e in b.scenes)
            b = replace(b, scenes=[])
        elif b.source and spans[i]:
            a, z = spans[i]
        elif prev and nxt and nxt[0] - prev[1] >= b.duration:
            a, z = prev[1], nxt[0]
        elif nxt:                            # the hook: where the next block's footage starts
            a, z = nxt[0], nxt[0] + b.duration
        elif prev:                           # the ending: where the last block's footage ends
            a, z = prev[1] - b.duration, prev[1]
        else:
            a, z = w0, w1
        # inside the window, grown to the block's duration
        a, z = max(a, w0), min(z, w1)
        if z - a < b.duration:
            z = min(w1, max(a, w0) + b.duration)
            a = max(w0, z - b.duration)
        out += _plan_block(b, part, (w0, w1), (a, z), cuts)
    return out
