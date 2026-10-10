# PITFALLS — Lỗi và bẫy có thể tái phát

Chỉ giữ thứ mà nếu không biết thì dễ làm sai hoặc mất nhiều giờ chẩn đoán. Mỗi mục: triệu chứng → nguyên nhân gốc → cách tránh/sửa. Chi tiết gốc nằm ở tài liệu được nêu cuối mỗi mục. Thông tin đo ngày nào ghi ngày đó vì môi trường ngoài (YouTube, Cloud, payOS) có thể đã đổi.

## A. Tải YouTube

### A1. "Sign in to confirm you're not a bot" (IP trung tâm dữ liệu)
- **Nguyên nhân:** YouTube chặn IP GCP của VM: 12/12 lượt bị đòi đăng nhập (2026-10-09), kể cả khi có bộ giải JS.
- **Tránh:** không tải YouTube từ server. Việc tải luôn chạy trên máy khách. Đường dự phòng là nạp file audio tiếng Trung.
- Khi thử nghiệm từ máy nhà: IP nhà có thể đổi theo giờ và dính 429 sau khoảng 30 lượt thử, nên giữ số lần thử ít nhất có thể.
- `YOUTUBE_DOWNLOAD.md` mục 1, 3.

### A2. `The page needs to be reloaded` / mọi client đều lỗi khi có cookie
- **Nguyên nhân:** phiên YouTube đã lưu bị YouTube từ chối hoặc xoay vòng. Có cookie hỏng thì mọi client lỗi; không cookie thì tải được. Không phải do yt-dlp cũ.
- **Tránh:** thứ tự thử hiện tại là ẩn danh trước, cookie sau. Báo khách vào Settings → Kết nối YouTube để đăng nhập lại.
- `BUILD_RELEASE.md` mục 11.

### A3. `n challenge solving failed` rồi `Requested format is not available`
- **Nguyên nhân gốc:** `packaging/build_installer.py` đánh giá điều kiện `extra == 'default'` của gói con mà không có extra, nên bỏ hết phụ thuộc của `yt-dlp[default]` (`yt-dlp-ejs`, certifi, mutagen, pycryptodomex, brotli, requests). Máy dev có đủ nên vẫn tải được, bản cài thì không. Đây là loại lỗi "dev chạy, bản cài hỏng".
- **Tránh:** build có chốt chặn `REQUIRED_PACKAGES` và dừng với `DEPENDENCY_DROPPED: <tên>`; cuối build có import kiểm tra. Khi thêm phụ thuộc nặng, kiểm tra bản cài chứ không chỉ máy dev.
- `YOUTUBE_DOWNLOAD.md` mục 6, 8.

### A4. "Không mở được hồ sơ YouTube" (Edge tự khởi động lại)
- **Nguyên nhân gốc:** mọi tiến trình của app thừa hưởng biến `__COMPAT_LAYER=DetectorsAppHealth` do Windows gắn. Edge thấy biến này thì tự chạy lại bản mới (cờ `--edge-skip-compat-layer-relaunch`) và tiến trình đầu thoát; `launch()` tưởng Edge chết. Edge khởi động lại bị bỏ rơi, tốn ~526 MB.
- **Đã sửa:** `browser_cleanup.browser_env()` bỏ biến này khi mở Edge; `launch()` chỉ báo lỗi khi tiến trình đầu thoát **và** không còn Edge ẩn nào của hồ sơ.
- **Khi tái hiện:** Python của app đã cài có `python312._pth` khóa đường dẫn nạp, nên chạy `worker/youtube_session.py` của repo bằng Python đó vẫn nạp mã cũ đã cài. Phải dùng Python dev (`.venv`) hoặc chèn đường dẫn trong script.
- `YOUTUBE_DOWNLOAD.md` mục 7, 9.

### A5. Tab `about:blank` dồn lại, Edge ẩn chạy ngầm sau khi đóng app
- **Nguyên nhân:** cờ `--restore-last-session` cộng thêm tab mỗi lần mở; Edge ẩn bị bỏ rơi khi Python bị giết (hạn 60 giây của web server, hoặc Dừng/Hủy lúc đang tải).
- **Đã sửa:** bỏ cờ đó; Edge ẩn chạy trong Job Object `KILL_ON_JOB_CLOSE`; dọn theo `--user-data-dir` đúng hồ sơ app và `--headless`. Cửa sổ đăng nhập thường và Edge của người dùng **không** được đụng vào.

## B. Build và phát hành

### B1. File `.exe` quá 4 GiB không chạy
- **Triệu chứng:** "This app can't run on your PC". Bản 1.2.0 đầu tiên (4,9 GB) hỏng vì vậy.
- **Tránh:** không nhét model vào bộ cài. Sau mỗi build xem kích thước trong `dist`; Basic ≈ 0,58 GB, Plus ≈ 0,62 GB. Nếu gần 4 GiB thì có thứ nặng lọt vào.

