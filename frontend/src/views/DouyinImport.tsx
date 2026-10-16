import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { DyItem, DyLookup, DyTask } from "../types";

const fmtDur = (s: number) => (s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : "ảnh");
const fmtDate = (t: number) => (t ? new Date(t * 1000).toLocaleDateString("vi-VN") : "");

/** Paste a Douyin video or channel link, pick videos, download them into new jobs. */
export default function DouyinImport({ onJobsCreated }: { onJobsCreated: () => void }) {
  const [url, setUrl] = useState("");
  const [look, setLook] = useState<DyLookup | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [task, setTask] = useState<DyTask | null>(null);
  const [presets, setPresets] = useState<string[]>([]);
  const [preset, setPreset] = useState("");
  const [login, setLogin] = useState<{ logged_in: boolean; login: { state: string; qr: string | null; error: string | null } | null } | null>(null);
  const poll = useRef<number>();

  useEffect(() => {
    api.presets().then((p) => setPresets(Object.keys(p))).catch(() => {});
    api.douyinSession().then(setLogin).catch(() => {});
    return () => window.clearInterval(poll.current);
  }, []);

  const lookup = async () => {
    setErr(""); setBusy("lookup"); setLook(null); setTask(null);
    try {
      const r = await api.douyinLookup(url.trim());
      setLook(r);
      setPicked(new Set(r.items.filter((i) => !i.is_images).map((i) => i.id)));
    } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };

  const download = async () => {
    if (!look) return;
    setErr(""); setBusy("download");
    const items = look.items.filter((i) => picked.has(i.id));
    try {
      const t = await api.douyinDownload(items.map((i) => i.id), Object.fromEntries(items.map((i) => [i.id, i.title])), preset || null);
      setTask(t);
      window.clearInterval(poll.current);
      poll.current = window.setInterval(async () => {
        const s = await api.douyinTask(t.id);
        setTask(s);
        if (s.done) { window.clearInterval(poll.current); setBusy(""); onJobsCreated(); }
        else if (s.items.some((x) => x.job)) onJobsCreated();
      }, 1500);
    } catch (e) { setErr((e as Error).message); setBusy(""); }
  };

  const startLogin = async () => {
    setLogin(await api.douyinLogin());
    window.clearInterval(poll.current);
    poll.current = window.setInterval(async () => {
      const s = await api.douyinSession();
      setLogin(s);
      if (s.logged_in || (s.login && !["starting", "waiting"].includes(s.login.state))) window.clearInterval(poll.current);
    }, 2000);
  };

  const toggle = (id: string) => setPicked((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const videos = look?.items.filter((i) => !i.is_images) ?? [];

  return (
    <section className="card douyin">
      <header className="card-head">
        <h2>Tải video từ Douyin</h2>
        <span className="muted small">
          {login?.logged_in ? <>✓ Đã đăng nhập Douyin · <button className="link small" onClick={async () => setLogin(await api.douyinLogout())}>Đăng xuất</button></>
            : <>Chưa đăng nhập · <button className="link small" onClick={startLogin}>Đăng nhập bằng mã QR</button></>}
        </span>
      </header>
      {login?.login && !login.logged_in && ["starting", "waiting"].includes(login.login.state) && (
        <div className="qr-box">
          {login.login.qr ? <img src={login.login.qr} alt="Mã QR đăng nhập Douyin" /> : <p className="muted">Đang lấy mã QR…</p>}
          <p className="small">Mở app <strong>Douyin</strong> trên điện thoại → biểu tượng quét ở góc trên → quét mã này. Đăng nhập để xem được toàn bộ video của kênh.</p>
        </div>
      )}
      {login?.login && ["expired", "failed"].includes(login.login.state) && !login.logged_in && (
        <p className="warn">{login.login.state === "expired" ? "Mã QR đã hết hạn." : `Đăng nhập lỗi: ${login.login.error ?? ""}`} <button className="link" onClick={startLogin}>Lấy mã mới</button></p>
      )}
      <form className="row" onSubmit={(e) => { e.preventDefault(); if (url.trim()) lookup(); }}>
        <input className="grow" value={url} onChange={(e) => setUrl(e.target.value)} aria-label="Link Douyin"
          placeholder="Dán link video, link kênh (douyin.com/user/…) hoặc nội dung chia sẻ có link v.douyin.com" />
        <button className="primary" disabled={!url.trim() || !!busy}>{busy === "lookup" ? "Đang đọc…" : "Xem"}</button>
      </form>
      {err && <p className="error">{err}</p>}
      {look && (
        <>
          <div className="row dy-head">
            <strong>{look.kind === "channel" ? `Kênh ${look.name || ""}` : "Video"}</strong>
            <span className="muted small">{videos.length} video{look.items.length > videos.length ? ` · bỏ qua ${look.items.length - videos.length} bài ảnh` : ""}</span>
            {look.kind === "channel" && !look.complete && (
              <span className="warn small">Mới thấy trang đầu của kênh. {look.logged_in ? "Douyin không trả thêm." : "Đăng nhập để xem hết."}</span>
            )}
            <span className="grow" />
            {videos.length > 1 && <>
              <button className="link small" onClick={() => setPicked(new Set(videos.map((v) => v.id)))}>Chọn hết</button>
              <button className="link small" onClick={() => setPicked(new Set())}>Bỏ chọn</button>
            </>}
          </div>
          <ul className="dy-list">
            {look.items.map((it: DyItem) => (
              <li key={it.id} className={it.is_images ? "disabled" : picked.has(it.id) ? "on" : ""}>
                <label>
                  <input type="checkbox" disabled={it.is_images} checked={picked.has(it.id)} onChange={() => toggle(it.id)} />
                  {it.cover ? <img src={it.cover} alt="" referrerPolicy="no-referrer" loading="lazy" /> : <span className="noimg" />}
                  <span className="dy-meta">
                    <span className="dy-title">{it.title || "(không có tiêu đề)"}</span>
                    <span className="muted small">{fmtDur(it.duration)} · {it.width && it.height ? `${it.width}×${it.height}` : ""} · {fmtDate(it.created)}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <div className="row">
            <label className="inline">Áp preset
              <select value={preset} onChange={(e) => setPreset(e.target.value)}>
                <option value="">Không</option>
                {presets.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </label>
            <span className="grow" />
            <button className="primary" disabled={!picked.size || !!busy} onClick={download}>
              {busy === "download" ? "Đang tải…" : `Tải ${picked.size} video thành job mới`}
            </button>
          </div>
        </>
      )}
      {task && (
        <ul className="dy-progress">
          {task.items.map((r) => (
            <li key={r.id} className={`s-${r.state}`}>
              <span className="dy-title">{r.title || r.id}</span>
              <span className="small">{r.state === "running" ? `${Math.round(r.pct * 100)}%` : r.state === "done" ? "✓ đã tạo job" : r.state === "error" ? `lỗi: ${r.error}` : "đang chờ"}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
