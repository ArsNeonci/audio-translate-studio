"""Vietnamese subtitles (.srt) for the voice this app made, timed from the voice itself.

The voice is the units of `voice/voice.manifest.jsonl` joined in order, each followed by its pause (`gap_after_ms`), exactly as
`postprocess.concatenate` joins them. So the start of every unit is the sum of the lengths before it: the cut between two units is
exact to the sample. A unit that holds a long paragraph is cut into cues at sentence ends, then clauses, then words; the time of
a unit is shared between its cues in proportion to their characters (an estimate inside a unit, exact at its ends).

The text is the moderated Vietnamese that was read aloud, never the Chinese source.
Format: SubRip (.srt), UTF-8, as YouTube accepts it (number, `00:00:00,599 --> 00:00:04,160`, text, blank line).
"""
import json
from pathlib import Path
import re
import unicodedata

SAMPLE_RATE = 48000
DEFAULTS = {'max_chars': 84, 'min_seconds': 1.0}
LIMITS = {'max_chars': (20, 200), 'min_seconds': (0.5, 5.0)}
OUTPUT = 'voice.vi.srt'
TOLERANCE_MS = 1000   # the manifest and the joined voice agree to the sample; this only catches a manifest of another voice
_BREAKS = re.compile(r'(?<=[.!?…])\s+')
_CLAUSES = re.compile(r'(?<=[,;:])\s+')


def validate(value):
    """The subtitle settings of a run: the two numbers, inside their limits (None gives the defaults)."""
    if value is None: return dict(DEFAULTS)
    if not isinstance(value, dict): raise ValueError('Invalid subtitle settings')
    out = {}
    for key, (low, high) in LIMITS.items():
        number = value.get(key, DEFAULTS[key])
        if isinstance(number, bool) or not isinstance(number, (int, float)) or number != number or not low <= number <= high:
            raise ValueError(f'{key} must be {low:g} to {high:g}')
        out[key] = int(number) if key == 'max_chars' else float(number)
    return out


