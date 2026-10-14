"""Stop, pause, resume, reprocess, review, abort and delete a run (was lib/server/management.ts)."""
import json

from audio_translate.api.license import license_denial
from audio_translate.api.runtime import worker_command
from audio_translate.api.web import json_response

TRANSLATION_MODES = ('normal', 'genius')
STARTS_WORK = ('reprocess', 'resume', 'review')
NO_BODY = ('cancel', 'pause', 'resume')
# Set by the scheduler module when it owns the queue (G4 jobs group): called after an action that may start work.
after_start = []


def management_response(body, job_id, action, scope='workflows'):
    """Blocking; `body` is the request body as text. Returns a Response."""
    if action in STARTS_WORK:
        denied = license_denial()
        if denied: return denied
    payload = {}
    if action not in NO_BODY:
        if len(body) > (65536 if action == 'reprocess' else 4096): return json_response({'error': 'Request too large'}, 413)   # reprocess may carry video paths
        try: payload = json.loads(body)
        except ValueError: return json_response({'error': 'Invalid JSON'}, 400)
        if not isinstance(payload, dict): payload = {}
    if action == 'reprocess' and 'mode' in payload and payload['mode'] not in TRANSLATION_MODES:
        return json_response({'error': 'Invalid translation mode'}, 400)
    if action == 'reprocess' and 'video' in payload and not isinstance(payload['video'], dict):
        return json_response({'error': 'Invalid video settings'}, 400)
    result = worker_command('manage.py', {**payload, 'action': action, 'id': job_id, 'scope': scope})
    status = result.pop('status')
    if status == 200 and action in STARTS_WORK:
        for hook in after_start: hook()
    return json_response(result, status, no_store=True)


ROLES = ('narrator', 'family', 'lover', 'friend', 'antagonist', 'other')
RANKS = ('elder', 'senior', 'peer', 'junior')


def _text(value, limit):
    import re
    return isinstance(value, str) and len(value) <= limit and not re.search(r'[\x00-\x1f<>]', value)


def valid_character_sheet(value):
    """lib/shared/address-profiles.ts validCharacterSheet: a normalized sheet, or None."""
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('characters'), list) or len(value['characters']) > 200: return None
    characters = []
    for item in value['characters']:
        if not isinstance(item, dict): item = {}
        raw = item.get('aliases')
        aliases = [a for a in ((a.strip() if isinstance(a, str) else a) for a in raw) if a] if isinstance(raw, list) else []
        source = item.get('source')
        if not _text(source, 20) or not source.strip() or not aliases or len(aliases) > 10 or not all(_text(a, 20) for a in aliases): return None
        identifier, target, third, you = (item.get(k) if item.get(k) is not None else '' for k in ('id', 'target', 'third', 'you'))
        if not _text(identifier, 20) or not _text(target, 40) or not _text(third, 20) or not _text(you, 20): return None
        if 'gender' not in item or item['gender'] not in ('male', 'female', None): return None
        if item.get('role') not in ROLES or item.get('rank') not in RANKS: return None
        auto = item.get('auto') is True
        characters.append({'id': (identifier or source).strip(), 'source': source.strip(), 'aliases': aliases, 'target': target.strip(),
                           'gender': item['gender'], 'role': item['role'], 'rank': item['rank'], 'third': third.strip(), 'you': you.strip(),
                           'auto': auto, 'sure': auto and item.get('sure') is True})
    return {'version': 1, 'characters': characters}
