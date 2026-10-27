import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import AudioBackground from "../components/AudioBackground";
import AudioParts from "../components/AudioParts";
import Icon from "../components/Icon";
import OptionsForm from "../components/OptionsForm";
import type { Job, JobEvent, Options, Project, Settings } from "../types";
import { useEvents } from "../useEvents";

const MUSIC_EXT = [".mp3", ".m4a", ".aac", ".wav", ".ogg"];
const MUSIC_MAX = 50 << 20;
const SCRIPT_EXT = [".txt", ".docx", ".srt"];
const SCRIPT_MAX = 20 << 20;
const readRunNow = () => { try { return localStorage.getItem("autosub.audioRunNow") !== "0"; } catch { return true; } };
const saveRunNow = (v: boolean) => { try { localStorage.setItem("autosub.audioRunNow", v ? "1" : "0"); } catch { /* private mode */ } };
type AudioPatch = { engine?: string; voice?: string; rate?: number; music_volume?: number };

/** An audio story: shared background video, music and voice, the script files dropped in (one part each) and
 *  the parts with their progress. Parts come from the app's job list, kept fresh by its SSE handler. */
export default function AudioProjectView({ project, options, jobs, onOpenJob, onChanged, onDelete }: {
  project: Project; options: Options; jobs: Job[]; onOpenJob: (id: string) => void; onChanged: (p?: Project) => void; onDelete: () => void;
}) {
  const pid = project.id;
  const a = project.audio!;
  const [msg, setMsg] = useState("");
  const [act, setAct] = useState("");
  const [musicV, setMusicV] = useState(0);
  const [vol, setVol] = useState(a.music_volume);
  const [voice, setVoiceS] = useState({ tts_engine: a.engine, tts_voice: a.voice, tts_rate: a.rate });
  const [pct, setPct] = useState<Record<string, number>>({});
  const [runNow, setRunNow] = useState(readRunNow);
  const [uploads, setUploads] = useState<{ name: string; pct: number }[]>([]);
  const [rejected, setRejected] = useState<{ name: string; reason: string }[]>([]);
  const [over, setOver] = useState(false);
  const pick = useRef<HTMLInputElement>(null);
  const saveTimer = useRef<number>();
  const pending = useRef<AudioPatch>({});

  /** Settings are saved half a second after the last change, and on leaving the page. */
  const flush = () => {
    window.clearTimeout(saveTimer.current);
    const body = pending.current; pending.current = {};
    if (Object.keys(body).length) api.saveAudio(pid, body).then((p) => onChanged(p)).catch((e) => setMsg(e.message));
  };
  const persist = (patch: AudioPatch) => {
    pending.current = { ...pending.current, ...patch };
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(flush, 500);
  };
  useEffect(() => () => flush(), []);  // eslint-disable-line react-hooks/exhaustive-deps

  const parts = jobs.filter((j) => j.project === pid && j.kind === "audio")
    .sort((x, y) => (x.audio_part?.index ?? 0) - (y.audio_part?.index ?? 0) || x.created - y.created);
  const ids = new Set(parts.map((j) => j.id));
  useEvents((e: JobEvent) => {
    if (e.type === "progress" && ids.has(e.job)) setPct((p) => ({ ...p, [e.job]: e.pct }));
    if (e.type === "state" && ids.has(e.job)) setPct((p) => { const n = { ...p }; delete n[e.job]; return n; });
  });

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setAct(key); setMsg("");
    try { await fn(); } catch (e) { setMsg((e as Error).message); } finally { setAct(""); }
  };

  const setVoice = (patch: Partial<Settings>) => {
    const n = { ...voice, ...patch } as typeof voice;
    setVoiceS(n);
    persist({ engine: n.tts_engine, voice: n.tts_voice, rate: n.tts_rate });
  };

  const addScripts = async (files: File[]) => {
    const bad: { name: string; reason: string }[] = [];
    const ok = files.filter((f) => {
      if (!SCRIPT_EXT.some((x) => f.name.toLowerCase().endsWith(x))) { bad.push({ name: f.name, reason: "chỉ nhận kịch bản .txt, .docx hoặc .srt" }); return false; }
      if (f.size > SCRIPT_MAX) { bad.push({ name: f.name, reason: "lớn hơn 20 MB" }); return false; }
      return true;
    });
    setRejected(bad);
    setUploads(ok.map((f) => ({ name: f.name, pct: 0 })));
    for (const f of ok) {                 // one file per request, keeps each request far under the tunnel limit
      try {
        await api.uploadScript(pid, f, runNow, (p) => setUploads((u) => u.map((x) => x.name === f.name ? { ...x, pct: p } : x)));
      } catch (e) {
        bad.push({ name: f.name, reason: (e as Error).message }); setRejected([...bad]);
      }
      setUploads((u) => u.filter((x) => x.name !== f.name));
      onChanged();
    }
  };

  const voiceSettings: Settings = { ...options.defaults, ...voice, ref_audio: null };
  return (
    <div className="rp ap">
      <section className="card rp-head ap-head">
        <div className="ap-icon"><Icon name="headphones" size={34} /></div>
        <div className="rp-title">
          <h1>{project.name}</h1>
          <p className="muted">Truyện audio · {parts.length} phần</p>
        </div>
        <div className="rp-nb row">
          <button className="ghost danger" disabled={parts.some((j) => j.state === "running" || j.state === "queued")}
            title={parts.some((j) => j.state === "running" || j.state === "queued") ? "Huỷ các phần đang chạy trước khi xoá" : undefined}
            onClick={onDelete}>Xoá truyện</button>
        </div>
      </section>
      {msg && <p className="error" role="alert">{msg}</p>}

      <div className="rp-grid">
        <section className="card">
          <header className="card-head">
            <div>
              <h2>Thiết lập chung</h2>
              <p className="muted small">Mọi phần dùng chung. Đổi thiết lập thì phần đã xong được gắn “Cần dựng lại”.</p>
            </div>
          </header>
          <AudioBackground project={project} onChanged={onChanged} />
          <div className="ap-music">
            <div className="ap-label"><strong>Nhạc nền</strong>{!a.music && <span className="badge">Không có</span>}</div>
            {a.music && <audio className="rp-music" controls preload="none" src={api.audioMusicUrl(pid, `${a.music}-${musicV}`)} />}
            <div className="row">
              <label className="btn ghost small rp-file">
                {act === "music" ? "Đang tải lên…" : a.music ? "Đổi nhạc" : "Chọn file nhạc"}
                <input type="file" accept={MUSIC_EXT.join(",")} disabled={!!act} className="sr-only" onChange={(e) => {
                  const file = e.target.files?.[0]; e.target.value = "";
                  if (!file) return;
                  if (!MUSIC_EXT.some((x) => file.name.toLowerCase().endsWith(x))) { setMsg("Định dạng nhạc không hỗ trợ (mp3, m4a, aac, wav, ogg)"); return; }
                  if (file.size > MUSIC_MAX) { setMsg("File nhạc quá lớn (tối đa 50 MB)"); return; }
                  run("music", async () => { onChanged(await api.uploadAudioMusic(pid, file)); setMusicV(Date.now()); });
                }} />
              </label>
              {a.music && <button className="ghost small danger" disabled={!!act}
                onClick={() => run("music-del", async () => onChanged(await api.deleteAudioMusic(pid)))}>Bỏ nhạc</button>}
              {!a.music && <span className="muted small">mp3, m4a, aac, wav, ogg · tối đa 50 MB · tự lặp</span>}
            </div>
            <label>Âm lượng nhạc <output>{Math.round(vol * 100)}%</output>
              <input type="range" min={0} max={100} step={1} value={Math.round(vol * 100)} disabled={!a.music}
                onChange={(e) => { const v = +e.target.value / 100; setVol(v); persist({ music_volume: v }); }} />
            </label>
          </div>
        </section>

        <section className="card">
          <header className="card-head">
            <div>
              <h2>Giọng đọc</h2>
              <p className="muted small">Bấm 🔊 để nghe thử ở tốc độ đang chọn.</p>
            </div>
          </header>
          <OptionsForm options={options} s={voiceSettings} set={setVoice} voiceOnly />
        </section>
      </div>

      <section className="card">
        <header className="card-head">
          <div>
            <h2>Thêm kịch bản</h2>
            <p className="muted small">Mỗi file là một phần: .txt, .docx hoặc .srt, tối đa 20 MB. Chọn nhiều file cùng lúc được.</p>
          </div>
          <label className="inline check">
            <input type="checkbox" checked={runNow} onChange={(e) => { setRunNow(e.target.checked); saveRunNow(e.target.checked); }} />
            Chạy ngay sau khi tải lên
          </label>
        </header>
        <div className={`drop ap-drop ${over ? "over" : ""} ${uploads.length ? "busy" : ""}`} role="button" tabIndex={0}
          aria-label="Chọn file kịch bản để tải lên" aria-disabled={!!uploads.length}
          onClick={() => !uploads.length && pick.current?.click()}
          onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !uploads.length) { e.preventDefault(); pick.current?.click(); } }}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); if (!uploads.length) addScripts([...e.dataTransfer.files]); }}>
          <Icon name="upload" size={22} />
          <strong>{uploads.length ? `Đang tải lên ${uploads.length} file…` : "Kéo thả file kịch bản vào đây"}</strong>
          <span className="muted small">hoặc bấm để chọn</span>
          <input ref={pick} type="file" multiple accept={SCRIPT_EXT.join(",")} hidden onChange={(e) => {
            const fs = [...(e.target.files ?? [])]; e.target.value = "";
            if (fs.length) addScripts(fs);
          }} />
        </div>
        {uploads.length > 0 && (
          <ul className="ap-uploads">
            {uploads.map((u) => (
              <li key={u.name}><span>{u.name}</span>
                <span className="dy-bar" role="progressbar" aria-label={`Tải lên ${u.name}`} aria-valuemin={0} aria-valuemax={100}
                  aria-valuenow={Math.round(u.pct * 100)}><span style={{ width: `${Math.round(u.pct * 100)}%` }} /></span></li>
            ))}
          </ul>
        )}
        {rejected.length > 0 && (
          <div className="error-box ap-rejected" role="alert">
            <strong>Không nhận {rejected.length} file:</strong>
            <ul>{rejected.map((r) => <li key={r.name}><strong>{r.name}</strong>: {r.reason}</li>)}</ul>
            <button className="link small" onClick={() => setRejected([])}>Ẩn</button>
          </div>
        )}
        {a.background_state !== "ready" && a.background_state !== "processing" && (
          <p className="warn small">Chưa có video nền: các phần vẫn đọc giọng được nhưng sẽ báo lỗi ở bước ghép video. Tải video nền lên trước khi chạy.</p>
        )}
      </section>

      <AudioParts parts={parts} pct={pct} onOpen={onOpenJob} onChange={() => onChanged()}
        onRunAll={async () => { await api.runProject(pid); }} />
    </div>
  );
}

