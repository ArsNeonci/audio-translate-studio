# Dịch thủ công, Công cụ 7 và nạp tệp vào một bước (Tạo lại)

Từ 3.3.0 (chưa build). Không tính phí. Gồm ba phần dùng chung một nền: **đoạn có mã số**.

## Nền chung: đoạn có mã số (`worker/audio_translate/translation/manual_text.py`)

- **Đoạn** được chia từ `transcript.zh.jsonl` theo đúng quy tắc của `transcript.zh.md`: nghỉ hơn 1,5 s, dài hơn 60 s hoặc hơn 240 ký tự thì sang đoạn mới (`paragraphs()`). Dòng không có thời gian thật (`start_ms == end_ms`, tức tệp TXT) tự là một đoạn.
- Mỗi đoạn có **mã số cố định** `[1]`, `[2]`… Mã đi qua chatbot của người dùng cùng với chữ, rồi quay lại để biết đoạn nào là của đoạn tiếng Trung nào, nên **giữ được thời gian gốc**. Thời gian vẫn quan trọng: kiểu giọng dùng khoảng lặng ≥ 1500 ms để ngắt cảnh (`tts/voice_styles.py`).
- `parse_translation(text, paras)` đọc bản dịch của người dùng:
  - Có mã `[n]` hoặc `【n】`: ghép đúng đoạn; các dòng nối tiếp thuộc về mã gần nhất; mã sai thứ tự được xếp lại; mã trùng giữ lần đầu.
  - Không có mã: ghép theo vị trí nếu số khối (cách nhau dòng trống) hoặc số dòng bằng số đoạn; nếu không thì chia thời gian theo độ dài chữ trên cả khoảng (`estimated_time`).
  - Lời dẫn của chatbot ("Đây là bản dịch:", `---`, `<!-- ... -->`) bị bỏ và đếm (`dropped_lines`).
- `blocking(report)` là các lý do **không cho nạp**: thiếu đoạn, mã không thuộc quy trình, đoạn trống. Các điều khác (còn chữ Hán, mã lặp, thời gian ước lượng) chỉ cảnh báo.
- `rows_from_pairs()` cắt đoạn Việt dài ở cuối câu (`. ! ? …`), chia thời gian của đoạn theo số ký tự (từng mili giây, không lùi) để ra `transcript.vi.jsonl`/`.md`.

## 1. Dịch thủ công ở Studio

- Ô **Lựa chọn dịch thủ công** nằm giữa "Giọng tiếng Việt" và "Chế độ dịch" (`components/voice/manual-translation-toggle.tsx`). Tick thì ẩn Chế độ dịch và Xưng hô; giọng, phụ đề, video vẫn chọn được và dùng lúc chạy tiếp.
- Gửi `manual: true` (JSON) hoặc `manual=1` (tải tệp âm thanh). `manage.create(manual=True)` ghi `job.manual_translation = true`, `selected_address_profile = None`; không đi cùng `mode` (Genius) và không dùng cho công cụ.
- `orchestrator.run`: tới bước `TRANSLATION` mà job có `manual_translation` (và không phải Retry đúng bước đó) thì **dừng, không giữ luồng/RAM**: `end_run(job_dir, 'AWAITING_TRANSLATION')`, trả 0. Trạng thái mới **`AWAITING_TRANSLATION`** ("Chờ bản dịch") được coi như đã dừng ở mọi danh sách trạng thái (bộ lập lịch, `manage.py`, `routes_history.EDITABLE`, `workflow_admission`, UI). Xóa, Tạo lại dùng được như workflow đã dừng; Tạm dừng/Tiếp tục không áp dụng.
**Từ bản sau 4.0.1:** workflow dịch thủ công **kết thúc** (trạng thái COMPLETED, tiến độ 100) ngay khi có bản chép tiếng Trung và các phần đã tách, giống Công cụ 7: một tệp `SPLIT_ZIP` và các tệp con `SPLIT_001`… Studio ẩn các thẻ Phụ đề và Ghép video khi tick dịch thủ công (server cũng bỏ `video` nếu có gửi); các lựa chọn đó được chọn ở trang Tạo lại khi nạp bản dịch (bắt đầu từ Kiểm duyệt). Run nằm ở Lịch sử, trang chi tiết có liên kết **Nạp bản dịch →**. Run cũ của 4.0.1 trở xuống có thể còn ở trạng thái AWAITING_TRANSLATION; trạng thái này vẫn hợp lệ. Tạo lại nhận cả hai trạng thái.

