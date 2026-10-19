"""Flows of the review feature. "film": prepare one movie/episode once (transcript, characters, chunk summaries).
"review": one video reviewing a part of a film (script, scenes, voice, assembly, render)."""
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import soundfile as sf
from .. import config, media, mix, pipeline, projects, store, workdir
from ..storage import get_store
from ..subtitles import _escape, build_srt, region_px
from ..timing import trim_silence
from ..tts.base import cached_synthesize
from ..models import FILM_STEPS, REVIEW_STEPS, ChunkSummary, FilmCharacter, Job, MovieMeta, Script, Segment, Word
from ..pipeline import Ctx, Flow, _h
from . import compose, film, narration, notebook, pace, parts, script, shots, templates, transcript

SR = 44100
NO_LINES ="Không có lời thoại: không viết được kịch bản review"

def _use_subs(job: Job) -> str | None:
    return job.film.subtitle if job.film else None

def _vtt(code: str) -> str:
    return f"subs/{code}.vtt"

def _meta(job: Job) -> MovieMeta:
    p = projects.get(job.project) if job.project else None
    return p.review.movie if p and p.review else MovieMeta(name=job.name)

def _lines(job: Job) -> list[Segment]:
    return [Segment.model_validate(s) for s in store.load_json(job.id, "transcript.json", default=[])]

def _known(job: Job) -> list[FilmCharacter]:
    """Notebook characters, then those found in earlier episodes of the project (notebook wins on a name)."""
    p = projects.get(job.project) if job.project else None
    if not p:
        return []
    out = {c.name: FilmCharacter.model_validate(c.model_dump()) for c in (p.review.notebook.characters if p.review else [])}
    idx = job.film.episode_index if job.film else 0
    eps = sorted((j for j in store.list_jobs() if j.kind == "film" and j.project == job.project and j.id != job.id
                  and j.film and j.film.episode_index < idx), key=lambda j: j.film.episode_index)
    for j in eps:
        for c in store.load_json(j.id, "characters.json", default=[]):
            out.setdefault(c["name"], FilmCharacter.model_validate(c))
    return list(out.values())

# ---------------------------------------------------------------- steps

def _skip_with_subs(runner):
    def run(ctx: Ctx):
        if code := _use_subs(ctx.job):
            ctx.log(f"Dùng phụ đề có sẵn ({code})")
            return
        runner(ctx)
    return run

def _transcript(ctx: Ctx):
    job = ctx.job
    duration = job.info.duration
    if code := _use_subs(job):
        p = ctx.work.fetch(_vtt(code))
        lines = transcript.parse_vtt(p.read_text(encoding="utf-8"))
    else:
        words = [Word.model_validate(w) for w in store.load_json(job.id, "words.json", default=[])]
        lines = transcript.from_words(words, transcript.transcript_lang(job))
    lines = transcript.filter_ads(lines, duration)
    store.save_json(job.id, "transcript.json", [s.model_dump(mode="json") for s in lines])
    job.warnings = [] if lines else [NO_LINES]
    ctx.log(f"Bản thoại: {len(lines)} dòng" if lines else NO_LINES)

def _characters(ctx: Ctx):
    job = ctx.job
    lines = _lines(job)
    chars = film.characters(pipeline._llm(ctx), _meta(job), lines, transcript.transcript_lang(job),
                            _known(job)) if lines else []
    store.save_json(job.id, "characters.json", [c.model_dump() for c in chars])
    ctx.log(f"Nhân vật: {len(chars)}")

def _summarize(ctx: Ctx):
    job = ctx.job
    lines = _lines(job)
    chunks: list[ChunkSummary] = []
    if lines:
        llm, meta, lang = pipeline._llm(ctx), _meta(job), transcript.transcript_lang(job)
        chars = [FilmCharacter.model_validate(c) for c in store.load_json(job.id, "characters.json", default=[])]
        spans = transcript.chunk(lines, job.info.duration)
        for i, (a, b) in enumerate(spans):
            ctx.check()
            last = i == len(spans) - 1
            part = [s for s in lines if a <= s.start < b or (last and s.start >= b)]
            chunks.append(film.summarize_chunk(llm, meta, chars, part, (a, b), lang))
            ctx.progress("summarize", (i + 1) / len(spans))
    store.save_json(job.id, "summary.json", {"chunks": [c.model_dump() for c in chunks]})
    ctx.log(f"Tóm tắt {len(chunks)} đoạn")
    parts.ensure_default_parts(job)

