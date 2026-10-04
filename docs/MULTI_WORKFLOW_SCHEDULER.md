# Chạy nhiều workflow cùng lúc: Bộ phân luồng (Lane Broker)

Trạng thái: **đã triển khai** (2026-10-04). Mục 7 ghi phần mã thực tế và những gì chưa kiểm chứng.

## 1. Mục tiêu

- Thêm workflow mới khi đang có workflow chạy. Workflow mới vào hàng chờ, các workflow đang chạy nhả bớt luồng song song (mỗi workflow giữ tối thiểu 1 luồng). Khi đủ tài nguyên thì workflow mới bắt đầu chạy.
- Luồng được rải đều theo thứ tự: workflow chạy trước được nhiều hơn **tối đa 1 luồng** so với workflow chạy sau.
- **Không giới hạn số workflow cố định.** Chỉ giới hạn theo tài nguyên, để máy mạnh hơn tự chạy được nhiều hơn.
- Khi tài nguyên không đủ, **workflow chạy sau cùng tự tạm dừng** để workflow chạy trước hoàn thành và trả tài nguyên.
- Chỉ có một workflow thì hành vi giữ nguyên như hiện nay.

## 2. Hiện trạng (vì sao cần lớp mới)

- `schedule()` trong `lib/server/jobs.ts` có `if(active.size)return;`, nên mỗi lúc chỉ một workflow chạy. Preflight Convert (`workflow/workflow_admission.py`) chỉ dự báo, trả `scheduler_mode: 'sequential'`.
- Mỗi stage tự điều chỉnh theo RAM/CPU trống của cả máy và không biết workflow khác tồn tại:
  - ASR pool: `transcription/asr_runtime.py`
  - Translation slots: `translation/translation_server.py` (`Runtime.observe`, `tune_between_batches`)
  - TTS pool: `tts/tts_runtime.py`
  Chỉ bỏ dòng chặn trong `schedule()` sẽ làm các workflow tranh nhau, dao động hoặc cùng tạm dừng vì thiếu RAM.

Chi phí một "luồng" khác nhau theo stage (số đo trên máy dev 16 GB):

| Stage | Một đơn vị song song | RAM |
|---|---|---|
| TRANSCRIPTION 3/4 | 1 worker ASR (model riêng) | ~5,2 GiB mỗi worker |
| TRANSLATION | 1 slot (model dùng chung) | 2,2 GiB nền + 0,25–0,4 GiB mỗi slot |
| TTS | 1 worker VieNeu | ~1,5–1,8 GiB mỗi worker |
| DOWNLOAD, MODERATION, TRANSCRIPTION 1/2/4 | không có pool | nhỏ |

## 3. Kiến trúc

### 3.1 Sổ cái dùng chung (`core/lanes.py`)

- File `data/config/lanes.json`, ghi dưới `file_lock` (đã có trong `core/storage.py`).
- Mỗi workflow đang chạy giữ một lease:
  `id`, `order` (thời điểm bắt đầu chạy lần đầu, dùng để xếp ưu tiên), `stage`, `target_units`, `used_units`, `unit_bytes` (RAM thực đo mỗi đơn vị), `base_bytes` (model nền), `threads`, `heartbeat`.
- Lease không có heartbeat quá 30 giây bị coi là chết và bị gỡ.
- Không dùng tiến trình broker thường trực: logic co giãn đã nằm trong các tiến trình Python của stage, file + khóa đủ dùng và ít điểm hỏng hơn.

### 3.2 Thuật toán chia luồng (hàm thuần, dễ test)

Đầu vào: danh sách lease xếp theo `order`, ngân sách = `RAM trống − 2 GiB dự trữ`, số lõi vật lý, mục tiêu CPU (85% cắm điện / 65% pin), cờ nhiệt.

1. Mỗi workflow giữ 1 đơn vị tối thiểu (và model nền của stage hiện tại).
2. Phần dư rải từng vòng: cấp thêm 1 đơn vị cho workflow đang có **ít đơn vị nhất**; hòa thì ưu tiên `order` nhỏ hơn (chạy trước).
3. Chỉ cấp nếu chi phí đơn vị theo stage của workflow đó còn vừa ngân sách RAM, lõi CPU, CPU% và nhiệt.
4. Workflow không dùng hết phần của mình (đang MODERATION, Continue chỉ 1 slot, gần hết việc) không giữ chỗ; phần dư chia tiếp cho workflow khác theo cùng luật.
5. Ngân sách CPU chia tương tự: `luồng CPU mỗi đơn vị = lõi được cấp ÷ số đơn vị`, tránh mỗi stage tự chọn 4/6/8 luồng rồi cộng vượt số lõi.

