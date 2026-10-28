import { useState } from "react";

export const SIDE_MIN = 200, SIDE_MAX = 480, SIDE_DEF = 280;
const STEP = 16;

/** Drag handle on the sidebar's right edge; also a keyboard-operable separator. */
export default function SideResizer({ width, onWidth }: { width: number; onWidth: (w: number, save?: boolean) => void }) {
  const [drag, setDrag] = useState(false);
  return (
    <div className={`side-resizer ${drag ? "drag" : ""}`} role="separator" aria-orientation="vertical" aria-label="Đổi độ rộng thanh bên"
      aria-valuenow={width} aria-valuemin={SIDE_MIN} aria-valuemax={SIDE_MAX} tabIndex={0}
      onPointerDown={(e) => { if (e.button !== 0) return; e.currentTarget.setPointerCapture(e.pointerId); setDrag(true); }}
      onPointerMove={(e) => { if (drag) onWidth(e.clientX, false); }}
      onPointerUp={() => { if (drag) onWidth(width); setDrag(false); }} onPointerCancel={() => setDrag(false)}
      onDoubleClick={() => onWidth(SIDE_DEF)}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") { e.preventDefault(); onWidth(width - STEP); }
        else if (e.key === "ArrowRight") { e.preventDefault(); onWidth(width + STEP); }
      }} />
  );
}
