"""Flow "audio": one part of an audio story. parse the script -> read every line (TTS) -> normalize the voice and
mix the looped music -> loop the project's normalized background under it by stream copy (no video re-encode)."""
import dataclasses
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import soundfile as sf
from .. import config, media, mix as mix_mod, pipeline, proc, projects, store
from ..fit import fit_segment
from ..models import AUDIO_STEPS, AudioPart, Job, Segment
from ..pipeline import Ctx, Flow, _h
from ..projects import AudioProject
from ..storage import get_store
from ..timing import trim_silence
from ..tts.base import cached_synthesize
from . import background, script, timeline
from .script import Line

SR = mix_mod.SR
KINDS = ("txt", "docx", "srt")
MUSIC_FADE = 3.0
WAIT = 2.0                                     # seconds between checks while the background is being normalized

def new_part(pid: str, filename: str, data: bytes, index: int) -> Job:
    """Create the job of one part from its script file (stored as script.<ext>); the name is the file stem."""
    p = Path(filename)
    kind = p.suffix.lower().lstrip(".")
    if kind not in KINDS:
        raise ValueError("Chỉ nhận kịch bản .txt, .docx hoặc .srt")
    job = store.create(p.stem or filename, f"script.{kind}", uploaded=True, kind="audio")
    get_store().put_bytes(store.key(job.id, job.source), data)
    job.project = pid
    job.audio_part = AudioPart(script_name=p.name, script_kind=kind, index=index)
    store.save(job)
    return job

def _audio(ctx: Ctx) -> AudioProject:
    """The project's settings, read once per run: a part keeps the settings it started with (and its step
    hashes say so, so a change made meanwhile marks it stale afterwards)."""
    a = getattr(ctx, "_audio", None)
    if a is None:
        p = projects.get(ctx.job.project) if ctx.job.project else None
        a = p.audio.model_copy() if p and p.audio else AudioProject()
        ctx._audio = a
    return a

def _project(ctx: Ctx) -> AudioProject:
    p = projects.get(ctx.job.project) if ctx.job.project else None
    if p is None or p.audio is None:
        raise RuntimeError("Không tìm thấy truyện của phần này")
    return p.audio

def _lines(job: Job) -> list[Line]:
    return [Line(**d) for d in store.load_json(job.id, "lines.json", default=[])]

# ---------------------------------------------------------------- steps

def _parse(ctx: Ctx):
    src = ctx.work.fetch(ctx.job.source)
    if src is None:
        raise RuntimeError("Không tìm thấy file kịch bản trong kho lưu trữ")
    try:
        lines = script.parse(src, ctx.job.audio_part.script_kind)
    except script.ScriptError as e:
        raise RuntimeError(str(e)) from None
    store.save_json(ctx.job.id, "lines.json", [dataclasses.asdict(l) for l in lines])
    ctx.log(f"Kịch bản: {len(lines)} câu, {sum(len(l.text) for l in lines)} ký tự")

def _read_line(ctx: Ctx, engine, a: AudioProject, i: int, line: Line, out: Path) -> float:
    if line.start is not None and line.end is not None:      # .srt: fit the line into its cue
        seg = Segment(id=i, start=line.start, end=line.end, source=line.text, vi=line.text)
        return fit_segment(engine, seg, max(0.3, line.end - line.start), a.voice, a.rate, None, out,
                           cancel=ctx.cancel).duration
    raw = cached_synthesize(engine, line.text, a.voice, a.rate, None)
    pcm = trim_silence(media.decode_mono(raw, SR), SR)
    sf.write(out, pcm, SR, subtype="PCM_16")
    return len(pcm) / SR

def _tts(ctx: Ctx):
    job, a = ctx.job, _audio(ctx)
    lines = _lines(job)
    engine = ctx.engines.tts(a.engine)
    if a.engine == "edge":
        workers = config.EDGE_WORKERS
    else:
        from ..tts import vieneu_tts
        workers = vieneu_tts.workers()
    tts_dir = ctx.dir / "tts"
    shutil.rmtree(tts_dir, ignore_errors=True)
    tts_dir.mkdir()
    done, lock = [0], threading.Lock()

    def one(i: int):
        if ctx.cancel.is_set():
            return None, "cancelled"
        try:
            res = (_read_line(ctx, engine, a, i, lines[i], tts_dir / f"l{i:05d}.wav"), None)
        except Exception as e:  # noqa: BLE001
            res = (None, str(e))
        with lock:
            done[0] += 1
            ctx.progress("tts", 0.95 * done[0] / max(1, len(lines)))
        return res

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, range(len(lines))))
    ctx.check()
    if any(err for _, err in results):     # second chance, one at a time, for lines that failed under parallel load
        ctx.log(f"Đọc lại {sum(1 for _, err in results if err)} câu bị lỗi")
        results = [one(i) if err else (d, err) for i, (d, err) in enumerate(results)]
        ctx.check()
    bad = [i for i, (_, err) in enumerate(results) if err]
    if bad:
        i = bad[0]
        raise RuntimeError(f"TTS lỗi ở {len(bad)} câu; câu {i + 1}: «{lines[i].text[:80]}» ({results[i][1]})")
    durs = [d for d, _ in results]
    timed = all(l.start is not None for l in lines)
    starts, total = (timeline.timed if timed else timeline.sequential)(lines, durs)
    track = mix_mod.build_voice_track([(s, tts_dir / f"l{i:05d}.wav") for i, s in enumerate(starts)], total)
    sf.write(ctx.dir / "voice_raw.wav", track, SR, subtype="PCM_16")
    store.save_json(job.id, "meta.json", {"duration": round(total, 3), "chars": sum(len(l.text) for l in lines),
                                          "lines": len(lines)})
    ctx.log(f"Lời đọc: {len(lines)} câu, {total:.1f}s")

