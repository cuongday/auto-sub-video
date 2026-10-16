import { useEffect, useState } from "react";
import { api } from "../api";
import type { BrowseFile, BrowseListing } from "../types";

const fmtSize = (n: number) => n >= 1 << 30 ? `${(n / (1 << 30)).toFixed(1)} GB` : n >= 1 << 20 ? `${(n / (1 << 20)).toFixed(0)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
const fmtDate = (t: number) => new Date(t * 1000).toLocaleDateString("vi-VN");

/** Browse the host folder mounted into the app. `start` is the saved video folder;
 *  onPick receives a video; onSetDefault saves the folder being viewed as the default. */
export default function FileBrowser({ start, onPick, onSetDefault, busy, selected, onToggle }: {
  start: string; onPick: (f: BrowseFile) => void; onSetDefault: (dir: string) => Promise<void>; busy: boolean;
  selected?: Set<string>; onToggle?: (f: BrowseFile) => void;     // multi-select for batch runs
}) {
  const [listing, setListing] = useState<BrowseListing | null>(null);
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState(start);

  const open = (path: string) => {
    setErr("");
    api.browse(path).then(setListing).catch((e) => {
      setErr(e.message);
      if (path) api.browse("").then(setListing).catch(() => {});   // saved folder gone: fall back to the root
    });
  };
  useEffect(() => { setSaved(start); open(start); }, [start]);

  if (!listing) return <p className="muted small">{err || "Đang đọc thư mục…"}</p>;
  const crumbs = listing.path ? listing.path.split("/") : [];
  return (
    <div className="browser">
      <div className="browser-bar">
        <nav className="crumbs" aria-label="Đường dẫn">
          <button className="link" onClick={() => open("")}>Thư mục gốc</button>
          {crumbs.map((c, i) => (
            <span key={i}> / <button className="link" onClick={() => open(crumbs.slice(0, i + 1).join("/"))}>{c}</button></span>
          ))}
        </nav>
        <span className="grow" />
        {listing.path === saved
          ? <span className="muted small">✓ Thư mục video mặc định</span>
          : <button className="ghost small" onClick={async () => { await onSetDefault(listing.path); setSaved(listing.path); }}>Đặt làm thư mục mặc định</button>}
      </div>
      {err && <p className="warn">{err}</p>}
      <ul className="browser-list">
        {listing.parent !== null && (
          <li><button className="entry dir" onClick={() => open(listing.parent!)}><span aria-hidden>↩</span> ..</button></li>
        )}
        {listing.dirs.map((d) => (
          <li key={d.path}><button className="entry dir" onClick={() => open(d.path)}><span aria-hidden>📁</span> {d.name}</button></li>
        ))}
        {listing.files.map((f) => (
          <li key={f.path} className="file-row">
            {onToggle && <input type="checkbox" aria-label={`Chọn ${f.name} để chạy hàng loạt`} checked={!!selected?.has(f.path)}
              disabled={busy} onChange={() => onToggle(f)} />}
            <button className="entry file" disabled={busy} onClick={() => onPick(f)} title="Mở video này">
              <span aria-hidden>🎬</span> <span className="fname">{f.name}</span>
              <span className="muted small">{fmtSize(f.size)} · {fmtDate(f.mtime)}</span>
            </button>
          </li>
        ))}
        {!listing.dirs.length && !listing.files.length && <li className="muted small pad">Thư mục trống (không có video).</li>}
      </ul>
    </div>
  );
}
