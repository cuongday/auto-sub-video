import { useState } from "react";
import { STATE_LABEL, STEP_LABEL } from "../labels";
import type { ApiKeyInfo, Job, Project } from "../types";
import Icon, { type IconName } from "./Icon";
import Stamp, { Serial } from "./Stamp";

export const NO_PROJECT = "_none";
const stateText = (j: Job) => (j.state === "running" && j.current_step ? STEP_LABEL[j.current_step] : STATE_LABEL[j.state]);

/** Left navigation: the subtitle workspace (projects -> videos), the Douyin downloader and film reviews.
 *  Every row is one hover target; nested buttons inside a row never paint their own hover. */
type Group = { id: string; name: string; real: boolean; icon: IconName; jobs: Job[]; running: number };

/** Projects -> jobs, with a toolbar (its own buttons + "select several to delete"). Shared by the subtitle
 *  workspace and the audio stories. */
function ProjectTree({ id, groups, tools, on, sel, selProject, expanded, unit, empty, emptyAll, onExpand, onOpenProject, onSelectJob, onDeleteProjects }: {
  id: string; groups: Group[]; tools: React.ReactNode; on: boolean; sel: string | null; selProject: string | null; expanded: Set<string>;
  unit: string; empty: string; emptyAll: string;
  onExpand: (pid: string, open: boolean) => void; onOpenProject: (pid: string) => void; onSelectJob: (id: string) => void;
  onDeleteProjects: (ids: string[]) => Promise<boolean>;
}) {
  const [selecting, setSelecting] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const realIds = groups.filter((g) => g.real).map((g) => g.id);
  const stopSelect = () => { setSelecting(false); setPicked(new Set()); };
  const toggle = (pid: string) => setPicked((s) => { const n = new Set(s); if (n.has(pid)) n.delete(pid); else n.add(pid); return n; });
  const allPicked = realIds.length > 0 && realIds.every((pid) => picked.has(pid));
  const doDelete = async () => {
    setDeleting(true);
    try { if (await onDeleteProjects(realIds.filter((pid) => picked.has(pid)))) stopSelect(); } finally { setDeleting(false); }
  };
  return (
    <div id={id} className="side-tree">
      <div className="side-tools">
        {tools}
        {realIds.length > 0 && (
          <button className={`tool icon-only ${selecting ? "on" : ""}`} aria-pressed={selecting} onClick={() => selecting ? stopSelect() : setSelecting(true)}
            title={`Chọn nhiều ${unit === "phần" ? "truyện" : "project"} để xoá`} aria-label={`Chọn nhiều ${unit === "phần" ? "truyện" : "project"} để xoá`}><Icon name="check" size={14} /></button>
        )}
      </div>
      {selecting && (
        <div className="side-tools select-bar" role="toolbar" aria-label={unit === "phần" ? "Xoá nhiều truyện" : "Xoá nhiều project"}>
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
          return (
            <li key={g.id}>
              <div className={`srow proj ${g.real ? "" : "loose"} ${on && selProject === g.id && !sel ? "on" : ""}`}>
                {selecting && g.real && (
                  <input type="checkbox" className="proj-check" tabIndex={-1} checked={picked.has(g.id)} onChange={() => toggle(g.id)}
                    aria-label={`Chọn ${g.name}`} />
                )}
                <button className="srow-chev lead" aria-expanded={open} aria-label={open ? `Thu gọn ${g.name}` : `Mở ${g.name}`}
                  onClick={() => onExpand(g.id, !open)}>
                  <Icon name="chevron" size={13} className={open ? "rot" : ""} />
                </button>
                <button className="srow-main" title={g.name}
                  onClick={() => g.real ? (selecting ? toggle(g.id) : onOpenProject(g.id)) : onExpand(g.id, !open)}>
                  <Icon name={g.icon} size={15} />
                  <span className="srow-label">{g.name}</span>
                  {g.running > 0 && <span className="pill busy" title={`${g.running} ${unit} đang chạy`}>{g.running}</span>}
                  {waiting > 0 && <span className="pill done" title={unit === "phần" ? `${waiting} phần xong` : `${waiting} video xong, chờ duyệt`}>{waiting}</span>}
                  <span className="pill" title={`${g.jobs.length} ${unit}`}>{g.jobs.length}</span>
                </button>
              </div>
              {open && (
                <ul className="tree-jobs">
                  {g.jobs.map((j, k) => (
                    <li key={j.id}>
                      <button className={`srow job ${on && j.id === sel ? "on" : ""}`} onClick={() => onSelectJob(j.id)} title={`${j.name} · ${stateText(j)}`}>
                        <span className="srow-label"><Serial n={(j.audio_part ? j.audio_part.index : k) + 1} />{j.audio_part ? j.audio_part.script_name : j.name}</span>
                        <Stamp state={j.state} job={j.id} at={j.state_at} className="jstate" title={stateText(j)} />
                      </button>
                    </li>
                  ))}
                  {!g.jobs.length && <li className="tree-empty">{empty}</li>}
                </ul>
              )}
            </li>
          );
        })}
        {!groups.length && <li className="tree-empty">{emptyAll}</li>}
      </ul>
    </div>
  );
}

/** Left navigation: the subtitle workspace (projects -> videos), audio stories (stories -> parts), the Douyin
 *  downloader and film reviews. Every row is one hover target; nested buttons inside a row never paint their own hover. */
