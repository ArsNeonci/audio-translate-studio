# Logo và ảnh gắn lên video (trang `/overlays`)

Từ 3.3.0 (chưa build). Không tính phí. Mã: `worker/audio_translate/video/overlays.py`, `api/routes_overlays.py`, `web/app/overlays/`, `web/components/overlay/`.

## Cách dùng

1. Trang **Logo & ảnh**: *Thêm ảnh* vào thư viện (PNG, JPG, WEBP, BMP, ICO, GIF khung đầu, SVG; ≤ 10 MB; tối đa 200 ảnh). Ảnh được ffmpeg đổi thành PNG giữ nền trong suốt, thu nhỏ nếu quá 4096 px một cạnh. SVG được trình duyệt vẽ ra PNG (≤ 2048 px) trước khi tải lên. Ảnh lưu **bản chép** ở `data/overlays/assets/<sha256[:32]>.png` (khác video chỉ lưu đường dẫn, vì mẫu phải dùng được lâu dài); cùng một ảnh chỉ lưu một lần. Ảnh đang nằm trong một mẫu thì không xóa được.
2. *Mẫu mới* → chọn khung **ngang 16:9 (1920×1080)** hoặc **dọc 9:16 (1080×1920)** → *Thêm vào khung* từ thư viện → kéo ảnh, kéo ô vuông góc dưới để đổi cỡ (giữ tỉ lệ), phím mũi tên dịch 1 điểm ảnh (Shift: 10), Delete bỏ ảnh khỏi khung; ô số cho vị trí ngang/dọc/chiều rộng (điểm ảnh của khung chuẩn), thanh độ đậm 10–100 %, đưa lên/xuống lớp. Ảnh hít vào mép và giữa khung; không bao giờ ra ngoài khung. Vùng phụ đề (đáy 18 %) được đánh dấu mờ để không đặt logo đè lên phụ đề của bước `BURN`. *Lưu mẫu*.
3. Mỗi mẫu: tạo, sửa, nhân bản, xóa, **Đặt làm mặc định** (mỗi hướng khung có mặc định riêng). Tối đa 50 mẫu, 20 ảnh một mẫu, tên không trùng (không phân biệt hoa thường).
4. Mọi video tạo từ nay tự gắn mẫu mặc định theo hướng của **clip đầu tiên**. Ở Studio, Công cụ 6 và Tạo lại (Ghép video), khung chọn video có ô **Logo và ảnh gắn lên video**: *Mặc định (tên mẫu)*, *Không gắn*, hoặc một mẫu.

## Dữ liệu

- `data/overlays/overlays.json`: `{assets, templates, defaults}`, ghi nguyên tử, có khóa `management-locks/overlays.lock`.
- Vị trí lưu **theo tỉ lệ khung** (`x`, `y` góc trên trái theo chiều rộng/cao; `w` theo chiều rộng; chiều cao suy ra từ tỉ lệ ảnh) nên đúng với 480p, 720p, 1080p và mọi hình dạng clip.
- API (`/api/overlays`): `GET`; `POST /assets?name=` (thân là ảnh); `GET|DELETE /assets/<id>`; `POST /templates` (có `id` thì thay thế); `DELETE /templates/<id>`; `PUT /defaults {orientation, template|null}`. Mã lỗi `OVERLAY_*` (giao diện dịch từng mã).

## Chạy khi ghép video

- `merge.validate(config)` nhận `config.overlay` ("default", "none" hoặc id mẫu), gọi `overlays.resolve` và **ghi bản chụp mẫu vào `job.video.overlay`**; `manage.create`/`reprocess` chép các PNG vào `working/overlays/` của chính workflow. Nhờ đó sửa hay xóa mẫu/ảnh sau này không làm hỏng workflow đang chờ hay Retry; mẫu đã xóa vẫn được giữ nếu chính workflow đã lưu nó. Thiếu ảnh khi chạy → lỗi **H106** (`OVERLAY_MISSING`).
- Có logo thì **luôn mã hóa lại hình** (không copy được): `_filters` nối `overlay` sau `concat` (độ đậm bằng `colorchannelmixer`, ảnh tĩnh một khung và `overlay` lặp lại cho đến hết). Vẫn chỉ mã hóa phần ngắn hơn giữa độ dài clip và độ dài giọng rồi lặp bằng copy, nên clip 37 s phủ 1 giờ giọng chỉ tốn thêm vài giây; clip dài thì tốn theo độ dài clip. `BURN` đọc video đã ghép nên logo giữ nguyên, phụ đề nằm trên cùng.
- `POST /api/video/estimate` nhận `overlay` để ước lượng đúng chế độ `encode`.

## Test

- `worker/tests/test_overlays.py` (14, dùng ffmpeg thật): thư viện, mẫu, mặc định theo hướng, bản chụp trong workflow, **điểm ảnh** của logo đúng vị trí/cỡ/độ đậm, bản sao riêng của workflow, lỗi thiếu ảnh, ước lượng.
- `contracts/tests/run_app_contract.py` (route) và `ui_smoke.py` (thêm ảnh, kéo thả, phím, khung 16:9/9:16, lưu, mặc định, ô chọn ở Studio, chế độ tối).

## Chưa làm

- Nền xem thử bằng khung hình lấy từ video thật (khung hiện là nền ô vuông).
- Chưa đo trên video dài hàng giờ (thời gian mã hóa tính theo độ dài clip: ước 8–18 phút cho clip 1 giờ, chưa đo).
