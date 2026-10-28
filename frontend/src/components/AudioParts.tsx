import { useRef, useState } from "react";
import { api } from "../api";
import { STATE_LABEL, STEP_LABEL, fmtClock } from "../labels";
import { canPickFolder, pickFolder, pool, saveFile, saveIntoFolder, sizeInFolder } from "../save";
import type { Job } from "../types";
import { useDialog } from "./Dialog";
import Icon from "./Icon";
import Stamp, { Serial } from "./Stamp";

export const CHARS_WARN = 500_000;
const KIND: Record<string, string> = { txt: "TXT", docx: "DOCX", srt: "SRT" };
const busy = (j: Job) => j.state === "running" || j.state === "queued";
const nf = new Intl.NumberFormat("vi-VN");

/** The parts of an audio story, in story order: state and progress, length, download, run again, cancel, delete. */
/** A long file name cut in the middle: the end ("-p12.txt", "-full.txt") is what tells parts apart. */
function MidName({ name }: { name: string }) {
  const k = Math.max(0, name.length - 12);
  return <><span className="mid-head">{name.slice(0, k)}</span><span className="mid-tail">{name.slice(k)}</span></>;
}

export default function AudioParts({ parts, pct, onOpen, onChange }: {
  parts: Job[]; pct: Record<string, Record<string, number>>; onOpen: (id: string) => void; onChange: () => void;
}) {
  const dialog = useDialog();
  const [act, setAct] = useState("");
  const [msg, setMsg] = useState("");
  const [dl, setDl] = useState<Record<string, number>>({});
  const [bulk, setBulk] = useState<{ done: number; total: number; inFlight: Record<number, number> } | null>(null);
  const [bulkMsg, setBulkMsg] = useState("");
  const stop = useRef<AbortController | null>(null);
  const ready = parts.filter((j) => j.files["output.mp4"]);
  const bulkPct = bulk ? (bulk.done + Object.values(bulk.inFlight).reduce((a, b) => a + b, 0)) / Math.max(1, bulk.total) : 0;
  const fileName = (j: Job) => `${(j.audio_part?.script_name ?? j.name).replace(/\.[^.]+$/, "")}.mp4`;

  /** Every finished part into one folder the user picks; a file already there at the same size is skipped,
   *  so running it again after new parts finish only fetches the new ones. */
  const downloadAll = async () => {
    setBulkMsg(""); setMsg("");
    if (!canPickFolder()) {             // Firefox/Safari: one ordinary download per video, into the browser's download folder
      for (const j of ready) await saveFile(api.download(j.id, "output.mp4"), fileName(j));
      setBulkMsg(`Đã gửi ${ready.length} video sang trình duyệt để tải về.`);
      return;
    }
    const dir = await pickFolder("autosub-audio");
    if (!dir) return;
    const ctl = new AbortController(); stop.current = ctl;
    const skipped: string[] = [], failed: string[] = [];
    let saved = 0;
    setBulk({ done: 0, total: ready.length, inFlight: {} });
    try {
      await pool(ready.map((j, k) => ({ j, k })), 2, async ({ j, k }) => {
        if (ctl.signal.aborted) return;
        const name = fileName(j);
        const url = api.download(j.id, "output.mp4");
        // one byte is enough to learn the size ("bytes 0-0/<size>") without fetching the video
        const probe = await fetch(url, { headers: { Range: "bytes=0-0" }, signal: ctl.signal }).catch(() => null);
        const size = Number(probe?.headers.get("Content-Range")?.split("/")[1] || 0);
        await probe?.body?.cancel().catch(() => {});
        if (size && (await sizeInFolder(dir, name)) === size) skipped.push(name);
        else {
          try {
            await saveIntoFolder(dir, url, name, (p) => setBulk((b) => b && { ...b, inFlight: { ...b.inFlight, [k]: p } }), ctl.signal);
            saved++;
          } catch (e) {
            if (!ctl.signal.aborted) failed.push(`${name}: ${(e as Error).message}`);
          }
        }
        setBulk((b) => { if (!b) return b; const f = { ...b.inFlight }; delete f[k]; return { ...b, done: b.done + 1, inFlight: f }; });
      });
    } finally {
      stop.current = null; setBulk(null);
    }
    const notReady = parts.length - ready.length;
    setBulkMsg([
      ctl.signal.aborted ? `Đã huỷ. Đã lưu ${saved} video vào “${dir.name}”.` : `Đã lưu ${saved} video vào “${dir.name}”.`,
      skipped.length ? `${skipped.length} video đã có sẵn, bỏ qua.` : "",
      notReady ? `${notReady} phần chưa xong, chưa có video.` : "",
    ].filter(Boolean).join(" "));
    if (failed.length) setMsg(`Không lưu được: ${failed.join("; ")}`);
  };
  const run = async (key: string, fn: () => Promise<unknown>) => {
    setAct(key); setMsg("");
    try { await fn(); onChange(); } catch (e) { setMsg((e as Error).message); } finally { setAct(""); }
  };
  const remove = async (j: Job) => {
    const ok = await dialog.confirm({ title: "Xoá phần này?", danger: true, confirmLabel: "Xoá",
      message: <><p><strong>{j.audio_part?.script_name ?? j.name}</strong></p><p className="muted">Xoá kịch bản, giọng đọc và video của phần này. Không khôi phục được.</p></> });
    if (ok) run(`del-${j.id}`, () => api.remove(j.id));
  };
  const download = async (j: Job) => {
    const stem = (j.audio_part?.script_name ?? j.name).replace(/\.[^.]+$/, "");
    setDl((d) => ({ ...d, [j.id]: 0 })); setMsg("");
    try { await saveFile(api.download(j.id, "output.mp4"), `${stem}.mp4`, (p) => setDl((d) => ({ ...d, [j.id]: p }))); }
    catch (e) { setMsg(`Lưu ${stem}.mp4 thất bại: ${(e as Error).message}`); }
    finally { setDl((d) => { const n = { ...d }; delete n[j.id]; return n; }); }
  };

  return (
    <section className="card">
      <header className="card-head ap-parts-head">
        <div>
          <h2>Các phần</h2>
          <p className="muted small">Mỗi file kịch bản là một phần, xếp theo tên file. Chạy 2 phần cùng lúc, phần sau tự chờ. File tên kết thúc bằng “full” chạy sau cùng, dùng lại giọng đọc của các phần.</p>
        </div>
        {bulk ? (
          <div className="ap-bulk" role="status" aria-live="polite">
            <span className="ap-bulk-count">Đã lưu <strong>{bulk.done}</strong>/{bulk.total}</span>
            <span className="dy-bar ap-bulk-bar" role="progressbar" aria-label="Tiến độ tải tất cả" aria-valuemin={0} aria-valuemax={100}
              aria-valuenow={Math.round(bulkPct * 100)}><span style={{ width: `${Math.round(bulkPct * 100)}%` }} /></span>
            <button className="small danger" onClick={() => stop.current?.abort()}><Icon name="x" size={14} /> Huỷ</button>
          </div>
        ) : (
          <button className="ap-dl-all" disabled={!ready.length}
            title={ready.length ? (canPickFolder() ? "Chọn một thư mục trên máy, lưu video của mọi phần đã xong vào đó" : "Tải lần lượt từng video về thư mục Tải về của trình duyệt") : "Chưa có phần nào xong"}
            onClick={downloadAll}>
            <Icon name="download" size={16} />
            <span>{canPickFolder() ? "Tải về thư mục" : "Tải tất cả"}</span>
            <span className="ap-dl-n" aria-label={`${ready.length} video`}>{ready.length}</span>
          </button>
        )}
      </header>
      {bulkMsg && (
        <p className="ap-dl-done" role="status">
          <Icon name="check" size={16} /><span>{bulkMsg}</span>
          <button className="icon" aria-label="Đóng thông báo" onClick={() => setBulkMsg("")}><Icon name="x" size={14} /></button>
        </p>
      )}
      {msg && <p className="error" role="alert">{msg}</p>}
      {parts.length ? (
        <ol className="ap-parts">
          {parts.map((j, i) => {
            const p = j.state === "running" && j.current_step ? pct[j.id]?.[j.current_step] : undefined;   // per step: no stale % after a step change
            const done = j.state === "done" || j.state === "approved";
            const chars = j.meta?.chars ?? null;
            const stepIdx = j.current_step ? j.flow.steps.indexOf(j.current_step) : -1;
            const overall = j.state === "running" && stepIdx >= 0 ? (stepIdx + (p ?? 0)) / j.flow.steps.length : null;
            return (
              <li key={j.id} className="ap-part">
                <span className="ap-no"><Serial n={(j.audio_part?.index ?? i) + 1} full={j.audio_part?.full} /></span>
                <button className="link ap-name" title={`${j.audio_part?.script_name ?? j.name} · mở tiến độ và kết quả`} onClick={() => onOpen(j.id)}><MidName name={j.audio_part?.script_name ?? j.name} /></button>
                <span className="se-tag">{KIND[j.audio_part?.script_kind ?? ""] ?? "?"}</span>
                <Stamp state={j.state} job={j.id} at={j.state_at}
                  label={j.state === "running" && j.current_step ? `${STEP_LABEL[j.current_step] ?? j.current_step}${p != null ? ` ${Math.round(p * 100)}%` : ""}` : STATE_LABEL[j.state]} />
                {done && j.stale_from && <span className="rp-stale"><Icon name="alert" size={13} /> Cần dựng lại</span>}
                {overall != null && (
                  <span className="dy-bar ap-bar" role="progressbar" aria-label={`Tiến độ ${j.audio_part?.script_name ?? j.name}`}
                    aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(overall * 100)}><span style={{ width: `${Math.round(overall * 100)}%` }} /></span>
                )}
                <span className="ap-meta meta">
                  {j.meta?.duration ? fmtClock(j.meta.duration) : ""}
                  {chars != null && <span className="muted small"> · {nf.format(chars)} ký tự</span>}
                </span>
                <span className="ap-acts row">
                  {j.files["output.mp4"] && (
                    <button className="ghost small" disabled={j.id in dl} onClick={() => download(j)}>
                      {j.id in dl ? (dl[j.id] ? `Đang lưu ${Math.round(dl[j.id] * 100)}%` : "Đang lưu…") : "Tải .mp4"}</button>
                  )}
                  {busy(j) ? (
                    <button className="ghost small danger" disabled={!!act} onClick={() => run(`cancel-${j.id}`, () => api.cancel(j.id))}>
                      {act === `cancel-${j.id}` ? "Đang huỷ…" : "Huỷ"}</button>
                  ) : (
                    <button className="ghost small" disabled={!!act} onClick={() => run(`run-${j.id}`, () => api.run(j.id, "auto", null, true))}>
                      {act === `run-${j.id}` ? "Đang gửi…" : j.state === "new" ? "Chạy" : done && !j.stale_from ? "Chạy lại" : done ? "Dựng lại" : "Chạy tiếp"}</button>
                  )}
                  <button className="icon danger" title="Xoá phần" aria-label={`Xoá ${j.audio_part?.script_name ?? j.name}`} disabled={busy(j) || !!act}
                    onClick={() => remove(j)}><Icon name="trash" size={16} /></button>
                </span>
                {chars != null && chars > CHARS_WARN && (
                  <p className="warn small ap-note">Kịch bản rất dài ({nf.format(chars)} ký tự): đọc TTS có thể mất nhiều giờ.</p>
                )}
                {j.state === "error" && j.error && <p className="error small ap-note">{j.error}</p>}
              </li>
            );
          })}
        </ol>
      ) : <p className="muted">Chưa có phần nào. Thả file kịch bản ở trên để tạo phần.</p>}
    </section>
  );
}
