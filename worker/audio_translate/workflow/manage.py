"""Local workflow registry, safe lifecycle operations and tool admission."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import uuid
from contextlib import contextmanager, closing
from audio_translate.core.storage import DATA, atomic_json, read_json, file_lock, LockedError, update_job
from audio_translate.core.errors import STEPS, initial_steps, redact
from audio_translate.core.control import now, cancel_run
from audio_translate.workflow import results

TOOLS = {'transcription': ['TRANSCRIPTION'], 'translation': ['TRANSLATION'], 'moderation': ['MODERATION'], 'tts': ['TTS']}

def filename(number, original):
    if type(number) is not int or number < 1 or Path(original).name != original: raise ValueError('Invalid artifact name')
    return f'{number:06d}-{original}'

@contextmanager
def registry():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA/'workflow-registry.sqlite3', timeout=30)
    try:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, scope TEXT, number INTEGER, deleted INTEGER DEFAULT 0, UNIQUE(scope, number))')
        db.execute('CREATE TABLE IF NOT EXISTS sequences (scope TEXT PRIMARY KEY, value INTEGER)')
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally: db.close()

def allocate(db, job_id, scope, requested=None):
    if requested is not None and (type(requested) is not int or requested < 1): raise ValueError('Invalid workflow number')
    row = db.execute('SELECT scope,number FROM runs WHERE id=?', (job_id,)).fetchone()
    if row:
        if row[0] != scope: raise ValueError('Registry scope collision')
        if requested and requested != row[1]: raise ValueError('Existing workflow number mismatch')
        return row[1]
    current = db.execute('SELECT value FROM sequences WHERE scope=?', (scope,)).fetchone()
    number = requested or ((current[0] if current else 0)+1)
    db.execute('INSERT INTO runs(id,scope,number) VALUES (?,?,?)', (job_id,scope,number))
    db.execute('INSERT OR REPLACE INTO sequences VALUES (?,?)', (scope,max(number,current[0] if current else 0)))
    return number

def safe_directory(path, root):
    path, root = Path(path), Path(root).resolve()
    resolved = path.resolve()
    if resolved == root or not resolved.is_relative_to(root) or path.is_symlink(): raise ValueError('Unsafe storage path')
    for parent in [path, *path.parents]:
        if parent == root: break
        if parent.is_symlink() or (hasattr(parent,'is_junction') and parent.is_junction()): raise ValueError('Linked storage paths are not allowed')
    return resolved

def migrate():
    """Reserve existing numbers first, then assign old records by creation time.
    Published legacy directories remain as backups; migration never deletes them.
    """
    jobs = {}
    for root in [DATA/'tmp', DATA/'jobs']:
        if not root.exists(): continue
        for directory in root.iterdir():
            if results.ID.fullmatch(directory.name) and (directory/'job.json').is_file():
                safe_directory(directory, root)
                job = read_json(directory/'job.json')
                if job.get('id') != directory.name: raise ValueError('Legacy identity mismatch')
                jobs.setdefault(directory.name, (directory,job))
    # Some old histories have only published metadata. Materialize recoverable
    # metadata without removing or modifying the original published directory.
    if results.RESULTS.exists():
        for archive in results.RESULTS.iterdir():
            if not results.ID.fullmatch(archive.name) or archive.name in jobs or not (archive/'job.json').is_file(): continue
            safe_directory(archive,results.RESULTS)
            job = read_json(archive/'job.json')
            if job.get('id') != archive.name: raise ValueError('Archived identity mismatch')
            directory = DATA/'jobs'/archive.name
            atomic_json(directory/'job.json',job)
            jobs[archive.name] = (directory,job)
    ordered = sorted(jobs.values(), key=lambda pair:(pair[1].get('created_at',''),pair[1]['id']))
    with registry() as db:
        for _,job in ordered:
            if job.get('workflow_no'): allocate(db,job['id'],'workflows',job['workflow_no'])
        for directory,job in ordered:
            number = allocate(db,job['id'],'workflows')
            if job.get('workflow_no') == number: continue
            try:
                with file_lock(directory/'working'/'worker.lock'):
                    backup = directory/'working'/'migration-v3-original.json'
                    if not backup.exists(): atomic_json(backup,job)
                    adapters = directory/'working'/'adapters.json'
                    voice = job.get('selected_voice_id') or (read_json(adapters).get('tts',{}).get('voice') if adapters.exists() else None)
                    update_job(directory, workflow_no=number, storage_scope='workflows', steps=initial_steps(job),
                               selected_voice_id=voice,total_duration_ms=job.get('total_duration_ms'),
                               started_at=job.get('started_at'),completed_at=job.get('completed_at'))
            except LockedError:
                raise ValueError('Wait for legacy workers to finish before migration')
    for directory,_ in ordered:
        job = read_json(directory/'job.json')
        legacy = results.RESULTS/job['id']
        if (legacy/'outputs.json').exists():
            target = results.destination(job['id'])
            manifest = read_json(target/'outputs.json') if (target/'outputs.json').exists() else {'job_id':job['id'],'files':[]}
            mapped = {kind:relative for items in results.output_files(job).values() for kind,_,relative in items}
            known = {f['type'] for f in manifest['files']}
            for item in read_json(legacy/'outputs.json')['files']:
                if item.get('type') not in mapped or item['type'] in known: continue
                source = safe_directory(legacy/item['path'],legacy)
                if not source.is_file(): continue
                relative = mapped[item['type']]
                dest = safe_directory(target/relative,target); dest.parent.mkdir(parents=True,exist_ok=True)
                sha = results.file_digest(source)
                if dest.exists() and results.file_digest(dest) != sha: raise ValueError('Migration artifact collision')
                temp = dest.with_suffix(dest.suffix+'.tmp')
                try:
                    with source.open('rb') as inp,temp.open('wb') as out:
                        shutil.copyfileobj(inp,out,1024*1024); out.flush(); os.fsync(out.fileno())
                    if results.file_digest(temp) != sha: raise ValueError('Migration validation failed')
                    results.replace(temp,dest)
                finally: temp.unlink(missing_ok=True)
                manifest['files'].append({**item,'id':item['type'],'path':relative,'sha256':sha,'status':item.get('status','AVAILABLE')})
                original = next(source_name for items in results.FILES.values() for kind,source_name,_ in items if kind == item['type'])
                working = safe_directory(directory/original,directory)
                if not working.exists():
                    working.parent.mkdir(parents=True,exist_ok=True)
                    wtemp = working.with_suffix(working.suffix+'.tmp')
                    try:
                        with source.open('rb') as inp,wtemp.open('wb') as out:
                            shutil.copyfileobj(inp,out,1024*1024);out.flush();os.fsync(out.fileno())
                        if results.file_digest(wtemp) != sha: raise ValueError('Migration input validation failed')
                        results.replace(wtemp,working)
                    finally: wtemp.unlink(missing_ok=True)
            results.write_metadata(target,'outputs.json',manifest)
            results.metadata(directory)
        try: results.import_existing(directory)
        except LockedError: pass

def translation_mode(mode, tool=None):
    """'genius' sends Translation to Gemini through the gateway; None keeps the local model."""
    if mode in (None, '', 'normal'): return None
    if mode != 'genius': raise ValueError('Unknown translation mode')
    if tool not in (None, 'translation'): raise ValueError('Genius applies to workflows and Tool 2 only')
    from audio_translate.translation.genius import configured
    if not configured(): raise ValueError('Genius gateway is not configured')
    return 'genius'


def needs_review(job):
    """Basic stops before paid Voice generation unless the run was created with Auto.

    Jobs created before this setting existed carry no `tts_auto` and are never held."""
    if 'tts_auto' not in job or job['tts_auto'] or job.get('review_approved'): return False
    return 'TTS' in job.get('tool_steps', STEPS)


def review(job_id, decision, scope='workflows'):
    """AWAITING_REVIEW -> continue (queue Voice generation) or finish (complete without voice)."""
    if decision not in ('continue', 'finish'): raise ValueError('Unknown review decision')
    if decision == 'continue':
        from audio_translate.core.license_gate import assert_allowed
        assert_allowed()
    directory = results.workspace(job_id)
    with file_lock(directory/'working'/'worker.lock'):
        job = read_json(directory/'job.json')
        if scope != job.get('storage_scope', 'workflows'): raise ValueError('Wrong history scope')
        if job.get('status') != 'AWAITING_REVIEW': raise ValueError('This run is not waiting for review')
        steps = initial_steps(job)
        if decision == 'continue':
            update_job(directory, status='QUEUED', review_approved=True, error=None)
        else:
            steps['TTS'].update(state='SKIPPED', progress=None)
            update_job(directory, status='COMPLETED', steps=steps, progress=100, review_skipped=True, completed_at=now())
        results.metadata(directory)
        return read_json(directory/'job.json')


def create(url='', voice=None, tool=None, upload=None, input_name=None, mime=None, style=None, address=None, mode=None, auto=None):
    from audio_translate.core.license_gate import assert_allowed
    assert_allowed()
    scope = 'tools' if tool else 'workflows'
    if tool and tool not in TOOLS: raise ValueError('Unsupported tool')
    from audio_translate.tts.voices import select
    from audio_translate.tts.voice_styles import validate
    from audio_translate.moderation.address import validate_profile
    chosen = select(voice, style)
    mode = translation_mode(mode, tool)
    # Genius handles forms of address itself; the local address layer is not offered.
    address = None if mode else validate_profile(address)
    job_id = str(uuid.uuid4())
    directory = DATA/('tool-tmp' if tool else 'tmp')/job_id
    directory.mkdir(parents=True)
    (directory/'working').mkdir()
    (directory/'source').mkdir()
    try:
        with registry() as db: number = allocate(db,job_id,scope)
        job = {'id':job_id,'workflow_no':number,'storage_scope':scope,'url':url,'name':input_name or url,
               'status':'QUEUED','progress':0,'duration_ms':0,'total_duration_ms':0,'created_at':now(),
               'error':None,'workflow_version':2,'selected_voice_id':chosen,'selected_voice_style':validate(style),'selected_address_profile':address,'steps':initial_steps({})}
        if mode: job['translation_mode'] = mode
        from audio_translate.core.edition import is_basic
        if is_basic() and tool in (None, 'tts'):
            # Basic pays for Voice generation: ask before it unless Auto was ticked.
            job['tts_auto'] = auto is True
        if tool and url and not upload:
            # Tool 1 from a YouTube link: the same download step as a workflow, then stop after Transcription.
            if tool != 'transcription': raise ValueError('Only Chinese audio transcription accepts a link')
            job.update(tool_type=tool,input_file=None,tool_steps=['DOWNLOAD','TRANSCRIPTION'])
        elif tool:
            job.update(tool_type=tool,input_file=input_name,tool_steps=TOOLS[tool],upload_file=Path(upload).name)
            normalize_input(directory,job,upload,input_name,mime)
        atomic_json(directory/'job.json',job)
        results.metadata(directory)
        return job
    except BaseException:
        shutil.rmtree(safe_directory(directory,directory.parent))
        # Keep allocated sequence numbers reserved even when admission fails.
        raise

def normalize_input(directory,job,upload,name,mime):
    path = safe_directory(upload,DATA/'uploads')
    if not path.is_file() or not path.stat().st_size: raise ValueError('Empty upload')
    ext = Path(name or '').suffix.lower()
    if job['tool_type'] == 'transcription':
        allowed = {'.wav','.mp3','.m4a','.flac','.ogg','.aac','.webm','.mp4'}
        if ext not in allowed or not (mime.startswith('audio/') or mime in ['video/mp4','video/webm','application/octet-stream']): raise ValueError('Unsupported audio type')
        import subprocess
        result = subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,check=True)
        info = json.loads(result.stdout)
        if not any(s.get('codec_type') == 'audio' for s in info['streams']): raise ValueError('No audio stream')
        formats = set(info['format'].get('format_name','').split(','))
        containers = {'.wav':{'wav'},'.mp3':{'mp3'},'.m4a':{'mov','mp4','m4a'},'.mp4':{'mov','mp4'},'.flac':{'flac'},'.ogg':{'ogg'},'.aac':{'aac'},'.webm':{'matroska','webm'}}
        if not formats.intersection(containers[ext]): raise ValueError('Audio container does not match filename extension')
        job['duration_ms'] = int(float(info['format']['duration'])*1000)
        if job['duration_ms'] <= 0: raise ValueError('Invalid audio duration')
        shutil.copyfile(path,directory/'source'/('audio'+ext))
        return
    if ext not in {'.txt','.md','.jsonl'} or mime not in {'text/plain','text/markdown','application/json','application/jsonl','application/x-ndjson','application/octet-stream',''}: raise ValueError('Use UTF-8 TXT, MD or segment JSONL')
    tool = job['tool_type']
    key,target = {'translation':('text','transcript.zh.jsonl'),'moderation':('text_vi','transcript.vi.jsonl'),'tts':('text_vi_moderated','transcript.vi.moderated.jsonl')}[tool]
    count = 0
    with path.open(encoding='utf-8-sig') as inp, (directory/target).open('w',encoding='utf-8') as out:
        # Bounded lines prevent a single huge text/JSONL row from consuming RAM.
        while True:
            line = inp.readline(65538)
            if not line: break
            if len(line)>65536 or '\x00' in line: raise ValueError('Text segment exceeds 64 KiB or contains binary data')
            text = line.strip()
            if not text: continue
            if ext == '.jsonl':
                row = json.loads(text)
                if not isinstance(row,dict) or not isinstance(row.get(key if tool != 'tts' else 'text_vi'),str):
                    # TTS also accepts the existing moderated output format.
                    if tool != 'tts' or not isinstance(row,dict) or not isinstance(row.get(key),str): raise ValueError('JSONL text field is invalid')
                if tool == 'tts': row[key] = row.get(key,row.get('text_vi'))
                if any(type(row.get(k)) is not int for k in ['start_ms','end_ms']): raise ValueError('JSONL needs integer timestamps')
            else: row = {'start_ms':count,'end_ms':count,key:text}
            out.write(json.dumps(row,ensure_ascii=False)+'\n'); count += 1
    from audio_translate.core.storage import count_rows
    if not count or count_rows(directory/target,key) != count: raise ValueError('Input contains no valid text')

def reprocess(job_id,step,voice=None,style=None,address=None,mode=None):
    from audio_translate.core.license_gate import assert_allowed
    assert_allowed()
    directory = results.workspace(job_id)
    from audio_translate.core.sealing import opened
    with file_lock(directory/'working'/'worker.lock'), opened(directory):
        job = read_json(directory/'job.json')
        effective = job.get('tool_steps',STEPS)
        if step not in effective: raise ValueError('Unknown restart stage')
        if (directory/'working'/'delete-request.json').exists(): raise ValueError('Workflow deletion is pending')
        if job['status'] not in ['COMPLETED','FAILED','CANCELLED','PAUSED','PARTIAL','AWAITING_REVIEW']: raise ValueError('Pause or finish the current run first')
        steps = initial_steps(job)
        if any(steps[s]['state'] != 'COMPLETED' for s in effective[:effective.index(step)]): raise ValueError('Complete predecessor stages first')
        inputs = {'TRANSCRIPTION':None,'TRANSLATION':'transcript.zh.jsonl','MODERATION':'transcript.vi.jsonl','TTS':'transcript.vi.moderated.jsonl'}
        if step == 'TRANSCRIPTION':
            from audio_translate.transcription.pipeline import source_file
            if not source_file(directory): raise ValueError('Source audio is missing; restart from Download')
        elif inputs.get(step) and not (directory/inputs[step]).is_file(): raise ValueError('Predecessor output is missing; restart from an earlier stage')
        affected = effective[effective.index(step):]
        if mode is not None:
            chosen_mode = translation_mode(mode, job.get('tool_type'))
            if chosen_mode != job.get('translation_mode') and 'TRANSLATION' not in affected:
                raise ValueError('Changing the translation mode requires restarting from Translation or earlier')
            if chosen_mode: job['translation_mode'] = chosen_mode
            else: job.pop('translation_mode', None)
            if chosen_mode: address = None
        if job.get('translation_mode') and 'selected_address_profile' in job:
            job['selected_address_profile'] = None
        if 'TRANSLATION' in affected:
            # Every Genius translation run is a new billed job on the gateway.
            (directory/'working'/'genius-state.json').unlink(missing_ok=True)
        if 'TTS' in affected:
            (directory/'working'/'tts-remote-state.json').unlink(missing_ok=True)
            # Reprocess from TTS is an explicit request to generate the voice: no second question.
            # Restarting earlier asks again (unless Auto), since the text may change.
            job['review_approved'] = step == 'TTS'
            job.pop('review_skipped', None)
        if address:
            from audio_translate.moderation.address import validate_profile
            address = validate_profile(address)
            # Forms of address are applied in Moderation; TTS alone cannot change them.
            if address != (job.get('selected_address_profile') or 'neutral') and 'MODERATION' not in affected:
                raise ValueError('Changing forms of address requires restarting from Moderation or earlier')
            job['selected_address_profile'] = address
        if voice or style:
            from audio_translate.tts.voices import select
            from audio_translate.tts.adapters import apply_style
            from audio_translate.tts.voice_styles import validate
            if style: job['selected_voice_style'] = validate(style)
            job['selected_voice_id'] = select(voice or job.get('selected_voice_id'), job.get('selected_voice_style'))
            config = directory/'working'/'adapters.json'
            if config.exists():
                settings = read_json(config); settings['tts']['voice'] = job['selected_voice_id']; apply_style(settings,job); atomic_json(config,settings)
        output = results.destination(job_id)
        manifest = read_json(output/'outputs.json')
        for item in manifest['files']:
            if item['step'] in affected: item['status'] = 'STALE'
        results.write_metadata(output,'outputs.json',manifest)
        for s in affected:
            steps[s].update(state='PENDING',progress=0,started_at=None,completed_at=None,duration_ms=0,resume_duration_ms=0)
            steps[s].pop('error',None)
            (directory/'working'/f'{s.lower()}.done.json').unlink(missing_ok=True)
        checkpoint = directory/'working'/'postprocess.sqlite3'
        if checkpoint.exists():
            with closing(sqlite3.connect(checkpoint)) as db:
                with db:
                    for s in affected: db.execute('DELETE FROM segments WHERE stage=?',(s.lower(),))
                    if 'TRANSLATION' in affected and db.execute("SELECT 1 FROM sqlite_master WHERE name='translation_parts'").fetchone():
                        db.execute('DELETE FROM translation_parts')
                    if 'TRANSLATION' in affected and db.execute("SELECT 1 FROM sqlite_master WHERE name='translation_failures'").fetchone():
                        db.execute('DELETE FROM translation_failures')
        if 'TRANSLATION' in affected:
            for name in ('translation-errors.json','translation-progress.json','translation-continue.json'):
                (directory/'working'/name).unlink(missing_ok=True)
        if 'DOWNLOAD' in affected:
            shutil.rmtree(safe_directory(directory/'source',directory)); (directory/'source').mkdir()
        if 'TRANSCRIPTION' in affected:
            for pattern in ['chunk-*.json','chunks.json','vad*','transcription-progress.json']:
                for file in (directory/'working').glob(pattern):
                    if file.is_file() and not file.is_symlink(): file.unlink()
        if 'MODERATION' in affected: (directory/'working'/'replacement-rules.snapshot.json').unlink(missing_ok=True)
        if 'TTS' in affected:
            for folder in [directory/'voice',directory/'working'/'voice-checkpoints']:
                if folder.exists(): shutil.rmtree(safe_directory(folder,directory))
        (directory/'working'/'cancel.signal').unlink(missing_ok=True)
        stages = job.get('stages',{})
        for s in affected: stages.pop(s.lower(),None)
        overall = round(100*sum(steps[s]['state']=='COMPLETED' for s in effective)/len(effective),2)
        job.update(progress=overall,reprocess_pending=True,steps=steps,stages=stages,status='QUEUED',retry_step=None,error=None,completed_at=None,active_stage=None)
        atomic_json(directory/'job.json',job)
        results.metadata(directory)
        return job

def cancel(job_id, mode='cancel'):
    directory = results.workspace(job_id)
    job = read_json(directory/'job.json')
    if job['status'] in ['COMPLETED','FAILED','CANCELLED','PAUSED','AWAITING_REVIEW']: raise ValueError('Run is already stopped')
    if mode=='pause' and (directory/'working'/'delete-request.json').exists(): raise ValueError('Workflow deletion is pending')
    atomic_json(directory/'working'/'cancel.signal',{'requested_at':now(),'mode':mode})
    try:
        with file_lock(directory/'working'/'worker.lock'):
            job = read_json(directory/'job.json')
            if job['status'] in ['COMPLETED','FAILED','CANCELLED','PAUSED']:
                (directory/'working'/'cancel.signal').unlink(missing_ok=True)
                return
            step = job.get('retry_step') or next(s for s in job.get('tool_steps',STEPS) if initial_steps(job)[s]['state'] != 'COMPLETED')
            cancel_run(directory,step)
    except LockedError: pass

def resume(job_id):
    from audio_translate.core.license_gate import assert_allowed
    assert_allowed()
    directory=results.workspace(job_id)
    from audio_translate.core.sealing import opened
    with file_lock(directory/'working'/'worker.lock'), opened(directory):
        job=read_json(directory/'job.json');steps=initial_steps(job)
        if (directory/'working'/'delete-request.json').exists(): raise ValueError('Workflow deletion is pending')
        translation_failed = job.get('status') == 'FAILED' and steps['TRANSLATION']['state'] == 'FAILED'
        if job.get('status') not in ('CANCELLED','PAUSED') and not translation_failed:
            raise ValueError('Only a paused workflow or failed Translation can continue')
        if job.get('retry_step') or any(item['state']=='RUNNING' for item in steps.values()):
            raise ValueError('Another step instance is running or queued')
        effective=job.get('tool_steps',STEPS)
        current='TRANSLATION' if translation_failed else next((step for step in effective if steps[step]['state'] in ('CANCELLED','PAUSED')),None)
        if not current: raise ValueError('No cancelled step to resume')
        if any(steps[step]['state']!='COMPLETED' for step in effective[:effective.index(current)]):
            raise ValueError('Previous steps must be completed')
        if translation_failed:
            from audio_translate.core.storage import count_rows
            count_rows(directory/'transcript.zh.jsonl', 'text')
            continuation=directory/'working'/'translation-continue.json'
            previous=read_json(continuation) if continuation.exists() else {}
            atomic_json(continuation, {'generation': previous.get('generation',0)+1, 'requested_at': now()})
        # Do not reprocess or clean valid chunks; a resumed run skips them.
        steps[current]['resume_duration_ms']=steps[current].get('duration_ms') or 0
        steps[current]['state']='PENDING'
        steps[current].pop('error',None)
        (directory/'working'/'cancel.signal').unlink(missing_ok=True)
        update_job(directory,steps=steps,status='QUEUED',retry_step=None,error=None,
                   completed_at=None,active_stage=None,failed_stage=None,memory_pause_reason=None,
                   pause_reason=None,auto_paused_for=None,auto_paused_at=None)
        results.metadata(directory)
        return read_json(directory/'job.json')


def hard_delete(job_id,confirm,scope=None):
    directory = results.workspace(job_id)
    job = read_json(directory/'job.json')
    if scope and scope != job.get('storage_scope'): raise ValueError('Wrong history scope')
    if type(confirm) is not int or confirm != job.get('workflow_no'): raise ValueError('Confirmation number does not match')
    with file_lock(DATA/'management-locks'/f'{job_id}.lock'):
        with file_lock(directory/'working'/'worker.lock'):
            if job['status'] not in ['COMPLETED','FAILED','CANCELLED','PAUSED','PARTIAL','DELETING','AWAITING_REVIEW'] and not (directory/'working'/'delete-request.json').exists(): raise ValueError('Pause the active or queued run before deleting')
            targets = [directory,results.destination(job_id),results.RESULTS/job_id,DATA/'jobs'/job_id,DATA/'tmp'/job_id,DATA/'tool-tmp'/job_id,results.RESULTS.parent/'.audio-results-staging'/job_id]
            if job.get('upload_file'):
                upload = DATA/'uploads'/job['upload_file']
                safe_directory(upload,DATA/'uploads')
                targets.append(upload)
            checked = []
            for target in targets:
                if target.exists():
                    root = results.RESULTS if target.is_relative_to(results.RESULTS) else (results.RESULTS.parent/'.audio-results-staging' if target.is_relative_to(results.RESULTS.parent/'.audio-results-staging') else DATA)
                    checked.append(safe_directory(target,root))
            # Tombstone admission before removing the lock-owning workspace.
            update_job(directory,status='DELETING')
            results.metadata(directory)
        # Keep the workspace until other removals finish, so a Windows locked
        # file can be retried. The global counter survives deletion of the row.
        for target in sorted(dict.fromkeys(checked),key=lambda p:p==directory.resolve()):
            if target.is_file(): target.unlink()
            else: shutil.rmtree(target)
        with registry() as db: db.execute('DELETE FROM runs WHERE id=?',(job_id,))
    (DATA/'management-locks'/f'{job_id}.lock').unlink(missing_ok=True)

def finish_abort(job_id):
    directory=results.workspace(job_id)
    request=read_json(directory/'working'/'delete-request.json')
    # hard_delete validates scope, confirmation and the worker lock before removal.
    hard_delete(job_id,request['confirm'],request['scope'])
    return {'deleted':True}

def abort(job_id,confirm,scope='workflows'):
    directory=results.workspace(job_id);job=read_json(directory/'job.json')
    if type(confirm) is not int or confirm!=job.get('workflow_no') or scope!=job.get('storage_scope'):
        raise ValueError('Confirmation number or scope does not match')
    atomic_json(directory/'working'/'delete-request.json',{'confirm':confirm,'scope':scope,'requested_at':now()})
    if job['status'] not in ['COMPLETED','FAILED','CANCELLED','PAUSED','PARTIAL','DELETING','AWAITING_REVIEW']:
        cancel(job_id,mode='abort')
    else:
        atomic_json(directory/'working'/'cancel.signal',{'mode':'abort','requested_at':now()})
    try: return finish_abort(job_id)
    except (LockedError,ValueError): return {'deleted':False,'deletion_pending':True}

def delete(job_id,confirm,scope=None):
    """Delete now when stopped; a queued or running tool first finishes its current
    mini task (pause drain), then the scheduler removes everything it created."""
    directory=results.workspace(job_id);job=read_json(directory/'job.json')
    stopped=job['status'] in ['COMPLETED','FAILED','CANCELLED','PAUSED','PARTIAL','DELETING','AWAITING_REVIEW']
    if stopped or job.get('storage_scope')!='tools':
        hard_delete(job_id,confirm,scope);return {'deleted':True}
    if type(confirm) is not int or confirm!=job.get('workflow_no') or scope!=job.get('storage_scope'):
        raise ValueError('Confirmation number or scope does not match')
    # Pause first (the drain refuses once a delete request exists), then request deletion;
    # the scheduler finishes it when the worker exits, or finish_abort below does it now.
    try: cancel(job_id,mode='pause')
    except ValueError: pass  # already stopped in the meantime
    atomic_json(directory/'working'/'delete-request.json',{'confirm':confirm,'scope':scope,'requested_at':now()})
    try: return finish_abort(job_id)
    except (LockedError,ValueError): return {'deleted':False,'deletion_pending':True}

def history(scope):
    if scope not in ['workflows','tools']: raise ValueError('Invalid history scope')
    root = results.RESULTS/scope
    if not root.exists(): return []
    jobs=[]
    for directory in root.iterdir():
        if not directory.name.isdigit() or not (directory/'job.json').exists(): continue
        safe_directory(directory,root)
        job = read_json(directory/'job.json')
        if job.get('storage_scope') != scope: continue
        # Working metadata is atomic and supplies live progress/timing. Only
        # public fields are overlaid; artifacts always come from the published
        # manifest, never from half-written processing files.
        try:
            live = read_json(results.workspace(job['id'])/'job.json')
            if live.get('id') == job['id'] and live.get('storage_scope') == scope:
                for key in ['name','status','progress','stages','started_at','completed_at','run_started_at','total_duration_ms','selected_voice_id','selected_voice_style','selected_address_profile','translation_mode','pause_reason','tts_auto','review_skipped','retry_step']:
                    if key in live: job[key] = live[key]
                job['steps'] = {step:{k:item.get(k) for k in ['state','progress','started_at','completed_at','duration_ms','attempt','retry_count','error']} for step,item in live.get('steps',{}).items()}
                working=results.workspace(job['id'])/'working'
                job['delete_requested']=(working/'delete-request.json').exists()
                signal=read_json(working/'cancel.signal') if (working/'cancel.signal').exists() else {}
                job['pause_requested']=signal.get('mode')=='pause' and live.get('status')!='PAUSED'
                telemetry=working/'transcription-progress.json'
                if telemetry.exists():job['transcription_steps']=read_json(telemetry)['steps']
                for name, field in [('translation-errors.json','translation_failures'),('translation-progress.json','translation_progress')]:
                    telemetry=working/name
                    if telemetry.exists():
                        value=read_json(telemetry)
                        job[field]=value['failures'] if field=='translation_failures' else value
        except FileNotFoundError: pass
        files = read_json(directory/'outputs.json')['files']
        expected = results.output_files(job)
        allowed = {kind:relative for items in expected.values() for kind,_,relative in items}
        job['files'] = [item for item in files if item.get('path') == allowed.get(item.get('type')) and safe_directory(directory/item['path'],directory).is_file()]
        for step,item in job.get('steps',{}).items():
            item['output_manifest'] = [f for f in job['files'] if f.get('step') == step]
        jobs.append(job)
    return jobs

def main():
    try:
        p=json.load(sys.stdin); action=p['action']; scope=p.get('scope','workflows')
        if action=='initialize': migrate(); value={}
        elif action=='voices':
            from audio_translate.tts.voices import discover
            value=discover()
        elif action=='create': value={'job':create(p.get('url',''),p.get('voice'),p.get('tool'),p.get('upload'),p.get('input_name'),p.get('mime',''),p.get('style'),p.get('address'),p.get('mode'),p.get('auto') is True)}
        elif action=='review': value={'job':review(p['id'],p.get('decision'),scope)}
        elif action=='preflight':
            from audio_translate.workflow.workflow_admission import preflight
            value={'assessment':preflight()}
        elif action=='convert':
            from audio_translate.workflow.workflow_admission import convert
            if type(p.get('queue_only',False)) is not bool: raise ValueError('Invalid queue option')
            response=convert(p.get('url',''),p.get('voice'),p.get('queue_only',False),p.get('style'),p.get('address'),p.get('mode'),p.get('auto') is True)
            print(json.dumps(response,ensure_ascii=False)); return
        elif action=='reprocess': value={'job':reprocess(p['id'],p['step'],p.get('voice'),p.get('style'),p.get('address'),p.get('mode'))}
        elif action=='cancel': cancel(p['id']); value={}
        elif action=='pause': cancel(p['id'],mode='pause'); value={}
        elif action=='abort': value=abort(p['id'],p.get('confirm'),scope)
        elif action=='finish_abort': value=finish_abort(p['id'])
        elif action=='resume': value={'job':resume(p['id'])}
        elif action=='delete': value=delete(p['id'],p.get('confirm'),p.get('scope'))
        elif action=='history': value={'jobs':history(scope)}
        elif action=='resolve':
            directory=results.workspace(p['id']); job=read_json(directory/'job.json')
            if job.get('storage_scope') != scope: raise ValueError('Wrong history scope')
            job=next((j for j in history(scope) if j['id']==p['id']),None)
            item=next((f for f in job['files'] if f['id']==p['file'] and f['status']=='AVAILABLE'),None) if job else None
            value={'resolved': {'item':item,'file':str(safe_directory(results.destination(p['id'])/item['path'],results.destination(p['id'])))}} if item else {'resolved':None}
        else: raise ValueError('Unknown action')
        response={'status':200,**value}
    except LockedError: response={'status':409,'error':'Worker is running; cancel and wait before changing this run.'}
    except FileNotFoundError: response={'status':404,'error':'Run or input not found.'}
    except (ValueError,KeyError) as exc: response={'status':409,'error':redact(exc)}
    except Exception as exc:
        response={'status':403 if getattr(exc,'code',None) else 500,'error':redact(exc)}
    print(json.dumps(response,ensure_ascii=False))

if __name__=='__main__': main()
