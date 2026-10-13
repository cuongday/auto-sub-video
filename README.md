# Auto-Sub

Ứng dụng web chạy cục bộ: nhận video tiếng Trung hoặc tiếng Anh, làm mờ phụ đề cũ ở vùng bạn chọn, chèn phụ đề tiếng Việt và thuyết minh tiếng Việt thay giọng gốc (giữ nhạc nền, tiếng động).

Pipeline: `ffmpeg` tách âm thanh → **Demucs** tách giọng / nhạc nền → **ASR** (FunASR Paraformer cho tiếng Trung, faster-whisper cho tiếng Anh) → cắt câu → **LLM** (Gemini qua Vertex AI hoặc OpenAI) phân tích bối cảnh rồi dịch theo lô, giới hạn độ dài theo thời lượng → *rà soát* → **TTS** (edge-tts hoặc VieNeu-TTS) → khớp thời gian (tăng tốc tối đa ×1.35) → trộn với nhạc nền → render (che vùng + phụ đề ASS).

Mọi model chạy trên CPU.

## Chạy

App chỉ chạy qua Docker Compose, gồm 2 service: `auto-sub` (app) và `minio` (kho lưu trữ toàn bộ dữ liệu).

```bash
cp .env.example .env        # điền MINIO_ROOT_PASSWORD, GOOGLE_CLOUD_PROJECT + ADC_HOST_PATH (hoặc OPENAI_API_KEY)
docker compose up -d --build   # hoặc: make up
# -> http://localhost:8020      (trang quản trị MinIO: http://127.0.0.1:9201)
```

- Image đầy đủ (Demucs, FunASR, faster-whisper, VieNeu, torch CPU) nặng khoảng 3 GB, build lần đầu mất 10–15 phút. Bản nhẹ chỉ có edge-tts + Gemini/OpenAI: đổi `FULL: "1"` thành `"0"` trong `docker-compose.yml`.
- **Dữ liệu:** mọi thứ của job (video gốc, âm thanh tách, phụ đề, giọng đọc, thành phẩm) và cache TTS nằm trong bucket MinIO `autosub` (volume `minio-data`). Container app chỉ có thư mục tạm `/work` cho ffmpeg/model đọc ghi, tự xoá khi khởi động lại và giới hạn bằng `AUTOSUB_WORK_MAX_GB`.
- **Model AI** tải ở lần dùng đầu (~2–5 GB), lưu trong volume `models`.
- **Video trên máy:** thư mục `HOST_ROOT` được gắn **chỉ đọc** vào app; mặc định là thư mục `videos/` trong project (bỏ video vào đó là thấy). Ở màn "Video mới" có hộp duyệt để chọn video trong đó (ẩn thư mục bắt đầu bằng dấu chấm, không ra ngoài `HOST_ROOT`), và nút "Đặt làm thư mục mặc định". Video được copy vào MinIO khi tạo job, nên xoá file gốc sau đó không ảnh hưởng.
- **Truy cập:** mặc định app chỉ mở cho máy này (`127.0.0.1:8020`), vì nó duyệt được file trong `HOST_ROOT`. Muốn máy khác trong mạng LAN dùng thì đặt `AUTOSUB_BIND=0.0.0.0` (họ cũng duyệt được `HOST_ROOT`).
- **Gemini:** file ADC tại `ADC_HOST_PATH` được gắn chỉ đọc. Chạy `gcloud auth application-default login` trên máy trước.
- Container chạy với UID/GID 1000; khác thì đặt `UID`/`GID` trong `.env`.

Lệnh hay dùng: `make logs`, `make down` (giữ dữ liệu), `docker compose down -v` (xoá cả dữ liệu MinIO và model).

### Windows / macOS

Chạy được với **Docker Desktop** (Windows dùng nền WSL2), lệnh giống hệt: `docker compose up -d --build`. Chỉ khác đường dẫn trong `.env` — dùng dấu `/`, Docker Desktop tự chuyển:

```dotenv
# Windows
HOST_ROOT=C:/Users/<tên>/Videos
ADC_HOST_PATH=C:/Users/<tên>/AppData/Roaming/gcloud/application_default_credentials.json
# macOS
HOST_ROOT=/Users/<tên>/Movies
ADC_HOST_PATH=/Users/<tên>/.config/gcloud/application_default_credentials.json
```

- Không dùng Gemini (chỉ OpenAI) thì để trống `ADC_HOST_PATH`.
- `make` không có sẵn trên Windows: dùng thẳng các lệnh `docker compose ...` tương ứng.
- Repo ép kết thúc dòng LF (`.gitattributes`) nên clone trên Windows vẫn build đúng.
- `UID`/`GID` chỉ có ý nghĩa trên Linux; Windows/macOS để mặc định.

### Cấu hình `.env`

