# Kế hoạch cập nhật lớn: chế độ Genius, gói Basic / Plus, tính phí qua VPS

**Bản final**, chốt ngày 2026-10-06 sau 5 vòng trao đổi. Chủ sản phẩm đã duyệt; code giai đoạn 1–3 đã triển khai cùng ngày (mục 0).

## 0. Trạng thái triển khai (2026-10-06)

### Đã làm và đã kiểm thử

| Phần | Nơi | Kiểm thử |
|---|---|---|
| Tier theo mã sản phẩm: `identity`/`check` trả `tier`; action `credential` trả license đã ký; build.rs nhận `audio-translate[-basic\|-plus]`; mỗi gói có file license riêng (`state-<product>.dpapi`, sản phẩm cũ giữ `state.dpapi`) | `security-core/` | Rust 10/10; binary Basic tổng hợp trả `tier: basic` |
| Basic ẩn tiếng Trung: không xuất ZH, bỏ `text_zh` khỏi JSONL xuất, chặn Tools 1 và Reprocess từ Download/Transcription, chặn bảng nhân vật và route `/transcript`, bỏ `source` khỏi lỗi dịch | `worker/core/edition.py`, `workflow/results.py`, `manage.py`, `lib/server/edition.ts`, các route API, UI | `tests/test_edition.py` |
| Mã hóa bản làm việc (Basic): AES-256-GCM, khóa bảo vệ bằng DPAPI user; mở khi worker giữ `worker.lock`, khóa lại khi xong; Plus đọc được job Basic cũ | `worker/core/sealing.py` | như trên (kể cả file bị sửa thì bị từ chối) |
| 2 bộ cài: `build_installer.py --product`, config/anchor riêng từng gói, core build vào staging (không đè binary dev), thư mục cài `AudioTranslate/<Gói>-<version>`, shortcut riêng; Admin đăng ký manifest có `repo_root` và tự đăng ký 2 gói | `packaging/`, `products/basic\|plus/`, `admin-system/` | Admin 22/22 |
| Gateway VPS: dịch theo khối, JSON có cấu trúc, kiểm tra từng dòng (không kiểm tiếng Anh), sửa chỉ id lỗi kèm tiếng Việt ngữ cảnh, idempotent, tính phí một lần theo dòng, hạn mức trước mỗi khối, `ABANDONED` sau 24 giờ, sổ chi phí nội bộ, admin API | `../billing-gateway/` | 13/13 |
| Admin → **Billing**: URL + admin token (DPAPI), đẩy khóa gốc Basic/Plus, giá/model/ngưỡng, hạn mức và giá riêng từng khách, nhập thanh toán, xem nợ, job theo trạng thái, lịch sử thanh toán | `admin-system/billing.py`, `ui/app.js` | `test_billing.py` (qua HTTP thật) |
| App Genius: lựa chọn Normal/Genius ở workflow chính, Tools 2 và Reprocess (khi chạy lại từ Translation trở về trước); Genius ẩn Forms of address; thẻ nhân vật cuốn chiếu; checkpoint từng khối; `CREDIT_LIMIT` / license bị từ chối / mất kết nối quá 10 phút → PAUSED kèm lý do, Continue chạy tiếp; job gateway bị đóng thì tiếp tục bằng job mới mà không tính lại dòng đã giao | `worker/translation/genius.py`, `config/genius.json`, UI | `tests/test_genius.py` 8/8, kể cả qua orchestrator thật |

- Toàn bộ test worker: 306 test đạt, 1 skip có sẵn.
- `tsc`, ESLint và Next production build đều sạch.
- Chạy thật với Gemini 61 dòng (cảnh vòng tay): xem `billing-gateway/README.md`. Các lỗi giới tính ở dòng 402–405 và 426 của model local đều được dịch đúng.

### Khác với thiết kế

- **Bộ cài Basic vẫn chứa code Tools 1 và route tải bản tiếng Trung.** Next.js build chung một bản cho cả 2 gói, và code chép lời dùng chung với workflow. Basic chặn các phần này lúc chạy ở 3 lớp: UI, API và worker, theo mã sản phẩm đã biên dịch.
- **Kiểm tra và vòng sửa lỗi chạy trên VPS** (một request mỗi khối). App chỉ gửi khối và nhận kết quả cuối.
- **Dòng không đạt sau 3 lần sửa** giữ bản nháp cuối, đã bỏ chữ Hán/kana/hangul (để TTS đọc được). Dòng này không tính phí và hiện trong danh sách "cần sửa tay qua Tools 4".