Kết quả bảo đảm: chênh lệch tối đa 1 đơn vị, workflow trước được trước. Ví dụ 7 đơn vị / 3 workflow → 3-2-2; 8 → 3-3-2.

### 3.3 Nhận workflow mới

- Convert luôn tạo job ở `QUEUED` (không còn chặn 409 vì thiếu tài nguyên; preflight chỉ còn thông báo).
- Broker kiểm tra: nếu mọi workflow đang chạy co về 1 đơn vị mà vẫn đủ chỗ cho model nền + 1 đơn vị của workflow mới, thì hạ `target_units` của các workflow đang chạy.
- Workflow mới chỉ được khởi chạy khi RAM **thực đo** đã trống đủ. Chưa đủ thì tiếp tục chờ; giao diện hiện lý do (ví dụ "chờ workflow #7 nhả luồng").

### 3.4 Nhả luồng an toàn (dùng cơ chế có sẵn)

- ASR: đặt `retire` cho worker thừa; worker xong chunk hiện tại, ghi checkpoint rồi thoát.
- TTS: gỡ worker rảnh (`Pool.remove`).
- Translation: ngừng cấp việc, chờ slot đang chạy checkpoint, khởi động lại server với ít slot hơn (`tune_between_batches`).
- Mỗi stage chỉ cần thêm một ràng buộc: `số đơn vị tối đa = min(giới hạn hiện có, target_units từ broker)`, và báo `used_units`, RAM thực đo vào lease ở mỗi nhịp quan sát.
- Mỗi workflow có thời gian chờ 30–60 giây giữa hai lần đổi số đơn vị (khởi động lại server Translation tốn một lần nạp model).

### 3.5 Tạm dừng workflow chạy sau cùng (đã chốt)

- Khi một workflow bước sang stage nặng (ví dụ ASR ~5,2 GiB) mà không đủ chỗ, nó xin cấp. Các workflow có `order` lớn hơn co về 1 đơn vị trước.
- Vẫn thiếu thì **workflow có `order` lớn nhất tự tạm dừng** bằng cơ chế Pause hiện có (nhả model, giữ checkpoint), đánh dấu `auto_paused_for=<id>` để phân biệt với người dùng bấm Pause.
- Workflow tự tạm dừng được tự Resume khi broker thấy đủ tài nguyên. Workflow người dùng tạm dừng thì không tự chạy lại.
- Vì luôn ưu tiên workflow chạy trước, không có vòng chờ kẹt nhau.

### 3.6 Lập lịch và giao diện

- `schedule()` khởi chạy nhiều orchestrator; trước mỗi lần khởi chạy hỏi broker qua entry mới `worker/resources.py` (gọi từ `lib/server/worker-client.ts`). Entry này không cần cấp phép native, nên **không phải sửa allowlist Rust**.
- Chỉ số workflow giới hạn bởi tài nguyên, không có hằng số tối đa.
- Giao diện mỗi workflow: "Luồng 2/3 · đang nhường cho #8", "Tự tạm dừng để ưu tiên #7". Mọi chuỗi phải có đủ Việt/Anh (`lib/i18n`) và qua `npm run check:i18n`.
- Preflight chuyển sang `scheduler_mode: 'shared'`.

## 4. Kỳ vọng thực tế

- Máy 16 GB: RAM dùng được ~4 GiB sau dự trữ. Song song hiệu quả chủ yếu khi các stage bổ trợ nhau (workflow A ở TTS 1 worker, workflow B tải/chép lời). Hai workflow cùng ở ASR không vừa; workflow sau sẽ chờ hoặc tự tạm dừng.
- Lợi ích chính là lồng ghép stage. Máy từ 32 GB trở lên chia được nhiều luồng thật.
- CPU vẫn dùng chung: chạy cùng stage chưa chắc tăng tổng thông lượng. Phải đo tổng thời gian song song so với tuần tự trước khi kết luận.

## 5. Kế hoạch triển khai

