import { useState } from "react";
import { api } from "../api";
import type { Job } from "../types";

export default function NewJob({ onCreated }: { onCreated: (j: Job) => void }) {
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [over, setOver] = useState(false);

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
      <label className={`drop ${over ? "over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) upload(f); }}>
        <input type="file" accept="video/*,.mkv,.flv,.ts" hidden disabled={!!busy}
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        <strong>{busy || "Kéo thả video vào đây"}</strong>
        <span className="muted">{busy ? "" : "hoặc bấm để chọn file · video tiếng Trung hoặc tiếng Anh"}</span>
      </label>
      <div className="or"><span>hoặc dùng file có sẵn trên máy (không phải copy)</span></div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); if (path.trim()) fromPath(); }}>
        <input className="grow" value={path} onChange={(e) => setPath(e.target.value)} placeholder="/home/ban/Videos/phim.mp4" aria-label="Đường dẫn video" />
        <button className="primary" disabled={!path.trim() || !!busy}>Mở</button>
      </form>
      {err && <p className="error" role="alert">{err}</p>}
    </section>
  );
}
