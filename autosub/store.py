"""Job documents in object storage: jobs/<id>/job.json, segments.json, context.json; presets.json."""
import time
import uuid
from .models import STEPS, Job, Segment, TranslationContext
from .storage import get_store, read_json, write_json
from .workdir import job_prefix

PRESETS = "presets.json"

def key(jid: str, name: str) -> str:
    return job_prefix(jid) + name

def create(name: str, source: str = "source", uploaded: bool = False) -> Job:
    """`source` is the object name of the video inside the job (always copied into storage)."""
    jid = uuid.uuid4().hex[:10]
    job = Job(id=jid, name=name, created=time.time(), source=source, uploaded=uploaded)
    save(job)
    return job

def load(jid: str) -> Job:
    data = read_json(get_store(), key(jid, "job.json"))
    if data is None:
        raise KeyError(jid)
    return Job.model_validate(data)

def save(job: Job) -> None:
    write_json(get_store(), key(job.id, "job.json"), job.model_dump(mode="json"))

def list_jobs() -> list[Job]:
    st = get_store()
    jobs = []
    for o in st.list("jobs/"):
        parts = o.key.split("/")
        if len(parts) == 3 and parts[2] == "job.json":
            try:
                jobs.append(load(parts[1]))
            except (KeyError, ValueError):
                continue
    return sorted(jobs, key=lambda j: j.created, reverse=True)

def exists(jid: str, name: str) -> bool:
    return get_store().stat(key(jid, name)) is not None

def names(jid: str, prefix: str = "") -> set[str]:
    """Object names under jobs/<id>/<prefix> (relative to the job)."""
    base = job_prefix(jid)
    return {o.key[len(base):] for o in get_store().list(base + prefix)}

def delete(jid: str) -> None:
    from . import workdir
    get_store().delete_prefix(job_prefix(jid))
    workdir.remove(jid)

def load_json(jid: str, name: str, default=None):
    return read_json(get_store(), key(jid, name), default)

def save_json(jid: str, name: str, value) -> None:
    write_json(get_store(), key(jid, name), value)

def load_segments(jid: str) -> list[Segment]:
    return [Segment.model_validate(s) for s in load_json(jid, "segments.json", default=[])]

def save_segments(jid: str, segs: list[Segment]) -> None:
    save_json(jid, "segments.json", [s.model_dump(mode="json") for s in segs])

def load_context(jid: str) -> TranslationContext | None:
    data = load_json(jid, "context.json")
    return None if data is None else TranslationContext.model_validate(data)

def save_context(jid: str, ctx: TranslationContext) -> None:
    save_json(jid, "context.json", ctx.model_dump(mode="json"))

def delete_context(jid: str) -> None:
    get_store().delete(key(jid, "context.json"))

def load_presets() -> dict[str, dict]:
    return read_json(get_store(), PRESETS, default={})

def save_preset(name: str, settings: dict) -> None:
    p = load_presets(); p[name] = settings; write_json(get_store(), PRESETS, p)

def delete_preset(name: str) -> None:
    p = load_presets(); p.pop(name, None); write_json(get_store(), PRESETS, p)

__all__ = ["STEPS"]
