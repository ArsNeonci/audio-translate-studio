# RUNBOOK — Chạy, test, build, deploy, vận hành

Lệnh và quy trình đã dùng được. Kiến trúc: `ARCHITECTURE.md`. Bẫy: `PITFALLS.md`. Máy dev: Windows 11, PowerShell. Gốc `C:\Workspace\Audio-translate` (ký hiệu `ROOT`).

## 1. Khởi động lại dự án sau thời gian dài

1. Đọc `Agent.md`, rồi `Document/ARCHITECTURE.md`, `Document/PITFALLS.md`. Đừng quét source trước khi tra `audio-translates/docs/README.md`.
2. Kiểm tra trạng thái repo (gốc không phải repo, phải vào từng thư mục):
   ```
   foreach($d in 'audio-translates','billing-gateway','admin-system','shared-license-sdk'){ "== $d"; git -C $d status --short; git -C $d log --oneline -3 }
   ```
   Có thay đổi chưa commit thì hỏi người dùng đó là gì trước khi làm tiếp, đừng tự commit.
3. Kiểm tra hạ tầng còn sống (VM Spot có thể đã dừng, xem `PITFALLS.md` D8): mở `https://admin.arsneonci.space` (qua Cloudflare Access) và kiểm gateway `audio-gateway.arsneonci.space`.
4. Chạy bộ test (mục 3) để biết nền có còn xanh không.

## 2. Chạy app ở máy dev (từ `ROOT\audio-translates`)

- Dev server: `npm run dev` → `http://localhost:3000`. Python: `.venv\Scripts\python.exe` (`torch +cpu`, mọi workflow chạy CPU).
- Chạy một module worker riêng: `$env:PYTHONPATH="worker"; .venv\Scripts\python.exe -m audio_translate.<pkg>.<module>`
- Khóa/bí mật ở `ROOT\.env` (đọc trong script, không in ra).
- Dữ liệu dev: `data/` (không xóa `data/tmp`, `data/results`).

## 3. Test

| Thành phần | Lệnh | Ghi chú |
|---|---|---|
| Worker Python | `.venv\Scripts\python.exe -m unittest discover -s worker/tests -t worker -p "test_*.py"` (từ `audio-translates`) | Lần gần nhất ghi trong Agent.md: 315 test pass (2026-10-07); chưa chạy lại ở phiên dọn tài liệu |
| Frontend | `npx tsc --noEmit`, `npm run lint`, `npm run check:i18n`, `npm run check:theme`, `npm run check:billing`, `npm run check:upload` | |
| Tải model | `node scripts/check-model-download.cjs` | Máy chủ HTTP giả Cloud Storage |
| Lõi Rust | `cargo test` trong `security-core` bằng bộ Rust ở `ROOT\.tools\rust` | Không có `cargo` trên PATH |
| Bảo mật | `packaging\test_security_phase2.py`, `packaging\test_security_phase1.py` | Phase 1 chưa chạy lại sau khi đổi sang Hy-MT2 |
| Cài/gỡ | `cd packaging; ..\.venv\Scripts\python.exe -m unittest test_install_flow` | Edition "Test" 9.9.9, không bao giờ dùng `/DATA` |
| Gateway | `cd billing-gateway; .venv\Scripts\python.exe -m unittest discover -p "test_*.py"` | Venv có SDK `payos` |
| Admin | `cd admin-system; .venv\Scripts\python.exe test_<tên>.py`; payments cần venv của gateway; `node test_payments_ui.cjs` | `test_access_auth`, `test_admin_server`, `test_migration`, `test_lease`, `test_issuance` |

## 4. Build bộ cài Basic/Plus

Hướng dẫn đầy đủ: `audio-translates/docs/BUILD_RELEASE.md`.

```
cd ROOT\audio-translates
.venv\Scripts\python.exe packaging\build_edition.py --dry-run     # kiểm tra, không đổi gì
.venv\Scripts\python.exe packaging\build_edition.py               # thêm --push-lease để đẩy khóa phiên bản
```

