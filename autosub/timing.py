"""How much time each subtitle line may use for its voice-over."""
import numpy as np
from .models import Segment

MAX_SPEED = 1.35     # fastest speed-up applied to a TTS line
CPS = 15             # Vietnamese characters per second at normal speaking rate
GAP = 0.05           # silence kept before the next line starts
MIN_SLOT = 0.3

def slots(segs: list[Segment], duration: float) -> list[float]:
    """Line i may speak from its start until just before line i+1 starts (it borrows the pause after it)."""
    out = []
    for i, s in enumerate(segs):
        if i + 1 < len(segs):
            slot = segs[i + 1].start - s.start - GAP
        else:
            slot = min(s.end + 1.0, duration) - s.start
        out.append(round(max(MIN_SLOT, slot), 3))
    return out

def max_chars(slot: float) -> int:
    return max(4, round(slot * CPS))

def trim_silence(pcm: np.ndarray, sr: int, thresh_db: float = -40.0, pad: float = 0.03) -> np.ndarray:
    """Cut leading/trailing samples quieter than thresh_db (keeping `pad` seconds)."""
    if len(pcm) == 0:
        return pcm
    thresh = 10 ** (thresh_db / 20)
    loud = np.flatnonzero(np.abs(pcm) > thresh)
    if len(loud) == 0:
        return pcm[:0]
    p = int(pad * sr)
    return pcm[max(0, loud[0] - p): min(len(pcm), loud[-1] + 1 + p)]