FILM_RUNNERS = {"probe": pipeline._probe, "extract": _skip_with_subs(pipeline._extract),
                "separate": _skip_with_subs(pipeline._separate), "asr": _skip_with_subs(pipeline._asr),
                "transcript": _transcript, "characters": _characters, "summarize": _summarize}

def film_step_hash(ctx: Ctx, step: str) -> str:
    j, st = ctx.job, ctx.job.settings
    if step == "probe":
        return pipeline.step_hash(ctx, "probe")
    prev = j.steps[FILM_STEPS[FILM_STEPS.index(step) - 1]].hash
    if step in ("extract", "separate", "asr"):
        return _h(prev, step, bool(_use_subs(j)), st.separate, st.lang, st.asr_model)
    if step == "transcript":
        code = _use_subs(j)
        info = ctx.work.store.stat(ctx.work.key(_vtt(code))) if code else None
        return _h(prev, code, info.etag if info else "", _h(templates.load()["ads"], templates.edge_keywords()))
    if step == "characters":
        return _h(prev, st.llm_provider, st.llm_model, _meta(j).model_dump(), [c.name for c in _known(j)])
    if step == "summarize":
        return _h(prev, store.load_json(j.id, "characters.json", default=[]), st.llm_provider, st.llm_model)
    raise KeyError(step)

def _film_inputs(ctx: Ctx, step: str) -> list[str]:
    if code := _use_subs(ctx.job):
        return [_vtt(code)] if step == "transcript" else []
    return pipeline._inputs(ctx, step)

def _film_pushes(ctx: Ctx, step: str) -> list[str]:
    return [] if _use_subs(ctx.job) else pipeline._pushes(ctx, step)

def _film_outputs(ctx: Ctx, step: str) -> list[str]:
    if step in ("transcript", "characters"):
        return [f"{step}.json"]
    if step == "summarize":
        return ["summary.json"]
    if step != "probe" and _use_subs(ctx.job):
        return []
    return pipeline._outputs(ctx, step)

FILM_FLOW = Flow(steps=FILM_STEPS, runners=FILM_RUNNERS, step_hash=film_step_hash, inputs=_film_inputs,
                 pushes=_film_pushes, outputs=_film_outputs, review_stop=None, overwrites=set(),
                 rebuild=pipeline._rebuild)
pipeline.register("film", FILM_FLOW)

# ---------------------------------------------------------------- review

def _position(job: Job) -> tuple[int, bool]:
    """(number of parts in the project, whether this part is the last one)."""
    ps = parts.parts_of(job.project)
    return len(ps), job.part.index == max(p.part.index for p in ps)

def _script(ctx: Ctx):
    job, st = ctx.job, ctx.job.settings
    fj = store.load(job.part.film_job)
    if fj.state not in ("done", "approved"):
        raise RuntimeError("Phim chưa chuẩn bị xong")
    if not _lines(fj):
        raise RuntimeError("Không có lời thoại để viết kịch bản")
    p = parts.project_of(job)
    nb = p.review.notebook
    total, last = _position(job)
    chars = [FilmCharacter.model_validate(c) for c in store.load_json(fj.id, "characters.json", default=[])]
    chunks = [ChunkSummary.model_validate(c) for c in store.load_json(fj.id, "summary.json", default={}).get("chunks", [])]
    old = Script.model_validate(store.load_json(job.id, "script.json", default={}))
    spm = pace.measure_spm(ctx.engines.tts(st.tts_engine), st.tts_voice, st.tts_rate, ctx.ref_audio())
    s = script.build_script(pipeline._llm(ctx), meta=p.review.movie, characters=chars, chunks=chunks, part=job.part,
                            total_parts=total, is_last=last, settings=job.review, notebook=nb, spm=spm,
                            locked=[b for b in old.blocks if b.edited])
    store.save_json(job.id, "script.json", s.model_dump(mode="json"))
    job.part.notebook_rev = notebook.rev_before(nb, job.part.index)
    job.segments_edited = False
    ctx.log(f"Kịch bản: {len(s.blocks)} khối, khoảng {script.estimate_seconds(s, spm) / 60:.1f} phút ({spm:.0f} âm tiết/phút)")