export default function Sidebar({
  mini, onToggleMini, jobs, projects, section, sel, selProject, jobsOpen, expanded, busyJobs, dyActive, checks, apiKeys,
  onSubs, onToggleJobs, onExpand, onNewVideo, onNewProject, onOpenProject, onSelectJob, onDouyin, onReview, onApiKeys, onDeleteProjects,
  audioOpen, busyAudio, onAudio, onToggleAudio, onNewStory,
}: {
  mini: boolean; onToggleMini: () => void;
  jobs: Job[]; projects: Project[]; section: "subs" | "douyin" | "review" | "audio"; sel: string | null; selProject: string | null;
  jobsOpen: boolean; expanded: Set<string>; busyJobs: number; dyActive: number;
  checks: { name: string; hint: string }[]; apiKeys: ApiKeyInfo[];
  onSubs: () => void; onToggleJobs: () => void; onExpand: (pid: string, open: boolean) => void;
  onNewVideo: () => void; onNewProject: () => void; onOpenProject: (pid: string) => void;
  onSelectJob: (id: string) => void; onDouyin: () => void; onReview: () => void; onApiKeys: () => void;
  onDeleteProjects: (ids: string[]) => Promise<boolean>;
  audioOpen: boolean; busyAudio: number; onAudio: () => void; onToggleAudio: () => void; onNewStory: () => void;
}) {
  const known = new Set(projects.map((p) => p.id));
  const active = (list: Job[]) => list.filter((j) => j.state === "running" || j.state === "queued").length;
  // a review project's movie is shown on the project page; audio parts live under "Truyện Audio"
  const shown = jobs.filter((j) => j.kind !== "film" && j.kind !== "audio");
  const subProjects = projects.filter((p) => p.kind !== "audio");
  const groups: Group[] = [
    ...subProjects.map((p) => {
      const mine = shown.filter((j) => j.project === p.id);
      // a review project's films are hidden here but their preparation still counts as running
      return { id: p.id, name: p.name, real: true, icon: (p.kind === "review" ? "clapper" : "folder") as IconName, jobs: mine,
        running: active(p.kind === "review" ? jobs.filter((j) => j.project === p.id) : mine) };
    }),
    (() => { const loose = shown.filter((j) => !j.project || !known.has(j.project));
      return { id: NO_PROJECT, name: "Không thuộc project", real: false, icon: "inbox" as IconName, jobs: loose, running: active(loose) }; })(),
  ].filter((g) => g.real || g.jobs.length);
  const stories: Group[] = projects.filter((p) => p.kind === "audio").map((p) => {
    const parts = jobs.filter((j) => j.kind === "audio" && j.project === p.id)
      .sort((x, y) => (x.audio_part?.index ?? 0) - (y.audio_part?.index ?? 0) || x.created - y.created);
    return { id: p.id, name: p.name, real: true, icon: "headphones" as IconName, jobs: parts, running: active(parts) };
  });
  const inSubs = section === "subs";
  const inAudio = section === "audio";
  const treeProps = { sel, selProject, expanded, onExpand, onOpenProject, onSelectJob, onDeleteProjects };

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
          <ProjectTree id="side-jobs" groups={groups} on={inSubs} unit="video" empty="Chưa có video" emptyAll="Chưa có video nào" {...treeProps}
            tools={<>
              <button className={`tool grow ${inSubs && !sel && !selProject ? "on" : ""}`} onClick={onNewVideo}>
                <Icon name="plus" size={14} /> Video mới
              </button>
              <button className="tool" onClick={onNewProject} title="Tạo project mới (một kênh)">
                <Icon name="folderPlus" size={14} /> <span className="tool-text">Project</span>
              </button>
            </>} />
        )}

        <div className={`srow top ${inAudio ? "on" : ""}`}>
          <button className="srow-main" aria-current={inAudio ? "page" : undefined} onClick={onAudio} title="Truyện Audio">
            <Icon name="headphones" /> <span className="srow-label">Truyện Audio</span>
            {busyAudio > 0 && (mini ? <i className="mini-dot" title="Phần đang chạy hoặc đang chờ" />
              : <span className="pill busy" title="Phần đang chạy hoặc đang chờ">{busyAudio}</span>)}
          </button>
          <button className="srow-chev" aria-expanded={audioOpen} aria-controls="side-audio"
            aria-label={audioOpen ? "Thu gọn danh sách truyện" : "Mở rộng danh sách truyện"} onClick={onToggleAudio}>
            <Icon name="chevron" size={14} className={audioOpen ? "rot" : ""} />
          </button>
        </div>

        {audioOpen && !mini && (
          <ProjectTree id="side-audio" groups={stories} on={inAudio} unit="phần" empty="Chưa có phần nào" emptyAll="Chưa có truyện nào" {...treeProps}
            tools={
              <button className="tool grow" onClick={onNewStory} title="Tạo truyện audio mới">
                <Icon name="plus" size={14} /> Truyện mới
              </button>
            } />
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
        <button className="checks" onClick={onApiKeys} title={checks.map((c) => `${c.name}: ${c.hint}`).join("\n")}>
          <Icon name="alert" size={14} /> <span className="srow-label">Cần cấu hình {checks.length} mục</span>
          <Icon name="chevron" size={13} />
        </button>
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
