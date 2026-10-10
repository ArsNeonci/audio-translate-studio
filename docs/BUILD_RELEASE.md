# Tự build bộ cài Basic và Plus

Hướng dẫn cho chủ sản phẩm tự build, không cần nhờ agent. Nguồn: `packaging/build_installer.py`, `packaging/build_security_core.py`, `admin-system/release_config.py`, `admin-system/export_build_keys.py` và `docs/SECURITY_PHASE_*_RESULT.md`.

Trạng thái: 2026-10-07. Script `packaging/build_edition.py` mới viết và **chỉ đã chạy thử ở chế độ `--dry-run`** (kiểm tra máy và in các bước); tôi chưa build thật gói Basic/Plus nào bằng nó. Các bước bên trong là những lệnh sẵn có.

---

## 1. Build bằng một lệnh

Mở terminal, chạy **bằng Python của chính repo này**:

```
cd C:\Workspace\Audio-translate\audio-translates
.venv\Scripts\python.exe packaging\build_edition.py basic
.venv\Scripts\python.exe packaging\build_edition.py plus
```

Mỗi lệnh build **một gói**, mất khoảng 10 đến 30 phút (ước tính, chưa đo), kết quả nằm ở:

| Gói | File cài | Bản ghi phát hành |
|---|---|---|
| Basic | `dist\AudioTranslate-Basic-<version>.exe` | `dist\release-audio-translate-basic-<version>.json` |
| Plus | `dist\AudioTranslate-Plus-<version>.exe` | `dist\release-audio-translate-plus-<version>.json` |

Tùy chọn:

| Tùy chọn | Ý nghĩa |
|---|---|
| `--dry-run` | Kiểm tra máy và in đủ 5 bước, **không đổi gì**. Nên chạy trước lần đầu |
| `--push-lease` | Build xong thì đẩy khóa của phiên bản mới lên gateway (cần admin đã cấu hình gateway) |
| `--force` | Bỏ qua yêu cầu RAM/ổ đĩa tối thiểu (xem mục 6) |
| `--keys-dir <thư mục>` | Nơi lưu file khóa phiên bản; mặc định `C:\Users\<bạn>\audio-translate-keys` |

Script chỉ nối các bước với nhau và dừng ở bước lỗi đầu tiên, không in khóa:

1. **Kiểm tra máy:** RAM trống ≥ 5 GiB, ổ đĩa trống ≥ 20 GiB (hai ngưỡng này do tôi đặt rộng tay, chưa đo), có Python của repo, môi trường admin, `node_modules`, bộ Rust, trình biên dịch .NET, file model dịch.
2. **Cấu hình công khai và trust anchor:** admin đọc lại manifest rồi xuất `licensing\<gói>.public-config.json` và `security-core\trust-anchor.<gói>.json`.
3. **Khóa phiên bản:** xuất khóa của đúng phiên bản này ra file **ngoài mọi repo** (`...\audio-translate-keys\<gói>-<version>.key`). Không bao giờ commit hay gửi file này đi.
4. **Build bộ cài:** biên dịch lõi bảo mật Rust, build Next.js, gom Python/Node và model, mã hóa tài sản, quét bí mật, nén và ghép bộ cài.
5. **Kiểm tra bộ cài:** `audit_package.py` quét xem có khóa riêng, token hay dữ liệu khách lọt vào không.

Cuối cùng, nếu chưa dùng `--push-lease`, vào **admin → Billing → *Đẩy khóa phiên bản (lease)* (Push Lease Keys)** (mục 4).

---

## 2. Chuẩn bị một lần

Máy này đã có đủ (preflight đã báo `ok` cho từng mục): môi trường admin, `node_modules`, bộ Rust riêng trong `C:\Workspace\Audio-translate\.tools\rust`, .NET Framework 4 (`csc.exe`), model dịch `models\Hy-MT2-7B-Q4_K_M`. Máy mới cần cài đủ các thứ này (xem README của từng thành phần).

Cần có sẵn và chạy được:
- admin-system đã đăng ký hai gói (`audio-translate-basic`, `audio-translate-plus`); chỉ cần mở admin một lần là tự đăng ký.
- Không có workflow đang chạy: build ngốn RAM và CPU, dễ làm workflow tạm dừng vì thiếu RAM.

