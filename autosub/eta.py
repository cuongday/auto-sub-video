"""Remaining-time estimate from this machine's own history: seconds of work per second of video,
per job kind and step, averaged over finished jobs (median, so one odd run doesn't skew it)."""
import statistics
from . import pipeline, store
from .models import STEPS_BY_KIND, Job

# fixed cost per step (model loading, process start) that does not scale with video length;
# measured: ASR ~35-45 s on an 8 s clip vs ~70 s on a 3.5-minute video
OVERHEAD = {"separate": 6.0, "asr": 35.0, "translate": 3.0, "tts": 3.0, "render": 1.5}
# fallback seconds-per-video-second, measured on an i5-13400 without GPU (2026-10)
DEFAULT_RATE = {"probe": 0.0, "extract": 0.002, "separate": 0.45, "asr": 0.25, "segment": 0.0,
                "translate": 0.15, "tts": 0.6, "fit": 0.001, "mix": 0.03, "render": 0.25}
DEFAULT_RATE_BY_KIND = {
    "sub": DEFAULT_RATE,
    "film": {"probe": 0, "extract": 0.002, "separate": 0.45, "asr": 0.25, "transcript": 0, "characters": 0.002,
             "summarize": 0.01},
    "review": {"script": 0.01, "scenes": 0.08, "tts": 0.6, "assemble": 0.01, "render": 0.25},
}
_CACHE: dict = {}

def basis_seconds(job, step: str) -> float:
    """Seconds of media a step's time scales with: the video (sub, film), the film part a review covers
    (script, scenes) or the review's target length (later steps). 0 when not known yet."""
    if job.kind != "review":
        return job.info.duration if job.info else 0.0
    if step in ("script", "scenes"):
        part = getattr(job, "part", None)
        return part.end - part.start if part else 0.0
    review = getattr(job, "review", None)
    return review.minutes * 60 if review else 0.0

def rates(kind: str = "sub") -> dict[str, float]:
    steps = STEPS_BY_KIND[kind]
    samples: dict[str, list[float]] = {s: [] for s in steps}
    for j in store.list_jobs():
        if j.kind != kind:
            continue
        for s in steps:
            st = j.steps.get(s)
            basis = basis_seconds(j, s)
            if basis <= 1 or st is None:
                continue
            if st.status == "done" and st.seconds is not None and st.seconds >= 0.05:
                if s == "separate" and not j.settings.separate:
                    continue
                samples[s].append(max(0.0, st.seconds - OVERHEAD.get(s, 0.0)) / basis)
    return {s: round(statistics.median(v), 4) for s, v in samples.items() if v}

def estimate(job: Job, current: str | None = None, pct: float = 0.0) -> dict:
    """{'steps': {step: seconds left}, 'total': seconds, 'calibrated': bool} for the steps still to run."""
    learned = rates(job.kind)
    flow = pipeline.flow_for(job)
    steps, stop = flow.steps, flow.review_stop
    last = stop if stop and job.mode == "review" and job.steps[stop].status != "done" else steps[-1]
    out: dict[str, float] = {}
    for s in steps[:steps.index(last) + 1]:
        if job.steps[s].status == "done" and s != current:
            continue
        rate = learned.get(s, DEFAULT_RATE_BY_KIND[job.kind][s])
        if s == "separate" and not job.settings.separate:
            left = 0.0
        else:
            left = (rate * basis_seconds(job, s) + OVERHEAD.get(s, 0.0)) * ((1 - pct) if s == current else 1)
        out[s] = round(left, 1)
    return {"steps": out, "total": round(sum(out.values()), 1), "calibrated": bool(learned)}
