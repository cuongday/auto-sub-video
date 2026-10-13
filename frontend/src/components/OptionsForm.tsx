import { useEffect, useState } from "react";
import { api } from "../api";
import type { Job, Options, Settings } from "../types";

export default function OptionsForm({ job, options, s, set, onRefUpload }: {
  job: Job; options: Options; s: Settings; set: (patch: Partial<Settings>) => void; onRefUpload: (f: File) => void;
}) {
  const [voices, setVoices] = useState<{ id: string; label: string }[]>([]);
  const [voiceErr, setVoiceErr] = useState("");
  const eng = options.engines;
  useEffect(() => {
    setVoiceErr("");
    if (s.tts_engine === "edge") { setVoices(options.tts.edge); return; }
    setVoices([]);
    api.voices("vieneu").then(setVoices).catch((e) => setVoiceErr(e.message));
  }, [s.tts_engine, options]);

  const llm = options.llm[s.llm_provider];
  return (
    <div className="opts">
      <fieldset>
        <legend>Nhận dạng giọng nói</legend>
        <label>Ngôn ngữ video
          <select value={s.lang} onChange={(e) => set({ lang: e.target.value as Settings["lang"], asr_model: "" })}>
            <option value="zh">Tiếng Trung</option><option value="en">Tiếng Anh</option>
          </select>
        </label>
        <label>Model
          <select value={s.asr_model || options.asr[s.lang][0].id} onChange={(e) => set({ asr_model: e.target.value })}>
            {options.asr[s.lang].map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </label>
        {!eng.asr[s.lang].ok && <p className="warn">{eng.asr[s.lang].hint}</p>}
        {!eng.separate.ok && <p className="warn">Demucs: {eng.separate.hint}</p>}
      </fieldset>

      <fieldset>
        <legend>Dịch</legend>
        <label>Nhà cung cấp
          <select value={s.llm_provider} onChange={(e) => set({ llm_provider: e.target.value as Settings["llm_provider"], llm_model: "" })}>
            <option value="gemini">Gemini (Vertex AI)</option>
            <option value="openai" disabled={!eng.llm.openai.ok}>OpenAI{eng.llm.openai.ok ? "" : " — chưa có API key"}</option>
          </select>
        </label>
        <label>Model
          <input list="llm-models" value={s.llm_model} placeholder={llm.default} onChange={(e) => set({ llm_model: e.target.value.trim() })} />
          <datalist id="llm-models">{llm.models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</datalist>
        </label>
        {!eng.llm[s.llm_provider].ok && <p className="warn">{eng.llm[s.llm_provider].hint}</p>}
        <label className="wide">Ghi chú cho người dịch
          <textarea rows={2} value={s.translator_notes} placeholder="Ví dụ: phim cổ trang, xưng ta/ngươi; giữ nguyên tên thương hiệu…"
            onChange={(e) => set({ translator_notes: e.target.value })} />
        </label>
      </fieldset>

      <fieldset>
        <legend>Thuyết minh</legend>
        <label>Engine
          <select value={s.tts_engine} onChange={(e) => set({ tts_engine: e.target.value as Settings["tts_engine"], tts_voice: "" })}>
            <option value="edge">Edge TTS (online)</option>
            <option value="vieneu" disabled={!eng.tts.vieneu.ok}>VieNeu-TTS (chạy máy){eng.tts.vieneu.ok ? "" : " — chưa cài"}</option>
          </select>
        </label>
        <label>Giọng
          <select value={s.tts_voice} onChange={(e) => set({ tts_voice: e.target.value })} disabled={s.tts_engine === "vieneu" && !!s.ref_audio}>
            <option value="">Mặc định</option>
            {voices.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
          </select>
        </label>
        {voiceErr && <p className="warn">{voiceErr}</p>}
        <label>Tốc độ đọc <output>{s.tts_rate.toFixed(2)}×</output>
          <input type="range" min={0.8} max={1.3} step={0.05} value={s.tts_rate} onChange={(e) => set({ tts_rate: +e.target.value })} />
        </label>
        <label>Âm lượng nhạc nền <output>{s.bg_volume_db > 0 ? "+" : ""}{s.bg_volume_db} dB</output>
          <input type="range" min={-20} max={6} step={1} value={s.bg_volume_db} onChange={(e) => set({ bg_volume_db: +e.target.value })} />
        </label>
        {s.tts_engine === "vieneu" && (
          <div className="wide ref">
            <span>Nhân bản giọng từ file mẫu (3–8 giây, giọng rõ, không nhạc):</span>
            {s.ref_audio ? (
              <span className="row">
                <audio controls src={api.file(job.id, "ref.wav", job.created)} />
                <button className="ghost" onClick={() => set({ ref_audio: null })}>Bỏ giọng mẫu</button>
              </span>
            ) : (
              <input type="file" accept="audio/*,video/*" onChange={(e) => e.target.files?.[0] && onRefUpload(e.target.files[0])} />
            )}
          </div>
        )}
      </fieldset>
    </div>
  );
}
