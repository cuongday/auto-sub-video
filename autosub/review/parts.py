"""The per-part review jobs of a film: create, re-split, order."""
from .. import projects, store
from ..models import ChunkSummary, Job, JobSettings, PartInfo, ReviewSettings, Segment
from ..projects import Project
from . import split

def project_of(job: Job) -> Project:
    p = projects.get(job.project) if job.project else None
    if not p or not p.review:
        raise KeyError(job.project)
    return p

def parts_of(project_id: str) -> list[Job]:
    return sorted((j for j in store.list_jobs() if j.kind == "review" and j.project == project_id),
                  key=lambda j: j.part.index)

def _reindex(project_id: str) -> None:
    films = {j.id: j.film.episode_index for j in store.list_jobs() if j.kind == "film" and j.project == project_id}
    jobs = sorted((j for j in store.list_jobs() if j.kind == "review" and j.project == project_id),
                  key=lambda j: (films.get(j.part.film_job, 0), j.part.start))
    for i, j in enumerate(jobs, 1):
        if j.part.index != i:
            j.part.index = i
            store.save(j)

def create_parts(film_job: Job, cuts: list[float]) -> list[Job]:
    p = project_of(film_job)
    old = [j for j in parts_of(p.id) if j.part.film_job == film_job.id]
    if any(j.steps["script"].status == "done" for j in old):
        raise ValueError("Đã có phần viết kịch bản, không chia lại được")
    for j in old:
        store.delete(j.id)
    bounds = [0.0, *cuts, film_job.info.duration]
    out = []
    for i, (a, b) in enumerate(zip(bounds, bounds[1:]), 1):
        job = store.create(f"{p.review.movie.name} · Phần {i}", film_job.source, uploaded=False, kind="review")
        job.project = p.id
        job.info = film_job.info
        job.settings = JobSettings.model_validate(p.review.job_settings) if p.review.job_settings else JobSettings()
        job.review = ReviewSettings.model_validate(p.review.settings.model_dump())
        job.part = PartInfo(film_job=film_job.id, index=i, start=a, end=b)
        store.save(job)
        out.append(job)
    _reindex(p.id)
    return [store.load(j.id) for j in out]

def ensure_default_parts(film_job: Job) -> None:
    """Series: one part per episode (or two) when the film has none yet."""
    p = project_of(film_job)
    if p.review.movie.type == "single" or any(j.part.film_job == film_job.id for j in parts_of(p.id)):
        return
    cuts = []
    if p.review.parts_per_episode == 2:
        lines = store.load_json(film_job.id, "transcript.json", default=[])
        chunks = [ChunkSummary.model_validate(c) for c in store.load_json(film_job.id, "summary.json", default={}).get("chunks", [])]
        cuts = split.propose_cuts([Segment.model_validate(s) for s in lines], film_job.info.duration, parts=2, chunks=chunks)
    create_parts(film_job, cuts)
