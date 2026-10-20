import { useRef, type PointerEvent as RPE, type ReactNode } from "react";
import type { Region } from "../types";

type Mode = "new" | "move" | "nw" | "ne" | "sw" | "se";
type Drag = { mode: Mode; idx: number; x0: number; y0: number; start: Region };
const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v));
const MIN = 0.02;

/** Regions on the frame: index 0 is the subtitle region (amber), the rest are extra covered regions
 *  (with coverOnly every region is a covered one; with `tags` every region is a fixed, named box that can't be
 *  removed). Drag on empty image to redraw the active region
 *  (with no region yet it draws region 0); drag a region to move it; drag a corner to resize. */
export default function RegionPicker({ src, aspect, regions, active, onActive, onChange, onRemove, children, coverOnly = false, tags }: {
  src: string; aspect: number; regions: Region[]; active: number;
  onActive: (i: number) => void; onChange: (i: number, r: Region) => void; onRemove: (i: number) => void;
  children?: ReactNode; coverOnly?: boolean; tags?: string[];
}) {
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const pos = (e: RPE) => {
    const r = box.current!.getBoundingClientRect();
    return { x: clamp((e.clientX - r.left) / r.width, 0, 1), y: clamp((e.clientY - r.top) / r.height, 0, 1) };
  };
  const down = (mode: Mode, idx: number) => (e: RPE) => {
    e.stopPropagation(); e.preventDefault();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    const p = pos(e);
    onActive(idx);
    drag.current = { mode, idx, x0: p.x, y0: p.y, start: regions[idx] };
    if (mode === "new") onChange(idx, { x: p.x, y: p.y, w: MIN, h: MIN });
  };
  const move = (e: RPE) => {
    const d = drag.current; if (!d) return;
    const p = pos(e); const s = d.start;
    const dx = p.x - d.x0, dy = p.y - d.y0;
    let r: Region;
    if (d.mode === "new") {
      r = { x: Math.min(d.x0, p.x), y: Math.min(d.y0, p.y), w: Math.max(MIN, Math.abs(dx)), h: Math.max(MIN, Math.abs(dy)) };
    } else if (d.mode === "move") {
      r = { ...s, x: clamp(s.x + dx, 0, 1 - s.w), y: clamp(s.y + dy, 0, 1 - s.h) };
    } else {
      let x1 = s.x, y1 = s.y, x2 = s.x + s.w, y2 = s.y + s.h;
      if (d.mode.includes("w")) x1 = clamp(s.x + dx, 0, x2 - MIN); else x2 = clamp(x2 + dx, x1 + MIN, 1);
      if (d.mode.includes("n")) y1 = clamp(s.y + dy, 0, y2 - MIN); else y2 = clamp(y2 + dy, y1 + MIN, 1);
      r = { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
    }
    r.w = Math.min(r.w, 1 - r.x); r.h = Math.min(r.h, 1 - r.y);
    onChange(d.idx, round(r));
  };
  const up = () => { drag.current = null; };
  return (
    <div className="picker" ref={box} style={{ aspectRatio: String(aspect) }}
      onPointerDown={down("new", active)} onPointerMove={move} onPointerUp={up}>
      <img src={src} alt="Khung hình video" draggable={false} />
      {children}
      {regions.map((rg, i) => {
        const sub = i === 0 && !coverOnly, n = coverOnly ? i + 1 : i;
        return (
        <div key={i} className={`picker-box ${sub ? "sub-box" : "extra"} ${i === active ? "active" : ""}`}
          onPointerDown={down("move", i)} title={tags?.[i] ?? (sub ? "Vùng phụ đề (che + chèn sub mới)" : `Vùng che ${n}`)}
          style={{ left: `${rg.x * 100}%`, top: `${rg.y * 100}%`, width: `${rg.w * 100}%`, height: `${rg.h * 100}%` }}>
          <span className="tag">{tags?.[i] ?? (sub ? "Phụ đề" : `Che ${n}`)}</span>
          {!sub && !tags && (
            <button type="button" className="remove" aria-label={`Xoá vùng che ${n}`}
              onPointerDown={(e) => e.stopPropagation()} onClick={(e) => { e.stopPropagation(); onRemove(i); }}>×</button>
          )}
          {i === active && (["nw", "ne", "sw", "se"] as const).map((c) => <span key={c} className={`handle ${c}`} onPointerDown={down(c, i)} />)}
        </div>
        );
      })}
    </div>
  );
}
const round = (r: Region): Region => ({ x: +r.x.toFixed(4), y: +r.y.toFixed(4), w: +r.w.toFixed(4), h: +r.h.toFixed(4) });
