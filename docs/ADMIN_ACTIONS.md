# Các nút trong admin: làm gì, lấy giá trị ở đâu

Trạng thái: 2026-10-08 (cập nhật sau lượt sửa nút Billing). Nội dung dựa trên mã `admin-system/ui/app.js`, `core.py`, `billing.py` và dữ liệu thật trên VM. Chưa bấm thử từng nút trên giao diện đã đăng nhập.

## 1. Customers → Xem chi tiết → bảng quyền sử dụng

| Nút | Làm gì | Giá trị cần nhập và lấy ở đâu |
|---|---|---|
| **Tạo kích hoạt offline** (Create Offline Activation) | Cấp token kích hoạt lần đầu cho một quyền sử dụng chưa gắn máy. Token gắn với đúng một máy. Hạn dùng = ngày kích hoạt + số ngày của quyền sử dụng. | **Mã máy** (`machine_id`, 64 ký tự). Khách mở app → trang **Giấy phép** → ô "Mã máy" → Sao chép → gửi cho bạn. Kết quả là hộp "Token đã ký": gửi riêng cho khách, khách dán vào ô "Mã kích hoạt" rồi bấm "Xác minh và lưu". |
| **Đặt lại / Thay máy** (Reset / Replace Device) | Gỡ máy cũ khỏi quyền sử dụng để khách kích hoạt máy khác (đổi PC). | Hai ô nhập: **lý do** hỗ trợ (5 đến 500 ký tự, được ghi vào nhật ký) và gõ đúng **`REPLACE DEVICE`**. Sau đó dùng "Tạo kích hoạt offline" với mã máy mới. Lưu ý: token offline đã gửi cho máy cũ **không thu hồi được**, máy cũ vẫn chạy được tới khi token đó hết hạn. |

## 2. Giấy phép (trang Licenses, đã gộp với trang Gia hạn)

Mỗi dòng là một bản ghi giấy phép: **thứ tự 1** là lần kích hoạt đầu, **thứ tự lớn hơn 1** là các lần gia hạn. Bộ lọc **Loại** chọn *Tất cả / Giấy phép (thứ tự 1) / Gia hạn (thứ tự lớn hơn 1)*, không cần cột riêng.

| Nút | Làm gì | Giá trị |
|---|---|---|
| **Mã khách** (Customer Code) | Hiện Mã khách hiện tại của giấy phép, **không đổi gì**. Khách nhập mã này ở `billing.arsneonci.space` để mua/gia hạn hoặc trả nợ. Dạng `XXXXX-XXXXX`. | Không nhập gì. Đây **không phải** `customer_id` trong bảng Customers; mã được tạo riêng cho từng giấy phép. Chưa có mã thì báo rõ và không tạo mới. |
| **Cấp lại mã khách** (Reissue Customer Code) | Tạo mã mới, **mã cũ ngừng dùng ngay**. Dùng khi mã bị lộ hoặc khách làm mất. | Có hộp xác nhận. Đừng bấm nếu chỉ muốn xem mã (dùng nút Mã khách). |
| **Token Giấy phép** (License Token) | Hiện lại token đã ký của đúng dòng đó để gửi lại cho khách. Không tạo token mới và không đổi hạn. | Không nhập gì. |
| **Gia hạn** (Renew) | Tạo token gia hạn có thứ tự kế tiếp. | **Số ngày**. Hộp thoại hiện ngay "Hạn hiện tại → Hạn mới". Gửi token cho khách dán vào ô Gia hạn trong app, hoặc khách tự mua qua cổng thanh toán (token tự được cài vào app). |

### Gia hạn được cộng dồn
Quy tắc ở server (`core.py`, hàm `renew`): **hạn mới = lớn hơn của (bây giờ, hạn hiện tại) + số ngày**. Không có chuyện "đợi cái cũ hết mới tính cái sau". Dữ liệu thật của giấy phép đang dùng: thứ tự 1 hết hạn 8/10/2026, thứ tự 2 (+1 ngày) hết hạn 9/10/2026, thứ tự 3 (+365 ngày) hết hạn 9/10/2027, tức đã gồm cả hai lần trước.
Lõi bảo mật của app bắt buộc nhập token **đúng thứ tự** (2 rồi 3), nhưng mỗi token đã mang sẵn mốc hạn cộng dồn nên sau khi nhập hết thì hạn là mốc cuối. Cho phép nhập thẳng token mới nhất (bỏ qua các token trung gian) cần sửa lõi Rust và build lại app, chưa làm.

## 3. Sản phẩm và Billing (cập nhật 2026-10-08)

