"""Loading a file into a run at a step the person picks (Reprocess; docs/MANUAL_TRANSLATION.md).

Two phases, so the person sees the check before anything changes:
  prepare()  checks the uploaded file for that step, turns it into the files the step normally makes, and parks them in data/imports/<id>/
             with a report (counts, what is missing, a preview). Nothing of the run is touched.
  apply()    (called by manage.reprocess under the run's lock) copies the parked files into the run; the step before the chosen one counts as
             done with origin "import", earlier steps that were not done count as "skipped", and the run continues from the chosen step.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shutil
import uuid

from audio_translate.core import storage
from audio_translate.core.storage import atomic_json, read_json
from audio_translate.translation import manual_text as text

# The step that gets the file -> the step whose result the file is.
PREVIOUS = {'TRANSCRIPTION': 'DOWNLOAD', 'TRANSLATION': 'TRANSCRIPTION', 'MODERATION': 'TRANSLATION', 'TTS': 'MODERATION'}
ID = re.compile(r'[0-9a-f]{32}')
KEEP_HOURS = 24
TEXT_EXTENSIONS = {'.txt', '.md', '.jsonl'}
# The stages whose file may come in several parts (the translation of each part of tool 7, for example): the parts are kept in the draft, put in the
# order the person gives (check), and read as one text. A translation numbered [n] lands on its paragraphs whatever the order.
MULTI = ('MODERATION', 'TTS')
MAX_FILES = 500
MAX_TOTAL = 64 * 1024 ** 2


def root(): return storage.DATA / 'imports'


def clean_old():
    """Parked files nobody used within a day are removed."""
    if not root().is_dir(): return
    limit = datetime.now(timezone.utc) - timedelta(hours=KEEP_HOURS)
    for folder in root().iterdir():
        try:
            if folder.is_dir() and datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc) < limit: shutil.rmtree(folder, ignore_errors=True)
        except OSError: continue


def _read_text(path, name, limit=64 * 1024 ** 2):
    path = Path(path)
    if Path(name or '').suffix.lower() not in TEXT_EXTENSIONS: raise ValueError('Use UTF-8 TXT, MD or segment JSONL')
    if not path.is_file() or not path.stat().st_size: raise ValueError('Empty upload')
    if path.stat().st_size > limit: raise ValueError('Upload too large')
    try: return path.read_text(encoding='utf-8-sig')
    except UnicodeDecodeError: raise ValueError('Use UTF-8 TXT, MD or segment JSONL')


def _chinese_rows(content, extension):
    """Rows of Chinese text: JSONL rows as they are, a plain text file one paragraph per line (no real time)."""
    rows = []
    if extension == '.jsonl':
        for line in content.splitlines():
            if not line.strip(): continue
            try: row = json.loads(line)
            except ValueError: raise ValueError('JSONL text field is invalid')
            if not isinstance(row, dict) or not isinstance(row.get('text'), str): raise ValueError('JSONL text field is invalid')
            if type(row.get('start_ms')) is not int or type(row.get('end_ms')) is not int: raise ValueError('JSONL needs integer timestamps')
            rows.append({'start_ms': row['start_ms'], 'end_ms': row['end_ms'], 'text': row['text']})
    else:
        for index, line in enumerate(l.strip() for l in content.splitlines() if l.strip()):
            if len(line) > 65536 or '\x00' in line: raise ValueError('Text segment exceeds 64 KiB or contains binary data')
            rows.append({'start_ms': index, 'end_ms': index, 'text': line})
    if not rows: raise ValueError('Input contains no valid text')
    return rows


def _job_paragraphs(job_dir):
    """The Chinese paragraphs of the run (numbers and times), or None when it has no Chinese text yet."""
    for name in ('transcript.zh.jsonl', 'transcript.jsonl'):
        path = Path(job_dir) / name
        if path.is_file():
            try: return text.paragraphs(text.read_rows(path)) or None
            except (ValueError, OSError): return None
    return None


def _vietnamese(content, extension, key, job_dir, job):
    """Rows of Vietnamese text and the report: JSONL with the key kept as it is, TXT/MD matched to the run's Chinese paragraphs."""
    if extension == '.jsonl':
        rows = []
        for line in content.splitlines():
            if not line.strip(): continue
            try: row = json.loads(line)
            except ValueError: raise ValueError('JSONL text field is invalid')
            value = row.get(key) if isinstance(row, dict) else None
            if value is None and isinstance(row, dict) and key == 'text_vi_moderated': value = row.get('text_vi')
            if not isinstance(value, str) or type(row.get('start_ms')) is not int or type(row.get('end_ms')) is not int:
                raise ValueError('JSONL text field is invalid')
            rows.append({'start_ms': row['start_ms'], 'end_ms': row['end_ms'], key: value})
        if not rows: raise ValueError('Input contains no valid text')
        report = {'mode': 'jsonl', 'expected': None, 'found': len(rows), 'missing': [], 'duplicate': [], 'unknown': [], 'empty': [], 'dropped_lines': 0,
                  'han_paragraphs': sum(bool(text.HAN.search(r[key])) for r in rows), 'estimated_time': False, 'out_of_order': False, 'preview': [{'n': i + 1, 'zh': '', 'vi': r[key][:200]} for i, r in enumerate(rows[:3])]}
        return rows, report
    paras = _job_paragraphs(job_dir)
    pairs, report = text.parse_translation(content, paras, job.get('duration_ms') or None)
    blocked = text.blocking(report)
    if blocked: report['blocked'] = blocked; return None, report
    return text.rows_from_pairs(pairs, key), report


