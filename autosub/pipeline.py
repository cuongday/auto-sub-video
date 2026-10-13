"""Named, cached steps for one job. Each step's hash covers its inputs; unchanged steps are skipped."""
import hashlib
import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
import soundfile as sf
from . import asr as asr_mod, config, media, mix as mix_mod, render, separate as separate_mod, store, translate
from .fit import fit_segment
from .llm import get_llm
from .models import STEPS, Job, Segment, TranslationContext, Word
from .proc import Cancelled
from .segmenter import build_segments
from .subtitles import build_ass, build_srt
from .timing import max_chars, slots
from .tts import get_tts
from .tts.base import file_sha

class NeedsConfirm(Exception):
    """Re-running this step would overwrite subtitles the user edited."""

@dataclass
class Engines:
    separate: Callable = separate_mod.separate
    asr: Callable = asr_mod.get_asr
    llm: Callable = get_llm
    tts: Callable = get_tts

@dataclass
class Ctx:
    job: Job
    dir: Path
    engines: Engines
    progress: Callable[[str, float], None] = lambda step, pct: None
    log: Callable[[str], None] = lambda msg: None
    cancel: threading.Event = field(default_factory=threading.Event)

    def check(self):
        if self.cancel.is_set():
            raise Cancelled()

def _h(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]

def _segments_key(segs: list[Segment], with_text: bool = True) -> list:
    return [(s.id, s.start, s.end, s.vi if with_text else s.source) for s in segs]

def step_hash(ctx: Ctx, step: str) -> str:
    """Hash of a step's inputs, chained on the previous step's hash."""
    j, st = ctx.job, ctx.job.settings
    prev = j.steps[STEPS[STEPS.index(step) - 1]].hash if step != "probe" else None
    if step == "probe":
        p = Path(j.source)
        stat = p.stat() if p.exists() else None
        return _h(str(p), stat.st_size if stat else 0, stat.st_mtime if stat else 0)
    if step in ("extract", "separate"):
        return _h(prev, step)
    if step == "asr":
        return _h(prev, st.lang, st.asr_model)
    if step == "segment":
        return _h(prev)
    if step == "translate":
        return _h(prev, st.llm_provider, st.llm_model, st.translator_notes)
    if step == "tts":
        ref = ctx.dir / st.ref_audio if st.ref_audio else None
        return _h(prev, _segments_key(store.load_segments(j.id)), st.tts_engine, st.tts_voice, st.tts_rate,
                  file_sha(ref) if ref and ref.exists() else "")
    if step == "fit":
        return _h(prev)
    if step == "mix":
        return _h(prev, st.bg_volume_db)
    if step == "render":
        return _h(prev, st.region.model_dump(), st.cover, st.cover_color, st.style.model_dump(),
                  _segments_key(store.load_segments(j.id)))
    raise KeyError(step)

# ---------------------------------------------------------------- steps

def _probe(ctx: Ctx):
    src = Path(ctx.job.source)
    if not src.exists():
        raise RuntimeError(f"Không tìm thấy video: {src}")
    ctx.job.info = media.probe(src)
    frames = ctx.dir / "frames"
    if not (frames / "f0.jpg").exists():
        media.grab_frames(src, frames, ctx.job.info.duration)

def _extract(ctx: Ctx):
    info = ctx.job.info
    if info.has_audio:
        media.extract_audio(ctx.job.source, ctx.dir / "audio.wav", duration=info.duration,
                            progress=lambda p: ctx.progress("extract", p), cancel=ctx.cancel)
    else:
        media.silent_audio(ctx.dir / "audio.wav", info.duration, cancel=ctx.cancel)

def _separate(ctx: Ctx):
    ctx.engines.separate(ctx.dir / "audio.wav", ctx.dir, progress=lambda p: ctx.progress("separate", p),
                         cancel=ctx.cancel)
    media.to_16k_mono(ctx.dir / "vocals.wav", ctx.dir / "vocals16k.wav", cancel=ctx.cancel)

