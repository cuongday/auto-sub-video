import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "./api";
import ApiKeysDialog from "./components/ApiKeysDialog";
import { useDialog } from "./components/Dialog";
import Icon from "./components/Icon";
import SideResizer, { SIDE_DEF, SIDE_MAX, SIDE_MIN } from "./components/SideResizer";
import Sidebar, { NO_PROJECT } from "./components/Sidebar";
import { STEP_LABEL } from "./labels";
import type { ApiKeyInfo, Job, JobEvent, Options, Project, Templates } from "./types";
import { useEvents } from "./useEvents";
import DouyinImport from "./views/DouyinImport";
import Login from "./views/Login";
import NewJob from "./views/NewJob";
import Progress from "./views/Progress";
import ProjectView from "./views/ProjectView";
import ReviewLayout from "./views/ReviewLayout";
import ReviewProjectView from "./views/ReviewProjectView";
import AudioProjectView, { AudioHome } from "./views/AudioProjectView";
import Result from "./views/Result";
import Review from "./views/Review";
import ReviewSource from "./views/ReviewSource";
import ScriptEditor from "./views/ScriptEditor";
import Setup from "./views/Setup";

type View = "setup" | "progress" | "review" | "result" | "script" | "layout";
type Section = "subs" | "douyin" | "review" | "audio";

const readOpen = (): boolean => { try { return localStorage.getItem("autosub.jobsOpen") !== "0"; } catch { return true; } };
const saveOpen = (v: boolean) => { try { localStorage.setItem("autosub.jobsOpen", v ? "1" : "0"); } catch { /* private mode */ } };
const readAudioOpen = (): boolean => { try { return localStorage.getItem("autosub.audioOpen") !== "0"; } catch { return true; } };
const saveAudioOpen = (v: boolean) => { try { localStorage.setItem("autosub.audioOpen", v ? "1" : "0"); } catch { /* private mode */ } };
const readSide = (): { w: number; mini: boolean } => {
  try {
    const w = Number(localStorage.getItem("autosub.sideW")), m = localStorage.getItem("autosub.sideMini");
    return { w: w >= SIDE_MIN && w <= SIDE_MAX ? w : SIDE_DEF, mini: m === null ? innerWidth < 900 : m === "1" };
  } catch { return { w: SIDE_DEF, mini: innerWidth < 900 }; }
};
const saveSide = (k: "sideW" | "sideMini", v: string) => { try { localStorage.setItem(`autosub.${k}`, v); } catch { /* private mode */ } };
const readExpanded = (): Set<string> => { try { return new Set(JSON.parse(localStorage.getItem("autosub.projOpen") || "[]")); } catch { return new Set(); } };
const saveExpanded = (v: Set<string>) => { try { localStorage.setItem("autosub.projOpen", JSON.stringify([...v])); } catch { /* private mode */ } };

function defaultView(j: Job): View {
  if (j.kind === "audio") return j.files["output.mp4"] && (j.state === "done" || j.state === "approved") ? "result" : "progress";
  if (j.kind === "review" && (j.state === "new" || j.state === "awaiting_review")) return "script";
  if (j.state === "running" || j.state === "queued" || j.state === "error" || j.state === "cancelled" || j.state === "interrupted") return "progress";
  if (j.state === "awaiting_review") return "review";
  if (j.state === "done" || j.state === "approved") return "result";
  return "setup";
}

