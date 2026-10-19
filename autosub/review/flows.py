"""Flows of the review feature. "film": prepare one movie/episode once (transcript, characters, chunk summaries).
"review": one video reviewing a part of a film (script, scenes, voice, assembly, render)."""
from .. import pipeline, projects, store
from ..models import FILM_STEPS, REVIEW_STEPS, ChunkSummary, FilmCharacter, Job, MovieMeta, Script, Segment, Word
from ..pipeline import Ctx, Flow, _h
from . import film, notebook, pace, parts, script, templates, transcript

NO_LINES = "Không có lời thoại: không viết được kịch bản review"

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

def _placeholder(ctx: Ctx):
    """ponytail: scenes/tts/assemble/render are filled in by later tasks; until then they do nothing."""

REVIEW_RUNNERS = {"script": _script, "scenes": _placeholder, "tts": _placeholder, "assemble": _placeholder,
                  "render": _placeholder}

def review_step_hash(ctx: Ctx, step: str) -> str:
    j, st = ctx.job, ctx.job.settings
    if step == "script":
        fj = store.load(j.part.film_job)
        rv = j.review.model_dump(include={"minutes", "style", "hook", "opening", "notes", "spoil_ending"})
        nb = parts.project_of(j).review.notebook
        return _h(fj.steps["summarize"].hash, notebook.rev_before(nb, j.part.index), rv, j.part.start, j.part.end,
                  _position(j)[1], st.llm_provider, st.llm_model, st.tts_engine, st.tts_voice, st.tts_rate)
    return _h(j.steps[REVIEW_STEPS[REVIEW_STEPS.index(step) - 1]].hash, step)

def _review_outputs(ctx: Ctx, step: str) -> list[str]:
    return ["script.json"] if step == "script" else []

REVIEW_FLOW = Flow(steps=REVIEW_STEPS, runners=REVIEW_RUNNERS, step_hash=review_step_hash,
                   inputs=lambda ctx, step: [], pushes=lambda ctx, step: [], outputs=_review_outputs,
                   review_stop="script", overwrites={"script"}, pins=lambda job: [job.part.film_job])
pipeline.register("review", REVIEW_FLOW)