def _asr(ctx: Ctx):
    st = ctx.job.settings
    words = ctx.engines.asr(st.lang, st.asr_model).transcribe(ctx.dir / "vocals16k.wav",
                                                               progress=lambda p: ctx.progress("asr", p))
    ctx.check()
    store.write_json(ctx.dir / "words.json", [w.model_dump() for w in words])
    ctx.log(f"ASR: {len(words)} từ")

def _segment(ctx: Ctx):
    words = [Word.model_validate(w) for w in store.read_json(ctx.dir / "words.json", default=[])]
    segs = build_segments(words, ctx.job.settings.lang)
    store.save_segments(ctx.job.id, segs)
    (ctx.dir / "context.json").unlink(missing_ok=True)      # new transcript -> context is analyzed again
    ctx.job.segments_edited = False
    ctx.log(f"Cắt được {len(segs)} câu")

def _llm(ctx: Ctx):
    st = ctx.job.settings
    return ctx.engines.llm(st.llm_provider, st.llm_model)

def _translate(ctx: Ctx):
    st, jid = ctx.job.settings, ctx.job.id
    segs = store.load_segments(jid)
    if not segs:
        ctx.log("Không nhận dạng được lời thoại nào")
        return
    llm = _llm(ctx)
    ctx_obj = store.load_context(jid)
    if ctx_obj is None:
        ctx_obj = translate.analyze(llm, segs, st.lang, st.translator_notes)
        store.save_context(jid, ctx_obj)
    ctx.progress("translate", 0.1)
    out = translate.translate_all(llm, segs, slots(segs, ctx.job.info.duration), ctx_obj, st.lang,
                                  st.translator_notes, progress=lambda p: ctx.progress("translate", 0.1 + 0.9 * p),
                                  cancel=ctx.cancel)
    store.save_segments(jid, out)
    ctx.job.segments_edited = False

def _tts_dir(ctx: Ctx) -> Path:
    return ctx.dir / "tts"

def _fit_all(ctx: Ctx, segs: list[Segment], only: set[int] | None = None) -> list[Segment]:
    """Synthesize + fit every line with text; returns segments with speed/flags updated."""
    st = ctx.job.settings
    engine = ctx.engines.tts(st.tts_engine)
    ref = ctx.dir / st.ref_audio if st.ref_audio else None
    sl = slots(segs, ctx.job.info.duration)
    todo = [(s, slot) for s, slot in zip(segs, sl) if s.vi.strip() and (only is None or s.id in only)]
    workers = config.EDGE_WORKERS if st.tts_engine == "edge" else max(1, config.VOICE_WORKERS)
    done = [0]
    lock = threading.Lock()

    def one(item):
        s, slot = item
        if ctx.cancel.is_set():
            return s.id, None, "cancelled"
        try:
            r = fit_segment(engine, s, slot, st.tts_voice, st.tts_rate, ref, _tts_dir(ctx) / f"seg_{s.id:04d}.wav",
                            config.CACHE_DIR / "tts")
            res = (s.id, r, None)
        except Exception as e:  # noqa: BLE001
            res = (s.id, None, str(e))
        with lock:
            done[0] += 1
            ctx.progress("tts", done[0] / max(1, len(todo)))
        return res

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, todo))
    ctx.check()
    # second chance, one at a time, for lines that failed under parallel load
    failed = {sid for sid, _, err in results if err}
    if failed:
        ctx.log(f"Đọc lại {len(failed)} câu bị lỗi")
        retry = {sid: one(item) for item in todo if (sid := item[0].id) in failed}
        results = [retry.get(sid, (sid, r, err)) for sid, r, err in results]
    ctx.check()
    by_id = {s.id: s for s in segs}
    for sid, r, err in results:
        s = by_id[sid]
        s.flags = [f for f in s.flags if f not in ("tts_failed", "overflow")]
        if err:
            s.flags.append("tts_failed"); s.speed = None
            ctx.log(f"TTS lỗi câu {sid}: {err}")
        else:
            s.speed = r.speed
            if r.overflow:
                s.flags.append("overflow")
    return segs

