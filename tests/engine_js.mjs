// Evaluate index.html's swRate() on an oracle grid; prints a JSON array of rates.
// usage: node tests/engine_js.mjs index.html grid.json
import fs from 'node:fs';
const [,, htmlPath, gridPath] = process.argv;
const html = fs.readFileSync(htmlPath, 'utf8');
let js = html.slice(html.indexOf('<script>') + 8, html.lastIndexOf('</script>'));
// same tolerant DOM stub as harness.mjs so the whole page script can load
const el = () => new Proxy(function () {}, {
  get(_, p) {
    if (p === 'querySelectorAll') return () => [];
    if (p === 'addEventListener' || p === 'click') return () => {};
    if (p === 'checked') return false;
    if (p === 'value') return '';
    if (p === Symbol.toPrimitive) return () => '';
    return el();
  },
  set() { return true; }, apply() { return el(); },
});
globalThis.document = el(); globalThis.window = globalThis;
js = js.replace(/^\s*(S\.sw=emptySw\(\); fillSettings\(\);|restoreAppData\(\);)\s*$/mg, '');
const { swRate } = new Function(js + ';return {swRate};')();
const g = JSON.parse(fs.readFileSync(gridPath, 'utf8'));
const cards = Object.fromEntries(g.cards.map(c => [c.id, c]));
const out = g.rows.map(([id, sc, cur, amt, vi]) => swRate(cards[id], sc, amt, cur, g.variants[vi]));
process.stdout.write(JSON.stringify(out));
