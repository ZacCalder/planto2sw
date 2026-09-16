#!/usr/bin/env python3
"""RewardCash reconciliation: does what the bank actually credited match what our logs say?

Inputs
  --account   Planto account_export_<ts>.csv (one or many). The `RewardCash (-***…NNN-NNNN)` rows are
              balance snapshots; each run is appended to a history file keyed by the export timestamp.
  --backup    SwipeWhich backup .json / transfer code / SW1. string: the logs (rate/rebate) and the
              statement days (cardSettings.statementDay) that decide when RC is credited.
  --config    config.json with `rewardcash_map`: {"123-4567": "hsbc_red", …}  (masked suffix -> cardId).
              Unmapped accounts are listed; nothing is guessed.
  --history   where snapshots live (default data/rewardcash_history.json; data/ is git-ignored).

Output
  1. Expected RC per card per statement period (from logs): spend, RC in HKD; for Pulse also RC in CNY
     (RMB-side RewardCash is credited in RMB: rebate_cny = rate x CNY amount parsed from the memo, carrying the
     sign of the log's amount, so an unmatched refund subtracts).
  2. If the history holds >= 2 snapshots: per mapped account, balance delta between the last two
     snapshots vs the expected RC of statements that fell inside that interval, and the difference.
     A negative delta means a redemption happened in between.

Nothing is written to SwipeWhich. Standard library only.
"""
import argparse, csv, json, os, re, sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from planto2sw import DISCLAIMER, DISCLAIMER_LINE, load_existing  # noqa: E402

DESCRIPTION = ("rewardcash_recon — reconcile the RewardCash balances in Planto's account_export against the "
               "rebates recorded in a SwipeWhich backup, statement period by statement period.")

RC_RE = re.compile(r"RewardCash \(-\**(\d{3}-\d{4})\)")
FX_RE = re.compile(r"^([A-Z]{3})\s([\d,]+(?:\.\d+)?)")


def export_ts(path):
    m = re.search(r"(\d{4}-\d{2}-\d{2})T(\d{2})_(\d{2})_(\d{2})", os.path.basename(path))
    return f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}" if m else None


def read_balances(path):
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        m = RC_RE.search(r.get("Account Name", ""))
        if m:
            out[m.group(1)] = {"cur": r["Currency"], "balance": float(r["Balance"] or 0)}
    return out


def statement_periods(statement_day, first_day, last_day):
    """[(period_start, period_end=statement date)] covering first_day..last_day. Period = (prev stmt, stmt]."""
    def stmt(y, m):
        last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
        return date(y, m, min(statement_day, last))
    y, m = first_day.year, first_day.month
    if stmt(y, m) < first_day:
        m += 1
        if m == 13: y, m = y + 1, 1
    out = []
    while True:
        end = stmt(y, m)
        pm, py = (m - 1, y) if m > 1 else (12, y - 1)
        start = stmt(py, pm) + timedelta(days=1)
        out.append((start, end))
        if end >= last_day:
            break
        m += 1
        if m == 13: y, m = y + 1, 1
    return out


def expected_by_statement(sw):
    """{cardId: [(start, end, spend_hkd, rc_hkd, rc_cny, n, rc_hkd_side)]} using each card's statementDay.
    rc_hkd = all logs' rebate in HKD; rc_cny = RC for CNY-currency logs in RMB; rc_hkd_side = rebate of the
    non-CNY logs (what a dual-currency card's HKD RewardCash account receives)."""
    logs = [l for l in sw.get("logs", []) if not l.get("isMiles") and not l.get("isManual")]
    by_card = defaultdict(list)
    for l in logs:
        by_card[l["cardId"]].append(l)
    res = {}
    for cid, ls in by_card.items():
        sd = (sw.get("cardSettings", {}).get(cid) or {}).get("statementDay")
        days = sorted(date.fromisoformat(str(l.get("day") or l["date"])[:10]) for l in ls)
        if not sd:
            res[cid] = None
            continue
        rows = []
        for start, end in statement_periods(int(sd), days[0], days[-1]):
            sel = [l for l in ls if start <= date.fromisoformat(str(l.get("day") or l["date"])[:10]) <= end]
            if not sel:
                continue
            spend = sum(float(l.get("amount") or 0) for l in sel)
            rc = sum(float(l.get("rebate") or 0) for l in sel)
            rc_cny, rc_hkd_side = 0.0, 0.0     # RMB spend is credited to the card's CNY RewardCash account
            for l in sel:
                m = FX_RE.match(l.get("memo") or "")
                if m and m.group(1) == "CNY":
                    # the memo amount is always positive; an unmatched refund is a log with a negative amount
                    sign = -1 if float(l.get("amount") or 0) < 0 else 1
                    rc_cny += sign * float(m.group(2).replace(",", "")) * float(l.get("rate") or 0)
                else:
                    rc_hkd_side += float(l.get("rebate") or 0)
            rows.append((start, end, spend, rc, rc_cny, len(sel), rc_hkd_side))
        res[cid] = rows
    return res


