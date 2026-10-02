"""Real compiled native core + Windows DPAPI + unchanged moderation workflow.

Synthetic root compiled into an isolated executable; never sign with live Admin
keys, edit the live verifier, or overwrite an installed user's license state.
Run with the Product venv: python -m unittest discover -s packaging -p test_*.py.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
import socket
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from build_security_core import build, ROOT
sys.path.insert(0,str(ROOT.parent/'shared-license-sdk'))
from license_sdk.crypto import private, public, sign, token, b64, canonical, decode
from license_sdk.windows import DPAPI, SecureStore, getMachineId

class NativeIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'data'/'verification').mkdir(parents=True,exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(prefix='security-phase1-',dir=ROOT/'data'/'verification')
        cls.base=Path(cls.temp.name);cls.app=cls.base/'app';cls.app.mkdir()
        cls.root_key=private(bytes([73])*32);cls.signer=private(bytes([19])*32)
        anchor=cls.base/'build-anchor.json'
        anchor.write_text(json.dumps({'product_id':'audio-translate','root_public_key':public(cls.root_key)}))
        cls.binary=build(anchor,cls.app/'security-core'/'bin'/'audio-security-core.exe')
        shutil.copytree(ROOT/'worker',cls.app/'worker',ignore=shutil.ignore_patterns('tmp*','test_*','__pycache__','*.pyc'))
        # Test runtime references host packages; the actual installer has its own
        # isolated portable runtime (separately audited by packaging smoke).
        runtime=cls.base/'runtime'/'python';runtime.mkdir(parents=True)
        host=Path(sys.base_prefix)
        for pattern in ['python*.exe','python*.dll','vcruntime*.dll']:
            for p in host.glob(pattern): shutil.copy2(p,runtime/p.name)
        paths=[str(host/'Lib'),str(host/'DLLs'),str(ROOT/'.venv'/'Lib'/'site-packages'),
               str(Path(os.environ['APPDATA'])/'Python'/'Python312'/'site-packages'),str(cls.app/'worker')]
        (runtime/'python312._pth').write_text('\n'.join(paths)+'\nimport site\n')
        cls.python=runtime/'python.exe'
        cls.machine=cls.invoke({'action':'machine'})['machine_id']

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    @classmethod
    def invoke(cls,payload,env=None):
        result=subprocess.run([str(cls.binary)],input=json.dumps(payload),text=True,encoding='utf-8',
            capture_output=True,env=env or {**os.environ,'AUDIO_LICENSE_STATE_ROOT':str(cls.base/'default-state')},timeout=120)
        if result.returncode and payload.get('action')!='workflow': raise AssertionError(result.stderr)
        try: return json.loads(result.stdout)
        except ValueError: return {'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr}

    def setUp(self):
        self.folder=self.base/uuid.uuid4().hex;self.folder.mkdir()
        self.state=self.folder/'license'
        self.activated_at=(datetime.now(timezone.utc)-timedelta(days=3)).isoformat()
        self.env={**os.environ,'AUDIO_LICENSE_STATE_ROOT':str(self.state),'AUDIO_DATA_DIR':str(self.folder/'data'),
                  'RESULTS_ROOT':str(self.folder/'data'/'results'), 'VIENEU_SOURCE':str(ROOT.parent/'VieNeu-TTS-main'),
                  'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1'}

    def issue(self,machine=None,days=30,sequence=1,key_version=1):
        current=datetime.now(timezone.utc)
        signer=private(bytes([18+key_version])*32)
        cert={'product_id':'audio-translate','key_version':key_version,'public_key':public(signer)}
        certificate={'payload':cert,'signature':sign(self.root_key,'product-signing-key-v1',cert)}
        payload={'license_id':'synthetic','entitlement_id':'synthetic-entitlement','customer_id':'synthetic-customer',
                 'product_id':'audio-translate','machine_id':machine or self.machine,'sequence':sequence,
                 'activated_at':self.activated_at,'issued_at':(current-timedelta(days=2)).isoformat(),
                 'expires_at':(current+timedelta(days=days)).isoformat(),'key_version':key_version}
        return token(certificate,payload,signer)

    def call(self,payload): return self.invoke(payload,self.env)
    def activate(self,**options): return self.call({'action':'activate','token':self.issue(**options)})

    def test_valid_restart_encrypted_and_machine_compatibility(self):
        self.assertEqual(self.machine,getMachineId())
        self.assertEqual(self.activate()['status'],'ACTIVE')
        self.assertEqual(self.call({'action':'check','internet':False})['allowed'],True)
        self.assertEqual(self.call({'action':'status'})['sequence'],1)
        raw=(self.state/'state.dpapi').read_bytes()
        self.assertNotIn(self.machine.encode(),raw)
        saved=SecureStore(self.state/'state.dpapi').read()
        self.assertEqual(saved['highest_sequence'],1);self.assertEqual(saved['key_version'],1)

    def test_wrong_machine_and_copy_rejected(self):
        self.assertEqual(self.activate(machine='b'*64)['status'],'WRONG_MACHINE')
        valid=self.issue(machine='b'*64)
        state={'current_license':valid,'current_public_key':public(self.signer),'machine_id':'b'*64,
               'highest_sequence':1,'last_verified_time':0,'key_version':1}
        SecureStore(self.state/'state.dpapi').write(state)
        self.assertEqual(self.call({'action':'check','internet':False})['status'],'WRONG_MACHINE')

    def test_expired_and_modified_token(self):
        expired=self.activate(days=-1);self.assertEqual(expired['status'],'EXPIRED')
        self.assertEqual(self.call({'action':'check'})['status'],'EXPIRED')
        e=decode(self.issue());e['payload']['expires_at']='2099-01-01T00:00:00Z'
        self.assertEqual(self.call({'action':'activate','token':b64(canonical(e))})['status'],'INVALID')

    def test_metadata_root_cannot_replace_compiled_anchor(self):
        config=self.app/'licensing'/'public-config.json';config.parent.mkdir(exist_ok=True)
        config.write_text(json.dumps({'root_public_key':public(private(bytes([99])*32)),'product_id':'evil'}))
        self.assertEqual(self.call({'action':'identity'})['root_public_key'],public(self.root_key))
        self.assertEqual(self.activate()['status'],'ACTIVE')

    def test_sequence_rotation_and_legacy_state_migration(self):
        activation=self.issue()
        SecureStore(self.state/'state.dpapi').write({'current_license':activation,'current_public_key':public(self.signer),
            'machine_id':self.machine,'license_sequence':1,'last_verified_time':0.0})
        self.assertEqual(self.call({'action':'check','internet':False})['status'],'ACTIVE')
        renewed=self.issue(sequence=2,key_version=2,days=60)
        self.assertEqual(self.call({'action':'renew','token':renewed})['sequence'],2)
        self.assertEqual(self.call({'action':'renew','token':renewed})['status'],'SEQUENCE_REPLAY')
        self.assertEqual(self.call({'action':'renew','token':activation})['status'],'SEQUENCE_REPLAY')

    def test_python_patch_cannot_unlock_native_admission(self):
        # Patch only a copied installation. Native launch must deny even though
        # this copied Python adapter advertises unconditional success.
        gate=self.app/'worker'/'license_gate.py';original=gate.read_bytes()
        try:
            gate.write_text('def assert_allowed(internet=True): return True\n')
            check=subprocess.run([str(self.python),'-c','from license_gate import assert_allowed; assert assert_allowed()'],env=self.env,capture_output=True)
            self.assertEqual(check.returncode,0,check.stderr.decode(errors='replace'))
            self.activate(days=-1)
            for script,action in [('manage.py','create'),('manage.py','convert'),('manage.py','reprocess'),('manage.py','resume'),('retry.py','retry')]:
                denied=self.call({'action':'command','script':script,'payload':{'action':action,'tool':'moderation'}})
                self.assertEqual(denied['status'],403);self.assertEqual(denied['license_status'],'EXPIRED')
            self.assertEqual(self.call({'action':'workflow','job_dir':str(self.folder/'nonexistent')})['license_status'],'EXPIRED')
        finally: gate.write_bytes(original)

    def test_real_moderation_tool_through_native_launcher(self):
        self.assertEqual(self.activate()['status'],'ACTIVE')
        data=self.folder/'data';upload=data/'uploads'/'input.txt';upload.parent.mkdir(parents=True);upload.write_text('Xin chào thế giới.',encoding='utf-8')
        response=self.call({'action':'command','script':'manage.py','payload':{'action':'create','tool':'moderation',
            'upload':str(upload),'input_name':'input.txt','mime':'text/plain'}})
        self.assertEqual(response.get('status'),200,response)
        job=response['job'];job_dir=data/'tool-tmp'/job['id']
        result=self.call({'action':'workflow','job_dir':str(job_dir)})
        saved=json.loads((job_dir/'job.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['status'],'COMPLETED',result)
        output=data/'results'/'tools'/f"{job['workflow_no']:06d}"/'moderation'/f"{job['workflow_no']:06d}-transcript.vi.moderated.md"
        self.assertIn('Xin chào',output.read_text(encoding='utf-8'))

    def test_next_http_boundaries_with_patched_python(self):
        dist=ROOT/'.next-security-phase1'/'standalone'
        source=dist/'audio-translates' if (dist/'audio-translates'/'server.js').exists() else dist
        self.assertTrue((source/'server.js').exists(),'Build Next with AUDIO_NEXT_DIST_DIR=.next-security-phase1 before integration tests')
        shutil.copytree(source,self.app,dirs_exist_ok=True,
            ignore=shutil.ignore_patterns('security-core','worker','.env*','data'))
        # Leave the synthetic-root native binary untouched. Only copied Python
        # is edited; the built Next server must continue to consult native core.
        gate=self.app/'worker'/'license_gate.py';original=gate.read_bytes()
        gate.write_text('def assert_allowed(internet=True): return True\n')
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env={**self.env,'HOSTNAME':'127.0.0.1','PORT':str(port)}
        base=f'http://127.0.0.1:{port}'
        def http(path,body=None):
            request=Request(base+path,data=json.dumps(body).encode() if body is not None else None,
                headers={'Content-Type':'application/json'})
            try:r=urlopen(request,timeout=60)
            except HTTPError as error:r=error
            with r:return r.status,json.loads(r.read())
        log=(self.folder/'http-server.log').open('wb')
        server=subprocess.Popen([shutil.which('node'),str(self.app/'server.js')],cwd=self.app,env=env,
            stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(60):
                try:http('/api/license');break
                except URLError:time.sleep(.25)
            else:self.fail('Next server startup failed')
            code,result=http('/api/license',{'action':'activate','token':self.issue(days=-1)})
            self.assertEqual(code,200);self.assertEqual(result['status'],'EXPIRED')
            job=str(uuid.uuid4())
            for route,body in [('/api/jobs',{'url':'https://youtu.be/1JzKgwOESoM'}),
                (f'/api/jobs/{job}/retry',{}),(f'/api/jobs/{job}/steps/TRANSLATION',{}),
                (f'/api/jobs/{job}/reprocess',{'step':'TRANSCRIPTION'}),(f'/api/jobs/{job}/resume',{}),
                ('/api/tools',{})]:
                code,result=http(route,body);self.assertEqual(code,403,(route,result))
            code,_=http('/api/jobs/preflight');self.assertEqual(code,403)
            code,result=http('/api/license');self.assertEqual(code,200);self.assertEqual(result['status'],'EXPIRED')
            code,result=http('/api/history');self.assertEqual(code,200,result)
            code,result=http('/api/license',{'action':'renew','token':self.issue(sequence=2,key_version=2,days=60)})
            self.assertEqual(code,200,result);self.assertEqual(result['status'],'ACTIVE')
            code,result=http('/api/license');self.assertEqual(result['sequence'],2)
        finally:
            server.terminate();server.wait(timeout=20);log.close();gate.write_bytes(original)

if __name__=='__main__':
    (ROOT/'data'/'verification').mkdir(parents=True,exist_ok=True)
    unittest.main()
