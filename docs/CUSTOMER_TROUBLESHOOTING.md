# Sổ tay xử lý sự cố AudioTranslate trên máy khách

Cập nhật: **17/11/2026**. Dùng cho nhân viên hỗ trợ và người quản lý sản phẩm.

## Tra cứu nhanh

| Triệu chứng | Nguyên nhân cần kiểm tra | Mục hướng dẫn |
| --- | --- | --- |
| Không mở được app, Windows báo thiếu `WebView2Loader.dll` | Bộ cài bỏ sót DLL đi kèm ứng dụng | [AT-001](#at-001-không-mở-được-app-thiếu-webview2loaderdll) |
| Chép lời hoàn tất, dịch lỗi ngay ở 0%, mã `X900`; log báo không nạp được `llama.dll` | Visual C++ Runtime hoặc DLL phụ thuộc bị thiếu/lỗi | [AT-002](#at-002-dịch-lỗi-ở-0-không-nạp-được-llamadll) |
| Không tìm thấy `data\jobs` | Tác vụ hiện tại thường nằm trong `data\tmp` | [Tìm dữ liệu và log](#tìm-dữ-liệu-và-log) |
| Chỉ có mã `X900`, chưa có log | Mã chung, chưa đủ để kết luận nguyên nhân | [Quy trình chẩn đoán](#quy-trình-chẩn-đoán) |

## Quy trình chẩn đoán

1. Ghi lại phiên bản app, số quy trình, tên tác vụ, thời điểm lỗi và chế độ dịch thường/Genius, CPU/GPU.
2. Mở chi tiết tác vụ để xác định **bước đầu tiên báo lỗi**. Không suy ra vị trí lỗi chỉ từ phần trăm tổng.
3. Giữ nguyên tác vụ, lấy log trước khi thử lại hoặc thay đổi cấu hình.
4. Đọc dòng lỗi mới nhất của `errors.jsonl`, đối chiếu thời gian và bước xử lý. Ưu tiên các trường `error_type`, `detail`, `step`, `error_code`.
5. Nếu chưa rõ, đọc cuối `working\worker.log`; tìm lỗi cuối cùng hoặc `Traceback`. Các dòng `WARNING` không mặc nhiên là nguyên nhân làm tác vụ dừng.
6. Thực hiện cách khắc phục phù hợp, thử lại tác vụ cũ và ghi nhận kết quả.

`X900` là mã cho lỗi chưa được phân loại cụ thể. Không mặc định đó là lỗi nội dung, RAM, model, license hay mạng.

## Tìm dữ liệu và log

Các đường dẫn dưới đây là mặc định. Nếu máy đã cấu hình `AUDIO_DATA_DIR`, dữ liệu có thể nằm ở vị trí khác. Thực hiện trên đúng tài khoản Windows đang chạy app.

Nhấn **Win + R**, dán:

```text
%LOCALAPPDATA%\AudioTranslate\data\tmp
```

Mỗi tác vụ có một thư mục ID. Mở `job.json` để đối chiếu tên video/số quy trình; số quy trình hiển thị không nhất thiết là tên thư mục.

| Vị trí dưới thư mục data | Mục đích |
| --- | --- |
| `tmp\<ID>` | Thư mục xử lý tác vụ hiện tại |
| `jobs\<ID>` | Vị trí tương thích cho tác vụ cũ |
| `tool-tmp\<ID>` | Tác vụ công cụ riêng |
| `results` | Kết quả đã công bố; không thay thế toàn bộ log xử lý |

Trong thư mục tác vụ, ưu tiên lấy:

```text
errors.jsonl
working\worker.log
```

Chỉ lấy bổ sung khi cần:

```text
job.json
working\adapters.json
working\transcription-progress.json
working\translation-runtime.json
transcript.zh.jsonl
```

Nếu chưa tìm được thư mục, mở PowerShell và chạy lệnh chỉ đọc sau:

```powershell
Get-ChildItem -LiteralPath "$env:LOCALAPPDATA\AudioTranslate\data" `
  -Filter errors.jsonl -Recurse -File -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 10 FullName, LastWriteTime
```

Đọc cuối log, thay `ID_TAC_VU` bằng ID vừa tìm:

```powershell
$jobFolder = Join-Path $env:LOCALAPPDATA 'AudioTranslate\data\tmp\ID_TAC_VU'
Get-Content -LiteralPath "$jobFolder\errors.jsonl" -Tail 3
Get-Content -LiteralPath "$jobFolder\working\worker.log" -Tail 150
```

Lượt đầu chỉ cần hai phần log trên. Khi chia sẻ, kiểm tra và che token, khóa, thông tin riêng nếu có; không gửi thư mục license hoặc toàn bộ database nếu chưa cần.

## AT-001: Không mở được app, thiếu WebView2Loader.dll

**Trạng thái:** đã xác định lỗi đóng gói; đã bổ sung DLL vào quy trình build bản Plus **3.2.7**. Không đồng nhất lỗi này với việc thiếu toàn bộ WebView2 Runtime.

### Dấu hiệu

Windows hiển thị ngay khi mở app:

```text
AudioTranslate.exe - System Error
The code execution cannot proceed because WebView2Loader.dll was not found.
```

### Nguyên nhân đã xác định

`AudioTranslate.exe` bản build Windows GNU phụ thuộc `WebView2Loader.dll`. DLL có trong thư mục build nhưng script cũ chỉ sao chép EXE sang gói cài, bỏ sót DLL đi kèm.

### Cách xử lý

1. Đóng app.
2. Cài bản có bản sửa đóng gói, từ Plus 3.2.7 được tạo trong lần xử lý này, hoặc bản mới hơn có giữ bản sửa.
3. Kiểm tra `WebView2Loader.dll` nằm **cùng thư mục** với `AudioTranslate.exe`:

   ```text
   %LOCALAPPDATA%\Programs\AudioTranslate\Plus
   ```

4. Mở lại app, xác nhận không còn hộp thoại thiếu DLL.

Nếu hỗ trợ bằng cách bổ sung DLL thủ công, dùng đúng DLL x64 từ bản build tương ứng; không lấy DLL từ nguồn không rõ xuất xứ. Cài lại bằng bộ cài cũ thiếu DLL không giải quyết được nguyên nhân.

### Phòng ngừa trong sản phẩm

- Giữ bước sao chép loader từ thư mục build sang gói cài.
- Kiểm tra chạy app trên máy Windows sạch, không chỉ máy phát triển.

## AT-002: Dịch lỗi ở 0%, không nạp được llama.dll

**Trạng thái:** khách xác nhận đã khắc phục sau hướng dẫn cài/Repair **Microsoft Visual C++ Runtime x64** vào ngày **17/11/2026**. Chưa có bằng chứng xác định riêng DLL phụ thuộc nào bị thiếu trên máy đó.

### Dấu hiệu

- Chép lời hoàn tất cả 4 bước, đã có 2 tệp kết quả.
- Dịch thuật lỗi ở **0%**, thường chỉ sau khoảng 1 giây.
- Giao diện hiện `X900`; thử lại nhiều lần vẫn lỗi giống nhau.
- `errors.jsonl` ghi `step: TRANSLATION`, `error_type: RuntimeError`, với chi tiết:

  ```text
  Failed to load shared library '...\llama_cpp\lib\llama.dll':
  Could not find module '...\llama.dll' (or one of its dependencies).
  ```

### Kết luận từ log

Windows không nạp được thư viện native của bộ dịch. Thông báo có thể do một **DLL phụ thuộc** bị thiếu, không có nghĩa riêng file `llama.dll` đã mất. Trong code loader được kiểm tra, nhánh `Failed to load shared library` chạy sau khi thấy file thư viện tồn tại.

Đối chiếu bộ thư viện trên máy build cho thấy các phụ thuộc gồm:

```text
ggml.dll
ggml-base.dll
ggml-cpu.dll
MSVCP140.dll
VCRUNTIME140.dll
VCRUNTIME140_1.dll
VCOMP140.dll
```

Không cần nhận dạng lại video để sửa lỗi thư viện. Các cảnh báo `jieba` dạng `SyntaxWarning: invalid escape sequence` trong ca này không phải lỗi làm quy trình dừng.

### Cách xử lý đã thành công

Thực hiện **trên máy khách bị lỗi**:

1. Đóng hoàn toàn AudioTranslate.
2. Tải [Microsoft Visual C++ Runtime x64 chính thức](https://aka.ms/vc14/vc_redist.x64.exe).
3. Mở `vc_redist.x64.exe` trong thư mục Downloads/Tải xuống.
4. Nếu có **Install**, đồng ý điều khoản rồi bấm Install. Nếu có **Repair**, bấm Repair.
5. Chọn **Yes/Có** khi Windows yêu cầu cho phép thay đổi thiết bị.
6. Đợi hoàn tất, chọn Close. Khởi động lại máy nếu bộ cài yêu cầu.
7. Mở AudioTranslate, bấm **Thử lại** tác vụ cũ.
8. Xác nhận bước dịch vượt 0% và log không còn lỗi nạp `llama.dll`. Theo dõi tiếp đến khi tác vụ hoàn tất để xác nhận toàn bộ quy trình.

Nguồn tải và thông tin runtime: [Microsoft — Latest supported Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist/).

### Nếu vẫn lỗi sau khi cài/Repair

1. Kiểm tra các DLL sau trong thư mục:

   ```text
   %LOCALAPPDATA%\Programs\AudioTranslate\Plus\runtime\python\Lib\site-packages\llama_cpp\lib
   ```

   ```text
   llama.dll
   ggml.dll
   ggml-base.dll
   ggml-cpu.dll
   ```

2. Nếu thiếu file, đối chiếu gói cài và lịch sử cách ly của phần mềm bảo vệ; khôi phục/cài lại từ bộ cài đã xác minh. Không tắt bảo vệ máy một cách mặc định.
3. Nếu đủ file, kiểm tra chuỗi phụ thuộc DLL trên máy khách, phiên bản/kiến trúc runtime và đường dẫn tìm DLL. Không chép riêng `llama.dll` từ phiên bản khác vì các thư viện `ggml` phải tương thích.
4. Lấy log mới sau lần thử lại để xác định lỗi còn giống hay đã chuyển sang lỗi khác.

### Phòng ngừa trong sản phẩm — đề xuất, chưa triển khai trong ca này

- Bộ cài kiểm tra runtime cần thiết và hướng dẫn/cài bổ sung khi thiếu.
- Kiểm tra nạp thư viện trên Windows sạch để tránh phụ thuộc vô tình vào máy build.
- Ánh xạ lỗi nạp DLL sang thông báo dễ hiểu thay cho `X900`.

## Những kết luận cần tránh

- Không kết luận lỗi ghép chép lời khi ảnh chi tiết xác nhận chép lời 4/4 hoàn tất và bước dịch mới là bước lỗi.
- Không khẳng định lỗi vault/license khi chưa có log tương ứng. Ca AT-002 đã xác nhận là lỗi nạp thư viện.
- File `.md` là bản đọc cho người dùng; quy trình dịch tự động đọc `transcript.zh.jsonl`. File Markdown hợp lệ không chứng minh JSONL đầu vào cũng hợp lệ.
- Khi đối chiếu file, đảm bảo đúng tác vụ: file mang số `000004` không tự động là đầu vào của tác vụ `000003`.
- Lỗi nhận dạng tên/thuật ngữ có thể làm giảm chất lượng bản dịch nhưng chưa đủ để giải thích lỗi nạp DLL.

## Mẫu ghi nhận ca mới

Sao chép mẫu dưới đây khi gặp sự cố mới. Chỉ đánh dấu “đã xác nhận” sau khi có bằng chứng hoặc khách xác nhận kết quả.

```text
Mã ca: AT-xxx
Ngày:
Phiên bản app / Windows:
Số quy trình hoặc ID tác vụ:
Chế độ dịch / CPU-GPU:
Triệu chứng và bước đầu tiên lỗi:
error_type / error_code / detail:
Nguyên nhân: [đã xác nhận / giả thuyết]
Các bước đã thực hiện:
Kết quả sau khắc phục:
Dữ liệu và checkpoint có được giữ lại:
Đề xuất phòng ngừa / trạng thái triển khai:
```
