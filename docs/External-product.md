# Prompt tích hợp sản phẩm bên ngoài với Admin System

## Cách dùng và giới hạn hiện tại

Sao chép phần **Prompt** bên dưới vào dự án mới, điền các biến đầu vào và cung cấp đường dẫn mã nguồn Admin/SDK để agent đọc hợp đồng thực tế. Đây là yêu cầu triển khai, không phải một manifest có khả năng tự tích hợp ứng dụng.

`product.manifest.json` nằm ở gốc repository sản phẩm. Admin đọc file khi **Register Product Manifest**, lưu nội dung và dùng thư mục chứa file làm `repo_path`. Mỗi `product_id` mới có root key và delegated signing key độc lập. Đăng ký lại cùng ID cập nhật manifest/version/path nhưng giữ authority hiện có. Sau khi sửa file phải đăng ký lại: Admin không theo dõi file tự động.

Admin đóng gói thành desktop app vẫn có thể đọc manifest ngoài nếu giữ chức năng đăng ký, đường dẫn repository có quyền truy cập và database/DPAPI được giữ trong thư mục dữ liệu bền vững. Quản lý khách hàng, entitlement và token không phụ thuộc việc repo sản phẩm nằm trong Admin. Build cần toolchain trên máy Admin; khách hàng chỉ cần runtime trong installer.

**Giới hạn quan trọng:** `admin-system/builds.py` hiện chỉ đăng ký adapter `audio-translate` trong `ADAPTERS`. `build_command` là thông tin hiển thị, không được BuildService thực thi trực tiếp. Một manifest của ứng dụng mới có thể đăng ký để quản lý bản quyền, nhưng **Build Product** sẽ thất bại nếu `build_adapter` chưa được đăng ký. Bản Admin desktop đóng gói cố định cần cập nhật/rebuild để thêm adapter mới; hiện chưa có cơ chế tự nạp plugin/adapter ngoài. Không dùng tên adapter `audio-translate` cho dự án khác chỉ để vượt kiểm tra.

Khi đóng gói Admin cần xử lý bootstrap đang mặc định đọc `../audio-translates/product.manifest.json` nếu chưa có sản phẩm đó, đưa `schema.sql`/UI/SDK vào gói, tách dữ liệu ghi khỏi thư mục cài đặt và bảo toàn cơ chế localhost/session/CSRF. Không xóa database hay tạo lại root khi nâng cấp. Khóa riêng được DPAPI bảo vệ theo tài khoản Windows của Admin; sao chép database sang máy/tài khoản khác không đủ để khôi phục khóa.

## Prompt

Bạn hãy triển khai hoàn chỉnh dự án Windows desktop sau để liên kết với Licensing Admin System hiện có và quản lý bản quyền theo Product → Customer → Entitlement → Machine → License → Renewal.

### Đầu vào

- PRODUCT_ID: `<id-duy-nhat-chu-thuong-so-va-dau-gach-ngang>`
- PRODUCT_NAME: `<ten-hien-thi>`
- PRODUCT_VERSION: `<major.minor.patch>`
- PRODUCT_REPO: `<duong-dan-tuyet-doi-repository-moi>`
- ADMIN_SOURCE: `<duong-dan/admin-system>`
- SHARED_SDK_SOURCE: `<duong-dan/shared-license-sdk>`
- REFERENCE_PRODUCT_SOURCE: `<duong-dan/audio-translates>`
- APP_STACK: `<cong-nghe-cua-du-an>`
- BUILD_ADAPTER_ID: `<ten-adapter-rieng>`
- INSTALLER_PATH: `dist/<ProductName>-<major.minor.patch>.exe`
- PROTECTED_FEATURES: `<nhung-tinh-nang-phai-co-license-con-han>`
- AVAILABLE_WHEN_EXPIRED: `<UI/license/history/download-hoac-chinh-sach-cu-the>`
- ADMIN_DISTRIBUTION: `<source-hoac-desktop-da-dong-goi>`

Nếu các đường dẫn hoặc chính sách bắt buộc còn thiếu, hỏi thông tin cần thiết. Đọc mã nguồn thật trước khi triển khai; không tự suy đoán API, token schema hay khả năng plugin chưa tồn tại. Hoàn thành mọi công việc độc lập có thể làm trong lúc chờ thông tin.

### 1. Kiểm tra hợp đồng hiện có

Đọc `core.py`, `schema.sql`, `builds.py`, `run.py`, README của Admin và SDK. Dùng Security Core Rust của sản phẩm tham chiếu làm mẫu cho verifier/native broker, nhưng thay toàn bộ định danh, đường dẫn dữ liệu và chính sách command của sản phẩm cũ bằng giá trị của dự án mới. SDK Python hiện là verifier tham chiếu/tương thích kiểm thử; không mặc định dùng nó thay Security Core native cho mức bảo vệ như sản phẩm tham chiếu.

