import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useDialog } from "../components/Dialog";
import Icon from "../components/Icon";
import Stamp, { Serial } from "../components/Stamp";
import NotebookDialog from "../components/NotebookDialog";
import OptionsForm from "../components/OptionsForm";
import RegionPicker from "../components/RegionPicker";
import ReviewSettingsForm from "../components/ReviewSettingsForm";
import SplitEditor from "../components/SplitEditor";
import { STATE_LABEL, STEP_LABEL, fmtClock } from "../labels";
import type { Job, JobEvent, Lang, Options, Project, ReviewProjectData, ReviewSettings, Settings, Templates } from "../types";
import { useEvents } from "../useEvents";
import { Poster } from "./ReviewSource";

const MUSIC_EXT = [".mp3", ".m4a", ".aac", ".wav", ".ogg"];
const MUSIC_MAX = 50 << 20;
const LANGS: { id: Lang; label: string }[] = [{ id: "zh", label: "Tiếng Trung" }, { id: "en", label: "Tiếng Anh" }, { id: "ko", label: "Tiếng Hàn" },
  { id: "vi", label: "Tiếng Việt (thuyết minh)" }];
const busy = (j: Job) => j.state === "running" || j.state === "queued";
const ready = (j: Job) => j.state === "done" || j.state === "approved";
const filmName = (j: Job) => j.film?.episode?.name ?? j.name;
const stopped = (j: Job) => j.state === "error" || j.state === "interrupted" || j.state === "cancelled";

/** A review project: the film(s) being prepared, how they are split into parts, the parts, and the settings every
 *  part starts from (templates, voice, music, covered regions), plus the project notebook. */
