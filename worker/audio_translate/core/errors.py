"""Persisted step states, sanitized failures and non-executing fix guides."""
from datetime import datetime, timezone
import errno
import json
import os
import re
from pathlib import Path

from audio_translate.core.storage import atomic_json, read_json, update_job

STEPS = ['DOWNLOAD', 'TRANSCRIPTION', 'TRANSLATION', 'MODERATION', 'TTS']
GUIDES = {
 'UNACTIVATED': ('Ứng dụng chưa kích hoạt.', 'License / Renewal', ['Mở License, copy Machine ID và gửi Admin.', 'Nhập token kích hoạt Admin cấp cho máy này.'], []),
 'EXPIRED': ('License đã hết hạn.', 'License / Renewal', ['Yêu cầu Admin cấp token gia hạn cho cùng máy.', 'Nhập token gia hạn theo đúng thứ tự. History và Download vẫn dùng được.'], []),
 'CLOCK_ROLLBACK': ('Đồng hồ máy chạy lùi so với lần kiểm tra trước.', 'Windows Date & Time', ['Bật đồng bộ giờ Windows và kiểm tra múi giờ.', 'Không xóa license state; đồng bộ giờ rồi thử lại.'], []),
 'TRUSTED_TIME_UNAVAILABLE': ('Không xác nhận được thời gian qua Internet.', 'Kết nối HTTPS / proxy của Windows', ['Kiểm tra kết nối Internet và chứng chỉ HTTPS.', 'Thử lại khi ít nhất hai nguồn thời gian có thể truy cập.'], []),
 'DEPENDENCY_MISSING': ('Thiếu thư viện Python.', 'worker/requirements.txt; .venv', ['Kiểm tra Python trong .venv.', 'Cài dependencies trong project rồi Retry Step.'], [r'.\.venv\Scripts\python.exe -m pip install -r worker/requirements.txt']),
 'MODEL_MISSING': ('Không tìm thấy model hoặc chưa tải đủ trọng số.', '.env.local: HY_MT_MODEL_PATH / VIENEU_SOURCE; models/Hy-MT2-7B-Q4_K_M; data/model-cache; data/hf-cache', ['Kiểm tra đường dẫn model tồn tại và mạng truy cập kho model.', 'Sửa đường dẫn hoặc tải đầy đủ model chính thức rồi Retry Step.'], []),
 'FFMPEG_MISSING': ('FFmpeg/ffprobe chưa có trên PATH.', 'PATH của server', ['Cài FFmpeg từ nguồn chính thức, thêm thư mục bin vào PATH.', 'Mở terminal mới và khởi động lại server.'], ['ffmpeg -version', 'ffprobe -version']),
 'PATH_MISSING': ('File/thư mục hoặc chương trình không tồn tại.', '.env.local; đường dẫn trong thông báo lỗi', ['Kiểm tra đường dẫn và file đầu vào.', 'Sửa đường dẫn; khởi động lại server nếu sửa .env.local.'], []),
 'FILE_PERMISSION': ('Không có quyền đọc/ghi hoặc file đang bị chương trình khác khóa.', 'data/tmp; data/jobs (legacy); RESULTS_ROOT; data/config; thư mục model', ['Kiểm tra quyền ghi thư mục bằng tài khoản chạy server.', 'Đóng chương trình đang giữ file; cấp quyền cho đúng thư mục rồi Retry Step.'], []),
 'DISK_FULL': ('Ổ đĩa không còn đủ chỗ.', 'Ổ chứa data/tmp, RESULTS_ROOT và model cache', ['Kiểm tra dung lượng trống.', 'Chuyển hoặc dọn file không cần thiết theo lựa chọn của bạn; giữ input, checkpoints và kết quả đã lưu của job.'], ['Get-PSDrive -PSProvider FileSystem']),
 'CUDA_OOM': ('GPU không đủ bộ nhớ.', 'Settings → CPU/GPU; data/settings/compute.json; job.json: compute_device', ['Đóng ứng dụng dùng GPU rồi thử lại.', 'Muốn dùng CPU: chọn CPU trong Cài đặt rồi tạo workflow mới. Retry của workflow cũ giữ thiết bị đã chọn.'], ['nvidia-smi']),
 'CUDA_CONFIG': ('CUDA/PyTorch hoặc backend GPU cấu hình không tương thích.', 'Settings → CPU/GPU; bản PyTorch và llama-cpp-python đã cài', ['Kiểm tra torch.cuda.is_available() và llama_supports_gpu_offload().', 'Cài backend GPU phù hợp rồi Retry; hoặc chọn CPU trong Cài đặt và tạo workflow mới. Workflow đã bắt đầu giữ thiết bị đã chọn.'], [r'.\.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"']),
 'YOUTUBE_AUTH': ('YouTube yêu cầu xác thực hoặc phiên đăng nhập không hợp lệ.', 'Settings → Kết nối YouTube', ['Bấm Đăng nhập lại / Mở YouTube và đăng nhập trong cửa sổ profile riêng.', 'Bấm Kiểm tra kết nối rồi Retry DOWNLOAD; không cần khởi động lại server.', 'Nếu vẫn dùng file cookie cũ: cập nhật file YTDLP_COOKIES_FILE dạng Netscape.'], []),
 'RATE_LIMIT': ('YouTube giới hạn truy cập.', 'Kết nối mạng/VPN/proxy', ['Chờ trước khi Retry Step.', 'Kiểm tra mạng và xác thực trong trình duyệt nếu YouTube yêu cầu.'], []),
 'ENV_CONFIG': ('Biến môi trường hoặc giá trị cấu hình không hợp lệ.', '.env.local; .env.example; working/adapters.json; RESULTS_ROOT', ['Đối chiếu .env.example; kiểm tra giá trị batch/device/đường dẫn. RESULTS_ROOT phải tách biệt data/tmp và data/jobs.', 'Sửa .env.local rồi khởi động lại server. Nếu job đã chốt adapters.json, sửa đúng trường cấu hình của job trước retry.'], []),
}


