# Công cụ 8 (gắn phụ đề) và 9 (gắn logo) lên video của người dùng

Mã nguồn đã xong và đã test, **chưa build, chưa phát hành** (dự kiến 3.2.9). Không tính phí. Mã: `worker/audio_translate/video/merge.py` (`render`, `render_plan`, `audio_codec`), `video/subtitle_import.py`, `workflow/manage.py` (`create`), `api/routes_jobs.py`, `api/routes_video.py` (`/api/video/render-estimate`), `web/components/video/render-tool.tsx`.

## Cách dùng

| | Công cụ 8: Video + Tệp phụ đề → Video có phụ đề | Công cụ 9: Video → Video gắn logo |
|---|---|---|
| Đầu vào | một video (hộp chọn tệp Windows, chỉ lưu đường dẫn) + một tệp **.srt hoặc .vtt** tải lên (≤ 5 MB) | một video |
| Logo | tùy chọn; mặc định **Không gắn**; có thể chọn một mẫu (cùng một lượt mã hóa) | bắt buộc: mẫu mặc định theo hướng khung của video, hoặc mẫu chọn tay |
| Khác | độ phân giải (Giữ nguyên, 1080, 720, 480), chất lượng (Cao, Vừa, Nhẹ) | như bên trái |
| Bước | `RENDER` | `RENDER` |
| Kết quả | `results/tools/<số>/video/<số>-video.mp4` (kiểu tệp `VIDEO_MP4`, có nút **Mở video**, tự mở khi xong) | như bên trái |

Mỗi lần chạy **một video** (hộp chọn cho nhiều tệp thì dùng tệp đầu tiên và báo). Video được đọc tại chỗ, không chép và không bị sửa; nếu tệp bị đổi tên/chuyển/xóa khi chạy thì lỗi `VIDEO_MISSING` (H101).

## Cách xử lý (một lượt ffmpeg)

`[video] → (độ phân giải, viền đen giữ nguyên hình) → (logo) → (phụ đề libass) → libx264 veryfast, +faststart`.

- **Hình** luôn được mã hóa lại (copy không vẽ được). Thời gian **tính theo độ dài video**, không có gì để lặp như ghép video: dùng số đo của bước `BURN` (khoảng 0,3 s xử lý cho mỗi giây video ở 1080p, 0,13 ở 720p, 0,07 ở 480p; một video 30 phút ở 1080p mất khoảng 9 phút). Trang hiện thời gian và dung lượng dự kiến cùng ổ trống (`render_estimate`); thiếu chỗ thì chặn.
- **Tiếng gốc** được giữ: sao chép nếu MP4 chứa được (aac, mp3, ac3, eac3, alac, mp2), không thì đổi sang AAC 192 kbit/s; video không có tiếng thì ra video không có tiếng.
- **Chữ phụ đề** dùng đúng kiểu của bước `BURN` (`subtitle_style`: Arial, viền đen, cỡ khoảng 5 % chiều cao ở hình ngang, nhỏ hơn ở hình dọc, nằm đáy).
- **Logo** dùng lại mẫu của `docs/OVERLAYS.md`: bản chụp mẫu và bản sao ảnh nằm trong chính lần chạy (`render.overlay`, `working/overlays/`), nên sửa/xóa mẫu sau đó không ảnh hưởng.

## Tệp phụ đề (`subtitle_import.py`)

- Nhận SRT và WebVTT (mốc `mm:ss.mmm` hoặc `hh:mm:ss.mmm`, bỏ dòng cài đặt, bỏ thẻ `<c>`, `<i>`, `{\an8}`). **Chưa hỗ trợ ASS** (giữ kiểu chữ riêng): quyết định ngày 2026-11-18.
- Mã hóa: BOM UTF-8/UTF-16, UTF-8, UTF-16 không BOM, cp1258 (tiếng Việt Windows), cp1252; văn bản chuẩn hóa NFC (cp1258 viết chữ bằng chữ gốc cộng dấu rời).
- Dòng hỏng (không có chữ, giờ sai, kết thúc trước lúc bắt đầu) bị bỏ và đếm; sắp xếp theo giờ; chuẩn hóa thành `working/render.srt` UTF-8. Tệp gốc của người dùng không bị sửa. Không còn dòng nào dùng được thì từ chối.
- Chưa có cảnh báo "phụ đề dài hơn video" trên giao diện (báo cáo có `longer_than_video`/`beyond_video` trong `job.render.subtitle_report`, chưa hiện).

## Dữ liệu và API

- `job.render = {video, resolution, quality, overlay, subtitle, subtitle_report}`; `tool_type` là `subtitle_burn` hoặc `overlay`; trạng thái `VIDEO_RENDERING`; `results.RENDER_TOOLS`/`RENDER_FILES` đăng `VIDEO_MP4` ở bước `RENDER`. Tách khỏi `FILES` vì bước `VIDEO` của workflow cũng có `VIDEO_MP4` ở đường dẫn khác.
- `POST /api/tools`: công cụ 9 gửi JSON `{tool: "overlay", video: {files: [..], overlay, resolution, quality}}`; công cụ 8 gửi tệp phụ đề `?tool=subtitle_burn&name=&video=<json>` (≤ 5 MB).
- `POST /api/video/render-estimate` `{path, resolution, quality, subtitle, overlay}`: kế hoạch, thời gian, dung lượng, ổ trống.
- Mã lỗi mới: **H107** (mất tệp phụ đề đã nạp), **H108** (ffmpeg lỗi khi xuất video), **H109** (lần chạy không có phụ đề hay logo); `H101` (video), `H106` (ảnh logo) dùng lại.

## Test

- `worker/tests/test_render_tools.py` (14, ffmpeg thật): đọc SRT/VTT và các bảng mã, tệp sạch, từ chối; công cụ 8 vẽ chữ đúng lúc có phụ đề (so điểm ảnh với clip gốc), giữ tiếng aac, logo cùng lượt, công cụ 9 đúng vị trí và cần mẫu, mẫu mặc định theo hướng, đúng một video, video bị chuyển chỗ báo H101, tiếng vorbis đổi sang AAC và video im lặng vẫn im lặng, ước lượng, tên tệp kết quả không đụng workflow.
- `worker/tests/test_api_routes.py` (`RenderToolRouteTests`), `contracts/tests/run_app_contract.py` (`/api/video/render-estimate`), `contracts/tests/ui_smoke.py` (hai thẻ mới, chọn video, ước lượng, từ chối tệp sai loại, chế độ tối).

## Chưa kiểm chứng

- Thời gian thật trên video dài (số đo lấy từ `BURN`, công cụ 9 không có phụ đề nên có thể nhanh hơn một chút).
- Tệp phụ đề thật của khách (nhiều kiểu lạ), phụ đề dài hơn video, video 10-bit/HDR (ép về yuv420p 8-bit).
- Chạy qua HTTP với giấy phép đang hoạt động và trên bản cài đặt.