export default function ReviewProjectView({ project, options, onOpenJob, onChanged, onDeleted }: {
  project: Project; options: Options; onOpenJob: (id: string) => void; onChanged: (p?: Project) => void; onDeleted: () => void;
}) {
  const pid = project.id;
  const dialog = useDialog();
  const [data, setData] = useState<ReviewProjectData | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [templates, setTemplates] = useState<Templates | null>(null);
  const [s, setS] = useState<ReviewSettings | null>(null);
  const [js, setJs] = useState<Settings | null>(null);           // null: the project has no voice settings of its own yet
  const [pct, setPct] = useState<Record<string, number>>({});     // film job -> progress of its running step
  const [langs, setLangs] = useState<Record<string, Lang>>({});
  const [filmSel, setFilmSel] = useState("");
  const [notebook, setNotebook] = useState(false);
  const [region, setRegion] = useState(0);
  const [musicV, setMusicV] = useState(0);
  const [act, setAct] = useState("");
  const saveTimer = useRef<number>();
  const pending = useRef<(() => void) | null>(null);
  const reloadTimer = useRef<number>();

  const load = () => api.reviewProject(pid).then((d) => {
    setData(d); setErr("");
    setS((cur) => cur ?? d.project.review!.settings);     // local edits win over a refresh
    setJs((cur) => cur ?? d.project.review!.job_settings);
  }).catch((e) => setErr((e as Error).message));
  const reload = () => { window.clearTimeout(reloadTimer.current); reloadTimer.current = window.setTimeout(load, 300); };
  useEffect(() => {
    load(); api.reviewTemplates().then(setTemplates).catch(() => {});
    return () => { window.clearTimeout(reloadTimer.current); window.clearTimeout(saveTimer.current); pending.current?.(); };
  }, [pid]);  // eslint-disable-line react-hooks/exhaustive-deps

  const ids = new Set([...(data?.films ?? []), ...(data?.parts ?? [])].map((j) => j.id));
  useEvents((e: JobEvent) => {
    if (e.type === "vsmov") reload();
    else if (e.type === "state" && (ids.has(e.job) || !data)) reload();
    else if (e.type === "progress" && data?.films.some((f) => f.id === e.job)) setPct((p) => ({ ...p, [e.job]: e.pct }));
  });

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setAct(key); setMsg("");
    try { await fn(); } catch (e) { setMsg((e as Error).message); } finally { setAct(""); }
  };

  /** Save the shared settings half a second after the last change (and on leaving the page). */
  const persist = (nextS: ReviewSettings, nextJs: Settings | null) => {
    window.clearTimeout(saveTimer.current);
    const save = () => { pending.current = null; api.saveReviewSettings(pid, nextS, nextJs).catch((e) => setMsg(e.message)); };
    pending.current = save;
    saveTimer.current = window.setTimeout(save, 500);
  };
  const setReview = (patch: Partial<ReviewSettings>) => { if (!s) return; const n = { ...s, ...patch }; setS(n); persist(n, js); };
  const setVoice = (patch: Partial<Settings>) => { const n = { ...(js ?? options.defaults), ...patch }; setJs(n); if (s) persist(s, n); };

  if (err && !data) return <p className="error pad" role="alert">{err}</p>;
  if (!data || !s) return <p className="muted pad" role="status">Đang tải dự án…</p>;

  const rv = data.project.review!;
  const movie = rv.movie;
  const series = movie.type !== "single" && rv.episodes.length > 1;   // a one-episode series is a single movie
  const films = data.films;
  const prepared = new Set(films.map((f) => f.film?.episode?.slug).filter(Boolean));
  const tasks = data.tasks.filter((t) => t.state !== "done");
  const pendingEps = series && rv.source === "vsmov"
    ? rv.episodes.filter((e) => !prepared.has(e.slug) && !tasks.some((t) => t.episode === e.slug && t.state !== "error")) : [];
  const splittable = films.filter(ready);
  const canSplit = !series || rv.parts_per_episode === 2;
  const film = splittable.find((f) => f.id === filmSel) ?? splittable[0];
  const partsOf = (fid: string) => data.parts.filter((p) => p.part?.film_job === fid).sort((a, b) => a.part!.index - b.part!.index);
  const cuts = film ? partsOf(film.id).slice(1).map((p) => p.part!.start) : [];
  const locked = !film ? "" : partsOf(film.id).some((p) => p.steps.script?.status === "done") ? "Đã có phần viết kịch bản, không chia lại được."
    : partsOf(film.id).some(busy) ? "Có phần đang chạy, hãy chờ hoặc huỷ trước khi chia lại." : "";
  const first = films.find((f) => f.info && f.frames.length);
  const regions = s.cover_regions;
  const voice = js ?? options.defaults;
  const prepDone = films.length > 0 && !tasks.length && films.every(ready) && !pendingEps.length;
  const splitDone = data.parts.length > 0;
  const next = data.parts.find((p) => p.state !== "approved") ?? null;
  const live = (slug?: string) => tasks.some((t) => t.episode === slug && t.state !== "error");
  const remove = async () => {
    const ok = await dialog.confirm({
      title: "Xoá dự án review?", danger: true, confirmLabel: "Xoá dự án",
      message: <><p><strong>{movie.name}</strong></p><p className="muted">Xoá hẳn {data.parts.length} phần review (kịch bản, lời đọc, video),
        {" "}{films.length} phim đã tải về{rv.music ? ", nhạc nền" : ""} và sổ tay dự án. Không khôi phục được.</p></>,
    });
    if (ok) run("delete", async () => { await api.deleteReview(pid); onDeleted(); });
  };

  return (
    <div className="rp rp-page">
      <section className="card rp-head">
        <div className="rp-poster"><Poster src={movie.poster_url || movie.thumb_url} alt={`Poster ${movie.name}`} /></div>
        <div className="rp-title">
          <h1>{movie.name}</h1>
          <p className="muted">{[movie.origin_name, movie.year, series ? `Phim bộ · ${rv.episodes.length} tập` : "Phim lẻ",
            rv.source === "upload" ? "File tải lên" : ""].filter(Boolean).join(" · ")}</p>
          {movie.categories.length > 0 && <ul className="rp-tags" aria-label="Thể loại">{movie.categories.map((c) => <li key={c}>{c}</li>)}</ul>}
        </div>
        <div className="rp-nb row">
          <button className="ghost" onClick={() => setNotebook(true)}><Icon name="book" size={15} /> Sổ tay dự án</button>
          <button className="ghost danger" disabled={!!act} onClick={remove}>{act === "delete" ? "Đang xoá…" : "Xoá dự án"}</button>
          {next && <button className="primary" onClick={() => onOpenJob(next.id)}>Mở Phần {next.part!.index}</button>}
        </div>
      </section>
      {notebook && <NotebookDialog pid={pid} onClose={() => setNotebook(false)} />}
      {msg && <p className="error" role="alert">{msg}</p>}

      <div className="ap-grid rp-layout">
        <div className="ap-work">
      <section className="card">
        <header className="card-head"><h2>Các phần</h2></header>
        {data.parts.length ? (
          <ul className="rp-parts">
            {data.parts.map((p) => {
              const i = p.part!.index;
              const f = films.find((x) => x.id === p.part!.film_job);
              const wait = p.prev_approved === false && p.steps.script?.status !== "done";
              return (
                <li key={p.id}>
                  <button className="rp-part" onClick={() => onOpenJob(p.id)}>
                    <span className="rp-part-name"><Serial n={i} /><strong>Phần {i}</strong></span>
                    <span className="meta">{series && f ? `${filmName(f)} · ` : ""}{fmtClock(p.part!.start)} – {fmtClock(p.part!.end)}</span>
                    <span className="rp-part-tags">
                      <Stamp state={p.state} job={p.id} at={p.state_at} label={p.state === "running" && p.current_step ? STEP_LABEL[p.current_step] : STATE_LABEL[p.state]} />
                      {wait && <Stamp state="wait" label={`Chờ phần ${i - 1} duyệt`} />}
                      {p.notebook_stale && <span className="rp-stale"><Icon name="alert" size={13} /> Sổ tay đã thay đổi sau khi viết kịch bản</span>}
                    </span>
                    <Icon name="chevron" size={15} />
                  </button>
                </li>
              );
            })}
          </ul>
        ) : <p className="muted">Chưa có phần nào. {canSplit ? "Chia phim ở trên rồi bấm “Tạo các phần”." : "Phần được tạo khi tập chuẩn bị xong."}</p>}
      </section>

      <details className="card rp-step" open={!prepDone}>
        <summary className="rp-step-sum">
          <h2>Chuẩn bị phim</h2>
          {prepDone ? <span className="muted small">{films.length} phim · {films.map((f) => fmtClock(f.info?.duration ?? 0)).join(", ")}</span> : null}
          {prepDone && <Stamp state="done" label="Xong" />}
        </summary>
        <p className="muted small rp-step-note">Tải phim, lấy lời thoại, nhận diện nhân vật và tóm tắt. Làm một lần cho mỗi phim hoặc tập, mọi phần dùng chung.</p>
        <ul className="rp-films">
          {tasks.map((t) => (
            <li key={t.id} className={`rp-film ${t.state === "error" ? "bad" : ""}`}>
              <span className="rp-film-name">{t.name}</span>
              {t.state === "error" ? <Stamp state="error" label="Lỗi tải" /> : <>
                <Stamp state={t.state === "queued" ? "queued" : "running"} label={t.state === "queued" ? "Đang chờ tải" : `Đang tải ${Math.round(t.pct * 100)}%`} />
                <span className="dy-bar rp-bar" role="progressbar" aria-label={`Tải ${t.name}`} aria-valuemin={0} aria-valuemax={100}
                  aria-valuenow={Math.round(t.pct * 100)}><span style={{ width: `${Math.round(t.pct * 100)}%` }} /></span>
              </>}
              {t.state === "error" && (
                <button className="ghost small" disabled={!!act} onClick={() => run(`retry-${t.id}`, async () => { await api.prepareEpisode(pid, t.episode); await load(); })}>
                  {act === `retry-${t.id}` ? "Đang bắt đầu…" : "Thử lại"}</button>
              )}
              {t.error && <p className="error small rp-film-note">{t.error}</p>}
            </li>
          ))}
          {films.map((f) => {
            const asr = !f.film?.subtitle;
            const lang = langs[f.id] ?? f.settings.lang;
            return (
              <li key={f.id} className="rp-film">
                <span className="rp-film-name">{filmName(f)}</span>
                <Stamp state={f.state} job={f.id} at={f.state_at} />
                {f.state === "running" && f.current_step && (
                  <span className="small muted">{STEP_LABEL[f.current_step] ?? f.current_step}{pct[f.id] ? ` · ${Math.round(pct[f.id] * 100)}%` : ""}</span>
                )}
                {f.info && <span className="meta">{fmtClock(f.info.duration)}</span>}
                <span className="small muted">{asr ? "Lời thoại: nhận dạng giọng nói" : `Lời thoại: phụ đề có sẵn (${f.film?.subtitle})`}</span>
                {asr && (
                  <span className="row rp-asr">
                    <select aria-label={`Ngôn ngữ thoại của ${filmName(f)}`} value={lang} disabled={busy(f)}
                      onChange={(e) => setLangs((l) => ({ ...l, [f.id]: e.target.value as Lang }))}>
                      {LANGS.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
                    </select>
                    <button className="ghost small" disabled={busy(f) || !!act} onClick={() => run(`asr-${f.id}`, async () => {
                      await api.saveSettings(f.id, { ...f.settings, lang, asr_model: lang === f.settings.lang ? f.settings.asr_model : "" });
                      await api.run(f.id, "auto", "asr", true); await load();
                    })}>{act === `asr-${f.id}` ? "Đang gửi…" : "Nhận dạng lại"}</button>
                  </span>
                )}
                {stopped(f) && f.info && (
                  <button className="ghost small" disabled={!!act} onClick={() => run(`rerun-${f.id}`, async () => { await api.run(f.id, "auto", null, true); await load(); })}>
                    {act === `rerun-${f.id}` ? "Đang gửi…" : "Chạy lại"}</button>
                )}
                {f.state === "new" && !f.info && f.film?.episode && !live(f.film.episode.slug) && (
                  <button className="ghost small" disabled={!!act} title="Lần tải trước bị ngắt giữa chừng"
                    onClick={() => run(`ep-${f.id}`, async () => { await api.prepareEpisode(pid, f.film!.episode!.slug); await load(); })}>
                    {act === `ep-${f.id}` ? "Đang bắt đầu…" : "Tải lại"}</button>
                )}
                {(f.error || f.warnings.length > 0) && (
                  <p className={`small rp-film-note ${f.error ? "error" : "warn"}`}>{f.error ?? f.warnings.join(" · ")}</p>
                )}
              </li>
            );
          })}
          {!films.length && !tasks.length && <li className="muted">Chưa có phim nào được chuẩn bị.</li>}
        </ul>
        {pendingEps.length > 0 && (
          <details className="rp-eps">
            <summary>{pendingEps.length} tập chưa chuẩn bị</summary>
            <p className="muted small">Tập chỉ nên tải khi sắp làm đến, để đỡ tốn chỗ.</p>
            <ul>
              {pendingEps.map((e) => (
                <li key={e.slug}>
                  <span>{e.name}</span>
                  <button className="ghost small" disabled={!!act} onClick={() => run(`ep-${e.slug}`, async () => { await api.prepareEpisode(pid, e.slug); await load(); })}>
                    {act === `ep-${e.slug}` ? "Đang bắt đầu…" : "Chuẩn bị tập"}</button>
                </li>
              ))}
            </ul>
          </details>
        )}
      </details>
      <details className="card rp-step" open={!splitDone}>
        <summary className="rp-step-sum">
          <h2>Chia phần</h2>
          {splitDone && <span className="muted small">{data.parts.length} phần</span>}
          {splitDone && <Stamp state="done" label="Xong" />}
        </summary>
        <header className="card-head">
          <div>
            <p className="muted small">{series ? "Mỗi tập thành một hoặc hai video review." : "Mỗi phần là một video review, làm lần lượt: phần sau viết kịch bản khi phần trước đã duyệt."}</p>
          </div>
          {series && (
            <div className="seg" role="radiogroup" aria-label="Số phần mỗi tập">
              {([1, 2] as const).map((n) => (
                <button key={n} type="button" role="radio" aria-checked={rv.parts_per_episode === n} className={rv.parts_per_episode === n ? "on" : ""}
                  disabled={!!act} onClick={() => run("ppe", async () => { onChanged(await api.saveReviewSettings(pid, s, js, n)); await load(); })}>
                  {n} phần mỗi tập</button>
              ))}
            </div>
          )}
        </header>
        {!canSplit ? <p className="muted">Mỗi tập là một phần, tạo tự động khi tập chuẩn bị xong.</p>
          : !film ? <p className="muted">Phim chuẩn bị xong mới chia được: tool cần lời thoại và bản tóm tắt để đề xuất điểm cắt.</p> : <>
            {series && splittable.length > 1 && (
              <label className="inline rp-film-pick">Tập
                <select value={film.id} onChange={(e) => setFilmSel(e.target.value)}>
                  {splittable.map((f) => <option key={f.id} value={f.id}>{filmName(f)}</option>)}
                </select>
              </label>
            )}
            <SplitEditor key={film.id} film={film} cuts={cuts} locked={locked}
              onPropose={async (by) => (await api.proposeSplit(pid, film.id, by)).cuts}
              onSave={async (c) => { onChanged(await api.saveParts(pid, film.id, c)); await load(); }} />
          </>}
      </details>
      <section className="card">
        <header className="card-head">
          <div>
            <h2>Giọng đọc & LLM</h2>
            <p className="muted small">Áp cho mọi phần chưa viết kịch bản.{js ? "" : " Đang dùng mặc định của tool."}</p>
          </div>
        </header>
        <OptionsForm options={options} s={voice} set={setVoice} review />
      </section>
        </div>
        <aside className="ap-side">
        <section className="card">
          <header className="card-head">
            <div>
              <h2>Cài đặt chung</h2>
              <p className="muted small">Phần chưa viết kịch bản tự dùng cài đặt này; từng phần vẫn chỉnh riêng được.</p>
            </div>
          </header>
          <ReviewSettingsForm value={s} templates={templates} onChange={setReview} />
        </section>

          <section className="card">
            <header className="card-head">
              <div>
                <h2>Nhạc nền</h2>
                <p className="muted small">Dùng cho mọi phần: tự lặp nếu ngắn hơn video, nhỏ dần 2 giây ở cuối. Âm thanh gốc của phim luôn tắt.</p>
              </div>
            </header>
            {rv.music && <audio className="rp-music" controls preload="none" src={api.musicUrl(pid, `${rv.music}-${musicV}`)} />}
            <div className="row">
              <label className="btn ghost small rp-file">
                {act === "music" ? "Đang tải lên…" : rv.music ? "Đổi nhạc" : "Chọn file nhạc"}
                <input type="file" accept={MUSIC_EXT.join(",")} disabled={!!act} className="sr-only" onChange={(e) => {
                  const file = e.target.files?.[0]; e.target.value = "";
                  if (!file) return;
                  if (!MUSIC_EXT.some((x) => file.name.toLowerCase().endsWith(x))) { setMsg("Định dạng nhạc không hỗ trợ (mp3, m4a, aac, wav, ogg)"); return; }
                  if (file.size > MUSIC_MAX) { setMsg("File nhạc quá lớn (tối đa 50 MB)"); return; }
                  run("music", async () => { onChanged(await api.uploadMusic(pid, file)); setMusicV(Date.now()); await load(); });
                }} />
              </label>
              {rv.music && <button className="ghost small danger" disabled={!!act}
                onClick={() => run("music-del", async () => { onChanged(await api.deleteMusic(pid)); await load(); })}>Xoá nhạc</button>}
              {!rv.music && <span className="muted small">mp3, m4a, aac, wav, ogg · tối đa 50 MB</span>}
            </div>
          </section>

          <section className="card">
            <header className="card-head">
              <div>
                <h2>Che phụ đề có sẵn</h2>
                <p className="muted small">Bản phim có phụ đề in sẵn trên hình thì khoanh vùng đó để làm mờ. Kéo trên ảnh để vẽ vùng.</p>
              </div>
              <button className="ghost small" disabled={!first || regions.length >= 5}
                onClick={() => { setReview({ cover_regions: [...regions, { x: 0.1, y: 0.8, w: 0.8, h: 0.12 }] }); setRegion(regions.length); }}>
                + Thêm vùng che</button>
            </header>
            {first ? <>
              <div className="rp-cover">
                <RegionPicker coverOnly src={api.file(first.id, `frames/${first.frames.includes("f0.jpg") ? "f0.jpg" : first.frames[0]}`)}
                  aspect={first.info!.width / first.info!.height} regions={regions} active={Math.min(region, Math.max(0, regions.length - 1))}
                  onActive={setRegion}
                  onChange={(i, r) => setReview({ cover_regions: i < regions.length ? regions.map((x, k) => k === i ? r : x) : [...regions, r] })}
                  onRemove={(i) => { setReview({ cover_regions: regions.filter((_, k) => k !== i) }); setRegion(0); }} />
              </div>
              <div className="row rp-cover-mode">
                <div className="seg" role="radiogroup" aria-label="Kiểu che">
                  {([["blur", "Làm mờ"], ["blur_dim", "Mờ + nền tối"], ["solid", "Dải đen"]] as const).map(([v, label]) => (
                    <button key={v} type="button" role="radio" aria-checked={s.cover === v} className={s.cover === v ? "on" : ""}
                      onClick={() => setReview({ cover: v })}>{label}</button>
                  ))}
                </div>
                <span className="muted small">{regions.length ? `${regions.length} vùng che` : "Không che vùng nào"}</span>
              </div>
            </> : <p className="muted">Phim đọc xong khung hình thì chọn vùng được.</p>}
          </section>
        </aside>
      </div>
    </div>
  );
}
