"""Compile the Windows Rust trust boundary. No runtime root-key override."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent

def build(anchor=None, destination=None, target_dir=None, dev_fallback=True):
    # dev_fallback=True keeps the CLI/in-process path when the service pipe is absent (dev/test).
    # Release installers build with dev_fallback=False so only the running service can authorize.
    core = ROOT/'security-core'
    anchor = Path(anchor or core/'trust-anchor.json').resolve()
    expected = json.loads(anchor.read_text(encoding='utf-8'))
    env = {**os.environ, 'AUDIO_TRUST_ANCHOR_BUILD_FILE':str(anchor)}
    local_tools = ROOT.parent/'.tools'/'rust'
    cargo = shutil.which('cargo')
    if not cargo and (local_tools/'cargo'/'bin'/'cargo.exe').is_file():
        cargo = str(local_tools/'cargo'/'bin'/'cargo.exe')
        env.update(CARGO_HOME=str(local_tools/'cargo'), RUSTUP_HOME=str(local_tools/'rustup'))
    if not cargo: raise RuntimeError('RUST_TOOLCHAIN_REQUIRED')
    target = os.getenv('AUDIO_RUST_TARGET', 'x86_64-pc-windows-gnu' if shutil.which('gcc') else 'x86_64-pc-windows-msvc')
    target_dir = Path(target_dir or core/'target').resolve()
    command = [cargo,'build','--release','--locked','--target',target,'--target-dir',str(target_dir)]
    if not dev_fallback: command.append('--no-default-features')
    subprocess.run(command,cwd=core,env=env,check=True)
    binary = target_dir/target/'release'/'audio-security-core.exe'
    identity = subprocess.run([str(binary)],input='{"action":"identity"}',capture_output=True,text=True,check=True)
    result = json.loads(identity.stdout)
    if any(result.get(k)!=expected[k] for k in ['product_id','root_public_key']): raise RuntimeError('COMPILED_TRUST_ANCHOR_MISMATCH')
    destination = Path(destination or core/'bin'/'audio-security-core.exe')
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(binary,destination)
    return destination

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--anchor');args=parser.parse_args()
    print('Native Security Core built:',build(args.anchor))
