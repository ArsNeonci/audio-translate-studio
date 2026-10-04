> Historical verification of the retired Qwen backend. Current setup: [Hy-MT2](TRANSLATION_LONG.md).

# Qwen CPU autotuning và slot dùng chung model

Đã tích hợp vào đường TRANSLATION hiện tại. `engine=auto` chọn llama-server
khi runtime đã cài; job Qwen đã có snapshot cũng sử dụng chính sách hiệu năng
mới khi tiến trình Translation tiếp theo khởi động. Không sửa cấu hình nội dung
dịch, không xóa checkpoint và không tự dịch lại các job đã hoàn thành.

- Một llama-server/model, nhiều slot; prompt cache bật, CPU thread pool dùng chung.
- Calibration 4/6/8 luồng, batch 128/256/512, warmup + trung vị các lần đo.
- X1/X2/X4/X8... được giữ chỉ khi hoàn thành cùng mẫu nhanh hơn ít nhất 10%.
- RAM/commit, CPU cắm điện/pin và nhiệt độ được kiểm tra riêng cho Qwen.
- SQLite được ghi từ một coordinator; parent row và phần con resume đúng ngữ cảnh.
- Pause drain các slot đang chạy; cancel bỏ phần chưa hoàn tất. Server được thu
  hồi khi stage kết thúc hoặc worker cha crash trên Windows.
- Installer đã có đường đóng gói runtime và kiểm tra checksum; chưa tạo installer mới.

## Chỉnh cấu hình

`worker/qwen-runtime.json` là file chỉnh trực tiếp. `max_slots=0` tự động theo
nhân vật lý/tài nguyên, không chặn X4; `threads=0`, `threads_batch=0`, `n_batch=0`
cho phép tự đo. Ngưỡng RAM nạp model hiện lấy `QWEN_STARTUP_AVAILABLE_GIB=2.5`
trong `.env.local`. Chi tiết trong [TRANSLATION_LONG.md](TRANSLATION_LONG.md).

Runtime chính thức: ggml-org/llama.cpp b11379, Windows CPU x64.
Archive SHA-256: ec014c2c2a27b18786d24eba3e8650d4e68b9003ca6cf91714125b71975eb7ea.
Đã cài trong `runtime/llama`, kèm thông báo giấy phép MIT và LLVM OpenMP.
Metadata model đang cài xác nhận 36 lớp, 8 KV heads, head dimension 128:
KV FP16 context 4096 = 576 MiB/slot, cộng dự phòng 128 MiB = 704 MiB/slot.
Đây là dự toán, không phải RAM tăng thêm đã đo được của X2.

## Kiểm chứng

72 test liên quan đã qua: Translation, điều phối slot, SSE, chọn cấu hình/từ chối
X2 không đủ lợi ích, resume/export, pause/cancel, CPU/pin/nhiệt độ/RAM/commit,
postprocess, lifecycle, admission, providers. Các test ASR memory được chạy với
fixture 4.5 + 3 GiB như kỳ vọng của test, không sửa file ASR hiện tại 3.5 + 2 GiB.

Phép thử model thật nằm trong fixture riêng, không thay job người dùng:

1. `data/verification/qwen-slots-1791049742350204000/report.json`: backend thật
   đã nạp model và nhận request; free RAM ban đầu 4.03 GiB, phép đo dừng ở guard
   dự phòng 1.5 GiB. Không hoàn tất calibration hay bản dịch.
2. `data/verification/qwen-slots-1791049893923973000/report.json`: dùng ngưỡng
   production 6.5 GiB; RAM trống 6.08 → 5.73 GiB, đợi 120 giây rồi pause đúng
   chính sách. Không nạp trọng số suy luận trong lượt này.

Chưa có kết quả throughput X1/X2 thật hoặc kiểm chứng bản dịch end-to-end với
server mới vì RAM hiện tại chưa đáp ứng. Không công bố hệ số tăng tốc.
Không còn llama-server chạy sau hai fixture. Chạy lại khi có đủ RAM:

```powershell
.\.venv\Scripts\python.exe worker/dev/verify_qwen_runtime.py --quick
```

`--quick` giới hạn fixture ở X2 và 16 token/1 lần đo để kiểm tra tích hợp;
production vẫn dùng chính sách trong `worker/config/qwen-runtime.json`.
