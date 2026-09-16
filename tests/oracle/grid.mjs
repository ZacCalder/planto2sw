// Ask the rate engine in the cached, frozen SwipeWhich 2.0.4 bundle (module 455 `FC`) for rates over a grid of
// cards x scenarios x currencies x amounts x knob variants, and write them as JSON.
// usage: node tests/oracle/grid.mjs <chunkDir> <app-data.json> <out.json>
import fs from 'node:fs';
import { loadSwipeWhich } from './runtime.mjs';
const [,, chunkDir, appDataPath, outPath] = process.argv;
const { req } = loadSwipeWhich(chunkDir, appDataPath);
const eng = req(455), cards = req(6822); req(6181);     // 6181 = hydrate: applies app-data.json to the data tables
const SC = ['local','dining','onlineHKD','onlineFX','physicalFX','supermarket','transport','fuel','mobilePay','octopus','octopusManual','travelCN','travelTW','travelJKSTA','flightDirect','flightOTA','hotelDirect','hotelOTA','medical','fitness','pet','cinema','rent','manual'];
const regsOn = { aeExplorerReg:true, aeChargeReg:true, everyMileReg:true, pulseReg:true, mmpowerReg:true, travelPlusReg:true, dbsEminentReg:true, beaWorldReg:true, ccbEyeReg:true, wewaQ3Reg:true, scSmartTier:'mid', promoRegs:{} };
const regsOff = Object.fromEntries(Object.entries(regsOn).map(([k, v]) => [k, typeof v === 'boolean' ? false : v]));
const vs0 = { world:0, savour:0, home:0, lifestyle:0, shopping:0 };
const base = { vs:vs0, guru:'none', moxTier:false, dbsLfFx:'none', wewaCat:'none', bocMs:'none', bocMf:'none', regs:regsOn, guruRemainingRc:null, emFxQuarterSpent:null, hsbcCat:null };
const variants = [base,
  { ...base, regs:regsOff }, { ...base, regs:{ ...regsOn, scSmartTier:'low' } }, { ...base, regs:{ ...regsOn, scSmartTier:'high' } },
  { ...base, vs:{ ...vs0, world:5 } }, { ...base, vs:{ ...vs0, savour:2, home:3 } }, { ...base, vs:'world' }, { ...base, vs:['savour', 'shopping'] },
  { ...base, guru:'L1' }, { ...base, guru:'L3' }, { ...base, guru:'L3', guruRemainingRc:0 }, { ...base, guru:'L3', guruRemainingRc:30 }, { ...base, guru:'L2', guruRemainingRc:1000, vs:{ ...vs0, world:5 } },
  { ...base, emFxQuarterSpent:14500 }, { ...base, emFxQuarterSpent:99999 }, { ...base, emFxQuarterSpent:14500, guru:'L3', guruRemainingRc:100 },
  { ...base, hsbcCat:'savour' }, { ...base, hsbcCat:'world', vs:{ ...vs0, world:2 } },
  { ...base, moxTier:true }, { ...base, dbsLfFx:'fx' }, { ...base, dbsLfFx:'travel' },
  { ...base, wewaCat:'mobilePay' }, { ...base, wewaCat:{ ds_wewa_vs:'mobilePay' } }, { ...base, wewaCat:'overseas', regs:{ ...regsOn, wewaQ3Reg:false } },
];
const cardIn = cards.gv.map(c => ({ id:c.id, issuer:c.issuer, net:(cards.i[c.id] || {}).net || null, cashback:c.cashback, otaFromFXcb:c.otaFromFXcb || null }));
const rows = [];
for (const c of cards.gv) for (const sc of SC) for (const cur of ['HKD', 'CNY']) for (const amt of [500, 20000]) for (let vi = 0; vi < variants.length; vi++)
  rows.push([c.id, sc, cur, amt, vi, eng.FC(c, sc, amt, cur, variants[vi]).rate]);
fs.writeFileSync(outPath, JSON.stringify({ generatedAt: req(6181).I, variants, cards: cardIn, rows }));
console.log(`grid rows ${rows.length} (app-data ${req(6181).I})`);