def prepare(job_id, step, upload, name, mime=''):
    """Check and park the file for `step`. Returns {import_id, report}; import_id is None when the text cannot be used yet (report.blocked says why)."""
    from audio_translate.workflow import manage, results
    if step not in PREVIOUS: raise ValueError('That stage takes no file')
    directory = results.workspace(job_id)
    job = read_json(directory / 'job.json')
    if job.get('tool_type'): raise ValueError('Loading a file applies to workflows only')
    clean_old()
    import_id = uuid.uuid4().hex
    folder = root() / import_id
    folder.mkdir(parents=True)
    try:
        extension = Path(name or '').suffix.lower()
        meta = {'id': import_id, 'job_id': job_id, 'step': step, 'created_at': datetime.now(timezone.utc).isoformat(), 'name': Path(name or '').name[:120]}
        if step == 'TRANSCRIPTION':
            stub = {'tool_type': 'transcription'}
            (folder / 'source').mkdir()
            manage.normalize_input(folder, stub, upload, name, mime)
            meta.update(duration_ms=stub['duration_ms'], source_ext=stub['source_ext'])
            report = {'mode': 'audio', 'duration_ms': stub['duration_ms'], 'blocked': []}
        else:
            content = _read_text(upload, name)
            if step == 'TRANSLATION':
                rows = _chinese_rows(content, extension)
                paras = text.paragraphs(rows)
                text.write_rows(folder, 'transcript.zh.jsonl', 'transcript.zh.md', rows, 'text')
                (folder / 'transcript.zh.md').write_text('\n\n'.join(p['text'] for p in paras) + '\n', encoding='utf-8', newline='\n')
                report = {'mode': 'zh', 'found': len(paras), 'rows': len(rows), 'blocked': [], 'preview': [{'n': p['n'], 'zh': p['text'][:160], 'vi': ''} for p in paras[:3]],
                          'han_paragraphs': 0, 'missing': [], 'duplicate': [], 'unknown': [], 'empty': [], 'dropped_lines': 0, 'estimated_time': False, 'out_of_order': False, 'expected': None}
            else:
                # A Vietnamese text: the first part of a draft that may get more (add_part), checked in order (check).
                meta['parts'] = []
                _store_part(folder, meta, upload, name)
                atomic_json(folder / 'meta.json', meta)
                return _check(folder, meta, [1], directory, job)
        atomic_json(folder / 'meta.json', meta)
        atomic_json(folder / 'report.json', report)
        return {'import_id': import_id, 'report': report, 'ready': True}
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def _store_part(folder, meta, upload, name):
    """Keep one uploaded file in the draft as it came (it is read again at every check)."""
    name = Path(name or '').name[:120]
    extension = Path(name).suffix.lower()
    if extension not in TEXT_EXTENSIONS: raise ValueError('Use UTF-8 TXT, MD or segment JSONL')
    source = Path(upload)
    if not source.is_file() or not source.stat().st_size: raise ValueError('Empty upload')
    if len(meta['parts']) >= MAX_FILES: raise ValueError('Too many files; load at most 500')
    if sum(p['size'] for p in meta['parts']) + source.stat().st_size > MAX_TOTAL: raise ValueError('Upload too large')
    number = max((p['id'] for p in meta['parts']), default=0) + 1
    (folder / 'parts').mkdir(exist_ok=True)
    shutil.copyfile(source, folder / 'parts' / f'{number:03d}{extension}')
    part = {'id': number, 'name': name, 'size': source.stat().st_size, 'file': f'{number:03d}{extension}'}
    meta['parts'].append(part)
    return part


