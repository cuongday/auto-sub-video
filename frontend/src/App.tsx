import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "./api";
import { useDialog } from "./components/Dialog";
import { STATE_LABEL, STEP_LABEL } from "./labels";
import type { Job, JobEvent, Options, Project } from "./types";
import { useEvents } from "./useEvents";
import DouyinImport from "./views/DouyinImport";
import Login from "./views/Login";
import NewJob from "./views/NewJob";
import Progress from "./views/Progress";
import ProjectView from "./views/ProjectView";
import Result from "./views/Result";
import Review from "./views/Review";
import Setup from "./views/Setup";

type View = "setup" | "progress" | "review" | "result";
type Section = "subs" | "douyin";

const readOpen = (): boolean => { try { return localStorage.getItem("autosub.jobsOpen") !== "0"; } catch { return true; } };
const saveOpen = (v: boolean) => { try { localStorage.setItem("autosub.jobsOpen", v ? "1" : "0"); } catch { /* private mode */ } };
const NO_PROJECT = "_none";
const readExpanded = (): Set<string> => { try { return new Set(JSON.parse(localStorage.getItem("autosub.projOpen") || "[]")); } catch { return new Set(); } };
const saveExpanded = (v: Set<string>) => { try { localStorage.setItem("autosub.projOpen", JSON.stringify([...v])); } catch { /* private mode */ } };
const stateBadge = (j: Job) => (j.state === "running" && j.current_step ? STEP_LABEL[j.current_step] : STATE_LABEL[j.state]);

function defaultView(j: Job): View {
  if (j.state === "running" || j.state === "queued" || j.state === "error" || j.state === "cancelled" || j.state === "interrupted") return "progress";
  if (j.state === "awaiting_review") return "review";
  if (j.state === "done" || j.state === "approved") return "result";
  return "setup";
}

