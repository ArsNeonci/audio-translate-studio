"""Genius mode: Translation runs on Gemini through the billing gateway (billing-gateway/ on the VPS).

The transcript is cleaned as in Normal mode, cut into chunks of `chunk_rows` rows and sent with
read-only context rows and a rolling character card (no whole-story preparation pass). The
gateway checks every row, repairs failing ids, bills finished Vietnamese characters once per
row and returns rows it could not fix as flagged; those keep their best draft for Tool 4.

Each chunk result is checkpointed, so Resume never resends (or re-bills) a finished chunk.
A Translation run has its own gateway job ID; Reprocess removes `genius-state.json`, so a
reprocessed translation is billed as a new job. The credit limit or a rejected license pauses
the workflow (`pause_reason`); Continue resumes after the cause is fixed.
"""
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from audio_translate.core.control import Cancelled, check_cancel, now, stop_mode
from audio_translate.core.storage import (ROOT, Checkpoints, atomic_json, completed, count_rows, digest, finish,
                                          progress, read_json, rows, text_outputs, update_job, write_row)

CONFIG = ROOT/'worker'/'config'/'genius.json'
FOREIGN = re.compile(r'[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]')
KEY_VERSION = 'genius-v1'


def settings():
    return {'endpoint': '', 'chunk_rows': 100, 'context_rows': 12, 'max_characters': 30,
            'request_timeout_seconds': 900, 'max_wait_seconds': 600, **read_json(CONFIG)}


def configured():
    endpoint = settings().get('endpoint') or ''
    return endpoint.startswith('https://') or endpoint.startswith('http://127.0.0.1')


class GatewayError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(f'{status} {code}')


def credential():
    from audio_translate.core.license_gate import native_command
    result = native_command({'action': 'credential'})
    if result.get('status') != 'ACTIVE' or not result.get('token'): raise GatewayError(401, result.get('status', 'INVALID'))
    return result['token']


# Cloudflare rejects urllib's default User-Agent (error 1010).
USER_AGENT = 'audio-translate-app/1'


