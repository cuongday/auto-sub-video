import { useEffect, useRef } from "react";
import type { JobEvent } from "./types";

/** One shared SSE stream; handler sees every event. */
export function useEvents(handler: (e: JobEvent) => void) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    const es = new EventSource("/api/events");
    es.onmessage = (m) => { try { ref.current(JSON.parse(m.data)); } catch { /* ignore */ } };
    return () => es.close();
  }, []);
}
