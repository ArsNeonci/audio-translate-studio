# Thanh toán tự động qua payOS (VietQR) và cổng Billing (phí dịch vụ, bản quyền): thiết kế

Trạng thái: **đã triển khai cả 6 bước, chờ chủ sản phẩm kiểm tra bằng một giao dịch thật** (bản 6, 2026-10-07; xem mục 15 về những gì đã chạy, những chỗ khác bản thiết kế và cách thử; trước đó: tải báo cáo ở mục 9.2 bước 8 và 9.4; chủ sản phẩm đã chốt toàn bộ các quyết định, gồm cả luồng cấp token tức thì, vòng đời dữ liệu và thứ tự triển khai). Tài liệu này thay mục "API ngân hàng: làm sau" trong [PLAN_GENIUS_BASIC_PLUS.md](PLAN_GENIUS_BASIC_PLUS.md) (mục 5 *Thanh toán*, mục 9 bước 4) và dòng "Thanh toán hiện nhập tay" trong `Doc-Admin.md` mục 4.1.

Ký hiệu: **[Chốt]** là điều chủ sản phẩm đã quyết. **[Đề xuất]** là con số hoặc chi tiết do agent đặt, chỉnh được khi triển khai. **[Kiểm chứng]** cần thử với payOS hoặc Cloudflare thật trước khi coi là đúng.

---

## 0. Phạm vi và các quyết định đã chốt

| # | Hạng mục | Quyết định |
|---|---|---|
| 1 | Webhook payOS tự ghi nhận thanh toán và trừ nợ | Làm |
| 2 | Admin tạo link/QR cho khách | Làm |
| 3 | Endpoint webhook công khai | Làm, trên VM GCP mới (mục 9) |
| 4 | Khi gặp `CREDIT_LIMIT`, app có nút trả nợ | Làm, mở cổng Billing |
| 5 | Trả xong thì job chạy tiếp | **Người dùng tự bấm Tiếp tục** [Chốt] |
| 6 | Gia hạn license sau khi trả tiền | **Admin tự ký**; có vấn đề thì xử lý tay. **Cấp tức thì** qua kênh gọi trực tiếp (mục 6.4), quét 5 phút chỉ là dự phòng [Chốt] |
| 7 | Kích hoạt lần đầu | **Giữ thủ công** (dùng thử, khuyến mãi) [Chốt] |
| 8 | App hiện hạn dùng, nợ; nút mua gói | Làm, mở cổng Billing |
| 9 | Lịch sử phân biệt payOS và nhập tay | Làm |
| 10 | Đối soát | Làm |
| A | Hạn mức dịch vụ ("token") | **Chỉ hạn mức nợ (VND), chỉnh được theo app**. Dùng nhiều trả nhiều; không có hạn mức số lượng [Chốt] |
| B | Nạp trước | **Không**. Dịch vụ chỉ trả nợ [Chốt] |
| C | Giá riêng từng khách | **Có**, cho cả dịch vụ và gói license [Chốt] |
| D | Giá license | **Hai kiểu**: theo số ngày, và gói theo tháng 1/3/6/9/12. Gói 12 tháng = **365 ngày**. Hiển thị **giá/tháng** làm chính để thấy gói dài rẻ hơn; tổng tiền hiện nhỏ hơn [Chốt] |
| E | Thanh toán qua **domain công khai** | **Cổng Billing** tại `billing.<domain>`. Tên "billing" vì đây là phí dịch vụ và phí bản quyền, không phải bán hàng hóa. Chủ sản phẩm chỉnh gói và giá mà không phải sửa app. Trả xong, server giao token license để khách lưu vào app [Chốt] |
| F | Thư viện payOS | SDK chính thức `payos` cho Python (mục 1.4) [Chốt] |
| G | Trang dự phòng nhập **Mã khách hàng** | **Có** (mục 6.1) [Chốt] |
| H | Dữ liệu VM cũ | Không có bản sao lưu và không cần: **xây mới** trên VM GCP (mục 9) [Chốt] |
| I | Cấp token ngay khi tiền về | Kênh **long-poll từ admin ra gateway**: webhook đánh thức admin, admin ký và giao token trong vài giây (mục 6.4) [Chốt] |
| J | Một tiến trình gateway, **hai hostname** | `billing.<domain>` cho khách, `audio-gateway.<domain>` cho app và admin. Tách host để route admin không bao giờ chạm tới người dùng (mục 2) [Chốt] |
| K | Giới hạn đơn | Tối đa 3 đơn đang mở mỗi license, đơn hết hạn sau 15 phút (mục 3.1) [Chốt] |
| L | Dữ liệu phát sinh hằng ngày | Dữ liệu nặng, phát sinh liên tục mỗi người dùng thì **dọn và tổng hợp**; dữ liệu thưa thì giữ lâu (mục 9.3). Con số mặc định chỉnh được [Đề xuất] |
| M | Thứ tự triển khai | Sáu bước ở mục 13 [Chốt] |
| N | Tải báo cáo | Admin tải báo cáo CSV theo kỳ; mỗi tháng lưu một bộ báo cáo lên Cloud Storage trước khi dữ liệu chi tiết bị dọn (mục 9.4) [Chốt] |

"Token dịch vụ" là mức dùng Genius/TTS, tính theo ký tự. "Token license" là chuỗi ký Ed25519 mà khách dán vào app. Tài liệu luôn ghi rõ là loại nào.

"Billing" xuất hiện ở ba nơi, đừng nhầm:
- **Cổng Billing**: trang web cho khách tại `billing.<domain>`.
- **billing-gateway**: tiến trình trên VM phục vụ cổng đó và API.
- **trang Billing / Payments trong admin-system**: giao diện quản lý của chủ sản phẩm.

---

## 1. Ràng buộc định hình thiết kế

1. **Webhook cần URL công khai.** admin-system chỉ nghe `127.0.0.1`. Vì vậy mọi việc với payOS và cổng Billing đặt trên **billing-gateway**, chạy ở VM GCP mới.
2. **Khóa ký license không rời máy admin** (`Doc-Admin.md` mục 1). Server không tự ký token license được. Hạng mục E ("server cấp token") được hiện thực như sau:
   - Server **giữ đơn đã trả**.
   - Một tiến trình nền trên máy admin, nối sẵn với server, ký token ngay khi có đơn đã trả rồi đẩy lên server.
   - Server **giao token** cho khách trên trang đơn hàng và qua app.

   Mục 6.4 có phương án thay thế và lý do không chọn.
3. Admin không phải lúc nào cũng mở. Vì vậy việc ký gia hạn chạy bằng **tiến trình Windows chạy ngầm** (khởi động cùng máy, tự chạy lại khi lỗi), không phụ thuộc giao diện admin (mục 6.4).
4. **Thư viện payOS.** Dùng gói `payos` (Python ≥ 3.9) cài vào venv của gateway: `pip install payos`, thêm vào `billing-gateway/requirements.txt`.
   - SDK tự đọc `PAYOS_CLIENT_ID`, `PAYOS_API_KEY`, `PAYOS_CHECKSUM_KEY`. Đây đúng là 3 tên đã đặt trong `.env`.
   - Các hàm dùng: `client.payment_requests.create(payment_data=CreatePaymentLinkRequest(order_code, amount, description, cancel_url, return_url, ...))`, `client.payment_requests.get(order_code)`, `client.webhooks.confirm(url)`, `client.webhooks.verify(raw_body)` (lỗi `WebhookError`), `payos.APIError`.
   - SDK kéo theo `httpx` và `pydantic`. Đây là phụ thuộc mới của gateway, chấp nhận được.
   - Chỉ module **`payments.py`** (đặt tên khác `payos.py` để không che gói `payos`) được import SDK, để phần còn lại không phụ thuộc vào nó và test có thể thay bằng client giả.
5. Sổ nợ lưu milli-VND; `payments` và payOS dùng VND nguyên. Không có làm tròn.

