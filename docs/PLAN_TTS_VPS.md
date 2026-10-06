# Kế hoạch cập nhật: Voice generation qua VPS cho gói Basic, bước duyệt trước khi tạo giọng, nền tảng dịch vụ chung

**Bản final**, chốt ngày 2026-10-06. **Chủ sản phẩm đã duyệt; đã triển khai bước 1–4 và 6. Bước 5 (test trên VM GCP) chờ chủ sản phẩm tạo VM** (mục 0). Đây là giai đoạn 4 của `PLAN_GENIUS_BASIC_PLUS.md`, dùng lại gateway và cơ chế tính phí của chế độ Genius.

## 0. Trạng thái triển khai (2026-10-06)

| Bước | Đã làm | Nơi | Kiểm thử |
|---|---|---|---|
| 1. Nền tảng nhiều app | Bảng `apps` (sản phẩm, khóa gốc, dịch vụ được bật). Cột `app_id` và `service` cho job và chi phí. Cài đặt theo `(app, service)`, giá riêng theo `(khách, app, service)`, nợ và hạn mức chung. Tự di chuyển dữ liệu Genius cũ. Admin Billing có cài đặt riêng cho Genius và Voice, giá theo dịch vụ, lọc job theo dịch vụ | `billing-gateway/store.py`, `gateway.py`, `admin-system/billing.py`, `ui/app.js` | gateway 22/22; admin 22/22 |
| 2. Duyệt trước TTS | Trạng thái `AWAITING_REVIEW`. Action `manage.py review` với `continue` hoặc `finish`; khi kết thúc, TTS được đánh dấu `SKIPPED`. Ô **Auto** chỉ ở Basic, cho workflow chính và Tools 4. Reprocess từ TTS không hỏi; Reprocess từ bước sớm hơn hỏi lại. Security core thêm `review` vào danh sách lệnh được phép | `workflow/manage.py`, `orchestrator.py`, `components/workflow/review-actions.tsx`, `components/voice/auto-tts-toggle.tsx`, `security-core` | `tests/test_review.py` 6/6; Rust 10/10 |
| 3. Dịch vụ TTS trên gateway | `POST /v1/tts`: gửi và hỏi lại (202 khi đang xếp hàng hoặc đang chạy), vì Cloudflare cắt request quá 100 giây. Mỗi worker là một tiến trình VieNeu riêng. Chia lượt giữa các khách. Style (cắt lặng, tempo) chạy trên VPS. Trả FLAC kèm SHA của PCM. Chống tính trùng theo nội dung, mỗi đơn vị chỉ tính một lần. Hạn mức chính xác theo ký tự đầu vào. Audio giữ 24 giờ | `billing-gateway/tts_engine.py`, `gateway.py` | `test_platform.py` |
| 4. Client TTS trong app (Basic) | `RemoteTTS` cắm vào `synthesize()`: đoạn khoảng 1.200 ký tự, gửi trước 1 đoạn, kiểm tra SHA, lưu đến đâu chắc đến đấy, chạy tiếp từ đơn vị còn thiếu. `PAUSED` với `CREDIT_LIMIT`, `LICENSE_REJECTED` hoặc `GATEWAY_UNAVAILABLE`. Basic bỏ CPU/GPU cho TTS và không giữ RAM cho model TTS | `tts/remote.py`, `postprocess.py`, `core/compute_settings.py`, `orchestrator.py` | `tests/test_tts_remote.py` 3/3; **chạy thật với VieNeu**: 20 dòng, 581 ký tự, 1 đoạn, sinh 20,4 s, FLAC 1,25 MB so với WAV 3,65 MB |
| Bộ cài Basic không có TTS local | Không có mã nguồn VieNeu, `sea-g2p`, `onnxruntime`, và build kiểm tra là chúng vắng mặt. Danh sách giọng đọc từ `worker/config/voice-catalog.json`, xuất bởi `worker/tools/export_voice_catalog.py` lúc build. Bản nghe thử là file tĩnh có sẵn ở `public/voice-previews` | `packaging/build_installer.py`, `tts/voices.py` | đọc danh sách 25 giọng khi không có VieNeu |
| 6. Hạ tầng và tài liệu | Terraform: tải mã nguồn VieNeu lên, cài ffmpeg, `requirements-tts.txt` (đường CPU không cần torch), biến `tts_workers` và `tts_threads`. Tài liệu đã cập nhật | `billing-gateway/deploy/gcp/` | `terraform validate` |