---

## 3. Làm từng bước bằng tay (khi cần tìm lỗi)

Thay `<gói>` bằng `audio-translate-basic` hoặc `audio-translate-plus`, `<ver>` bằng phiên bản trong manifest.

```
cd C:\Workspace\Audio-translate\admin-system
.venv\Scripts\python.exe release_config.py <gói>
.venv\Scripts\python.exe export_build_keys.py --product <gói> --version <ver> --out C:\Users\<bạn>\audio-translate-keys\<gói>-<ver>.key

cd C:\Workspace\Audio-translate\audio-translates
set AUDIO_CONTENT_KEY_FILE=C:\Users\<bạn>\audio-translate-keys\<gói>-<ver>.key
.venv\Scripts\python.exe packaging\build_installer.py --product <gói>

cd C:\Workspace\Audio-translate\admin-system
.venv\Scripts\python.exe audit_package.py --edition basic       (hoặc plus)
```

---

## 4. Sau khi build xong

1. **Đẩy khóa phiên bản lên gateway** (nếu chưa dùng `--push-lease`): admin → Billing → *Đẩy khóa phiên bản (lease)* (Push Lease Keys). Thiếu bước này thì app của khách không xin được lease cho phiên bản mới.
2. **Thử cài** bộ cài trên một máy thử (hoặc thư mục tạm): kích hoạt bằng một token thử và kiểm tra các trang License, nút **Mua / gia hạn gói**.
3. **Phát cho khách:** gửi file `.exe` trong `dist`. Cùng một bộ cài dùng cho mọi khách của gói đó; mỗi khách chỉ khác nhau ở token license.
4. **Ngừng hỗ trợ bản cũ** (tùy chọn): admin gọi `retire_version` cho phiên bản cũ để khách phải cập nhật; xem `Doc-Admin.md`.

---

## 5. Có thay đổi thì làm gì

| Bạn đổi | Cần build lại app? | Việc cần làm |
|---|---|---|
| Giá gói, giá dịch vụ, hạn mức nợ, nội dung trang thanh toán | **Không** | Sửa ở admin → Payments, bấm Lưu & áp dụng |
| Nút bấm, chữ trong app, logic xử lý (thư mục `app`, `components`, `lib`, `worker`) | **Có** | Tăng phiên bản (bên dưới), build lại từng gói |
| `billing-gateway` (gateway, cổng thanh toán, webhook) | Không | Triển khai lại lên VM (`README` của billing-gateway) |
| `admin-system` | Không | Đóng và mở lại admin |

**Tăng phiên bản** (bắt buộc khi đã build một phiên bản rồi mà mã đã đổi, nếu không script dừng với `VERSION_ALREADY_RELEASED`): trong **cả hai** file `products\basic\product.manifest.json` và `products\plus\product.manifest.json`, sửa `version` (ví dụ `1.2.0` thành `1.2.1`) **và** `artifact_path` cho khớp (`dist/AudioTranslate-Basic-1.2.1.exe`). Rồi chạy lại `build_edition.py`; bước 1 tự đăng ký phiên bản mới với admin.

Mỗi phiên bản có khóa nội dung riêng, nên sau mỗi lần build phiên bản mới nhớ **đẩy khóa phiên bản (lease)**.

---

## 6. Lỗi thường gặp