def _tts(ctx: Ctx):
    jid = ctx.job.id
    tts_dir = _tts_dir(ctx)
    if tts_dir.exists():
        shutil.rmtree(tts_dir)
    tts_dir.mkdir()
    segs = _fit_all(ctx, store.load_segments(jid))
    if ctx.job.mode == "auto":
        segs = _shorten_overflow(ctx, segs)
    store.save_segments(jid, segs)
    failed = [s.id for s in segs if "tts_failed" in s.flags]
    if failed and ctx.job.mode == "auto":
        # fail this step (not `fit`) so "retry from this step" re-synthesizes; good lines come from the cache
        raise RuntimeError(f"TTS lỗi ở {len(failed)} câu ({', '.join(map(str, failed[:10]))}). Chạy lại bước này "
                           "để đọc lại các câu lỗi.")

def _shorten_overflow(ctx: Ctx, segs: list[Segment]) -> list[Segment]:
    over = [s for s in segs if "overflow" in s.flags]
    if not over:
        return segs
    sl = dict(zip([s.id for s in segs], slots(segs, ctx.job.info.duration)))
    ctx_obj = store.load_context(ctx.job.id) or TranslationContext()
    fixed = translate.shorten(_llm(ctx), [(s, max(4, round(max_chars(sl[s.id]) / 1.1))) for s in over], ctx_obj,
                              ctx.job.settings.lang)
    for s in over:
        if s.id in fixed:
            s.vi = fixed[s.id]
    ctx.log(f"Rút gọn {len(fixed)}/{len(over)} câu đọc không kịp")
    return _fit_all(ctx, segs, only=set(fixed)) if fixed else segs

def _fit(ctx: Ctx):
    segs = store.load_segments(ctx.job.id)
    failed = [s.id for s in segs if "tts_failed" in s.flags]
    if failed:
        raise RuntimeError(f"TTS lỗi ở {len(failed)} câu ({', '.join(map(str, failed[:10]))}). Sửa câu hoặc chạy lại.")
    items = [(s.start, _tts_dir(ctx) / f"seg_{s.id:04d}.wav") for s in segs
             if s.vi.strip() and (_tts_dir(ctx) / f"seg_{s.id:04d}.wav").exists()]
    track = mix_mod.build_voice_track(items, ctx.job.info.duration)
    sf.write(ctx.dir / "voice_raw.wav", track, mix_mod.SR, subtype="PCM_16")
    over = sum("overflow" in s.flags for s in segs)
    ctx.job.warnings = [f"{over} câu đọc không kịp dù đã tăng tốc ×1.35"] if over else []

def _mix(ctx: Ctx):
    mix_mod.mix(ctx.dir / "voice_raw.wav", ctx.dir / "no_vocals.wav", ctx.dir / "voice.wav", ctx.dir / "mix.m4a",
                ctx.job.settings.bg_volume_db, ctx.job.info.duration, cancel=ctx.cancel)

def _render(ctx: Ctx):
    j, info = ctx.job, ctx.job.info
    segs = store.load_segments(j.id)
    (ctx.dir / "subs.ass").write_text(build_ass(segs, info.width, info.height, j.settings.region, j.settings.style),
                                      encoding="utf-8")
    (ctx.dir / "subs.srt").write_text(build_srt(segs), encoding="utf-8")
    render.render_video(j.source, ctx.dir / "mix.m4a", ctx.dir / "subs.ass", ctx.dir / "output.mp4", info, j.settings,
                        progress=lambda p: ctx.progress("render", p), cancel=ctx.cancel)

RUNNERS = {"probe": _probe, "extract": _extract, "separate": _separate, "asr": _asr, "segment": _segment,
           "translate": _translate, "tts": _tts, "fit": _fit, "mix": _mix, "render": _render}
OUTPUTS = {"probe": ["frames/f0.jpg"], "extract": ["audio.wav"], "separate": ["vocals16k.wav", "no_vocals.wav"],
           "asr": ["words.json"], "segment": ["segments.json"], "translate": ["segments.json"], "tts": ["tts"],
           "fit": ["voice_raw.wav"], "mix": ["mix.m4a"], "render": ["output.mp4"]}
REVIEW_STOP = "translate"
OVERWRITES_SEGMENTS = {"segment", "translate"}

# ---------------------------------------------------------------- driver

def _fresh(ctx: Ctx, step: str, h: str) -> bool:
    s = ctx.job.steps[step]
    return s.status == "done" and s.hash == h and all((ctx.dir / o).exists() for o in OUTPUTS[step])

