"""Measured CPU TTS pool. Workers write temporary WAVs; parent commits checkpoints."""
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace

import psutil
from audio_translate.core.control import Cancelled, check_cancel, stop_mode
from audio_translate.core import lanes
from audio_translate.core.scaling import GainTrial
from audio_translate.core.storage import ROOT, DATA, atomic_json, digest, file_digest, read_json, file_lock, LockedError

GIB = 1024 ** 3
_cpu_sample_at = 0
_cpu_sample = 0


class TrialPressure(RuntimeError):
    pass
# Workers grow +1 after `scale_up_seconds` of healthy resources and are kept only if
# measured throughput rises (core/scaling.py). There is no up-front calibration.
DEFAULTS = dict(enabled=True, threads=0, max_workers=0, cpu_target=85,
                temperature_limit=85, reserve_gib=1.5, initial_worker_gib=1.5,
                observe_seconds=10, memory_wait_seconds=120, scale_up_seconds=10,
                gain_window_seconds=30, retry_seconds=600,
                cache_enabled=True, cache_max_gib=1., cache_max_entries=1000)


def policy():
    path = Path(os.getenv('TTS_RUNTIME_CONFIG', ROOT/'worker'/'config'/'tts-runtime.json'))
    value = {**DEFAULTS, **(json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {})}
    for key in ('enabled','cache_enabled'):
        if type(value[key]) is not bool: raise ValueError(f'Invalid TTS {key}')
    for key in ('threads','max_workers','cache_max_entries'):
        if type(value[key]) is not int or value[key] < (1 if key=='cache_max_entries' else 0):
            raise ValueError(f'Invalid TTS {key}')
    for key in ('cpu_target','temperature_limit','reserve_gib','initial_worker_gib','observe_seconds','memory_wait_seconds',
                'scale_up_seconds','gain_window_seconds','retry_seconds','cache_max_gib'):
        if isinstance(value[key],bool) or not isinstance(value[key],(float,int)) or not math.isfinite(value[key]) or value[key] <= 0:
            raise ValueError(f'Invalid TTS {key}')
    if value['cpu_target']>100: raise ValueError('Invalid TTS cpu_target')
    return value


def hardware():
    global _cpu_sample_at, _cpu_sample
    from audio_translate.core.memory_policy import commit_available
    p=policy();battery=psutil.sensors_battery()
    target=min(p['cpu_target'],65) if battery and not battery.power_plugged else p['cpu_target']
    try: temperatures=getattr(psutil,'sensors_temperatures',lambda:{})()
    except (OSError,NotImplementedError): temperatures={}
    if time.monotonic()-_cpu_sample_at>=1:
        _cpu_sample=psutil.cpu_percent(interval=None);_cpu_sample_at=time.monotonic()
    return dict(available=psutil.virtual_memory().available, commit=commit_available(),
                cpu=_cpu_sample, target=target,
                cores=psutil.cpu_count(logical=False) or 1,
                hot=any(t.current>=p['temperature_limit'] for group in temperatures.values() for t in group))


def provider_signature(config):
    from audio_translate.core.providers import vieneu_source
    source=vieneu_source(config['source'])/'src'
    # Invalidate content cache/profile on provider code or cached weight revision changes.
    sha=hashlib.sha256()
    for path in sorted(source.rglob('*.py')):
        sha.update(str(path.relative_to(source)).encode());sha.update(path.read_bytes())
    hub=Path(os.getenv('HF_HOME',str(DATA/'hf-cache')))/'hub'
    for path in sorted(hub.glob('models--*/refs/*')):
        if path.is_file():sha.update(str(path).encode());sha.update(path.read_bytes())
    return sha.hexdigest()


