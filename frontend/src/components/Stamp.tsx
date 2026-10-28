import type { ReactNode } from "react";
import { STATE_LABEL } from "../labels";
import type { JobState } from "../types";

/** When each job last changed state, from the live event stream (this tab only). */
const seen = new Map<string, { state: string; t: number }>();
export const noteState = (job: string, state: string, t: number) => { seen.set(job, { state, t }); };

const p2 = (n: number) => String(n).padStart(2, "0");
/** "14:02" today, "27/10 14:02" on another day (local time, 24h). */
export const stampTime = (t: number) => {
  const d = new Date(t * 1000), now = new Date();
  const hm = `${p2(d.getHours())}:${p2(d.getMinutes())}`;
  return d.toDateString() === now.toDateString() ? hm : `${p2(d.getDate())}/${p2(d.getMonth() + 1)} ${hm}`;
};

/** A job / part / download state, drawn as a postmark, with the time it changed (`at`, else when this tab saw it). */
export default function Stamp({ state, label, job, at, title, className = "" }: {
  state: string; label?: ReactNode; job?: string; at?: number | null; title?: string; className?: string;
}) {
  const s = job ? seen.get(job) : undefined;
  const t = at ?? (s && s.state === state ? s.t : null);
  const when = t ? stampTime(t) : null;
  return (
    <span className={`stamp s-${state} ${className}`} title={title}>
      {label ?? STATE_LABEL[state as JobState] ?? state}
      {when && <span className="stamp-at"> · <time dateTime={new Date(t! * 1000).toISOString()}>{when}</time></span>}
    </span>
  );
}

/** "Số 0042": an item's number in its list. */
export const serialText = (n: number) => `Số ${String(n).padStart(4, "0")}`;
export function Serial({ n }: { n: number }) {
  return <span className="serial">{serialText(n)}</span>;
}
