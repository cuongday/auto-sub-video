import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ApiKeyInfo } from "../types";
import Icon from "./Icon";

/** Every provider's API key in one place. The server keeps them encrypted and only returns the last 4 characters. */
export default function ApiKeysDialog({ keys, checks = [], onChange, onClose }: {
  keys: ApiKeyInfo[]; checks?: { name: string; hint: string }[]; onChange: (k: ApiKeyInfo[]) => void; onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return (
    <dialog ref={ref} className="modal" aria-labelledby="keys-title" onCancel={(e) => { e.preventDefault(); onClose(); }}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      <form method="dialog" onSubmit={(e) => e.preventDefault()}>
        <h3 id="keys-title">API key</h3>
        {checks.length > 0 && (
          <div className="checks-list" role="note">
            <strong className="with-icon"><Icon name="alert" size={15} /> Cần cấu hình</strong>
            <ul>{checks.map((c) => <li key={c.name}><strong>{c.name}</strong>: {c.hint}</li>)}</ul>
          </div>
        )}
        <p className="muted small">Lưu mã hoá trên server, dùng chung cho cả máy. Key nhập ở đây được ưu tiên hơn file .env.</p>
        {keys.map((k) => <KeyRow key={k.id} k={k} onChange={onChange} />)}
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={onClose}>Đóng</button>
        </div>
      </form>
    </dialog>
  );
}

function KeyRow({ k, onChange }: { k: ApiKeyInfo; onChange: (k: ApiKeyInfo[]) => void }) {
  const [value, setValue] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const act = async (fn: () => Promise<ApiKeyInfo[]>) => {
    setBusy(true); setErr("");
    try { onChange(await fn()); setValue(""); setEditing(false); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const save = () => { if (value.trim()) act(() => api.saveApiKey(k.id, value)); };
  return (
    <div className="key-row">
      <div className="key-head">
        <strong>{k.label}</strong>
        <span className={`small ${k.source ? "ok-text" : "muted"}`}>
          {k.source === "web" ? "đã lưu (mã hoá)" : k.source === "env" ? `từ .env (${k.env})` : "chưa có"}
        </span>
      </div>
      {editing || !k.source ? (
        <div className="row">
          <input type="password" autoComplete="off" value={value} placeholder={k.placeholder} aria-label={`${k.label} API key`}
            onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); save(); } }}
            style={{ flex: 1 }} />
          <button type="button" className="primary small" disabled={busy || !value.trim()} onClick={save}>{busy ? "Đang lưu…" : "Lưu"}</button>
          {k.source && <button type="button" className="ghost small" onClick={() => { setEditing(false); setValue(""); }}>Huỷ</button>}
        </div>
      ) : (
        <div className="row">
          <code>••••{k.last4}</code>
          <button type="button" className="ghost small" onClick={() => setEditing(true)}>Đổi</button>
          {k.source === "web" && <button type="button" className="ghost small" disabled={busy}
            onClick={() => act(() => api.deleteApiKey(k.id))}>Xoá</button>}
        </div>
      )}
      {k.stale && !k.source && <p className="small warn">Key đã lưu không giải mã được (khoá mã hoá đã đổi) — nhập lại.</p>}
      {err && <p className="warn">{err}</p>}
    </div>
  );
}
