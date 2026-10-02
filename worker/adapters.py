"""Adapters around the unmodified official NLLB and VieNeu APIs."""
import os
from pathlib import Path
import re
import sys

from storage import DATA, ROOT, atomic_json, read_json
from providers import vieneu_source


def adapter_settings(job_dir):
    path = Path(job_dir) / "working" / "adapters.json"
    job = read_json(Path(job_dir)/'job.json')
    if path.exists():
        settings = read_json(path)
        if job.get('selected_voice_id'): settings['tts']['voice'] = job['selected_voice_id']
        return settings
    model = os.getenv("NLLB_MODEL_PATH")
    if not model:
        cached = ROOT.parent / "huggingface" / "hub" / "models--facebook--nllb-200-distilled-600M"
        ref = cached / "refs" / "main"
        snapshot = cached / "snapshots" / ref.read_text().strip() if ref.exists() else None
        model = str(snapshot) if snapshot and (snapshot / "config.json").is_file() else "facebook/nllb-200-distilled-600M"
    settings = {
        "translation": {"model": model, "source_lang": "zho_Hans", "target_lang": "vie_Latn",
            "device": os.getenv("NLLB_DEVICE", "cpu"), "batch_size": max(1, min(8, int(os.getenv("NLLB_BATCH_SIZE", "4")))),
            "source_tokens": 384, "output_tokens": 768, "version": 1},
        "tts": {"source": str(vieneu_source()),
            "device": os.getenv("VIENEU_DEVICE", "cpu"), "voice": job.get("selected_voice_id") or os.getenv("VIENEU_VOICE", "Hải Đăng"),
            "precision": os.getenv("VIENEU_PRECISION", "fp32"), "sample_rate": 48000, "version": 1},
    }
    atomic_json(path, settings)
    return settings


class TranslationAdapter:
    def __init__(self, settings):
        self.settings = settings
        self.model = None

    def load(self):
        if self.model is not None:
            return
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        torch.set_num_threads(max(1, int(os.getenv("AI_NUM_THREADS", "4"))))
        s = self.settings
        self.tokenizer = AutoTokenizer.from_pretrained(s["model"], src_lang=s["source_lang"], trust_remote_code=False)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(s["model"], trust_remote_code=False).to(s["device"]).eval()
        self.target_id = self.tokenizer.convert_tokens_to_ids(s["target_lang"])
        if self.target_id == self.tokenizer.unk_token_id:
            raise RuntimeError("NLLB tokenizer does not contain vie_Latn")

    def parts(self, text):
        # Split oversized segments without dropping/truncating any source text.
        if len(self.tokenizer.encode(text, add_special_tokens=True)) <= self.settings["source_tokens"]:
            yield text
            return
        middle = len(text) // 2
        boundaries = [m.end() for m in re.finditer(r"[。！？；，.!?;\s]", text[:middle + 1])]
        cut = boundaries[-1] if boundaries and boundaries[-1] > middle // 2 else middle
        if not 0 < cut < len(text):
            raise RuntimeError("NLLB cannot split oversized input safely")
        yield from self.parts(text[:cut])
        yield from self.parts(text[cut:])

    from control import complete_task
    @complete_task
    def translate(self, texts):
        if not any(text.strip() for text in texts):
            return ["" for _ in texts]
        self.load()
        import torch
        outputs = [[] for _ in texts]
        pending = []
        def flush():
            if not pending:
                return
            from control import check_cancel
            check_cancel()
            inputs = self.tokenizer([part for _, part in pending], return_tensors="pt", padding=True, truncation=False).to(self.settings["device"])
            with torch.inference_mode():
                generated = self.model.generate(**inputs, forced_bos_token_id=self.target_id,
                    max_new_tokens=self.settings["output_tokens"], num_beams=1, do_sample=False)
            for (owner, _), tokens in zip(pending, generated, strict=True):
                # The decoder starts with EOS; only a later EOS proves completion.
                if self.tokenizer.eos_token_id not in tokens.tolist()[1:]:
                    raise RuntimeError("NLLB reached its output limit; refusing to save a truncated translation")
                translated = self.tokenizer.decode(tokens, skip_special_tokens=True).strip()
                if not translated:
                    raise RuntimeError("NLLB returned empty text for a nonempty source segment")
                outputs[owner].append(translated)
            pending.clear()
        for index, text in enumerate(texts):
            if not text.strip():
                continue
            for part in self.parts(text):
                if part.strip():
                    pending.append((index, part))
                if len(pending) >= self.settings["batch_size"]:
                    flush()
        flush()
        return [" ".join(parts) for parts in outputs]


class TTSAdapter:
    sample_rate = 48000

    def __init__(self, settings):
        self.settings = settings
        self.engine = None

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
                             threads=max(1, int(os.getenv("AI_NUM_THREADS", "4"))), max_batch_size=1)
        if self.engine.sample_rate != self.sample_rate:
            raise RuntimeError("Unexpected VieNeu sample rate")
        # Validate the requested preset instead of silently changing voices.
        self.engine.get_preset_voice(self.settings["voice"])

    from control import complete_task
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
                from control import check_cancel
                check_cancel()
                chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
                if not np.isfinite(chunk).all():
                    raise RuntimeError("VieNeu returned invalid audio samples")
                handle.write(chunk)
                frames += len(chunk)
        if not frames:
            raise RuntimeError("VieNeu returned no audio for a nonempty moderated segment")
