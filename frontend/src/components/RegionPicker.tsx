import { useRef, type PointerEvent as RPE, type ReactNode } from "react";
import type { Region } from "../types";

type Drag = { mode: "new" | "move" | "nw" | "ne" | "sw" | "se"; x0: number; y0: number; start: Region };
const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v));
const MIN = 0.02;

/** Drag on the image to draw the region; drag inside to move; drag a corner to resize. */
export default function RegionPicker({ src, region, onChange, children }: {
  src: string; region: Region; onChange: (r: Region) => void; children?: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const pos = (e: RPE) => {
    const r = box.current!.getBoundingClientRect();
    return { x: clamp((e.clientX - r.left) / r.width, 0, 1), y: clamp((e.clientY - r.top) / r.height, 0, 1) };
  };
  const down = (mode: Drag["mode"]) => (e: RPE) => {
    e.stopPropagation(); e.preventDefault();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    const p = pos(e);
    drag.current = { mode, x0: p.x, y0: p.y, start: region };
    if (mode === "new") onChange({ x: p.x, y: p.y, w: MIN, h: MIN });
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
    onChange(round(r));
  };
  const up = () => { drag.current = null; };
  return (
    <div className="picker" ref={box} onPointerDown={down("new")} onPointerMove={move} onPointerUp={up}>
      <img src={src} alt="Khung hình video" draggable={false} />
      {children}
      <div className="picker-box" onPointerDown={down("move")}
        style={{ left: `${region.x * 100}%`, top: `${region.y * 100}%`, width: `${region.w * 100}%`, height: `${region.h * 100}%` }}>
        {(["nw", "ne", "sw", "se"] as const).map((c) => <span key={c} className={`handle ${c}`} onPointerDown={down(c)} />)}
      </div>
    </div>
  );
}
const round = (r: Region): Region => ({ x: +r.x.toFixed(4), y: +r.y.toFixed(4), w: +r.w.toFixed(4), h: +r.h.toFixed(4) });
