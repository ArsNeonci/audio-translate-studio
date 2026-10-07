// Checks lib/server/origin.ts: the launcher's own page must be accepted whichever loopback name the server uses for itself, and every
// other website or local program must still be refused. Run: node scripts/check-origin.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

const scope = { exports: {}, URL };
vm.runInNewContext(ts.transpileModule(fs.readFileSync('lib/server/origin.ts', 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { ...scope, Set, URL, exports: scope.exports });
const { originAllowed } = scope.exports;
const ask = (url, origin) => originAllowed({ url, headers: { get: (name) => (name === 'origin' ? origin : null) } });

// Accepted
assert.equal(ask('http://localhost:3210/api/license', null), true);                       // not a browser page (a script, curl)
assert.equal(ask('http://localhost:3210/api/license', 'http://localhost:3210'), true);   // same origin
assert.equal(ask('http://localhost:3210/api/license', 'http://127.0.0.1:3210'), true);   // the launcher opens 127.0.0.1, the server names itself localhost
assert.equal(ask('http://127.0.0.1:3210/api/license', 'http://localhost:3210'), true);   // and the other way round
assert.equal(ask('http://localhost:3210/api/license', 'http://[::1]:3210'), true);
// Refused
assert.equal(ask('http://localhost:3210/api/license', 'https://evil.example'), false);            // another website
assert.equal(ask('http://localhost:3210/api/license', 'http://localhost:9999'), false);          // another local program (different port)
assert.equal(ask('http://localhost:3210/api/license', 'http://127.0.0.1:4000'), false);
assert.equal(ask('http://localhost:3210/api/license', 'http://localhost.evil.example:3210'), false); // a lookalike name
assert.equal(ask('http://localhost:3210/api/license', 'https://localhost:3210'), false);          // other scheme
assert.equal(ask('http://localhost:3210/api/license', 'null'), false);                            // sandboxed frames send the literal "null"
assert.equal(ask('http://localhost:3210/api/license', 'not a url'), false);
assert.equal(ask('http://app.example:3210/api/license', 'http://127.0.0.1:3210'), false);          // never trust loopback origins for a non-loopback server
console.log('Origin checks passed: launcher page accepted under either loopback name; other sites, ports, schemes and lookalikes refused.');
