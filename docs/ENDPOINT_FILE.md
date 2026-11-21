# Tệp địa chỉ có chữ ký

App tìm server (gateway và trang Billing) qua một tệp nhỏ có chữ ký đặt ở nơi tĩnh, nên đổi tên miền không cần bản app mới.

- `worker/config/genius.json`: `endpoint`, `billing_url` (địa chỉ app được phát hành kèm) và `directory` (danh sách địa chỉ `https://…` của các nơi giữ cùng một cặp tệp
  `endpoint.json` + `endpoint.json.sig`). Danh sách trống thì tính năng tắt.
- `worker/config/endpoint-keys.json`: khoá công khai Ed25519 được tin. Khoá riêng ở ngoài repo.
- `worker/audio_translate/core/endpoint.py`: đọc, kiểm chữ ký, lưu bản mới nhất ở `data/endpoint/directory.json`.
  - Chỉ nhận tệp đúng `schema`, `serial` là số nguyên ≥ 1, `gateway` và `billing` dạng `https://tên-miền[:cổng]` (không đường dẫn).
  - Bản có serial cũ hơn bản đã lưu bị bỏ; bản đã lưu được kiểm chữ ký lại mỗi lần đọc.
  - Đọc khi mở app (tối đa mỗi ngày) và khi một cuộc gọi tới server hỏng ở mức mạng (tối đa mỗi 10 phút); nếu địa chỉ đã đổi thì cuộc gọi được gửi lại.
  - Chỉ có một lệnh GET không kèm giấy phép tới các nơi này.
- `genius.settings()` và `api/license.py` (`gateway_endpoint`, `billing_url`) trả địa chỉ từ tệp đã đọc nếu có, nếu không thì địa chỉ phát hành kèm.
- `packaging/publish_endpoint.py`: tạo khoá (`--init-key`), ký và ghi tệp (`--gateway --billing --out`), đọc lại từ mọi nơi (`--check`).
- Test: `worker/tests/test_endpoint.py`. Biến `AUDIO_ENDPOINT_MIRRORS` (cách nhau bằng dấu phẩy) thay cho `directory` khi thử; `worker/tests/__init__.py` đặt nó rỗng để không test nào ra mạng.

Quy trình vận hành (đổi domain, thứ tự bước) nằm trong repo riêng tư của server.
