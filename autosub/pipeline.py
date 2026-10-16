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
from .workdir import WorkDir, pinned
from .fit import fit_segment
from .llm import get_llm
from .models import STEPS, Job, Segment, TranslationContext, Word
from .proc import Cancelled
from .segmenter import build_segments
from .speakers import voice_for
from .subtitles import build_ass, build_srt
from .timing import max_chars, slots
from .tts import get_tts

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
    work: WorkDir
    engines: Engines
    progress: Callable[[str, float], None] = lambda step, pct: None
    log: Callable[[str], None] = lambda msg: None
    cancel: threading.Event = field(default_factory=threading.Event)

    @property
    def dir(self) -> Path:
        return self.work.path

    def check(self):
        if self.cancel.is_set():
            raise Cancelled()

    def source(self) -> Path:
        p = self.work.fetch(self.job.source)
        if p is None:
            raise RuntimeError("Không tìm thấy video gốc trong kho lưu trữ")
        return p

    def ref_audio(self) -> Path | None:
        st = self.job.settings
        return self.work.fetch(st.ref_audio) if st.ref_audio else None

def _h(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]

def _segments_key(segs: list[Segment], with_text: bool = True) -> list:
    return [(s.id, s.start, s.end, s.vi if with_text else s.source) for s in segs]

def step_hash(ctx: Ctx, step: str) -> str:
    """Hash of a step's inputs, chained on the previous step's hash."""
    j, st = ctx.job, ctx.job.settings
    prev = j.steps[STEPS[STEPS.index(step) - 1]].hash if step != "probe" else None
    if step == "probe":
        info = ctx.work.store.stat(ctx.work.key(j.source))
        return _h(j.source, info.etag if info else "")
    if step == "extract":
        return _h(prev, step)
    if step == "separate":
        return _h(prev, step, st.separate)
    if step == "asr":
        return _h(prev, st.lang, st.asr_model, st.diarize and st.lang == "zh")
    if step == "segment":
        return _h(prev)
    if step == "translate":
        return _h(prev, st.llm_provider, st.llm_model, st.translator_notes)
    if step == "tts":
        ref = ctx.work.store.stat(ctx.work.key(st.ref_audio)) if st.ref_audio else None
        segs = store.load_segments(j.id)
        return _h(prev, _segments_key(segs), [s.speaker for s in segs], st.tts_engine, st.tts_voice,
                  sorted(st.speaker_voices.items()), st.tts_rate, ref.etag if ref else "")
    if step == "fit":
        return _h(prev)
    if step == "mix":
        return _h(prev, st.bg_volume_db, st.separate, st.duck_db if not st.separate else None)
    if step == "render":
        return _h(prev, st.region.model_dump(), [r.model_dump() for r in st.extra_regions], st.cover, st.cover_color,
                  st.style.model_dump(),
                  _segments_key(store.load_segments(j.id)))
    raise KeyError(step)

# ---------------------------------------------------------------- steps

def _probe(ctx: Ctx):
    src = ctx.source()
    ctx.job.info = media.probe(src)
    if not store.exists(ctx.job.id, "frames/f0.jpg"):
        media.grab_frames(src, ctx.dir / "frames", ctx.job.info.duration)
        ctx.work.push("frames")

def _extract(ctx: Ctx):
    info = ctx.job.info
    if info.has_audio:
        media.extract_audio(ctx.source(), ctx.dir / "audio.wav", duration=info.duration,
                            progress=lambda p: ctx.progress("extract", p), cancel=ctx.cancel)
    else:
        media.silent_audio(ctx.dir / "audio.wav", info.duration, cancel=ctx.cancel)

def _separate(ctx: Ctx):
    if not ctx.job.settings.separate:
        # no Demucs: ASR listens to the original audio, the mix ducks it under the narration
        media.to_16k_mono(ctx.dir / "audio.wav", ctx.dir / "vocals16k.wav", cancel=ctx.cancel)
        ctx.log("Bỏ qua tách giọng: dùng âm thanh gốc làm nền, hạ nhỏ khi có thuyết minh")
        return
    ctx.engines.separate(ctx.dir / "audio.wav", ctx.dir, progress=lambda p: ctx.progress("separate", p),
                         cancel=ctx.cancel)
    media.to_16k_mono(ctx.dir / "vocals.wav", ctx.dir / "vocals16k.wav", cancel=ctx.cancel)

