"""Manual translation: Chinese text out as numbered paragraphs, the person's own Vietnamese text back in (docs/MANUAL_TRANSLATION.md).

One paragraph is the unit both ways. The paragraphs follow the same rule as transcript.zh.md (a pause over 1.5 s, 60 s or 240 characters ends
one), each gets a fixed number, and the number travels with the text through the person's chatbot as `[12] ...`. When the Vietnamese comes back,
the number says which paragraph it belongs to, so the original timestamps are kept (the voice styles use them for scene breaks).
"""
import json
from pathlib import Path
import re

from audio_translate.core.storage import atomic_json, read_json

PAUSE_MS, SPAN_MS, PARAGRAPH_CHARS = 1500, 60000, 240     # the paragraph rule of transcription/pipeline.py merge()
SPLIT_LIMITS = (500, 20000)                              # characters per part, as the person can set it
SPLIT_DEFAULT = 3000
MAX_PARTS = 500
MAX_PROMPT = 2000
MARKER = re.compile(r'^\s*(?:\[(\d{1,6})\]|【(\d{1,6})】)\s*(.*)$')
HAN = re.compile(r'[㐀-鿿]')
SENTENCE_END = re.compile(r'(?<=[.!?…])\s+(?=\S)')
# Lines a chatbot puts before or after the translation itself.
CHATTER = re.compile(r'^\s*(?:<!--.*-->|(?:đây là|dưới đây là|bản dịch|here is|here\'s|sure|certainly|translation)\b.*[:：]\s*|---+|\*\*\*+)\s*$', re.I)


# Put at the top of each part when the person leaves the box ticked (the UI shows its own, translated copy of this sentence to edit).
DEFAULT_PROMPT = ('Hãy dịch các đoạn tiếng Trung dưới đây sang tiếng Việt tự nhiên, đúng văn phong truyện. '
                  'Giữ nguyên mã số [n] ở đầu mỗi đoạn, mỗi đoạn dịch xuống một dòng riêng, không thêm lời dẫn hay giải thích.')


class ManualTextError(ValueError):
    """A problem with the text, as a short English sentence the UI translates (uiText has each one)."""


def validate_split(value):
    """Tool 7's settings: characters per part, and the instruction put at the top of every part."""
    value = {} if value is None else value
    if not isinstance(value, dict): raise ManualTextError('Invalid part size')
    size = value.get('max_chars', SPLIT_DEFAULT)
    if not isinstance(size, int) or isinstance(size, bool) or not SPLIT_LIMITS[0] <= size <= SPLIT_LIMITS[1]: raise ManualTextError('Invalid part size')
    prompt = value.get('prompt', True)
    prompt_text = value.get('prompt_text', '')
    if not isinstance(prompt, bool) or not isinstance(prompt_text, str) or len(prompt_text) > MAX_PROMPT or '\x00' in prompt_text: raise ManualTextError('Invalid part size')
    return {'max_chars': size, 'prompt': prompt, 'prompt_text': prompt_text.strip() or DEFAULT_PROMPT}


def paragraphs(rows):
    """[{n, start_ms, end_ms, text}] from the Chinese rows. Rows without real time (start == end: a plain text file) are already paragraphs."""
    result, group, last_end = [], None, -1
    for row in rows:
        text, start, end = row['text'], row['start_ms'], row['end_ms']
        if not text.strip(): continue
        flat = start == end
        if group and (flat or start - last_end > PAUSE_MS or start - group['start_ms'] > SPAN_MS or len(group['text']) > PARAGRAPH_CHARS):
            result.append(group); group = None
        if group is None: group = {'n': len(result) + 1, 'start_ms': start, 'end_ms': end, 'text': ''}
        group['text'] += text.strip() if flat else text
        group['end_ms'] = max(group['end_ms'], end)
        last_end = max(last_end, end)
    if group: result.append(group)
    return result


def read_rows(path, key='text'):
    rows = []
    with Path(path).open(encoding='utf-8-sig') as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip(): continue
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get(key), str) or type(row.get('start_ms')) is not int or type(row.get('end_ms')) is not int:
                raise ManualTextError('The text file is not valid')
            rows.append(row)
    return rows


def numbered(paras):
    return ''.join(f"[{p['n']}] {p['text']}\n\n" for p in paras)


