"""Projects group the videos of one source (a Douyin channel, a series...) and keep a shared preset:
the settings of a video already done well (subtitle position, covered regions, font, voice...), applied
to every new video of the project. Stored as projects.json in object storage."""
import time
import uuid
from typing import Literal
from pydantic import BaseModel, Field
from .models import Episode, MovieMeta, Notebook, ReviewSettings
from .storage import get_store, read_json, write_json

KEY = "projects.json"

class ReviewProject(BaseModel):
    """A film to review: the movie, its episodes, shared settings and the story notebook."""
    source: Literal["upload", "vsmov"]
    movie: MovieMeta
    server: str = ""
    episodes: list[Episode] = Field(default_factory=list)
    parts_per_episode: Literal[1, 2] = 1
    settings: ReviewSettings = Field(default_factory=ReviewSettings)
    job_settings: dict | None = None
    music: str | None = None              # object key of the background music
    notebook: Notebook = Field(default_factory=Notebook)

class Project(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=80)
    source_url: str = ""                  # e.g. the Douyin channel link
    created: float = 0
    preset: dict | None = None            # JobSettings as JSON; None until saved from a video
    preset_from: str | None = None        # name of the video the preset was taken from
    kind: Literal["sub", "review"] = "sub"
    review: ReviewProject | None = None

def _all() -> dict[str, dict]:
    return read_json(get_store(), KEY, default={})

def _write(data: dict[str, dict]) -> None:
    write_json(get_store(), KEY, data)

def list_projects() -> list[Project]:
    return sorted((Project.model_validate(v) for v in _all().values()), key=lambda p: p.created)

def get(pid: str) -> Project | None:
    v = _all().get(pid)
    return Project.model_validate(v) if v else None

def create(name: str, source_url: str = "", kind: Literal["sub", "review"] = "sub",
           review: ReviewProject | None = None) -> Project:
    p = Project(id=uuid.uuid4().hex[:8], name=name.strip()[:80] or "Project", source_url=source_url.strip(),
                created=time.time(), kind=kind, review=review)
    save(p)
    return p

def music_key(pid: str, ext: str) -> str:
    return f"projects/{pid}/music{ext}"

def save(p: Project) -> None:
    data = _all(); data[p.id] = p.model_dump(mode="json"); _write(data)

def delete(pid: str) -> None:
    data = _all(); data.pop(pid, None); _write(data)

def find_by_source(url: str) -> Project | None:
    url = url.strip()
    return next((p for p in list_projects() if url and p.source_url == url), None)
