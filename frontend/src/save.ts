/** Save a server file where the user chooses.
 *  Chromium (Chrome/Edge/Opera): native "Save as" dialog via the File System Access API, streamed to disk
 *  so large videos are never held in memory; the browser reopens the last folder used ("id").
 *  Other browsers: a normal download (where it lands follows the browser's "ask where to save" setting). */

type Picker = (opts: {
  suggestedName: string; id?: string; startIn?: string;
  types?: { description: string; accept: Record<string, string[]> }[];
}) => Promise<FileSystemFileHandle>;

export const canPickLocation = (): boolean => typeof (window as unknown as { showSaveFilePicker?: Picker }).showSaveFilePicker === "function";

const TYPES: Record<string, { description: string; mime: string }> = {
  ".mp4": { description: "Video MP4", mime: "video/mp4" },
  ".srt": { description: "Phụ đề SRT", mime: "application/x-subrip" },
  ".ass": { description: "Phụ đề ASS", mime: "text/plain" },
  ".wav": { description: "Âm thanh WAV", mime: "audio/wav" },
};

export type SaveResult = "saved" | "cancelled" | "downloaded";

export async function saveFile(url: string, suggestedName: string, onProgress?: (p: number) => void): Promise<SaveResult> {
  const picker = (window as unknown as { showSaveFilePicker?: Picker }).showSaveFilePicker;
  if (!picker) {
    const a = document.createElement("a");
    a.href = url; a.download = suggestedName;
    document.body.appendChild(a); a.click(); a.remove();
    return "downloaded";
  }
  const ext = suggestedName.slice(suggestedName.lastIndexOf(".")).toLowerCase();
  const t = TYPES[ext];
  let handle: FileSystemFileHandle;
  try {
    handle = await picker({
      suggestedName, id: "autosub-export", startIn: "downloads",
      types: t ? [{ description: t.description, accept: { [t.mime]: [ext] } }] : undefined,
    });
  } catch (e) {
    if ((e as DOMException).name === "AbortError") return "cancelled";
    throw e;
  }
  const res = await fetch(url);
  if (!res.ok || !res.body) throw new Error(`Không tải được file (${res.status})`);
  const total = Number(res.headers.get("Content-Length") || 0);
  const writable = await handle.createWritable();
  const reader = res.body.getReader();
  let done = 0;
  try {
    for (;;) {
      const { value, done: end } = await reader.read();
      if (end) break;
      await writable.write(value);
      done += value.byteLength;
      if (total && onProgress) onProgress(done / total);
    }
    await writable.close();
  } catch (e) {
    await writable.abort().catch(() => {});
    throw e;
  }
  return "saved";
}

/* ---------- saving several files into one folder the user picks (Douyin downloads) ---------- */

type DirPicker = (opts: { id?: string; mode?: "readwrite"; startIn?: string }) => Promise<FileSystemDirectoryHandle>;

export const canPickFolder = (): boolean => typeof (window as unknown as { showDirectoryPicker?: DirPicker }).showDirectoryPicker === "function";

/** Ask for a folder; null when the user closes the dialog. */
export async function pickFolder(): Promise<FileSystemDirectoryHandle | null> {
  const picker = (window as unknown as { showDirectoryPicker: DirPicker }).showDirectoryPicker;
  try {
    return await picker({ id: "autosub-douyin", mode: "readwrite", startIn: "downloads" });
  } catch (e) {
    if ((e as DOMException).name === "AbortError") return null;
    throw e;
  }
}

/** Stream `url` into `dir`; the file name comes from the server's X-Filename header (or `fallback`). */
export async function saveIntoFolder(dir: FileSystemDirectoryHandle, url: string, fallback: string,
  onProgress?: (p: number) => void, signal?: AbortSignal): Promise<string> {
  const res = await fetch(url, { signal });
  if (!res.ok || !res.body) {
    const d = (await res.json().catch(() => ({}))).detail;
    throw new Error(d || `Không tải được file (${res.status})`);
  }
  const name = decodeURIComponent(res.headers.get("X-Filename") || "") || fallback;
  const total = Number(res.headers.get("Content-Length") || 0);
  const handle = await dir.getFileHandle(name, { create: true });
  const writable = await handle.createWritable();
  const reader = res.body.getReader();
  let done = 0;
  try {
    for (;;) {
      const { value, done: end } = await reader.read();
      if (end) break;
      await writable.write(value);
      done += value.byteLength;
      if (total && onProgress) onProgress(done / total);
    }
    await writable.close();
  } catch (e) {
    await writable.abort().catch(() => {});
    await dir.removeEntry(name).catch(() => {});
    throw e;
  }
  return name;
}

/** Run `fn` over `items` with at most `limit` running at once. */
export async function pool<T>(items: T[], limit: number, fn: (x: T) => Promise<void>): Promise<void> {
  const queue = [...items];
  await Promise.all(Array.from({ length: Math.min(limit, queue.length) }, async () => {
    for (let x = queue.shift(); x !== undefined; x = queue.shift()) await fn(x);
  }));
}