### Việc còn lại (cần chủ sản phẩm)

1. **Deploy gateway lên VPS** theo `billing-gateway/README.md`: tên miền, Caddy, `GEMINI_API_KEY`, `ADMIN_TOKEN`.
2. **Điền `endpoint`** trong `worker/config/genius.json` trước khi build. Khi để trống, app báo Genius chưa cấu hình.
3. **Admin:** mở lại để tự đăng ký `audio-translate-basic` / `-plus` (tạo khóa gốc). Vào Billing → đẩy khóa gốc, đặt giá và hạn mức. Sau đó Products → Build Product cho từng gói. Kiểm tra bộ cài bằng `audit_package.py --edition basic|plus`. `smoke_installer.py` hiện vẫn chỉ kiểm sản phẩm cũ.
4. **Cấp license theo gói mới** cho khách. License sản phẩm cũ `audio-translate` không dùng được với bộ cài Basic/Plus, và không được bật Genius.
5. Kiểm tra điều khoản lưu dữ liệu của Gemini API và bảng giá token hiện hành (tham số trong Settings của gateway).
6. Giai đoạn 4 (Basic dùng TTS trên VPS, API ngân hàng) chưa làm, đúng như kế hoạch.

Ký hiệu:
- **[Chốt]**: quyết định của chủ sản phẩm.
- **[Đề xuất]**: đề xuất kỹ thuật đã được giữ trong bản duyệt. Các con số trong đó vẫn là tham số cấu hình, cần đo lại khi triển khai.

## 1. Tóm tắt

| Hạng mục | Kết luận |
|---|---|
| Chế độ dịch | **Normal** (model local Hy-MT2-7B) và **Genius** (Gemini qua VPS) [Chốt] |
| Gói sản phẩm | **Basic** và **Plus**, 2 bộ cài riêng, người bán chủ động cấp [Chốt] |
| Genius dành cho | Cả hai gói; áp cho workflow chính và Tools 2 [Chốt] |
| Gemini API key | Chỉ nằm trên VPS, không bao giờ xuống máy khách [Chốt] |
| Nội dung gửi Gemini | Chữ Hán; riêng vòng sửa lỗi được kèm tiếng Việt làm ngữ cảnh [Chốt] |
| Tính phí Genius | Theo **ký tự tiếng Việt thành phẩm**, ghi sổ ngay khi Gemini dịch xong; chủ sản phẩm chịu chi phí model [Chốt] |
| Hạn mức | Trả sau, có hạn mức nợ cấu hình trong admin-system; mọi request Gemini đều đối chiếu hạn mức [Chốt] |
| Thanh toán | Người bán nhập thủ công số tiền đã nhận; API ngân hàng làm sau [Chốt] |
| Bản tiếng Trung ở Basic | Không cho xem hay tải; bản làm việc giữ dạng **mã hóa** [Chốt] |
| Sửa bản dịch | Hủy chức năng sửa Markdown trong app; người dùng tải bản Moderated Markdown về sửa rồi chạy Tools 4 [Chốt] |
| Về sau | Basic bỏ TTS local, dùng TTS trên VPS có tính phí theo ký tự tiếng Việt đầu vào; Plus giữ TTS local miễn phí [Chốt hướng] |

## 2. Chế độ dịch Normal / Genius

- Giao diện chính có hai lựa chọn: **Normal** và **Genius (Fast and accurate)**. [Chốt]
- Chỉ khi chọn Normal mới hiện **Forms of address**. Với Genius, mục này bị ẩn có chủ ý: lớp xưng hô ở Moderation (`moderation/address.py`) cũng **không chạy**. Gemini xử lý xưng hô nhờ thẻ nhân vật (mục 4). Các luật thay từ khác của Moderation vẫn chạy như cũ. [Chốt]
- Genius áp cho workflow chính và cho **Tools 2** (văn bản Trung → văn bản Việt). [Chốt]
- Sau Translation, mọi chế độ đi tiếp Moderation → TTS như workflow gốc. [Chốt]

## 3. VPS trung gian

Cấu hình VPS hiện có:
- 4 vCPU, 6 GB RAM, 100 GB SSD, 1 IPv4.
- Băng thông quốc tế 1–10 Mbps, không giới hạn lưu lượng.

Cấu hình này đủ cho việc chuyển tiếp request và ghi sổ. Văn bản của một truyện chỉ vài trăm KB.

