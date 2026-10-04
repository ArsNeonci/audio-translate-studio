# Checkpoint từng đoạn và xuất chuỗi hoàn thành từ đầu

Áp dụng ngày 2026-10-04 theo kết luận cuối của phiên **Cập nhật ngưỡng CPU 1x**.

## Điều phối

- Mỗi đoạn có ID dòng 1-based và phần 0-based. Một coordinator duy nhất ghi SQLite và file; các slot chỉ sinh bản dịch.
- Cửa sổ tối đa `2 × số slot hiện tại` (tối thiểu 2 đoạn), tính cả kết quả đã hoàn thành nhưng còn chờ đoạn trước. Khi giảm slot, phần đã nhận được giữ và không đọc thêm cho tới khi đủ chỗ.
- Slot rảnh nhận phần/đoạn tiếp theo ngay, không phải chờ toàn bộ nhóm. Các phần trong cùng đoạn giữ thứ tự vì còn phụ thuộc ngữ cảnh nguồn.
- Phần thành công được commit ngay; dòng hoàn chỉnh được commit riêng. Hai kết quả về cùng lượt được xử lý theo ID dòng/phần. Bộ ghi chỉ nối chuỗi dòng hoàn thành liên tiếp từ đầu.
- File `transcript.vi.partial.jsonl` và `.md` được cập nhật khi có chuỗi liên tiếp mới. Checkpoint SQLite là nguồn phục hồi sau crash; partial được dựng lại khi Continue/Resume. Phần prefix được dựng lại từ cache được flush theo nhóm nhỏ.
- `transcript.vi.jsonl`, `.md` và marker hoàn thành chỉ được công nhận sau khi đủ mọi dòng. File partial không được dùng làm đầu vào Moderation.
- Giữ bộ điều phối tài nguyên hiện có: khởi đầu CPU 3,5 GiB, dự phòng 2 GiB, ngân sách slot thêm tối thiểu 0,4 GiB, CPU/GPU 85%, nhiệt 85°C. Không benchmark trước khi dịch. Khi cần đổi phân bổ KV/threads, ngừng cấp việc và drain slot trước khi restart server.

## Lỗi và Continue

- **Cách ly dòng lỗi (từ 2026-10-04):** một dòng thất bại cả 3 lượt vì lỗi chất lượng (`TranslationFailure`) được ghi chẩn đoán và đưa ra khỏi cửa sổ; các dòng khác vẫn tiếp tục dịch và checkpoint. Chuỗi xuất liên tiếp dừng trước dòng đó. Hết file, stage báo `FAILED` một lần, kèm danh sách `row N: lý do`. Nếu 5 dòng liên tiếp đều lỗi (`QUARANTINE_STREAK`), stage dừng ngay vì model/runtime có vấn đề.
- Lỗi hạ tầng (server chết, exception khác) vẫn ngừng cấp việc mới; chờ các tác vụ đang chạy kết thúc và lưu kết quả hợp lệ. Không xóa kết quả được tạo gần nhất.
- Nút **Tiếp tục giai đoạn** được thêm cho Translation `FAILED`, dùng API Resume hiện có. Vẫn kiểm tra license, worker lock, yêu cầu xóa và các stage tiền nhiệm.
- Continue giữ nguyên cấu hình và fingerprint checkpoint, tăng generation thử lại riêng. Đoạn lỗi được ưu tiên chạy 1X trước khi cấp việc cho đoạn khác; sau đó bộ điều phối tự tăng tải như bình thường.
- Các lỗi chất lượng có tối đa 3 lượt, mỗi lượt đổi chỉ dẫn, nhiệt độ và seed (`STRATEGIES` trong `hymt_translation.py`): `natural` (văn phong tự nhiên, giữ cảm xúc, nhiệt độ 0.7) → `conversational` (khẩu ngữ, 0.3) → `literal` (mẫu chính thức của Tencent, 0.0). **Không bao giờ đưa bản nháp lỗi vào prompt lượt sau.** Seed = hash(văn bản nguồn) + 101 × generation + lượt, nên không phụ thuộc slot hay thứ tự hoàn thành. Giữ glossary đã cấu hình; không tự thêm cách dịch tên vào glossary.
- Ngân sách đầu ra theo độ dài nguồn: `min(output_tokens, 48 + 6 × số ký tự)`. Chạm ngân sách nghĩa là model đang lan man, được tính là lỗi chất lượng của lượt đó và chuyển sang lượt tiếp, không dừng stage. Không retry vô hạn trong một lần chạy.