| Bước | Việc | Kiểm chứng |
|---|---|---|
| 0 | **Sửa lỗi license `CLOCK_ROLLBACK`**: thêm dung sai khi so mốc thời gian (`security-core`, build lại, tăng version) hoặc giảm kiểm tra offline ở mỗi dòng | Nhiều workflow kiểm tra license cùng lúc không còn lỗi. Bắt buộc làm trước |
| 1 | `core/lanes.py`: hàm chia luồng thuần + sổ cái lease/heartbeat | Unit test: tối thiểu 1, chênh tối đa 1, ưu tiên `order`, chia lại phần dư, gỡ lease chết |
| 2 | ASR/Translation/TTS đọc `target_units` và ngân sách CPU, báo RAM thực đo | Một workflow: hành vi và test hiện có không đổi |
| 3 | `schedule()` chạy nhiều workflow; nhận workflow mới qua broker; tự tạm dừng/tự resume workflow sau cùng | Kiểm tra pause, cancel, delete, retry, Continue khi chạy song song |
| 4 | Giao diện, i18n, tài liệu; đo thông lượng thật | `tsc`, lint, `check:i18n`, `check:theme`; so sánh thời gian tuần tự và song song |

## 6. Quyết định đã chốt

- Cho phép tự tạm dừng workflow chạy sau cùng để ưu tiên hoàn thành workflow chạy trước và hoàn trả tài nguyên.
- Không giới hạn số workflow; chỉ giới hạn theo tài nguyên.
- Giữ dự trữ 2 GiB RAM cho hệ thống.

## 7. Triển khai thực tế (2026-10-04)

| Thành phần | Vị trí |
|---|---|
| Dung sai đồng hồ license (bước 0) | `security-core/src/license.rs`: `CLOCK_SKEW_SECONDS = 300`; binary build lại vào `security-core/bin/` |
| Sổ cái, thuật toán chia luồng, lease/heartbeat, tự tạm dừng | `worker/audio_translate/core/lanes.py` |
| Orchestrator giữ lease, báo stage | `workflow/orchestrator.py` (`Lease`, `lease.stage()`) |
| ASR | `transcription/asr_runtime.py`: `lanes.report` mỗi 2 giây giới hạn số worker và lõi; `wait_memory` chờ tiếp khi workflow sau đang nhả RAM, hết giờ thì tự tạm dừng nếu có workflow khác |
| Translation | `translation/translation_server.py`: `lane_maximum()`/`lane_cores()`, thu slot khi vượt mục tiêu, `yield_wait()` trước khi tạm dừng; `hymt_translation.wait_memory` tương tự |
| TTS | `tts/tts_runtime.py`: `report_lane()`, giới hạn worker và lõi, gỡ worker rảnh khi vượt mục tiêu, `pause_memory` chờ trước khi tạm dừng |
| Quyết định nhận/tự resume | `workflow/scheduling.py`, entry `worker/resources.py` (không cần allowlist Rust) |
| Lập lịch nhiều workflow | `lib/server/jobs.ts` `schedule()`: hỏi `resources.py`, chạy một workflow mỗi lần, xét lại sau 5 giây, hẹn giờ 15 giây khi còn workflow chờ |
| Convert | `workflow/workflow_admission.py`: luôn xếp hàng, `scheduler_mode: 'shared'` |
| Giao diện | `components/workflow/pipeline-status.tsx` (dòng "Chạy song song … luồng", "Đang nhường …"), chuỗi Việt/Anh trong `lib/i18n/ui-text.ts` |
| Telemetry mỗi job | `working/lane.json` (orchestrator ghi mỗi 3 giây) |

Chi tiết hành vi:
- Sổ cái nằm ở `<data>/config/lanes.json` của chính job; job trong thư mục test dùng `.lanes/` cạnh nó, nên test không chạm sổ cái thật.
- Workflow tự tạm dừng có `auto_paused_for` và `memory_pause_reason`; bấm Resume thủ công xóa các trường này. Tạm dừng do người dùng không bao giờ tự chạy lại.
- Một workflow duy nhất: mục tiêu = giới hạn riêng của stage, lõi = toàn bộ; hành vi như trước.

Kiểm chứng:
- Rust: 9/9 test (có test dung sai). Python: 235 test; 16 test mới cho lanes/admission pass; còn đúng 5 lỗi có sẵn (`memory_policy` 4, `workflow_admission` 1) và `test_idle_slot_refills…` thỉnh thoảng fail do thời gian khi máy tải nặng (pass khi chạy riêng).
- `packaging/test_security_phase1.py` 8/8 với core mới. `tsc`, eslint, `check:i18n`, `check:theme` sạch. localhost:3000 trả 200.
- **Chưa** chạy thật hai workflow cùng lúc từ đầu đến cuối và chưa đo thông lượng song song so với tuần tự.
- Core Rust đã đổi: **tăng version sản phẩm trước khi build installer**.
