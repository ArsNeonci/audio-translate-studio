"""Streaming translation, snapshot moderation, and resumable WAV synthesis."""
import json
import os
import re
import sqlite3
from contextlib import closing, ExitStack
from pathlib import Path

from audio_translate.core.control import check_cancel, Cancelled
from audio_translate.tts.adapters import TranslationAdapter, TTSAdapter, adapter_settings
from audio_translate.moderation.rules import ReplaceEngine, ReplacementRules
from audio_translate.core.storage import (Checkpoints, atomic_json, completed, count_rows, digest, file_digest,
                     finish, progress, read_json, rows, text_outputs, update_job, write_row)


def tool_addresser(job_dir):
    """Tool 2 (Chinese text -> Vietnamese text) applies the chosen forms of address to
    its own output, since a standalone tool never reaches Moderation."""
    job = read_json(Path(job_dir)/'job.json')
    if job.get('tool_type') != 'translation' or not job.get('selected_address_profile'):
        return None
    from audio_translate.moderation.address import resolver
    zh = [{'text_zh': row['text']} for _, row in rows(Path(job_dir)/'transcript.zh.jsonl', 'text')]
    return resolver(job_dir, zh, job['selected_address_profile'])


def is_genius(job_dir):
    return read_json(Path(job_dir)/'job.json').get('translation_mode') == 'genius'


def translation_signature(job_dir, source, config):
    addresser = tool_addresser(job_dir)
    return digest([file_digest(source), config, *([addresser.signature] if addresser else []), *(['genius-v1'] if is_genius(job_dir) else [])])


def stage_complete(job_dir, stage):
    """Check durable outputs before the orchestrator starts any model process."""
    job_dir = Path(job_dir)
    config = adapter_settings(job_dir)
    if stage == "translation":
        source = job_dir / "transcript.zh.jsonl"
        signature = translation_signature(job_dir, source, config["translation"])
    elif stage == "moderation":
        snapshot = job_dir / "working" / "replacement-rules.snapshot.json"
        source = job_dir / "transcript.vi.jsonl"
        if not snapshot.exists() or not source.exists():
            return False
        signature = digest([file_digest(source), read_json(snapshot), "literal-nfc-leftmost-longest-v1"])
    elif stage == "tts":
        source = job_dir / "transcript.vi.moderated.jsonl"
        if not source.exists():
            return False
        signature = digest([file_digest(source), config["tts"]])
    else:
        return False
    if not completed(job_dir, stage, signature):
        return False
    if stage == 'tts':
        try:
            with (job_dir/'voice'/'voice.manifest.jsonl').open(encoding='utf-8') as manifest:
                for line in manifest:
                    item = json.loads(line)
                    name = f"{item['index']:06d}"
                    if item['file'] != name + '.wav': return False
                    wav = job_dir/'voice'/item['file']
                    meta = read_json(job_dir/'working'/'voice-checkpoints'/f'{name}.json')
                    if meta['sha256'] != file_digest(wav): return False
                    audio_info(wav)
        except (OSError, ValueError, KeyError):
            return False
    return True


def translate(job_dir, adapter=None):
    if adapter is None and is_genius(job_dir):
        # Gemini through the billing gateway; no local model is loaded.
        from audio_translate.translation.genius import translate as genius_translate
        return genius_translate(job_dir)
    try:
        return _translate(job_dir,adapter)
    except Exception:
        # Export once at interruption, never repeatedly copy the growing file.
        try:
            if (Path(job_dir)/'working'/'postprocess.sqlite3').exists(): export_translation_partial(job_dir)
        except (OSError,ValueError,KeyError,sqlite3.Error): pass
        raise