export default function App() {
  const [options, setOptions] = useState<Options | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [sel, setSel] = useState<string | null>(() => new URLSearchParams(location.search).get("job"));
  const [section, setSection] = useState<Section>(() => new URLSearchParams(location.search).get("tab") === "douyin" ? "douyin" : "subs");
  const [jobsOpen, setJobsOpen] = useState(readOpen);
  const [dyActive, setDyActive] = useState(0);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selProject, setSelProject] = useState<string | null>(() => new URLSearchParams(location.search).get("project"));
  const [expanded, setExpanded] = useState<Set<string>>(readExpanded);
  const [dyProject, setDyProject] = useState<string>("");     // project new Douyin downloads go into
  const [view, setView] = useState<View>("setup");
  const [pct, setPct] = useState<Record<string, Record<string, number>>>({});
  const [logs, setLogs] = useState<Record<string, string[]>>({});
  const [fatal, setFatal] = useState("");
  const [checks, setChecks] = useState<{ name: string; ok: boolean; hint: string }[]>([]);
  const dialog = useDialog();

  const [authed, setAuthed] = useState<boolean | null>(null);
  const refresh = useCallback(() => api.jobs().then(setJobs).catch((e) => setFatal(e.message)), []);
  const refreshProjects = useCallback(() => api.projects().then(setProjects).catch(() => {}), []);
  useEffect(() => {
    fetch("/api/auth").then((r) => r.json()).then((a) => setAuthed(a.ok)).catch(() => setAuthed(true));
  }, []);
  useEffect(() => {
    if (!authed) return;
    api.options().then(setOptions).catch((e) => setFatal(`Không kết nối được server: ${e.message}`));
    api.health().then((h) => setChecks(h.checks.filter((c) => !c.ok))).catch(() => {});
    refresh(); refreshProjects();
  }, [refresh, refreshProjects, authed]);

  const job = jobs.find((j) => j.id === sel) ?? null;
  const replace = (j: Job) => setJobs((all) => all.some((x) => x.id === j.id) ? all.map((x) => x.id === j.id ? j : x) : [j, ...all]);
  const expand = (pid: string, open = true) => setExpanded((e) => {
    if (e.has(pid) === open) return e;
    const n = new Set(e); open ? n.add(pid) : n.delete(pid); saveExpanded(n); return n;
  });
  const select = (id: string | null, v?: View) => {
    setSel(id); setSelProject(null); setSection("subs");
    const j = jobs.find((x) => x.id === id);
    if (j) { setView(v ?? defaultView(j)); expand(j.project ?? NO_PROJECT); }
    history.replaceState(null, "", id ? `?job=${id}` : location.pathname);
  };
  const openProject = (pid: string) => {
    setSel(null); setSelProject(pid); setSection("subs"); expand(pid);
    history.replaceState(null, "", `?project=${pid}`);
  };
  const newProject = async (sourceUrl = "", name = "") => {
    const n = name || await dialog.prompt({ title: "Project mới", message: "Mỗi project gom video của một kênh (Douyin hoặc nguồn khác) và dùng chung một preset.",
      placeholder: "Ví dụ: Kênh 土豆 — vlog", confirmLabel: "Tạo project" });
    if (!n) return null;
    const p = await api.createProject(n, sourceUrl);
    await refreshProjects();
    return p;
  };
  const putProject = (p?: Project) => { if (p) setProjects((all) => all.map((x) => x.id === p.id ? p : x)); refresh(); refreshProjects(); };
  const project = projects.find((p) => p.id === selProject) ?? null;
  const openDouyin = (pid?: string) => { if (pid !== undefined) setDyProject(pid); setSection("douyin"); history.replaceState(null, "", "?tab=douyin"); };
  const toggleJobs = () => setJobsOpen((o) => { saveOpen(!o); return !o; });
  const onDyActive = useCallback((n: number) => setDyActive(n), []);
  const busyJobs = jobs.filter((j) => j.state === "running" || j.state === "queued").length;
  useEffect(() => { if (job && view === "setup" && job.state !== "new" && defaultView(job) !== "setup") setView(defaultView(job)); }, [sel, jobs.length]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEvents((e: JobEvent) => {
    if (e.type === "progress") setPct((p) => ({ ...p, [e.job]: { ...p[e.job], [e.step]: e.pct } }));
    if (e.type === "log") setLogs((l) => ({ ...l, [e.job]: [...(l[e.job] ?? []), e.msg] }));
    if (e.type === "state" || (e.type === "progress" && (e.pct === 0 || e.pct === 1))) {
      api.job(e.job).then((j) => {
        replace(j);
        if (e.type === "state" && j.id === sel && ["awaiting_review", "done", "approved"].includes(j.state)) setView(defaultView(j));
      }).catch(() => {});
    }
  });

  const run = async (mode: "review" | "auto", fromStep?: string | null) => {
    if (!job) return;
    const go = (confirm: boolean) => api.run(job.id, mode, fromStep || null, confirm);
    try {
      replace(await go(false));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.message.startsWith("NEEDS_CONFIRM")) {
        const ok = await dialog.confirm({
          title: "Ghi đè phụ đề đã sửa?",
          message: "Chạy lại sẽ nhận dạng và dịch lại từ đầu, các câu bạn đã sửa tay sẽ bị thay thế.",
          confirmLabel: "Chạy lại", danger: true,
        });
        if (!ok) return;
        replace(await go(true));
      } else throw e;
    }
    setLogs((l) => ({ ...l, [job.id]: [] })); setPct((p) => ({ ...p, [job.id]: {} }));
    setView("progress");
  };

  const removeJob = async (j: Job) => {
    const ok = await dialog.confirm({
      title: "Xoá video đã xử lý?",
      message: (
        <>
          <p><strong>{j.name}</strong></p>
          <p className="muted">Xoá toàn bộ dữ liệu đã xử lý của job này: âm thanh tách, phụ đề, giọng thuyết minh và video thành phẩm.
            {j.uploaded ? " File video đã tải lên cũng bị xoá." : " File video gốc trên máy của bạn được giữ nguyên."}</p>
        </>
      ),
      confirmLabel: "Xoá", danger: true,
    });
    if (!ok) return;
    try { await api.remove(j.id); select(null); refresh(); } catch (e) { setFatal((e as Error).message); }
  };

  if (authed === false) return <Login onDone={() => setAuthed(true)} />;
  if (fatal) return <div className="app"><p className="error">{fatal}</p></div>;
  if (!options) return <div className="app"><p className="muted pad">Đang tải…</p></div>;

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand"><span className="logo" aria-hidden /> Auto-Sub</div>
        <nav className="side-nav" aria-label="Chức năng">
          <div className={`nav-group ${section === "subs" ? "on" : ""}`}>
            <div className="nav-head">
              <button className="nav-item" aria-current={section === "subs" ? "page" : undefined}
                onClick={() => { if (section !== "subs") { setSection("subs"); history.replaceState(null, "", sel ? `?job=${sel}` : location.pathname); } if (!jobsOpen) toggleJobs(); }}>
                <span className="nav-ico" aria-hidden>🎬</span>
                <span className="nav-label" title="Làm phụ đề &amp; thuyết minh">Làm phụ đề video</span>
                {busyJobs > 0 && <span className="nav-count" title="Job đang chạy hoặc đang chờ">{busyJobs}</span>}
              </button>
              <button className="nav-toggle" aria-expanded={jobsOpen} aria-controls="side-jobs"
                aria-label={jobsOpen ? "Thu gọn danh sách video" : "Mở rộng danh sách video"} onClick={toggleJobs}>
                <span className={`chev ${jobsOpen ? "open" : ""}`} aria-hidden>›</span>
              </button>
            </div>
            {jobsOpen && (
              <div id="side-jobs" className="nav-sub">
                <div className="row nav-actions">
                  <button className={`new grow ${section === "subs" && sel === null && !selProject ? "on" : ""}`} onClick={() => select(null)}>+ Video mới</button>
                  <button className="new" title="Tạo project mới" onClick={async () => { const p = await newProject(); if (p) openProject(p.id); }}>+ Project</button>
                </div>
                <ul className="projects">
                  {[...projects.map((p) => ({ id: p.id, name: p.name, real: true })),
                    ...(jobs.some((j) => !j.project || !projects.some((p) => p.id === j.project)) ? [{ id: NO_PROJECT, name: "Không thuộc project", real: false }] : [])
                  ].map((p) => {
                    const mine = jobs.filter((j) => p.real ? j.project === p.id : !j.project || !projects.some((x) => x.id === j.project));
                    const open = expanded.has(p.id);
                    const pending = mine.filter((j) => j.state === "done").length;
                    return (
                      <li key={p.id} className={`proj ${p.real ? "" : "loose"}`}>
                        <div className={`proj-head ${section === "subs" && selProject === p.id ? "on" : ""}`}>
                          <button className="proj-toggle" aria-expanded={open} aria-label={open ? `Thu gọn ${p.name}` : `Mở ${p.name}`} onClick={() => expand(p.id, !open)}>
                            <span className={`chev ${open ? "open" : ""}`} aria-hidden>›</span>
                          </button>
                          <button className="proj-name" onClick={() => p.real ? openProject(p.id) : expand(p.id, !open)} title={p.name}>
                            <span aria-hidden>{p.real ? "📂" : "📄"}</span> <span className="jname">{p.name}</span>
                          </button>
                          <span className="proj-count" title={pending ? `${pending} video xong chờ duyệt` : `${mine.length} video`}>
                            {pending ? <span className="badge s-done">{pending}</span> : mine.length}
                          </span>
                        </div>
                        {open && (
                          <ul className="jobs">
                            {mine.map((j) => (
                              <li key={j.id}>
                                <button className={section === "subs" && j.id === sel ? "on" : ""} onClick={() => select(j.id)}>
                                  <span className="jname">{j.name}</span>
                                  <span className={`badge s-${j.state}`}>{stateBadge(j)}</span>
                                </button>
                              </li>
                            ))}
                            {!mine.length && <li className="muted small nav-empty">Chưa có video.</li>}
                          </ul>
                        )}
                      </li>
                    );
                  })}
                  {!jobs.length && !projects.length && <li className="muted small nav-empty">Chưa có video nào.</li>}
                </ul>
              </div>
            )}
          </div>
          <div className={`nav-group ${section === "douyin" ? "on" : ""}`}>
            <button className="nav-item" aria-current={section === "douyin" ? "page" : undefined} onClick={() => openDouyin()}>
              <span className="nav-ico" aria-hidden>⬇</span>
              <span className="nav-label">Tải video Douyin</span>
              {dyActive > 0 && <span className="nav-count" title="Video đang tải">{dyActive}</span>}
            </button>
          </div>
        </nav>
        {checks.length > 0 && (
          <div className="checks">
            <strong>Cần cấu hình</strong>
            {checks.map((c) => <p key={c.name} title={c.hint}>• {c.name}: <span className="muted">{c.hint}</span></p>)}
          </div>
        )}
      </aside>
      <main className="main">
        {/* kept mounted while hidden so downloads to a folder keep going when you switch screens */}
        <div hidden={section !== "douyin"}>
          <DouyinImport onJobsCreated={refresh} onActive={onDyActive}
            projects={projects} project={dyProject} onProject={setDyProject} onNewProject={newProject} onOpenProject={openProject}
            onOpenJob={(id) => { refresh(); select(id, "setup"); }} />
        </div>
        {section !== "subs" ? null : project && !job ? (
          <ProjectView key={project.id} project={project} jobs={jobs} onOpenJob={(id) => select(id)} onChanged={putProject}
            onAddVideos={() => openDouyin(project.id)}
            onDeleted={() => { setSelProject(null); history.replaceState(null, "", location.pathname); refresh(); refreshProjects(); }} />
        ) : !job ? (
          <NewJob onBatch={refresh} projects={projects}
            onCreated={(j) => { replace(j); setSel(j.id); setView("setup"); expand(j.project ?? NO_PROJECT); history.replaceState(null, "", `?job=${j.id}`); }} />
        ) : (
          <>
            <header className="job-head">
              <div>
                {job.project && projects.some((p) => p.id === job.project) && (
                  <button className="link small crumb" onClick={() => openProject(job.project!)}>📂 {projects.find((p) => p.id === job.project)!.name} /</button>
                )}
                <h1>{job.name}</h1>
                <span className="muted small">{job.source}</span>
              </div>
              <label className="inline small job-proj">Project
                <select value={job.project ?? ""} disabled={job.state === "running" || job.state === "queued"} onChange={async (e) => {
                  const pid = e.target.value || null;
                  const p = projects.find((x) => x.id === pid);
                  const take = !!p?.preset && await dialog.confirm({
                    title: `Áp preset của “${p.name}”?`, message: "Đặt vị trí phụ đề, vùng che, font và giọng đọc của video này theo preset của project.",
                    confirmLabel: "Áp preset", cancelLabel: "Chỉ chuyển project",
                  });
                  try { replace(await api.setJobProject(job.id, pid, take)); refreshProjects(); } catch (err) { setFatal((err as Error).message); }
                }}>
                  <option value="">Không thuộc project</option>
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </label>
              <nav className="tabs" aria-label="Màn hình">
                <button className={view === "setup" ? "on" : ""} onClick={() => setView("setup")}>Thiết lập</button>
                <button className={view === "progress" ? "on" : ""} onClick={() => setView("progress")}>Tiến độ</button>
                <button className={view === "review" ? "on" : ""} disabled={job.steps.translate.status !== "done"} onClick={() => setView("review")}>Rà soát</button>
                <button className={view === "result" ? "on" : ""} disabled={!job.files["output.mp4"]} onClick={() => setView("result")}>Kết quả</button>
              </nav>
              <button className="icon danger" title="Xoá job" aria-label="Xoá job" disabled={job.state === "running" || job.state === "queued"}
                onClick={() => removeJob(job)}>🗑</button>
            </header>
            {view === "setup" && <Setup job={job} options={options} onJob={replace} onRun={(m) => run(m)} />}
            {view === "progress" && (
              <Progress job={job} steps={options.steps} pct={pct[job.id] ?? {}} logs={logs[job.id] ?? []}
                onCancel={() => api.cancel(job.id)} onRetry={(step) => run(job.mode, step || job.stale_from)} />
            )}
            {view === "review" && <Review key={job.id} job={job} fonts={options.fonts} onJob={replace} onRender={() => run("review", "tts")} />}
            {view === "result" && <Result job={job} onEdit={() => setView("review")} onSetup={() => setView("setup")}
              project={projects.find((p) => p.id === job.project) ?? null} onJob={replace} onProject={putProject}
              onRefresh={() => api.job(job.id).then(replace)} />}
            {view !== "progress" && (job.state === "done" || job.state === "approved") && job.stale_from && view !== "review" && (
              <div className="actions sticky stale">
                <span>Tuỳ chọn đã đổi từ bước “{STEP_LABEL[job.stale_from]}”.</span>
                <button className="primary" onClick={() => run(job.mode, null)}>Cập nhật video</button>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
