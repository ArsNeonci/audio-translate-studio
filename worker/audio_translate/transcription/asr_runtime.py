"""CPU admission, measured tuning and single-writer ASR coordination."""
import hashlib
import importlib.metadata
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import statistics
import subprocess
import threading
import time

import psutil
from audio_translate.core.control import check_cancel, stop_mode
from audio_translate.core import lanes
from audio_translate.core.storage import DATA, atomic_json, read_json, file_lock
from audio_translate.core.memory_policy import reserve, required, fits, commit_available, settings, worker_limit

GIB = 1024 ** 3
PROFILE = DATA/'config'/'asr-autotune.json'


def hardware():
    memory = psutil.virtual_memory()
    battery = psutil.sensors_battery()
    try:
        temperatures = getattr(psutil, 'sensors_temperatures', lambda: {})()
    except (OSError, NotImplementedError):
        temperatures = {}
    hot = any(item.current >= float(os.getenv('ASR_TEMP_LIMIT', '85'))
              for group in temperatures.values() for item in group)
    return {'physical_cores':psutil.cpu_count(logical=False) or 1,
            'logical_cores':psutil.cpu_count() or 1, 'total':memory.total,
            'available':memory.available, 'commit_available':commit_available(), 'cpu':psutil.cpu_percent(),
            'plugged':battery is None or battery.power_plugged, 'hot':hot,
            'thermal_available':bool(temperatures)}


def may_add(snapshot, peak, loaded_workers=0):
    target = float(os.getenv('ASR_CPU_TARGET', '85')) if snapshot['plugged'] else 65
    return (not snapshot['hot'] and snapshot['cpu'] < target - 5
            and fits(snapshot, peak, parallel=True, workers=max(2,loaded_workers+1),loaded_workers=loaded_workers))


def wait_memory(job_dir, peak, state):
    from audio_translate.core.control import now
    from audio_translate.transcription.transcription_progress import memory_wait
    began = time.monotonic()
    started = now()
    timeout = max(10, float(os.getenv('ASR_MEMORY_WAIT_SECONDS', '120')))
    waiting = False
    try:
        while True:
            check_cancel(job_dir)
            snapshot=hardware()
            if fits(snapshot, peak):
                lanes.waiting(job_dir, 0)
                return
            keep_waiting = lanes.waiting(job_dir, peak)
            if not waiting:
                memory_wait(job_dir, started)
                waiting = True
            waited = time.monotonic()-began
            atomic_json(Path(job_dir)/'working'/'asr-runtime.json', {'state':'WAITING_MEMORY',
                'phase':state,'workers':0,'threads':0,'wait_started_at':started,
                'wait_seconds':round(waited,1),'wait_timeout_seconds':timeout,
                'ram_available_gib':round(snapshot['available']/GIB,2),
                'required_available_gib':round(required(snapshot['total'], peak)/GIB,2),
                'commit_available_gib':round(snapshot['commit_available']/GIB,2) if snapshot.get('commit_available') is not None else None})
            if waited >= timeout and keep_waiting:
                pass  # later workflows are shrinking or pausing for this one
            elif waited >= timeout and lanes.others_running(job_dir):
                lanes.auto_pause(job_dir, reason='memory_timeout')
                check_cancel(job_dir)
            elif waited >= timeout:
                update_job_reason = 'Thiếu RAM sau thời gian chờ; đã dừng tạm và giữ checkpoint. Có thể tiếp tục khi RAM khả dụng tăng.'
                from audio_translate.core.storage import update_job
                update_job(job_dir, memory_pause_reason=update_job_reason)
                atomic_json(Path(job_dir)/'working'/'cancel.signal', {'mode':'pause','reason':'memory_timeout'})
                check_cancel(job_dir)
            time.sleep(2)
    finally:
        if waiting:
            memory_wait(job_dir, None, int((time.monotonic()-began)*1000))


