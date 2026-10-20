import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useDialog } from "../components/Dialog";
import Icon from "../components/Icon";
import NotebookDialog from "../components/NotebookDialog";
import ReviewSettingsForm from "../components/ReviewSettingsForm";
import { fmtClock, parseClock } from "../labels";
import type { Job, PartInfo, ReviewSettings, ScriptBlock, ScriptData, Templates, TimeSpan } from "../types";

const PAUSE = 0.35;        // autosub/review/script.py BLOCK_PAUSE: silence between blocks
const TOLERANCE = 0.15;    // script.py LENGTH_TOLERANCE
const NEW_SCENE = 4;
/** Same count as autosub/review/pace.py: one Vietnamese syllable per word. */
const syllables = (t: string) => t.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length;
const mss = (s: number) => { const r = Math.round(s); return `${Math.floor(r / 60)}:${String(r % 60).padStart(2, "0")}`; };
/** The reading pace the server used for its estimate, so block durations update while typing. */
const paceOf = (d: ScriptData) => {
  const n = d.blocks.reduce((a, b) => a + syllables(b.text), 0), talk = d.estimate - PAUSE * d.blocks.length;
  return n && talk > 0 ? n * 60 / talk : 190;
};
const blockSecs = (b: ScriptBlock, spm: number) => syllables(b.text) / spm * 60 + PAUSE;
const KIND_LABEL = { hook: "HOOK", mo_dau: "MỞ ĐẦU", ket: "KẾT" } as const;
const grow = (el: HTMLTextAreaElement | null) => { if (el) { el.style.height = "auto"; el.style.height = `${el.scrollHeight + 2}px`; } };

