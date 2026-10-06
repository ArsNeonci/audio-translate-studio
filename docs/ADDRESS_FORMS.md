# Xưng hô, giới tính và thuật ngữ theo thể loại

Mục tiêu: cách gọi nhân vật trong bản tiếng Việt đúng giới tính, thể hiện được quan hệ (thân/sơ, yêu/ghét) và dùng từ đúng thể loại, như các kênh mẫu. Mã: `moderation/address.py`, `moderation/flow.py`, `translation/lexicon.py`, `translation/hymt_translation.py`. Test: `test_address.py`, `test_styled_translation.py`.

**Phạm vi:** chỉ job tạo với Kiểu giọng (có `selected_address_profile` trong `job.json`). Job cũ giữ nguyên hành vi, checkpoint và cache.

## Nguyên nhân gốc (đã đo, 2026-10-04)

- ASR ghi 他 và 她 theo phỏng đoán vì cả hai đều đọc là "tā". Workflow 000009 có 72 dòng 他 so với 21 dòng 她 dù nhân vật chính hầu hết là nữ. ASR cũng ghi 她 quanh nhân vật nam (宋轩, 李强). Vì vậy 他/她 không đáng tin để suy ra giới tính.
- Translation dịch từng câu hoặc từng nhóm câu, không có ngữ cảnh. Model chọn cách gọi trung tính ("bạn", "anh ấy/cô ấy").
- Model 1.8B thỉnh thoảng tự thêm chủ ngữ sai giới tính (dòng 979 của 000008: 6/6 lần thử, kể cả đổi seed).
- Hy-MT2-1.8B làm theo mẫu Personalization chỉ một phần. Thử các mẫu Style và Background trên model thật (2026-10-05) không cải thiện rõ nên **không áp dụng**.

## Các lớp (theo thứ tự chạy)

| Lớp | Giai đoạn | Nội dung |
|---|---|---|
| **L1. Bảng nhân vật** | đầu Translation | `working/characters.json`, soạn tự động, sửa được ở trang Reprocess |
| **Sửa giới tính tiếng Trung** | Translation | Sửa 他/她 trong câu gửi cho model; `text_zh` lưu lại vẫn là bản ASR gốc |
| **Từ điển thuật ngữ** | Translation | Cụm tiếng Trung đã biết dịch sai, đưa vào mẫu thuật ngữ chính thức của Hy-MT2 |
| **Kiểm tra giới tính khi dịch** | Translation | Dịch lại khi đại từ mâu thuẫn, rồi chốt theo đại từ tiếng Trung |
| **L0. Profile xưng hô + L2 sửa đại từ** | đầu Moderation | Cách gọi theo vai trò × giới tính × vai vế (`worker/config/address-profiles.json`) |
| **Làm sạch dòng chảy câu** | Moderation | Hạ chữ hoa đầu mảnh khi mảnh trước chưa kết thúc câu |

Chọn Kiểu giọng thì profile cùng thể loại và từ điển tương ứng tự được chọn. Người dùng đổi riêng Xưng hô được.

## L1. Bảng nhân vật

- **Tên người:** lấy từ `name-glossary.json`. Tên ngắn nằm trong tên đầy đủ được gộp làm bí danh (倩倩 vào 张倩倩).
- **Giới tính tự đoán:** dựa trên chữ trong tên (淑, 婷, 倩 là nữ; 强, 伟 là nam), các từ chỉ giới tính đứng gần tên và đại từ model đã dịch. **Đại từ 他/她 không được tính.**
- **`sure`:** chỉ đặt khi tên có ít nhất hai chữ cùng giới (张倩倩, 顾念念 là sure; 李强 chỉ có một chữ nên không sure; 穆淑泽 là nam nhưng có chữ 淑 nên cố ý không sure). Người thân của người kể (我妈, 我哥, 嫂子 xuất hiện ≥ 3 lần) cũng sure. Người dùng sửa một dòng thì dòng đó thành xác nhận.
- **Chỉ giới tính đã xác nhận (người dùng sửa, `sure`, hoặc người thân) mới được đổi 他/她.** Giới tính chưa xác nhận chỉ đổi sắc thái.
- Không tự tạo mục người yêu, vì "我男朋友" thường nằm trong lời thoại của người khác. Vai trò mặc định là "Khác"; phản diện do người dùng đánh dấu.

## Quy tắc an toàn (dùng chung cho sửa tiếng Trung và L2)

