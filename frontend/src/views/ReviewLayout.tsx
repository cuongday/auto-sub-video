import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import CoverControls from "../components/CoverControls";
import RegionPicker from "../components/RegionPicker";
import { autoFontSize } from "../geometry";
import { fmtTime } from "../labels";
import type { Job, Options, Region, ReviewSettings, Settings } from "../types";

// same boxes as autosub/review/compose.py layout(): used while the part has none of its own
const DEFAULT: Record<ReviewSettings["aspect"], { subs: Region; title: Region | null }> = {
  "9:16": { subs: { x: 0.05, y: 0.69, w: 0.9, h: 0.11 }, title: { x: 0.06, y: 0.2, w: 0.88, h: 0.12 } },
  "16:9": { subs: { x: 0.05, y: 0.8, w: 0.9, h: 0.14 }, title: null },
};
const OUT = { "9:16": { width: 1080, height: 1920 }, "16:9": { width: 1920, height: 1080 } };

/** The look of a rendered part: subtitle/title boxes on the output frame, cover over the film, subtitle style;
 *  a real frame (ffmpeg) to check, then save and re-render (only assembly/render rerun). */
export default function ReviewLayout({ job, options, onJob, onRun }: {
  job: Job; options: Options; onJob: (j: Job) => void; onRun: (mode: "auto") => Promise<void>;
}) {
  const [rv, setRv] = useState<ReviewSettings>(job.review!);
  const [s, setS] = useState<Settings>(job.settings);
  const [active, setActive] = useState(0);
  const [cover, setCover] = useState(0);
  const [t, setT] = useState(0);
  const [length, setLength] = useState(0);
  const [img, setImg] = useState("");
  const [act, setAct] = useState("");
  const [err, setErr] = useState("");
  const pending = useRef<{ rv?: ReviewSettings; s?: Settings }>({});
  const timer = useRef<number>();
  const slide = useRef<number>();
  const at = useRef(0);
  const busy = job.state === "running" || job.state === "queued";
  const ready = job.steps.assemble?.status === "done";
  const aspect = rv.aspect;
  const out = OUT[aspect];
  const def = DEFAULT[aspect];
  const sub = rv.sub_region ?? def.subs;
  const title = def.title && rv.show_title ? rv.title_region ?? def.title : null;
  const film = job.info;

  const flush = async () => {
    window.clearTimeout(timer.current);
    const p = pending.current; pending.current = {};
    if (p.s) onJob(await api.saveSettings(job.id, p.s));
    if (p.rv) onJob(await api.saveJobReviewSettings(job.id, p.rv));
  };
  const queue = (p: { rv?: ReviewSettings; s?: Settings }) => {
    pending.current = { ...pending.current, ...p };
    window.clearTimeout(timer.current);
    // saved, then the frame is rendered again so the burnt-in text follows the boxes
    timer.current = window.setTimeout(() => flush().then(() => preview(at.current)).catch((e) => setErr((e as Error).message)), 700);
  };
  const setReview = (patch: Partial<ReviewSettings>) => setRv((cur) => { const n = { ...cur, ...patch }; queue({ rv: n }); return n; });
  const set = (patch: Partial<Settings>) => setS((cur) => { const n = { ...cur, ...patch }; queue({ s: n }); return n; });

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setAct(key); setErr("");
    try { await fn(); } catch (e) { setErr((e as Error).message); } finally { setAct(""); }
  };
  const preview = (at: number) => run("preview", async () => {
    await flush();
    const r = await api.reviewPreview(job.id, at);
    setImg(r.url); setLength(r.duration);
  });

  useEffect(() => { if (ready && !busy) preview(0); }, [job.id, ready]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { window.clearTimeout(slide.current); flush().catch(() => {}); }, [job.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!ready) return (
    <section className="card rl-empty">
      <h2>Dựng video trước rồi mới chỉnh</h2>
      <p className="muted">Bố cục chỉnh trên khung hình thật của video, nên cần chạy xong bước dựng ít nhất một lần.</p>
    </section>
  );

  const boxes = title ? [sub, title] : [sub];
  const regions = rv.cover_regions;
  return (
    <div className="rl">
      <fieldset className="rl-grid" disabled={busy}>
        <legend className="sr-only">Bố cục video</legend>
        <section className="card rl-stage">
          <header className="card-head">
            <div>
              <h2>Khung hình video</h2>
              <p className="muted small">Kéo khung <strong>Phụ đề</strong>{title && <> và <strong>Tiêu đề</strong></>} để đổi vị trí, kéo góc để đổi cỡ. Bấm “Xem thử” để render lại khung hình này.</p>
            </div>
            <button className="ghost small" disabled={!rv.sub_region && !rv.title_region}
              onClick={() => setReview({ sub_region: null, title_region: null })}>Về vị trí mặc định</button>
          </header>
          <div className={`rl-frame ${aspect === "9:16" ? "tall" : "wide"}`}>
            {img ? (
              <RegionPicker src={img} aspect={out.width / out.height} regions={boxes} tags={title ? ["Phụ đề", "Tiêu đề"] : ["Phụ đề"]}
                active={Math.min(active, boxes.length - 1)} onActive={setActive} onRemove={() => {}}
                onChange={(i, r) => setReview(i === 0 ? { sub_region: r } : { title_region: r })} />
            ) : (
              <div className="rl-wait" style={{ aspectRatio: `${out.width} / ${out.height}` }}>
                {act === "preview" ? <><span className="spin" aria-hidden /> Đang dựng khung hình…</> : "Chưa có khung hình"}
              </div>
            )}
          </div>
          <div className="rl-time">
            <label className="rl-slider">Thời điểm <output>{fmtTime(t)}</output>
              <input type="range" min={0} max={Math.max(1, length)} step={0.1} value={t} disabled={!length}
                onChange={(e) => {
                  const v = +e.target.value; setT(v); at.current = v;
                  window.clearTimeout(slide.current); slide.current = window.setTimeout(() => preview(v), 400);
                }} />
            </label>
            <button className="primary" disabled={!!act} onClick={() => preview(t)}>
              {act === "preview" ? <><span className="spin" aria-hidden /> Đang render…</> : "Xem thử"}</button>
          </div>
        </section>

        <div className="rl-side">
          <section className="card">
            <h3>Chữ</h3>
            {aspect === "9:16" && (
              <label className="inline check rl-check"><input type="checkbox" checked={rv.show_title}
                onChange={(e) => setReview({ show_title: e.target.checked })} /> Hiện tiêu đề (tên phim, phần)</label>
            )}
            {!rv.subtitles && <p className="muted small">Phụ đề lời đọc đang tắt (tab Kịch bản), chỉ còn tiêu đề.</p>}
            <CoverControls s={s} set={set} textOnly autoFont={autoFontSize(sub, { ...out, duration: 0, fps: 30, has_audio: true })} fonts={options.fonts} />
          </section>

          <section className="card">
            <header className="card-head">
              <div>
                <h3>Che chữ trên phim</h3>
                <p className="muted small">Khoanh phụ đề hay logo in sẵn trên phim để che. Chỉ áp cho phần này.</p>
              </div>
              <button className="ghost small" disabled={!film || regions.length >= 5}
                onClick={() => { setReview({ cover_regions: [...regions, { x: 0.1, y: 0.8, w: 0.8, h: 0.12 }] }); setCover(regions.length); }}>
                + Thêm vùng che</button>
            </header>
            {film && job.part && (
              <RegionPicker coverOnly src={api.file(job.part.film_job, "frames/f2.jpg")} aspect={film.width / film.height}
                regions={regions} active={Math.min(cover, Math.max(0, regions.length - 1))} onActive={setCover}
                onChange={(i, r) => setReview({ cover_regions: i < regions.length ? regions.map((x, k) => k === i ? r : x) : [...regions, r] })}
                onRemove={(i) => { setReview({ cover_regions: regions.filter((_, k) => k !== i) }); setCover(0); }} />
            )}
            <div className="row rl-cover-mode">
              <div className="seg" role="radiogroup" aria-label="Kiểu che">
                {([["blur", "Làm mờ"], ["blur_dim", "Mờ + nền tối"], ["solid", "Dải đen"]] as const).map(([v, label]) => (
                  <button key={v} type="button" role="radio" aria-checked={rv.cover === v} className={rv.cover === v ? "on" : ""}
                    onClick={() => setReview({ cover: v })}>{label}</button>
                ))}
              </div>
              <span className="muted small">{regions.length ? `${regions.length} vùng che` : "Không che vùng nào"}</span>
            </div>
          </section>
        </div>
      </fieldset>

      {busy && <p className="se-banner info" role="status">Phần này đang chạy. Xem tab “Tiến độ”; chỉnh được khi chạy xong.</p>}
      {err && <p className="error" role="alert">{err}</p>}
      <div className="actions sticky">
        <button className="primary" disabled={busy || !!act} onClick={() => run("go", async () => { await flush(); await onRun("auto"); })}>
          {act === "go" ? "Đang gửi…" : "Lưu & dựng lại video"}</button>
        <span className="muted small">Chỉ dựng lại hình và phụ đề, không đọc lại lời. Video cần duyệt lại sau khi dựng.</span>
      </div>
    </div>
  );
}
