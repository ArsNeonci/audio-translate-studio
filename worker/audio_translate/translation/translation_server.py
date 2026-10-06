"""One shared model with live resource admission; no synthetic benchmarks.

SQLite and ordered exports are owned exclusively by the coordinator thread.
Performance settings are live and do not change translation fingerprints.
"""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import ctypes
import json
import math
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.request

import psutil
from audio_translate.core import lanes
from audio_translate.core.scaling import GainTrial
from audio_translate.core.control import Cancelled, check_cancel
from audio_translate.core.storage import ROOT, DATA, atomic_json

DEFAULTS = dict(engine='auto', enabled=True, threads=4, threads_batch=4,
                n_batch=128, max_slots=0, start_free_gib=3.5, extra_slot_gib=.4,
                cpu_target=85, gpu_target=85, temperature_limit=85, reserve_gib=2,
                observe_seconds=1, recovery_seconds=30, safety_gib=.4,
                scale_up_seconds=10, vram_reserve_gib=.5, gain_window_seconds=30, retry_seconds=600)
GIB = 1024 ** 3


def policy():
    path = Path(os.getenv('HY_MT_RUNTIME_CONFIG', ROOT / 'worker' / 'config' / 'translation-runtime.json'))
    values = {**DEFAULTS, **(json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {})}
    if values['engine'] not in ('auto', 'server', 'embedded') or type(values['enabled']) is not bool:
        raise ValueError('Invalid Hy-MT2 engine/enabled policy')
    for key in ('threads', 'threads_batch', 'n_batch', 'max_slots'):
        if type(values[key]) is not int or values[key] < 0:
            raise ValueError(f'Invalid Hy-MT2 runtime {key}')
    for key in ('start_free_gib','extra_slot_gib','cpu_target','gpu_target','temperature_limit','reserve_gib', 'observe_seconds', 'recovery_seconds', 'scale_up_seconds','safety_gib', 'vram_reserve_gib',
                'gain_window_seconds', 'retry_seconds'):
        if isinstance(values[key], bool) or not isinstance(values[key], (int, float)) or not math.isfinite(values[key]) or values[key] <= 0:
            raise ValueError(f'Invalid Hy-MT2 runtime {key}')
    if values['cpu_target'] > 100 or values['gpu_target'] > 100:
        raise ValueError('Hy-MT2 utilization targets must not exceed 100')
    return values


def executable():
    return Path(os.getenv('HY_MT_SERVER_PATH', ROOT / 'runtime' / 'llama' / ('llama-server.exe' if os.name == 'nt' else 'llama-server')))