def _duration(job: Job) -> float:
    return float(store.load_json(job.id, "meta.json", default={}).get("duration") or 0)

def _mix(ctx: Ctx):
    a, dur = _audio(ctx), _duration(ctx.job)
    voice, out = ctx.dir / "voice.wav", ctx.dir / "mix.m4a"
    music = None
    if a.music:
        music = ctx.dir / f"music{Path(a.music).suffix}"
        if not get_store().get_file(a.music, music):
            raise RuntimeError("Không tìm thấy nhạc nền trong kho lưu trữ")
    if music is None:
        mix_mod.mix(ctx.dir / "voice_raw.wav", None, voice, out, 0.0, dur, cancel=ctx.cancel)
        return
    tmp_voice = voice.with_name("voice.tmp.wav")
    proc.run_ffmpeg(["-i", str(ctx.dir / "voice_raw.wav"), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", str(SR),
                     "-ac", "1", "-t", f"{dur:.3f}", "-c:a", "pcm_s16le", str(tmp_voice)], cancel=ctx.cancel)
    tmp_voice.replace(voice)
    fade = min(MUSIC_FADE, dur)
    graph = (f"[1:a]aresample={SR},volume={a.music_volume:.3f},afade=t=out:st={max(0.0, dur - fade):.3f}:d={fade:.3f}[bg];"
             f"[0:a]aresample={SR},pan=stereo|c0=c0|c1=c0[vo];"
             "[vo][bg]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
    tmp = out.with_name("mix.tmp.m4a")
    proc.run_ffmpeg(["-i", str(voice), "-stream_loop", "-1", "-i", str(music), "-filter_complex", graph,
                     "-map", "[a]", "-t", f"{dur:.3f}", "-c:a", "aac", "-b:a", "192k", str(tmp)],
                    duration=dur, progress=lambda p: ctx.progress("mix", p), cancel=ctx.cancel)
    tmp.replace(out)

def _wait_background(ctx: Ctx) -> None:
    """A part reaching render while the background is still being normalized waits (cancellable)."""
    told = False
    while True:
        a = _project(ctx)
        if a.background_state == "ready":
            return
        if a.background_state == "processing":
            if not told:
                ctx.log("Đang chờ chuẩn hoá video nền xong")
                told = True
            if ctx.cancel.wait(WAIT):
                raise proc.Cancelled()
            continue
        if a.background_state == "error":
            raise RuntimeError(f"Video nền bị lỗi: {a.background_error or 'chưa chuẩn hoá được'}. Hãy tải lại video nền")
        raise RuntimeError(background.NO_BACKGROUND)

def _render(ctx: Ctx):
    job = ctx.job
    _wait_background(ctx)
    bg = background.local_loop(job.project)        # the run holds workdir.pinned on the project dir (Flow.pins)
    _audio(ctx).background_etag = background.local_etag(job.project)   # the step's hash names the copy it used
    dur, out = _duration(job), ctx.dir / "output.mp4"
    tmp = out.with_name("output.tmp.mp4")
    proc.run_ffmpeg(["-stream_loop", "-1", "-i", str(bg), "-i", str(ctx.dir / "mix.m4a"), "-map", "0:v:0",
                     "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy", "-t", f"{dur:.3f}", "-movflags", "+faststart",
                     str(tmp)], duration=dur, progress=lambda p: ctx.progress("render", p), cancel=ctx.cancel)
    tmp.replace(out)
    job.info = media.probe(out)

RUNNERS = {"parse": _parse, "tts": _tts, "mix": _mix, "render": _render}

def step_hash(ctx: Ctx, step: str) -> str:
    j, a = ctx.job, _audio(ctx)
    if step == "parse":
        info = ctx.work.store.stat(ctx.work.key(j.source))
        return _h(step, info.etag if info else "", j.audio_part.script_kind if j.audio_part else "")
    prev = j.steps[AUDIO_STEPS[AUDIO_STEPS.index(step) - 1]].hash
    if step == "tts":
        return _h(prev, step, a.engine, a.voice, a.rate)
    if step == "mix":
        m = ctx.work.store.stat(a.music) if a.music else None
        return _h(prev, step, a.music or "", m.etag if m else "", a.music_volume)
    if step == "render":
        return _h(prev, step, a.background_etag or "")
    raise KeyError(step)

def _inputs(ctx: Ctx, step: str) -> list[str]:
    return {"mix": ["voice_raw.wav"], "render": ["mix.m4a"]}.get(step, [])

def _pushes(ctx: Ctx, step: str) -> list[str]:
    return {"tts": ["voice_raw.wav"], "mix": ["mix.m4a"], "render": ["output.mp4"]}.get(step, [])

def _outputs(ctx: Ctx, step: str) -> list[str]:
    return {"parse": ["lines.json"], "tts": ["voice_raw.wav", "meta.json"], "mix": ["mix.m4a"],
            "render": ["output.mp4"]}[step]

def _rebuild(ctx: Ctx, name: str) -> bool:
    """voice_raw.wav may be pruned after a run: read it again (lines come from the shared TTS cache)."""
    if name != "voice_raw.wav":
        return False
    _tts(ctx)
    ctx.work.push(name)
    if name in ctx.job.pruned:
        ctx.job.pruned.remove(name)
    return True

AUDIO_FLOW = Flow(steps=AUDIO_STEPS, runners=RUNNERS, step_hash=step_hash, inputs=_inputs, pushes=_pushes,
                  outputs=_outputs, review_stop=None, overwrites=set(), rebuild=_rebuild,
                  pins=lambda job: [background.pin_key(job.project)] if job.project else [])
pipeline.register("audio", AUDIO_FLOW)
