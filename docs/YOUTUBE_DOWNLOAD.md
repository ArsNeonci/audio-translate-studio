# Tải audio YouTube: các lỗi, nạp file thay thế, và đánh giá tải qua máy chủ

> **Cập nhật 2026-10-11:** kênh cập nhật yt-dlp nằm trên VPS (`MODEL_DIR/youtube/`), không còn ở bucket. Phát hành: `packaging/publish_youtube_update.py --ssh ubuntu@15.235.207.5 --key %USERPROFILE%\.ssh\ovh_audio`. Chỗ nào bên dưới nói `--bucket`/`gcloud` là cách cũ. Xem `MIGRATION_GCP_TO_VPS.md`.

Trạng thái: 2026-10-09. yt-dlp 2026.08.19 (bản mới nhất trên PyPI lúc viết, cùng bản trong app đã cài). Mục 4 đến 6 mô tả phần đã làm cùng ngày.

## 1. Các dạng lỗi đã gặp hoặc có thể gặp

| Lỗi yt-dlp báo | Nguyên nhân thường gặp | App hiện xử lý |
|---|---|---|
| `Sign in to confirm you're not a bot` | YouTube nghi IP/phiên là bot. Gần như luôn xảy ra với IP trung tâm dữ liệu. | Thử lại với phiên Edge đã kết nối hoặc `YTDLP_COOKIES_FILE`; báo "Kết nối YouTube". |
| `The page needs to be reloaded` | Cookie đã lưu bị YouTube xoay vòng hoặc từ chối. | Chỉ dùng cookie khi bị đòi đăng nhập; báo "đăng nhập lại". |
| `Requested format is not available` | Client (web_safari, ios...) cần PO token nên không trả luồng audio. | Không thử client khác. Báo lỗi chung. |
| `HTTP Error 429` | Quá nhiều lượt từ một IP. | Báo chờ hoặc đổi mạng. |
| `Video unavailable`, `Private video`, giới hạn tuổi, chặn theo vùng, buổi phát trực tiếp | Bản thân video. | Báo lỗi chung kèm chi tiết. |
| JS challenge (`n` / signature) không giải được | Thiếu Node, thiếu `yt-dlp-ejs`, hoặc yt-dlp quá cũ so với player mới. | App gói Node. ejs và yt-dlp mới đến qua kênh cập nhật (mục 5). |
| Mạng đứt giữa chừng | Mạng khách. | yt-dlp tự thử lại 10 lần và tải tiếp được. |

Kết quả đo thật với cùng video `8qH7C3NvAQE`:

| Nơi chạy, thời điểm | Ẩn danh, client mặc định | Ẩn danh, mweb | Ẩn danh, tv / ios / android_vr / web_safari | Cookie, mặc định | Cookie, mweb / tv |
|---|---|---|---|---|---|
| Máy khách, sáng 2026-10-09 | đòi đăng nhập | không có định dạng | lỗi | "page needs to be reloaded" | lỗi |
| Máy khách, chiều 2026-10-09 | đòi đăng nhập | **được** | lỗi | **được** | **được** |
| VM GCP (34.97.47.166), chiều 2026-10-09, có Deno | đòi đăng nhập | đòi đăng nhập | đòi đăng nhập | không thử (không có cookie) | không thử |

Trên VM còn thử thêm video `1JzKgwOESoM`: cả 12 lần (2 video, 6 client) đều bị đòi đăng nhập. Thư mục thử đã xóa.

Nhận xét: trên máy khách, kết quả thay đổi theo giờ. Không có một cấu hình nào luôn đúng, nhưng thường có ít nhất một client còn chạy.

## 2. Nạp file audio tiếng Trung vào workflow chính (đã làm)

Trang Studio có thêm lựa chọn nguồn: **Link YouTube** hoặc **Tệp âm thanh tiếng Trung**, giống Tool 1.
- Định dạng nhận: WAV, MP3, M4A, FLAC, OGG, AAC, WEBM, MP4, tối đa 2 GB. Worker kiểm tra bằng ffprobe như Tool 1 (có luồng âm thanh, đuôi khớp nội dung, thời lượng hợp lệ).
- File được đặt làm kết quả bước Tải (`source/audio.<đuôi>`), nên bước Tải hoàn tất ngay và không gọi YouTube. Các bước sau chạy như workflow từ link.
- Job có cờ `source_upload`. Chạy lại từ bước Tải không xóa file này, vì đó là bản duy nhất. Nếu file mất, bước Tải báo cần tạo workflow mới.
- API: `POST /api/jobs?name=<tên file>&voice=&style=&mode=&address=&auto=1&queue_only=1`, thân là nội dung file. Gửi JSON thì vẫn là đường link cũ.
- Test: `worker/tests/test_management.py` (test 34), `worker/tests/test_workflow_admission.py`, `scripts/check-workflow-upload.cjs` (`npm run check:upload`).