Chỉ đổi giới tính khi **tất cả** điều kiện đúng:
- Câu có đúng một 他/她 số ít. Bỏ qua 他们/她们, dòng chứa dạng số nhiều, và đại từ nằm cuối dòng (ASR hay cắt "他|们").
- Chỉ một nhân vật trong phạm vi 4 dòng, được nhắc trong 3 dòng gần nhất, và giới tính đã xác nhận.
- Trong 6 dòng gần nhất không có đại từ ngược giới nào còn nguyên (đó là một người khác).
- Trong 4 dòng trước không có danh từ giới tính ngược (哥, 爸, 男友, 男人, 男生 ngoài "男生宿舍"…). Những người này có thể là người được nhắc tới.

Ngoài ra:
- **L2** chỉ sửa đại từ cùng giới ("cô ấy" thành "cô ta") và bỏ qua dòng có đại từ cả hai giới.
- **"bạn" ở lời gọi:** chỉ đổi khi dòng mở đầu bằng đúng một bí danh ("倩倩，你…") hoặc dòng trước chỉ gồm bí danh đó. Không đổi "các bạn", "bạn trai", "bạn bè"…
- Hai nhân vật trong phạm vi: giữ nguyên.

## Kiểm tra giới tính khi dịch

Câu có đúng một 他/她 và không chứa tên đã biết mà bản dịch có đại từ cả hai giới thì chắc chắn sai một chỗ ("Có lẽ **anh ấy** đang ở với bạn trai của **cô ấy**"). Xử lý theo thứ tự:
1. Dịch lại nhóm (2 lần). Nếu vẫn mâu thuẫn thì dịch riêng từng dòng (3 chiến lược, mỗi chiến lược một seed).
2. Nếu mọi lần thử đều mâu thuẫn, thay đại từ sai giới bằng đại từ cùng giới với 他/她 của câu. Đây chỉ là bước cuối, vì bản nháp chắc chắn đã sai ở đâu đó. Tuyệt đối không làm dòng thất bại.

Không ép giới tính của chính đại từ gốc ở bước này, vì ASR ghi 他/她 không đáng tin.

## Từ điển thuật ngữ

`worker/config/genre-lexicon.json`: mục `common` áp cho mọi job có style, mục `profiles` thêm theo thể loại. Khớp theo chuỗi con, không phụ thuộc ngữ cảnh, nên mục phải là cụm cụ thể (大胆的小偷, không phải 大胆). Danh sách hiện chỉ gồm các lỗi đã thấy trong bản dịch thật: 心虚 → chột dạ (trước đây "vô sỉ"), 再睁眼 → mở mắt ra lần nữa, 大胆的想法 → ý tưởng táo bạo, 大胆的小偷 → kẻ trộm liều lĩnh, 重生 → trọng sinh (Drama, Trọng sinh), 上辈子/这辈子 → kiếp trước/kiếp này (Trọng sinh). Thêm mục mới khi gặp lỗi lặp lại. Mục chỉ vào prompt của dòng chứa cụm đó, nên không làm tăng chi phí cho các dòng khác.

## Làm sạch dòng chảy câu (Moderation)

Hạ chữ hoa đầu mảnh khi mảnh trước kết thúc bằng dấu phẩy hoặc chấm phẩy ("tôi bị đẩy xuống sông, Tôi không biết bơi" thành "…, tôi không biết bơi"). Chỉ đổi từ mà dạng viết thường của nó xuất hiện giữa dòng ≥ 5 lần trong chính job đó, không phải tên trong glossary, và không phải cặp từ viết hoa ("Lý Cường"). Chỉ áp cho job có style.

## Checkpoint và Reprocess

- Khóa checkpoint theo dòng chỉ đổi với dòng bị sửa tiếng Trung hoặc dòng có cụm trong từ điển. Dòng còn lại giữ khóa cũ.
- **Đổi giới tính hoặc bí danh** trong bảng nhân vật: Reprocess từ **Translation** (dịch lại ≈ 12 phút cho 1000 dòng).
- **Đổi vai trò, vai vế hoặc cách gọi:** Reprocess từ **Moderation** (vài giây, rồi TTS).
- Bảng nhân vật không bị xóa khi Reprocess.

## Chạy thử trên dữ liệu thật (2026-10-05)

Sửa giới tính tiếng Trung, chỉ từ bảng nhân vật tự soạn (không đánh dấu tay):