def _asr(ctx: Ctx):
    st = ctx.job.settings
    asr = ctx.engines.asr(st.lang, st.asr_model, diarize=True) if st.diarize and st.lang == "zh" \
        else ctx.engines.asr(st.lang, st.asr_model)
    words = asr.transcribe(ctx.dir / "vocals16k.wav",
                                                               progress=lambda p: ctx.progress("asr", p))
    ctx.check()
    store.save_json(ctx.job.id, "words.json", [w.model_dump() for w in words])
    ctx.log(f"ASR: {len(words)} từ")

def _segment(ctx: Ctx):
    words = [Word.model_validate(w) for w in store.load_json(ctx.job.id, "words.json", default=[])]
    from .speakers import assign_speakers, speakers_of
    segs = assign_speakers(build_segments(words, ctx.job.settings.lang), words)
    segs = _flag_lyrics(ctx, segs)
    if speakers_of(segs):
        ctx.log(f"Nhận ra {len(speakers_of(segs))} người nói")
    store.save_segments(ctx.job.id, segs)
    store.delete_context(ctx.job.id)      # new transcript -> context is analyzed again
    ctx.job.segments_edited = False
    ctx.log(f"Cắt được {len(segs)} câu")

def _flag_lyrics(ctx: Ctx, segs: list[Segment]) -> list[Segment]:
    """Mark lines that look like song lyrics picked up from the background music."""
    from . import lyrics
    if not ctx.job.settings.separate:
        return segs
    voice, music = ctx.work.fetch("vocals.wav"), ctx.work.fetch("no_vocals.wav")
    if not segs or voice is None or music is None:
        return segs
    v, sr = sf.read(voice, dtype="float32", always_2d=True)
    m, _ = sf.read(music, dtype="float32", always_2d=True)
    segs = lyrics.flag_lyrics(segs, lyrics.levels(v.mean(axis=1), m.mean(axis=1), sr, segs), ctx.job.settings.lang)
    n = sum(lyrics.FLAG in s.flags for s in segs)
    if n:
        ctx.log(f"{n} câu có thể là lời bài hát trong nhạc nền (đánh dấu để rà soát)")
    return segs

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
    ref = ctx.ref_audio()
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
            r = fit_segment(engine, s, slot, voice_for(st, s), st.tts_rate, ref, _tts_dir(ctx) / f"seg_{s.id:04d}.wav")
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
    ctx.work.push("tts")
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
    tts_dir = ctx.work.fetch_dir("tts")
    items = [(s.start, tts_dir / f"seg_{s.id:04d}.wav") for s in segs
             if s.vi.strip() and (tts_dir / f"seg_{s.id:04d}.wav").exists()]
    track = mix_mod.build_voice_track(items, ctx.job.info.duration)
    sf.write(ctx.dir / "voice_raw.wav", track, mix_mod.SR, subtype="PCM_16")
    over = sum("overflow" in s.flags for s in segs)
    ctx.job.warnings = [f"{over} câu đọc không kịp dù đã tăng tốc ×1.35"] if over else []

def _mix(ctx: Ctx):
    st = ctx.job.settings
    bg = ctx.dir / ("no_vocals.wav" if st.separate else "audio.wav")
    mix_mod.mix(ctx.dir / "voice_raw.wav", bg, ctx.dir / "voice.wav", ctx.dir / "mix.m4a", st.bg_volume_db,
                ctx.job.info.duration, cancel=ctx.cancel, duck_db=None if st.separate else st.duck_db)