def _translate(job_dir, adapter=None):
    job_dir = Path(job_dir)
    source = job_dir / "transcript.zh.jsonl"
    config = adapter_settings(job_dir)["translation"]
    use_context = config.get("backend") == "hy-mt2-gguf"
    signature = translation_signature(job_dir, source, config)
    total = count_rows(source, "text")
    if completed(job_dir, "translation", signature):
        progress(job_dir, "translation", "TRANSLATION_COMPLETED", total, total)
        return
    adapter = adapter or TranslationAdapter(config)
    if isinstance(adapter,TranslationAdapter):adapter.job_dir=job_dir
    if hasattr(adapter, 'translate_stream'):
        return _translate_streaming(job_dir, adapter, source, config, signature, total)
    progress(job_dir, "translation", "TRANSLATING", 0, total)
    names = ["transcript.vi.jsonl", "transcript.vi.md"]
    with ExitStack() as cleanup, Checkpoints(job_dir) as checkpoints, text_outputs(job_dir, *names) as handles:
        if hasattr(adapter, 'close'): cleanup.callback(adapter.close)
        batch = []
        previous_source = ""
        completed_rows = 0
        def flush():
            nonlocal completed_rows
            if not batch:
                return
            missing = [entry for entry in batch if entry[3] is None]
            if missing:
                if hasattr(adapter,'translate_checkpointed'):
                    def part_key(owner,part_id,text):
                        return digest([missing[owner][2],part_id,text,'sentence-token-v2'])
                    def lookup(owner,part_id,text):
                        return checkpoints.get_translation_part(missing[owner][0],part_id,part_key(owner,part_id,text))
                    def save(owner,part_id,source,text):
                        checkpoints.put_translation_part(missing[owner][0],part_id,part_key(owner,part_id,source),text)
                    def save_row(owner,text):
                        index,row,key,_,_=missing[owner]
                        result={'start_ms':row['start_ms'],'end_ms':row['end_ms'],'text_zh':row['text'],
                                'text_vi':apply_glossary(row['text'],text,config.get('glossary',[]))}
                        checkpoints.put('translation',index,key,result)
                        missing[owner][3]=result
                        from audio_translate.core.control import stop_mode
                        if not stop_mode(job_dir):
                            progress(job_dir,'translation','TRANSLATING',completed_rows+sum(entry[3] is not None for entry in batch),total)
                    translated=adapter.translate_checkpointed([entry[1]['text'] for entry in missing],lookup,save,save_row, **({'contexts': [entry[4] for entry in missing]} if use_context else {}))
                else:
                    translated = adapter.translate([entry[1]["text"] for entry in missing])
                if len(translated) != len(missing):
                    raise RuntimeError("Translation adapter changed the segment count")
                for entry, text in zip(missing, translated, strict=True):
                    if not isinstance(text, str) or (entry[1]["text"].strip() and not text.strip()):
                        raise RuntimeError("Invalid translation output")
                    index, row, key, _, _ = entry
                    text=apply_glossary(row['text'],text,config.get('glossary',[]))
                    result = {"start_ms": row["start_ms"], "end_ms": row["end_ms"], "text_zh": row["text"], "text_vi": text}
                    if entry[3] is None: checkpoints.put("translation", index, key, result)
                    entry[3] = result
            for index, _, _, result, _ in batch:
                write_row(handles, result, "text_vi")
            progress(job_dir, "translation", "TRANSLATING", batch[-1][0], total)
            completed_rows = batch[-1][0]
            batch.clear()
        for index, row in rows(source, "text"):
            check_cancel(job_dir)
            context = previous_source if use_context else ""
            key = digest([row, config, context]) if use_context else digest([row, config])
            batch.append([index, row, key, checkpoints.get("translation", index, key), context])
            previous_source = (previous_source + row["text"])[-config.get("context_chars", 512):]
            if len(batch) >= (adapter.window_size() if hasattr(adapter, 'window_size') else config["batch_size"]):
                flush()
        flush()
    finish(job_dir, "translation", signature, names, total)
    progress(job_dir, "translation", "TRANSLATION_COMPLETED", total, total)


