"""Remaining-time estimate from this machine's own history: seconds of work per second of video,
per step, averaged over finished jobs (median, so one odd run doesn't skew it)."""
import statistics
from . import store
from .models import STEPS, Job

# fixed cost per step (model loading, process start) that does not scale with video length;
# measured: ASR ~35-45 s on an 8 s clip vs ~70 s on a 3.5-minute video
OVERHEAD = {"separate": 6.0, "asr": 35.0, "translate": 3.0, "tts": 3.0, "render": 1.5}
# fallback seconds-per-video-second, measured on an i5-13400 without GPU (2026-10)
DEFAULT_RATE = {"probe": 0.0, "extract": 0.002, "separate": 0.45, "asr": 0.25, "segment": 0.0,
                "translate": 0.15, "tts": 0.6, "fit": 0.001, "mix": 0.03, "render": 0.25}
REVIEW_STOP = "translate"
_CACHE: dict = {}

def rates() -> dict[str, float]:
    samples: dict[str, list[float]] = {s: [] for s in STEPS}
    for j in store.list_jobs():
        if not j.info or j.info.duration <= 1:
            continue
        for s in STEPS:
            st = j.steps[s]
            if st.status == "done" and st.seconds is not None and st.seconds >= 0.05:
                if s == "separate" and not j.settings.separate:
                    continue
                samples[s].append(max(0.0, st.seconds - OVERHEAD.get(s, 0.0)) / j.info.duration)
    return {s: round(statistics.median(v), 4) for s, v in samples.items() if v}

def estimate(job: Job, current: str | None = None, pct: float = 0.0) -> dict:
    """{'steps': {step: seconds left}, 'total': seconds, 'calibrated': bool} for the steps still to run."""
    learned = rates()
    dur = job.info.duration if job.info else 0.0
    last = REVIEW_STOP if job.mode == "review" and job.steps[REVIEW_STOP].status != "done" else STEPS[-1]
    out: dict[str, float] = {}
    for s in STEPS[:STEPS.index(last) + 1]:
        if job.steps[s].status == "done" and s != current:
            continue
        rate = learned.get(s, DEFAULT_RATE[s])
        if s == "separate" and not job.settings.separate:
            left = 0.0
        else:
            left = (rate * dur + OVERHEAD.get(s, 0.0)) * ((1 - pct) if s == current else 1)
        out[s] = round(left, 1)
    return {"steps": out, "total": round(sum(out.values()), 1), "calibrated": bool(learned)}
