"""Explicit X1/X2/X3 measurements, isolated from workflow state and Auto profiles."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # worker/ import root
import argparse
import json
import os
from pathlib import Path
import threading
import time

import psutil
from audio_translate.transcription.asr_runtime import GIB, hardware, measure, sample_audio
from audio_translate.core.memory_policy import fits, required, reserve
from audio_translate.core.storage import DATA, atomic_json, file_lock, read_json


def local_processes():
    """Identify the local app by command/cwd, then include descendants."""
    current = psutil.Process()
    excluded = {current.pid, *(p.pid for p in current.parents())}
    rows, selected = {}, set()
    root = str(DATA.parent).lower()
    for process in psutil.process_iter(['pid', 'ppid', 'name']):
        rows[process.pid] = process
        if process.pid in excluded:
            continue
        try:
            if root in ' '.join(process.cmdline()).lower() or process.cwd().lower().startswith(root):
                selected.add(process.pid)
        except (psutil.Error, OSError):
            pass
    for _ in range(len(rows)):
        added = {p.pid for p in rows.values() if p.info['ppid'] in selected} - selected
        if not added: break
        selected.update(added)
    return [rows[pid] for pid in sorted(selected)]


def memory(process):
    info = process.memory_full_info()
    return {'rss': info.rss, 'private': getattr(info, 'private', info.vms), 'uss': info.uss}


class MemorySampler:
    def __init__(self, control, local, timeout=300):
        self.control = control
        self.timeout = timeout
        self.stop = threading.Event()
        self.peaks = {'rss':0, 'private':0, 'uss':0, 'individual_peak_rss':0}
        self.per_worker = {}
        self.coordinator_peak_rss = 0
        self.minimum_available = hardware()['available']
        self.failure = None
        self.local = local
        self.phase = 'loading'
        self.samples = []

    def observe(self, phase):
        self.phase = phase

    def run(self):
        parent = psutil.Process()
        began = time.monotonic()
        while not self.stop.is_set():
            totals = {'rss':0, 'private':0, 'uss':0}
            try:
                phase = self.phase
                self.coordinator_peak_rss = max(self.coordinator_peak_rss, parent.memory_info().rss)
                for child in parent.children(recursive=True):
                    try:
                        info = child.memory_full_info()
                        values = {'rss':info.rss, 'private':getattr(info,'private',info.vms),
                                  'uss':info.uss}
                        previous = self.per_worker.setdefault(child.pid, {'rss':0,'private':0,'uss':0})
                        for key, value in values.items():
                            totals[key] += value
                            previous[key] = max(previous[key], value)
                        self.peaks['individual_peak_rss'] = max(self.peaks['individual_peak_rss'],
                                                               getattr(info,'peak_wset',info.rss))
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                for key,value in totals.items():
                    self.peaks[key] = max(self.peaks[key],value)
                snapshot = hardware()
                self.minimum_available = min(self.minimum_available,snapshot['available'])
                local = dict.fromkeys(totals, 0)
                for process in self.local:
                    try:
                        for key, value in memory(process).items(): local[key] += value
                    except psutil.Error: pass
                coordinator = memory(parent)
                self.samples.append({'elapsed':round(time.monotonic()-began,3), 'phase':phase,
                    'workers':totals, 'local':local, 'coordinator':coordinator,
                    'project':{key:totals[key]+local[key]+coordinator[key] for key in totals},
                    'available':snapshot['available'],'commit_available':snapshot['commit_available']})
                if snapshot['available'] < 256*1024**2 or (snapshot['commit_available'] is not None and snapshot['commit_available'] < 512*1024**2) or time.monotonic()-began > self.timeout:
                    self.failure = 'benchmark_timeout' if time.monotonic()-began > self.timeout else 'critical_memory'
                    atomic_json(self.control/'working'/'cancel.signal',{'mode':'cancel','reason':self.failure})
                    return
            except psutil.Error:
                pass
            self.stop.wait(.2)

    def __enter__(self):
        self.thread = threading.Thread(target=self.run,daemon=True)
        self.thread.start()
        return self

    def __exit__(self,*_):
        self.stop.set()
        self.thread.join(5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--workers',type=int,nargs='+',default=[1,2],choices=[1,2,3])
    parser.add_argument('--allow-memory-trial',action='store_true',
                        help='Explicit diagnostic bypass of predicted admission; critical physical/commit guards remain.')
    parser.add_argument('--sample-source',action='store_true',
                        help='Use first/middle/last 30-second source windows when VAD chunks are unavailable.')
    parser.add_argument('--stagger-load',action='store_true')
    parser.add_argument('--offline-license',action='store_true',
                        help='Use the existing native offline license check (signature, machine, expiration and clock checks remain).')
    args = parser.parse_args()
    from audio_translate.core.license_gate import assert_allowed
    from audio_translate.transcription.pipeline import source_file
    os.environ.setdefault('MODELSCOPE_CACHE',str(DATA/'model-cache'))
    os.environ.setdefault('HF_HOME',str(DATA/'hf-cache'))
    os.environ['HF_HUB_OFFLINE'] = '1'
    assert_allowed(internet=not args.offline_license)
    for root in (DATA/'tmp',DATA/'jobs',DATA/'tool-tmp'):
        for path in root.glob('*/job.json'):
            if read_json(path).get('status') not in ('COMPLETED','FAILED','PAUSED','CANCELLED','PARTIAL','DELETING'):
                raise RuntimeError('Pause active workflows before measuring memory')
    source = source_file(args.job)
    chunk_path = args.job/'working'/'chunks.json'
    if chunk_path.exists():
        chunks = read_json(chunk_path)
        sample_basis = 'existing_vad_chunks'
    elif args.sample_source and source is not None:
        from audio_translate.transcription.pipeline import duration_ms, MAX_CHUNK_MS, OVERLAP_MS
        duration = duration_ms(source)
        starts = sorted(set((0,max(0,duration//2-MAX_CHUNK_MS//2),max(0,duration-MAX_CHUNK_MS))))
        chunks = [{'start':max(0,start-OVERLAP_MS),'end':min(duration,start+MAX_CHUNK_MS+OVERLAP_MS),
                   'own_start':start,'own_end':min(duration,start+MAX_CHUNK_MS)} for start in starts]
        sample_basis = 'source_windows_without_vad'
    else:
        raise ValueError('No VAD chunks; use --sample-source for an isolated source-window trial')
    if source is None or not chunks:
        raise ValueError('Benchmark requires downloaded audio and existing chunks')
    destination = DATA/'verification'/'asr-memory'
    destination.mkdir(parents=True,exist_ok=True)
    run_id = str(time.time_ns())
    local = local_processes()
    local_baseline = []
    for process in local:
        try: local_baseline.append({'pid':process.pid,'name':process.name(),**memory(process)})
        except psutil.Error: pass
    report = {'job_id':args.job.name,'created_at':time.time(), 'hardware_before':hardware(),
              'sample_basis':sample_basis,'sample_chunks':chunks if args.sample_source else None,
              'parallel_reserve_gib':reserve(hardware()['total'],parallel=True)/GIB,
              'stagger_load':args.stagger_load,
              'license_check':'native_offline' if args.offline_license else 'native_online',
              'allow_memory_trial':args.allow_memory_trial, 'local_baseline':local_baseline,
              'metric_note':'Sampled aggregate worker RSS may count shared pages twice. USS counts unique resident pages; private is committed private memory, not all resident RAM. Peaks sampled every 0.2s.',
              'configurations':[]}
    # Use three representative complete chunks. All benchmark output stays here.
    samples = sample_audio(source,chunks,sorted(set((0,len(chunks)//2,len(chunks)-1))))
    baseline = None
    peak = 2*GIB
    with file_lock(DATA/'config'/'asr-memory-benchmark.lock'):
        for workers in args.workers:
            threads = min(4,max(1,hardware()['physical_cores']//workers))
            snapshot = hardware()
            allocation = peak*workers
            item = {'workers':workers,'threads':threads,'available_before_gib':round(snapshot['available']/GIB,3),
                    'required_gib':round(required(snapshot['total'],allocation,parallel=workers>1)/GIB,3)}
            item['admission_fits'] = fits(snapshot,allocation,parallel=workers>1)
            if not item['admission_fits'] and not args.allow_memory_trial:
                item.update(status='SKIPPED_INSUFFICIENT_MEMORY',estimated_worker_rss_gib=round(peak*workers/GIB,3))
            else:
                control = destination/f'x{workers}-{time.time_ns()}'
                (control/'working').mkdir(parents=True)
                print(f'BENCHMARK_START X{workers} threads={threads} available={snapshot["available"]/GIB:.2f}GiB',flush=True)
                sampler = MemorySampler(control, local)
                trial_started = time.monotonic()
                try:
                    with sampler:
                        score, outputs = measure(control,samples,len(chunks),workers,threads,baseline,observe=sampler.observe,stagger_load=args.stagger_load)
                    if sampler.failure:
                        raise RuntimeError(sampler.failure)
                    if baseline is None:
                        baseline = outputs
                        peak = max(score['peak_bytes'],sampler.peaks['individual_peak_rss'])
                    item.update(status='MEASURED',seconds=score['seconds'],compatible=score['compatible'],
                                aggregate_worker_peaks_bytes=sampler.peaks,
                                per_worker_peak_bytes=sampler.per_worker,
                                coordinator_peak_rss_bytes=sampler.coordinator_peak_rss,
                                minimum_available_gib=round(sampler.minimum_available/GIB,3))
                except Exception as exc:
                    item.update(status='FAILED',error=sampler.failure or str(exc),aggregate_worker_peaks_bytes=sampler.peaks,
                                per_worker_peak_bytes=sampler.per_worker,
                                minimum_available_gib=round(sampler.minimum_available/GIB,3))
                item['total_wall_seconds'] = round(time.monotonic()-trial_started,3)
                atomic_json(control/'samples.json',sampler.samples)
                item['samples_path'] = str(control/'samples.json')
                item['phases'] = {}
                for phase in ('loading','warmup','inference','shutdown'):
                    rows = [row for row in sampler.samples if row['phase']==phase]
                    if rows:
                        item['phases'][phase] = {
                            'sample_count':len(rows), 'minimum_available':min(row['available'] for row in rows),
                            'minimum_commit_available':min((row['commit_available'] for row in rows if row['commit_available'] is not None),default=None),
                            **{group:{key:max(row[group][key] for row in rows) for key in ('rss','private','uss')}
                               for group in ('workers','local','coordinator','project')}}
            report['configurations'].append(item)
            atomic_json(destination/f'report-{run_id}.json',report)
            atomic_json(destination/'latest.json',report)
            print(json.dumps(item,ensure_ascii=False),flush=True)
    print('REPORT '+str(destination/'latest.json'),flush=True)


if __name__ == '__main__':
    main()
