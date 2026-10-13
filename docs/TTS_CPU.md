# TTS CPU: worker +1 theo hiệu quả đo được và cache

TTS CPU dùng VieNeu v3 Turbo ONNX với engine riêng trong mỗi worker. Bộ điều
phối duy nhất ghi checkpoint và manifest theo ID/timestamp gốc. Giọng, FP32,
48 kHz, max_chars=256 và max_new_frames=1000 giữ theo adapter hiện tại.
GPU hoặc `enabled=false` tiếp tục dùng đường adapter tuần tự hiện có.

## File chỉnh trực tiếp

**`worker/config/tts-runtime.json`** được đọc lại trong điều phối. Có thể đặt đường dẫn
khác qua `TTS_RUNTIME_CONFIG`. Job Hy-MT2/TTS đã tạo vẫn nhận chính sách mới khi
tiến trình TTS tiếp theo khởi động, không cần sửa snapshot hoặc xóa WAV.

- `threads=0`: worker đầu dùng 4 luồng (không vượt nhân vật lý). Worker thêm vào
  dùng `nhân ÷ (số worker + 1)` luồng. Giá trị dương ép số luồng mỗi worker.
- `max_workers=0`: tự động; giới hạn cuối là nhân vật lý, RAM/commit, CPU/nhiệt
  độ, mục tiêu của Bộ phân luồng khi chạy nhiều workflow và lợi ích đo được.
- **Không còn hiệu chuẩn trước** (đã bỏ cơ chế nhân đôi 1→2→4 qua phép đo và
  profile `tts-profile-*.json`, 2026-10-05). TTS bắt đầu đọc ngay với 1 worker.
- `scale_up_seconds=10`: sau 10 giây tài nguyên ổn định (CPU dưới mục tiêu − 5%,
  đủ RAM cho thêm 1 worker, không nóng) thì nạp **thêm 1 worker** trong nền;
  các worker khác vẫn đọc trong lúc nạp.
- `gain_window_seconds=30`: tốc độ (ký tự nguồn/giây) đo 30 giây trước và 30 giây
  sau khi worker mới sẵn sàng. **Nhanh hơn bất kỳ mức nào thì giữ**; không nhanh
  hơn thì gỡ worker đó khi nó rảnh.
- `retry_seconds=600`: mức worker đã thử không nhanh hơn sẽ không thử lại trong
  10 phút. Logic dùng chung với Translation: `worker/audio_translate/core/scaling.py`.
- `cpu_target=85`: tối đa 65% khi dùng pin. `temperature_limit=85` °C nếu hệ
  điều hành cung cấp cảm biến; không có cảm biến thì không đo được nhiệt độ.
- `reserve_gib=1.5`: RAM/commit dự phòng. `initial_worker_gib=1.5` là dự toán
  ban đầu, không phải số đo; sau nạp/sinh dùng RSS worker đã đo × 1.25 làm dự toán
  bảo thủ cho worker thêm. Ngưỡng khởi động mặc định khoảng 3 GiB trống.
- `memory_wait_seconds=120`: thiếu RAM lúc nạp hoặc không thể cấp việc thì pause,
  giữ WAV/checkpoint đã hoàn thành. RAM/commit dưới 256 MiB dừng khẩn cấp.
- `observe_seconds=10`: chu kỳ telemetry; CPU lấy mẫu tối đa một lần/giây.
  Quá tải giảm cấp việc, thu hồi worker dư khi rảnh; cấu hình luồng thay ở ranh
  giới batch đã drain. Tài nguyên hồi phục có thể đo lại, tránh thử liên tục.

Sinh TTS có thể ngẫu nhiên; đổi worker/luồng không bảo đảm audio bit-for-bit giống
nhau. Cần nghe mẫu để kiểm tra chất lượng; chương trình không tự đánh giá giọng đọc.

## Checkpoint và cache

Chỉ đọc `transcript.vi.moderated.jsonl`. Cửa sổ read-ahead hữu hạn (2× nhân vật
lý, tối thiểu 4 dòng), không nạp cả bản ghi dài vào RAM. WAV hoàn chỉnh được kiểm
tra mono/PCM16/48kHz, băm và ghi metadata trước rename. Kết quả hoàn thành lệch
thứ tự vẫn có checkpoint riêng và manifest cuối được ghép đúng nguồn.

Pause ngừng cấp việc và lưu toàn bộ WAV đang chạy; cancel thu hồi worker trước
khi xóa WAV tạm. Lỗi một worker drain kết quả hợp lệ của worker khác rồi báo lỗi.
Windows Job Object thu hồi worker khi process cha crash; mỗi stage chạy trong
process riêng, nên model Hy-MT2 được giải phóng trước TTS.

`cache_enabled=true` dùng cache nội dung trong `data/tts-cache`: văn bản nguyên
vẹn, giọng/config/provider/revision phải trùng. Không lấy timestamp làm cache
key; mỗi dòng vẫn có WAV và timestamp riêng. Văn bản trùng trong cùng cửa sổ
chỉ sinh một lần. Cache lỗi SHA/format bị bỏ qua. Cache là tối ưu tùy chọn, không
thay checkpoint của job. Dọn LRU sau mỗi 16 mục mới, mặc định 1000 mục/1 GiB,
nên có thể vượt nhẹ giữa hai lần dọn. Chỉnh `cache_max_entries`, `cache_max_gib`.
Reprocess hoặc fresh Retry TTS bỏ qua cache nội dung để thực sự sinh lại âm
thanh; WAV mới vẫn cập nhật cache. Resume thông thường giữ khả năng dùng cache.
Production giữ cách nạp/tải model hiện có của VieNeu; sau nạp, cập nhật chữ ký
revision trong cache/profile nếu weights đổi. Fixture kiểm chứng ép offline để
chỉ dùng model đã tải; thiếu assets báo lỗi thay vì tự tải trong phép đo.

Telemetry: `working/tts-runtime.json`; log worker: `working/tts-worker-*.log`.

## Kiểm chứng

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s worker/tests -t worker -p test_tts_runtime.py -v
.\.venv\Scripts\python.exe worker/dev/verify_runtime_tests.py
.\.venv\Scripts\python.exe worker/dev/verify_tts_runtime.py --quick
```

`--quick` chỉ ép fixture riêng thử 4 luồng, tối đa X2, một lần đo sau warmup,
tắt cache để phép đo không bị skip. Không sửa job người dùng/chính sách production.
Thử đầy đủ bằng cách bỏ `--quick` khi RAM đủ. Kết quả gồm WAV thật để nghe và
`report.json`; RTF nhỏ hơn 1 nghĩa là tạo âm thanh nhanh hơn thời gian phát.
