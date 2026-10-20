export type Lang = "zh" | "en" | "ko";
export type Cover = "blur" | "blur_dim" | "solid";
export type Region = { x: number; y: number; w: number; h: number };
export type SubStyle = { font: string; font_size: number | null; color: string; outline_color: string; outline: number | null };
export type FontOption = { id: string; label: string; family: string; weight: number; file: string };
export type Settings = {
  lang: Lang; asr_model: string; llm_provider: "gemini" | "openai"; llm_model: string; translator_notes: string;
  tts_engine: "edge" | "vieneu"; tts_voice: string; tts_rate: number; ref_audio: string | null;
  region: Region; extra_regions: Region[]; cover: Cover; cover_color: string; style: SubStyle; bg_volume_db: number; separate: boolean; duck_db: number; diarize: boolean; speaker_voices: Record<string, string>; text_source: "asr" | "ocr";
};
export type StepStatus = "pending" | "running" | "done" | "error";
export type StepState = { status: StepStatus; hash: string | null; seconds: number | null; error: string | null };
export type JobState = "new" | "queued" | "running" | "awaiting_review" | "done" | "approved" | "error" | "interrupted" | "cancelled";
export type VideoInfo = { width: number; height: number; duration: number; fps: number; has_audio: boolean };
export type JobKind = "sub" | "film" | "review";
export type SubTrack = { code: string; url: string };
export type MovieMeta = {
  slug: string; name: string; origin_name: string; year: number | null; type: string; poster_url: string; thumb_url: string;
  time: string; lang: string; content: string; actors: string[]; directors: string[]; categories: string[]; countries: string[];
};
export type Episode = { name: string; slug: string; embed: string };
export type FilmInfo = { episode: Episode | null; episode_index: number; subtitles: SubTrack[]; subtitle: string | null };
export type PartInfo = { film_job: string; index: number; start: number; end: number; notebook_rev: number };
export type ReviewSettings = {
  minutes: number; aspect: "16:9" | "9:16"; style: string; hook: string; use_hook: boolean; opening: string; notes: string; spoil_ending: boolean;
  subtitles: boolean; music_db: number; music_duck: boolean; cover_regions: Region[]; cover: Cover;
};
export type TimeSpan = { start: number; end: number };
export type ScriptBlock = {
  id: number; kind: "hook" | "mo_dau" | "than" | "ket"; text: string; scenes: TimeSpan[];
  source_start: number | null; source_end: number | null; template: string; edited: boolean;
};
export type ScriptData = { blocks: ScriptBlock[]; estimate: number; target: number };
export type NotebookCharacter = { name: string; aliases: string[]; role: string; relations: string; arc: string };
export type NotebookEntry = {
  job: string; index: number; range_label: string; summary: string; ending: string; open_threads: string[]; hooks: string[]; rev: number;
};
export type Notebook = { entries: NotebookEntry[]; characters: NotebookCharacter[]; voice: string; rev: number; shared_rev: number };
export type Template = { id: string; label: string; prompt: string };
export type Templates = { styles: Template[]; hooks: Template[]; openings: Template[] };
export type Job = {
  id: string; name: string; created: number; source: string; uploaded: boolean; info: VideoInfo | null; kind: JobKind;
  settings: Settings; steps: Record<string, StepState>; state: JobState; mode: "review" | "auto";
  current_step: string | null; error: string | null; segments_edited: boolean; warnings: string[];
  frames: string[]; files: Record<string, boolean>; stale_from: string | null; pruned: string[]; project: string | null;
  film: FilmInfo | null; part: PartInfo | null; review: ReviewSettings | null; flow: { steps: string[]; review_stop: string | null };
  notebook_stale?: boolean; film_state?: JobState | null; prev_approved?: boolean;   // review parts only
};
export type Segment = { id: number; start: number; end: number; source: string; vi: string; flags: string[]; speed: number | null; speaker?: number | null };
export type Character = { name: string; vi_name: string; addressing: string };
export type Context = { summary: string; genre_tone: string; characters: Character[]; glossary: { source: string; vi: string }[] };
export type Option = { id: string; label: string };
export type Voice = Option & { gender?: string; featured?: boolean; default?: boolean; custom?: boolean };
export type EngineOk = { ok: boolean; hint: string };
export type Options = {
  asr: Record<Lang, Option[]>;
  llm: Record<"gemini" | "openai", { default: string; models: Option[] }>;
  tts: { edge: Voice[] };
  engines: { separate: EngineOk; ocr: EngineOk; asr: Record<Lang, EngineOk>; llm: Record<string, EngineOk>; tts: Record<string, EngineOk> };
  steps: string[];
  fonts: FontOption[];
  defaults: Settings;
};
export type JobEvent =
  | { type: "state"; job: string; state: JobState; error?: string; t: number }
  | { type: "progress"; job: string; step: string; pct: number; t: number }
  | { type: "log"; job: string; msg: string; t: number }
  | { type: "vsmov"; task: string };
export type BrowseEntry = { name: string; path: string };
export type BrowseFile = BrowseEntry & { size: number; mtime: number };
export type BrowseListing = { path: string; parent: string | null; dirs: BrowseEntry[]; files: BrowseFile[] };
export type VieneuDevice = "auto" | "cpu" | "cuda";
export type AppSettings = { video_dir: string; browse_available: boolean; auto_prune: boolean; vieneu_device: VieneuDevice };
export type GpuStatus = {
  requested: VieneuDevice; device: "cpu" | "cuda"; note: string;
  cuda: { available: boolean; name: string; vram_gb: number; capability: string; torch: string; cuda: string; reason: string };
};
export type DyItem = { id: string; title: string; duration: number; cover: string; created: number; width: number; height: number; size: number; is_images: boolean };
export type DyLookup = { kind: "video" | "channel"; name?: string; sec_uid?: string; items: DyItem[]; complete: boolean; logged_in: boolean };
export type DyTask = { id: string; done: boolean; items: { id: string; title: string; state: string; pct: number; job: string | null; error: string | null }[] };
export type SharedGlossary = { terms: { source: string; vi: string }[]; characters: Character[] };
export type ReviewProject = {
  source: "upload" | "vsmov"; movie: MovieMeta; server: string; episodes: Episode[]; parts_per_episode: 1 | 2;
  settings: ReviewSettings; job_settings: Settings | null; music: string | null; notebook: Notebook;
};
export type Project = {
  id: string; name: string; source_url: string; created: number; preset: Settings | null; preset_from: string | null;
  kind: "sub" | "review"; review: ReviewProject | null;
  jobs: number; counts: Partial<Record<JobState, number>>;
};
export type VsTask = { id: string; project: string; episode: string; name: string; state: "queued" | "running" | "done" | "error"; pct: number; job: string | null; error: string | null };
export type ReviewProjectData = { project: Project; films: Job[]; parts: Job[]; tasks: VsTask[] };
export type VsCard = { slug: string; name: string; origin_name: string; year: number | null; poster: string; thumb: string; rating: number | null };
export type VsPage = { items: VsCard[]; page: number; total_pages: number };
export type VsFilters = { genres: { name: string; slug: string }[]; countries: { name: string; slug: string }[] };
export type VsMovie = { meta: MovieMeta; servers: { name: string; episodes: Episode[] }[]; default_server: string };
