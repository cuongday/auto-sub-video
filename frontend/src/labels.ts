import type { JobState } from "./types";

export const STEP_LABEL: Record<string, string> = {
  probe: "Đọc video", extract: "Tách âm thanh", separate: "Tách giọng / nhạc nền", asr: "Nhận dạng giọng nói",
  segment: "Cắt câu", translate: "Dịch (LLM)", tts: "Đọc thuyết minh", fit: "Khớp thời gian", mix: "Trộn âm thanh",
  render: "Ghép video", transcript: "Lấy lời thoại", characters: "Nhận diện nhân vật", summarize: "Tóm tắt phim",
  script: "Viết kịch bản", scenes: "Dò chuyển cảnh", assemble: "Ghép lời đọc và cảnh",
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
/** h:mm:ss, for points in a whole film. */
export const fmtClock = (t: number) => {
  const s = Math.round(t);
  return `${Math.floor(s / 3600)}:${String(Math.floor(s / 60) % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};
/** "h:mm:ss", "m:ss" or seconds -> seconds; null when malformed. */
export const parseClock = (v: string): number | null => {
  const parts = v.trim().split(":");
  if (parts.length > 3 || !parts.every((p) => /^\d+(\.\d+)?$/.test(p))) return null;
  return parts.reduce((acc, p) => acc * 60 + Number(p), 0);
};
export const fmtDur = (s: number) => s < 60 ? `${Math.round(s)} giây` : `${Math.floor(s / 60)} phút ${Math.round(s % 60)} giây`;