Giữ nguyên Admin làm authority duy nhất: app khách hàng không tạo license, không giữ khóa ký riêng và không đọc database Admin. Mỗi sản phẩm có một root public key được pin khi build, dưới đó các delegated signing key có certificate để hỗ trợ Rotate Signing Key.

### 2. Cấu trúc dự án và manifest

Tạo cấu trúc tương đương sau, điều chỉnh thư mục giao diện/backend theo APP_STACK:

```text
<PRODUCT_REPO>/
  product.manifest.json
  licensing/
    public-config.json           # chỉ metadata công khai lúc chạy
  security-core/
    Cargo.toml
    Cargo.lock
    build.rs
    src/                        # verifier, secure store, native broker
    trust-anchor.json           # đầu vào công khai chỉ dùng lúc build
    bin/<product-security-core>.exe
  packaging/
    build_security_core.py      # hoặc script tương đương
    build_installer.py          # hoặc script tương đương
  dist/<ProductName>-<version>.exe
  tests/
  README.md
```

Tạo manifest hợp lệ theo mẫu (thay mọi placeholder):

```json
{
  "product_id": "<PRODUCT_ID>",
  "name": "<PRODUCT_NAME>",
  "platform": "windows",
  "version": "<PRODUCT_VERSION>",
  "build_adapter": "<BUILD_ADAPTER_ID>",
  "license_scheme": "ed25519-v1",
  "build_command": ["<build-tool>", "<build-script>"],
  "artifact_path": "dist/<ProductName>-<version>.exe"
}
```

ID phải khớp `[a-z0-9][a-z0-9-]{1,60}`; version phải là ba nhóm chữ số ngăn bằng dấu chấm. Không đưa khóa riêng, token, khách hàng, đường dẫn database hoặc thông tin entitlement vào manifest/installer. Metadata runtime gồm `product_id`, `version`, `scheme`; root public key lấy từ Admin, biên dịch vào native core qua trust anchor. Không dùng root của Audio Translate cho sản phẩm mới, không tạo root mẫu cho bản phát hành thực.

### 3. Build adapter và Admin desktop

Triển khai adapter riêng tương thích `ProductBuildAdapter` với đủ sáu phương thức:

1. `validateEnvironment`: kiểm tra manifest, version, repository, toolchain và script build.
2. `prepareBuild`: chuẩn bị staging chỉ thuộc sản phẩm.
3. `injectPublicConfig`: nhận `Authority.public_config(PRODUCT_ID)`; ghi metadata công khai và trust anchor bằng thao tác thay file an toàn.
4. `build`: chạy build bằng argv, cwd xác định, timeout hữu hạn; kiểm tra exit code; không log dữ liệu authority.
5. `getArtifact`: trả `Path` installer đúng version; xác minh tồn tại và thuộc `dist` đã resolve, tránh path traversal.
6. `cleanup`: chỉ dọn staging do adapter sở hữu; không xóa repo, license state hoặc artifact phát hành.

Đăng ký lớp adapter trong `ADAPTERS` của Admin. Nếu Admin là binary đóng gói cố định, cung cấp bản cập nhật Admin có adapter mới. Nếu chỉ được chỉnh repo sản phẩm, hoàn thành tích hợp client và cung cấp patch adapter cùng hướng dẫn cài đặt cho Admin; báo rõ Build Product chưa hoạt động trước khi adapter được cài. Không tuyên bố manifest tự nạp mã adapter. Cơ chế plugin động/generic adapter là một thay đổi riêng cần được triển khai và kiểm thử nếu muốn hỗ trợ dự án mới mà không rebuild Admin.

Giữ nguyên BuildService lưu hash SHA-256 và tái sử dụng release `COMPLETED` theo product/version. Không build theo khách hàng; một installer chung cho mọi khách hàng. Đổi mã phát hành phải tăng version rồi đăng ký lại manifest. Không ghi đè artifact của version đã phát hành. Đường dẫn artifact phải bền vững sau restart/nâng cấp Admin để Download Installer tiếp tục hoạt động.

### 4. License tương thích byte-for-byte

Triển khai theo mã thật của SDK/Security Core; giữ envelope `scheme`, `certificate`, `payload`, `signature` và `scheme = ed25519-v1`. Base64 URL-safe không padding; canonical JSON sắp xếp key, phân cách `,`/`:`, ASCII escaping và cấm NaN. Miền chữ ký gồm domain UTF-8 + byte NUL + canonical payload:

- Certificate: `product-signing-key-v1`, payload `product_id`, `key_version`, `public_key`.
- License: `machine-license-v1`, payload `license_id`, `entitlement_id`, `customer_id`, `product_id`, `machine_id`, `sequence`, `activated_at`, `issued_at`, `expires_at`, `key_version`.

Xác minh certificate bằng root đã biên dịch, rồi license bằng public key trong certificate; kiểm tra schema, product ID, key version, machine binding, timestamp và expiration. Từ chối field trùng lặp/sai schema, token lỗi, sai chữ ký, sai product và machine. Không tin root do token, file metadata có thể sửa hoặc biến môi trường runtime cung cấp.

