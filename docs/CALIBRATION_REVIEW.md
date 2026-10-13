# Đánh giá thiết kế hiệu chuẩn (2026-10-04)

Đánh giá tĩnh qua đọc mã, chưa đo thời gian chạy. Phạm vi: TRANSCRIPTION 3/4 (ASR), TRANSLATION (Hy-MT2) và TTS. Chưa kiểm tra `file_lock` xử lý thế nào khi hai workflow cùng calibrate. Chưa sửa mã theo đánh giá này.

## Tóm tắt

| Stage | Cách làm | Nhận xét |
|---|---|---|
| ASR 3/4 | Benchmark thật, cache 7 ngày, kiểm chứng lại khi chạy | Tốt nhất ba stage; còn điểm yếu về mẫu đo và nhiễu |
| Translation | Không benchmark; điều chỉnh theo RAM/CPU/GPU/nhiệt đang rảnh | Đơn giản; không kiểm chứng thêm slot có nhanh hơn; có nguy cơ dao động |
| TTS | Benchmark RTF, cache 7 ngày, đo lại mỗi 10 phút | Đo đúng thứ cần đo; đo lại giữa job tốn kém |

## ASR 3/4 (`transcription/asr_runtime.py`)

Cách làm: fingerprint (CPU, số lõi, phiên bản funasr/torch, kích thước/mtime model) → cache `data/config/asr-autotune.json` 7 ngày. Mẫu là chunk đầu/giữa/cuối lấy bằng ffmpeg seek. Mỗi cấu hình nạp model, khởi động, 2 vòng đo, lấy median. Quét luồng {4,6,8} với 1 worker, rồi thử 2 worker × 3 luồng nếu có ≥ 6 lõi và `may_add`. Khi chạy thật, cửa sổ 30 giây so tốc độ pool với single; nếu pool nhanh hơn dưới 5% thì tắt pool.

Tốt:
- Calibrate không ghi checkpoint hay `job.json`.
- Cổng đúng đắn: kết quả phải khớp baseline (±30 ms mỗi mốc).
- Hoãn calibrate khi thiếu RAM (`tuning_deferred`).
- Lớp kiểm chứng khi chạy bù được phần lớn sai số benchmark.

Yếu:
1. Chỉ 3 mẫu, chunk đầu hay là intro, chunk cuối hay ngắn hoặc im lặng. Thử 2 worker trên 3 mẫu bị lệch tải (2+1).
2. "Median của 2 vòng" là trung bình, không kiểm tra nhiễu. Ngưỡng 10%/5% sát nhiễu của laptop (turbo, giảm xung). Thứ tự đo cố định 4→6→8 làm cấu hình đầu có lợi thế.
3. Không gian tìm kiếm nhỏ (luồng chỉ {4,6,8}; pool chỉ 2×3 và chỉ khi ≥ 6 lõi).
4. Cache không ghi điều kiện lúc đo (pin/cắm điện, tải nền, nhiệt). Nếu CPU bận lúc đó, bỏ qua thử pool và kết quả "1 worker" bị cache 7 ngày.
5. Peak memory đo được chỉ dùng cho kiểm tra commit. Ngưỡng RAM khả dụng dùng JSON tĩnh (`asr-memory.json`).
6. `tune()` nhận `observe` nhưng không truyền xuống nên không có bước con "đang hiệu chuẩn"; calibrate nằm trong thời lượng phase 3.
7. Chế độ GPU (`FUNASR_DEVICE` ≠ `cpu`) vào `transcribe_serial`: không calibrate, không pool, không admission VRAM.

## Translation (`translation/hymt_translation.py`, `translation_server.py`)

Cách làm: không benchmark. `Runtime` bắt đầu 1 slot, `observe()` mỗi 1 giây. Giảm một nửa slot và luồng khi áp lực; thêm một slot sau `scale_up_seconds` (10 giây) khỏe và đủ RAM/VRAM. Đổi số slot phải restart `llama-server` (vì `--parallel` cố định), chỉ làm giữa các batch. Bộ nhớ mỗi slot tính từ metadata GGUF (`slot_bytes`).

Tốt: ước lượng KV từ metadata; không tốn thời gian calibrate; chỉ đổi kích thước khi đã checkpoint; nhánh GPU kiểm VRAM, nhiệt, `--list-devices`.

