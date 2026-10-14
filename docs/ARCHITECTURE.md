# Kiến trúc hiện hành

Mô tả cách app Audio Translate được ghép từ các phần. Chi tiết từng tính năng nằm ở các tài liệu khác trong thư mục này (xem [README.md](README.md)). Vận hành server, hạ tầng và chi tiết cơ chế bảo vệ nằm ở repo riêng tư của dự án, không đặt ở đây.

## Sản phẩm

Ứng dụng Windows chạy trên máy người dùng: tải audio (YouTube hoặc file tiếng Trung) → chép lời tiếng Trung → dịch sang tiếng Việt → kiểm duyệt bằng luật thay thế → tạo giọng đọc. Có hai gói:

| Gói | Khác biệt |
|---|---|
| **Plus** | Tạo giọng ngay trên máy. |
| **Basic** | Tạo giọng qua dịch vụ trực tuyến; dừng ở bước duyệt trước khi tạo giọng, trừ khi bật ô Auto. |

Dịch có hai chế độ: chạy trên máy (Hy-MT2-7B, tải sau khi cài) hoặc dịch vụ trực tuyến (tính phí, theo hạn mức).

## Bố cục thư mục

Mỗi framework có thư mục riêng, đồng cấp ở gốc repo: `web/` (Next.js, UI tĩnh, `npm` chạy ở đây), `worker/` (Python: FastAPI + pipeline AI), `desktop/` (Tauri, Rust), `security-core/` (Rust, Windows Service). Cùng với `packaging/` (build bộ cài), `contracts/` (hợp đồng API và test), `docs/`, `products/`, `licensing/`.

## Các lớp của app

```
Cửa sổ (Tauri, Rust)  ──mở──▶  UI Next.js xuất tĩnh (HTML/JS/CSS)
        │                              │ HTTP, 127.0.0.1
        └─khởi động/giám sát──▶  API cục bộ (FastAPI, Python)  ──▶  worker Python (pipeline AI)
                                       │ Named Pipe                      ▲
                                       └──▶  security-core (Rust, Windows Service) ── cho phép/từ chối chạy
```

- **Vỏ desktop (`desktop/`)**: Tauri 2. Mở cửa sổ WebView2, khởi động API cục bộ, chạy lại nếu API chết, chỉ cho một bản chạy cùng lúc, mở link ngoài bằng trình duyệt, dọn mọi tiến trình con khi thoát (Job Object). Không chứa logic sản phẩm và không nói chuyện với security-core.
- **UI (`web/`: `app/`, `components/`, `lib/`, `packages/ui`)**: Next.js với `output: "export"`; không có server Node, không có route handler. Phần dùng chung (theme, cơ chế ngôn ngữ, component chung, adapter API) là gói workspace `@audio/ui`.
- **API cục bộ (`worker/audio_translate/api`)**: FastAPI trên 127.0.0.1 (cổng cố định khi đã cài). Phục vụ UI tĩnh và toàn bộ `/api/*`; hợp đồng ở `contracts/app-api.openapi.json`. Đăng nhập bằng link khởi động dùng một lần → cookie `HttpOnly`, `SameSite=Strict`; kiểm `Host` và `Origin`. Bộ lập lịch (`api/jobs.py`) sở hữu các tiến trình workflow.
- **Worker (`worker/audio_translate/{core,workflow,transcription,translation,tts,moderation}`)**: pipeline AI, chạy CPU. Cấu hình JSON ở `worker/config/`. Các script vào (`manage`, `retry`, `orchestrator`, ...) giữ tên cố định vì nằm trong danh sách cho phép của security-core.
- **security-core (`security-core/`)**: Rust, Windows Service + Named Pipe. Xác minh license/lease và tính toàn vẹn của gói trước mỗi lần chạy xử lý; không có đường tắt nào cho mã Python.
- **Node**: chỉ còn đi kèm bộ cài để yt-dlp giải thử thách JavaScript của YouTube.

## Dữ liệu

Khi đã cài, dữ liệu người dùng (kích hoạt, kết quả, model đã tải) nằm ở `%LOCALAPPDATA%\AudioTranslate`, ngoài thư mục cài nên được giữ qua cập nhật và gỡ cài đặt.

## Đóng gói

`python packaging/build_edition.py basic|plus` build lõi bảo mật, vỏ Tauri, UI tĩnh, gom Python/Node/FFmpeg và ghép bộ cài (`installer.cs`, .NET) dưới 4 GiB; model dịch không nằm trong bộ cài. Xem [BUILD_RELEASE.md](BUILD_RELEASE.md) và [CLEAN_ARCHITECTURE.md](CLEAN_ARCHITECTURE.md).

## Kiểm thử

| Phần | Lệnh |
|---|---|
| Worker (Python) | `cd worker; ..\.venv\Scripts\python.exe -m unittest discover -s tests -t .` |
| API so với hợp đồng | `.venv\Scripts\python.exe contracts\tests\run_app_contract.py` |
| UI trong Edge thật | `.venv\Scripts\python.exe contracts\tests\ui_smoke.py` |
| Type, lint, ngôn ngữ, theme | `cd web; npx tsc --noEmit`, `npm run lint`, `npm run check:i18n`, `npm run check:theme` |
| Lõi bảo mật | `cd security-core; cargo test --release` |
| Vỏ Tauri | `cd desktop; cargo test --release`; `cd packaging; ..\.venv\Scripts\python.exe -m unittest test_shell` |
| Cài/gỡ/bảo mật | `cd packaging; ..\.venv\Scripts\python.exe -m unittest test_install_flow test_security_phase1 test_security_phase2` |
