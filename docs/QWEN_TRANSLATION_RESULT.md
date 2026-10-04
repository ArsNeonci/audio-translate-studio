> Historical verification of the retired Qwen backend. Current setup: [Hy-MT2](TRANSLATION_LONG.md).

# Qwen3 TRANSLATION — 2026-10-03

TRANSLATION sử dụng Qwen3-8B Q4_K_M GGUF, chạy offline
qua llama-cpp-python 0.3.19 CPU trong `.venv` của dự án.

## Model và nguồn tải

- Kho: https://huggingface.co/Aldaris/Qwen3-8B-Q4_K_M-GGUF
- Revision: `13bd893bea2d84ef95500851983ed8c4f24e70e3`
- File: `models/Qwen3-8B-Q4_K_M/qwen3-8b-q4_k_m.gguf`
- Dung lượng: 5.027.783.872 byte.
- SHA-256 đã kiểm chứng: `609eb8a9fb256d0e2be8b8d252b00bae7c0496fac5e9ccca190206abbb24e2e5`.

Tải trực tiếp, không clone source. Thư mục model chỉ giữ GGUF, MODEL_CARD.md,
LICENSE và provenance.json. Runtime cài bằng wheel, không tạo checkout llama.cpp.
Quét toàn workspace chỉ phát hiện `audio-translates/.git`; 9 thư mục tempfile rỗng
trong worker đã được kiểm tra và xóa. Không xóa lịch sử Git, dữ liệu xử lý,
kết quả đã xuất hoặc các model của ASR/TTS. Cache của bộ dịch trước đã được xóa
trong đợt dọn ngày 2026-10-04.

## Thay đổi luồng dịch

Prompt yêu cầu tiếng Việt tự nhiên, giữ đủ ý và tên/thuật ngữ nhất quán. Các câu
liền nhau được giữ chung trong giới hạn token; thêm ngữ cảnh nguồn trước đoạn.
Qwen chạy non-thinking. Bản dịch rỗng, có reasoning/control token hoặc chạm giới
hạn đầu ra không được lưu checkpoint. Nếu còn chữ Hán thì sửa một lần; vẫn còn
sẽ báo lỗi trước khi chuyển sang TTS. Bản nháp sửa được giới hạn token.

Checkpoint từng phần, resume, pause/cancel và timestamp được giữ. Snapshot
cũ chuyển sang Qwen và giữ glossary/TTS, không lưu kèm cấu hình bộ dịch trước.
Model/prompt/ngữ cảnh nằm trong fingerprint nên chỉ dùng lại checkpoint phù hợp.
Các kết quả History cũ không tự
dịch lại; dùng Reprocess TRANSLATION để tạo bản mới và xử lý các bước phụ thuộc.

Ngưỡng nạp production: 6.5 GiB RAM trống, context 4096, tối đa 768 token nguồn
và 1536 token đầu ra. Thiếu RAM sẽ đợi rồi pause. Admission dự toán cả Qwen.

## Kiểm chứng

- 13 kiểm thử adapter: token/source preservation, ngữ cảnh qua batch/resume,
  checkpoint/partial export, pause/cancel, CPU pressure, glossary, migration,
  output validation và retry chữ Hán.
- 44 kiểm thử liên quan: postprocess, kết quả, lifecycle, admission và memory.
  Kiểm thử memory dùng fixture ASR mặc định 4.5/3.0 GiB, độc lập với cấu hình
  live người dùng đã chỉnh 3.5/2.0 GiB; không thay cấu hình live.
- Tokenizer GGUF thật: ba mẫu dài 3.200–3.800 ký tự, nguồn được giữ đầy đủ và
  mọi phần đều trong giới hạn 768 token.
- Model thật: hai đoạn Trung → Việt, kiểm tra timestamp, export và resume.
  Một lượt ban đầu còn sót chữ Trung đã dẫn đến bổ sung validation; lượt kiểm
  chứng sau đó hoàn tất với đầu ra tiếng Việt không còn chữ Hán.
- Lượt model thật sau sửa: 119,31 giây, RSS cuối lượt 6,68 GiB. Fixture dùng
  context 2048, hai luồng (giảm còn một khi chịu áp lực) và ngưỡng nạp riêng
  2 GiB với mmap. Mặc định production 6.5 GiB/4096 không bị thay đổi.
- Benchmark điều phối giả lập 20/60/120 đoạn với timestamp trải 1/6/60 giờ:
  đúng số dòng, thứ tự, timestamp và partial export. Không phải benchmark
  chất lượng/tốc độ dịch model thật trên bản ghi dài.
- Python syntax và Git diff whitespace checks qua.

Ví dụ model thật:

> Tôi vốn định đi sớm, nhưng vừa nhìn ra ngoài thấy mưa to như trút nước,
> đành phải đợi mưa tạnh rồi mới đi.

Báo cáo chi tiết nằm ở `data/verification/qwen-real-translation/report.json`
và `data/verification/translation-long/tokenizer-result.json`.

Whitelist đóng gói đã bổ sung runtime llama-cpp-python, GGUF đã kiểm checksum,
license và provenance. Launcher bản cài đặt trỏ tới model được đóng gói.
Chưa build/phát hành installer mới; installer đã phát hành trước đó vẫn dùng
payload cũ. Chất lượng và tốc độ trên bản ghi dài cần đo riêng trên dữ liệu thực.