## Prompt (từ 2026-10-04)

Mỗi dòng gửi một prompt tự đủ theo mẫu zh→xx chính thức: (glossary nếu có) + chỉ dẫn + văn bản nguồn. **Không gửi ngữ cảnh nền**, không có nhãn `[Background Information]`/`[Source Text]`/`[Draft to correct]`.

Lý do (đo trên model thật, workflow 000007): với ngữ cảnh 512 ký tự, prompt cũ mất 6–7 giây/dòng và ở dòng 553, 570 model dịch luôn đoạn ngữ cảnh (660–716 token, ≈50 giây) rồi lọt nhãn `[Thông tin cơ bản]`. Ngay cả 60 ký tự ngữ cảnh kèm câu "不需要翻译上文" vẫn lan man ở dòng 567. Prompt không ngữ cảnh mất 0.5–2 giây/dòng và không lan man. Biến thể chỉ dẫn bằng tiếng Anh bị loại vì đôi khi trả về tiếng Trung hoặc tiếng Anh.

Tương thích checkpoint: khóa mỗi dòng vẫn là `digest([row, config, ngữ cảnh nguồn 512 ký tự])`; ngữ cảnh chỉ còn dùng cho khóa. `settings['prompt']` trong `adapters.json` chỉ là định danh fingerprint; mẫu prompt nằm trong mã. Vì vậy job cũ Resume được mà không mất các dòng đã dịch (các dòng đó giữ văn phong prompt cũ; muốn đồng nhất thì chọn Chạy lại giai đoạn).

## Dịch theo câu (từ 2026-10-04, `segmentation: sentence`, mặc định)

Các dòng liên tiếp chưa có cache được gom tới hết câu (`。！？!?…`), tối đa 6 dòng / 120 ký tự, mỗi dòng ≤ 80 ký tự. Một nhóm được dịch bằng một prompt theo mẫu dịch giữ định dạng của Hunyuan: `<source><s1>dòng 1</s1><s2>dòng 2</s2>…</source>` → `<target><s1>…</s1>…</target>`. Kết quả tách lại đúng từng dòng và timestamp gốc, nên Moderation/TTS không đổi.

- Kiểm tra căn chỉnh (`split_group`): đủ và đúng thứ tự thẻ, không thẻ thừa/lồng, không chữ ngoài thẻ, mỗi phần qua `output_problem`. Thử 2 lần (nhiệt độ 0.7, 0.3). Không căn chỉnh được thì cả nhóm **lùi về dịch từng dòng** với 3 lượt như cũ (không tính là lỗi dòng).
- Dòng đơn lẻ trong câu, dòng có Continue (recovery) hoặc dòng dài dùng prompt từng dòng.
- Cửa sổ đọc trước tính theo dòng: `2 × slot × 6`; nhóm đang gom được phép hoàn tất câu.
- `translation-progress.json` thêm `groups`, `grouped_rows`, `fallbacks`.
- `segmentation: row` trong `adapters.json` quay về dịch từng dòng.

Đo trên model thật (workflow 000007): căn chỉnh đúng 18/19 nhóm không glossary, 24/24 nhóm có glossary; chạy thử 150 dòng: 38 nhóm phủ 141 dòng, **0 lần lùi**. Câu đọc liền mạch hơn và các dòng bị ASR cắt giữa từ (`只，|有我盯着照片右，|右下角…`) được dịch đúng ý.

## Glossary tên Hán-Việt (`translation/names.py`)

Model không tự phiên âm Hán-Việt được (张倩倩 → "Trương Tiểu Tiểu", 宋轩 → "Sung Huan") nhưng tuân thủ danh sách thuật ngữ. Ở đầu stage Translation, tên người được phát hiện một lần và lưu vào `working/name-glossary.json` (`{"version":1,"names":[{"source","target","count","auto"}]}`):