- Toàn bộ test worker: 315 test đạt, 1 skip có sẵn. `tsc` và ESLint sạch.
- **Chưa làm:**
  - Bước 5: đo CPU cloud, chạy nhiều worker, băng thông thật, chi phí mỗi 1000 ký tự. Lần đầu VM khởi động cần kiểm tra các thư viện trong `requirements-tts.txt` đủ cho VieNeu trên Linux; danh sách này mới suy ra từ mã nguồn.
  - Build lại 2 bộ cài (cần admin build).

Ký hiệu:
- **[Chốt]**: quyết định của chủ sản phẩm.
- **[Đề xuất]**: đề xuất kỹ thuật được giữ trong bản duyệt.
- **[Đo tiếp]**: số cần đo lại trên VM cloud. Chưa có số này vẫn triển khai được.

## 1. Tóm tắt

| Hạng mục | Kết luận |
|---|---|
| TTS gói Basic | Chạy qua VPS ở workflow chính, Tools 4 và Reprocess. Code local vẫn nằm trong bộ cài nhưng Basic không gọi [Chốt] |
| TTS gói Plus | Giữ local, miễn phí, không đổi [Chốt] |
| Tính phí TTS | Theo **ký tự tiếng Việt đầu vào** của các đoạn đã giao. Còn lại giống Translation: idempotent, hạn mức nợ, `PAUSED` kèm lý do, trạng thái job, sổ sách, Billing [Chốt] |
| Giọng và Kiểu giọng | Gửi kèm từng request. Mọi xử lý style chạy trên VPS [Chốt] |
| Thiết lập CPU/GPU | Không áp dụng cho Voice generation của Basic. VPS chỉ dùng CPU [Chốt] |
| Duyệt trước TTS | Basic dừng trước Voice generation để hỏi. Có ô **Auto** (chỉ ở Basic) để chạy thẳng [Chốt] |
| Truyền dữ liệu | Máy khách băm thành đoạn khoảng **1.200 ký tự**, gửi lần lượt và nhận audio từng đoạn. Ghép tại máy, lưu đến đâu chắc đến đấy, lỗi thì chạy tiếp từ đoạn gần nhất [Chốt cách làm; cỡ đoạn là Đề xuất theo số đo] |
| Định dạng audio trả về | **FLAC**: không mất dữ liệu, bằng 34% WAV [Chốt] |
| Nền tảng nhiều app | Gateway có `app_id` và `service`, admin-system quản lý theo app. **Làm trước TTS** [Chốt] |
| Hạ tầng | Bắt đầu với **một máy**, nâng cấp theo chiều dọc. Test trên VM GCP theo giờ rồi xóa [Đề xuất] |

## 2. Bước duyệt trước Voice generation (Basic)

**Ô Auto** [Chốt]
- Nhãn: "Auto: chạy liên tục, không hỏi trước khi tạo giọng".
- Có ở form tạo workflow chính và ở Tools 4. **Chỉ hiện ở gói Basic, mặc định tắt.** Plus không có vì TTS local miễn phí.

**Khi Auto tắt:**
- Workflow chính: Moderation xong thì dừng trước TTS.
- Tools 4: dừng ngay khi nhận file, trước khi tạo giọng.
- Trạng thái mới `AWAITING_REVIEW`. **Chưa gọi VPS, chưa tính phí.** Lúc này lane và RAM được trả lại cho workflow khác. [Đề xuất]
- Người dùng xem bản kiểm duyệt ở trang chi tiết. Nếu muốn sửa: tải về, sửa, rồi chạy Tools 4.
- Trang chính hiện 2 nút:
  - **Tiếp tục tạo giọng**: xếp hàng TTS qua VPS.
  - **Kết thúc**: workflow thành `COMPLETED`, chỉ có bản dịch và bản kiểm duyệt, không có voice. Workflow vào History và tự ẩn khỏi trang chính như các workflow hoàn tất khác. Sau này vẫn tạo giọng được bằng Reprocess từ TTS. [Chốt]
