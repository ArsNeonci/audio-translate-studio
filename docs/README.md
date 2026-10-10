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
| [VOICE_STYLES.md](VOICE_STYLES.md) | Kiểu giọng Mặc định/Drama/Sinh tồn/Trọng sinh: số đo nguồn và cách áp dụng |
| [ADDRESS_FORMS.md](ADDRESS_FORMS.md) | Xưng hô, giới tính và thuật ngữ theo thể loại: bảng nhân vật, sửa giới tính, từ điển, kiểm tra khi dịch |
| [PLAN_TTS_VPS.md](PLAN_TTS_VPS.md) | Basic tạo giọng qua VPS (FLAC, đoạn 1.200 ký tự), duyệt trước TTS + ô Auto, nền tảng nhiều app, số đo TTS: thiết kế + trạng thái triển khai (mục 0) |
| [PLAN_GENIUS_BASIC_PLUS.md](PLAN_GENIUS_BASIC_PLUS.md) | Genius qua VPS, tính phí và hạn mức, gói Basic / Plus: thiết kế đã duyệt + trạng thái triển khai (mục 0) |
| [PLAN_PAYMENTS_PAYOS.md](PLAN_PAYMENTS_PAYOS.md) | Thanh toán payOS/VietQR và cổng Billing (phí dịch vụ; gói license theo ngày hoặc 1/3/6/9/12 tháng): webhook, đối soát, renewal-worker ký gia hạn, bảng giá và hạn mức nợ theo app/khách, triển khai trên VM GCP (đã triển khai 2026-10-07; mục 15 ghi trạng thái và cách thử giao dịch thật) |
| [BUILD_RELEASE.md](BUILD_RELEASE.md) | Tự build bộ cài Basic/Plus bằng một lệnh (`packaging/build_edition.py`), quy tắc tăng phiên bản, lỗi thường gặp, bản phát hành cứng |
| [ADMIN_ACTIONS.md](ADMIN_ACTIONS.md) | Các nút trong admin: làm gì, lấy giá trị ở đâu; gia hạn cộng dồn; lỗi `LEASE_VERSION_UNSUPPORTED` |
| [MODEL_DOWNLOAD.md](MODEL_DOWNLOAD.md) | Model dịch 4,6 GB tải sau khi cài (bộ cài .exe không được quá 4 GiB): luồng, link ký sẵn từ gateway, việc phải làm ở GCP, đổi model |
| [MIGRATION_GCP_TO_VPS.md](MIGRATION_GCP_TO_VPS.md) | Chuyển gateway, admin, TTS từ VM GCP sang VPS OVH (đã cắt chuyển 2026-10-11): trạng thái VPS, đo TTS, mã đã đổi, cách cắt chuyển và quay lại |
| [ADMIN_ONLINE.md](ADMIN_ONLINE.md) | Admin chạy liên tục trên VM sau Cloudflare Access: kiến trúc, rủi ro khi khóa ký nằm trên server, việc cần làm trên Cloudflare, chuyển quyền từ máy bạn, máy build, vận hành (đã cài ở trạng thái đóng, chưa chuyển dữ liệu) |
| [TOOLS.md](TOOLS.md) | Bốn tool đơn lẻ: link YouTube, xưng hô, xóa khi đang chạy, chạy song song |
| [WORKFLOW_LIFECYCLE.md](WORKFLOW_LIFECYCLE.md) | Vòng đời, tạm dừng và tiếp tục workflow |
| [MULTI_WORKFLOW_SCHEDULER.md](MULTI_WORKFLOW_SCHEDULER.md) | Chạy nhiều workflow cùng lúc, chia luồng theo tài nguyên (đã triển khai) |
| [CALIBRATION_REVIEW.md](CALIBRATION_REVIEW.md) | Đánh giá hiệu chuẩn ASR, Translation, TTS và đề xuất cải tiến |
| [QWEN_RUNTIME_RESULT.md](QWEN_RUNTIME_RESULT.md) | Lịch sử: runtime Qwen (đã thay bằng Hy-MT2) |
| [QWEN_TRANSLATION_RESULT.md](QWEN_TRANSLATION_RESULT.md) | Lịch sử: dịch Qwen (đã thay bằng Hy-MT2) |
| [TTS_RUNTIME_RESULT.md](TTS_RUNTIME_RESULT.md) | Kết quả tối ưu runtime TTS |
| [IMPLEMENTATION_RESULT.md](IMPLEMENTATION_RESULT.md) | Ghi nhận triển khai |
| [CV_PROJECT_EVIDENCE.md](CV_PROJECT_EVIDENCE.md) | Bằng chứng kỹ thuật cho CV (đồng bộ 2026-10-05; mục 0 liệt kê thay đổi so với bản 1.0.2) |
| [CLEAN_ARCHITECTURE.md](CLEAN_ARCHITECTURE.md) | Bố cục mã nguồn và phát hành |
| [SECURITY_PHASE_1_RESULT.md](SECURITY_PHASE_1_RESULT.md) | Bảo mật Phase 1: ranh giới tin cậy native, license gắn máy, broker |
| [SECURITY_PHASE_2_RESULT.md](SECURITY_PHASE_2_RESULT.md) | Bảo mật Phase 2: service + Named Pipe, manifest ký, integrity, tamper states (2A xong; 2B/2C đang làm) |
| [SECURITY_PHASE_3_RESULT.md](SECURITY_PHASE_3_RESULT.md) | Bảo mật Phase 3: xác minh tiến trình pipe, anti-debug, quét secret, hook ký Authenticode; phần cần cert/TPM/pipeline ghi rõ |

Trạng thái dự án, vấn đề đang mở và dòng thời gian: [Agent.md](../../Agent.md).
