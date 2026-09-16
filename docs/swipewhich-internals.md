# 碌邊張 SwipeWhich 內部結構（逆向自 swipewhich.com 前端 bundle，2026-09-11）

> **非官方文件。** 以下內容全部由公開前端 bundle 逆向整理，並非碌邊張官方文檔；本工具同 Planto 及碌邊張都冇任何關聯，亦唔係由佢哋提供支援。

適用：Next.js 版本 2.0.4，`app-data.json` schemaVersion 2，`sw_data._v = 12`。碌邊張之後可能改格式，本文件只對上述版本成立；本項目嘅費率引擎凍結喺 2.0.4（決定 22），唔會跟新版更新。

## 架構

- Next.js PWA（`/_next/static/chunks/app/[lang]/layout-*.js` 承載整個 app，~1.1MB）。iOS/Android 為 Capacitor 套殼，資料格式三端一致。
- 本地優先：用戶資料全部在 `localStorage["sw_data"]`；`sw_lang`、`sw_dark`、`sw_ui` 為介面偏好。
- 登入後可選 Supabase 雲同步，按每條記錄的 `u`（更新時間戳）做衝突解決。本項目唔寫雲端。
- 規則庫公開：`https://www.swipewhich.com/app-data.json`（~850KB，CORS `*`）。

## app-data.json

```
schemaVersion, generatedAt
offers[19]            編輯精選
promoCatalog[13]      銀行推廣活動：id, campaign, cardIds[], sc[], rate, start, end, tiers[], note, regNote…
cardData.cardPromos   {cardId: {cashback:{scenario:rate}, milesPerDollar:{…}, cond:{scenario:條款文字}, otaFromFX…}}  91 張卡
cardData.capAmt       {cardId: {scenario: 上限金額}}
cardData.sharedCap    {cardId: [{scenarios[], capDollars, capType:"amount"|…, label}]}
cardData.minSpend     {cardId: 最低消費 | null}
cardData.milestonePromos {id: {startDate,endDate,tiers[{threshold,reward}],period:"m",rewardMode,minTxn,excludeScenarios}}
cardData.merchantOffers[391] {n:中文名, en, a:"別名 別名", sc:[scenario], offers:[{c:cardId, r:"8% RC", exp, cg:cap群組, ca:cap額}]}
cardData.perks[196]
cardArt
```

24 個場景 id：`local dining onlineHKD onlineFX physicalFX supermarket transport fuel mobilePay octopus octopusManual travelCN travelTW travelJKSTA flightDirect flightOTA hotelDirect hotelOTA medical fitness pet cinema rent manual`。不是每張卡每個場景都有定義，寫 log 前要對 `cardPromos[cardId].cashback` 校驗，缺的回退。

卡 id 與顯示名在 bundle 的 `6822-*.js`（`l("hsbc_pulse","HSBC 銀聯 Pulse","HSBC","both",…)`），已抽到 `docs/swipewhich-cards.json`。第四參數是卡類型 `cashback|miles|both`。

## sw_data（用戶資料）

```
_v: 12
own: [cardId]                      持有的卡
logs: [Log]                        記賬（核心）
recurring, customPromos, customMilestones: []
cardSettings: {cardId: {u, _open, statementDay, dueDay, annualFeeDate, cardExpiry, trackFee, perkUse, suppVs, suppAttrCount, wewaCat, cutDate, cooldownEnd, _noCut, _auto*…}}
—— 全局優惠設定（排行榜頁）——
everyMileReg pulseReg aeExplorerReg aeChargeReg mmpowerReg travelPlusReg dbsEminentReg beaWorldReg ccbEyeReg wewaQ3Reg : bool
vs: {world, savour, home, lifestyle, shopping}   HSBC 最紅自主 5 格分配
guru: "none"|"L1"|"L2"|"L3"        Travel Guru（+3/4/6%，年度上限 $500/$1,200/$2,200 RC）
guruStartDate, guruRcBaseline, guruRcBaselineDate
hsbcDining: "none"|"registered"
scSmartTier: "low"|"mid"|"high"
dbsLfFx: "none"|"fx"|"travel"|"fashion"|"charity"
bocMs, bocMf: "none"|"both";  moxTier: bool;  wewaCategory
promoRegs: {regId: bool}           逐個優惠登記/退出（regId 來自 app-data 每個 offer 的 reg 欄）
milestoneEnroll: {}
mode: "cashback"|"miles", mileValue, enabledExtras, scenarioOrder, quickAmts …
_su, _vsU, _guruU, _wcU, _meU, _woU : 各設定群組的更新時間戳（同步用）
```

### Log

