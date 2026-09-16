// Runs index.html's <script> in Node with a tolerant DOM stub, so the browser
// implementation can be compared with planto2sw.py on the same CSV.
// usage: node tests/harness.mjs index.html cases.csv app-data.json [existing.txt]
// stdout: {"rows":[...], "logs":[...]}
import fs from 'node:fs';
const [,, htmlPath, csvPath, appDataPath, existingPath] = process.argv;
const html = fs.readFileSync(htmlPath, 'utf8');
let js = html.slice(html.indexOf('<script>') + 8, html.lastIndexOf('</script>'));
// DOM stub: every element read returns an empty-ish value, every write is accepted.
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
js = js.replace(/^\s*(S\.sw=emptySw\(\); fillSettings\(\);|restoreAppData\(\);)\s*$/mg, '');   // skip page init
new Function(js + ';globalThis.__api={S,parseCSV,toRows,detId,parseCustomRules,buildCardMap,buildAll,buildLogs,rowRate,loadExisting,fillSettings,emptySw,setAppData,DEFAULT_CARD_MAP,EXCLUDE,USER_RULES,PREFIX_RULES,ONLINE_HINTS,ALIAS_STOP,FALLBACK,CHANNEL_RULES,GURU_MONTHLY_TOP_CARD};')();
const { S, parseCSV, toRows, detId, parseCustomRules, buildCardMap, buildAll, buildLogs, rowRate, loadExisting, fillSettings, emptySw, setAppData,
        DEFAULT_CARD_MAP, EXCLUDE, USER_RULES, PREFIX_RULES, ONLINE_HINTS, ALIAS_STOP, FALLBACK, CHANNEL_RULES, GURU_MONTHLY_TOP_CARD } = globalThis.__api;
// the page has no embedded snapshot and only fetches when the user clicks 一鍵攞最新 (never done here): supply app-data the same way the file picker does
setAppData(JSON.parse(fs.readFileSync(appDataPath, 'utf8')), appDataPath);
S.sw = emptySw(); fillSettings();
if (existingPath) loadExisting(fs.readFileSync(existingPath, 'utf8'));
S.settings = {};   // the stubbed step-2 form is empty; in the browser it mirrors the snapshot, so "no edits" = snapshot values
S.rows = toRows(parseCSV(fs.readFileSync(csvPath, 'utf8')));
for (const r of S.rows) r.id = await detId(r.acct, r.date, r.amtRaw, r.cur, r.desc);   // as the #csvFile handler does
if (process.env.P2S_RULES) S.customRules = parseCustomRules(process.env.P2S_RULES).rules;   // optional: rules as typed in the step-3 box
buildCardMap(); buildAll();
const logs = await buildLogs();
const rows = S.rows.map(r => ({
  row: r.row, status: r.status, cardId: r.cardId, scenario: r.scenario, layer: r.layer, detail: r.detail,
  rate: r.status === 'ok' ? rowRate(r)[0] : null, rateSrc: r.status === 'ok' ? rowRate(r)[1] : null,
}));
// constants that must mirror config.example.json (compare.py checks them)
const mirror = {
  card_map: Object.fromEntries(DEFAULT_CARD_MAP.map(([re, id]) => [re.source, id])),
  exclude_patterns: EXCLUDE.map(re => re.source),
  merchant_rules: Object.fromEntries(USER_RULES.map(([re, sc]) => [re.source, sc])),
  prefix_rules: Object.fromEntries(PREFIX_RULES.map(([re, sc]) => [re.source, sc])),
  online_hints: ONLINE_HINTS, merchant_alias_stop: ALIAS_STOP, scenario_fallback: FALLBACK, guru_monthly_top_card: GURU_MONTHLY_TOP_CARD,
  channel_rules: CHANNEL_RULES.map(c => ({ cardId: c.cardId, scenario: c.scenario, pattern: c.re.source, rate: c.rate, note: c.note })),
};
process.stdout.write(JSON.stringify({ rows, logs, mirror }));
