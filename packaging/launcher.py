"""Installed per-user application: isolated data, bundled CPU runtime."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import webbrowser
from paths import application_paths

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--no-browser',action='store_true'); parser.add_argument('--port',type=int,default=3210); args=parser.parse_args()
    root=Path(__file__).resolve().parent
    paths=application_paths(root)
    if not paths['security_core'].is_file(): raise RuntimeError('NATIVE_SECURITY_CORE_MISSING')
    data=paths['data']; data.mkdir(parents=True,exist_ok=True)
    env={**os.environ,'PYTHON_BIN':str(root/'runtime'/'python'/'python.exe'),'PYTHONUTF8':'1','HY_MT_MODEL_PATH':str(root/'app'/'models'/'Hy-MT2-7B-Q4_K_M'/'Hy-MT2-7B-Q4_K_M.gguf'),'PYTHONNOUSERSITE':'1','AUDIO_DATA_DIR':str(data),'RESULTS_ROOT':str(data/'results'),'VIENEU_SOURCE':str(root/'providers'/'VieNeu'),'NODE_PATH':str(root/'app'/'node_modules'),'PORT':str(args.port),'HOSTNAME':'127.0.0.1','PATH':str(root/'runtime'/'ffmpeg')+';'+str(root/'runtime'/'node')+';'+os.environ.get('PATH','')}
    url=f'http://127.0.0.1:{args.port}'
    product=json.loads((root/'app'/'licensing'/'public-config.json').read_text(encoding='utf-8'))['product_id']
    try:
        with urllib.request.urlopen(url+'/api/license',timeout=2) as response:
            # Another edition already serving this port must be closed first.
            if json.load(response).get('product_id')!=product: raise RuntimeError('PORT_IN_USE')
    except urllib.error.URLError:
        with (data/'desktop-server.log').open('ab') as log:
            subprocess.Popen([str(root/'runtime'/'node'/'node.exe'),str(root/'app'/'server.js')],cwd=root/'app',env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(60):
            try:
                with urllib.request.urlopen(url+'/api/license',timeout=2) as response: json.load(response)
                break
            except urllib.error.URLError: time.sleep(1)
        else: raise RuntimeError('STARTUP_FAILED: see desktop-server.log')
    if not args.no_browser:webbrowser.open(url)

if __name__=='__main__':main()
