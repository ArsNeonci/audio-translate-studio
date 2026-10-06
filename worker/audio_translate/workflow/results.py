"""Durable result publication; no model execution and no history database."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

from audio_translate.core.storage import DATA, ROOT, file_digest, file_lock, LockedError, read_json, count_rows

RESULTS = Path(os.getenv('RESULTS_ROOT', str(DATA/'results')))
if not RESULTS.is_absolute(): RESULTS = ROOT/RESULTS
RESULTS = RESULTS.resolve()
ID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
FILES = {
 'TRANSCRIPTION': [('ZH_JSONL', 'transcript.zh.jsonl', 'transcription/transcript.zh.jsonl'),
                   ('ZH_MD', 'transcript.zh.md', 'transcription/transcript.zh.md')],
 'TRANSLATION': [('VI_JSONL', 'transcript.vi.jsonl', 'translation/transcript.vi.jsonl'),
                 ('VI_MD', 'transcript.vi.md', 'translation/transcript.vi.md')],
 'MODERATION': [('MODERATED_JSONL', 'transcript.vi.moderated.jsonl', 'moderation/transcript.vi.moderated.jsonl'),
                ('MODERATED_MD', 'transcript.vi.moderated.md', 'moderation/transcript.vi.moderated.md'),
                ('MODERATION_RESULT', 'moderation-result.json', 'moderation/moderation-result.json')],
 'TTS': [('VOICE_WAV', 'voice.vi.wav', 'tts/voice.vi.wav'),
         ('VOICE_MANIFEST', 'voice/voice.manifest.jsonl', 'tts/voice.manifest.jsonl')],
}


CHINESE_KINDS = {'ZH_JSONL', 'ZH_MD'}
# Exports that carry `text_zh` per row; Basic publishes them without it.
TRANSCRIPT_ROWS = {'VI_JSONL', 'MODERATED_JSONL'}


def output_files(job):
    from audio_translate.core.edition import is_basic
    files = {step:[item for item in items if item[0] not in CHINESE_KINDS] for step,items in FILES.items()} if is_basic() else FILES
    if not job.get("workflow_no"): return files
    from audio_translate.workflow.manage import filename
    return {step:[(kind,source,str(Path(relative).parent/filename(job["workflow_no"],Path(relative).name)).replace("\\","/")) for kind,source,relative in items] for step,items in files.items()}


def copy_export(kind, source, out):
    from audio_translate.core.edition import is_basic, strip_chinese
    if kind not in TRANSCRIPT_ROWS or not is_basic():
        with source.open('rb') as inp: shutil.copyfileobj(inp, out, 1024*1024)
        return
    with source.open(encoding='utf-8') as inp:
        for line in inp:
            if line.strip(): out.write((json.dumps(strip_chinese(json.loads(line)), ensure_ascii=False)+'\n').encode('utf-8'))

def workspace(job_id):
    if not ID.fullmatch(job_id): raise ValueError('Invalid job ID')
    tool = DATA/'tool-tmp'/job_id
    if (tool/'job.json').is_file(): return tool
    current = DATA/'tmp'/job_id
    return current if (current/'job.json').is_file() else DATA/'jobs'/job_id


def destination(job_id):
    if not ID.fullmatch(job_id): raise ValueError('Invalid job ID')
    for work in [DATA/'tmp', DATA/'jobs']:
        if RESULTS.is_relative_to(work.resolve()) or work.resolve().is_relative_to(RESULTS):
            raise ValueError('RESULTS_ROOT must be separate from processing workspaces')
    job = read_json(workspace(job_id)/'job.json')
    scope = job.get('storage_scope','workflows')
    if scope not in ['workflows','tools']: raise ValueError('Invalid scope')
    directory = RESULTS/scope/f"{job['workflow_no']:06d}" if job.get('workflow_no') else RESULTS/job_id
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.resolve().is_relative_to(RESULTS): raise ValueError('Unsafe result directory')
    if (directory/'job.json').exists() and read_json(directory/'job.json').get('id') != job_id:
        raise ValueError('Result directory identity collision')
    return directory


def staging(job_id, directory):
    # Rename is atomic only on the same filesystem. Custom roots on another
    # volume use a sibling staging directory, always OUTSIDE RESULTS_ROOT.
    base = workspace(job_id)/'publication'
    base.mkdir(parents=True, exist_ok=True)
    if base.stat().st_dev != directory.stat().st_dev:
        base = RESULTS.parent/'.audio-results-staging'/job_id
        base.mkdir(parents=True, exist_ok=True)
    if base.resolve().is_relative_to(RESULTS): raise ValueError('Unsafe staging directory')
    return base


def replace(temp, target):
    for attempt in range(8):
        try:
            os.replace(temp, target)
            return
        except PermissionError:
            if attempt == 7: raise
            time.sleep(.025*(attempt+1))


def write_metadata(directory, name, value):
    content = (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    target = directory/name
    if target.exists() and target.read_bytes() == content: return
    temp = directory/f'.{uuid.uuid4().hex}.tmp'
    try:
        with temp.open('wb') as out:
            out.write(content); out.flush(); os.fsync(out.fileno())
        replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def metadata(job_dir):
    job = read_json(Path(job_dir)/'job.json')
    job_id = job.get('id', '')
    if not ID.fullmatch(job_id): return  # Unit fixtures are not public jobs.
    directory = destination(job_id)
    summary = {key: job.get(key) for key in ['id', 'workflow_no', 'storage_scope', 'tool_type', 'input_file', 'name', 'url', 'created_at', 'status', 'progress', 'duration_ms', 'workflow_version', 'started_at', 'completed_at', 'total_duration_ms', 'run_started_at', 'selected_voice_id', 'selected_voice_style', 'selected_address_profile', 'translation_mode', 'pause_reason', 'tts_auto', 'review_skipped', 'stages', 'tool_steps']}
    # No adapter paths, raw errors, credentials or private worker metadata.
    summary['compute_device'] = job.get('compute_device')
    summary['steps'] = {key: {k:value.get(k) for k in ['state','retry_count','attempt','progress','started_at','completed_at','duration_ms','error']}
                        for key, value in job.get('steps', {}).items()}
    telemetry = Path(job_dir)/'working'/'transcription-progress.json'
    if telemetry.exists():
        summary['transcription_steps'] = read_json(telemetry).get('steps', [])
    if job.get('workflow_no') and (directory/'outputs.json').exists():
        files = read_json(directory/'outputs.json')['files']
        for step, value in summary['steps'].items():
            value['output_manifest'] = [f for f in files if f.get('step') == step]
    write_metadata(directory, 'job.json', summary)
    write_metadata(directory, 'source.json', {'job_id': job_id, 'url': job.get('url'), 'title': job.get('name')})
    if not (directory/'outputs.json').exists():
        write_metadata(directory, 'outputs.json', {'job_id': job_id, 'files': []})


def publish_step(job_dir, step):
    job_dir = Path(job_dir)
    job = read_json(job_dir/'job.json')
    job_id = job.get('id', '')
    if not ID.fullmatch(job_id): return
    with file_lock(job_dir/'working'/'results.lock'):
        metadata(job_dir)
        if step not in FILES: return
        directory = destination(job_id)
        manifest = read_json(directory/'outputs.json')
        entries = {item['type']: item for item in manifest['files']}
        prepared = []
        try:
            for kind, source_name, relative in output_files(job)[step]:
                source = job_dir/source_name
                if not source.is_file():
                    if kind == 'ZH_JSONL' and (job_dir/'transcript.jsonl').is_file(): source = job_dir/'transcript.jsonl'
                    else: raise FileNotFoundError(f'Final {kind} output is missing')
                if not source.resolve().is_relative_to(job_dir.resolve()): raise ValueError('Unsafe source file')
                target = directory/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.resolve().is_relative_to(directory.resolve()): raise ValueError('Unsafe output path')
                from audio_translate.core.edition import is_basic
                if kind in TRANSCRIPT_ROWS and is_basic():
                    # The published copy differs from the working copy (no transcript).
                    temp = staging(job_id, directory)/f'{uuid.uuid4().hex}.tmp'
                    prepared.append((temp, target, kind, relative, None))
                    with temp.open('wb') as out:
                        copy_export(kind, source, out); out.flush(); os.fsync(out.fileno())
                    sha = file_digest(temp)
                    if target.is_file() and file_digest(target) == sha:
                        temp.unlink(); prepared[-1] = (None, target, kind, relative, sha)
                    else: prepared[-1] = (temp, target, kind, relative, sha)
                    continue
                sha = file_digest(source)
                if target.is_file() and file_digest(target) == sha:
                    prepared.append((None, target, kind, relative, sha))
                    continue
                temp = staging(job_id, directory)/f'{uuid.uuid4().hex}.tmp'
                prepared.append((temp, target, kind, relative, sha))
                with source.open('rb') as inp, temp.open('wb') as out:
                    shutil.copyfileobj(inp, out, 1024*1024)
                    out.flush(); os.fsync(out.fileno())
                if file_digest(temp) != sha: raise ValueError('Result validation failed')
            from audio_translate.core.control import check_cancel
            check_cancel(job_dir)
            # Hide the whole stage while swapping its validated files. A crash
            # cannot advertise a mixed generation as AVAILABLE.
            for _,_,kind,relative,_ in prepared:
                if kind in entries: entries[kind]['status'] = 'PUBLISHING'
            write_metadata(directory, 'outputs.json', {'job_id':job_id,'files':list(entries.values())})
            # Validate every staged file before replacing any published file.
            for temp, target, kind, relative, sha in prepared:
                if temp: replace(temp, target)
                entries[kind] = {'id': kind, 'step': step, 'type': kind, 'path': relative,
                    'size': target.stat().st_size, 'sha256': sha, 'status': 'AVAILABLE',
                    'created_at': entries.get(kind, {}).get('created_at') or datetime.now(timezone.utc).isoformat()}
            write_metadata(directory, 'outputs.json', {'job_id': job_id, 'files': list(entries.values())})
        finally:
            for temp, *_ in prepared:
                if temp: temp.unlink(missing_ok=True)


def import_existing(job_dir):
    """Backfill only validated finals; never start a model or change old jobs."""
    job_dir = Path(job_dir)
    from audio_translate.core.sealing import opened
    # Sealing here also re-encrypts plaintext left behind by a crashed Basic worker.
    with file_lock(job_dir/'working'/'worker.lock'), opened(job_dir):
        metadata(job_dir)
        job = read_json(job_dir/'job.json')
        job_id = job.get('id', '')
        if not ID.fullmatch(job_id): return
        directory = destination(job_id)
        existing = {item['type']: item for item in read_json(directory/'outputs.json')['files']}
        def archived(step):
            # Startup backfill never replaces an already published generation.
            # Replacements belong to explicit, validated worker publication.
            return all(kind in existing and existing[kind].get('path') == relative and
                       (directory/relative).is_file() for kind, _, relative in output_files(job)[step])
        zh = job_dir/'transcript.zh.jsonl'
        if not zh.exists(): zh = job_dir/'transcript.jsonl'
        if job.get('reprocess_pending') or job.get('status') in ['CANCELLED','DELETING']: return
        if not archived('TRANSCRIPTION') and zh.is_file() and (job_dir/'transcript.zh.md').is_file():
            count_rows(zh, 'text')
            publish_step(job_dir, 'TRANSCRIPTION')
        for step in ['TRANSLATION', 'MODERATION', 'TTS']:
            if archived(step) or any(item.get('step') == step and item.get('status') in ['STALE','PUBLISHING'] for item in existing.values()): continue
            marker = job_dir/'working'/f'{step.lower()}.done.json'
            if not marker.is_file(): continue
            outputs = read_json(marker)['outputs']
            if all((job_dir/name).is_file() and file_digest(job_dir/name) == sha for name, sha in outputs.items()):
                publish_step(job_dir, step)


def cleanup_temporary(job_dir):
    # Checkpoints and inputs remain available for resume. Only abandoned temp
    # files within this workspace are removed; results are never a target.
    directory = Path(job_dir).resolve()
    for temp in directory.rglob('*.tmp'):
        if temp.is_file() and not temp.is_symlink() and temp.resolve().is_relative_to(directory): temp.unlink()


def main():
    try:
        payload = json.loads(sys.stdin.read().lstrip('\ufeff'))
        if payload.get('id'):
            directory = workspace(payload['id'])
            import_existing(directory)
            count = 1
        else:
            count = 0
            # One-level job metadata enumeration, not a recursive filesystem scan.
            seen = set()
            for root in [DATA/'tmp', DATA/'jobs']:
                if not root.exists(): continue
                for directory in root.iterdir():
                    if not ID.fullmatch(directory.name) or directory.name in seen or not (directory/'job.json').is_file(): continue
                    seen.add(directory.name)
                    try:
                        import_existing(directory)
                        count += 1
                    except (LockedError, OSError, ValueError, KeyError):
                        continue  # Busy jobs publish themselves on node completion.
        print(json.dumps({'status': 200, 'imported': count}))
    except LockedError:
        print(json.dumps({'status': 409, 'error': 'Job is busy.'}))
    except Exception:
        print(json.dumps({'status': 500, 'error': 'Cannot publish results. Check storage permissions and configuration.'}))


if __name__ == '__main__': main()
