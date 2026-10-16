import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useDialog } from "../components/Dialog";
import CoverControls from "../components/CoverControls";
import OptionsForm from "../components/OptionsForm";
import RegionPicker from "../components/RegionPicker";
import SubOverlay from "../components/SubOverlay";
import { autoFontSize, isPortrait } from "../geometry";
import { fmtDur } from "../labels";
import type { Job, Options, Settings } from "../types";

const SAMPLE = "Đây là phụ đề tiếng Việt mẫu để xem thử vị trí và cỡ chữ";

/** Pick the cover region and every option, then start (review) or run straight through (auto). */
export default function Setup({ job, options, onJob, onRun }: {
  job: Job; options: Options; onJob: (j: Job) => void; onRun: (mode: "review" | "auto") => Promise<void>;
}) {
  const [s, setS] = useState<Settings>(job.settings);
  const [frame, setFrame] = useState(Math.min(3, job.frames.length - 1));
  const [frameH, setFrameH] = useState(0);
  const [activeRegion, setActiveRegion] = useState(0);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [presets, setPresets] = useState<Record<string, Settings>>({});
  const [previewV, setPreviewV] = useState(0);
  const imgWrap = useRef<HTMLDivElement>(null);
  const saveTimer = useRef<number>();
  const dialog = useDialog();

  useEffect(() => { setS(job.settings); }, [job.id]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { api.presets().then(setPresets).catch(() => {}); }, []);
  useEffect(() => {
    const el = imgWrap.current; if (!el) return;
    const ro = new ResizeObserver(() => setFrameH(el.querySelector("img")?.clientHeight ?? 0));
    ro.observe(el); return () => ro.disconnect();
  }, []);

  const persist = (next: Settings) => {
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => api.saveSettings(job.id, next).then(onJob).catch((e) => setErr(e.message)), 500);
  };
  const set = (patch: Partial<Settings>) => setS((cur) => { const n = { ...cur, ...patch }; persist(n); return n; });
  const flush = async () => { window.clearTimeout(saveTimer.current); onJob(await api.saveSettings(job.id, s)); };

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label); setErr("");
    try { await fn(); } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };
  const info = job.info!;
  const t = (info.duration * (frame + 0.5)) / Math.max(1, job.frames.length);
  const autoFont = autoFontSize(s.region, info);
  const portrait = isPortrait(info);
  const extras = s.extra_regions ?? [];

  return (
    <div className={`setup ${portrait ? "portrait" : "landscape"}`}>
      <section className="card">
        <header className="card-head">
          <div>
            <h2>Chọn vùng phụ đề cũ</h2>
            <p className="muted">Kéo trên ảnh để khoanh vùng cần che; kéo khung để di chuyển, kéo góc để đổi kích thước. Phụ đề mới nằm giữa vùng <strong>Phụ đề</strong>; các vùng <strong>Che</strong> chỉ bị làm mờ (logo, chữ chú thích…).</p>
            <div className="row region-actions">
              <button className="ghost small" disabled={extras.length >= 5} onClick={() => {
                const r = { x: 0.03, y: 0.04 + 0.12 * extras.length, w: 0.3, h: 0.1 };
                set({ extra_regions: [...extras, r] }); setActiveRegion(extras.length + 1);
              }}>+ Thêm vùng che</button>
              {extras.length > 0 && <span className="muted small">{extras.length} vùng che thêm · đang sửa: {activeRegion === 0 ? "Phụ đề" : `Che ${activeRegion}`}</span>}
            </div>
          </div>
          <span className="meta">{info.width}×{info.height} · {fmtDur(info.duration)}{info.has_audio ? "" : " · không có tiếng"}</span>
        </header>
        <div className="stage">
          <div className="stage-frame" ref={imgWrap} style={{ width: `min(100%, calc(var(--stage-h) * ${info.width / info.height}))` }}>
            <RegionPicker src={api.file(job.id, `frames/${job.frames[frame]}`)} aspect={info.width / info.height}
              regions={[s.region, ...extras]} active={activeRegion} onActive={setActiveRegion}
              onChange={(i, r) => i === 0 ? set({ region: r }) : set({ extra_regions: extras.map((x, k) => k === i - 1 ? r : x) })}
              onRemove={(i) => { set({ extra_regions: extras.filter((_, k) => k !== i - 1) }); setActiveRegion(0); }}>
              <SubOverlay region={s.region} cover={s.cover} coverColor={s.cover_color} style={s.style} text={SAMPLE}
                frameH={frameH} info={info} fonts={options.fonts} extraRegions={extras} />
            </RegionPicker>
          </div>
          <div className="stage-side">
            <div className="thumbs">
              {job.frames.map((f, i) => (
                <button key={f} className={i === frame ? "on" : ""} onClick={() => setFrame(i)} aria-label={`Khung hình ${i + 1}`}
                  style={{ aspectRatio: `${info.width} / ${info.height}` }}>
                  <img src={api.file(job.id, `frames/${f}`)} alt="" />
                </button>
              ))}
            </div>
            <CoverControls s={s} set={set} autoFont={autoFont} fonts={options.fonts} />
            <div className="row">
              <button className="ghost" disabled={!!busy} onClick={() => act("preview", async () => {
                await flush(); await api.previewRender(job.id, Math.max(0, t - 2.5)); setPreviewV(Date.now());
              })}>{busy === "preview" ? "Đang render thử…" : "Render thử 5 giây"}</button>
              <span className="muted small">Kết quả ffmpeg thật tại khung hình đang chọn.</span>
            </div>
            {previewV > 0 && (
              <video className="preview" src={api.file(job.id, "preview.mp4", previewV)} controls autoPlay muted
                style={{ aspectRatio: `${info.width} / ${info.height}`, width: `min(100%, calc(var(--preview-h) * ${info.width / info.height}))` }} />
            )}
          </div>
        </div>
      </section>

      <section className="card">
        <header className="card-head">
          <h2>Tuỳ chọn</h2>
          <div className="row">
            <select value="" onChange={(e) => { const p = presets[e.target.value]; if (p) set({ ...p, ref_audio: s.ref_audio }); }} aria-label="Áp dụng preset">
              <option value="">Áp dụng preset…</option>
              {Object.keys(presets).map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
            <button className="ghost" onClick={async () => {
              const name = await dialog.prompt({ title: "Lưu preset", message: "Lưu bộ tuỳ chọn hiện tại để dùng lại cho video khác.",
                placeholder: "Ví dụ: Phim Trung — VieNeu", confirmLabel: "Lưu" });
              if (name) api.savePreset(name, s).then(setPresets).catch((e) => setErr(e.message));
            }}>Lưu preset</button>
          </div>
        </header>
        <OptionsForm job={job} options={options} s={s} set={set}
          onRefUpload={(f) => act("ref", async () => { await flush(); const j = await api.uploadRef(job.id, f); onJob(j); setS(j.settings); })} />
      </section>

      {err && <p className="error" role="alert">{err}</p>}
      <div className="actions sticky">
        <button className="primary" disabled={!!busy} onClick={() => act("run", async () => { await flush(); await onRun("review"); })}>
          Bắt đầu — dừng ở bước rà soát
        </button>
        <button className="ghost" disabled={!!busy} onClick={() => act("run", async () => { await flush(); await onRun("auto"); })}>
          Chạy thẳng đến video
        </button>
      </div>
    </div>
  );
}