/** The script of a review part (spec 5.4): narration blocks with their film scenes, the part's own settings beside them. */
export default function ScriptEditor({ job, templates, onJob, onRun }: {
  job: Job; templates: Templates | null; onJob: (j: Job) => void; onRun: (mode: "review" | "auto") => Promise<void>;
}) {
  const part = job.part!;
  const written = job.steps.script?.status === "done";
  const busy = job.state === "running" || job.state === "queued";
  const [blocks, setBlocks] = useState<ScriptBlock[] | null>(null);
  const [spm, setSpm] = useState(190);
  const [rv, setRv] = useState<ReviewSettings>(job.review!);
  const [open, setOpen] = useState<{ bid: number; i: number } | null>(null);
  const [act, setAct] = useState("");
  const [err, setErr] = useState("");
  const [notebook, setNotebook] = useState(false);
  const saved = useRef<ScriptBlock[]>([]);                       // what the server has
  const saving = useRef<Promise<unknown>>(Promise.resolve());    // saves run one after another
  const rvTimer = useRef<number>();
  const rvPending = useRef<(() => Promise<unknown>) | null>(null);
  const dialog = useDialog();

  useEffect(() => { setRv(job.review!); setOpen(null); }, [job.id]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!written) { setBlocks(null); return; }
    let live = true;
    api.script(job.id).then((d) => { if (live) { saved.current = d.blocks; setSpm(paceOf(d)); setBlocks(d.blocks); } })
      .catch((e) => live && setErr((e as Error).message));
    return () => { live = false; };
  }, [job.id, written, job.steps.script?.hash]);
  useEffect(() => () => { window.clearTimeout(rvTimer.current); rvPending.current?.(); }, [job.id]);

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setAct(key); setErr("");
    try { await fn(); } catch (e) { setErr((e as Error).message); } finally { setAct(""); }
  };
  const save = (next: ScriptBlock[]) => {
    saving.current = saving.current.then(async () => {
      try {
        const d = await api.saveScript(job.id, next);
        saved.current = d.blocks;
        // only the flags come back: the text typed meanwhile in another block stays
        setBlocks((cur) => cur && cur.map((b) => ({ ...b, edited: d.blocks.find((x) => x.id === b.id)?.edited ?? b.edited })));
        onJob(await api.job(job.id));     // editing unapproves the part
      } catch (e) { setErr((e as Error).message); }
    });
    return saving.current;
  };
  const flush = async () => { window.clearTimeout(rvTimer.current); await rvPending.current?.(); await saving.current; };
  const setScenes = (bid: number, scenes: TimeSpan[]) => {
    const next = blocks!.map((b) => b.id === bid ? { ...b, scenes, edited: true } : b);
    setBlocks(next); save(next);
  };
  const setReview = (patch: Partial<ReviewSettings>) => {
    const n = { ...rv, ...patch };
    setRv(n);
    window.clearTimeout(rvTimer.current);
    const go = () => { rvPending.current = null; return api.saveJobReviewSettings(job.id, n).then(onJob).catch((e) => setErr(e.message)); };
    rvPending.current = go;
    rvTimer.current = window.setTimeout(go, 500);
  };

  const label = (b: ScriptBlock, n: number) => b.kind === "than" ? `ĐOẠN ${n}` : KIND_LABEL[b.kind];
  const tplLabel = (b: ScriptBlock) =>
    (b.kind === "hook" ? templates?.hooks : b.kind === "mo_dau" ? templates?.openings : undefined)?.find((t) => t.id === b.template)?.label;

  const rewriteBlock = async (b: ScriptBlock, name: string) => {
    const ins = await dialog.prompt({
      title: `Viết lại ${name}`, optional: true, confirmLabel: "Viết lại", placeholder: "Chỉ dẫn (có thể để trống)",
      message: "Gõ chỉ dẫn nếu muốn, ví dụ “ngắn hơn” hay “nhấn vào tình mẹ con”. Để trống thì viết lại theo mẫu đang chọn.",
    });
    if (ins === null) return;
    await run(`b${b.id}`, async () => {
      await saving.current;
      const nb = await api.rewriteBlock(job.id, b.id, ins);
      saved.current = saved.current.map((x) => x.id === nb.id ? nb : x);
      setBlocks((cur) => cur && cur.map((x) => x.id === nb.id ? nb : x));
      onJob(await api.job(job.id));
    });
  };
  const rewriteAll = async () => {
    const ok = await dialog.confirm({
      title: "Viết lại kịch bản?", confirmLabel: "Viết lại",
      message: "LLM viết lại kịch bản theo cài đặt hiện tại và sổ tay dự án. Các khối đã sửa tay vẫn được giữ nguyên.",
    });
    if (ok) await run("all", async () => { await flush(); onJob(await api.rewriteScript(job.id)); });
  };

  const total = blocks ? blocks.reduce((a, b) => a + blockSecs(b, spm), 0) : 0;
  const target = rv.minutes * 60;
  const off = blocks !== null && Math.abs(total - target) > target * TOLERANCE;
  const blocked = !written && job.prev_approved === false;
  const filmWait = !written && !blocked && job.film_state != null && job.film_state !== "done" && job.film_state !== "approved";
  let body = 0;

  return (
    <div className="se">
      <header className="se-head">
        <div>
          <p className="se-crumb">Dự án: {job.name.replace(/ · Phần \d+$/, "")} · Phần {part.index} ({fmtClock(part.start)} → {fmtClock(part.end)})</p>
          <h2>Kịch bản review: Phần {part.index}</h2>
        </div>
        {blocks && (
          <div className={`se-meter ${off ? "off" : ""}`}>
            <span>Ước tính <b>{mss(total)}</b> / mục tiêu {mss(target)}</span>
            <span className="se-track" role="meter" aria-label="Độ dài ước tính so với mục tiêu" aria-valuemin={0} aria-valuemax={Math.round(target)}
              aria-valuenow={Math.round(Math.min(total, target))} aria-valuetext={`${mss(total)} trên ${mss(target)}${off ? ", lệch hơn 15%" : ""}`}>
              <i style={{ width: `${Math.min(100, total / target * 100)}%` }} />
            </span>
          </div>
        )}
      </header>

      {busy && <p className="se-banner info" role="status">Phần này đang chạy. Xem tab “Tiến độ”; sửa được khi chạy xong.</p>}
      {written && job.notebook_stale && !busy && (
        <div className="se-banner" role="status">
          <Icon name="alert" size={15} /> <span>Sổ tay đã thay đổi sau khi viết kịch bản</span>
          <span className="grow" />
          <button className="ghost small" disabled={!!act} onClick={rewriteAll}>Viết lại kịch bản</button>
        </div>
      )}
      {written && job.stale_from === "script" && !busy && (
        <p className="se-banner" role="status"><Icon name="alert" size={15} /> Cài đặt kịch bản đã đổi. Bấm “Viết lại kịch bản” để áp dụng; duyệt ngay thì kịch bản cũng được viết lại trước khi dựng.</p>
      )}

      <div className="se-grid">
        <fieldset className="se-main" disabled={busy}>
          <legend className="sr-only">Các khối kịch bản</legend>
          {!written ? (
            <div className="se-empty">
              {blocked ? <>
                <h3>Phần trước chưa được duyệt</h3>
                <p className="muted">Phần {part.index} viết kịch bản sau khi phần {part.index - 1} đã duyệt, để LLM đọc được sổ tay có phần đó.</p>
              </> : filmWait ? <>
                <h3>Phim chưa chuẩn bị xong</h3>
                <p className="muted">Kịch bản viết từ lời thoại và bản tóm tắt của phim. Xem tiến độ ở trang dự án.</p>
              </> : <>
                <h3>Chưa có kịch bản</h3>
                <p className="muted">Chọn phong cách và mẫu ở cột bên rồi bấm viết. Viết xong, tool dừng ở đây để bạn sửa trước khi đọc và dựng video.</p>
              </>}
              <button className="primary" disabled={blocked || filmWait || !!act} onClick={() => run("write", async () => { await flush(); await onRun("review"); })}>
                {act === "write" ? "Đang gửi…" : "Viết kịch bản"}</button>
            </div>
          ) : !blocks ? <p className="muted" role="status">Đang tải kịch bản…</p> : <>
            {blocks.map((b) => {
              const name = label(b, b.kind === "than" ? ++body : 0);
              const tpl = tplLabel(b);
              const mine = act === `b${b.id}`;
              return (
                <section key={b.id} className={`se-blk ${b.kind}`} aria-label={name}>
                  <div className="se-bh">
                    <span className="se-tag kind">{name}</span>
                    {tpl && <span className="se-tag">mẫu: {tpl}</span>}
                    {b.kind === "than" && b.source_start != null && b.source_end != null &&
                      <span className="se-tag">{fmtClock(b.source_start)} – {fmtClock(b.source_end)}</span>}
                    {b.edited && <span className="se-tag ed">đã sửa tay</span>}
                    <span className="se-dur" title="Thời lượng đọc ước tính">{mss(blockSecs(b, spm))}</span>
                  </div>
                  <textarea ref={(el) => grow(el)} rows={2} value={b.text} disabled={mine} aria-label={`Lời đọc ${name}`}
                    onChange={(e) => { grow(e.currentTarget); const text = e.target.value; setBlocks((cur) => cur && cur.map((x) => x.id === b.id ? { ...x, text, edited: true } : x)); }}
                    onBlur={() => { if (b.text !== saved.current.find((x) => x.id === b.id)?.text) save(blocks); }} />
                  <div className="se-scenes">
                    {b.scenes.map((s, i) => {
                      const on = open?.bid === b.id && open.i === i;
                      return (
                        <button key={i} className="se-scene" aria-expanded={on} aria-label={`Cảnh ${fmtClock(s.start)} đến ${fmtClock(s.end)}`}
                          onClick={() => setOpen(on ? null : { bid: b.id, i })}>
                          <img src={api.thumbUrl(job.id, s.start)} alt="" loading="lazy" width={48} height={27} />
                          {fmtClock(s.start)}–{fmtClock(s.end)}
                        </button>
                      );
                    })}
                    <button className="link small" onClick={() => {
                      const start = Math.min(b.source_start ?? part.start, part.end - 1);
                      setScenes(b.id, [...b.scenes, { start, end: Math.min(start + NEW_SCENE, part.end) }]);
                      setOpen({ bid: b.id, i: b.scenes.length });
                    }}>+ thêm cảnh</button>
                    <button className="link small se-rw" disabled={!!act} onClick={() => rewriteBlock(b, name)}>
                      {mine ? <><span className="spin" aria-hidden /> Đang viết lại…</> : "↻ Viết lại"}</button>
                    {open?.bid === b.id && b.scenes[open.i] && (
                      <ScenePop key={open.i} src={api.file(part.film_job, "source")} scene={b.scenes[open.i]} part={part}
                        onClose={() => setOpen(null)}
                        onChange={(s) => setScenes(b.id, b.scenes.map((x, k) => k === open.i ? s : x))}
                        onRemove={() => { setOpen(null); setScenes(b.id, b.scenes.filter((_, k) => k !== open.i)); }} />
                    )}
                  </div>
                </section>
              );
            })}
            <p className="muted small">Bấm vào cảnh để xem thử, đổi mốc thời gian hoặc xoá. Lời đọc sửa trực tiếp trong ô, rời ô là lưu.</p>
          </>}
        </fieldset>

        <fieldset className="se-side card" disabled={busy}>
          <legend className="sr-only">Cài đặt phần này</legend>
          <h3>Cài đặt phần này</h3>
          <ReviewSettingsForm value={rv} templates={templates} onChange={setReview} />
          <p className="muted small">Đổi phong cách hoặc mẫu xong bấm “Viết lại kịch bản”. Các khối đã sửa tay sẽ được giữ.</p>
        </fieldset>
      </div>

      {err && <p className="error" role="alert">{err}</p>}
      {notebook && job.project && <NotebookDialog pid={job.project} onClose={() => setNotebook(false)} />}
      <div className="actions sticky se-foot">
        {written && <button className="ghost" disabled={busy || !!act} onClick={rewriteAll}>{act === "all" ? "Đang gửi…" : "↻ Viết lại kịch bản"}</button>}
        {job.project && <button className="ghost" onClick={() => setNotebook(true)}><Icon name="book" size={15} /> Xem sổ tay dự án</button>}
        {written && <button className="primary" disabled={busy || !!act || !blocks}
          onClick={() => run("go", async () => { await flush(); await onRun("auto"); })}>
          {act === "go" ? "Đang gửi…" : "Duyệt kịch bản → tạo video"}</button>}
      </div>
    </div>
  );
}