def name_glossary(job_dir, source=None):
    """Detected person names, created once per job so Resume uses the same glossary.

    `working/name-glossary.json` may be edited by the user; entries are {source, target}.
    """
    path = Path(job_dir)/'working'/'name-glossary.json'
    if not path.exists():
        if source is None:
            return []
        try:
            from audio_translate.translation.names import detect
            names = detect([row['text'] for _, row in rows(source, 'text')])
        except ImportError:
            names = []
        atomic_json(path, {'version': 1, 'names': names})
    names = read_json(path).get('names', [])
    return [item for item in names if isinstance(item, dict) and isinstance(item.get('source'), str) and item['source']
            and isinstance(item.get('target'), str) and item['target']]


def translation_key(row, config, context, extra):
    """Row checkpoint identity; `extra` carries segmentation mode and the name glossary."""
    if config.get('backend') != 'hy-mt2-gguf':
        return digest([row, config])
    return digest([row, config, context, extra])


def is_styled(job_dir):
    """Jobs created with a voice style carry `selected_address_profile`; older jobs keep legacy behaviour."""
    return 'selected_address_profile' in read_json(Path(job_dir)/'job.json')


def row_extra_builder(extra, repaired, lexicon):
    """Per-row key parts: unchanged for rows the styled layers did not touch, so caches stay valid."""
    def row_extra(index, row):
        changed = index in repaired  # '' (dropped intro) is a change too
        source = repaired[index] if changed else row['text']
        terms = [(item['source'], item['target']) for item in lexicon if item['source'] in source]
        if not changed and not terms: return extra
        return {**extra, **({'zh': source} if changed else {}), **({'lexicon': terms} if terms else {})}
    return row_extra


def styled_state(job_dir, source, config, record=False):
    """(cleaned + gender-repaired Chinese by row index, genre lexicon); both empty for legacy jobs.

    Cleanup (channel intro removal, known ASR mishearings) runs first; '' marks a dropped row.
    """
    if config.get('backend') != 'hy-mt2-gguf' or not is_styled(job_dir): return {}, []
    from audio_translate.moderation.address import Resolver, load_sheet
    from audio_translate.translation.lexicon import entries
    profile = read_json(Path(job_dir)/'job.json').get('selected_address_profile')
    lexicon = entries(profile)
    from audio_translate.translation.source_cleanup import clean
    originals = [(index, row['text']) for index, row in rows(source, 'text')]
    cleaned = clean(originals)
    texts = [(index, cleaned.get(index, text)) for index, text in originals]
    sheet = load_sheet(job_dir, [{'text_zh': text} for _, text in texts])
    repaired, genders = dict(cleaned), 0
    if sheet:
        resolver = Resolver(sheet, profile)
        for index, text in texts:
            fixed = resolver.repair(text)
            if fixed != text: repaired[index] = fixed; genders += 1
    if record:
        atomic_json(Path(job_dir)/'working'/'gender-repair.json', {'rows': genders, 'profile': profile})
        atomic_json(Path(job_dir)/'working'/'source-cleanup.json', {'dropped_rows': sorted(i for i, t in cleaned.items() if not t),
                    'changed_rows': sorted(i for i, t in cleaned.items() if t)})
    return repaired, lexicon


def translation_extra(job_dir, config):
    return {'segmentation': config.get('segmentation', 'sentence'), 'names': digest(name_glossary(job_dir))}