- (Cũ, đến 4.0.1) Workflow chờ vẫn nằm ở Studio với hai liên kết: **Tách văn bản →** (`/tools?tool=split&source=<id>`) và **Nạp bản dịch →** (`/reprocess?id=<id>&step=MODERATION`).
- Tạo lại từ `TRANSLATION` **không nạp tệp** trên job thủ công thì xóa cờ: máy dịch thay.

### Tự tách sẵn (từ 2026-11-19, chưa phát hành)

- Workflow dịch thủ công có thêm bước **`SPLIT`** ngay sau Chép lời (`effective_steps`: DOWNLOAD, TRANSCRIPTION, SPLIT, TRANSLATION…). Nó cắt bản tiếng Trung thành các phần như Công cụ 7, **dùng thiết lập của lần chạy Công cụ 7 gần nhất** (`data/config/split-settings.json`, ghi mỗi khi tạo một lần chạy Công cụ 7; chưa có thì 3000 ký tự, có lời nhắc). Thiết lập được chụp vào `job.split` lúc tạo workflow.
- Các phần được đăng trong kết quả của workflow (`SPLIT_001`…, `SPLIT_ZIP`); hàng của workflow đang chờ ở Studio có liên kết **Tải các phần →** (trang Lịch sử của workflow). Studio hiện dưới ô tick: "tách sẵn thành các phần tối đa N ký tự". `GET /api/split/settings` trả thiết lập này (Công cụ 7 cũng mở với thiết lập đó).
- Nạp bản dịch ở Tạo lại làm workflow thành "dịch thủ công": nếu bước `SPLIT` chưa chạy thì được tính là `skipped`.

## 2. Công cụ 7: Tách văn bản (bước `SPLIT`)

- Đầu vào: bản chép tiếng Trung của một quy trình đã chạy (workflow hoặc Công cụ 1, lấy từ `ZH_JSONL` đã đăng; `GET /api/split/sources` kèm `chars` = cỡ `ZH_MD` ÷ 3) hoặc một tệp TXT/MD/JSONL (≤ 64 MB).
- Thông số (`validate_split`): **số ký tự mỗi phần** 500–20 000 (mặc định 3000; một đoạn không bao giờ bị cắt, đoạn dài hơn giới hạn có phần riêng), tối đa 500 phần; ô tick **Kèm lời nhắc ở đầu mỗi tệp** (bật sẵn, nội dung sửa được ≤ 2000 ký tự; ô hiện câu mặc định theo ngôn ngữ đang dùng).
- Ra `results/tools/<số>/split/<số>-part-001.md`… và `<số>-parts.zip`. Mỗi phần: lời nhắc, `---`, dòng chú thích `<!-- i/n · [a]–[b] -->`, rồi các đoạn `[n] 原文`. Mã số chạy liên tục qua mọi phần, nên bản dịch gom lại vẫn khớp.
- Kết quả trong Lịch sử công cụ có loại tệp động `SPLIT_001`… (số phần ghi ở `job.split.parts`, `results.split_files`) và `SPLIT_ZIP`. Không dùng AI, chạy dưới 1 giây.
- API: `POST /api/tools` JSON `{tool: "split", source_job, split: {max_chars, prompt, prompt_text}}`, hoặc tải tệp `?tool=split&name=&max_chars=&prompt=0|1&prompt_text=`.

## 3. Tạo lại: chọn một bước rồi nạp tệp và chạy tiếp

Chọn workflow → chọn bước → mục **Nguồn của bước này**: *Dùng kết quả đang có* hoặc *Nạp một tệp*. Phần thiết lập các bước sau (giọng, kiểu giọng, phụ đề, video, logo) nằm ngay bên dưới, nên thiết lập một lần rồi chạy đến hết.

| Bước bắt đầu | Tệp nạp | Bước được coi là xong bằng tệp (`origin: import`) |
|---|---|---|
| TRANSCRIPTION | Audio tiếng Trung (≤ 2 GB) | DOWNLOAD |
| TRANSLATION | Văn bản Trung TXT/MD/JSONL | TRANSCRIPTION |
| MODERATION | Bản Việt TXT/MD (có mã `[n]` hoặc không) hoặc JSONL (`text_vi`) | TRANSLATION |
| TTS | Văn bản Việt đã hoàn thiện TXT/MD/JSONL | MODERATION (kèm `moderation-result.json` tối giản) |

Các bước còn xa hơn mà chưa xong được đánh `origin: skipped`; orchestrator **không đăng** file của bước `skipped`.

