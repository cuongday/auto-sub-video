from typing import Literal
from pydantic import BaseModel, Field, model_validator

Lang = Literal["zh", "en", "ko", "vi"]   # "vi": a film dubbed in Vietnamese ("Thuyết minh"), transcribed as is
STEPS = ["probe", "extract", "separate", "asr", "segment", "translate", "tts", "fit", "mix", "render"]
FILM_STEPS = ["probe", "extract", "separate", "asr", "transcript", "characters", "summarize"]
REVIEW_STEPS = ["script", "scenes", "tts", "assemble", "render"]
AUDIO_STEPS = ["parse", "tts", "mix", "render"]
STEPS_BY_KIND = {"sub": STEPS, "film": FILM_STEPS, "review": REVIEW_STEPS, "audio": AUDIO_STEPS}
# "sub": subtitle/voice-over a video; "film": analyze a whole movie; "review": one review video of a film part
JobKind = Literal["sub", "film", "review", "audio"]

class Region(BaseModel):
    """Rectangle in normalized frame coordinates (0..1)."""
    x: float = Field(0.05, ge=0, le=1)
    y: float = Field(0.80, ge=0, le=1)
    w: float = Field(0.90, gt=0, le=1)
    h: float = Field(0.14, gt=0, le=1)

    @model_validator(mode="after")
    def _inside(self):
        if self.x + self.w > 1.0001 or self.y + self.h > 1.0001:
            raise ValueError("Vùng che vượt ra ngoài khung hình")
        return self

def default_region(width: int, height: int) -> "Region":
    """Bottom band; on portrait videos (Douyin/TikTok) subtitles sit higher, above the app UI."""
    if height > width:
        return Region(x=0.04, y=0.78, w=0.92, h=0.10)
    return Region()

HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"

class SubStyle(BaseModel):
    font: str = "bevietnam"               # id from autosub/fonts.py
    font_size: int | None = None          # None -> auto from region height
    color: str = Field("#FFFFFF", pattern=HEX_COLOR)
    outline_color: str = Field("#000000", pattern=HEX_COLOR)
    outline: float | None = None          # None -> auto from font size

class JobSettings(BaseModel):
    lang: Lang = "zh"
    asr_model: str = ""                   # "" -> default for lang
    llm_provider: Literal["gemini", "openai"] = "gemini"
    llm_model: str = ""                   # "" -> provider default
    translator_notes: str = ""
    tts_engine: Literal["edge", "vieneu"] = "edge"
    tts_voice: str = ""                   # "" -> engine default
    tts_rate: float = Field(1.0, ge=0.5, le=2.0)
    ref_audio: str | None = None          # VieNeu clone reference (file name inside job dir)
    region: Region = Field(default_factory=Region)
    extra_regions: list[Region] = Field(default_factory=list, max_length=5)  # covered only, no subtitle
    cover: Literal["blur", "blur_dim", "solid"] = "blur_dim"
    cover_color: str = "#000000"
    style: SubStyle = Field(default_factory=SubStyle)
    bg_volume_db: float = Field(0.0, ge=-30, le=10)
    # False: skip Demucs; the original audio is the background and is ducked under the narration
    separate: bool = True
    diarize: bool = False                 # label who speaks each line (Chinese ASR, CAM++)
    text_source: Literal["asr", "ocr"] = "asr"   # ocr: read the burnt-in subtitles inside `region`
    speaker_voices: dict[str, str] = Field(default_factory=dict)   # speaker label -> TTS voice; others use tts_voice
    duck_db: float = Field(-14.0, ge=-40, le=0)

class Word(BaseModel):
    text: str
    start: float
    end: float
    speaker: int | None = None            # diarization label (Chinese ASR with speaker labels on)

class Segment(BaseModel):
    id: int
    start: float
    end: float
    source: str
    vi: str = ""
    flags: list[str] = Field(default_factory=list)
    speed: float | None = None            # actual speed-up applied by the fit step
    speaker: int | None = None

class Character(BaseModel):
    name: str
    vi_name: str
    addressing: str = ""

class GlossaryItem(BaseModel):
    source: str
    vi: str

class TranslationContext(BaseModel):
    summary: str = ""
    genre_tone: str = ""
    characters: list[Character] = Field(default_factory=list)
    glossary: list[GlossaryItem] = Field(default_factory=list)

class VideoInfo(BaseModel):
    width: int
    height: int
    duration: float
    fps: float
    has_audio: bool

