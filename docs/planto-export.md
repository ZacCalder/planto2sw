# Planto 匯出 CSV

Planto → 設定 → 匯出資料 → 電郵送兩個檔：`transaction_export_<ts>.csv`、`account_export_<ts>.csv`。手動觸發，全量匯出（觀察到約 3 個月窗口），無增量選項。

## transaction_export 欄位
`Merchant Name, Description, Original Description, Category, Amount, Currency, Amount in HKD, User Notes, Bank Name, Account Name, Transaction Date`

- `Account Name` 就是卡名（雙幣卡按幣種拆成兩個賬戶，如 `HSBC Pulse Dual Currency Diamond Card - RMB` / `- HKD`）。HSBC 卡不帶末四位；CNCBI 帶末四位，如 `(-1234; CNY)`。
- `Amount` 原幣；消費為負，還款/退款/回贈為正。`Amount in HKD` 用 Planto 匯率換算。
- `Original Description` 是判斷一切的依據；**不要用 `Category`**（類別經常錯歸；退款配對會被標 Internal_Transfers）。`Merchant Name` 經常為空。
- 沒有：交易唯一 id、入賬日、MCC、逐筆獎分。
- 只有 HSBC RewardCash 餘額（account_export 裡每張 HSBC 卡一個 `RewardCash (-***…)` 賬戶，雙幣卡兩個）和 CNCBI 的 `LAST STATEMENT MONTHLY CASH REBATE` 入賬行，能作校驗，不能作逐筆來源。

## 清洗規則（config.exclude_patterns）
`^PAYMENT\s*-?\s*THANK YOU`、`^PAYMENT REVERSAL`、`FINANCE CHARGE`、`LATE CHARGE`（含 ` REV` 沖回）、`^IBANKING PAYMENT`、`MONTHLY CASH REBATE`、`^INTEREST`。

## 退款
`RETURN:` 前綴、正數。配對規則：同賬戶、原幣金額相同（±0.005）、退款日之前 90 天內（CLI config `refund_window_days`，預設 90）最近一筆消費 → 兩筆一起剔除。配不上的（部分退款）寫成負數記賬（decisions 8），場景按描述照常分類，review 標 `退款未配對 → 負數記賬`。

## 描述前綴 = 支付通道
| 前綴/關鍵字 | 通道 | Pulse 內地 +2% |
|---|---|---|
| `APPLEPAY …` | Apple Pay | 計 |
| `QR UNIONPAY MERCHANT` | 雲閃付掃碼 | 計 |
| `SALES: tencent` / `QR tencent` | 微信支付 | 不計（Guru 照計） |
| `SALES: TAOBAO MERCHANT` / `SALES: ELEME PLATFORM MERCHANT` | 支付寶 | 不計（Guru 照計） |
| `SALES: …` 其他商戶 | 網上卡號支付 | 不計（Guru 照計；場景仍記 travelCN） |

「不計」嘅判斷由 config `channel_rules` 做，目前只有一條：卡 `hsbc_pulse` × 場景 `travelCN`，描述命中 `^SALES:|tencent|wechat|weixin|taobao|eleme|alipay|zhifubao` → `no-bonus`（引擎去掉 Pulse +2% 同最紅自主，Travel Guru 照計）。所以 `QR tencent` 係靠 `tencent` 命中，唔係靠前綴。

## 場景分類（分層，命中即停）
1. 用戶規則：瀏覽器版先試「自訂商戶規則」（存喺 localStorage），再試內置嘅 `merchant_rules`；CLI 只有 config `merchant_rules` 正則
2. 幣種 CNY，而且描述有 `CHN`／`CN` 整詞或者 shenzhen／beijing／shanghai／guangzhou → travelCN
3. app-data `merchantOffers` 整詞匹配，最長嘅 key 先贏。key 包括：中文名、英文名（≥4 字元），同埋喺成個商戶庫只出現一次、唔喺 `merchant_alias_stop`（地名、泛用字）、唔係純數字嘅別名（≥4 字元）。匹配前先剝 `APPLEPAY/SALES:/QR/RETURN:` 前綴 —— 早期版本沒剝，`apple`/`ten`/`store` 等短別名造成大量誤配
4. 其他外幣：命中 `online_hints`（網購線索）→ onlineFX，否則 `fx_default`（physicalFX）
5. HKD 且命中 `prefix_rules`（`^APPLEPAY`／`^QR `）→ mobilePay
6. 兜底 local，在檢查表標記（瀏覽器版「兜底 ⚠」、CLI review.csv `6:fallback`）；⛔ 不寫入 memo，memo 只帶 ` [auto]`
再按 `cardPromos[cardId].cashback` 校驗場景存在，否則按 `scenario_fallback` 回退。
