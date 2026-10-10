# ARCHITECTURE — Kiến trúc và tính năng hiện hành

Mô tả **trạng thái hiện tại** của hệ thống, không ghi lịch sử sửa lỗi. Lỗi dễ tái phát: `PITFALLS.md`. Build, deploy, vận hành: `RUNBOOK.md`. Chi tiết sâu từng phần: `audio-translates/docs/` (mục lục `docs/README.md`).

Nguồn: `Agent.md`, `audio-translates/docs/*`, `Doc-Admin.md`, memory, tổng hợp 2026-10-10. Số liệu đo thật nằm trong docs chi tiết; tài liệu này chỉ nêu kết luận. Chưa đối chiếu lại từng dòng mã nguồn.

## 1. Sản phẩm

Ứng dụng Windows chạy offline trên máy khách: tải audio (YouTube hoặc file tiếng Trung) → chép lời tiếng Trung → dịch sang tiếng Việt → kiểm duyệt bằng luật thay thế → tạo giọng đọc. Bán theo license gắn máy, hai gói:

| Gói | Khác biệt |
|---|---|
| **Plus** | Tạo giọng ngay trên máy (VieNeu TTS). Bộ cài ≈ 0,6 GB |
| **Basic** | Tạo giọng qua gateway trên VM; dừng ở `AWAITING_REVIEW` trước TTS trừ khi bật ô Auto. Bộ cài không có VieNeu |

Cả hai gói đều xem/tải bản tiếng Trung. Dịch có hai chế độ: chạy máy (Hy-MT2-7B) hoặc **Genius** (Gemini qua gateway, tính phí).

## 2. Các thành phần và vị trí

Gốc: `C:\Workspace\Audio-translate`. Mỗi thư mục dưới đây là một repo git riêng (gốc không phải repo).

| Thư mục | Repo GitHub (ArsNeonci/) | Vai trò |
|---|---|---|
| `audio-translates/` | `audio-translate-studio` (nhánh `main`) | **App**: Next.js 16 (UI + API) + `worker/` Python (pipeline AI) + `security-core/` Rust + `packaging/` (build bộ cài) |
| `billing-gateway/` | `billing-gateway` (`master`) | Gateway trên VM: Genius, TTS, thanh toán payOS, cổng Billing, lease, link tải model, kênh cập nhật yt-dlp |
| `admin-system/` | `admin-system` (`master`) | Admin cấp license/lease/giá. **Đang chạy online** trên VM. Bị `.gitignore` ở gốc |
| `shared-license-sdk/` | `shared-license-sdk` (`master`) | SDK license/lease dùng chung |
| `FunASR-main/`, `VieNeu-TTS-main/`, `yt-dlp-master/` | upstream | Không sửa. VieNeu nạp qua `VIENEU_SOURCE` |
| `.tools/rust` | — | Bộ Rust riêng để build `security-core` (không có trên PATH). Bị git ignore |
| `.env` (gốc) | — | Khóa/bí mật (GEMINI, PAYOS, GATEWAY_ADMIN_TOKEN, LEASE_MASTER_KEY). Không commit, không in ra |

Hạ tầng ngoài:

| Thành phần | Chi tiết |
|---|---|
| VPS OVH `vps-6629050b` (`15.235.207.5`) | Từ 2026-10-11. VPS-1: 2 vCPU, 4 GB RAM (+2 GB swap), 40 GB, Singapore, Ubuntu 24.04. Chạy gateway (`127.0.0.1:8790`, 1 worker TTS × 2 luồng, ~51 giây/1000 ký tự), admin (`127.0.0.1:8787`) và cloudflared. Không mở cổng nào ngoài SSH (chỉ khóa). Vào bằng `ssh -i ~/.ssh/ovh_audio ubuntu@15.235.207.5`. VM GCP cũ đã tắt dịch vụ, chủ dự án tự xóa |
| Tên miền (Cloudflare Tunnel) | `audio-gateway.arsneonci.space` (API, app khách gọi), `billing.arsneonci.space` (cổng khách + webhook payOS), `admin.arsneonci.space` (admin, sau Cloudflare Access) |
| Model trên VPS `/var/lib/audio-gateway/files` (`MODEL_DIR`) | Model dịch, 21 tệp model ASR, `youtube/manifest.json(.sig)` + wheel yt-dlp. Gateway tự phát qua `https://audio-gateway.arsneonci.space/files/...` bằng link HMAC 1 giờ (hỗ trợ tải nối), chỉ cấp cho license hợp lệ |
| Sao lưu `/var/backups/audio-gateway`, `/var/backups/audio-admin` (`BACKUP_DIR`) | Hằng ngày 03:00/03:30 giờ VN + báo cáo tháng; tự dọn 35 ngày (daily) / 180 ngày (weekly). Bản ngoài máy: `billing-gateway/deploy/pull_backups.py` kéo về `C:\Users\Linh\audio-translate-backups` (chạy tay; lịch sử bucket cũ ở `gcp-bucket-archive/`) |
| payOS | Thanh toán VietQR; webhook đã đăng ký |