### B2. `FileNotFoundError WinError 3` khi chép thư viện
- **Nguyên nhân:** đường dẫn đích > 259 ký tự (máy `LongPathsEnabled=0`; `modelscope` có tệp 262 ký tự), bị đẩy qua ngưỡng bởi tên thư mục staging dài.
- **Tránh:** staging dùng tên ngắn (`s` + 6 ký tự băm). Gặp lại `WinError 3` thì kiểm tra độ dài đường dẫn trước.

### B3. Cài xong nhưng bấm shortcut không thấy gì
- **Nguyên nhân:** (1) `python312._pth` của runtime đi kèm tắt thư mục-của-script trong `sys.path`, `from paths import ...` lỗi `ModuleNotFoundError`; (2) lần khởi động nguội đầu tiên `/api/license` trả lời chậm > 2 giây, launcher chỉ bắt `URLError` nên sập vì `TimeoutError`. Shortcut dùng `pythonw.exe` nên lỗi bị nuốt.
- **Tránh:** launcher tự thêm thư mục của nó vào `sys.path`, timeout dài hơn, bắt `OSError`. Lỗi khởi động ghi vào `%LOCALAPPDATA%\AudioTranslate\launcher-error.log`. Mọi script chạy trong runtime đóng gói đều chịu cùng ràng buộc `_pth`.

### B4. `VERSION_ALREADY_RELEASED` hoặc `RELEASE_ARTIFACT_MISSING_OR_MODIFIED`
- **Nguyên nhân:** mã đã đổi mà chưa tăng version; hoặc `.exe` / `dist\release-*.json` bị xóa hay sửa tay.
- **Tránh:** tăng `version` **và** `artifact_path` ở cả `products\basic\product.manifest.json` và `products\plus\product.manifest.json`. Nếu bản cũ chưa từng phát cho ai thì xóa cả cặp `.exe` + `release-*.json` của version đó rồi build lại.

### B5. Thiếu lease cho phiên bản mới → app không mở được kho tài nguyên
- **Triệu chứng:** gateway trả `LEASE_VERSION_UNSUPPORTED`; danh sách giọng không tải.
- **Nguyên nhân:** mỗi phiên bản có content key riêng; chưa đẩy lên gateway.
- **Tránh:** sau **mỗi** build version mới: admin → Sản phẩm → *Đồng bộ khóa với gateway* (hoặc `build_edition.py --push-lease`). Build lại cùng số version thì không cần.

