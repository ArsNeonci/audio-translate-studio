const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function compile(file) {
  return ts.transpileModule(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
}

function harness(initial, blocked = false, writeBlocked = false) {
  const stored = new Map(initial ? [['audio-studio-theme', initial]] : []);
  const listeners = new Map();
  const root = { dataset: {}, style: {} };
  let subscription;
  let getClient;
  let getServer;
  let hydration = false;
  const react = {
    createContext: () => ({ Provider: 'provider' }),
    useCallback: (callback) => callback,
    useMemo: (factory) => factory(),
    useEffect: (effect) => effect(),
    useSyncExternalStore: (subscribe, client, server) => {
      subscription = subscribe;
      getClient = client;
      getServer = server;
      return hydration ? server() : client();
    },
  };
  const scope = vm.createContext({
    exports: {},
    document: { documentElement: root },
    localStorage: {
      getItem(key) { if (blocked) throw Error('blocked'); return stored.get(key) ?? null; },
      setItem(key, value) { if (blocked || writeBlocked) throw Error('blocked'); stored.set(key, value); },
    },
    Event: class { constructor(type) { this.type = type; } },
    window: {
      addEventListener: (event, callback) => listeners.set(event, callback),
      removeEventListener: (event) => listeners.delete(event),
      dispatchEvent: (event) => listeners.get(event.type)?.(),
    },
    require: (name) => name === 'react' ? react : name === './theme' ? theme : require(name),
  });
  vm.runInContext(compile('lib/theme.ts'), scope);
  const theme = scope.exports;
  vm.runInContext(theme.themeBootstrap, scope);
  scope.exports = {};
  vm.runInContext(compile('lib/theme-context.tsx'), scope);
  const render = () => scope.exports.ThemeProvider({ children: null }).props.value;
  return { root, stored, listeners, render, theme,
    hydrate() { hydration = true; const result = render(); hydration = false; return result; },
    subscribe: (cb) => subscription(cb),
    server: () => getServer(), client: () => getClient(),
  };
}

for (const [saved, expected] of [[null, 'light'], ['dark', 'dark'], ['light', 'light'], ['invalid', 'light']]) {
  const app = harness(saved);
  assert.equal(app.root.dataset.theme, expected, 'Prepaint saved/default theme');
  app.hydrate();
  assert.equal(app.root.dataset.theme, expected, 'Hydration must not flash Light');
  assert.equal(app.render().theme, expected);
  assert.equal(app.server(), 'light');
  let changes = 0;
  const unsubscribe = app.subscribe(() => changes++);
  app.render().setTheme('dark');
  assert.equal(app.root.style.colorScheme, 'dark');
  assert.equal(app.stored.get('audio-studio-theme'), 'dark');
  assert.equal(app.render().theme, 'dark');
  assert.equal(changes, 1);
  app.stored.set('audio-studio-theme', 'light');
  app.listeners.get('storage')();
  assert.equal(app.render().theme, 'light', 'Sync another tab');
  assert.equal(app.root.dataset.theme, 'light');
  unsubscribe();
  assert.equal(app.listeners.size, 0);
}
for (const args of [[null, true], [null, false, true]]) {
  const app = harness(...args);
  app.render().setTheme('dark');
  assert.equal(app.render().theme, 'dark', 'Storage failure keeps session preference');
  app.render().setTheme('light');
  assert.equal(app.client(), 'light');
}
console.log('Theme checks passed: defaults, prepaint, hydration, persistence, cross-tab sync and blocked storage.');