def checkpoint(path):
    try:
        rows = read_json(path)
        return isinstance(rows, list) and all(isinstance(row, dict)
            and isinstance(row.get('text'), str) and type(row.get('start_ms')) is int
            and type(row.get('end_ms')) is int and row['end_ms'] >= row['start_ms'] for row in rows)
    except (OSError, ValueError):
        return False


def model(threads):
    os.environ['OMP_NUM_THREADS'] = str(threads)
    os.environ['MKL_NUM_THREADS'] = str(threads)
    import torch
    torch.set_num_threads(threads)
    torch.set_num_interop_threads(1)
    from funasr import AutoModel
    from audio_translate.transcription.pipeline import model_reference, MAX_CHUNK_MS
    return AutoModel(model=model_reference('paraformer-zh'), vad_model=model_reference('fsmn-vad'),
                     punc_model=model_reference('ct-punc'), ncpu=threads,
                     vad_kwargs={'max_single_segment_time':MAX_CHUNK_MS, 'ncpu':threads},
                     punc_kwargs={'ncpu':threads}, device='cpu', disable_update=True,
                     disable_pbar=True, trust_remote_code=False)


def recognize(engine, audio, chunk, index, total, threads):
    from audio_translate.transcription.pipeline import RATE, clean_text
    if not len(audio):
        raise ValueError(f'Empty audio chunk {index}')
    result = engine.generate(input=audio, fs=RATE, batch_size_s=30,
                             batch_size_threshold_s=30, sentence_timestamp=True, ncpu=threads)
    item = result[0] if result else {}
    sentences = item.get('sentence_info') or []
    if not sentences and clean_text(item.get('text', '')):
        stamps = item.get('timestamp') or []
        sentences = [{'start':stamps[0][0] if stamps else 0,
                      'end':stamps[-1][1] if stamps else len(audio)*1000//RATE, 'text':item['text']}]
    rows = []
    for sentence in sentences:
        text = clean_text(sentence.get('text', ''))
        if not text:
            continue
        start = chunk['start'] + int(sentence['start'])
        end = chunk['start'] + int(sentence['end'])
        if chunk['own_start'] <= (start + end)/2 < chunk['own_end'] + (index == total - 1):
            rows.append({'start_ms':max(0,start), 'end_ms':max(start,end), 'text':text})
    return sorted(rows, key=lambda row:(row['start_ms'],row['end_ms']))


def peak_memory():
    info = psutil.Process().memory_info()
    return max(info.rss, getattr(info, 'peak_wset', 0))


def worker(connection, job_dir, threads, fake=False):
    """Only writes its assigned chunk; never job.json, telemetry or model globals."""
    try:
        engine = None if fake else model(threads)
        connection.send(('ready', peak_memory()))
        while True:
            task = connection.recv()
            if task[0] == 'stop':
                return
            _, index, audio, chunk, total, ncpu, publish = task
            began = time.monotonic()
            if fake:
                if chunk.get('test_fail'): raise RuntimeError('Simulated inference failure')
                time.sleep(chunk.get('test_delay', 0))
                rows = [{'start_ms':chunk['own_start'], 'end_ms':chunk['own_end'], 'text':str(index)}]
            else:
                rows = recognize(engine, audio, chunk, index, total, ncpu)
            if publish:
                atomic_json(Path(job_dir)/'working'/f'chunk-{index:06d}.json', rows)
            connection.send(('done', index, rows if not publish else None,
                             time.monotonic()-began, peak_memory()))
    except BaseException as exc:
        try:
            connection.send(('error', type(exc).__name__, str(exc)[:1000]))
        except (OSError, EOFError):
            pass
    finally:
        connection.close()


class Pool:
    def __init__(self, job_dir, threads, count=1, fake=False):
        self.context = mp.get_context('spawn')
        self.job_dir, self.fake = str(job_dir), fake
        self.members = []
        self.peak = 0
        self.add(threads, count)

    def add(self, threads, count=1):
        for _ in range(count):
            parent, child = self.context.Pipe()
            process = self.context.Process(target=worker, args=(child,self.job_dir,threads,self.fake))
            process.start(); child.close()
            self.members.append({'process':process,'pipe':parent,'pending':None,'ready':False,'retire':False,'started':time.monotonic()})

    def receive(self, member):
        try:
            result = member['pipe'].recv()
        except (EOFError, OSError):
            raise RuntimeError('ASR worker exited unexpectedly') from None
        if result[0] == 'error':
            raise RuntimeError(f'ASR worker {result[1]}: {result[2]}')
        if result[0] == 'ready':
            member['ready'] = True
            self.peak = max(self.peak,result[1])
        elif result[0] == 'done':
            if member['pending'] != result[1]:
                raise RuntimeError('ASR result does not match assigned chunk')
            member['pending'] = None
            self.peak = max(self.peak,result[4])
        return result

    def submit(self, member, task):
        if member['pending'] is not None:
            raise RuntimeError('Worker already has a task')
        member['pending'] = task[1]
        member['pipe'].send(task)

    def remove(self, member):
        member['pipe'].send(('stop',))
        member['process'].join(10)
        if member['process'].is_alive():
            member['process'].terminate(); member['process'].join(5)
        member['pipe'].close()
        self.members.remove(member)

    def close(self):
        # Let current inference finish and commit its checkpoint before stopping.
        for member in self.members[:]:
            try:
                member['pipe'].send(('stop',))
                deadline = time.monotonic()+120
                while member['process'].is_alive() and (time.monotonic()<deadline or
                        (member['pending'] is not None and stop_mode(self.job_dir)=='pause')):
                    if member['pipe'].poll(.2):
                        try:
                            message=member['pipe'].recv()
                            if message[0]=='done':member['pending']=None
                        except EOFError: break
                    else: member['process'].join(.2)
                if member['process'].is_alive():
                    member['process'].terminate(); member['process'].join(5)
            except (OSError, EOFError):
                member['process'].join(2)
            finally:
                member['pipe'].close()
        self.members.clear()


def sample_audio(source, chunks, indices):
    """Small seek-based calibration only. Main inference uses one stream decoder."""
    import numpy as np
    from audio_translate.transcription.pipeline import RATE
    samples = []
    for index in indices:
        chunk = chunks[index]
        result = subprocess.run(['ffmpeg','-nostdin','-v','error','-ss',str(chunk['start']/1000),
            '-i',str(source),'-t',str((chunk['end']-chunk['start'])/1000),'-ac','1','-ar',str(RATE),
            '-f','s16le','-'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        audio = np.frombuffer(result.stdout,dtype='<i2').astype(np.float32)/32768
        if len(audio): samples.append((index,audio,chunk))
    return samples


def fingerprint():
    from audio_translate.transcription.pipeline import model_reference
    identity = {'version':1, 'cpu':os.getenv('PROCESSOR_IDENTIFIER',''),
                'cores':psutil.cpu_count(logical=False),
                'versions':{name:importlib.metadata.version(name) for name in ('funasr','torch')},
                'models':[]}
    for alias in ('paraformer-zh','fsmn-vad','ct-punc'):
        path = Path(model_reference(alias))
        identity['models'].append([str(path), [(file.name,file.stat().st_size,file.stat().st_mtime_ns)
            for file in (path/'model.pt',path/'config.yaml') if file.exists()]])
    return hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()


def same_output(left, right):
    return len(left)==len(right) and all(a['text']==b['text'] and
        abs(a['start_ms']-b['start_ms'])<=30 and abs(a['end_ms']-b['end_ms'])<=30
        for a,b in zip(left,right))


def measure(job_dir, samples, total, workers, threads, baseline=None, fake=False, observe=None, stagger_load=False):
    if observe: observe('loading')
    lanes.report(job_dir,'transcription',workers,2*GIB,None,workers)  # calibration pools hold RAM too
    pool = Pool(job_dir,threads,1 if stagger_load else workers,fake)
    try:
        # Every worker warms up before timed rounds. No calibration writes checkpoints.
        deadline = time.monotonic()+180
        while not all(member['ready'] for member in pool.members):
            check_cancel(job_dir)
            if time.monotonic()>deadline: raise TimeoutError('ASR model startup timed out')
            for member in pool.members:
                if member['pipe'].poll(.05): pool.receive(member)
                elif not member['process'].is_alive(): raise RuntimeError('ASR model failed to start')
        if observe: observe('warmup')
        for member in pool.members:
            index,audio,chunk = samples[0]
            pool.submit(member,('infer',index,audio,chunk,total,threads,False))
        while any(member['pending'] is not None for member in pool.members):
            check_cancel(job_dir)
            for member in pool.members:
                if member['pipe'].poll(.05): pool.receive(member)
        if stagger_load:
            # Match incremental runtime expansion: warm the existing worker before
            # loading another model, avoiding simultaneous startup allocations.
            while len(pool.members) < workers:
                if observe: observe('loading')
                pool.add(threads)
                member = pool.members[-1]
                deadline = time.monotonic()+180
                while not member['ready']:
                    check_cancel(job_dir)
                    if time.monotonic()>deadline: raise TimeoutError('ASR model startup timed out')
                    if member['pipe'].poll(.05): pool.receive(member)
                    elif not member['process'].is_alive(): raise RuntimeError('ASR model failed to start')
                if observe: observe('warmup')
                index,audio,chunk = samples[0]
                pool.submit(member,('infer',index,audio,chunk,total,threads,False))
                while member['pending'] is not None:
                    check_cancel(job_dir)
                    if member['pipe'].poll(.05): pool.receive(member)
                    elif not member['process'].is_alive(): raise RuntimeError('ASR worker crashed during warmup')
        if observe: observe('inference')
        durations, outputs = [], {}
        for _ in range(2):
            pending = iter(samples); remaining = len(samples); began = time.monotonic()
            while remaining:
                check_cancel(job_dir)
                for member in pool.members:
                    if member['pending'] is None:
                        item = next(pending,None)
                        if item:
                            index,audio,chunk=item
                            pool.submit(member,('infer',index,audio,chunk,total,threads,False))
                    if member['pipe'].poll(.01):
                        result = pool.receive(member)
                        if result[0]=='done': outputs[result[1]]=result[2]; remaining-=1
                    elif not member['process'].is_alive(): raise RuntimeError('ASR worker crashed during calibration')
            durations.append(time.monotonic()-began)
        compatible = baseline is None or all(same_output(outputs[index],rows) for index,rows in baseline.items())
        return {'workers':workers,'threads':threads,'seconds':statistics.median(durations),
                'peak_bytes':pool.peak,'compatible':compatible}, outputs
    finally:
        if observe: observe('shutdown')
        pool.close()


def tune(job_dir, source, chunks, force=False):
    key = fingerprint()
    with file_lock(DATA/'config'/'asr-autotune.lock'):
        if not force and PROFILE.exists():
            try:
                cached=read_json(PROFILE)
            except (OSError, ValueError):
                cached={}
            if isinstance(cached,dict) and cached.get('fingerprint')==key and time.time()-cached.get('created_at',0)<7*86400:
                return cached
        wait_memory(job_dir,2*GIB,'CALIBRATION')
        # Measuring beside another workflow is memory-hungry and biased by its load.
        if not fits(hardware(), 2*GIB, parallel=True) or lanes.others_running(job_dir):
            # Defer benchmarking while memory is scarce; start actual recognition.
            return {'single_threads':min(4,hardware()['physical_cores']), 'workers':1,
                    'threads':min(4,hardware()['physical_cores']), 'peak_bytes':2*GIB,
                    'tuning_deferred':True}
        atomic_json(Path(job_dir)/'working'/'asr-runtime.json',{'state':'CALIBRATING','workers':1,'threads':4})
        indices=sorted(set((0,len(chunks)//2,len(chunks)-1)))
        samples=sample_audio(source,chunks,indices)
        if not samples: raise ValueError('No audio available for ASR calibration')
        benchmarks=[]; baseline=None
        cores=hardware()['physical_cores']
        for threads in sorted(set(min(cores,n) for n in (4,6,8))):
            wait_memory(job_dir,max((score['peak_bytes'] for score in benchmarks),default=2*GIB),'CALIBRATION')
            score,outputs=measure(job_dir,samples,len(chunks),1,threads,baseline)
            benchmarks.append(score)
            if baseline is None: baseline=outputs
            print(f'CPU benchmark: {score}',flush=True)
        single=min((score for score in benchmarks if score['compatible']),key=lambda score:score['seconds'])
        best=single
        if cores>=6 and may_add(hardware(),single['peak_bytes']*2):
            score,_=measure(job_dir,samples,len(chunks),2,3,baseline)
            benchmarks.append(score)
            print(f'CPU pool benchmark: {score}',flush=True)
            if score['compatible'] and score['seconds']<single['seconds']: best=score
        profile={'fingerprint':key,'created_at':time.time(),'benchmarks':benchmarks,
                 'single_threads':single['threads'],'workers':best['workers'],'threads':best['threads'],
                 'peak_bytes':max(score['peak_bytes'] for score in benchmarks),
                 'speedup':single['seconds']/best['seconds']}
        atomic_json(PROFILE,profile)
        return profile


def run(job_dir, source, chunks, profile=None, fake=False, producer_override=None):
    from audio_translate.transcription.pipeline import decoder, audio_piece, update
    from audio_translate.transcription.transcription_progress import report
    from audio_translate.core.storage import progress
    working=job_dir/'working'
    done={index for index in range(len(chunks)) if checkpoint(working/f'chunk-{index:06d}.json')}
    if not chunks or len(done)==len(chunks):
        update(job_dir,status='TRANSCRIBING',chunks_total=len(chunks),chunks_done=len(done),processed_ms=sum(c['own_end']-c['own_start'] for c in chunks))
        return
    update(job_dir,status='TRANSCRIBING',chunks_total=len(chunks),chunks_done=len(done))
    if profile is None:
        mode=os.getenv('ASR_CPU_MODE','auto')
        if mode not in ('auto','manual'): raise ValueError('ASR_CPU_MODE must be auto or manual')
        if mode=='auto': profile=tune(job_dir,source,chunks)
        else:
            threads=max(1,min(hardware()['physical_cores'],int(os.getenv('ASR_CPU_THREADS',os.getenv('AI_NUM_THREADS','4')))))
            profile={'single_threads':threads,'threads':threads,'workers':max(1,min(hardware()['physical_cores'],int(os.getenv('ASR_CPU_WORKERS','1')))), 'peak_bytes':2*GIB}
    maximum=min(settings()['max_workers'] or hardware()['physical_cores'],hardware()['physical_cores'])
    if os.getenv('ASR_CPU_MODE','auto')=='manual': maximum=min(maximum,profile['workers'])
    multi_threads=min(profile['threads'],max(1,hardware()['physical_cores']//maximum))
    if not fake: wait_memory(job_dir,profile['peak_bytes'],'INFERENCE')
    pool=Pool(job_dir,profile['single_threads'],fake=fake)
    stop=threading.Event(); feed=queue.Queue(maxsize=max(2,maximum*2))
    decode=None
    def put(item):
        while not stop.is_set():
            try: feed.put(item,timeout=.1); return
            except queue.Full: pass
    def produce():
        nonlocal decode
        try:
            if producer_override:
                for index,audio,chunk in producer_override(): put(('audio',index,audio,chunk))
            else:
                decode=decoder(source);cursor=0;tail=b''
                for index,chunk in enumerate(chunks):
                    if stop.is_set(): return
                    audio,cursor,tail=audio_piece(decode.stdout,cursor,tail,chunk['start'],chunk['end'])
                    if index not in done: put(('audio',index,audio,chunk))
                # The source may contain trailing silence beyond the last chunk.
                # Do not wait for a blocked full stdout pipe: cleanup terminates it.
            put(('end',))
        except BaseException as exc:
            put(('error',exc))
    reader=threading.Thread(target=produce,daemon=True);reader.start()
    completed_ms=sum(chunks[i]['own_end']-chunks[i]['own_start'] for i in done)
    total_ms=sum(c['own_end']-c['own_start'] for c in chunks)
    lane_cores=hardware()['physical_cores']
    peak=profile['peak_bytes']; ended=False; last_control=0; healthy_since=None; pause=False
    window_start=time.monotonic();window_audio=0;single_rate=None;trial_started=None;pool_disabled=False;primed=False
    def publish():
        update(job_dir,status='TRANSCRIBING',chunks_total=len(chunks),chunks_done=len(done),processed_ms=completed_ms)
        # Out-of-order completion uses totals, never max chunk index/end timestamp.
        progress(job_dir,'transcription','TRANSCRIBING',len(done),len(chunks))
        report(job_dir,3,len(done),len(chunks))
    try:
        publish()
        while not ended or any(member['pending'] is not None for member in pool.members):
            check_cancel(job_dir)
            current=time.monotonic()
            if current-last_control>=2:
                snapshot=hardware();last_control=current
                maximum=min(settings()['max_workers'] or snapshot['physical_cores'],snapshot['physical_cores'])
                if os.getenv('ASR_CPU_MODE','auto')=='manual': maximum=min(maximum,profile['workers'])
                lane=lanes.report(job_dir,'transcription',len(pool.members),peak,None,maximum)
                maximum=max(1,min(maximum,lane['target']))
                lane_cores=max(1,min(snapshot['physical_cores'],lane['cores']))
                multi_threads=min(profile['threads'],max(1,lane_cores//max(1,min(maximum,len(pool.members)+1))))
                for member in pool.members[maximum:]: member['retire']=True
                target=float(os.getenv('ASR_CPU_TARGET','85')) if snapshot['plugged'] else 65
                pressure=snapshot['hot'] or snapshot['available']<reserve(snapshot['total'], parallel=len(pool.members)>1) or snapshot['cpu']>target
                if pressure:
                    healthy_since=None
                    for member in pool.members[1:]: member['retire']=True
                elif (all(member['ready'] and not member['retire'] for member in pool.members)
                      and len(pool.members)<worker_limit(snapshot['available'],len(pool.members))
                      and may_add(snapshot,peak,loaded_workers=len(pool.members))):
                    healthy_since=healthy_since or current
                    if current-healthy_since>=float(os.getenv('ASR_SCALE_UP_SECONDS','10')) and len(pool.members)<maximum and not ended and not pool_disabled and (fake or single_rate is not None):
                        pool.add(multi_threads);healthy_since=current;trial_started=current
                else: healthy_since=None
                if current-window_start>=30 and window_audio:
                    rate=window_audio/(current-window_start)
                    if len(pool.members)==1: single_rate=rate
                    elif single_rate and trial_started and current-trial_started>=60 and rate<=single_rate:
                        pool_disabled=True
                        for member in pool.members[1:]: member['retire']=True
                    window_start=current;window_audio=0
                reduced_threads=pressure or not snapshot['plugged']
                display_threads=multi_threads if len(pool.members)>1 else profile['single_threads']
                if reduced_threads:display_threads=max(1,display_threads//2)
                atomic_json(working/'asr-runtime.json',{'state':'RUNNING','mode':os.getenv('ASR_CPU_MODE','auto'),
                    'workers':sum(not member['retire'] for member in pool.members),
                    'threads':display_threads,
                    'cpu_percent':snapshot['cpu'],'ram_available_gib':round(snapshot['available']/GIB,2),
                    'reserve_gib':round(reserve(snapshot['total'], parallel=len(pool.members)>1)/GIB,2),
                    'ram_worker_limit':worker_limit(snapshot['available'],len(pool.members)),
                    'start_free_gib':settings()['start_free_gib'],
                    'extra_worker_gib':settings()['extra_worker_gib'],
                    'tuning_deferred':profile.get('tuning_deferred',False),
                    'thermal_available':snapshot['thermal_available'],'throttled':pressure,
                    'pool_disabled_no_gain':pool_disabled,'done':len(done),'total':len(chunks)})
                # Severe pressure also pauses new work on the last worker. Its
                # current task can complete/checkpoint; cancellation remains responsive.
                pause=snapshot['hot'] or snapshot['available']<512*1024**2
            for member in pool.members[:]:
                if member['pipe'].poll(.01):
                    result=pool.receive(member)
                    peak=max(peak,pool.peak)
                    if result[0]=='ready' and len(pool.members)>1: trial_started=time.monotonic()
                    if result[0]=='done':
                        index=result[1]
                        if not checkpoint(working/f'chunk-{index:06d}.json'): raise ValueError('Invalid ASR checkpoint')
                        if index not in done:
                            if not primed:window_start=time.monotonic();primed=True
                            done.add(index);milliseconds=chunks[index]['own_end']-chunks[index]['own_start'];completed_ms+=milliseconds;window_audio+=milliseconds;publish()
                elif not member['process'].is_alive(): raise RuntimeError('ASR worker crashed; completed checkpoints preserved')
                elif not member['ready'] and time.monotonic()-member['started']>180:
                    if member is pool.members[0]:raise TimeoutError('ASR model startup timed out')
                    member['retire']=True;member['ready']=True;pool_disabled=True
                if member['retire'] and member['pending'] is None and member['ready']:
                    pool.remove(member);continue
                if member['ready'] and member['pending'] is None and not ended and not pause and not member['retire']:
                    try: item=feed.get_nowait()
                    except queue.Empty: continue
                    if item[0]=='error': raise item[1]
                    if item[0]=='end': ended=True;continue
                    _,index,audio,chunk=item
                    ncpu=multi_threads if len(pool.members)>1 else min(profile['single_threads'],lane_cores)
                    if reduced_threads: ncpu=max(1,ncpu//2)
                    check_cancel(job_dir)
                    pool.submit(member,('infer',index,audio,chunk,len(chunks),ncpu,True))
            if ended and not any(m['pending'] is not None for m in pool.members): break
        if len(done)!=len(chunks): raise RuntimeError('ASR ended with missing chunks; checkpoints preserved')
    finally:
        stop.set()
        if decode is not None and decode.poll() is None: decode.kill();decode.wait()
        reader.join(3)
        pool.close()
        if (working/'cancel.signal').exists():
            # Drained workers can have committed after cancellation was detected.
            done={i for i in range(len(chunks)) if checkpoint(working/f'chunk-{i:06d}.json')}
            completed_ms=sum(chunks[i]['own_end']-chunks[i]['own_start'] for i in done)
            publish()


def main():
    import argparse
    from audio_translate.core.license_gate import assert_allowed
    from audio_translate.transcription.pipeline import source_file
    parser=argparse.ArgumentParser();parser.add_argument('--benchmark-job',type=Path,required=True)
    args=parser.parse_args()
    os.environ.setdefault('MODELSCOPE_CACHE',str(DATA/'model-cache'))
    os.environ.setdefault('HF_HOME',str(DATA/'hf-cache'))
    assert_allowed()
    # Calibration reads source/chunk boundaries only; cannot resume or publish jobs.
    chunks=read_json(args.benchmark_job/'working'/'chunks.json')
    import tempfile
    (DATA/'verification').mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='asr-benchmark-',dir=DATA/'verification') as folder:
        # A cancelled job's cancel.signal must not cancel this isolated,
        # explicitly requested calibration. It never touches that job's state.
        control=Path(folder);(control/'working').mkdir()
        profile=tune(control,source_file(args.benchmark_job),chunks,force=True)
    print(json.dumps(profile,ensure_ascii=False),flush=True)


if __name__=='__main__': main()
