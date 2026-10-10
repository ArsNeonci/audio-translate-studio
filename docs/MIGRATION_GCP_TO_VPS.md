# Chuyển máy chủ từ GCP sang VPS (OVHcloud)

Trạng thái 2026-10-11: **ĐÃ CẮT CHUYỂN.** Mọi dịch vụ chạy trên VPS OVH; trên VM GCP 5 dịch vụ đã dừng và `disable`. Chủ dự án tự xóa VM, bucket, Secret Manager và ngân sách trên GCP. Mục 0 là trạng thái hiện tại; mục 2–9 là phân tích ban đầu (mục 5 đã chốt phương án C).
Ký hiệu: **[Đã đọc]** = có trong mã, **[Đã kiểm]** = đã chạy thử, **[Chưa kiểm]** = suy luận hoặc chưa thử.

## 0. Trạng thái hiện tại

**VPS:** OVH VPS-1, `vps-6629050b.vps.ovh.ca`, IPv4 `15.235.207.5`, Singapore, Ubuntu 24.04.4 (Python 3.12.3), 2 vCPU Intel Haswell (KVM), RAM 3,8 GB, ổ 38 GB, băng thông 500 Mbps không giới hạn.
- Đăng nhập: `ssh -i %USERPROFILE%\.ssh\ovh_audio ubuntu@15.235.207.5` (khóa do agent tạo, khóa riêng chỉ nằm trên máy bạn). Root tắt; `ubuntu` có sudo không mật khẩu (`/etc/sudoers.d/90-agent`), cần cho các script deploy. **Đăng nhập SSH bằng mật khẩu đã tắt** (`/etc/ssh/sshd_config.d/00-key-only.conf`); mật khẩu vẫn dùng được ở console KVM của OVH. Mất khóa riêng thì vào bằng console hoặc OVH rescue.
- ufw bật, chỉ mở 22/tcp (cloudflared chỉ kết nối ra). Swap 2 GB, `vm.swappiness=10`.

**Kết quả cắt chuyển [Đã kiểm, 2026-10-11 ~06:00 giờ VN]:** chạy `billing-gateway/deploy/migrate_gcp_to_vps.py` (lần đầu hỏng ở bước tải về vì `pscp` không hiểu `~`, đã sửa, chạy lại). Database thật (gateway: 1 khách, 1 thanh toán, 3 job, 6 đơn; leases; admin) và khóa thật đã cài. DB thử để lại `*.trial-20261011-060028` (gateway) và `admin.sqlite3.replaced-20261010-230055` (admin), xóa được. Cloudflared đăng ký 4 kết nối ở Singapore. `/health` qua `audio-gateway.*` và `billing.*` trả 200; `admin.*` chuyển sang trang đăng nhập Cloudflare Access. Tải model qua Cloudflare về máy chủ dự án: Range đầu/cuối trả 206, link bị sửa trả 403, ~10,5 MB/s. Gemini gọi từ IP VPS trả 200. Backup đầu tiên chạy và đã kéo về máy; báo cáo tháng 9 thay bằng bản thật từ bucket. Chưa thử: một job thật từ app (Genius, TTS Basic, tải model bằng license thật), một giao dịch payOS thật.

**Lúc chuẩn bị đã cài thử trên VPS [Đã kiểm]:**
- Gateway (`audio-gateway`, 1 worker TTS × 2 luồng) và admin (`audio-admin`, `ADMIN_FULFILLMENT=off`, master key mới tạm thời) với **khóa và dữ liệu thử**. Chưa có cloudflared, chưa có tên miền.
- Model, ASR và kênh yt-dlp: 26 file, 6,81 GB, chép từ bucket bằng link ký sẵn trong 180 giây, khớp toàn bộ SHA-256 đã ghim, nằm ở `/var/lib/audio-gateway/files`.
- Tuyến `/files/`: tải trọn file trả 200, tải nối bằng Range trả 206 (đúng byte), sai chữ ký trả 403. **Chưa thử qua Cloudflare.**
- Backup vào thư mục (`/var/backups/audio-gateway`, `/var/backups/audio-admin`) và kéo về máy bằng `deploy/pull_backups.py`.