def _translate_streaming(job_dir, adapter, source, config, signature, total):
    """Append the durable contiguous prefix; checkpoints remain authoritative on crash."""
    from audio_translate.core.control import stop_mode, now
    from audio_translate.translation.hymt_translation import output_problem
    adapter.names = name_glossary(job_dir, source) if config.get('backend') == 'hy-mt2-gguf' else []
    extra = translation_extra(job_dir, config)
    repaired, lexicon = styled_state(job_dir, source, config, record=True)
    if is_styled(job_dir) and config.get('backend') == 'hy-mt2-gguf': adapter.lexicon, adapter.gender_check = lexicon, True
    row_extra = row_extra_builder(extra, repaired, lexicon)
    dropped = {index for index, text in repaired.items() if not text.strip()}

    def valid_cache(row, cached, index=None):
        if index in dropped: return isinstance(cached, dict) and cached.get('text_vi') == '' and cached.get('text_zh') == row['text']
        return (isinstance(cached, dict) and cached.get('start_ms') == row['start_ms'] and
                cached.get('end_ms') == row['end_ms'] and cached.get('text_zh') == row['text'] and
                isinstance(cached.get('text_vi'), str) and
                (not row['text'].strip() or output_problem(cached['text_vi'], row['text']) is None))
    names = ['transcript.vi.jsonl', 'transcript.vi.md']
    partial_names = ['transcript.vi.partial.jsonl', 'transcript.vi.partial.md']
    pending = {}
    head, done = 1, 0
    continuation = job_dir/'working'/'translation-continue.json'
    generation = read_json(continuation).get('generation', 0) if continuation.exists() else 0
    with ExitStack() as cleanup, Checkpoints(job_dir) as checkpoints, text_outputs(job_dir, *names) as final_handles:
        if hasattr(adapter, 'close'): cleanup.callback(adapter.close)
        partial = tuple(cleanup.enter_context((job_dir/name).open('w', encoding='utf-8', newline='\n')) for name in partial_names)
        failures = {item['row']: item for item in checkpoints.translation_failures()}
        previous = ''
        for index, row in rows(source, 'text'):
            key = translation_key(row, config, previous, row_extra(index, row))
            if valid_cache(row, checkpoints.get('translation', index, key), index): done += 1
            previous = (previous + row['text'])[-config.get('context_chars', 512):]
        progress(job_dir, 'translation', 'TRANSLATING', done, total)

        from audio_translate.core.edition import is_basic
        hide_source = is_basic()

        def emit_errors():
            # The UI reads this file directly; Basic never shows the Chinese row.
            failures = checkpoints.translation_failures()
            if hide_source: failures = [{k: v for k, v in item.items() if k != 'source'} for item in failures]
            atomic_json(job_dir/'working'/'translation-errors.json', {'failures': failures})

        def entries():
            previous = ''
            for index, row in rows(source, 'text'):
                context = previous if config.get('backend') == 'hy-mt2-gguf' else ''
                key = translation_key(row, config, context, row_extra(index, row))
                previous = (previous + row['text'])[-config.get('context_chars', 512):]
                pending[index] = dict(row=row, key=key, result=None)
                cached = checkpoints.get('translation', index, key)
                if not valid_cache(row, cached, index): cached = None
                failure = failures.get(index)
                recovery = generation if failure and failure.get('fingerprint') == key else 0
                # The prompt uses the gender-repaired Chinese; stored rows keep `text_zh` as transcribed.
                yield index, repaired.get(index, row['text']), context, cached, recovery

        def lookup(index, part, text):
            cached = checkpoints.get_translation_part(index, part, digest([pending[index]['key'], part, text, 'sentence-token-v2']))
            return cached if isinstance(cached, str) and (not text.strip() or output_problem(cached, text) is None) else None

        def save(index, part, source_text, text):
            checkpoints.put_translation_part(index, part, digest([pending[index]['key'], part, source_text, 'sentence-token-v2']), text)

        addresser = tool_addresser(job_dir)

        def save_row(index, text, cached=False):
            nonlocal head, done
            entry = pending[index]
            row = entry['row']
            result = text if cached else dict(start_ms=row['start_ms'], end_ms=row['end_ms'], text_zh=row['text'],
                                             text_vi=apply_glossary(row['text'], text, config.get('glossary', [])))
            if not isinstance(result.get('text_vi'), str) or (row['text'].strip() and not result['text_vi'].strip() and index not in dropped):
                raise RuntimeError('Invalid translation output')
            if not cached: checkpoints.put('translation', index, entry['key'], result)
            entry['result'] = result
            if index in failures:
                checkpoints.resolve_translation_failure(index)
                failures.pop(index, None)
                emit_errors()
            if not cached: done += 1
            wrote = False
            while head in pending and pending[head]['result'] is not None:
                value = pending.pop(head)['result']
                if addresser:
                    # Stateful referent window: applied in row order at export; checkpoints stay raw.
                    value = {**value, 'text_vi': addresser.apply(value)[0]}
                write_row(final_handles, value, 'text_vi')
                write_row(partial, value, 'text_vi')
                head += 1
                wrote = True
            if wrote and (not cached or head % 64 == 0 or head == total+1):
                for handle in partial:
                    handle.flush()
                    os.fsync(handle.fileno())
            if not cached or head == total+1:
                atomic_json(job_dir/'working'/'translation-progress.json',
                            {'done': done, 'total': total, 'exported_rows': head-1, 'buffered_rows': len(pending),
                             **getattr(adapter, 'group_stats', {})})
                if not stop_mode(job_dir): progress(job_dir, 'translation', 'TRANSLATING', done, total)

        def fail_row(index, part, source_text, exc):
            row = pending[index]['row']
            detail = dict(row=index, part=part, start_ms=row['start_ms'], end_ms=row['end_ms'],
                          source=source_text, fingerprint=pending[index]['key'], reason=str(exc), failed_at=now(),
                          generation=generation, attempts=getattr(exc, 'attempts', []))
            prior = failures.get(index)
            detail['failure_count'] = (prior.get('failure_count', 0) if prior else 0) + 1
            checkpoints.put_translation_failure(index, part, pending[index]['key'], detail)
            failures[index] = detail
            emit_errors()

        emit_errors()
        adapter.translate_stream(entries(), lookup, save, save_row, fail_row)
        if done != total or head != total+1:
            raise RuntimeError('Translation ended with missing rows')
    finish(job_dir, 'translation', signature, names, total)
    progress(job_dir, 'translation', 'TRANSLATION_COMPLETED', total, total)