def _render(ctx: Ctx):
    j, info = ctx.job, ctx.job.info
    segs = store.load_segments(j.id)
    (ctx.dir / "subs.ass").write_text(build_ass(segs, info.width, info.height, j.settings.region, j.settings.style),
                                      encoding="utf-8")
    (ctx.dir / "subs.srt").write_text(build_srt(segs), encoding="utf-8")
    render.render_video(ctx.source(), ctx.dir / "mix.m4a", ctx.dir / "subs.ass", ctx.dir / "output.mp4", info, j.settings,
                        progress=lambda p: ctx.progress("render", p), cancel=ctx.cancel)

RUNNERS = {"probe": _probe, "extract": _extract, "separate": _separate, "asr": _asr, "segment": _segment,
           "translate": _translate, "tts": _tts, "fit": _fit, "mix": _mix, "render": _render}
# files a step reads from earlier steps (fetched into the scratch dir first) and the files it produces
# (pushed to storage before the step counts as done; JSON documents are written to storage directly)
INPUTS = {"separate": ["audio.wav"], "asr": ["vocals16k.wav"], "fit": [], "mix": ["voice_raw.wav", "no_vocals.wav"],
          "render": ["mix.m4a"]}
PUSH = {"extract": ["audio.wav"], "separate": ["vocals.wav", "no_vocals.wav", "vocals16k.wav"],
        "fit": ["voice_raw.wav"], "mix": ["voice.wav", "mix.m4a"], "render": ["subs.ass", "subs.srt", "output.mp4"]}
OUTPUTS = {"probe": ["frames/f0.jpg"], "extract": ["audio.wav"], "separate": ["vocals16k.wav", "no_vocals.wav"],
           "asr": ["words.json"], "segment": ["segments.json"], "translate": ["segments.json"], "tts": ["tts/"],
           "fit": ["voice_raw.wav"], "mix": ["mix.m4a"], "render": ["output.mp4"]}
REVIEW_STOP = "translate"
OVERWRITES_SEGMENTS = {"segment", "translate"}

# ---------------------------------------------------------------- driver

def _fresh(ctx: Ctx, step: str, h: str, present: set[str] | None = None) -> bool:
    s = ctx.job.steps[step]
    if not (s.status == "done" and s.hash == h):
        return False
    present = store.names(ctx.job.id) if present is None else present
    # a pruned output does not make its step stale: later steps rebuild it on demand
    ok = lambda o: (any(n.startswith(o) for n in present) if o.endswith("/") else o in present) or o in ctx.job.pruned  # noqa: E731
    return all(ok(o) for o in _outputs(ctx, step))

def _rebuild(ctx: Ctx, name: str) -> bool:
    """Regenerate a pruned intermediate from what is kept (cheap: no Demucs, no TTS)."""
    if name == "audio.wav":
        _extract(ctx); ctx.work.push("audio.wav")
    elif name == "voice_raw.wav":
        _fit(ctx); ctx.work.push("voice_raw.wav")
    else:
        return False
    if name in ctx.job.pruned:
        ctx.job.pruned.remove(name)
    ctx.log(f"Tạo lại {name} (đã dọn trước đó)")
    return True

def _inputs(ctx: Ctx, step: str) -> list[str]:
    if step == "mix" and not ctx.job.settings.separate:
        return ["voice_raw.wav", "audio.wav"]
    return INPUTS.get(step, [])

def _pushes(ctx: Ctx, step: str) -> list[str]:
    if step == "separate" and not ctx.job.settings.separate:
        return ["vocals16k.wav"]
    return PUSH.get(step, [])

def _outputs(ctx: Ctx, step: str) -> list[str]:
    if step == "separate" and not ctx.job.settings.separate:
        return ["vocals16k.wav"]
    return OUTPUTS[step]

def _run_step(ctx: Ctx, step: str) -> None:
    for name in _inputs(ctx, step):
        if ctx.work.fetch(name) is None and not (_rebuild(ctx, name) and ctx.work.fetch(name) is not None):
            raise RuntimeError(f"Thiếu file {name} của bước trước, hãy chạy lại từ đầu")
    RUNNERS[step](ctx)
    ctx.check()
    for name in _pushes(ctx, step):
        ctx.work.push(name)
        if name in ctx.job.pruned:
            ctx.job.pruned.remove(name)