- App gửi khối tiếng Trung lên VPS. VPS giữ key, gọi Gemini, kiểm tra kết quả, trả về app và ghi sổ. [Chốt]
- Chỉ mở HTTPS. Key nằm trong biến môi trường hoặc file chỉ root đọc được. Không ghi key hay nội dung truyện vào log. [Đề xuất]
- Mỗi khối có khóa idempotent `job_id + chunk_no`. Nếu app gửi lại sau khi mất mạng, VPS trả kết quả đã lưu: **không gọi Gemini lần nữa và không tính phí hai lần**. [Đề xuất]
- Xác thực request bằng license của máy (mã khách + mã máy), không dùng khóa dùng chung. [Đề xuất]
- VPS là điểm hỏng duy nhất. App giữ checkpoint từng khối và tự chạy tiếp khi VPS hoạt động lại. [Đề xuất]
- Model Gemini chọn bằng cấu hình trên VPS, không gắn cứng trong app. [Đề xuất]

## 4. Luồng dịch Genius

Các con số dưới đây là điểm xuất phát **chưa đo**. Cần thử trên workflow 000008 và 000009, sau đó để thành tham số cấu hình trên VPS.

1. **Chia khối:** 80–120 dòng mỗi lượt, khoảng 1.000–1.500 chữ Hán. Ví dụ 000008 có 1048 dòng, tức khoảng 10 lượt. Không gửi cả truyện một lượt: đầu ra dài dễ bị cắt hoặc bỏ dòng, và hỏng một lần là mất cả lượt. [Đề xuất]
2. **Ngữ cảnh chỉ để đọc:** gửi kèm 5–20 dòng liền trước khối. Gemini không dịch và app không ghi lại các dòng này. [Đề xuất]
3. **Thẻ nhân vật cuốn chiếu:** dùng thay cho lượt chuẩn bị. Lượt chuẩn bị đã bị bỏ: một truyện 60 giờ có khoảng 170 nghìn dòng (gần 2 triệu chữ Hán), đọc trước cả truyện sẽ làm gấp đôi token đầu vào. [Chốt]
   - Thẻ ban đầu lấy miễn phí từ dữ liệu app có sẵn: danh sách tên Hán-Việt và bảng nhân vật nháp.
   - Mỗi lượt, Gemini trả thêm nhân vật mới hoặc thông tin thay đổi (vài chục token). App gộp vào thẻ cho lượt sau.
   - Thẻ chỉ giữ 20–30 nhân vật gần nhất. Ước tính đầu vào mỗi lượt tăng thêm 5–15%.
4. **Đầu ra JSON có cấu trúc:** mỗi dòng trả về dạng `[{id, vi}]`. App **ghép theo `id`**, nên bản dịch luôn khớp đúng dòng và mốc thời gian. Model local thì khác: nó dùng thẻ `<sN>`, tối đa 6 dòng mỗi lượt. [Đề xuất]
5. **Kiểm tra mỗi lượt:** [Chốt bỏ kiểm tra tiếng Anh; phần còn lại Đề xuất]
   - Có đủ và đúng tập `id`.
   - Không có dòng rỗng, trừ dòng quảng cáo đã bị bỏ.
   - Không còn chữ Hán, kana, hangul hay chữ viết khác. **Không kiểm tra tiếng Anh.**
   - Tỉ lệ độ dài Việt/Trung hợp lý.
   - Không lặp câu giữa các dòng kề nhau.
6. **Vòng sửa lỗi:** [Chốt kèm tiếng Việt làm ngữ cảnh; phần còn lại Đề xuất]
   - Chỉ dịch lại các `id` bị lỗi, kèm 2–3 dòng trước và sau làm ngữ cảnh. Phần ngữ cảnh gồm chữ Hán và bản dịch tiếng Việt đã đạt.
   - **Chỉ thế vào các dòng lỗi**, không thế phần ngữ cảnh. Thế cả ngữ cảnh sẽ ghi đè dòng đúng và gây lặp nội dung.
   - Tối đa 3 lần. Sau 3 lần vẫn lỗi thì đánh dấu dòng để người dùng tự sửa qua Tools 4.
7. **Lỗi 429 hay lỗi mạng:** thử lại có giãn cách; một lần chậm không bị coi là lỗi dịch. Checkpoint từng khối. [Đề xuất]
8. **Làm sạch trước khi gửi:** các lớp làm sạch tiếng Trung hiện có (cắt quảng cáo kênh, sửa lỗi ASR) chạy trước khi gửi, giống chế độ Normal. [Đề xuất]

## 5. Tính phí, hạn mức, thanh toán

