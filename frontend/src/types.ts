export type Lang = "zh" | "en";
export type Cover = "blur" | "blur_dim" | "solid";
export type Region = { x: number; y: number; w: number; h: number };
export type SubStyle = { font_size: number | null; color: string; outline_color: string; outline: number | null };
export type Settings = {
  lang: Lang; asr_model: string; llm_provider: "gemini" | "openai"; llm_model: string; translator_notes: string;
  tts_engine: "edge" | "vieneu"; tts_voice: string; tts_rate: number; ref_audio: string | null;
  region: Region; cover: Cover; cover_color: string; style: SubStyle; bg_volume_db: number;
};
export type StepStatus = "pending" | "running" | "done" | "error";
export type StepState = { status: StepStatus; hash: string | null; seconds: number | null; error: string | null };
export type JobState = "new" | "queued" | "running" | "awaiting_review" | "done" | "error" | "interrupted" | "cancelled";
export type VideoInfo = { width: number; height: number; duration: number; fps: number; has_audio: boolean };
export type Job = {
  id: string; name: string; created: number; source: string; uploaded: boolean; info: VideoInfo | null;
  settings: Settings; steps: Record<string, StepState>; state: JobState; mode: "review" | "auto";
  current_step: string | null; error: string | null; segments_edited: boolean; warnings: string[];
  frames: string[]; files: Record<string, boolean>; stale_from: string | null;
};
export type Segment = { id: number; start: number; end: number; source: string; vi: string; flags: string[]; speed: number | null };
export type Character = { name: string; vi_name: string; addressing: string };
export type Context = { summary: string; genre_tone: string; characters: Character[]; glossary: { source: string; vi: string }[] };
export type Option = { id: string; label: string };
export type Voice = Option & { gender?: string; featured?: boolean; default?: boolean };
export type EngineOk = { ok: boolean; hint: string };
export type Options = {
  asr: Record<Lang, Option[]>;
  llm: Record<"gemini" | "openai", { default: string; models: Option[] }>;
  tts: { edge: Voice[] };
  engines: { separate: EngineOk; asr: Record<Lang, EngineOk>; llm: Record<string, EngineOk>; tts: Record<string, EngineOk> };
  steps: string[];
  defaults: Settings;
};
export type JobEvent =
  | { type: "state"; job: string; state: JobState; error?: string; t: number }
  | { type: "progress"; job: string; step: string; pct: number; t: number }
  | { type: "log"; job: string; msg: string; t: number };