**Tốc độ TTS trên VPS này [Đã kiểm]:** 1 worker × 2 luồng, đoạn 1.194 ký tự: **50,8 giây cho mỗi 1000 ký tự**, RTF 0,92, RSS đỉnh 1,48 GiB (nạp model 11,5 s). Chậm hơn Ryzen 5800H khoảng 1,7 lần (29,8 s). Một worker khoảng 20 ký tự/giây, nên truyện 60 giờ (~4,3 triệu ký tự) mất khoảng 60 giờ. RAM chỉ đủ 1 worker.

**Mã đã đổi (chưa commit):**
- `billing-gateway`: `files.py` mới (`LocalFiles`: model, kênh yt-dlp và lưu trữ báo cáo trên đĩa, link HMAC 1 giờ). Gateway có tuyến `GET /files/<tên>?exp=&sig=` (hỗ trợ Range) và `storage_from_env` (thư mục `MODEL_DIR`/`BACKUP_DIR` được ưu tiên hơn bucket). `deploy/backup.py` lưu vào thư mục và tự dọn (35/180 ngày). `deploy/pull_backups.py` mới. `deploy_gateway.py` có `--ssh/--key`. `vm-install.sh` tạo thư mục, `FILE_LINK_SECRET`, và sửa lỗi `set -e` làm cài đặt dừng âm thầm khi file secrets thiếu khóa. Hai script deploy giờ trả đúng mã lỗi của bước cài (trước đây luôn báo "Done").
- `admin-system`: `deploy_admin.py --ssh/--key`; `admin-install.sh` dùng `BACKUP_DIR`.
- `audio-translates/packaging`: `remote_files.py` mới; `upload_model.py` và `publish_youtube_update.py` có `--ssh` (đẩy lên `MODEL_DIR` của server). App **không** cần build lại: link tải do gateway trả về và app không kiểm tra tên miền của link.
- Test: gateway 118, admin 71, `packaging/test_remote_files.py` 9 đều qua. Worker 367 có 2 lỗi ở `test_browser_cleanup` (mở Edge thật), không liên quan.

**Đang chạy trên GCP (đọc lúc 2026-10-11):** `instance-20261006-200055`, `e2-custom-2-4096`, Debian 13, gateway + admin + cloudflared + 2 timer backup đều active, `TTS_WORKERS=1`, `ADMIN_FULFILLMENT=on`. Dữ liệu: `gateway.sqlite3` 720 KB, `leases.sqlite3` 48 KB. Tunnel token ở `/etc/cloudflared/token`.

**Thứ tự cắt chuyển (đã làm):**
1. GCP: dừng `audio-gateway`, `audio-admin`, `cloudflared` (khách thấy gián đoạn vài phút).
2. GCP: chụp SQLite online (gateway, leases, admin), lấy `gateway.env`, `admin.env`, `master.key`, tunnel token về máy bạn qua IAP, xóa bản tạm trên VM.
3. VPS: dừng hai dịch vụ, thay DB thử bằng DB thật. Cài gateway bằng secrets thật (bỏ `MODEL_BUCKET`/`BACKUP_BUCKET` để dùng thư mục, thêm `TUNNEL_TOKEN`) và admin bằng `--db --replace-db` cùng `ADMIN_MASTER_KEY` thật.
4. Kiểm: `/health` qua 3 tên miền; admin qua Cloudflare Access; tải một link `/files/` từ máy bạn qua Cloudflare (có Range); gọi thử Gemini từ VPS; backup đầu tiên.
5. GCP: tắt (disable) dịch vụ, giữ VM ở trạng thái dừng vài ngày. Xóa VM, bucket, Secret Manager và ngân sách chỉ khi bạn đồng ý.
6. Xóa file secrets tạm trên máy bạn.

Quay lại GCP: chỉ khi VPS chưa phát sinh giao dịch hay license mới. Dừng dịch vụ VPS, bật lại 3 dịch vụ trên GCP.

## 1. Quyết định đã chốt

- Giữ nguyên mọi dịch vụ: Basic (TTS trên server, tính phí theo ký tự) cho khách máy yếu; Plus (TTS local) tính giá theo thực tế. Nên **vẫn cần worker TTS trên VPS**.
- Nhà cung cấp: OVHcloud VPS-1. Phương án lưu model và backup: **C** (mọi thứ trên VPS, xóa hẳn GCP sau khi ổn định). Backup: thư mục trên VPS + kéo về máy bạn.

