import type { ReactNode } from "react";
import { STATE_LABEL } from "../labels";
import type { JobState } from "../types";

/** When each job last changed state, from the live event stream (this tab only). */
const seen = new Map<string, { state: string; t: number }>();
export const noteState = (job: string, state: string, t: number) => { seen.set(job, { state, t }); };

const hhmm = (t: number) => {
  const d = new Date(t * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

/** A job / part / download state, drawn as a postmark. Shows the time it changed when this tab saw it happen. */
export default function Stamp({ state, label, job, title, className = "" }: {
  state: string; label?: ReactNode; job?: string; title?: string; className?: string;
}) {
  const s = job ? seen.get(job) : undefined;
  const at = s && s.state === state ? hhmm(s.t) : null;
  return (
    <span className={`stamp s-${state} ${className}`} title={title}>
      {label ?? STATE_LABEL[state as JobState] ?? state}
      {at && <span className="stamp-at"> · <time>{at}</time></span>}
    </span>
  );
}

/** "Số 0042": an item's number in its list. */
export const serialText = (n: number) => `Số ${String(n).padStart(4, "0")}`;
export function Serial({ n }: { n: number }) {
  return <span className="serial">{serialText(n)}</span>;
}
