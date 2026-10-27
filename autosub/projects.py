"""Projects group the videos of one source (a Douyin channel, a series...) and keep a shared preset:
the settings of a video already done well (subtitle position, covered regions, font, voice...), applied
to every new video of the project. Stored as projects.json in object storage."""
import threading
import time
import uuid
from typing import Callable, Literal
from pydantic import BaseModel, Field
from .models import Episode, MovieMeta, Notebook, ReviewSettings, VideoInfo
from .storage import get_store, read_json, write_json

KEY = "projects.json"
_LOCK = threading.Lock()                  # read-modify-write of projects.json inside this process

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

class AudioProject(BaseModel):
    """An audio story: shared background video, music and voice; each part (job) reads one script file."""
    background: str | None = None         # original background video key (projects/{pid}/background.<ext>)
    background_info: VideoInfo | None = None
    background_state: Literal["none", "processing", "ready", "error"] = "none"   # the normalized bg_loop.mp4
    background_error: str | None = None
    background_etag: str | None = None    # ETag of bg_loop.mp4 in storage (parts re-render when it changes)
    music: str | None = None              # projects/{pid}/music.<ext>; None = no background music
    music_volume: float = Field(0.15, ge=0, le=1)   # gain of the music under the normalized voice
    engine: str = "edge"                  # edge | vieneu
    voice: str = ""
    rate: float = 1.0
    rev: int = 0                          # bumped on every change of the settings above

class Project(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=80)
    source_url: str = ""                  # e.g. the Douyin channel link
    created: float = 0
    preset: dict | None = None            # JobSettings as JSON; None until saved from a video
    preset_from: str | None = None        # name of the video the preset was taken from
    kind: Literal["sub", "review", "audio"] = "sub"
    review: ReviewProject | None = None
    audio: AudioProject | None = None

def _all() -> dict[str, dict]:
    return read_json(get_store(), KEY, default={})

def _write(data: dict[str, dict]) -> None:
    write_json(get_store(), KEY, data)

def list_projects() -> list[Project]:
    return sorted((Project.model_validate(v) for v in _all().values()), key=lambda p: p.created)

def get(pid: str) -> Project | None:
    v = _all().get(pid)
    return Project.model_validate(v) if v else None

def create(name: str, source_url: str = "", kind: Literal["sub", "review", "audio"] = "sub",
           review: ReviewProject | None = None, audio: AudioProject | None = None) -> Project:
    if kind == "audio" and audio is None:
        audio = AudioProject()
    p = Project(id=uuid.uuid4().hex[:8], name=name.strip()[:80] or "Project", source_url=source_url.strip(),
                created=time.time(), kind=kind, review=review, audio=audio)
    save(p)
    return p

def music_key(pid: str, ext: str) -> str:
    return f"projects/{pid}/music{ext}"

def bg_key(pid: str, ext: str) -> str:
    """The uploaded (original) background video of an audio story."""
    return f"projects/{pid}/background{ext}"

def bg_loop_key(pid: str) -> str:
    """The normalized, silent, 1 s-keyframe copy of the background that every part loops."""
    return f"projects/{pid}/bg_loop.mp4"

def save(p: Project) -> None:
    with _LOCK:
        data = _all(); data[p.id] = p.model_dump(mode="json"); _write(data)

def update(pid: str, fn: Callable[[Project], None]) -> Project | None:
    """Load, change and save one project under the lock (no lost writes between threads). None if gone."""
    with _LOCK:
        data = _all()
        if pid not in data:
            return None
        p = Project.model_validate(data[pid])
        fn(p)
        data[pid] = p.model_dump(mode="json"); _write(data)
        return p

def delete(pid: str) -> None:
    with _LOCK:
        data = _all(); data.pop(pid, None); _write(data)

def find_by_source(url: str) -> Project | None:
    url = url.strip()
    return next((p for p in list_projects() if url and p.source_url == url), None)
