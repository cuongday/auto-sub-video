import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import FileBrowser from "../components/FileBrowser";
import type { AppSettings, BrowseFile, Job } from "../types";

export default function NewJob({ onCreated, onBatch }: { onCreated: (j: Job) => void; onBatch?: () => void }) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
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
  useEffect(() => {
    api.appSettings().then(setSettings).catch((e) => setErr(e.message));
    api.presets().then((p) => setPresets(Object.keys(p))).catch(() => {});
  }, []);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [presets, setPresets] = useState<string[]>([]);
  const [preset, setPreset] = useState("");
  const [batchMsg, setBatchMsg] = useState("");
  const toggle = (f: BrowseFile) => setPicked((s0) => { const n = new Set(s0); n.has(f.path) ? n.delete(f.path) : n.add(f.path); return n; });
  const runBatch = async () => {
    setErr(""); setBatchMsg(""); setBusy(`Đang tạo ${picked.size} job…`);
    try {
      const r = await api.batch([...picked], preset || null);
      const ok = r.results.filter((x) => x.ok).length;
      const bad = r.results.filter((x) => !x.ok);
      setBatchMsg(`Đã xếp ${ok} video vào hàng đợi chạy thẳng${bad.length ? ` · ${bad.length} lỗi: ${bad.map((b) => b.error).join("; ")}` : ""}`);
      setPicked(new Set());
      onBatch?.();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };
  const fromHost = async (f: BrowseFile) => {
    setErr(""); setBusy(`Đang chép ${f.name} vào kho lưu trữ…`);
    try { onCreated(await api.createFromPath(f.path)); } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
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
      {settings?.browse_available && (
        <>
          <div className="or"><span>hoặc chọn video có sẵn trên máy (không phải tải lên)</span></div>
          <FileBrowser start={settings.video_dir} busy={!!busy} onPick={fromHost}
            selected={picked} onToggle={toggle}
            onSetDefault={async (dir) => { setSettings(await api.saveAppSettings({ video_dir: dir })); }} />
          <div className="row batch-bar">
            <span className="muted small">{picked.size ? `Đã chọn ${picked.size} video để chạy hàng loạt` : "Tích ô bên trái nhiều video để chạy hàng loạt"}</span>
            <span className="grow" />
            <label className="inline">Preset
              <select value={preset} onChange={(e) => setPreset(e.target.value)}>
                <option value="">Mặc định</option>
                {presets.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </label>
            <button className="primary" disabled={!picked.size || !!busy} onClick={runBatch}>Chạy thẳng {picked.size || ""} video</button>
          </div>
          {batchMsg && <p className="ok-msg">{batchMsg}</p>}
        </>
      )}
      {err && <p className="error" role="alert">{err}</p>}
    </section>
  );
}