```json
{"u":1789000000000,"id":1789000000000,"day":"2026-09-10","date":"2026-09-10T04:00:00.000Z",
 "memo":"CNY 1,234.56 · 商戶","rate":0.104,"miles":0,"amount":1432.09,"cardId":"hsbc_pulse",
 "rebate":148.93736,"isMiles":false,"cardName":"HSBC 銀聯 Pulse","scenario":"travelCN"}
```

- `id`：app 用 `Date.now()` 或 `Date.now()+Math.random()`；校驗只要求非空（數字或字串都收）。本項目用 9e14 區間的確定性數字，避免撞。
- `amount`：港幣，數字。外幣資訊不另存欄位，寫在 `memo` 開頭，app 用 `/^([A-Z]{3})\s([\d,]+(?:\.\d+)?)(\s\+[\d.]+%)?/` 反解，顯示時用 `rI` 正則剝掉。
- `rate`/`rebate`/`miles`：**儲賬時算好寫死**。追蹤頁彙總函數 `eG` 直接累加儲存的 `rebate`；全代碼唯一改寫已有 log 的 `rate/rebate` 的地方是「編輯該筆並儲存」。登記開關、最紅自主等改動不會回溯。匯入亦一樣：每條 log 照寫入內容原樣儲低，唔會重新分類、唔會重算回贈，顯示時讀 `rebate || 0`。所以本工具要喺匯入前自己分類同計好 `rate`/`rebate`。
- `"(自動) "` memo 前綴是 app 給定期支出物化 log 用的，不要佔用。
- 月份分組 `eU`：`day.slice(0,7)`，自然月。
- 顯示層 `eJ` 會做 cap 調整（`capAdjustSpending`：用儲存嘅 `rebate ÷ spent` 反推有效率，再按 `capAmt`/`sharedCap` 把超上限部分降到 `getPostCapRate`；只改彙總物件，唔改 log，亦唔重算逐筆回贈），和過往月份的最低消費調整（`minSpendAdjustSpending`）。這些是彙總層調整，不改 log。

### 費率引擎（已復刻，2026-09-11）

- 模組位置：chunk `2565-*.js` 的 webpack module **455**（`n.d` 導出 `FC:ed`），`ed(card, scenario, amountHKD, currency, knobs)` → `{rate: L(...), mpd: ep(...)}`；`L` 處理 rent（`W` 集合不計、扣 `j(id)` 租金手續費），`G` 是主體（~8KB，18 張卡有專屬分支，其餘回 `card.cashback[scenario]`）。
- `knobs = {vs, guru, moxTier, dbsLfFx, wewaCat, bocMs, bocMf, regs:{…10 個 *Reg, scSmartTier, promoRegs}, guruRemainingRc, emFxQuarterSpent, hsbcCat}`；`bocMs/bocMf/promoRegs` 不影響 rate（用於排行榜加成 `en`），`hsbcCat` 只在計算器選商戶時傳入，記賬保存路徑 `hX` 傳 null。
- **記賬存的 rate 就是 `hX` 裡 `FC(...).rate`**，沒有別的加成；cap 混合（`eD.Yj`）只在排行榜顯示層。
- `guruRemainingRc` = 頁面 `hz` memo：`guru` 非 none 且有 `guruStartDate` 時，視窗 = 起始日（HK 零時）起 12 個月（JS `setMonth(+12)`）；今天在視窗外 → null（不混合）；已賺 RC = `guruRcBaseline` + Σ（HSBC 發卡的卡、場景 ∈ physicalFX/travelJKSTA/travelTW/travelCN、日期 ∈ [基準日或起始日, 視窗末)）`amount × guru率`；剩餘 = cap − min(已賺, cap)，cap L1/L2/L3 = 500/1200/2200。
- 上面嘅已賺 RC 係將多張卡嘅外幣簽賬合併計。滙豐 Travel Guru 條款第 9c 條寫明，持有多於一張合資格信用卡時簽賬合併計算，所以本項目回放預設同樣合併（config `guru_monthly_top_card` = `false`，決定 19）；設為 `true` 會改用較早嘅另一種讀法（每個自然月只計外幣簽賬最多嗰張卡），只保留作比較。
- `emFxQuarterSpent` = 頁面 `hY` memo：持有 EveryMile 時，Σ 本季（瀏覽器本地時間的自然季）EveryMile 卡 onlineFX/physicalFX/travelJKSTA/travelTW/travelCN 記賬金額；`z()` 每季前 $15,000 2.5%、之後 1%，跨界那筆按比例混合。
- 數據表：卡常量在 module **7379**（`CAP_AMT/SHARED_CAP/MIN_SPEND/POST_CAP_RATE/CAP_PERIOD/RENT_FEE_OVERRIDE/WEWA_Q3_*` 等），卡清單 **6822**（`gv` 陣列，`i` = CARD_META 含 `net` 卡網絡），商戶庫 **8479**（`am`）。app-data.json 由 module **6181**（chunk `5665`）的 hydrate 打進這些表；該模組在 Capacitor 環境下 require 時自動從 `localStorage["sw_appdata_v2"]` 讀取——`tests/oracle/runtime.mjs` 就是靠桩掉 `window.Capacitor` 讓它在 Node 裡跑起來，作為回歸 oracle。
- 本項目移植：index.html `swRate()` / planto2sw.py `sw_rate()`，**凍結喺 2.0.4**（chunk `2565-b2d113f70d98cb47`，決定 22），唔跟新版更新。基本費率同商戶優惠照讀用戶載入嘅 app-data.json；逐卡分支、Travel Guru 年度 RC 上限、EveryMile 季度門檻寫死喺移植入面。**逐卡簽賬上限（`capAmt`／`sharedCap`／`POST_CAP_RATE`）完全冇做**，簽過上限嗰部分嘅回贈會高估。`tests/engine_check.py` 離線用本機已快取嘅 2.0.4 bundle（`.cache/sw`，git-ignored，唔隨 repo 發佈），對 91 卡 × 24 場景 × 2 幣種 × 2 金額 × 24 組 knobs 逐一比對；工具同測試都唔會下載 bundle。