def apply_glossary(source,target,entries):
    """Source-aware normalization of explicitly supplied target variants."""
    replacements={}
    for entry in entries:
        if not isinstance(entry,dict) or not isinstance(entry.get('source'),str) or not entry['source'] or not isinstance(entry.get('target'),str) or not entry['target']:
            raise ValueError('Invalid translation glossary entry')
        variants=entry.get('variants',[])
        if not isinstance(variants,list) or any(not isinstance(v,str) or not v for v in variants):
            raise ValueError('Invalid translation glossary variants')
        if entry['source'] in source:
            for variant in variants:
                if variant in replacements and replacements[variant]!=entry['target']: raise ValueError('Conflicting translation glossary variants')
                replacements[variant]=entry['target']
    if not replacements:return target
    pattern='|'.join(re.escape(v) for v in sorted(replacements,key=len,reverse=True))
    return re.sub(r'(?<!\w)(?:'+pattern+r')(?!\w)',lambda m:replacements[m.group()],target)


def export_translation_partial(job_dir):
    """Export the complete, valid row prefix without loading a model or resuming."""
    job_dir=Path(job_dir).resolve()
    config=read_json(job_dir/'working'/'adapters.json')['translation']
    database=job_dir/'working'/'postprocess.sqlite3'
    names=['transcript.vi.partial.jsonl','transcript.vi.partial.md']
    paths=[job_dir/name for name in names]
    temporary=[path.with_name(path.name+'.tmp') for path in paths]
    count=0
    previous_source=""
    extra=translation_extra(job_dir,config)
    repaired,lexicon=styled_state(job_dir,job_dir/'transcript.zh.jsonl',config)
    row_extra=row_extra_builder(extra,repaired,lexicon)
    dropped={index for index,text in repaired.items() if not text.strip()}
    from audio_translate.translation.hymt_translation import output_problem
    try:
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db, temporary[0].open('w',encoding='utf-8',newline='\n') as jout, temporary[1].open('w',encoding='utf-8',newline='\n') as mout:
            for index,row in rows(job_dir/'transcript.zh.jsonl','text'):
                found=db.execute('SELECT fingerprint,output FROM segments WHERE stage=? AND idx=?',('translation',index)).fetchone()
                key=translation_key(row,config,previous_source,row_extra(index,row))
                if not found or found[0]!=key:break
                value=json.loads(found[1])
                if config.get('backend')=='hy-mt2-gguf' and (
                        not isinstance(value,dict) or value.get('start_ms')!=row['start_ms'] or
                        value.get('end_ms')!=row['end_ms'] or value.get('text_zh')!=row['text'] or
                        not isinstance(value.get('text_vi'),str) or
                        (row['text'].strip() and index not in dropped and output_problem(value['text_vi'],row['text']) is not None)):
                    break
                previous_source=(previous_source+row['text'])[-config.get('context_chars',512):]
                write_row((jout,mout),value,'text_vi'); count+=1
            for handle in (jout,mout):handle.flush(); os.fsync(handle.fileno())
        for source,target in zip(temporary,paths):os.replace(source,target)
    finally:
        for path in temporary:path.unlink(missing_ok=True)
    return {'rows':count,'files':[str(path) for path in paths],'complete':count==count_rows(job_dir/'transcript.zh.jsonl','text')}


