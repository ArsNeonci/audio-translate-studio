"""Names that differ between Windows and Linux builds of the same app."""
import os
from pathlib import Path

CORE_NAME = 'audio-security-core.exe' if os.name == 'nt' else 'audio-security-core'


def core_binary(root):
    """The native security core inside an app folder."""
    return Path(root) / 'security-core' / 'bin' / CORE_NAME
