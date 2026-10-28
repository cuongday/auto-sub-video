"""Place narration clips on a timeline."""
from .script import Line

GAP_SENT = 0.35
GAP_PARA = 0.8
TAIL = 1.0


def sequential(lines: list[Line], durations: list[float]) -> tuple[list[float], float]:
    starts: list[float] = []
    t = 0.0
    for i, (ln, d) in enumerate(zip(lines, durations)):
        if i:
            t += GAP_PARA if ln.para != lines[i - 1].para else GAP_SENT
        starts.append(t)
        t += d
    return starts, t + TAIL


def timed(lines: list[Line], durations: list[float]) -> tuple[list[float], float]:
    starts: list[float] = []
    end = 0.0
    for ln, d in zip(lines, durations):
        s = max(ln.start or 0.0, end)
        starts.append(s)
        end = s + d
    last = max((ln.end or 0.0 for ln in lines), default=0.0)
    return starts, max(end, last) + TAIL