def redact(message):
    text = str(message)
    for key, value in os.environ.items():
        if value and re.search(r'token|password|secret|api.?key|cookie|authorization|credential', key, re.I):
            text = text.replace(value, '[REDACTED]')
    text = re.sub(r'https?://[^\s]+', '[URL]', text)
    text = re.sub(r'(?im)^.*(?:cookie|authorization|bearer|password|secret|token|api[_-]?key|\bSID=|\bSAPISID=).*$','[Sensitive detail removed]', text)
    text = re.sub(r'\b[\w-]{2,}=[^\s;,]+', '[REDACTED]', text)
    return text[:2000]


def classify(exc):
    if getattr(exc, 'code', None) in {'UNACTIVATED','EXPIRED','CLOCK_ROLLBACK','TRUSTED_TIME_UNAVAILABLE','WRONG_MACHINE','INVALID','RENEWAL_REQUIRED'}:
        return exc.code
    message = str(exc).lower()
    number = getattr(exc, 'errno', None)
    if type(exc).__name__ == 'YouTubeSessionError': code = 'YOUTUBE_AUTH'
    elif isinstance(exc, ModuleNotFoundError): code = 'DEPENDENCY_MISSING'
    elif number == errno.ENOSPC or getattr(exc, 'winerror', None) == 112 or 'no space left' in message or 'disk full' in message: code = 'DISK_FULL'
    elif isinstance(exc, PermissionError): code = 'FILE_PERMISSION'
    elif 'out of memory' in message and 'cuda' in message: code = 'CUDA_OOM'
    elif any(word in message for word in ['cuda', 'not compiled with', 'invalid device']): code = 'CUDA_CONFIG'
    elif any(word in message for word in ['cookie', 'sign in', 'xác thực']): code = 'YOUTUBE_AUTH'
    elif '429' in message: code = 'RATE_LIMIT'
    elif any(word in message for word in ['ffmpeg', 'ffprobe']) and isinstance(exc, FileNotFoundError): code = 'FFMPEG_MISSING'
    elif any(word in message for word in ['model', 'vieneu', 'trọng số', 'tokenizer', 'weights']) and ('not found' in message or 'không tìm' in message or 'load' in message): code = 'MODEL_MISSING'
    elif isinstance(exc, FileNotFoundError): code = 'PATH_MISSING'
    elif isinstance(exc, ValueError) and any(word in message for word in ['invalid literal', 'environment', 'device', 'batch', 'results_root']): code = 'ENV_CONFIG'
    else: code = 'STEP_FAILED'
    return code