def post(endpoint, path, body, token, timeout):
    request = urllib.request.Request(endpoint.rstrip('/') + path, json.dumps(body, ensure_ascii=False).encode(),
                                     {'Content-Type': 'application/json', 'Authorization': f'License {token}',
                                      'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response: return json.load(response)
    except urllib.error.HTTPError as error:
        try: code = json.load(error).get('error', 'GATEWAY_ERROR')
        except Exception: code = 'GATEWAY_ERROR'
        raise GatewayError(error.code, code) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        raise GatewayError(0, 'UNREACHABLE') from None


def get(endpoint, path, token, timeout):
    request = urllib.request.Request(endpoint.rstrip('/') + path, headers={'Authorization': f'License {token}', 'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response: return json.load(response)
    except urllib.error.HTTPError as error:
        try: code = json.load(error).get('error', 'GATEWAY_ERROR')
        except Exception: code = 'GATEWAY_ERROR'
        raise GatewayError(error.code, code) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        raise GatewayError(0, 'UNREACHABLE') from None


def pause(job_dir, reason):
    """Stop like a user pause; Continue (resume) clears the reason and the signal."""
    update_job(job_dir, pause_reason=reason)
    atomic_json(Path(job_dir)/'working'/'cancel.signal', {'requested_at': now(), 'mode': 'pause', 'reason': reason})
    raise Cancelled(reason)


def initial_card(job_dir, source):
    """Free starting card: detected Han-Viet names, plus genders from a character sheet if present."""
    from audio_translate.workflow.postprocess import name_glossary
    card = {item['source']: {'zh': item['source'], 'vi': item['target'], 'gender': 'unknown', 'note': ''}
            for item in name_glossary(job_dir, source)}
    sheet = Path(job_dir)/'working'/'characters.json'
    if sheet.exists():
        try:
            for item in read_json(sheet).get('characters', []):
                if isinstance(item, dict) and isinstance(item.get('source'), str) and item['source']:
                    card[item['source']] = {'zh': item['source'], 'vi': item.get('target') or card.get(item['source'], {}).get('vi', ''),
                                            'gender': item.get('gender') or 'unknown', 'note': ''}
        except (OSError, ValueError, AttributeError): pass
    return list(card.values())


def merge_card(card, updates, limit):
    merged = {item['zh']: item for item in card}
    for item in updates:
        if isinstance(item, dict) and isinstance(item.get('zh'), str) and item['zh'].strip():
            merged.pop(item['zh'], None)
            merged[item['zh']] = {k: str(item.get(k) or ('unknown' if k == 'gender' else ''))[:200] for k in ('zh', 'vi', 'gender', 'note')}
    return list(merged.values())[-limit:]  # Most recently seen characters.


def readable(text):
    """Best draft of a row the gateway could not fix: foreign script removed for narration."""
    return re.sub(r'\s+', ' ', FOREIGN.sub('', text)).strip() or '…'


def translate(job_dir, send=None, token=None, sleep=time.sleep):
    job_dir = Path(job_dir)
    try:
        return _translate(job_dir, send, token, sleep)
    except Cancelled:
        if stop_mode(job_dir) == 'cancel': _finish(job_dir, 'CANCELLED', send, token)
        raise


def _finish(job_dir, status, send, token):
    state_path = job_dir/'working'/'genius-state.json'
    if not state_path.exists(): return
    config = settings()
    try:
        (send or post)(config['endpoint'], f"/v1/jobs/{read_json(state_path)['billing_job_id']}/finish", {'status': status},
                       token or credential(), 60)
    except Exception: pass  # The gateway marks idle jobs ABANDONED; billing already happened per chunk.


def _translate(job_dir, send, token, sleep):
    from audio_translate.tts.adapters import adapter_settings
    from audio_translate.workflow.postprocess import translation_signature
    from audio_translate.translation.source_cleanup import clean
    source = job_dir/'transcript.zh.jsonl'
    signature = translation_signature(job_dir, source, adapter_settings(job_dir)['translation'])
    total = count_rows(source, 'text')
    if completed(job_dir, 'translation', signature):
        progress(job_dir, 'translation', 'TRANSLATION_COMPLETED', total, total)
        return
    config, job = settings(), read_json(job_dir/'job.json')
    send = send or post
    try: token = token or credential()
    except GatewayError: pause(job_dir, 'LICENSE_REJECTED')
    originals = list(rows(source, 'text'))
    cleaned = clean([(index, row['text']) for index, row in originals])
    texts = {index: cleaned.get(index, row['text']) for index, row in originals}
    state_path = job_dir/'working'/'genius-state.json'
    state = read_json(state_path) if state_path.exists() else {
        'billing_job_id': str(uuid.uuid4()), 'characters': initial_card(job_dir, source), 'billed': {}}
    atomic_json(state_path, state)

    def key(index, row): return digest([row, texts[index], KEY_VERSION])

    def valid(row, cached):
        return (isinstance(cached, dict) and cached.get('start_ms') == row['start_ms'] and cached.get('end_ms') == row['end_ms']
                and cached.get('text_zh') == row['text'] and isinstance(cached.get('text_vi'), str))

    with Checkpoints(job_dir) as checkpoints:
        results = {}
        for index, row in originals:
            cached = checkpoints.get('translation', index, key(index, row))
            if valid(row, cached): results[index] = cached
            elif not texts[index].strip():
                # Channel intro removed by cleanup, or an empty ASR row: nothing to translate or bill.
                results[index] = {'start_ms': row['start_ms'], 'end_ms': row['end_ms'], 'text_zh': row['text'], 'text_vi': ''}
                checkpoints.put('translation', index, key(index, row), results[index])
        wanted = [index for index, _ in originals if texts[index].strip()]
        size = max(1, int(config['chunk_rows']))
        chunks = [wanted[at:at + size] for at in range(0, len(wanted), size)]
        by_index = dict(originals)

        def report():
            flagged = sorted(i for i, r in results.items() if r.get('genius_flagged'))
            atomic_json(job_dir/'working'/'genius-progress.json', {
                'chunks_done': sum(all(i in results for i in ids) for ids in chunks), 'chunks_total': len(chunks),
                'rows_done': len(results), 'rows_total': total, 'flagged_rows': flagged,
                'billed_chars': sum(state['billed'].values())})
            if not stop_mode(job_dir): progress(job_dir, 'translation', 'TRANSLATING', len(results), total)

        report()
        for number, ids in enumerate(chunks):
            if all(i in results for i in ids): continue
            check_cancel(job_dir)
            before = [i for i in wanted if i < ids[0]][-int(config['context_rows']):]
            request = {'chunk_no': number, 'kind': 'tool' if job.get('storage_scope') == 'tools' else 'workflow',
                       'label': str(job.get('name') or '')[:200], 'rows_total': len(wanted),
                       'rows': [{'id': i, 'zh': texts[i]} for i in ids],
                       'context': [{'id': i, 'zh': texts[i], **({'vi': results[i]['text_vi']} if i in results and not results[i].get('genius_flagged') else {})} for i in before],
                       'characters': state['characters'][-int(config['max_characters']):]}
            response = _request(job_dir, config, state, state_path, request, send, token, sleep)
            returned = {item['id']: item for item in response.get('rows', []) if isinstance(item, dict)}
            if set(returned) != set(ids): raise RuntimeError('Genius gateway returned a different row set')
            for i in ids:
                item, row = returned[i], by_index[i]
                ok = item.get('ok') is True and isinstance(item.get('vi'), str) and item['vi'].strip()
                result = {'start_ms': row['start_ms'], 'end_ms': row['end_ms'], 'text_zh': row['text'],
                          'text_vi': item['vi'].strip() if ok else readable(str(item.get('vi') or ''))}
                if not ok: result['genius_flagged'] = True
                checkpoints.put('translation', i, key(i, row), result)
                results[i] = result
            state['characters'] = merge_card(state['characters'], response.get('characters', []), int(config['max_characters']))
            state['billed'][str(number)] = int(response.get('billed_chars') or 0)
            atomic_json(state_path, state)
            report()
        names = ['transcript.vi.jsonl', 'transcript.vi.md']
        with text_outputs(job_dir, *names) as handles:
            for index, _ in originals:
                write_row(handles, {k: v for k, v in results[index].items() if k != 'genius_flagged'}, 'text_vi')
    finish(job_dir, 'translation', signature, names, total)
    _finish(job_dir, 'COMPLETED', send, token)
    progress(job_dir, 'translation', 'TRANSLATION_COMPLETED', total, total)


def _request(job_dir, config, state, state_path, request, send, token, sleep):
    waited, renewed = 0, False
    while True:
        check_cancel(job_dir)
        try:
            return send(config['endpoint'], '/v1/translate', {**request, 'job_id': state['billing_job_id']}, token,
                        int(config['request_timeout_seconds']))
        except GatewayError as error:
            if error.status == 402: pause(job_dir, 'CREDIT_LIMIT')
            if error.status in (401, 403): pause(job_dir, 'LICENSE_REJECTED')
            if error.status == 409 and error.code in ('JOB_CLOSED', 'CHUNK_MISMATCH') and not renewed:
                # The gateway closed this run (idle 24 h, or chunking changed): finished rows stay
                # checkpointed and billed; the remaining rows continue as a new gateway job.
                state['billing_job_id'] = str(uuid.uuid4()); atomic_json(state_path, state); renewed = True
                continue
            if error.status == 400: raise RuntimeError(f'Genius gateway rejected the request: {error.code}') from None
            delay = 30 if error.code == 'CHUNK_BUSY' else min(60, 5 * 2 ** min(4, waited // 30))
            if waited >= int(config['max_wait_seconds']): pause(job_dir, 'GATEWAY_UNAVAILABLE')
            sleep(delay); waited += delay