class StepState(BaseModel):
    status: Literal["pending", "running", "done", "error"] = "pending"
    hash: str | None = None
    seconds: float | None = None
    error: str | None = None

# "approved": a finished video the user has checked; any re-run turns it back into "done"
JobState = Literal["new", "queued", "running", "awaiting_review", "done", "approved", "error", "interrupted", "cancelled"]

class SubTrack(BaseModel):
    code: str
    url: str


class MovieMeta(BaseModel):
    slug: str = ""
    name: str
    origin_name: str = ""
    year: int | None = None
    type: str = "single"
    poster_url: str = ""
    thumb_url: str = ""
    time: str = ""
    lang: str = ""
    content: str = ""
    actors: list[str] = Field(default_factory=list)
    directors: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)


class Episode(BaseModel):
    name: str
    slug: str
    embed: str


class FilmInfo(BaseModel):
    episode: Episode | None = None
    episode_index: int = 0
    subtitles: list[SubTrack] = Field(default_factory=list)
    subtitle: str | None = None           # chosen code; None -> ASR


class PartInfo(BaseModel):
    film_job: str
    index: int
    start: float
    end: float
    notebook_rev: int = 0


class ReviewSettings(BaseModel):
    minutes: float = Field(5, ge=1, le=30)
    aspect: Literal["16:9", "9:16"] = "9:16"
    style: str = "kich_tinh"
    hook: str = "cau_hoi"
    use_hook: bool = True                 # False: the video opens with mo_dau, no hook block
    opening: str = ""                     # "" -> gioi_thieu for part 1, tom_tat_truoc after
    notes: str = ""
    spoil_ending: bool = False
    subtitles: bool = True
    music_db: float = Field(-20, ge=-40, le=0)
    music_duck: bool = True
    cover_regions: list[Region] = Field(default_factory=list, max_length=5)   # source-frame coordinates
    cover: Literal["blur", "blur_dim", "solid"] = "blur_dim"
    sub_region: Region | None = None      # output-frame coordinates; None -> compose.layout's default
    title_region: Region | None = None    # 9:16 only; None -> default
    show_title: bool = True               # 9:16 "movie name / PHẦN N" title


class TimeSpan(BaseModel):
    start: float
    end: float


class ScriptBlock(BaseModel):
    id: int
    kind: Literal["hook", "mo_dau", "than", "ket"]
    text: str
    scenes: list[TimeSpan] = Field(default_factory=list)
    source_start: float | None = None
    source_end: float | None = None
    template: str = ""
    edited: bool = False


class Script(BaseModel):
    blocks: list[ScriptBlock] = Field(default_factory=list)


class FilmCharacter(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    role: str = ""


class SceneNote(BaseModel):
    start: float
    end: float
    text: str


class ChunkSummary(BaseModel):
    start: float
    end: float
    summary: str
    events: list[SceneNote] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    highlights: list[SceneNote] = Field(default_factory=list)


class NotebookCharacter(FilmCharacter):
    relations: str = ""
    arc: str = ""


class NotebookEntry(BaseModel):
    job: str
    index: int
    range_label: str
    summary: str
    ending: str = ""
    open_threads: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)
    rev: int


class Notebook(BaseModel):
    entries: list[NotebookEntry] = Field(default_factory=list)
    characters: list[NotebookCharacter] = Field(default_factory=list)
    voice: str = ""
    rev: int = 0
    shared_rev: int = 0


class Job(BaseModel):
    id: str
    name: str
    created: float
    source: str                           # absolute path of the video
    uploaded: bool = False                # source lives inside the job dir
    kind: JobKind = "sub"                 # which flow runs it (pipeline.flow_for)
    info: VideoInfo | None = None
    settings: JobSettings = Field(default_factory=JobSettings)
    steps: dict[str, StepState] = Field(default_factory=lambda: {s: StepState() for s in STEPS})
    state: JobState = "new"
    mode: Literal["review", "auto"] = "review"
    current_step: str | None = None
    error: str | None = None
    segments_edited: bool = False
    warnings: list[str] = Field(default_factory=list)
    pruned: list[str] = Field(default_factory=list)   # intermediates deleted to save space (rebuilt on demand)
    project: str | None = None            # id of the project (e.g. one Douyin channel) this video belongs to
    film: FilmInfo | None = None          # kind "film": the movie being analyzed
    part: PartInfo | None = None          # kind "review": which part of the film this video covers
    review: ReviewSettings | None = None  # kind "review": settings of this video
