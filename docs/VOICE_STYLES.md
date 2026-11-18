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

## Số đo cho style "Nhịp nhanh" (2026-11-18, đề xuất, chưa làm)

Mẫu: youtube.com/watch?v=fJSSkWW1bww ("Bí Cảnh Dị Giới", 6,9 giờ). Số âm tiết lấy từ phụ đề tự động tiếng Việt (có mốc thời gian từng âm tiết, 106 333 âm tiết); khoảng lặng đo bằng VAD năng lượng 10 ms, khoảng nghỉ là đoạn lặng ≥ 120 ms. Đo 14 cửa sổ × 120 s rải đều; so với các giọng app đã tạo (`results/*/tts`). Script: thư mục scratchpad của phiên, `pace.py`, `pace2.py`, `pace3.py`.

| | Âm tiết/s (cả nghỉ) | Âm tiết/s (chỉ lúc nói) | Tỉ lệ lặng | Nghỉ /100 âm tiết | Nghỉ trung vị / p90 / lớn nhất |
|---|---|---|---|---|---|
| Mẫu | 4,27 (4,18–4,48) | 4,88 (4,80–4,99) | 12 % | 9,2 | 0,25 / 0,35 / 0,39 s |
| App Ngọc Huyền (Drama) | 4,44–4,79 | 5,23–5,47 | 12–17 % | 7–14 | 0,22 / 0,33–0,45 / 0,71 s |
| App Trúc Ly (Sinh tồn) | 4,62 | 5,58 | 17 % | 12 | 0,25 / 0,34 / 0,53 s |
| App Thùy Dương (Mặc định) | 4,59 | 5,63 | 19 % | 13 | 0,29 / 0,41 / 0,63 s |

- Mẫu **không nói nhanh hơn** giọng app tính theo âm tiết. Điểm khác là nhịp nghỉ: khoảng nghỉ ngắn và rất đều, có trần cứng 0,39 s, không có nghỉ dài kể cả ở cuối câu (sau dấu chấm 0,28 s, sau dấu phẩy 0,24 s), cụm nói dài trung bình 11 âm tiết. Đoạn lặng là lặng số (−67 đến −92 dB), có dấu hiệu đã qua bước cắt lặng.
- Ở app, nghỉ dài nằm **trong** từng đơn vị (VieNeu tự nghỉ ở dấu phẩy: p90 0,43–0,46 s, có lúc 0,6–0,7 s); nghỉ giữa các đơn vị đã do style kiểm soát.
- Mô phỏng chỉ ép khoảng nghỉ theo mẫu trên các giọng đã có: ngắn hơn 0–2 %. Muốn "nhanh" thật phải tăng tốc độ đọc, nên mức tăng cần được người nghe chọn.

### Phản hồi khách hàng (2026-11-18): mẫu 32 s "rời rạc", mẫu 39 s "mượt"

Hai tệp `1K7MOTB4D_8B9MUO.aac` (A, 32 s) và `1K7MOTG08_8B9MUO.aac` (B, 39 s), ở thư mục gốc `Audio-translate`. Cả hai có nền âm liên tục (sàn khoảng −50 dB), nên dùng VAD trừ nền theo từng dải tần (300–3400 Hz); số âm tiết chỉ là ước lượng (sai khoảng ±10 %).

| | Nghỉ ≥ 0,40 s | Nghỉ trung vị / p90 / lớn nhất | Ghi chú |
|---|---|---|---|
| A 32 s (rời rạc) | 47 % số lần nghỉ, cứ 1,5–2,5 s một lần | 0,38 / 0,51 / 1,00 s | khớp kiểu Mặc định: dòng ASR trung vị 8 âm tiết, mỗi dòng đọc riêng, giữ lặng đầu/cuối của VieNeu (0,07 + 0,36 s) |
| B 39 s (mượt) | 15 % | 0,18 / 0,42 / 0,51 s | dài hơn nhưng được khen: vấn đề là độ liền, không phải tốc độ |
| Video khách muốn | 0 % (đo trên âm lặng sạch) | 0,25 / 0,35 / 0,39 s | giọng gần Ngọc Huyền (cosine 0,888) |

- A và B cùng một giọng (0,91), không trùng giọng nào trong ba giọng app đã đo. DTW cho thấy hai mẫu **không chắc cùng văn bản**.
- Hướng xử lý: style đọc liền mạch, dùng được với mọi giọng (gộp câu, cắt lặng, trần nghỉ khoảng 0,35–0,39 s, không đổi tốc độ). Trước mắt dùng Drama + Ngọc Huyền.

## Kiểm chứng

- `worker/tests/test_voice_styles.py`: gộp câu, giới hạn độ dài, khoảng nghỉ, thẻ cảm xúc, atempo, manifest/WAV ghép, và style Mặc định không đổi cấu hình.
- Chạy thật VieNeu (CPU): cùng một câu, bản Mặc định dài 5.20 s (lặng đầu/cuối 0.07/0.36 s), bản Drama 4.32 s (0.02/0.02 s).