Machine ID phải tương thích thuật toán Windows MachineGuid + SMBIOS System UUID được chuẩn hóa và SHA-256 trong mã tham chiếu, không dùng random UUID hay username. Mỗi entitlement chỉ dùng một máy. UI có trang License với Machine ID có thể copy, nhập kích hoạt lần đầu, nhập renewal và xem trạng thái/ngày hết hạn.

Activation bắt đầu ở sequence 1. Renewal phải nối đúng license/entitlement/customer/product/machine/activated_at, có sequence bằng sequence hiện tại + 1, key_version không giảm và expires_at tăng. Từ chối replay/nhảy sequence. Reissue của Admin trả nguyên token cũ, không phải một renewal mới. Sau khi Rotate Signing Key, app nhận certificate mới trong token và xác minh bằng root cũ; không cần build lại installer.

Lưu token/current key, machine, sequence cao nhất và thời gian đã xác minh bằng Windows DPAPI, có khóa liên tiến trình và atomic write như mã tham chiếu. State nằm trong thư mục dữ liệu riêng theo sản phẩm dưới LocalAppData, được giữ qua update. Không dùng state/path/env của Audio Translate. Không reset license để vượt replay, expiry hoặc clock rollback.

### 5. Chặn tính năng ở nơi thực thi

Pin product/root trong native core. Backend và đường chạy worker/tác vụ phải đi qua native broker xác minh license trước khi chạy PROTECTED_FEATURES; không chỉ disable nút UI. Broker dùng allowlist lệnh/script và đường dẫn cố định của app, từ chối lệnh tùy ý. Core thiếu/hỏng hoặc kiểm tra thất bại thì từ chối tính năng bảo vệ, không có dev unlock/Python fallback.

Theo chính sách tham chiếu, nhập token và xem trạng thái hoạt động offline; bắt đầu tác vụ bảo vệ cần quorum thời gian Internet từ các nguồn HTTPS độc lập và chặn khi không đủ quorum hoặc phát hiện rollback. Nêu rõ điều này trong README/UI: offline activation không có nghĩa mọi chức năng chạy hoàn toàn offline. Giữ AVAILABLE_WHEN_EXPIRED theo chính sách đầu vào và chặn đầy đủ API/worker tương ứng.

Admin hiện quản lý bằng trao đổi token thủ công, không có server online cấp/thu hồi license. Reset/Replace Device và rotation không vô hiệu hóa tức thời token cũ trên máy offline. Không hứa chống tuyệt đối người có quyền administrator sửa binary, giả hardware hoặc rollback toàn bộ state; muốn thu hồi từ xa cần dịch vụ online riêng.

### 6. Đóng gói và kiểm chứng

Installer mang runtime cần thiết và native core đã biên dịch; không yêu cầu khách hàng có repo Admin, Python/Node/Rust toolchain hoặc đọc manifest để chạy. Không kèm private authority keys, database Admin, session grant, token kiểm thử hay dữ liệu khách hàng. Trust anchor JSON là đầu vào build công khai; root authoritative ở runtime nằm trong native executable.

Dùng database, root và khách hàng tổng hợp độc lập cho kiểm thử. Không đọc/in/xuất khóa riêng thực, không tạo khách hàng hay entitlement thử trong database production. Kiểm thử:

- Đăng ký product mới/đăng ký lại, độc lập root giữa các product.
- Build bằng adapter thật, kiểm tra installer/hash và reuse release; activation/renewal không gọi build.
- Kích hoạt đúng máy và chặn máy/sản phẩm/token sai, state hỏng hoặc core thiếu.
- Expiry, clock rollback, trusted-time quorum mất, renewal sau hết hạn, replay và sai sequence.
- Token từ delegated key mới sau rotation được installer cũ chấp nhận.
- API/worker không thể chạy PROTECTED_FEATURES bằng cách bỏ qua UI; ngoại lệ khi hết hạn đúng chính sách.
- Cài đặt trên Windows sạch có runtime đầy đủ; nâng cấp giữ nguyên state.
- Quét installer để không mang dữ liệu authority/khách hàng; kiểm tra DPAPI trên máy thứ hai nếu có thiết bị, nếu chưa có thì ghi rõ chưa kiểm chứng vật lý.

### 7. Bàn giao

Bàn giao mã sản phẩm, manifest hoàn chỉnh, adapter/patch Admin, build scripts, installer khi môi trường cho phép và kết quả kiểm thử thực tế. README phải hướng dẫn: đăng ký manifest bằng đường dẫn tuyệt đối → Build Product → Download Installer → tạo Customer/Entitlement → nhận Machine ID → phát activation → nhập token → gia hạn tuần tự. Mô tả cách cập nhật version, thêm adapter vào Admin desktop và bảo toàn database/DPAPI khi nâng cấp. Liệt kê rõ phần đã chạy và phần còn phụ thuộc toolchain/máy thứ hai/bản cập nhật Admin; không coi việc chỉ tạo manifest là tích hợp hoàn tất.
