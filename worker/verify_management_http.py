"""Isolated HTTP acceptance with real adapters and real signed license states.

Use --setup, then run an isolated Next server with matching AUDIO_DATA_DIR,
RESULTS_ROOT and AUDIO_LICENSE_STATE_ROOT. No production license bypass exists.
"""
import argparse
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import uuid
import wave
import manage,results
from storage import DATA,ROOT,atomic_json,read_json,file_digest
from errors import initial_steps

def call(base,path,method='GET',body=None,headers=None):
    raw = body if isinstance(body,bytes) else json.dumps(body).encode() if body is not None else None
    req=Request(base+path,data=raw,method=method,headers=headers or ({'Content-Type':'application/json'} if raw else {}))
    try:r=urlopen(req,timeout=90)
    except HTTPError as e:r=e
    with r:return r.status,r.headers,r.read()

def setup():
    if not DATA.is_relative_to((ROOT/'data'/'verification').resolve()): raise ValueError('Use an isolated AUDIO_DATA_DIR under data/verification')
    DATA.mkdir(parents=True,exist_ok=True)
    job_id=str(uuid.uuid4());d=DATA/'tmp'/job_id;(d/'working').mkdir(parents=True)
    with manage.registry() as db:number=manage.allocate(db,job_id,'workflows')
    import voices
    catalog=voices.discover();voice=catalog['voices'][-1]['id']
    steps=initial_steps({})
    for item in steps.values():item.update(state='COMPLETED',progress=100,duration_ms=1000,attempt=1)
    job={'id':job_id,'workflow_no':number,'storage_scope':'workflows','name':'Management HTTP fixture','url':'https://youtu.be/1JzKgwOESoM','created_at':datetime.now(timezone.utc).isoformat(),'status':'COMPLETED','progress':100,'workflow_version':2,'selected_voice_id':voice,'steps':steps,'total_duration_ms':5000,'error':None}
    atomic_json(d/'job.json',job)
    for name,key,text in [('transcript.zh','text','你好，欢迎。'),('transcript.vi','text_vi','Xin chào các bạn.'),('transcript.vi.moderated','text_vi_moderated','Xin chào các bạn.')]:
        (d/(name+'.md')).write_text(text+'\n',encoding='utf-8')
        (d/(name+'.jsonl')).write_text(json.dumps({'start_ms':0,'end_ms':1000,key:text},ensure_ascii=False)+'\n',encoding='utf-8')
    atomic_json(d/'moderation-result.json',{'total_segments':1})
    (d/'voice').mkdir();(d/'voice'/'voice.manifest.jsonl').write_text('{"index":1,"file":"000001.wav"}\n')
    with wave.open(str(d/'voice.vi.wav'),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000)
        for _ in range(64):w.writeframesraw(b'\x00'*(1024*1024))
    for step in results.FILES:results.publish_step(d,step)
    saved=results.destination(job_id)
    fixture={'id':job_id,'number':number,'voice':voice,'audio_sha':file_digest(saved/'tts'/manage.filename(number,'voice.vi.wav'))}
    # Clone Admin's SQLite snapshot before creating only synthetic test rights.
    # Signing remains inside the unchanged Admin implementation and DPAPI.
    sys.path.insert(0,str(ROOT.parent/'admin-system'))
    from core import Authority
    from license_gate import service
    from license_sdk import LicenseService,SecureStore,getMachineId
    source=sqlite3.connect(f"file:{(ROOT.parent/'admin-system'/'data'/'admin.sqlite3').as_posix()}?mode=ro",uri=True)
    clone=ROOT.parent/'admin-system'/'data'/'verification'/'management-http'/'synthetic-admin.sqlite3'
    clone.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(clone) as target:source.backup(target)
    source.close();authority=Authority(clone)
    if authority.public_config('audio-translate')['root_public_key'] != service().root:raise AssertionError('Fixture signing root mismatch')
    customer=authority.customer('Synthetic management acceptance')
    entitlement=authority.entitlement(customer,'audio-translate',1)
    with patch('core.now',return_value=datetime.now(timezone.utc)-timedelta(days=3)):
        activation=authority.activate(entitlement,getMachineId())
    expired=DATA/'expired-license';manage.safe_directory(expired,DATA)
    # This path is reserved to the synthetic fixture, never the app license.
    (expired/'state.dpapi').unlink(missing_ok=True)
    client=LicenseService('audio-translate',service().root,SecureStore(expired/'state.dpapi'));client.activate(activation['token'])
    assert client.getLicenseStatus()['status']=='EXPIRED'
    atomic_json(DATA/'http-fixture.json',fixture)
    print('SETUP OK: isolated numbered history, 64 MiB WAV, signed expired fixture; no original Admin/license writes')

