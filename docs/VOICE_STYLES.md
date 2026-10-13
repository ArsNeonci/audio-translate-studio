# Kiểu giọng (Voice style)

Chọn ở bước bắt đầu (Studio), Tools → "Vietnamese Text → Vietnamese Voice" và Reprocess. Bộ chọn nằm trong `components/voice/voice-select.tsx` (prop `style`/`onStyleChange`). Danh sách style dùng chung giữa `lib/shared/voice-styles.ts` và `worker/audio_translate/tts/voice_styles.py`.

| Style | Giọng gợi ý | Tốc độ | Nghỉ thường / nghỉ dài | Thẻ cảm xúc |
|---|---|---|---|---|
| Mặc định / Default | giọng người dùng chọn | 1.00 | như cũ (không chèn) | không |
| Drama | Ngọc Huyền | 1.06 | 170 / 260 ms | có |
| Sinh tồn / Survival | Trúc Ly | 1.00 | 200 / 480 ms | có |
| Trọng sinh / Rebirth | Trúc Ly | 1.00 | 420 / 1000 ms | có |

Chọn style sẽ tự đặt giọng gợi ý. Người dùng vẫn đổi được giọng.

## Cách áp dụng (stage TTS)

1. **Gộp câu.** Các dòng liên tiếp được gộp tới khi gặp dấu kết câu (`. ! ? …`), tối đa 220 ký tự, hoặc khi khoảng cách thời gian giữa hai dòng ≥ 1.5 s. Manifest ghi `index` của dòng đầu, `rows` và `gap_after_ms`.
2. **Nhịp.** Cắt khoảng lặng đầu/cuối (ngưỡng −45 dBFS, chừa 30 ms), đổi tốc độ bằng `ffmpeg atempo` (giữ cao độ). Khi nối file, chèn đúng khoảng nghỉ của style. Nghỉ dài áp sau câu kết bằng `! ? …` hoặc trước một đoạn cách ≥ 1.5 s.
3. **Thẻ cảm xúc (thử nghiệm của VieNeu).** Chỉ thán từ đứng riêng mới được đổi, tối đa một thẻ mỗi câu. Ví dụ "ha ha", "hì hì" thành `[cười]`, còn "haiz", "hầy" thành `[thở dài]`.

Style **Mặc định** không thêm khóa `style` vào cấu hình TTS. Vì vậy chữ ký stage, checkpoint và cache WAV của job cũ giữ nguyên. Đổi style qua Reprocess sẽ làm đổi chữ ký, và TTS được tạo lại.

## Số đo nguồn (2026-10-04, mẫu 2 phút từ phút 5)

Speaker similarity đo bằng `speaker_encoder.onnx` của VieNeu. Mốc "cùng giọng" khoảng 0.89 (bản TTS Trúc Ly so với preset của chính nó).

| Nguồn | Preset gần nhất | F0 trung vị | Nghỉ trung vị / p90 | Ghi chú |
|---|---|---|---|---|
| Mù Tịt Audio (Drama) | Ngọc Huyền 0.70 | ~241 Hz | 0.17 / 0.22 s | cụm nói 1.7–2.4 s, nhanh hơn Trúc Ly ~8% |
| youtu.be/HfMx2Svq2XA (Sinh tồn) | Trúc Ly 0.50 | ~315 Hz | 0.16–0.24 / 0.22–0.51 s | có nền âm thanh (sàn −44 dB), cụm nói dài ~4 s |
| youtu.be/8WuOw9M8nOo (Trọng sinh) | Trúc Ly 0.51 | ~310 Hz | 0.34–0.53 / ~1.1 s | không có nhạc nền, nhịp chậm rãi |

Hai video Sinh tồn và Trọng sinh dùng cùng một giọng (0.90). Giọng này cao hơn Trúc Ly khoảng 3.4 bán cung và không có preset nào khớp. Style chưa đổi cao độ, vì pitch shift sẽ làm méo âm sắc.

## Kiểm chứng

- `worker/tests/test_voice_styles.py`: gộp câu, giới hạn độ dài, khoảng nghỉ, thẻ cảm xúc, atempo, manifest/WAV ghép, và style Mặc định không đổi cấu hình.
- Chạy thật VieNeu (CPU): cùng một câu, bản Mặc định dài 5.20 s (lặng đầu/cuối 0.07/0.36 s), bản Drama 4.32 s (0.02/0.02 s).
