# Auto-Sub

Ứng dụng web chạy cục bộ: nhận video tiếng Trung hoặc tiếng Anh, làm mờ phụ đề cũ ở vùng bạn chọn, chèn phụ đề tiếng Việt và thuyết minh tiếng Việt thay giọng gốc (giữ nhạc nền, tiếng động).

Pipeline: `ffmpeg` tách âm thanh → **Demucs** tách giọng / nhạc nền → **ASR** (FunASR Paraformer cho tiếng Trung, faster-whisper cho tiếng Anh) → cắt câu → **LLM** (Gemini qua Vertex AI hoặc OpenAI) phân tích bối cảnh rồi dịch theo lô, giới hạn độ dài theo thời lượng → *rà soát* → **TTS** (edge-tts hoặc VieNeu-TTS) → khớp thời gian (tăng tốc tối đa ×1.35) → trộn với nhạc nền → render (che vùng + phụ đề ASS).

Mọi model chạy trên CPU.

## Yêu cầu

- Python ≥ 3.10, Node ≥ 18
- ffmpeg có `ffprobe`, filter `ass` (libass)
- gcloud CLI (nếu dùng Gemini)

## Cài đặt

```bash
make setup-full   # .venv + torch CPU + demucs, funasr, faster-whisper, vieneu + npm
cp .env.example .env   # rồi sửa giá trị
make run          # build giao diện + chạy server -> http://localhost:8020
```

`make setup` chỉ cài phần lõi (edge-tts, Gemini/OpenAI); các engine chưa cài sẽ bị làm mờ trong giao diện.
Model tự tải ở lần dùng đầu: Demucs và faster-whisper từ Hugging Face, FunASR từ ModelScope, VieNeu khoảng vài trăm MB.

### Cấu hình `.env`

| Biến | Mặc định | Ghi chú |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | — | bắt buộc khi dùng Gemini |
| `GOOGLE_LOCATION` | `global` | vùng gọi Vertex AI |
| `ADC_HOST_PATH` | — | file ADC, gán vào `GOOGLE_APPLICATION_CREDENTIALS` |
| `GEMINI_TEXT_MODEL` | `gemini-2.5-flash` | |
| `OPENAI_API_KEY` | — | bắt buộc khi dùng OpenAI |
| `OPENAI_MODEL` | `gpt-4.1-mini` | |
| `VIENEU_MODE` | `v3turbo` | |
| `AUTOSUB_VOICE_WORKERS` | `4` | số bản VieNeu đọc song song (~1,5 GB RAM mỗi bản) |
| `AUTOSUB_FFMPEG_PRESET` | `veryfast` | preset x264 |
| `AUTOSUB_FFMPEG_CRF` | `20` | nhỏ hơn = nét hơn |
| `AUTOSUB_PROJECTS_DIR` | `projects/` | |
| `AUTOSUB_PORT` | `8020` | |

Xác thực Gemini: `gcloud auth application-default login`, và bật Vertex AI API cho project.

## Sử dụng

1. **Video mới**: kéo thả file, hoặc nhập đường dẫn file trên máy (không copy, hợp với file lớn).
2. **Thiết lập**: kéo khung trên ảnh để chọn vùng phụ đề cũ; đổi khung hình bằng thumbnail; chọn kiểu che (làm mờ / mờ + nền tối / dải màu), cỡ chữ, màu. "Render thử 5 giây" cho ra đúng kết quả ffmpeg. Chọn ngôn ngữ, model ASR, LLM, ghi chú cho người dịch, engine/giọng TTS (VieNeu có thể nhân bản giọng từ file mẫu 3–8 giây). Lưu thành preset để dùng lại.
3. **Bắt đầu** chạy đến bước dịch rồi dừng ở **Rà soát**; **Chạy thẳng** làm một mạch đến video (câu đọc không kịp sẽ được LLM tự rút gọn).
4. **Rà soát**: sửa bối cảnh dịch (xưng hô, thuật ngữ) rồi dịch lại; sửa từng câu, thời gian; nghe thử, dịch lại, gộp, tách, xoá câu. Thanh màu dưới mỗi câu: xanh = đọc vừa, vàng = cần tăng tốc, đỏ = quá ×1.35. Video bên cạnh hiển thị vùng che và phụ đề hiện tại. Phím tắt: `Space`, `Ctrl+↑/↓`, `Ctrl+Enter`.
5. **Render video** → **Kết quả**: xem và tải `.mp4`, `.srt`, `.ass`, giọng `.wav`.

Mỗi bước được cache theo đầu vào: đổi vùng che chỉ render lại; đổi giọng chỉ đọc lại TTS; sửa vài câu chỉ đọc lại đúng những câu đó. Lỗi ở bước nào thì "Chạy lại từ bước này"; tắt app giữa chừng thì job chuyển sang "Bị gián đoạn" và chạy tiếp được.

### Dòng lệnh

```bash
.venv/bin/autosub run video.mp4 --lang zh --region 0.05,0.8,0.9,0.14 --llm gemini --tts edge --out out.mp4
```

## Phát triển

```bash
make dev        # uvicorn --reload (8020) + Vite (5175)
make test       # test nhanh: không mạng, không model
make test-slow  # Demucs, FunASR, faster-whisper thật (tải model ở lần đầu)
```

Cấu trúc: `autosub/` (lõi: `pipeline.py` điều phối các bước; `asr/`, `llm/`, `tts/` là engine cắm được; `api.py` FastAPI), `frontend/` (React + Vite), `projects/<job>/` (dữ liệu từng job), `fonts/` (Be Vietnam Pro, giấy phép OFL).