| Nút | Ở trang | Làm gì |
|---|---|---|
| **Đồng bộ khóa với gateway** (Sync Keys with Gateway) | **Sản phẩm** | Gộp hai việc: gửi sang gateway khóa công khai gốc và dịch vụ của từng app (để xác minh token khách), rồi gửi khóa của từng **phiên bản app** (lease). Bấm khi đăng ký sản phẩm/edition mới, thêm app, hoặc ra **số phiên bản mới**. Build lại cùng số phiên bản thì không cần. Bấm lại không hại gì. Thiếu lease thì gateway trả `LEASE_VERSION_UNSUPPORTED` và app không mở được kho tài nguyên (danh sách giọng không tải). |
| **Địa chỉ Gateway & Admin Token** | Billing | **Ẩn khi đã cấu hình** (admin trên server lấy địa chỉ và token từ biến môi trường). Chỉ hiện trên admin chưa cấu hình. |
| **Ứng dụng** (App) | Billing | Ô chọn app đang xem giá và cài đặt. Chỉ một app thì hiện tên app như nhãn, từ hai app trở lên mới là ô chọn. |
| **Làm mới** | Billing | Tải lại dữ liệu **từ gateway** (khách, nợ, chi phí, cài đặt) và vẽ lại. Không tải lại bảng của admin (giấy phép, khách hàng), phần đó đổi sau mỗi thao tác hoặc khi tải lại trang. |

Trang **Máy** chỉ còn là bảng xem: một máy chỉ xuất hiện sau khi quyền sử dụng được kích hoạt (từ Quyền sử dụng hoặc từ chi tiết khách), nên nút "Thêm máy" cũ bị gỡ vì trùng.

## 4. Cài đặt Billing: ý nghĩa từng ô

Tất cả nằm ở gateway (cơ sở dữ liệu trên VM), admin chỉ chỉnh qua API.

**Cài đặt chung**
- **Giữ các dòng công việc (180 ngày):** mỗi lần dịch Genius/tạo giọng là một dòng (mã job, khách, nhãn ≤ 200 ký tự, số ký tự, số tiền, trạng thái). Hết hạn thì gộp thành số liệu theo tháng (khách × app × dịch vụ) rồi xóa, nợ không đổi.
- **Giữ chi tiết từng đoạn (24 giờ sau khi job đóng):** có lưu **bản dịch tiếng Việt** của từng đoạn để gửi lại khi app thử lại; văn bản Trung gốc chỉ lưu mã băm. Hết hạn thì xóa.
- **Giữ các dòng chi phí nội bộ (30 ngày):** mỗi lần gọi Gemini một dòng (token vào/ra/suy luận, USD). Là tiền vốn của bạn, không phải tiền khách trả. Hết hạn thì gộp theo ngày/app/dịch vụ/model rồi xóa.
- **Giữ sự kiện lease (90 ngày):** mỗi lần app xin lease ghi mã license, mã máy, loại, thời điểm, không có nội dung khách. Dùng phát hiện lạm dụng: từ 5 lần bị từ chối trong 60 phút thì bị đánh dấu, tự thu hồi nếu bật `auto_revoke` (mặc định tắt). Sự kiện thu hồi/khôi phục giữ mãi.

**Dịch Genius**
- **Tỉ lệ ký tự Việt/Trung (3,5):** chỉ để **ước tính trước** khi gọi Gemini: chữ Trung của đoạn × tỉ lệ = số ký tự Việt dự kiến; nếu nợ + tiền dự kiến vượt hạn mức thì chặn (`CREDIT_LIMIT`, 402). Tiền khách trả thật tính theo ký tự thực tế (đã bỏ khoảng trắng). **Số đo ngày 2026-10-08** trên 6 bản dịch thật có sẵn trên máy (39.099 chữ Trung): ký tự tính tiền / chữ Trung = **3,08** (từ 2,91 đến 3,20; hai mẫu Genius 2,91 và 3,03). Vậy 3,5 là mức an toàn cao hơn thực tế khoảng 14%; 3,2 vẫn còn dư. Chưa thử được với Gemini thật vì khóa API đang bị chặn (mục 6).
- **Số vòng sửa lỗi (3):** dòng dịch lỗi (thiếu, rỗng, lẫn chữ Trung/Nhật/Hàn, quá ngắn/dài, lặp câu trước) được gửi lại tối đa 3 vòng. Hết vòng mà vẫn lỗi thì gắn cờ, giữ bản nháp tốt nhất (đã bỏ chữ lạ), **không tính tiền** dòng đó. Mỗi vòng là thêm một lần gọi Gemini.
- **Tỉ lệ độ dài Việt/Trung tối thiểu (1) / tối đa (12):** dòng từ 4 chữ Hán trở lên có số ký tự Việt phải ≥ min × số chữ Hán và ≤ max × số chữ Hán + 40, ngoài khoảng đó bị coi là quá ngắn/quá dài và vào vòng sửa.
- **Nhiệt độ (0,3):** tham số của Gemini (khoảng 0 đến 2) điều khiển độ ngẫu nhiên khi chọn từ tiếp theo: xác suất của từ được chia cho nhiệt độ trước khi chọn. Gần 0 thì luôn chọn từ xác suất cao nhất (ổn định, bám nghĩa); 1 là phân bố gốc; lớn hơn thì ngẫu hứng, dễ lệch nghĩa. Gateway chỉ kiểm giá trị là số không âm, không có trần.
- **Ngân sách suy luận (-1):** số token tối đa model "nghĩ" trước khi trả lời, cho model Gemini có chế độ suy nghĩ. -1 để model tự quyết, 0 tắt (rẻ hơn, kém chính xác hơn), số dương là giới hạn cứng. Token suy nghĩ tính vào chi phí nội bộ.

