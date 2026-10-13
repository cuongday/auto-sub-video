import { useRef, useState } from "react";
import { api } from "../api";
import type { Job } from "../types";

export default function NewJob({ onCreated }: { onCreated: (j: Job) => void }) {
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [over, setOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  // open the picker explicitly: label-wrapped hidden inputs are flaky in some browsers/portals
  const pick = () => { if (!busy) fileInput.current?.click(); };

  const upload = async (f: File) => {
    setErr(""); setBusy("Đang tải lên 0%");
    try { onCreated(await api.upload(f, (p) => setBusy(p < 1 ? `Đang tải lên ${Math.round(p * 100)}%` : "Đang đọc video…"))); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };
  const fromPath = async () => {
    setErr(""); setBusy("Đang đọc video…");
    try { onCreated(await api.createFromPath(path.trim())); } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };
  return (
    <section className="card new-job">
      <h2>Video mới</h2>
      <div className={`drop ${over ? "over" : ""} ${busy ? "busy" : ""}`} role="button" tabIndex={0}
        aria-label="Chọn video để tải lên" aria-disabled={!!busy} onClick={pick}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } }}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f && !busy) upload(f); }}>
        <input ref={fileInput} type="file" accept="video/*,.mkv,.flv,.ts" hidden
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) upload(f); }} />
        <strong>{busy || "Kéo thả video vào đây"}</strong>
        <span className="muted">{busy ? "" : "hoặc bấm để chọn file · video tiếng Trung hoặc tiếng Anh"}</span>
      </div>
      <div className="or"><span>hoặc dùng file có sẵn trên máy (không phải copy)</span></div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); if (path.trim()) fromPath(); }}>
        <input className="grow" value={path} onChange={(e) => setPath(e.target.value)} placeholder="/home/ban/Videos/phim.mp4" aria-label="Đường dẫn video" />
        <button className="primary" disabled={!path.trim() || !!busy}>Mở</button>
      </form>
      {err && <p className="error" role="alert">{err}</p>}
    </section>
  );
}
