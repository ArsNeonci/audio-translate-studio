"""Chinese transcript cleanup before translation (docs/ADDRESS_FORMS.md, "Làm sạch bản tiếng Trung").

`boilerplate` regexes match channel intros that the narrator reads aloud ("好看小说千千万，
悠悠这里占一半…"). They are matched on the joined text of the first rows, because ASR
splits them unpredictably ("袖手旁观好看。|小说千千万"), and only the matched characters
are removed from each row. `asr_corrections` are literal fixes of mishearings observed in
real transcripts (煤运 -> 霉运). The stored `text_zh` always stays as transcribed.
"""
import json
import os
import re

from audio_translate.core.storage import ROOT, digest

PUNCT = re.compile(r'^[\s，,。．.！!？?、；;：:…“”"\'‘’（）()]*$')


def config():
    override = os.getenv('SOURCE_CLEANUP_CONFIG')
    if override:
        with open(override, encoding='utf-8-sig') as handle:
            data = json.load(handle)
    else:
        # Asset 4 (language data): encrypted vault with a plaintext dev fallback.
        from audio_translate.core import vault
        data = vault.load_json('source-cleanup', ROOT/'worker'/'config'/'source-cleanup.json')
    if data.get('version') != 1 or not isinstance(data.get('boilerplate'), list) or not isinstance(data.get('asr_corrections'), list):
        raise ValueError('Invalid source cleanup config')
    for item in data['asr_corrections']:
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k] for k in ('source', 'target')):
            raise ValueError('Invalid ASR correction')
    data['patterns'] = [re.compile(p, re.I) for p in data['boilerplate']]
    return data


def clean(texts, data=None):
    """{index: cleaned text} for rows that change; '' means the row is dropped from translation."""
    data = data or config()
    indexes = [index for index, _ in texts]
    values = {index: text for index, text in texts}
    for item in data['asr_corrections']:
        for index in indexes:
            values[index] = values[index].replace(item['source'], item['target'])
    head = indexes[:int(data.get('boilerplate_rows', 80))]
    starts, joined = [], ''
    for index in head:
        starts.append(len(joined)); joined += values[index]
    removed = set()
    for pattern in data['patterns']:
        for match in pattern.finditer(joined):
            removed.update(range(*match.span()))
    for position, index in enumerate(head):
        start = starts[position]
        text = values[index]
        kept = ''.join(ch for offset, ch in enumerate(text) if start + offset not in removed)
        if kept != text:
            kept = '' if PUNCT.match(kept) else kept.lstrip('，,。 ')
            # Keep the sentence end the intro swallowed ("袖手旁观好看。" -> "袖手旁观。").
            if kept and text[-1:] in '。！？!?…，,' and kept[-1:] not in '。！？!?…，,': kept += text[-1]
            values[index] = kept
    return {index: values[index] for index, original in texts if values[index] != original}


def signature():
    data = config()
    return digest([data['boilerplate'], data['asr_corrections'], data.get('boilerplate_rows', 80)])
