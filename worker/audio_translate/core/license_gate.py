"""Application adapter to native Windows authority; no Python verification."""
import json
import os
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[3]  # app root: worker/audio_translate/core/license_gate.py
class LicenseError(Exception):
    def __init__(self, code): self.code=code; super().__init__(code)

def native_command(payload):
    # The security service (native core as a Windows service) is the authority. Prefer the pipe;
    # fall back to the CLI binary when the pipe is absent. The binary itself decides whether it is
    # allowed to answer offline (dev builds) or must report the service unavailable (release).
    try:
        from audio_translate.core import secure_channel
        return secure_channel.call(payload)
    except Exception:
        pass
    try:
        process=subprocess.run([str(ROOT/'security-core'/'bin'/'audio-security-core.exe')],
            input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=40,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if process.returncode or len(process.stdout)>65536: raise ValueError('CORE_UNAVAILABLE')
        return json.loads(process.stdout)
    except Exception as exc: raise LicenseError('CORE_UNAVAILABLE') from exc

class NativeLicenseService:
    @property
    def root(self): return native_command({'action':'identity'})['root_public_key']
    def getLicenseStatus(self): return native_command({'action':'status'})
    def getMachineId(self): return native_command({'action':'machine'})['machine_id']
    def activate(self, token): return self._adopt('activate',token)
    def renew(self, token): return self._adopt('renew',token)
    def _adopt(self, action, token):
        result=native_command({'action':action,'token':token})
        if result.get('http_status')!=200: raise LicenseError(result.get('status','INVALID'))
        return result
    def canRunProtectedFeature(self, internet=True):
        result=native_command({'action':'check','internet':internet})
        if result.get('status')!='ACTIVE' or result.get('allowed') is not True: raise LicenseError(result.get('status','INVALID'))
        return True

def service(): return NativeLicenseService()

def assert_allowed(internet=True): return service().canRunProtectedFeature(internet)

def main():
    try:
        payload = json.loads(sys.stdin.read().lstrip('\ufeff'))
        print(json.dumps(native_command(payload)))
    except LicenseError as exc:
        print(json.dumps({'http_status':403, 'status':exc.code, 'error':exc.code}))
    except Exception:
        print(json.dumps({'http_status':503,'status':'INVALID','error':'License service unavailable. Check Windows secure storage and machine identifiers.'}))

if __name__ == '__main__': main()