### Đơn vị và thời điểm tính [Chốt]
- Phí tính theo số ký tự tiếng Việt của **các dòng đã dịch xong và đạt kiểm tra**.
- Mỗi dòng (`job_id + row_id`) chỉ tính **một lần**. Các lần Gemini dịch lại do lỗi là chi phí của chủ sản phẩm. Phần tiếng Việt gửi kèm làm ngữ cảnh trong vòng sửa lỗi không tính cho khách.
- Ghi sổ ngay khi VPS giao một khối đạt yêu cầu. Người dùng sửa bản dịch về sau không làm thay đổi số tiền.
- **Reprocess Translation và mỗi lượt Tools là một job mới, tính phí mới.**
- Định nghĩa ký tự: ký tự Unicode sau chuẩn hóa NFC, không tính khoảng trắng. [Đề xuất]

### Trạng thái job [Chốt]

| Trạng thái | Khi nào | Tính phí |
|---|---|---|
| `IN_PROGRESS` | Đang dịch hoặc tạm dừng | Các dòng đã giao |
| `COMPLETED` | Mọi dòng đã dịch | Toàn bộ |
| `CANCELLED` | App gửi lệnh hủy | Các dòng đã giao |
| `ABANDONED` | Không hoạt động sau **24 giờ** | Các dòng đã giao |

Người dùng không thể né phí bằng cách hủy job: VPS tính theo số dòng **đã giao**, không theo báo cáo của app.

### Sổ sách hai phần [Đề xuất]
- **Phần tính cho khách:** số ký tự thành phẩm, ghi theo job, khách và trạng thái.
- **Phần chi phí nội bộ:** token vào và ra, số lần thử lại, model, chi phí ước tính theo khối. Dùng để đo biên lợi nhuận và lập công thức giá.
- Công thức giá (giá mỗi 1.000 ký tự, phí tối thiểu…) là **tham số trong admin-system**, vì chưa chốt con số.

### Hạn mức nợ [Chốt]
- admin-system đặt hạn mức cho từng khách.
- **Mọi request Gemini** đều đối chiếu hạn mức, kể cả khi đang giữa một job hay một lượt Tools.
- Công thức: `nợ hiện tại = tổng đã tính phí − tổng đã thanh toán`.
- Trước mỗi khối, VPS kiểm tra `nợ hiện tại + ước tính của khối ≤ hạn mức`, để không vượt hạn mức giữa chừng. Ước tính = số chữ Hán của khối × hệ số Việt/Trung đo được. [Đề xuất]
- Khi vượt hạn mức, VPS từ chối với mã `CREDIT_LIMIT`. App tạm dừng job (giữ checkpoint) và báo người dùng. Job chạy tiếp được sau khi thanh toán. [Đề xuất]

### Thanh toán [Chốt]
1. Người bán nhập thủ công số tiền đã nhận trong admin-system; số này trừ vào nợ. Lưu lịch sử: ai nhập, khi nào, số tiền, ghi chú.
2. API ngân hàng: làm sau.

## 6. Gói Basic / Plus

### Đóng gói [Chốt]
- Có 2 bộ cài, mỗi bộ một **mã sản phẩm riêng**: `audio-translate-basic` và `audio-translate-plus`.
- security-core gắn mã sản phẩm lúc build (`EMBEDDED_PRODUCT_ID`) và từ chối license khác mã (`WRONG_PRODUCT`). Vì vậy license Basic không kích hoạt được bộ cài Plus.
- Cần sửa:
  - `packaging/build_installer.py` đang gán cứng `product_id == 'audio-translate'`.
  - Mỗi gói cần `product.manifest.json`, `licensing/public-config.json` và tên file `.exe` riêng.
  - Đăng ký 2 sản phẩm trong admin-system.
- Bộ cài Basic **không đóng gói** những phần không dùng: Tools 1 và route tải bản tiếng Trung. Phần dùng chung kiểm tra gói lúc chạy theo mã sản phẩm đã gắn. [Đề xuất]
- Mỗi lần phát hành: build, kiểm thử và đăng ký cả 2 bộ cài. Nâng Basic lên Plus là cài bộ cài kia và cấp license mới; dữ liệu cũ phải dùng lại được. [Đề xuất]

### Basic: không cho xem hay tải bản tiếng Trung [Chốt]
Mục đích là không để người dùng lấy bản tiếng Trung đem chạy dịch vụ dịch bên ngoài. Các nơi chứa tiếng Trung đều bị ẩn trên giao diện **và** bị từ chối ở API/worker:

