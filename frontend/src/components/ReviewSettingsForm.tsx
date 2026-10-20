import type { ReviewSettings, Template, Templates } from "../types";

function Chips({ label, items, value, onPick }: { label: string; items: Template[]; value: string; onPick: (id: string) => void }) {
  return (
    <div className="chip-field">
      <span className="chip-label" id={`chips-${label}`}>{label}</span>
      <div className="chips" role="radiogroup" aria-labelledby={`chips-${label}`}>
        {items.map((t) => (
          <button key={t.id} type="button" role="radio" aria-checked={value === t.id} className={`chip ${value === t.id ? "on" : ""}`}
            title={t.prompt} onClick={() => onPick(t.id)}>{t.label}</button>
        ))}
      </div>
    </div>
  );
}

const AUTO_OPENING: Template = { id: "", label: "Tự động", prompt: "Phần 1 giới thiệu phim, các phần sau tóm tắt phần trước." };

/** The review options of a project (shared by its parts) or of one part: templates, length, frame, subtitles, music. */
export default function ReviewSettingsForm({ value, templates, onChange }: {
  value: ReviewSettings; templates: Templates | null; onChange: (patch: Partial<ReviewSettings>) => void;
}) {
  const v = value;
  return (
    <div className="rv-form">
      {templates ? <>
        <Chips label="Phong cách" items={templates.styles} value={v.style} onPick={(style) => onChange({ style })} />
        <Chips label="Hook" items={templates.hooks} value={v.hook} onPick={(hook) => onChange({ hook })} />
        <Chips label="Mở đầu" items={[AUTO_OPENING, ...templates.openings]} value={v.opening} onPick={(opening) => onChange({ opening })} />
      </> : <p className="muted small">Đang tải mẫu kịch bản…</p>}
      <label>Yêu cầu thêm
        <textarea rows={2} value={v.notes} placeholder="Ví dụ: gọi nam chính là “anh Tư”, nhấn vào tình cảm hai mẹ con…"
          onChange={(e) => onChange({ notes: e.target.value })} />
      </label>
      <div className="rv-row">
        <label className="inline">Mỗi video dài
          <input type="number" min={1} max={30} step={1} value={v.minutes} className="rv-minutes"
            onChange={(e) => { const m = +e.target.value; if (m >= 1 && m <= 30) onChange({ minutes: m }); }} />
          <span className="muted">phút</span>
        </label>
        <div className="seg" role="radiogroup" aria-label="Khung hình">
          {(["9:16", "16:9"] as const).map((a) => (
            <button key={a} type="button" role="radio" aria-checked={v.aspect === a} className={v.aspect === a ? "on" : ""}
              onClick={() => onChange({ aspect: a })}>{a === "9:16" ? "9:16 dọc" : "16:9 ngang"}</button>
          ))}
        </div>
      </div>
      <div className="rv-row">
        <label className="inline check"><input type="checkbox" checked={v.spoil_ending} onChange={(e) => onChange({ spoil_ending: e.target.checked })} />
          Kể cả cái kết</label>
        <label className="inline check"><input type="checkbox" checked={v.subtitles} onChange={(e) => onChange({ subtitles: e.target.checked })} />
          Phụ đề lời đọc</label>
      </div>
      <div className="rv-row">
        <label className="rv-db">Nhạc nền so với giọng <output>{v.music_db} dB</output>
          <input type="range" min={-40} max={0} step={1} value={v.music_db} onChange={(e) => onChange({ music_db: +e.target.value })} />
        </label>
        <label className="inline check"><input type="checkbox" checked={v.music_duck} onChange={(e) => onChange({ music_duck: e.target.checked })} />
          Tự nhỏ khi có giọng đọc</label>
      </div>
    </div>
  );
}
