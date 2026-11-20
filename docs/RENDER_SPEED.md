# Tốc độ render video: logo, phụ đề, và tùy chọn Siêu nhanh (Ultra fast)

Đo ngày 2026-11-19 trên máy phát triển (Ryzen 7 5800H 8 nhân/16 luồng, RTX 3050 Laptop driver 566, Radeon iGPU). Giọng 180 giây, video ra 1080p30, chất lượng "Cao" (8000 kbit/s), có logo và phụ đề in vào hình. App dùng 8 luồng (một nửa số nhân luận lý). Số đo dao động khoảng ±10% giữa các lần chạy (máy laptop).

## Kết luận

1. **Bộ lọc không phải chỗ chậm.** Giải mã + logo + phụ đề libass không mã hóa đạt khoảng 305 fps; x264 `veryfast` chỉ đạt 83–110 fps. Muốn nhanh phải đổi cách mã hóa, không phải tối ưu bộ lọc.
2. **Tách 2 lượt chậm gấp 2,1 lần** (logo rồi phụ đề: 15,5 s so với 7,2 s cho 20 s video) và nén hai lần.
3. **Gộp tất cả vào 1 lệnh ffmpeg** nhanh hơn cách cũ (VIDEO rồi BURN) khi video dài bằng giọng (52 s so với 96 s), nhưng **chậm hơn** khi clip ngắn phải lặp (vẽ logo và đổi cỡ trên từng khung hình suốt độ dài giọng).
4. **Cách tốt nhất:** x264 `ultrafast` cộng một lượt mã hóa duy nhất cho toàn bộ độ dài. Clip ngắn hơn giọng: vẽ logo lên clip ngắn một lần, rồi một lượt lặp + giọng + phụ đề ("kiểu lai"). Clip phủ hết giọng: một lệnh ffmpeg làm tất cả.

| Cách làm | Clip 20 s lặp (S1) | Video 180 s (S2) |
|---|---|---|
| Cũ: VIDEO rồi BURN (veryfast) | 50–56 s | 96 s |
| 1 lệnh, veryfast | 54,5 s | 52 s |
| Kiểu lai, veryfast | 51 s | |
| **Kiểu lai, ultrafast (đang dùng cho Ultra fast)** | **19,2 s** | 40,5 s |
| **1 lệnh, ultrafast (đang dùng khi clip phủ hết giọng)** | 34 s | **32,5 s** |
| 1 lệnh, h264_amf (GPU AMD tích hợp) | 33,9 s | 30,5 s |
| Kiểu lai, h264_amf | 24,8 s | 56,1 s |

Chất lượng (VMAF so với bản gốc không nén, 30 giây đầu của một clip): cùng khoảng 97 ở 8 Mbit/s với mọi cách; ở 3 Mbit/s: veryfast 96,6, ultrafast 96,9, AMF 97,0. Chỉ đo một clip tương đối dễ nén; video nhiều chuyển động hoặc nhiễu hạt chưa đo.

## Ultra fast trong app

- Là một ô tick **Siêu nhanh (Ultra fast)** trong khung video của Studio (workflow) và của Tạo lại. **Công cụ đơn không có ô này** (server bỏ khóa `ultra` khi tạo công cụ).
- Lưu ở `job.video.ultra` (bool), gửi cùng `burn` qua `video` của `POST /api/jobs`, `POST /api/jobs/<id>/reprocess` và `POST /api/video/estimate`.
- **Không tick phụ đề:** luồng cũ, chỉ khác là lượt mã hóa clip (khi cần: logo, đổi độ phân giải, clip khác nhau) dùng `ultrafast` thay `veryfast`. Clip copy được vẫn copy.
- **Tick phụ đề + Ultra:** bước `VIDEO` tự làm luôn việc của `BURN`. Run **không có bước BURN** (`core/errors.py effective_steps`), chỉ ra **một file** `VIDEO_SUB_MP4` (`video.vi.sub.mp4`) do bước `VIDEO` công bố (`workflow/results.py output_files`), **không có video không phụ đề**.
  - Clip ngắn hơn giọng hoặc copy được: mã hóa/copy clip gốc thành "base" ngắn, rồi `-stream_loop -1` + giọng + `subtitles` một lượt mã hóa `ultrafast` (`video/merge.py merge`).
  - Clip phủ hết giọng và phải mã hóa: một lệnh duy nhất gồm clip, logo, giọng, phụ đề (`_filters(..., subtitle=...)`).
- **Tạo lại:** với run Ultra, bấm "BURN" chạy lại bước `VIDEO`; tick "thêm video phụ đề" ở bước Phụ đề cũng chạy lại `VIDEO` (không còn BURN riêng). Bỏ tick Ultra rồi ghép lại trả về hai bước và hai file như trước (file Ultra cũ thành `STALE`).
- **Ước tính:** `plan(..., ultra=True)` nhân thời gian của bảng `BURN_SECONDS_PER_SECOND` với `ULTRA_FACTOR = 0.6` (đo 0,62 cho video dài bằng giọng; clip lặp còn nhanh hơn). `/api/video/estimate` với Ultra + burn chỉ tính dung lượng của một file.
- Tự mở video khi xong: `routes_video.auto_open` mở `VIDEO_MP4`, không có thì mở `VIDEO_SUB_MP4`.

## Chưa làm / chưa đo

- **NVENC (RTX)** không chạy với bản ffmpeg đóng gói (BtbN master 2025-09, NVENC API 13 cần driver NVIDIA từ 570; máy có 566): lỗi `Required: 13.0 Found: 12.2`. Chưa thử bản ffmpeg 7.1 (tải bị chặn quyền trong phiên đo). Muốn dùng GPU phải thăm dò bằng cách mã hóa thử 1 khung hình rồi mới chọn, và lùi về x264 nếu lỗi.
- **AMF** (Radeon tích hợp) nhanh tương đương ultrafast ở video dài, ít CPU/RAM hơn một nửa, nhưng chậm hơn ở kiểu lai; **QSV** chưa đo (máy không có Intel).
- Video dài 1 giờ thật, máy khách yếu, video nhiều chuyển động: chưa đo. Ước tính tuyến tính cho 1 giờ 1080p: cũ khoảng 19–32 phút, Ultra khoảng 6,5–10 phút.
- Soft-sub (nhúng `.srt` làm luồng riêng trong MP4, vài giây, không mã hóa lại) chưa làm; TikTok/Reels vẫn cần phụ đề in cứng.

## Test

- `worker/tests/test_video_merge.py` lớp `UltraFastMergeTests`: video đen thật, chữ phụ đề là điểm sáng duy nhất. Kiểm tra phụ đề đúng giờ sau chỗ lặp clip, logo có ở mọi vòng lặp, một lệnh khi clip phủ hết giọng, preset thật của x264 trong luồng (`subme`), không để lại file tạm, ước tính và danh sách bước/file.
- `worker/tests/test_subtitle_workflow.py`: run Ultra không có BURN, chỉ có `VIDEO_SUB_MP4` của bước `VIDEO`, Tạo lại (BURN, tick ở Phụ đề, bỏ Ultra), công cụ đơn bỏ `ultra`.
- Script đo nằm ở thư mục tạm của phiên (`scratchpad/bench/ultra.py`), có thể không còn.