### B6. Khóa phiên bản `.key` / khóa ký không được vào repo
- Khóa nội dung xuất ra **ngoài mọi repo** (`C:\Users\<user>\audio-translate-keys\`), script từ chối ghi vào trong repo. Không commit, không gửi đi, không sửa tay `dist\release-*.json`. `SECRET_SCAN_FAILED` nghĩa là có thứ giống khóa/token/DB trong gói: **không phát gói**.

### B7. Build khi đang chạy workflow
- Build ngốn RAM/CPU làm workflow tạm dừng vì thiếu RAM. `build_edition.py` đòi 5 GiB trống (ngưỡng đặt rộng; thực đo giảm khoảng 1 GiB, `--force` được nếu còn trên khoảng 3,3 GiB). Không build khi đang dịch hoặc tạo giọng.

### B8. `security-core` đổi thì phải tăng version
- Sửa Rust (`security-core`) hoặc shim ở `worker/` đòi build lại lõi và tăng version. Rust dùng bộ riêng ở `.tools\rust` (không có `cargo` trên PATH, đừng kết luận là "không có cargo").

## C. Model và tài nguyên

### C1. Tải model dịch báo "không tải được"
- **Nguyên nhân thường gặp:** app **chưa kích hoạt** (`UNACTIVATED`), lõi bảo mật không cấp token, lệnh dừng ngay với `LICENSE_REQUIRED` mà không gọi mạng. Đây là đúng hành vi; giao diện hiện "chưa kích hoạt".
- **Giới hạn:** 12 link/ngày/license. Bấm nhiều lần chỉ tạo một lượt tải và một link nhờ khóa ở server.
- **Đồng bộ ba chỗ khi đổi model:** `download_translation_model.py` (`FILENAME/SIZE/SHA256`), `lib/server/model-download.ts` (`MODEL`), gateway `MODELS` + `upload_model.py`.

### C2. ASR chết ở ~54% mô hình 990 MB (`ASR model startup timed out`)
- **Nguyên nhân:** FunASR tự tải model từ ModelScope trong lúc worker khởi động, bị giới hạn 180 giây.
- **Tránh:** bước `model_prefetch.py` tải trước khi worker bắt đầu đếm giờ, từ bucket qua gateway; ModelScope chỉ là dự phòng.

### C3. Hy-MT2-7B hết RAM
- Mặc định `llama.cpp` repack tensor làm RAM > 6,7 GiB; phải dùng `--no-repack` (+4,5–4,8 GiB). Luôn chừa **2 GiB** cho hệ thống. Ngưỡng khởi động 6 GiB; dưới mức này job tự tạm dừng, cần đóng bớt ứng dụng.
- Repo model chính thức không có Q4_K_S/Q3_K_M.

### C4. Dịch lan man, dòng ngắn thành đoạn dài
- **Nguyên nhân (đã đo):** dòng phụ đề rất ngắn (trung vị 9 ký tự) nhưng prompt cũ kèm 512 ký tự ngữ cảnh nên model dịch luôn đoạn ngữ cảnh; lượt sửa nhét bản nháp lỗi vào prompt khiến lỗi lặp lại.
- **Tránh:** không đưa ngữ cảnh dài hay bản nháp lỗi vào prompt dòng ngắn; giữ kiểm tra độ dài `max(80, 12 × ký tự nguồn)`; seed theo hash nội dung. Cache dịch từ prompt cũ có thể chứa bản lạc nên Reprocess từ TRANSLATION.

### C5. ASR không phân biệt 他/她
- Nguyên nhân gốc của sai giới tính/xưng hô ở bản dịch. Không đoán lại ở bước dịch: dùng bảng nhân vật (`working/characters.json`) và sửa 他/她 chỉ khi chắc.

### C6. `CLOCK_ROLLBACK` thoáng qua giữa hai stage
- Đã sửa bằng dung sai 5 phút (`CLOCK_SKEW_SECONDS` trong `security-core/src/license.rs`). Nếu tái xuất hiện: `progress()` ghi `last_verified_time` bằng giờ local còn stage sau so với giờ internet; đồng hồ máy nhanh ~1 giây là đủ để báo lỗi. Retry stage thì qua.

### C7. Định mức RAM trong test lệch với cấu hình thật
- Test `memory_policy`/`workflow_admission` từng viết theo ngưỡng cũ. Khi đổi `worker/config/*.json` phải cập nhật test mẫu và test kiểm tra `asr-memory.json` khớp tiêu chuẩn.

## D. License, admin, thanh toán

### D1. Cấp license từ PC admin sau khi đã chuyển lên server
- PC admin đã **đóng băng** (`AUTHORITY_MOVED`); cấp từ hai nơi sẽ lệch `sequence`. Thay đổi cấu hình server bằng `deploy/deploy_admin.py` / `deploy_gateway.py`, không sửa tay trên VM.
- Thêm người vào admin cần **cả** policy Cloudflare Access **và** `ADMIN_EMAILS`.
- **Không đặt Cloudflare Access lên `billing.*` hoặc `audio-gateway.*`** (chặn payOS và app khách).

### D2. Mất master key hoặc khóa ký
- `/etc/audio-admin/master.key` (64 hex) và một bản offline. Mất cả hai là mất toàn bộ khóa ký, không khôi phục được. Bản master key còn ở `C:\Users\Linh\audio-translate-keys\admin-move\admin-master.key` chờ người dùng chuyển offline. `LEASE_MASTER_KEY` thiếu thì dịch vụ lease tắt; giữ bản offline.
- Khóa ký cập nhật yt-dlp: `C:\Users\Linh\.audio-translate\youtube-update-signing.pem`. Không nằm trong repo. **Mất thì phải `--init-key` và build lại app** để app tin khóa mới. Cần sao lưu.

### D3. Gia hạn: token phải nhập đúng thứ tự
- Lõi bắt buộc `sequence` liên tiếp (2 rồi 3), dù mỗi token đã mang mốc hạn cộng dồn. Cho phép nhảy thẳng đòi sửa Rust và build lại, chưa làm.

### D4. License hết hạn không tự gia hạn được từ app
- Lõi từ chối cấp token cho license hết hạn (chủ ý không sửa). Khách đi theo **Mã khách hàng** rồi **dán mã gia hạn** từ trang đơn. Nhập sai mã 10 lần trong 10 phút bị chặn theo IP.

### D5. Khách mới không dùng được Genius/giọng đọc
- Hạn mức nợ mặc định toàn cục là **0**. Đặt ở admin → Payments → Hạn mức. Job dừng với `CREDIT_LIMIT` (402) cho tới khi trả nợ hoặc nâng hạn mức.
- Giá/hạn mức sửa là **nháp**, chỉ áp dụng sau Lưu.

### D6. payOS
- Mức tối thiểu 1.000đ (đã thử, thấp hơn chưa thử). Mã đơn = `epoch giây × 1000 + ngẫu nhiên 0–999`. Đơn trả nợ tối thiểu `min(trả tối thiểu, số nợ)`, không cho trả quá nợ.
- Trước đây gia hạn chỉ được ký khi giao diện admin hoặc `renewal_worker` chạy; admin trên VM giờ ký tự động (`ADMIN_FULFILLMENT=on`). Nếu đơn "đã trả mà chưa gia hạn", kiểm tra admin trên VM đang chạy và kênh duyệt trực tiếp.
- Khi sửa webhook: chữ ký đúng → 200, giả → 400; kiểm sau mỗi lần đổi Cloudflare/Tunnel.

### D7. Gemini key bị chặn theo IP (đã xử lý 2026-10-11)
- `403 API_KEY_IP_ADDRESS_BLOCKED`: khóa giới hạn IP chỉ cho phép IP của máy cũ. Chủ dự án đã bỏ giới hạn; đã gọi thử từ VPS `15.235.207.5` trả 200.
- **Nếu đổi máy chủ lần nữa** hoặc đặt lại giới hạn IP: thêm IP mới trước khi cắt chuyển rồi gọi thử từ chính máy đó.
- Mã tính phí: ước tính trước dùng tỉ lệ Việt/Trung 3,5; số đo thật 3,08 (2,91–3,20).

### D8. Máy chủ: VPS OVH (VM Spot GCP đã bỏ 2026-10-11)
- Không còn rủi ro Spot tự dừng. Máy chỉ có 4 GB RAM: đủ **một** worker TTS; đừng tăng `TTS_WORKERS` khi chưa nâng gói.
- Mọi thứ (model, backup) nằm trên một ổ đĩa: **kéo backup về máy định kỳ** bằng `deploy/pull_backups.py`, nếu không mất VPS là mất hết. Có thể bật thêm Automated backup của OVH.
- Mất khóa ssh `~/.ssh/ovh_audio`: SSH bằng mật khẩu đã tắt, vào bằng console KVM hoặc rescue mode của OVH.

### D9. Bẫy khi deploy/chuyển máy (gặp lúc chuyển sang VPS)
- **Script deploy luôn báo "Done" dù cài lỗi:** lệnh từ xa là `cài; dọn`, nên mã thoát là của bước dọn. Đã sửa thành `cài; status=$?; dọn; exit $status` ở cả hai script. Mọi lần deploy trước 2026-10-11 có thể đã lỗi âm thầm.
- **`vm-install.sh` dừng âm thầm** khi file secrets thiếu một khóa: `set -euo pipefail` + `VAR=$(grep ...)` không khớp. Hàm `get` phải có `|| true`.
- **`gcloud compute scp` trên Windows (pscp) không hiểu `~`:** dùng đường dẫn tương đối với home (`instance:migrate.tgz`).
- **Tên tệp model bắt đầu bằng dấu chấm** (`.gitattributes` trong bộ ASR) là tệp thật app sẽ xin; bộ kiểm tra tên trong `files.py` phải cho phép (có test đối chiếu `asr_models.json`).
- **Quyền thư mục backup:** `chmod 0750` xóa bit setgid, làm thư mục con mất nhóm `ubuntu` và `pull_backups.py` không đọc được. Dùng `0o2750`; tệp lưu trữ báo cáo phải `0640` (mkstemp tạo `0600`).
- **Cài thử trên máy mới để lại dữ liệu thử:** gateway cài thử sẽ tạo báo cáo tháng từ DB thử vào `BACKUP_DIR/reports` và không bao giờ ghi đè. Xóa `reports/` thử sau khi cắt chuyển.

## E. Môi trường dev / công cụ

- **Python text-mode trên Windows** đổi LF thành CRLF; các repo dùng autocrlf. Dùng `newline="\n"` khi cần byte chính xác (ví dụ file được hash hoặc ký).
- **Heredoc dài trong shell** với nhiều dấu nháy dễ vỡ; ghi script ra file rồi chạy.
- **Test admin/payments** cần gói `payos`: chạy bằng venv của gateway (`billing-gateway\.venv`). `test_platform` cần numpy, thiếu ở env không liên quan.
- **Next.js** là bản có breaking changes: đọc `node_modules/next/dist/docs/` trước khi sửa. Đừng chạy `next build` đè lên `.next` của dev server đang chạy.
- **Không sửa** `FunASR-main`, `VieNeu-TTS-main`, `yt-dlp-master`.
- Không xóa `data/tmp`, `data/results`, model weights khi chưa hỏi; không tác động workflow đang chạy.
- Khi test Gemini thật: đọc khóa từ `.env` trong script, **không in ra**; dùng bản sao dữ liệu trong thư mục tạm, không đụng `data/tmp`.
