import type {
  ApiKeyInfo, AppSettings, BrowseListing, GpuStatus, VieneuDevice, Context, DyLookup, DyTask, Job, Lang, Notebook, Options, Project, ReviewProjectData,
  ReviewSettings, ScriptBlock, ScriptData, Segment, Settings, SharedGlossary, Templates, Voice, VsFilters, VsMovie, VsPage, VsTask,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string, public busy: { id: string; name: string }[] = []) { super(message); }
}

async function j<T>(r: Promise<Response>): Promise<T> {
  const res = await r;
  if (!res.ok) {
    const d = (await res.json().catch(() => ({}))).detail;
    const msg = Array.isArray(d) ? d.map((x: { msg?: string }) => x?.msg ?? JSON.stringify(x)).join("; ") : d;
    throw new ApiError(res.status, msg || res.statusText);
  }
  return res.json();
}
const JSONH = { "Content-Type": "application/json" };
const post = (url: string, body?: unknown) => fetch(url, { method: "POST", headers: JSONH, body: JSON.stringify(body ?? {}) });
const put = (url: string, body: unknown) => fetch(url, { method: "PUT", headers: JSONH, body: JSON.stringify(body) });

/** POST a form with upload progress (fetch has no upload progress). */
const send = <T>(url: string, fd: FormData, onProgress: (p: number) => void) => new Promise<T>((resolve, reject) => {
  const xhr = new XMLHttpRequest();
  xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
  xhr.onload = () => {
    let body: { detail?: string } = {};
    try { body = JSON.parse(xhr.responseText || "{}"); } catch { /* proxy error page */ }
    xhr.status < 300 ? resolve(body as T) : reject(new ApiError(xhr.status, body.detail || xhr.statusText));
  };
  xhr.onerror = () => reject(new ApiError(0, "Lỗi mạng khi tải lên"));
  xhr.open("POST", url); xhr.send(fd);
});

export type SegmentsData = { segments: Segment[]; slots: number[] };

