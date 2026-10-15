# Phụ đề tiếng Việt (.srt)

Từ 3.1.0, giống nhau ở Basic và Plus, không tính phí.

## Định dạng
- **SubRip (`.srt`), UTF-8**, theo trang hỗ trợ của YouTube (https://support.google.com/youtube/answer/2734698).
  - Mỗi phụ đề gồm số thứ tự, dòng thời gian `00:00:00,599 --> 00:00:04,160` (dấu phẩy cho mili giây), nội dung, rồi một dòng trống.
- YouTube nhận SRT và SBV là hai định dạng cơ bản có mã thời gian. Các định dạng nâng cao (WebVTT, TTML, SAMI…) chỉ hỗ trợ một phần, nên chọn SRT.
- **Tải lên YouTube:** YouTube Studio → Phụ đề → Thêm ngôn ngữ → Tiếng Việt → Tải tệp lên → **Có mã thời gian** → chọn file `.srt`.
- Nội dung là bản tiếng Việt **đã kiểm duyệt**, đúng với giọng đọc. Không phải chữ Trung gốc.

## Nơi dùng
| Nơi | Cách dùng |
|---|---|
| Studio | Mục **Phụ đề .srt (thông số, không bắt buộc)**. Mọi workflow mới đều có bước `SUBTITLE` sau Tạo giọng và đều có file `.srt`. Mục này chỉ để đổi hai thông số. |
| Công cụ 5 | **Giọng Việt → Phụ đề (.srt)**: chọn một giọng đã xong (của workflow hoặc công cụ 4), chọn thông số, ra file `.srt`. Không nhận file giọng từ ngoài app. |
| Tạo lại | Bước **Phụ đề**: tạo lại `.srt` với thông số mới, không tạo lại giọng, không tốn phí. Workflow cũ (3.0.0 trở về trước) có thêm bước này lần đầu bạn chọn nó. |
| Video có phụ đề | Bước riêng `BURN` sau Ghép video, chọn bằng ô tick **Gắn phụ đề vào video** (Studio, Công cụ 6, Tạo lại). Xem bên dưới và `docs/VIDEO_MERGE.md`. |

## Thông số
- **Số ký tự tối đa mỗi phụ đề:** 20 đến 200, mặc định 84. Mỗi phụ đề có tối đa hai dòng, ngắt gần giữa. Màn hình dọc có thể xuống nhiều dòng hơn vì khung hẹp.
- **Thời gian hiện tối thiểu:** 0,5 đến 5 giây, mặc định 1 giây.
  - Phụ đề ngắn hơn mức này được giữ đến đủ thời gian, nhưng không lấn vào phụ đề kế tiếp và không vượt quá hết giọng.

## Cách tính thời gian (`worker/audio_translate/video/subtitles.py`)
- `voice.vi.wav` là các đơn vị trong `voice/voice.manifest.jsonl` nối theo thứ tự, mỗi đơn vị kèm khoảng nghỉ `gap_after_ms`. Thời điểm bắt đầu một đơn vị bằng tổng độ dài các đơn vị trước đó cộng khoảng nghỉ.
  - Ranh giới giữa các đơn vị khớp từng mẫu âm thanh.
  - Độ dài mỗi đơn vị lấy từ `frames` mà bước Tạo giọng ghi vào manifest từ 3.1.0. Manifest cũ không có `frames` thì đọc từ file WAV của từng đơn vị. Nếu những file đó đã mất thì chia phần thời gian còn lại theo số ký tự.
  - Kiểm tra: tổng độ dài các đơn vị phải khớp độ dài `voice.vi.wav` (lệch quá 1 giây là báo lỗi, vì manifest không thuộc giọng này).
- Đơn vị dài (kiểu giọng gộp cả đoạn) được cắt thành nhiều phụ đề ở cuối câu (`. ! ? …`), rồi ở dấu phẩy, chấm phẩy, hai chấm, rồi ở khoảng trắng. Các phần nhỏ liền kề được nối lại khi còn vừa.
  - Trong một đơn vị, thời gian chia theo số ký tự. Đây là ước lượng: chính xác ở hai đầu đơn vị, lệch nhẹ ở giữa.
- Đo: 5000 đơn vị (khoảng 8,7 giờ giọng, 50.000 phụ đề) mất khoảng 0,3 giây để tính và ghi file, không kể việc đọc file WAV. Với `frames` đã có sẵn thì không cần mở file WAV nào.

## Video có phụ đề (bước `BURN`, từ 3.2.1)
- `.srt` luôn có, không điều kiện. Video có phụ đề là **lựa chọn thêm**: ô tick **Gắn phụ đề vào video** (mặc định tắt) ở Studio, Công cụ 6 và Tạo lại. Với YouTube không cần, chỉ cần tải file `.srt`.
- Ghép video (copy hình) vẫn nhanh như cũ và ra video không phụ đề. Tick thì chạy **thêm một bước riêng `BURN`** sau đó, ra file video thứ hai; chi tiết ở `docs/VIDEO_MERGE.md`.
- **Phải mã hóa lại toàn bộ hình**, không copy được nữa. Đo trên máy thử (4 luồng, libx264 veryfast, 30 fps): khoảng 0,3 giây xử lý cho mỗi giây giọng ở 1080p, 0,13 ở 720p và khoảng 0,07 ở 480p. Cùng bài đó, ghép copy chỉ mất khoảng 0,01 giây cho mỗi giây giọng. App hiện thời gian dự kiến bên cạnh ô tick.
- Tick là xác nhận duy nhất (đã bỏ ô "Tôi hiểu sẽ lâu hơn"), vì cảnh báo và ước tính nằm ngay cạnh.
- Chữ: Arial, viền đen, cỡ khoảng 5% chiều cao hình (ngang), nhỏ hơn một chút ở hình dọc, nằm ở đáy hình.
- Tạo lại: bước **Phụ đề** có ô tick (tick: tạo `.srt` rồi `BURN`, không ghép lại; không tick: chỉ `.srt`); bước **Gắn phụ đề vào video** chạy lại riêng `BURN`.

## Kết quả và lỗi
- `results/<workflows|tools>/<số>/subtitle/<số>-voice.vi.srt`. Hiện trong bảng kết quả, có nút xem và tải; thẻ file ghi sẵn cách tải lên YouTube.
- Lỗi: `VOICE_MISSING` (không còn giọng hoặc manifest, kèm hướng dẫn), `SUBTITLE_FAILED` (manifest không khớp giọng). Bấm **Chạy lại giai đoạn**.

## Test
- `worker/tests/test_subtitles.py`: cộng thời gian, cắt đoạn dài, thời gian tối thiểu, không vượt quá giọng, định dạng SRT, kiểm tra thông số, đọc manifest có và không có `frames`.
- `worker/tests/test_subtitle_workflow.py`: workflow mới có `.srt`, thông số khi tạo, Tạo lại và workflow cũ có thêm bước, công cụ 5 (kể cả khi thư mục làm việc của giọng đã mất), bỏ qua giọng thì bỏ qua phụ đề, bước `BURN` riêng (ghi cứng thật bằng ffmpeg, video không phụ đề vẫn giữ) và Tạo lại có/không tick.
- `contracts/tests/ui_smoke.py`: thông số, ô tick video phụ đề, thứ tự công cụ 5 và 6 và Tạo lại. Chạy trên bản cài: `AudioTranslate` tạo `.srt` từ giọng thật và ghi cứng.
