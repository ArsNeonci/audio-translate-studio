# Trang Tạo lại: thẻ theo từng "Bắt đầu lại từ" (2026-11-19)

Trang Tạo lại dùng **cùng các thẻ và cùng thứ tự với Studio** (Giọng đọc → Cách dịch → Phụ đề → Ghép video), nhưng chỉ hiện thẻ của giai đoạn được chọn và của **mọi giai đoạn sẽ chạy lại sau nó**. Giai đoạn trước giữ kết quả nên không hiện cài đặt của chúng. Thẻ "Nguồn" của Studio được thay bằng thẻ "Chọn workflow + Bắt đầu lại từ" (cộng thẻ Nạp file ở Chép lời, Dịch, Kiểm duyệt, Giọng). Mọi ô điền sẵn cài đặt đã lưu của run. Mã: `web/app/reprocess/page.tsx`.

## Thẻ theo giai đoạn

| Bắt đầu lại từ | Giọng | Cách dịch | Phụ đề | Ghép video | Ghi chú |
|---|---|---|---|---|---|
| Tải về | có | Dịch thủ công, chế độ dịch, xưng hô | có (nếu run có phụ đề) | có | Dòng "Nguồn giữ nguyên: …" (không đổi được link/tệp) |
| Chép lời, Dịch | có | Dịch thủ công, chế độ dịch, xưng hô | có | có | |
| Kiểm duyệt | có | chỉ xưng hô | có | có | Nạp bản dịch tay thì không có xưng hô |
| Giọng đọc | có | **không** (xưng hô áp dụng ở Kiểm duyệt) | có | có | |
| Phụ đề | | | có + ô "Gắn phụ đề vào video" | | Mô tả theo Ultra nếu run dùng Siêu nhanh |
| Ghép video | | | có khi tick "Gắn phụ đề" | có (cả Siêu nhanh) | |
| Gắn phụ đề | | | có + ô "Nén nhanh nhất" | | Không có trong danh sách với run Siêu nhanh |

Xưng hô chỉ hiện khi chế độ Normal và bản dịch không phải bản tay. Đổi "Kiểu giọng" chỉ tự đổi xưng hô khi ô xưng hô đang hiện.

Dưới các thẻ có dòng **"Sẽ chạy lại: …"** tính theo thứ tự của worker (`runSteps`): có SPLIT khi chuyển sang dịch tay, không có BURN với Siêu nhanh, giai đoạn Phụ đề chỉ chạy Phụ đề (và BURN, hoặc VIDEO với Siêu nhanh, khi tick gắn phụ đề).

## Gửi gì lên `POST /api/jobs/<id>/reprocess`

- `voice`, `style` khi có thẻ Giọng; `mode` khi có chế độ dịch (không gửi khi nạp file); `address` chỉ khi ô xưng hô hiện (trước đây gửi cả ở Giọng đọc nên đổi kiểu giọng ở đó bị từ chối "Changing forms of address requires restarting from Moderation or earlier").
- `subtitle` khi có thẻ Phụ đề; `burn: true` khi tick ở giai đoạn Phụ đề.
- `video`: luôn gửi ở giai đoạn Ghép video; ở giai đoạn sớm hơn **chỉ gửi khi người dùng đổi** (trước đây gửi ngầm lại video cũ, nên clip bị chuyển chỗ làm hỏng cả việc chạy lại giọng).
- Mới (backend `workflow/manage.py reprocess`, kiểm tra kiểu ở `api/management.py`):
  - `manual` (bool, Tải về đến Dịch): `true` = như tạo workflow dịch tay (cắt phần theo cài đặt Công cụ 7 mới nhất, xưng hô và chế độ dịch bị bỏ; từ Dịch thì chạy lại từ SPLIT rồi dừng ở AWAITING_TRANSLATION); `false` = máy dịch lại.
  - `drop_video` (bool, gửi khi gỡ hết clip trong thẻ Video ở giai đoạn trước Ghép video): run mất bước Ghép video, các file VIDEO/BURN thành STALE, mục VIDEO/BURN bị gỡ khỏi `steps`. Không dùng với giai đoạn Ghép video, Gắn phụ đề hay cùng lúc với `video`.
  - `ultra` (bool, chỉ giai đoạn Gắn phụ đề, run không Siêu nhanh): lưu `job.burn_ultra`; `burn()` dùng x264 `ultrafast` cho lượt đó, video không phụ đề vẫn giữ.

## Test

- `worker/tests/test_manual_translation.py` `test_reprocess_switches_a_workflow_to_hand_translation_and_back`.
- `worker/tests/test_subtitle_workflow.py` `test_reprocess_can_drop_the_videos_and_draw_one_burn_with_the_fastest_setting`.
- `contracts/tests/ui_smoke.py` (phần Tạo lại).

## Studio nhớ lựa chọn lần trước (2026-11-20, chưa phát hành)

`web/lib/shared/remembered-settings.ts` + `web/app/page.tsx`: Studio lưu trong `localStorage` (khóa `audio-studio-settings-v1`) **cách làm việc** lần cuối: kiểu giọng, giọng, xưng hô, chế độ dịch, dịch thủ công, hai số phụ đề, độ phân giải, chất lượng, mẫu logo, Gắn phụ đề, Siêu nhanh. **Không** nhớ link YouTube, tệp âm thanh, danh sách clip. Mở lại thì áp dụng một lần sau khi trang vẽ xong; từng trường được kiểm tra, trường sai hoặc không còn hợp lệ bị bỏ (giọng không còn trong danh sách, mẫu logo đã xóa → Mặc định, số phụ đề ngoài giới hạn). Không có bộ nhớ, bộ nhớ hỏng hoặc bị chặn thì dùng mặc định như trước (mọi đọc/ghi nằm trong try/catch). Sau khi tạo run thành công, clip bị xóa nhưng các lựa chọn giữ nguyên. Trang Tạo lại luôn lấy cài đặt đã lưu của run; Công cụ đơn không nhớ. Test: `contracts/tests/ui_smoke.py` (khối "remembered").