## 3. Pipeline xử lý

`DOWNLOAD → TRANSCRIPTION (1/4 VAD, 2/4 chia đoạn, 3/4 nhận dạng, 4/4 ghép + dấu câu) → TRANSLATION → MODERATION → (duyệt, chỉ Basic) → TTS`

Danh sách bước: `worker/audio_translate/core/errors.py: STEPS`. Mỗi stage AI chạy trong subprocess riêng. Có checkpoint, pause/continue/retry/cancel và cổng license ở mỗi bước. Hỗ trợ nhiều workflow cùng lúc (`docs/MULTI_WORKFLOW_SCHEDULER.md`). Ở khoảng 4 GiB RAM, chạy tuần tự nhanh hơn song song.

| Stage | Công nghệ | Điều chỉnh tài nguyên |
|---|---|---|
| DOWNLOAD | yt-dlp, thứ tự client lấy từ manifest ký; hoặc nhận file audio (WAV, MP3, M4A, FLAC, OGG, AAC, WEBM, MP4, ≤ 2 GB) | Xem mục 6 |
| TRANSCRIPTION 3/4 | FunASR paraformer-zh, pool worker | **Benchmark** (luồng 4/6/8, thử 2 worker), cache 7 ngày |
| TRANSLATION | **Hy-MT2-7B Q4_K_M GGUF** qua `llama-server` nhiều slot; hoặc Genius (Gemini qua gateway) | **Không benchmark**: bắt đầu 1 slot, theo dõi RAM/CPU/GPU/nhiệt mỗi giây, tăng slot sau 10 giây khỏe, giảm khi áp lực |
| MODERATION | Luật thay thế literal (`moderation/rules.py`); sửa xưng hô (`moderation/address.py`) | Không cần |
| TTS | VieNeu v3turbo, pool worker (Plus) hoặc gateway `/v1/tts` (Basic, đoạn 1.200 ký tự, FLAC) | Benchmark RTF, cache 7 ngày |

Trước TTS luôn chạy `tts/voice_check.py`: xóa chữ Hán/kana/hangul sót, dòng rỗng thành "…" (tránh trả tiền cho âm thanh hỏng).

**Tăng/giảm song song theo hiệu quả đo được** (`core/scaling.py`, dùng chung cho TTS worker và Translation slot): +1 sau 10 giây ổn định, giữ nếu ký tự/giây tăng, nếu không thì gỡ và chặn mức đó 10 phút.

### Ngưỡng tài nguyên (sửa ở `worker/config/*.json`)

| Stage | Giá trị đang áp dụng |
|---|---|
| ASR (`asr-memory.json`) | Khởi động 3,0 GiB trống, +2,0 GiB mỗi worker, dự phòng 1,5 GiB. Thực đo ASR X1 ≈ 5,17 GiB RSS đỉnh nên ngưỡng tĩnh thấp hơn thực tế |
| Translation 7B (`translation-runtime.json`) | Khởi động 6 GiB, giữ 1 GiB, slot thêm 0,35 GiB; KV `q8_0` 0,32 GiB/slot; 2–3 slot đỉnh ≈ +5,28 GiB; luôn chừa 2 GiB cho hệ thống |
| TTS (`tts-runtime.json`) | Dự phòng 1,5 GiB, +10% tối thiểu mới thêm worker |

CPU/GPU: Settings lưu `data/settings/compute.json`; mỗi job đóng băng `compute_device` ở lần chạy đầu. **GPU chưa dùng được an toàn** (ASR GPU bỏ qua calibrate/pool/VRAM, TTS GPU dùng heuristic CPU, Translation GPU cần `llama-server` CUDA; máy dev có RTX 3050 4 GB nhưng `.venv` cài `torch +cpu`). Xem `docs/CALIBRATION_REVIEW.md`.

## 4. Dịch và chất lượng văn bản