def fix_guide(code):
    if code not in GUIDES:
        return None
    cause, config, instructions, commands = GUIDES[code]
    return {'cause': cause, 'config': config, 'checks_and_fixes': instructions, 'commands': commands}


def initial_steps(job):
    steps = {step: {'state': 'PENDING', 'retry_count': 0, 'attempt': 0, 'progress':0,
                    'started_at':None,'completed_at':None,'duration_ms':None} for step in STEPS}
    for step, item in job.get('steps', {}).items():
        if step in steps: steps[step].update(item)
    return steps


def transition(job_dir, step, state):
    job = read_json(Path(job_dir)/'job.json')
    steps = initial_steps(job)
    item = steps[step]
    from audio_translate.core.control import now, elapsed
    stamp = now()
    if state == 'RUNNING':
        item.update(started_at=stamp,completed_at=None,duration_ms=item.get('resume_duration_ms',0),progress=None)
        item.pop('error',None)
    elif state in ['COMPLETED','FAILED','CANCELLED','PAUSED']:
        item.update(completed_at=stamp,duration_ms=item.get('resume_duration_ms',0)+elapsed(item.get('started_at'),stamp))
        if state == 'COMPLETED': item['progress'] = 100
    item['state'] = state
    if state == 'RUNNING':
        item['attempt'] = item.get('attempt', 0) + 1
    if state == 'COMPLETED':
        item.pop('error', None)
    stages = job.get('stages',{})
    if state == 'RUNNING': stages[step.lower()] = {'percent':None,'done':0,'total':None}
    elif state == 'COMPLETED': stages[step.lower()] = {**stages.get(step.lower(),{}),'percent':100}
    effective = job.get('tool_steps',STEPS)
    values = [100 if steps[s]['state']=='COMPLETED' else stages.get(s.lower(),{}).get('percent',0) for s in effective]
    overall = None if any(v is None for v in values) else round(sum(values)/len(values),2)
    update_job(job_dir, steps=steps, stages=stages, progress=overall)


def record_failure(job_dir, step, exc):
    job_dir = Path(job_dir)
    job = read_json(job_dir/'job.json')
    steps = initial_steps(job)
    item = steps[step]
    code = classify(exc)
    timestamp = datetime.now(timezone.utc).isoformat()
    failure = {'step': step, 'error_code': code, 'error_message': redact(exc), 'error_type': type(exc).__name__,
               'recoverable_manually': code in GUIDES, 'failed_at': timestamp, 'retry_count': item.get('retry_count', 0)}
    from audio_translate.core.control import now, elapsed, end_run
    item.update(state='FAILED', error=failure, completed_at=now(), duration_ms=item.get('resume_duration_ms',0)+elapsed(item.get('started_at')))
    end_run(job_dir,'FAILED')
    update_job(job_dir, steps=steps, status='FAILED', failed_stage=step.lower(), active_stage=None,
               retry_step=None, error=failure['error_message'])
    entry = {**failure, 'attempt': item.get('attempt', 1), 'message': failure['error_message'], 'timestamp': timestamp}
    with (job_dir/'errors.jsonl').open('a', encoding='utf-8') as out:
        out.write(json.dumps(entry, ensure_ascii=False)+'\n')
        out.flush()
        os.fsync(out.fileno())
    try:
        from audio_translate.workflow.results import metadata
        metadata(job_dir)
    except (OSError, ValueError):
        pass  # The workspace failure survives even when result storage is full.
    return failure
