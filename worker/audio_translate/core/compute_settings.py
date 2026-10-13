"""Saved compute preference, frozen per workflow; GPU never falls back to CPU."""
import json
from pathlib import Path
import subprocess
import sys
from audio_translate.core.storage import DATA, atomic_json, file_lock, read_json, update_job

CONFIG = DATA / 'settings' / 'compute.json'
GPU_ERROR = 'GPU chưa sẵn sàng. Cần CUDA/PyTorch và llama-cpp-python hỗ trợ GPU; kiểm tra Cài đặt.'


def preference():
    if not CONFIG.exists(): return 'cpu'
    value = read_json(CONFIG).get('device')
    if value not in ('cpu', 'gpu'): raise ValueError('Invalid compute device')
    return value


def capabilities():
    # No model loading; isolate library imports from the API/worker process.
    code = """
import json
result = {'cuda':False, 'llama':False, 'gpu_name':None}
try:
    import torch
    result['cuda'] = bool(torch.cuda.is_available())
    if result['cuda']: result['gpu_name'] = torch.cuda.get_device_name(0)
except Exception: pass
try:
    from llama_cpp import llama_supports_gpu_offload
    result['llama'] = bool(llama_supports_gpu_offload())
except Exception: pass
print(json.dumps(result))
"""
    try:
        output = subprocess.run([sys.executable, '-c', code], capture_output=True,
                                text=True, timeout=30,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        result = json.loads(output.stdout) if output.returncode == 0 else {}
    except (OSError, ValueError, subprocess.TimeoutExpired): result = {}
    return {'transcription':bool(result.get('cuda')), 'translation':bool(result.get('cuda') and result.get('llama')),
            'tts':bool(result.get('cuda')), 'gpu_name':result.get('gpu_name')}


def validate(device, stages, available=None):
    if device not in ('cpu', 'gpu'): raise ValueError('Invalid compute device')
    if device == 'cpu': return
    from audio_translate.core.edition import is_basic
    # Basic generates the voice on the VPS (CPU there); the local GPU choice does not apply to TTS.
    if is_basic(): stages = [s for s in stages if s.lower() != 'tts']
    available = available if available is not None else capabilities()
    if any(s.lower() in ('transcription', 'translation', 'tts') and
           not available.get(s.lower()) for s in stages): raise RuntimeError(GPU_ERROR)


def freeze(job_dir):
    """Freeze at first start; retries retain it. Previously started legacy jobs retain CPU."""
    job_dir = Path(job_dir)
    job = read_json(job_dir / 'job.json')
    device = job.get('compute_device')
    if device is None:
        device = 'cpu' if job.get('started_at') else preference()
        update_job(job_dir, compute_device=device)
    return device


def stage_environment(device):
    return {'FUNASR_DEVICE':'cuda:0' if device == 'gpu' else 'cpu',
            'VIENEU_DEVICE':'cuda' if device == 'gpu' else 'cpu'}


def apply_adapters(settings, device):
    settings['translation'].update(device=device, n_gpu_layers=999 if device == 'gpu' else 0)
    from audio_translate.core.edition import is_basic
    if is_basic():
        # Voice generation runs on the VPS; a distinct backend keeps its checkpoints apart from local ones.
        settings['tts'].update(device='cpu', backend='remote')
    else:
        settings['tts']['device'] = 'cuda' if device == 'gpu' else 'cpu'
        settings['tts'].pop('backend', None)
    return settings


def command(payload):
    action = payload.get('action')
    if action == 'set':
        device = payload.get('device')
        if device not in ('cpu', 'gpu'): return {'status':400, 'error':'Invalid compute device'}
        # Saving a preference is allowed before installing GPU dependencies.
        with file_lock(CONFIG.with_suffix('.lock')):
            atomic_json(CONFIG, {'version':1, 'device':device})
    elif action != 'status': return {'status':400, 'error':'Invalid action'}
    return {'status':200, 'device':preference(), 'capabilities':capabilities()}


if __name__ == '__main__':
    try: result = command(json.load(sys.stdin))
    except Exception: result = {'status':503, 'error':'Compute settings unavailable'}
    print(json.dumps(result, ensure_ascii=True))
