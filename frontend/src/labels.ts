import type { JobState } from "./types";

export const STEP_LABEL: Record<string, string> = {
  probe: "Đọc video", extract: "Tách âm thanh", separate: "Tách giọng / nhạc nền", asr: "Nhận dạng giọng nói",
  segment: "Cắt câu", translate: "Dịch (LLM)", tts: "Đọc thuyết minh", fit: "Khớp thời gian", mix: "Trộn âm thanh",
  render: "Ghép video",
};
export const STATE_LABEL: Record<JobState, string> = {
  new: "Mới", queued: "Đang chờ", running: "Đang chạy", awaiting_review: "Chờ rà soát", done: "Xong", approved: "Đã duyệt",
  error: "Lỗi", interrupted: "Bị gián đoạn", cancelled: "Đã huỷ",
};
export const FLAG_LABEL: Record<string, string> = {
  translate_failed: "Dịch lỗi — đang giữ câu gốc", too_long: "Câu dài hơn thời lượng cho phép",
  tts_failed: "Đọc TTS lỗi", overflow: "Đọc không kịp dù đã tăng tốc ×1.35",
  lyrics: "Có thể là lời bài hát trong nhạc nền — xoá nếu không cần thuyết minh",
};
export const fmtTime = (t: number) => {
  const m = Math.floor(t / 60), s = t - m * 60;
  return `${m}:${s.toFixed(2).padStart(5, "0")}`;
};
export const parseTime = (v: string): number | null => {
  const m = v.trim().match(/^(?:(\d+):)?(\d+(?:\.\d+)?)$/);
  return m ? Number(m[1] ?? 0) * 60 + Number(m[2]) : null;
};
export const fmtDur = (s: number) => s < 60 ? `${Math.round(s)} giây` : `${Math.floor(s / 60)} phút ${Math.round(s % 60)} giây`;
