import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent as RPE } from "react";
import { fmtClock, parseClock } from "../labels";
import type { Job } from "../types";

const MIN_PART = 60;                         // seconds, same as autosub/review/split.py
type By = { parts?: number; minutes?: number };

/** Problem with a list of cuts (same rule as the server), or "" when they can be saved. */
export function cutsError(cuts: number[], duration: number): string {
  const b = [0, ...cuts, duration];
  if (cuts.some((c) => !Number.isFinite(c))) return "Điểm cắt không hợp lệ";
  if (b.some((x, i) => i > 0 && x - b[i - 1] < MIN_PART)) return "Các điểm cắt phải tăng dần và mỗi phần dài ít nhất 1 phút";
  return "";
}

const dur = (s: number) => s >= 3600 ? `${Math.floor(s / 3600)} giờ ${Math.round(s % 3600 / 60)} phút` : `${Math.round(s / 60)} phút`;

/** Split one film into parts: draggable cut markers on a timeline (arrow keys nudge them), one h:mm:ss field per cut,
 *  a proposal from the server by number of parts or minutes per part, then "Tạo các phần". */
export default function SplitEditor({ film, cuts, locked, onPropose, onSave }: {
  film: Job; cuts: number[]; locked: string;          // locked: why the parts can no longer be changed ("" = free)
  onPropose: (by: By) => Promise<number[]>; onSave: (cuts: number[]) => Promise<void>;
}) {
  const duration = film.info?.duration ?? 0;
  const [draft, setDraft] = useState<number[]>(cuts);
  const [text, setText] = useState<string[]>(cuts.map(fmtClock));
  const [by, setBy] = useState<"parts" | "minutes">("parts");
  const [n, setN] = useState(() => String(Math.max(2, cuts.length + 1)));
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const track = useRef<HTMLDivElement>(null);
  const drag = useRef<number | null>(null);
  const saved = cuts.join() === draft.join();

  const put = (next: number[]) => { setDraft(next); setText(next.map(fmtClock)); };
  useEffect(() => { put(cuts); }, [cuts.join()]);    // eslint-disable-line react-hooks/exhaustive-deps

  /** Move cut i to t, kept a minute away from its neighbours and the film's ends. */
  const move = (i: number, t: number) => {
    const lo = (i ? draft[i - 1] : 0) + MIN_PART, hi = (i < draft.length - 1 ? draft[i + 1] : duration) - MIN_PART;
    const v = Math.round(Math.min(Math.max(t, lo), Math.max(lo, hi)));
    put(draft.map((c, k) => k === i ? v : c));     // also rewrites a typed value that was clamped
  };
  const at = (e: RPE) => {
    const r = track.current!.getBoundingClientRect();
    return ((e.clientX - r.left) / r.width) * duration;
  };
  const key = (i: number) => (e: KeyboardEvent) => {
    const step = e.shiftKey ? 10 : 1;
    const to = { ArrowLeft: draft[i] - step, ArrowDown: draft[i] - step, ArrowRight: draft[i] + step, ArrowUp: draft[i] + step,
      PageDown: draft[i] - 60, PageUp: draft[i] + 60 }[e.key];
    if (to === undefined) return;
    e.preventDefault(); move(i, to);
  };
  const typed = (i: number) => {
    const t = parseClock(text[i]);
    if (t === null) { setErr(`Điểm cắt ${i + 1}: nhập theo dạng giờ:phút:giây, ví dụ 0:45:30`); return; }
    setErr(""); move(i, t);
  };

  const act = async (label: string, fn: () => Promise<void>) => {
    setBusy(label); setErr("");
    try { await fn(); } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };
  const propose = () => act("propose", async () => {
    const v = Number(n.replace(",", "."));
    if (!(v > 0)) throw new Error(by === "parts" ? "Nhập số phần" : "Nhập số phút phim mỗi phần");
    put(await onPropose(by === "parts" ? { parts: Math.round(v) } : { minutes: v }));
  });
  const problem = cutsError(draft, duration);
  const bounds = [0, ...draft, duration];
  const pct = (t: number) => `${(t / Math.max(duration, 1)) * 100}%`;
  const tick = duration > 3 * 3600 ? 1800 : duration > 3600 ? 900 : duration > 1200 ? 300 : 60;

  return (
    <div className="split">
      <div className="split-bar row">
        <div className="seg" role="radiogroup" aria-label="Chia theo">
          <button type="button" role="radio" aria-checked={by === "parts"} className={by === "parts" ? "on" : ""}
            onClick={() => { setBy("parts"); setN(String(Math.max(2, draft.length + 1))); }}>Số phần</button>
          <button type="button" role="radio" aria-checked={by === "minutes"} className={by === "minutes" ? "on" : ""}
            onClick={() => { setBy("minutes"); setN(String(Math.max(5, Math.round(duration / 60 / Math.max(2, draft.length + 1))))); }}>Phút phim mỗi phần</button>
        </div>
        <label className="inline split-n">{by === "parts" ? "Số phần" : "Phút phim mỗi phần"}
          <input type="number" inputMode="decimal" min={1} max={by === "parts" ? 100 : 600} step={by === "parts" ? 1 : 5} value={n}
            onChange={(e) => setN(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") propose(); }} />
        </label>
        <button type="button" className="ghost" disabled={!!busy || !!locked} onClick={propose}>
          {busy === "propose" ? "Đang đề xuất…" : "Đề xuất"}</button>
        <span className="muted small">Tool chọn điểm cắt ở chỗ chuyển mạch truyện, rơi vào khoảng lặng thoại.</span>
      </div>

      <div className="split-track" ref={track} aria-label="Thanh thời gian của phim">
        {bounds.slice(1).map((end, i) => (
          <div key={i} className={`split-seg ${i % 2 ? "alt" : ""}`} style={{ left: pct(bounds[i]), width: pct(end - bounds[i]) }}>
            <strong>Phần {i + 1}</strong><span>{dur(end - bounds[i])}</span>
          </div>
        ))}
        {draft.map((c, i) => (
          <button key={i} type="button" role="slider" className="split-cut" style={{ left: pct(c) }} disabled={!!locked}
            aria-label={`Điểm cắt ${i + 1}`} aria-valuemin={0} aria-valuemax={Math.round(duration)} aria-valuenow={c}
            aria-valuetext={fmtClock(c)} title={`${fmtClock(c)} · kéo hoặc dùng phím mũi tên (Shift: 10 giây)`}
            onKeyDown={key(i)}
            onPointerDown={(e) => { e.preventDefault(); (e.target as HTMLElement).setPointerCapture(e.pointerId); drag.current = i; e.currentTarget.focus(); }}
            onPointerMove={(e) => { if (drag.current === i) move(i, at(e)); }}
            onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
            <span className="split-grip" aria-hidden />
          </button>
        ))}
      </div>
      <div className="split-ruler" aria-hidden>
        {Array.from({ length: Math.floor(duration / tick) + 1 }, (_, k) => k * tick).map((t) => (
          <span key={t} style={{ left: pct(t) }}>{fmtClock(t).replace(/^0:/, "")}</span>
        ))}
      </div>

      {draft.length > 0 ? (
        <ol className="split-cuts">
          {draft.map((_, i) => (
            <li key={i}>
              <label className="inline">Điểm cắt {i + 1}
                <input className="time" value={text[i] ?? ""} disabled={!!locked} inputMode="numeric" aria-describedby="split-help"
                  onChange={(e) => setText((all) => all.map((x, k) => k === i ? e.target.value : x))}
                  onBlur={() => typed(i)} onKeyDown={(e) => { if (e.key === "Enter") typed(i); }} />
              </label>
              <button type="button" className="icon" disabled={!!locked} aria-label={`Bỏ điểm cắt ${i + 1}`} title="Bỏ điểm cắt này (gộp hai phần)"
                onClick={() => put(draft.filter((__, k) => k !== i))}>×</button>
            </li>
          ))}
        </ol>
      ) : <p className="muted small">Chưa có điểm cắt: cả phim là một phần. Bấm “Đề xuất” để chia.</p>}
      <p id="split-help" className="muted small">Dạng giờ:phút:giây. Mỗi phần dài ít nhất 1 phút.</p>

      {(err || problem) && <p className="error" role="alert">{err || problem}</p>}
      <div className="actions">
        <button type="button" className="primary" disabled={!!busy || !!locked || !!problem} onClick={() => act("save", () => onSave(draft))}>
          {busy === "save" ? "Đang tạo…" : "Tạo các phần"}</button>
        {locked ? <span className="muted small">{locked}</span>
          : <span className="muted small">{saved ? `${draft.length + 1} phần như hiện tại.` : "Tạo lại các phần theo điểm cắt mới (chưa phần nào có kịch bản)."}</span>}
      </div>
    </div>
  );
}
