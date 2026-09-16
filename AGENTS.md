# planto2sw — agent guide

Converts the credit-card transaction CSV exported by **Planto** (a Hong Kong personal-finance app) into a
backup / transfer code that **SwipeWhich** (碌邊張) can import, after the user has filled in their reward
registrations. Personal open-source project. Everything runs locally; nothing is uploaded anywhere.
Since 2026-09-12 further development of the import path is paused (decision 18): it still works and is tested,
but is not being extended.

`AGENTS.md` and `CLAUDE.md` are kept identical — change both, or neither.

## Read first

1. `docs/swipewhich-internals.md` — SwipeWhich's data structures, backup format, import validation, rate
   engine. All of it was reverse-engineered from the public front-end bundle. This is the most important
   knowledge in the project; read it before changing anything about the output format.
2. `docs/planto-export.md` — Planto CSV columns, cleaning rules, payment-channel detection, classification.
3. `docs/decisions.md` — settled design decisions and why.
4. `docs/roadmap.md` — what is left.

A working copy may also hold a `private/` directory: local-only, git-ignored personal notes that are not part of
the project and absent from any public clone. Never copy its content into a tracked file.

## Code

| File | Role | State |
|---|---|---|
| `index.html` | Single-file browser tool (the main deliverable): supply `app-data.json` (前置) → paste transfer code → reward settings → upload CSV → review row by row → generate transfer code. No dependencies. It carries no snapshot of the rule library and never fetches one automatically: the 一鍵攞最新 button fetches `https://www.swipewhich.com/app-data.json` only when clicked; otherwise the user pastes, drops or picks a copy they saved themselves. All of that happens in the unnumbered 前置 section before step 1, which shows the copy's `generatedAt` date and asks for a fresh copy past 30 days. | Works; exercised end to end in a real browser and through `tests/harness.mjs` |
| `planto2sw.py` | Same logic as a CLI, standard library only. CSV + existing backup + `config.json` + the user's own `app-data.json` → backup JSON, transfer code, `review.csv`. `--app-data` (default: `app-data.json` in the current directory) points at that copy; the CLI has no network code, and warns when the copy is more than 30 days old, the same threshold the browser tool uses. `--refresh-rates` rewrites rates on logs that already exist, `--since` skips older rows. | Works; both tools produce identical logs and identical log ids |
| `rewardcash_recon.py` | RewardCash reconciliation: stores balance snapshots from Planto's `account_export` (in `data/`, git-ignored), lists the RC each statement period should have earned, and diffs two snapshots. Needs `rewardcash_map` in the config. | V1 |
| `config.example.json` | Shipped config template: card mapping, exclusion rules, channel rules, merchant-alias stop list, rate overrides, reward settings, RewardCash mapping. | |
| `config.json` | The user's private copy. **Git-ignored, never commit it.** | |
| `docs/swipewhich-cards.json` | SwipeWhich's 91 cards: id, name, issuer, type, network (extracted from the bundle). | |
| `docs/sample-backup-decoded.json` | Demo backup — every value is invented, the structure matches a real transfer code. | Format reference |
| `docs/planto-export-sample.csv` | Synthetic Planto rows, one per row type. | Documentation sample |
| `tests/` | `compare.py` (the two implementations must agree), `engine_check.py` (+ `oracle/`, `engine_js.mjs`: the rate-engine ports must reproduce the frozen SwipeWhich 2.0.4 engine, run from a locally cached copy of that bundle which the repository does not distribute), `harness.mjs` (runs the page's logic in Node), `fixtures/planto-cases.csv` (synthetic transactions). | |

## Invariants — keep these when changing code

- **Log ids are deterministic**: `900_000_000_000_000 + int(sha1("account|date|rawAmount|cur|desc")[:12], 16) % 1e14`.
  Re-running either tool must never create a duplicate log, and the Python and JS implementations must return
  the same number.
- **Merging touches only `own`, `logs` and the keys listed under `settings`.** Every other top-level key of
  `sw_data` (`cardSettings`, `promoRegs`, `_v`, …) is carried over untouched. Import overwrites wholesale, so
  dropping a key silently deletes the user's settings.
- **An existing log with the same id wins.** If the app's copy has a different scenario, the row is not
  regenerated at all (status `kept` / `kept-existing`) and the replay uses the app's scenario. `--refresh-rates`
  only rewrites `rate`/`rebate`, and only when the scenario is unchanged.
- **`rate` and `rebate` are computed by us and written literally.** SwipeWhich's import stores each log exactly
  as written and never recomputes its category or reward afterwards: each log's displayed reward is the stored `rebate` (read as `rebate || 0`), the tracker's
  totals only scale that stored value down for spend past a cap, and the
  only recompute is a person opening one log and pressing Save (inferred from the bundle; holds for
  schemaVersion 2 / `sw_data._v` 12). So a 0 stays 0, and the tool has to classify and price every row before
  import. The values come from the ported rate engine — `swRate()` in `index.html` and `sw_rate()` in
  `planto2sw.py`, which must stay literally equivalent. Run `tests/engine_check.py` after touching either.
  **The engine is frozen** at SwipeWhich app 2.0.4 (chunk `2565-b2d113f70d98cb47`, 2026-09-11), where it matched
  exactly over 209,664 combinations. Base rates and merchant offers still come from the user's `app-data.json`;
  the calculation logic hard-coded in the port (per-card branches, the Travel Guru annual RC cap, the EveryMile
  quarterly tier) stays as it was in 2.0.4. Do not update it to track the live app: it is frozen rather than
  removed, because removing it would leave every imported reward at HK$0 (decision 22). Fix genuine
  bugs in the port if found, but never chase new upstream behaviour. **Per-card spend caps are not modelled at
  all** (`capAmt`, `sharedCap` and post-cap rates, e.g. Pulse's mainland half-year cap), so rewards on spend past
  such a cap are overstated; never describe them as frozen or handled. The frozen notice above the step-3 rate
  table and in the CLI output must stay.
- **Travel Guru replay** is strictly chronological over snapshot logs plus new rows. Eligible HSBC cards **pool**
  their FX spend (HSBC Travel Guru T&C clause 9c), so `guru_monthly_top_card` defaults to `false`. Setting it to
  `true` reproduces an earlier single-card-per-month reading, which came from clause 9d (that clause only governs
  which account the extra RewardCash is credited to); it survives solely for comparison. The RC baseline and
  baseline date follow the app's own semantics. See decisions 13, 15 and 19.
- **Unmatched refunds become negative logs** (negative `amount` and `rebate`); the tracker nets them correctly.
- **Timestamps such as `_su` need not be written**: the app resets all six on a successful import.
- **`memo` foreign-currency format must be `"CNY 1,234.56 · merchant"`** — the app parses it with a regex.
  Generated logs get a trailing ` [auto]`; hand-typed ones do not, and dedupe depends on that difference. The
  `"(自動) "` prefix belongs to the app's recurring-expense feature; never use it.
- **The rule constants in `index.html` must equal `config.example.json`** — `tests/compare.py` enforces this.
- **Never write to Supabase.** The only supported write path is the backup import.
- **`app-data.json` is supplied by the user and never fetched automatically.** Neither tool may embed a snapshot
  of SwipeWhich's rule library or download it without an explicit user action. `index.html` takes it in the
  unnumbered 前置 step and remembers it in `localStorage` under `p2s_appdata`; `planto2sw.py` takes `--app-data`
  (default `./app-data.json`). Both surface the copy's `generatedAt` date and warn once it is older than
  `APP_DATA_STALE_DAYS` (30). The page may fetch `APP_DATA_URL`, but **only from an explicit user gesture** —
  today that is the 一鍵攞最新 button, whose handler is the file's single `fetch()` call site. Never on load, on a
  timer, on retry, or as a fallback when the stored copy is missing or stale: a click is not automatic.
  `planto2sw.py` has no network code at all, and no test downloads anything: the bundle downloader that
  `tests/engine_check.py` used to carry was removed (decision 23) and must not come back. Reason: a stale snapshot
  shows wrong numbers.
- **The unofficial disclaimer stays visible, and the brand never names this tool.** The notice — 粵語
  「非官方工具，同 Planto 及碌邊張都冇任何關聯，亦唔係由佢哋提供支援。」 / English "Unofficial tool. Not
  affiliated with, endorsed by, or supported by Planto or SwipeWhich." — must stay in `README.md` (in all three
  language sections, because the anchor links at the top jump readers straight past the shared one), in
  `index.html`'s visible UI, and in the `--help` of both CLIs. Adapt the wording to the surface, never drop it:
  restyling a header is not a licence to delete it. Separately, the repository, the page title and the tools are
  never named after 碌邊張/SwipeWhich — descriptive names only (`planto2sw`). Using the
  brand to name the destination app, a data format, a key or a filename (碌邊張轉移碼, `sw_data`,
  `app-data.json`) is fine and is outside this rule.
- **The SwipeWhich-derived material stays outside the MIT license.** In `index.html` the card list and scenario
  ids sit between `BEGIN/END SwipeWhich-derived data` markers and the rate engine between `BEGIN/END
  SwipeWhich-derived rate engine` markers; in `planto2sw.py` the rate engine sits between the same engine markers.
  `LICENSE` excludes everything between any such pair, plus `docs/swipewhich-internals.md` and
  `docs/swipewhich-cards.json`. Page-state adapters (`swCard`, `swKnobs`, `Converter.knobs`) are project code and
  stay outside.
  Keep the markers exactly bracketing the derived code: anything newly derived from SwipeWhich's front-end goes
  inside them, and project code (the replay, classification, UI) stays outside. If a derived file is added,
  list it in `LICENSE`.
- **No personal data in the repository.** No real transactions, backups, card numbers, statement or due dates,
  reward balances, or account suffixes — in code, fixtures, docs or comments. Fixtures stay obviously synthetic
  (flat conversion rates, DEMO merchants). `config.json`, `data/`, `.cache/` and `private/` are git-ignored.

## Tests

```bash
python3 tests/compare.py        # both implementations on tests/fixtures/planto-cases.csv, three snapshots, plus golden assertions; needs node >= 18 and an app-data.json saved at .cache/app-data.json; run after changing either tool
python3 tests/engine_check.py   # offline: runs the frozen SwipeWhich 2.0.4 engine in Node via tests/oracle/ from the bundle cached in .cache/sw, compares both ports combination by combination
python3 planto2sw.py --tx tests/fixtures/planto-cases.csv --config config.example.json --app-data app-data.json --out /tmp/out   # CLI smoke test
```

The smoke test needs an `app-data.json` you saved yourself; the CLI does not download one, and none is committed.
`tests/engine_check.py` needs the SwipeWhich 2.0.4 bundle in `.cache/sw` plus `.cache/app-data.json`. `.cache/`
is git-ignored and not distributed, and nothing in the repository downloads it, so the check runs only where that
cache already exists; outside contributors can run `tests/compare.py` but not `tests/engine_check.py`.

For the browser tool, open `index.html` directly (or serve the folder), supply `app-data.json` in the 前置
section and walk the five steps; `#reviewSummary` and the ledger on the right show the result. Real verification
can only happen inside SwipeWhich: import, then check the tracker page totals per card and scenario.

## Style

- UI copy in Traditional Chinese (SwipeWhich is a Hong Kong app); code comments in English; docs in Traditional
  Chinese; reply to the user in the user's own language.
- Mechanism first, state the conclusion directly.
- Anything derived from the minified bundle is labelled "inferred from the bundle; holds for schemaVersion 2 /
  `sw_data._v` 12".
