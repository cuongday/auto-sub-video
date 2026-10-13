import type { CSSProperties } from "react";
import type { Cover, Region, SubStyle } from "../types";

/** CSS approximation of the final render: covered region + subtitle text centered inside it.
 *  `frameH` is the rendered height in CSS px of a frame whose real height is `videoH`. */
export default function SubOverlay({ region, cover, coverColor, style, text, frameH, videoH }: {
  region: Region; cover: Cover; coverColor: string; style: SubStyle; text: string; frameH: number; videoH: number;
}) {
  const scale = videoH ? frameH / videoH : 1;
  const hPx = region.h * videoH;
  const fs = (style.font_size ?? Math.max(14, Math.round(hPx / 2.6))) * scale;
  const outline = (style.outline ?? Math.max(1.5, fs / scale / 18)) * scale;
  const box: CSSProperties = {
    left: `${region.x * 100}%`, top: `${region.y * 100}%`, width: `${region.w * 100}%`, height: `${region.h * 100}%`,
  };
  if (cover === "solid") box.background = coverColor;
  else {
    box.backdropFilter = "blur(10px)";
    (box as Record<string, string>).WebkitBackdropFilter = "blur(10px)";
    if (cover === "blur_dim") box.background = "rgba(0,0,0,.45)";
  }
  const shadow = [`${outline}px`, `-${outline}px`].flatMap((x) => [`${outline}px`, `-${outline}px`].map((y) => `${x} ${y} 0 ${style.outline_color}`));
  return (
    <div className="sub-overlay" style={box}>
      {text && <span style={{ fontSize: fs, color: style.color, textShadow: [...shadow, `0 0 ${outline}px ${style.outline_color}`].join(",") }}>{text}</span>}
    </div>
  );
}
