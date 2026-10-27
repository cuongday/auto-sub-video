import { ApiError } from "./api";
import type { Project } from "./types";

const RETRIES = 3;                 // per request, after the first try: waits 1, 2, 4 s
const CHUNK_MAX = 64 << 20;        // Cloudflare Tunnel rejects bodies over 100 MB
const TIMEOUT = 120_000;           // a stalled request (dropped LAN/Wi-Fi) is retried instead of hanging forever

const aborted = () => new DOMException("Đã huỷ tải lên", "AbortError");
const wait = (ms: number, signal?: AbortSignal) => new Promise<void>((resolve, reject) => {
  if (signal?.aborted) return reject(aborted());
  const t = window.setTimeout(() => { signal?.removeEventListener("abort", stop); resolve(); }, ms);
  const stop = () => { window.clearTimeout(t); reject(aborted()); };
  signal?.addEventListener("abort", stop, { once: true });
});

/** One request through XHR (upload progress, abort). Rejects with ApiError; status 0 = network error. */
function xhr<T>(method: string, url: string, body: Blob | string | null, onProgress?: (loaded: number) => void, signal?: AbortSignal) {
  return new Promise<T>((resolve, reject) => {
    if (signal?.aborted) return reject(aborted());
    const x = new XMLHttpRequest();
    const stop = () => x.abort();
    signal?.addEventListener("abort", stop, { once: true });
    const done = () => signal?.removeEventListener("abort", stop);
    if (onProgress) x.upload.onprogress = (e) => onProgress(e.loaded);
    x.onload = () => {
      done();
      let d: { detail?: unknown } = {};
      try { d = JSON.parse(x.responseText || "{}"); } catch { /* proxy error page */ }
      if (x.status < 300) resolve(d as T);
      else reject(new ApiError(x.status, typeof d.detail === "string" ? d.detail : x.statusText || `HTTP ${x.status}`));
    };
    x.onerror = () => { done(); reject(new ApiError(0, "Lỗi mạng khi tải lên")); };
    x.ontimeout = () => { done(); reject(new ApiError(0, "Hết thời gian chờ khi tải lên")); };
    x.onabort = () => { done(); reject(aborted()); };
    x.open(method, url);
    x.timeout = TIMEOUT;
    if (typeof body === "string") x.setRequestHeader("Content-Type", "application/json");
    x.send(body);
  });
}

/** Network errors, timeouts and server/proxy 5xx are worth another try; 4xx answers are final. */
const retryable = (e: unknown) => e instanceof ApiError && (e.status === 0 || e.status >= 500 || e.status === 408 || e.status === 429);

async function withRetry<T>(fn: () => Promise<T>, signal?: AbortSignal): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try { return await fn(); } catch (e) {
      if (attempt >= RETRIES || !retryable(e)) throw e;
      await wait(1000 * 2 ** attempt, signal);
    }
  }
}

/** Test hook: a smaller slice size so chunking can be exercised with a small file. Never above the server's
 *  size and never below 64 KB, so a stray value cannot turn one upload into thousands of requests. */
const sliceSize = (server: number) => {
  const o = Number((globalThis as { __AUTOSUB_CHUNK?: number }).__AUTOSUB_CHUNK);
  return Math.min(server || CHUNK_MAX, CHUNK_MAX, o > 0 ? Math.max(o, 64 << 10) : Infinity);
};

/** Upload a large file to `${url}/start`, `${url}/{id}?offset=N` (one slice per request) and `${url}/{id}/finish`.
 *  Each request is retried 3 times (1/2/4 s) on network errors; finish is idempotent so it is retried too. */
export async function uploadChunked(url: string, file: File, onProgress: (p: number) => void, signal?: AbortSignal,
  onUploadId?: (id: string) => void): Promise<Project> {
  const { upload_id: id, chunk_size } = await withRetry(
    () => xhr<{ upload_id: string; chunk_size: number }>("POST", `${url}/start`, JSON.stringify({ name: file.name, size: file.size }), undefined, signal), signal);
  onUploadId?.(id);
  const step = sliceSize(chunk_size);
  onProgress(0);
  for (let off = 0; off < file.size; off += step) {
    const slice = file.slice(off, Math.min(off + step, file.size));
    await withRetry(() => xhr("PUT", `${url}/${id}?offset=${off}`, slice, (n) => onProgress((off + n) / file.size), signal), signal);
    onProgress(Math.min(1, (off + slice.size) / file.size));
  }
  return finishUpload(url, id, signal);
}

/** Finish (or re-finish: idempotent, re-queues a failed store/normalize from the file already on the server). */
export const finishUpload = (url: string, id: string, signal?: AbortSignal) =>
  withRetry(() => xhr<Project>("POST", `${url}/${id}/finish`, null, undefined, signal), signal);
