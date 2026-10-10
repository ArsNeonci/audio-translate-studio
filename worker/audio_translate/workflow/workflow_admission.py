"""Read-only Convert preflight. Never imports/starts an inference model."""
import time
import os

import psutil
from audio_translate.transcription.asr_runtime import GIB, hardware, reserve, fingerprint
from audio_translate.core.storage import DATA, read_json
from audio_translate.core.memory_policy import required

TERMINAL = {'COMPLETED', 'FAILED', 'CANCELLED', 'PAUSED', 'PARTIAL', 'DELETING', 'AWAITING_REVIEW'}


def pending_jobs():
    jobs = {}
    for root in (DATA/'tmp', DATA/'jobs', DATA/'tool-tmp'):
        if not root.exists():
            continue
        for directory in root.iterdir():
            source = directory/'job.json'
            if not directory.is_dir() or not source.is_file():
                continue
            job = read_json(source)
            if job.get('status') not in TERMINAL:
                telemetry = directory/'working'/'asr-runtime.json'
                runtime = read_json(telemetry) if telemetry.exists() else {}
                job['_asr_loaded'] = (job.get('status')=='TRANSCRIBING'
                    and runtime.get('state','RUNNING')=='RUNNING')
                jobs.setdefault(job['id'], job)
    return list(jobs.values())


def model_budget(cores):
    # Stages are isolated: reserve for the largest model, including Hy-MT2 GGUF.
    # Hy-MT2-7B Q4_K_M measured 4.77 GiB (no repack) + 1 GiB kept for the OS.
    translation_allocation = int(max(6, float(os.getenv('HY_MT_STARTUP_AVAILABLE_GIB', '6')))*GIB)
    # A profile is useful only for the same hardware/model versions and <=7 days.
    try:
        profile = read_json(DATA/'config'/'asr-autotune.json')
        if (profile['fingerprint'] == fingerprint()
                and 0 <= time.time()-profile['created_at'] < 7*86400
                and profile['peak_bytes'] > 0 and profile['single_threads'] > 0):
            return max(translation_allocation,int(profile['peak_bytes']*1.25)), min(cores,profile['single_threads']), 'measured-asr/estimated-translation'
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return max(translation_allocation,int(2*GIB*1.25)), min(cores, 4), 'estimated'


def assess(snapshot, jobs, allocation, threads, basis='estimated'):
    """Conservative simultaneous-run forecast, not a promise of throughput."""
    count = len(jobs)+1
    kept = reserve(snapshot['total'], parallel=count>1)
    # Current free RAM already excludes resident models. Forecast from total
    # reclaimable application budget AND require free room for the new model.
    unloaded = sum(not job.get('_asr_loaded',False) for job in jobs)
    required_free = max(required(snapshot['total'],allocation,workers=unloaded+1), kept+(unloaded+1)*allocation)
    total_required = max(required(snapshot['total'],allocation,workers=count), kept+count*allocation)
    target = float(os.getenv('ASR_CPU_TARGET','85')) if snapshot['plugged'] else 65
    reasons = []
    if snapshot['available'] < required_free:
        reasons.append(f"RAM trống {snapshot['available']/GIB:.2f} GB; cần dự phòng {required_free/GIB:.2f} GB cho workflow mới và các workflow chưa nạp model (đã giữ {kept/GIB:.2f} GB cho hệ thống).")
    if snapshot.get('commit_available') is not None and snapshot['commit_available'] < (unloaded+1)*allocation+GIB//4:
        reasons.append('Bộ nhớ có thể cấp phát gần giới hạn; cần thêm dung lượng pagefile hoặc giảm tải ứng dụng.')
    if total_required > snapshot['total']:
        reasons.append(f"{count} workflow đồng thời cần dự toán {total_required/GIB:.2f} GB, vượt RAM tổng {snapshot['total']/GIB:.2f} GB.")
    if count*threads > snapshot['physical_cores']:
        reasons.append(f"Dự toán {count*threads} luồng cho {count} workflow, nhưng máy có {snapshot['physical_cores']} lõi CPU vật lý.")
    if snapshot['cpu'] >= target-5:
        reasons.append(f"CPU đang dùng {snapshot['cpu']:.0f}%; chưa có đủ khoảng trống dưới mục tiêu {target}% để thêm tải.")
    if snapshot['hot']:
        reasons.append('Cảm biến báo máy đang nóng; hãy chờ máy giảm nhiệt.')
    return {'allowed':not reasons, 'reasons':reasons, 'existing_workflows':len(jobs),
            'running_workflows':sum(job.get('status')!='QUEUED' for job in jobs),
            'queued_workflows':sum(job.get('status')=='QUEUED' for job in jobs),
            'projected_workflows':count, 'ram_available_gib':round(snapshot['available']/GIB,2),
            'required_available_gib':round(required_free/GIB,2), 'reserve_gib':round(kept/GIB,2),
            'model_allocation_gib':round(allocation/GIB,2), 'cpu_percent':round(snapshot['cpu'],1),
            'physical_cores':snapshot['physical_cores'], 'threads_per_workflow':threads,
            'estimate_basis':basis, 'thermal_available':snapshot['thermal_available'],
            'scheduler_mode':'shared',
            'notice':'Workflow được xếp hàng và chạy song song khi đủ tài nguyên; luồng được chia đều, workflow chạy trước được ưu tiên.'}


def preflight():
    snapshot = hardware()
    # First cpu_percent() without an interval in a fresh CLI is otherwise 0.
    snapshot['cpu'] = psutil.cpu_percent(interval=.25)
    jobs = pending_jobs()
    allocation, threads, basis = model_budget(snapshot['physical_cores'])
    return assess(snapshot, jobs, allocation, threads, basis)


def convert(url, voice=None, queue_only=False, style=None, address=None, mode=None, auto=False, upload=None, input_name=None, mime=''):
    from audio_translate.core.license_gate import assert_allowed
    from audio_translate.core.storage import file_lock
    from audio_translate.workflow.manage import create
    assert_allowed()
    # Check + create serialized across tabs/processes, not merely a browser check.
    with file_lock(DATA/'management-locks'/'convert-admission.lock'):
        # The lane broker admits queued workflows when resources allow; Convert only queues.
        assessment = preflight()
        source = {'upload':upload,'input_name':input_name,'mime':mime} if upload else {}
        job = create(url, voice, style=style, address=address, mode=mode, auto=auto, **source)
        return {'status':200, 'job':job, 'assessment':assessment}