**Giọng đọc (TTS)**
- **Yêu cầu lớn nhất (3000):** trần phía server cho **một** yêu cầu tạo giọng; lớn hơn thì bị từ chối.
- **Kích thước đoạn băm (1200), ô mới ngay dưới ô trên:** app cắt kịch bản thành các đoạn cỡ này, mỗi đoạn là một yêu cầu và được lưu ngay khi xong, nên kịch bản 700.000 đến 1.000.000 ký tự chỉ là hàng trăm đoạn nối tiếp, lỗi giữa chừng chỉ làm lại đoạn đó. Giá trị đặt ở admin, app đọc qua `GET /v1/tts/settings` khi bắt đầu tạo giọng (không cần build lại để đổi). Không được vượt ô "Yêu cầu lớn nhất" (gateway từ chối `CHUNK_LARGER_THAN_MAX`), tối thiểu 100. Đoạn nhỏ hơn: lỗi tốn ít công làm lại nhưng nhiều yêu cầu hơn; đoạn lớn hơn: ít yêu cầu nhưng mỗi lần chờ lâu hơn. Mức tối ưu chưa đo; 1200 là giá trị hiện dùng.

## 5. Kiểm tra chữ Trung trước bước tạo giọng

Ở chế độ **Auto** (Basic) bản dịch đi thẳng vào bước tạo giọng có tính phí mà không có người xem lại. Dòng Genius bị gắn cờ vẫn có thể đi vào đó, và bản dịch chạy trên máy cũng có thể còn sót chữ Trung (tên riêng chưa dịch, hoặc quy tắc thay thế đưa chữ lạ vào). Giọng sẽ đọc sai và bạn trả tiền cho đoạn âm thanh hỏng.
Vì vậy ngay trước bước tạo giọng, `worker/audio_translate/tts/voice_check.py` duyệt từng dòng của `transcript.vi.moderated.jsonl`: xóa chữ Hán, kana, hangul; dọn ngoặc rỗng và khoảng trắng thừa trước dấu câu; dòng không còn gì thì thành "…" (một quãng nghỉ). Dòng sạch không bị đụng; chạy lại không đổi gì; kết quả ghi ở `working/voice-check.json`. Áp dụng cho cả Normal và Genius.

## 6. Sự cố đang mở: khóa Gemini bị chặn theo IP

Ngày 2026-10-08 mọi lệnh gọi Gemini bằng khóa trong cấu hình gateway đều trả `403 PERMISSION_DENIED`: *"The provided API key has an IP address restriction. The originating IP address of the call (34.97.47.166) violates this restriction"*. 34.97.47.166 là IP ra ngoài hiện tại của VM (cũng bị chặn từ máy cá nhân). Nhiều khả năng khóa đang chỉ cho phép IP của VM cũ đã xóa. Hệ quả: dịch Genius của khách đang hỏng. Cách sửa (làm trong Google AI Studio / Cloud Console, phần giới hạn của khóa): thêm IP hiện tại của VM vào danh sách cho phép, hoặc bỏ giới hạn IP và chỉ giới hạn theo API "Generative Language". Lưu ý VM là Spot (`STOP`) và IP ngoài là IP tạm: nên **đặt IP tĩnh** cho VM, nếu không IP có thể đổi sau mỗi lần VM dừng/khởi động và lỗi này lặp lại.

## 7. Nút trong chi tiết khách (2026-10-09)

Mã khách, Cấp lại mã khách và Gia hạn tác động lên **cả license** (mọi bản ghi thứ tự của nó), nên trong **Customers > Xem chi tiết** chúng nằm ở **dòng sản phẩm** (bảng quyền sử dụng), mỗi license một lần, và lấy bản ghi mới nhất làm gốc. Quyền sử dụng chưa kích hoạt chưa có license nên chưa có ba nút này. Bảng giấy phép bên dưới chỉ còn nút **Token Giấy phép** trên từng bản ghi. Trang **Giấy phép** chung vẫn giữ đủ bốn nút trên mọi hàng.

**Định danh khi thanh toán không phụ thuộc vào mã khách.** License còn hạn: app gửi token license (đã ký, chứa `license_id`, `customer_id`, `product_id`) để xin link một lần, nên cổng biết đúng khách và license từ chữ ký. Mã khách chỉ là đường vào cho license đã hết hạn. Mỗi đơn thanh toán lưu `customer_id`, `license_id`, `product_id` lúc tạo; đối soát payOS đi theo mã đơn, nên đổi mã khách không ảnh hưởng đơn đang có hay đã trả.

**Cột khách hàng (2026-10-09):** các bảng Quyền sử dụng, Máy và Giấy phép hiện **tên khách hàng** thay cho mã 32 ký tự (cột "Khách hàng" / "Customer"). Mã vẫn nằm trong dữ liệu của từng dòng nên tìm kiếm theo mã vẫn dùng được và các nút vẫn dùng đúng khách; bộ lọc theo khách ở trang Giấy phép liệt kê tên. Khách đã bị xóa thì hiện lại mã. Bảng Khách hàng giữ cột mã.