| Thông báo | Nguyên nhân và cách xử lý |
|---|---|
| `free RAM >= 5 GiB` báo FAIL | Đóng bớt chương trình, hoặc đợi workflow chạy xong. Đang có workflow dịch thì **không** build. `--force` chỉ dùng khi bạn biết mình đang làm gì |
| `VERSION_ALREADY_RELEASED: bump version` | Mã đã đổi nhưng chưa tăng phiên bản. Làm theo mục 5 |
| `RELEASE_ARTIFACT_MISSING_OR_MODIFIED` | File `.exe` hoặc bản ghi `release-*.json` bị xóa hoặc sửa. Xóa cả hai file của phiên bản đó rồi build lại |
| `PUBLIC_CONFIG_INVALID` | Phiên bản trong manifest khác với cấu hình đã xuất. Chạy `release_config.py` (hoặc script, đã tự làm) sau khi sửa manifest |
| `ARTIFACT_PATH_INVALID` | `artifact_path` trong manifest không nằm trong `dist` hoặc sai tên |
| `RUST_TOOLCHAIN_REQUIRED` | Không thấy bộ Rust ở `.tools\rust` và không có `cargo` trên PATH |
| `COMPILED_TRUST_ANCHOR_MISMATCH` | File trust anchor không khớp lõi vừa biên dịch; chạy lại `release_config.py` |
| `HY_MT_MODEL_CHECKSUM_MISMATCH` | File model dịch hỏng hoặc sai phiên bản |
| `WINDOWS_DOTNET_BUILD_TOOLS_REQUIRED` | Thiếu `csc.exe` của .NET Framework 4 |
| `SECRET_SCAN_FAILED` | Có thứ giống khóa riêng, token hoặc cơ sở dữ liệu trong gói. **Đừng phát gói**; báo lại để xử lý |
| Build dừng giữa chừng | Xóa thư mục `dist\staging-*` (chỉ thư mục tạm của lần build đó) rồi chạy lại |

---

## 7. Bản "phát hành cứng" (chưa thiết lập)

Mặc định build **không** ở chế độ cứng: lõi bảo mật giữ đường dự phòng cho phát triển, payload không có chữ ký, và trình build in cảnh báo (`WARNING: ... unsigned`). Chế độ cứng (`AUDIO_RELEASE_HARDENED=1`) yêu cầu thêm:

- **Chứng chỉ ký mã** `AUDIO_SIGNING_CERT` (file `.pfx`) và `AUDIO_SIGNING_PASSWORD`, kèm `signtool` (Windows SDK). Chứng chỉ phải do chính bạn đăng ký; tôi chưa thấy bạn có.
- **Khóa chữ ký payload** `AUDIO_MANIFEST_KEY_FILE`, cùng khóa công khai tương ứng trong trust anchor (`manifest_public_key`). Hiện `release_config.py` **chưa** ghi trường này vào trust anchor, nên đường này chưa dùng được từ đầu đến cuối.

Khi bạn có chứng chỉ, đặt các biến này rồi chạy `build_edition.py`; script sẽ từ chối chạy nếu thiếu biến. Chi tiết kỹ thuật: `SECURITY_PHASE_2_RESULT.md` và `SECURITY_PHASE_3_RESULT.md`.

---

## 8. Điều không được làm

- Không đặt file khóa `.key` trong thư mục repo hoặc gửi cho ai; script từ chối ghi vào trong repo.
- Không sửa tay `dist\release-*.json` hay các file `.exe` đã phát hành.
- Không build khi đang chạy workflow dịch hoặc tạo giọng.

---

## 7. Lỗi đã gặp: `FileNotFoundError WinError 3` khi chép thư viện Python

Nguyên nhân (đã xác nhận 2026-10-07): hai file của `modelscope` có đường dẫn đích dài 262 và 260 ký tự, vượt giới hạn 259 của Windows (máy này `LongPathsEnabled=0`). Tên thư mục staging dài (`staging-audio-translate-basic-1.2.0`) làm vượt ngưỡng. Đã sửa: staging đặt tên ngắn (`s` + 6 ký tự băm) trong `packaging/build_installer.py`. Nếu sau này thêm thư viện có đường dẫn rất dài mà vẫn lỗi `WinError 3`, hãy kiểm tra độ dài đường dẫn trước tiên.

Hai file 4894 MB và 4934 MB build lần đầu **không chạy được** (xem mục 8) và đã bị bỏ. Build lại sau khi tách model ra, 2026-10-07: `AudioTranslate-Basic-1.2.0.exe` (552 MB) và `AudioTranslate-Plus-1.2.0.exe` (592 MB), cả hai đã qua audit. Chưa cài thử, chưa push lease, và model chưa có trên bucket nên chưa tải được.

## 8. Giới hạn 4 GiB của file .exe