def _film_source(ctx: Ctx) -> tuple[Job, Path]:
    """The film job of this part and its source video in local scratch."""
    fj = store.load(ctx.job.part.film_job)
    src = workdir.WorkDir(fj.id, ctx.work.store).fetch(fj.source)
    if src is None:
        raise RuntimeError("Không tìm thấy video gốc của phim trong kho lưu trữ")
    return fj, src

def _scenes(ctx: Ctx):
    """Real scene cuts of the film over the part; the shots are planned by `assemble` once narration is timed."""
    job = ctx.job
    fj, src = _film_source(ctx)
    cuts = shots.detect_cuts(src, job.part.start, job.part.end, ctx.cancel)
    store.save_json(job.id, "cuts.json", cuts)
    ctx.log(f"Chuyển cảnh: {len(cuts)} điểm cắt")

def _tts(ctx: Ctx):
    """One TTS call per sentence of every script block; the voice-over is laid out later by `assemble`."""
    job, st = ctx.job, ctx.job.settings
    blocks = Script.model_validate(store.load_json(job.id, "script.json", default={})).blocks
    engine, ref = ctx.engines.tts(st.tts_engine), ctx.ref_audio()
    if st.tts_engine == "edge":
        workers = config.EDGE_WORKERS
    else:
        from ..tts import vieneu_tts
        workers = vieneu_tts.workers()
    tts_dir = ctx.dir / "tts"
    if tts_dir.exists():
        shutil.rmtree(tts_dir)
    tts_dir.mkdir()
    todo = [(b.id, i, s) for b in blocks for i, s in enumerate(narration.sentences(b.text))]
    done, lock = [0], threading.Lock()

    def one(item):
        bid, i, s = item
        if ctx.cancel.is_set():
            return None, "cancelled"
        rel = f"tts/b{bid:03d}_s{i:03d}.wav"
        try:
            raw = cached_synthesize(engine, s, st.tts_voice, st.tts_rate, ref)
            pcm = trim_silence(media.decode_mono(raw, SR), SR)
            sf.write(ctx.dir / rel, pcm, SR, subtype="PCM_16")
            res = ({"block": bid, "n": i, "text": s, "file": rel, "dur": len(pcm) / SR}, None)
        except Exception as e:  # noqa: BLE001
            res = (None, str(e))
        with lock:
            done[0] += 1
            ctx.progress("tts", done[0] / max(1, len(todo)))
        return res

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, todo))
    ctx.check()
    if any(err for _, err in results):   # second chance, one at a time, for sentences that failed under parallel load
        ctx.log(f"Đọc lại {sum(1 for _, err in results if err)} câu bị lỗi")
        results = [one(it) if err else (r, err) for it, (r, err) in zip(todo, results)]
        ctx.check()
    bad = [it for it, (_, err) in zip(todo, results) if err]
    ctx.work.push("tts")
    if bad:
        ids = sorted({b for b, _, _ in bad})
        raise RuntimeError(f"TTS lỗi ở {len(bad)} câu (khối {', '.join(map(str, ids))})")
    store.save_json(job.id, "narration.json", [r for r, _ in results])
    ctx.log(f"Lời đọc: {len(results)} câu")

def _title(job: Job) -> str:
    """9:16 title: movie name, then the part (series: the episode and the part's rank inside it)."""
    movie = parts.project_of(job).review.movie
    if movie.type == "single":
        return f"{_escape(movie.name)}\\NPHẦN {job.part.index}"
    fj = store.load(job.part.film_job)
    same = [j.id for j in parts.parts_of(job.project) if j.part.film_job == fj.id]
    return f"{_escape(movie.name)}\\NTẬP {fj.film.episode_index + 1} · PHẦN {same.index(job.id) + 1}"