Trước khi build:
- Không có workflow đang chạy; RAM trống ≥ 5 GiB (`--force` nếu biết rõ), ổ đĩa trống ≥ 20 GiB.
- Đã **tăng version** nếu mã đã đổi (cả hai `products\{basic,plus}\product.manifest.json`, cả `version` và `artifact_path`).
- Biến môi trường cho bản cứng (`AUDIO_RELEASE_HARDENED=1`, `AUDIO_SIGNING_CERT`, `AUDIO_SIGNING_PASSWORD`, `AUDIO_MANIFEST_KEY_FILE`) chỉ khi đã có chứng chỉ; chưa thiết lập.

Sau khi build:
1. Kiểm kích thước `dist\*.exe` (≈ 0,6 GB; gần 4 GiB là lỗi).
2. Đẩy khóa phiên bản: admin → **Sản phẩm** → *Đồng bộ khóa với gateway* (nếu chưa dùng `--push-lease`).
3. Cài thử bằng `/Q` vào thư mục tạm (`AUDIO_INSTALL_DIR=<tạm>`), kích hoạt bằng token thử, kiểm trang License và nút **Mua / gia hạn gói**.
4. Phát file `.exe` cho khách (một bộ cài chung mỗi gói; khách khác nhau ở token license).
5. Tùy chọn: `retire_version` cho phiên bản cũ.

Thay đổi nào cần build lại:

| Đổi | Build lại app? | Việc cần làm |
|---|---|---|
| Giá, hạn mức, nội dung trang thanh toán | Không | Admin → Payments → Lưu & áp dụng |
| `app/`, `components/`, `lib/`, `worker/`, `security-core/` | **Có** | Tăng version, build, đẩy lease |
| `billing-gateway` | Không | Deploy gateway (mục 5) |
| `admin-system` | Không | Deploy admin (mục 5) |
| Thứ tự client YouTube, yt-dlp mới | Không | Mục 6 |

## 5. Deploy lên VM

- **Gateway:** `billing-gateway\deploy\deploy_gateway.py`. Cài mới: `deploy/vm-install.sh`. Cloudflare Tunnel: `deploy/tunnel/` (Terraform). Hướng dẫn: `billing-gateway/README.md`.
- **Admin:** `python admin-system\deploy\deploy_admin.py` (giữ nguyên DB, khóa và cấu hình). Chuyển dữ liệu lần đầu: `migrate_to_server.py --freeze-to`, rồi `deploy_admin.py --db ... --replace-db` (đã làm, không lặp lại).
- Xem log trên VM: `journalctl -u audio-admin` (không chứa khóa/token).
- Đăng ký sản phẩm trên server bằng đường build: `release_config.py --remote` (trang UI chỉ đọc đường dẫn file trên máy server).
- Máy build cần biến người dùng: `ADMIN_REMOTE_URL`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET` (đã đặt trên máy build hiện tại).
- Sao lưu: DB admin lên bucket 03:30 giờ VN hằng ngày (`admin.sqlite3.gz`); gateway sao lưu hằng ngày và báo cáo tháng lên `gs://audio-gateway-backup-erp-project-8386`.
- **Khôi phục admin:** dừng dịch vụ → chép DB đã giải nén vào `/var/lib/audio-admin/admin.sqlite3` (quyền `600`, chủ `audio-admin`) → đặt đúng master key → khởi động lại. Rollback chuyển quyền chỉ khi chưa cấp gì trên server (`docs/ADMIN_ONLINE.md` mục 5).

## 6. Phát hành bản cập nhật yt-dlp (không cần build lại app)

Chạy trên máy có khóa ký (`C:\Users\Linh\.audio-translate\youtube-update-signing.pem`) và `gcloud`:

```
cd ROOT\audio-translates
.venv\Scripts\python.exe packaging\publish_youtube_update.py --bucket audio-translate-models-8386 --dry-run
.venv\Scripts\python.exe packaging\publish_youtube_update.py --bucket audio-translate-models-8386
```

