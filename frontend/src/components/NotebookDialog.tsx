import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Notebook, NotebookCharacter, NotebookEntry } from "../types";

const clean = (v: string[]) => v.map((x) => x.trim()).filter(Boolean);

/** The project notebook (what the LLM reads when writing the next part): one entry per approved part, the characters
 *  and the narrator's voice. Saved with the rev it was loaded at; the server refuses a save over a newer notebook. */
export default function NotebookDialog({ pid, onClose }: { pid: string; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [nb, setNb] = useState<Notebook | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => { setErr(""); api.notebook(pid).then(setNb).catch((e) => setErr(e.message)); };
  useEffect(() => { ref.current?.showModal(); load(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const entry = (i: number, p: Partial<NotebookEntry>) => setNb((n) => n && { ...n, entries: n.entries.map((e, k) => k === i ? { ...e, ...p } : e) });
  const char = (i: number, p: Partial<NotebookCharacter>) => setNb((n) => n && { ...n, characters: n.characters.map((c, k) => k === i ? { ...c, ...p } : c) });
  const save = async () => {
    if (!nb) return;
    setBusy(true); setErr("");
    try {
      await api.saveNotebook(pid, {     // lists are edited as raw text, cleaned here
        ...nb, entries: nb.entries.map((e) => ({ ...e, open_threads: clean(e.open_threads), hooks: clean(e.hooks) })),
        characters: nb.characters.filter((c) => c.name.trim()).map((c) => ({ ...c, name: c.name.trim(), aliases: clean(c.aliases) })),
      });
      onClose();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <dialog ref={ref} className="modal wide-modal nb" aria-labelledby="nb-title" onCancel={(e) => { e.preventDefault(); onClose(); }}>
      <form method="dialog" onSubmit={(e) => { e.preventDefault(); save(); }}>
        <h3 id="nb-title">Sổ tay dự án</h3>
        <p className="muted small">LLM đọc sổ tay khi viết kịch bản phần tiếp theo. Sổ tay tự cập nhật mỗi khi một phần được duyệt; sửa tay ở đây cũng được.
          Phần nào đã viết kịch bản trước khi sổ tay đổi sẽ hiện cảnh báo để bạn tự quyết có viết lại hay không.</p>
        {!nb ? (err ? null : <p className="muted" role="status">Đang tải…</p>) : (
          <div className="nb-body">
            <section>
              <h4>Các phần đã làm</h4>
              {nb.entries.length ? nb.entries.map((e, i) => (
                <fieldset key={e.job} className="nb-entry">
                  <legend>Phần {e.index} <span className="muted">· {e.range_label}</span></legend>
                  <label>Tóm tắt<textarea rows={3} value={e.summary} onChange={(x) => entry(i, { summary: x.target.value })} /></label>
                  <label>Điểm dừng<textarea rows={2} value={e.ending} onChange={(x) => entry(i, { ending: x.target.value })} /></label>
                  <div className="nb-two">
                    <label>Tình tiết còn lửng <span className="muted small">(mỗi dòng một ý)</span>
                      <textarea rows={3} value={e.open_threads.join("\n")} onChange={(x) => entry(i, { open_threads: x.target.value.split("\n") })} /></label>
                    <label>Hook đã dùng <span className="muted small">(mỗi dòng một câu)</span>
                      <textarea rows={3} value={e.hooks.join("\n")} onChange={(x) => entry(i, { hooks: x.target.value.split("\n") })} /></label>
                  </div>
                </fieldset>
              )) : <p className="muted nb-empty">Chưa có phần nào được duyệt. Duyệt phần 1 xong, tóm tắt và tình tiết còn lửng sẽ được ghi vào đây.</p>}
            </section>

            <section>
              <h4>Nhân vật</h4>
              {nb.characters.map((c, i) => (
                <fieldset key={i} className="nb-char">
                  <legend className="sr-only">Nhân vật {i + 1}</legend>
                  <div className="nb-two">
                    <label>Tên<input value={c.name} onChange={(x) => char(i, { name: x.target.value })} /></label>
                    <label>Tên khác <span className="muted small">(cách nhau dấu phẩy)</span>
                      <input value={c.aliases.join(",")} onChange={(x) => char(i, { aliases: x.target.value.split(",") })} /></label>
                  </div>
                  <label>Vai trò<input value={c.role} onChange={(x) => char(i, { role: x.target.value })} /></label>
                  <label>Quan hệ<textarea rows={2} value={c.relations} onChange={(x) => char(i, { relations: x.target.value })} /></label>
                  <label>Diễn biến đến hiện tại<textarea rows={2} value={c.arc} onChange={(x) => char(i, { arc: x.target.value })} /></label>
                  <button type="button" className="link danger small" onClick={() => setNb({ ...nb, characters: nb.characters.filter((_, k) => k !== i) })}>
                    Xoá nhân vật này</button>
                </fieldset>
              ))}
              {!nb.characters.length && <p className="muted small">Chưa có nhân vật. Danh sách được lấy từ phim khi chuẩn bị xong và bổ sung sau mỗi phần.</p>}
              <button type="button" className="link" onClick={() => setNb({ ...nb, characters: [...nb.characters, { name: "", aliases: [], role: "", relations: "", arc: "" }] })}>
                + Thêm nhân vật</button>
            </section>

            <section>
              <h4>Giọng kể</h4>
              <label className="sr-only" htmlFor="nb-voice">Giọng kể</label>
              <textarea id="nb-voice" rows={3} value={nb.voice} placeholder="Ví dụ: xưng “mình”, gọi người xem là “các bạn”, hay mở bằng “Chuyện là thế này…”"
                onChange={(x) => setNb({ ...nb, voice: x.target.value })} />
            </section>
          </div>
        )}
        {err && <p className="error" role="alert">{err}{err.includes("tải lại") && <> <button type="button" className="link" onClick={load}>Tải lại</button></>}</p>}
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={onClose}>Đóng</button>
          <button type="submit" className="primary" disabled={busy || !nb}>{busy ? "Đang lưu…" : "Lưu sổ tay"}</button>
        </div>
      </form>
    </dialog>
  );
}