def _music(job: Job) -> tuple[str, str] | None:
    """(object key, etag) of the project's background music."""
    key = parts.project_of(job).review.music
    info = get_store().stat(key) if key else None
    return (key, info.etag) if info else None

def _has_ass(job: Job) -> bool:
    """16:9 without subtitles burns nothing; 9:16 always has the title."""
    return job.review.subtitles or job.review.aspect == "9:16"

def _assemble(ctx: Ctx):
    """Lay the narration out block after block, mix it with the music, plan the film shots, write the subtitles."""
    job, rv = ctx.job, ctx.job.review
    blocks = Script.model_validate(store.load_json(job.id, "script.json", default={})).blocks
    nar = store.load_json(job.id, "narration.json", default=[])
    ctx.work.fetch_dir("tts")
    t, items, lines, needs = 0.0, [], [], []
    for b in blocks:
        sents = sorted((n for n in nar if n["block"] == b.id), key=lambda n: n["n"])
        if not sents:
            continue
        start = t
        for i, n in enumerate(sents):
            t += narration.SENT_GAP if i else 0
            items.append((t, ctx.work.local(n["file"])))
            lines += narration.subtitle_lines(n["text"], t, n["dur"])
            t += n["dur"]
        t += narration.BLOCK_GAP
        src = (b.source_start, b.source_end) if b.source_start is not None and b.source_end is not None else None
        needs.append(shots.BlockNeed(b.id, t - start, [(s.start, s.end) for s in b.scenes], src))
    if not needs:
        raise RuntimeError("Không có lời đọc để dựng video")
    sf.write(ctx.dir / "voice_raw.wav", mix.build_voice_track(items, t), mix.SR, subtype="PCM_16")
    bed = None
    if m := _music(job):
        local = ctx.dir / ("music" + Path(m[0]).suffix)
        get_store().get_file(m[0], local)
        bed = compose.music_bed(local, ctx.dir / "music_bed.wav", t, ctx.cancel)
    mix.mix(ctx.dir / "voice_raw.wav", bed, ctx.dir / "voice.wav", ctx.dir / "mix.m4a", rv.music_db, t,
            cancel=ctx.cancel, duck_db=-10 if rv.music_duck else None)
    plan = shots.plan_shots(needs, (job.part.start, job.part.end), store.load_json(job.id, "cuts.json", default=[]))
    store.save_json(job.id, "shots.json", [{"block": s.block, "start": s.start, "end": s.end} for s in plan])
    files = {"subs.ass": _has_ass(job) and compose.build_review_ass(
                 lines if rv.subtitles else [], rv.aspect, job.settings.style,
                 _title(job) if rv.aspect == "9:16" else None),
             "subs.srt": rv.subtitles and build_srt(lines)}
    for name, text in files.items():
        if text:
            (ctx.dir / name).write_text(text, encoding="utf-8")
        elif store.exists(job.id, name):
            ctx.work.drop(name)                  # subtitles turned off: no stale file left beside the video
    ctx.log(f"Dựng: {t:.1f} giây lời đọc, {len(plan)} cảnh" + (", có nhạc nền" if bed else ""))

def _render(ctx: Ctx):
    """Encode each planned shot once (named by its content, reused across renders), then join them under the mix."""
    job, rv = ctx.job, ctx.job.review
    fj, src = _film_source(ctx)
    etag = ctx.work.store.stat(store.key(fj.id, fj.source)).etag
    boxes = [region_px(r, fj.info.width, fj.info.height) for r in rv.cover_regions]
    plan = store.load_json(job.id, "shots.json", default=[])
    names: list[str] = []
    frames = compose.frame_counts([s["end"] - s["start"] for s in plan])
    for i, (s, n) in enumerate(zip(plan, frames)):
        ctx.check()
        start = round(s["start"], 3)
        name = f"shots/{_h(etag, start, n, rv.aspect, boxes, rv.cover)}.mp4"
        if name not in names and ctx.work.fetch(name) is None:
            compose.render_shot(src, start, n, ctx.work.local(name), rv.aspect, fj.info, boxes, rv.cover, ctx.cancel)
            ctx.work.push(name)
        names.append(name)
        ctx.progress("render", 0.9 * (i + 1) / len(plan))
    for old in store.names(job.id, "shots/") - set(names):
        ctx.work.drop(old)                       # shots of an older plan
    compose.finalize([ctx.work.local(n) for n in names], ctx.dir / "mix.m4a",
                     ctx.dir / "subs.ass" if _has_ass(job) else None, ctx.dir / "output.mp4",
                     sum(s["end"] - s["start"] for s in plan), lambda p: ctx.progress("render", 0.9 + 0.1 * p),
                     ctx.cancel)

