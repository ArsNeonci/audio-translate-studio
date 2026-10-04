"""Offline Hy-MT2 GGUF translation and the unchanged VieNeu API."""
import os
from pathlib import Path
import sys

from audio_translate.core.storage import DATA, ROOT, atomic_json, read_json
from audio_translate.core.providers import vieneu_source
from audio_translate.translation.hymt_translation import TranslationAdapter, default_settings


def adapter_settings(job_dir):
    path = Path(job_dir) / "working" / "adapters.json"
    job = read_json(Path(job_dir)/'job.json')
    from audio_translate.core.compute_settings import apply_adapters, freeze
    device = freeze(job_dir)
    if path.exists():
        settings = read_json(path)
        if settings['translation'].get('backend') != 'hy-mt2-gguf':
            # Upgrade at the stage boundary; changed fingerprints invalidate old translations.
            glossary = settings['translation'].get('glossary', [])
            settings['translation'] = default_settings()
            settings['translation']['glossary'] = glossary
            atomic_json(path, settings)
        if job.get('selected_voice_id'): settings['tts']['voice'] = job['selected_voice_id']
        apply_style(settings, job)
        apply_adapters(settings, device)
        atomic_json(path, settings)
        return settings
    settings = {
        "translation": default_settings(),
        "tts": {"source": str(vieneu_source()),
            "device": os.getenv("VIENEU_DEVICE", "cpu"), "voice": job.get("selected_voice_id") or os.getenv("VIENEU_VOICE", "Hải Đăng"),
            "precision": os.getenv("VIENEU_PRECISION", "fp32"), "sample_rate": 48000, "version": 1},
    }
    apply_style(settings, job)
    apply_adapters(settings, device)
    atomic_json(path, settings)
    return settings


def apply_style(settings, job):
    # Default jobs keep the legacy config (and therefore checkpoint/cache keys).
    from audio_translate.tts.voice_styles import settings as style_settings
    style = style_settings(job.get('selected_voice_style'))
    if style: settings['tts']['style'] = style
    else: settings['tts'].pop('style', None)


class TTSAdapter:
    sample_rate = 48000

    def __init__(self, settings, threads=None):
        self.settings = settings
        self.engine = None
        self.threads = threads or max(1, int(os.getenv('AI_NUM_THREADS', '4')))

    def load(self):
        if self.engine is not None:
            return
        source = vieneu_source(self.settings["source"]) / "src"
        if not (source / "vieneu" / "factory.py").is_file():
            raise RuntimeError("Không tìm thấy VieNeu-TTS source. Đặt VIENEU_SOURCE tới repo nguyên bản.")
        # No editable install, monkeypatch, or bytecode files inside the repo.
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(source))
        os.environ.setdefault("HF_HOME", str(DATA / "hf-cache"))
        from vieneu import Vieneu
        self.engine = Vieneu(mode="v3turbo", device=self.settings["device"], precision=self.settings["precision"],
                             threads=self.threads, max_batch_size=1)
        if self.engine.sample_rate != self.sample_rate:
            raise RuntimeError("Unexpected VieNeu sample rate")
        # Validate the requested preset instead of silently changing voices.
        self.engine.get_preset_voice(self.settings["voice"])

    from audio_translate.core.control import complete_task
    @complete_task
    def synthesize(self, text, output):
        import numpy as np
        import soundfile as sf
        frames = 0
        with sf.SoundFile(str(output), "w", samplerate=self.sample_rate, channels=1, subtype="PCM_16", format="WAV") as handle:
            if not text.strip():
                handle.write(np.zeros(1, dtype=np.float32))
                return
            self.load()
            for chunk in self.engine.infer_stream(text, voice=self.settings["voice"], max_chars=256,
                    max_new_frames=1000, apply_watermark=False):
                from audio_translate.core.control import check_cancel
                check_cancel()
                chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
                if not np.isfinite(chunk).all():
                    raise RuntimeError("VieNeu returned invalid audio samples")
                handle.write(chunk)
                frames += len(chunk)
        if not frames:
            raise RuntimeError("VieNeu returned no audio for a nonempty moderated segment")
        from audio_translate.tts.voice_styles import finish_audio
        finish_audio(output, self.settings.get("style"))
