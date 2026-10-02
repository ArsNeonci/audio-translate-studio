"""Phase 1 layout abstraction; per-user installation remains supported."""
import os
from pathlib import Path

def user_root(): return Path(os.environ['LOCALAPPDATA'])/'AudioTranslate'
def data_root(): return Path(os.getenv('AUDIO_DATA_DIR',str(user_root()/'data')))
def license_root(): return Path(os.getenv('AUDIO_LICENSE_STATE_ROOT',str(user_root()/'license')))
def preferred_install_root(): return Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'AudioTranslate'

def application_paths(install_root):
    root=Path(install_root)
    return {'application':root/'app','security_core':root/'app'/'security-core'/'bin'/'audio-security-core.exe',
            'data':data_root(),'license':license_root(),'preferred_install':preferred_install_root()}