- Chọn bản: `--yt-dlp <phiên bản>`. Quay lui: phát hành lại bản cũ (serial mới vẫn lớn hơn).
- Chỉ đổi thứ tự client: `--attempts "[{\"client\": \"tv\", \"cookies\": true}, ...]"`.
- Mất khóa: `--init-key`, rồi bắt buộc build lại app.
- Phát hành gần nhất đã ghi: yt-dlp 2026.8.19 + yt-dlp-ejs 0.8.0, serial 1791505617 (2026-10-09). Dùng khi YouTube lại báo lỗi tải hàng loạt, sau khi đã loại trừ IP/cookie (`PITFALLS.md` A1–A4).

## 7. Đổi model dịch hoặc model ASR

- **Model dịch:** đổi `FILENAME/SIZE/SHA256` ở `worker/tools/download_translation_model.py` và `MODEL` ở `lib/server/model-download.ts`; thêm id vào `MODELS` ở `billing-gateway/gateway.py`; upload bằng `audio-translates\packaging\upload_model.py`; build lại hai gói. App cũ vẫn dùng id cũ nên không hỏng.
- **Model ASR:** `python packaging\make_asr_manifest.py --source <thư mục chứa models/<org>--<tên>/snapshots/master>` (ghi `worker/config/asr-models.json` và `billing-gateway/asr_models.json`), upload lên `models/asr/<tên>/` trong bucket, deploy gateway, build lại.

## 8. Thao tác thường ngày ở admin

Chi tiết từng nút: `docs/ADMIN_ACTIONS.md`.

- **Cấp khách mới:** Customers → tạo khách → tạo entitlement cho gói → cấp token kích hoạt → gửi khách.
- **Gia hạn:** Licenses → Gia hạn (số ngày; cộng dồn). Khách tự mua qua cổng Billing thì token tự cài vào app.
- **Gửi lại token:** nút *Token Giấy phép* (không đổi hạn).
- **Mã khách hàng:** ở dòng sản phẩm trong Customers → Xem chi tiết; *Cấp lại mã* khi cần.
- **Hạn mức nợ, bảng giá:** Payments → tab Hạn mức / Bảng giá → Lưu & áp dụng. Khách mới cần hạn mức > 0 mới dùng được dịch vụ trả phí.
- **Thu hồi / khôi phục lease:** qua Billing hoặc API `lease_revoke` (hiệu lực ngay).
- **Thêm app mới vào nền tảng:** `Doc-Admin.md` (khai báo `product.manifest.json` có khối `gateway`, đăng ký, thêm service ở gateway).

## 9. Thử một giao dịch thật (chưa từng làm)

1. Admin: tạo khách + entitlement Basic/Plus, cấp token, dán vào bản app **có nút thanh toán** (cần build mới).
2. Admin → Payments → tab Gia hạn: kiểm *Kênh duyệt trực tiếp: đang nối*.
3. App → License → **Mua / gia hạn gói** → 1 tháng (2.000đ) → quét QR.
4. Kỳ vọng trong vài giây: đơn *Hoàn tất*, app báo "Đã nhận và cài gia hạn mới", `sequence` +1, hạn +30 ngày; tab Lịch sử có khoản `PAYOS` / `LICENSE`.
5. Thử trả nợ: đặt hạn mức nhỏ, tạo job Genius tới `CREDIT_LIMIT`, bấm **Trả nợ**, rồi **Tiếp tục**.
6. Thử khi admin tắt: đơn phải được ký bù khi admin bật lại.

## 10. Quy ước làm việc với chủ dự án

- Trả lời tiếng Việt, ngắn gọn, tách rõ phần đã kiểm chứng và chưa kiểm chứng.
- "Chỉ đánh giá / đề xuất / chưa code" nghĩa là không sửa mã.
- Không đoán nguyên nhân khi chưa có log; nói rõ khi chưa xác nhận được.
- Không tác động workflow đang chạy; hỏi trước khi xóa `data/tmp`, `data/results`, model.
- Dịch phải luôn chừa 2 GiB RAM cho hệ thống.
- Tài liệu kỹ thuật mới đặt ở `audio-translates/docs/` (theo `audio-translates/CLAUDE.md`); cập nhật `Agent.md` khi trạng thái hoặc vấn đề mở thay đổi.