**Nhiều tệp (Kiểm duyệt và Tạo giọng, từ 2026-11-19, chưa phát hành).** Bản dịch có thể nạp thành nhiều tệp (ví dụ bản dịch của từng phần Công cụ 7): chọn hoặc kéo thả nhiều tệp (tối đa 500, tổng 64 MB), danh sách sắp theo tên tự nhiên (`part-2` trước `part-10`), đổi thứ tự bằng ↑ ↓, bỏ bằng ✕, có nút *Sắp theo tên* và *Bỏ hết* (component chung `components/common/ordered-file-list.tsx`, khung Ghép video cũng dùng nó). Tệp đầu tạo **bản nạp nháp** (`/import`), tệp sau thêm vào (`POST /api/jobs/<id>/import/<import_id>/parts`), mỗi lần đổi danh sách thì kiểm lại theo thứ tự (`POST .../check {order}`): các tệp nối liền nhau (chèn dòng trống), chạy cùng bộ kiểm tra; báo cáo có thêm từng tệp (`parts`: khoảng mã, số mã, dòng lời dẫn đã bỏ, còn chữ Hán, tệp trống, mã trùng với tệp nào). Có mã `[n]` thì thứ tự tệp không đổi kết quả; không có mã thì thứ tự quyết định. Chặn thêm khi: trộn tệp có mã với tệp không có mã, trộn JSONL với văn bản, JSONL không theo thứ tự thời gian. Bản nháp chưa dùng được (`ready: false`) thì Tạo lại từ chối `import_id` đó. Chép lời và Dịch vẫn chỉ nhận một tệp.

Hai pha để người dùng thấy kết quả kiểm tra trước khi có gì thay đổi (`workflow/imports.py`):
1. `POST /api/jobs/<id>/import?step=&name=` (thân là tệp; cần giấy phép): kiểm tra, đổi thành đúng các tệp mà bước đó thường tạo, cất ở `data/imports/<import_id>/` (xóa sau 24 giờ) và trả `{import_id, report}`. `import_id = null` khi `report.blocked` có lý do. Báo cáo: số đoạn, đoạn thiếu/lạ/trống/lặp, số đoạn còn chữ Hán, dòng lời dẫn đã bỏ, thời gian ước lượng, 3 cặp xem trước.
2. `POST /api/jobs/<id>/reprocess` kèm `import_id`: `manage.reprocess` kiểm tra tệp thuộc đúng workflow và bước, bỏ yêu cầu "các bước trước phải xong", chép tệp vào workflow (`imports.apply`), đánh dấu bước, đánh `STALE` các tệp đã đăng của bước bị thay và các bước sau, xóa checkpoint, rồi chạy tiếp bình thường. Tệp nạp được đăng kèm nhãn `origin: import` ("do bạn nạp").

Nạp bản dịch tại MODERATION/TTS cũng đặt `manual_translation = true`, `selected_address_profile = None`, xóa `characters.json`/`name-glossary.json`: **chỉ áp luật thay thế (Quy tắc cộng đồng), không áp xưng hô**, và UI ẩn Chế độ dịch/Xưng hô/Bảng nhân vật.

Chỉ nạp được cho **workflow** (không cho công cụ đơn) đang đã dừng (COMPLETED, FAILED, CANCELLED, PAUSED, PARTIAL, AWAITING_TRANSLATION).

## Lỗi và chuỗi giao diện

Lỗi nhập là câu tiếng Anh ngắn do worker trả, giao diện dịch qua `uiText` (khóa chính là câu tiếng Anh). Muốn thêm lỗi mới phải thêm khóa tương ứng ở `web/lib/i18n/ui-text.ts`. Toàn bộ chuỗi mới là `[vi, en]` cùng placeholder.

## Test

- `worker/tests/test_manual_translation.py` (27): chia đoạn, mã số, kiểm tra, cắt phần, workflow chờ rồi nạp, nạp ở TRANSCRIPTION/TRANSLATION/MODERATION/TTS, nạp sai workflow/bước/dùng hai lần, công cụ 7 từ quy trình và từ tệp.
- `worker/tests/test_api_routes.py` (`ManualTranslationRouteTests`): cờ `manual`, `/import`, công cụ 7.
- `contracts/tests/run_app_contract.py` và `ui_smoke.py`: route mới và giao diện (ô tick, công cụ 7, bộ nạp ở Tạo lại, cả hai chế độ sáng/tối).

## Chưa kiểm chứng

- Nạp tệp qua HTTP với giấy phép ACTIVE và trên bản cài đặt (môi trường test không có giấy phép; logic worker đã có test, đường HTTP chỉ kiểm tới cổng giấy phép).
- VieNeu đọc các dòng Việt dài do người dùng dán (đã giảm rủi ro bằng cách cắt câu khi nạp).
