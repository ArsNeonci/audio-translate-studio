# Agent.md — Trạng thái Project (cập nhật 2026-10-04)

## 0. BẮT ĐẦU NHANH (đọc phần này trước, rồi dừng nếu chỉ cần nắm bức tranh)

Dự án có thể đã bỏ lâu. Đừng quét source code và đừng đọc cả file này. Đọc theo thứ tự:

1. `Document/ARCHITECTURE.md`: hệ thống gồm gì, chạy ở đâu, mỗi tính năng hoạt động ra sao, việc chưa làm. Đây là nguồn chuẩn về **trạng thái hiện tại**.
2. `Document/PITFALLS.md`: các lỗi và bẫy đã gặp, nguyên nhân gốc, cách tránh. Đọc **trước khi** sửa phần tải YouTube, build/phát hành, model, license, thanh toán.
3. `Document/RUNBOOK.md`: lệnh chạy, test, build, deploy, phát hành cập nhật yt-dlp, thao tác admin, quy ước làm việc.
4. Cần chi tiết sâu một phần: `audio-translates/docs/README.md` là mục lục (mỗi tài liệu một chủ đề). Tra đó trước khi tìm trong mã.

Quy tắc dùng và giữ các tài liệu này:
- Ba file trong `Document/` mô tả **trạng thái hiện tại**, không ghi nhật ký sửa lỗi. Khi sửa xong một lỗi: nếu nguyên nhân không hiển nhiên hoặc có thể tái phát thì thêm/cập nhật một mục trong `PITFALLS.md` (triệu chứng, nguyên nhân gốc, cách tránh); còn lại thì chỉ ghi vào git commit. Khi đổi kiến trúc hoặc tính năng thì sửa thẳng `ARCHITECTURE.md` (ghi trạng thái mới, không ghi "trước đây là...").
- Phần còn lại của file này (mục 1 trở xuống) là **lịch sử và nhật ký làm việc** từ 2026-10-04, có chỗ đã cũ (ví dụ số test, trạng thái "chưa commit", "chưa chuyển admin"). Khi mâu thuẫn với `Document/`, tin `Document/` và kiểm lại bằng mã hoặc git.
- Gốc `C:\Workspace\Audio-translate` **không phải repo git**. Bốn repo riêng: `audio-translates/` (app, nhánh `main`), `billing-gateway/`, `admin-system/`, `shared-license-sdk/` (nhánh `master`). `Agent.md` và `Document/` nằm ở gốc nên không nằm trong repo nào, trừ khi đã được chép vào một repo (xem trạng thái ở cuối mục này).
- Khóa và bí mật: không bao giờ in ra, không commit. Vị trí: `.env` ở gốc, `C:\Users\Linh\audio-translate-keys\`, `C:\Users\Linh\.audio-translate\`.
- Ngôn ngữ làm việc với chủ dự án: tiếng Việt, ngắn gọn; tách phần đã kiểm chứng và chưa kiểm chứng.

Tài liệu bàn giao cho agent làm việc sau. Nguồn: mã nguồn hiện tại, `audio-translates/docs/*.md`, 7 phiên Codex gần nhất (2026-10-02 → 10-04) và các phiên Claude Code cùng ngày. Không thay thế docs chi tiết; xem mục "Bản đồ tài liệu".

## 1. Tổng quan

Ứng dụng Windows offline: tải video/audio (YouTube hoặc file), chép lời tiếng Trung, dịch sang tiếng Việt, kiểm duyệt bằng luật thay thế, tạo giọng đọc (VieNeu TTS). Đóng gói thành installer có license gắn máy.

| Thư mục (gốc `C:\Workspace\Audio-translate`) | Vai trò |
|---|---|
| `audio-translates/` | **App chính** và là repo git duy nhất của sản phẩm. Next.js 16 (UI + API) và `worker/` Python (pipeline AI) |
| `audio-translates/docs/` | Toàn bộ tài liệu kỹ thuật (đã gom về đây; `worker/docs/` đang trống) |
| `admin-system/`, `shared-license-sdk/` | Admin cấp license (ngoài repo sản phẩm, bị git ignore), SDK license dùng chung |
| `FunASR-main/`, `VieNeu-TTS-main/`, `yt-dlp-master/` | Upstream, không sửa. VieNeu được import qua `VIENEU_SOURCE` |
| `audio-translates/docs/{External-product,CV_PROJECT_EVIDENCE,SECURITY_PHASE_1_RESULT}.md` | Prompt đăng ký sản phẩm ngoài, bằng chứng CV, báo cáo bảo mật phase 1 |

Máy dev: Windows 11, GPU RTX 3050 Laptop, nhưng `.venv` cài `torch +cpu` nên **mọi workflow chạy CPU**. Dev server chạy ở `http://localhost:3000`.

## 2. Pipeline và thiết bị

`DOWNLOAD → TRANSCRIPTION (1/4 VAD, 2/4 chia đoạn, 3/4 nhận dạng, 4/4 ghép+dấu câu) → TRANSLATION → MODERATION → TTS`
(`worker/audio_translate/core/errors.py: STEPS`). Mỗi stage AI chạy trong subprocess riêng. Có checkpoint, pause/continue/retry, cancel, license gate.

| Stage | Công nghệ | Điều chỉnh tài nguyên | Chế độ GPU |
|---|---|---|---|
| TRANSCRIPTION 3/4 | FunASR paraformer-zh, pool nhiều worker (`transcription/asr_runtime.py`) | **Benchmark** (luồng 4/6/8, thử 2 worker), cache 7 ngày + kiểm chứng khi chạy | `FUNASR_DEVICE=cuda:0` đi vào `transcribe_serial`: không calibrate, không pool, không kiểm VRAM |
| TRANSLATION | **Hy-MT2-7B Q4_K_M GGUF** qua `llama-server` dùng chung nhiều slot (`translation/hymt_translation.py`, `translation_server.py`) | **Không benchmark.** Bắt đầu 1 slot, quan sát RAM/CPU/GPU/nhiệt mỗi 1 giây, tăng slot sau 10 giây khỏe, giảm khi áp lực | `llama-server` đóng gói chỉ có CPU: GPU dùng `llama-cpp-python` nhúng, 1 slot, trừ khi đặt `HY_MT_SERVER_PATH` (bản CUDA) |
| MODERATION | Luật thay thế literal (`moderation/rules.py`) | Không cần | CPU |
| TTS | VieNeu v3turbo, pool worker (`tts/tts_runtime.py`) | **Benchmark** (RTF), cache 7 ngày, đo lại mỗi 10 phút, cache WAV theo nội dung | `VIENEU_DEVICE=cuda` nhưng vẫn dùng heuristic CPU, không kiểm VRAM |

Chọn CPU/GPU: Settings lưu `data/settings/compute.json`; mỗi job đóng băng `compute_device` ở lần chạy đầu; GPU không tự hạ về CPU (`core/compute_settings.py`, `docs/COMPUTE_SETTINGS.md`).

Ngưỡng tài nguyên (đang áp dụng, sửa trong `worker/config/*.json`):
- ASR: khởi động 3.0 GiB trống, mỗi worker thêm 2.0 GiB, dự phòng song song 1.5 GiB (`asr-memory.json`). Đo thực tế ASR X1 ≈ 5.17 GiB RSS đỉnh, nên ngưỡng tĩnh thấp hơn thực tế.
- Translation: khởi động 3.5 GiB, dự phòng 2 GiB, slot thêm ≥ 0.4 GiB, an toàn 0.4 GiB, CPU/GPU 85%, nhiệt 85°C, 4 luồng (`translation-runtime.json`). 1x đo được ≈ 2.17 GiB, mỗi slot thêm ≈ 0.25 GiB.
- TTS: dự phòng 1.5 GiB, tối thiểu +10% mới thêm worker (`tts-runtime.json`).
- Ràng buộc người dùng: luôn chừa **2 GiB RAM cho hệ thống** ở Translation; không làm ảnh hưởng workflow đang chạy.

## 3. Bố cục mã nguồn (sau tái cấu trúc 2026-10-04)

Chi tiết ở `audio-translates/docs/CLEAN_ARCHITECTURE.md` (mục *Source layout*).

- Frontend: `app/` chỉ chứa route (URL không đổi, 38 route). `components/<feature>/` chứa React component. `lib/{server,i18n,theme,shared}/` chứa logic. Import qua alias `@/`.
- Worker: logic trong `worker/audio_translate/{core,workflow,transcription,translation,tts,moderation}/`.
  Ở `worker/` chỉ có 7 shim (`manage`, `retry`, `orchestrator`, `rules`, `results`, `youtube_session`, `compute_settings`).
  **Không đổi tên/di chuyển shim:** allowlist của security-core (Rust, `main.rs`) và `lib/server/worker-client.ts` gọi theo tên. Đổi phải build lại Rust và tăng version.
- `worker/config/` (3 JSON), `worker/tools/` (script cài đặt, được đóng gói), `worker/dev/` và `worker/tests/` (không đóng gói).
- Điểm gắn GPU nếu làm tiếp: `core/compute_settings.py`, `transcription/asr_runtime.py`, `translation/translation_server.py`, `tts/adapters.py`, `tts/tts_runtime.py`.

## 4. Trạng thái hiện tại

Kiểm tra gần nhất (2026-10-04):
- Python: `python -m unittest discover -s worker/tests -t worker -p "test_*.py"` → **287 test pass, 1 bỏ qua** (2026-10-05; trước đó 5 test viết theo ngưỡng RAM cũ, đã sửa).
- `tsc --noEmit`, eslint, `check:i18n`, `check:theme`: sạch. `next build`: đủ 38 route. `packaging/test_security_phase1.py`: 8/8 (chạy trước khi Codex đổi sang Hy-MT2, chưa chạy lại).
- Test localhost:3000: mọi trang GET và API đọc trả 200; CRUD rules, đọc voices/history đi qua security-core → worker thành công.
- **Chưa** build installer sau thay đổi; chưa chạy job thật từ đầu đến cuối sau tái cấu trúc; chưa thử trên máy Windows thứ hai.
- Cây git `audio-translates/` đang có ~141 đường dẫn thay đổi chưa commit (gồm tái cấu trúc, gom docs về `docs/`, chuyển Qwen sang Hy-MT2).

## 5. Vấn đề đang mở (ưu tiên)

0. **Admin online (2026-10-07): ĐANG CHẠY tại https://admin.arsneonci.space, dữ liệu đã chuyển, bản trên PC đã đóng băng.** Access app do giao diện Cloudflare quản lý (đã `terraform state rm`); máy build dùng biến môi trường `ADMIN_REMOTE_URL` + service token. Phần dưới là lịch sử: `admin-system/run.py --server` chạy trên VM (tài khoản `audio-admin`, `127.0.0.1:8787`) sau Cloudflare Access: từ chối mọi yêu cầu cho tới khi có `ACCESS_TEAM_DOMAIN` + `ACCESS_AUD`; khóa mã hóa bằng master key 64 hex (người dùng chọn phương án file mã hóa trên VM, không phải KMS); vòng ký tự động chỉ chạy khi `ADMIN_FULFILLMENT=on`. Thiếu: người dùng tạo ứng dụng Access (hướng dẫn trong `audio-translates/docs/ADMIN_ONLINE.md` mục 3), thêm `admin_hostname` vào Terraform tunnel, rồi chạy `migrate_to_server.py --freeze-to` và `deploy/deploy_admin.py --db ... --replace-db` (mục 5). Sau khi chuyển, bản admin trên máy bị đóng băng (`AUTHORITY_MOVED`) và máy build dùng `ADMIN_REMOTE_URL` + service token. Test: admin 9 + 8 + 7 mới. Chưa commit.
0. **Thanh toán payOS / cổng Billing (2026-10-07): đã triển khai, chờ thử bằng một giao dịch thật.** Thiết kế + trạng thái: `audio-translates/docs/PLAN_PAYMENTS_PAYOS.md` (mục 15). Gateway chạy trên VM GCP `instance-20261006-200055` (Spot, kết thúc = STOP) với hai tên miền: `audio-gateway.arsneonci.space` (API/admin) và `billing.arsneonci.space` (cổng khách + webhook payOS, đã đăng ký). Sao lưu hằng ngày + báo cáo tháng lên `gs://audio-gateway-backup-erp-project-8386`. Admin: trang Payments (bảng giá/hạn mức có nháp, đơn, gia hạn, đối soát, báo cáo), `fulfillment.py` + `renewal_worker.py` (ký gia hạn ngay khi tiền về); app và sản phẩm khai báo app qua khối `gateway` trong `product.manifest.json`. Bảng giá demo đã lưu (1.000đ/ngày, gói tháng 2.000đ). Test: gateway 80 (`billing-gateway/.venv`), admin 46 + 16 (cần `payos`), `node test_payments_ui.cjs`, app `npm run check:billing`. **Chưa làm:** cài tác vụ Windows renewal worker, build installer app mới, đặt hạn mức nợ, giao dịch tiền thật. Lõi bảo mật không lấy được token license hết hạn (không có `cargo` để sửa) nên license hết hạn đi qua Mã khách hàng + dán token tay. Chưa commit trong cả 3 repo.
0. **Bảo mật Phase 2 — 2A+2B+2C+6b đã code & test local (2026-10-06, Claude Code).** Branch `security-phase-2` ở `audio-translates` (chưa push); server `admin-system`/`billing-gateway`/`shared-license-sdk` giờ là repo git riêng (mỗi repo 1 snapshot + commit 2C; secret/DB/key bị gitignore). Xem `docs/SECURITY_PHASE_2_RESULT.md`.
   - **2C+6b (mới):** lease ngắn hạn (mặc định 7 ngày) do admin ký (domain `machine-lease-v1`), mang content key **gói cho máy** bằng ECIES X25519→HKDF-SHA256→AES-256-GCM; service giữ machine X25519 keypair (DPAPI), giải key chỉ trong RAM (`security-core/src/lease.rs`, action `machine_pubkey`/`install_lease`; `content_key` ưu tiên lease hơn key nhúng). Rollback: counter lùi → `SECURE_STATE_INVALID`; grace offline `GRACE_SECONDS` (3 ngày) rồi `LICENSE_EXPIRED`. Admin `core.py`: `issue_lease`, content key/sản phẩm (`content_keys`), `evaluate_request` (đánh giá theo **giờ server**), `revoke/restore`, `events` (chỉ id/máy/loại, **không** nội dung người dùng), `_suspicious` (≥5 từ chối/60 phút). Gateway: `POST /v1/lease` + `guard` chặn work request hết hạn/thu hồi. ModelVault (`core/model_vault.py`) interface cho model riêng (không mã hóa model public). Canary: core ghi tamper vào `security-events.log` cục bộ.
   - **Test 2C/6b:** cross-language lease (Python ký+wrap ↔ Rust install+unwrap, rollback, hết hạn); admin `test_lease.py` 6/6; admin cũ 28/28; gateway `test_lease_gateway.py` 4/4 + `test_gateway.py` 13/13 (`test_platform` cần numpy — thiếu ở env, không liên quan).
   - **Bản crack không liên lạc server:** chỉ bị chặn khi lease hết hạn (sau grace); online thì token bất thường bị phát hiện và có thể thu hồi.
   - **Tự gia hạn + khóa cứng (2026-10-07):** app tự xin lease khi mở trang, sau kích hoạt/gia hạn license và trước mỗi lần cho chạy (`lib/server/lease.ts`; gia hạn khi đã qua nửa hạn lease). Ân hạn offline **cấu hình được** và nằm trong lease do server ký (admin đặt hạn lease 1–90 ngày, ân hạn 0–30 ngày; máy khách không đổi được). Bản release **bỏ chìa khóa nhúng**, bắt buộc có lease (`LEASE_REQUIRED` / `LICENSE_EXPIRED`) nên xóa lease cũng không mở khóa; hết hạn lease + ân hạn là khóa kể cả bản crack chỉ sửa Python. Thu hồi có hiệu lực ngay (`lease_revoke`), chép lại lease cũ không gỡ được. Gateway tự cấp lease (`billing-gateway/lease_authority.py`; admin đẩy khóa ký + content key qua kênh admin, thu hồi/khôi phục, xem sự kiện, tùy chọn auto-revoke); admin `billing.py` + `run.py` có API, chưa có màn hình. Test: Rust 13, `test_security_phase2` 10, gateway 8+13, admin lease 8 + link 3, worker 315. Chi tiết và rủi ro: cuối `docs/SECURITY_PHASE_2_RESULT.md`. **Khắc phục rủi ro mới (2026-10-07):** mỗi bản phát hành có **content key riêng** (`export_build_keys.py` tạo khi build; app gửi `app_version` khi xin lease; có thể **ngừng hỗ trợ** bản cũ bằng `retire_version` / `/api/billing/retire-version`); gateway giữ **khóa ký lease riêng** (domain `product-lease-key-v1`, không thể ký license) và **mã hóa tài liệu khi lưu** bằng `LEASE_MASTER_KEY` (đặt trong `gateway.env`, thiếu thì dịch vụ lease tắt). Quy trình phát hành: xuất key theo phiên bản (file ngoài repo) → `AUDIO_CONTENT_KEY_FILE` → tăng version → build → đẩy lease material. Còn mở: bản crack sửa cả binary dịch vụ (cần Authenticode, Phase 3); ai có root trên VPS vẫn đọc được master key (nhưng chỉ lấy được khóa ký lease, không giả license được).

0b. **Bảo mật Phase 2A/2B (2026-10-06, Claude Code).** Xem `docs/SECURITY_PHASE_2_RESULT.md`.
   - **Đã làm & test:** security-core thành Windows Service + Named Pipe IPC (ACL IU/SY/BA, từ chối remote, framing 64 KiB, allowlist action, chỉ `windows-sys`, build offline); launcher hỏi service authorize trước khi spawn worker → tắt service thì workflow bị chặn (`SECURITY_SERVICE_UNAVAILABLE`), dev fallback bằng cờ build `dev_fallback` (release bỏ). `payload.manifest.json` ký Ed25519 **khóa manifest riêng** (nhúng qua `build.rs`, tùy chọn), integrity install=toàn bộ / runtime=binary+config+payload (không hash model). Client Node (`lib/server/security-core.ts`,`license.ts`) + Python (`core/secure_channel.py`,`license_gate.py`) đi pipe, fallback spawn exe. Tamper states + i18n. Tool admin: `packaging/manage_service.ps1`; sinh manifest `packaging/build_manifest.py` (+hook trong `build_installer.py` qua `AUDIO_MANIFEST_KEY_FILE`, core hardened qua `AUDIO_RELEASE_HARDENED=1`).
   - **Test:** Rust 12/12; cross-language Python ký↔Rust verify; `packaging/test_security_phase2.py` 5/5 (integrity, tamper config/binary/manifest, pipe service+authorize, fail-closed khi service tắt dù patch Python — kịch bản 1,5,6,7,8); tsc/eslint/i18n/theme sạch; 315 test worker pass; Phase 1 native 5/5 (workflow thật vẫn chạy qua launcher).
   - **2B:** vault mã hóa tài sản 1–5 (data tách khỏi code → `translation-prompts.json`,`names.json`+3 config, nạp qua service content key — gate integrity+license); Nuitka compile (đã chứng minh: `names.py`→.pyd chạy); hook installer. **Giới hạn:** execution-context per-stage chưa luồn qua orchestrator → máy còn license gọi worker trực tiếp vẫn đọc asset; chốt chặn là lease hết hạn (2C). Test `test_security_phase2.py` (vault round-trip), 315 test worker pass.
   - **Hoãn (cần admin, chỉ chuẩn bị script/hook):** đăng ký service thật, cài Program Files + migrate, smoke installer; kịch bản tamper 7 (service thật), 9/10/11 với 2 máy thật; benchmark overhead khởi động/cấp phép/integrity chưa đo. Máy dev không có quyền admin.
   - **Rủi ro còn lại:** admin có thể dừng service SYSTEM và giả server trên pipe (response chưa ký — Phase 3); launcher exe vẫn được spawn (service kiểm integrity); execution-context per-stage chưa luồn (2B); bản crack offline chỉ chặn khi lease hết hạn.

1. **Translation — đã sửa lỗi lan man prompt (2026-10-04), còn giới hạn chất lượng.**
   - Nguyên nhân gốc (đã đo trên model thật): mỗi dòng phụ đề rất ngắn (trung vị 9 ký tự, 40% ≤ 8 ký tự) nhưng prompt cũ kèm 512 ký tự ngữ cảnh. Model 1.8B dịch luôn đoạn ngữ cảnh (dòng 553, 570: 660–716 token) và lọt nhãn `[Thông tin cơ bản]`; lượt sửa còn nhét bản nháp lỗi vào prompt. Không do chạy song song (lúc lỗi chỉ có 1 slot).
   - Đã làm (Claude Code): prompt zh→xx chính thức không ngữ cảnh, kèm chỉ dẫn văn phong tự nhiên; 3 lượt đổi chỉ dẫn/nhiệt độ/seed (`natural` → `conversational` → `literal`), không đưa bản nháp lỗi vào; ngân sách token `48 + 6 × ký tự`; seed theo hash nội dung; cách ly dòng lỗi để các dòng khác vẫn chạy, dừng nếu 5 dòng lỗi liên tiếp. Khóa checkpoint giữ nguyên nên Resume không mất dòng đã dịch. Chi tiết: `docs/TRANSLATION_CHECKPOINTS.md` (mục Prompt).
   - Kết quả: mỗi dòng 0.5–2 giây (prompt cũ 6–7 giây, dòng lỗi ≈50 giây). Workflow `000007` đã Reprocess từ TRANSLATION: 1048/1048 dòng trong ~12 phút (trước: ~48 phút cho 567 dòng), 4 slot, 0 dòng lỗi, bản dịch dài nhất 154 ký tự.
   - Phát hiện thêm: 12 dòng cache từ prompt cũ (vd dòng 128 `笑死我了。` → 1200 ký tự) là bản dịch lạc sang ngữ cảnh mà bộ lọc cũ không bắt; đã thêm kiểm tra `độ dài > max(80, 12 × ký tự nguồn)` vào `output_problem`.
   - **Bước B đã làm (2026-10-04):** dịch theo câu (gom dòng tới hết câu, thẻ `<sN>`, tách lại theo timestamp, lùi về từng dòng nếu lệch thẻ) và glossary tên Hán-Việt theo job (`translation/names.py`, `working/name-glossary.json`, sửa tay được). Chạy thử 150 dòng thật: 38 nhóm/141 dòng, 0 lần lùi, tên nhất quán. Chi tiết: `docs/TRANSLATION_CHECKPOINTS.md`. Test: 211, đúng 5 lỗi có sẵn.
   - Chưa làm: Reprocess workflow 000007 bằng chế độ mới (chờ người dùng xác nhận và đủ RAM). Với RAM trống ~3.7 GiB, sau khi nạp model còn < 2 GiB dự trữ nên job tự tạm dừng; cần đóng bớt ứng dụng (~1–2 GiB) để chạy và mở thêm slot.
2. **License `CLOCK_ROLLBACK` thoáng qua giữa hai stage — đã sửa 2026-10-04** bằng dung sai 5 phút trong `security-core/src/license.rs` (`CLOCK_SKEW_SECONDS`), core đã build lại; cần tăng version trước khi build installer. Mô tả gốc: `core/storage.py: progress()` gọi `assert_allowed(False)` mỗi dòng, ghi `last_verified_time` = giờ local. Stage kế tiếp kiểm tra online (`security-core/src/main.rs: check`, `trusted_time`) và so giờ internet với mốc đó **không dung sai** (`license.rs: expiration`, `now < last`). Đồng hồ máy nhanh hơn internet ~1 giây là đủ để báo lỗi. Đã gặp ở workflow 000007 (Moderation FAILED ngay sau Translation); Retry MODERATION thì qua. Hướng sửa: thêm dung sai (ví dụ 120 giây) khi so mốc trong Rust (cần build lại security-core, tăng version) và/hoặc chỉ gọi kiểm tra offline trong `progress()` theo chu kỳ thay vì mỗi dòng. Không vượt qua license gate.
3. **Năm test fail có sẵn — đã sửa (2026-10-05):** test `memory_policy` và `workflow_admission` viết theo ngưỡng cũ (4,5/+3,0 GiB). Nay dùng file cấu hình mẫu theo tiêu chuẩn hiện tại (3,0/+2,0/dự trữ 1,5 GiB) và có test kiểm tra `asr-memory.json` khớp tiêu chuẩn. Toàn bộ 287 test pass (1 bỏ qua), chạy 3 lần liên tiếp.
4. **GPU chưa dùng được và chưa an toàn** (đánh giá tại `docs/CALIBRATION_REVIEW.md`): ASR GPU bỏ qua calibrate/pool/VRAM; TTS GPU dùng heuristic CPU, nhiều worker có thể hết VRAM (card ~4 GB); Translation GPU cần `llama-server` CUDA. Cần cài `torch` CUDA và `llama-cpp-python` GPU trước khi thử.
5. **Hiệu chuẩn:** các cải tiến ưu tiên ở `docs/CALIBRATION_REVIEW.md` (chống dao động ở Translation, lấy RTF từ dòng TTS đã xong, chọn mẫu đo theo độ dài, ghi điều kiện lúc đo vào profile).
6. **Phát hành:** tăng version sản phẩm trước khi build lại installer; đăng ký lại manifest 1.1.0 trong Admin; phase 1 vẫn còn rủi ro thay binary/backend và chạy model ngoài ứng dụng (`SECURITY_PHASE_1_RESULT.md`).
7. `worker/dev/verify_notice.cjs` hỏng từ trước (thiếu mock `useLanguage`).
8. **Kiểu giọng (Voice style), đã làm 2026-10-04 (Claude Code):** Mặc định/Drama/Sinh tồn/Trọng sinh ở Studio, Tools (TTS) và Reprocess. Mỗi style có giọng gợi ý, gộp câu, tốc độ atempo, khoảng nghỉ đo từ video mẫu và thẻ cảm xúc thử nghiệm. Xem `docs/VOICE_STYLES.md`. Chưa chạy một workflow đầy đủ với style mới. Test: 219, đúng 5 lỗi có sẵn.
9. **Xưng hô theo thể loại, đã làm 2026-10-05 (Claude Code):** L0 profile (`worker/config/address-profiles.json`), L1 bảng nhân vật (`working/characters.json`, sửa ở trang Reprocess), L2 sửa đại từ ở đầu Moderation (`moderation/address.py`). Nguyên nhân gốc: ASR không phân biệt 他/她; Translation không có ngữ cảnh. Profile Trung tính giữ nguyên hành vi cũ. Chạy thử trên dữ liệu thật 000008/000009: 12/14 và khoảng 45/50 thay đổi đúng. Chưa Reprocess workflow thật. Xem `docs/ADDRESS_FORMS.md`. Test: 247, đúng 5 lỗi có sẵn.
10. **Ngữ cảnh dịch cho job có style (2026-10-05, Claude Code):** bảng nhân vật soạn từ đầu Translation; sửa 他/她 trên bản tiếng Trung (chỉ khi chắc, chặt hơn L2); từ điển thuật ngữ `worker/config/genre-lexicon.json`; kiểm tra giới tính khi dịch (dịch lại, rồi chốt theo đại từ tiếng Trung); hạ chữ hoa đầu mảnh ở Moderation. Job cũ không đổi. Đã thử trên model thật với 48 dòng của 000008; chưa Reprocess cả workflow. Không áp dụng mẫu Style/Background (thử không hiệu quả). Test: 267, đúng 5 lỗi có sẵn.
11. **Làm sạch bản tiếng Trung (2026-10-05, Claude Code):** cắt lời quảng cáo kênh đọc đầu truyện (dòng thành bản dịch rỗng, TTS bỏ qua), sửa lỗi ASR đã gặp (`worker/config/source-cleanup.json`), mở rộng từ điển thuật ngữ. Chỉ job có Kiểu giọng. Mục từ điển mới chưa thử trên model thật (RAM < 4.3 GiB). Hy-MT2-7B tạm hoãn vì tài nguyên. Test: 279, đúng 5 lỗi có sẵn.
12. **Cập nhật lớn Genius + Basic/Plus (đã triển khai code 2026-10-06, chưa build installer / chưa deploy VPS):**
    - Gói: tier lấy từ mã sản phẩm biên dịch trong security-core (`identity.tier`); worker `core/edition.py`, Next `lib/server/edition.ts`.
    - Basic ẩn tiếng Trung ở 3 lớp (UI, API, worker) và mã hóa bản làm việc (`core/sealing.py`).
    - Build từng gói: `packaging/build_installer.py --product audio-translate-basic|plus`, manifest ở `products/`.
    - Genius: `translation/genius.py` gọi gateway mới `../billing-gateway/` (VPS); Admin → trang Billing.
    - Chi tiết, trạng thái và việc còn lại: `docs/PLAN_GENIUS_BASIC_PLUS.md` mục 0; triển khai VPS: `billing-gateway/README.md`.
13. **Basic tạo giọng qua VPS + duyệt trước TTS + nền tảng nhiều app (đã triển khai code 2026-10-06; chờ test trên VM GCP):**
    - Gateway có `app_id`/`service` (`translation`, `tts`), cài đặt và giá theo dịch vụ, một sổ nợ cho mỗi khách.
    - `/v1/tts` gửi và hỏi lại, chạy worker VieNeu, trả FLAC. App dùng `tts/remote.py` (đoạn 1.200 ký tự) khi là Basic.
    - Basic dừng ở `AWAITING_REVIEW` trước TTS, trừ khi bật ô Auto.
    - Bộ cài Basic không có VieNeu, `sea-g2p`, `onnxruntime`; danh sách giọng ở `worker/config/voice-catalog.json`.
    - Chi tiết: `docs/PLAN_TTS_VPS.md` mục 0.
14. **Deploy thử gateway lên GCP (2026-10-06):**
    - VM của người dùng `instance-20261006-011041` (e2-custom-2-4608, Spot, **tự xóa sau 10 giờ chạy**), Debian 13.
    - Tunnel `https://audio-gateway.arsneonci.space` (Terraform `billing-gateway/deploy/tunnel/`), cài bằng `deploy/vm-install.sh`.
    - TTS chạy trọn từ máy local: 20 dòng, 63 giây, đúng 581 ký tự tính phí.
    - Genius bị chặn vì Gemini key giới hạn IP (`API_KEY_IP_ADDRESS_BLOCKED`); job tool `genius-vm-test.jsonl` đang PAUSED.
    - Admin không còn build (`release_config.py` xuất cấu hình công khai). Test cấp token: `admin-system/test_issuance.py`. Hướng dẫn nối app mới: `Doc-Admin.md`.
    - Gói cũ `audio-translate` được đẩy lên gateway chỉ để test từ localhost:3000.
15. **Basic khôi phục tiếng Trung (2026-10-06):** Basic xem/tải ZH JSONL và Markdown, có Tools 1, Reprocess từ Download/Transcription, bảng nhân vật, `text_zh` trong file xuất; bỏ mã hóa bản làm việc (`core/sealing.py` chỉ còn giải mã job cũ). Hai gói chỉ khác cách tạo giọng. Cần build lại cả frontend và cả 2 bộ cài; chưa build.
9. **Chạy nhiều workflow cùng lúc: đã triển khai và chạy thử thật (2026-10-04)**, xem `docs/MULTI_WORKFLOW_SCHEDULER.md` mục 7–8. Chạy thử phát hiện và sửa 4 lỗi (hiệu chuẩn TTS theo giọng, hiệu chuẩn lại ngay sau cache, pool hiệu chuẩn không báo sổ cái, dao động tạm dừng). Ở ~4 GiB RAM chạy tuần tự nhanh hơn song song; còn việc: đo lại `stage_cost` ASR. Các sửa này chưa commit.
10. **Tăng X theo hiệu quả đo được (2026-10-05):** TTS bỏ hiệu chuẩn nhân đôi và profile cache; giờ +1 worker sau 10 giây ổn định (nạp nền), giữ nếu ký tự/giây tăng bất kỳ mức nào, không thì gỡ và chặn mức đó 10 phút. Translation dùng cùng `core/scaling.py` cho slot. ASR bỏ ngưỡng 5%/10%, nhanh hơn là giữ. Test 274, đúng 5 lỗi có sẵn. Chưa chạy thật trên workflow, chưa commit.
11. **Tools đồng bộ với workflow (2026-10-05):** Tool 1 nhận link YouTube (Download + Transcription), Tool 2 có Forms of address áp dụng khi xuất, Tool History xóa được khi đang chờ/chạy (dừng sau tác vụ hiện tại rồi xóa sạch). Tool dùng chung Bộ phân luồng. Xem `docs/TOOLS.md`. Chưa commit.
12. **Translation chuyển sang Hy-MT2-7B Q4_K_M (2026-10-05):** đã tải và xác minh SHA-256, xóa bản 1.8B. **RAM khi chạy (đo thật):** `--no-repack` +4,52–4,77 GiB (mặc định repack > 6,7 GiB, phải dừng), đường chạy thật 2–3 slot đỉnh +5,28 GiB, RAM trống thấp nhất 2,18 GiB; KV `q8_0` 0,32 GiB/slot. Ngưỡng: khởi động 6 GiB, giữ 1 GiB, slot +0,35 GiB. 7B dùng mẫu chat Hunyuan (`<|startoftext|>…<|extra_0|>`, dừng `<|eos|>`), tự nhận từ GGUF. Job cũ tự chuyển model khi SHA khác. Thử nghiệm batch 20 dòng + ngữ cảnh + 2 lượt: không hơn cách hiện tại, chưa bật. Repo chính thức không có Q4_K_S/Q3_K_M. Chi tiết: `docs/TRANSLATION_LONG.md`.

## 6. Dòng thời gian gần đây

- **10-02** (Codex): Security Phase 1 (core Rust xác minh license, Machine ID, DPAPI, chặn workflow/retry khi hết hạn); admin-system thêm tìm kiếm/lọc, sửa lỗi Product detail lặp bảng; profile YouTube riêng thay cookie file; tách TRANSCRIPTION thành 4 pha có tiến độ và Elapsed; voice preview dựng sẵn; ASR autotune (X1/X2/X3 pool); preflight kiểm tra khi chạy nhiều workflow; Pause/Continue/Cancel chuyển ra bảng chính dùng icon; dọn upstream và gom về một git/một cách build; tạo `CV_PROJECT_EVIDENCE.md`.
- **10-03** (Codex): trả lời về lưu dữ liệu (file + SQLite registry); đo RAM ASR (X1 5.17 GiB); thay NLLB bằng Qwen3-8B Q4_K_M rồi xóa hẳn NLLB, ẩn `admin-system` khỏi GitHub; lỗi Translation, đổi sang **Hy-MT2-1.8B Q8_0**; đo RAM 1x/2x/3x; thiết kế đơn vị song song theo tài nguyên; thay calibrate bằng điều phối trực tiếp theo RAM/CPU/GPU/nhiệt (không benchmark).
- **10-04** (Codex): chẩn đoán lỗi Translation giữa chừng; thêm hàng đợi hữu hạn, checkpoint từng đoạn, xuất chuỗi liên tiếp, Continue theo đoạn lỗi, chẩn đoán từng dòng (`TRANSLATION_CHECKPOINTS.md`); gom docs vào `docs/`; đánh giá nguy cơ song song ở Transcription/TTS; đề xuất chuyển sang tuần tự (chưa làm).
- **10-04** (Claude Code): `Agent.md`; kiểm tra CPU/GPU; tái cấu trúc worker thành package và frontend theo layer; test localhost:3000; đánh giá hiệu chuẩn; tổng hợp tài liệu này; sửa prompt Translation (không ngữ cảnh, văn phong tự nhiên, ngân sách token, cách ly dòng lỗi) và Resume workflow 000007.
- **10-06** (Claude Code): Bảo mật Phase 2A — Windows Service + Named Pipe IPC, manifest ký Ed25519 khóa riêng + integrity, client Node/Python đi pipe, launcher authorize qua service (fail-closed), tamper states + i18n, `test_security_phase2.py` (5/5). Branch `security-phase-2`, chưa push. Chi tiết: `docs/SECURITY_PHASE_2_RESULT.md`.

## 7. Bản đồ tài liệu (`audio-translates/docs/`)

| File | Nội dung |
|---|---|
| `README.md` | Mục lục |
| `CLEAN_ARCHITECTURE.md` | Bố cục mã nguồn, phát hành, lịch sử dọn dẹp |
| `COMPUTE_SETTINGS.md` | CPU/GPU theo workflow |
| `ASR_CPU.md`, `TRANSCRIPTION_PROGRESS.md` | ASR autotune/RAM; tiến độ 4 pha |
| `TRANSLATION_LONG.md` | Hy-MT2: model, runtime, ngưỡng, điều phối tài nguyên |
| `TRANSLATION_CHECKPOINTS.md` | Hàng đợi, checkpoint từng đoạn, Continue, chẩn đoán |
| `TTS_CPU.md`, `VOICE_PREVIEWS.md` | TTS autotune; xem trước giọng |
| `WORKFLOW_LIFECYCLE.md` | Vòng đời, pause/resume |
| `CALIBRATION_REVIEW.md` | Đánh giá hiệu chuẩn ASR, Translation, TTS (mới) |
| `QWEN_*_RESULT.md` | Lịch sử Qwen (đã thay bằng Hy-MT2), `TTS_RUNTIME_RESULT.md`, `IMPLEMENTATION_RESULT.md` |
| `SECURITY_PHASE_1_RESULT.md`, `SECURITY_PHASE_2_RESULT.md` | Bảo mật Phase 1 (ranh giới native, license gắn máy) và Phase 2 (service + Named Pipe, manifest ký, integrity, tamper states; 2A xong, 2B/2C đang làm) |

## 8. Lệnh thường dùng (từ `audio-translates/`)

- Test worker: `.venv\Scripts\python.exe -m unittest discover -s worker/tests -t worker -p "test_*.py"`
- Module riêng: `$env:PYTHONPATH="worker"; .venv\Scripts\python.exe -m audio_translate.<pkg>.<module>`
- Frontend: `npx tsc --noEmit`, `npm run lint`, `npm run check:i18n`, `npm run check:theme`, `npm run dev`.
- Installer: `npm run package:windows` (kích hoạt `.venv` trước; tăng version trước khi build).

## 9. Quy ước làm việc với người dùng

- Trả lời bằng tiếng Việt, ngắn gọn, nêu rõ phần đã kiểm chứng và phần chưa.
- Khi người dùng nói "chỉ đánh giá/đề xuất/chưa code" thì không sửa mã. Đã nhiều lần dùng cách này trước khi chốt phương án.
- Không tác động workflow đang chạy; không xóa `data/tmp`, `data/results`, model weights. Hỏi trước khi xóa.
- Không đoán nguyên nhân khi chưa có log; ghi rõ nếu chưa xác nhận được.
- Next.js ở đây là bản có breaking changes: đọc `node_modules/next/dist/docs/` trước khi sửa code Next (`audio-translates/AGENTS.md`).
- Không sửa `FunASR-main`, `VieNeu-TTS-main`, `yt-dlp-master`.