| Nơi chứa tiếng Trung | Xử lý |
|---|---|
| `transcript.zh.jsonl` / `.md` | Không xuất vào thư mục kết quả, không xem, không tải |
| Trường `text_zh` trong Vietnamese JSONL và Moderated JSONL | Bỏ khỏi file xuất |
| Bảng nhân vật (tên gốc, bí danh) | Ẩn |
| Tools 1 (Audio Trung → Văn bản Trung) | Ẩn và từ chối |
| Reprocess từ Download / Transcription | Ẩn và từ chối |
| Route xem/tải file (`/api/jobs/[id]/artifacts`) | Từ chối theo gói |

- **Bản làm việc tiếng Trung giữ dạng mã hóa DPAPI** (chỉ app trên đúng máy đó đọc được). Nhờ vậy Reprocess từ Translation vẫn chạy được mà không phải chép lời lại. [Chốt]
- Bảo vệ ở mức **gây khó**, không tuyệt đối: ASR chạy trên máy khách nên văn bản tiếng Trung luôn tồn tại trong bộ nhớ trong lúc xử lý. Ở chế độ Genius, văn bản còn đi qua mạng (đã mã hóa HTTPS).

### Lộ trình về sau [Chốt hướng; chi tiết thiết kế khi đến giai đoạn đó]
- Basic bỏ **Voice generation chạy local**.
- Basic dùng TTS chạy trên VPS, tính phí theo **ký tự tiếng Việt đầu vào**, vì TTS chỉ đọc tiếng Việt.
- Plus giữ TTS local, **miễn phí**.
- Lưu ý kỹ thuật: VPS hiện tại có 4 vCPU và không có GPU. Chưa đo tốc độ VieNeu trên cấu hình này, nên có thể phải nâng VPS hoặc chạy một máy TTS riêng.

## 7. Sửa bản dịch bằng Tools 4 [Chốt]

Đã kiểm tra trong code (`normalize_input`, file `worker/audio_translate/workflow/manage.py`):
- Tools 4 nhận `.txt`, `.md`, `.jsonl`.
- Với TXT/MD, mỗi dòng không trống là một câu cần đọc; không cần mốc thời gian.
- Có bộ chọn giọng và Kiểu giọng.
- Giới hạn 64 KiB mỗi dòng, 64 MiB mỗi file.

**Chưa chạy thử với file sửa tay.**

Hướng dẫn cho người dùng:
- Sửa bản **Moderated Vietnamese Markdown**, vì Tools 4 bỏ qua bước kiểm duyệt. Nếu sửa bản chưa kiểm duyệt thì chạy Tools 3 trước, rồi mới chạy Tools 4.
- Giữ văn bản thuần: không thêm `#` hay `**…**`.
- Chọn cùng giọng và Kiểu giọng với workflow gốc.
- Kết quả nằm trong lịch sử Tools, không gắn với số workflow gốc.

## 8. Ràng buộc kỹ thuật khi triển khai

- security-core chặn mọi lệnh lạ (`command_protected` → `INVALID_ACTION`). Mỗi action mới của `manage.py` (dịch Genius, kiểm tra gói…) phải được thêm vào allowlist, build lại Rust và tăng version.
- Tăng version sản phẩm trước khi build installer; đăng ký manifest mới trong admin-system.
- Văn bản truyện được gửi cho Google qua VPS: cần kiểm tra điều khoản lưu dữ liệu của Gemini API và thông báo cho khách. [Đề xuất]
- Job cũ và chế độ Normal giữ nguyên hành vi hiện tại; các test hiện có phải tiếp tục đạt, trừ 5 lỗi RAM cũ đã biết.

## 9. Thứ tự triển khai

1. **Gói Basic / Plus và ẩn tiếng Trung.** Chỉ làm ở local, không phụ thuộc VPS. Gồm: mã sản phẩm, build 2 bộ cài, ẩn và chặn tiếng Trung, mã hóa bản làm việc.
2. **Dịch vụ VPS:**
   - Chuyển tiếp Gemini, kiểm tra kết quả, khóa idempotent, ghi sổ, hạn mức, chuyển `ABANDONED` sau 24 giờ.
   - Màn hình admin-system: hạn mức, công thức giá, nhập thanh toán, xem nợ và trạng thái job.
3. **Genius trong app:** lựa chọn Normal / Genius, ẩn Forms of address, áp cho workflow chính và Tools 2, xử lý `CREDIT_LIMIT`.
4. **Về sau:** Basic chuyển sang TTS trên VPS có tính phí; kết nối API ngân hàng.

Mỗi giai đoạn chạy đủ test và được chủ sản phẩm kiểm tra rồi mới sang giai đoạn sau.