export default function App() {
  const [options, setOptions] = useState<Options | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [sel, setSel] = useState<string | null>(() => new URLSearchParams(location.search).get("job"));
  const [section, setSection] = useState<Section>(() => {
    const t = new URLSearchParams(location.search).get("tab");
    return t === "douyin" || t === "review" || t === "audio" ? t : "subs";
  });
  const [reviewSeen, setReviewSeen] = useState(section === "review");   // mounted on first visit, then kept (uploads)
  const [jobsOpen, setJobsOpen] = useState(readOpen);
  const [audioOpen, setAudioOpen] = useState(readAudioOpen);
  const [side, setSide] = useState(readSide);
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
  const [templates, setTemplates] = useState<Templates | null>(null);
  const [apiKeys, setApiKeys] = useState<ApiKeyInfo[]>([]);
  const [keysOpen, setKeysOpen] = useState(false);
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
    api.apiKeys().then(setApiKeys).catch(() => {});
    refresh(); refreshProjects();
  }, [refresh, refreshProjects, authed]);

  const job = jobs.find((j) => j.id === sel) ?? null;
  const replace = (j: Job) => setJobs((all) => all.some((x) => x.id === j.id) ? all.map((x) => x.id === j.id ? j : x) : [j, ...all]);
  const expand = (pid: string, open = true) => setExpanded((e) => {
    if (e.has(pid) === open) return e;
    const n = new Set(e); open ? n.add(pid) : n.delete(pid); saveExpanded(n); return n;
  });
  const select = (id: string | null, v?: View) => {
    const j = jobs.find((x) => x.id === id);
    setSel(id); setSelProject(null); setSection(j?.kind === "audio" ? "audio" : "subs");
    if (j) { setView(v ?? defaultView(j)); expand(j.project ?? NO_PROJECT); }
    history.replaceState(null, "", id ? `?job=${id}` : location.pathname);
  };
  const openProject = (pid: string, kind?: Project["kind"]) => {
    const k = kind ?? projects.find((p) => p.id === pid)?.kind;
    setSel(null); setSelProject(pid); setSection(k === "audio" ? "audio" : "subs"); expand(pid);
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
  const newStory = async () => {
    const n = await dialog.prompt({ title: "Truyện mới", message: "Mỗi truyện gom các phần (chương) đọc thành video, dùng chung video nền, nhạc nền và giọng đọc.",
      placeholder: "Ví dụ: Đấu Phá Thương Khung", confirmLabel: "Tạo truyện" });
    if (!n) return;
    try {
      const p = await api.createProject(n, "", "audio");
      await refreshProjects(); openProject(p.id, "audio");
    } catch (e) { await dialog.confirm({ title: "Chưa tạo được truyện", message: (e as Error).message, confirmLabel: "Đã hiểu" }); }
  };
  const putProject = (p?: Project) => { if (p) setProjects((all) => all.map((x) => x.id === p.id ? p : x)); refresh(); refreshProjects(); };
  const project = projects.find((p) => p.id === selProject) ?? null;
  // opened from a ?job= link: unfold the group holding that video so it is visible in the sidebar
  useEffect(() => { if (job) expand(job.project && projects.some((p) => p.id === job.project) ? job.project : NO_PROJECT); },  // eslint-disable-line react-hooks/exhaustive-deps
    [job?.id, job?.project, projects.length]);
  const openDouyin = (pid?: string) => { if (pid !== undefined) setDyProject(pid); setSection("douyin"); history.replaceState(null, "", "?tab=douyin"); };
  const openReview = () => { setSection("review"); setReviewSeen(true); history.replaceState(null, "", "?tab=review"); };
  const openAudio = () => {
    setSection("audio");
    const j = jobs.find((x) => x.id === sel), p = projects.find((x) => x.id === selProject);
    if (!(j?.kind === "audio" || p?.kind === "audio")) { setSel(null); setSelProject(null); }
    history.replaceState(null, "", j?.kind === "audio" ? `?job=${sel}` : p?.kind === "audio" ? `?project=${selProject}` : "?tab=audio");
    if (!audioOpen && !side.mini) toggleAudio();
  };
  const toggleAudio = () => setAudioOpen((o) => { saveAudioOpen(!o); return !o; });
  const toggleJobs = () => setJobsOpen((o) => { saveOpen(!o); return !o; });
  const setSideW = (w: number, save = true) => { const v = Math.round(Math.min(SIDE_MAX, Math.max(SIDE_MIN, w))); if (save) saveSide("sideW", String(v)); setSide((s) => ({ ...s, w: v })); };
  const toggleMini = () => setSide((s) => { saveSide("sideMini", s.mini ? "0" : "1"); return { ...s, mini: !s.mini }; });
  const onDyActive = useCallback((n: number) => setDyActive(n), []);
  const busyJobs = jobs.filter((j) => j.kind !== "audio" && (j.state === "running" || j.state === "queued")).length;
  const busyAudio = jobs.filter((j) => j.kind === "audio" && (j.state === "running" || j.state === "queued")).length;
  useEffect(() => {
    if (job && ((view === "setup" && defaultView(job) !== "setup") || ((view === "script" || view === "layout") && job.kind !== "review")
      || (job.kind === "audio" && view !== "progress" && view !== "result"))) setView(defaultView(job));
  }, [sel, jobs.length]);  // eslint-disable-line react-hooks/exhaustive-deps
  const isReview = job?.kind === "review";
  const isAudio = job?.kind === "audio";
  // a ?job= / ?project= link opens in the section it belongs to
  useEffect(() => {
    if (job && section === "subs" && isAudio) setSection("audio");
    else if (!job && project && section === "subs" && project.kind === "audio") setSection("audio");
  }, [job?.id, project?.id, isAudio, project?.kind]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (isReview && !templates) api.reviewTemplates().then(setTemplates).catch(() => {}); }, [isReview, templates]);

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
        const ok = await dialog.confirm(job.kind === "review" ? {
          title: "Viết lại kịch bản trước khi dựng?",
          message: "Cài đặt kịch bản đã đổi nên kịch bản sẽ được viết lại. Các khối bạn đã sửa tay vẫn được giữ nguyên.",
          confirmLabel: "Viết lại và chạy",
        } : {
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
    const ok = await dialog.confirm(j.kind === "audio" ? {
      title: "Xoá phần này?", confirmLabel: "Xoá", danger: true,
      message: <><p><strong>{j.audio_part?.script_name ?? j.name}</strong></p><p className="muted">Xoá kịch bản, giọng đọc và video của phần này. Không khôi phục được.</p></>,
    } : {
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
    try { await api.remove(j.id); if (j.kind === "audio" && j.project) openProject(j.project, "audio"); else select(null); refresh(); } catch (e) { setFatal((e as Error).message); }
  };

  const deleteProjects = async (ids: string[]): Promise<boolean> => {
    const doomed = projects.filter((p) => ids.includes(p.id));
    if (!doomed.length) return false;
    const videos = jobs.filter((j) => j.project && ids.includes(j.project)).length;
    const stories = doomed.every((p) => p.kind === "audio");
    const ok = await dialog.confirm({
      title: stories ? `Xoá ${doomed.length} truyện?` : `Xoá ${doomed.length} project?`,
      message: (
        <>
          <ul>{doomed.map((p) => <li key={p.id}><strong>{p.name}</strong></li>)}</ul>
          <p className="muted">{stories
            ? `Xoá luôn ${videos} phần của các truyện này (kịch bản, giọng đọc, video) cùng video nền và nhạc nền. Không khôi phục được.`
            : `Xoá luôn ${videos} video của các project này cùng toàn bộ dữ liệu đã xử lý. File video gốc trên máy của bạn được giữ nguyên.`}</p>
        </>
      ),
      confirmLabel: "Xoá", danger: true,
    });
    if (!ok) return false;
    try {
      await api.deleteProjects(ids);
    } catch (e) {
      const busy = e instanceof ApiError ? e.busy : [];
      await dialog.confirm({
        title: "Chưa xoá được",
        message: (
          <>
            <p>{(e as Error).message}</p>
            {busy.length > 0 && <ul>{busy.map((b) => <li key={b.id}><strong>{b.name}</strong></li>)}</ul>}
          </>
        ),
        confirmLabel: "Đã hiểu",
      });
      return false;
    }
    const openJob = jobs.find((j) => j.id === sel);
    if ((selProject && ids.includes(selProject)) || (openJob?.project && ids.includes(openJob.project))) {
      if (section === "audio") { setSel(null); setSelProject(null); history.replaceState(null, "", "?tab=audio"); } else select(null);
    }
    await Promise.all([refresh(), refreshProjects()]);
    return true;
  };

  if (authed === false) return <Login onDone={() => setAuthed(true)} />;
  if (fatal) return <div className="app"><p className="error">{fatal}</p></div>;
  if (!options) return <div className="app"><p className="muted pad">Đang tải…</p></div>;

  return (
    <div className="shell" style={{ "--side-w": side.mini ? "56px" : `${side.w}px` } as React.CSSProperties}>
      <Sidebar mini={side.mini} onToggleMini={toggleMini} jobs={jobs} projects={projects} section={section} sel={sel} selProject={selProject}
        jobsOpen={jobsOpen} expanded={expanded} busyJobs={busyJobs} dyActive={dyActive} checks={checks} apiKeys={apiKeys} onApiKeys={() => setKeysOpen(true)}
        onSubs={() => {
          if (section !== "subs") { setSection("subs"); history.replaceState(null, "", sel ? `?job=${sel}` : selProject ? `?project=${selProject}` : location.pathname); }
          if (!jobsOpen && !side.mini) toggleJobs();
        }}
        onToggleJobs={toggleJobs} onExpand={expand} onNewVideo={() => select(null)} onSelectJob={(id) => select(id)}
        onNewProject={async () => { const p = await newProject(); if (p) openProject(p.id); }}
        onDeleteProjects={deleteProjects} onOpenProject={(pid) => openProject(pid)} onDouyin={() => openDouyin()} onReview={openReview}
        audioOpen={audioOpen} busyAudio={busyAudio} onAudio={openAudio} onToggleAudio={toggleAudio} onNewStory={newStory} />
      {!side.mini && <SideResizer width={side.w} onWidth={setSideW} />}
      <main className="main">
        {/* kept mounted while hidden so downloads to a folder keep going when you switch screens */}
        <div hidden={section !== "douyin"}>
          <DouyinImport onJobsCreated={refresh} onActive={onDyActive}
            projects={projects.filter((p) => p.kind !== "audio")} project={dyProject} onProject={setDyProject} onNewProject={newProject} onOpenProject={openProject}
            onOpenJob={(id) => { refresh(); select(id, "setup"); }} />
        </div>
        {reviewSeen && (
          <div hidden={section !== "review"}>
            <ReviewSource onCreated={async (p) => { await Promise.all([refresh(), refreshProjects()]); openProject(p.id); }} />
          </div>
        )}
        {section !== "subs" && section !== "audio" ? null : section === "audio" && !job && !(project && project.kind === "audio") ? (
          <AudioHome stories={projects.filter((p) => p.kind === "audio")} onOpen={(pid) => openProject(pid, "audio")} onNew={newStory} />
        ) : project && !job && project.kind === "audio" ? (
          <AudioProjectView key={project.id} project={project} options={options} jobs={jobs} onOpenJob={(id) => select(id)} onChanged={putProject}
            onDelete={() => deleteProjects([project.id])} />
        ) : project && !job && project.kind === "review" ? (
          <ReviewProjectView key={project.id} project={project} options={options} onOpenJob={(id) => select(id)} onChanged={putProject}
            onDeleted={() => { setSelProject(null); history.replaceState(null, "", location.pathname); refresh(); refreshProjects(); }} />
        ) : project && !job ? (
          <ProjectView key={project.id} project={project} jobs={jobs} onOpenJob={(id) => select(id)} onChanged={putProject}
            onAddVideos={() => openDouyin(project.id)}
            onDeleted={() => { setSelProject(null); history.replaceState(null, "", location.pathname); refresh(); refreshProjects(); }} />
        ) : !job ? (
          <NewJob onBatch={refresh} projects={projects.filter((p) => p.kind !== "audio")}
            onCreated={(j) => { replace(j); setSel(j.id); setView("setup"); expand(j.project ?? NO_PROJECT); history.replaceState(null, "", `?job=${j.id}`); }} />
        ) : (
          <>
            <header className="job-head">
              <div>
                {job.project && projects.some((p) => p.id === job.project) && (
                  <button className="link small crumb" onClick={() => openProject(job.project!)}><Icon name="folder" size={13} /> {projects.find((p) => p.id === job.project)!.name} /</button>
                )}
                <h1>{job.name}</h1>
                <span className="muted small">{job.source}</span>
              </div>
              {!isReview && !isAudio && <label className="inline small job-proj">Project
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
                  {projects.filter((p) => p.kind !== "audio").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </label>}
              <nav className="tabs" aria-label="Màn hình">
                {isReview
                  ? <button className={view === "script" ? "on" : ""} onClick={() => setView("script")}>Kịch bản</button>
                  : !isAudio && <button className={view === "setup" ? "on" : ""} onClick={() => setView("setup")}>Thiết lập</button>}
                {isReview && <button className={view === "layout" ? "on" : ""} disabled={job.steps.assemble?.status !== "done"}
                  title={job.steps.assemble?.status !== "done" ? "Dựng video trước rồi mới chỉnh" : undefined} onClick={() => setView("layout")}>Bố cục</button>}
                <button className={view === "progress" ? "on" : ""} onClick={() => setView("progress")}>Tiến độ</button>
                {!isReview && !isAudio && <button className={view === "review" ? "on" : ""} disabled={job.steps.translate?.status !== "done"} onClick={() => setView("review")}>Rà soát</button>}
                <button className={view === "result" ? "on" : ""} disabled={!job.files["output.mp4"]} onClick={() => setView("result")}>Kết quả</button>
              </nav>
              <button className="icon danger" title="Xoá job" aria-label="Xoá job" disabled={job.state === "running" || job.state === "queued"}
                onClick={() => removeJob(job)}>🗑</button>
            </header>
            {view === "setup" && !isReview && !isAudio && <Setup job={job} options={options} onJob={replace} onRun={(m) => run(m)} />}
            {view === "script" && isReview && <ScriptEditor key={job.id} job={job} film={projects.find((p) => p.id === job.project)?.review?.movie.name} templates={templates} onJob={replace} onRun={(m) => run(m)} />}
            {view === "layout" && isReview && <ReviewLayout key={job.id} job={job} options={options} onJob={replace} onRun={(m) => run(m)} />}
            {view === "progress" && (
              <Progress job={job} pct={pct[job.id] ?? {}} logs={logs[job.id] ?? []}
                onCancel={() => api.cancel(job.id)} onRetry={(step) => run(job.mode, step || job.stale_from)} />
            )}
            {view === "review" && !isReview && !isAudio && <Review key={job.id} job={job} fonts={options.fonts} onJob={replace} onRender={() => run("review", "tts")} />}
            {view === "result" && <Result job={job} onEdit={() => setView(isReview ? "script" : "review")} onSetup={() => setView(isReview ? "layout" : "setup")}
              project={isAudio ? null : projects.find((p) => p.id === job.project) ?? null} onJob={replace} onProject={putProject}
              onRefresh={() => api.job(job.id).then(replace)} />}
            {view !== "progress" && (job.state === "done" || job.state === "approved") && job.stale_from && view !== "review" && view !== "script" && view !== "layout" && (
              <div className="actions sticky stale">
                <span>Tuỳ chọn đã đổi từ bước “{STEP_LABEL[job.stale_from]}”.</span>
                <button className="primary" onClick={() => run(job.mode, null)}>Cập nhật video</button>
              </div>
            )}
          </>
        )}
      </main>
      {keysOpen && <ApiKeysDialog keys={apiKeys} onClose={() => setKeysOpen(false)} onChange={(k) => {
        // a new key turns its provider on in every options form and clears the "Cần cấu hình" warning
        setApiKeys(k);
        api.options().then(setOptions).catch(() => {});
        api.health().then((h) => setChecks(h.checks.filter((c) => !c.ok))).catch(() => {});
      }} />}
    </div>
  );
}
