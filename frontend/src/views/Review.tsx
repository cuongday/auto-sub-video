import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import ContextEditor from "../components/ContextEditor";
import SubOverlay from "../components/SubOverlay";
import { FLAG_LABEL, fmtTime, parseTime } from "../labels";
import type { FontOption, Job, Segment } from "../types";

const CPS = 15, MAX_SPEED = 1.35, GAP = 0.05;

/** Same rule as autosub/timing.py: a line may speak until just before the next line starts. */
function computeSlots(segs: Segment[], duration: number): number[] {
  return segs.map((s, i) => Math.max(0.3, i + 1 < segs.length ? segs[i + 1].start - s.start - GAP : Math.min(s.end + 1, duration) - s.start));
}

export default function Review({ job, fonts, onRender }: { job: Job; fonts: FontOption[]; onRender: () => Promise<void> }) {
  const [segs, setSegs] = useState<Segment[]>([]);
  const [measured, setMeasured] = useState<Record<number, { text: string; dur: number }>>({});
  const [cur, setCur] = useState<number | null>(null);
  const [time, setTime] = useState(0);
  const [saving, setSaving] = useState<"" | "dirty" | "saving" | "saved">("");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [frameH, setFrameH] = useState(0);
  const video = useRef<HTMLVideoElement>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const timer = useRef<number>();
  const rows = useRef<Record<number, HTMLTableRowElement | null>>({});
  const latest = useRef<Segment[]>([]);
  const info = job.info!;

  useEffect(() => { api.segments(job.id).then((d) => { setSegs(d.segments); latest.current = d.segments; }); }, [job.id]);
  useEffect(() => {
    const v = video.current; if (!v) return;
    const ro = new ResizeObserver(() => setFrameH(v.clientHeight)); ro.observe(v); return () => ro.disconnect();
  }, []);

  const save = useCallback(async (list: Segment[]) => {
    setSaving("saving");
    try { await api.saveSegments(job.id, list); setSaving("saved"); setErr(""); }
    catch (e) { setSaving("dirty"); setErr((e as Error).message); }
  }, [job.id]);
  const update = (list: Segment[]) => {
    setSegs(list); latest.current = list; setSaving("dirty");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => save(list), 800);
  };
  const flush = async () => { window.clearTimeout(timer.current); if (saving === "dirty") await save(latest.current); };
  const patch = (id: number, p: Partial<Segment>) => update(segs.map((s) => s.id === id ? { ...s, ...p, flags: p.vi !== undefined ? s.flags.filter((f) => f !== "too_long" && f !== "translate_failed" && f !== "overflow" && f !== "tts_failed") : s.flags } : s));

  const slots = useMemo(() => computeSlots(segs, info.duration), [segs, info.duration]);
  const active = segs.findIndex((s) => time >= s.start && time < s.end);
  const activeSeg = active >= 0 ? segs[active] : null;
  useEffect(() => {
    if (active >= 0 && !video.current?.paused) rows.current[segs[active].id]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active]);  // eslint-disable-line react-hooks/exhaustive-deps

  const seek = (s: Segment) => { setCur(s.id); if (video.current) { video.current.currentTime = s.start + 0.01; } };
  const ratio = (s: Segment, i: number) => {
    const m = measured[s.id];
    const need = m && m.text === s.vi ? m.dur : s.vi.length / CPS;
    return need / slots[i];
  };

  const listen = async (s: Segment) => {
    await flush(); setBusy(`tts-${s.id}`); setErr("");
    try {
      const r = await api.previewTts(job.id, s.id);
      setMeasured((m) => ({ ...m, [s.id]: { text: s.vi, dur: r.duration } }));
      if (audio.current) { audio.current.src = r.url; audio.current.play(); }
    } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };
  const retranslate = async (ids?: number[]) => {
    await flush(); setBusy(ids ? `tr-${ids[0]}` : "tr-all"); setErr("");
    try { const d = await api.retranslate(job.id, ids); setSegs(d.segments); latest.current = d.segments; }
    catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };
  const nextId = () => Math.max(0, ...segs.map((s) => s.id)) + 1;
  const merge = (i: number) => {
    const a = segs[i], b = segs[i + 1]; if (!b) return;
    const joiner = job.settings.lang === "zh" ? "" : " ";
    update([...segs.slice(0, i), { ...a, end: b.end, source: a.source + joiner + b.source, vi: `${a.vi} ${b.vi}`.trim(), flags: [] }, ...segs.slice(i + 2)]);
  };
  const split = (i: number) => {
    const s = segs[i]; const mid = +(s.start + (s.end - s.start) / 2).toFixed(2);
    const words = s.vi.split(" "); const h = Math.ceil(words.length / 2);
    update([...segs.slice(0, i), { ...s, end: mid, vi: words.slice(0, h).join(" "), flags: [] },
      { ...s, id: nextId(), start: mid, vi: words.slice(h).join(" "), source: "", flags: [] }, ...segs.slice(i + 1)]);
  };
  const remove = (i: number) => update(segs.filter((_, k) => k !== i));
  const addAt = () => {
    const t = video.current?.currentTime ?? 0;
    const s: Segment = { id: nextId(), start: +t.toFixed(2), end: +Math.min(info.duration, t + 2).toFixed(2), source: "", vi: "", flags: [], speed: null };
    update([...segs, s].sort((a, b) => a.start - b.start)); setCur(s.id);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement).matches("input, textarea, select");
      if (e.key === " " && !typing) { e.preventDefault(); const v = video.current; if (v) v.paused ? v.play() : v.pause(); }
      const idx = segs.findIndex((s) => s.id === cur);
      if ((e.ctrlKey || e.metaKey) && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        const n = segs[Math.min(segs.length - 1, Math.max(0, idx + (e.key === "ArrowDown" ? 1 : -1)))];
        if (n) { seek(n); rows.current[n.id]?.querySelector("textarea")?.focus(); }
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && idx >= 0) { e.preventDefault(); listen(segs[idx]); }
    };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  });

  const red = segs.filter((s, i) => s.vi && ratio(s, i) > MAX_SPEED).length;
  const lyricCount = segs.filter((s) => s.flags.includes("lyrics")).length;
  const flagged = segs.filter((s) => s.flags.length).length;

  return (
    <div className="review">
      <ContextEditor jobId={job.id} busy={busy === "tr-all"} onRetranslate={() => retranslate()} />
      {job.warnings.map((w) => <p key={w} className="warn">{w}</p>)}
      {job.error && <p className="warn">{job.error}</p>}
      {lyricCount > 0 && (
        <div className="notice row">
          <span>🎵 {lyricCount} câu có vẻ là lời bài hát trong nhạc nền (giọng nghe lẫn vào nhạc). Thường không cần dịch và thuyết minh các câu này.</span>
          <button className="ghost" onClick={() => update(segs.filter((s) => !s.flags.includes("lyrics")))}>Xoá {lyricCount} câu này</button>
        </div>
      )}
      <div className={`review-grid ${info.height > info.width ? "portrait" : ""}`}>
        <div className="card table-card">
          <div className="table-head">
            <strong>{segs.length} câu</strong>
            {red > 0 && <span className="pill red">{red} câu quá dài</span>}
            {flagged > 0 && <span className="pill amber">{flagged} cần xem</span>}
            <span className="grow" />
            <span className="muted small">{saving === "saving" ? "Đang lưu…" : saving === "saved" ? "Đã lưu" : saving === "dirty" ? "Chưa lưu" : ""}</span>
            <button className="ghost" onClick={addAt}>+ Thêm câu tại {fmtTime(time)}</button>
          </div>
          <div className="table-scroll">
            <table className="segs">
              <thead><tr><th>Thời gian</th><th>Câu gốc</th><th>Tiếng Việt</th><th aria-label="Thao tác" /></tr></thead>
              <tbody>
                {segs.map((s, i) => {
                  const r = ratio(s, i);
                  const lvl = !s.vi ? "" : r <= 1 ? "ok" : r <= MAX_SPEED ? "warn" : "bad";
                  return (
                    <tr key={s.id} ref={(el) => { rows.current[s.id] = el; }}
                      className={`${cur === s.id ? "cur" : ""} ${i === active ? "playing" : ""}`} onClick={() => setCur(s.id)}>
                      <td className="tc">
                        <TimeInput value={s.start} onChange={(v) => patch(s.id, { start: v })} />
                        <TimeInput value={s.end} onChange={(v) => patch(s.id, { end: v })} />
                        <button className="link small" onClick={() => seek(s)}>▶ xem</button>
                      </td>
                      <td className="src">{s.source}</td>
                      <td className="vi">
                        <textarea rows={2} value={s.vi} onFocus={() => seek(s)} onChange={(e) => patch(s.id, { vi: e.target.value })} />
                        <div className={`len ${lvl}`} title={`Cần đọc nhanh ×${r.toFixed(2)} so với tốc độ thường`}>
                          <i style={{ width: `${Math.min(100, (r / MAX_SPEED) * 100)}%` }} />
                        </div>
                        {s.flags.map((f) => <span key={f} className={`flag ${f}`}>{f === "lyrics" ? "🎵" : "⚠"} {FLAG_LABEL[f] ?? f}</span>)}
                      </td>
                      <td className="acts">
                        <button className="icon" title="Nghe thử (Ctrl+Enter)" aria-label="Nghe thử" disabled={!s.vi || !!busy} onClick={() => listen(s)}>{busy === `tts-${s.id}` ? "…" : "🔊"}</button>
                        <button className="icon" title="Dịch lại câu này" aria-label="Dịch lại" disabled={!s.source || !!busy} onClick={() => retranslate([s.id])}>{busy === `tr-${s.id}` ? "…" : "↻"}</button>
                        <button className="icon" title="Gộp với câu sau" aria-label="Gộp" disabled={i === segs.length - 1} onClick={() => merge(i)}>⤓</button>
                        <button className="icon" title="Tách đôi" aria-label="Tách" onClick={() => split(i)}>✂</button>
                        <button className="icon danger" title="Xoá" aria-label="Xoá" onClick={() => remove(i)}>×</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {segs.length === 0 && <p className="muted pad">Không nhận dạng được lời thoại. Bạn có thể tự thêm câu.</p>}
          </div>
        </div>
        <div className="card player-card">
          <div className="player" style={{ width: `min(100%, calc(var(--player-h) * ${info.width / info.height}))` }}>
            <video ref={video} src={api.file(job.id, "source")} controls onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
              style={{ aspectRatio: `${info.width} / ${info.height}` }} />
            <div className="overlay-layer" style={{ height: frameH }}>
              <SubOverlay region={job.settings.region} cover={job.settings.cover} coverColor={job.settings.cover_color}
                style={job.settings.style} text={activeSeg?.vi ?? ""} frameH={frameH} info={info} fonts={fonts} extraRegions={job.settings.extra_regions ?? []} />
            </div>
          </div>
          <p className="muted small">Space: phát/dừng · Ctrl+↑/↓: câu trước/sau · Ctrl+Enter: nghe thử</p>
          <audio ref={audio} hidden />
        </div>
      </div>
      {err && <p className="error" role="alert">{err}</p>}
      <div className="actions sticky">
        <button className="primary" disabled={!!busy || saving === "saving"} onClick={async () => {
          await flush(); setBusy("render"); try { await onRender(); } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
        }}>Render video</button>
        <span className="muted small">Chỉ đọc lại TTS cho các câu đã đổi.</span>
      </div>
    </div>
  );
}

function TimeInput({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const [text, setText] = useState(fmtTime(value));
  useEffect(() => setText(fmtTime(value)), [value]);
  return (
    <input className="time" value={text} aria-label="Thời gian" onChange={(e) => setText(e.target.value)}
      onBlur={() => { const v = parseTime(text); if (v == null) setText(fmtTime(value)); else if (v !== value) onChange(+v.toFixed(2)); }} />
  );
}
