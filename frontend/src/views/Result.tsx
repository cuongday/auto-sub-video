import { useEffect, useState } from "react";
import { api } from "../api";
import { canPickLocation, saveFile } from "../save";
import type { Job } from "../types";

const FILES = [
  { name: "output.mp4", label: "Tải video (.mp4)", suffix: ".vi.mp4", primary: true },
  { name: "output_softsub.mp4", label: "Video + phụ đề mềm (.mp4)", suffix: ".vi.softsub.mp4" },
  { name: "subs.srt", label: "Phụ đề .srt", suffix: ".vi.srt" },
  { name: "subs.ass", label: "Phụ đề .ass", suffix: ".vi.ass" },
  { name: "voice.wav", label: "Giọng thuyết minh .wav", suffix: ".voice.wav" },
];

export default function Result({ job, onEdit, onSetup, onRefresh }: { job: Job; onEdit: () => void; onSetup: () => void; onRefresh?: () => void }) {
  const bust = job.steps.render.hash ?? "";
  const stem = job.name.replace(/\.[^.]+$/, "");
  const [busy, setBusy] = useState<string | null>(null);
  const [pct, setPct] = useState(0);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const pickable = canPickLocation();
  const [storage, setStorage] = useState<{ total: number; reclaimable: number } | null>(null);
  const [autoPrune, setAutoPrune] = useState(false);
  useEffect(() => {
    api.storage(job.id).then(setStorage).catch(() => {});
    api.appSettings().then((a) => setAutoPrune(a.auto_prune)).catch(() => {});
  }, [job.id, job.steps.render.hash]);
  const mb = (n: number) => `${Math.max(1, Math.round(n / (1 << 20)))} MB`;

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
      {!job.files["output_softsub.mp4"] && job.files["output.mp4"] && (
        <p className="muted small">
          <button className="link" disabled={!!busy} onClick={async () => {
            setBusy("softsub"); setMsg(null);
            try { await api.softsub(job.id); onRefresh?.(); setMsg({ kind: "ok", text: "Đã tạo bản có phụ đề mềm" }); }
            catch (e) { setMsg({ kind: "err", text: (e as Error).message }); } finally { setBusy(null); }
          }}>{busy === "softsub" ? "Đang tạo…" : "Tạo bản có phụ đề mềm"}</button>
          {" "}— thêm phụ đề tiếng Việt thành một track bật/tắt được trong trình phát (vẫn giữ sub in cứng).
        </p>
      )}
      <p className="muted small">
        {pickable
          ? "Bấm tải sẽ mở hộp thoại để chọn thư mục và tên file; lần sau tự mở lại thư mục đã chọn."
          : "Trình duyệt này lưu theo cài đặt tải xuống của nó. Bật “Hỏi nơi lưu mỗi tệp trước khi tải xuống” trong cài đặt trình duyệt để chọn thư mục, hoặc dùng Chrome / Edge."}
      </p>
      {msg && <p className={msg.kind === "ok" ? "ok-msg" : "error"} role="status">{msg.text}</p>}
      {storage && (
        <div className="storage-box">
          <div className="row">
            <span>Dung lượng job trên MinIO: <strong>{mb(storage.total)}</strong>
              {storage.reclaimable > 0 && <> · dữ liệu tạm có thể dọn: <strong>{mb(storage.reclaimable)}</strong></>}</span>
            <span className="grow" />
            {storage.reclaimable > 0 && (
              <button className="ghost" disabled={!!busy} onClick={async () => {
                setBusy("prune");
                try { const r = await api.prune(job.id); setStorage(r); setMsg({ kind: "ok", text: `Đã dọn ${mb(r.freed)}` }); }
                catch (e) { setMsg({ kind: "err", text: (e as Error).message }); } finally { setBusy(null); }
              }}>{busy === "prune" ? "Đang dọn…" : "Dọn dữ liệu tạm"}</button>
            )}
          </div>
          <p className="muted small">Chỉ xoá file âm thanh trung gian. Thành phẩm, phụ đề, video gốc và kết quả tách giọng được giữ, nên sửa và render lại vẫn nhanh.</p>
          <label className="inline small">
            <input type="checkbox" checked={autoPrune} onChange={async (e) => {
              const v = e.target.checked; setAutoPrune(v); await api.saveAppSettings({ auto_prune: v });
            }} /> Tự dọn sau khi mỗi job chạy xong
          </label>
        </div>
      )}
    </section>
  );
}