- `AWAITING_REVIEW` không tự hết hạn và không tính phí khi chờ. [Đề xuất]

**Khi không hỏi:**
- Reprocess từ TTS không hỏi lại, vì người dùng đã chủ động chọn chạy. [Chốt]
- Tools 4 vẫn hỏi, trừ khi bật Auto. [Chốt]

## 3. Giao thức TTS qua VPS

1. **Gom đơn vị đọc (máy khách):** gom dòng đã kiểm duyệt thành đơn vị đọc như hiện tại (`voice_styles.units`: tối đa 220 ký tự, giữ ranh giới cảnh). Default style vẫn là mỗi dòng một đơn vị. Sau đó gom tiếp thành **đoạn gửi khoảng 1.200 ký tự**, không cắt giữa một đơn vị. Cỡ đoạn là tham số cấu hình. [Đề xuất]
2. **Request `POST /v1/tts`:** gồm `app_id`, `job_id`, `chunk_no`, giọng, style và `[{unit_id, text}]`. License đặt trong header như Translation. [Đề xuất]
   - Idempotent theo `(job_id, chunk_no)`: gửi lại sau khi mất mạng thì nhận lại audio đã lưu tạm, không sinh lại, không tính phí lần hai.
   - VPS giữ audio đã giao trong một thời gian ngắn rồi xóa, ví dụ 24 giờ.
3. **Xử lý trên VPS:**
   - Sinh audio từng đơn vị, áp style (cắt lặng −45 dB, atempo), mã hóa FLAC.
   - Trả về **một gói nhiều FLAC** kèm `unit_id`, số mẫu và SHA của từng đơn vị.
   - Tính phí theo ký tự đầu vào của đoạn ngay khi giao.
   - Kiểm tra hạn mức trước mỗi đoạn, ước tính bằng chính số ký tự đầu vào nên biết trước chính xác.
   - Đơn vị nào sinh lỗi thì cả đoạn thất bại, không tính phí; máy khách gửi lại. [Đề xuất]
4. **Máy khách:**
   - Giải nén FLAC thành `voice/NNNNNN.wav` (mono, PCM16, 48 kHz). Kiểm tra SHA và ghi checkpoint như TTS local hiện tại.
   - Manifest, khoảng nghỉ giữa câu (`gap_after_ms`) và ghép `voice.vi.wav` giữ nguyên code hiện có, nên kết quả cuối có cùng định dạng với Plus.
   - **Gửi trước 1 đoạn** để việc tải về chạy song song với việc sinh.
5. **Chạy tiếp sau lỗi:** đơn vị đã có WAV hợp lệ thì giữ. Lần sau chỉ gửi các đơn vị còn thiếu, tức là chạy tiếp từ đoạn lỗi gần nhất. [Chốt]
6. **Hàng đợi VPS:**
   - Mỗi worker TTS là một tiến trình riêng, nạp model một lần.
   - Chia lượt giữa các khách theo vòng, để một truyện dài không chặn người khác.
   - Số worker = min(RAM trống ÷ 1,5 GiB, vCPU ÷ 4). [Đề xuất; Đo tiếp trên cloud]
7. **Lỗi mạng hoặc VPS bận:** thử lại có giãn cách.
   - Quá 10 phút thì `PAUSED`, lý do `GATEWAY_UNAVAILABLE`.
   - Vượt hạn mức thì `PAUSED`, lý do `CREDIT_LIMIT`.
   - Bấm Continue để chạy tiếp, như Translation. [Đề xuất]
8. **Basic:** TTS chạy qua VPS nên không áp dụng thiết lập CPU/GPU, không qua kiểm tra RAM local và lane không dành RAM cho model TTS. Trang Settings ghi chú điều này cho Basic. [Chốt]

## 4. Số đo hiệu năng (2026-10-06, máy chủ sản phẩm)

