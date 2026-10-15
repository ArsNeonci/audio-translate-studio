# Cài đặt tại chỗ và cập nhật qua VPS (3.2.0)

Phiên bản chỉ còn là **thông tin**. Giấy phép, khóa giải mã và việc app chạy được không còn phụ thuộc số phiên bản. Cài hoặc cập nhật bản mới thì thay thế bản đang có, không tạo ra hai app.

## 1. Vì sao đổi (đã đo ở giai đoạn 0)

Dựng thử nghiệm: cài Plus 3.0.0, Plus 3.1.0 và Basic 3.1.0 vào ba thư mục, dùng chung một thư mục trạng thái (giấy phép, lease, dữ liệu) như trên một máy thật.

| Tình huống | Kết quả quan sát (mã cũ) | Nguyên nhân (đọc từ mã) |
|---|---|---|
| Plus 3.0.0 kích hoạt, chạy tool kiểm duyệt | đạt | |
| Rồi mở Plus **3.1.0** trên cùng trạng thái, chạy tool kiểm duyệt | **lỗi 500** | `lease.dpapi` chỉ chứa khóa tài sản của 3.0.0; vault của 3.1.0 mã hóa bằng khóa khác nên không giải mã được. Lease còn hạn nên app không xin lease mới. |
| Basic 3.1.0 kích hoạt trên máy đã có lease của Plus | giấy phép `ACTIVE` nhưng lease `None`, tool bị từ chối `SECURE_STATE_INVALID` | `lease.dpapi` là một file dùng chung cho mọi gói; lease của Plus không xác thực được bằng khóa gốc của Basic, và bộ đếm `highest_counter` cũng dùng chung. |

Ngoài ra bộ cài cũ tạo thư mục riêng cho từng phiên bản (`Plus-3.0.0`), mỗi bản một mục gỡ cài đặt và một lối tắt, nên người dùng có hai app; cả hai cùng tranh cổng 3210 và cơ chế một cửa sổ duy nhất.

## 2. Thiết kế

### 2.1 Khóa tài sản theo gói
- Mỗi gói có **một khóa vault duy nhất** (đã có sẵn trong admin: `content_keys`). Mọi phiên bản của gói mã hóa vault bằng khóa đó (`export_build_keys.py` không còn `--version`).
- App xin lease với `{key_scope: "product", client_version}`. Gateway trả khóa của gói và ghi `"key_scope": "product"` **vào phần được ký** của lease. `client_version` chỉ được ghi vào sự kiện lease để thống kê.
- security-core chỉ lấy khóa từ lease có `key_scope == "product"`. Lease kiểu cũ (một khóa cho một phiên bản) vẫn chứng minh giấy phép còn sống nhưng không cho khóa, và app xin lease mới ngay khi mở.
- Gateway giữ nguyên cách cũ cho app cũ (`app_version` chọn khóa của đúng bản đó), nên 3.0.x đang cài vẫn chạy bình thường.

### 2.2 Lease theo gói
- `lease-<gói>.dpapi` thay cho `lease.dpapi`. Bộ đếm tính riêng từng gói, nên Basic và Plus không còn đè nhau. Khóa máy (`machine.x25519.dpapi`) vẫn dùng chung.
- Lần chạy đầu: nếu file mới chưa có và `lease.dpapi` cũ **xác thực được với khóa gốc của gói này**, nó được nhận làm lease của gói (bộ đếm tính lại từ lease đó); lease của gói khác bị bỏ qua. File cũ không bị xóa.

### 2.3 Cài đặt thay thế tại chỗ
- Một thư mục cho mỗi gói: `%LOCALAPPDATA%\Programs\AudioTranslate\Plus` (hoặc `Basic`). Một mục "Installed apps" cho mỗi gói; số phiên bản chỉ là `DisplayVersion`.
- Cài bản mới: giải nén vào `Plus.new` cạnh bản cũ, dừng app, rồi **đổi tên** (`Plus` → `Plus.old`, `Plus.new` → `Plus`). Nếu giải nén hỏng, hết ổ đĩa hay bất kỳ lỗi nào, bản cũ không bị đụng tới.
- Dọn các bản kiểu cũ của **cùng gói** (`Plus-3.0.0`, ...): dừng app, xóa thư mục và mục gỡ cài đặt. Gói khác không bị đụng tới. Dữ liệu người dùng nằm ngoài (`%LOCALAPPDATA%\AudioTranslate`) nên được giữ.
- **Không thay thế bản mới hơn**: bộ cài cũ hơn bản đang có thoát với mã 3 (cửa sổ báo "đã cài bản mới hơn"). `/FORCE` hoặc `AUDIO_ALLOW_DOWNGRADE=1` để cố ý hạ cấp.
- `/Q` cài im lặng, `/RUN` mở app sau khi cài. Mã thoát: 0 xong, 1 lỗi, 3 đã có bản mới hơn.
- Biến môi trường cho test: `AUDIO_INSTALL_PARENT` (thay thư mục `Programs\AudioTranslate`), `AUDIO_UNINSTALL_ROOT` (thay đường dẫn registry).

### 2.4 Nháp và phát hành
- Bản mới build là **bản nháp**: sửa mã và build lại cùng số phiên bản được, không cần xóa gì.
- `publish_update.py` (kênh `stable`) đánh dấu bản ghi `published: true`. Từ đó mã của phiên bản đó không đổi được nữa (`VERSION_ALREADY_RELEASED`).

## 3. Cập nhật qua VPS

### 3.1 Luồng
1. Bạn build và test, rồi chạy `packaging\publish_update.py <gói> --ssh ... --key ...`.
   - Hai file được tải lên VPS tại `updates/<gói>/<phiên bản>/` và không bao giờ bị ghi đè.
   - Sau đó ký `updates/<gói>/<kênh>/latest.json` bằng khóa ký của bạn và đăng cả `latest.sig`.
