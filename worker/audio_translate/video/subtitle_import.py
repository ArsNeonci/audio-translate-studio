"""A subtitle file the person brings (tool 8): SRT or WebVTT, in any of the encodings such files come in, made into one clean UTF-8 SRT.

The drawing of the text is libass (ffmpeg `subtitles`), which reads UTF-8 only and stops at a broken cue, so the file is read here, checked, and written
again as `working/render.srt`. The person's own file is never changed. Errors are short English sentences (the UI translates each one).
"""
import codecs
from pathlib import Path
import re
import unicodedata

MAX_BYTES = 5 * 1024 ** 2
MAX_CUES = 50000
EXTENSIONS = {'.srt', '.vtt'}
TIME = re.compile(r'(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[,.](\d{1,3})')
ARROW = re.compile(r'^\s*(\S+)\s*-->\s*(\S+)')
TAG = re.compile(r'<[^>]+>|\{\\[^}]*\}')    # WebVTT <c>, <i>... and ASS-style {\an8} overrides


class SubtitleFileError(ValueError):
    """The text of the problem is the message (an English sentence listed in uiText)."""


def decode(raw):
    """(text, encoding name): a byte-order mark decides; else UTF-8; else Vietnamese Windows text (cp1258), else Western (cp1252)."""
    text, name = _decode(raw)
    # cp1258 spells a Vietnamese letter as a base letter plus a combining accent; one composed letter is what the renderer and the fonts want.
    return unicodedata.normalize('NFC', text), name


def _decode(raw):
    for mark, name in ((codecs.BOM_UTF8, 'utf-8-sig'), (codecs.BOM_UTF16_LE, 'utf-16'), (codecs.BOM_UTF16_BE, 'utf-16')):
        if raw.startswith(mark): return raw.decode(name), name
    try: return raw.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError: pass
    # UTF-16 without a mark: every other byte is zero for Latin text
    if len(raw) > 4 and raw[1::2].count(0) > len(raw) // 4:
        try: return raw.decode('utf-16-le'), 'utf-16'
        except UnicodeDecodeError: pass
    for name in ('cp1258', 'cp1252'):
        try: return raw.decode(name), name
        except UnicodeDecodeError: continue
    raise SubtitleFileError('The subtitle file cannot be read')


def to_ms(text):
    found = TIME.fullmatch(text.strip())
    if not found: return None
    hours, minutes, seconds, fraction = found.groups()
    return ((int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(fraction.ljust(3, '0'))


def parse(text):
    """([(start_ms, end_ms, text)], dropped): cues sorted by time; a cue with no text, a bad time or no length is dropped (and counted)."""
    text = text.replace('\r\n', '\n').replace('\r', '\n').lstrip('﻿')
    cues, dropped = [], 0
    for block in re.split(r'\n{2,}', text.strip()):
        lines = [line for line in block.split('\n')]
        at = next((i for i, line in enumerate(lines) if '-->' in line), None)
        if at is None:
            if block.strip() and not block.lstrip().upper().startswith(('WEBVTT', 'NOTE', 'STYLE', 'REGION', 'KIND', 'LANGUAGE')) and not block.strip().isdigit(): dropped += 1
            continue
        found = ARROW.match(lines[at])
        start, end = (to_ms(found.group(1)), to_ms(found.group(2))) if found else (None, None)
        body = '\n'.join(line.strip() for line in lines[at + 1:] if line.strip())
        body = TAG.sub('', body).strip()
        if start is None or end is None or end <= start or not body: dropped += 1; continue
        cues.append((start, end, body))
    cues.sort(key=lambda cue: (cue[0], cue[1]))
    return cues, dropped


def srt(cues):
    def clock(ms): return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'
    return ''.join(f'{i}\n{clock(a)} --> {clock(b)}\n{body}\n\n' for i, (a, b, body) in enumerate(cues, 1))


def prepare(source, name, target, video_ms=None):
    """Check the person's file and write the clean SRT to `target`. Returns the report the page shows."""
    source = Path(source)
    if Path(name or '').suffix.lower() not in EXTENSIONS: raise SubtitleFileError('Use an SRT or VTT subtitle file')
    if not source.is_file() or not source.stat().st_size: raise SubtitleFileError('Empty upload')
    if source.stat().st_size > MAX_BYTES: raise SubtitleFileError('The subtitle file is larger than 5 MB')
    text, encoding = decode(source.read_bytes())
    cues, dropped = parse(text)
    if not cues: raise SubtitleFileError('The subtitle file has no usable subtitles')
    if len(cues) > MAX_CUES: raise SubtitleFileError('The subtitle file has too many subtitles')
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + '.tmp')
    temp.write_text(srt(cues), encoding='utf-8', newline='\n')
    temp.replace(target)
    last = max(end for _, end, _ in cues)
    return {'cues': len(cues), 'dropped': dropped, 'encoding': encoding, 'last_end_ms': last, 'first_start_ms': cues[0][0],
            'beyond_video': bool(video_ms and cues[0][0] >= video_ms), 'longer_than_video': bool(video_ms and last > video_ms + 1000)}