- Máy: Ryzen 7 5800H, 1 worker × 4 luồng CPU, FP32. Giọng Ngọc Huyền, style Drama, văn bản là các dòng đã kiểm duyệt của 000008.
- Chủ sản phẩm cho phép hạ chốt RAM xuống 1,5 GiB riêng cho lần đo này. RAM khả dụng thấp nhất đo được là 3,67 GiB.

| Cỡ đoạn | Ký tự | Thời gian sinh | Giây / 1000 ký tự | Audio | RTF | RSS worker |
|---|---|---|---|---|---|---|
| 300 | 350 | 10,4 s | 29,8 | 17,6 s | 0,60 | 1,43 GiB |
| 1.200 | 1.211 | 36,1 s | 29,8 | 61,9 s | 0,58 | 1,46 GiB |
| 4.800 | 4.818 | 137,4 s | 28,5 | 242,7 s | 0,57 | 1,48 GiB |

- **RAM mỗi worker khoảng 1,5 GiB** (ngay sau khi nạp model là 1,08 GiB). Nạp model mất 9–12 giây.
- **Khoảng 29 giây cho mỗi 1000 ký tự** với 1 worker. Tốc độ gần như không đổi theo cỡ đoạn.
- Khoảng 19,9 ký tự cho mỗi giây audio. Truyện 60 giờ có khoảng 4,3 triệu ký tự, nên **1 worker cần khoảng 34 giờ**. Muốn nhanh hơn thì phải có nhiều worker trên VPS.

| Mỗi 1000 ký tự | Dung lượng | Tải về ở 1 / 5 / 10 Mbps (tính toán, chưa đo mạng thật) |
|---|---|---|
| Văn bản gửi lên | khoảng 1,3 KB | không đáng kể |
| WAV 48 kHz | khoảng 4,84 MB | 38,7 / 7,7 / 3,9 s (ở 1 Mbps chậm hơn thời gian sinh) |
| **FLAC** | **khoảng 1,64 MB (34%)** | **13,1 / 2,6 / 1,3 s** |

- **FLAC không mất dữ liệu:** đã kiểm tra giải nén ra đúng từng mẫu như WAV. Nén mất 0,27 s, giải nén 0,10 s cho đoạn 4.800 ký tự.
- **Băm đoạn không làm giảm dung lượng.** Nó cho phép tải đoạn trước trong lúc VPS sinh đoạn sau, nên tổng thời gian chỉ còn bằng phần chậm hơn trong hai việc.
- Với FLAC và 1 worker, ở mọi băng thông từ 1 Mbps trở lên, việc tải về không làm chậm thêm.
- **Vì sao chọn 1.200 ký tự:**
  - Mỗi đoạn mất khoảng 36 giây sinh và 2 MB tải về.
  - Lỗi thì mất tối đa khoảng 36 giây công việc.
  - Có audio đầu tiên sớm.
  - Đoạn 4.800 chỉ nhanh hơn 4% nhưng khi lỗi mất tới 2,3 phút.
- **[Đo tiếp] trên VM GCP:**
  - Tốc độ CPU cloud.
  - Nhiều worker cùng lúc (RAM và tốc độ tổng).
  - Băng thông thực tế.
  - Chi phí cho mỗi 1000 ký tự, dùng để đặt giá bán.

## 5. Nền tảng dịch vụ chung (làm trước TTS)

- **Bảng sổ sách** của gateway (`jobs`, `chunks`, `billed_rows`, `costs`) thêm cột `app_id` và `service` (`translation` | `tts`). Dữ liệu Genius hiện có được gán `audio-translates` / `translation` bằng một lần di chuyển dữ liệu khi khởi động. [Đề xuất]
- **Bảng `apps`:** mỗi app có `app_id`, tên, các mã sản phẩm và khóa gốc license, cùng danh sách dịch vụ được bật. License chỉ được nhận nếu mã sản phẩm thuộc app đó. [Đề xuất]
- **Cài đặt** (giá, hạn mức mặc định, model, ngưỡng) theo `(app_id, service)`. Ví dụ: `translation` tính theo ký tự tiếng Việt thành phẩm, `tts` theo ký tự đầu vào. [Đề xuất]
- **Khách hàng:** mỗi khách có **một sổ nợ chung**, báo cáo tách theo app và dịch vụ. Hạn mức áp trên tổng nợ. Giá riêng có thể đặt cho từng `(khách, app, dịch vụ)`. [Đề xuất]
- **admin-system → Billing:** có bộ lọc theo app và dịch vụ, nút đẩy khóa gốc theo từng app, cột dịch vụ ở bảng job và chi phí. [Đề xuất]
- **Tương thích:** API `/v1/translate` hiện có vẫn chạy, mặc định `app_id = audio-translates`. [Đề xuất]

