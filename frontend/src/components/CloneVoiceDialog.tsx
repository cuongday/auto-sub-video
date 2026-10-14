import { useEffect, useRef, useState } from "react";
import { api } from "../api";

/** Create a named VieNeu voice from an uploaded clip; it then appears for every job. */
export default function CloneVoiceDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  const [gender, setGender] = useState("female");
  const [file, setFile] = useState<File | null>(null);
  const [start, setStart] = useState("0");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => { ref.current?.showModal(); }, []);

  const submit = async () => {
    if (!file || !name.trim()) return;
    setBusy(true); setErr("");
    const fd = new FormData();
    fd.append("name", name.trim()); fd.append("gender", gender); fd.append("file", file);
    fd.append("start", String(Math.max(0, Number(start) || 0)));
    try { const v = await api.createVoice(fd); onCreated(v.id); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <dialog ref={ref} className="modal" aria-labelledby="clone-title" onCancel={(e) => { e.preventDefault(); if (!busy) onClose(); }}>
      <form method="dialog" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <h3 id="clone-title">Tạo giọng nhân bản</h3>
        <p className="muted small">Một đoạn 5–15 giây chỉ có giọng người nói, rõ, không nhạc nền. File dài hơn sẽ được cắt 15 giây kể từ “bắt đầu”.</p>
        <label>Tên giọng<input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ví dụ: NgocHuyen-Vbee" autoFocus /></label>
        <label>Giới tính
          <select value={gender} onChange={(e) => setGender(e.target.value)}>
            <option value="female">Nữ</option><option value="male">Nam</option>
          </select>
        </label>
        <label>File giọng mẫu (âm thanh hoặc video)
          <input type="file" accept="audio/*,video/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label>Bắt đầu từ giây<input type="number" min={0} step={0.5} value={start} onChange={(e) => setStart(e.target.value)} /></label>
        {err && <p className="error">{err}</p>}
        <div className="modal-actions">
          <button type="button" className="ghost" disabled={busy} onClick={onClose}>Huỷ</button>
          <button type="submit" className="primary" disabled={busy || !file || !name.trim()}>{busy ? "Đang tạo…" : "Tạo giọng"}</button>
        </div>
      </form>
    </dialog>
  );
}