def moderate(job_dir, service=None, after_segment=None):
    job_dir = Path(job_dir)
    source = job_dir / "transcript.vi.jsonl"
    service = service or ReplacementRules()
    total = count_rows(source, "text_vi")
    snapshot_path = job_dir / "working" / "replacement-rules.snapshot.json"
    # Even a resumed job uses the first snapshot, regardless of subsequent CRUD.
    with service.locked():
        try:
            if not snapshot_path.exists():
                atomic_json(snapshot_path, service.read())
            snapshot = read_json(snapshot_path)
            engine = ReplaceEngine(snapshot)
            from audio_translate.moderation.address import resolver as address_resolver
            # Forms of address run before literal rules so user rules still win.
            # None (neutral, no manual forms) keeps the legacy signature and keys.
            addresser = address_resolver(job_dir, [row for _, row in rows(source, "text_vi")],
                                         read_json(job_dir / "job.json").get("selected_address_profile"))
            flow = None
            if is_styled(job_dir):
                from audio_translate.moderation.flow import Flow
                flow = Flow([row["text_vi"] for _, row in rows(source, "text_vi")], [n["target"] for n in name_glossary(job_dir)])
            signature = digest([file_digest(source), snapshot, "literal-nfc-leftmost-longest-v1",
                                *([addresser.signature] if addresser else []), *(["flow-v1"] if flow else [])])
            if completed(job_dir, "moderation", signature):
                progress(job_dir, "moderation", "MODERATION_COMPLETED", total, total)
                return
            progress(job_dir, "moderation", "MODERATING", 0, total)
            names = ["transcript.vi.moderated.jsonl", "transcript.vi.moderated.md"]
            stats = {"total_segments": total, "modified_segments": 0, "total_replacements": 0,
                     "rules_snapshot_sha256": digest(snapshot), "rules": {r["id"]: 0 for r in snapshot}}
            if addresser: stats.update(address_profile=addresser.profile, address_replacements=0, address_segments=0)
            previous_vi = ""
            with Checkpoints(job_dir) as checkpoints, text_outputs(job_dir, *names) as handles:
                for index, row in rows(source, "text_vi"):
                    check_cancel(job_dir)
                    flowed = flow.apply(previous_vi, row["text_vi"]) if flow else row["text_vi"]
                    previous_vi = row["text_vi"]
                    if addresser:
                        # Stateful (referent window): runs for every row, cached or not.
                        addressed, address_changes = addresser.apply({**row, "text_vi": flowed})
                        key = digest([row, snapshot, "literal-nfc-leftmost-longest-v1", addresser.signature, addressed])
                    else:
                        addressed, address_changes = flowed, 0
                        key = digest([row, snapshot, "literal-nfc-leftmost-longest-v1", *(["flow-v1", flowed] if flow else [])])
                    cached = checkpoints.get("moderation", index, key)
                    if cached is None:
                        text, counts = engine.apply(addressed)
                        moderated = {**row, "text_vi_moderated": text}
                        if addresser: moderated["address_changes"] = address_changes
                        cached = {"row": moderated, "counts": counts}
                        checkpoints.put("moderation", index, key, cached)
                    result, counts = cached["row"], cached["counts"]
                    if addresser:
                        stats["address_replacements"] += address_changes
                        stats["address_segments"] += int(address_changes > 0)
                    stats["modified_segments"] += int(result["text_vi_moderated"] != row["text_vi"])
                    stats["total_replacements"] += sum(counts.values())
                    for rule_id, count in counts.items():
                        stats["rules"][rule_id] += count
                    write_row(handles, result, "text_vi_moderated")
                    if index % 25 == 0 or index == total:
                        progress(job_dir, "moderation", "MODERATING", index, total)
                    if after_segment:
                        after_segment(index)
            atomic_json(job_dir / "moderation-result.json", stats)
            finish(job_dir, "moderation", signature, [*names, "moderation-result.json"], total)
            progress(job_dir, "moderation", "MODERATION_COMPLETED", total, total)
        except Cancelled:
            raise
        except Exception as exc:
            # Publish FAILED before releasing the lock, even for standalone runs.
            update_job(job_dir, status="FAILED", failed_stage="moderation", error=f"{type(exc).__name__}: {exc}")
            raise