def worker(pipe, job_dir, config, threads, fake):
    os.environ.update(AUDIO_ACTIVE_JOB=str(job_dir),AI_NUM_THREADS=str(threads),OMP_NUM_THREADS=str(threads),MKL_NUM_THREADS=str(threads))
    try:
        directory=Path(job_dir)/'working';directory.mkdir(parents=True,exist_ok=True)
        log=(directory/f'tts-worker-{os.getpid()}.log').open('a',encoding='utf-8')
        sys.stdout=sys.stderr=log
        if fake: adapter=None
        else:
            from audio_translate.tts.adapters import TTSAdapter
            adapter=TTSAdapter(config,threads=threads);adapter.load()
        process=psutil.Process()
        pipe.send(('ready',process.memory_info().rss))
        while True:
            message=pipe.recv()
            if message[0]=='stop':return
            _,index,text,path=message
            began=time.monotonic()
            if fake:
                from audio_translate.core.control import complete_task
                @complete_task
                def render():
                    import numpy as np
                    import soundfile as sf
                    if text.startswith('FAIL'):raise RuntimeError('simulated TTS failure')
                    if text.startswith('SLOW'):time.sleep(.15)
                    if text.startswith('PAUSE'):
                        time.sleep(.1);atomic_json(Path(job_dir)/'working'/'cancel.signal',dict(mode='pause'))
                    sf.write(path,np.full(480,.05,dtype=np.float32),48000,format='WAV',subtype='PCM_16')
                render()
            else:adapter.synthesize(text,path)
            pipe.send(('done',index,time.monotonic()-began,process.memory_info().rss))
    except BaseException as exc:
        try:pipe.send(('error',type(exc).__name__,str(exc)[:1000]))
        except (OSError,EOFError):pass
    finally:pipe.close()


class Pool:
    def __init__(self, job_dir, config, fake=False):
        self.job_dir,self.config,self.fake=str(job_dir),config,fake
        self.context=mp.get_context('spawn');self.members=[];self.peak=0
    def add(self, threads):
        parent,child=self.context.Pipe()
        process=self.context.Process(target=worker,args=(child,self.job_dir,self.config,threads,self.fake),daemon=True)
        process.start();child.close()
        member=dict(process=process,pipe=parent,threads=threads,pending=None,ready=False,job=None,started=time.monotonic())
        self.members.append(member)
        if os.name=='nt':
            from audio_translate.translation.translation_server import windows_job
            try:member['job']=windows_job(SimpleNamespace(_handle=process._popen._handle))
            except BaseException:self.close();raise
        return member
    def receive(self, member):
        try:message=member['pipe'].recv()
        except (OSError,EOFError):raise RuntimeError('TTS worker exited unexpectedly') from None
        if message[0]=='error':
            if message[1]=='Cancelled':raise Cancelled(message[2])
            raise RuntimeError(f'TTS worker {message[1]}: {message[2]}')
        if message[0]=='ready':member['ready']=True;self.peak=max(self.peak,message[1])
        if message[0]=='done':
            if member['pending'] is None or member['pending'][0]!=message[1]:raise RuntimeError('TTS worker returned wrong row')
            self.peak=max(self.peak,message[3])
        return message
    def remove(self,member):
        if member['pending'] is not None:raise RuntimeError('Cannot retire a busy TTS worker')
        try:
            if member['process'].is_alive():member['pipe'].send(('stop',))
        except (OSError,EOFError):pass
        member['process'].join(2)
        if member['process'].is_alive():member['process'].terminate();member['process'].join(2)
        member['pipe'].close()
        if member['job']:member['job'][0].CloseHandle(member['job'][1])
        self.members.remove(member)
    def close(self):
        for member in self.members[:]:
            member['pending']=None;self.remove(member)


class ContentCache:
    def __init__(self, config, signature):
        self.config,self.signature=config,signature
        self.directory=DATA/'tts-cache';self.stores=0
    def key(self,text):return digest([self.config,self.signature,text,'tts-content-v1'])
    def get(self,text,target):
        if not policy()['cache_enabled']:return False
        key=self.key(text);wav=self.directory/(key+'.wav');meta=self.directory/(key+'.json')
        try:
            saved=read_json(meta)
            if file_digest(wav)!=saved['sha256']:return False
            from audio_translate.workflow.postprocess import audio_info
            if audio_info(wav)!=saved['frames']:return False
            shutil.copyfile(wav,target);meta.touch();return True
        except (OSError,ValueError,KeyError,json.JSONDecodeError):return False
    def put(self,text,source):
        p=policy()
        if not p['cache_enabled'] or source.stat().st_size>p['cache_max_gib']*GIB:return
        self.directory.mkdir(parents=True,exist_ok=True)
        key=self.key(text);target=self.directory/(key+'.wav');meta=self.directory/(key+'.json')
        try:
            with file_lock(self.directory/'cache.lock'):
                temporary=target.with_suffix('.wav.tmp')
                try:
                    shutil.copyfile(source,temporary);os.replace(temporary,target)
                    from audio_translate.workflow.postprocess import audio_info
                    atomic_json(meta,dict(sha256=file_digest(target),frames=audio_info(target)))
                finally:temporary.unlink(missing_ok=True)
                self.stores+=1
                if self.stores%16==1:self.trim()
        except (LockedError,OSError):pass  # Cache is optional; job WAV is already durable.
    def trim(self):
        p=policy();entries=sorted(self.directory.glob('*.json'),key=lambda path:path.stat().st_mtime)
        total=sum(path.with_suffix('.wav').stat().st_size for path in entries if path.with_suffix('.wav').exists())
        while entries and (total>p['cache_max_gib']*GIB or len(entries)>p['cache_max_entries']):
            meta=entries.pop(0);wav=meta.with_suffix('.wav')
            if wav.exists():total-=wav.stat().st_size;wav.unlink(missing_ok=True)
            meta.unlink(missing_ok=True)