### 其他（2026-09-11 核對補記）

- Log 實際還有 `merchant`（正常記賬固定寫 `""` 或商戶名）、可選 `suppIdx`（附屬卡序號）、`share`（夾單自付額）；現金/八達通記錄 `cardId:"_manual_*"`、`isManual:true`。彙總排除 `isMiles` 與 `isManual`。
- 匯入成功後 app 自己把 `_su/_vsU/_guruU/_wcU/_meU/_woU` 全部重置為 `Date.now()`，工具不必寫。
- 匯入還接受第三種格式：頂層就是 `sw_data` 本體（判定 `own` 是陣列）。
- 數字 id 校驗要求有限且非 0；log id 由 `hJ()` 單調遞增（`max(Date.now(), 上次+1)`）。
- 加載時的靜默規範化：`mileValue` 須在 [0.01, 1]；`enabledExtras` 剔除 `otaHKD/otaFX/ota/billPay/transport/physicalFX/onlineFX` 並強制含 `flight/hotel`；`scenarioOrder` 的 `onlineHKD/onlineFX` 合併成 `online`；舊鍵 `moxSummerReg` 遷入 `milestoneEnroll.mox_cb_2026summer`。
- `promoRegs` 的 regId 來自 `cardData.merchantOffers[].offers[].reg`（目前 `ae_5x_2026`、`hsbc_zdzr_bw`），`promoRegs[reg] === false` 才算退出。
- `wewaCategory` 取值：`none / overseas / mobilePay / travel / entertainment`（以 UI 選項為準）。

已知的 Pulse 內地邏輯（`cardPromos.hsbc_pulse.cond.travelCN`）：基本 0.4%；內地/澳門 +2% 只限 RMB/MOP 經 Reward+/雲閃付掃碼或 Apple/Google/Samsung Pay，需登記，每半年 $80K cap；支付寶/微信/AlipayHK 掃碼、普通拍卡、網上卡號：不計 +2%，也不計最紅自主，只有 0.4%。Apple Pay 全套疊加最高 10.4%（0.4 + 賞世界 5 格 2 + 2 + Guru L3 6）。

## 備份 / 轉移碼

```json
{"v":1,"app":"swipewhich","ts":1789000000000,
 "data":{"sw_data":"<JSON.stringify(sw_data)>","sw_lang":"zh","sw_dark":"auto","sw_ui":"<JSON string>"}}
```
- `data.*` 每個值都是**字串**（localStorage 原樣 dump）；`sw_data` 要二次序列化。
- 轉移碼 = `"SW1." + base64(utf8(整個外殼 JSON))`。
- 匯出：設定 → 匯出備份 → 下載 .json / 複製轉移碼。localStorage 寫入有 debounce，改完設定要等幾秒再匯出。
- 匯入：設定 → 匯入資料 → 貼碼或選 `.json`。**整份覆蓋，不合併**；登入狀態下會 `importOverwrite()` 推上雲端（網頁版是否登入看設定頁頂部：顯示「登入同步／電郵地址」即未登入）。貼碼的 textarea 無 maxlength，數萬字元的碼亦可貼；自動化工具貼不進長文本時用「由檔案匯入」。
- 匯入校驗（`t3/t2/t5`）：`app==="swipewhich"` 且 `data` 是物件；`sw_data` 可 parse 成物件；`own/logs/recurring/customPromos/customMilestones` 若存在必須是陣列；`logs/recurring/customPromos` 每條要有非空 `id`（否則靜默丟棄），`customMilestones` 還要非空 `tiers`；`own` 元素非空。不校驗其他欄位。
- 網頁版與 iOS/Android 各自一份 localStorage；未登入時互不相通。
