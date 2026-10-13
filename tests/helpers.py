"""Create jobs the way the API does: the video is copied into the job's storage."""
import shutil
from pathlib import Path
from autosub import media, store, workdir

def new_job(video: Path, name: str | None = None):
    job = store.create(name or video.name, "source" + video.suffix.lower())
    w = workdir.WorkDir(job.id)
    shutil.copyfile(video, w.local(job.source))
    w.push(job.source)
    job.info = media.probe(video)
    store.save(job)
    return job
