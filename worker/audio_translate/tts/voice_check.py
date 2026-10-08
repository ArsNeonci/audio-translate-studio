"""Last check before the (paid) voice step: no Chinese, Japanese or Korean text may reach the voice.

The translation can leave such characters behind: a Genius row that kept failing its repair rounds is flagged and keeps its best draft, a
local translation may leave a name untranslated, and a replacement rule can bring one back. The voice would mispronounce them or fail on
them, and the owner pays for that audio. So right before the voice step this looks at every row of the moderated text, takes those
characters out, and leaves a small report (working/voice-check.json). Rows without such characters are never touched, and a second run
changes nothing.
"""
import json
import os
from pathlib import Path
import re

# Han (basic, extension A, compatibility), Hiragana/Katakana and Hangul: the same set the Genius check rejects.
FOREIGN = re.compile(r'[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]')
FIELD = 'text_vi_moderated'


def strip_foreign(text):
    """The text without those characters; '…' (a pause) when nothing readable is left."""
    text = FOREIGN.sub('', text)
    text = re.sub(r'[(（\[]\s*[)）\]]', '', text)           # "Lý Minh (李明)" must not leave "()" behind
    text = re.sub(r'\s+([,.;:!?…])', r'\1', re.sub(r'\s+', ' ', text))   # nor a space in front of the punctuation
    return text.strip() or '…'


def clean_foreign(job_dir):
    """Rewrites transcript.vi.moderated.jsonl only when a row needs it. Returns the report (also saved to working/voice-check.json)."""
    job_dir = Path(job_dir)
    source = job_dir / 'transcript.vi.moderated.jsonl'
    report = {'rows_checked': 0, 'rows_changed': 0, 'characters_removed': 0, 'rows': []}
    if not source.is_file(): return report
    lines, changed = [], False
    for number, line in enumerate(source.read_text(encoding='utf-8').splitlines()):
        if not line.strip(): lines.append(line); continue
        row = json.loads(line)
        report['rows_checked'] += 1
        text = row.get(FIELD)
        if isinstance(text, str) and FOREIGN.search(text):
            report['rows_changed'] += 1; report['characters_removed'] += len(FOREIGN.findall(text)); report['rows'].append(number)
            row[FIELD] = strip_foreign(text); changed = True
            line = json.dumps(row, ensure_ascii=False)
        lines.append(line)
    if changed:
        temp = source.with_suffix('.jsonl.tmp')
        temp.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
        os.replace(temp, source)
        working = job_dir / 'working'; working.mkdir(exist_ok=True)
        (working / 'voice-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