def split_plan(paras, max_chars):
    """Paragraph groups of at most max_chars characters; a paragraph is never cut (one longer than the limit gets a part of its own)."""
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or not SPLIT_LIMITS[0] <= max_chars <= SPLIT_LIMITS[1]:
        raise ManualTextError('Invalid part size')
    parts, group, size = [], [], 0
    for para in paras:
        cost = len(para['text']) + len(str(para['n'])) + 4
        if group and size + cost > max_chars:
            parts.append(group); group, size = [], 0
        group.append(para); size += cost
    if group: parts.append(group)
    if len(parts) > MAX_PARTS: raise ManualTextError('Too many parts; raise the part size')
    return parts


def render_part(group, index, total, prompt):
    head = f'{prompt.strip()}\n\n---\n\n' if prompt and prompt.strip() else ''
    return f"{head}<!-- {index}/{total} · [{group[0]['n']}]–[{group[-1]['n']}] -->\n\n{numbered(group)}"


def split_files(rows, max_chars, prompt):
    """[(name, text)] for the parts, in order; names are part-001.md and so on."""
    paras = paragraphs(rows)
    if not paras: raise ManualTextError('Input contains no valid text')
    parts = split_plan(paras, max_chars)
    width = max(3, len(str(len(parts))))
    return [(f'part-{i:0{width}d}.md', render_part(group, i, len(parts), prompt)) for i, group in enumerate(parts, 1)], paras


def run_split(job_dir):
    """The SPLIT stage of tool 7: the numbered parts, a zip of them and the part count in job.json."""
    import zipfile
    from audio_translate.core.control import check_cancel
    from audio_translate.core.storage import progress, update_job
    job_dir = Path(job_dir)
    job = read_json(job_dir / 'job.json')
    settings = job.get('split') or {}
    rows = read_rows(job_dir / 'transcript.zh.jsonl')
    files, paras = split_files(rows, settings.get('max_chars', SPLIT_DEFAULT), settings.get('prompt_text') if settings.get('prompt') else '')
    target = job_dir / 'split'
    if target.exists():
        for old in target.iterdir(): old.unlink()
    target.mkdir(exist_ok=True)
    progress(job_dir, 'split', 'SPLITTING', 0, len(files))
    for index, (name, text) in enumerate(files, 1):
        check_cancel(job_dir)
        (target / name).write_text(text, encoding='utf-8', newline='\n')
        progress(job_dir, 'split', 'SPLITTING', index, len(files))
    archive = target / 'parts.zip.tmp'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name, _ in files: bundle.write(target / name, name)
    archive.replace(target / 'parts.zip')
    update_job(job_dir, split={**settings, 'parts': len(files), 'paragraphs': len(paras)})


def _sentences(text):
    parts = [piece.strip() for piece in SENTENCE_END.split(text.strip()) if piece.strip()]
    return parts or [text.strip()]


def _spread(texts, start, end):
    """(start_ms, end_ms) per text: the span shared by the number of characters, in whole milliseconds, never backwards."""
    weights = [max(1, len(t)) for t in texts]
    total, span, spent, cursor, out = sum(weights), max(0, end - start), 0, start, []
    for weight in weights:
        spent += weight
        edge = start + round(span * spent / total)
        out.append((cursor, max(cursor, edge))); cursor = max(cursor, edge)
    return out


def _clean(lines):
    """The chatbot's own words around the translation are dropped (and counted)."""
    kept, dropped = [], 0
    for line in lines:
        if CHATTER.match(line) and not MARKER.match(line): dropped += 1
        else: kept.append(line)
    return kept, dropped


def _blocks(lines):
    blocks, current = [], []
    for line in lines:
        if line.strip(): current.append(line.strip())
        elif current: blocks.append(' '.join(current)); current = []
    if current: blocks.append(' '.join(current))
    return blocks