## 3. Đánh giá phương án "dịch vụ tải chạy trên máy chủ GCP"

Kết luận: không nên tải YouTube từ máy chủ GCP hiện tại.
- IP của VM bị chặn ngay từ đầu: 12/12 lượt đòi đăng nhập, kể cả khi đã có bộ giải JS. Mục tiêu 95% không đạt được trên IP này.
- Muốn qua được phải thêm cookie tài khoản hoặc proxy dân cư. Một tài khoản dùng chung cho mọi khách dễ bị khóa, và khi bị khóa thì toàn bộ khách cùng hỏng một lúc. Proxy dân cư tốn phí theo GB.
- Khi máy chủ tải và phát lại nội dung YouTube, bên vận hành máy chủ là người tải và phân phối. Trách nhiệm theo điều khoản YouTube và bản quyền chuyển sang bên bạn.
- Phí băng thông ra internet của GCP tính cho mỗi file gửi về khách (chưa tra giá hiện tại). VM có 4 GB RAM; một trình duyệt headless cho mỗi lượt tải chiếm khá nhiều.

Lợi ích thật của phương án là **cập nhật mà không bắt khách cài lại app**. Lợi ích đó đạt được mà không cần máy chủ tải hộ:

1. **Kênh cập nhật yt-dlp qua gateway** (đề xuất chính). App hỏi gateway phiên bản yt-dlp mới, tải gói từ bucket bằng link ký như model, kiểm chữ ký bằng khóa công khai ghim trong app, rồi dùng bản này thay bản gói kèm. Việc tải vẫn chạy từ IP nhà khách, là loại IP ít bị chặn nhất.
2. **Thứ tự client do gateway cấp.** Gateway trả một cấu hình nhỏ có chữ ký, ví dụ: thử mặc định, rồi mweb, rồi cookie với mặc định, mweb, tv. Khi YouTube đổi, chỉ sửa cấu hình trên gateway. Số liệu ở mục 1 cho thấy chuỗi này sẽ qua được lần đo chiều nay.
3. **Nạp file** (mục 2) là đường dự phòng khi mọi cách trên đều hỏng.
4. Bộ tạo PO token: chỉ cân nhắc sau cùng, xem các rủi ro đã ghi trước đó.

Mục 1 và 2 đã làm ngày 2026-10-09, xem mục 4 và 5.

## 4. Thứ tự thử client (đã làm)

`worker/audio_translate/transcription/pipeline.py` (`download`, `try_attempts`, `refused`) thử lần lượt cho tới khi có luồng audio:
1. Client mặc định, ẩn danh.
2. mweb, ẩn danh.
3. Client mặc định, dùng phiên Edge đã kết nối (hoặc `YTDLP_COOKIES_FILE`).
4. mweb, có cookie.
5. tv, có cookie.

- Cookie chỉ được đọc khi tới bước cần nó. Không có phiên đã lưu thì bỏ qua các bước có cookie.
- Dừng ngay, không thử tiếp, khi gặp lỗi mà client khác không cứu được: HTTP 429, video riêng tư, đã bị gỡ, chỉ dành cho hội viên, chưa tới giờ phát, bản quyền.
- Giữa hai lần thử, file `.part` dở dang của lần trước bị xóa, để không nối nhầm sang định dạng khác.
- Mọi lần thử được ghi vào `working/download-attempts.json` của job: client, có cookie hay không, đoạn cuối lỗi. Không ghi giá trị cookie.
- Thứ tự này lấy từ manifest đã ký (mục 5) nếu có, nên đổi được mà không build lại.
- Hỏng hết thì app hỏi gateway ngay xem có bản mới không (tối đa 15 phút một lần). Có bản mới thì lỗi báo thêm "Đã nhận bản cập nhật bộ tải YouTube; bấm Thử lại."

