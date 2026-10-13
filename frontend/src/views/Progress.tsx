import { STEP_LABEL } from "../labels";
import type { Job } from "../types";

export default function Progress({ job, steps, pct, logs, onCancel, onRetry }: {
  job: Job; steps: string[]; pct: Record<string, number>; logs: string[];
  onCancel: () => void; onRetry: (step: string) => void;
}) {
  const active = job.state === "running" || job.state === "queued";
  const lastStep = job.mode === "review" && job.steps.translate.status !== "done" ? "translate" : "render";
  const shown = steps.slice(0, steps.indexOf(lastStep) + 1);
  const failed = steps.find((s) => job.steps[s].status === "error");
  return (
    <section className="card">
      <header className="card-head">
        <h2>{job.state === "queued" ? "Đang chờ trong hàng đợi" : active ? "Đang xử lý" : job.state === "error" ? "Gặp lỗi" : "Đã dừng"}</h2>
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
              <span className="time">{st.status === "done" && st.seconds != null ? `${st.seconds}s` : running ? `${Math.round(p * 100)}%` : ""}</span>
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