REVIEW_RUNNERS = {"script": _script, "scenes": _scenes, "tts": _tts, "assemble": _assemble, "render": _render}

def review_step_hash(ctx: Ctx, step: str) -> str:
    j, st = ctx.job, ctx.job.settings
    if step == "script":
        fj = store.load(j.part.film_job)
        rv = j.review.model_dump(include={"minutes", "style", "hook", "opening", "notes", "spoil_ending"})
        # the notebook version and is_last stay out: a changed notebook only warns (notebook_rev), the user rewrites
        return _h(fj.steps["summarize"].hash, rv, j.part.start, j.part.end, st.llm_provider, st.llm_model,
                  st.tts_engine, st.tts_voice, st.tts_rate)
    if step == "scenes":
        fj = store.load(j.part.film_job)
        info = ctx.work.store.stat(store.key(fj.id, fj.source))
        return _h(step, info.etag if info else "", j.part.start, j.part.end)
    if step == "tts":
        ref = ctx.work.store.stat(ctx.work.key(st.ref_audio)) if st.ref_audio else None
        blocks = Script.model_validate(store.load_json(j.id, "script.json", default={})).blocks
        return _h(j.steps["scenes"].hash, step, [(b.id, b.text) for b in blocks], st.tts_engine, st.tts_voice,
                  st.tts_rate, ref.etag if ref else "")
    prev, rv = j.steps[REVIEW_STEPS[REVIEW_STEPS.index(step) - 1]].hash, j.review
    if step == "assemble":
        blocks = Script.model_validate(store.load_json(j.id, "script.json", default={})).blocks
        m = _music(j)
        return _h(prev, step, [(b.id, [s.model_dump() for s in b.scenes], b.source_start, b.source_end) for b in blocks],
                  rv.subtitles, rv.aspect, st.style.model_dump(), m[1] if m else "", rv.music_db, rv.music_duck,
                  _title(j) if rv.aspect == "9:16" else "")
    if step == "render":
        return _h(prev, step, rv.aspect, [r.model_dump() for r in rv.cover_regions], rv.cover)
    raise KeyError(step)

def _review_outputs(ctx: Ctx, step: str) -> list[str]:
    return {"script": ["script.json"], "scenes": ["cuts.json"], "tts": ["narration.json"],
            "assemble": ["shots.json", "mix.m4a"], "render": ["output.mp4"]}[step]

def _review_inputs(ctx: Ctx, step: str) -> list[str]:
    if step != "render":
        return []
    return ["mix.m4a", "subs.ass"] if _has_ass(ctx.job) else ["mix.m4a"]

def _review_pushes(ctx: Ctx, step: str) -> list[str]:
    if step == "assemble":
        return (["voice_raw.wav", "voice.wav", "mix.m4a"] + (["subs.ass"] if _has_ass(ctx.job) else [])
                + (["subs.srt"] if ctx.job.review.subtitles else []))
    return ["output.mp4"] if step == "render" else []

REVIEW_FLOW = Flow(steps=REVIEW_STEPS, runners=REVIEW_RUNNERS, step_hash=review_step_hash,
                   inputs=_review_inputs, pushes=_review_pushes, outputs=_review_outputs,
                   review_stop="script", overwrites={"script"}, pins=lambda job: [job.part.film_job])
pipeline.register("review", REVIEW_FLOW)
