"""Compile the desktop shell (desktop/, Tauri). Same toolchain rules as build_security_core.py; the shell holds no product logic."""
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def build(destination=None, target_dir=None):
    shell = ROOT/'desktop'
    env = dict(os.environ)
    local_tools = ROOT.parent/'.tools'/'rust'
    cargo = shutil.which('cargo')
    if not cargo and (local_tools/'cargo'/'bin'/'cargo.exe').is_file():
        cargo = str(local_tools/'cargo'/'bin'/'cargo.exe')
        env.update(CARGO_HOME=str(local_tools/'cargo'), RUSTUP_HOME=str(local_tools/'rustup'))
    if not cargo: raise RuntimeError('RUST_TOOLCHAIN_REQUIRED')
    gcc = shutil.which('gcc')
    if not gcc and Path(r'C:\msys64\mingw64\bin\gcc.exe').is_file(): env['PATH'] = r'C:\msys64\mingw64\bin;' + env.get('PATH', ''); gcc = 'gcc'
    target = os.getenv('AUDIO_RUST_TARGET', 'x86_64-pc-windows-gnu' if gcc else 'x86_64-pc-windows-msvc')
    target_dir = Path(target_dir or shell/'target').resolve()
    subprocess.run([cargo, 'build', '--release', '--locked', '--target', target, '--target-dir', str(target_dir)], cwd=shell, env=env, check=True)
    binary = target_dir/target/'release'/'AudioTranslate.exe'
    destination = Path(destination or shell/'bin'/'AudioTranslate.exe')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binary, destination)
    return destination


if __name__ == '__main__': print('Desktop shell built:', build())