def make_ctx(job: Job, engines: Engines | None = None) -> Ctx:
    return Ctx(job=job, work=WorkDir(job.id), engines=engines or Engines())

def invalidate_from(job: Job, step: str) -> None:
    for s in STEPS[STEPS.index(step):]:
        job.steps[s].status = "pending"; job.steps[s].hash = None

def run(jid: str, mode: str = "review", from_step: str | None = None, confirm: bool = False,
        engines: Engines | None = None, progress=None, log=None, cancel: threading.Event | None = None) -> Job:
    """Run the job's steps in order, skipping fresh ones. mode=review stops after translation
    (unless the job is already past review: from_step at or after tts)."""
    with pinned(jid):
        return _run(jid, mode, from_step, confirm, engines, progress, log, cancel)

def _run(jid, mode, from_step, confirm, engines, progress, log, cancel) -> Job:
    job = store.load(jid)
    ctx = make_ctx(job, engines)
    ctx.cancel = cancel or threading.Event()
    logf = ctx.dir / "log.txt"
    if not logf.exists():
        ctx.work.fetch("log.txt")

    def _log(msg: str):
        with logf.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        if log:
            log(msg)

    def _flush_log():
        try:
            ctx.work.push("log.txt")
        except Exception:  # noqa: BLE001  (never hide the real error behind a log upload failure)
            pass

    ctx.log = _log
    ctx.progress = lambda step, pct: progress and progress(step, pct)
    job.mode = mode
    job.error = None
    if from_step:
        invalidate_from(job, from_step)
    start_idx = STEPS.index(from_step) if from_step else 0
    stop_at_review = mode == "review" and start_idx <= STEPS.index(REVIEW_STOP)

    present = store.names(jid)
    for step in STEPS:
        if ctx.cancel.is_set():
            job.state, job.current_step = "cancelled", None
            store.save(job); _log("Đã huỷ"); _flush_log()
            raise Cancelled()
        h = step_hash(ctx, step)
        if _fresh(ctx, step, h, present):
            continue
        present = set()                    # from here on everything reruns; no need to list again
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
            _run_step(ctx, step)
        except Cancelled:
            st.status = "pending"; job.state = "cancelled"; job.current_step = None
            store.save(job); _log("Đã huỷ"); _flush_log()
            raise
        except Exception as e:
            st.status, st.error = "error", str(e)
            job.state, job.error, job.current_step = "error", f"Bước {step}: {e}", None
            store.save(job); _log(f"Lỗi bước {step}: {e}"); _flush_log()
            raise
        st.status, st.seconds = "done", round(time.time() - t0, 1)
        st.hash = step_hash(ctx, step)
        # later steps' inputs may have changed (e.g. tts rewrites segments): recompute lazily via their hashes
        ctx.progress(step, 1.0)
        store.save(job)
        _log(f"Xong bước {step} ({st.seconds}s)"); _flush_log()
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
    _flush_log()
    if store.load_app_settings().get("auto_prune"):
        from . import prune
        freed = prune.prune(jid)
        if freed:
            _log(f"Đã dọn {freed / (1 << 20):.0f} MB dữ liệu tạm"); _flush_log()
        job = store.load(jid)
    return job

def preview_tts(jid: str, sid: int, engines: Engines | None = None) -> Path:
    """Fitted voice for one line (uses the shared TTS cache)."""
    job = store.load(jid)
    ctx = make_ctx(job, engines)
    segs = store.load_segments(jid)
    idx = next(i for i, s in enumerate(segs) if s.id == sid)
    slot = slots(segs, job.info.duration)[idx]
    st = job.settings
    out = ctx.dir / "preview" / f"seg_{sid}.wav"
    r = fit_segment(ctx.engines.tts(st.tts_engine), segs[idx], slot, voice_for(st, segs[idx]), st.tts_rate,
                    ctx.ref_audio(), out)
    return r.path
