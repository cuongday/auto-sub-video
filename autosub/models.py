from typing import Literal
from pydantic import BaseModel, Field, model_validator

Lang = Literal["zh", "en"]
STEPS = ["probe", "extract", "separate", "asr", "segment", "translate", "tts", "fit", "mix", "render"]

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

class SubStyle(BaseModel):
    font_size: int | None = None          # None -> auto from region height
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
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
    cover: Literal["blur", "blur_dim", "solid"] = "blur_dim"
    cover_color: str = "#000000"
    style: SubStyle = Field(default_factory=SubStyle)
    bg_volume_db: float = Field(0.0, ge=-30, le=10)

class Word(BaseModel):
    text: str
    start: float
    end: float

class Segment(BaseModel):
    id: int
    start: float
    end: float
    source: str
    vi: str = ""
    flags: list[str] = Field(default_factory=list)
    speed: float | None = None            # actual speed-up applied by the fit step

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

JobState = Literal["new", "queued", "running", "awaiting_review", "done", "error", "interrupted", "cancelled"]

class Job(BaseModel):
    id: str
    name: str
    created: float
    source: str                           # absolute path of the video
    uploaded: bool = False                # source lives inside the job dir
    info: VideoInfo | None = None
    settings: JobSettings = Field(default_factory=JobSettings)
    steps: dict[str, StepState] = Field(default_factory=lambda: {s: StepState() for s in STEPS})
    state: JobState = "new"
    mode: Literal["review", "auto"] = "review"
    current_step: str | None = None
    error: str | None = None
    segments_edited: bool = False
    warnings: list[str] = Field(default_factory=list)
