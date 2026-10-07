// Checks lib/server/model-download.ts with a real local HTTP server standing in for Cloud Storage and a scripted gateway.
// The pinned size and hash are swapped for a small test file, so the 4.6 GB file is not needed. Run: node scripts/check-model-download.cjs
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const work = fs.mkdtempSync(path.join(os.tmpdir(), 'model-download-'));
const payload = crypto.randomBytes(3 * 1024 * 1024 + 123);
const good = crypto.createHash('sha256').update(payload).digest('hex');
const target = path.join(work, 'models', 'Hy-MT2-7B-Q4_K_M', 'model.gguf');
process.env.HY_MT_MODEL_PATH = target;
let credential = { status: 'ACTIVE', token: 'LIC.TOKEN' };
let gateway = { status: 200, body: {} };
let urlCalls = 0;
let store = { served: payload, cutAt: 0, status: 0, ranges: [] };

const server = http.createServer((request, response) => {
  const range = /bytes=(\d+)-/.exec(request.headers.range || '');
  const start = range ? Number(range[1]) : 0;
  store.ranges.push(start);
  if (store.status) { response.writeHead(store.status); return response.end(); }
  const body = store.served.subarray(start);
  response.writeHead(range ? 206 : 200, { 'Content-Length': body.length });
  if (store.slow) { // 256 KiB every 100 ms, so the speed and time-left readings have something to measure
    let at = 0;
    const timer = setInterval(() => { response.write(body.subarray(at, at + 262144)); at += 262144; if (at >= body.length) { clearInterval(timer); response.end(); } }, 100);
    return;
  }
  if (store.cutAt && !range) { response.write(body.subarray(0, store.cutAt)); return setTimeout(() => request.socket.destroy(), 20); }
  response.end(body);
});

const fakes = {
  '@/lib/server/license': { licenseCommand: async () => ({ http_status: credential.status === 'ACTIVE' ? 200 : 403, ...credential }) },
  '@/lib/server/lease': { gatewayEndpoint: async () => 'https://api.test' },
};
const realFetch = global.fetch;
function load(file, patch) {
  let source = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  if (patch) source = patch(source);
  const scope = {
    exports: {}, process, URL, Object, Buffer, AbortSignal, setTimeout, Date, JSON, Promise, Error, Math, Number, String, Array, RegExp, Map, console,
    fetch: (url, init) => (String(url).startsWith('https://api.test') ? gatewayFetch(url, init) : realFetch(url, init)),
    require: (name) => fakes[name] ?? require(name),
  };
  scope.globalThis = scope;
  vm.runInNewContext(source, scope);
  return scope.exports;
}
async function gatewayFetch(url, init) {
  urlCalls += 1;
  assert.equal(new URL(url).pathname, '/v1/model/url');
  assert.equal(init.headers.Authorization, 'License LIC.TOKEN');
  assert.deepEqual({ ...JSON.parse(init.body) }, { model: 'hy-mt2-7b-q4km' });
  const body = gateway.status === 200 ? { url: `http://127.0.0.1:${server.address().port}/model` } : gateway.body;
  return { ok: gateway.status === 200, status: gateway.status, json: async () => body };
}
const fresh = () => load('lib/server/model-download.ts', (s) => s
  .replace('size: 4624648896', `size: ${payload.length}`)
  .replace(/sha256: "[0-9a-f]{64}"/, `sha256: "${good}"`)
  .replace('3000 * (attempt + 1)', '5')); // retry pause shortened for the test
async function settle(m) {
  for (let i = 0; i < 400; i++) {
    await new Promise((r) => setTimeout(r, 25));
    const state = await m.modelState();
    if (!['downloading', 'verifying'].includes(state.phase)) return state;
  }
  throw new Error('timeout');
}
const clean = () => fs.rmSync(path.join(work, 'models'), { recursive: true, force: true });

