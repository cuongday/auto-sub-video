import { type ReactNode, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { canPickFolder, pickFolder, pool, saveIntoFolder } from "../save";
import type { DyItem, DyLookup, DyTask, Project } from "../types";

type Dest = "jobs" | "folder";
type SaveRow = { id: string; title: string; state: "queued" | "running" | "done" | "error"; pct: number; file?: string; error?: string };
const SAVE_PARALLEL = 3;
const channelUrl = (secUid: string) => `https://www.douyin.com/user/${secUid}`;

const fmtDur = (s: number) => (s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : "ảnh");
const fmtDate = (t: number) => (t ? new Date(t * 1000).toLocaleDateString("vi-VN") : "");

/** Paste a Douyin video or channel link, pick videos, then download them in parallel either into new
 *  subtitle jobs (kept in storage) or straight into a folder on this computer. */
export default function DouyinImport({ onJobsCreated, onOpenJob, onActive, projects, project, onProject, onNewProject, onOpenProject }: {
  onJobsCreated: () => void; onOpenJob: (id: string) => void; onActive?: (n: number) => void;
  projects: Project[]; project: string; onProject: (id: string) => void;
  onNewProject: (sourceUrl?: string, name?: string) => Promise<Project | null>; onOpenProject: (id: string) => void;
}) {
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
  const loginPoll = useRef<number>();
  const [dest, setDest] = useState<Dest>("jobs");
  const [folder, setFolder] = useState<FileSystemDirectoryHandle | null>(null);
  const [saves, setSaves] = useState<SaveRow[] | null>(null);
  const abort = useRef<AbortController>();
  const folderOk = canPickFolder();

  useEffect(() => {
    api.presets().then((p) => setPresets(Object.keys(p))).catch(() => {});
    api.douyinSession().then(setLogin).catch(() => {});
    return () => { window.clearInterval(poll.current); window.clearInterval(loginPoll.current); abort.current?.abort(); };
  }, []);

  const running = (task && !task.done ? task.items.filter((x) => x.state !== "done" && x.state !== "error").length : 0)
    + (saves ? saves.filter((x) => x.state === "queued" || x.state === "running").length : 0);
  useEffect(() => { onActive?.(running); }, [running, onActive]);

  const lookup = async () => {
    setErr(""); setBusy("lookup"); setLook(null); setTask(null);
    try {
      const r = await api.douyinLookup(url.trim());
      setLook(r);
      if (r.kind === "channel" && r.sec_uid) {
        const same = projects.find((p) => p.source_url === channelUrl(r.sec_uid!));
        if (same) onProject(same.id);
      }
      setPicked(new Set(r.items.filter((i) => !i.is_images).map((i) => i.id)));
    } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };

  const toJobs = async (items: DyItem[]) => {
    setErr(""); setBusy("download"); setSaves(null);
    try {
      const t = await api.douyinDownload(items.map((i) => i.id), Object.fromEntries(items.map((i) => [i.id, i.title])), preset || null, project || null);
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

  const toFolder = async (items: DyItem[]) => {
    let dir = folder;
    if (!dir) { dir = await pickFolder(); if (!dir) return; setFolder(dir); }
    setErr(""); setBusy("download"); setTask(null);
    const rows: SaveRow[] = items.map((i) => ({ id: i.id, title: i.title, state: "queued", pct: 0 }));
    setSaves(rows);
    const upd = (id: string, patch: Partial<SaveRow>) => setSaves((all) => all && all.map((r) => r.id === id ? { ...r, ...patch } : r));
    abort.current = new AbortController();
    const signal = abort.current.signal;
    try {
      // fetch fresh play links for all of them in one go, so the parallel downloads start right away
      const bad = await api.douyinPrepare(items.map((i) => i.id));
      await pool(items, SAVE_PARALLEL, async (it) => {
        if (signal.aborted) { upd(it.id, { state: "error", error: "Đã huỷ" }); return; }
        if (bad[it.id]) { upd(it.id, { state: "error", error: bad[it.id]! }); return; }
        upd(it.id, { state: "running" });
        try {
          const file = await saveIntoFolder(dir!, api.douyinFileUrl(it.id, it.title), `douyin_${it.id}.mp4`,
            (p) => upd(it.id, { pct: p }), signal);
          upd(it.id, { state: "done", pct: 1, file });
        } catch (e) {
          upd(it.id, { state: "error", error: signal.aborted ? "Đã huỷ" : (e as Error).message });
        }
      });
    } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };

  /** Browsers without a folder picker (Firefox, Safari): one normal download per video. */
  const toBrowserDownloads = (items: DyItem[]) => {
    items.forEach((it, i) => window.setTimeout(() => {
      const a = document.createElement("a");
      a.href = api.douyinFileUrl(it.id, it.title); a.download = "";
      document.body.appendChild(a); a.click(); a.remove();
    }, i * 800));
  };

  const download = () => {
    if (!look) return;
    const items = look.items.filter((i) => picked.has(i.id));
    if (dest === "jobs") toJobs(items);
    else if (folderOk) toFolder(items);
    else toBrowserDownloads(items);
  };

  const startLogin = async () => {
    setLogin(await api.douyinLogin());
    window.clearInterval(loginPoll.current);
    loginPoll.current = window.setInterval(async () => {
      const s = await api.douyinSession();
      setLogin(s);
      if (s.logged_in || (s.login && !["starting", "waiting"].includes(s.login.state))) window.clearInterval(loginPoll.current);
    }, 2000);
  };

  const toggle = (id: string) => setPicked((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const videos = look?.items.filter((i) => !i.is_images) ?? [];

  return (
    <section className="card douyin">
      <header className="card-head">
        <div>
          <h2>Tải video từ Douyin</h2>
          <p className="muted small">Dán link video hoặc link kênh, chọn video rồi tải nhiều video cùng lúc.</p>
        </div>
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
          <fieldset className="dy-dest">
            <legend>Tải về đâu</legend>
            <label className={`dest ${dest === "jobs" ? "on" : ""}`}>
              <input type="radio" name="dy-dest" checked={dest === "jobs"} onChange={() => setDest("jobs")} />
              <span><strong>Tạo job làm phụ đề</strong><span className="muted small">Lưu vào kho của app, sẵn sàng để thuyết minh</span></span>
            </label>
            <label className={`dest ${dest === "folder" ? "on" : ""}`}>
              <input type="radio" name="dy-dest" checked={dest === "folder"} onChange={() => setDest("folder")} />
              <span><strong>Lưu về máy</strong><span className="muted small">
                {folderOk ? "Lưu file MP4 gốc vào thư mục bạn chọn" : "Trình duyệt này lưu vào thư mục Tải xuống mặc định"}</span></span>
            </label>
          </fieldset>
          <div className="row">
            {dest === "jobs" ? (
              <>
                <label className="inline">Project
                  <select value={project} onChange={async (e) => {
                    if (e.target.value !== "__new") { onProject(e.target.value); return; }
                    const isCh = look.kind === "channel" && look.sec_uid;
                    const p = await onNewProject(isCh ? channelUrl(look.sec_uid!) : "", "");
                    if (p) onProject(p.id);
                  }}>
                    <option value="">Không thuộc project</option>
                    {projects.map((p) => <option key={p.id} value={p.id}>{p.name}{p.preset ? " · có preset" : ""}</option>)}
                    <option value="__new">+ Tạo project mới…</option>
                  </select>
                </label>
                {look.kind === "channel" && look.sec_uid && !projects.some((p) => p.source_url === channelUrl(look.sec_uid!)) && (
                  <button className="link small" onClick={async () => {
                    const p = await onNewProject(channelUrl(look.sec_uid!), look.name || "Kênh Douyin");
                    if (p) onProject(p.id);
                  }}>Tạo project “{look.name || "kênh này"}”</button>
                )}
                <label className="inline">Preset
                  <select value={preset} onChange={(e) => setPreset(e.target.value)}>
                    <option value="">{projects.find((p) => p.id === project)?.preset ? "Preset của project" : "Không"}</option>
                    {presets.map((p) => <option key={p} value={p}>{p}</option>)}
                  </select>
                </label>
              </>
            ) : folderOk && (
              <span className="small">
                {folder ? <>Thư mục: <strong>📁 {folder.name}</strong> · </> : <span className="muted">Chưa chọn thư mục · </span>}
                <button className="link small" disabled={!!busy} onClick={async () => { const d = await pickFolder(); if (d) setFolder(d); }}>
                  {folder ? "Đổi thư mục" : "Chọn thư mục"}</button>
              </span>
            )}
            <span className="grow" />
            {busy === "download" && saves && <button className="ghost" onClick={() => abort.current?.abort()}>Huỷ</button>}
            <button className="primary" disabled={!picked.size || !!busy} onClick={download}>
              {busy === "download" ? "Đang tải…" : dest === "jobs" ? `Tải ${picked.size} video thành job mới` : `Lưu ${picked.size} video về máy`}
            </button>
          </div>
        </>
      )}
      {task && task.done && project && task.items.some((x) => x.state === "done") && (
        <p className="ok-msg">Đã thêm vào project. <button className="link" onClick={() => onOpenProject(project)}>Mở project để chạy hàng loạt →</button></p>
      )}
      {task && (
        <Progress title={`Tạo job · ${task.items.filter((x) => x.state === "done").length}/${task.items.length}`}
          rows={task.items.map((r) => ({
            id: r.id, title: r.title || r.id, state: r.state, pct: r.pct,
            note: r.state === "done" ? <button className="link small" onClick={() => onOpenJob(r.job!)}>Mở job →</button>
              : r.state === "error" ? `lỗi: ${r.error}` : null,
          }))} />
      )}
      {saves && (
        <Progress title={`Lưu về ${folder?.name ? `“${folder.name}”` : "máy"} · ${saves.filter((x) => x.state === "done").length}/${saves.length}`}
          rows={saves.map((r) => ({
            id: r.id, title: r.title || r.id, state: r.state, pct: r.pct,
            note: r.state === "done" ? `✓ ${r.file}` : r.state === "error" ? `lỗi: ${r.error}` : null,
          }))} />
      )}
    </section>
  );
}

type Row = { id: string; title: string; state: string; pct: number; note: ReactNode };

function Progress({ title, rows }: { title: string; rows: Row[] }) {
  return (
    <div className="dy-progress">
      <h4>{title}</h4>
      <ul>
        {rows.map((r) => (
          <li key={r.id} className={`s-${r.state}`}>
            <span className="dy-title">{r.title}</span>
            <span className="dy-bar" aria-hidden><span style={{ width: `${Math.round((r.state === "done" ? 1 : r.pct) * 100)}%` }} /></span>
            <span className="small dy-note">{r.note ?? (r.state === "running" ? `${Math.round(r.pct * 100)}%` : "đang chờ")}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
