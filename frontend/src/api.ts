import type { AppSettings, BrowseListing, Context, Job, Options, Segment, Settings, Voice } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
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
  createFromPath: (path: string) => j<Job>(post("/api/jobs", { path })),
  upload: (file: File, onProgress: (p: number) => void) => new Promise<Job>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const fd = new FormData(); fd.append("file", file);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      const body = JSON.parse(xhr.responseText || "{}");
      xhr.status < 300 ? resolve(body) : reject(new ApiError(xhr.status, body.detail || xhr.statusText));
    };
    xhr.onerror = () => reject(new ApiError(0, "Lỗi mạng khi tải lên"));
    xhr.open("POST", "/api/jobs"); xhr.send(fd);
  }),
  browse: (path: string) => j<BrowseListing>(fetch(`/api/browse?path=${encodeURIComponent(path)}`)),
  appSettings: () => j<AppSettings>(fetch("/api/app-settings")),
  saveAppSettings: (s: { video_dir?: string; auto_prune?: boolean }) => j<AppSettings>(put("/api/app-settings", s)),
  storage: (id: string) => j<{ total: number; reclaimable: number }>(fetch(`/api/jobs/${id}/storage`)),
  prune: (id: string) => j<{ freed: number; total: number; reclaimable: number }>(post(`/api/jobs/${id}/prune`)),
  createVoice: (fd: FormData) => j<{ id: string; name: string; duration: number }>(fetch("/api/voices/custom", { method: "POST", body: fd })),
  deleteVoice: (name: string) => j(fetch(`/api/voices/custom/${encodeURIComponent(name)}`, { method: "DELETE" })),
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
};