- **Prompt** zh→vi không kèm ngữ cảnh dài (dòng phụ đề rất ngắn, trung vị 9 ký tự), ngân sách token `48 + 6 × ký tự`, 3 lượt đổi chỉ dẫn/nhiệt độ/seed (`natural` → `conversational` → `literal`), cách ly dòng lỗi (dừng nếu 5 dòng lỗi liên tiếp). Có kiểm tra `độ dài > max(80, 12 × ký tự nguồn)` để bắt bản dịch lạc.
- **Dịch theo câu** (gom dòng tới hết câu, thẻ `<sN>`, tách lại theo timestamp, lùi về từng dòng nếu lệch thẻ) + **glossary tên Hán-Việt theo job** (`translation/names.py`, `working/name-glossary.json`, sửa tay được).
- **Checkpoint từng đoạn**, hàng đợi hữu hạn, Continue theo đoạn lỗi (`docs/TRANSLATION_CHECKPOINTS.md`). Khóa checkpoint giữ nguyên để Resume không mất dòng đã dịch.
- Mẫu chat Hy-MT2-7B là Hunyuan (`<|startoftext|>…<|extra_0|>`, dừng `<|eos|>`), tự nhận từ GGUF. Job cũ tự chuyển model khi SHA khác.
- **Kiểu giọng** (Mặc định/Drama/Sinh tồn/Trọng sinh): giọng gợi ý, gộp câu, tốc độ atempo, khoảng nghỉ (`docs/VOICE_STYLES.md`).
- **Xưng hô theo thể loại** (`docs/ADDRESS_FORMS.md`): L0 `address-profiles.json`, L1 bảng nhân vật `working/characters.json` (sửa ở trang Reprocess), L2 sửa đại từ ở đầu Moderation. Cộng thêm sửa 他/她 trên bản tiếng Trung (chỉ khi chắc), `genre-lexicon.json`, kiểm tra giới tính khi dịch. Chỉ áp dụng cho job có Kiểu giọng; profile Trung tính giữ hành vi cũ.
- **Làm sạch bản tiếng Trung** (`source-cleanup.json`): cắt lời quảng cáo kênh, sửa lỗi ASR đã gặp.
- **Genius** (`translation/genius.py` → gateway `/v1`): Gemini 2.5 Flash có suy nghĩ bật (rẻ hơn khi tắt 3,6 lần nhưng sai giới tính/từ). Vòng sửa lỗi tối đa 3 lần; dòng vẫn lỗi thì gắn cờ và **không tính tiền**.
- **Tools** (`docs/TOOLS.md`): Tool 1 nhận link YouTube hoặc file, Tool 2 có Forms of address, Tool History xóa được khi đang chạy; dùng chung bộ phân luồng.

## 5. Bảo mật và license

Mô hình: không tin mã Python/Node trên máy khách; quyết định cấp phép nằm ở lõi native và server.

- **`security-core` (Rust)**: chạy như **Windows Service + Named Pipe** (ACL IU/SY/BA, từ chối remote, khung 64 KiB, allowlist action, chỉ crate `windows-sys`, build offline). Xác minh license Ed25519, Machine ID, DPAPI, trạng thái chống lùi đồng hồ (dung sai `CLOCK_SKEW_SECONDS` = 5 phút), `payload.manifest.json` ký bằng **khóa manifest riêng** (integrity: install = toàn bộ; runtime = binary + config + payload, không hash model).
- **Launcher** hỏi service trước khi spawn worker; tắt service thì workflow bị chặn (`SECURITY_SERVICE_UNAVAILABLE`). Cờ build `dev_fallback` chỉ có ở bản dev.
- **Lease**: do admin/gateway ký (domain `machine-lease-v1`), mang **content key gói riêng cho máy** (ECIES X25519 → HKDF-SHA256 → AES-256-GCM). Thời hạn lease 1–90 ngày, ân hạn offline 0–30 ngày, đặt ở server. Bản release **bỏ khóa nhúng**, bắt buộc có lease (`LEASE_REQUIRED`, `LICENSE_EXPIRED`). Mỗi phiên bản app có **content key riêng**; có thể ngừng hỗ trợ bản cũ (`retire_version`). Thu hồi có hiệu lực ngay.
- **Gateway** giữ khóa ký lease riêng (domain `product-lease-key-v1`, không ký được license) và mã hóa tài liệu khi lưu bằng `LEASE_MASTER_KEY`. Thiếu key này thì dịch vụ lease tắt.
- **Vault**: các cấu hình/prompt/danh sách tên được mã hóa và nạp qua content key của service (gate integrity + license). Nuitka compile một số module.
- **Phase 3** (đã code, một phần cần chứng chỉ): xác minh tiến trình trên pipe, anti-debug, quét secret cuối build, hook Authenticode, build theo khách. **Bản "phát hành cứng"** (`AUDIO_RELEASE_HARDENED=1`) cần chứng chỉ `.pfx` và khóa chữ ký payload; **chưa thiết lập**. Rủi ro còn lại: kẻ có quyền admin trên máy khách sửa binary dịch vụ, và ai có root trên VPS đọc được master key (chỉ lấy được khóa ký lease).

