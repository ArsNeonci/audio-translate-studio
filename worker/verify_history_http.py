"""Large-file streaming/history acceptance; use --restart after server restart."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
import wave

from errors import initial_steps
import results
from storage import atomic_json, read_json, file_digest
from verify_http import request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://localhost:3001')
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--restart', action='store_true')
    parser.add_argument('--existing', action='store_true')
    parser.add_argument('--pid', type=int)
    args = parser.parse_args()
    results.DATA = args.data.resolve()
    results.RESULTS = results.DATA/'results'
    marker = args.data/'history-fixture.json'
    if args.restart or args.existing:
        fixture = read_json(marker)
        job_id = fixture['id']
    else:
        job_id = str(uuid.uuid4())
        job = args.data/'tmp'/job_id
        (job/'working').mkdir(parents=True)
        states = initial_steps({})
        for state in states.values(): state['state'] = 'COMPLETED'
        atomic_json(job/'job.json', {'id': job_id, 'name': 'History large-file acceptance', 'url':'https://youtu.be/1JzKgwOESoM', 'created_at':'2026-10-02T08:00:00Z', 'status':'COMPLETED', 'steps':states})
        with (job/'transcript.zh.jsonl').open('w', encoding='utf-8') as out:
            for i in range(160000):
                out.write(json.dumps({'start_ms':i*100, 'end_ms':i*100+90, 'text':'你好，世界。'*10}, ensure_ascii=False)+'\n')
        (job/'transcript.zh.md').write_text('## 中文\n\n你好，世界。\n', encoding='utf-8')
        (job/'voice').mkdir()
        (job/'voice'/'voice.manifest.jsonl').write_text(json.dumps({'index':1, 'file':'000001.wav'})+'\n')
        with wave.open(str(job/'voice.vi.wav'), 'wb') as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(48000)
            block = b'\0'*(1024*1024)
            for _ in range(64): out.writeframesraw(block)
        results.publish_step(job, 'TRANSCRIPTION')
        results.publish_step(job, 'TTS')
        saved = results.RESULTS/job_id
        fixture = {'id':job_id, 'jsonl_size':(saved/'transcription'/'transcript.zh.jsonl').stat().st_size,
                   'audio_sha':file_digest(saved/'tts'/'voice.vi.wav'), 'audio_size':(saved/'tts'/'voice.vi.wav').stat().st_size}
        atomic_json(marker, fixture)
        # The old working copy differs: API must read the published file.
        (job/'transcript.zh.md').write_text('NOT THE SAVED FILE', encoding='utf-8')
    saved = results.RESULTS/job_id
    base = f'/api/history/{job_id}'
    def call(path, expected=200):
        status, headers, body = request(args.base, path)
        assert status == expected, (path, status, body[:300])
        return json.loads(body)
    if args.restart:
        state = call(base)['job']
        assert state['name'] == 'History large-file acceptance'
        assert any(f['id'] == 'VOICE_WAV' for f in state['files'])
        assert request(args.base, base+'/files/VOICE_WAV', headers={'Range':'bytes=0-43'})[0] == 206
        assert '你好' in call(base+'/files/ZH_MD?preview=1')['content']
        from urllib.request import urlopen
        for _ in range(10):
            with urlopen(args.base+base+'/files/VOICE_WAV', timeout=30) as audio:
                audio.read(1024)  # Simulate stopping playback/closing a tab.
        assert call(base)['job']['id'] == job_id
        print('HISTORY RESTART OK: persisted metadata/files remain available without a history database')
        print('STREAM CANCELLATION OK: 10 interrupted audio requests; server still responds')
        return
    state = call(base)['job']
    assert len(state['files']) == 4
    assert not any(Path(f['path']).is_absolute() for f in state['files'])
    assert str(results.RESULTS) not in json.dumps(state)
    listing = call('/api/history?search=History%20large-file&status=COMPLETED&sort=oldest')
    assert any(j['id'] == job_id for j in listing['jobs'])
    original_id = (args.data/'current-job.txt').read_text().strip()
    assert call(f'/api/history/{original_id}')['job']['files']
    md = call(base+'/files/ZH_MD?preview=1')
    assert '你好' in md['content'] and 'NOT THE SAVED FILE' not in md['content']
    response = call(base+'/files/ZH_JSONL?preview=1')
    assert response['next_offset'] and len(response['content'].encode('utf-8')) <= 65536
    baseline = peak = None
    process = None
    if args.pid:
        import psutil
        process = psutil.Process(args.pid)
        baseline = peak = process.memory_info().rss
    for _ in range(20):
        response = call(base+f"/files/ZH_JSONL?preview=1&offset={response['next_offset']}")
        assert len(response['content'].encode('utf-8')) <= 65536
        if process: peak = max(peak, process.memory_info().rss)
    from urllib.request import urlopen
    digest = hashlib.sha256()
    with urlopen(args.base+base+'/files/VOICE_WAV/download', timeout=30) as response:
        assert int(response.headers['Content-Length']) == fixture['audio_size']
        assert response.headers['Content-Type'] == 'audio/wav'
        assert 'attachment' in response.headers['Content-Disposition']
        while chunk := response.read(1024*1024):
            digest.update(chunk)
            if process: peak = max(peak, process.memory_info().rss)
    assert digest.hexdigest() == fixture['audio_sha']
    range_status, range_headers, audio = request(args.base, base+'/files/VOICE_WAV', headers={'Range':'bytes=0-43'})
    assert range_status == 206 and len(audio) == 44 and audio[:4] == b'RIFF'
    assert request(args.base, base+'/files/VOICE_WAV', headers={'Range':'bytes=999999999999-'})[0] == 416
    call(base+'/files/ZH_JSONL?preview=1&offset=-1', 400)
    for path in ['/api/history/not-a-job', base+'/files/..%5C..%5C.env.local/download', base+'/files/%2Fetc%2Fpasswd/download']:
        call(path, 404)
    manifest = read_json(saved/'outputs.json')
    ghost = {'id':'VI_MD', 'type':'VI_MD', 'step':'TRANSLATION', 'path':'translation/transcript.vi.md', 'size':42, 'created_at':'now', 'status':'AVAILABLE'}
    manifest['files'].append(ghost)
    atomic_json(saved/'outputs.json', manifest)
    assert all(f['id'] != 'VI_MD' for f in call(base)['job']['files'])
    manifest['files'][-1]['path'] = '../private/secret.txt'
    atomic_json(saved/'outputs.json', manifest)
    call(base+'/files/VI_MD/download', 404)
    manifest['files'].pop()
    atomic_json(saved/'outputs.json', manifest)
    assert request(args.base, '/history')[0] == 200
    assert request(args.base, '/history/'+job_id)[0] == 200
    if process:
        delta = peak-baseline
        assert delta < 100*1024*1024, (baseline, peak)
        fixture['server_rss_delta'] = delta
        atomic_json(marker, fixture)
        print(f'Memory: peak RSS increase {delta/1048576:.1f} MiB; JSONL {fixture["jsonl_size"]/1048576:.1f} MiB; streamed WAV 64 MiB')
    print('HISTORY HTTP OK: legacy jobs, search/filter/sort, saved Markdown, bounded JSONL chunks, audio ranges, 64 MiB streamed download checksum, path traversal/missing files blocked, no absolute paths')
    print('Fixture:', job_id)


if __name__ == '__main__': main()
