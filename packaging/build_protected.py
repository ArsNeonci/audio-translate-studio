"""Compile asset code modules to .pyd with Nuitka (Phase 2B), removing the .py sources.

Feasibility verified on this toolchain: Nuitka 4.2 + the bundled MinGW gcc compiles an asset
module to a ~400 KB .pyd offline, and the compiled module imports and runs in-package. The
hardened installer build invokes this over the staged payload so asset data lives in the vault
and asset logic ships as .pyd instead of readable .py. PyInstaller is not treated as protection.

Modules keep working because their imports resolve at runtime (`--module` does not inline them).
If Nuitka is unavailable the installer logs the reason and keeps the .py (documented degradation).
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Asset 1-5 logic (data already moved to the vault). Paths are relative to the worker root.
MODULES = [
    'audio_translate/translation/names.py',
    'audio_translate/translation/lexicon.py',
    'audio_translate/translation/source_cleanup.py',
    'audio_translate/translation/hymt_translation.py',
    'audio_translate/moderation/address.py',
    'audio_translate/moderation/rules.py',
    'audio_translate/workflow/postprocess.py',
]


def compile_module(py_path):
    out_dir = py_path.parent
    stem = py_path.stem
    subprocess.run([sys.executable, '-m', 'nuitka', '--module', '--mingw64',
                    '--assume-yes-for-downloads', '--quiet', f'--output-dir={out_dir}', str(py_path)],
                   check=True)
    built = list(out_dir.glob(f'{stem}.*.pyd'))
    if not built:
        raise RuntimeError(f'Nuitka produced no .pyd for {py_path}')
    py_path.unlink()
    shutil.rmtree(out_dir / f'{stem}.build', ignore_errors=True)
    (out_dir / f'{stem}.pyi').unlink(missing_ok=True)
    return built[0].name


def build(worker_root, modules=None):
    """Compile each present module to .pyd and drop its .py; return the .pyd names written."""
    worker_root = Path(worker_root)
    written = []
    for rel in (modules or MODULES):
        py = worker_root / rel
        if py.is_file():
            written.append(compile_module(py))
    return written


def main():
    parser = argparse.ArgumentParser(description='Compile asset modules to .pyd (Nuitka)')
    parser.add_argument('--worker-root', required=True, help='the worker/ root to compile in place')
    args = parser.parse_args()
    written = build(args.worker_root)
    print(f'Compiled to .pyd: {", ".join(written) or "(no modules found)"}')


if __name__ == '__main__':
    main()
