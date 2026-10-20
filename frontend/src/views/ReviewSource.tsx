import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import Icon from "../components/Icon";
import type { Lang, Project, VsCard, VsFilters, VsMovie, VsPage } from "../types";

type Source = { kind: "home" } | { kind: "search"; q: string } | { kind: "phim-le" | "phim-bo" } | { kind: "the-loai" | "quoc-gia"; slug: string };
const LANGS: { id: Lang; label: string }[] = [{ id: "zh", label: "Trung" }, { id: "en", label: "Anh" }, { id: "ko", label: "Hàn" }];
// vsmov descriptions are HTML: keep the text only (DOMParser never runs scripts)
const plain = (html: string) => new DOMParser().parseFromString(html, "text/html").body.textContent?.trim() ?? "";

export function Poster({ src, alt = "" }: { src: string; alt?: string }) {
  const [bad, setBad] = useState(false);
  return src && !bad ? <img src={src} alt={alt} loading="lazy" referrerPolicy="no-referrer" onError={() => setBad(true)} />
    : <span className="noimg" aria-hidden><Icon name="clapper" size={28} /></span>;
}

/** Start a review project: pick a movie on vsmov (search, filters, detail with servers and episodes) or upload a file. */
export default function ReviewSource({ onCreated }: { onCreated: (p: Project) => void }) {
  const [tab, setTab] = useState<"vsmov" | "upload">("vsmov");
  return (
    <section className="card review-src">
      <header className="card-head">
        <div>
          <h2>Review phim</h2>
          <p className="muted small">Chọn một bộ phim để tạo dự án: tool tải phim, đọc lời thoại rồi viết kịch bản review cho từng phần.</p>
        </div>
        <nav className="tabs" aria-label="Nguồn phim">
          <button className={tab === "vsmov" ? "on" : ""} aria-pressed={tab === "vsmov"} onClick={() => setTab("vsmov")}>
            <Icon name="search" size={14} /> Tìm trên vsmov</button>
          <button className={tab === "upload" ? "on" : ""} aria-pressed={tab === "upload"} onClick={() => setTab("upload")}>
            <Icon name="upload" size={14} /> Upload file</button>
        </nav>
      </header>
      <div hidden={tab !== "vsmov"}><VsmovSearch onCreated={onCreated} /></div>
      <div hidden={tab !== "upload"}><UploadFilm onCreated={onCreated} /></div>
    </section>
  );
}

