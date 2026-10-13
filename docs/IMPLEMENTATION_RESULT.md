# IMPLEMENTATION_RESULT

Đã tích hợp vào pipeline/model/license hiện có.

- **Workflow numbering:** registry SQLite cấp số tăng dần, không tái sử dụng sau delete; retry/resume/reprocess giữ số cũ.
- **Naming:** helper duy nhất tạo tên output `000125-transcript.zh.md`, `000125-transcript.vi.jsonl`, `000125-voice.vi.wav` và các artifact liên quan.
- **Progress:** bytes download, thời lượng ASR, segments translation/moderation/TTS; numeric bị giới hạn 0–100, UI `toFixed(2)`. Workload chưa biết hiển thị indeterminate. Overall là trung bình đều các stage, có giải thích trên UI.
- **Timing:** timestamps và milliseconds cho stage/attempt; elapsed realtime; tổng thời gian xử lý cộng dồn qua các lần chạy, không tính thời gian chờ hàng đợi.
- **Voice:** discover preset VieNeu từ source config và metadata model đã cache; hiện có 25 voices. Lưu `selected_voice_id`, truyền đúng vào adapter, persist last voice trong application preferences và fallback hợp lệ.
- **Standalone tools:** `/tools` có Audio→Chinese, Chinese→Vietnamese, Vietnamese→Moderation, Vietnamese→Voice; dùng lại adapter/worker. Upload streaming, kiểm tra extension/MIME/content/container; TXT/MD/JSONL UTF-8 có giới hạn rõ trên UI.
- **Tool history:** `results/tools/<number>` riêng với `results/workflows/<number>`; View/Play theo license, Download/Delete riêng. Studio và Reprocess không liệt kê tools.
- **Hard delete:** confirmation chứa số workflow và cảnh báo không hoàn tác; xóa metadata, logs, outputs, checkpoints, temp và backup của đúng run. Kiểm tra scope/path/OS lock; giữ global counter, xóa registry row của run. Delete vẫn được phép khi EXPIRED.
- **Reprocess:** `/reprocess`, chọn workflow/stage/voice; giữ predecessors, invalidate và rebuild stage được chọn cùng downstream, giữ số và tên file. Output STALE không được sử dụng như kết quả hiện hành.
- **Cancel:** signal cooperative tới worker; stage CANCELLED, cleanup incomplete temp, giữ completed outputs. Có thể reprocess tiếp; không kill inference đột ngột.
- **Atomic replacement:** validate temp, atomic file replacement, commit manifest rồi COMPLETED. PUBLISHING/STALE bị chặn; lỗi trước publish giữ bản đã xuất. Tích hợp Error/Fix Guide/Retry.
- **Migration:** cấp số record cũ theo `created_at`, kiểm tra collision, backup metadata, copy có checksum/atomic rename. Không xóa legacy; khôi phục được cả history chỉ còn bản published.
- **Validation:** build và lint PASS; 62 worker/management tests, 19 Admin/license tests, 9 UI-format assertions PASS. HTTP ACTIVE 64, RESTART 20, EXPIRED 20 assertions PASS; có translation/VieNeu thật, Cancel/resume, tải WAV 64 MiB có checksum, Range và traversal checks. Browser kiểm tra 25 voices, history tách scope và stage table. Dữ liệu kiểm tra cô lập trong `data/verification`.

**Giới hạn:** Cancel chờ điểm kiểm tra an toàn sau lời gọi inference đang chạy. Timing cũ chưa được ghi không thể khôi phục và hiển thị “—”. Migration giữ backup legacy nên cần thêm dung lượng lưu trữ. Các kiểm tra AI thật dùng input ngắn; không chạy lại một video dài trong lượt này.