## 2. Đang chạy gì trên VM GCP `instance-20261006-200055` [Đã đọc]

| Thành phần | Chi tiết |
|---|---|
| Gateway | `audio-gateway.service`, `127.0.0.1:8790`, file `/etc/audio-gateway/gateway.env`, dữ liệu `/var/lib/audio-gateway/` (`gateway.sqlite3`, `leases.sqlite3`, `tts-results`, `hf-cache`) |
| Admin | `audio-admin.service`, `127.0.0.1:8787`, `/etc/audio-admin/admin.env`, `/etc/audio-admin/master.key`, `/var/lib/audio-admin/admin.sqlite3` |
| cloudflared | Chạy bằng tunnel token, trỏ 3 host: `audio-gateway.*` và `billing.*` → 8790, `admin.*` → 8787. VM không mở cổng nào ra Internet |
| Backup | `audio-gateway-backup.timer` và `audio-admin-backup.timer`, 03:00 giờ VN, lên bucket `audio-gateway-backup-erp-project-8386` |
| Model và YouTube | Bucket `audio-translate-models-8386` (model 4,6 GB, ASR, `youtube/manifest.json`); gateway cấp link ký sẵn 1 giờ |
| TTS | Worker VieNeu (`TTS_WORKERS`, `TTS_THREADS`), cần ffmpeg và `libsndfile1` |

## 3. Chỗ mã đang phụ thuộc GCP, phải xử lý khi chuyển

| # | Phụ thuộc | Vị trí | Hậu quả nếu bỏ qua | Cách xử lý |
|---|---|---|---|---|
| 1 | Token và chữ ký link lấy từ **metadata server của VM** (`metadata.google.internal`, `iamcredentials ... signBlob`) | `billing-gateway/gcs.py` | Ngoài GCP không lấy được token: link tải model, cập nhật yt-dlp và backup đều lỗi `GCS_NO_CREDENTIALS` | Sửa mã (mục 4) |
| 2 | Backup dùng metadata token | `billing-gateway/deploy/backup.py` (admin dùng chung) | Backup hằng ngày không chạy | Sửa cùng #1 hoặc đổi nơi lưu |
| 3 | Triển khai qua `gcloud compute ssh --tunnel-through-iap` | `deploy/deploy_gateway.py`, `admin-system/deploy/deploy_admin.py` (mặc định project/zone/instance GCP) | Hai script không kết nối được VPS | Đổi sang `ssh`/`scp` thường (mục 4). Phải sửa mã vì script chỉ biết `gcloud` |
| 4 | **Khóa Gemini giới hạn theo IP** (lần thử 2026-10-06 báo `API_KEY_IP_ADDRESS_BLOCKED`) | Cấu hình khóa trên Google Cloud | Genius báo lỗi sau khi chuyển vì IP VPS mới chưa được cho phép | Thêm IP công khai của VPS vào danh sách của khóa **trước** khi cắt. [Chưa kiểm] khóa hiện có đang giới hạn IP nào |
| 5 | Terraform `deploy/gcp/` (VM Spot, Secret Manager, IAP, ngân sách) | `deploy/gcp/*.tf` | Không còn dùng | Bỏ. **Giữ** `deploy/tunnel/` (Cloudflare, không phụ thuộc GCP) |
| 6 | VM đang là **Spot** (bị dừng bất cứ lúc nào) | GCP | Trên VPS thuê thường không có chuyện này | Không cần làm gì, là điểm có lợi |

Điểm chung #1–#2: giữ bucket trên GCS hay không là quyết định ở mục 5.

## 4. Thay đổi mã cần làm (chưa làm)

1. `gcs.py` thêm chế độ **khóa service account** (biến `GOOGLE_APPLICATION_CREDENTIALS`): lấy token bằng JWT bearer, ký link V4 trực tiếp bằng khóa RSA. `cryptography` đã có trong `requirements.txt`, nên không cần thư viện mới. Chế độ metadata cũ giữ nguyên để chạy tiếp được trên GCP. Cần test mới, vì hiện có `test_signed_url.py` cho chế độ cũ.
2. `backup.py` dùng chung hàm lấy token của `gcs.py` thay vì tự gọi metadata.
3. `deploy_gateway.py` và `deploy_admin.py` thêm tham số `--ssh user@host` (dùng `ssh`/`scp`), bỏ `--tunnel-through-iap`. Giữ chế độ `gcloud` cũ.
4. Cập nhật `vm-install.sh`, `admin-install.sh` nếu cần (đang chạy trên Debian/Ubuntu, dùng `apt`).