def _clean(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', str(text or ''))).strip()


def _words(text, limit):
    """Cuts `text` at spaces into pieces of at most `limit` characters (a word longer than that is cut hard)."""
    pieces, current = [], ''
    for word in text.split(' '):
        while len(word) > limit:
            if current: pieces.append(current); current = ''
            pieces.append(word[:limit]); word = word[limit:]
        if current and len(current) + 1 + len(word) > limit: pieces.append(current); current = word
        else: current = f'{current} {word}'.strip()
    if current: pieces.append(current)
    return pieces


def split_text(text, limit):
    """The text as pieces of at most `limit` characters, cut at sentence ends first, then clauses, then words.
    Neighbouring small pieces are joined back as long as they fit."""
    text = _clean(text)
    if not text: return []
    if len(text) <= limit: return [text]
    atoms = []
    for sentence in _BREAKS.split(text):
        if len(sentence) <= limit: atoms.append(sentence); continue
        for clause in _CLAUSES.split(sentence):
            atoms.extend([clause] if len(clause) <= limit else _words(clause, limit))
    pieces, current = [], ''
    for atom in atoms:
        if current and len(current) + 1 + len(atom) > limit: pieces.append(current); current = atom
        else: current = f'{current} {atom}'.strip()
    if current: pieces.append(current)
    return pieces


def two_lines(text):
    """One line, or two lines broken at the space nearest the middle (a cue never has more than two)."""
    if len(text) <= 42: return text
    middle, best = len(text) / 2, None
    for position, char in enumerate(text):
        if char == ' ' and (best is None or abs(position - middle) < abs(best - middle)): best = position
    return text if best is None else text[:best] + '\n' + text[best + 1:]


def build(units, settings=None, total_ms=None):
    """Cues [(start_ms, end_ms, text)] for units [(text, length_ms, gap_ms)] laid one after another.

    `total_ms` is the length of the whole voice; when a unit has no length of its own (None) the time left is shared between those
    units in proportion to their characters."""
    settings = validate(settings)
    limit, least = settings['max_chars'], int(settings['min_seconds'] * 1000)
    units = [(_clean(text), length, gap or 0) for text, length, gap in units]
    unknown = [i for i, (_, length, _) in enumerate(units) if length is None]
    if unknown:
        if not total_ms: raise ValueError('The length of the voice is unknown')
        known = sum(length for _, length, _ in units if length is not None) + sum(gap for _, _, gap in units)
        weight = sum(max(1, len(units[i][0])) for i in unknown)
        share = max(0, total_ms - known)
        units = [(t, round(share * max(1, len(t)) / weight) if length is None else length, g) for t, length, g in units]
    cues, position = [], 0
    for text, length, gap in units:
        start, end = position, position + length
        position = end + gap
        pieces = split_text(text, limit)
        if not pieces: continue
        weight = sum(len(p) for p in pieces)
        edge, last = start, len(pieces) - 1
        for i, piece in enumerate(pieces):
            stop = end if i == last else edge + round(length * len(piece) / weight)
            cues.append([edge, stop, piece]); edge = stop
    # A cue shorter than the least time stays up until then, but never into the next cue.
    for i, cue in enumerate(cues):
        following = cues[i + 1][0] if i + 1 < len(cues) else None
        wanted = cue[0] + least
        if cue[1] < wanted: cue[1] = wanted if following is None else max(cue[1], min(wanted, following))
    if total_ms:   # nothing may outlast the voice (the last cue's least time can reach past its end)
        for cue in cues: cue[1] = min(cue[1], total_ms)
    return [(a, b, two_lines(t)) for a, b, t in cues if b > a]


def timestamp(ms):
    hours, rest = divmod(int(ms), 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    return f'{hours:02d}:{minutes:02d}:{rest // 1000:02d},{rest % 1000:03d}'


def to_srt(cues):
    return ''.join(f'{n}\n{timestamp(a)} --> {timestamp(b)}\n{text}\n\n' for n, (a, b, text) in enumerate(cues, 1))


def read_units(manifest, wav_dir=None):
    """Units [(text, length_ms, gap_ms)] of a voice manifest. The length is the frames the manifest recorded (3.1.0 on), else the
    segment WAV itself in `wav_dir`, else None (the caller shares the voice length between such units)."""
    units = []
    for line in Path(manifest).read_text(encoding='utf-8').splitlines():
        if not line.strip(): continue
        row = json.loads(line)
        frames = row.get('frames')
        if not isinstance(frames, int):
            try:
                import soundfile as sf
                frames = sf.info(str(Path(wav_dir) / row['file'])).frames
            except (OSError, RuntimeError, KeyError, TypeError):
                frames = None
        units.append((row.get('text') or '', None if frames is None else round(frames * 1000 / SAMPLE_RATE), int(row.get('gap_after_ms') or 0)))
    if not units: raise ValueError('The voice manifest is empty')
    return units


def make(manifest, wav_dir=None, settings=None, total_ms=None):
    """The .srt text for a voice manifest (and its segment WAVs, when they are still there)."""
    units = read_units(manifest, wav_dir)
    known = [length for _, length, _ in units]
    if total_ms and None not in known and abs(sum(known) + sum(gap for _, _, gap in units) - total_ms) > TOLERANCE_MS:
        raise ValueError('The voice manifest does not match the voice file')
    cues = build(units, settings, total_ms)
    if not cues: raise ValueError('The voice has no text to show')
    return to_srt(cues)


def write(target, manifest, wav_dir=None, settings=None, total_ms=None):
    """Writes the .srt atomically and returns the number of cues."""
    text = make(manifest, wav_dir, settings, total_ms)
    target = Path(target)
    temp = target.with_name(target.name + '.tmp')
    temp.write_text(text, encoding='utf-8', newline='\n')
    temp.replace(target)
    return text.count('\n\n')


def voice_length_ms(wav):
    import soundfile as sf
    info = sf.info(str(wav))
    return round(info.frames * 1000 / info.samplerate)


class VoiceMissing(ValueError):
    """The voice (or its manifest) to put subtitles on is not there; shown as VOICE_MISSING."""
    code = 'VOICE_MISSING'


def voice_inputs(job_dir, job):
    """(manifest, wav_dir, total_ms) of the voice a run puts subtitles on: its own, or the voice of the run it points at
    (tool 6 `subtitle_voice`, tool 5 `video_voice`). A finished run's folders may be gone; its published manifest is then used."""
    from audio_translate.core.storage import read_json
    from audio_translate.workflow import results
    reference = job.get('subtitle_voice') or job.get('video_voice')
    folder = Path(job_dir) if not reference else results.workspace(reference['job_id'])
    manifest, wav = folder / 'voice' / 'voice.manifest.jsonl', folder / 'voice.vi.wav'
    if manifest.is_file() and wav.is_file(): return manifest, folder / 'voice', voice_length_ms(wav)
    if not reference: raise VoiceMissing()
    try:
        directory = results.destination(reference['job_id'])
        files = {f['type']: f for f in read_json(directory / 'outputs.json')['files'] if f.get('status') == 'AVAILABLE'}
    except (OSError, ValueError, KeyError):
        raise VoiceMissing() from None
    if 'VOICE_MANIFEST' not in files or 'VOICE_WAV' not in files: raise VoiceMissing()
    return directory / files['VOICE_MANIFEST']['path'], None, voice_length_ms(directory / files['VOICE_WAV']['path'])


def run(job_dir):
    """The SUBTITLE stage: voice.vi.srt in the run's workspace, from the run's settings."""
    from audio_translate.core.storage import progress, read_json
    job_dir = Path(job_dir)
    job = read_json(job_dir / 'job.json')
    progress(job_dir, 'subtitle', 'SUBTITLE_BUILDING', 0, 1)
    manifest, wav_dir, total = voice_inputs(job_dir, job)
    write(job_dir / OUTPUT, manifest, wav_dir, validate(job.get('subtitle')), total)
    progress(job_dir, 'subtitle', 'SUBTITLE_BUILDING', 1, 1)
