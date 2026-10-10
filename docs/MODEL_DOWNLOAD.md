# Tải model dịch sau khi cài

Trạng thái: 2026-10-07. Mã đã viết và có test (gateway 84 test, `scripts/check-model-download.cjs`, lint, tsc, i18n). **Phần GCP (bucket, quyền, upload, cấu hình gateway) chưa làm được lúc viết** vì lệnh tạo bucket và cấp quyền IAM bị chặn chờ bạn duyệt; xem mục 3. Chưa thử tải model thật từ bucket.

## 1. Vì sao

Windows không chạy file `.exe` lớn hơn 4 GiB (đã thử: một exe 4,5 GiB bị báo "This app can't run on your PC"). Model `Hy-MT2-7B-Q4_K_M` nặng 4,6 GB nên không thể nằm trong bộ cài. Bộ cài giờ chỉ còn dưới 1 GB; model tải một lần sau khi kích hoạt.

## 2. Luồng

1. App kích hoạt bản quyền như thường. Trang nào cũng hiện một thanh báo **"Model dịch trên máy"** cho tới khi có model (`components/layout/model-banner.tsx`).
2. Khách bấm **Tải model**. Server của app (`lib/server/model-download.ts`) lấy token bản quyền từ lõi bảo mật và gọi gateway `POST /v1/model/url {"model":"hy-mt2-7b-q4km"}`.
3. Gateway kiểm tra bản quyền còn hạn và chưa bị thu hồi, rồi trả về **một link ký sẵn có hạn 1 giờ** tới file trong bucket riêng. Mỗi bản quyền tối đa 12 link mỗi ngày (đếm trong bộ nhớ, reset khi gateway khởi động lại).
4. App tải thẳng từ Cloud Storage vào `%LOCALAPPDATA%\AudioTranslate\data\models\Hy-MT2-7B-Q4_K_M\`, ghi vào file `.part`, **tiếp tục được khi đứt mạng** (Range), tự xin link mới khi link hết hạn.
5. Tải đủ thì tính SHA-256 và so với giá trị **ghi cứng trong app** (`MODEL` trong `model-download.ts`). Đúng mới đổi tên và ghi file `.ok`; sai thì xóa và báo lỗi. Lần khởi động sau không tính lại hash nếu `.ok` còn khớp kích thước và thời gian sửa file.
6. Launcher (`packaging/launcher.py`) trỏ `HY_MT_MODEL_PATH` tới thư mục dữ liệu này, nên worker dịch dùng đúng file đã kiểm.

Phần ký link: gateway dùng service account của VM, ký qua IAM Credentials API (`signBlob`), nên trên VM **không có khóa riêng nào** (`billing-gateway/gcs.py`, `signed_url`). Bucket không công khai.

## 3. Việc phải làm ở GCP (một lần)

Tên bucket đề xuất: `audio-translate-models-8386`, vùng `asia-northeast2` (cùng VM).

```
gcloud storage buckets create gs://audio-translate-models-8386 --project erp-project-8386 --location asia-northeast2 --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets add-iam-policy-binding gs://audio-translate-models-8386 --member serviceAccount:audio-gateway-vm@erp-project-8386.iam.gserviceaccount.com --role roles/storage.objectViewer
gcloud iam service-accounts add-iam-policy-binding audio-gateway-vm@erp-project-8386.iam.gserviceaccount.com --member serviceAccount:audio-gateway-vm@erp-project-8386.iam.gserviceaccount.com --role roles/iam.serviceAccountTokenCreator
```

- Dòng 2 cho service account của VM quyền **chỉ đọc** bucket model (cần để link ký tải được file).
- Dòng 3 cho service account quyền ký bằng chính nó (cần cho `signBlob`). Quyền này chỉ trên chính tài khoản đó.
- API `iamcredentials.googleapis.com` đã bật (đã kiểm tra), VM có scope `cloud-platform` (đã kiểm tra).

Rồi upload model (script kiểm tra kích thước và SHA-256 trước, không ghi đè file đã có, và so CRC32C sau khi tải lên):

```
cd audio-translates
.venv\Scripts\python.exe packaging\upload_model.py --bucket audio-translate-models-8386
```

Cuối cùng cấu hình gateway: thêm `MODEL_BUCKET=audio-translate-models-8386` vào `/etc/audio-gateway/gateway.env` trên VM (hoặc qua file secrets của `vm-install.sh`), triển khai lại mã gateway (`deploy/bundle.py` + `vm-install.sh`), khởi động lại `audio-gateway`. Thiếu `MODEL_BUCKET` thì gateway trả `503 MODEL_DOWNLOAD_DISABLED` và app hiện thông báo tương ứng.

## 4. Chi phí và giới hạn (chưa kiểm chứng)

- Mỗi lượt tải 4,6 GB là băng thông ra khỏi GCP, có tính phí theo bảng giá của GCP cho vùng này; tôi chưa tra giá hiện tại. Giới hạn 12 link mỗi bản quyền mỗi ngày chỉ là rào chắn thô, không chặn một khách tải lại nhiều lần trong giới hạn đó.
- Nếu lượng khách tăng, cân nhắc Cloudflare R2 (không tính phí băng thông ra) và giữ nguyên cách gateway cấp link.

## 5. Đổi model hoặc phiên bản model

1. Đổi `FILENAME`/`SIZE`/`SHA256` trong `worker/tools/download_translation_model.py` và `MODEL` trong `lib/server/model-download.ts` (hai chỗ phải khớp).
2. Thêm id mới vào `MODELS` trong `billing-gateway/gateway.py` và upload bằng `upload_model.py`.
3. Build lại hai gói. App cũ vẫn dùng link/id cũ nên không hỏng.

## 6. Kiểm tra

- Gateway: `billing-gateway\.venv\Scripts\python.exe -m unittest discover -p "test_*.py"` (có `test_signed_url.py` và test link model trong `test_lease_gateway.py`).
- App: `node scripts/check-model-download.cjs` (máy chủ HTTP thật giả làm Cloud Storage: tải, tiếp tục sau khi đứt, link hết hạn, file bị sửa, gateway từ chối, file đặt tay).

## 7. Giao diện tải và vì sao "không tải được" (2026-10-07)

- Nguyên nhân thực tế đã tái hiện trên máy thử: app **chưa kích hoạt** (`UNACTIVATED`) nên lõi bảo mật không cấp token, lệnh tải dừng ngay với `LICENSE_REQUIRED` mà không gọi mạng. Đây là hành vi đúng, nhưng trước đây giao diện không nói rõ.
- Giao diện giờ: nếu license chưa hợp lệ thì thanh báo hiện "chưa kích hoạt" kèm nút mở trang Giấy phép, không có nút tải. Khi đang tải: thanh tiến trình, phần trăm, GB đã tải / tổng, tốc độ MB/giây và thời gian còn lại; khi đang kiểm hash thì hiện tiến độ kiểm. Cập nhật 1,5 giây một lần.
- Chống lặp lệnh: nút bị khóa từ lúc bấm tới lúc server trả lời và biến mất khi đang tải; ở server, việc kiểm tra và giành quyền tải nằm trong cùng một bước đồng bộ nên ba lần bấm cùng lúc chỉ tạo **một** lượt tải và **một** link (không tốn hạn mức 12 link mỗi ngày). `scripts/check-model-download.cjs` kiểm cả hai.

## 8. Mô hình nhận dạng giọng nói cũng lấy từ kho này (2026-10-08)

Trước đây mô hình nhận dạng giọng nói (3 mô hình, 2,04 GB) do FunASR tự tải từ ModelScope **ngay trong lúc worker chép lời khởi động**, và bước đó bị giới hạn 180 giây: lần chạy đầu thường chết ở khoảng 54% mô hình 990 MB (`ASR model startup timed out`), chạy lại cũng vậy.

Giờ có một bước tải riêng **trước khi worker bắt đầu đếm giờ** (`worker/audio_translate/transcription/model_prefetch.py`):
- Nguồn chính là cùng bucket `audio-translate-models-8386`, thư mục `models/asr/<tên mô hình>/<tệp>`, qua link ký 1 giờ của gateway cho license hợp lệ: `POST /v1/model/url {"model":"asr-zh","paths":[...]}` trả `{"urls":{đường dẫn: link}}`. Cả bộ tính **một** lượt trong hạn mức 12 link mỗi ngày mỗi license. Chỉ các tệp có trong `asr_models.json` mới được cấp.
- `worker/config/asr-models.json` ghim kích thước và SHA-256 của từng tệp (21 tệp). Tải vào `<tệp>.part`, tải tiếp bằng Range nếu đứt, so SHA-256 rồi mới đổi tên; tệp sai bị xóa, không giữ. Link hết hạn thì xin lại. Tối đa 6 lần mỗi tệp, không giới hạn thời gian.
- Tiến độ hiện ngay trên công việc: "Đang tải mô hình nhận dạng giọng nói (chỉ lần đầu): x / y GB, tệp i/n".
- **Dự phòng:** nếu gateway không dùng được (chưa có license, mất mạng, gói chưa được đăng) thì tải từ ModelScope như FunASR vẫn làm, nhưng vẫn không có hạn 180 giây.
- Chỉ tải thứ còn thiếu. Tệp nào đã có đúng kích thước thì không tải lại.

Đổi hoặc thêm mô hình:
1. Có thư mục chứa đủ mô hình (cấu trúc `models/<org>--<tên>/snapshots/master`), chạy `python packaging\make_asr_manifest.py --source <thư mục>` (ghi `worker/config/asr-models.json` và `billing-gateway/asr_models.json`).
2. `python packaging\upload_model.py --bucket audio-translate-models-8386 --asr <thư mục>` (kiểm SHA-256 từng tệp trước, không ghi đè, so kích thước sau khi lên).
3. Triển khai gateway (`deploy_gateway.py`, đã gồm `asr_models.json`) rồi build lại hai gói.

Đã kiểm chứng: 21 tệp trên bucket đều khớp SHA-256 ghim (VM tải về trong 13 giây); gateway ký được link cho cả bộ; 14 test của bước tải (tải tiếp, link hết hạn, tệp sai, gateway hỏng, ModelScope dự phòng). Chưa kiểm chứng đầu-cuối trong app thật: cần kích hoạt license rồi chạy bước chép lời trên máy chưa có `model-cache`.

Tổng dung lượng khách phải tải sau khi cài: 4,6 GB mô hình dịch (sau khi kích hoạt, bấm "Tải model"; chỉ cần cho chế độ Normal) và 2,04 GB mô hình nhận dạng giọng nói (tự tải ở lần chép lời đầu tiên).
