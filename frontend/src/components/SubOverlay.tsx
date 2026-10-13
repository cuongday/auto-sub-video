import type { CSSProperties } from "react";
import { ASS_TO_CSS, autoFontSize } from "../geometry";
import type { Cover, Region, SubStyle, VideoInfo } from "../types";

/** CSS approximation of the final render: covered region + subtitle text centered inside it.
 *  `frameH` is the rendered height in CSS px of the video frame. */
export default function SubOverlay({ region, cover, coverColor, style, text, frameH, info }: {
  region: Region; cover: Cover; coverColor: string; style: SubStyle; text: string; frameH: number; info: VideoInfo;
}) {
  const scale = info.height ? frameH / info.height : 1;
  const assSize = style.font_size ?? autoFontSize(region, info);
  const fs = assSize * scale * ASS_TO_CSS;
  const outline = (style.outline ?? Math.max(1.5, assSize / 18)) * scale;
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