def server_gpu_available():
    """Probe the actual helper; Python's CUDA support does not imply helper support."""
    try:
        result = subprocess.run([str(executable()), '--list-devices'], capture_output=True,
                                text=True, timeout=15,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return result.returncode == 0 and 'CUDA0' in result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def gpu_memory(config):
    if config.get('device') != 'gpu':
        return None
    import torch
    free, total = torch.cuda.mem_get_info(0)
    return {'free': free, 'total': total, 'name': torch.cuda.get_device_name(0)}


def gpu_metrics(config):
    if config.get('device') != 'gpu': return {'utilization':None,'temperature':None}
    try:
        result = subprocess.run(['nvidia-smi','--id=0','--query-gpu=utilization.gpu,temperature.gpu',
                                 '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=2,
                                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        utilization, temperature = map(float,result.stdout.strip().split(','))
        return {'utilization':utilization,'temperature':temperature}
    except (OSError,ValueError,subprocess.TimeoutExpired):
        return {'utilization':None,'temperature':None}


KV_BYTES = {'f16': 2.0, 'bf16': 2.0, 'q8_0': 34 / 32, 'q4_0': 18 / 32}


def slot_bytes(metadata, context, cache_type='f16'):
    # K + V: 2 caches * bytes per element (by cache type) * layers * KV heads * head dimension.
    arch = metadata.get('general.architecture', 'hunyuan-dense')
    layers = int(metadata.get(f'{arch}.block_count', 32))
    heads = int(metadata.get(f'{arch}.attention.head_count', 16))
    kv = int(metadata.get(f'{arch}.attention.head_count_kv', 4))
    dimension = int(metadata.get(f'{arch}.attention.key_length', int(metadata.get(f'{arch}.embedding_length', 2048)) // heads))
    return int(context * layers * kv * dimension * 2 * KV_BYTES.get(cache_type, 2.0)) + 128 * 1024 ** 2


def pressure(config):
    battery = psutil.sensors_battery()
    p = policy()
    target = min(config['cpu_target'],p['cpu_target'],65 if battery and not battery.power_plugged else 100)
    available = psutil.virtual_memory().available
    from audio_translate.core.memory_policy import commit_available
    commit = commit_available()
    reserve = max(p['reserve_gib'], config['min_available_gib']) * GIB
    gpu = gpu_memory(config)
    metrics = gpu_metrics(config)
    low_vram = gpu is not None and gpu['free'] < p['vram_reserve_gib'] * GIB
    try:
        temperatures = getattr(psutil, 'sensors_temperatures', lambda: {})()
    except (OSError, NotImplementedError):
        temperatures = {}
    hot = any(item.current >= p['temperature_limit'] for group in temperatures.values() for item in group)
    hot = hot or (metrics['temperature'] is not None and metrics['temperature'] >= p['temperature_limit'])
    return {'cpu': psutil.cpu_percent(interval=None), 'cpu_target': target,
            'available': available, 'reserve': reserve, 'commit': commit,
            'hot': hot, 'thermal_available': bool(temperatures) or metrics['temperature'] is not None,
            'gpu_utilization':metrics['utilization'],'gpu_target':p['gpu_target'],
            'gpu_temperature':metrics['temperature'],
            'gpu': gpu, 'low_vram': low_vram,
            'low_memory': available < reserve or (commit is not None and commit < reserve) or low_vram}


def windows_job(process):
    """Kill the helper if its Python parent exits/crashes (no orphan model)."""
    if os.name != 'nt':
        return None
    from ctypes import wintypes as w
    class Basic(ctypes.Structure):
        _fields_ = [('per_process', ctypes.c_int64), ('per_job', ctypes.c_int64), ('flags', w.DWORD),
                    ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t), ('active', w.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
    class Extended(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                    ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    limits = Extended(); limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle, w.HANDLE(int(process._handle))):
        if handle: kernel.CloseHandle(handle)
        raise OSError(ctypes.get_last_error(), 'Cannot contain llama-server in a Windows job')
    return (kernel, handle)


class SharedServer:
    def __init__(self, config, job_dir, threads, threads_batch, batch, slots):
        self.config, self.job_dir = config, job_dir
        self.threads, self.threads_batch, self.batch, self.capacity = threads, threads_batch, batch, slots
        self.process = self.log = self.job_handle = None
        self.key = secrets.token_hex(24)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def start(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
        self.url = f'http://127.0.0.1:{port}'
        directory = Path(self.job_dir) / 'working' if self.job_dir else DATA / 'config'
        directory.mkdir(parents=True, exist_ok=True)
        self.log = (directory / 'translation-server.log').open('ab')
        command = [str(executable()), '-m', self.config['model'], '--host', '127.0.0.1', '--port', str(port),
                   '--api-key', self.key, '--no-webui', '--offline', '--no-context-shift',
                   '--threads', str(self.threads), '--threads-batch', str(self.threads_batch),
                   '--batch-size', str(self.batch), '--ubatch-size', str(min(self.batch, 512)),
                   '--parallel', str(self.capacity), '--ctx-size', str(self.config['n_ctx'] * self.capacity),
                   '--no-kv-unified', '--cache-ram', '0', '--sse-ping-interval', '1',
                   '--n-gpu-layers', str(self.config['n_gpu_layers']),
                   '--cache-type-k', self.config.get('kv_cache_type', 'f16'),
                   '--cache-type-v', self.config.get('kv_cache_type', 'f16'),
                   # Q4_K repacking keeps a second copy beside the mmapped GGUF: 7B cost 4.77 GiB
                   # with --no-repack versus >6.7 GiB repacked, at the same ~6.5 tokens/s.
                   *([] if self.config.get('repack', False) else ['--no-repack'])]
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.job_handle = windows_job(self.process)
            began = time.monotonic()
            while True:
                check_cancel(self.job_dir)
                if self.process.poll() is not None:
                    raise RuntimeError('llama-server exited during load; see working/translation-server.log')
                try:
                    with self.request('/health', timeout=2) as response:
                        if json.load(response).get('status') == 'ok': return self
                except (urllib.error.URLError, TimeoutError):
                    pass
                if time.monotonic() - began > 180:
                    raise RuntimeError('llama-server model loading timed out')
                time.sleep(.2)
        except BaseException:
            self.close(); raise

    def request(self, endpoint, payload=None, timeout=120):
        request = urllib.request.Request(self.url + endpoint,
                    data=json.dumps(payload).encode('utf-8') if payload is not None else None,
                    headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.key})
        return self.opener.open(request, timeout=timeout)

    def completion(self, prompt, slot, limit, progress=None, seed=42, temperature=.7, stop=None):
        from audio_translate.translation.hymt_translation import STOP
        stop = stop or STOP
        payload = dict(prompt=prompt, n_predict=limit, temperature=temperature, top_p=.6, top_k=20,
                       repeat_penalty=1.05, seed=seed, stop=stop, cache_prompt=True, id_slot=slot, stream=True)
        pieces, final = [], None
        with self.request('/completion', payload) as response:
            for raw in response:
                if progress: progress()
                if not raw.startswith(b'data: '): continue
                data = raw[6:].strip()
                if data == b'[DONE]': continue
                item = json.loads(data)
                if 'error' in item: raise RuntimeError(f"Hy-MT2 server generation failed: {item['error']}")
                pieces.append(item.get('content', ''))
                if item.get('stop'): final = item
        if final is None: raise RuntimeError('Hy-MT2 stream ended without a completion marker')
        text = ''.join(pieces)
        for token in stop: text = text.replace(token, '')  # a rendered end token is not translation
        return text.strip(), final

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: self.process.kill(); self.process.wait(timeout=5)
        if self.job_handle:
            self.job_handle[0].CloseHandle(self.job_handle[1]); self.job_handle = None
        if self.log: self.log.close(); self.log = None


class Runtime:
    def __init__(self, adapter):
        self.adapter, self.server = adapter, None
        self.config = adapter.settings
        self.cores = psutil.cpu_count(logical=False) or 1
        self.extra_bytes = slot_bytes(adapter.model.metadata, self.config['n_ctx'], self.config.get('kv_cache_type', 'f16'))
        self.slots = 1
        self.last_observed = 0
        self.pending_reduction = None
        self.last_memory = None
        self.recover_after = 0
        self.observed_cpu = 0
        self.healthy_since = None
        self.admission_blocked = False
        self.lane = dict(target=10**6, cores=self.cores)
        # An extra slot is kept only if measured characters per second rise (core/scaling.py).
        self.gain = GainTrial(policy()['gain_window_seconds'], policy()['retry_seconds'])
        psutil.cpu_percent(interval=None)

    def record(self, characters):
        self.gain.record(characters)

    def lane_maximum(self):
        p = policy()
        return max(1, min(self.cores, p['max_slots'] or self.cores, self.lane['target'])) if p['enabled'] else 1

    def lane_cores(self):
        return max(1, min(self.cores, self.lane['cores']))

    def report_lane(self):
        p = policy()
        capacity = self.server.capacity if self.server else 0
        model = Path(self.config.get('model') or '')
        base = int(model.stat().st_size) if self.config.get('model') and model.is_file() else None
        self.lane = lanes.report(self.adapter.job_dir, 'translation', capacity,
                                 max(self.extra_bytes, int(p['extra_slot_gib']*GIB)), base,
                                 min(self.cores, p['max_slots'] or self.cores) if p['enabled'] else 1)

    def emit(self, state='RUNNING', health=None, **fields):
        if not self.adapter.job_dir: return
        h = health or pressure(self.config)
        self.last_memory = h
        p = policy()
        atomic_json(Path(self.adapter.job_dir)/'working'/'translation-runtime.json',dict(
            state=state, mode='resource', backend='hy-mt2-gguf', engine='llama-server',
            device=self.config.get('device','cpu'), slots=self.slots,
            allocated_slots=self.server.capacity if self.server else 0,
            threads=self.server.threads if self.server else 0,
            threads_batch=self.server.threads_batch if self.server else 0,
            n_batch=self.server.batch if self.server else 0,
            available_gib=round(h['available']/GIB,2), cpu=round(h['cpu'],1), cpu_target=h['cpu_target'],
            gpu_utilization=h['gpu_utilization'], gpu_target=h['gpu_target'],
            gpu_temperature=h['gpu_temperature'], gpu=h['gpu'],
            thermal_available=h['thermal_available'], hot=h['hot'],
            reserve_gib=h['reserve']/GIB, start_free_gib=p['start_free_gib'],
            extra_slot_gib=max(p['extra_slot_gib'],self.extra_bytes/GIB),
            temperature_limit=p['temperature_limit'], admission_blocked=self.admission_blocked,
            scaling=self.gain.state(), **fields))

    def pause_memory(self, hot=False):
        if not hot and self.yield_wait():
            return
        if self.server: self.server.close()
        if hasattr(self.adapter,'close'): self.adapter.close()
        self.server = None
        self.emit('WAITING_TEMPERATURE' if hot else 'WAITING_MEMORY',required_available_gib=policy()['start_free_gib'])
        if self.adapter.job_dir and not hot and lanes.others_running(self.adapter.job_dir):
            lanes.auto_pause(self.adapter.job_dir, reason='translation_memory_reserve')
        elif self.adapter.job_dir:
            atomic_json(Path(self.adapter.job_dir)/'working'/'cancel.signal',{'mode':'pause','reason':'translation_temperature' if hot else 'translation_memory_reserve'})
        raise Cancelled('Translation paused under resource pressure; model released and checkpoints preserved')

    def yield_wait(self):
        """An earlier workflow waits for later ones to shrink or pause instead of pausing itself."""
        job = self.adapter.job_dir
        need = max(self.extra_bytes, int(policy()['extra_slot_gib']*GIB))
        began = time.monotonic()
        try:
            while lanes.waiting(job, need):
                check_cancel(job)
                h = pressure(self.config)
                if not h['low_memory'] and h['available'] >= 256*1024**2:
                    return True
                if time.monotonic()-began > 10*policy()['observe_seconds']+120:
                    return False
                self.emit('WAITING_MEMORY', health=h, waiting_for_lanes=True)
                time.sleep(2)
            return False
        finally:
            lanes.waiting(job, 0)

    def start(self, threads=None, threads_batch=None, batch=None, capacity=1):
        p = policy()
        threads = min(self.cores,threads or p['threads'] or self.config['threads'])
        threads_batch = min(self.cores,threads_batch or p['threads_batch'] or threads)
        batch = batch or p['n_batch'] or self.config['n_batch']
        if self.server: self.server.close()
        self.server = SharedServer(self.config,self.adapter.job_dir,threads,threads_batch,batch,capacity)
        self.emit('MODEL_LOADING')
        self.server.start()
        self.slots = min(self.slots,capacity)

    def can_expand(self, count, health=None):
        p = policy(); h = health or pressure(self.config)
        maximum = self.lane_maximum()
        extra = max(0,count-self.server.capacity)*max(self.extra_bytes,int(p['extra_slot_gib']*GIB))
        margin = p['safety_gib']*GIB if extra else 0
        gpu_ok = h['gpu'] is None or (h['gpu_utilization'] is not None and
                 h['gpu_utilization'] < h['gpu_target']-5 and
                 h['gpu']['free'] >= p['vram_reserve_gib']*GIB+extra+margin)
        return (p['enabled'] and count<=maximum and not h['hot'] and
                max(h['cpu'],self.observed_cpu)<h['cpu_target']-5 and gpu_ok and
                h['available']>=h['reserve']+extra+margin and
                (h['commit'] is None or h['commit']>=h['reserve']+extra+margin))

    def observe(self):
        current = time.monotonic(); p = policy()
        if current-self.last_observed < p['observe_seconds']: return
        self.last_observed = current
        h = pressure(self.config); self.observed_cpu = h['cpu']
        self.report_lane()
        if self.server:
            self.gain.observe(self.server.capacity)
            if self.gain.verdict() == 'revert' and self.server.capacity > 1:
                # The extra slot was not faster: drop it at the next checkpoint boundary.
                self.slots = self.server.capacity - 1
                self.pending_reduction = self.pending_reduction or self.server.threads
        if self.server and self.server.capacity > self.lane_maximum():
            self.slots = self.lane_maximum()
            self.pending_reduction = self.pending_reduction or self.server.threads
        gpu_busy = h['gpu_utilization'] is not None and h['gpu_utilization'] >= h['gpu_target']
        self.admission_blocked = h['low_memory'] or h['hot']
        if h['available']<256*1024**2 or (h['commit'] is not None and h['commit']<256*1024**2):
            self.pause_memory()
        pressured = h['low_memory'] or h['hot'] or h['cpu']>=h['cpu_target'] or gpu_busy
        if pressured:
            self.healthy_since = None
            self.slots = max(1,self.slots//2)
            reduced = max(1,self.server.threads//2)
            self.pending_reduction = reduced if reduced!=self.server.threads or self.server.capacity!=self.slots else self.pending_reduction
            self.recover_after = current+p['recovery_seconds']
        elif self.can_expand(self.slots+1,h):
            if self.healthy_since is None: self.healthy_since = current
        else: self.healthy_since = None
        self.emit(health=h,throttled=pressured)

    def tune_between_batches(self, tasks):
        # Only resize KV allocation after active requests have checkpointed.
        p = policy(); h = pressure(self.config); current = time.monotonic()
        self.admission_blocked = h['low_memory'] or h['hot']
        if h['low_memory'] and self.server.capacity==1: self.pause_memory()
        if h['hot']:
            self.pause_memory(hot=True)
        maximum = self.lane_maximum()
        if h['low_memory']:
            self.slots = max(1,min(self.slots,self.server.capacity//2))
            self.pending_reduction = self.pending_reduction or max(1,self.server.threads//2)
        desired_threads = min(self.lane_cores(),p['threads'] or self.config['threads'])
        desired_threads_batch = min(self.lane_cores(),p['threads_batch'] or desired_threads)
        desired_batch = p['n_batch'] or self.config['n_batch']
        if self.pending_reduction or self.slots>maximum or self.server.capacity>maximum:
            self.slots = min(self.slots,maximum)
            self.start(self.pending_reduction,self.pending_reduction,self.server.batch,self.slots)
            self.pending_reduction = None
        elif (self.healthy_since is not None and current-self.healthy_since>=p['scale_up_seconds'] and
              current>=self.recover_after and len(tasks)>self.slots and self.can_expand(self.slots+1,h)
              and self.gain.can_try(self.server.capacity)):
            count = self.slots+1
            self.start(desired_threads,desired_threads_batch,desired_batch,count)
            self.slots = count; self.healthy_since = current
            self.gain.begin(count-1)
        elif (current>=self.recover_after and not h['low_memory'] and h['cpu']<h['cpu_target']-5 and
              (self.server.threads!=desired_threads or self.server.threads_batch!=desired_threads_batch or self.server.batch!=desired_batch)):
            self.start(desired_threads,desired_threads_batch,desired_batch,self.slots)
        h = pressure(self.config)
        while h['low_memory'] and self.server.capacity>1:
            self.slots = max(1,self.server.capacity//2)
            self.start(self.server.threads,self.server.threads_batch,self.server.batch,self.slots)
            h = pressure(self.config)
        self.admission_blocked = h['low_memory'] or h['hot']
        if self.admission_blocked: self.pause_memory(hot=h['hot'])
        self.emit(health=h)

    def needs_drain(self):
        """A server resize requires a checkpoint boundary, not a fixed row batch."""
        p = policy()
        current = time.monotonic()
        return bool(self.admission_blocked or self.pending_reduction or
                    self.slots > self.lane_maximum() or
                    (self.server is not None and self.server.capacity > self.lane_maximum()) or
                    (self.healthy_since is not None and current-self.healthy_since >= p['scale_up_seconds']
                     and current >= self.recover_after))

    def close(self):
        if self.server: self.server.close()
