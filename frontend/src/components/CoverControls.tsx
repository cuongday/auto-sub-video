import type { Settings } from "../types";

export default function CoverControls({ s, set, autoFont }: { s: Settings; set: (p: Partial<Settings>) => void; autoFont: number }) {
  const st = s.style;
  return (
    <div className="cover-controls">
      <div className="seg" role="radiogroup" aria-label="Kiểu che">
        {([["blur", "Làm mờ"], ["blur_dim", "Mờ + nền tối"], ["solid", "Dải màu"]] as const).map(([v, label]) => (
          <button key={v} role="radio" aria-checked={s.cover === v} className={s.cover === v ? "on" : ""} onClick={() => set({ cover: v })}>{label}</button>
        ))}
      </div>
      {s.cover === "solid" && <label className="inline">Màu dải <input type="color" value={s.cover_color} onChange={(e) => set({ cover_color: e.target.value })} /></label>}
      <label className="inline">Cỡ chữ
        <input type="number" min={10} max={200} value={st.font_size ?? ""} placeholder={`tự động (${autoFont})`}
          onChange={(e) => set({ style: { ...st, font_size: e.target.value ? +e.target.value : null } })} />
      </label>
      <label className="inline">Chữ <input type="color" value={st.color} onChange={(e) => set({ style: { ...st, color: e.target.value } })} /></label>
      <label className="inline">Viền <input type="color" value={st.outline_color} onChange={(e) => set({ style: { ...st, outline_color: e.target.value } })} /></label>
    </div>
  );
}