## 5. Kênh cập nhật yt-dlp có chữ ký (đã làm)

**Luồng:** app gọi gateway `POST /v1/youtube/update` (cần license hợp lệ, tối đa 48 lần mỗi ngày mỗi license). Gateway đọc `youtube/manifest.json` và `youtube/manifest.sig` trong bucket `audio-translate-models-8386`, giữ trong bộ nhớ 5 phút, rồi trả nguyên văn cùng link ký 1 giờ tới các file wheel. App (`worker/audio_translate/transcription/ytdlp_update.py`):
- Chỉ nhận manifest có chữ ký Ed25519 khớp một khóa công khai trong `worker/config/youtube-update-keys.json`.
- Từ chối manifest có số `serial` nhỏ hơn bản đang dùng, nên không ai phát lại được bản cũ để kéo lùi.
- Chỉ cài gói `yt-dlp` và `yt-dlp-ejs`. Mỗi wheel phải đúng kích thước và SHA-256 ghi trong manifest. Wheel có đường dẫn thoát ra ngoài thư mục bị từ chối.
- Cài vào `%LOCALAPPDATA%\AudioTranslate\data\ytdlp\releases\<serial>\`. Thư mục chỉ xuất hiện khi đủ. Giữ bản trước đó, xóa các bản cũ hơn.
- Trước mỗi lần tải YouTube, bản đã cài được đặt lên đầu `sys.path`. Chưa có bản nào thì dùng bản đi kèm app.
- Kiểm tra mỗi `check_hours` giờ (mặc định 6). Lần kiểm tra lỗi thì thử lại sau 1 giờ. Lỗi không bao giờ chặn việc tải.
- Settings → Kết nối YouTube hiện dòng "Bộ tải YouTube: yt-dlp x (bản cập nhật từ máy chủ / bản đi kèm app)" và lúc kiểm tra gần nhất. Nút **Kiểm tra** cũng hỏi gateway ngay.

**Khóa ký:** `C:\Users\Linh\.audio-translate\youtube-update-signing.pem`, tạo ngày 2026-10-09. Khóa không nằm trong repo và không lên gateway. Gateway bị chiếm cũng không làm app chạy mã lạ được. **Hãy sao lưu file này.** Mất khóa thì phải tạo khóa mới (`--init-key`) và build lại app để app tin khóa mới.

**Phát hành bản mới** (chạy trên máy có khóa và `gcloud`):

```
cd C:\Workspace\Audio-translate\audio-translates
.venv\Scripts\python.exe packaging\publish_youtube_update.py --bucket audio-translate-models-8386 --dry-run
.venv\Scripts\python.exe packaging\publish_youtube_update.py --bucket audio-translate-models-8386
```

- Mặc định lấy yt-dlp mới nhất trên PyPI, kèm đúng phiên bản `yt-dlp-ejs` mà nó ghim. Script kiểm SHA-256 của PyPI, thử import cả hai bằng Python 3.12, tải lên `youtube/` (không ghi đè), so kích thước, rồi ký và tải lên manifest.
- Chọn phiên bản: `--yt-dlp 2026.8.19`. Quay lui: phát hành lại với phiên bản cũ (serial mới vẫn lớn hơn nên app nhận).
- Chỉ đổi thứ tự client: `--attempts "[{\"client\": \"tv\", \"cookies\": true}, ...]"`. Không truyền thì giữ thứ tự đang phát hành.

**Đã phát hành** 2026-10-09: yt-dlp 2026.8.19 + yt-dlp-ejs 0.8.0, serial 1791505617, thứ tự như mục 4.

**Đã kiểm chứng:**
- Gateway thật trên VM đọc được manifest và ký được link. Worker mới chạy bằng Python của app đã cài: nhận câu trả lời đó, kiểm chữ ký và SHA-256, cài, rồi import yt-dlp và ejs từ bản phát hành.
- Cùng video, Python của app bản 08/10 (thiếu ejs) có cookie vẫn lỗi "Requested format is not available". Thêm bản từ gateway thì có cookie lấy được 11 định dạng.
- Test: `worker/tests/test_ytdlp_update.py` (chữ ký giả, manifest bị sửa, wheel sai hash, chống quay lui, giãn lịch, wheel độc hại), `worker/tests/test_pipeline.py`, `billing-gateway/test_lease_gateway.py`.
- Chưa kiểm chứng: lời gọi có license thật từ app, vì máy thử chưa kích hoạt license.

## 6. Lỗi đóng gói đã sửa: thiếu bộ giải JS

`packaging/build_installer.py` đánh giá lại điều kiện `extra == 'default'` của gói con mà không có extra. Vì thế mọi phụ thuộc của `yt-dlp[default]` đều bị bỏ: `yt-dlp-ejs`, certifi, mutagen, pycryptodomex, brotli, requests. App bản 08/10 trở về trước báo "n challenge solving failed" rồi "Requested format is not available", dù máy dev (có ejs) tải được. Đã sửa: bỏ điều kiện sau khi đã đánh giá với extra của gói cha. Bước kiểm tra cuối build giờ import cả `yt_dlp_ejs, certifi, mutagen, Cryptodome, brotli`. App cũ cũng nhận được ejs qua kênh cập nhật, nhưng chỉ khi đã có mã cập nhật, tức từ bản build này trở đi.

Build lại 2026-10-09 (bản 1.2.0, cài đè được): Basic 582 MB, Plus 624 MB, nhiều hơn khoảng 460 tệp so với bản 08/10 (các gói phụ thuộc trước đây bị rơi). Cả hai đã kiểm có `ytdlp_update.py`, `youtube-update-keys.json`, `yt_dlp_ejs`, `certifi`. Bản 08/10 được dời sang `dist/previous-1.2.0-20261008/`, không xóa.

## 7. Tab trống và trình duyệt YouTube chạy ngầm tốn RAM (điều tra và sửa 2026-10-09)

Hiện tượng: mỗi lần yêu cầu đăng nhập thì cửa sổ Edge của app có thêm tab `about:blank`, và đóng app xong vẫn còn Edge chạy ngầm.

**Nguyên nhân (đã kiểm chứng)**
1. **Cờ `--restore-last-session` ở cả hai kiểu mở** (`launch()` trong `youtube_session.py`). Mỗi lần mở lại phiên cũ rồi cộng thêm một tab mới. Thí nghiệm trên hồ sơ tạm, mở ẩn 4 lần: có cờ thì số tab là 1, 2, 2, 2; không có cờ thì 1, 1, 1, 1.
2. **Edge ẩn bị bỏ rơi khi Python bị giết.** Luồng đóng bình thường sạch (đo: 0 tiến trình còn lại). Nhưng giết tiến trình Python giữa chừng thì 16 tiến trình Edge ở lại (đo trên hồ sơ tạm). Có hai chỗ giết: hạn 60 giây của máy chủ web cho lệnh YouTube, và người dùng bấm Dừng hoặc Hủy lúc đang tải.
3. **Không ai dọn.** `app_processes()` trong `packaging/launcher.py` chỉ gom tiến trình có file chạy nằm trong thư mục cài app, nên không thấy Edge ở Program Files.
4. **Edge bỏ rơi bị dùng lại mà không ai đóng** (`owned=None` trong `cookies_for_download()`).

Đo trên máy bạn lúc 08:08: một Edge ẩn bị bỏ rơi, 9 tiến trình, khoảng 526 MB, một tab trống. Chưa chứng minh được nó bị bỏ rơi theo cách nào trong hai cách ở mục 2.

**Đã sửa** (`browser_cleanup.py` mới, `youtube_session.py`, `launcher.py`, trang Cài đặt)
1. Bỏ `--restore-last-session` ở cả hai kiểu mở. Cookie đăng nhập đều là cookie lâu dài (30 cookie, 0 cookie phiên), và test Edge thật xác nhận cookie sống qua một lần đóng và mở lại.
2. Edge ẩn được tạo ở trạng thái treo, đưa vào Windows Job Object có cờ `KILL_ON_JOB_CLOSE`, rồi mới chạy. Tiến trình Python chết vì bất cứ lý do gì thì cả cây Edge chết theo. Test thật: giết Python rồi kiểm tra không còn tiến trình nào của hồ sơ.
3. Dọn theo dấu nhận dạng chính xác: chỉ tiến trình có `--user-data-dir` đúng bằng hồ sơ của app, và chỉ khi tiến trình chính có `--headless`. Cửa sổ đăng nhập thường và Edge của người dùng không bị đụng. Gọi trong `stop_app()` của launcher (lúc app khởi động và lúc Thoát) và đầu mỗi `cookies_for_download()`.
4. Gặp Edge ẩn không do lần gọi này mở thì đóng nhẹ nhàng (để nó lưu hồ sơ), rồi dọn nốt phần còn lại và mở mới. Edge ẩn của lần gọi luôn được đóng ở `finally`, kể cả khi có lỗi.
5. `refresh_page` dùng lại tab trống sẵn có rồi trả về `about:blank`, đóng mọi tab thừa. Edge ẩn chạy với `--disable-extensions`.
6. Nút "Đóng trình duyệt YouTube" trong Cài đặt: đóng Edge ẩn, và gửi yêu cầu đóng (không kill) cho cửa sổ đăng nhập để Edge kịp lưu phiên. Nút chỉ bấm được khi có trình duyệt đang chạy, kèm dòng báo "đang chạy ngầm và chiếm bộ nhớ".

**Test:** `worker/tests/test_browser_cleanup.py` (nhận dạng tiến trình, cờ mở trình duyệt, dọn bản bỏ rơi, nút đóng, cùng 3 test Edge thật), `worker/tests/test_youtube_browser.py` (opt-in, cookie giả qua lần đóng và mở lại).

**Chưa kiểm chứng:** mức RAM giảm của `--disable-extensions`; hành vi với cookie phiên của một tài khoản đăng nhập mới; việc launcher bản đã cài nạp được `browser_cleanup` (có `try/except`, lỗi nạp thì bỏ qua chứ không chặn việc khởi động).

## 8. Chốt chặn build: gói bị rơi

`python_runtime()` trong `packaging/build_installer.py` giờ có `REQUIRED_PACKAGES` (yt-dlp, yt-dlp-ejs, certifi, mutagen, pycryptodomex, requests, urllib3, websockets, brotli, psutil, cryptography). Thiếu một gói thì build dừng với `DEPENDENCY_DROPPED: <tên>`. Đã thử: bước dò phụ thuộc thấy 83 gói và đủ các gói trên, và khi thêm một tên giả thì build dừng đúng.

## 9. "Không mở được hồ sơ YouTube" trên bản 09/10 lúc 08:47: nguyên nhân thật là `__COMPAT_LAYER` (2026-10-09)

**Hiện tượng:** bấm "Kiểm tra kết nối" trong Cài đặt thì báo "Không mở được hồ sơ YouTube. Đóng cửa sổ hồ sơ riêng rồi thử lại; kiểm tra chính sách trình duyệt."

**Nguyên nhân (đã kiểm chứng):**
- Mọi tiến trình của app (Node, lõi bảo mật, worker Python) chạy với biến `__COMPAT_LAYER=DetectorsAppHealth`. Windows gắn biến này, và các tiến trình con thừa hưởng nó.
- Edge thấy biến này thì tự khởi động lại một bản mới (dòng lệnh có thêm `--edge-skip-compat-layer-relaunch`), còn tiến trình đầu thoát ngay.
- `launch()` thấy tiến trình đầu đã thoát thì kết luận Edge chết và báo lỗi sau khoảng 0,4 giây. Đặt biến này khi mở trên hồ sơ tạm: 3/3 lần lỗi; không có biến: lần nào cũng được.
- Bản cũ cũng dính lỗi này. Edge khởi động lại bị bỏ rơi, và lần gọi sau dùng lại nó nên trông như thành công ở lần thứ hai. Đây cũng là nguồn của Edge ẩn khoảng 526 MB ghi ở mục 7: lệnh của nó có đúng cờ `--edge-skip-compat-layer-relaunch`, và tiến trình cha (tiến trình đầu của Edge) đã chết.
- Bản 09/10 lúc 08:47 dọn sạch Edge bỏ rơi, nên không còn bản nào để dùng lại, và lần nào cũng lỗi.
- Workflow tải YouTube vẫn có lúc được, vì việc Edge khởi động lại có thể kịp ghi cổng điều khiển trước khi app kiểm tra.

**Đã sửa:**
1. `browser_cleanup.browser_env()`: môi trường truyền cho Edge (cả kiểu ẩn lẫn cửa sổ đăng nhập) không có `__COMPAT_LAYER`, nên Edge không khởi động lại.
2. `launch()` chỉ coi là lỗi khi tiến trình đầu đã thoát **và** không còn tiến trình Edge ẩn nào của hồ sơ. Edge khởi động lại vì lý do khác vẫn được nhận.

**Đã kiểm chứng:**
- Có biến và đã sửa: 3/3 lần mở được, Edge không khởi động lại.
- Cố tình giữ biến: 3/3 lần mở được nhờ chốt thứ hai, Edge có khởi động lại.
- Sau khi đóng không còn tiến trình nào.
- Trọn luồng "Kiểm tra kết nối" bằng mã mới, gọi qua Node có biến này, trên hồ sơ thật: 2/2 lần ra `SESSION_SAVED`.
- Test: `CompatLayerTests` và `test_launch_works_when_the_app_runs_under_the_compat_layer` trong `worker/tests/test_browser_cleanup.py`.

**Lưu ý khi tái hiện:** Python của app đã cài có tệp `python312._pth` khóa đường dẫn nạp. Chạy `worker/youtube_session.py` của repo bằng Python đó vẫn nạp mã cũ đã cài. Phải dùng Python dev hoặc chèn đường dẫn trong script.

## 10. Audio gốc là kết quả của bước Tải xuống (2026-10-09)

- Audio tiếng Trung mà workflow dùng (tải từ YouTube hoặc nạp từ file) được xuất thành kết quả `SOURCE_AUDIO` của bước Tải xuống: `download/<số workflow>-source-audio.<đuôi>`, đuôi đúng như tệp (yt-dlp thường cho `webm` hoặc `m4a`).
- Trang Lịch sử có mục "Tải xuống" với trình phát và nút tải, giống thẻ giọng đọc. Thẻ trong Studio cũng có "Audio gốc tiếng Trung".
- `job.json` ghi `source_ext` khi bước Tải xong, hoặc ngay khi nạp file. Job cũ được bổ sung một lần trong `import_existing()` nếu bước Tải đã xong và tệp còn.
- Công cụ đơn không có bước Tải (Tool 1 từ file) thì không xuất mục này.
- Đổi lại, mỗi job giữ thêm một bản sao audio trong thư mục kết quả. Bản gốc trong thư mục làm việc vẫn còn để các bước sau dùng.

**Sửa lỗi mục 10 (cùng ngày, sau khi bản Basic 09:50 báo trình phát 0:00 và lịch sử không có mục Tải xuống):**
- Nguyên nhân: tệp audio đã được xuất ra đúng (`download/<số>-source-audio.webm`, mở được bằng ffprobe) và thẻ trong Studio hiện "SẴN SÀNG" vì đọc thẳng `outputs.json`. Nhưng `history()` trong `manage.py` lọc kết quả theo `results.output_files(job)`, và `job` là hồ sơ công khai trong thư mục kết quả. Hồ sơ này chỉ giữ danh sách trường cố định, không có `source_ext`, nên mục Tải xuống bị loại. Hệ quả: trang Lịch sử không có mục nào, còn `/artifacts/source` và `/files/SOURCE_AUDIO` trả 404 "Output chưa sẵn sàng", nên trình phát chết (0:00 / 0:00).
- Sửa: `source_ext` được thêm vào hồ sơ công khai (`results.metadata`) và vào các trường phủ từ hồ sơ làm việc trong `history()`. `output_files()` cũng chịu được `tool_steps` rỗng của hồ sơ công khai.
- Trình phát mới dùng chung `components/common/audio-player.tsx`: nếu tệp không phát được thì hiện thông báo thay vì trình phát chết. Nút tải đổi thành "Tải xuống audio" / "Download audio".
- Kiểm chứng trên dữ liệu thật ở localhost: job 5, 7, 8, 9 giờ đều có audio gốc trong danh sách; tải về trả 200, `audio/webm`, đúng tên tệp. Chụp trang chi tiết ở 4 tổ hợp sáng/tối và Việt/Anh đều đúng. Phát trực tiếp trên máy dev trả 403 và hiện "Cần giấy phép đang hoạt động để phát Audio", giống thẻ giọng đọc; chưa thử phát trên app có bản quyền.
- Test hồi quy: `test_34b_the_source_audio_appears_in_history...` trong `worker/tests/test_management.py`.