Quy ước giữ ổn định: **không đổi tên hoặc di chuyển 7 shim ở `worker/`** (`manage`, `retry`, `orchestrator`, `rules`, `results`, `youtube_session`, `compute_settings`). Allowlist của security-core (Rust) và `lib/server/worker-client.ts` gọi theo tên; đổi thì phải build lại Rust và tăng version.

## 6. Tải YouTube

Chi tiết: `docs/YOUTUBE_DOWNLOAD.md`. Kết luận kiến trúc: **tải từ IP nhà khách**, không tải hộ qua server (IP GCP bị chặn 12/12 lượt, kèm rủi ro pháp lý và băng thông).

- **Thứ tự client** (`transcription/pipeline.py: download`): mặc định ẩn danh → mweb ẩn danh → mặc định + cookie phiên Edge đã kết nối (hoặc `YTDLP_COOKIES_FILE`) → mweb + cookie → tv + cookie. Dừng ngay khi lỗi mà client khác không cứu được (429, riêng tư, đã gỡ, hội viên, chưa phát, bản quyền). Mọi lần thử ghi vào `working/download-attempts.json`.
- **Kênh cập nhật yt-dlp có chữ ký**: app gọi gateway `POST /v1/youtube/update`; gateway trả manifest Ed25519 + link ký các wheel `yt-dlp` và `yt-dlp-ejs` từ `MODEL_DIR` trên VPS. App chỉ nhận khi khớp khóa công khai ghim trong `worker/config/youtube-update-keys.json`, `serial` không lùi, SHA-256 và kích thước đúng. Cài vào `%LOCALAPPDATA%\AudioTranslate\data\ytdlp\releases\<serial>\`. Hỏng hết thì app hỏi gateway ngay (tối đa 15 phút một lần).
- **Phiên YouTube** là hồ sơ Edge riêng của app; Edge ẩn chạy trong Windows Job Object `KILL_ON_JOB_CLOSE`, dọn bằng `browser_cleanup.py`.
- **Dự phòng cuối**: người dùng nạp file audio tiếng Trung. File đó là bản duy nhất (`source_upload`), Rerun bước Tải không xóa nó.
- Audio gốc được xuất thành kết quả `SOURCE_AUDIO` của bước Tải, hiện ở trang Lịch sử và thẻ Studio.

## 7. Model tải sau khi cài

Windows không chạy `.exe` > 4 GiB, nên **bộ cài không chứa model dịch** (4,6 GB). Luồng (`docs/MODEL_DOWNLOAD.md`): sau khi kích hoạt, app gọi gateway `POST /v1/model/url` → link ký V4 1 giờ (license hợp lệ, **12 link/ngày/license**) → tải vào `.part`, tiếp tục bằng Range, so SHA-256 ghim sẵn mới đổi tên. Model nhận dạng giọng nói (3 mô hình, 2,04 GB, 21 tệp) cùng cơ chế (`transcription/model_prefetch.py`, `asr-models.json`), có dự phòng ModelScope.

## 8. Thanh toán và Billing

Chi tiết: `docs/PLAN_PAYMENTS_PAYOS.md` (mục 15 = hiện trạng), `docs/ADMIN_ACTIONS.md`, `Doc-Admin.md`.

- **Khóa ký license nằm ở admin**, không ở gateway. Khi payOS báo đã trả, admin (nay chạy trên VM, `ADMIN_FULFILLMENT=on`) ký gia hạn ngay. Kích hoạt lần đầu vẫn thủ công. Gia hạn **cộng dồn**: hạn mới = max(bây giờ, hạn hiện tại) + số ngày; lõi app bắt buộc nhập token đúng thứ tự `sequence`.
- **Dịch vụ tính phí là ghi nợ** (Genius, TTS), một sổ nợ cho mỗi khách × app; **hạn mức nợ mặc định 0** nên khách mới chưa dùng được dịch vụ trả phí cho tới khi đặt hạn mức. Giá và hạn mức sửa ở dạng nháp, chỉ áp dụng khi bấm Lưu. Giá trị demo: 1.000đ/ngày, gói tháng 2.000đ, dịch 2.000đ và giọng 1.000đ mỗi 1.000 ký tự.
- **Cổng Billing** (`billing.arsneonci.space`): phiên một lần từ app khi license còn hạn; **Mã khách hàng** (10 ký tự Crockford base32) cho license đã hết hạn, vì lõi bảo mật từ chối cấp token license hết hạn (chủ ý không sửa). Token trên trang đơn chỉ hiện cho phiên đã tạo đơn.
- Webhook payOS: chữ ký đúng → 200, giả → 400. Đối soát theo mã đơn. Dữ liệu cũ được gộp rồi xóa theo hạn giữ (180 ngày job, 24 giờ chi tiết đoạn, 30 ngày chi phí nội bộ, 90 ngày sự kiện lease), nợ không đổi.
- Thêm app mới vào nền tảng: khai báo khối `gateway` trong `product.manifest.json`, đăng ký ở admin, thêm service ở gateway (`Doc-Admin.md`).

## 9. Admin online

Admin chạy liên tục trên VPS sau **Cloudflare Access** (quản lý ở giao diện Cloudflare, không còn trong Terraform state). Bản trên PC đã **đóng băng** (`AUTHORITY_MOVED`) để không có hai nơi cùng cấp license. Admin tự kiểm lại JWT của Access và `ADMIN_EMAILS` (đóng khi lỗi). Master key = 64 hex ở `/etc/audio-admin/master.key`; khóa ký trong DB được mã hóa bằng nó. Máy build dùng service token và `ADMIN_REMOTE_URL` (chỉ `/api/build/*`). Người dùng chấp nhận rủi ro: khóa ký nằm trên server nên nếu lộ thì không thu hồi được. **Không đặt Access lên `billing.*` hay `audio-gateway.*`** (sẽ chặn payOS và app khách).

## 10. Bố cục mã nguồn app

- Frontend: `app/` chỉ chứa route (38 route); `components/<feature>/`; `lib/{server,i18n,theme,shared}/`; import qua alias `@/`. Next.js ở đây là bản có breaking changes: đọc `node_modules/next/dist/docs/` trước khi sửa.
- Worker: `worker/audio_translate/{core,workflow,transcription,translation,tts,moderation}/`; `worker/config/` (JSON cấu hình), `worker/tools/` (được đóng gói), `worker/dev/` và `worker/tests/` (không đóng gói).
- Edition: tier lấy từ mã sản phẩm biên dịch trong security-core (`identity.tier`); `worker/core/edition.py`, `lib/server/edition.ts`; manifest từng gói ở `products/`.
- Dữ liệu người dùng khi đã cài: `%LOCALAPPDATA%\AudioTranslate` (kích hoạt, kết quả, model đã tải), nằm ngoài thư mục cài nên giữ qua cập nhật. Lưu bằng file + SQLite registry.
- Điểm gắn GPU nếu làm tiếp: `core/compute_settings.py`, `transcription/asr_runtime.py`, `translation/translation_server.py`, `tts/adapters.py`, `tts/tts_runtime.py`.

## 11. Việc chưa làm (tính đến 2026-10-10)

- Cài tác vụ Windows `AudioTranslateRenewalWorker` (ngoài ra gia hạn chỉ được ký khi admin online; admin trên VPS đã ký nên mức ưu tiên thấp hơn, kiểm lại).
- **Chưa có giao dịch tiền thật** từ đầu đến cuối (cách thử: `docs/PLAN_PAYMENTS_PAYOS.md` mục 15.4).
- Chưa thử tải model đầy đủ từ app với license thật đã kích hoạt; chưa thử lời gọi cập nhật yt-dlp bằng license thật.
- Chưa đặt hạn mức nợ cho khách; chưa cài installer thử trên máy Windows thứ hai.
- Bản phát hành cứng (chứng chỉ ký mã, khóa chữ ký payload, `release_config.py` chưa ghi `manifest_public_key`).
- GPU chưa an toàn (mục 3). `worker/dev/verify_notice.cjs` hỏng từ trước (thiếu mock `useLanguage`).
- Chưa chạy Reprocess một workflow thật đầy đủ với Kiểu giọng, xưng hô và Hy-MT2-7B mới.
