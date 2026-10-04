const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const cache = new Map();
function load(file) {
  file = path.resolve(file);
  if (cache.has(file)) return cache.get(file);
  const scope = { exports: {}, require: name => load(name.startsWith('@/') ? path.resolve(name.slice(2) + '.ts') : path.resolve(path.dirname(file), name + '.ts')) };
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, scope);
  cache.set(file, scope.exports);
  return scope.exports;
}
const { translations } = load('lib/i18n/i18n.ts');
const { uiText, translateUi, translateVoiceDescription } = load('lib/i18n/ui-text.ts');
const { localizeGuide } = load('lib/i18n/localized-guides.ts');
const placeholders = text => [...text.matchAll(/\{(\w+)\}/g)].map(match => match[1]).sort();
let checked = 0;
function compare(left, right, prefix='') {
  assert.deepEqual(Object.keys(left).sort(), Object.keys(right).sort(), `Translation keys differ at ${prefix}`);
  for (const key of Object.keys(left)) {
    if (typeof left[key] === 'object') compare(left[key], right[key], `${prefix}.${key}`);
    else { assert.ok(left[key].trim() && right[key].trim(), `Empty translation ${prefix}.${key}`); assert.deepEqual(placeholders(left[key]), placeholders(right[key]), `Placeholder mismatch ${prefix}.${key}`); checked++; }
  }
}
compare(translations.vi, translations.en);
for (const [key, [vi,en]] of Object.entries(uiText)) {
  assert.ok(vi && en, `Missing UI translation: ${key}`);
  assert.deepEqual(placeholders(vi), placeholders(en), `Placeholder mismatch: ${key}`);
}
for (const lang of ['vi','en']) {
  for (const name of ['Audio', 'Studio', 'Audio Studio', 'Ars Neonci', 'YouTube', 'Google Chrome', 'Trúc Ly', 'Thiện Minh', 'Qwen3', 'VieNeu-TTS', 'my-input.txt']) assert.equal(translateUi(name,lang), name);
  assert.ok(translateUi('voiceSample',lang,{name:'Trúc Ly'}).includes('Trúc Ly'));
  assert.ok(translateUi('abortConfirm',lang,{number:'000123'}).includes('Audio'));
}
assert.equal(translateVoiceDescription('Nam · Nam · Phong cách tự nhiên','en'), 'Male · Southern · Natural style');
assert.equal(translateVoiceDescription('Nữ · Bắc · Phong cách tin tức','en'), 'Female · Northern · News style');
assert.equal(translateUi('RAM trống 2.00 GB; cần dự phòng 8.00 GB cho workflow mới và các workflow chưa nạp model (đã giữ 4.00 GB cho hệ thống).','en'), '2.00 GB RAM available; 8.00 GB is required for the new workflow and workflows with unloaded models (4.00 GB reserved for the system).');
const commands = ['ffmpeg -version'];
const guide = localizeGuide({cause:'test',config:'test',checks_and_fixes:[],commands},'FFMPEG_MISSING','en');
assert.equal(guide.commands, commands);
assert.equal(guide.cause, 'FFmpeg/ffprobe is not on PATH.');

