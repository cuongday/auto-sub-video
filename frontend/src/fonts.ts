import type { FontOption } from "./types";

/** Register the bundled subtitle fonts with the browser (same .ttf files libass renders with),
 *  under a private family name so the preview matches the final video exactly. */
const loaded = new Set<string>();

export const previewFamily = (f: FontOption) => `autosub-${f.id}`;

export function loadFont(f: FontOption): void {
  if (loaded.has(f.id)) return;
  loaded.add(f.id);
  const face = new FontFace(previewFamily(f), `url(/api/fonts/${encodeURIComponent(f.file)})`, { weight: "100 900" });
  face.load().then((ff) => document.fonts.add(ff)).catch(() => loaded.delete(f.id));
}

export function loadAll(fonts: FontOption[]): void {
  fonts.forEach(loadFont);
}

export const fontCss = (f: FontOption | undefined): string =>
  f ? `"${previewFamily(f)}", "Be Vietnam Pro", sans-serif` : `"Be Vietnam Pro", sans-serif`;
