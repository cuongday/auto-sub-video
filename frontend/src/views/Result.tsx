import { useState } from "react";
import { api } from "../api";
import { canPickLocation, saveFile } from "../save";
import type { Job } from "../types";

const FILES = [
  { name: "output.mp4", label: "Tải video (.mp4)", suffix: ".vi.mp4", primary: true },
  { name: "subs.srt", label: "Phụ đề .srt", suffix: ".vi.srt" },
  { name: "subs.ass", label: "Phụ đề .ass", suffix: ".vi.ass" },
  { name: "voice.wav", label: "Giọng thuyết minh .wav", suffix: ".voice.wav" },
];

export default function Result({ job, onEdit, onSetup }: { job: Job; onEdit: () => void; onSetup: () => void }) {
  const bust = job.steps.render.hash ?? "";
  const stem = job.name.replace(/\.[^.]+$/, "");
  const [busy, setBusy] = useState<string | null>(null);
  const [pct, setPct] = useState(0);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const pickable = canPickLocation();

  const save = async (f: (typeof FILES)[number]) => {
    const fname = stem + f.suffix;
    setBusy(f.name); setPct(0); setMsg(null);
    try {
      const r = await saveFile(api.download(job.id, f.name), fname, setPct);
      if (r === "saved") setMsg({ kind: "ok", text: `Đã lưu ${fname}` });
    } catch (e) {
      setMsg({ kind: "err", text: `Lưu ${fname} thất bại: ${(e as Error).message}` });
    } finally { setBusy(null); }
  };

  return (
    <section className="card">
      <header className="card-head">
        <h2>Thành phẩm</h2>
        <div className="row">
          <button className="ghost" onClick={onEdit}>Quay lại sửa phụ đề</button>
          <button className="ghost" onClick={onSetup}>Đổi vùng che / tuỳ chọn</button>
        </div>
      </header>
      {job.warnings.map((w) => <p key={w} className="warn">{w}</p>)}
      {job.info && (
        <video className="result" src={api.file(job.id, "output.mp4", bust)} controls
          style={{ aspectRatio: `${job.info.width} / ${job.info.height}`, width: `min(100%, calc(70vh * ${job.info.width / job.info.height}))` }} />
      )}
      <div className="downloads">
        {FILES.filter((f) => job.files[f.name]).map((f) => (
          <button key={f.name} className={f.primary ? "primary" : "ghost"} disabled={!!busy} onClick={() => save(f)}>
            {busy === f.name ? (pct ? `Đang lưu… ${Math.round(pct * 100)}%` : "Đang lưu…") : f.label}
          </button>
        ))}
      </div>
      <p className="muted small">
        {pickable
          ? "Bấm tải sẽ mở hộp thoại để chọn thư mục và tên file; lần sau tự mở lại thư mục đã chọn."
          : "Trình duyệt này lưu theo cài đặt tải xuống của nó. Bật “Hỏi nơi lưu mỗi tệp trước khi tải xuống” trong cài đặt trình duyệt để chọn thư mục, hoặc dùng Chrome / Edge."}
      </p>
      {msg && <p className={msg.kind === "ok" ? "ok-msg" : "error"} role="status">{msg.text}</p>}
    </section>
  );
}
