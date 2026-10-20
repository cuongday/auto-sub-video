import { useEffect } from "react";
import { fontCss, loadAll } from "../fonts";
import type { FontOption, Settings } from "../types";

// common subtitle colors: white/yellow read best on video; the rest for styled channels
const TEXT_COLORS = [
  ["#FFFFFF", "Trắng"], ["#FFE14D", "Vàng"], ["#FFC400", "Vàng đậm"], ["#7CF2FF", "Xanh nhạt"],
  ["#9BFF8A", "Xanh lá"], ["#FF9EC4", "Hồng"], ["#FF5A5A", "Đỏ"], ["#111111", "Đen"],
] as const;
const OUTLINE_COLORS = [
  ["#000000", "Đen"], ["#1A1A2E", "Xanh đen"], ["#5A0000", "Đỏ sẫm"], ["#FFFFFF", "Trắng"],
] as const;

function Swatches({ label, value, colors, onChange }: {
  label: string; value: string; colors: readonly (readonly [string, string])[]; onChange: (c: string) => void;
}) {
  const v = value.toUpperCase();
  return (
    <div className="swatch-row" role="radiogroup" aria-label={label}>
      <span className="swatch-label">{label}</span>
      {colors.map(([c, name]) => (
        <button key={c} type="button" role="radio" aria-checked={v === c} aria-label={name} title={name}
          className={`swatch ${v === c ? "on" : ""}`} style={{ background: c }} onClick={() => onChange(c)} />
      ))}
      <label className="swatch custom" title="Màu khác">
        <input type="color" value={value} onChange={(e) => onChange(e.target.value.toUpperCase())} aria-label={`${label} — màu khác`} />
        <span aria-hidden>+</span>
      </label>
      <code className="hex">{v}</code>
    </div>
  );
}

export default function CoverControls({ s, set, autoFont, fonts, textOnly = false }: {
  s: Settings; set: (p: Partial<Settings>) => void; autoFont: number | null; fonts: FontOption[]; textOnly?: boolean;
}) {
  const st = s.style;
  const style = (p: Partial<Settings["style"]>) => set({ style: { ...st, ...p } });
  useEffect(() => { loadAll(fonts); }, [fonts]);
  const current = fonts.find((f) => f.id === st.font) ?? fonts[0];
  return (
    <div className="cover-controls">
      {!textOnly && <div className="row">
        <div className="seg" role="radiogroup" aria-label="Kiểu che">
          {([["blur", "Làm mờ"], ["blur_dim", "Mờ + nền tối"], ["solid", "Dải màu"]] as const).map(([v, label]) => (
            <button key={v} role="radio" aria-checked={s.cover === v} className={s.cover === v ? "on" : ""} onClick={() => set({ cover: v })}>{label}</button>
          ))}
        </div>
        {s.cover === "solid" && <label className="inline">Màu dải <input type="color" value={s.cover_color} onChange={(e) => set({ cover_color: e.target.value })} /></label>}
      </div>}
      <div className="text-style">
        <label className="font-pick">Font chữ
          <select value={current?.id} onChange={(e) => style({ font: e.target.value })}
            style={{ fontFamily: fontCss(current), fontWeight: current?.weight }}>
            {fonts.map((f) => (
              <option key={f.id} value={f.id} style={{ fontFamily: fontCss(f), fontWeight: f.weight }}>{f.label}</option>
            ))}
          </select>
        </label>
        <label className="inline">Cỡ chữ
          <input type="number" min={10} max={200} value={st.font_size ?? ""} placeholder={autoFont ? `tự động (${autoFont})` : "tự động"}
            onChange={(e) => style({ font_size: e.target.value ? +e.target.value : null })} />
        </label>
      </div>
      <Swatches label="Màu chữ" value={st.color} colors={TEXT_COLORS} onChange={(c) => style({ color: c })} />
      <Swatches label="Màu viền" value={st.outline_color} colors={OUTLINE_COLORS} onChange={(c) => style({ outline_color: c })} />
    </div>
  );
}
