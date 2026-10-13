"""Genre terminology (docs/ADDRESS_FORMS.md, "Từ điển thuật ngữ").

Hy-MT2 follows its official terminology template reliably, so recurring mistranslations
(心虚 -> "vô sỉ", 大胆的想法 -> "ý định dũng cảm") are pinned here. Entries are Chinese
phrases, deliberately specific (大胆的小偷, not 大胆), because matching is by substring
and context-free. `common` applies to every styled job; `profiles` adds per genre.
"""
import json
import os

from audio_translate.core.storage import ROOT, digest

LIMIT = 40


def config():
    override = os.getenv('GENRE_LEXICON_CONFIG')
    if override:
        with open(override, encoding='utf-8-sig') as handle:
            return json.load(handle)
    # Asset 4 (language data): load from the encrypted vault, falling back to the plaintext
    # source in development (no vault file present).
    from audio_translate.core import vault
    return vault.load_json('genre-lexicon', ROOT/'worker'/'config'/'genre-lexicon.json')


def entries(profile):
    """[{source, target}] for the job's profile; invalid entries are a configuration error."""
    data = config()
    if data.get('version') != 1 or not isinstance(data.get('common'), list) or not isinstance(data.get('profiles'), dict):
        raise ValueError('Invalid genre lexicon')
    chosen = {}
    for item in [*data['common'], *data['profiles'].get(profile or 'neutral', [])]:
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip() or len(item[k]) > LIMIT for k in ('source', 'target')):
            raise ValueError('Invalid genre lexicon entry')
        chosen[item['source']] = item['target']
    return [{'source': source, 'target': target} for source, target in chosen.items()]


def signature(profile):
    return digest(entries(profile))