Yếu:
1. Thêm slot không được kiểm chứng bằng tokens/giây trước và sau (ASR/TTS có kiểm tra gain, Translation thì không). Trên CPU các slot dùng chung một pool luồng cố định, lợi ích có thể bằng không.
2. `threads: 4` cố định trong JSON, trong khi số slot bị chặn theo số lõi. Không tự thích ứng phần cứng.
3. **Rủi ro dao động, cần kiểm chứng trên máy ít lõi (chưa chạy thử):** vòng điều khiển đo CPU toàn hệ thống, gồm cả `llama-server`. Nếu 4 luồng của nó đã vượt 85%, hệ thống giảm luồng và restart; sau 30 giây khôi phục 4 luồng, CPU lại vượt ngưỡng, và lặp lại. Mỗi vòng tốn một lần nạp model.
4. Mỗi job bắt đầu lại từ 1 slot, không lưu cấu hình ổn định lần trước. Mỗi lần tăng slot là một lần restart.
5. GPU: `gpu_metrics` gọi `nvidia-smi` (timeout 2 giây) trong vòng quan sát 1 giây.

## TTS (`tts/tts_runtime.py`)

Cách làm: mẫu `texts[:max(4, cores*2)]`, 1 vòng warm-up + `calibration_rounds` (2) vòng đo, median. Quét luồng {4,6,8} với 1 worker, rồi nhân đôi worker (2, 4, …) với luồng = `cores // count`, chấp nhận nếu nhanh hơn ≥ 10%. Cache 7 ngày theo (config, hash source VieNeu + revision weight, CPU, số lõi, policy). Trong job, `tune()` đo lại mỗi 600 giây nếu còn dư tài nguyên.

Tốt: đo RTF thật cùng RSS đỉnh, RAM tối thiểu, CPU; `min_gain` tránh thêm worker biên; `TrialPressure` hủy thử khi sát mức dự trữ; cache WAV nội dung.

Yếu:
1. Mẫu là các câu đầu chưa có audio, không theo phân bố độ dài; chi phí TTS tỷ lệ độ dài câu.
2. Mỗi `measure` gọi `configure` = đóng pool và nạp lại model. Quét đầy đủ ≈ 5 lần nạp (chỉ lần đầu nhờ cache).
3. Đo lại giữa job mỗi 10 phút chạy lại benchmark, sinh WAV rồi xóa, nạp lại pool. Dữ liệu thật đã có (thông điệp `done` mang thời gian mỗi dòng) nhưng không dùng. Job ngắn có thể lỗ.
4. Chỉ nhân đôi worker (1, 2, 4…), bỏ qua các cấu hình như 3 worker.
5. Peak memory là tổng RSS các worker, tính lặp phần trang dùng chung (weights/ONNX) nên `worker_bytes` bị ước cao, có thể chặn thêm worker không cần thiết.
6. Không có kiểm tra khớp đầu ra (hợp lý vì TTS không tất định), nên không có cổng chất lượng.
7. Chế độ GPU (`VIENEU_DEVICE=cuda`) vẫn dùng pool đa worker theo heuristic CPU; `fit()` chỉ kiểm RAM máy chủ, không kiểm VRAM. Mỗi worker nạp một bản model lên GPU nên có nguy cơ hết VRAM trên card ~4 GB.

## Vấn đề chung

- Ba stage có ba triết lý khác nhau; code lặp (snapshot phần cứng, admission, TTL 7 ngày, `min_gain`, khóa file).
- Ngưỡng RAM là hằng số đặt tay trong ba file JSON (ASR 3.0/2.0; Translation 3.5/0.4; TTS 1.5/1.5), không suy ra từ peak đo được.
- Calibrate chưa gắn với chế độ GPU của `compute_settings.py`.
- Test hiện có (`test_asr_runtime`, `test_tts_runtime`) dùng worker giả, chỉ kiểm tra luồng điều khiển, không kiểm tra chất lượng chọn cấu hình.

## Đề xuất theo thứ tự ưu tiên

1. Chặn GPU đi qua đường calibrate CPU: GPU thì 1 worker, bỏ quét luồng, thêm admission VRAM cho ASR và TTS.
2. Chống dao động ở Translation: trừ CPU của chính tiến trình khi đo áp lực (hoặc lấy CPU ngoài tiến trình); lưu cấu hình slot/luồng ổn định gần nhất.
3. Thay đo lại giữa job của TTS bằng RTF lấy từ các dòng đã xong.
4. Chọn mẫu đo theo độ dài (ASR: ≥ 4–6 chunk, bỏ chunk đầu/cuối quá ngắn; TTS: theo phân bố độ dài); đo 3 vòng, đảo thứ tự (ABA); chỉ chấp nhận chênh lệch lớn hơn nhiễu.
5. Ghi điều kiện lúc đo (pin/cắm điện, CPU nền) vào profile, không cache nếu đo trong điều kiện xấu; truyền `observe` xuống `tune`.
6. Dài hạn: gom hardware snapshot, admission, kho profile vào một module chung trong `core/`.
