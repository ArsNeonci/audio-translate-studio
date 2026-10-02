const fs=require('node:fs'),assert=require('node:assert/strict'),ts=require('typescript');
const code=ts.transpileModule(fs.readFileSync('lib/format.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const moduleFixture={exports:{}};new Function('module','exports',code)(moduleFixture,moduleFixture.exports);
const {percent,elapsed,runNumber}=moduleFixture.exports;
assert.equal(percent(7.16),'7.16%');assert.equal(percent(100),'100.00%');assert.equal(percent(0),'0.00%');assert.equal(percent(48.2134),'48.21%');assert.equal(percent(null),'—');assert.equal(percent(101),'100.00%');
assert.equal(elapsed(6138000),'01:42:18');assert.equal(runNumber(125),'000125');assert.equal(runNumber(1000000),'1000000');
console.log('UI FORMAT OK: 9 assertions');
