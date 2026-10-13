import { api } from "../api";
import type { Job } from "../types";

export default function Result({ job, onEdit, onSetup }: { job: Job; onEdit: () => void; onSetup: () => void }) {
  const bust = job.steps.render.hash ?? "";
  return (
    <section className="card">
      <header className="card-head">
        <h2>Thành phẩm</h2>
        <div className="row">
          <button className="ghost" onClick={onEdit}>Quay lại sửa phụ đề</button>
          <button className="ghost" onClick={onSetup}>Đổi vùng che / tuỳ chọn</button>
        </div>
      </header>
      {job.warnings.map((w) => <p key={w} className="warn">{w}</p>)}
      <video className="result" src={api.file(job.id, "output.mp4", bust)} controls />
      <div className="downloads">
        <a className="primary btn" href={api.download(job.id, "output.mp4")}>Tải video (.mp4)</a>
        <a className="ghost btn" href={api.download(job.id, "subs.srt")}>Phụ đề .srt</a>
        <a className="ghost btn" href={api.download(job.id, "subs.ass")}>Phụ đề .ass</a>
        <a className="ghost btn" href={api.download(job.id, "voice.wav")}>Giọng thuyết minh .wav</a>
      </div>
    </section>
  );
}
