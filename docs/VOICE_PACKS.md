# Giọng fine-tune (gói giọng)

Từ 3.2.6, ngoài 25 giọng có sẵn của VieNeu, app có thể mang **giọng fine-tune**: một giọng được train riêng bằng LoRA. Giọng đầu tiên là **Thùy Dương** (Nữ · Bắc · Phong cách tự nhiên). Mã: `worker/audio_translate/tts/voice_packs.py`.

## Khác giọng có sẵn ở đâu

| | Giọng có sẵn | Giọng fine-tune |
|---|---|---|
| Dữ liệu | `speaker_emb` + `codes` trong `voices_v3_turbo.json` | `speaker_emb` (không có `codes`) + phần chỉnh trọng số model |
| Model | Dùng chung model gốc | Model gốc đã vá, chỉ dùng cho đúng giọng đó |
| Đường chạy | ONNX/CPU | Vẫn ONNX/CPU, không cần GPU hay PyTorch |

## Gói giọng

Mỗi gói nằm trong `models/voice-packs/<tên>/`. Thư mục này nằm ngoài git (`models/` bị bỏ qua); bộ cài tự chép vào.

- `voice.json`:
  - các trường hiển thị giống một preset (`description`, `gender`, `region`, `style`, `aliases`);
  - vector giọng 192 số;
  - model gốc được ghim (`repo`, `revision`, sha256 của `vieneu_backbone_shared.data`);
  - sha256 của delta.
- `delta.npz` (khoảng 13 MB): với mỗi ma trận trong 84 ma trận backbone (12 tầng × q, k, v, o, gate, up, down), lưu offset byte trong file `.data`, kích thước, và hai thừa số `left`, `right` thỏa `left @ right = (α/r)·Aᵀ·Bᵀ`.

Gói được tạo trong `voice-clone-lab/finetune` bằng `export_pack.py`, từ adapter LoRA của một lần train.

## Lúc chạy

1. **Danh sách giọng:** `voices.live_presets()` thêm các gói vào danh sách, cùng định dạng với preset. Nếu trùng tên với preset thì gói được ưu tiên, giống adapter.
2. **Lần đầu dùng giọng**, `voice_packs.prepare()` làm các bước sau trong `DATA/voice-packs/<tên>/onnx`:
   - lấy thư mục `onnx_update` của model gốc ở đúng revision đã ghim (từ cache HF, hoặc tải như engine thường);
   - kiểm sha256 của delta và của file `.data` gốc;
   - chép 6 file đồ thị và cấu hình;
   - cộng delta vào bản sao của `vieneu_backbone_shared.data` (memory-map, fp32), rồi ghi `ready.json`.

   Nhiều worker TTS cùng nạp thì chỉ một worker làm việc này, các worker khác chờ. Đo trên máy dev: khoảng 7 giây, tốn thêm khoảng 475 MB đĩa.
3. **`TTSAdapter`** tạo `Vieneu(backend="onnx", onnx_dir=<thư mục đã vá>)` và đọc với `voice={"speaker_emb": ..., "codes": None}`. Đổi giữa giọng fine-tune và giọng thường thì engine được nạp lại.
4. **Bộ nhớ đệm TTS:** chữ ký của giọng fine-tune có thêm chữ ký của gói, nên train lại thì câu cũ không bị dùng lại. Các giọng khác giữ nguyên chữ ký.

Gói không phụ thuộc `VIENEU_PRECISION`, vì đồ thị trong `onnx_dir` là bản fp32.

## Đã kiểm chứng (2026-10-26)

- **Trọng số:** các ma trận ONNX trùng tuyệt đối với trọng số PyTorch gốc ở dạng chuyển vị (84/84). Sau khi vá, mỗi ma trận bằng `W + 2·B·A` (sai lệch tương đối 7·10⁻⁸). Phần còn lại của file giữ nguyên từng byte.
- **Âm thanh:** trên 4 câu model chưa thấy khi train, đường CPU cho phổ và thanh điệu tương đương bản GPU của lần train đó (lệch thanh điệu 0,87 nửa cung, tương quan 0,94). Mất khoảng 0,5 giây xử lý cho mỗi giây âm thanh; RAM khoảng 1,1 GiB, như giọng thường.
- **Test:** `worker/tests/test_voice_packs.py`.

## Giới hạn

- **Delta gắn với đúng bản model gốc.** Nếu VieNeu đổi `onnx_update`, sha256 không khớp và giọng báo lỗi thay vì phát ra âm thanh sai. Khi đó phải xuất lại gói, hoặc train lại nếu kiến trúc đổi.
- **Chỉ áp cho LoRA trên backbone.** Train với `--target all` (thêm acoustic decoder) thì cần mở rộng định dạng gói.
