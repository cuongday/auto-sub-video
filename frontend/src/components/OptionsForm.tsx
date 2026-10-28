import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import CloneVoiceDialog from "./CloneVoiceDialog";
import CoverControls from "./CoverControls";
import { useDialog } from "./Dialog";
import VieneuDevice from "./VieneuDevice";
import type { Job, Options, Settings, Voice } from "../types";
import Icon from "./Icon";

const GENDER: Record<string, string> = { custom: "Giọng nhân bản", female: "Giọng nữ", male: "Giọng nam" };

/** Every option of a subtitle job. `review`: the shared voice of a review project instead (LLM, voice, subtitle font;
 *  no ASR, translation notes, original-audio volume or per-job voice sample). `voiceOnly`: just the voice block
 *  (engine, voice with sample, rate), as an audio story uses it. */
export default function OptionsForm({ job, options, s, set, onRefUpload, review = false, voiceOnly = false }: {
  job?: Job; options: Options; s: Settings; set: (patch: Partial<Settings>) => void; onRefUpload?: (f: File) => void; review?: boolean;
  voiceOnly?: boolean;
}) {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [voiceErr, setVoiceErr] = useState("");
  const [loadingVoices, setLoadingVoices] = useState(false);
  const [sampling, setSampling] = useState(false);
  const audio = useRef<HTMLAudioElement>(null);
  const [cloneOpen, setCloneOpen] = useState(false);
  const dialog = useDialog();
  const eng = options.engines;
  useEffect(() => {
    setVoiceErr(""); setVoices([]); setLoadingVoices(true);
    api.voices(s.tts_engine).then(setVoices).catch((e) => setVoiceErr(e.message)).finally(() => setLoadingVoices(false));
  }, [s.tts_engine]);
  const defaultVoice = voices.find((v) => v.default);
  const groups = Object.entries(voices.reduce<Record<string, Voice[]>>((acc, v) => {
    (acc[v.custom ? "custom" : v.gender || "other"] ??= []).push(v); return acc;
  }, {}));
  const reloadVoices = (select?: string) => api.voices(s.tts_engine).then((v) => {
    setVoices(v); if (select !== undefined) set({ tts_voice: select });
  });
  const current = voices.find((v) => v.id === s.tts_voice);
  const sample = async () => {
    setSampling(true); setVoiceErr("");
    try {
      const url = await api.voiceSample(s.tts_engine, s.tts_voice || defaultVoice?.id || "", s.tts_rate);
      if (audio.current) { audio.current.src = url; await audio.current.play(); }
    } catch (e) { setVoiceErr((e as Error).message); } finally { setSampling(false); }
  };

  const llm = options.llm[s.llm_provider];
  return (
    <div className={voiceOnly ? "opts voice-only" : "opts"}>
      {!review && !voiceOnly && <fieldset>
        <legend>Lấy lời thoại</legend>
        <div className="seg" role="radiogroup" aria-label="Nguồn lời thoại">
          <button type="button" role="radio" aria-checked={s.text_source === "asr"} className={s.text_source === "asr" ? "on" : ""}
            onClick={() => set({ text_source: "asr" })}>Nghe giọng (ASR)</button>
          <button type="button" role="radio" aria-checked={s.text_source === "ocr"} className={s.text_source === "ocr" ? "on" : ""}
            disabled={!eng.ocr?.ok} onClick={() => set({ text_source: "ocr" })}>Đọc phụ đề có sẵn (OCR)</button>
        </div>
        <p className="muted small">{s.text_source === "ocr"
          ? "Đọc chữ trong vùng “Phụ đề” đã khoanh ở trên. Chính xác hơn khi video đã có sub cứng; video không có sub sẽ ra trống."
          : "Nghe giọng nói rồi chép ra chữ. Dùng được cho mọi video."}</p>
        {!eng.ocr?.ok && <p className="warn">OCR: {eng.ocr?.hint}</p>}
        <label>Ngôn ngữ video
          <select value={s.lang} onChange={(e) => set({ lang: e.target.value as Settings["lang"], asr_model: "" })}>
            <option value="zh">Tiếng Trung</option><option value="en">Tiếng Anh</option><option value="ko">Tiếng Hàn</option>
          </select>
        </label>
        <label>Model
          <select value={s.asr_model || options.asr[s.lang][0].id} onChange={(e) => set({ asr_model: e.target.value })}>
            {options.asr[s.lang].map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </label>
        {!eng.asr[s.lang].ok && <p className="warn">{eng.asr[s.lang].hint}</p>}
        {!eng.separate.ok && <p className="warn">Demucs: {eng.separate.hint}</p>}
        <label className="inline check">
          <input type="checkbox" checked={s.separate} onChange={(e) => set({ separate: e.target.checked })} />
          Tách giọng khỏi nhạc nền (Demucs)
        </label>
        {s.lang === "zh" && (
          <label className="inline check" title="Nhận ra ai đang nói từng câu, để mỗi người một giọng thuyết minh">
            <input type="checkbox" checked={s.diarize} onChange={(e) => set({ diarize: e.target.checked })} />
            Nhận diện người nói
          </label>
        )}
        <p className="muted small">{s.separate
          ? "Thay hẳn giọng gốc, giữ nhạc nền. Tốn khoảng 0,5× thời lượng video."
          : "Nhanh hơn: giữ âm thanh gốc làm nền và tự hạ nhỏ khi có thuyết minh (kiểu thuyết minh truyền hình). Hợp với vlog, review ít nhạc."}</p>
      </fieldset>}

      {!voiceOnly && <fieldset>
        <legend>{review ? "LLM viết kịch bản" : "Dịch"}</legend>
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
        {!review && <label className="wide">Ghi chú cho người dịch
          <textarea rows={2} value={s.translator_notes} placeholder="Ví dụ: phim cổ trang, xưng ta/ngươi; giữ nguyên tên thương hiệu…"
            onChange={(e) => set({ translator_notes: e.target.value })} />
        </label>}
      </fieldset>}

      <fieldset>
        {voiceOnly ? <legend className="sr-only">Giọng đọc</legend> : <legend>{review ? "Giọng đọc" : "Thuyết minh"}</legend>}
        <label>Engine
          <select value={s.tts_engine} onChange={(e) => set({ tts_engine: e.target.value as Settings["tts_engine"], tts_voice: "" })}>
            <option value="edge">Edge TTS (online)</option>
            <option value="vieneu" disabled={!eng.tts.vieneu.ok}>VieNeu-TTS (chạy máy){eng.tts.vieneu.ok ? "" : " — chưa cài"}</option>
          </select>
        </label>
        <label>Giọng{s.ref_audio && s.tts_engine === "vieneu" ? " (đang dùng giọng mẫu)" : ""}
          <span className="voice-row">
            <select value={s.tts_voice} onChange={(e) => set({ tts_voice: e.target.value })}
              disabled={loadingVoices || (s.tts_engine === "vieneu" && !!s.ref_audio)}>
              <option value="">{loadingVoices ? "Đang tải danh sách giọng…" : `Mặc định${defaultVoice ? ` — ${defaultVoice.label}` : ""}`}</option>
              {groups.map(([g, list]) => (
                <optgroup key={g} label={GENDER[g] ?? "Khác"}>
                  {list.map((v) => <option key={v.id} value={v.id}>{v.featured ? "★ " : ""}{v.label}</option>)}
                </optgroup>
              ))}
            </select>
            <button type="button" className="ghost" title="Nghe thử giọng ở tốc độ đang chọn" aria-label="Nghe thử giọng"
              disabled={sampling || loadingVoices || (s.tts_engine === "vieneu" && !!s.ref_audio)} onClick={sample}>
              {sampling ? <span className="spin" aria-hidden /> : <Icon name="volume" size={16} />}
            </button>
          </span>
        </label>
        <audio ref={audio} hidden />
        {voiceErr && <p className="warn">{voiceErr}</p>}
        {s.tts_engine === "vieneu" && (
          <div className="row voice-manage">
            <button type="button" className="link" onClick={() => setCloneOpen(true)}>+ Tạo giọng nhân bản</button>
            {current?.custom && (
              <button type="button" className="link danger" onClick={async () => {
                const name = current.id.slice("custom:".length);
                if (!(await dialog.confirm({ title: `Xoá giọng "${name}"?`, message: "Các job đang dùng giọng này sẽ phải chọn giọng khác.",
                  confirmLabel: "Xoá", danger: true }))) return;
                await api.deleteVoice(name); reloadVoices("");
              }}>Xoá giọng này</button>
            )}
          </div>
        )}
        {s.tts_engine === "vieneu" && eng.tts.vieneu.ok && <VieneuDevice />}
        {cloneOpen && <CloneVoiceDialog onClose={() => setCloneOpen(false)}
          onCreated={(id) => { setCloneOpen(false); reloadVoices(id); }} />}
        <label>Tốc độ đọc <output>{s.tts_rate.toFixed(2)}×</output>
          <input type="range" min={0.8} max={1.3} step={0.05} value={s.tts_rate} onChange={(e) => set({ tts_rate: +e.target.value })} />
        </label>
        {!review && !voiceOnly && <label>{s.separate ? "Âm lượng nhạc nền" : "Âm lượng âm thanh gốc"} <output>{s.bg_volume_db > 0 ? "+" : ""}{s.bg_volume_db} dB</output>
          <input type="range" min={-20} max={6} step={1} value={s.bg_volume_db} onChange={(e) => set({ bg_volume_db: +e.target.value })} />
        </label>}
        {!review && !voiceOnly && !s.separate && (
          <label>Hạ âm thanh gốc khi có thuyết minh <output>{s.duck_db} dB</output>
            <input type="range" min={-30} max={-4} step={1} value={s.duck_db} onChange={(e) => set({ duck_db: +e.target.value })} />
          </label>
        )}
        {job && onRefUpload && s.tts_engine === "vieneu" && (
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

      {review && !voiceOnly && (
        <fieldset>
          <legend>Kiểu chữ phụ đề</legend>
          <CoverControls s={s} set={set} autoFont={null} fonts={options.fonts} textOnly />
        </fieldset>
      )}
    </div>
  );
}
