"""Installed per-user application: isolated data, bundled CPU runtime."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
# The bundled python312._pth switches off the script-directory entry of sys.path, so `paths` must be found explicitly.
sys.path.insert(0,str(Path(__file__).resolve().parent))
from paths import application_paths

def app_processes(root,skip=()):
    """Every running process whose program file lives inside this installation (the web server, workers, llama-server)."""
    import psutil
    prefix=str(Path(root).resolve()).lower().rstrip('\\/')+os.sep
    found=[]
    for process in psutil.process_iter(['pid','exe']):
        try:
            exe=process.info.get('exe') or ''
            if exe.lower().startswith(prefix) and process.pid not in skip: found.append(process)
        except psutil.Error: continue
    return found

def stop_app(root,keep=()):
    """Stop everything started from this installation, except this process. Returns how many processes were stopped."""
    import psutil
    processes=app_processes(root,{os.getpid(),*keep})
    for process in processes:
        try: process.terminate()
        except psutil.Error: pass
    _,alive=psutil.wait_procs(processes,timeout=5)
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

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--no-browser',action='store_true'); parser.add_argument('--port',type=int,default=3210)
    parser.add_argument('--quit',action='store_true',help='stop the web server and every worker of this installation'); args=parser.parse_args()
    root=Path(__file__).resolve().parent
    if args.quit:
        time.sleep(1.5)  # the page that asked for this gets its answer before the server goes away
        stop_app(root); return
    paths=application_paths(root)
    if not paths['security_core'].is_file(): raise RuntimeError('NATIVE_SECURITY_CORE_MISSING')
    data=paths['data']; data.mkdir(parents=True,exist_ok=True)
    # The 4.6 GB model is not in the installer (Windows refuses executables over 4 GiB); the app downloads it into the data folder after activation.
    env={**os.environ,'PYTHON_BIN':str(root/'runtime'/'python'/'python.exe'),'AUDIO_LAUNCHER':str(root/'launcher.py'),'PYTHONUTF8':'1','HY_MT_MODEL_PATH':str(data/'models'/'Hy-MT2-7B-Q4_K_M'/'Hy-MT2-7B-Q4_K_M.gguf'),'PYTHONNOUSERSITE':'1','AUDIO_DATA_DIR':str(data),'RESULTS_ROOT':str(data/'results'),'VIENEU_SOURCE':str(root/'providers'/'VieNeu'),'NODE_PATH':str(root/'app'/'node_modules'),'PORT':str(args.port),'HOSTNAME':'127.0.0.1','PATH':str(root/'runtime'/'ffmpeg')+';'+str(root/'runtime'/'node')+';'+os.environ.get('PATH','')}
    url=f'http://127.0.0.1:{args.port}'
    product=json.loads((root/'app'/'licensing'/'public-config.json').read_text(encoding='utf-8'))['product_id']
    try:
        with urllib.request.urlopen(url+'/api/license',timeout=10) as response:
            # Another edition already serving this port must be closed first.
            if json.load(response).get('product_id')!=product: raise RuntimeError('PORT_IN_USE')
    except (urllib.error.URLError,OSError):  # a refused connection or a slow first answer both mean: not serving yet
        # A second click on the shortcut while the first launcher is still starting the server must wait for it, not clean it away.
        import psutil
        lock=data/'launcher.lock'; other=None
        try:
            pid,stamp=lock.read_text(encoding='utf-8').split()
            if time.time()-float(stamp)<120 and int(pid)!=os.getpid() and psutil.pid_exists(int(pid)): other=int(pid)
        except (OSError,ValueError): pass
        if other is None:
            lock.write_text(f'{os.getpid()} {time.time()}',encoding='utf-8')
            try: stop_app(root)  # leftovers of an earlier run (a crashed server, a worker that outlived it) would hold memory and files
            except Exception: pass
            with (data/'desktop-server.log').open('ab') as log:
                subprocess.Popen([str(root/'runtime'/'node'/'node.exe'),str(root/'app'/'server.js')],cwd=root/'app',env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(60):
            try:
                with urllib.request.urlopen(url+'/api/license',timeout=15) as response: json.load(response)
                break
            except (urllib.error.URLError,OSError): time.sleep(1)
        else: raise RuntimeError('STARTUP_FAILED: see desktop-server.log')
    if not args.no_browser:webbrowser.open(url)

def run():
    # The Start-menu shortcut uses pythonw.exe, which shows no console: a startup failure is written to a log and shown in a message box.
    try: main()
    except BaseException as error:
        if isinstance(error,SystemExit) and not error.code: raise
        log=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'AudioTranslate'/'launcher-error.log'
        try: log.parent.mkdir(parents=True,exist_ok=True); log.write_text(traceback.format_exc(),encoding='utf-8')
        except OSError: pass
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,f'Audio Translate could not start: {error}\n\nDetails: {log}','Audio Translate',0x10)
        except Exception: pass
        raise

if __name__=='__main__':run()
