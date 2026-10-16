import { useEffect, useState } from "react";
import { api } from "../api";
import type { Job, Segment, Voice } from "../types";

export const SPEAKER_COLORS = ["#F5B83D", "#6EA8FF", "#3CCB8C", "#FF9EC4", "#B48CFF", "#FF7A59"];
export const speakerColor = (n: number) => SPEAKER_COLORS[n % SPEAKER_COLORS.length];

/** Pick a TTS voice per detected speaker. Saved into job settings (speaker_voices). */
export default function SpeakerVoices({ job, segs, onSaved }: { job: Job; segs: Segment[]; onSaved: (j: Job) => void }) {
  const [voices, setVoices] = useState<Voice[]>([]);
  const st = job.settings;
  useEffect(() => { api.voices(st.tts_engine).then(setVoices).catch(() => setVoices([])); }, [st.tts_engine]);
  const counts = new Map<number, number>();
  segs.forEach((s) => { if (s.speaker != null) counts.set(s.speaker, (counts.get(s.speaker) ?? 0) + 1); });
  if (counts.size < 2) return null;
  const setVoice = async (spk: number, voice: string) => {
    const speaker_voices = { ...st.speaker_voices };
    if (voice) speaker_voices[String(spk)] = voice; else delete speaker_voices[String(spk)];
    onSaved(await api.saveSettings(job.id, { ...st, speaker_voices }));
  };
  return (
    <div className="card speakers">
      <strong>Giọng theo người nói</strong>
      <span className="muted small"> — {counts.size} người. Đổi giọng xong bấm Render, chỉ các câu đổi giọng được đọc lại.</span>
      <div className="speaker-grid">
        {[...counts.entries()].sort((a, b) => a[0] - b[0]).map(([spk, n]) => (
          <label key={spk} className="speaker-row">
            <span className="spk-dot" style={{ background: speakerColor(spk) }} />
            <span className="spk-name">Người {spk + 1} <span className="muted small">({n} câu)</span></span>
            <select value={st.speaker_voices[String(spk)] ?? ""} onChange={(e) => setVoice(spk, e.target.value)}>
              <option value="">Giọng chung của job</option>
              {voices.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
            </select>
          </label>
        ))}
      </div>
    </div>
  );
}
