import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { SharedGlossary } from "../types";

/** Edit the glossary shared by every job: it overrides each job's automatic context for the same entries. */
export default function SharedGlossaryDialog({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [g, setG] = useState<SharedGlossary | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { ref.current?.showModal(); api.glossary().then(setG); }, []);
  const save = async () => { if (!g) return; setBusy(true); try { setG(await api.saveGlossary(g)); onClose(); } finally { setBusy(false); } };
  return (
    <dialog ref={ref} className="modal wide-modal" aria-labelledby="sg-title" onCancel={(e) => { e.preventDefault(); onClose(); }}>
      <form method="dialog" onSubmit={(e) => { e.preventDefault(); save(); }}>
        <h3 id="sg-title">Bảng thuật ngữ dùng chung</h3>
        <p className="muted small">Áp dụng cho mọi video khi dịch lần đầu: tên nhân vật, cách xưng hô, thuật ngữ ở đây được ưu tiên hơn bối cảnh tự phân tích. Hợp khi dịch nhiều video của cùng một kênh.</p>
        {!g ? <p className="muted">Đang tải…</p> : (
          <div className="ctx-grid">
            <div>
              <h4>Nhân vật & xưng hô</h4>
              {g.characters.map((c, i) => (
                <div className="ctx-row" key={i}>
                  <input value={c.name} aria-label="Tên gốc" onChange={(e) => setG({ ...g, characters: g.characters.map((x, k) => k === i ? { ...x, name: e.target.value } : x) })} />
                  <input value={c.vi_name} aria-label="Tên tiếng Việt" onChange={(e) => setG({ ...g, characters: g.characters.map((x, k) => k === i ? { ...x, vi_name: e.target.value } : x) })} />
                  <input value={c.addressing} aria-label="Xưng hô" placeholder="xưng hô" onChange={(e) => setG({ ...g, characters: g.characters.map((x, k) => k === i ? { ...x, addressing: e.target.value } : x) })} />
                  <button type="button" className="icon" aria-label="Xoá" onClick={() => setG({ ...g, characters: g.characters.filter((_, k) => k !== i) })}>×</button>
                </div>
              ))}
              <button type="button" className="link" onClick={() => setG({ ...g, characters: [...g.characters, { name: "", vi_name: "", addressing: "" }] })}>+ Thêm nhân vật</button>
            </div>
            <div>
              <h4>Thuật ngữ</h4>
              {g.terms.map((t, i) => (
                <div className="ctx-row" key={i}>
                  <input value={t.source} aria-label="Gốc" onChange={(e) => setG({ ...g, terms: g.terms.map((x, k) => k === i ? { ...x, source: e.target.value } : x) })} />
                  <input value={t.vi} aria-label="Tiếng Việt" onChange={(e) => setG({ ...g, terms: g.terms.map((x, k) => k === i ? { ...x, vi: e.target.value } : x) })} />
                  <button type="button" className="icon" aria-label="Xoá" onClick={() => setG({ ...g, terms: g.terms.filter((_, k) => k !== i) })}>×</button>
                </div>
              ))}
              <button type="button" className="link" onClick={() => setG({ ...g, terms: [...g.terms, { source: "", vi: "" }] })}>+ Thêm thuật ngữ</button>
            </div>
          </div>
        )}
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={onClose}>Huỷ</button>
          <button type="submit" className="primary" disabled={busy || !g}>Lưu</button>
        </div>
      </form>
    </dialog>
  );
}