Đánh đổi bảo mật: mã hiện nay ghi rõ "không có khóa riêng trên VM". Chế độ khóa service account làm khóa này xuất hiện trên VPS. Giảm rủi ro bằng cách dùng **hai service account tối thiểu**: một chỉ đọc bucket model, một chỉ tạo object ở bucket backup (không xóa, không ghi đè, như thiết kế `ifGenerationMatch=0` hiện tại).

## 5. Quyết định cần chốt: lưu model và backup ở đâu

| Phương án | Ưu | Nhược |
|---|---|---|
| A. Giữ bucket GCS, VPS dùng khóa service account | Ít việc nhất, model đã tải lên và kiểm CRC32C | Còn dùng GCP; **phí egress GCS** mỗi lần khách tải model 4,6 GB (ước lượng từ kiến thức của tôi, chưa kiểm bảng giá hiện hành: vài chục nghìn đồng mỗi lượt). Gateway giới hạn 12 lượt/ngày/license |
| B. OVH Object Storage (S3) | Cùng nhà cung cấp, băng thông thường rẻ hơn | Phải viết lại `gcs.py` theo S3 SigV4 (link ký sẵn, tải, tải lên), tải lại model, đổi manifest và script `publish_youtube_update.py` |
| C. Model nằm trên đĩa VPS, gateway phát trực tiếp | Đơn giản | Tốn băng thông và CPU VPS khi khách tải 4,6 GB; chiếm 4,6 GB ổ đĩa |

Đề xuất: **A cho đợt chuyển đầu** (rủi ro thấp nhất, chỉ đổi cách xác thực), cân nhắc B sau khi xem chi phí egress thực tế.

## 6. Cấu hình VPS

- **Hệ điều hành:** Debian 13 là bản đã chạy TTS thật (Agent.md mục 14). Nếu không có thì Ubuntu 24.04. **Ubuntu 26.04 chưa kiểm**: `requirements-tts.txt` không ghim phiên bản (`numpy`, `onnxruntime>=1.20`, `sea-g2p`...) và `vm-install.sh` dùng `python3` mặc định, nên Python quá mới có thể thiếu wheel. Muốn dùng 26.04 thì chạy thử `vm-install.sh` trên một VPS tạm trước.
- **Cấu hình khởi điểm** (theo số đo của tôi trong PLAN_TTS_VPS, chưa đo trên VPS thật): 4 vCPU, 8 GB RAM, 80 GB NVMe, 2 worker TTS với `TTS_THREADS=2`. Mỗi worker khoảng 1,5 GiB RAM. Chọn gói vCPU chuyên dụng hoặc ít bị chia sẻ.
- **Mạng:** không cần mở cổng vào (cloudflared chỉ kết nối ra ngoài). Chỉ mở SSH, ưu tiên giới hạn theo IP của bạn. Cần IPv4 cố định để đưa vào khóa Gemini.
- Bật snapshot hoặc backup của nhà cung cấp, vì máy chứa khóa ký và dữ liệu license.

## 7. Dữ liệu và bí mật phải chuyển

Không in ra màn hình, không commit, chuyển bằng kênh an toàn rồi xóa bản sao (script cài đặt đã `shred` file secrets).

