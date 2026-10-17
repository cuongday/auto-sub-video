import { useEffect, useState } from "react";
import { api } from "../api";
import type { GpuStatus, VieneuDevice as Device } from "../types";

const LABEL: Record<Device, string> = { auto: "Tự động", cpu: "CPU", cuda: "GPU (NVIDIA)" };

/** Machine-wide choice of where VieNeu runs (not per video): CPU, NVIDIA GPU, or GPU when usable. */
export default function VieneuDevice() {
  const [st, setSt] = useState<GpuStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => { api.gpu().then(setSt).catch((e) => setErr(e.message)); }, []);
  if (!st) return err ? <p className="warn">{err}</p> : null;
  const gpuOk = st.cuda.available;
  const choose = async (d: Device) => {
    setSaving(true); setErr("");
    try { await api.saveAppSettings({ vieneu_device: d }); setSt(await api.gpu()); }
    catch (e) { setErr((e as Error).message); } finally { setSaving(false); }
  };
  return (
    <div className="wide device">
      <span className="device-head">VieNeu chạy trên <span className="muted small">(áp dụng cho cả máy)</span></span>
      <div className="seg" role="radiogroup" aria-label="VieNeu chạy trên">
        {(["auto", "cpu", "cuda"] as Device[]).map((d) => (
          <button key={d} type="button" role="radio" aria-checked={st.requested === d} className={st.requested === d ? "on" : ""}
            disabled={saving || (d === "cuda" && !gpuOk && st.requested !== "cuda")} onClick={() => choose(d)}
            title={d === "cuda" && !gpuOk ? st.cuda.reason : undefined}>{LABEL[d]}</button>
        ))}
      </div>
      <p className={`small ${st.note ? "warn" : "muted"}`}>
        {st.device === "cuda"
          ? <>Đang dùng GPU <strong>{st.cuda.name}</strong> ({st.cuda.vram_gb} GB) — đọc nhanh hơn CPU nhiều lần.</>
          : st.note || (gpuOk ? "Đang dùng CPU." : <>Đang dùng CPU. GPU: {st.cuda.reason}.</>)}
      </p>
      {err && <p className="warn">{err}</p>}
    </div>
  );
}
