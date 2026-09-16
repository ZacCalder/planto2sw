# planto2sw

Turn the credit-card CSV exported by **Planto** into a backup / transfer code that **SwipeWhich** (碌邊張) can
import, so spending is logged automatically instead of by hand. Runs entirely on your own machine.

**[粵語](#粵語) · [简体中文](#简体中文) · [English](#english)**

Unofficial tool. Not affiliated with, endorsed by, or supported by Planto or SwipeWhich.

---

## 粵語

非官方工具，同 Planto 及碌邊張都冇任何關聯，亦唔係由佢哋提供支援。

Planto 匯出嘅信用卡交易 CSV → 碌邊張可以「匯入資料」嘅備份／轉移碼。記帳唔使再逐筆手 mark。
全部喺你部機度行，唔會上傳任何嘢，亦唔會掂你嘅銀行戶口。

**點解工具要自己計回贈**

碌邊張匯入嘅時候，每條記賬係照寫入嘅內容原樣儲低，之後唔會再重新分類，亦唔會重算回贈：app 每一處顯示嘅回贈，都係直接讀記賬入面存咗嘅數（冇就當 0）；唯一會重算嘅情況，係你自己打開某一條記賬再撳儲存。所以本工具一定要喺匯入之前，自己將每筆交易分好類、計好回贈，因此佢有自己一套費率引擎：

- 基本費率同商戶優惠：讀你自己載入嘅 `app-data.json`。
- 計法（逐張卡嘅特殊規則、Travel Guru 每年 RC 上限、EveryMile 每季門檻）：寫死喺引擎入面，**凍結喺碌邊張 app 2.0.4（2026-09-11）**，之後唔再更新。碌邊張之後改咗計法嘅話，數字會有出入，一切以碌邊張 app 為準。
- **逐張卡嘅簽賬上限冇計**（`capAmt`／`sharedCap`／爆上限之後嘅較低回贈率，例如 Pulse 內地每半年嘅上限）：簽過上限嗰部分，工具計出嚟嘅回贈會偏高。

**匯入之前要知**

- 匯入嘅回贈會永久寫死喺記賬度，app 唔會幫你重算。
- 匯入會整份覆蓋你喺碌邊張嘅資料；如果登入咗雲端同步，仲會推上雲端。匯入之前，先喺碌邊張匯出一份最新備份。
- 作者已經暫停再開發匯入呢條路：功能照用得，但唔會再改進。

**前置：自己攞一份 `app-data.json`**

碌邊張嘅公開規則庫喺 `https://www.swipewhich.com/app-data.json`，用你部機嘅瀏覽器自己下載一份。
本工具唔會自動去拉，亦冇內嵌任何快照——碌邊張會定期改 T&C 資料，過期嘅數係錯數。
瀏覽器版喺第 1 步之前嗰個「前置」區收檔。最快係撳粒「一鍵攞最新」，直接攞當日最新嗰份；呢粒掣淨係你撳嗰陣先會去攞，工具唔會自己走去攞。撳唔到就用另外三個方法：喺 app-data.json 嗰版全選複製再貼入去、將個檔拖入嗰一格、或者用「選擇檔案」。CLI 版用 `--app-data`；兩邊都會顯示呢份嘅日期，
超過 30 日就會叫你去下載過。

**用法（瀏覽器版）**

1. 碌邊張 → 設定 → 匯出備份 → 下載 `.json`（或者複製轉移碼），喺第 1 步貼入。**要用最新嗰份**，因為匯入係整份覆蓋。
2. 第 2 步填優惠設定：登記開關、最紅自主、Travel Guru 等級同日期、逐個優惠登記、簽滿賞。
3. 第 3 步上傳 Planto 嘅 `transaction_export_….csv`，確認每個帳戶對應邊張卡。自己嘅商戶規則喺「自訂商戶規則」填，格式 `正則 => 場景`，只存喺你嘅瀏覽器。
4. 第 4 步逐筆檢查，可以改場景或者唔匯入某筆。
5. 第 5 步生成轉移碼；設定改過就剔「用而家嘅費率重寫 rate／rebate」。碌邊張 → 設定 → 匯入資料 → 貼碼。

**CLI 版**

```bash
cp config.example.json config.json    # 填自己嘅卡對應、規則同設定
# 用瀏覽器去 https://www.swipewhich.com/app-data.json 下載一份，擺喺同一個資料夾
python3 planto2sw.py --tx transaction_export.csv --existing backup.json --config config.json --app-data app-data.json --out out
```

`--app-data` 預設就係當前目錄嘅 `app-data.json`；超過 30 日會出過期警告，自己去下載過一份。
`--refresh-rates` 會用而家嘅設定重寫已有記帳嘅費率，`--since 2026-09-01` 只處理之後嘅交易。

**RewardCash 對賬**

```bash
python3 rewardcash_recon.py --account account_export.csv --backup backup.json
```

存低每次嘅 RewardCash 餘額，按每張卡嘅結單日列出每期應得幾多；有兩次快照就比差額。要先喺 `config.json` 嘅 `rewardcash_map` 填好每個 RewardCash 戶口尾碼對應邊張卡。

**驗證範圍**

- 費率引擎：2026-09-11 對住碌邊張 app 2.0.4，全部 91 張卡逐組合比對，零差異（`tests/engine_check.py`）。之後已凍結，見上面「點解工具要自己計回贈」。
- 端到端：只對 HSBC 同信銀國際嘅 Planto 帳戶命名格式驗證過。
- 其他銀行：帳戶命名同描述前綴（`APPLEPAY` / `SALES:` / `QR`）係咪一樣，未驗證。自己喺第 3 步揀卡、第 4 步逐筆檢查；歡迎開 issue 補資料。

**環境要求**

- 瀏覽器版：用瀏覽器直接開 `index.html`，唔使裝任何嘢。
- CLI：Python 3，只用標準庫。
- Node.js ≥ 18：淨係跑測試先要。

**測試**

- `python3 tests/compare.py`：用合成測試資料分別跑瀏覽器版同 CLI，兩邊生成嘅記賬要完全一樣。要 Node ≥ 18，同埋一份你自己存喺 `.cache/app-data.json` 嘅 app-data.json；golden 值係按作者手上嗰份錄嘅，你嗰份嘅基本費率唔同嘅話，個別斷言可能唔過。
- `python3 tests/engine_check.py`：離線將兩個移植引擎同碌邊張 app 2.0.4 嘅 bundle 逐組合比對。佢要一份本機快取嘅 2.0.4 bundle，本 repo 冇提供，亦冇任何嘢會幫你下載，所以外部貢獻者跑到 `compare.py`，但跑唔到 `engine_check.py`。

**授權**

為呢個項目寫嘅代碼用 MIT 授權。由碌邊張前端推導出嚟嘅部分（兩個工具入面用註解標明嘅費率引擎段落、`index.html` 入面同樣標明嘅卡片清單同場景清單、`docs/swipewhich-internals.md`、`docs/swipewhich-cards.json`）唔喺 MIT 範圍內，亦唔授權俾任何人，詳見 `LICENSE`。

---

## 简体中文

非官方工具，与 Planto 及碌邊張均无任何关联，也不由它们提供支持。

把 Planto 导出的信用卡交易 CSV 转成碌邊張可以「匯入資料」的备份或转移码，记账不用再逐笔手填。
全部在你自己的电脑上运行，不上传任何数据，也不碰你的银行账户。

**为什么工具要自己计算回赠**

碌邊張导入时，每条记账按写入的内容原样保存，之后不会重新分类，也不会重算回赠：app 里每一处显示的回赠，都直接读取记账里存着的数值（没有就当 0）；唯一会重算的情况，是你自己打开某一条记账再点保存。所以本工具必须在导入之前，自己把每笔交易分好类、算好回赠，因此它有自己的一套费率引擎：

- 基础费率和商户优惠：读取你自己载入的 `app-data.json`。
- 计算逻辑（各卡特殊规则、Travel Guru 每年 RC 上限、EveryMile 每季门槛）：写死在引擎里，**冻结在碌邊張 app 2.0.4（2026-09-11）**，此后不再更新。碌邊張之后若改了计算方式，数字会有出入，一切以碌邊張 app 为准。
- **各卡的签账上限没有计算**（`capAmt`／`sharedCap`／超出上限后的较低回赠率，例如 Pulse 内地每半年的上限）：超出上限的那部分，工具算出的回赠会偏高。

**导入之前请注意**

- 导入的回赠会永久写死在记账里，app 不会帮你重算。
- 导入会整份覆盖你在碌邊張的数据；如果登录了云端同步，还会推送到云端。导入之前，请先在碌邊張导出一份最新备份。
- 作者已暂停继续开发导入这条路径：功能仍可使用，但不会再改进。

**前置：自己下载一份 `app-data.json`**

碌邊張的公开规则库在 `https://www.swipewhich.com/app-data.json`，请用自己的浏览器下载一份。
本工具不会自动去拉，也没有内嵌任何快照——碌邊張会定期修改 T&C 数据，过期的快照算出来就是错数。
浏览器版在第 1 步之前的「前置」区收文件。最快是点一下「一鍵攞最新」，直接取当天最新的那份；这个按钮只在你点的时候才会去取，工具不会自己去取。点不动就用另外三种方式：在 app-data.json 那一页全选复制再粘贴进去、把文件拖进那一格、或者用「选择文件」。命令行版用 `--app-data`；两边都会显示这份的日期，
超过 30 天会提示你重新下载。

**用法（浏览器版）**

1. 碌邊張 → 設定 → 匯出備份 → 下载 `.json`（或复制转移码），在第 1 步贴进去。**必须用最新的那份**，因为导入是整份覆盖。
2. 第 2 步填优惠设定：登记开关、最红自主、Travel Guru 等级和日期、逐个优惠登记、签满赏。
3. 第 3 步上传 Planto 的 `transaction_export_….csv`，确认每个账户对应哪张卡。自己的商户规则在「自訂商戶規則」里填，格式是 `正则 => 场景`，只存在你的浏览器里。
4. 第 4 步逐笔检查，可以改场景或者取消某笔。
5. 第 5 步生成转移码；设定改过就勾上「用而家嘅費率重寫 rate／rebate」。碌邊張 → 設定 → 匯入資料 → 贴码。

**命令行版**

```bash
cp config.example.json config.json    # 填自己的卡对应、规则和设定
# 用浏览器到 https://www.swipewhich.com/app-data.json 下载一份，放在同一个文件夹
python3 planto2sw.py --tx transaction_export.csv --existing backup.json --config config.json --app-data app-data.json --out out
```

`--app-data` 默认就是当前目录的 `app-data.json`；超过 30 天会给出过期警告，请自己重新下载一份。
`--refresh-rates` 用当前设定重写已有记账的费率，`--since 2026-09-01` 只处理该日期之后的交易。

**RewardCash 对账**

```bash
python3 rewardcash_recon.py --account account_export.csv --backup backup.json
```

保存每次的 RewardCash 余额快照，按每张卡的结单日列出每期应得多少；有两次快照后比较差额。需要先在 `config.json` 的 `rewardcash_map` 填好每个 RewardCash 账户尾号对应哪张卡。

**验证范围**

- 费率引擎：2026-09-11 对照碌邊張 app 2.0.4，全部 91 张卡逐组合比对，零差异（`tests/engine_check.py`）。此后已冻结，见上面「为什么工具要自己计算回赠」。
- 端到端：只对 HSBC 和信银国际的 Planto 账户命名格式验证过。
- 其他银行：账户命名和描述前缀（`APPLEPAY` / `SALES:` / `QR`）是否相同尚未验证。请在第 3 步自行选卡、第 4 步逐笔检查分类；欢迎提 issue 补充。

**环境要求**

- 浏览器版：用浏览器直接打开 `index.html`，无需安装任何东西。
- 命令行版：Python 3，只用标准库。
- Node.js ≥ 18：只有运行测试时才需要。

**测试**

- `python3 tests/compare.py`：用合成测试数据分别运行浏览器版和命令行版，两边生成的记账必须完全一致。需要 Node ≥ 18，以及一份你自己保存在 `.cache/app-data.json` 的 app-data.json；golden 值是按作者手上那份录制的，如果你那份的基础费率不同，个别断言可能不通过。
- `python3 tests/engine_check.py`：离线把两个移植引擎与碌邊張 app 2.0.4 的 bundle 逐组合比对。它需要一份本机缓存的 2.0.4 bundle，本仓库不提供，也没有任何脚本会替你下载，所以外部贡献者可以运行 `compare.py`，但无法运行 `engine_check.py`。

**许可证**

为本项目编写的代码采用 MIT 许可证。从碌邊張前端推导出来的部分（两个工具里用注释标明的费率引擎段落、`index.html` 里同样标明的卡片清单和场景清单、`docs/swipewhich-internals.md`、`docs/swipewhich-cards.json`）不在 MIT 范围内，也不授权给任何人，详见 `LICENSE`。

---

## English

Unofficial tool. Not affiliated with, endorsed by, or supported by Planto or SwipeWhich.

Converts the credit-card transaction CSV exported by Planto into a backup / transfer code that SwipeWhich can
import, so your spending is logged automatically instead of by hand. Everything runs locally: nothing is
uploaded, and the tool never touches your bank accounts.

**Why the tool computes rewards itself**

SwipeWhich's import stores each log exactly as written and never recomputes its category or reward afterwards:
everywhere the app shows a reward, it reads the value stored in the log (0 if there is none), and the only
recompute happens when you open a single log and press Save. So this tool has to classify every transaction and
compute its reward before import, which is why it has its own rate engine:

- Base rates and merchant offers come from the `app-data.json` you load.
- The calculation logic (per-card rules, the Travel Guru annual RewardCash cap, the EveryMile quarterly tier) is
  hard-coded in the engine and **frozen at SwipeWhich app 2.0.4 (2026-09-11)**; it is no longer updated. If
  SwipeWhich has changed its calculations since, figures will differ. The app is authoritative.
- **Per-card spend caps are not modelled** (`capAmt` / `sharedCap` / the lower rate after a cap, e.g. the HSBC
  Pulse mainland half-year cap), so rewards for spending past such a cap are overstated.

**Before you import**

- Imported rewards are written permanently; the app does not recompute them.
- An import overwrites all of your SwipeWhich data, and if you are signed in to cloud sync it is pushed to the
  cloud as well. Export a fresh backup from SwipeWhich first.
- The author has paused further development of the import path: it still works, but is not being improved.

**First: get your own copy of `app-data.json`**

SwipeWhich's public rule library lives at `https://www.swipewhich.com/app-data.json`. Download it yourself in
your browser. This tool never fetches it automatically, only when you click 「一鍵攞最新」, and ships no snapshot
of it — SwipeWhich revises the T&C data regularly, and a stale copy simply shows wrong numbers. The browser tool
takes the file in the setup section (前置) above step 1. The quickest route is that 「一鍵攞最新」 button, which
pulls today's copy. Otherwise paste the JSON straight in, drop the file onto that block, or use the file picker.
The CLI takes it with `--app-data`. Both show the date of the copy you hold and tell you
to download a fresh one once it is more than 30 days old.

**Browser tool**

1. In SwipeWhich: Settings → Export backup → download the `.json` (or copy the transfer code) and paste it into
   step 1. **Use the newest export**, because importing overwrites everything.
2. Step 2: fill in your reward settings — registrations, 最紅自主 allocation, Travel Guru tier and dates,
   per-offer registrations, milestone campaigns.
3. Step 3: upload Planto's `transaction_export_….csv` and confirm which card each account maps to. Your own
   merchant rules go in the custom-rules box as `regex => scenario`; they stay in your browser.
4. Step 4: review row by row; change a scenario or exclude a row.
5. Step 5: generate the transfer code. Tick the rewrite option if you changed any setting. Then import it in
   SwipeWhich under Settings → Import.

**CLI**

```bash
cp config.example.json config.json    # your card mapping, rules and settings
# download https://www.swipewhich.com/app-data.json in your browser, into this folder
python3 planto2sw.py --tx transaction_export.csv --existing backup.json --config config.json --app-data app-data.json --out out
```

`--app-data` defaults to `app-data.json` in the current directory; it warns when that copy is more than 30 days
old, at which point you download a fresh one yourself.
`--refresh-rates` rewrites the rates of logs that already exist, `--since 2026-09-01` skips older rows.

**RewardCash reconciliation**

```bash
python3 rewardcash_recon.py --account account_export.csv --backup backup.json
```

Stores a snapshot of your RewardCash balances, lists the RC each statement period should have earned, and
compares the balance delta once two snapshots exist. Fill in `rewardcash_map` in `config.json` first, mapping each
RewardCash account suffix to its card.

**What has been verified**

- Rate engine: on 2026-09-11 every one of the 91 cards was checked combination by combination against
  SwipeWhich app 2.0.4, with zero differences (`tests/engine_check.py`). It has been frozen there since; see
  "Why the tool computes rewards itself" above.
- End to end: only verified against the Planto account-name formats of HSBC and CNCBI cards.
- Other banks: whether Planto names their accounts the same way, and uses the same description prefixes
  (`APPLEPAY` / `SALES:` / `QR`), is unverified. Pick the card yourself in step 3, check each row in step 4, and
  please open an issue with your account-name and description patterns.

**Requirements**

- Browser tool: open `index.html` in a browser; nothing to install.
- CLI: Python 3, standard library only.
- Node.js >= 18: only needed to run the tests.

**Tests**

- `python3 tests/compare.py` runs the browser tool and the CLI on synthetic fixtures and requires identical logs.
  It needs Node >= 18 and an `app-data.json` you saved at `.cache/app-data.json`. The golden values were recorded
  with the author's copy; if yours has different base rates, individual assertions can fail.
- `python3 tests/engine_check.py` compares both engine ports, offline and combination by combination, with the
  SwipeWhich app 2.0.4 bundle. It needs a locally cached 2.0.4 bundle, which this repository does not distribute
  and nothing here downloads, so outside contributors can run `compare.py` but not `engine_check.py`.

**License**

Code written for this project is MIT-licensed. Material derived from SwipeWhich's front-end (the rate-engine
sections marked with comments in both tools, the card list and scenario ids marked the same way in `index.html`, `docs/swipewhich-internals.md` and `docs/swipewhich-cards.json`) is
excluded from the MIT license and is not licensed to anyone; see `LICENSE`.

---

## Repository

- `index.html` — the browser tool, one file, no dependencies.
- `planto2sw.py` — the same logic as a CLI.
- `rewardcash_recon.py` — RewardCash reconciliation.
- `config.example.json` — config template; copy it to `config.json`, which is git-ignored.
- `LICENSE` — MIT for this project's own code, with the SwipeWhich-derived material excluded.
- `docs/` — SwipeWhich internals, Planto export format, design decisions, roadmap.
- `tests/` — `compare.py` proves the browser and CLI tools produce identical logs; `engine_check.py` checks the
  ported rate engine against the frozen SwipeWhich 2.0.4 bundle (needs Node and a locally cached bundle that is
  not distributed).
