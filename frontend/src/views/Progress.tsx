import { useEffect, useState } from "react";
import { api } from "../api";
import { STEP_LABEL, fmtDur } from "../labels";
import type { Job } from "../types";

export default function Progress({ job, pct, logs, onCancel, onRetry }: {
  job: Job; pct: Record<string, number>; logs: string[];
  onCancel: () => void; onRetry: (step: string) => void;
}) {
  const active = job.state === "running" || job.state === "queued";
  const { steps, review_stop: stop } = job.flow;
  const shown = job.mode === "review" && stop && job.steps[stop]?.status !== "done" ? steps.slice(0, steps.indexOf(stop) + 1) : steps;
  const failed = steps.find((s) => job.steps[s].status === "error");
  const [eta, setEta] = useState<{ steps: Record<string, number>; total: number; calibrated: boolean } | null>(null);
  const curPct = job.current_step ? pct[job.current_step] ?? 0 : 0;
  useEffect(() => {
    if (!active) { setEta(null); return; }
    api.eta(job.id, job.current_step, curPct).then(setEta).catch(() => {});
  }, [job.id, job.current_step, active, Math.round(curPct * 20)]);
  return (
    <section className="card">
      <header className="card-head">
        <h2>{job.state === "queued" ? "Đang chờ trong hàng đợi" : active ? "Đang xử lý" : job.state === "error" ? "Gặp lỗi" : "Đã dừng"}</h2>
        <span className="grow" />
        {eta && eta.total > 0 && (
          <span className="muted small" title={eta.calibrated ? "Ước tính theo tốc độ các job trước trên máy này" : "Ước tính sơ bộ (chưa có job nào xong để đo)"}>
            Còn khoảng {fmtDur(eta.total)}{eta.calibrated ? "" : " (ước tính sơ bộ)"}
          </span>
        )}
        {active && <button className="ghost danger" onClick={onCancel}>Huỷ</button>}
      </header>
      <ol className="steps">
        {shown.map((s) => {
          const st = job.steps[s];
          const running = job.current_step === s;
          const p = st.status === "done" ? 1 : running ? pct[s] ?? 0 : 0;
          return (
            <li key={s} className={`step ${running ? "running" : st.status}`}>
              <span className="dot" aria-hidden />
              <span className="name">{STEP_LABEL[s]}</span>
              <span className="bar"><i style={{ width: `${Math.round(p * 100)}%` }} /></span>
              <span className="time">{st.status === "done" && st.seconds != null ? `${st.seconds}s`
                : running ? `${Math.round(p * 100)}%` : eta?.steps[s] ? `~${fmtDur(eta.steps[s])}` : ""}</span>
            </li>
          );
        })}
      </ol>
      {job.state === "error" && (
        <div className="error-box" role="alert">
          <pre>{job.error}</pre>
          {failed && <button className="primary" onClick={() => onRetry(failed)}>Chạy lại từ bước “{STEP_LABEL[failed]}”</button>}
        </div>
      )}
      {(job.state === "cancelled" || job.state === "interrupted") && (
        <div className="row">
          <button className="primary" onClick={() => onRetry("")}>Chạy tiếp</button>
          <span className="muted small">Các bước đã xong được giữ lại, không phải chạy lại.</span>
        </div>
      )}
      {logs.length > 0 && <pre className="log" aria-label="Nhật ký">{logs.slice(-200).join("\n")}</pre>}
    </section>
  );
}
