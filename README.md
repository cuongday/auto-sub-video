# Auto-Sub

Ứng dụng web chạy cục bộ: nhận video tiếng Trung hoặc tiếng Anh, làm mờ phụ đề cũ ở vùng bạn chọn, chèn phụ đề tiếng Việt và thuyết minh tiếng Việt thay giọng gốc (giữ nhạc nền, tiếng động).

Pipeline: `ffmpeg` tách âm thanh → **Demucs** tách giọng / nhạc nền → **ASR** (FunASR Paraformer cho tiếng Trung, faster-whisper cho tiếng Anh) → cắt câu → **LLM** (Gemini qua Vertex AI hoặc OpenAI) phân tích bối cảnh rồi dịch theo lô, giới hạn độ dài theo thời lượng → *rà soát* → **TTS** (edge-tts hoặc VieNeu-TTS) → khớp thời gian (tăng tốc tối đa ×1.35) → trộn với nhạc nền → render (che vùng + phụ đề ASS).

Mọi model chạy trên CPU.

## Chạy

App chỉ chạy qua Docker Compose, gồm 2 service: `auto-sub` (app) và `minio` (kho lưu trữ toàn bộ dữ liệu).

```bash
cp .env.example .env        # điền MINIO_ROOT_PASSWORD, GOOGLE_CLOUD_PROJECT + ADC_HOST_PATH (hoặc OPENAI_API_KEY), VIDEOS_DIR
docker compose up -d --build   # hoặc: make up
# -> http://localhost:8020      (trang quản trị MinIO: http://127.0.0.1:9201)
```

- Image đầy đủ (Demucs, FunASR, faster-whisper, VieNeu, torch CPU) nặng khoảng 3 GB, build lần đầu mất 10–15 phút. Bản nhẹ chỉ có edge-tts + Gemini/OpenAI: đổi `FULL: "1"` thành `"0"` trong `docker-compose.yml`.
- **Dữ liệu:** mọi thứ của job (video gốc, âm thanh tách, phụ đề, giọng đọc, thành phẩm) và cache TTS nằm trong bucket MinIO `autosub` (volume `minio-data`). Container app chỉ có thư mục tạm `/work` cho ffmpeg/model đọc ghi, tự xoá khi khởi động lại và giới hạn bằng `AUTOSUB_WORK_MAX_GB`.
- **Model AI** tải ở lần dùng đầu (~2–5 GB), lưu trong volume `models`.
- **Video trên máy:** `VIDEOS_DIR` (mặc định `~/Videos`) được gắn chỉ đọc vào `/videos`; nhập `/videos/<tên file>` ở ô "dùng file có sẵn". Video luôn được copy vào MinIO khi tạo job, nên xoá file gốc sau đó không ảnh hưởng.
- **Gemini:** file ADC tại `ADC_HOST_PATH` được gắn chỉ đọc. Chạy `gcloud auth application-default login` trên máy trước.
- Container chạy với UID/GID 1000; khác thì đặt `UID`/`GID` trong `.env`.

Lệnh hay dùng: `make logs`, `make down` (giữ dữ liệu), `docker compose down -v` (xoá cả dữ liệu MinIO và model).

### Cấu hình `.env`

| Biến | Mặc định | Ghi chú |
|---|---|---|
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | — | bắt buộc; tài khoản MinIO (mật khẩu ≥ 8 ký tự) |
| `MINIO_BUCKET` | `autosub` | |
| `MINIO_CONSOLE_PORT` | `9201` | trang quản trị MinIO, chỉ mở trên máy này |
| `GOOGLE_CLOUD_PROJECT` | — | bắt buộc khi dùng Gemini |
| `GOOGLE_LOCATION` | `global` | vùng gọi Vertex AI |
| `ADC_HOST_PATH` | — | file ADC trên máy |
| `GEMINI_TEXT_MODEL` | `gemini-2.5-flash` | |
| `OPENAI_API_KEY` | — | bắt buộc khi dùng OpenAI |
| `OPENAI_MODEL` | `gpt-4.1-mini` | |
| `VIDEOS_DIR` | `~/Videos` | thư mục video trên máy |
| `VIENEU_MODE` | `v3turbo` | |
| `AUTOSUB_VOICE_WORKERS` | `4` | số bản VieNeu đọc song song (~1,5 GB RAM mỗi bản) |
| `AUTOSUB_FFMPEG_PRESET` | `veryfast` | preset x264 |
| `AUTOSUB_FFMPEG_CRF` | `20` | nhỏ hơn = nét hơn |
| `AUTOSUB_WORK_MAX_GB` | `20` | giới hạn thư mục tạm trong container |
| `AUTOSUB_PORT` | `8020` | |

## Sử dụng

1. **Video mới**: kéo thả file, hoặc nhập đường dẫn `/videos/<tên file>` (file trong `VIDEOS_DIR`, không phải upload qua trình duyệt). Video được copy vào MinIO.
2. **Thiết lập**: kéo khung trên ảnh để chọn vùng phụ đề cũ; đổi khung hình bằng thumbnail; chọn kiểu che (làm mờ / mờ + nền tối / dải màu), cỡ chữ, màu. "Render thử 5 giây" cho ra đúng kết quả ffmpeg. Chọn ngôn ngữ, model ASR, LLM, ghi chú cho người dịch, engine/giọng TTS (VieNeu có thể nhân bản giọng từ file mẫu 3–8 giây). Lưu thành preset để dùng lại.
3. **Bắt đầu** chạy đến bước dịch rồi dừng ở **Rà soát**; **Chạy thẳng** làm một mạch đến video (câu đọc không kịp sẽ được LLM tự rút gọn).
4. **Rà soát**: sửa bối cảnh dịch (xưng hô, thuật ngữ) rồi dịch lại; sửa từng câu, thời gian; nghe thử, dịch lại, gộp, tách, xoá câu. Thanh màu dưới mỗi câu: xanh = đọc vừa, vàng = cần tăng tốc, đỏ = quá ×1.35. Video bên cạnh hiển thị vùng che và phụ đề hiện tại. Phím tắt: `Space`, `Ctrl+↑/↓`, `Ctrl+Enter`.
5. **Render video** → **Kết quả**: xem và tải `.mp4`, `.srt`, `.ass`, giọng `.wav`.

Mỗi bước được cache theo đầu vào: đổi vùng che chỉ render lại; đổi giọng chỉ đọc lại TTS; sửa vài câu chỉ đọc lại đúng những câu đó. Lỗi ở bước nào thì "Chạy lại từ bước này"; tắt app giữa chừng thì job chuyển sang "Bị gián đoạn" và chạy tiếp được.

### Dòng lệnh

```bash
docker compose exec auto-sub autosub run /videos/clip.mp4 --lang zh --tts edge
```

## Phát triển

```bash
make setup        # .venv + npm, chỉ để chạy test và build giao diện
make test         # test nhanh: không mạng, không model, kho lưu trữ giả lập trong bộ nhớ
make test-minio   # test lớp lưu trữ với MinIO thật (tự bật container tạm, cần Docker)
make test-slow    # Demucs, FunASR, faster-whisper thật
```

Cấu trúc: `autosub/` (lõi: `pipeline.py` điều phối các bước; `storage.py` + `store.py` đọc ghi MinIO; `workdir.py` thư mục tạm; `asr/`, `llm/`, `tts/` là engine cắm được; `api.py` FastAPI), `frontend/` (React + Vite), `fonts/` (Be Vietnam Pro, giấy phép OFL).