function VsmovSearch({ onCreated }: { onCreated: (p: Project) => void }) {
  const [q, setQ] = useState("");
  const [src, setSrc] = useState<Source>({ kind: "home" });
  const [page, setPage] = useState(1);
  const [data, setData] = useState<VsPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [filters, setFilters] = useState<VsFilters | null>(null);
  const [slug, setSlug] = useState<string | null>(null);
  const scrollY = useRef(0);
  const seq = useRef(0);

  useEffect(() => { api.vsFilters().then(setFilters).catch(() => {}); }, []);
  useEffect(() => {
    const n = ++seq.current;              // only the latest request may fill the grid
    setLoading(true); setErr("");
    const req = src.kind === "home" ? api.vsHome(page) : src.kind === "search" ? api.vsSearch(src.q, page)
      : api.vsList(src.kind, "slug" in src ? src.slug : "", page);
    req.then((d) => { if (n === seq.current) setData(d); })
      .catch((e) => { if (n === seq.current) { setData(null); setErr((e as Error).message); } })
      .finally(() => { if (n === seq.current) setLoading(false); });
  }, [src, page]);

  const filter = "slug" in src ? src.slug : "";   // genre or country slug
  const go = (s: Source) => { setSrc(s); setPage(1); };
  const open = (s: string) => { scrollY.current = window.scrollY; setSlug(s); };
  const back = () => { setSlug(null); requestAnimationFrame(() => window.scrollTo(0, scrollY.current)); };
  const pick = (kind: "the-loai" | "quoc-gia", v: string) => { setQ(""); go(v ? { kind, slug: v } : { kind: "home" }); };
  const toggle = (kind: "phim-le" | "phim-bo") => { setQ(""); go(src.kind === kind ? { kind: "home" } : { kind }); };
  const title = src.kind === "home" ? "Phim mới cập nhật" : src.kind === "search" ? `Kết quả cho “${src.q}”`
    : src.kind === "phim-le" ? "Phim lẻ" : src.kind === "phim-bo" ? "Phim bộ"
    : (src.kind === "the-loai" ? filters?.genres : filters?.countries)?.find((x) => x.slug === filter)?.name ?? "";

  return (
    <>
      {slug && <MovieDetail slug={slug} onBack={back} onCreated={onCreated} />}
      <div hidden={!!slug}>
        <div className="row vs-bar">
          <form className="vs-search" role="search" onSubmit={(e) => { e.preventDefault(); go(q.trim() ? { kind: "search", q: q.trim() } : { kind: "home" }); }}>
            <Icon name="search" size={15} />
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Tên phim"
              placeholder="Tên phim hoặc tên gốc, Enter để tìm" />
          </form>
          {filters && <>
            <select aria-label="Thể loại" value={src.kind === "the-loai" ? filter : ""} onChange={(e) => pick("the-loai", e.target.value)}>
              <option value="">Thể loại</option>
              {filters.genres.map((g) => <option key={g.slug} value={g.slug}>{g.name}</option>)}
            </select>
            <select aria-label="Quốc gia" value={src.kind === "quoc-gia" ? filter : ""} onChange={(e) => pick("quoc-gia", e.target.value)}>
              <option value="">Quốc gia</option>
              {filters.countries.map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
            </select>
          </>}
          <div className="seg" role="group" aria-label="Loại phim">
            <button className={src.kind === "phim-le" ? "on" : ""} aria-pressed={src.kind === "phim-le"} onClick={() => toggle("phim-le")}>Phim lẻ</button>
            <button className={src.kind === "phim-bo" ? "on" : ""} aria-pressed={src.kind === "phim-bo"} onClick={() => toggle("phim-bo")}>Phim bộ</button>
          </div>
        </div>
        <div className="row vs-head">
          <strong>{title}</strong>
          {loading && <span className="muted small" role="status">Đang tải…</span>}
        </div>
        {err && <p className="error" role="alert">{err}</p>}
        {data && !data.items.length && !loading && <p className="muted vs-empty">Không tìm thấy phim nào. Thử tên khác hoặc tên gốc của phim.</p>}
        {data && data.items.length > 0 && (
          <ul className={`vs-grid ${loading ? "dim" : ""}`}>
            {data.items.map((c: VsCard) => (
              <li key={c.slug}>
                <button className="vs-card" onClick={() => open(c.slug)} title={c.name}>
                  <span className="vs-poster">
                    <Poster src={c.poster || c.thumb} />
                    {!!c.rating && <span className="vs-rate" aria-label={`Điểm ${c.rating.toFixed(1)}`}>{c.rating.toFixed(1)}</span>}
                  </span>
                  <span className="vs-name">{c.name}</span>
                  <span className="vs-sub muted small">{[c.origin_name, c.year].filter(Boolean).join(" · ")}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {data && data.total_pages > 1 && (
          <nav className="row vs-pages" aria-label="Phân trang">
            <button disabled={page <= 1 || loading} onClick={() => setPage(page - 1)}>← Trước</button>
            <span className="muted small">Trang {page} / {data.total_pages}</span>
            <button disabled={page >= data.total_pages || loading} onClick={() => setPage(page + 1)}>Sau →</button>
          </nav>
        )}
      </div>
    </>
  );
}

function MovieDetail({ slug, onBack, onCreated }: { slug: string; onBack: () => void; onCreated: (p: Project) => void }) {
  const [m, setM] = useState<VsMovie | null>(null);
  const [server, setServer] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const top = useRef<HTMLDivElement>(null);

  useEffect(() => { if ((top.current?.getBoundingClientRect().top ?? 0) < 0) top.current!.scrollIntoView(); }, []);
  useEffect(() => {
    let live = true;
    setM(null); setErr("");
    api.vsMovie(slug).then((d) => { if (live) { setM(d); setServer(d.default_server); } })
      .catch((e) => live && setErr((e as Error).message));
    return () => { live = false; };
  }, [slug]);

  const create = async () => {
    setBusy(true); setErr("");
    try { onCreated(await api.createReview(slug, server)); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const meta = m?.meta;
  const eps = m?.servers.find((s) => s.name === server)?.episodes ?? [];
  const single = meta?.type === "single" || eps.length === 1;      // a one-episode series is a single movie
  const facts: [string, string][] = meta ? ([
    ["Thể loại", meta.categories.join(", ")], ["Quốc gia", meta.countries.join(", ")], ["Thời lượng", meta.time],
    ["Ngôn ngữ", meta.lang], ["Đạo diễn", meta.directors.slice(0, 4).join(", ")], ["Diễn viên", meta.actors.slice(0, 8).join(", ")],
  ] as [string, string][]).filter(([, v]) => v) : [];

  return (
    <div className="vs-detail" ref={top}>
      <button className="link small" onClick={onBack}>← Quay lại danh sách</button>
      {!m && !err && <p className="muted" role="status">Đang tải thông tin phim…</p>}
      {err && <p className="error" role="alert">{err}</p>}
      {meta && m && (
        <div className="vs-movie">
          <div className="vs-poster big"><Poster src={meta.poster_url || meta.thumb_url} alt={`Poster ${meta.name}`} /></div>
          <div className="vs-info">
            <h1>{meta.name}</h1>
            <p className="muted">{[meta.origin_name, meta.year, single ? "Phim lẻ" : "Phim bộ"].filter(Boolean).join(" · ")}</p>
            {facts.length > 0 && <dl className="vs-facts">{facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>}
            {meta.content && <p className="vs-plot">{plain(meta.content)}</p>}
            {m.servers.length ? (
              <>
                <label className="inline vs-server">Server
                  <select value={server} onChange={(e) => setServer(e.target.value)}>
                    {m.servers.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
                  </select>
                  <span className="muted small">{eps.length} tập</span>
                </label>
                {!single && (
                  <ul className="vs-eps" aria-label="Danh sách tập">{eps.map((e) => <li key={e.slug}>{e.name}</li>)}</ul>
                )}
              </>
            ) : (
              <p className="vs-none"><Icon name="alert" size={15} /> Chưa có nguồn. vsmov mới có trailer của phim này, chưa tải được để review.</p>
            )}
            <div className="row vs-go">
              <button className="primary" disabled={!m.servers.length || busy} onClick={create}>
                {busy ? "Đang tạo dự án…" : single ? "Review phim này" : "Tạo dự án review cho cả bộ"}
              </button>
              {m.servers.length > 0 && <span className="muted small">
                {single ? "Tool sẽ tải phim về rồi đọc lời thoại." : "Tool tải tập 1 trước, các tập sau được tải khi cần."}</span>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function UploadFilm({ onCreated }: { onCreated: (p: Project) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [lang, setLang] = useState<Lang>("zh");
  const [pct, setPct] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const busy = pct !== null;
  const choose = () => { if (!busy) input.current?.click(); };

  const create = async () => {
    if (!file) return;
    setErr(""); setPct(0);
    try { onCreated(await api.uploadReview(file, lang, setPct)); setFile(null); }
    catch (e) { setErr((e as Error).message); } finally { setPct(null); }
  };

  return (
    <div className="vs-upload">
      <div className={`drop ${over ? "over" : ""} ${busy ? "busy" : ""}`} role="button" tabIndex={0}
        aria-label="Chọn file phim" aria-disabled={busy} onClick={choose}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(); } }}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f && !busy) setFile(f); }}>
        <input ref={input} type="file" accept=".mp4,video/mp4" hidden
          onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) setFile(f); }} />
        <strong>{file ? file.name : "Kéo thả file phim vào đây"}</strong>
        <span className="muted">{file ? `${file.size >= 2 ** 30 ? `${(file.size / 2 ** 30).toFixed(2)} GB` : `${Math.round(file.size / 2 ** 20)} MB`} · bấm để chọn file khác` : "hoặc bấm để chọn file .mp4"}</span>
      </div>
      <div className="row vs-upload-bar">
        <span className="small muted">Ngôn ngữ thoại</span>
        <div className="seg" role="radiogroup" aria-label="Ngôn ngữ thoại">
          {LANGS.map((l) => (
            <button key={l.id} role="radio" aria-checked={lang === l.id} className={lang === l.id ? "on" : ""} disabled={busy}
              onClick={() => setLang(l.id)}>{l.label}</button>
          ))}
        </div>
        <span className="grow" />
        <button className="primary" disabled={!file || busy} onClick={create}>
          {busy ? (pct! < 1 ? `Đang tải lên ${Math.round(pct! * 100)}%` : "Đang đọc video…") : "Tạo dự án review"}
        </button>
      </div>
      {busy && <span className="dy-bar vs-progress" role="progressbar" aria-label="Tiến độ tải lên"
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct! * 100)}><span style={{ width: `${Math.round(pct! * 100)}%` }} /></span>}
      {err && <p className="error" role="alert">{err}</p>}
    </div>
  );
}
