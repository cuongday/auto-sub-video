import { useState } from "react";

const MIN = 200, MAX = 480, DEF = 280, STEP = 16;

/** Drag handle on the sidebar's right edge; also a keyboard-operable separator. */
export default function SideResizer({ width, onWidth }: { width: number; onWidth: (w: number) => void }) {
  const [drag, setDrag] = useState(false);
  return (
    <div className={`side-resizer ${drag ? "drag" : ""}`} role="separator" aria-orientation="vertical" aria-label="Đổi độ rộng thanh bên"
      aria-valuenow={width} aria-valuemin={MIN} aria-valuemax={MAX} tabIndex={0}
      onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); setDrag(true); }}
      onPointerMove={(e) => { if (drag) onWidth(e.clientX); }}
      onPointerUp={() => setDrag(false)} onPointerCancel={() => setDrag(false)}
      onDoubleClick={() => onWidth(DEF)}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") { e.preventDefault(); onWidth(width - STEP); }
        else if (e.key === "ArrowRight") { e.preventDefault(); onWidth(width + STEP); }
      }} />
  );
}