## 6. Hạ tầng

**Nhiều VPS trung bình hay một VPS cấu hình cao:**
- Trên cloud, giá gần như tỉ lệ thuận với số vCPU và RAM, nên chi phí cho mỗi 1000 ký tự gần như như nhau.
- Một máy tiết kiệm phần cố định (hệ điều hành, gateway, cloudflared: khoảng 0,5–1 GB RAM mỗi máy) và vận hành đơn giản hơn.
- Nhiều máy chỉ đáng khi cần dự phòng, hoặc tải lên xuống mạnh theo giờ.
- **Bắt đầu với một máy, nâng cấp theo chiều dọc.** Trên GCP, đổi cấu hình chỉ cần dừng VM, đổi loại máy và chạy lại.
- Khi cần, tách thành gateway trên máy nhỏ chạy liên tục và worker TTS trên máy lớn.

**Ước lượng theo số đo** (cần xác nhận trên cloud):
- Máy 4 vCPU chạy được khoảng 1 worker.
- Máy 8 vCPU / 16 GB chạy được khoảng 2 worker, tức khoảng 15 giây cho mỗi 1000 ký tự tính tổng.

**Băng thông:**
- VPS hiện tại không tính lưu lượng.
- GCP tính phí dữ liệu đi ra theo GB. FLAC chỉ bằng khoảng 1/3 WAV: một giờ audio khoảng 118 MB thay vì 345 MB.

**Cấu hình GCP:** `billing-gateway/deploy/gcp/`, viết theo mẫu ERP, đã `terraform validate`, **chưa tạo tài nguyên**.
- Spot VM `e2-standard-4`, không mở cổng nào ra Internet, SSH qua IAP.
- HTTPS qua Cloudflare Tunnel, key nằm trong Secret Manager, có cảnh báo ngân sách.
- Khi triển khai TTS sẽ bổ sung: model VieNeu và ffmpeg trên VM, biến cấu hình số worker, và loại máy theo số đo.

## 7. Thứ tự triển khai

1. **Nền tảng chung:** `app_id` và `service` trên gateway (kèm di chuyển dữ liệu Genius), bảng `apps`, cài đặt theo app và dịch vụ, admin-system Billing có bộ lọc. Test lại toàn bộ Genius.
2. **Bước duyệt trước TTS:** trạng thái `AWAITING_REVIEW`, nút Tiếp tục / Kết thúc, ô Auto (chỉ Basic) ở workflow chính và Tools 4. Áp dụng ngay cả khi TTS còn chạy local, để kiểm tra được giao diện.
3. **Dịch vụ TTS trên gateway:** `/v1/tts`, worker VieNeu, style, FLAC, hàng đợi chia lượt giữa các khách, idempotent, tính phí theo ký tự đầu vào, hạn mức.
4. **Client TTS trong app (Basic):** workflow chính, Tools 4 và Reprocess; gửi trước 1 đoạn; chạy tiếp từ đoạn lỗi; `PAUSED` kèm lý do; bỏ CPU/GPU và kiểm tra RAM TTS local ở Basic.
5. **Test trên VM GCP theo giờ:** đo CPU cloud, nhiều worker, băng thông thật và chi phí mỗi 1000 ký tự; chốt loại máy, số worker và giá bán; sau đó xóa VM.
6. **Tài liệu và bộ cài:** tăng version, build lại 2 gói, cập nhật `docs/` và `Agent.md`.

Mỗi bước chạy đủ test và chờ chủ sản phẩm kiểm tra rồi mới sang bước sau.
