"""Basic edition: Voice generation on the VPS gateway (VieNeu there, CPU), billed per input character.

Plugs into `postprocess.synthesize` as a runtime (`synthesize_many(pending, commit)`), so reading units,
checkpoints, the manifest, pauses between units and the final `voice.vi.wav` stay exactly as for the
local engine. Units are sent in chunks of about `tts_chunk_chars` characters with `tts_inflight` chunks
outstanding, so the next chunk is synthesized while the previous one downloads. Audio comes back as
lossless FLAC; each unit is verified (frames, SHA-256 of the PCM) and committed as soon as it arrives,
so an interruption resumes from the first unit without a valid WAV.

The gateway voice and style processing (trim, tempo) use the same values the app sent; cues such as
[cười] are already in the unit text. A TTS run has its own gateway job (`tts-remote-state.json`);
Reprocess from TTS removes it, so a regenerated voice is billed as a new job.
"""
import base64
import hashlib
import io
import time
import uuid
from pathlib import Path

from audio_translate.core.control import Cancelled, check_cancel, stop_mode
from audio_translate.core.storage import atomic_json, read_json
from audio_translate.translation import genius

SAMPLE_RATE = 48000
MAX_UNIT_CHARS = 2000  # Gateway limit per unit; styled units are at most 220 characters.