class Runtime:
    def __init__(self,job_dir,config,fake=False):
        self.job_dir,self.config,self.fake=Path(job_dir),config,fake
        self.pool=Pool(job_dir,config,fake);self.signature='fake' if fake else provider_signature(config)
        self.cache=ContentCache(config,self.signature)
        job=read_json(self.job_dir/'job.json')
        self.cache_allowed=not job.get('reprocess_pending') and job.get('retry_step')!='TTS'
        self.selected=None;self.last_observed=0;self.worker_bytes=int(policy()['initial_worker_gib']*GIB)
        p=policy();self.gain=GainTrial(p['gain_window_seconds'],p['retry_seconds']);self.healthy_since=None;self.loading=None
        self.last_cpu=0;self.cache_hits=0
        self.lane=dict(target=10**6,cores=hardware()['cores']);self.lane_at=0
        psutil.cpu_percent(interval=None)
    def emit(self,state='RUNNING',**fields):
        h=hardware()
        atomic_json(self.job_dir/'working'/'tts-runtime.json',dict(state=state,workers=len(self.pool.members),
            threads=[m['threads'] for m in self.pool.members],available_gib=round(h['available']/GIB,2),
            cpu=round(h['cpu'],1),cpu_target=h['target'],hot=h['hot'],cache_hits=self.cache_hits,
            measured_worker_gib=round(self.worker_bytes/GIB,3),selected=self.selected,scaling=self.gain.state(),**fields))
    def report_lane(self,force=False):
        if not force and time.monotonic()-self.lane_at<2:return self.lane
        self.lane_at=time.monotonic();h=hardware();p=policy()
        self.lane=lanes.report(self.job_dir,'tts',len(self.pool.members),self.worker_bytes,None,
                               min(h['cores'],p['max_workers'] or h['cores']))
        return self.lane
    def lane_limit(self,cores):
        return max(1,min(cores,self.lane['target']))
    def lane_cores(self,cores):
        return max(1,min(cores,self.lane['cores']))
    def pause_memory(self):
        # An earlier workflow waits for later ones to shrink or pause instead of pausing itself.
        began=time.monotonic()
        try:
            while lanes.waiting(self.job_dir,self.worker_bytes) and time.monotonic()-began<policy()['memory_wait_seconds']*2:
                check_cancel(self.job_dir);self.emit('WAITING_MEMORY',waiting_for_lanes=True)
                h=hardware()
                if h['available']>=policy()['reserve_gib']*GIB+self.worker_bytes:return
                time.sleep(1)
        finally:lanes.waiting(self.job_dir,0)
        if lanes.others_running(self.job_dir):
            lanes.auto_pause(self.job_dir,reason='tts_memory_timeout')
            raise Cancelled('TTS paused while other workflows hold memory; it resumes automatically')
        atomic_json(self.job_dir/'working'/'cancel.signal',dict(mode='pause',reason='tts_memory_timeout'))
        raise Cancelled('TTS paused while waiting for memory; checkpoints preserved')
    def fit(self,count,initial=False):
        h=hardware();p=policy();extra=max(0,count-len(self.pool.members))*self.worker_bytes
        return (count<=self.lane_limit(min(h['cores'],p['max_workers'] or h['cores'])) and not h['hot'] and
                (initial or max(h['cpu'],self.last_cpu)<h['target']-5) and
                h['available']>=p['reserve_gib']*GIB+extra and (h['commit'] is None or h['commit']>=p['reserve_gib']*GIB+extra))
    def add(self,threads,initial=False):
        began=time.monotonic()
        while not self.fit(len(self.pool.members)+1,initial):
            check_cancel(self.job_dir);self.emit('WAITING_MEMORY')
            if not initial:return False
            if time.monotonic()-began>=policy()['memory_wait_seconds']:self.pause_memory()
            time.sleep(.2)
        member=self.pool.add(threads)
        while not member['ready']:
            check_cancel(self.job_dir)
            if member['pipe'].poll(.2):self.pool.receive(member)
            elif not member['process'].is_alive():raise RuntimeError('TTS worker failed to load')
            if time.monotonic()-member['started']>180:raise RuntimeError('TTS model load timed out')
            if hardware()['available']<256*1024**2:self.pause_memory()
        self.worker_bytes=max(self.worker_bytes,int(self.pool.peak*1.25))
        if self.job_dir and not self.fake:self.report_lane(force=True)  # every loaded worker
        if not self.fake:
            signature=provider_signature(self.config)
            if signature!=self.signature:self.signature=self.cache.signature=signature
        return True
    def configure(self,count,threads):
        self.pool.close()
        for index in range(count):
            if not self.add(threads,initial=index==0):break
        return len(self.pool.members)==count
    def first_threads(self):
        p=policy();return min(self.lane_cores(hardware()['cores']),p['threads'] or 4)
    def prepare(self,texts):
        """Start with one worker; run() adds more only while it measurably helps."""
        if self.selected is not None:return
        self.report_lane(force=True);threads=self.first_threads()
        self.add(threads,initial=True);self.selected=dict(workers=1,threads=threads)
        self.gain.observe(len(self.pool.members))
    def tune(self,texts):
        """Between batches: honour the lane target and policy limit by retiring idle workers."""
        h=hardware();p=policy();self.report_lane(force=True)
        limit=self.lane_limit(min(h['cores'],p['max_workers'] or h['cores']))
        while len(self.pool.members)>max(1,limit):
            idle=next((m for m in reversed(self.pool.members) if m['pending'] is None),None)
            if not idle:break
            self.pool.remove(idle)
        self.gain.observe(len(self.pool.members));self.emit()
    def scale(self,h):
        """+1 worker after scale_up_seconds healthy; keep it only if throughput rises."""
        p=policy();now=time.monotonic();count=len(self.pool.members)
        if self.loading is not None:
            member=self.loading
            if member['pipe'].poll():
                try:self.pool.receive(member)
                except BaseException:
                    if member in self.pool.members:self.pool.remove(member)
                    self.loading=None;return
            if member.get('ready'):
                self.loading=None;self.worker_bytes=max(self.worker_bytes,int(self.pool.peak*1.25))
                self.gain.begin(count-1);self.report_lane(force=True)
            elif not member['process'].is_alive() or now-member['started']>180:
                self.pool.remove(member);self.loading=None
            return
        if self.gain.verdict()=='revert' and count>1:
            # Not faster: retire the newest worker once it is idle.
            self.pool.members[-1]['retire']=True
        active=len([m for m in self.pool.members if not m.get('retire')])
        self.gain.observe(active)
        limit=self.lane_limit(min(h['cores'],p['max_workers'] or h['cores']))
        healthy=(not h['hot'] and h['cpu']<h['target']-5 and active==count and count<limit and self.fit(count+1))
        if not healthy:
            self.healthy_since=None;return
        self.healthy_since=self.healthy_since or now
        if now-self.healthy_since>=p['scale_up_seconds'] and self.gain.can_try(count):
            threads=max(1,min(p['threads'] or 4,self.lane_cores(h['cores'])//(count+1)))
            self.loading=self.pool.add(threads);self.healthy_since=None
    def run(self,tasks,on_done,observe=True):
        pending=list(tasks);failure=None;paused=False;pressure_since=None;trial_pressure=False
        while pending or any(m['pending'] for m in self.pool.members):
            mode=stop_mode(self.job_dir)
            if mode and mode!='pause':raise Cancelled('TTS cancelled')
            paused=paused or mode=='pause'
            h=hardware()
            if h['available']<256*1024**2 or (h['commit'] is not None and h['commit']<256*1024**2):self.pause_memory()
            if observe and time.monotonic()-self.last_observed>=policy()['observe_seconds']:
                self.last_observed=time.monotonic();self.last_cpu=h['cpu'];self.emit()
            if observe:self.scale(h)
            if observe and self.job_dir:
                self.report_lane()
                while len(self.pool.members)>self.lane_limit(len(self.pool.members)):
                    idle=next((m for m in reversed(self.pool.members) if m['pending'] is None),None)
                    if not idle:break
                    self.pool.remove(idle)
            busy=sum(m['pending'] is not None for m in self.pool.members)
            target=max(1,len(self.pool.members)//2) if h['hot'] or h['cpu']>=h['target'] or h['available']<policy()['reserve_gib']*GIB else len(self.pool.members)
            target=min(target,self.lane_limit(target))
            low=h['available']<policy()['reserve_gib']*GIB or (h['commit'] is not None and h['commit']<policy()['reserve_gib']*GIB)
            if low:
                pressure_since=pressure_since or time.monotonic()
                if not observe:trial_pressure=True
            else:pressure_since=None
            for member in list(self.pool.members):
                if member is self.loading or not member.get('ready',True):continue
                if member.get('retire') and member['pending'] is None and len(self.pool.members)>1:
                    self.pool.remove(member);continue
                if pending and member['pending'] is None and busy<target and not low and not trial_pressure and not paused and failure is None and not member.get('retire'):
                    item=pending.pop(0);member['pending']=item;busy+=1
                    member['pipe'].send(('render',item[0],item[1],str(item[2])))
                if member['pending'] is not None and member['pipe'].poll():
                    try:
                        result=self.pool.receive(member)
                        if result[0]=='done':
                            item=member['pending'];member['pending']=None
                            self.worker_bytes=max(self.worker_bytes,int(self.pool.peak*1.25))
                            self.gain.record(len(item[1]));on_done(item)
                    except BaseException as exc:
                        member['pending']=None;failure=failure or exc
                elif member['pending'] is not None and not member['process'].is_alive():
                    member['pending']=None;failure=failure or RuntimeError('TTS worker crashed')
            if observe and low and len(self.pool.members)>1:
                idle=next((m for m in reversed(self.pool.members) if m['pending'] is None and m is not self.loading),None)
                if idle:self.pool.remove(idle);self.loading=None if idle is self.loading else self.loading
            if not any(m['pending'] for m in self.pool.members):
                if failure:raise failure
                if paused:raise Cancelled('TTS paused; completed WAV checkpoints preserved')
                if trial_pressure:raise TrialPressure('TTS trial exceeded RAM reserve')
                if pressure_since and time.monotonic()-pressure_since>=policy()['memory_wait_seconds']:self.pause_memory()
            if pending or any(m['pending'] for m in self.pool.members):time.sleep(.01)
    def synthesize_many(self,tasks,on_done):
        missing=[];unique={};aliases={}
        for item in tasks:
            check_cancel(self.job_dir)
            if not item[1].strip():
                import numpy as np
                import soundfile as sf
                sf.write(str(item[2]),np.zeros(1,dtype=np.float32),48000,format='WAV',subtype='PCM_16')
                on_done(item);continue
            if self.cache_allowed and self.cache.get(item[1],item[2]):self.cache_hits+=1;on_done(item)
            else:
                key=self.cache.key(item[1])
                if self.cache_allowed and policy()['cache_enabled'] and key in unique:
                    aliases.setdefault(unique[key][0],[]).append(item)
                else:
                    unique[key]=item;missing.append(item)
        if not missing:return
        texts=[item[1] for item in missing if item[1].strip()]
        self.prepare(texts or ['']);self.tune(texts)
        def save(item):
            # Cache before coordinator renames the temporary WAV.
            self.cache.put(item[1],item[2])
            for alias in aliases.get(item[0],[]):
                shutil.copyfile(item[2],alias[2]);on_done(alias)
            on_done(item)
        try:self.run(missing,save)
        except BaseException:
            # Release worker file handles before the caller removes temporary WAVs.
            self.close();raise
    def close(self):self.pool.close()