| Mục | Nguồn | Ghi chú |
|---|---|---|
| `gateway.sqlite3`, `leases.sqlite3` | `/var/lib/audio-gateway/` | Dùng bản sao lưu SQLite online, **không** chép file đang mở. Có thể lấy từ backup đêm gần nhất rồi bù phần phát sinh |
| `admin.sqlite3` | `/var/lib/audio-admin/` | Chứa token license và khách. Cùng cách trên |
| `gateway.env` | `/etc/audio-gateway/` | `GEMINI_API_KEY`, `ADMIN_TOKEN`, `LEASE_MASTER_KEY`, `PAYOS_*`, `BACKUP_BUCKET`, `MODEL_BUCKET`, `BILLING_HOST`, `API_HOST`, `TTS_*` |
| `admin.env` | `/etc/audio-admin/` | `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`, `ADMIN_EMAILS`, `ACCESS_SERVICE_CLIENTS`... |
| `master.key` admin | `/etc/audio-admin/master.key` | Ghi chú admin-online: bản gốc cũng nằm ở `C:\Users\Linh\audio-translate-keys\admin-move\admin-master.key` và chưa dời offline. **Mất khóa này là mất toàn bộ khóa ký license** |
| `LEASE_MASTER_KEY` | trong `gateway.env` | Thiếu thì phần lease tắt và phải đẩy lại khóa từ admin |
| Tunnel token | Cloudflare dashboard hoặc state của `deploy/tunnel/` | Dùng lại đúng tunnel cũ (mục 8) |
| Mã nguồn VieNeu | `VieNeu-TTS-main/` | `bundle.py ... --tts ../VieNeu-TTS-main` đóng gói kèm. `hf-cache` không cần chuyển, tự tải lại |
| Cloudflare Access | Tạo trong giao diện Cloudflare | Không đổi, vì tên miền giữ nguyên |
| Không chuyển | `tts-results/`, `hf-cache/` | Tái tạo theo yêu cầu, audio chỉ giữ 24 giờ |

## 8. Thứ tự cắt chuyển, để không có hai bên cùng ghi dữ liệu

Nguyên tắc: **chỉ một gateway và một admin được hoạt động tại mọi thời điểm**. Bản admin trên PC đã đóng băng, nên admin trên VM là nơi duy nhất cấp license; hai admin chạy song song là rủi ro lớn nhất.

1. Chuẩn bị VPS: cài hệ điều hành, tài khoản và SSH, rồi sửa mã (mục 4) và test local. **Chưa** chạy cloudflared trên VPS.
2. Thử cài gateway và admin lên VPS với dữ liệu thử, kiểm `/health` nội bộ. Không dùng tunnel thật.
3. Thêm IP VPS vào khóa Gemini. Thử gọi Gemini từ VPS.
4. Chọn giờ ít khách. Báo trước nếu cần.
5. Trên VM GCP: dừng `audio-gateway` và `audio-admin` (đóng băng ghi), lấy backup SQLite cuối.
6. Chép dữ liệu và bí mật sang VPS (`REPLACE_DB=1` cho `admin-install.sh`, như hướng dẫn trong ADMIN_ONLINE mục 5), khởi động cả hai dịch vụ.
7. Dừng cloudflared trên VM GCP, rồi bật cloudflared trên VPS **với cùng tunnel token**. Tên miền không đổi, vì tunnel chỉ gắn với token, nên không cần sửa DNS. Hai connector cùng tunnel sẽ chia tải, nên đừng để cả hai chạy.
8. Kiểm: các host `audio-gateway.*`, `billing.*`, `admin.*`; `/health`; một lần sinh TTS thật; tạo link tải model; hỏi `youtube/update`; chờ webhook payOS thử; đăng nhập admin qua Cloudflare Access; backup đêm đầu tiên lên bucket.
9. Để VM GCP **dừng, không xóa**, giữ vài ngày để quay lại. Chỉ quay lại nếu VPS chưa phát sinh giao dịch hay license mới (cùng nguyên tắc rollback ở ADMIN_ONLINE mục 5). Sau khi ổn định mới xóa VM, Secret Manager, bucket mã nguồn và ngân sách.

## 9. Việc chưa kiểm chứng, cần làm trước khi cắt

- Khóa Gemini đang giới hạn IP nào (xem trong Google Cloud, API & Services → Credentials).
- payOS: webhook gọi qua tên miền `billing.*` nên không phụ thuộc IP máy chủ. [Chưa kiểm] payOS có danh sách IP cho phép không.
- Python mặc định của hệ điều hành VPS và việc `pip install -r requirements-tts.txt` chạy thành công. Sau đó sinh một đoạn TTS thật.
- Tốc độ vCPU của VPS: đo giây cho mỗi 1000 ký tự (số hiện có chỉ của Ryzen 5800H: ~29 giây).
- Băng thông ra của gói VPS (khách tải FLAC của TTS, tải app và cập nhật).
- Lần tải model đầy đủ từ app bằng license thật vẫn chưa thử (ghi chú model-download).
