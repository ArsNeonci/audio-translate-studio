# Hạn dùng hàng tháng (gia hạn qua GitHub, không cần máy chủ)

Dành cho khách mua bản vĩnh viễn nhưng trả phí hàng tháng. Từ bản 4.2.0.

- Người bán đăng tệp `status.json` cạnh `endpoint.json` ở mọi nơi trong `directory` của `worker/config/genius.json` (GitHub Pages và Cloudflare Worker):
  `{"serial", "updated", "strict", "message", "devices": {"<mã thiết bị>": "<hạn dùng UTC>"}}`.
- **Mã thiết bị** = 16 ký tự hex đầu của SHA-256 mã máy (`api/paid_until.py: device_code`). Trang Giấy phép hiện mã này kèm nút sao chép; `GET /api/license?machine=1` trả `device_code`.
- App đọc tệp khi mở, rồi tối đa 4 giờ một lần (15 phút khi đang bị khoá; nút "Kiểm tra lại" đọc ngay). Bản đã đọc lưu ở `data/license/paid-until.json`.
- **Khoá:** hết hạn thì `license_denial()` (`api/license.py`) trả 403 `PAYMENT_DUE`, kể cả khi không có mạng. Chỉ chặn việc bắt đầu mới (tạo job, lệnh, bộ lập lịch khởi chạy);
  workflow đang chạy không bị ngắt; tải file trong History vẫn được.
- **Đồng hồ:** so với giờ mới nhất từng thấy (đồng hồ máy, hoặc tiêu đề `Date` của lần đọc cộng thời gian trôi qua), không bao giờ lùi, nên chỉnh đồng hồ máy về trước không kéo dài được hạn.
- Thiết bị không có trong tệp: được dùng, trừ khi `"strict": true`. Không có nơi nào trong `directory` (phát triển, test): tính năng tắt.
- Serial thấp hơn bản đã lưu bị bỏ (một nơi chậm cập nhật không làm mất bản mới). Tệp hỏng không đổi gì.
- Giao diện: dải nhắc 5 ngày cuối và thông báo quá hạn (`components/license/license-status.tsx: PaidUntilNotice`), chuỗi `PAYMENT_DUE`, `paidDueSoon`, `paidOverdue`, `paidDevice`, `paidStill`, `deviceCode` trong `lib/i18n/ui-text.ts`.
- Mức bảo mật thấp có chủ ý: tệp không ký, việc chặn ở phía Python (lõi Rust phát hiện nếu mã app bị sửa).
- Test: `worker/tests/test_paid_until.py`. Trang quản lý của người bán và quy trình nằm ở repo `audio-endpoint` (`manage/`) và repo riêng của máy chủ.