class RemoteTTS:
    def __init__(self, job_dir, config, send=None, token=None, sleep=time.sleep):
        self.job_dir, self.config = Path(job_dir), config
        settings = genius.settings()
        self.endpoint = settings.get('endpoint') or ''
        self.chunk_chars = int(settings.get('tts_chunk_chars', 1200))
        self.inflight = max(1, int(settings.get('tts_inflight', 2)))
        self.poll = float(settings.get('tts_poll_seconds', 3))
        self.timeout = int(settings.get('request_timeout_seconds', 900))
        self.max_wait = int(settings.get('max_wait_seconds', 600))
        self.send, self.sleep = send or genius.post, sleep
        if not self.endpoint and send is None: genius.pause(job_dir, 'GATEWAY_UNAVAILABLE')
        try: self.token = token or genius.credential()
        except genius.GatewayError: genius.pause(job_dir, 'LICENSE_REJECTED')
        self.state_path = self.job_dir/'working'/'tts-remote-state.json'
        self.state = read_json(self.state_path) if self.state_path.exists() else {'billing_job_id': str(uuid.uuid4()), 'billed': {}}
        atomic_json(self.state_path, self.state)
        job = read_json(self.job_dir/'job.json')
        self.meta = {'kind': 'tool' if job.get('storage_scope') == 'tools' else 'workflow', 'label': str(job.get('name') or '')[:200]}
        self.done_units, self.failures = 0, {}

    def full(self, batch):
        """Batch boundary for synthesize(): several chunks, so requests overlap with downloads."""
        return len(batch) >= 400 or sum(len(entry[1][2]) for entry in batch) >= self.chunk_chars * max(4, self.inflight * 2)

    def chunks(self, pending):
        group, size = [], 0
        for item in pending:
            if group and size + len(item[1]) > self.chunk_chars: yield group; group, size = [], 0
            group.append(item); size += len(item[1])
        if group: yield group

    def synthesize_many(self, pending, commit):
        try:
            self._synthesize(pending, commit)
        except Cancelled:
            if stop_mode(self.job_dir) == 'cancel': self._finish('CANCELLED')
            raise

    def _synthesize(self, pending, commit):
        import numpy as np
        import soundfile as sf
        work = []
        for item in pending:
            index, text, temp = item
            if not text.strip():
                # Same as the local adapter: a one-sample silent unit, never sent or billed.
                sf.write(str(temp), np.zeros(1, dtype=np.int16), SAMPLE_RATE, format='WAV', subtype='PCM_16'); commit(item)
            elif len(text) > MAX_UNIT_CHARS: raise RuntimeError(f'Segment {index} is longer than {MAX_UNIT_CHARS} characters; split it and rerun')
            else: work.append(item)
        queue, outstanding = list(self.chunks(work)), []
        while queue or outstanding:
            check_cancel(self.job_dir)
            while queue and len(outstanding) < self.inflight:
                outstanding.append(queue.pop(0))
            progressed = False
            for chunk in list(outstanding):
                response = self._request(chunk)
                if response.get('state') != 'done': continue
                self._commit(chunk, response, commit)
                outstanding.remove(chunk); progressed = True
            if outstanding and not progressed: self.sleep(self.poll)

    def _body(self, chunk):
        return {'job_id': self.state['billing_job_id'], 'voice': self.config['voice'], 'style': self.config.get('style'),
                'units': [{'id': index, 'text': text} for index, text, _ in chunk], **self.meta}

    def _request(self, chunk):
        waited, renewed = 0, False
        while True:
            check_cancel(self.job_dir)
            try:
                return self.send(self.endpoint, '/v1/tts', self._body(chunk), self.token, self.timeout)
            except genius.GatewayError as error:
                if error.status == 402: genius.pause(self.job_dir, 'CREDIT_LIMIT')
                if error.status in (401, 403): genius.pause(self.job_dir, 'LICENSE_REJECTED')
                if error.status == 409 and error.code == 'JOB_CLOSED' and not renewed:
                    # Idle more than 24 h: units already saved stay; the rest continue as a new gateway job.
                    self.state['billing_job_id'] = str(uuid.uuid4()); atomic_json(self.state_path, self.state); renewed = True
                    continue
                if error.status == 400: raise RuntimeError(f'Voice gateway rejected the request: {error.code}') from None
                if error.code == 'TTS_FAILED':
                    # Counted per chunk across polls; the next request queues it again.
                    first = chunk[0][0]
                    self.failures[first] = self.failures.get(first, 0) + 1
                    if self.failures[first] >= 3: raise RuntimeError('Voice generation failed on the server three times for the same segment') from None
                    continue
                if waited >= self.max_wait: genius.pause(self.job_dir, 'GATEWAY_UNAVAILABLE')
                delay = min(60, 5 * 2 ** min(4, waited // 30)); self.sleep(delay); waited += delay

    def _commit(self, chunk, response, commit):
        import numpy as np
        import soundfile as sf
        returned = {unit['id']: unit for unit in response.get('units', []) if isinstance(unit, dict)}
        if set(returned) != {index for index, _, _ in chunk}: raise RuntimeError('Voice gateway returned a different unit set')
        for item in chunk:
            unit = returned[item[0]]
            pcm, rate = sf.read(io.BytesIO(base64.b64decode(unit['flac'])), dtype='int16')
            pcm = np.asarray(pcm, dtype='<i2').reshape(-1)
            if rate != SAMPLE_RATE or len(pcm) != unit['frames'] or hashlib.sha256(pcm.tobytes()).hexdigest() != unit['sha256']:
                raise RuntimeError('Voice audio failed verification; it will be downloaded again on retry')
            sf.write(str(item[2]), pcm, SAMPLE_RATE, format='WAV', subtype='PCM_16')
            commit(item)
            self.done_units += 1
        self.state['billed'][str(response.get('chunk_no'))] = int(response.get('billed_chars') or 0)
        atomic_json(self.state_path, self.state)
        atomic_json(self.job_dir/'working'/'tts-remote-progress.json',
                    {'units_done': self.done_units, 'billed_chars': sum(self.state['billed'].values())})

    def _finish(self, status):
        try: self.send(self.endpoint, f"/v1/jobs/{self.state['billing_job_id']}/finish", {'status': status}, self.token, 60)
        except Exception: pass  # The gateway marks idle jobs ABANDONED; billing already happened per chunk.

    def finished(self):
        self._finish('COMPLETED')

    def close(self):
        pass
