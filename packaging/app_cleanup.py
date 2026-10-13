"""Ends every process started from this installation (the local API, workers, llama-server). The desktop shell runs it before it starts
the API and when it quits: a workflow started by the security service is not a child of the API, so only a scan by program path finds it.

    python app_cleanup.py [--keep PID ...]
"""
import argparse
import os
from pathlib import Path
import sys
# The bundled python312._pth switches off the script-directory entry of sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent / 'app' / 'worker'))


def app_processes(root, skip=()):
    """Every running process whose program file lives inside this installation."""
    import psutil
    prefix = str(Path(root).resolve()).lower().rstrip('\\/') + os.sep
    found = []
    for process in psutil.process_iter(['pid', 'exe']):
        try:
            exe = process.info.get('exe') or ''
            if exe.lower().startswith(prefix) and process.pid not in skip: found.append(process)
        except psutil.Error: continue
    return found


def stop_app(root, keep=()):
    """Stop everything started from this installation, except `keep` and this process. Returns how many processes were stopped."""
    import psutil
    processes = app_processes(root, {os.getpid(), *keep})
    for process in processes:
        try: process.terminate()
        except psutil.Error: pass
    _, alive = psutil.wait_procs(processes, timeout=5)
    for process in alive:
        try: process.kill()
        except psutil.Error: pass
    # The hidden Edge that reads the YouTube sign-in is not inside the installation folder, so the scan above never sees it. A worker stopped
    # mid-download leaves it running (about 500 MB). Only a hidden browser on this app's own profile is ended, never the person's own Edge.
    try:
        from audio_translate.transcription import browser_cleanup
        browser_cleanup.stop_hidden()
    except Exception: pass
    return len(processes)


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument('--keep', type=int, action='append', default=[])
    args = parser.parse_args(argv)
    stop_app(Path(__file__).resolve().parent, args.keep)


if __name__ == '__main__': main()
