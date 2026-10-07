# Admin online (chạy liên tục trên VM, sau Cloudflare Access)

Trạng thái: **đã chạy thật từ 2026-10-07** tại `https://admin.arsneonci.space`.

- Ứng dụng Cloudflare Access "Audio Translate admin" (policy: email `quanglinh1286@gmail.com`, đăng nhập bằng mã PIN; thêm một policy *Service Auth* cho service token của máy build) đã được tạo, rồi **chuyển sang quản lý bằng giao diện Cloudflare** để bạn tự sửa (Terraform không còn đụng tới).
- Đã kiểm chứng với Cloudflare thật: không đăng nhập thì bị chuyển sang trang đăng nhập Access; service token qua được và admin chấp nhận token của Cloudflare; sai secret thì Cloudflare chặn.
- Dữ liệu đã chuyển (`migrate_to_server.py --freeze-to`): 3 sản phẩm, 1 khách, 1 license, 12 khóa được mã hóa lại và kiểm tra. **Bản admin trên máy bạn đã đóng băng.** Khóa gốc trên server khớp bản gốc; server đẩy được lease materials sang gateway; vòng ký gia hạn đang chạy (`ADMIN_FULFILLMENT=on`, Tự duyệt BẬT) và đã nối với gateway.
- Master key: `C:\Users\Linh\audio-translate-keys\admin-move\admin-master.key` (và `/etc/audio-admin/master.key` trên VM). **Hãy chép nó ra chỗ cất offline rồi xóa bản trên ổ C.**
- Máy build: đã đặt biến môi trường người dùng `ADMIN_REMOTE_URL`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`, nên `build_edition.py` tự lấy khóa từ admin online.
- Sao lưu DB admin đầu tiên đã lên bucket (`daily/2026-10-07/admin.sqlite3.gz`).

**Thêm hoặc bớt người được vào admin:** sửa policy email của ứng dụng trên Cloudflare **và** danh sách `ADMIN_EMAILS` của admin (admin kiểm tra thêm một lần; người không có trong danh sách sẽ bị từ chối dù Cloudflare cho qua). Đổi `ADMIN_EMAILS` bằng `deploy/deploy_admin.py --secrets <file>` (file cần đủ các dòng ở mục 4) hoặc nhờ agent.

Phần dưới đây giữ nguyên làm tài liệu tham chiếu (cách đã làm, cách làm lại, cách quay lui).

## 1. Đã làm và đã kiểm chứng

| Phần | Kết quả |
|---|---|
| Chế độ server của admin (`run.py --server`) | Chạy được trên Linux. Mọi yêu cầu phải mang token Cloudflare Access hợp lệ; **chưa cấu hình Access thì từ chối tất cả** (đã thử trên VM: 403) |
| Kiểm tra token Access (`access_auth.py`) | 9 test: chữ ký RS256 theo khóa của Cloudflare, đúng team và AUD, hết hạn, đúng email, token `alg: none`, đổi khóa Cloudflare, mất kết nối tới khóa |
| Khóa ký trên VM | Mã hóa AES-256-GCM bằng **master key 64 ký tự hex** nằm trong file riêng; không ai gõ nó |
| Chống hai admin cùng cấp license | Bản trên máy bạn bị **đóng băng** khi chuyển (`AUTHORITY_MOVED`): đọc được, không ghi được |
| Công cụ chuyển dữ liệu (`migrate_to_server.py`) | 7 test: mã hóa lại từng khóa, kiểm tra từng khóa còn khớp khóa công khai, token cũ giữ nguyên, bảng chống ký trùng đi theo |
| Máy build sau khi chuyển | Lấy cấu hình và khóa phiên bản từ admin online bằng **Access service token**, chỉ vào được `/api/build/*` |
| Triển khai | `deploy/deploy_admin.py` một lệnh; phân quyền đã kiểm tra (thư mục `700`, DB `600`, tài khoản `audio-gateway` không đọc được) |
| Vòng ký tự động trên server | Chỉ chạy khi `ADMIN_FULFILLMENT=on` (đã bật sau khi chuyển dữ liệu) |

Admin chạy cùng VM với gateway nhưng là **tài khoản hệ thống riêng** (`audio-admin`), thư mục riêng, cổng `127.0.0.1:8787` và dịch vụ systemd có giới hạn quyền. Tách VM riêng sẽ an toàn hơn nữa; chưa làm vì tốn thêm chi phí.

## 2. Rủi ro bạn đã chấp nhận khi chọn "file mã hóa trên VM"

- Khóa ký (và cả khóa gốc, vì cả hai nằm trong cùng một cơ sở dữ liệu) nằm trên VM. **Ai chiếm được VM cùng lúc đọc được master key là mang khóa đi được** và in license cho mọi khách, kể cả khi sau đó bạn đã đóng VM lại.
- Theo cách xác minh hiện tại, **khóa ký đã lộ không thu hồi được** (không có danh sách thu hồi khóa ký; tôi đã đọc phía gateway, chưa đọc lõi Rust). Cách duy nhất khi đó là đổi sang sản phẩm mới và phát lại bộ cài.
- Các lớp giảm rủi ro đang có: Cloudflare Access (đăng nhập email) trước admin; admin tự kiểm tra lại token và danh sách email; không mở cổng nào ra ngoài; file khóa quyền `640` chỉ `root` và `audio-admin` đọc; DB quyền `600`; dịch vụ tách tài khoản; sao lưu hằng ngày lên bucket chỉ cho tạo và đọc, không xóa.
- Muốn khóa không bao giờ rời khỏi hạ tầng của Google thì phải chuyển sang Cloud KMS (phương án A ở lần thảo luận trước). Việc đó làm sau được, vì mọi truy cập khóa đi qua `SecretStore` trong `core.py`.

## 3. Việc của bạn trên Cloudflare

Tên mục có thể khác chút tùy phiên bản giao diện (tôi không thao tác được trên tài khoản của bạn).

1. **Zero Trust → Access → Applications → Add an application → Self-hosted.** Tên tùy ý, *Public hostname* = `admin.arsneonci.space`, thời hạn phiên khoảng 8 giờ.
2. **Policy**: Action **Allow**, điều kiện **Include → Emails → `quanglinh1286@gmail.com`**. Cách đăng nhập mặc định là mã PIN gửi về email.
3. Mở ứng dụng vừa tạo, ghi lại **Application Audience (AUD) Tag** (chuỗi 64 ký tự). Ghi lại cả **team domain** (dạng `tên-của-bạn.cloudflareaccess.com`, ở Settings của Zero Trust).
4. **Cho máy build** (làm sau cũng được): *Access → Service credentials → Create service token*, chép Client ID và Client Secret (secret chỉ hiện một lần). Thêm vào ứng dụng một policy **Action = Service Auth**, điều kiện **Service Token = token vừa tạo**; thiếu policy này Cloudflare chặn token đó.

**Đừng bao giờ gắn Access lên `billing.arsneonci.space` hoặc `audio-gateway.arsneonci.space`**: payOS và app của khách không đăng nhập được và bạn mất thanh toán tự động. Access chỉ áp theo tên miền bạn gắn, nên các tên miền khác không bị ảnh hưởng.

## 4. Mở admin ra internet (sau khi xong mục 3)

1. Gửi tôi **team domain** và **AUD tag** (hoặc tự điền vào file settings bên dưới). Chúng không phải bí mật.
2. Tạo file settings (xem `admin-system/deploy/admin.env.example`) rồi chạy từ thư mục `admin-system`:
   `..\audio-translates\.venv\Scripts\python.exe deploy\deploy_admin.py --secrets settings.txt`
   (file settings bị xóa trên VM sau khi nạp; chỉ cần các dòng `ADMIN_HOST`, `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`, `ADMIN_EMAILS`, `ACCESS_SERVICE_CLIENTS`, `GATEWAY_URL`, `GATEWAY_ADMIN_TOKEN`, `BACKUP_BUCKET`, `ADMIN_FULFILLMENT`).
3. Trong `billing-gateway\deploy\tunnel\terraform.tfvars` thêm `admin_hostname = "admin.arsneonci.space"` rồi `terraform apply`: tạo bản ghi DNS và đường vào của tunnel.
4. Mở `https://admin.arsneonci.space`: phải thấy trang đăng nhập của Cloudflare, nhập email, nhận mã PIN. Chưa chuyển dữ liệu thì admin còn trống (không có khách, không có sản phẩm).

## 5. Chuyển quyền từ máy bạn lên server

Làm một lần, vào lúc bạn không đang cấp license. Từ lúc bước 3 chạy xong, **máy bạn không cấp license được nữa**; server là nơi cấp duy nhất.

1. Đóng admin trên máy. Nếu đã cài tác vụ Windows: `python renewal_worker.py --remove-task`.
2. (Tùy chọn, an toàn) diễn tập, không đổi gì trên máy bạn: `python migrate_to_server.py --out D:\admin-move`
3. Chuyển thật: `python migrate_to_server.py --out D:\admin-move --freeze-to https://admin.arsneonci.space`
   - từ chối chạy nếu admin hoặc worker còn mở;
   - đóng băng bản trên máy, sao chép, mã hóa lại mọi khóa bằng master key mới, kiểm tra từng khóa.
4. **Cất bản sao offline của `D:\admin-move\admin-master.key`** (không có file này thì không mở được bản sao lưu nào của DB).
5. Thêm `ADMIN_MASTER_KEY=<nội dung file đó>` vào file settings (cùng các dòng ở mục 4, `ADMIN_FULFILLMENT=off`), rồi:
   `python deploy\deploy_admin.py --secrets settings.txt --db D:\admin-move\admin.sqlite3 --replace-db`
   (DB và khóa cũ của bản thử được giữ lại cạnh bản mới trên VM).
6. Đăng nhập admin online, kiểm tra Dashboard (khách, sản phẩm, license), mở Payments → Gia hạn.
7. Khi hài lòng: đặt `ADMIN_FULFILLMENT=on` (chạy lại `deploy_admin.py --secrets ...`) và bật công tắc **Tự duyệt** trong trang Gia hạn. Từ đó gia hạn được ký ngay khi tiền về, kể cả khi máy bạn tắt.
8. Xóa thư mục `D:\admin-move` (chứa master key và bản sao DB).

**Quay lại nếu cần:** nếu **chưa cấp gì** trên server, mở khóa bản trên máy bằng `python -c "from core import Authority; Authority('data/admin.sqlite3').unfreeze()"` và dừng dịch vụ trên VM. Nếu server đã cấp license thì **đừng quay lại**: hai bên sẽ có hai dãy số thứ tự khác nhau.

## 6. Máy build sau khi chuyển

Bản trên máy bạn không còn tạo được khóa phiên bản mới (đã đóng băng), nên máy build lấy từ server. Đặt ba biến môi trường người dùng:
`ADMIN_REMOTE_URL=https://admin.arsneonci.space`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET` (service token ở mục 3.4).
Khi thấy `ADMIN_REMOTE_URL`, `packaging\build_edition.py` tự đăng ký manifest, lấy cấu hình công khai, lấy khóa phiên bản và đẩy lease materials qua admin online. Bước kiểm tra gói `audit_package.py` vẫn chạy trên bản đóng băng ở máy (nó đọc được nhưng chỉ biết các khóa phát hành trước khi chuyển; bước quét bí mật của trình build vẫn chạy đủ).

## 7. Vận hành

- **Sửa mã admin:** `python deploy\deploy_admin.py` (giữ nguyên DB, khóa và cấu hình).
- **Master key:** nằm ở `/etc/audio-admin/master.key` trên VM và một bản offline ở chỗ bạn. Mất cả hai là mất toàn bộ khóa ký.
- **Sao lưu:** DB admin lên bucket mỗi ngày 03:30 giờ VN (tên `admin.sqlite3.gz`). Khóa trong đó chỉ mở được bằng master key.
- **Khôi phục:** dừng dịch vụ, chép DB đã giải nén vào `/var/lib/audio-admin/admin.sqlite3` (quyền `600`, chủ `audio-admin`), đặt đúng master key tương ứng, khởi động lại.
- **Trang đăng ký sản phẩm** trong giao diện chỉ đọc đường dẫn file trên máy server, nên trên server hãy đăng ký sản phẩm bằng đường build (`release_config.py --remote`).
- **Xem log:** `journalctl -u audio-admin` trên VM (không chứa khóa hay token).

## 8. Kiểm thử

- `admin-system`: `test_access_auth.py` (9), `test_admin_server.py` (8: đóng khi chưa cấu hình, host và email, CSRF, service token, khóa được mã hóa, vòng ký không tự chạy, máy build), `test_migration.py` (7).
- Chạy bằng Python của admin: `.venv\Scripts\python.exe -m unittest discover -s . -p "test_*.py"`.
