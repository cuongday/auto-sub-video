import type { Region, VideoInfo } from "./types";

export const isPortrait = (info: VideoInfo) => info.height > info.width;

/** Same rule as autosub/subtitles.py auto_font_size: two lines fit the height, ~24 chars fit the width. */
export function autoFontSize(region: Region, info: VideoInfo): number {
  const h = region.h * info.height, w = region.w * info.width;
  return Math.max(14, Math.round(Math.min(h / 2.6, w / (24 * 0.55))));
}

/** libass sizes text by ascent+descent; for Be Vietnam Pro that is 1.265 em, so an ASS font size
 *  of N renders like a CSS font-size of N / 1.265. */
export const ASS_TO_CSS = 1 / 1.265;
