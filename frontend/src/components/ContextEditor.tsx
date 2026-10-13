import { useEffect, useState } from "react";
import { api } from "../api";
import type { Context } from "../types";

/** Translation context (summary, characters/addressing, glossary). Saving + "dịch lại" re-translates everything. */
export default function ContextEditor({ jobId, onRetranslate, busy }: {
  jobId: string; onRetranslate: () => Promise<void>; busy: boolean;
}) {
  const [ctx, setCtx] = useState<Context | null>(null);
  const [open, setOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  useEffect(() => { api.context(jobId).then(setCtx).catch(() => setCtx(null)); }, [jobId]);
  if (!ctx) return null;
  const upd = (p: Partial<Context>) => { setCtx({ ...ctx, ...p }); setDirty(true); };
  const save = async () => { await api.saveContext(jobId, ctx); setDirty(false); };

  return (
    <details className="card ctx" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        <strong>Bối cảnh dịch</strong>
        <span className="muted"> — {ctx.genre_tone || "chưa có"} · {ctx.characters.length} nhân vật · {ctx.glossary.length} thuật ngữ</span>
      </summary>
      <label>Tóm tắt<textarea rows={2} value={ctx.summary} onChange={(e) => upd({ summary: e.target.value })} /></label>
      <label>Thể loại / giọng điệu<input value={ctx.genre_tone} onChange={(e) => upd({ genre_tone: e.target.value })} /></label>
      <div className="ctx-grid">
        <div>
          <h4>Nhân vật & xưng hô</h4>
          {ctx.characters.map((c, i) => (
            <div className="ctx-row" key={i}>
              <input value={c.name} aria-label="Tên gốc" onChange={(e) => upd({ characters: ctx.characters.map((x, k) => k === i ? { ...x, name: e.target.value } : x) })} />
              <input value={c.vi_name} aria-label="Tên tiếng Việt" onChange={(e) => upd({ characters: ctx.characters.map((x, k) => k === i ? { ...x, vi_name: e.target.value } : x) })} />
              <input value={c.addressing} aria-label="Xưng hô" placeholder="xưng hô" onChange={(e) => upd({ characters: ctx.characters.map((x, k) => k === i ? { ...x, addressing: e.target.value } : x) })} />
              <button className="icon" aria-label="Xoá" onClick={() => upd({ characters: ctx.characters.filter((_, k) => k !== i) })}>×</button>
            </div>
          ))}
          <button className="link" onClick={() => upd({ characters: [...ctx.characters, { name: "", vi_name: "", addressing: "" }] })}>+ Thêm nhân vật</button>
        </div>
        <div>
          <h4>Thuật ngữ</h4>
          {ctx.glossary.map((g, i) => (
            <div className="ctx-row" key={i}>
              <input value={g.source} aria-label="Gốc" onChange={(e) => upd({ glossary: ctx.glossary.map((x, k) => k === i ? { ...x, source: e.target.value } : x) })} />
              <input value={g.vi} aria-label="Tiếng Việt" onChange={(e) => upd({ glossary: ctx.glossary.map((x, k) => k === i ? { ...x, vi: e.target.value } : x) })} />
              <button className="icon" aria-label="Xoá" onClick={() => upd({ glossary: ctx.glossary.filter((_, k) => k !== i) })}>×</button>
            </div>
          ))}
          <button className="link" onClick={() => upd({ glossary: [...ctx.glossary, { source: "", vi: "" }] })}>+ Thêm thuật ngữ</button>
        </div>
      </div>
      <div className="row">
        <button className="ghost" disabled={!dirty} onClick={save}>Lưu bối cảnh</button>
        <button className="primary" disabled={busy} onClick={async () => {
          if (!confirm("Dịch lại toàn bộ theo bối cảnh mới? Các câu đã sửa tay sẽ bị thay.")) return;
          await save(); await onRetranslate();
        }}>{busy ? "Đang dịch lại…" : "Dịch lại theo bối cảnh mới"}</button>
      </div>
    </details>
  );
}
