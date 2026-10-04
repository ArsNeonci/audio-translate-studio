"""Narration styles for the TTS stage.

Each style bundles a recommended VieNeu preset and delivery settings measured
from reference narration (docs/VOICE_STYLES.md). ``default`` keeps the original
per-row behaviour byte for byte: no grouping, trimming, tempo or extra pauses.
"""
import re
import subprocess

STYLES = {
    'default': None,
    # "Mù Tịt Audio": nearest preset Ngọc Huyền (0.70), ~8% faster than Trúc Ly,
    # pauses median 0.17 s / p90 0.22 s.
    'drama': dict(voice='Ngọc Huyền', tempo=1.06, gap_ms=170, long_gap_ms=260, tags=True),
    # Survival reference: nearest preset Trúc Ly (0.50), long continuous phrases,
    # pauses median 0.16-0.24 s / p90 0.22-0.51 s.
    'survival': dict(voice='Trúc Ly', tempo=1.0, gap_ms=200, long_gap_ms=480, tags=True),
    # Rebirth reference (same narrator as survival, 0.90): calm, pauses median
    # 0.34-0.53 s / p90 ~1.1 s.
    'rebirth': dict(voice='Trúc Ly', tempo=1.0, gap_ms=420, long_gap_ms=1000, tags=True),
}
DEFAULT_STYLE = 'default'
MAX_UNIT_CHARS = 220
SCENE_BREAK_MS = 1500
SAMPLE_RATE = 48000

_SENTENCE_END = re.compile(r'[.!?…。！？]["”’)\]]*$')
_LONG_END = re.compile(r'(?:[!?…！？]|\.\.\.)["”’)\]]*$')
# Only standalone interjections become cues; ordinary words are never touched.
_LAUGH = re.compile(r'(?<![\w\[])(?:ha(?:[ -]?ha)+|hà(?:[ -]?hà)+|hô(?:[ -]?hô)+|he(?:[ -]?he)+|hi(?:[ -]?hi)+|hì(?:[ -]?hì)+|khà(?:[ -]?khà)+|khì(?:[ -]?khì)+)(?![\w\]])', re.I)
_SIGH = re.compile(r'(?<![\w\[])(?:hai+z+|ai+z+|hầy+|haizz+|ai da|hây da)(?![\w\]])', re.I)


def validate(style):
    style = style or DEFAULT_STYLE
    if style not in STYLES: raise ValueError('Voice style is unavailable')
    return style


def catalog():
    return [{'id': key, 'recommended_voice_id': (value or {}).get('voice')} for key, value in STYLES.items()]


def settings(style):
    """Parameters stored in the TTS adapter config; None keeps legacy fingerprints."""
    value = STYLES[validate(style)]
    if value is None: return None
    return {'id': validate(style), 'version': 1, **{k: v for k, v in value.items() if k != 'voice'}}


def add_cues(text):
    text, laughs = _LAUGH.subn('[cười]', text, count=1)
    if not laughs: text = _SIGH.sub('[thở dài]', text, count=1)
    return text


def units(rows, style):
    """Yield (index, rows, text, gap_after_ms). Without a style each row is a unit."""
    if not style:
        for index, row in rows:
            yield index, [row], row['text_vi_moderated'], None
        return
    group = []

    def emit(next_row=None):
        text = ' '.join(r['text_vi_moderated'].strip() for _, r in group if r['text_vi_moderated'].strip())
        if style.get('tags'): text = add_cues(text)
        last = group[-1][1]
        scene = next_row is not None and next_row['start_ms'] - last['end_ms'] >= SCENE_BREAK_MS
        gap = style['long_gap_ms'] if scene or _LONG_END.search(text) else style['gap_ms']
        return group[0][0], [r for _, r in group], text, gap if next_row is not None else 0

    for index, row in rows:
        text = row['text_vi_moderated'].strip()
        if group:
            current = sum(len(r['text_vi_moderated']) + 1 for _, r in group)
            previous = group[-1][1]
            if (_SENTENCE_END.search(previous['text_vi_moderated'].strip()) or current + len(text) > MAX_UNIT_CHARS
                    or row['start_ms'] - previous['end_ms'] >= SCENE_BREAK_MS):
                yield emit(row); group = []
        group.append((index, row))
    if group: yield emit()


def finish_audio(path, style):
    """Trim edge silence and change tempo (pitch preserved) in place."""
    if not style: return
    import numpy as np
    import soundfile as sf
    audio, rate = sf.read(str(path), dtype='float32')
    if rate != SAMPLE_RATE: raise RuntimeError('Unexpected TTS sample rate')
    audio = trim(audio)
    if style.get('tempo', 1.0) != 1.0 and len(audio) > SAMPLE_RATE // 10:
        result = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'f32le', '-ar', str(SAMPLE_RATE), '-ac', '1', '-i', '-',
                                 '-filter:a', f"atempo={style['tempo']:.4f}", '-f', 'f32le', '-ar', str(SAMPLE_RATE), '-ac', '1', '-'],
                                input=audio.tobytes(), capture_output=True, check=True)
        audio = np.frombuffer(result.stdout, dtype=np.float32)
    if not len(audio) or not np.isfinite(audio).all(): raise RuntimeError('Voice style produced invalid audio')
    sf.write(str(path), np.clip(audio, -1, 1), SAMPLE_RATE, format='WAV', subtype='PCM_16')


def trim(audio, threshold_db=-45, margin_ms=30):
    import numpy as np
    frame = SAMPLE_RATE // 100
    count = len(audio) // frame
    if not count: return audio
    rms = np.sqrt(np.mean(audio[:count * frame].reshape(count, frame) ** 2, axis=1))
    voiced = np.flatnonzero(20 * np.log10(rms + 1e-9) > threshold_db)
    if not len(voiced): return audio
    margin = SAMPLE_RATE * margin_ms // 1000
    return audio[max(0, voiced[0] * frame - margin):min(len(audio), (voiced[-1] + 1) * frame + margin)]