def main():
    ap = argparse.ArgumentParser(description=DESCRIPTION, epilog=DISCLAIMER,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--account", nargs="+", required=True, help="Planto account_export CSV(s)")
    ap.add_argument("--backup", required=True, help="SwipeWhich backup .json / transfer code")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--history", default=os.path.join("data", "rewardcash_history.json"))
    a = ap.parse_args()

    print(f"rewardcash_recon · {DISCLAIMER_LINE}")
    cfg = json.load(open(a.config, encoding="utf-8"))
    rc_map = {k: v for k, v in (cfg.get("rewardcash_map") or {}).items() if not k.startswith("_")}
    hist = json.load(open(a.history, encoding="utf-8")) if os.path.exists(a.history) else {"snapshots": []}
    known = {s["ts"] for s in hist["snapshots"]}
    for path in a.account:
        ts = export_ts(path) or date.fromtimestamp(os.path.getmtime(path)).isoformat()
        if ts in known:
            continue
        hist["snapshots"].append({"ts": ts, "balances": read_balances(path)})
        known.add(ts)
    hist["snapshots"].sort(key=lambda s: s["ts"])
    os.makedirs(os.path.dirname(a.history) or ".", exist_ok=True)
    json.dump(hist, open(a.history, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    snaps = hist["snapshots"]
    print(f"history: {len(snaps)} snapshot(s) in {a.history}; latest {snaps[-1]['ts']}")

    sw = load_existing(a.backup)["data"]["sw_data"]
    exp = expected_by_statement(sw)

    print("\n== expected RewardCash per statement (from logs; statementDay from cardSettings) ==")
    for cid in sorted(exp):
        rows = exp[cid]
        if rows is None:
            print(f"  {cid}: no statementDay in cardSettings - set it in SwipeWhich card page"); continue
        for start, end, spend, rc, rc_cny, n, rc_hkd_side in rows:
            cny = f"  (RMB-side RC ¥{rc_cny:,.2f}, HKD-side RC HK${rc_hkd_side:,.2f})" if rc_cny else ""
            print(f"  {cid:15s} {start} .. {end}  {n:3d} logs  spend HK${spend:>10,.2f}  RC HK${rc:>8,.2f}{cny}")

    print("\n== RewardCash accounts (latest snapshot) ==")
    latest = snaps[-1]["balances"]
    for suf, b in latest.items():
        print(f"  {suf}: {b['cur']} {b['balance']:>9,.2f}  ->  {rc_map.get(suf, '(unmapped: add to config rewardcash_map)')}")

    if len(snaps) < 2:
        print("\nOnly one snapshot: nothing to diff yet. Export account_export again after the next statement "
              "and rerun; the balance delta will be compared with the statements that fell in between.")
        return
    prev, cur = snaps[-2], snaps[-1]
    p_ts, c_ts = date.fromisoformat(prev["ts"][:10]), date.fromisoformat(cur["ts"][:10])
    print(f"\n== delta {prev['ts']} -> {cur['ts']} vs statements credited in between ==")
    has_cny = {cid for suf, cid in rc_map.items() if cur["balances"].get(suf, {}).get("cur") == "CNY"}
    for suf, cid in rc_map.items():
        if suf not in cur["balances"] or suf not in prev["balances"]:
            continue
        b0, b1 = prev["balances"][suf]["balance"], cur["balances"][suf]["balance"]
        cny = cur["balances"][suf]["cur"] == "CNY"
        due = [r for r in (exp.get(cid) or []) if p_ts < r[1] <= c_ts]
        expect = sum((r[4] if cny else r[6] if cid in has_cny else r[3]) for r in due)
        print(f"  {suf} ({cid}): {b0:,.2f} -> {b1:,.2f}  delta {b1 - b0:+,.2f}  expected {expect:+,.2f}  "
              f"diff {b1 - b0 - expect:+,.2f}  [{len(due)} statement(s)]{'  (redemption?)' if b1 < b0 else ''}")


if __name__ == "__main__":
    main()
