# Tự build bộ cài Basic và Plus

Hướng dẫn cho chủ sản phẩm tự build, không cần nhờ agent. Nguồn: `packaging/build_installer.py`, `packaging/build_security_core.py`, `admin-system/release_config.py`, `admin-system/export_build_keys.py` và `docs/SECURITY_PHASE_*_RESULT.md`.

Trạng thái: 2026-10-07. Script `packaging/build_edition.py` mới viết và **chỉ đã chạy thử ở chế độ `--dry-run`** (kiểm tra máy và in các bước); tôi chưa build thật gói Basic/Plus nào bằng nó. Các bước bên trong là những lệnh sẵn có.

---

## 1. Build bằng một lệnh

Mở terminal, chạy **bằng Python của chính repo này**:

```
cd C:\Workspace\Audio-translate\audio-translates
.venv\Scripts\python.exe packaging\build_edition.py basic
.venv\Scripts\python.exe packaging\build_edition.py plus
```

Mỗi lệnh build **một gói**, mất khoảng 10 đến 30 phút (ước tính, chưa đo), kết quả nằm ở:

| Gói | File cài | Bản ghi phát hành |
|---|---|---|
| Basic | `dist\AudioTranslate-Basic-<version>.exe` | `dist\release-audio-translate-basic-<version>.json` |
| Plus | `dist\AudioTranslate-Plus-<version>.exe` | `dist\release-audio-translate-plus-<version>.json` |

Tùy chọn:

| Tùy chọn | Ý nghĩa |
|---|---|
| `--dry-run` | Kiểm tra máy và in đủ 5 bước, **không đổi gì**. Nên chạy trước lần đầu |
| `--push-lease` | Build xong thì đẩy khóa của phiên bản mới lên gateway (cần admin đã cấu hình gateway) |
| `--force` | Bỏ qua yêu cầu RAM/ổ đĩa tối thiểu (xem mục 6) |
| `--keys-dir <thư mục>` | Nơi lưu file khóa phiên bản; mặc định `C:\Users\<bạn>\audio-translate-keys` |

Script chỉ nối các bước với nhau và dừng ở bước lỗi đầu tiên, không in khóa:

1. **Kiểm tra máy:** RAM trống ≥ 5 GiB, ổ đĩa trống ≥ 20 GiB (hai ngưỡng này do tôi đặt rộng tay, chưa đo), có Python của repo, môi trường admin, `node_modules`, bộ Rust, trình biên dịch .NET, file model dịch.
2. **Cấu hình công khai và trust anchor:** admin đọc lại manifest rồi xuất `licensing\<gói>.public-config.json` và `security-core\trust-anchor.<gói>.json`.
3. **Khóa phiên bản:** xuất khóa của đúng phiên bản này ra file **ngoài mọi repo** (`...\audio-translate-keys\<gói>-<version>.key`). Không bao giờ commit hay gửi file này đi.
4. **Build bộ cài:** biên dịch lõi bảo mật Rust, build Next.js, gom Python/Node và model, mã hóa tài sản, quét bí mật, nén và ghép bộ cài.
5. **Kiểm tra bộ cài:** `audit_package.py` quét xem có khóa riêng, token hay dữ liệu khách lọt vào không.

Cuối cùng, nếu chưa dùng `--push-lease`, vào **admin → Billing → Push lease materials** (mục 4).

---

## 2. Chuẩn bị một lần

Máy này đã có đủ (preflight đã báo `ok` cho từng mục): môi trường admin, `node_modules`, bộ Rust riêng trong `C:\Workspace\Audio-translate\.tools\rust`, .NET Framework 4 (`csc.exe`), model dịch `models\Hy-MT2-7B-Q4_K_M`. Máy mới cần cài đủ các thứ này (xem README của từng thành phần).

Cần có sẵn và chạy được:
- admin-system đã đăng ký hai gói (`audio-translate-basic`, `audio-translate-plus`); chỉ cần mở admin một lần là tự đăng ký.
- Không có workflow đang chạy: build ngốn RAM và CPU, dễ làm workflow tạm dừng vì thiếu RAM.

---

## 3. Làm từng bước bằng tay (khi cần tìm lỗi)

Thay `<gói>` bằng `audio-translate-basic` hoặc `audio-translate-plus`, `<ver>` bằng phiên bản trong manifest.

```
cd C:\Workspace\Audio-translate\admin-system
.venv\Scripts\python.exe release_config.py <gói>
.venv\Scripts\python.exe export_build_keys.py --product <gói> --version <ver> --out C:\Users\<bạn>\audio-translate-keys\<gói>-<ver>.key

cd C:\Workspace\Audio-translate\audio-translates
set AUDIO_CONTENT_KEY_FILE=C:\Users\<bạn>\audio-translate-keys\<gói>-<ver>.key
.venv\Scripts\python.exe packaging\build_installer.py --product <gói>

cd C:\Workspace\Audio-translate\admin-system
.venv\Scripts\python.exe audit_package.py --edition basic       (hoặc plus)
```

---

## 4. Sau khi build xong