Bộ cài bản 1.2.0 đầu tiên (4,9 GB) **không chạy được**: Windows từ chối mọi `.exe` lớn hơn 4 GiB ("This app can't run on your PC"); đã thử với một exe thật được nối thêm dữ liệu. Vì vậy model dịch 4,6 GB không còn nằm trong bộ cài mà tải sau khi kích hoạt (xem `MODEL_DOWNLOAD.md`). Bộ cài vẫn phải kiểm model trên máy build khớp hash ghim sẵn, nhưng không đóng gói file `.gguf`. Mỗi lần build nên xem kích thước file trong `dist`: nếu gần 4 GiB thì có thêm thứ gì đó quá nặng lọt vào.

## 9. Lỗi đã gặp: cài xong nhưng app không mở được (2026-10-07)

Bộ cài báo "installed" nhưng bấm shortcut không thấy gì. Có hai lỗi trong `packaging/launcher.py`, đã sửa và kiểm chứng bằng cách cài thật bản Plus im lặng (`AUDIO_INSTALL_DIR=<thư mục tạm>` và tham số `/Q`):

1. `from paths import ...` lỗi `ModuleNotFoundError`: `python312._pth` của runtime đi kèm tắt mục thư mục-của-script trong `sys.path`. Sửa: launcher tự thêm thư mục của nó vào `sys.path`.
2. Lần khởi động nguội đầu tiên, `/api/license` trả lời chậm hơn 2 giây nên launcher gặp `TimeoutError` (chỉ bắt `URLError`) rồi sập, dù server đã lên. Sửa: timeout dài hơn và bắt cả `OSError`.

Shortcut dùng `pythonw.exe` nên lỗi khởi động trước đây bị nuốt. Giờ launcher ghi lỗi vào `%LOCALAPPDATA%\AudioTranslate\launcher-error.log` và hiện hộp thoại.

**Ghi chú:** đoạn "cài lại thì bộ cài không làm gì" ở bản đầu đã được thay bằng cập nhật đè (mục 10). Máy build cần RAM trống: `build_edition.py` đòi 5 GiB (ngưỡng tôi đặt rộng); đo thực tế khi build, RAM trống giảm khoảng 1 GiB, nên chạy `--force` được nếu còn trên khoảng 3,3 GiB để vẫn chừa 2 GiB cho hệ thống.

## 10. Cài, cập nhật, gỡ và thoát app (2026-10-07)

- **Cài lại cùng phiên bản = cập nhật đè:** bộ cài dừng app đang chạy, xóa sạch thư mục cài cũ (chỉ khi thư mục có `installation.json` do chính bộ cài tạo) rồi giải nén bản mới. Dữ liệu, kích hoạt và kết quả nằm ở `%LOCALAPPDATA%\AudioTranslate`, ngoài thư mục cài nên được giữ.
- **Installed apps:** bộ cài ghi mục gỡ cài đặt theo người dùng (`HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\AudioTranslate-<Edition>-<version>`, không cần quyền admin) và đặt `uninstall.exe` trong thư mục cài (`packaging/uninstaller.cs`). Mỗi phiên bản có một mục riêng.
- **Gỡ:** `uninstall.exe` hỏi xác nhận, dừng app, xóa shortcut (chỉ khi còn trỏ vào thư mục này), xóa mục registry rồi xóa thư mục cài. Nếu không còn bản cài nào khác thì hỏi thêm có xóa dữ liệu (kích hoạt, kết quả, model đã tải) không, mặc định là **không**. `/Q` gỡ im lặng giữ dữ liệu, `/Q /DATA` xóa cả dữ liệu. Từ chối chạy nếu thư mục không có `installation.json`.
- **Thoát app:** nút **Thoát app** trên thanh đầu trang gọi `/api/quit`; launcher (`launcher.py --quit`) dừng mọi tiến trình có file chương trình nằm trong thư mục cài (web server, worker, llama-server). Đang có workflow chạy thì hỏi xác nhận trước. Mỗi lần mở app, launcher cũng dọn tiến trình sót của lần trước, và khóa `launcher.lock` ngăn bấm shortcut hai lần dọn nhầm server đang khởi động.
- **Kiểm chứng:** `packaging/test_install_flow.py` (chạy trong thư mục `packaging`: `..\.venv\Scripts\python.exe -m unittest test_install_flow`) dùng đúng hai stub .NET với edition riêng "Test" 9.9.9: cài, cài lại đè (dừng tiến trình giả, xóa file thừa), gỡ, và từ chối gỡ thư mục lạ; không bao giờ dùng `/DATA`. Đã chạy thêm bằng bộ cài Basic thật đè lên bản đang chạy: tiến trình bị dừng, mục Installed apps xuất hiện, thoát qua API dừng hết tiến trình trong 2 giây, mở lại bình thường.
- **Chưa kiểm chứng:** bấm Gỡ từ trang Installed apps của Windows và hộp thoại hỏi xóa dữ liệu (cần thao tác tay); nút Thoát khi có workflow đang chạy; icon trên file `.exe` và shortcut bằng mắt.