- Phát hiện: n-gram họ + 1–2 chữ xuất hiện ≥ 3 lần (bỏ từ có trong từ điển jieba nếu không phải tên, bỏ dạng "tên + từ" như `李强家`), cộng các từ jieba gắn nhãn `nr`. Họ dễ nhầm với từ thường (那, 和, 高, 时…) chỉ được nhận qua nhãn jieba. Thêm bí danh tên gọi (倩倩) khi nó cũng đứng riêng ≥ 2 lần.
- Âm đọc: bảng họ (đơn và kép) và chữ đặt tên phổ biến được biên soạn. Tên có chữ ngoài bảng **bị bỏ qua, không đoán**. Unihan `kVietnamese` không dùng vì lẫn âm Nôm (徐 → chờ, 强 → càng, 莲 → sen); đã dùng nó để đối chiếu bảng.
- Đưa vào prompt (dòng và nhóm) bằng mẫu thuật ngữ chính thức `参考下面的翻译：\n张倩倩 翻译成 Trương Thiến Thiến`. Glossary cấu hình trong `adapters.json` được ưu tiên; bí danh nằm trọn trong tên đầy đủ thì không gửi lặp.
- Người dùng có thể sửa `name-glossary.json` rồi Reprocess Translation; Reprocess không xóa file này. Digest glossary và chế độ dịch nằm trong khóa checkpoint dòng (không nằm trong signature stage), nên sửa glossary sẽ dịch lại các dòng.

Ví dụ workflow 000007: 张倩倩 → Trương Thiến Thiến, 李强 → Lý Cường, 宋轩 → Tống Hiên, 穆淑泽 → Mục Thục Trạch, 倩倩 → Thiến Thiến.

Lưu ý tương thích: khóa checkpoint dòng giờ gồm `{segmentation, digest(names)}`, nên job đang dịch dở trước bản này sẽ dịch lại các dòng còn lại từ đầu Translation (job đã hoàn thành không bị ảnh hưởng).
- Sau 3 lượt chưa đạt, giữ trạng thái FAILED để người dùng Continue thêm hoặc **Chạy lại giai đoạn**. Retry stage xóa checkpoint và chẩn đoán của Translation.
- Bản dịch còn chữ Trung, token suy luận/điều khiển, hoặc nhãn prompt phổ biến như `[Thông tin cơ bản]` bị từ chối. Cache cũ có lỗi này được coi là thiếu và dịch lại riêng, không làm mất hiệu lực các dòng tốt.

## Chẩn đoán và tiến độ

SQLite `translation_failures` cùng `working/translation-errors.json` lưu dòng, phần, mốc thời gian, nguồn, nguyên nhân, các bản nháp bị từ chối, seed, generation và số lần thất bại. Giao diện **View Error** hiển thị các thông tin này. Đây là chẩn đoán của lỗi đang còn tồn tại; khi dòng thành công, lỗi đó được gỡ.

`working/translation-progress.json` phân biệt **done** (tất cả dòng đã checkpoint hợp lệ, gồm dòng sau khoảng trống) và **exported_rows** (chuỗi liên tiếp đã xuất). Continue khôi phục số dòng đã lưu từ SQLite, giữ nguyên thứ tự, ngữ cảnh nguồn và timestamp.

## Xác minh

Kiểm thử gồm nhận việc mới khi dòng đầu còn chạy, giới hạn bộ đệm, prefix xuất trước khi kết thúc, lỗi slot/drain/resume, phục hồi tiến độ sau khoảng trống, retry 3 cách và thay seed, lọc nhãn prompt trong cache, Continue nhiều lần và bảo toàn checkpoint. Thử nghiệm dùng model/server mô phỏng; chưa benchmark thông lượng hoặc chất lượng model thật cho thay đổi này.

Kết quả cuối: **118 kiểm thử liên quan đạt**, TypeScript (`tsc --noEmit`), lint, check:i18n và check:theme đạt. Lần chạy toàn bộ trước ca kiểm thử cuối có 198 test: 192 đạt, 1 bỏ qua, 5 lỗi ở `test_memory_policy` (4) và `test_workflow_admission` (1); hai phần này không được sửa trong thay đổi này. Không Pause/Resume/Retry workflow thật trong quá trình triển khai.
