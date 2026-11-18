# Tài liệu Audio Translates

| Tài liệu | Nội dung |
| --- | --- |
| [COMPUTE_SETTINGS.md](COMPUTE_SETTINGS.md) | Chọn CPU/GPU và cấu hình theo workflow |
| [ASR_CPU.md](ASR_CPU.md) | Tự điều chỉnh worker và RAM cho TRANSCRIPTION 3/4 |
| [TRANSCRIPTION_PROGRESS.md](TRANSCRIPTION_PROGRESS.md) | Tiến độ bốn pha chép lời |
| [TRANSLATION_LONG.md](TRANSLATION_LONG.md) | Dịch Hy-MT2-7B Q4_K_M: model, RAM đo thật, mẫu chat, ngưỡng, điều phối |
| [TRANSLATION_CHECKPOINTS.md](TRANSLATION_CHECKPOINTS.md) | Hàng đợi hữu hạn, checkpoint từng đoạn, xuất liên tiếp và Continue khi Translation lỗi |
| [TTS_CPU.md](TTS_CPU.md) | Tự điều chỉnh TTS CPU |
| [VOICE_PREVIEWS.md](VOICE_PREVIEWS.md) | Xem trước giọng đọc |
| [VOICE_PACKS.md](VOICE_PACKS.md) | Giọng fine-tune (Thùy Dương): gói delta LoRA, vá model ONNX lúc chạy, kiểm chứng |
| [VOICE_STYLES.md](VOICE_STYLES.md) | Kiểu giọng Mặc định/Drama/Sinh tồn/Trọng sinh: số đo nguồn và cách áp dụng |
| [ADDRESS_FORMS.md](ADDRESS_FORMS.md) | Xưng hô, giới tính và thuật ngữ theo thể loại: bảng nhân vật, sửa giới tính, từ điển, kiểm tra khi dịch |
| [BUILD_RELEASE.md](BUILD_RELEASE.md) | Tự build bộ cài Plus bằng một lệnh (`packaging/build_edition.py`), quy tắc tăng phiên bản, lỗi thường gặp, bản phát hành cứng |
| [TOOLS.md](TOOLS.md) | Bảy tool đơn lẻ: link YouTube, xưng hô, xóa khi đang chạy, chạy song song |
| [MANUAL_TRANSLATION.md](MANUAL_TRANSLATION.md) | Dịch thủ công: workflow chờ bản dịch, Công cụ 7 tách văn bản, nạp tệp vào một bước ở Tạo lại, đoạn có mã số |
| [OVERLAYS.md](OVERLAYS.md) | Logo và ảnh gắn lên video: thư viện ảnh, mẫu theo khung 16:9/9:16, mặc định, cách vẽ khi ghép video |
| [WORKFLOW_LIFECYCLE.md](WORKFLOW_LIFECYCLE.md) | Vòng đời, tạm dừng và tiếp tục workflow |
| [MULTI_WORKFLOW_SCHEDULER.md](MULTI_WORKFLOW_SCHEDULER.md) | Chạy nhiều workflow cùng lúc, chia luồng theo tài nguyên (đã triển khai) |
| [CALIBRATION_REVIEW.md](CALIBRATION_REVIEW.md) | Đánh giá hiệu chuẩn ASR, Translation, TTS và đề xuất cải tiến |
| [QWEN_RUNTIME_RESULT.md](QWEN_RUNTIME_RESULT.md) | Lịch sử: runtime Qwen (đã thay bằng Hy-MT2) |
| [QWEN_TRANSLATION_RESULT.md](QWEN_TRANSLATION_RESULT.md) | Lịch sử: dịch Qwen (đã thay bằng Hy-MT2) |
| [TTS_RUNTIME_RESULT.md](TTS_RUNTIME_RESULT.md) | Kết quả tối ưu runtime TTS |
| [IMPLEMENTATION_RESULT.md](IMPLEMENTATION_RESULT.md) | Ghi nhận triển khai |
| [CV_PROJECT_EVIDENCE.md](CV_PROJECT_EVIDENCE.md) | Bằng chứng kỹ thuật cho CV (đồng bộ 2026-10-05; mục 0 liệt kê thay đổi so với bản 1.0.2) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Kiến trúc hiện hành: vỏ Tauri, UI Next tĩnh, API FastAPI cục bộ, worker, lõi bảo mật, đóng gói |
| [CLEAN_ARCHITECTURE.md](CLEAN_ARCHITECTURE.md) | Bố cục mã nguồn và phát hành |

Kiến trúc hiện hành: [ARCHITECTURE.md](ARCHITECTURE.md). Tài liệu vận hành, thiết kế phía server và bảo mật nằm ở repo riêng tư của dự án, không đặt ở đây.