/** "Truyện Audio" with no story open: the stories, or how to start one. */
export function AudioHome({ stories, onOpen, onNew }: { stories: Project[]; onOpen: (pid: string) => void; onNew: () => void }) {
  return (
    <section className="card ap-home">
      <header className="card-head">
        <div>
          <h2>Truyện Audio</h2>
          <p className="muted small">Đọc kịch bản thành giọng nói, ghép lên video nền lặp lại và nhạc nền. Mỗi truyện gồm nhiều phần, mỗi phần một file kịch bản.</p>
        </div>
        <button className="primary" onClick={onNew}><Icon name="plus" size={15} /> Truyện mới</button>
      </header>
      {stories.length ? (
        <ul className="rp-parts">
          {stories.map((p) => (
            <li key={p.id}>
              <button className="rp-part ap-story" onClick={() => onOpen(p.id)}>
                <Icon name="headphones" size={16} />
                <strong>{p.name}</strong>
                <span className="muted small">{p.jobs} phần{p.counts.done ? ` · ${p.counts.done} xong` : ""}{(p.counts.running ?? 0) + (p.counts.queued ?? 0) ? ` · ${(p.counts.running ?? 0) + (p.counts.queued ?? 0)} đang chạy` : ""}</span>
                <Icon name="chevron" size={15} />
              </button>
            </li>
          ))}
        </ul>
      ) : <p className="muted">Chưa có truyện nào. Bấm “Truyện mới” để bắt đầu.</p>}
    </section>
  );
}
