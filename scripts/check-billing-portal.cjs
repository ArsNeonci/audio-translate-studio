// Checks lib/server/billing-portal.ts without the native core or a gateway: the licence service, the lease module and the
// network are replaced by scripted fakes. Run: node scripts/check-billing-portal.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'billing-portal-'));
const commands = [];           // every licence command the module sent
let credential = { status: 'ACTIVE', token: 'LIC.TOKEN' };
let sequence = 4;
const installed = [];
const gatewayCalls = [];       // {method, url, headers, body}
let routes = {};               // 'METHOD /path' -> {status, body} | function
let leaseRenewals = 0;
const fakes = {
  '@/lib/server/license': { licenseCommand: async (payload) => {
    commands.push(payload.action);
    if (payload.action === 'credential') return { http_status: credential.status === 'ACTIVE' ? 200 : 403, ...credential };
    if (payload.action === 'status') return { http_status: 200, status: 'ACTIVE', sequence };
    if (payload.action === 'renew') { if (payload.token.startsWith('BAD')) return { http_status: 400, status: 'INVALID' }; installed.push(payload.token); sequence += 1; return { http_status: 200, status: 'ACTIVE', sequence }; }
    return { http_status: 404, status: 'INVALID' };
  } },
  '@/lib/server/lease': { gatewayEndpoint: async () => 'https://api.test', ensureLease: async () => { leaseRenewals += 1; } },
  '@/lib/server/python': { dataRoot },
};
global.fetch = async (url, init) => {
  const key = `${init.method} ${new URL(url).pathname}`;
  gatewayCalls.push({ method: init.method, url, headers: init.headers, body: init.body && JSON.parse(init.body) });
  const route = routes[key];
  if (!route) throw new Error('offline');
  const { status, body } = typeof route === 'function' ? route(url) : route;
  return { status, json: async () => body };
};
const cache = new Map();
function load(file) {
  file = path.resolve(file);
  if (cache.has(file)) return cache.get(file);
  const scope = { exports: {}, process, URL, Object, Buffer, AbortSignal, setTimeout, Date, JSON, Promise, Error, encodeURIComponent, Array, fetch: global.fetch,
    require: (name) => (fakes[name] ?? (name.startsWith('node:') ? require(name) : load(path.resolve(name.slice(2) + '.ts')))) };
  scope.globalThis = scope;
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText, scope);
  cache.set(file, scope.exports);
  return scope.exports;
}
const portal = load('lib/server/billing-portal.ts');
const reset = () => { commands.length = 0; gatewayCalls.length = 0; installed.length = 0; routes = {}; };

(async () => {
  // A valid licence: a one-time link, the licence token only in the Authorization header, and a User-Agent Cloudflare accepts.
  routes = { 'POST /v1/billing/session': { status: 200, body: { url: 'https://billing.test/s/abc?next=license', customer_code: 'ABCDE-FGHJK', expires_in: 1800 } } };
  let link = await portal.openBilling('license');
  assert.deepEqual({ ...link }, { url: 'https://billing.test/s/abc?next=license', mode: 'app' });
  assert.equal(gatewayCalls[0].headers.Authorization, 'License LIC.TOKEN');
  assert.match(gatewayCalls[0].headers['User-Agent'], /audio-translate-app/);
  assert.deepEqual({ ...gatewayCalls[0].body }, { next: 'license' });
  await new Promise((r) => setTimeout(r, 50));
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dataRoot, 'settings', 'billing.json'), 'utf8')).code, 'ABCDE-FGHJK'); // remembered for the day it expires
  assert.equal(JSON.parse(fs.readFileSync(path.join(dataRoot, 'settings', 'billing.json'), 'utf8')).portal_url, 'https://billing.test');

  // An expired licence: the core releases no token, so the remembered Customer Code opens the portal with the code filled in.
  reset(); credential = { status: 'EXPIRED' };
  link = await portal.openBilling('debt');
  assert.deepEqual({ ...link }, { url: 'https://billing.test/?code=ABCDE-FGHJK', mode: 'code' });
  assert.equal(gatewayCalls.length, 0);

  // The gateway refusing a revoked licence is reported, not hidden behind the fallback.
  reset(); credential = { status: 'ACTIVE', token: 'LIC.TOKEN' };
  routes = { 'POST /v1/billing/session': { status: 403, body: { error: 'LICENSE_REVOKED' } } };
  await assert.rejects(portal.openBilling('license'), /LICENSE_REVOKED/);

  // Offline with a valid licence: fall back to the remembered code. Nothing remembered: a clear error.
  reset(); routes = {};
  assert.equal((await portal.openBilling('license')).mode, 'code');
  fs.rmSync(path.join(dataRoot, 'settings', 'billing.json'));
  await assert.rejects(portal.openBilling('license'), /GATEWAY_UNREACHABLE/);
  credential = { status: 'EXPIRED' };
  await assert.rejects(portal.openBilling('license'), /BILLING_CODE_UNKNOWN/);

  // Renewals: installed in order, using the sequence the core already has; a bad token stops the chain.
  reset(); credential = { status: 'ACTIVE', token: 'LIC.TOKEN' }; sequence = 4;
  routes = { 'GET /v1/license/renewals': { status: 200, body: { renewals: [{ sequence: 6, token: 'T6' }, { sequence: 5, token: 'T5' }] } } };
  assert.equal(await portal.fetchRenewals(true), 2);
  assert.deepEqual(installed, ['T5', 'T6']);
  assert.match(gatewayCalls[0].url, /after=4$/);
  assert.equal(leaseRenewals, 1); // a fresh licence gets its lease at once
  reset(); sequence = 6;
  routes = { 'GET /v1/license/renewals': { status: 200, body: { renewals: [{ sequence: 7, token: 'BAD7' }, { sequence: 8, token: 'T8' }] } } };
  assert.equal(await portal.fetchRenewals(true), 0);
  assert.deepEqual(installed, []);
  // Throttled: a second call right after does not hit the gateway again (once a minute, every 4 s only after the portal was opened).
  reset(); routes = { 'GET /v1/license/renewals': { status: 200, body: { renewals: [] } } };
  assert.equal(await portal.fetchRenewals(), 0);
  assert.equal(gatewayCalls.length, 0);
  // An expired licence collects nothing in the background: its token comes from the order page.
  reset(); credential = { status: 'EXPIRED' };
  assert.equal(await portal.fetchRenewals(true), 0);
  assert.equal(gatewayCalls.length, 0);

  // The Customer Code shown on the licence page is read once and cached.
  fs.rmSync(path.join(dataRoot, 'settings', 'billing.json'), { force: true });
  reset(); credential = { status: 'ACTIVE', token: 'LIC.TOKEN' };
  routes = { 'GET /v1/billing/code': { status: 200, body: { code: 'QQQQQ-WWWWW', portal_url: 'https://billing.test' } } };
  assert.deepEqual({ ...(await portal.billingInfo()) }, { code: 'QQQQQ-WWWWW', portal_url: 'https://billing.test', enabled: true });
  assert.deepEqual({ ...(await portal.billingInfo()) }, { code: 'QQQQQ-WWWWW', portal_url: 'https://billing.test', enabled: true });
  assert.equal(gatewayCalls.length, 1);
  fs.rmSync(dataRoot, { recursive: true, force: true });
  console.log('Billing portal checks passed: one-time link, Customer Code fallback, refusal reporting, ordered renewals, throttling, code cache.');
})().catch((error) => { console.error(error); process.exit(1); });