1. **Đẩy khóa phiên bản lên gateway** (nếu chưa dùng `--push-lease`): admin → Billing → *Push lease materials*. Thiếu bước này thì app của khách không xin được lease cho phiên bản mới.
2. **Thử cài** bộ cài trên một máy thử (hoặc thư mục tạm): kích hoạt bằng một token thử và kiểm tra các trang License, nút **Mua / gia hạn gói**.
3. **Phát cho khách:** gửi file `.exe` trong `dist`. Cùng một bộ cài dùng cho mọi khách của gói đó; mỗi khách chỉ khác nhau ở token license.
4. **Ngừng hỗ trợ bản cũ** (tùy chọn): admin gọi `retire_version` cho phiên bản cũ để khách phải cập nhật; xem `Doc-Admin.md`.

---

## 5. Có thay đổi thì làm gì

| Bạn đổi | Cần build lại app? | Việc cần làm |
|---|---|---|
| Giá gói, giá dịch vụ, hạn mức nợ, nội dung trang thanh toán | **Không** | Sửa ở admin → Payments, bấm Lưu & áp dụng |
| Nút bấm, chữ trong app, logic xử lý (thư mục `app`, `components`, `lib`, `worker`) | **Có** | Tăng phiên bản (bên dưới), build lại từng gói |
| `billing-gateway` (gateway, cổng thanh toán, webhook) | Không | Triển khai lại lên VM (`README` của billing-gateway) |
| `admin-system` | Không | Đóng và mở lại admin |

**Tăng phiên bản** (bắt buộc khi đã build một phiên bản rồi mà mã đã đổi, nếu không script dừng với `VERSION_ALREADY_RELEASED`): trong **cả hai** file `products\basic\product.manifest.json` và `products\plus\product.manifest.json`, sửa `version` (ví dụ `1.2.0` thành `1.2.1`) **và** `artifact_path` cho khớp (`dist/AudioTranslate-Basic-1.2.1.exe`). Rồi chạy lại `build_edition.py`; bước 1 tự đăng ký phiên bản mới với admin.

Mỗi phiên bản có khóa nội dung riêng, nên sau mỗi lần build phiên bản mới nhớ **Push lease materials**.

---

## 6. Lỗi thường gặp

| Thông báo | Nguyên nhân và cách xử lý |
|---|---|
| `free RAM >= 5 GiB` báo FAIL | Đóng bớt chương trình, hoặc đợi workflow chạy xong. Đang có workflow dịch thì **không** build. `--force` chỉ dùng khi bạn biết mình đang làm gì |
| `VERSION_ALREADY_RELEASED: bump version` | Mã đã đổi nhưng chưa tăng phiên bản. Làm theo mục 5 |
| `RELEASE_ARTIFACT_MISSING_OR_MODIFIED` | File `.exe` hoặc bản ghi `release-*.json` bị xóa hoặc sửa. Xóa cả hai file của phiên bản đó rồi build lại |
| `PUBLIC_CONFIG_INVALID` | Phiên bản trong manifest khác với cấu hình đã xuất. Chạy `release_config.py` (hoặc script, đã tự làm) sau khi sửa manifest |
| `ARTIFACT_PATH_INVALID` | `artifact_path` trong manifest không nằm trong `dist` hoặc sai tên |
| `RUST_TOOLCHAIN_REQUIRED` | Không thấy bộ Rust ở `.tools\rust` và không có `cargo` trên PATH |
| `COMPILED_TRUST_ANCHOR_MISMATCH` | File trust anchor không khớp lõi vừa biên dịch; chạy lại `release_config.py` |
| `HY_MT_MODEL_CHECKSUM_MISMATCH` | File model dịch hỏng hoặc sai phiên bản |
| `WINDOWS_DOTNET_BUILD_TOOLS_REQUIRED` | Thiếu `csc.exe` của .NET Framework 4 |
| `SECRET_SCAN_FAILED` | Có thứ giống khóa riêng, token hoặc cơ sở dữ liệu trong gói. **Đừng phát gói**; báo lại để xử lý |
| Build dừng giữa chừng | Xóa thư mục `dist\staging-*` (chỉ thư mục tạm của lần build đó) rồi chạy lại |

---

## 7. Bản "phát hành cứng" (chưa thiết lập)

Mặc định build **không** ở chế độ cứng: lõi bảo mật giữ đường dự phòng cho phát triển, payload không có chữ ký, và trình build in cảnh báo (`WARNING: ... unsigned`). Chế độ cứng (`AUDIO_RELEASE_HARDENED=1`) yêu cầu thêm:

- **Chứng chỉ ký mã** `AUDIO_SIGNING_CERT` (file `.pfx`) và `AUDIO_SIGNING_PASSWORD`, kèm `signtool` (Windows SDK). Chứng chỉ phải do chính bạn đăng ký; tôi chưa thấy bạn có.
- **Khóa chữ ký payload** `AUDIO_MANIFEST_KEY_FILE`, cùng khóa công khai tương ứng trong trust anchor (`manifest_public_key`). Hiện `release_config.py` **chưa** ghi trường này vào trust anchor, nên đường này chưa dùng được từ đầu đến cuối.

Khi bạn có chứng chỉ, đặt các biến này rồi chạy `build_edition.py`; script sẽ từ chối chạy nếu thiếu biến. Chi tiết kỹ thuật: `SECURITY_PHASE_2_RESULT.md` và `SECURITY_PHASE_3_RESULT.md`.

---

## 8. Điều không được làm

- Không đặt file khóa `.key` trong thư mục repo hoặc gửi cho ai; script từ chối ghi vào trong repo.
- Không sửa tay `dist\release-*.json` hay các file `.exe` đã phát hành.
- Không build khi đang chạy workflow dịch hoặc tạo giọng.