Nguồn: [payOS Python SDK (README)](https://github.com/payOSHQ/payos-lib-python), [tài liệu payOS cho Python](https://payos.vn/docs/sdks/back-end/python), [quick start payOS-hosted page](https://payos.vn/docs/checkout/quick-start-payos-hosted-page?lang=Python&client=HTML).

---

## 2. Kiến trúc

```
                                ┌──────────────── VM GCP (asia-northeast2-b) ────────────────┐
  Khách (trình duyệt)           │  cloudflared ── Tunnel ── 127.0.0.1:8790  billing-gateway   │
   │  https://billing.<domain> ──┼──►  /license /debt /orders  cổng Billing: gói, trả nợ, đơn │
   │                            │      /payos/webhook   (chỉ tin chữ ký payOS)                │
   │  quét QR / trang payOS     │      /v1/*      App API (License)                           │
   ▼                            │      /admin/*   Admin API (Bearer ADMIN_TOKEN)              │
 payOS ◄── tạo link, tra đơn ───┼──   SQLite: orders, payments, price_book, limits, mailbox   │
       ─── webhook ─────────────┼──►                                                          │
                                └────────────────────────────▲──────────────────────────────┘
  App (Next.js server) ── License ──► /v1/billing/session, /v1/license/renewals │
                                                  Bearer, kết nối đi RA từ admin │ nghe /admin/fulfillment/wait,
  Máy admin (Windows): admin-system UI  +  "renewal-worker" thường trú ──────────┘ ký (DPAPI key), đẩy token
```

- **Một tiến trình, hai hostname** [Chốt]. Cloudflare Tunnel có hai ingress cùng trỏ `127.0.0.1:8790`:
  - `audio-gateway.<domain>`: API cho app và admin, như hiện tại.
  - `billing.<domain>`: cổng Billing (trang web cho khách) và webhook.

  Gateway phân luồng theo header `Host`: các trang cổng Billing và `/payos/webhook` chỉ phục vụ trên host `billing`, `/v1/*` và `/admin/*` chỉ trên host API. Chung một tiến trình thì một transaction SQLite ghi được cả đơn và sổ nợ, không cần đồng bộ hai dịch vụ.

  Lý do tách hai host (nếu gộp một host thì phải tự dựng thêm lớp bảo vệ riêng cho `/admin/*`):
  - Mỗi host có **bảng route riêng, mặc định từ chối**. Host `billing` không có route `/admin/*` hay `/v1/*`: yêu cầu tới đó trả 404 trước cả bước kiểm tra xác thực, nên không có gì để dò hay tấn công mật khẩu.
  - Host lạ hoặc thiếu `Host` thì trả 404. [Kiểm chứng] cloudflared giữ nguyên `Host` công khai khi chuyển yêu cầu tới `127.0.0.1:8790`; nếu không, phải đặt `httpHostHeader` cho từng ingress.
  - Cookie, CORS và giới hạn tần suất của cổng Billing tách khỏi API.
  - Tùy chọn thêm [Đề xuất]: đặt Cloudflare Access (service token) trước đường `/admin/*` của host API, để admin không bao giờ tới được gateway nếu thiếu thêm một lớp ngoài `ADMIN_TOKEN`.
- Cổng Billing là **HTML render phía server** bằng thư viện chuẩn, kèm một file CSS. Không dùng framework JS, theo phong cách admin-system. Mọi chữ, gói và giá hiển thị đều lấy từ cấu hình admin đẩy lên (mục 4), nên **đổi gói hay giá không cần sửa app**.

---

## 3. Mô hình dữ liệu (gateway, `store.py`)

### 3.1 Đơn thanh toán `payment_orders` (mới)

| Cột | Ý nghĩa |
|---|---|
| `order_code` INTEGER PK | Do gateway sinh: tăng dần từ một mốc ngẫu nhiên, không dùng lại. [Kiểm chứng] giới hạn trên của payOS |
| `public_id` | Chuỗi ngẫu nhiên 128 bit, dùng trong URL trang đơn hàng `/orders/<public_id>`. Không lộ `order_code` tuần tự |
| `customer_id`, `app_id`, `product_id`, `license_id` | |
| `kind` | `DEBT` (trả nợ dịch vụ) hoặc `LICENSE` (mua gói) |
| `plan_kind`, `plan_units`, `duration_days` | `LICENSE`: `DAYS` + số ngày, hoặc `MONTHS` + 1/3/6/9/12 |
| `amount_vnd`, `price_version` | Chốt lúc tạo đơn |
| `status` | `CREATED` → `PAID` → `FULFILLED`; `CANCELLED`, `EXPIRED`, `AMOUNT_MISMATCH`, `NEEDS_ATTENTION` |
| `payment_link_id`, `checkout_url`, `qr_code` | payOS trả về |
| `created_by` | `PORTAL` hoặc `ADMIN` |
| `created_at`, `expires_at`, `paid_at`, `fulfilled_at`, `reference`, `paid_amount`, `note` | |

Mỗi license có tối đa **3 đơn `CREATED`** cùng lúc. Đơn hết hạn sau **15 phút**, đặt qua `expired_at` khi tạo link [Chốt].

### 3.2 Bảng `payments` (sửa)

Thêm 3 cột:
- `source`: `MANUAL` hoặc `PAYOS`.
- `order_code`: UNIQUE; NULL với dòng nhập tay.
- `purpose`: `SERVICE` hoặc `LICENSE`.

`_debt_milli` và `account()` chỉ cộng các dòng `purpose = SERVICE`. Tiền mua gói không trừ vào nợ dịch vụ, nhưng vẫn có trong lịch sử và doanh thu. `order_code UNIQUE` chặn việc cộng tiền hai lần.

### 3.3 Hộp thư token license `token_mailbox` (mới)

Các cột: `(license_id, sequence)` là PK, `order_code`, `token`, `expires_at`, `created_at`, `delivered_at`. Server chỉ chứa token admin đã ký; nó không tạo và không sửa token.

### 3.4 Phiên Billing `billing_sessions` (mới)

Các cột: `code` (ngẫu nhiên 128 bit, chỉ lưu hash SHA-256), `license_id`, `customer_id`, `product_id`, `machine_id`, `expires_at` (30 phút), `created_at`. Xem mục 6.1.

### 3.5 Mã khách hàng `billing_codes` (mới)

Các cột: `code` (10 ký tự Crockford base32, UNIQUE), `license_id`, `customer_id`, `created_at`, `revoked_at`. Mỗi license có một mã đang dùng; admin cấp lại được. Dùng cho trang dự phòng (mục 6.1).

### 3.6 Bảng tổng hợp để dọn dữ liệu mà nợ không đổi (mới)

- `usage_rollup(customer_id, app_id, service, month, jobs, chars, billed_milli)`: gộp các job đã đóng quá hạn giữ chi tiết.
- `cost_rollup(day, app_id, service, model, input_tokens, output_tokens, thought_tokens, seconds, cost_usd)`: gộp chi phí nội bộ theo ngày.
- Công thức nợ trở thành `SUM(jobs.billed_milli) + SUM(usage_rollup.billed_milli) − SUM(payments SERVICE) × 1000`. `account()`, `summary()` và các bảng của admin cộng cả phần tổng hợp. Dọn dữ liệu **không được làm đổi nợ của bất kỳ khách nào** (có test, mục 12).
- Chính sách dọn đầy đủ ở mục 9.3.

---

## 4. Bảng giá (draft → Lưu mới áp dụng)

### 4.1 Đối tượng tính tiền

| Đối tượng | Khóa | Giá trị |
|---|---|---|
| **Gói license theo ngày** | `product_id` | `enabled`, `price_per_day_vnd`, `min_days`, `max_days` |
| **Gói license theo tháng** | `(product_id, months ∈ {1,3,6,9,12})` | `enabled`, `price_vnd` (tổng của gói; tự do, để gói dài rẻ hơn), `duration_days` (mặc định 30/90/180/270/**365**, sửa được) |
| **Giá license riêng khách** | `(customer_id, product_id, DAYS)` hoặc `(customer_id, product_id, months)` | `price_per_day_vnd` hoặc `price_vnd`. Trống = dùng giá sản phẩm |
| **Dịch vụ: giá mặc định** | `(app_id, service)` | VND / 1.000 ký tự (đang có, `scoped_settings`) |
| **Dịch vụ: giá riêng khách** | `(customer_id, app_id, service)` | VND / 1.000 ký tự (đang có, `customer_prices`) |
| **Trả nợ** | toàn cục | `min_payment_vnd` (số nhỏ nhất cho một đơn trả một phần) |
| **Nội dung cổng Billing** | theo `product_id` | Tên hiển thị, mô tả ngắn, ghi chú, thông tin liên hệ |

Cách tính tiền một đơn license:
- Theo ngày: `số ngày × giá/ngày` (giá riêng khách nếu có).
- Theo tháng: `price_vnd` của gói (giá riêng khách nếu có).

Kết quả được chốt vào đơn.

### 4.1a Hiển thị gói trên cổng Billing [Chốt]

Mỗi gói là một thẻ:
- **Dòng lớn**: giá/tháng = `price_vnd / months`, làm tròn tới đồng. Ví dụ `79.000đ / tháng`.
- **Dòng nhỏ** bên dưới: tổng tiền và thời hạn. Ví dụ `Tổng 948.000đ · 365 ngày`.
- **Nhãn tiết kiệm**, chỉ hiện khi rẻ hơn gói 1 tháng: `Tiết kiệm 21%` = `1 − (giá/tháng của gói) / (giá gói 1 tháng)`.
- Gói có giá/tháng thấp nhất được gắn nhãn **Tiết kiệm nhất**.

Quy tắc:
- Thứ tự thẻ: 1 → 3 → 6 → 9 → 12 tháng. Thẻ "theo ngày" đặt riêng, hiện `giá/ngày`, ô nhập số ngày và tổng tạm tính.
- Gói 1 tháng bị tắt thì không hiện % tiết kiệm.
- Giá riêng khách (nếu có) thay giá sản phẩm **trước khi** tính giá/tháng và % tiết kiệm.
- Số tiền thực trả luôn là `price_vnd` (tổng). Giá/tháng chỉ để hiển thị.
- Admin có **xem trước** đúng các thẻ này ngay trong tab Bảng giá, tính theo bản nháp. Nhờ vậy, khi chỉnh giá giảm dần theo độ dài gói, bạn thấy ngay mức giảm trước khi bấm Lưu.
- Cảnh báo (không chặn) khi giá/tháng của một gói dài **cao hơn** gói ngắn hơn.

Mua khi license **chưa hết hạn** thì hạn mới tính từ hạn cũ (`max(hôm nay, hạn cũ)`, như `core.renew`), nên khách mua sớm không mất ngày nào.

### 4.2 Quy tắc "chỉ áp dụng khi sửa và Lưu" [Chốt]

- Bản nháp nằm trong `admin.sqlite3` (bảng `price_drafts`). Ô nào đã sửa thì được tô màu, kèm dòng "N thay đổi chưa lưu". Server **không đổi gì** cho tới khi Lưu.
- **Lưu & áp dụng**: hiện hộp thoại so sánh *cũ → mới* để xác nhận. Admin gửi toàn bộ bảng bằng `PUT /admin/price-book {base_version, book}`, và gateway áp dụng trong một transaction rồi tăng `price_version`.
  - Nếu `base_version` lệch, gateway trả `409 PRICE_BOOK_CHANGED` và không ghi gì.
  - **Hủy thay đổi** xóa bản nháp.
- Đơn đã tạo giữ số tiền đã chốt. Giá dịch vụ mới chỉ áp cho các khối dịch vụ bắt đầu sau khi lưu.
- Gateway lưu `price_book_versions` (version, thời điểm, JSON). Admin ghi audit `PRICE_BOOK_SAVED`.
- Giá dịch vụ vẫn ghi vào `scoped_settings` và `customer_prices`, nên `begin_chunk` không đổi cách đọc giá.

---

## 5. Hạn mức nợ chỉnh được theo app [Chốt]

Nợ vẫn **tính chung cho khách trên mọi app** (dùng nhiều trả nhiều). Chỉ **ngưỡng chặn** thay đổi theo app đang gọi. Tra theo thứ tự sau; ô trống thì xuống cấp tiếp theo:

```
khách × app  →  khách (mọi app)  →  mặc định của app  →  mặc định toàn cục (default_limit_vnd)
```

- Bảng mới `credit_limits(customer_id NULL, app_id NULL, limit_vnd, updated_at)`. Cột `customers.limit_vnd` hiện có trở thành cấp "khách (mọi app)".
- `_terms()` trả cả **hạn mức hiệu lực** và **nguồn** của nó (ví dụ "mặc định app"), để admin thấy và để `/v1/account` báo cho app.
- Áp dụng theo cùng cơ chế draft → Lưu (`PUT /admin/limits {base_version, ...}`).
- Mã lỗi giữ nguyên `402 CREDIT_LIMIT`. Không có hạn mức số lượng.

---

## 6. Luồng nghiệp vụ

### 6.1 Từ app sang cổng Billing: phiên Billing

App **không** chứa giao diện giá hay gói. App chỉ mở cổng Billing ở đúng ngữ cảnh:

1. Người dùng bấm **Mua / gia hạn gói** (trang License) hoặc **Trả nợ** (thông báo `CREDIT_LIMIT`).
2. Next.js server gọi `POST /v1/billing/session` với `Authorization: License <token>`. Gateway nhận cả **token đã hết hạn nhưng chữ ký đúng**; `REVOKED` thì từ chối.
   - Gateway trả về `https://billing.<domain>/s/<code>?next=license|debt`.
   - `code` dùng một lần và hết hạn sau 30 phút.
3. App mở URL trong **trình duyệt hệ thống**.
4. Cổng Billing đổi `code` thành **cookie phiên** (HttpOnly, Secure, SameSite=Lax, 2 giờ) rồi chuyển hướng sang `/license` hoặc `/debt`. Từ đây trang biết khách, sản phẩm, license và máy.

Không cần tài khoản hay mật khẩu trên web. Quyền mua đi theo license đang có trong app.

**Dự phòng khi không mở được từ app** [Chốt]: trang `/` cho nhập **Mã khách hàng**.
- Mã hiện ở trang License của app: 10 ký tự Crockford base32, sinh ngẫu nhiên cho mỗi license, lưu ở gateway (`billing_codes`). Mã không suy ra được từ `license_id`, và admin cấp lại được.
- Trang dự phòng cho **xem gói, xem số nợ đã làm tròn và trả tiền**.
- Token license **không** hiện trên trang này. Token chỉ đến tay khách qua app (`/v1/license/renewals`), hoặc qua trang đơn hàng mở từ phiên app. Người lạ biết mã cũng chỉ trả tiền hộ được.
- Có giới hạn tần suất nhập mã theo IP để chống dò mã.

### 6.2 Mua gói license trên cổng Billing (hạng mục E, 6, 8)

```
/license  →  chọn [Theo ngày: nhập số ngày] hoặc [Gói 1/3/6/9/12 tháng]  →  hiện giá (riêng khách nếu có)
   →  POST /orders  →  gateway tính tiền theo price_book, tạo đơn, gọi payOS
   →  chuyển sang trang thanh toán payOS (QR VietQR)  →  khách quét, trả
   →  payOS gọi webhook  →  đơn PAID
   →  webhook đánh thức kênh duyệt trực tiếp → renewal-worker trên máy admin ký ngay (vài giây nếu máy bật), đẩy vào hộp thư  →  FULFILLED
   →  trang /orders/<public_id> tự làm mới: "Đã nhận tiền" → "Token đã sẵn sàng" [Sao chép]
   →  App tự nhận token qua GET /v1/license/renewals và cài; hoặc khách dán tay vào ô Gia hạn
```

- `return_url` trỏ về `/orders/<public_id>`; `cancel_url` trỏ về `/orders/<public_id>?cancel=1`. **Không** coi tham số trên `return_url` là bằng chứng đã trả: chỉ webhook hoặc `payment_requests.get` mới là bằng chứng.
- Trang đơn hàng chỉ hiện token khi cookie phiên khớp license của đơn. Token dù sao cũng gắn máy nên lộ ra không dùng được ở máy khác, nhưng vẫn không nên hiện công khai.
- Cả hai đường giao token (app tự lấy, khách dán tay) đều đi qua kiểm tra `sequence` của app, nên mỗi token chỉ dùng một lần và phải đúng thứ tự.

### 6.3 Trả nợ dịch vụ (hạng mục 4, 5)

- `/debt` hiện tổng nợ, hạn mức hiệu lực (theo app) và lịch sử dùng ngắn gọn. Mặc định số tiền **bằng toàn bộ nợ**; cho sửa trong khoảng từ `min_payment_vnd` tới số nợ. **Không cho trả quá số nợ** (không nạp trước) [Chốt].
- Webhook chuyển đơn sang `PAID` rồi ghi `payments(source=PAYOS, purpose=SERVICE)` và đơn thành `FULFILLED` trong **cùng một transaction**.
- Nợ được tính lại ở mỗi request, nên khối dịch vụ tiếp theo tự đi qua.
- App: thông báo `pause.CREDIT_LIMIT` có thêm nút **Trả nợ**. Sau khi trả, người dùng **tự bấm Tiếp tục** [Chốt]. App không tự chạy lại.

### 6.4 Admin tự ký gia hạn, cấp tức thì [Chốt]

Khóa ký nằm ở máy admin, nên gateway không thể gọi vào admin (máy nằm sau NAT, và mở cổng vào máy admin là điều không nên làm). Thay vào đó **admin gọi ra và giữ một kết nối chờ sẵn**: khi tiền về, gateway đánh thức kết nối đó và admin ký ngay. Có hai đường:

**Đường nhanh: kênh duyệt trực tiếp (long-poll)**

1. `renewal-worker` (`admin-system/renewal_worker.py`) là tiến trình **thường trú**: Windows Task Scheduler chạy khi khởi động máy hoặc khi đăng nhập, tự khởi động lại khi lỗi, chạy dưới chính tài khoản Windows của admin (để khóa DPAPI giải mã được).
2. Worker gọi `GET /admin/fulfillment/wait?cursor=<n>&timeout=25` (Bearer `ADMIN_TOKEN`). Gateway giữ yêu cầu tối đa 25 giây, dưới giới hạn 100 giây của Cloudflare. Hết 25 giây thì trả rỗng và worker gọi lại ngay.
3. Webhook chuyển đơn `LICENSE` sang `PAID` thì tăng `fulfillment_seq` và đánh thức yêu cầu đang chờ (một biến điều kiện trong tiến trình gateway). Gateway trả danh sách đơn mới.
4. Với từng đơn, theo thứ tự `paid_at`, worker gọi `authority.renew(license_id, duration_days)` rồi `PUT /admin/token-mailbox/<license_id>/<sequence> {order_code, token}`. Gateway chuyển đơn sang `FULFILLED`.
5. `cursor` là số thứ tự mà worker đã xử lý. Khi nối lại sau lúc máy tắt hay mất mạng, gateway trả ngay mọi đơn có `seq > cursor`, nên **không có đơn nào bị bỏ sót**.

Độ trễ: thời gian payOS gửi webhook (thường vài giây) cộng khoảng 1 giây. Trang đơn hàng hỏi `/orders/<public_id>/status` mỗi 2 giây nên khách thấy "Token đã sẵn sàng" gần như ngay. Phía app, sau khi mở cổng Billing, app hỏi hộp thư mỗi 5 giây trong 15 phút (mục 7), nên token vào app trong vài giây.

**Đường dự phòng: quét định kỳ**

Mỗi 5 phút worker gọi `GET /admin/payment-orders?status=PAID&kind=LICENSE` để bắt đơn còn sót (kênh vừa đứt, worker vừa khởi động lại). Đường này chạy cùng một hàm xử lý, nên không ký trùng.

**Nút thủ công**: trang **Gia hạn** trong admin có **Ký ngay** cho từng đơn, cùng hàm xử lý, dùng khi bạn tắt Tự duyệt hoặc muốn ép chạy.

**Ai chạy vòng lặp:** UI admin và worker dùng chung một khóa riêng `fulfillment.lock`. Bên nào giữ khóa thì chạy vòng lặp; bên kia thử lại mỗi 30 giây. Nhờ vậy UI đang mở hay đã đóng đều không làm mất kênh, và không bao giờ có hai bên cùng ký.

**Chống ký trùng và ký nhầm**
- `renew` ghi `order_code` vào audit. Trước khi ký, worker kiểm tra đơn đã có token chưa; nếu có thì chỉ đẩy lại token đó (dùng `reissue`).
- Chỉ tự ký khi: `paid_amount = amount_vnd`; license `ISSUED` và gắn đúng máy; **không quá 5 lần tự ký mỗi license trong 24 giờ** [Đề xuất]. Ngoài các điều kiện đó, đơn chuyển `NEEDS_ATTENTION`.
- `AMOUNT_MISMATCH`, license `REPLACED` hoặc `REVOKED`, hay ký lỗi: không bao giờ tự ký; bạn xử lý tay [Chốt].
- Công tắc **Tự duyệt** (mặc định Bật) nằm trong admin. Tắt thì đơn đã trả vẫn được ghi nhận nhưng chờ bạn bấm **Ký ngay**.

**Khi máy admin tắt hoặc ngủ**: không có đường tức thì, vì khóa ký không rời máy này. Trang đơn hàng hiện "Đã nhận tiền, token sẽ được cấp khi hệ thống xử lý" cùng thông tin liên hệ. Máy bật lại thì worker nối kênh với `cursor` cũ và cấp bù ngay.

**Phương án bị loại:** đặt một khóa ký "chỉ gia hạn" trên server để cấp tức thì kể cả khi máy admin tắt. Các installer hiện tại không kiểm phạm vi của khóa ủy quyền: mọi khóa có certificate của root đều ký được cả token kích hoạt. Nếu VM bị chiếm, kẻ tấn công in được license cho mọi bản đã phát hành. Chỉ cân nhắc lại khi một bản app mới kiểm tra `scope` trong certificate.

### 6.5 Webhook (hạng mục 1, 3)

`POST /payos/webhook`, chỉ phục vụ trên host `billing`:

1. `client.webhooks.verify(raw_body)`. Nếu `WebhookError` thì trả 400 và không ghi gì.
2. Tìm đơn theo `orderCode`. Nếu không có đơn nào, trả 200 và ghi event `UNKNOWN_ORDER`: payOS gửi một webhook mẫu khi gọi `webhooks.confirm`.
3. Trong một transaction:
   - Đơn đã `PAID` hoặc `FULFILLED`: trả 200, không làm gì.
   - `amount ≠ amount_vnd`: chuyển `AMOUNT_MISMATCH`, không ghi tiền.
   - Còn lại: chuyển `PAID`, ghi `reference` và `paid_at`. Nếu là `DEBT` thì ghi `payments` và chuyển `FULFILLED`. Nếu là `LICENSE` thì ghi `payments(purpose=LICENSE)`, tăng `fulfillment_seq` và **đánh thức kênh duyệt trực tiếp** (mục 6.4).
4. Trả 200 nhanh.

Đăng ký URL webhook: nút trên admin gọi `POST /admin/payos/confirm-webhook`, gateway chạy `client.webhooks.confirm("https://billing.<domain>/payos/webhook")`.

### 6.6 Đối soát (hạng mục 10)

Gắn vào `sweeper()` của gateway, chạy mỗi 5 phút:
- Đơn `CREATED` quá 2 phút và chưa hết hạn: gọi `payment_requests.get`. Nếu đã trả mà webhook lỡ, ghi nhận bằng đúng hàm của webhook.
- Đơn quá hạn: tra lại một lần rồi chuyển `EXPIRED`.

Admin có trang **Đối soát** gồm: `AMOUNT_MISMATCH`, `NEEDS_ATTENTION`, đơn `PAID` loại `LICENSE` chưa xong quá 1 giờ, `UNKNOWN_ORDER`, và tổng tiền theo ngày để so sao kê.

---

## 7. Thay đổi phía app (ít nhất có thể)

| Nơi | Thay đổi |
|---|---|
| `lib/server/billing-portal.ts` (mới) | `billingSession(next)`: gọi `/v1/billing/session` bằng token license, theo mẫu `lib/server/lease.ts` (User-Agent riêng, timeout). `fetchRenewals()`: lấy token từ hộp thư rồi `licenseCommand({action:"renew", token})` lần lượt theo sequence |
| `app/api/billing/route.ts` (mới) | `POST {next}` → trả URL. Kiểm `Origin` như `app/api/license/route.ts` |
| `GET /api/license` | Bên cạnh `ensureLease()`, gọi `fetchRenewals()` (chia sẻ kết quả 1 phút, như `ensureLease`). Ngay sau khi người dùng mở cổng Billing (`POST /api/billing`), app chuyển sang hỏi hộp thư **mỗi 5 giây trong 15 phút**, rồi trở lại 1 phút [Đề xuất] |
| Trang License (`app/license/page.tsx`, `components/license/license-status.tsx`) | Hiện hạn dùng; nợ và hạn mức (`/v1/account`); **Mã khách hàng**; nút **Mua / gia hạn gói**. Giữ ô dán token tay |
| Thông báo `pause.CREDIT_LIMIT` (`lib/i18n/ui-text.ts:109`) và chỗ hiện job tạm dừng | Thêm nút **Trả nợ**. Sửa câu "Thanh toán cho người bán" thành hướng dẫn trả qua cổng Billing |
| `worker/config/genius.json` | Thêm `billing_endpoint` (hoặc dùng `/v1/billing/session` trả URL đầy đủ, để đổi domain cổng Billing không cần cập nhật app). **Đề xuất cách thứ hai** |

App chỉ cần cập nhật **một lần** để có hai nút này. Sau đó mọi thay đổi về gói, giá và chữ hiển thị nằm trên server.

---

## 8. Giao diện admin (`admin-system/ui/app.js`, trang mới **Payments**)

1. **Bảng giá** (mục 4)
   - Ba nhóm: *License theo ngày*, *License gói tháng 1/3/6/9/12*, *Dịch vụ*.
   - Có tab con **Giá riêng khách**: chọn khách, hiện ma trận sản phẩm/gói/dịch vụ. Ô trống thì hiện giá kế thừa, màu nhạt.
   - Thêm phần **Nội dung cổng Billing** và **Trả nợ tối thiểu**.
   - Thanh trên cùng: `N thay đổi chưa lưu` · **Lưu & áp dụng** (hộp thoại so sánh) · **Hủy thay đổi** · **Lịch sử phiên bản**.
2. **Hạn mức nợ** (mục 5): bảng khách × app, ô trống hiện giá trị hiệu lực và nguồn. Cùng cơ chế nháp → Lưu.
3. **Đơn thanh toán**
   - Lọc theo trạng thái, loại, khách, app.
   - **Tạo link** cho khách (trả nợ hoặc mua gói): hiện QR và link để gửi qua Zalo, email.
   - Thêm **Hủy đơn** và **Kiểm tra lại**.
4. **Gia hạn**: trạng thái kênh duyệt trực tiếp (đang nối hay đứt, lần cấp cuối, lỗi cuối), công tắc **Tự duyệt**, danh sách đơn `PAID` chờ ký với nút **Ký ngay**, và nút **Cài tác vụ Windows** để tạo hoặc gỡ task thường trú.
5. **Đối soát**: mục 6.6.
6. **Lịch sử thanh toán**: bảng hiện có, thêm cột `source`, `purpose`, `order_code`, `reference`. **Record Payment** (nhập tay) giữ nguyên.
7. Trang Billing: trạng thái payOS (đã cấu hình chưa, webhook cuối cùng nhận lúc nào), nút **Đăng ký webhook payOS**.
8. **Global Settings**: thêm các tham số thời hạn giữ dữ liệu (mục 9.3) vào form hiện có.
9. **Báo cáo**: chọn loại, kỳ, app, khách rồi tải CSV; danh sách báo cáo tháng đã lưu (mục 9.4).

**Điều kiện tiên quyết:** `admin-system/billing.py` đang gán cứng `APP='audio-translates'` và `EDITIONS`, còn `run.py` tự đăng ký 3 manifest của Audio. Phải tổng quát hóa cho nhiều app trước (đọc `app_id` và `services` từ manifest, thêm cột chọn app), như `Doc-Admin.md` 4.4.

---

## 9. Triển khai trên VM GCP mới

VM: `instance-20261006-200055`, zone `asia-northeast2-b` (Osaka), IP trong `10.174.0.3`, IP ngoài `34.97.244.134`. VM tạo bằng console, không phải Terraform `deploy/gcp/`.

### 9.1 Xây mới [Chốt]

Không khôi phục dữ liệu VM cũ. Gateway mới bắt đầu với SQLite trống. Schema mới (mục 3) tạo thẳng, **không cần migration** cho `payments` và các bảng mới.

Sau khi cài, admin cấu hình từ đầu:
- Gateway URL và `ADMIN_TOKEN` mới.
- Push root keys & services.
- Lease materials.
- Bảng giá.
- Hạn mức nợ.
- Đăng ký webhook payOS.

`GATEWAY_ADMIN_TOKEN` trong `.env` nên sinh mới cho VM này.

### 9.2 Các bước (dùng `deploy/vm-install.sh`)

1. **Cloudflare Tunnel.** Tunnel `audio-gateway` và bản ghi DNS **vẫn còn** (đã kiểm tra bằng `terraform plan`, 2026-10-07: không có thay đổi), nên dùng lại `TUNNEL_TOKEN` từ state. VM chỉ cần kết nối ra ngoài.
   - Ingress `billing.<domain>` và bản ghi DNS của nó thêm ở **bước 2** của mục 13, cùng lúc với phân tách route theo host. Thêm sớm hơn thì host mới sẽ phục vụ cả `/admin/*`.
   - **Không mở cổng vào** trên firewall GCP, ngoài SSH (nên dùng IAP).
   - Nhờ tunnel, IP ngoài có đổi cũng không ảnh hưởng.
2. File secrets cho `vm-install.sh`: `GEMINI_API_KEY`, `ADMIN_TOKEN` (sinh mới), `LEASE_MASTER_KEY` (sinh mới), `TUNNEL_TOKEN`, `PAYOS_CLIENT_ID`, `PAYOS_API_KEY`, `PAYOS_CHECKSUM_KEY`, `BACKUP_BUCKET`, `TTS_WORKERS`, `TTS_THREADS`. **Đã làm:** `vm-install.sh` giờ ghi đủ các biến này (trước đây thiếu `LEASE_MASTER_KEY`, khiến lease service tắt) vào `/etc/audio-gateway/gateway.env` quyền 640. Bundle tạo bằng `python deploy/bundle.py <thư mục>`. `BILLING_HOST`/`API_HOST` thêm ở bước 2 của mục 13.
3. `requirements.txt` của gateway thêm `payos`.
4. **Gemini key giới hạn IP**: nếu key đang khóa theo IP VM cũ thì sẽ gặp `API_KEY_IP_ADDRESS_BLOCKED`. Có hai cách: thêm `34.97.244.134` và **đặt IP tĩnh** (IP ephemeral đổi khi stop/start), hoặc đổi sang key giới hạn theo API.
5. **Cấu hình máy (đã kiểm tra 2026-10-07 bằng `gcloud`)**: e2 tùy chỉnh 2 vCPU, 4 GiB, đĩa 10 GB pd-balanced, Debian 13. Phải sửa trước khi nhận tiền thật:
   - **Spot, `instanceTerminationAction: DELETE`, `maxRunDuration` 68 giờ.** Google sẽ **xóa VM cùng đĩa** sau 68 giờ chạy (khoảng 23:51 giờ VN ngày 09/10/2026) hoặc ngay khi thu hồi máy Spot. Rất có thể đây là lý do VM cũ biến mất. Sửa: dừng VM, `set-scheduling --provisioning-model=STANDARD --clear-max-run-duration --clear-instance-termination-action` (có bật lại `--restart-on-failure`). Giá máy thường cao hơn Spot.
   - **Tài khoản dịch vụ mặc định của Compute** (thường có quyền Editor cả project) với scope `devstorage.read_only`: không ghi được bản sao lưu. Sửa: tạo tài khoản riêng `audio-gateway-vm` chỉ có quyền tạo và đọc object trên bucket sao lưu, gắn vào VM với scope `cloud-platform` (cần dừng VM).
   - **Đĩa 10 GB**: đủ cho gateway; nếu bật TTS (VieNeu, venv có torch, cache model) có thể chật. Đo khi cài TTS rồi mở rộng nếu cần.
   - **TTS**: 4 GiB vừa đủ 1 worker (`TTS_WORKERS=1`).
   - **Firewall project**: `default-allow-ssh` và `default-allow-rdp` mở cho `0.0.0.0/0` và áp lên mọi VM. Nên xóa, chỉ giữ `allow-ssh-ingress-from-iap`. Đây là thay đổi cấp project nên cần chủ sản phẩm đồng ý.
6. **Sao lưu và dọn dữ liệu** (bắt buộc khi có tiền thật): xem mục 9.3. Lưu `LEASE_MASTER_KEY` offline. **Đã làm:** `deploy/backup.py`, `audio-gateway-backup.service/.timer`, `backup-lifecycle.json`, DB tạo với `auto_vacuum=INCREMENTAL` (`store.py`, `lease_authority.py`), test `test_backup.py`.
7. Kiểm tra: `/health` trên cả hai host; host `billing` trả 404 cho `/admin/*` và `/v1/*`; `confirm-webhook`; một đơn 2.000đ thật từ đầu tới cuối; **thử khôi phục một bản sao lưu** sang thư mục tạm.
8. **Tải báo cáo** (bổ sung theo yêu cầu chủ sản phẩm): admin tải báo cáo CSV theo kỳ, và mỗi tháng gateway lưu sẵn một bộ báo cáo lên Cloud Storage. Chi tiết ở mục 9.4.

Ghi chú cho đường Terraform: `deploy/gcp/main.tf` đã thêm `lease_authority.py` vào danh sách file tải lên. Danh sách đã gồm các module mới (`payments.py`, `orders.py`, `pricebook.py`, `portal.py`, `web.py`, `gcs.py`, `reports.py`, `retention.py`).

### 9.3 Dữ liệu phát sinh hằng ngày: giữ bao lâu, dọn và sao lưu

**Bước 6 ở 9.2 nói về dữ liệu nào.** Gateway có hai file SQLite: `gateway.sqlite3` (sổ nợ, thanh toán, đơn, job, chi phí) và `leases.sqlite3` (lease, sự kiện, danh sách thu hồi). Hai file này chứa **tiền và quyền**, nên sao lưu là bắt buộc. Câu hỏi của bạn đúng chỗ: nếu cứ giữ nguyên mọi thứ thì file phình theo từng người dùng mỗi ngày.

**Đã kiểm tra trong mã hiện tại:** `store.py` và `lease_authority.py` không có lệnh dọn dữ liệu nào (chỉ `release_chunk` xóa một dòng đang chạy dở). Cụ thể:
- `chunks.response` lưu **nguyên phản hồi của từng khối dịch** (gồm văn bản tiếng Việt), không bao giờ xóa. Điều này cũng trái lời hứa trong `gateway.py` "không ghi nội dung truyện".
- `billed_rows` thêm **một dòng cho mỗi dòng đã dịch**, `costs` thêm một dòng cho mỗi khối, `jobs` một dòng cho mỗi job.
- `leases` thêm một dòng mỗi lần gia hạn lease; `events` ghi mọi lần bị từ chối.

**Quy mô (ước tính theo giả định, chưa đo):** nếu 100 người dùng hoạt động, mỗi người 3 job một ngày, mỗi job khoảng 0,4 MB (văn bản đã dịch cộng chỉ mục từng dòng), thì ~120 MB một ngày, tức ~44 GB một năm. Sau khi dọn theo bảng dưới, dữ liệu nóng chỉ còn vài ngày gần nhất (vài trăm MB), phần lâu dài tăng vài chục MB một năm. Cần đo lại khi có dữ liệu thật.

**Phân loại và chính sách** (con số là [Đề xuất], chỉnh được trong Global Settings của admin):

| Loại | Bảng | Tăng thế nào | Chính sách |
|---|---|---|---|
| **A. Thưa, quan trọng** | `payments`, `payment_orders` đã trả, `price_book_versions`, `credit_limits`, `customers`, `apps`, `products`, `billing_codes`, `revoked`, các `settings` | Theo thao tác của người, vài dòng mỗi tháng mỗi khách | **Giữ mãi**, không dọn. Đây là chứng từ tài chính |
| **B. Một dòng mỗi job** | `jobs` | Mỗi ngày, mỗi người dùng | Giữ chi tiết **180 ngày sau khi đóng**. Sau đó gộp vào `usage_rollup` theo (khách, app, dịch vụ, tháng) rồi xóa dòng job. Nợ không đổi nhờ công thức ở mục 3.6 |
| **C. Nặng, từng khối/dòng** | `chunks` (gồm `response`), `billed_rows` | Mỗi ngày, rất nhiều | **Xóa 48 giờ sau khi job đóng** (`COMPLETED`, `CANCELLED`, `ABANDONED`). An toàn vì `begin_chunk` từ chối mọi yêu cầu vào job đã đóng bằng `JOB_CLOSED` trước cả bước tra khối, nên dữ liệu này không còn dùng để phát lại. Tổng tiền đã nằm trong `jobs` |
| **D. Chi phí nội bộ** | `costs` | Mỗi khối | Giữ chi tiết **30 ngày**, sau đó gộp vào `cost_rollup` theo ngày. Admin vẫn xem được tổng chi phí theo app và dịch vụ |
| **E. Lease và sự kiện** | `leases`, `events` | `leases`: mỗi lần gia hạn lease; `events`: mỗi lần bị từ chối | `leases`: chỉ giữ **dòng mới nhất mỗi license** (đủ cho bộ đếm tăng dần chống lùi). `events`: giữ **90 ngày**, trừ `REVOKED` và `RESTORED` giữ mãi |
| **F. Tạm thời** | đơn `EXPIRED` hoặc `CANCELLED` chưa trả, `billing_sessions` hết hạn, token trong `token_mailbox` đã giao | Mỗi lần mở cổng, mỗi lần mua | Đơn chưa trả: **90 ngày**. Phiên hết hạn: **1 ngày**. Token đã giao: **30 ngày** (admin vẫn giữ bản gốc, có `reissue`). Token chưa giao: giữ tới khi giao |
| **G. File** | kết quả TTS (`tts-results/`) | Mỗi lần tạo giọng | Đã tự xóa theo `result_hours` (mặc định 24 giờ). **Không sao lưu** |

**Cách dọn**
- `Store.prune()` chạy mỗi giờ trong `sweeper()` đang có. Xóa **theo lô** (khoảng 2.000 dòng mỗi transaction), để không giữ khóa ghi lâu làm chậm yêu cầu của khách.
- Gộp và xóa nằm **trong cùng một transaction**: cộng vào bảng tổng hợp rồi mới xóa dòng chi tiết. Không bao giờ xóa trước khi gộp.
- Không đụng tới job `IN_PROGRESS`. Job không hoạt động 24 giờ đã tự thành `ABANDONED` (cơ chế hiện có), nên dữ liệu loại C luôn có hạn.
- Vì SQLite không thu nhỏ file sau khi xóa, DB mới tạo với `PRAGMA auto_vacuum=INCREMENTAL` (làm được vì **xây mới, không cần chuyển đổi**), và sau mỗi lần dọn chạy `PRAGMA incremental_vacuum`. Không dùng `VACUUM` đầy đủ trong lúc đang chạy, vì nó khóa DB.
- Các tham số (`keep_job_detail_hours`=48, `keep_jobs_days`=180, `keep_cost_days`=30, `keep_event_days`=90, `keep_unpaid_order_days`=90, `keep_delivered_token_days`=30) nằm trong `GLOBAL_DEFAULTS` và sửa được ở Global Settings.
- Phía admin: bảng `audit` của admin-system tăng theo thao tác của người nên không cần dọn.

**Sao lưu** (script `deploy/backup.py`, thư viện chuẩn, chạy bằng systemd timer mỗi ngày 03:00 giờ VN) [Đề xuất]:
1. Dùng `sqlite3.Connection.backup()` để chụp bản nhất quán của `gateway.sqlite3` và `leases.sqlite3` mà không dừng dịch vụ, rồi nén.
2. Đẩy lên một bucket Cloud Storage riêng tư. Tài khoản dịch vụ của VM **chỉ có quyền tạo và đọc object, không có quyền xóa hay ghi đè** (vai trò `storage.objectCreator` + `storage.objectViewer`; mọi lần tải lên dùng `ifGenerationMatch=0`), nên VM bị chiếm cũng không xóa được bản sao lưu. Quyền đọc dùng để admin tải lại báo cáo tháng (mục 9.4); nó không lộ thêm gì vì VM vốn đã giữ dữ liệu gốc.
3. Vòng đời tự động của bucket: bản ngày giữ **35 ngày**; bản chủ nhật chép sang `weekly/` giữ **180 ngày**.
4. Không sao lưu `tts-results/` và `hf-cache/` (tạo lại được). Nhờ đã dọn dữ liệu loại C nên mỗi bản sao lưu chỉ vài chục MB trở xuống, chi phí không đáng kể.
5. Khôi phục: tải bản mới nhất, giải nén vào `GATEWAY_DB` khi dịch vụ đang dừng. Thử khôi phục một lần khi cài (mục 9.2 bước 7) và nhắc thử lại mỗi quý.
6. `LEASE_MASTER_KEY` lưu riêng, ngoài bucket. Không có khóa này thì phần vật liệu lease trong bản sao lưu không đọc được, và admin phải đẩy lại lease materials.

### 9.4 Tải báo cáo [Chốt]

Mục đích: bạn tải được số liệu để đối chiếu, kế toán hay lưu trữ, kể cả phần chi tiết đã bị dọn khỏi DB theo mục 9.3.

**Tải theo yêu cầu (admin).** Trang **Báo cáo** trong admin-system: chọn loại, kỳ (từ tháng – đến tháng), app, khách (tùy chọn), rồi bấm **Tải CSV**.
- Gateway sinh CSV theo dòng chảy (`GET /admin/reports/<loại>.csv?from=YYYY-MM&to=YYYY-MM&app_id=&customer_id=`), không dựng cả file trong RAM.
- Admin chuyển tiếp qua `/api/billing/reports/...` và trả về dạng file tải (`Content-Disposition: attachment`), tên kiểu `payments_2026-10_2026-12.csv`. Mỗi lần tải ghi audit `REPORT_DOWNLOADED`.
- CSV mã hóa UTF-8 **có BOM**, dấu phẩy, số tiền là VND nguyên, thời gian theo giờ VN, để mở thẳng bằng Excel không lỗi tiếng Việt.

| Loại | Nội dung | Nguồn |
|---|---|---|
| `payments` | Mọi khoản thu: thời điểm, khách, số tiền, `source` (payOS / tay), `purpose` (dịch vụ / license), mã đơn, mã giao dịch ngân hàng, ghi chú | `payments` + `payment_orders` |
| `orders` | Mọi đơn với trạng thái, kể cả hết hạn, hủy, sai số tiền | `payment_orders` |
| `usage` | Theo khách × app × dịch vụ × tháng: số job, ký tự, tiền tính phí | `jobs` + `usage_rollup` |
| `statement` | Theo khách: nợ đầu kỳ, phát sinh, đã trả, nợ cuối kỳ | tính từ `usage` và `payments` |
| `jobs` | Từng job: thời điểm, khách, app, dịch vụ, trạng thái, ký tự, tiền. **Chỉ có trong 180 ngày gần nhất**; xa hơn thì lấy từ báo cáo tháng đã lưu | `jobs` |
| `licenses` | Gia hạn đã bán: khách, sản phẩm, gói, số ngày, tiền, thời điểm trả, thời điểm cấp token | `payment_orders` (LICENSE) |
| `costs` | Chi phí nội bộ theo ngày × app × dịch vụ × model: token vào/ra, giây TTS, USD | `costs` + `cost_rollup` |
| `reconciliation` | Danh sách đối soát ở mục 6.6 | `payment_orders` |

**Lưu sẵn mỗi tháng (gateway).** Ngày 1 hằng tháng, `sweeper()` sinh bộ báo cáo của tháng trước (mọi loại ở trên, toàn bộ khách) và tải lên bucket sao lưu với tiền tố `reports/YYYY-MM/`, dùng `ifGenerationMatch=0`.
- Tiền tố `reports/` **không có quy tắc tự xóa**, vì là chứng từ (luật kế toán thường yêu cầu giữ nhiều năm). Mỗi tháng chỉ vài trăm KB tới vài MB.
- Báo cáo `jobs` của tháng được lưu **trước khi** dữ liệu chi tiết tới hạn dọn (180 ngày), nên chi tiết từng job vẫn còn ở dạng file dù DB đã gộp.
- Trang **Báo cáo** có danh sách các tháng đã lưu. Admin tải về qua gateway (`GET /admin/reports/archive`, `GET /admin/reports/archive/<YYYY-MM>/<loại>.csv`); gateway đọc từ bucket bằng quyền `objectViewer`.

**Sao kê cho khách** [Đề xuất]: trang `/debt` của cổng Billing có nút **Tải sao kê** (CSV `statement` và `usage` của chính khách đó, 12 tháng gần nhất), làm ở bước 4.

---

## 10. API mới (tóm tắt)

| Host | Route | Ghi chú |
|---|---|---|
| billing | `GET /s/<code>` | Đổi code thành cookie phiên |
| billing | `GET /` (nhập Mã khách hàng), `GET /license`, `GET /debt`, `POST /orders`, `GET /orders/<public_id>` | HTML; POST có CSRF token |
| billing | `GET /orders/<public_id>/status` | JSON để trang tự làm mới |
| billing | `POST /payos/webhook` | Chỉ tin chữ ký |
| api | `POST /v1/billing/session` | License, nhận cả token hết hạn |
| api | `GET /v1/license/renewals` | License, nhận cả token hết hạn; chỉ token của chính license đó |
| api | `GET /v1/account` (mở rộng) | Thêm hạn mức hiệu lực và nguồn |
| api | `GET/PUT /admin/price-book`, `GET/PUT /admin/limits` | `base_version` |
| api | `GET/POST /admin/payment-orders`, `…/<code>/cancel`, `…/<code>/refresh` | |
| api | `GET /admin/fulfillment/wait?cursor=&timeout=` | Kênh duyệt trực tiếp (long-poll, tối đa 25 giây) |
| api | `PUT /admin/token-mailbox/<license_id>/<sequence>`, `POST /admin/payment-orders/<code>/attention` | Dùng cho renewal-worker |
| api | `POST /admin/payos/confirm-webhook`, `GET /admin/reconciliation` | |
| api | `GET /admin/reports/<loại>.csv`, `GET /admin/reports/archive`, `GET /admin/reports/archive/<YYYY-MM>/<loại>.csv` | Báo cáo (mục 9.4) |

Mã lỗi mới:

| Mã | Khi nào |
|---|---|
| `503 PAYMENTS_DISABLED` | Thiếu biến payOS |
| `409 TOO_MANY_OPEN_ORDERS` | Đã có 3 đơn mở |
| `400 AMOUNT_OUT_OF_RANGE` | Số tiền ngoài khoảng cho phép |
| `404 PLAN_NOT_AVAILABLE` | Gói không có hoặc đã tắt |
| `409 PRICE_BOOK_CHANGED` | `base_version` lệch |
| `401 BILLING_SESSION_EXPIRED` | Phiên Billing hết hạn |

---

## 11. An toàn

- Khóa payOS chỉ nằm trên VM. Gateway không ghi log khóa, chữ ký, token license hay cookie phiên.
- Tiền chỉ được ghi khi webhook có chữ ký đúng, đơn tồn tại và **số tiền khớp**. Không có đường nào để client tự khai số tiền.
- Số tiền do server tính từ bảng giá. Trình duyệt chỉ gửi *gói* và *số ngày*, và hai giá trị này bị kẹp theo `min_days` và `max_days`.
- Phiên Billing:
  - code dùng một lần; chỉ lưu hash;
  - cookie HttpOnly + Secure;
  - POST có CSRF;
  - giới hạn tần suất theo IP và theo license.
- Token license hết hạn chỉ mở được 2 route: `billing/session` và `license/renewals`.
- Khóa ký license chỉ nằm ở máy admin. VM bị chiếm vẫn không in được license.
- Kênh duyệt trực tiếp do admin **gọi ra**. Không mở cổng vào máy admin. Tự ký bị chặn bởi các điều kiện ở mục 6.4 (số tiền khớp, license hợp lệ, tối đa 5 lần mỗi ngày, công tắc Tự duyệt).
- Host `billing` không có route admin hay API app (mục 2). Tài khoản dịch vụ của VM không xóa được bản sao lưu (mục 9.3).
- Mọi thao tác của admin và renewal-worker đều ghi audit.

---

## 12. Kiểm thử

- **Gateway** (`test_payments.py`, `test_billing_web.py`, dùng client payOS giả):
  - Chữ ký sai; webhook gửi hai lần; sai số tiền; đơn lạ; webhook bị lỡ được đối soát bắt lại.
  - `purpose=LICENSE` không trừ nợ. Không cho trả quá số nợ. Trả nợ xong thì hết `CREDIT_LIMIT`.
  - Hạn mức theo thứ bậc khách × app.
  - Tính giá theo ngày, gói tháng và giá riêng khách. Lỗi `PRICE_BOOK_CHANGED`. Giá mới không đổi đơn đã tạo.
  - Phiên dùng một lần và hết hạn. License hết hạn chỉ qua được 2 route.
  - Phân theo host: host `billing` trả 404 cho `/admin/*` và `/v1/*`; host API trả 404 cho trang cổng Billing và webhook; host lạ trả 404.
  - **Dọn dữ liệu không đổi nợ:** tạo job, chunk, billed_rows và thanh toán; ghi `account()` và `summary()`; chạy `prune()` ở các mốc thời gian giả lập; so sánh lại, nợ của mọi khách phải bằng nhau. Job `IN_PROGRESS` không bị đụng. Xóa theo lô không để lại dòng mồ côi.
- **Admin** (`test_billing.py`, `test_renewal_worker.py`, `test_table_ui.cjs`):
  - Bản nháp không gửi đi cho tới khi Lưu.
  - Worker: PAID → ký → hộp thư → FULFILLED. Ngắt giữa chừng không ký trùng. License `REPLACED` thì vào `NEEDS_ATTENTION`. Giành `fulfillment.lock` giữa UI và worker: chỉ một bên chạy, bên kia tiếp quản khi bên đầu thoát.
  - Kênh trực tiếp: webhook đánh thức long-poll trong dưới 1 giây; nối lại với `cursor` cũ thì nhận bù đủ đơn; hết 25 giây thì trả rỗng; tắt Tự duyệt thì không ký; quá 5 lần mỗi ngày thì vào `NEEDS_ATTENTION`.
- **App**: nhận hai token liên tiếp đúng thứ tự; mất mạng; mở cổng Billing khi license hết hạn; nút Trả nợ.
- **Với payOS thật trên VM mới**:
  - Đơn 2.000đ: quét QR → webhook qua Tunnel (kiểm tra WAF/Bot Fight của Cloudflare không chặn payOS) → token vào app.
  - Thử lại khi tắt máy admin, rồi bật lên.

---

## 13. Thứ tự triển khai [Chốt]

0. **Xây mới gateway trên VM GCP** (mục 9), tạo DB với `auto_vacuum=INCREMENTAL`, có `backup.py` chạy từ đầu (mục 9.3). Admin cấu hình từ đầu.
   **Trạng thái 2026-10-07: đã cài, chờ chủ sản phẩm kiểm tra.**
   - VM: vẫn Spot theo lựa chọn của chủ sản phẩm, nhưng đổi sang `instanceTerminationAction: STOP` và bỏ `maxRunDuration`. Bị thu hồi thì VM dừng, giữ đĩa, và phải bật lại tay.
   - Tài khoản dịch vụ riêng `audio-gateway-vm`, scope `cloud-platform`, chỉ có quyền trên bucket. Đã thử: xóa, ghi đè và liệt kê bucket khác đều bị 403.
   - Firewall: đã xóa `default-allow-ssh` và `default-allow-rdp`; SSH chỉ qua IAP.
   - Bucket `audio-gateway-backup-erp-project-8386` (asia-northeast2, chặn truy cập công khai, có lifecycle). Đã chạy một lần sao lưu và tải về khôi phục thành công (`integrity_check ok`, `auto_vacuum=2`).
   - Gateway cài bằng `bundle.py` + `vm-install.sh`, 1 worker TTS: health OK cả trên máy và qua `https://audio-gateway…`; Gemini trả 200 (không bị chặn IP).
   - `ADMIN_TOKEN` và `LEASE_MASTER_KEY` sinh mới, lưu trong `.env`. Admin đã nạp token mới và đẩy khóa gốc Basic/Plus.
   - **Lease materials đã đẩy** cho Basic và Plus (đã kiểm tra: gateway lưu mã hóa, không có khóa dạng rõ). Nguyên nhân trước đó không phải do chưa build: 3 sản phẩm đăng ký trước khi mã tạo content key theo sản phẩm tồn tại nên bảng `content_keys` trống. `Authority` giờ tự bù khóa còn thiếu khi mở DB (không đổi khóa đã có; có test và dòng audit `CONTENT_KEY_BACKFILLED`). Khóa **theo phiên bản** vẫn tạo ở lần `export_build_keys.py` đầu tiên của mỗi bản phát hành, sau đó phải đẩy lại lease materials.
   - Giá, hạn mức và khách: chủ sản phẩm tự nhập.
1. Tổng quát hóa `admin-system/billing.py` cho nhiều app.
2. Gateway: `payments.py`, `payment_orders`, sửa `payments`, webhook, đối soát, **`prune()` và bảng tổng hợp** (mục 3.6, 9.3), **báo cáo CSV và báo cáo tháng** (mục 9.4). Admin: tạo link, xem đơn, lịch sử, trang Báo cáo. → Hạng mục 1, 2, 3, 9, 10, L, N.
3. Bảng giá (ngày, gói tháng, giá riêng khách) và hạn mức nợ theo app, có nháp → Lưu.
4. Cổng Billing và phiên Billing; trả nợ qua web. App: nút **Trả nợ** và **Mua / gia hạn gói**, trang License. → Hạng mục 4, 5, 8.
5. Mua gói license: renewal-worker thường trú, **kênh duyệt trực tiếp**, hộp thư, app tự nhận token. → Hạng mục 6, E, I.

Mỗi bước chạy đủ test và được chủ sản phẩm kiểm tra rồi mới sang bước sau.

---

## 14. Đã chốt (2026-10-07)

1. Domain công khai là **cổng Billing** `billing.<domain>` (dự kiến `billing.arsneonci.space`), không dùng "store". API cho app và admin giữ host riêng (`audio-gateway.arsneonci.space`). Một tiến trình, hai hostname, để route admin không chạm tới người dùng.
2. Gói 12 tháng = 365 ngày. Cổng hiện giá/tháng làm chính, tổng tiền nhỏ hơn, kèm % tiết kiệm (mục 4.1a).
3. Có trang dự phòng nhập Mã khách hàng (mục 6.1).
4. Không khôi phục dữ liệu VM cũ: xây mới (mục 9.1).
5. Cấp token **tức thì** bằng kênh admin gọi ra (long-poll); quét 5 phút chỉ là dự phòng (mục 6.4).
6. Giới hạn đơn: 3 đơn mở mỗi license, hết hạn sau 15 phút (mục 3.1).
7. Thứ tự triển khai 6 bước (mục 13).
8. Dữ liệu phát sinh liên tục thì dọn và tổng hợp, dữ liệu thưa thì giữ (mục 9.3).

9. Bổ sung tải báo cáo: CSV theo kỳ cho admin và bộ báo cáo tháng lưu trên Cloud Storage (mục 9.4).

**Còn lại là chi tiết do agent đặt, chỉnh được khi triển khai [Đề xuất]:** sao kê cho khách trên cổng Billing (mục 9.4), các con số thời hạn giữ dữ liệu và lịch sao lưu (mục 9.3), giới hạn 5 lần tự ký mỗi license mỗi ngày, hỏi hộp thư mỗi 5 giây trong 15 phút (mục 7), Cloudflare Access cho `/admin/*` (mục 2).

**Sẽ thử khi triển khai [Kiểm chứng]:** giới hạn mã đơn và độ dài nội dung chuyển khoản của payOS, cách ký webhook, và cloudflared giữ nguyên `Host`.

---

## 15. Trạng thái triển khai (2026-10-07)

### 15.1 Đã làm và đã kiểm chứng

| Phần | Kết quả |
|---|---|
| Gateway (`billing-gateway`) | 80 test qua, gồm lớp HTTP thật. Thêm `payments.py`, `orders.py`, `pricebook.py`, `portal.py`, `web.py`, `retention.py`, `reports.py`, `gcs.py`; sửa `store.py`, `lease_authority.py`, `gateway.py` |
| Admin (`admin-system`) | 46 + 16 test qua (16 test thanh toán cần gói `payos`, chạy bằng venv của gateway). Thêm `fulfillment.py`, `renewal_worker.py`, `billing.py` nhiều app, trang **Payments**, 2 file test Node |
| App (`audio-translates`) | `tsc`, `eslint`, `check:i18n`, `check:theme`, `check:billing` sạch. Thêm `lib/server/billing-portal.ts`, `app/api/billing/route.ts`, nút trong trang License và nút **Trả nợ** khi job tạm dừng vì hạn mức |
| VM GCP | Gateway chạy bản mới, 1 worker TTS, sao lưu hằng ngày đã chạy và khôi phục thử thành công |
| Cloudflare | Thêm `billing.arsneonci.space` vào cùng Tunnel (Terraform, `deploy/tunnel`). Đã kiểm chứng cloudflared giữ nguyên `Host`: host billing và host API phục vụ route khác nhau |
| payOS | Webhook đã đăng ký (payOS gọi thử thành công). Đã tạo link thật 1.000đ và 2.000đ rồi hủy; webhook ký bằng khóa thật qua Cloudflare: đúng thì `200`, giả mạo thì `400` |
| Bảng giá | Đã lưu bản demo (phiên bản 1): 1.000đ/ngày (từ 1 ngày), mọi gói tháng 2.000đ (365 ngày cho gói 12 tháng), trả nợ tối thiểu 1.000đ, dịch 2.000đ và giọng đọc 1.000đ mỗi 1.000 ký tự |

### 15.2 Khác với bản thiết kế phía trên (và lý do)

1. **Mức tối thiểu của payOS là 1.000đ, không phải 2.000đ.** Đã thử trực tiếp: payOS nhận link 1.000đ. Hằng số `PAYOS_MIN_VND` trong `orders.py` là 1.000 (chưa thử mức thấp hơn).
2. **License đã hết hạn không lấy được token từ lõi bảo mật.** Hàm `credential()` trong `security-core` từ chối license hết hạn. Tôi **không sửa lõi này**: đó là thành phần bảo mật, đổi nó phải biên dịch lại, ký lại và kiểm thử lại cho cả hai gói. (Ghi chú sửa lỗi: lúc đầu tôi nêu lý do là máy không có `cargo`; điều đó chỉ đúng với PATH, vì máy có bộ Rust riêng ở `.toolsust` mà script build dùng.) Vì vậy:
   - Khi license còn hạn: app tạo liên kết một lần (đăng nhập sẵn, thấy token và app tự cài gia hạn trong vài giây).
   - Khi license đã hết hạn: app nhớ **Mã khách hàng** từ lúc còn hạn (`data/settings/billing.json`) và mở trang thanh toán với mã điền sẵn. Khách bấm Tiếp tục, trả tiền, rồi **sao chép mã gia hạn trên trang đơn hàng và dán vào ô Gia hạn** (cách dán tay vốn có). App không tự cài được trong trường hợp này.
   - Token trên trang đơn hàng chỉ hiện cho phiên của app, hoặc cho **chính phiên trình duyệt đã tạo đơn đó** (cột `session_hash`). Người khác có cùng Mã khách hàng không đọc được token của đơn cũ.
3. **Mã khách hàng** là 10 ký tự Crockford base32 sinh ngẫu nhiên cho mỗi license. Nhập sai 10 lần trong 10 phút thì bị chặn theo IP.
4. **Sao kê khách tự tải** (`/statement.csv` trên cổng Billing) đã làm; chưa có nút trong trang (chỉ có đường dẫn).
5. **Đơn trả nợ** tối thiểu là `min(trả tối thiểu của bảng giá, số nợ)`, và không cho trả quá số nợ.
6. **Mã đơn** là `epoch giây × 1000 + số ngẫu nhiên 0-999`; payOS chấp nhận.
7. **Xem trước và nháp** của trang Bảng giá chạy ở trình duyệt; logic của chúng có test Node (`test_payments_ui.cjs`), nhưng **chưa được kiểm tra bằng mắt trong trình duyệt thật**.

### 15.3 Chưa làm / chưa kiểm chứng

- **Chưa có giao dịch tiền thật nào từ đầu đến cuối** (không thể tự trả tiền). Công thức thử ở 15.4.
- **Tác vụ Windows `AudioTranslateRenewalWorker` chưa cài** (thay đổi lâu dài trên máy của bạn). Bấm **Cài tác vụ Windows** ở tab Gia hạn, hoặc `renewal_worker.py --install-task`. Cho tới khi cài, đơn gia hạn chỉ được ký khi **giao diện admin đang mở** (hoặc worker chạy tay).
- **App chưa build installer mới.** Nút thanh toán chỉ có sau khi build lại app (kèm `export_build_keys.py` cho bản phát hành mới, rồi đẩy lại lease materials).
- **Hạn mức nợ** chưa đặt: mặc định toàn cục là 0 nên khách mới chưa dùng được Genius/giọng đọc. Đặt ở tab Hạn mức.
- `next build` chưa chạy (tránh ghi đè `.next` của dev server); `tsc` và `eslint` đã sạch.
- Giá trị **[Đề xuất]** vẫn là con số tôi đặt: 5 lần tự ký/ngày, hỏi hộp thư mỗi 5 giây trong 15 phút, các hạn dọn dữ liệu.

### 15.4 Cách thử một giao dịch thật

1. Trong admin: tạo khách, tạo entitlement cho gói Basic/Plus, cấp token kích hoạt, dán vào app (cần bản app có nút mới).
2. Mở admin → Payments → tab **Gia hạn**: kiểm tra *Kênh duyệt trực tiếp: đang nối*.
3. Trong app, trang License → **Mua / gia hạn gói** → chọn 1 tháng (2.000đ) → quét QR trả tiền thật.
4. Kỳ vọng: trong vài giây trang đơn hiện *Hoàn tất*, app báo "Đã nhận và cài gia hạn mới", `sequence` tăng thêm 1 và hạn dùng thêm 30 ngày. Admin: tab Đơn có đơn *Hoàn tất*, tab Lịch sử có khoản thu `PAYOS` / `LICENSE`.
5. Thử trả nợ: tạo job Genius cho tới khi gặp *CREDIT_LIMIT* (đặt hạn mức nhỏ trước), bấm **Trả nợ**, rồi **Tiếp tục**.
6. Thử máy admin tắt: trả tiền khi admin đóng và worker chưa cài; bật admin lên thì đơn được ký bù trong vài giây.
