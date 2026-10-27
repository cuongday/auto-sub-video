import { useEffect, useRef } from "react";
import type { JobEvent } from "./types";

/** One EventSource for the whole page, shared by every useEvents caller: browsers allow only 6 connections per
 *  origin over HTTP/1.1, so a stream per component would starve uploads and video previews. Opened with the first
 *  handler, closed with the last. */
const handlers = new Set<(e: JobEvent) => void>();
let es: EventSource | null = null;

function subscribe(h: (e: JobEvent) => void) {
  handlers.add(h);
  if (!es) {
    es = new EventSource("/api/events");
    es.onmessage = (m) => {
      let e: JobEvent;
      try { e = JSON.parse(m.data); } catch { return; }
      handlers.forEach((f) => { try { f(e); } catch (err) { console.error(err); } });
    };
  }
  return () => {
    handlers.delete(h);
    if (!handlers.size && es) { es.close(); es = null; }
  };
}

/** Every server event goes to `handler` (the latest one passed, so it may close over fresh state). */
export function useEvents(handler: (e: JobEvent) => void) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => subscribe((e) => ref.current(e)), []);
}