2. App (khi mở và mỗi 6 giờ nếu có mạng) gọi `POST /v1/app/update` của gateway. Gateway chuyển nguyên manifest đã ký và cấp liên kết tải có hạn 1 giờ cho các file nó liệt kê.
3. App kiểm tra chữ ký, sản phẩm, kênh, serial không cũ hơn bản đã thấy. Nếu bản mới hơn bản đang cài, app báo ở đầu trang và ở Cài đặt → Cập nhật ứng dụng.
4. Người dùng bấm **Tải và cập nhật**. App tải (tiếp tục được khi đứt), kiểm tra SHA-256 và kích thước trong manifest, rồi kiểm tra nội dung gói. Bấm **Cập nhật ngay**: nếu có workflow đang chạy thì hỏi, chúng dừng và tiếp tục sau khi cập nhật.
5. App thoát; vỏ desktop khởi động `updater.exe`. `updater.exe` áp dụng gói rồi mở app mới.

### 3.2 Hai loại gói
| Gói | Khi nào | Nội dung | Cách áp dụng |
|---|---|---|---|
| **app** (vài chục MB) | `runtime_sha256` của bản mới bằng dấu vân tay runtime của bản đang cài | mọi thứ trừ `runtime/` và `providers/` | `updater.exe`: đổi tên `app` → `app.old`, giải nén, khởi động và chờ `health.json`; không báo sẵn sàng trong 150 giây thì **tự quay về** `app.old` |
| **installer** (khoảng 600 MB) | runtime thay đổi (Python, thư viện, ffmpeg, node, nhà cung cấp TTS) | bộ cài đầy đủ | `updater.exe` chạy `bộ cài /Q`; bộ cài tự thay thế tại chỗ và giữ bản cũ nếu lỗi; rồi mở app |

Dấu vân tay runtime (`runtime-fingerprint.json`, SHA-256 trên đường dẫn và nội dung của `runtime/` và `providers/`) do `build_installer.py` ghi vào payload và vào bản ghi phát hành. Gói app chỉ chứa thứ `updater.exe` được phép thay: `runtime/` và `providers/` bị cấm, đường dẫn thoát khỏi thư mục cài bị từ chối.

### 3.3 Tin cậy
- Cập nhật là mã chạy trên máy khách, nên **chữ ký Ed25519** là điều kiện bắt buộc. Khóa ký (`~\.audio-translate\app-update-signing.pem`) nằm **ngoài repo và ngoài VPS**. App chỉ tin khóa công khai trong `worker/config/app-update-keys.json`.
- Gateway không giữ khóa ký, chỉ chuyển byte và cấp liên kết. Một manifest chỉ mở được file trong `updates/<gói của giấy phép>/<phiên bản>/`, không mở được model hay file của gói khác.
- Manifest có `serial` tăng dần; manifest cũ hơn bản đã thấy bị từ chối (không quay lui bằng cách phát lại). Quay lui là việc của bạn: đăng manifest mới với `--allow-downgrade`.
- Chưa có chứng chỉ ký mã (Authenticode). Cập nhật do app tải về và tự cài không đi qua SmartScreen như file `.exe` tải bằng trình duyệt.

### 3.4 Quay lui và nhật ký
- Cập nhật app: `app.old` được giữ lại sau khi cập nhật thành công (vài chục MB) để khôi phục tay nếu cần.
- Kết quả ghi ở `data\updates\last-update.json`; phiên bản lỗi vào `failed-versions.json` (app vẫn hiện bản đó nhưng ghi "lần trước không thành công"). Nhật ký ở `updates\updater.log`.
- Sau khi mở lại, trang đầu cho biết "Đã cập nhật lên X" hoặc "không thành công, đã quay về Y".

### 3.5 Chính sách phiên bản tối thiểu (tùy chọn, tách khỏi giấy phép)
- `--min-version X`: app cũ hơn X hiện "cần cập nhật" (đỏ).
- Admin `retire_version`: gateway từ chối lease cho phiên bản đó (`LEASE_VERSION_RETIRED`). App báo "đã ngừng hỗ trợ, hãy cập nhật", không báo lỗi giấy phép.
- Admin → Tổng quan có bảng **phiên bản đang dùng** (theo lease gần nhất của từng giấy phép).

## 4. Đổi nhà cung cấp VPS
App chỉ biết **tên miền** (`audio-gateway...`), nên dựng VPS mới rồi đưa tunnel Cloudflare sang đó là khách không phải làm gì. Cần chuyển cơ sở dữ liệu, khóa của admin, thư mục `updates/` và các secret. Khóa ký cập nhật không nằm trên VPS.

## 5. Kiểm thử
- `security-core` (cargo test): scope khóa, lease theo gói, nhận lease cũ một lần.
- `billing-gateway/test_lease_gateway.py`: lease theo gói, phiên bản bị ngừng, chuyển tiếp manifest, bảng phiên bản.
- `worker/tests/test_app_update.py` và `test_lease_request.py`: tin cậy, quyết định đề nghị, tải và kiểm tra gói, kế hoạch cho `updater.exe`.
- `packaging/test_install_flow.py`: cài tại chỗ, dọn bản cũ, không thay bản mới hơn, lỗi giữ nguyên bản cũ.
- `packaging/test_update_flow.py`: `updater.exe` thật với app giả: thành công, gói sai hash, bản không khởi động được bị quay về, gói cố chạm vào runtime, cài bằng bộ cài.
- Trên bản cài thật: nâng cấp 3.2.0 → 3.2.1 bằng gói app và bằng bộ cài, qua kênh `test` của VPS.