def verify(base,mode):
    if not DATA.is_relative_to((ROOT/'data'/'verification').resolve()): raise ValueError('Use isolated verification data')
    f=read_json(DATA/'http-fixture.json');job_id=f['id'];prefix=f'/api/history/{job_id}'
    checks=0
    def check(condition,label):
        nonlocal checks
        assert condition,label;checks+=1
    def data(path,expected=200,method='GET',body=None,headers=None):
        status,_,raw=call(base,path,method,body,headers);check(status==expected,f'{path}: {status} {raw[:300]}');return json.loads(raw)
    for page in ['/','/history','/tools','/reprocess',f'/history/{job_id}']:
        status,_,html=call(base,page);check(status==200 and b'Audio Studio' in html,'Page '+page)
    catalog=data('/api/voices');check(len(catalog['voices'])>=25,'All voices returned')
    item=data(prefix)['job'];check(item['workflow_no']==f['number'] and item['total_duration_ms']>=5000,'History number/timing')
    check(not any(Path(x['path']).is_absolute() for x in item['files']),'No storage paths exposed')
    data(prefix+'/files/VOICE_WAV?preview=1',403 if mode=='expired' else 200) if mode=='expired' else None
    # Download is permitted regardless of license and is read incrementally.
    request=Request(base+prefix+'/files/VOICE_WAV/download')
    with urlopen(request,timeout=90) as r:
        sha=hashlib.sha256();count=0
        while block:=r.read(65536):sha.update(block);count+=len(block)
        check(sha.hexdigest()==f['audio_sha'],'Streaming download checksum')
        check(count>=64*1024**2 and f"{f['number']:06d}-voice.vi.wav" in r.headers['Content-Disposition'],'Prefix and large download')
    data(prefix+'/files/..%5C..%5C.env.local/download',404)
    if mode=='expired':
        data('/api/tools?tool=tts&name=vi.txt',403,'POST',b'Xin chao',{'Content-Type':'text/plain'})
        data(f'/api/jobs/{job_id}/reprocess',403,'POST',{'step':'TTS'})
        data(prefix+'/files/ZH_MD?preview=1',403)
        # Hard deletion stays available even with expired license.
        data(prefix,409,'DELETE',{'confirm':f['number']+1})
        data(prefix,200,'DELETE',{'confirm':f['number']})
        check(not results.workspace(job_id).exists() and not (results.RESULTS/'workflows'/f"{f['number']:06d}").exists(),'Hard delete complete')
    elif mode=='restart':
        check(item['status']=='COMPLETED' and len(item['files'])==9,'Restart restores history')
        for tool_id in f.get('tool_ids',[]):check(data(f'/api/tools/{tool_id}')['job']['status']=='COMPLETED','Tool history after restart')
    else:
        data(prefix+'/files/ZH_MD?preview=1')
        status,_,raw=call(base,prefix+'/files/VOICE_WAV',headers={'Range':'bytes=0-43'});check(status==206 and len(raw)==44,'Audio range')
        tool_ids=[]
        for tool,text in [('translation','你好，欢迎。'),('tts','Xin chào các bạn.'),('moderation','Xin chào các bạn.')]:
            from urllib.parse import urlencode
            params=urlencode({'tool':tool,'name':'input.txt','voice':f['voice']})
            accepted=data('/api/tools?'+params,201,'POST',text.encode('utf-8'),{'Content-Type':'text/plain'})
            tool_id=accepted['job']['id'];tool_ids.append(tool_id)
            deadline=time.monotonic()+480
            while time.monotonic()<deadline:
                state=data(f'/api/tools/{tool_id}')['job']
                if state['status'] in ['COMPLETED','FAILED','CANCELLED']:break
                time.sleep(3)
            check(state['status']=='COMPLETED',f'Real {tool} adapter: '+str(state.get('steps')))
            check(state['selected_voice_id']==f['voice'],'Selected voice persisted')
            check(all(x['path'].split('/')[-1].startswith(f"{state['workflow_no']:06d}-") for x in state['files']),'Tool output names')
        listing=data('/api/tools');check(all(j['storage_scope']=='tools' for j in listing['jobs']),'Tool separation')
        listing=data('/api/history');check(all(j['storage_scope']=='workflows' for j in listing['jobs']),'Workflow separation')
        listing=data('/api/jobs');check(all(j.get('storage_scope')!='tools' for j in listing['jobs']),'Studio/Reprocess exclude tools')
        f['tool_ids']=tool_ids;atomic_json(DATA/'http-fixture.json',f)
        # A real reprocess uses the selected voice and retains the ASR artifact.
        zh=next(x for x in item['files'] if x['id']=='ZH_MD')['sha256']
        data(f'/api/jobs/{job_id}/reprocess',200,'POST',{'step':'TTS','voice':f['voice']})
        data(f'/api/jobs/{job_id}/cancel',200,'POST')
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            state=data(prefix)['job']
            if state['status']=='CANCELLED':break
            time.sleep(2)
        check(state['status']=='CANCELLED','Graceful HTTP cancel')
        check(next(x for x in state['files'] if x['id']=='ZH_MD')['sha256']==zh,'Cancel kept completed ASR')
        data(f'/api/jobs/{job_id}/reprocess',200,'POST',{'step':'TTS','voice':f['voice']})
        deadline=time.monotonic()+480
        while time.monotonic()<deadline:
            state=data(prefix)['job']
            if state['status'] in ['COMPLETED','FAILED','CANCELLED']:break
            time.sleep(3)
        check(state['status']=='COMPLETED','Real TTS reprocess completed')
        check(next(x for x in state['files'] if x['id']=='ZH_MD')['sha256']==zh,'Reprocess preserved ASR')
        check(state['workflow_no']==f['number'],'Reprocess preserved number')
        # Restore large fixture only for streaming restart/expired checks; tools
        # and the reprocessed small real WAV remain separately available.
        original=results.workspace(job_id)/'voice.vi.wav'
        with wave.open(str(original),'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000)
            for _ in range(64):w.writeframesraw(b'\0'*(1024*1024))
        results.publish_step(results.workspace(job_id),'TTS')
    print(f'MANAGEMENT HTTP {mode.upper()} OK: {checks} assertions')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--setup',action='store_true');p.add_argument('--base',default='http://localhost:3013');p.add_argument('--mode',choices=['active','restart','expired'],default='active');a=p.parse_args()
    if a.setup:setup()
    else:verify(a.base,a.mode)
