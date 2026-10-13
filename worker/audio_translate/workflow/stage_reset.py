"""Fresh failed-stage restart. Never delete predecessor inputs/shared models."""
import sqlite3
from contextlib import closing
from pathlib import Path
from audio_translate.core.storage import read_json, atomic_json
from audio_translate.workflow import results


def reset(job_dir, step):
    job_dir=Path(job_dir).resolve()
    patterns={
        'DOWNLOAD':['source/*'],
        'TRANSCRIPTION':['transcript.zh.*','transcript.jsonl','transcript*.tmp',
            'working/chunk-*','working/chunks.json','working/vad*','working/transcription-progress.json','working/asr-runtime.json'],
        'TRANSLATION':['transcript.vi.jsonl*','transcript.vi.md*','transcript.vi.partial.*','working/translation.done.json','working/translation-runtime.json','working/translation-server.log','working/translation-errors.json','working/translation-progress.json','working/translation-continue.json','working/genius-state.json'],
        'MODERATION':['transcript.vi.moderated.*','moderation-result*','working/moderation.done.json','working/replacement-rules.snapshot.json'],
        'TTS':['voice/*','voice.vi.wav*','working/voice-checkpoints/*','working/tts.done.json','working/tts-runtime.json','working/tts-worker-*.log','working/tts-calibration/*','working/tts-remote-state.json','working/tts-remote-progress.json'],
    }
    job_file=job_dir/'job.json'
    if step=='DOWNLOAD' and job_file.exists() and read_json(job_file).get('source_upload'):
        patterns['DOWNLOAD']=[]  # The uploaded audio is the only copy: never delete it.
    targets=[]
    for pattern in patterns[step]:
        for path in job_dir.glob(pattern):
            if path.is_symlink() or not path.resolve().is_relative_to(job_dir):
                raise ValueError('Unsafe stage reset path')
            if path.is_file():targets.append(path)
    output=results.destination(job_dir.name)
    manifest=read_json(output/'outputs.json') if (output/'outputs.json').exists() else {'files':[]}
    for item in manifest['files']:
        if item['step']==step:
            target=output/item['path']
            if target.is_symlink() or any(parent.is_symlink() for parent in target.parents if parent!=output.parent) or not target.resolve().is_relative_to(output.resolve()):
                raise ValueError('Unsafe published output path')
            if target.is_file():targets.append(target)
    # Validate all target paths first, then delete exact files only.
    for path in targets:path.unlink(missing_ok=True)
    database=job_dir/'working'/'postprocess.sqlite3'
    if database.exists():
        with closing(sqlite3.connect(database)) as db:
            with db:
                db.execute('DELETE FROM segments WHERE stage=?',(step.lower(),))
                if step=='TRANSLATION' and db.execute("SELECT 1 FROM sqlite_master WHERE name='translation_parts'").fetchone():
                    db.execute('DELETE FROM translation_parts')
                if step=='TRANSLATION' and db.execute("SELECT 1 FROM sqlite_master WHERE name='translation_failures'").fetchone():
                    db.execute('DELETE FROM translation_failures')
    manifest['files']=[item for item in manifest['files'] if item['step']!=step]
    if output.exists():atomic_json(output/'outputs.json',manifest)
    (job_dir/'working'/'cancel.signal').unlink(missing_ok=True)