## 11. Lỗi tải YouTube "The page needs to be reloaded" (2026-10-08)

Triệu chứng: workflow dừng ở bước tải với `Không tải được audio YouTube: ERROR: [youtube] <id>: The page needs to be reloaded.`
Nguyên nhân (đã tái hiện bằng runtime của bản cài, cùng máy, cùng video): phiên YouTube đã lưu trong "Kết nối YouTube" (21 cookie) bị YouTube từ chối. **Có cookie thì mọi cách đi (client) đều lỗi; không có cookie thì tải được.** `yt-dlp` 2026.08.19 đã là bản mới nhất, nên không phải do bản cũ.
Sửa (`worker/audio_translate/transcription/pipeline.py`, hàm `download`): thử **không cookie trước**; chỉ khi YouTube đòi đăng nhập ("Sign in to confirm") mới mở phiên đã lưu (hoặc `YTDLP_COOKIES_FILE`) và thử lần hai. Nếu chính phiên đã lưu bị từ chối thì báo rõ: mở Settings → Kết nối YouTube, đăng nhập lại. Test: `tests/test_pipeline.py` (3 test mới) và `tests/test_youtube_session.py`. Đã kiểm bằng cách tải thật một video 19 giây bằng runtime của bản cài trong khi phiên lỗi vẫn còn: tải được và phiên không bị dùng.
Lưu ý: video thật sự cần đăng nhập vẫn cần một phiên YouTube còn tốt; phiên hiện tại của máy thử đã hỏng và cần đăng nhập lại.

## 12. Cửa sổ tiến trình khi chạy file cài (2026-10-08)

Trước đây chạy file exe thì không thấy gì cho tới khi hiện hộp thoại cuối, nên khách không biết nó đang chạy hay treo. Giờ khi chạy không có `/Q`, bộ cài hiện một cửa sổ nhỏ (`packaging/installer.cs`):
- Dòng trạng thái từng bước: dừng app đang chạy, gỡ phiên bản cũ (dữ liệu giữ lại), **giải nén có thanh tiến trình** kèm "Tệp i/n - x MB / y MB", tạo shortcut, đăng ký vào Installed apps, hoàn tất.
- Xong thì hiện nút **Mở ứng dụng** và **Đóng**; lỗi thì hiện thông báo màu đỏ và nút Đóng. Chữ theo ngôn ngữ Windows (tiếng Việt hoặc tiếng Anh).
- `/Q` vẫn cài im lặng, không cửa sổ (dùng cho kiểm thử và cài hàng loạt).
- Hai biến chỉ dùng khi kiểm thử: `AUDIO_INSTALL_LOG=<tệp>` ghi từng bước dạng `phần trăm|chữ|chi tiết`, `AUDIO_INSTALL_NOWAIT=1` tự đóng cửa sổ khi xong.
- Test: `packaging/test_install_flow.py` chạy thật chế độ có cửa sổ (cài mới, cài đè dừng được app giả và xóa file thừa, tiến độ không đi lùi và chạm 95% khi giải nén xong, lỗi thì thoát mã 1 và ghi `FAILED`).
- Chưa kiểm chứng bằng mắt: hình dạng thật của cửa sổ trên màn hình (kiểm bằng nhật ký và test, không có ảnh chụp).
