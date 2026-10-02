"""Provider locations, including compatibility with pre-cleanup checkpoints."""
import os
from pathlib import Path
from storage import ROOT


def vieneu_source(source=None):
    flat = ROOT.parent / 'VieNeu-TTS-main'
    requested = Path(source or os.getenv('VIENEU_SOURCE') or flat)
    # Resolve old persisted paths without rewriting adapter settings/fingerprints.
    if requested.resolve() == (flat / 'VieNeu-TTS-main').resolve():
        if (flat / 'src' / 'vieneu' / 'factory.py').is_file():
            return flat
    return requested
