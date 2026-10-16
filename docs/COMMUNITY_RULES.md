# Quy tắc kiểm duyệt cộng đồng: danh sách nạp sẵn (3.2.4)

App có sẵn một danh sách từ cần thay (545 từ) để người dùng khỏi nhập từng từ. Danh sách là của người dùng: sửa, xóa, thêm như bình thường ở trang Quy tắc cộng đồng.

## Cách hoạt động
- Nguồn: `worker/config/community-rules.json` (từ gốc → từ thay thế). Khi đóng gói, tệp này được mã hóa vào kho tài sản (`community-rules.vault`) như các dữ liệu ngôn ngữ khác và tệp rõ bị loại khỏi bộ cài.
- **Nạp một lần** cho mỗi máy, vào lần đầu mở danh sách hoặc chạy kiểm duyệt (`moderation/rules.py`, `ReplacementRules.seed_once`):
  - máy chưa có quy tắc: nạp cả danh sách;
  - máy đã có quy tắc riêng: giữ nguyên, chỉ thêm các từ còn thiếu (cách viết của người dùng được ưu tiên);
  - sau đó ghi dấu `replacement-rules.seeded.json`; từ người dùng đã xóa không bị đưa lại, và xóa hết cũng không nạp lại.
- Chưa đọc được danh sách (ví dụ chưa kích hoạt giấy phép nên chưa mở được kho) thì chưa ghi dấu; lần sau thử lại.
- Biến `AUDIO_NO_RULE_SEED=1` tắt việc nạp (dành cho test).

## Lưu ý về cách khớp từ
Quy tắc khớp **đúng từng ký tự, phân biệt hoa thường** (và không đệ quy; từ dài nhất thắng). Danh sách nguồn viết hoa chữ đầu ("Giết"), nên chỉ khớp ở đầu câu hoặc khi bản dịch có viết hoa như vậy. Khớp mọi chỗ cần thêm các dạng viết thường ("giết"), nhưng một số từ ("chim", "mông", "ngực") sẽ thay cả trong câu bình thường, nên việc này cần chủ sản phẩm quyết định.

## Tạo danh sách từ tệp nguồn
`CommunityModerationRules.md` (hai cột cách nhau bằng tab, dòng đầu là tiêu đề) → bỏ khoảng trắng thừa, chuẩn hóa NFC, bỏ từ trùng (giữ dòng đầu tiên; trùng: Bướm, Địt mẹ, Lồn, Cặc).

## Test
`worker/tests/test_community_rules.py`: nạp lần đầu, sửa/xóa/thêm, không nạp lại sau khi xóa, giữ quy tắc có sẵn, thử lại khi chưa đọc được, danh sách hợp lệ cho bộ thay thế.