export const api = {
  options: () => j<Options>(fetch("/api/options")),
  health: (llm?: string, model?: string) =>
    j<{ checks: { name: string; ok: boolean; hint: string }[]; llm_test?: { ok: boolean; error: string | null } }>(
      fetch(`/api/health${llm ? `?llm=${llm}&model=${encodeURIComponent(model ?? "")}` : ""}`)),
  voices: (engine: string) => j<Voice[]>(fetch(`/api/tts/${engine}/voices`)),
  voiceSample: async (engine: string, voice: string, rate: number) => {
    const res = await post("/api/tts/sample", { engine, voice, rate });
    if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).detail || res.statusText);
    return URL.createObjectURL(await res.blob());
  },
  jobs: () => j<Job[]>(fetch("/api/jobs")),
  job: (id: string) => j<Job>(fetch(`/api/jobs/${id}`)),
  createFromPath: (path: string, project?: string | null) => j<Job>(post("/api/jobs", { path, project: project || null })),
  upload: (file: File, onProgress: (p: number) => void, project?: string | null) => {
    const fd = new FormData(); fd.append("file", file);
    if (project) fd.append("project", project);
    return send<Job>("/api/jobs", fd, onProgress);
  },
  browse: (path: string) => j<BrowseListing>(fetch(`/api/browse?path=${encodeURIComponent(path)}`)),
  appSettings: () => j<AppSettings>(fetch("/api/app-settings")),
  saveAppSettings: (s: { video_dir?: string; auto_prune?: boolean; vieneu_device?: VieneuDevice }) => j<AppSettings>(put("/api/app-settings", s)),
  gpu: () => j<GpuStatus>(fetch("/api/gpu")),
  apiKeys: () => j<ApiKeyInfo[]>(fetch("/api/api-keys")),
  saveApiKey: (provider: string, key: string) => j<ApiKeyInfo[]>(put(`/api/api-keys/${provider}`, { key })),
  deleteApiKey: (provider: string) => j<ApiKeyInfo[]>(fetch(`/api/api-keys/${provider}`, { method: "DELETE" })),
  storage: (id: string) => j<{ total: number; reclaimable: number }>(fetch(`/api/jobs/${id}/storage`)),
  prune: (id: string) => j<{ freed: number; total: number; reclaimable: number }>(post(`/api/jobs/${id}/prune`)),
  createVoice: (fd: FormData) => j<{ id: string; name: string; duration: number }>(fetch("/api/voices/custom", { method: "POST", body: fd })),
  deleteVoice: (name: string) => j(fetch(`/api/voices/custom/${encodeURIComponent(name)}`, { method: "DELETE" })),
  douyinLookup: (url: string) => j<DyLookup>(post("/api/douyin/lookup", { url })),
  douyinDownload: (ids: string[], titles: Record<string, string>, preset: string | null, project: string | null) =>
    j<DyTask>(post("/api/douyin/download", { ids, titles, preset, project })),
  douyinPrepare: (ids: string[]) => j<Record<string, string | null>>(post("/api/douyin/prepare", { ids })),
  douyinFileUrl: (id: string, title: string) => `/api/douyin/file/${id}?title=${encodeURIComponent(title)}`,
  douyinTask: (id: string) => j<DyTask>(fetch(`/api/douyin/download/${id}`)),
  douyinSession: () => j<{ logged_in: boolean; login: { state: string; qr: string | null; error: string | null } | null }>(fetch("/api/douyin/session")),
  douyinLogin: () => j<{ logged_in: boolean; login: { state: string; qr: string | null; error: string | null } | null }>(post("/api/douyin/login")),
  douyinLogout: () => j<{ logged_in: boolean; login: null }>(fetch("/api/douyin/session", { method: "DELETE" })),
  batch: (paths: string[], preset: string | null, project?: string | null) =>
    j<{ results: { path?: string; job?: string; ok: boolean; error?: string }[] }>(post("/api/batch", { paths, preset, project: project || null, run: true })),
  projects: () => j<Project[]>(fetch("/api/projects")),
  createProject: (name: string, source_url = "", kind: "sub" | "audio" = "sub") => j<Project>(post("/api/projects", { name, source_url, kind })),
  updateProject: (id: string, name: string, source_url: string) => j<Project>(put(`/api/projects/${id}`, { name, source_url })),
  deleteProject: (id: string) => j<{ ok: boolean }>(fetch(`/api/projects/${id}`, { method: "DELETE" })),
  deleteProjects: async (ids: string[]) => {
    const res = await post("/api/projects/delete", { ids });
    if (res.ok) return res.json() as Promise<{ deleted_projects: number; deleted_jobs: number }>;
    const d = (await res.json().catch(() => ({}))).detail;
    if (d && typeof d === "object" && !Array.isArray(d)) throw new ApiError(res.status, d.message || res.statusText, d.busy ?? []);
    throw new ApiError(res.status, (typeof d === "string" && d) || res.statusText);
  },
  saveProjectPreset: (id: string, jobId: string) => j<Project>(post(`/api/projects/${id}/preset`, { job_id: jobId })),
  clearProjectPreset: (id: string) => j<Project>(fetch(`/api/projects/${id}/preset`, { method: "DELETE" })),
  runProject: (id: string, states: string[] = ["new"]) => j<{ queued: string[]; skipped: string[] }>(post(`/api/projects/${id}/run`, { states })),
  setJobProject: (jid: string, project: string | null, applyPreset = false) =>
    j<Job>(put(`/api/jobs/${jid}/project`, { project, apply_preset: applyPreset })),
  approve: (jid: string, approved = true) => j<Job>(post(`/api/jobs/${jid}/approve`, { approved })),
  glossary: () => j<SharedGlossary>(fetch("/api/glossary")),
  saveGlossary: (g: SharedGlossary) => j<SharedGlossary>(put("/api/glossary", g)),
  promoteGlossary: (id: string) => j<SharedGlossary>(post(`/api/jobs/${id}/glossary/promote`)),
  eta: (id: string, step?: string | null, pct = 0) =>
    j<{ steps: Record<string, number>; total: number; calibrated: boolean }>(fetch(`/api/jobs/${id}/eta?pct=${pct}${step ? `&step=${step}` : ""}`)),
  softsub: (id: string) => j(post(`/api/jobs/${id}/softsub`)),
  remove: (id: string) => j(fetch(`/api/jobs/${id}`, { method: "DELETE" })),
  saveSettings: (id: string, s: Settings) => j<Job>(put(`/api/jobs/${id}/settings`, s)),
  uploadRef: (id: string, file: File) => {
    const fd = new FormData(); fd.append("file", file);
    return j<Job>(fetch(`/api/jobs/${id}/ref-audio`, { method: "POST", body: fd }));
  },
  run: (id: string, mode: "review" | "auto", from_step?: string | null, confirm = false) =>
    j<Job>(post(`/api/jobs/${id}/run`, { mode, from_step: from_step ?? null, confirm })),
  cancel: (id: string) => j(post(`/api/jobs/${id}/cancel`)),
  context: (id: string) => j<Context>(fetch(`/api/jobs/${id}/context`)),
  saveContext: (id: string, c: Context) => j<Context>(put(`/api/jobs/${id}/context`, c)),
  segments: (id: string) => j<SegmentsData>(fetch(`/api/jobs/${id}/segments`)),
  saveSegments: (id: string, s: Segment[]) => j<SegmentsData>(put(`/api/jobs/${id}/segments`, s)),
  retranslate: (id: string, ids?: number[]) => j<SegmentsData>(post(`/api/jobs/${id}/retranslate`, { ids: ids ?? null })),
  previewTts: async (id: string, sid: number) => {
    const res = await fetch(`/api/jobs/${id}/segments/${sid}/preview-tts`, { method: "POST" });
    if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).detail || res.statusText);
    return { url: URL.createObjectURL(await res.blob()), duration: Number(res.headers.get("X-Duration") || 0) };
  },
  previewRender: (id: string, t: number) => j(post(`/api/jobs/${id}/preview-render`, { t })),
  presets: () => j<Record<string, Settings>>(fetch("/api/presets")),
  savePreset: (name: string, settings: Settings) => j<Record<string, Settings>>(post("/api/presets", { name, settings })),
  deletePreset: (name: string) => j<Record<string, Settings>>(fetch(`/api/presets/${encodeURIComponent(name)}`, { method: "DELETE" })),
  file: (id: string, name: string, bust?: number | string) => `/api/jobs/${id}/files/${name}${bust ? `?v=${bust}` : ""}`,
  download: (id: string, name: string) => `/api/jobs/${id}/files/${name}?download=1`,

  // ---- review phim
  vsHome: (page = 1) => j<VsPage>(fetch(`/api/vsmov/home?page=${page}`)),
  vsSearch: (q: string, page = 1) => j<VsPage>(fetch(`/api/vsmov/search?q=${encodeURIComponent(q)}&page=${page}`)),
  vsList: (kind: "phim-le" | "phim-bo" | "the-loai" | "quoc-gia", slug = "", page = 1) =>
    j<VsPage>(fetch(`/api/vsmov/list?kind=${kind}&slug=${encodeURIComponent(slug)}&page=${page}`)),
  vsFilters: () => j<VsFilters>(fetch("/api/vsmov/filters")),
  vsMovie: (slug: string) => j<VsMovie>(fetch(`/api/vsmov/movie/${encodeURIComponent(slug)}`)),
  reviewTemplates: () => j<Templates>(fetch("/api/review/templates")),
  createReview: (slug: string, server: string) => j<Project>(post("/api/review/projects", { slug, server })),
  uploadReview: (file: File, lang: Lang, onProgress: (p: number) => void) => {
    const fd = new FormData(); fd.append("file", file); fd.append("lang", lang);
    return send<Project>("/api/review/projects/upload", fd, onProgress);
  },
  reviewProject: (pid: string) => j<ReviewProjectData>(fetch(`/api/review/projects/${pid}`)),
  deleteReview: (pid: string) => j<{ ok: boolean }>(fetch(`/api/review/projects/${pid}`, { method: "DELETE" })),
  prepareEpisode: (pid: string, slug: string) => j<VsTask>(post(`/api/review/projects/${pid}/episodes/${encodeURIComponent(slug)}/prepare`)),
  saveReviewSettings: (pid: string, settings: ReviewSettings, job_settings: Settings | null = null, parts_per_episode: 1 | 2 | null = null) =>
    j<Project>(put(`/api/review/projects/${pid}/settings`, { settings, job_settings, parts_per_episode })),
  proposeSplit: (pid: string, film_job: string, by: { parts?: number; minutes?: number }) =>
    j<{ cuts: number[] }>(post(`/api/review/projects/${pid}/split`, { film_job, ...by })),
  saveParts: (pid: string, film_job: string, cuts: number[]) => j<Project>(put(`/api/review/projects/${pid}/parts`, { film_job, cuts })),
  uploadMusic: (pid: string, file: File) => {
    const fd = new FormData(); fd.append("file", file);
    return j<Project>(fetch(`/api/review/projects/${pid}/music`, { method: "POST", body: fd }));
  },
  musicUrl: (pid: string, bust: string | number) => `/api/review/projects/${pid}/music?v=${encodeURIComponent(bust)}`,
  deleteMusic: (pid: string) => j<Project>(fetch(`/api/review/projects/${pid}/music`, { method: "DELETE" })),
  notebook: (pid: string) => j<Notebook>(fetch(`/api/review/projects/${pid}/notebook`)),
  saveNotebook: (pid: string, nb: Notebook) => j<Notebook>(put(`/api/review/projects/${pid}/notebook`, nb)),
  script: (jid: string) => j<ScriptData>(fetch(`/api/jobs/${jid}/script`)),
  saveScript: (jid: string, blocks: ScriptBlock[]) => j<ScriptData>(put(`/api/jobs/${jid}/script`, blocks)),
  rewriteScript: (jid: string) => j<Job>(post(`/api/jobs/${jid}/script/rewrite`)),
  rewriteBlock: (jid: string, bid: number, instruction = "") => j<ScriptBlock>(post(`/api/jobs/${jid}/script/blocks/${bid}/rewrite`, { instruction })),
  saveJobReviewSettings: (jid: string, s: ReviewSettings) => j<Job>(put(`/api/jobs/${jid}/review-settings`, s)),
  reviewPreview: (jid: string, t: number) => j<{ url: string; duration: number }>(post(`/api/jobs/${jid}/review-preview`, { t })),
  thumbUrl: (jid: string, t: number) => `/api/jobs/${jid}/thumb?t=${t.toFixed(1)}`,

  // ---- truyện audio
  saveAudio: (pid: string, s: { engine?: string; voice?: string; rate?: number; music_volume?: number }) => j<Project>(put(`/api/projects/${pid}/audio`, s)),
  audioBgBase: (pid: string) => `/api/projects/${pid}/audio/background`,
  audioBgUrl: (pid: string, bust: string | number) => `/api/projects/${pid}/audio/background?v=${encodeURIComponent(bust)}`,
  uploadAudioMusic: (pid: string, file: File) => {
    const fd = new FormData(); fd.append("file", file);
    return j<Project>(fetch(`/api/projects/${pid}/audio/music`, { method: "POST", body: fd }));
  },
  audioMusicUrl: (pid: string, bust: string | number) => `/api/projects/${pid}/audio/music?v=${encodeURIComponent(bust)}`,
  deleteAudioMusic: (pid: string) => j<Project>(fetch(`/api/projects/${pid}/audio/music`, { method: "DELETE" })),
  uploadScript: (pid: string, file: File, run: boolean, onProgress: (p: number) => void) => {
    const fd = new FormData(); fd.append("file", file);
    return send<Job>(`/api/projects/${pid}/audio/scripts?run=${run ? 1 : 0}`, fd, onProgress);
  },
};