def audio_info(path):
    import soundfile as sf
    info = sf.info(str(path))
    if info.channels != 1 or info.samplerate != 48000 or info.subtype != "PCM_16" or info.frames <= 0:
        raise ValueError("Invalid completed segment WAV")
    return info.frames


def concatenate(job_dir, manifest):
    import numpy as np
    import soundfile as sf
    total_frames = 0
    with manifest.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            total_frames += audio_info(job_dir / "voice" / row["file"]) + gap_frames(row)
    target = job_dir / "voice.vi.wav"
    temp = job_dir / "voice.vi.wav.tmp"
    # RIFF WAV cannot represent 40h of PCM. RF64 is its 64-bit WAV extension.
    fmt = "RF64" if total_frames * 2 + 128 >= 0xFFFFFFFF else "WAV"
    try:
        with sf.SoundFile(str(temp), "w", samplerate=48000, channels=1, subtype="PCM_16", format=fmt) as out:
            with manifest.open(encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    with sf.SoundFile(str(job_dir / "voice" / row["file"])) as source:
                        for block in source.blocks(blocksize=65536, dtype="int16"):
                            check_cancel(job_dir)
                            out.write(block)
                    # Styled narration owns its pauses; legacy manifests have none.
                    if gap_frames(row): out.write(np.zeros(gap_frames(row), dtype=np.int16))
        check_cancel(job_dir)
        audio_info(temp)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def gap_frames(row):
    return int(row.get("gap_after_ms") or 0) * 48


def synthesize(job_dir, adapter=None):
    job_dir = Path(job_dir)
    # This is the ONLY text input for TTS. Missing moderation is a hard failure.
    source = job_dir / "transcript.vi.moderated.jsonl"
    config = adapter_settings(job_dir)["tts"]
    signature = digest([file_digest(source), config])
    from audio_translate.tts.voice_styles import units
    style = config.get("style")
    total = sum(1 for _ in units(rows(source, "text_vi_moderated"), style))
    if stage_complete(job_dir, "tts"):
        progress(job_dir, "tts", "TTS_GENERATING", total, total)
        return
    progress(job_dir, "tts", "TTS_GENERATING", 0, total)
    runtime = None
    if adapter is None and config.get('backend') == 'remote':
        # Basic: the VPS generates the voice; nothing is loaded locally.
        from audio_translate.tts.remote import RemoteTTS
        runtime = RemoteTTS(job_dir, config)
    elif adapter is None:
        from audio_translate.tts.tts_runtime import Runtime, policy
        if config['device'] == 'cpu' and policy()['enabled']:
            runtime = Runtime(job_dir,config)
        else: adapter = TTSAdapter(config)
    elif hasattr(adapter,'synthesize_many'):runtime=adapter
    voice = job_dir / "voice"
    voice.mkdir(exist_ok=True)
    checkpoint_dir = job_dir / "working" / "voice-checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    manifest = voice / "voice.manifest.jsonl"
    manifest_tmp = manifest.with_suffix(".jsonl.tmp")
    done_count=0
    batch=[]
    def flush(out):
        nonlocal done_count
        pending=[];by_index={entry[0]:entry for entry in batch}
        def commit(item):
            nonlocal done_count
            index,_,temp=item
            _,unit,key,wav,meta=by_index[index]
            frames=audio_info(temp)
            atomic_json(meta,{"fingerprint":key,"sha256":file_digest(temp),"frames":frames})
            os.replace(temp,wav)
            done_count+=1;progress(job_dir,"tts","TTS_GENERATING",done_count,total)
        for index,unit,key,wav,meta in batch:
            saved=read_json(meta) if meta.exists() else None
            reusable=saved and saved['fingerprint']==key and wav.exists() and saved['sha256']==file_digest(wav)
            if reusable:audio_info(wav);done_count+=1
            else:pending.append((index,unit[2],wav.with_suffix('.wav.tmp')))
        try:
            if runtime:runtime.synthesize_many(pending,commit)
            else:
                for item in pending:
                    check_cancel(job_dir);adapter.synthesize(item[1],item[2]);commit(item)
        finally:
            for _,_,temp in pending:temp.unlink(missing_ok=True)
        for index,unit,_,wav,_ in batch:
            _,members,text,gap=unit
            entry={"index":index,"start_ms":members[0]['start_ms'],"end_ms":members[-1]['end_ms'],"text":text,"file":wav.name}
            if gap is not None:entry.update(rows=len(members),gap_after_ms=gap)
            out.write(json.dumps(entry,ensure_ascii=False)+'\n')
        out.flush();progress(job_dir,"tts","TTS_GENERATING",done_count,total);batch.clear()
    try:
        with manifest_tmp.open("w", encoding="utf-8", newline="\n") as out:
            for unit in units(rows(source, "text_vi_moderated"), style):
                check_cancel(job_dir)
                index, members, text, _ = unit
                # Legacy key for per-row units keeps existing checkpoints reusable.
                key = digest([members[0], config]) if style is None else digest([members, text, config])
                wav = voice / f"{index:06d}.wav"
                meta = checkpoint_dir / f"{index:06d}.json"
                batch.append((index,unit,key,wav,meta))
                if (runtime.full(batch) if hasattr(runtime,'full') else len(batch)>=(max(4,(psutil_cores())*2) if runtime else 1)):flush(out)
            if batch:flush(out)
        check_cancel(job_dir)
        os.replace(manifest_tmp, manifest)
    finally:
        manifest_tmp.unlink(missing_ok=True)
        if runtime:runtime.close()
    concatenate(job_dir, manifest)
    finish(job_dir, "tts", signature, ["voice/voice.manifest.jsonl", "voice.vi.wav"], total)
    if hasattr(runtime, 'finished'): runtime.finished()
    progress(job_dir, "tts", "TTS_GENERATING", total, total)


def psutil_cores():
    import psutil
    return psutil.cpu_count(logical=False) or 1
