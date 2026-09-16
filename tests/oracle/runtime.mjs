// Minimal webpack runtime: loads every SwipeWhich chunk, hydrates the data tables with app-data.json
// (via the app's own hydrate module 6181, which runs on require when it thinks it is on Capacitor),
// and exposes the rate engine module 455 + data modules.
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';

export function loadSwipeWhich(chunkDir, appDataPath) {
  const modules = {};
  const cache = {};
  const appData = fs.readFileSync(appDataPath, 'utf8');
  // --- browser stubs -------------------------------------------------------
  const ls = { getItem: k => (k === 'sw_appdata_v2' ? appData : null), setItem() {}, removeItem() {} };
  globalThis.self = globalThis; globalThis.window = globalThis;
  globalThis.localStorage = ls; globalThis.sessionStorage = ls;
  globalThis.location = { search: '', href: 'https://www.swipewhich.com/' };

  globalThis.document = { cookie: '', createElement: () => ({ setAttribute() {}, style: {} }), head: { appendChild() {} }, documentElement: {}, getElementsByTagName: () => [] };
  globalThis.Capacitor = { isNativePlatform: () => true };
  globalThis.webpackChunk_N_E = { push(arg) { Object.assign(modules, arg[1]); } };
  for (const f of fs.readdirSync(chunkDir)) {
    if (!f.endsWith('.js') || f.startsWith('webpack-') || f.startsWith('main-app') || f.startsWith('polyfills')) continue;
    const src = fs.readFileSync(path.join(chunkDir, f), 'utf8');
    if (!src.includes('webpackChunk_N_E')) continue;            // skip my extracted fragments
    vm.runInThisContext(src, { filename: f });
  }
  // --- require --------------------------------------------------------------
  function req(id) {
    if (cache[id]) return cache[id].exports;
    if (!modules[id]) throw new Error('module ' + id + ' not found');
    const m = (cache[id] = { exports: {} });
    modules[id].call(m.exports, m, m.exports, req);
    return m.exports;
  }
  req.m = modules;
  req.d = (e, t) => { for (const k in t) if (Object.hasOwn(t, k) && !Object.hasOwn(e, k)) Object.defineProperty(e, k, { enumerable: true, get: t[k] }); };
  req.o = (e, t) => Object.prototype.hasOwnProperty.call(e, t);
  req.r = e => { Object.defineProperty(e, Symbol.toStringTag, { value: 'Module' }); Object.defineProperty(e, '__esModule', { value: true }); };
  req.n = e => { const g = e && e.__esModule ? () => e.default : () => e; req.d(g, { a: g }); return g; };
  req.g = globalThis; req.p = '/_next/';
  req.e = () => Promise.resolve();
  req.t = (e, r) => { if (1 & r) e = req(e); return e; };
  req.u = () => ''; req.miniCssF = () => {};
  return { req, modules };
}