def _draft(job_id, import_id):
    from audio_translate.workflow import results
    if not isinstance(import_id, str) or not ID.fullmatch(import_id): raise ValueError('The loaded file is no longer available; load it again')
    folder = root() / import_id
    try: meta = read_json(folder / 'meta.json')
    except (OSError, ValueError): raise ValueError('The loaded file is no longer available; load it again')
    if meta.get('job_id') != job_id: raise ValueError('The loaded file belongs to another stage; load it again')
    if meta.get('step') not in MULTI or 'parts' not in meta: raise ValueError('That stage takes one file')
    directory = results.workspace(job_id)
    return folder, meta, directory, read_json(directory / 'job.json')


def add_part(job_id, import_id, upload, name):
    """One more file for a draft. It is not checked here: the page asks for a check with the order it shows."""
    folder, meta, _, _ = _draft(job_id, import_id)
    part = _store_part(folder, meta, upload, name)
    meta['ready'] = False
    atomic_json(folder / 'meta.json', meta)
    return {'import_id': import_id, 'part': {k: part[k] for k in ('id', 'name', 'size')}}


def check(job_id, import_id, order):
    """The draft's files read in `order` (part ids; one left out is not used): the report, and the stage files when they can be used."""
    folder, meta, directory, job = _draft(job_id, import_id)
    known = {p['id'] for p in meta['parts']}
    if not isinstance(order, list) or not order or len(order) != len(set(order)) or any(type(i) is not int or i not in known for i in order):
        raise ValueError('Invalid file order')
    return _check(folder, meta, order, directory, job)


def _part_report(part, content):
    """What one file holds: its [n] numbers, the chatbot lines dropped, paragraphs with Chinese characters left."""
    lines, dropped = text._clean(content.replace('\r\n', '\n').replace('\r', '\n').split('\n'))
    numbers = [int(m.group(1) or m.group(2)) for m in (text.MARKER.match(line) for line in lines) if m]
    has_text = any(line.strip() for line in lines)
    return {'id': part['id'], 'name': part['name'], 'size': part['size'], 'numbers': numbers, 'first': min(numbers) if numbers else None, 'last': max(numbers) if numbers else None,
            'count': len(numbers), 'dropped_lines': dropped, 'han': bool(text.HAN.search(content)), 'empty': not has_text}