/** Preview of one scene (the film itself, seeked by a media fragment) with its two times and delete. */
function ScenePop({ src, scene, part, onChange, onRemove, onClose }: {
  src: string; scene: TimeSpan; part: PartInfo; onChange: (s: TimeSpan) => void; onRemove: () => void; onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [a, setA] = useState(fmtClock(scene.start));
  const [b, setB] = useState(fmtClock(scene.end));
  const [bad, setBad] = useState("");
  useEffect(() => { setA(fmtClock(scene.start)); setB(fmtClock(scene.end)); }, [scene.start, scene.end]);
  useEffect(() => {
    const out = (e: PointerEvent) => {
      const t = e.target as HTMLElement;
      if (!ref.current?.contains(t) && !t.closest(".se-scene")) onClose();
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("pointerdown", out); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", out); document.removeEventListener("keydown", esc); };
  }, [onClose]);

  const apply = () => {
    // untouched fields keep their exact value (the box shows whole seconds)
    const s = a === fmtClock(scene.start) ? scene.start : parseClock(a);
    const e = b === fmtClock(scene.end) ? scene.end : parseClock(b);
    if (s === null || e === null) return setBad("Nhập mốc theo dạng giờ:phút:giây, ví dụ 0:45:30");
    if (s < part.start || e > part.end || e <= s)
      return setBad(`Cảnh phải nằm trong phần này (${fmtClock(part.start)} → ${fmtClock(part.end)}) và kết thúc sau khi bắt đầu`);
    setBad("");
    if (s !== scene.start || e !== scene.end) onChange({ start: s, end: e });
  };
  const key = (e: React.KeyboardEvent) => { if (e.key === "Enter") { e.preventDefault(); apply(); } };

  return (
    <div ref={ref} className="se-pop" role="dialog" aria-label={`Cảnh ${fmtClock(scene.start)}–${fmtClock(scene.end)}`}>
      <video key={`${scene.start}-${scene.end}`} src={`${src}#t=${scene.start.toFixed(2)},${scene.end.toFixed(2)}`} controls preload="metadata" />
      <div className="se-times">
        <label>Bắt đầu<input value={a} onChange={(e) => setA(e.target.value)} onBlur={apply} onKeyDown={key} inputMode="decimal" /></label>
        <label>Kết thúc<input value={b} onChange={(e) => setB(e.target.value)} onBlur={apply} onKeyDown={key} inputMode="decimal" /></label>
      </div>
      {bad && <p className="error small" role="alert">{bad}</p>}
      <div className="row">
        <button className="ghost small danger" onClick={onRemove}>Xoá cảnh</button>
        <span className="grow" />
        <button className="ghost small" onClick={onClose}>Đóng</button>
      </div>
    </div>
  );
}
