import { useEffect, useState } from "react";
import { api } from "../api";
import { finishUpload, uploadChunked } from "../chunkUpload";
import { fmtClock } from "../labels";
import type { JobEvent, Project } from "../types";
import { useEvents } from "../useEvents";

const VIDEO_EXT = [".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv", ".m4v", ".ts"];
const BG_MAX = 1 << 30;
const idKey = (pid: string) => `autosub.bgUpload.${pid}`;
const readId = (pid: string) => { try { return localStorage.getItem(idKey(pid)); } catch { return null; } };
const saveId = (pid: string, id: string) => { try { localStorage.setItem(idKey(pid), id); } catch { /* private mode */ } };
/** Uploads live outside the component: switching to another screen does not abort a 1 GB upload, and coming
 *  back shows its progress again. Cancelled only by "Huỷ tải lên". */
type Up = { name: string; size: number; pct: number; ctl: AbortController; err: string };
const uploads = new Map<string, Up>();
const errors = new Map<string, string>();
const subs = new Set<() => void>();
const notify = () => subs.forEach((f) => f());
/** Stop a background upload of a story (it is being deleted). */
export const abortBgUpload = (pid: string) => uploads.get(pid)?.ctl.abort();
const mb = (n: number) => n >= 1 << 30 ? `${(n / (1 << 30)).toFixed(2)} GB` : `${Math.max(1, Math.round(n / (1 << 20)))} MB`;

/** The story's background video: chunked upload (64 MB per request, under the tunnel's limit), then a one-time
 *  normalization on the server (task "bg:{pid}") whose progress arrives over SSE; preview once there is a file. */
export default function AudioBackground({ project, onChanged }: { project: Project; onChanged: (p?: Project) => void }) {
  const pid = project.id;
  const a = project.audio!;
  const [, tick] = useState(0);
  useEffect(() => { const f = () => tick((n) => n + 1); subs.add(f); return () => { subs.delete(f); }; }, []);
  const up = uploads.get(pid) ?? null;
  const [norm, setNorm] = useState<number | null>(null);        // normalization progress 0..1 from SSE
  const err = errors.get(pid) ?? "";
  const setErr = (m: string) => { if (m) errors.set(pid, m); else errors.delete(pid); notify(); };
  const [retrying, setRetrying] = useState(false);
  useEffect(() => { if (a.background_state !== "processing") setNorm(null); }, [a.background_state]);

  useEvents((e: JobEvent) => {
    if (e.type === "task_progress" && e.key === `bg:${pid}`) setNorm(e.pct);
    else if (e.type === "task" && e.key === `bg:${pid}`) {
      if (e.state === "running" || e.state === "queued") setNorm((n) => n ?? 0);
      else onChanged();                      // done / error / cancelled: the project holds the new state
    }
  });

  const upload = async (file: File) => {
    setErr("");
    if (!VIDEO_EXT.some((x) => file.name.toLowerCase().endsWith(x))) { setErr(`Định dạng video không hỗ trợ (${VIDEO_EXT.map((x) => x.slice(1)).join(", ")})`); return; }
    if (file.size > BG_MAX) { setErr("Video nền quá lớn (tối đa 1 GB)"); return; }
    const u: Up = { name: file.name, size: file.size, pct: 0, ctl: new AbortController(), err: "" };
    uploads.set(pid, u); notify();
    try {
      onChanged(await uploadChunked(api.audioBgBase(pid), file, (pct) => { u.pct = pct; notify(); }, u.ctl.signal, (id) => saveId(pid, id)));
    } catch (e) {
      if ((e as Error).name !== "AbortError") setErr(`Tải video nền lỗi: ${(e as Error).message}`);
    } finally { uploads.delete(pid); notify(); }
  };
  /** finish is idempotent: called again it re-queues the failed store/normalize from the file already uploaded. */
  const retry = async () => {
    const id = readId(pid);
    setRetrying(true); setErr("");
    try {
      if (!id) throw new Error("Không còn phiên tải lên trước, hãy chọn lại file video nền");
      onChanged(await finishUpload(api.audioBgBase(pid), id));
    } catch (e) { setErr(`${(e as Error).message}. Nếu vẫn lỗi, hãy chọn lại file video nền.`); } finally { setRetrying(false); }
  };

  const info = a.background_info;
  const st = a.background_state;
  const badge = up ? <span className="badge s-running">Đang tải lên {Math.round(up.pct * 100)}%</span>
    : st === "processing" ? <span className="badge s-running">Đang chuẩn hoá{norm != null ? ` ${Math.round(norm * 100)}%` : "…"}</span>
    : st === "ready" ? <span className="badge s-done">Sẵn sàng</span>
    : st === "error" ? <span className="badge s-error">Lỗi</span>
    : <span className="badge">Chưa có</span>;
  const bar = up ? up.pct : st === "processing" ? norm ?? 0 : null;

  return (
    <div className="ap-bg">
      <div className="ap-label">
        <strong>Video nền</strong> {badge}
        {info && <span className="muted small">{fmtClock(info.duration)} · {info.width}×{info.height}</span>}
      </div>
      {a.background && !up && (
        <video className="ap-video" controls preload="metadata" src={api.audioBgUrl(pid, `${a.background}-${st}-${a.background_etag ?? a.rev}`)} />
      )}
      {bar != null && (
        <span className="dy-bar" role="progressbar" aria-label={up ? "Tải video nền lên" : "Chuẩn hoá video nền"}
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(bar * 100)}><span style={{ width: `${Math.round(bar * 100)}%` }} /></span>
      )}
      {up && <p className="muted small">{up.name} · {mb(up.pct * up.size)} / {mb(up.size)} · gửi từng mảnh 64 MB, tự gửi lại mảnh lỗi</p>}
      {st === "processing" && !up && <p className="muted small">Đang chuyển video nền về một định dạng chung để ghép nhanh. Làm một lần, mọi phần dùng chung.</p>}
      {st === "error" && !up && <p className="error small" role="alert">{a.background_error || "Chuẩn hoá video nền lỗi"}</p>}
      {err && <p className="error small" role="alert">{err}</p>}
      <div className="row">
        {up ? <button className="ghost small danger" onClick={() => up.ctl.abort()}>Huỷ tải lên</button> : (
          <label className="btn ghost small rp-file">
            {a.background ? "Đổi video nền" : "Chọn video nền"}
            <input type="file" accept={VIDEO_EXT.join(",") + ",video/*"} className="sr-only" disabled={retrying} onChange={(e) => {
              const f = e.target.files?.[0]; e.target.value = "";
              if (f) upload(f);
            }} />
          </label>
        )}
        {st === "error" && !up && <button className="ghost small" disabled={retrying} onClick={retry}>{retrying ? "Đang thử lại…" : "Thử lại"}</button>}
        {!a.background && !up && <span className="muted small">{VIDEO_EXT.map((x) => x.slice(1)).join(", ")} · tối đa 1 GB · tự lặp nếu ngắn hơn giọng đọc</span>}
      </div>
    </div>
  );
}