server.listen(0, '127.0.0.1', async () => {
  try {
    let m = fresh();
    assert.equal((await m.modelState()).phase, 'missing');

    // A normal download: a link was requested with the licence, the file is verified and then reported ready.
    await m.startModelDownload();
    assert.equal((await settle(m)).phase, 'ready');
    assert.equal(urlCalls, 1);
    assert.equal(fs.readFileSync(target).equals(payload), true);
    assert.equal(fs.existsSync(`${target}.part`), false);
    // Ready survives a restart (a new module instance) without hashing again, and a second start does nothing.
    m = fresh();
    assert.equal((await m.modelState()).phase, 'ready');
    assert.equal((await m.startModelDownload()).phase, 'ready');
    assert.equal(urlCalls, 1);
    // The file changed on disk: the marker no longer matches, so it is not trusted.
    fs.appendFileSync(target, 'x');
    m = fresh();
    assert.equal((await m.modelState()).phase, 'missing');

    // The connection drops half way: the download resumes with a Range request instead of starting over.
    clean(); store = { served: payload, cutAt: 1024 * 1024, status: 0, ranges: [] }; urlCalls = 0; m = fresh();
    await m.startModelDownload();
    assert.equal((await settle(m)).phase, 'ready');
    assert.ok(store.ranges.length >= 2 && store.ranges[1] > 0, `expected a resumed range, got ${store.ranges}`);
    assert.equal(fs.readFileSync(target).equals(payload), true);

    // The expired link (403) is replaced by a new one.
    clean(); store = { served: payload, cutAt: 0, status: 403, ranges: [] }; urlCalls = 0; m = fresh();
    await m.startModelDownload();
    await new Promise((r) => setTimeout(r, 40));
    store.status = 0;
    assert.equal((await settle(m)).phase, 'ready');
    assert.ok(urlCalls >= 2);

    // Wrong bytes (a tampered object): deleted, never kept, reported.
    clean(); store = { served: Buffer.concat([payload.subarray(0, payload.length - 1), Buffer.from('z')]), cutAt: 0, status: 0, ranges: [] }; m = fresh();
    await m.startModelDownload();
    const bad = await settle(m);
    assert.deepEqual([bad.phase, bad.error], ['error', 'CHECKSUM_MISMATCH']);
    assert.equal(fs.existsSync(target), false);
    assert.equal(fs.existsSync(`${target}.part`), false);

    // The gateway refusing (expired licence, daily limit, disabled, revoked) stops at once with its code.
    for (const [status, code] of [[401, 'EXPIRED'], [429, 'MODEL_LINK_LIMIT'], [503, 'MODEL_DOWNLOAD_DISABLED'], [403, 'LICENSE_REVOKED']]) {
      clean(); store = { served: payload, cutAt: 0, status: 0, ranges: [] }; gateway = { status, body: { error: code } }; urlCalls = 0; m = fresh();
      await m.startModelDownload();
      const refused = await settle(m);
      assert.deepEqual([refused.phase, refused.error, urlCalls], ['error', code, 1]);
    }
    // No valid licence in the core: no request leaves the computer.
    clean(); gateway = { status: 200, body: {} }; credential = { status: 'EXPIRED' }; urlCalls = 0; m = fresh();
    await m.startModelDownload();
    assert.deepEqual([(await settle(m)).error, urlCalls], ['LICENSE_REQUIRED', 0]);

    // A complete file placed by hand (a development checkout) is hashed and accepted without any request.
    clean(); credential = { status: 'ACTIVE', token: 'LIC.TOKEN' };
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, payload);
    urlCalls = 0; m = fresh();
    assert.equal((await m.modelState()).phase, 'missing');
    await m.startModelDownload();
    assert.equal((await settle(m)).phase, 'ready');
    assert.equal(urlCalls, 0);

    // Several clicks at once (a double click, a second window) start exactly one download and ask the gateway for one link.
    clean(); store = { served: payload, cutAt: 0, status: 0, ranges: [] }; urlCalls = 0; m = fresh();
    const answers = await Promise.all([m.startModelDownload(), m.startModelDownload(), m.startModelDownload()]);
    assert.deepEqual(answers.map((a) => a.phase), ['downloading', 'downloading', 'downloading']);
    assert.equal((await settle(m)).phase, 'ready');
    assert.equal(urlCalls, 1);
    assert.equal(store.ranges.length, 1);

    // The state says whether the licence is active (so the page can say "activate first"), and reports speed and time left while downloading.
    clean(); credential = { status: 'UNACTIVATED' }; m = fresh();
    assert.equal((await m.modelState()).license, 'UNACTIVATED');
    credential = { status: 'ACTIVE', token: 'LIC.TOKEN' };
    assert.equal((await m.modelState()).license, 'ACTIVE');
    store = { served: payload, cutAt: 0, status: 0, ranges: [], slow: true }; urlCalls = 0; m = fresh();
    await m.startModelDownload();
    let measured = null;
    for (let i = 0; i < 200 && !measured; i++) { await new Promise((r) => setTimeout(r, 50)); const state = await m.modelState(); if (state.phase === 'downloading' && state.rate && state.eta !== undefined) measured = state; }
    assert.ok(measured && measured.rate > 0 && measured.done > 0 && measured.done <= measured.total, 'expected a speed and time-left reading');
    assert.equal((await settle(m)).phase, 'ready');

    console.log('Model download checks passed: signed link with licence, verified file, resume after a drop, link renewal, tamper rejection, gateway refusals, hand-placed file.');
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  } finally {
    server.close();
    fs.rmSync(work, { recursive: true, force: true });
  }
});