| Workflow | Dòng được sửa | Chấm tay |
|---|---|---|
| 000008 | 2 / 1048 | 2 đúng (張倩倩 là chủ ngữ) |
| 000009 | 2 / 817 | 2 đúng (mẹ, chị dâu) |

Độ phủ thấp có chủ đích: lúc đầu thử nghiệm sửa nhiều hơn (17 và 8 dòng) nhưng chấm tay ra các lỗi nghiêm trọng (他们 thành 她们, nhân vật nam thành nữ), nên các điều kiện ở trên là kết quả của việc loại các lỗi đó.

L2 sau dịch (profile Drama, phản diện được đánh dấu tay): 52 dòng đổi ở 000008, 12 dòng ở 000009, 0 dòng ở Trung tính. Dòng 736/740 của 000009 (nhân vật nam bị đổi thành nữ ở lần chạy trước) đã được chặn. Đổi lại, dòng 111 của 000008 ("她只是一个大胆的小偷", nhân vật là Lý Cường) không còn được sửa thành "anh ta", vì hai trường hợp này không phân biệt được bằng quy tắc.

Model thật, 48 dòng chọn từ 000008 qua đúng đường dịch của pipeline: 心虚 thành "chột dạ", 大胆的小偷 thành "kẻ trộm liều lĩnh", dòng 979 thành "Có lẽ cô ấy đang ở với bạn trai của cô ấy", không dòng nào rỗng hay còn chữ Trung.

## Giới hạn

- Những dòng đầu truyện kể về "我室友" trước khi tên xuất hiện (000008, dòng 5–8) **không sửa được tự động**: câu "每天进口零食…" ở giữa nói về bạn trai, nên không thể biết "他" thuộc về ai nếu không hiểu nghĩa. Người dùng có thể thêm bí danh "我室友" vào nhân vật nhưng khoảng cách vẫn vượt phạm vi 3 dòng.
- ASR ghi 她 cho nhân vật nam (như dòng 111) thường không sửa được khi vừa có đại từ ngược giới ở gần.
- Không xác định được ai đang nói, nên "bạn" không kèm lời gọi tên vẫn giữ nguyên.
- Nhân vật không tên không được theo dõi. Trước đây các giá trị của profile mới dựa trên 1 video mỗi thể loại, nên hiệu chỉnh sau vài job thật.
- Model 1.8B dịch ngẫu nhiên và không thật sự hiểu mạch truyện. Các lớp ở đây giảm lỗi nhưng không thay thế một model lớn hơn.

## Làm sạch bản tiếng Trung (job có Kiểu giọng)

Chạy ở đầu Translation, trước bước sửa giới tính. `text_zh` lưu lại vẫn là bản ASR gốc; chỉ prompt và khóa checkpoint của dòng thay đổi dùng bản đã làm sạch (`translation/source_cleanup.py`, cấu hình `worker/config/source-cleanup.json`).

- **Cắt lời quảng cáo của kênh** đọc ở đầu truyện ("好看小说千千万，悠悠这里占一半，连好wifi，备好瓜子饮料，精彩故事现在开始"). Mẫu được khớp trên văn bản nối liền của 80 dòng đầu vì ASR cắt nó ngẫu nhiên ("袖手旁观好看。|小说千千万", "现在开始木木，"). Chỉ các ký tự khớp bị bỏ; phần truyện trong cùng dòng được giữ. Dòng chỉ còn dấu câu có bản dịch rỗng; số dòng và mốc thời gian không đổi, Moderation giữ dòng rỗng, TTS không đọc dòng rỗng.
- **Sửa lỗi nghe nhầm đã gặp** (thay chuỗi cố định): 煤运→霉运, 苦苦婆心→苦口婆心, 撒比→傻逼, 全闻完→全文完.
- Kết quả ghi ở `working/source-cleanup.json` (`dropped_rows`, `changed_rows`).

Đo ngoại tuyến: 000009 bỏ 6 dòng quảng cáo, cắt đuôi 1 dòng, sửa 4 lỗi ASR; 000008 bỏ 7 dòng, cắt đầu 1 dòng. Không dòng truyện nào bị bỏ.

Từ điển thuật ngữ (`genre-lexicon.json`) thêm các mục từ lỗi của 000009: 嫂子, 植物人/变成了植物, 娶媳妇, 老娘, 傻逼, 尿里, 霉运. **Các mục mới chưa được thử trên model thật** (RAM không đủ lúc triển khai); cơ chế thì đã thử với 心虚/大胆的小偷.
