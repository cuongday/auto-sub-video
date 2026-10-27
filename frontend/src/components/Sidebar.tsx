import { useState } from "react";
import { STATE_LABEL, STEP_LABEL } from "../labels";
import type { ApiKeyInfo, Job, Project } from "../types";
import Icon from "./Icon";

export const NO_PROJECT = "_none";
const stateText = (j: Job) => (j.state === "running" && j.current_step ? STEP_LABEL[j.current_step] : STATE_LABEL[j.state]);

/** Left navigation: the subtitle workspace (projects -> videos), the Douyin downloader and film reviews.
 *  Every row is one hover target; nested buttons inside a row never paint their own hover. */
export default function Sidebar({
  mini, onToggleMini, jobs, projects, section, sel, selProject, jobsOpen, expanded, busyJobs, dyActive, checks, apiKeys,
  onSubs, onToggleJobs, onExpand, onNewVideo, onNewProject, onOpenProject, onSelectJob, onDouyin, onReview, onApiKeys, onDeleteProjects,
}: {
  mini: boolean; onToggleMini: () => void;
  jobs: Job[]; projects: Project[]; section: "subs" | "douyin" | "review"; sel: string | null; selProject: string | null;
  jobsOpen: boolean; expanded: Set<string>; busyJobs: number; dyActive: number;
  checks: { name: string; hint: string }[]; apiKeys: ApiKeyInfo[];
  onSubs: () => void; onToggleJobs: () => void; onExpand: (pid: string, open: boolean) => void;
  onNewVideo: () => void; onNewProject: () => void; onOpenProject: (pid: string) => void;
  onSelectJob: (id: string) => void; onDouyin: () => void; onReview: () => void; onApiKeys: () => void;
  onDeleteProjects: (ids: string[]) => Promise<boolean>;
}) {
  const [selecting, setSelecting] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const known = new Set(projects.map((p) => p.id));
  const shown = jobs.filter((j) => j.kind !== "film");   // a review project's movie is shown on the project page
  const groups = [
    ...projects.map((p) => ({ id: p.id, name: p.name, real: true, review: p.kind === "review", jobs: shown.filter((j) => j.project === p.id) })),
    { id: NO_PROJECT, name: "Không thuộc project", real: false, review: false, jobs: shown.filter((j) => !j.project || !known.has(j.project)) },
  ].filter((g) => g.real || g.jobs.length);
  const inSubs = section === "subs";
  const realIds = projects.map((p) => p.id);
  const stopSelect = () => { setSelecting(false); setPicked(new Set()); };
  const toggle = (id: string) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const allPicked = realIds.length > 0 && realIds.every((id) => picked.has(id));
  const doDelete = async () => {
    setDeleting(true);
    try { if (await onDeleteProjects(realIds.filter((id) => picked.has(id)))) stopSelect(); } finally { setDeleting(false); }
  };

  return (
    <aside className={`side ${mini ? "mini" : ""}`}>
      <div className="brand">
        <span className="logo" aria-hidden /> <span className="srow-label">Auto-Sub</span>
        <button className="side-toggle" onClick={onToggleMini} aria-expanded={!mini} aria-controls="side-nav" title={mini ? "Mở rộng thanh bên" : "Thu gọn thanh bên"}
          aria-label={mini ? "Mở rộng thanh bên" : "Thu gọn thanh bên"}>
          <Icon name="chevron" size={14} className={mini ? "" : "flip"} />
        </button>
      </div>

      <nav id="side-nav" className="side-nav" aria-label="Chức năng">
        <div className={`srow top ${inSubs ? "on" : ""}`}>
          <button className="srow-main" aria-current={inSubs ? "page" : undefined} onClick={onSubs} title="Làm phụ đề video">
            <Icon name="film" /> <span className="srow-label">Làm phụ đề video</span>
            {busyJobs > 0 && (mini ? <i className="mini-dot" title="Video đang chạy hoặc đang chờ" />
              : <span className="pill busy" title="Video đang chạy hoặc đang chờ">{busyJobs}</span>)}
          </button>
          <button className="srow-chev" aria-expanded={jobsOpen} aria-controls="side-jobs"
            aria-label={jobsOpen ? "Thu gọn danh sách" : "Mở rộng danh sách"} onClick={onToggleJobs}>
            <Icon name="chevron" size={14} className={jobsOpen ? "rot" : ""} />
          </button>
        </div>

        {jobsOpen && !mini && (
          <div id="side-jobs" className="side-tree">
            <div className="side-tools">
              <button className={`tool grow ${inSubs && !sel && !selProject ? "on" : ""}`} onClick={onNewVideo}>
                <Icon name="plus" size={14} /> Video mới
              </button>
              <button className="tool" onClick={onNewProject} title="Tạo project mới (một kênh)">
                <Icon name="folderPlus" size={14} /> Project
              </button>
              {projects.length > 0 && (
                <button className={`tool ${selecting ? "on" : ""}`} aria-pressed={selecting} onClick={() => selecting ? stopSelect() : setSelecting(true)}
                  title="Chọn nhiều project để xoá">Chọn</button>
              )}
            </div>
            {selecting && (
              <div className="side-tools select-bar" role="toolbar" aria-label="Xoá nhiều project">
                <span className="small">Đã chọn {picked.size}</span>
                <button className="tool" onClick={() => setPicked(new Set(allPicked ? [] : realIds))}>{allPicked ? "Bỏ chọn" : "Chọn tất cả"}</button>
                <button className="tool danger" disabled={!picked.size || deleting} onClick={doDelete}>Xoá</button>
                <button className="tool" onClick={stopSelect}>Huỷ</button>
              </div>
            )}

            <ul className="tree">
              {groups.map((g) => {
                const open = expanded.has(g.id);
                const waiting = g.jobs.filter((j) => j.state === "done").length;
                // a review project's films are hidden here but their preparation still counts as running
                const running = (g.review ? jobs.filter((j) => j.project === g.id) : g.jobs)
                  .filter((j) => j.state === "running" || j.state === "queued").length;
                return (
                  <li key={g.id}>
                    <div className={`srow proj ${g.real ? "" : "loose"} ${inSubs && selProject === g.id && !sel ? "on" : ""}`}>
                      {selecting && g.real && (
                        <input type="checkbox" className="proj-check" checked={picked.has(g.id)} onChange={() => toggle(g.id)}
                          aria-label={`Chọn ${g.name}`} />
                      )}
                      <button className="srow-chev lead" aria-expanded={open} aria-label={open ? `Thu gọn ${g.name}` : `Mở ${g.name}`}
                        onClick={() => onExpand(g.id, !open)}>
                        <Icon name="chevron" size={13} className={open ? "rot" : ""} />
                      </button>
                      <button className="srow-main" title={g.name}
                        onClick={() => g.real ? onOpenProject(g.id) : onExpand(g.id, !open)}>
                        <Icon name={g.review ? "clapper" : g.real ? "folder" : "inbox"} size={15} />
                        <span className="srow-label">{g.name}</span>
                        {running > 0 && <span className="pill busy" title={`${running} video đang chạy`}>{running}</span>}
                        {waiting > 0 && <span className="pill done" title={`${waiting} video xong, chờ duyệt`}>{waiting}</span>}
                        <span className="pill" title={`${g.jobs.length} video`}>{g.jobs.length}</span>
                      </button>
                    </div>
                    {open && (
                      <ul className="tree-jobs">
                        {g.jobs.map((j) => (
                          <li key={j.id}>
                            <button className={`srow job ${inSubs && j.id === sel ? "on" : ""}`} onClick={() => onSelectJob(j.id)} title={j.name}>
                              <span className="srow-label">{j.name}</span>
                              <span className={`jstate s-${j.state}`}><i className="dot" />{stateText(j)}</span>
                            </button>
                          </li>
                        ))}
                        {!g.jobs.length && <li className="tree-empty">Chưa có video</li>}
                      </ul>
                    )}
                  </li>
                );
              })}
              {!groups.length && <li className="tree-empty">Chưa có video nào</li>}
            </ul>
          </div>
        )}

        <div className={`srow top ${section === "douyin" ? "on" : ""}`}>
          <button className="srow-main" aria-current={section === "douyin" ? "page" : undefined} onClick={onDouyin} title="Tải video Douyin">
            <Icon name="download" /> <span className="srow-label">Tải video Douyin</span>
            {dyActive > 0 && (mini ? <i className="mini-dot" title="Video đang tải" />
              : <span className="pill busy" title="Video đang tải">{dyActive}</span>)}
          </button>
        </div>

        <div className={`srow top ${section === "review" ? "on" : ""}`}>
          <button className="srow-main" aria-current={section === "review" ? "page" : undefined} onClick={onReview} title="Review phim">
            <Icon name="clapper" /> <span className="srow-label">Review phim</span>
          </button>
        </div>
      </nav>

      <div className="side-foot">
      {checks.length > 0 && !mini && (
        <div className="checks">
          <strong><Icon name="alert" size={14} /> Cần cấu hình</strong>
          {checks.map((c) => <p key={c.name} title={c.hint}>{c.name}: <span className="muted">{c.hint}</span></p>)}
        </div>
      )}

      <button className="side-keys" onClick={onApiKeys} title="Cấu hình API key của các nhà cung cấp">
        <Icon name="key" size={15} />
        {mini && (checks.length > 0 || apiKeys.some((k) => !k.source)) && <i className="mini-dot warn" title="Cần cấu hình" />}
        <span className="srow-label">API key</span>
        <span className="side-keys-status">
          {apiKeys.map((k) => <i key={k.id} className={`dot ${k.source ? "on" : ""}`} title={`${k.label}: ${k.source ? "đã có" : "chưa có"}`} />)}
          <span className="muted small">{apiKeys.filter((k) => k.source).length}/{apiKeys.length}</span>
        </span>
      </button>
      </div>
    </aside>
  );
}
