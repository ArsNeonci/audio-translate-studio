# Tools (công cụ đơn lẻ)

Mỗi tool là một workflow bị cắt ra chỉ còn một vai trò, chạy qua **cùng orchestrator,
cùng hàng chờ, cùng Bộ phân luồng** (`core/lanes.py`) với workflow. Nhiều tool hoặc
tool và workflow chạy cùng lúc được chia luồng và tự nhường đúng như workflow
(`docs/MULTI_WORKFLOW_SCHEDULER.md`). Dữ liệu ở `data/tool-tmp/<id>`, kết quả ở
`data/results/tools/<số>`.

| Tool | Đầu vào | Bước chạy (`tool_steps`) |
|---|---|---|
| 1. Chinese Audio → Chinese Text | Tệp âm thanh **hoặc link YouTube** | `TRANSCRIPTION`; từ link: `DOWNLOAD`, `TRANSCRIPTION` |
| 2. Chinese Text → Vietnamese Text | TXT/MD/JSONL + **Forms of address (Xưng hô)** | `TRANSLATION` |
| 3. Vietnamese Text → Moderated | TXT/MD/JSONL | `MODERATION` |
| 4. Vietnamese Text → Voice | TXT/MD/JSONL + giọng, kiểu giọng | `TTS` |

## Tool 1 từ link YouTube

`POST /api/tools` với JSON `{"tool":"transcription","url":"…"}` (link được kiểm tra
như Convert). Bước Download dùng cùng hồ sơ YouTube với workflow.

## Tool 2 và Forms of address

Trong workflow, xưng hô được áp dụng ở Moderation. Tool 2 dừng sau Translation, nên
chính nó áp dụng xưng hô khi xuất từng dòng theo thứ tự (`postprocess.tool_addresser`);
checkpoint vẫn lưu bản dịch gốc. Hồ sơ xưng hô nằm trong chữ ký hoàn thành, nên đổi hồ sơ
sẽ xuất lại kết quả. Hồ sơ cũng bật lexicon/sửa giới tính như workflow có kiểu giọng.

## Xóa trong Tool History khi đang chờ hoặc đang chạy

1. Gửi tín hiệu `pause`: tác vụ nhỏ đang chạy được hoàn thành (`complete_task`), không nhận việc mới.
2. Ghi `working/delete-request.json`.
3. Khi worker thoát (hoặc ngay lập tức nếu tool còn đang chờ), `finish_abort` xóa toàn bộ:
   thư mục làm việc, thư mục kết quả, file upload, dòng trong registry.

Trạng thái hiển thị "ĐANG HỦY VÀ XÓA" trong lúc chờ. Workflow vẫn giữ quy tắc cũ
(phải dừng trước khi xóa trong History; nút Hủy và xóa ở trang chính).

Kiểm chứng (2026-10-05): `worker/tests/test_tools.py` (7 test). Chạy thật trên localhost:
tool từ link bắt đầu sau 5 s; xóa lúc đang Transcription dừng sau ~20 s và xóa sạch,
xóa lúc đang Download xong sau ~12 s.