const allowedText = new Set(['Audio Studio', 'Tiếng Việt', 'English', 'YouTube URL', 'JSONL ↓']);
function scan(directory) {
  for (const item of fs.readdirSync(directory, {withFileTypes:true})) {
    const file=path.join(directory,item.name);
    if(item.isDirectory()) {if(item.name!=='api')scan(file); continue;}
    if(!file.endsWith('.tsx'))continue;
    const source=ts.createSourceFile(file,fs.readFileSync(file,'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
    function walk(node) {
      if(ts.isJsxText(node)) {
        const text=node.text.trim();
        if(/[\p{L}]/u.test(text))assert.ok(allowedText.has(text), `Unlocalized JSX text in ${file}: ${text}`);
      }
      ts.forEachChild(node,walk);
    }
    walk(source);
  }
}
scan('app');
scan('components');
// Render real components with inert dependencies; no jobs, uploads or deletes.
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
function component(file, language, modules = new Map()) {
  file = path.resolve(file);
  if (modules.has(file)) return modules.get(file);
  const scope = {exports: {}, require: name => {
    if (name === '@/lib/i18n/language-context') return {useLanguage: () => ({language, t: translations[language], tr: (text, values) => translateUi(text,language,values)})};
    if (name.endsWith('license-status')) return {useLicense: () => ({status:'ACTIVE',allowed:true})};
    if (name === 'next/link') return {__esModule:true,default:props => React.createElement('a',props,props.children)};
    if (name.startsWith('@/') || name.startsWith('.')) {
      const base = name.startsWith('@/') ? path.resolve(name.slice(2)) : path.resolve(path.dirname(file),name);
      return component(fs.existsSync(base+'.tsx') ? base+'.tsx' : base+'.ts',language,modules);
    }
    return require(name);
  }};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,scope);
  modules.set(file,scope.exports);
  return scope.exports;
}
const fixture = {id:'00000000-0000-0000-0000-000000000123',workflow_no:123,name:'Trúc Ly Audio Studio',status:'PAUSED',progress:25,duration_ms:0,created_at:'2026-10-03T00:00:00Z',error:null,steps:{TRANSCRIPTION:{state:'PENDING',attempt:0,retry_count:0}}};
for (const language of ['vi','en']) {
  const Detail = component('components/workflow/job-detail.tsx',language).default;
  const detail = renderToStaticMarkup(React.createElement(Detail,{job:fixture,onClose:()=>{}}));
  assert.ok(detail.includes('Trúc Ly Audio Studio'), 'Job name changed');
  assert.ok(detail.includes(language==='vi'?'CHI TIẾT TÁC VỤ':'JOB DETAIL'));
  assert.ok(detail.includes(language==='vi'?'Bản chép tiếng Trung':'Chinese Transcript'));
  assert.ok(detail.includes(language==='vi'?'Tổng tiến độ:':'Overall:'));
  assert.ok(detail.includes(language==='vi'?'Chưa bắt đầu':'Pending'));
  const Actions = component('components/workflow/workflow-actions.tsx',language).default;
  const actions = renderToStaticMarkup(React.createElement(Actions,{job:fixture,onChanged:async()=>{},onNotice:()=>{}}));
  assert.ok(actions.includes(language==='vi'?'Tiếp tục giai đoạn':'Resume stage'));
  assert.ok(actions.includes(language==='vi'?'Hủy và xóa quy trình':'Abort and delete workflow'));
  const Pipeline = component('components/workflow/pipeline-status.tsx',language).default;
  const translationJob = {...fixture,status:'TRANSLATING',tool_steps:['TRANSLATION'],steps:{TRANSLATION:{state:'RUNNING',attempt:1,retry_count:0,progress:0}}};
  for (const [state,vi,en] of [['MODEL_LOADING','Đang nạp mô hình','Loading model'],['WAITING_MEMORY','Chờ RAM','Waiting for RAM']]) {
    const output=renderToStaticMarkup(React.createElement(Pipeline,{job:{...translationJob,translation_runtime:{state,threads:6,slots:1,available_gib:3,required_available_gib:3.5,measurements:[]}}}));
    assert.ok(output.includes(language==='vi'?vi:en));
    assert.ok(output.includes('indeterminate'), 'Preparation must not look like frozen 0% translation');
  }
  const running=renderToStaticMarkup(React.createElement(Pipeline,{job:{...translationJob,steps:{TRANSLATION:{...translationJob.steps.TRANSLATION,progress:25}},translation_runtime:{state:'RUNNING',mode:'resource',threads:4,slots:2}}}));
  assert.ok(running.includes('25%'));
  assert.ok(running.includes(language==='vi'?'2 lượt dịch song song':'2 parallel translations'));
  assert.ok(!running.includes('indeterminate'));
  assert.ok(running.includes('3.5 GiB'));
  assert.ok(running.includes('85%/85%'));
  const completed=renderToStaticMarkup(React.createElement(Pipeline,{job:{...translationJob,status:'COMPLETED',steps:{TRANSLATION:{state:'COMPLETED',progress:100}},translation_runtime:{state:'CALIBRATING'}}}));
  assert.ok(!completed.includes(language==='vi'?'Đang hiệu chuẩn':'Calibrating'), 'Historical telemetry must not override completed state');
}
console.log(`Localization checks passed: ${checked} translation keys, ${Object.keys(uiText).length} UI entries, placeholders, preserved names, descriptions, diagnostic templates and frontend text coverage.`);
