# TTS CPU optimization

Đã tích hợp vào đường TTS hiện tại, áp dụng khi tiến trình TTS mới khởi động.
Không sửa snapshot giọng/precision, không xóa WAV hay tự chạy lại job người dùng.

- Calibration X1 4/6/8 luồng; thử thêm worker với tổng luồng không vượt nhân
  vật lý. Mức X mới chỉ được giữ khi hoàn thành cùng mẫu nhanh hơn ít nhất 10%.
- Worker có VieNeu engine riêng. RAM/commit, CPU 85%/65% pin và nhiệt độ được
  kiểm tra; worker dư được thu hồi khi rảnh. Không chặn cứng X4.
- Một coordinator ghi SHA/metadata/rename WAV, ghép manifest đúng thứ tự.
  Pause drain, cancel thu hồi worker trước khi dọn WAV tạm; lỗi một worker vẫn
  lưu kết quả hợp lệ của worker khác. Windows Job Object ngăn worker mồ côi.
- Cache theo văn bản/giọng/config/provider/revision, dedup cùng cửa sổ, giới hạn
  LRU 1000 mục/1 GiB với dọn định kỳ. Reprocess/fresh Retry bỏ qua cache để sinh
  mới. Dòng rỗng giữ WAV tối thiểu và không nạp model.
- Profile calibration tái sử dụng tối đa 7 ngày; hiệu năng tách khỏi fingerprint
  WAV. TTS CPU vẫn dùng FP32 theo cấu hình hiện tại; không tự chuyển INT8.
- Đường installer đã bao gồm policy/module mới; chưa tạo installer phát hành.

Chỉnh trực tiếp **`worker/tts-runtime.json`**. Hướng dẫn:
[TTS_CPU.md](TTS_CPU.md). Telemetry `working/tts-runtime.json`, log worker
`working/tts-worker-*.log`, profile `data/config/tts-profile-*.json`.

## Kiểm chứng

85 kiểm thử liên quan đã qua, gồm 13 test TTS mới dùng multiprocessing thật
với âm thanh fixture: thứ tự/timestamp, ghép frame, pause/resume, cancel, drain
khi lỗi, cache/corruption/voice/eviction/reprocess, chọn cấu hình và dùng lại
profile, chặn tăng worker theo CPU/RAM/commit. Các test ASR sử dụng fixture
4.5 + 3 GiB; cấu hình ASR hiện tại của người dùng được giữ nguyên.

Lệnh regression: `.venv/Scripts/python.exe worker/dev/verify_runtime_tests.py`.

Phép thử VieNeu thật đầu tiên nằm ở
`data/verification/tts-workers-1791054532556141100/report.json`:
RAM trống trước 2.52 GiB, sau 2.46 GiB. Guard yêu cầu khoảng 3 GiB cho worker
đầu (1.5 GiB dự toán + 1.5 GiB dự phòng), đợi 120 giây rồi pause đúng chính
sách. Lượt đầu chưa nạp model TTS.

Lượt thứ hai, khi RAM tăng lên 3.22 GiB, đã hoàn tất:
`data/verification/tts-workers-1791055521538651800/report.json`.

- X1, 4 luồng, FP32, giọng Hải Đăng.
- Cùng mẫu 4 câu: lần đo sau warmup mất 7.047 giây, RTF 0.629
  (khoảng 1.59 lần tốc độ phát). WAV đầu ra cuối dài 11.52 giây.
- RSS worker đỉnh 1.275 GiB, RAM trống thấp nhất 1.859 GiB.
- X2 không được nạp vì RAM còn lại không đáp ứng worker thêm + dự phòng.
- Đúng manifest/timestamp, tổng frame WAV ghép và completed-stage resume.
- Tổng fixture 47.02 giây gồm nạp/reload model, warmup, đo và sinh kết quả.

Đây là tốc độ X1 trên mẫu ngắn, không phải hệ số cải thiện so với hệ thống cũ
hay bằng chứng X2 nhanh hơn. Chưa đo đầy đủ 4/6/8 luồng trên bản ghi dài.

Khi RAM đủ để đo thêm X2, chạy lại fixture độc lập:

```powershell
.\.venv\Scripts\python.exe worker/dev/verify_tts_runtime.py --quick
```

Quick chỉ dùng 4 luồng, tối đa X2, một lần đo sau warmup, cache tắt và assets
offline trong fixture; không đổi chính sách production. Bỏ `--quick` để đo đầy đủ.
