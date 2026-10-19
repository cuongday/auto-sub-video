"""Film shots for a review video: real scene cuts (ffmpeg `scene` score) and a deterministic plan that fills each
script block's narration with 2-6 s straight-cut shots of the film (no slow motion)."""
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from .. import proc

MIN_SHOT, MAX_SHOT, MIN_LAST = 2.0, 6.0, 1.0
SAME = 0.05                                  # starts closer than this count as the same shot
_PTS = re.compile(r"pts_time:\s*(-?[\d.]+)")

@dataclass(frozen=True)
class BlockNeed:
    id: int
    duration: float                          # narration seconds to cover
    scenes: list[tuple[float, float]]
    source: tuple[float, float] | None

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

def _plan_block(b: BlockNeed, part: tuple[float, float], cuts: list[float]) -> list[Shot]:
    p0, p1 = part
    if b.duration <= 0:
        return []
    if p1 - p0 < MIN_SHOT:
        raise RuntimeError("Phần phim quá ngắn để cắt cảnh")
    shots: list[list[float]] = []
    total = lambda: sum(e - s for s, e in shots)  # noqa: E731
    need = b.duration - 1e-6                     # float noise never adds a shot
    same = lambda x, y: abs(x[0] - y[0]) < SAME  # noqa: E731

    # 1. the block's scenes in order, snapped to a real cut within 1 s
    for a, e in b.scenes:
        a = min(max(a, p0), p1 - MIN_SHOT)
        near = [c for c in cuts if abs(c - a) <= 1]
        s = min(max(min(near, key=lambda c: abs(c - a)) if near else a, p0), p1 - MIN_SHOT)
        sh = [s, min(p1, s + max(MIN_SHOT, min(MAX_SHOT, e - s)))]
        if any(same(sh, o) for o in shots):          # clustered scenes: same start or snapped to the same cut
            continue
        inside = next((o for o in shots if o[0] < s < o[1]), None)
        if inside and s - inside[0] < MIN_SHOT:      # starts inside an earlier shot too early to trim it
            continue
        if inside:
            inside[1] = s
        shots.append(sh)
    # 2. widen each up to MAX_SHOT, never into another shot of the block
    for sh in shots:
        if total() >= need:
            break
        room = min([sh[0] + MAX_SHOT, p1] + [o[0] for o in shots if o is not sh and o[0] >= sh[0]])
        sh[1] = max(sh[1], min(room, sh[1] + b.duration - total()))
    # 3. new shots at unused cuts: inside the source range first (in order), then nearest to it
    ref = b.source or ((shots[0][0],) * 2 if shots else (p0, p0))

    def add_from(starts: list[float]):
        for c in sorted(starts, key=lambda c: (max(ref[0] - c, 0, c - ref[1]), c)):
            if total() >= need:
                return
            if any(s <= c < e for s, e in shots):
                continue
            end = min([c + MAX_SHOT, p1] + [x for x in starts if x >= c + MIN_SHOT] + [s for s, _ in shots if s > c])
            if end - c >= MIN_SHOT:
                shots.append([c, end])

    add_from([c for c in cuts if p0 <= c < p1])
    # cuts used up: unused footage between the shots, in MAX_SHOT steps (films with few detected cuts)
    grid, t = [], p0
    for s, e in sorted(shots) + [[p1, p1]]:
        x = t
        while x <= s - MIN_SHOT:
            grid.append(x)
            x += MAX_SHOT
        t = max(t, e)
    add_from(grid)
    # 4. the part has no unused footage left: reuse shots, never the same one twice in a row
    if len(shots) == 1:                      # one shot fills the part: alternate it with another framing of the part
        alts = [[p0, min(p1, p0 + MAX_SHOT)], [max(p0, p1 - MAX_SHOT), p1], [p1 - MIN_SHOT, p1]]
        shots.append(next((a for a in alts if not same(a, shots[0])), alts[0]))
    pool, i = list(shots), 0
    # ponytail: a part under MIN_SHOT + SAME has no second framing and repeats back to back (parts are >= 60 s)
    alternate = any(not same(x, pool[0]) for x in pool)
    while total() < need:
        sh = pool[i % len(pool)]
        i += 1
        if alternate and same(sh, shots[-1]):
            continue
        shots.append(list(sh))
    # 5. cut the last shot to the exact duration; a too-short last shot borrows from the one before
    # (a block shorter than MIN_LAST gets one shot of its own length: accepted)
    out, acc = [], 0.0
    for s, e in shots:
        if acc + e - s >= need:
            out.append([s, s + b.duration - acc])
            break
        out.append([s, e])
        acc += e - s
    if len(out) > 1 and (d := MIN_LAST - (out[-1][1] - out[-1][0])) > 0:
        prev, last = out[-2], out[-1]
        if prev[1] - prev[0] - d >= MIN_SHOT:
            prev[1] -= d
            last[1] += d
            if last[1] > p1:
                last[0], last[1] = last[0] - (last[1] - p1), p1
        else:                                # prev is under MIN_SHOT + MIN_LAST: it absorbs the last shot
            n = prev[1] - prev[0] + last[1] - last[0]
            start = min(prev[0], p1 - n)
            if start >= p0:                  # else the part is too short to merge: keep the short last shot
                out.pop()
                prev[0], prev[1] = start, start + n
    return [Shot(b.id, s, e) for s, e in out]

def plan_shots(blocks: list[BlockNeed], part: tuple[float, float], cuts: list[float]) -> list[Shot]:
    """Shots covering each block's narration, in block order. Pure: same input, same plan."""
    return [sh for b in blocks for sh in _plan_block(b, part, sorted(cuts))]
