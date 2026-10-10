// Checks app/api/jobs/route.ts: a main workflow can start from a Chinese audio file instead of a YouTube link.
// The worker is faked; the route's real upload streaming, validation and clean-up run. Run: node scripts/check-workflow-upload.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const work = fs.mkdtempSync(path.join(os.tmpdir(), 'workflow-upload-'));
const calls = [];
let reply = { status: 200, job: { id: 'job-1' } };
let scheduled = 0;
const fakes = {
  '@/lib/server/license': { licenseDenial: async () => null },
  '@/lib/server/worker-client': { pythonCommand: async (script, payload) => {
    calls.push({ script, payload, bytes: payload.upload ? fs.readFileSync(payload.upload) : null });
    return reply;
  } },
  '@/lib/server/jobs': { listJobs: async () => [], schedule: async () => { scheduled += 1; }, validYoutubeUrl: (url) => /^https:\/\/www\.youtube\.com\/watch\?v=/.test(url) },
  '@/lib/server/history': { ensureHistory: async () => {} },
  '@/lib/server/python': { dataRoot: work },
};
function load(file) {
  const source = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  const scope = { exports: {}, process, URL, Object, Buffer, Response, Number, String, Array, RegExp, JSON, Promise, Error, Math, console,
    require: (name) => fakes[name] ?? (name.startsWith('@/') ? load(name.replace('@/', '') + '.ts') : require(name)) };
  scope.globalThis = scope;
  vm.runInNewContext(source, scope);
  return scope.exports;
}
const route = load('app/api/jobs/route.ts');
const post = (query, body, headers) => route.POST(new Request(`http://127.0.0.1/api/jobs${query}`, { method: 'POST', body, headers, duplex: 'half' }));
const leftovers = () => (fs.existsSync(path.join(work, 'uploads')) ? fs.readdirSync(path.join(work, 'uploads')) : []);

(async () => {
  const audio = Buffer.alloc(3 * 1024 * 1024 + 17, 7);

  // A file: streamed to disk whole, sent to the worker as a workflow (not a tool), then removed.
  let response = await post('?name=clip.mp3&voice=v1&style=drama&mode=genius&address=drama&auto=1&queue_only=1', audio, { 'content-type': 'audio/mpeg' });
  assert.equal(response.status, 201);
  assert.deepEqual(await response.json(), { job: { id: 'job-1' } });
  let { script, payload, bytes } = calls.at(-1);
  assert.equal(script, 'manage.py');
  assert.equal(payload.action, 'convert');
  assert.equal(payload.url, '');
  assert.equal(payload.tool, undefined);
  assert.equal(payload.input_name, 'clip.mp3');
  assert.equal(payload.mime, 'audio/mpeg');
  assert.equal(payload.voice, 'v1');
  assert.equal(payload.style, 'drama');
  assert.equal(payload.mode, 'genius');
  assert.equal(payload.address, undefined); // Genius handles forms of address itself
  assert.equal(payload.auto, true);
  assert.equal(payload.queue_only, true);
  assert.ok(bytes.equals(audio));
  assert.deepEqual(leftovers(), []);
  assert.equal(scheduled, 1);

  // Defaults: no queue confirmation, no Auto, Normal mode keeps the address profile.
  response = await post('?name=clip.wav&address=drama', audio, { 'content-type': '' });
  assert.equal(response.status, 201, JSON.stringify(await response.clone().json()));
  ({ payload } = calls.at(-1));
  assert.equal(payload.queue_only, false);
  assert.equal(payload.auto, false);
  assert.equal(payload.address, 'drama');

  // Rejected before the worker is asked.
  const before = calls.length;
  for (const [query, status] of [['?name=a%2Fb.mp3', 400], ['', 400], ['?name=clip.mp3&style=nope', 400], ['?name=clip.mp3&mode=nope', 400]]) {
    response = await post(query, audio, { 'content-type': 'audio/mpeg' });
    assert.equal(response.status, status, query);
  }
  response = await post('?name=clip.mp3', audio, { 'content-type': 'audio/mpeg', 'content-length': String(2 * 1024 ** 3 + 1) }).catch(() => null);
  if (response) assert.equal(response.status, 413);
  assert.equal(calls.length, before);

  // The worker's refusal (bad audio, resource warning) is passed through and the temporary file still goes.
  reply = { status: 409, error: 'Unsupported audio type' };
  response = await post('?name=clip.mp3', audio, { 'content-type': 'audio/mpeg' });
  assert.equal(response.status, 409);
  assert.equal((await response.json()).error, 'Unsupported audio type');
  assert.deepEqual(leftovers(), []);

  // A YouTube link still works as before.
  reply = { status: 200, job: { id: 'job-2' } };
  response = await post('', JSON.stringify({ url: 'https://www.youtube.com/watch?v=abc' }), { 'content-type': 'application/json' });
  assert.equal(response.status, 201);
  ({ payload } = calls.at(-1));
  assert.equal(payload.url, 'https://www.youtube.com/watch?v=abc');
  assert.equal(payload.upload, undefined);
  response = await post('', JSON.stringify({ url: 'not a link' }), { 'content-type': 'application/json' });
  assert.equal(response.status, 400);

  fs.rmSync(work, { recursive: true, force: true });
  console.log('Workflow upload checks passed: file and link sources, validation, worker refusal, temporary file clean-up.');
})().catch((error) => { console.error(error); process.exit(1); });
