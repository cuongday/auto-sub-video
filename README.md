# Auto-Sub

Ứng dụng web chạy cục bộ: nhận video tiếng Trung hoặc tiếng Anh, làm mờ phụ đề cũ ở vùng bạn chọn, chèn phụ đề tiếng Việt và thuyết minh tiếng Việt thay giọng gốc (giữ nhạc nền, tiếng động).

Pipeline: `ffmpeg` tách âm thanh → **Demucs** tách giọng / nhạc nền → **ASR** (FunASR Paraformer cho tiếng Trung, faster-whisper cho tiếng Anh) → cắt câu → **LLM** (Gemini qua Vertex AI hoặc OpenAI) phân tích bối cảnh rồi dịch theo lô, giới hạn độ dài theo thời lượng → *rà soát* → **TTS** (edge-tts hoặc VieNeu-TTS) → khớp thời gian (tăng tốc tối đa ×1.35) → trộn với nhạc nền → render (che vùng + phụ đề ASS).

Mọi model chạy trên CPU.

## Chạy

App chỉ chạy qua Docker Compose, gồm 2 service: `auto-sub` (app) và `minio` (kho lưu trữ toàn bộ dữ liệu).

```bash
cp .env.example .env        # điền MINIO_ROOT_PASSWORD, GOOGLE_CLOUD_PROJECT + ADC_HOST_PATH (hoặc nhập OpenAI API key trên giao diện)
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
| `OPENAI_API_KEY` | — | khi dùng OpenAI; có thể nhập trên giao diện thay vì đặt ở đây (key trên web được ưu tiên) |
| `AUTOSUB_SECRET` | `MINIO_ROOT_PASSWORD` | khoá mã hoá API key nhập trên web |
| `OPENAI_MODEL` | `gpt-4.1-mini` | |
| `HOST_ROOT` | `./videos` | thư mục máy được duyệt chọn video trên web (chỉ đọc) |
| `AUTOSUB_BIND` | `127.0.0.1` | `0.0.0.0` để mở cho mạng LAN |
| `AUTOSUB_PASSWORD` | (trống) | mật khẩu đăng nhập web; trống = không cần đăng nhập |
| `VIENEU_MODE` | `v3turbo` | |
| `AUTOSUB_VOICE_WORKERS` | `4` | số bản VieNeu đọc song song trên CPU (~1,5 GB RAM mỗi bản) |
| `AUTOSUB_FFMPEG_PRESET` | `veryfast` | preset x264 |
| `AUTOSUB_FFMPEG_CRF` | `20` | nhỏ hơn = nét hơn |
| `AUTOSUB_WORK_MAX_GB` | `20` | giới hạn thư mục tạm trong container |
| `AUTOSUB_PORT` | `8020` | |
| `AUTOSUB_DOUYIN_WORKERS` | `4` | số video Douyin tải cùng lúc khi tạo job |

### Chạy VieNeu bằng GPU (NVIDIA)

Mặc định VieNeu chạy bằng CPU, máy nào cũng chạy được. Máy có GPU NVIDIA thì dùng bản GPU để đọc nhanh hơn nhiều lần:

1. Cài driver NVIDIA (≥ 525) và [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) (Linux), hoặc Docker Desktop dùng WSL2 + driver NVIDIA mới (Windows). Kiểm tra: `docker run --rm --gpus all ubuntu nvidia-smi`.
2. Chạy bản GPU:
   ```bash
   make up-gpu
   # = docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
   ```
   Muốn `docker compose up -d --build` luôn ra bản GPU thì thêm vào `.env`: `COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml` (Windows dùng `;`).
3. Trên web, ở mục **Thuyết minh** chọn VieNeu, phần **VieNeu chạy trên** chọn **Tự động** hoặc **GPU (NVIDIA)**; dòng bên dưới cho biết đang chạy trên GPU nào.

GPU cần ≥ 3,5 GB VRAM và compute capability ≥ 6.0 (GTX 10xx trở lên). Nếu chọn GPU mà máy không dùng được, app tự chạy CPU và ghi rõ lý do. Image GPU nặng khoảng 10 GB (so với ~3,4 GB bản CPU) vì có thư viện CUDA, và lần build đầu mất khoảng 10–15 phút để tải. Chỉ VieNeu dùng GPU; tách giọng, ASR, OCR vẫn chạy CPU.

| Biến `.env` | Mặc định | |
|---|---|---|
| `VIENEU_DEVICE` | `auto` | `auto` / `cpu` / `cuda`, chọn trên web sẽ ghi đè |
| `AUTOSUB_VIENEU_GPU_WORKERS` | `2` | số câu đọc song song trên GPU |

### Tải video Douyin

Chọn **Tải video Douyin** ở thanh bên trái rồi dán link:
- **link video** (`douyin.com/video/…`, hoặc cả đoạn chia sẻ có link `v.douyin.com/…`) → tải video đó;
- **link kênh** (`douyin.com/user/…`) → hiện danh sách video để tích chọn.

Chọn **Tải về đâu**:
- **Tạo job làm phụ đề**: video vào kho MinIO thành job mới (có thể áp một preset cho tất cả), tải song song `AUTOSUB_DOUYIN_WORKERS` video;
- **Lưu về máy**: lưu file MP4 gốc vào thư mục bạn chọn trên máy (Chrome/Edge), 3 video cùng lúc; trình duyệt khác thì lưu vào thư mục Tải xuống. Việc tải vẫn chạy khi bạn chuyển sang màn khác trong app.

Không đăng nhập thì mỗi kênh chỉ xem được trang đầu (~10–20 video). Bấm **Đăng nhập bằng mã QR** và quét bằng app Douyin để xem hết; phiên đăng nhập lưu trong MinIO (`douyin/session.json`). App dùng Chromium chạy ngầm trong container để đọc Douyin; video tải về đúng bản gốc không logo. Chỉ tải video bạn có quyền sử dụng.

### Project (mỗi kênh một project)

Video được gom theo **project**, thường mỗi project là một kênh Douyin (hoặc một nguồn khác). Project nằm ở thanh bên trái, bấm › để mở danh sách video bên trong.
- **Tạo project:** nút **+ Project**, hoặc lúc tải từ Douyin chọn "Tạo project ‘tên kênh’" (link kênh được gắn vào project, lần sau dán lại link kênh đó sẽ tự chọn đúng project).
- **Thêm video:** khi tải Douyin thành job, chọn project ở ô **Project**; ở màn **Video mới** chọn "Thêm vào project"; video có sẵn thì đổi ô **Project** ở đầu trang của video.
- **Preset của project:** sau khi làm tốt một video (vị trí phụ đề, vùng che, font, màu, giọng đọc…), bấm **Lưu làm preset của project** ở màn Kết quả (hoặc chọn video ở mục Preset trong trang project). Video mới thêm vào project tự dùng preset này.
- **Chạy hàng loạt:** trong trang project bấm **Chạy hàng loạt N video chưa chạy**: các video trạng thái "Mới" được áp preset rồi chạy thẳng tới thành phẩm.
- **Duyệt:** video chạy xong ở trạng thái **Xong**; xem lại rồi bấm **✓ Duyệt video** để chuyển sang **Đã duyệt**. Sửa phụ đề hoặc tuỳ chọn của video đã duyệt thì nó quay về **Xong** để duyệt lại.

### Các tiện ích khác

- **Chạy hàng loạt:** trong hộp duyệt thư mục, tích ô bên trái nhiều video → chọn preset → "Chạy thẳng N video".
- **Đọc phụ đề có sẵn (OCR):** ở "Lấy lời thoại" chọn *Đọc phụ đề có sẵn* — đọc chữ trong vùng **Phụ đề** đã khoanh; chính xác hơn nghe giọng khi video đã có sub cứng.
- **Nhiều người nói:** bật "Nhận diện người nói" (video tiếng Trung), rồi ở màn rà soát chọn giọng cho từng người.
- **Bỏ qua tách giọng:** tắt "Tách giọng khỏi nhạc nền" với vlog/review ít nhạc — nhanh hơn, giữ âm thanh gốc và tự hạ nhỏ khi có thuyết minh.
- **Nhiều vùng che:** "+ Thêm vùng che" để che logo, chữ chú thích ngoài vùng phụ đề.
- **Lời bài hát:** câu nghi là lời bài hát trong nhạc nền được đánh dấu 🎵, xoá một lần ở màn rà soát.
- **Bảng thuật ngữ dùng chung:** "Lưu vào bảng dùng chung" ở bối cảnh dịch — tên nhân vật, xưng hô, thuật ngữ áp cho mọi video sau.
- **Phụ đề mềm:** ở màn Kết quả, "Tạo bản có phụ đề mềm" thêm track phụ đề tiếng Việt bật/tắt được.
- **Dọn dữ liệu tạm:** ở màn Kết quả, hoặc bật tự dọn sau mỗi job.
- **Mật khẩu:** đặt `AUTOSUB_PASSWORD` trong `.env` (nên đặt khi mở app cho mạng LAN bằng `AUTOSUB_BIND=0.0.0.0`).

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

Sửa code không cần build lại image (chế độ dev, mount code từ thư mục này vào container):

```bash
make dev          # build giao diện 1 lần rồi chạy container với code ở máy; sửa .py là server tự khởi động lại
make dev-web      # (cửa sổ khác) tự build lại giao diện mỗi lần lưu — refresh trang để thấy
                  # hoặc: cd frontend && npm run dev  → mở http://localhost:5175 (đổi giao diện ngay, /api chuyển sang :8020)
make up           # quay lại chạy bằng image (cần khi đổi thư viện, Dockerfile, hoặc để chạy thật)
```

Lưu ý: mỗi lần server tự khởi động lại thì job đang chạy sẽ dừng — đừng sửa code backend khi có job dài đang chạy.

Thêm / nâng thư viện: `uv add <gói>` (hoặc `uv add --optional full <gói>`), rồi commit cả `pyproject.toml` và `uv.lock`.

Cấu trúc: `autosub/` (lõi: `pipeline.py` điều phối các bước; `storage.py` + `store.py` đọc ghi MinIO; `workdir.py` thư mục tạm; `asr/`, `llm/`, `tts/` là engine cắm được; `api.py` FastAPI), `frontend/` (React + Vite), `fonts/` (Be Vietnam Pro, giấy phép OFL).