def invalidate_from(job: Job, step: str) -> None:
    for s in STEPS[STEPS.index(step):]:
        job.steps[s].status = "pending"; job.steps[s].hash = None

def run(jid: str, mode: str = "review", from_step: str | None = None, confirm: bool = False,
        engines: Engines | None = None, progress=None, log=None, cancel: threading.Event | None = None) -> Job:
    """Run the job's steps in order, skipping fresh ones. mode=review stops after translation
    (unless the job is already past review: from_step at or after tts)."""
    job = store.load(jid)
    ctx = Ctx(job=job, dir=store.job_dir(jid), engines=engines or Engines(), cancel=cancel or threading.Event())
    logf = ctx.dir / "log.txt"

    def _log(msg: str):
        with logf.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        if log:
            log(msg)

    ctx.log = _log
    ctx.progress = lambda step, pct: progress and progress(step, pct)
    job.mode = mode
    job.error = None
    if from_step:
        invalidate_from(job, from_step)
    start_idx = STEPS.index(from_step) if from_step else 0
    stop_at_review = mode == "review" and start_idx <= STEPS.index(REVIEW_STOP)

    for step in STEPS:
        if ctx.cancel.is_set():
            job.state, job.current_step = "cancelled", None
            store.save(job); _log("Đã huỷ")
            raise Cancelled()
        h = step_hash(ctx, step)
        if _fresh(ctx, step, h):
            continue
        if step in OVERWRITES_SEGMENTS and job.segments_edited and not confirm:
            raise NeedsConfirm(f"Chạy lại bước {step} sẽ ghi đè phụ đề đã sửa")
        if step in OVERWRITES_SEGMENTS:
            invalidate_from(job, step)
        st = job.steps[step]
        st.status, st.error, st.hash = "running", None, None
        job.state, job.current_step = "running", step
        store.save(job)
        _log(f"Bắt đầu bước {step}")
        ctx.progress(step, 0.0)
        t0 = time.time()
        try:
            RUNNERS[step](ctx)
            ctx.check()
        except Cancelled:
            st.status = "pending"; job.state = "cancelled"; job.current_step = None
            store.save(job); _log("Đã huỷ")
            raise
        except Exception as e:
            st.status, st.error = "error", str(e)
            job.state, job.error, job.current_step = "error", f"Bước {step}: {e}", None
            store.save(job); _log(f"Lỗi bước {step}: {e}")
            raise
        st.status, st.seconds = "done", round(time.time() - t0, 1)
        st.hash = step_hash(ctx, step)
        # later steps' inputs may have changed (e.g. tts rewrites segments): recompute lazily via their hashes
        ctx.progress(step, 1.0)
        store.save(job)
        _log(f"Xong bước {step} ({st.seconds}s)")
        if step == REVIEW_STOP and stop_at_review:
            job.state, job.current_step = "awaiting_review", None
            store.save(job)
            return job
        if step == "tts" and mode == "review" and any("tts_failed" in s.flags for s in store.load_segments(jid)):
            job.state, job.current_step = "awaiting_review", None
            job.warnings = ["Một số câu đọc TTS bị lỗi, sửa rồi bấm Render lại"]
            store.save(job)
            return job
    job.state, job.current_step = "done", None
    store.save(job)
    return job

def preview_tts(jid: str, sid: int, engines: Engines | None = None) -> Path:
    """Fitted voice for one line (uses the shared TTS cache)."""
    job = store.load(jid)
    ctx = Ctx(job=job, dir=store.job_dir(jid), engines=engines or Engines())
    segs = store.load_segments(jid)
    idx = next(i for i, s in enumerate(segs) if s.id == sid)
    slot = slots(segs, job.info.duration)[idx]
    st = job.settings
    out = ctx.dir / "preview" / f"seg_{sid}.wav"
    ref = ctx.dir / st.ref_audio if st.ref_audio else None
    r = fit_segment(ctx.engines.tts(st.tts_engine), segs[idx], slot, st.tts_voice, st.tts_rate, ref, out,
                    config.CACHE_DIR / "tts")
    return r.path