def _check(folder, meta, order, directory, job):
    step = meta['step']
    key = 'text_vi' if step == 'MODERATION' else 'text_vi_moderated'
    by_id = {p['id']: p for p in meta['parts']}
    parts = [by_id[i] for i in order]
    extensions = {Path(p['name']).suffix.lower() for p in parts}
    contents = [_read_text(folder / 'parts' / p['file'], p['name']) for p in parts]
    per_part = [_part_report(p, c) for p, c in zip(parts, contents)]
    # A number found in two files: usually the same part loaded twice. The first file in the order keeps it.
    seen = {}
    for item in per_part:
        item['repeats'] = sorted({n for n in item['numbers'] if n in seen})
        item['repeats_of'] = sorted({seen[n] for n in item['numbers'] if n in seen})
        for n in item['numbers']: seen.setdefault(n, item['name'])
        del item['numbers']
    names = ('transcript.vi.jsonl', 'transcript.vi.md') if step == 'MODERATION' else ('transcript.vi.moderated.jsonl', 'transcript.vi.moderated.md')
    for stale in (*names, 'moderation-result.json'): (folder / stale).unlink(missing_ok=True)
    extra = []
    if '.jsonl' in extensions and len(extensions) > 1:
        rows, report = None, {'mode': 'mixed', 'blocked': []}
        extra.append('Do not mix JSONL with text files')
    elif '.jsonl' in extensions:
        rows, report = _vietnamese('\n'.join(contents), '.jsonl', key, directory, job)
        if any(b['start_ms'] < a['start_ms'] for a, b in zip(rows, rows[1:])): extra.append('The JSONL files are not in time order')
    else:
        numbered = [item for item in per_part if item['count']]
        if numbered and any(not item['count'] and not item['empty'] for item in per_part): extra.append('Some files have no [n] numbers')
        # A blank line between two files, so the last paragraph of one never runs into the first of the next.
        rows, report = _vietnamese('\n\n'.join(contents), '.txt', key, directory, job)
    report.setdefault('blocked', [])
    report['blocked'] += extra
    report['parts'] = per_part
    ready = rows is not None and not report['blocked']
    if ready:
        text.write_rows(folder, names[0], names[1], rows, key)
        if step == 'TTS':
            # The Moderation result the published Moderation step expects: nothing was replaced, the person's text is used as it is.
            atomic_json(folder / 'moderation-result.json', {'total_segments': len(rows), 'modified_segments': 0, 'total_replacements': 0, 'imported': True, 'rules': {}})
        report['rows'] = len(rows)
    meta.update(order=order, ready=ready)
    atomic_json(folder / 'meta.json', meta)
    atomic_json(folder / 'report.json', report)
    return {'import_id': meta['id'], 'report': report, 'ready': ready}


def load(import_id, job_id, step):
    """The parked import (its folder and meta) for this run and step; ValueError when it is not there, not this run's, or too old."""
    if not isinstance(import_id, str) or not ID.fullmatch(import_id): raise ValueError('The loaded file is no longer available; load it again')
    folder = root() / import_id
    try: meta = read_json(folder / 'meta.json')
    except (OSError, ValueError): raise ValueError('The loaded file is no longer available; load it again')
    if meta.get('job_id') != job_id or meta.get('step') != step: raise ValueError('The loaded file belongs to another stage; load it again')
    if meta.get('ready') is False: raise ValueError('The loaded files cannot be used yet')
    return folder, meta


FILES = {'TRANSLATION': ['transcript.zh.jsonl', 'transcript.zh.md'], 'MODERATION': ['transcript.vi.jsonl', 'transcript.vi.md'],
         'TTS': ['transcript.vi.moderated.jsonl', 'transcript.vi.moderated.md', 'moderation-result.json']}


def apply(job_dir, step, folder, meta, job):
    """Copy the parked files into the run and change `job` (not saved here). The caller holds the run's lock."""
    job_dir = Path(job_dir)
    if step == 'TRANSCRIPTION':
        source = job_dir / 'source'
        if source.exists(): shutil.rmtree(source)
        source.mkdir()
        shutil.copyfile(folder / 'source' / ('audio' + meta['source_ext']), source / ('audio' + meta['source_ext']))
        job.update(duration_ms=meta['duration_ms'], source_ext=meta['source_ext'], source_upload=True, input_file=meta.get('name') or job.get('input_file'))
        return
    for name in FILES[step]:
        target = job_dir / name
        temp = job_dir / (name + '.import.tmp')
        shutil.copyfile(folder / name, temp)
        temp.replace(target)
    if step == 'TRANSLATION':
        (job_dir / 'transcript.jsonl').unlink(missing_ok=True)
    else:
        # The person's own translation: the machine's character sheet and name list do not describe it, and no forms of address are applied to it.
        for stale in ('working/characters.json', 'working/name-glossary.json', 'transcript.vi.partial.jsonl', 'transcript.vi.partial.md'):
            (job_dir / stale).unlink(missing_ok=True)
        job.update(manual_translation=True, selected_address_profile=None)
        job.pop('translation_mode', None)


def discard(import_id):
    if isinstance(import_id, str) and ID.fullmatch(import_id): shutil.rmtree(root() / import_id, ignore_errors=True)
