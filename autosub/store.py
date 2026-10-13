import json
import os
import shutil
import time
import uuid
from pathlib import Path
from . import config
from .models import STEPS, Job, Segment, TranslationContext

def job_dir(jid: str) -> Path:
    return config.PROJECTS_DIR / jid

def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default

def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)

def create(name: str, source: str, uploaded: bool = False) -> Job:
    jid = uuid.uuid4().hex[:10]
    job = Job(id=jid, name=name, created=time.time(), source=source, uploaded=uploaded)
    save(job)
    return job

def load(jid: str) -> Job:
    data = read_json(job_dir(jid) / "job.json")
    if data is None:
        raise KeyError(jid)
    return Job.model_validate(data)

def save(job: Job) -> None:
    write_json(job_dir(job.id) / "job.json", job.model_dump(mode="json"))

def list_jobs() -> list[Job]:
    if not config.PROJECTS_DIR.exists():
        return []
    jobs = []
    for d in config.PROJECTS_DIR.iterdir():
        try:
            jobs.append(load(d.name))
        except (KeyError, ValueError, NotADirectoryError):
            continue
    return sorted(jobs, key=lambda j: j.created, reverse=True)

def delete(jid: str) -> None:
    shutil.rmtree(job_dir(jid), ignore_errors=True)

def load_segments(jid: str) -> list[Segment]:
    return [Segment.model_validate(s) for s in read_json(job_dir(jid) / "segments.json", default=[])]

def save_segments(jid: str, segs: list[Segment]) -> None:
    write_json(job_dir(jid) / "segments.json", [s.model_dump(mode="json") for s in segs])

def load_context(jid: str) -> TranslationContext | None:
    data = read_json(job_dir(jid) / "context.json")
    return None if data is None else TranslationContext.model_validate(data)

def save_context(jid: str, ctx: TranslationContext) -> None:
    write_json(job_dir(jid) / "context.json", ctx.model_dump(mode="json"))

def _presets_path() -> Path:
    return config.PROJECTS_DIR / "presets.json"

def load_presets() -> dict[str, dict]:
    return read_json(_presets_path(), default={})

def save_preset(name: str, settings: dict) -> None:
    p = load_presets(); p[name] = settings; write_json(_presets_path(), p)

def delete_preset(name: str) -> None:
    p = load_presets(); p.pop(name, None); write_json(_presets_path(), p)

__all__ = ["STEPS"]
