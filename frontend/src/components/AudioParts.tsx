import { useState } from "react";
import { api } from "../api";
import { STATE_LABEL, STEP_LABEL, fmtClock } from "../labels";
import { saveFile } from "../save";
import type { Job } from "../types";
import { useDialog } from "./Dialog";
import Icon from "./Icon";
import Stamp, { Serial } from "./Stamp";

export const CHARS_WARN = 500_000;
const KIND: Record<string, string> = { txt: "TXT", docx: "DOCX", srt: "SRT" };
const busy = (j: Job) => j.state === "running" || j.state === "queued";
const nf = new Intl.NumberFormat("vi-VN");

/** The parts of an audio story, in story order: state and progress, length, download, run again, cancel, delete. */
export default function AudioParts({ parts, pct, onOpen, onChange }: {
  parts: Job[]; pct: Record<string, Record<string, number>>; onOpen: (id: string) => void; onChange: () => void;
}) {
  const dialog = useDialog();
  const [act, setAct] = useState("");
  const [msg, setMsg] = useState("");
  const [dl, setDl] = useState<Record<string, number>>({});
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
      <header className="card-head">
        <div>
          <h2>Các phần</h2>
          <p className="muted small">Mỗi file kịch bản là một phần, xếp theo tên file. Chạy 2 phần cùng lúc, phần sau tự chờ.</p>
        </div>
      </header>
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
                <span className="ap-no"><Serial n={(j.audio_part?.index ?? i) + 1} /></span>
                <button className="link ap-name" title="Mở tiến độ và kết quả" onClick={() => onOpen(j.id)}>{j.audio_part?.script_name ?? j.name}</button>
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
