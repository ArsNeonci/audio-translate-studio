# Ghép video (Video merge)

Từ 3.0.0, giống nhau ở Basic và Plus, không tính phí.

Giọng Việt do app tạo được ghép vào video của người dùng. Video không bắt buộc. Có thể chọn ở ba nơi:

| Nơi | Cách dùng |
|---|---|
| Studio | Mục **Ghép video (không bắt buộc)** khi tạo workflow. Workflow có thêm bước thứ sáu `VIDEO` sau Tạo giọng. |
| Công cụ 5 | **Giọng Việt + Video → Video**: chọn một giọng đọc đã xong (của workflow hoặc công cụ 4) rồi chọn video. Không nhận file giọng từ ngoài app. |
| Tạo lại | Bước **Ghép video**: thêm video cho workflow đã xong, hoặc đổi video, độ phân giải, chất lượng rồi chạy lại. Các bước trước giữ nguyên. |

## Cách chọn file

- Nút **Chọn video…** mở hộp chọn file của Windows. Có thể chọn nhiều file một lần (`api/dialog.py`).
- App chỉ lưu đường dẫn. Video được đọc tại chỗ, không chép vào app và không bị sửa.
- Thứ tự ghép là thứ tự trong danh sách. Dùng ↑ ↓ để đổi thứ tự, ✕ để bỏ một file.
- Tiếng gốc của video bị bỏ.
- Định dạng nhận: mp4, mov, m4v, mkv, webm, avi, wmv, flv, ts, mts, m2ts, 3gp, mpg, mpeg. Tối đa 50 file.
- Trước khi ghép, app kiểm tra lại từng file. File đã đổi tên, bị chuyển chỗ hoặc bị xóa sẽ làm bước `VIDEO` lỗi `VIDEO_MISSING`, kèm hướng dẫn. Có hai cách sửa:
  - đưa file về chỗ cũ rồi bấm **Retry**;
  - hoặc vào Tạo lại → Ghép video → **Chọn lại video**.

## Quy tắc độ dài

- Video dài hơn giọng đọc: cắt phần thừa.
- Video ngắn hơn: lặp cả danh sách N = ⌈độ dài giọng ÷ tổng độ dài video⌉ lần, rồi cắt đúng tại điểm hết giọng.

## Cách chạy (`worker/audio_translate/video/merge.py`)

| Trường hợp | Cách làm |
|---|---|
| Giữ nguyên độ phân giải và các video cùng codec, cùng khung hình, cùng fps | Không mã hóa lại. Lặp và cắt bằng `-c:v copy`. Số đo cũ: 1 giờ giọng từ clip 37 giây mất 31 giây, dùng 52 MB RAM. |
| Video khác nhau, hoặc chọn độ phân giải khác | Mã hóa các video **một lần** thành một clip nền: viền đen để giữ nguyên hình, libx264 veryfast, dùng nửa số lõi CPU. Chỉ mã hóa phần cần dùng, rồi lặp clip nền bằng `-c:v copy`. Chi phí tính theo độ dài video, không theo độ dài giọng. |

- Giọng được mã hóa AAC 128 kbit/s.
- File ra là MP4 có chỉ mục ở đầu file (`+faststart`).

## Phụ đề
Từ 3.1.0 có thể ghi cứng phụ đề tiếng Việt vào hình (không bắt buộc, cần xác nhận vì phải mã hóa lại toàn bộ video). File `.srt` để tải lên YouTube thì tách riêng, xem `docs/SUBTITLES.md`.

## Độ phân giải và chất lượng

- **Độ phân giải:** Giữ nguyên gốc, 1080p, 720p, 480p. Không có mức cao hơn video lớn nhất, nên hình không bị phóng to.
- **Khung hình:** khung đầu ra theo tỉ lệ của video đầu tiên trong danh sách.
- **Chất lượng** (chỉ hiện khi phải mã hóa):

| Độ phân giải | Cao | Vừa | Nhẹ |
|---|---|---|---|
| 1080p | 8 Mbit/s | 5 Mbit/s | 3 Mbit/s |
| 720p | 4 Mbit/s | 2,5 Mbit/s | 1,5 Mbit/s |
| 480p | 2 Mbit/s | 1,2 Mbit/s | 0,8 Mbit/s |

## Dung lượng ước tính

| Nơi | App hiện |
|---|---|
| Studio (chưa có giọng) | Dung lượng cho **mỗi giờ giọng đọc** và dung lượng ổ còn trống |
| Công cụ 5 và Tạo lại (đã có giọng) | Dung lượng dự kiến và cảnh báo nếu ổ không đủ chỗ |

Khi bắt đầu ghép, app đòi khoảng 2,1 lần dung lượng dự kiến cộng 512 MB trống. Phần dư dùng cho bản tạm khi đưa chỉ mục lên đầu file. Nếu không đủ, bước báo lỗi `DISK_FULL`.

## Kết quả

- File: `results/<workflows|tools>/<số>/video/<số>-video.vi.mp4`.
- File được **chuyển** từ thư mục làm việc sang thư mục kết quả, không chép thêm bản thứ hai.
- File hiện trong cả hai bảng kết quả (Lịch sử và Lịch sử công cụ), có nút **▶ Mở video**.
- Trang chi tiết có bản xem trước, nút **Mở video** (trình phát mặc định) và **Mở thư mục** (Explorer chọn sẵn file).
- Tự mở khi xong: chỉ khi cửa sổ app đang mở. Thu nhỏ cửa sổ vẫn tính là đang mở. Trang gọi `POST /api/video/auto-open` 4 giây một lần. Mỗi video chỉ mở một lần. Video xong quá 10 phút trước sẽ không tự mở. Đặt biến môi trường `AUDIO_VIDEO_AUTO_OPEN=0` để tắt tự mở. Biến này dùng cho test tự động trên máy thật, để không bật trình phát lên màn hình.

## API

| Route | Việc |
|---|---|
| `POST /api/video/pick` | Mở hộp chọn file, trả các file đã kiểm tra |
| `POST /api/video/check` | Kiểm tra lại danh sách đường dẫn |
| `POST /api/video/estimate` | Kế hoạch (copy hay mã hóa, số lần lặp), dung lượng, ổ trống, các độ phân giải được phép |
| `GET /api/video/voices` | Các giọng đọc đã xong cho Công cụ 5 |
| `POST /api/video/open` | Mở video hoặc thư mục chứa video |
| `POST /api/video/auto-open` | Mở các video vừa xong |

Video cũng được gửi kèm khi tạo việc:
- `POST /api/jobs`: JSON `video`, hoặc query `video` khi tải tệp âm thanh lên.
- `POST /api/tools`: `{tool: "video", voice_job, video}`.
- `POST /api/jobs/<id>/reprocess`: `{step: "VIDEO", video}`.

## Test

- `worker/tests/test_video_merge.py`: dùng clip thật tạo bằng ffmpeg. Kiểm tra lặp, cắt, ghép không mã hóa lại, viền đen, độ phân giải, lỗi file và tách đường dẫn từ hộp thoại.
- `worker/tests/test_video_workflow.py`: workflow có và không có video, Tạo lại để thêm video, Công cụ 5, và Retry sau khi file bị chuyển chỗ.
- `contracts/tests/run_app_contract.py`: các route `/api/video/*`.
- `contracts/tests/ui_smoke.py`: chọn video, đổi thứ tự, ước tính dung lượng, chế độ tối, Công cụ 5 và Tạo lại.
