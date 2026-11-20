# Bộ khung biểu mẫu (Studio, Công cụ, Tạo lại)

Làm ngày 2026-11-19. Mục tiêu: người không rành công nghệ nhìn là hiểu — mỗi chức năng một thẻ, chữ ba cỡ, ô nhập và ô tick đủ lớn, không có gì bị giấu sau nút bấm mở/đóng.

## Phân tích giao diện cũ (vì sao khó nhìn)

| Vấn đề | Ở đâu |
|---|---|
| Ô tick 18 px, mô tả 12 px xám nhạt | `.auto-tts-toggle` |
| Nhiều cỡ chữ lẫn lộn (11, 12, 13, 14, 16 px) cho cùng một vai trò | mô tả, nhãn, giá trị |
| Ô chọn / ô nhập không viền rõ hoặc bé (viền 1 px, cao ~ 30 px) | `.subtitle-options`, `.video-options`, `select` |
| Chức năng bị giấu sau `<details>` ("Phụ đề", "Ghép video") nên người dùng không biết có | Studio |
| Hộp lồng hộp (khung phụ đề trong khung video trong trang), khoảng cách mỗi chỗ một kiểu | `.video-picker`, `.import-panel` |
| Nút "Chuyển đổi" nằm ở đầu, các thiết lập nằm dưới nó | Studio |

## Ba loại chữ, ba cỡ (mọi nơi trong form)

| Loại | Cỡ | Ví dụ |
|---|---|---|
| Tên chức năng (tiêu đề thẻ, `.fsec-title`) | 20 px, đậm | "Giọng đọc tiếng Việt" |
| Tên thông số (nhãn, `.field-label`) và giá trị nhập/chọn | 16 px, đậm vừa / thường | "Độ phân giải", "1080" |
| Mô tả (`.fsec-desc`, `small`) | 14 px, màu nhạt | một câu giải thích |

## Khoảng cách và điều khiển

- Mỗi chức năng là **một thẻ** (`FormSection`, viền 2 px, bo góc, nền riêng). Các thẻ cách nhau **32 px**, các khối trong một thẻ cách nhau **20 px**.
- Thẻ Studio và Tạo lại có số thứ tự (1, 2, 3…) để người dùng biết đi từ trên xuống.
- Ô nhập, ô chọn, chip: cao tối thiểu **48 px**, viền **2 px** màu đủ tương phản; ô nhập link và ô chọn giọng 56 px.
- Chip (lựa chọn một trong nhiều): chip đang chọn có nền đậm **và dấu ✓**, không chỉ đổi màu.
- Ô tick: **28 px**, viền 2 px, dấu ✓ lớn; cả thẻ (viền, nền) là vùng bấm; khi tick thẻ đổi nền.
- Không còn `<details>`: "Phụ đề .srt" và "Ghép video" luôn mở, ghi rõ "(không bắt buộc)".
- Nút chạy chính (Chuyển đổi / Tạo lại / Chạy công cụ) nằm **cuối form**, cao 60 px, kèm một câu nhắc. Trên Studio nút này nằm ngoài `<form>` nhưng gắn bằng `form="convert-form"`, nên Enter trong ô link vẫn gửi form.

## Cách dùng trong mã

- `web/app/forms.css` (nạp sau `dark.css`): mọi quy tắc nằm dưới `.form-kit` (đặt trên `.hero` của Studio, Công cụ, Tạo lại). Màu lấy từ biến `--fk-*`; chế độ tối chỉ đổi các biến (và vài quy tắc nâng độ ưu tiên cho chip, nút chọn giọng, vì quy tắc tối cũ cụ thể hơn).
- `web/components/common/form-section.tsx`: `FormSection({ step?, title, description?, children })` và `FormStack`.
- Thành phần con (`VoiceSelect`, `TranslationModeSelect`, `AddressProfileSelect`, `ManualTranslationToggle`, `SubtitleOptions`, `VideoPicker`, `ImportPanel`, `SplitTool`, `RenderTool`) giữ tên lớp cũ; trong thẻ chúng tự bỏ viền/nền riêng (`.fsec :is(.video-picker, .import-panel, …)`), nên không có hộp lồng hộp.
- `SubtitleOptions` không còn `<fieldset>`/`<legend>` (tiêu đề đã nằm ở thẻ).
- Chữ mới: khóa `fk*` trong `web/lib/i18n/ui-text.ts` (Việt + Anh).
- Trang Logo & ảnh, Lịch sử, Cài đặt, bảng nhân vật và bảng tiến độ ở cuối trang Tạo lại **chưa** đổi sang bộ khung này.

## Kiểm chứng

`contracts/tests/ui_smoke.py` có thêm: không còn `<details>` trên Studio, các thẻ cách nhau đều (≥ 28 px), ba cỡ chữ (20/16/14), ô nhập/chip/thẻ tick cao ≥ 48 px, ô tick rộng ≥ 26 px; chụp ảnh sáng/tối của Studio, Tạo lại, Công cụ vào thư mục tạm. Lưu ý khi chụp: nút có hiệu ứng chuyển màu 0,2 giây, phải chờ 0,6 giây sau khi đổi giao diện sáng/tối mới chụp.