def parse_translation(text, paras=None, span_ms=None):
    """The person's Vietnamese text as (texts_by_paragraph, report).

    texts_by_paragraph: [(start_ms, end_ms, vietnamese_text)] in paragraph order, ready to become rows.
    With the Chinese paragraphs known (`paras`) and numbers `[n]` in the text, each text lands on its own paragraph and keeps its timestamps.
    Without numbers it is matched by position when the counts agree; otherwise the time is shared by length across `span_ms` (or the Chinese span).
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n').lstrip('﻿')
    if '\x00' in text: raise ManualTextError('Text segment exceeds 64 KiB or contains binary data')
    lines, dropped = _clean(text.split('\n'))
    report = {'mode': 'plain', 'expected': len(paras) if paras else None, 'found': 0, 'dropped_lines': dropped, 'missing': [], 'duplicate': [], 'unknown': [],
              'han_paragraphs': 0, 'empty': [], 'estimated_time': False, 'out_of_order': False, 'preview': []}
    if any(MARKER.match(line) for line in lines):
        found, order, current = {}, [], None
        for line in lines:
            match = MARKER.match(line)
            if match:
                current = int(match.group(1) or match.group(2))
                if current in found: report['duplicate'].append(current)
                found.setdefault(current, []).append(match.group(3).strip())
                order.append(current)
            elif current is not None and line.strip(): found[current].append(line.strip())
        # A repeated number keeps its first text; the report lists it so the person can look.
        joined = {n: ' '.join(p for p in parts if p).strip() for n, parts in found.items()}
        if not paras:
            raise ManualTextError('Numbers [n] need the Chinese text of this workflow')
        known = {p['n'] for p in paras}
        report.update(mode='numbered', found=len(joined), unknown=sorted(n for n in joined if n not in known), missing=sorted(known - set(joined)),
                      empty=sorted(n for n, t in joined.items() if not t and n in known), out_of_order=order != sorted(order))
        pairs = [(p['start_ms'], p['end_ms'], joined.get(p['n'], '')) for p in paras]
        report['han_paragraphs'] = sum(bool(HAN.search(t)) for _, _, t in pairs)
        _preview(report, paras, [t for _, _, t in pairs])
        return pairs, report
    blocks = _blocks(lines)
    single = [line.strip() for line in lines if line.strip()]
    report['found'] = len(blocks)
    if paras and len(blocks) == len(paras): chosen = blocks
    elif paras and len(single) == len(paras): chosen, report['found'] = single, len(single)
    else: chosen = blocks
    if paras and len(chosen) == len(paras):
        pairs = [(p['start_ms'], p['end_ms'], t) for p, t in zip(paras, chosen)]
    else:
        if not chosen: raise ManualTextError('Input contains no valid text')
        report['estimated_time'] = True
        begin = paras[0]['start_ms'] if paras else 0
        finish = paras[-1]['end_ms'] if paras else (span_ms or 60 * sum(len(t) for t in chosen))   # about 60 ms of speech per character
        pairs = [(a, b, t) for (a, b), t in zip(_spread(chosen, begin, finish), chosen)]
    report['han_paragraphs'] = sum(bool(HAN.search(t)) for _, _, t in pairs)
    _preview(report, paras, [t for _, _, t in pairs])
    return pairs, report


def _preview(report, paras, texts):
    for index, text in enumerate(texts[:3]):
        report['preview'].append({'n': index + 1, 'zh': paras[index]['text'][:160] if paras and index < len(paras) else '', 'vi': text[:200]})


def blocking(report):
    """The reasons the text cannot be used yet (a short English sentence each), empty when it can."""
    reasons = []
    if report['mode'] == 'numbered':
        if report['missing']: reasons.append('Some paragraphs have no translation')
        if report['unknown']: reasons.append('Some numbers do not belong to this workflow')
        if report['empty']: reasons.append('Some paragraphs are empty')
    return reasons


def rows_from_pairs(pairs, key='text_vi'):
    """Rows for transcript.vi.jsonl (or the moderated file): a long paragraph is cut at sentence ends, the paragraph's time shared by length."""
    rows = []
    for start, end, text in pairs:
        text = text.strip()
        if not text: continue
        pieces = _sentences(text)
        for (a, b), piece in zip(_spread(pieces, start, end), pieces):
            rows.append({'start_ms': a, 'end_ms': b, key: piece})
    if not rows: raise ManualTextError('Input contains no valid text')
    return rows


def write_rows(directory, name, md_name, rows, key):
    """The JSONL and the readable Markdown of rows (one paragraph per row, like the model's own output)."""
    directory = Path(directory)
    with (directory / name).open('w', encoding='utf-8', newline='\n') as out:
        for row in rows: out.write(json.dumps(row, ensure_ascii=False) + '\n')
    with (directory / md_name).open('w', encoding='utf-8', newline='\n') as out:
        for row in rows: out.write(row[key] + '\n\n')


def write_report(directory, report):
    atomic_json(Path(directory) / 'report.json', report)