| Biến | Mặc định | Ghi chú |
|---|---|---|
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | — | bắt buộc; tài khoản MinIO (mật khẩu ≥ 8 ký tự) |
| `MINIO_BUCKET` | `autosub` | |
| `MINIO_CONSOLE_PORT` | `9201` | trang quản trị MinIO, chỉ mở trên máy này |
| `GOOGLE_CLOUD_PROJECT` | — | bắt buộc khi dùng Gemini |
| `GOOGLE_LOCATION` | `global` | vùng gọi Vertex AI |
| `ADC_HOST_PATH` | (trống) | file ADC trên máy; trống nếu chỉ dùng OpenAI |
| `GEMINI_TEXT_MODEL` | `gemini-2.5-flash` | |
| `OPENAI_API_KEY` | — | bắt buộc khi dùng OpenAI |
| `OPENAI_MODEL` | `gpt-4.1-mini` | |
| `HOST_ROOT` | `./videos` | thư mục máy được duyệt chọn video trên web (chỉ đọc) |
| `AUTOSUB_BIND` | `127.0.0.1` | `0.0.0.0` để mở cho mạng LAN |
| `VIENEU_MODE` | `v3turbo` | |
| `AUTOSUB_VOICE_WORKERS` | `4` | số bản VieNeu đọc song song (~1,5 GB RAM mỗi bản) |
| `AUTOSUB_FFMPEG_PRESET` | `veryfast` | preset x264 |
| `AUTOSUB_FFMPEG_CRF` | `20` | nhỏ hơn = nét hơn |
| `AUTOSUB_WORK_MAX_GB` | `20` | giới hạn thư mục tạm trong container |
| `AUTOSUB_PORT` | `8020` | |

## Sử dụng

1. **Video mới**: kéo thả / bấm chọn file để tải lên, hoặc chọn video có sẵn trên máy trong hộp duyệt thư mục (không phải tải lên). Video được copy vào MinIO.
2. **Thiết lập**: kéo khung trên ảnh để chọn vùng phụ đề cũ; đổi khung hình bằng thumbnail; chọn kiểu che (làm mờ / mờ + nền tối / dải màu), cỡ chữ, màu. "Render thử 5 giây" cho ra đúng kết quả ffmpeg. Chọn ngôn ngữ, model ASR, LLM, ghi chú cho người dịch, engine/giọng TTS (VieNeu có thể nhân bản giọng từ file mẫu 3–8 giây). Lưu thành preset để dùng lại.
3. **Bắt đầu** chạy đến bước dịch rồi dừng ở **Rà soát**; **Chạy thẳng** làm một mạch đến video (câu đọc không kịp sẽ được LLM tự rút gọn).
4. **Rà soát**: sửa bối cảnh dịch (xưng hô, thuật ngữ) rồi dịch lại; sửa từng câu, thời gian; nghe thử, dịch lại, gộp, tách, xoá câu. Thanh màu dưới mỗi câu: xanh = đọc vừa, vàng = cần tăng tốc, đỏ = quá ×1.35. Video bên cạnh hiển thị vùng che và phụ đề hiện tại. Phím tắt: `Space`, `Ctrl+↑/↓`, `Ctrl+Enter`.
5. **Render video** → **Kết quả**: xem và tải `.mp4`, `.srt`, `.ass`, giọng `.wav`.

Mỗi bước được cache theo đầu vào: đổi vùng che chỉ render lại; đổi giọng chỉ đọc lại TTS; sửa vài câu chỉ đọc lại đúng những câu đó. Lỗi ở bước nào thì "Chạy lại từ bước này"; tắt app giữa chừng thì job chuyển sang "Bị gián đoạn" và chạy tiếp được.

### Dòng lệnh

```bash
docker compose exec auto-sub autosub run /host/Videos/clip.mp4 --lang zh --tts edge
```

## Phát triển

Môi trường Python quản lý bằng [uv](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock` khoá đúng phiên bản; torch lấy bản CPU). Docker image cũng cài từ cùng `uv.lock`.

```bash
make setup        # uv sync (.venv nhẹ) + npm — đủ để chạy test và build giao diện
make setup-full   # uv sync --extra full: thêm torch CPU, Demucs, FunASR, faster-whisper, VieNeu
make test         # test nhanh: không mạng, không model, kho lưu trữ giả lập trong bộ nhớ
make test-minio   # test lớp lưu trữ với MinIO thật (tự bật container tạm, cần Docker)
make test-slow    # Demucs, FunASR, faster-whisper thật (cần setup-full)
```

Thêm / nâng thư viện: `uv add <gói>` (hoặc `uv add --optional full <gói>`), rồi commit cả `pyproject.toml` và `uv.lock`.

Cấu trúc: `autosub/` (lõi: `pipeline.py` điều phối các bước; `storage.py` + `store.py` đọc ghi MinIO; `workdir.py` thư mục tạm; `asr/`, `llm/`, `tts/` là engine cắm được; `api.py` FastAPI), `frontend/` (React + Vite), `fonts/` (Be Vietnam Pro, giấy phép OFL).
