import { useState } from "react";
import { api } from "../api";
import { useDialog } from "../components/Dialog";
import Icon from "../components/Icon";
import Stamp, { Serial } from "../components/Stamp";
import { STATE_LABEL, STEP_LABEL } from "../labels";
import type { Job, JobState, Project } from "../types";

const COVER: Record<string, string> = { blur: "làm mờ", blur_dim: "mờ + nền tối", solid: "dải màu" };
const pct = (v: number) => `${Math.round(v * 100)}%`;
const FILTERS: { id: string; label: string; states: JobState[] | null }[] = [
  { id: "all", label: "Tất cả", states: null },
  { id: "new", label: "Chưa chạy", states: ["new"] },
  { id: "busy", label: "Đang chạy", states: ["queued", "running"] },
  { id: "review", label: "Chờ rà soát", states: ["awaiting_review"] },
  { id: "done", label: "Xong, chờ duyệt", states: ["done"] },
  { id: "approved", label: "Đã duyệt", states: ["approved"] },
  { id: "bad", label: "Lỗi", states: ["error", "interrupted", "cancelled"] },
];

/** One project (e.g. a Douyin channel): its preset, the batch run of not-yet-run videos and the video list. */
export default function ProjectView({ project, jobs, onOpenJob, onChanged, onDeleted, onAddVideos }: {
  project: Project; jobs: Job[]; onOpenJob: (id: string) => void; onChanged: (p?: Project) => void;
  onDeleted: () => void; onAddVideos: () => void;
}) {
  const dialog = useDialog();
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const mine = jobs.filter((j) => j.project === project.id);
  const count = (states: JobState[] | null) => states ? mine.filter((j) => states.includes(j.state)).length : mine.length;
  const shown = mine.filter((j) => { const f = FILTERS.find((x) => x.id === filter)!; return !f.states || f.states.includes(j.state); });
  const finished = mine.filter((j) => j.state === "done" || j.state === "approved");
  const fresh = count(["new"]);
  const p = project.preset;

  const act = async (key: string, fn: () => Promise<void>) => {
    setBusy(key); setMsg(null);
    try { await fn(); } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); } finally { setBusy(""); }
  };

  const runNew = () => act("run", async () => {
    const ok = await dialog.confirm({
      title: `Chạy ${fresh} video chưa chạy?`,
      message: <p>{p ? <>Mỗi video được áp preset của project (vị trí phụ đề, vùng che, font, giọng đọc) rồi chạy thẳng đến video thành phẩm.</>
        : <>Project chưa có preset nên mỗi video dùng tuỳ chọn hiện tại của nó. Nên lưu preset từ một video đã làm tốt trước.</>}</p>,
      confirmLabel: "Chạy hàng loạt",
    });
    if (!ok) return;
    const r = await api.runProject(project.id);
    setMsg({ kind: "ok", text: `Đã xếp ${r.queued.length} video vào hàng đợi${r.skipped.length ? ` · bỏ qua ${r.skipped.length} video chưa đọc được` : ""}.` });
    onChanged();
  });

  const pickPreset = (jid: string) => act("preset", async () => {
    if (!jid) return;
    onChanged(await api.saveProjectPreset(project.id, jid));
    setMsg({ kind: "ok", text: "Đã lưu preset. Video mới thêm vào project sẽ dùng các tuỳ chọn này." });
  });

  const edit = () => act("edit", async () => {
    const name = await dialog.prompt({ title: "Đổi tên project", initial: project.name, confirmLabel: "Lưu" });
    if (name) onChanged(await api.updateProject(project.id, name, project.source_url));
  });

  const remove = () => act("delete", async () => {
    const ok = await dialog.confirm({
      title: "Xoá project?", danger: true, confirmLabel: "Xoá project",
      message: <><p><strong>{project.name}</strong></p><p className="muted">Chỉ xoá project và preset của nó. {mine.length} video bên trong vẫn được giữ, chuyển sang “Không thuộc project”.</p></>,
    });
    if (!ok) return;
    await api.deleteProject(project.id); onDeleted();
  });

  return (
    <>
      <section className="card project-head">
        <header className="card-head">
          <div>
            <h2 className="with-icon"><Icon name="folder" size={18} /> {project.name}</h2>
            {project.source_url && <a className="small src-link" href={project.source_url} target="_blank" rel="noreferrer">{project.source_url}</a>}
          </div>
          <div className="row">
            <button className="ghost small" onClick={onAddVideos}><Icon name="plus" size={14} /> Thêm video từ Douyin</button>
            <button className="ghost small" disabled={!!busy} onClick={edit}>Đổi tên</button>
            <button className="ghost small danger" disabled={!!busy} onClick={remove}>Xoá project</button>
          </div>
        </header>
        <div className="stat-row">
          {FILTERS.slice(1).map((f) => (
            <button key={f.id} className={`stat ${filter === f.id ? "on" : ""}`} onClick={() => setFilter(filter === f.id ? "all" : f.id)}>
              <strong>{count(f.states)}</strong><span>{f.label}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="card">
        <header className="card-head">
          <div>
            <h2>Preset của project</h2>
            <p className="muted small">Lấy tuỳ chọn của một video đã làm tốt (vị trí phụ đề, vùng che, font, màu, giọng đọc…) để áp cho các video khác cùng kênh.</p>
          </div>
          <label className="inline preset-pick">Lấy từ video
            <select value="" disabled={!mine.length || !!busy} onChange={(e) => pickPreset(e.target.value)}>
              <option value="">{mine.length ? "Chọn video…" : "Chưa có video"}</option>
              {finished.length > 0 && <optgroup label="Đã xong">{finished.map((j) => <option key={j.id} value={j.id}>{j.name}</option>)}</optgroup>}
              {mine.length > finished.length && <optgroup label="Khác">{mine.filter((j) => !finished.includes(j)).map((j) => <option key={j.id} value={j.id}>{j.name}</option>)}</optgroup>}
            </select>
          </label>
        </header>
        {p ? (
          <div className="preset-box">
            <dl>
              <dt>Lấy từ</dt><dd>{project.preset_from}</dd>
              <dt>Vùng phụ đề</dt><dd>trái {pct(p.region.x)}, trên {pct(p.region.y)}, rộng {pct(p.region.w)}, cao {pct(p.region.h)}</dd>
              <dt>Vùng che thêm</dt><dd>{p.extra_regions?.length ? `${p.extra_regions.length} vùng` : "không"}</dd>
              <dt>Kiểu che</dt><dd>{COVER[p.cover] ?? p.cover}</dd>
              <dt>Chữ</dt><dd>{p.style.font} · <span className="swatch" style={{ background: p.style.color }} /> viền <span className="swatch" style={{ background: p.style.outline_color }} /></dd>
              <dt>Giọng đọc</dt><dd>{p.tts_engine === "vieneu" ? "VieNeu" : "Edge"} · {p.tts_voice?.replace(/^custom:/, "nhân bản: ") || "giọng mặc định"} · tốc độ ×{p.tts_rate}</dd>
              <dt>Nguồn chữ</dt><dd>{p.text_source === "ocr" ? "đọc phụ đề trên hình (OCR)" : "nhận dạng giọng nói"} · {p.lang === "zh" ? "tiếng Trung" : "tiếng Anh"}</dd>
            </dl>
            <button className="link small danger" disabled={!!busy} onClick={() => act("clear", async () => onChanged(await api.clearProjectPreset(project.id)))}>Bỏ preset</button>
          </div>
        ) : <p className="muted">Chưa có preset. Làm xong một video (chỉnh vùng phụ đề, vùng che, giọng…) rồi chọn nó ở trên.</p>}
        <div className="actions project-run">
          <button className="primary" disabled={!fresh || !!busy} onClick={runNew}>
            {busy === "run" ? "Đang xếp hàng…" : `Chạy hàng loạt ${fresh} video chưa chạy`}
          </button>
          <span className="muted small">{fresh ? "Chạy thẳng đến video thành phẩm, lần lượt từng video." : "Không còn video nào chưa chạy."}</span>
        </div>
        {msg && <p className={msg.kind === "ok" ? "ok-msg" : "error"} role={msg.kind === "err" ? "alert" : undefined}>{msg.text}</p>}
      </section>

      <section className="card">
        <header className="card-head">
          <h2>Video trong project</h2>
          <nav className="tabs filter-tabs" aria-label="Lọc theo trạng thái">
            {FILTERS.map((f) => (
              <button key={f.id} className={filter === f.id ? "on" : ""} onClick={() => setFilter(f.id)}>
                {f.label} <span className="muted">{count(f.states)}</span>
              </button>
            ))}
          </nav>
        </header>
        {shown.length ? (
          <ul className="project-jobs">
            {shown.map((j) => (
              <li key={j.id}>
                <Serial n={mine.indexOf(j) + 1} />
                <button className="pj-open" onClick={() => onOpenJob(j.id)}>
                  {j.frames[0] ? <img src={api.file(j.id, `frames/${j.frames[Math.min(2, j.frames.length - 1)]}`)} alt="" loading="lazy" /> : <span className="noimg" />}
                  <span className="pj-name">{j.name}</span>
                </button>
                <Stamp state={j.state} job={j.id} label={j.state === "running" && j.current_step ? STEP_LABEL[j.current_step] : STATE_LABEL[j.state]} />
                {j.state === "done" && <button className="ghost small" onClick={() => act(`ap-${j.id}`, async () => { await api.approve(j.id); onChanged(); })}><Icon name="check" size={14} /> Duyệt</button>}
              </li>
            ))}
          </ul>
        ) : <p className="muted pad">{mine.length ? "Không có video nào ở trạng thái này." : "Project chưa có video. Tải video từ Douyin hoặc chọn project khi tạo video mới."}</p>}
      </section>
    </>
  );
}
