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
| Công cụ 6 | **Giọng Việt → Phụ đề (.srt)**: chọn một giọng đã xong (của workflow hoặc công cụ 4), chọn thông số, ra file `.srt`. Không nhận file giọng từ ngoài app. |
| Tạo lại | Bước **Phụ đề**: tạo lại `.srt` với thông số mới, không tạo lại giọng, không tốn phí. Workflow cũ (3.0.0 trở về trước) có thêm bước này lần đầu bạn chọn nó. |
| Ghi cứng vào hình | Tùy chọn trong phần Ghép video (Studio, Công cụ 5, Tạo lại). Xem bên dưới. |

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

## Ghi cứng phụ đề vào hình
- Không bắt buộc. Với YouTube thì không cần, chỉ cần tải file `.srt`.
- **Phải mã hóa lại toàn bộ video**, không copy hình được nữa. Đo trên máy thử (4 luồng, libx264 veryfast, 30 fps): khoảng 0,3 giây xử lý cho mỗi giây giọng ở 1080p, 0,13 ở 720p và khoảng 0,07 ở 480p. Cùng bài đó, ghép copy chỉ mất khoảng 0,01 giây cho mỗi giây giọng.
- Ở Studio, Công cụ 5 và Tạo lại, tick **Ghi cứng phụ đề vào hình** rồi tick tiếp **Tôi hiểu sẽ lâu hơn…**. Chưa xác nhận thì không chạy được, và server cũng từ chối (`burn_confirmed`).
- Chữ: Arial, viền đen, cỡ khoảng 5% chiều cao hình (ngang), nhỏ hơn một chút ở hình dọc, nằm ở đáy hình.
- Chất lượng và độ phân giải theo bảng của Ghép video. Một clip, giữ nguyên độ phân giải: mã hóa một lần. Nhiều clip hoặc đổi độ phân giải: mã hóa clip nền một lần rồi mã hóa lần cuối kèm phụ đề.

## Kết quả và lỗi
- `results/<workflows|tools>/<số>/subtitle/<số>-voice.vi.srt`. Hiện trong bảng kết quả, có nút xem và tải; thẻ file ghi sẵn cách tải lên YouTube.
- Lỗi: `VOICE_MISSING` (không còn giọng hoặc manifest, kèm hướng dẫn), `SUBTITLE_FAILED` (manifest không khớp giọng). Bấm **Chạy lại giai đoạn**.

## Test
- `worker/tests/test_subtitles.py`: cộng thời gian, cắt đoạn dài, thời gian tối thiểu, không vượt quá giọng, định dạng SRT, kiểm tra thông số, đọc manifest có và không có `frames`.
- `worker/tests/test_subtitle_workflow.py`: workflow mới có `.srt`, thông số khi tạo, Tạo lại và workflow cũ có thêm bước, công cụ 6 (kể cả khi thư mục làm việc của giọng đã mất), bỏ qua giọng thì bỏ qua phụ đề, và ghi cứng thật bằng ffmpeg.
- `contracts/tests/ui_smoke.py`: thông số, xác nhận ghi cứng, công cụ 6 và Tạo lại. Chạy trên bản cài: `AudioTranslate` tạo `.srt` từ giọng thật và ghi cứng.
