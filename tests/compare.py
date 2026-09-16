#!/usr/bin/env python3
"""Cross-implementation check: index.html and planto2sw.py must produce identical logs.

Runs both on tests/fixtures/planto-cases.csv three times (no backup; a backup built from
docs/sample-backup-decoded.json; the same backup patched with 賞世界 and Travel Guru), diffs every log field by
id, diffs row statuses, and asserts a few golden values. Also checks rewardcash_recon.py's RMB-side expectation
on the generated logs. Exit 1 on any difference.

usage: python3 tests/compare.py            (needs node >= 18 on PATH)
"""
import base64, csv, json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES = os.path.join(ROOT, "tests", "fixtures", "planto-cases.csv")
APP_DATA = os.path.join(ROOT, ".cache", "app-data.json")   # user-supplied; nothing here downloads it
# tests always run against the shipped example config; config.json is a private copy (git-ignored)
CONFIG = os.path.join(ROOT, "config.example.json")
LOG_FIELDS = ["day", "date", "memo", "rate", "miles", "amount", "cardId", "rebate", "isMiles", "cardName", "scenario"]
# JS status -> Python status
STATUS = {"ok": "converted", "no-card": "no-card-map", "refund": "refund-paired", "credit": "credit-skipped", "kept": "kept-existing"}


sys.path.insert(0, ROOT)
from planto2sw import det_id  # noqa: E402
from rewardcash_recon import expected_by_statement  # noqa: E402

# Row 16 of the fixture (AMAZON.CO.JP, JPY 3,200 on 2026-08-07) already in the app, re-categorised there as physicalFX.
SEED_LOGS = [{"u": 1, "id": det_id("HSBC EveryMile Card", "2026-08-07", "-3200.0", "JPY", "SALES: AMAZON.CO.JP TOKYO JP"),
              "day": "2026-08-07", "date": "2026-08-07T04:00:00.000Z", "memo": "JPY 3,200.00 · SALES: AMAZON.CO.JP TOKYO JP [auto]",
              "rate": 0.025, "miles": 0, "amount": 160.0, "cardId": "hsbc_everymile", "rebate": 4.0, "isMiles": False,
              "cardName": "HSBC EveryMile", "scenario": "physicalFX"}]


def sw1_from_decoded(path, patch=None):
    o = json.load(open(path, encoding="utf-8"))
    o["data"]["sw_data"].update(patch or {})
    o["data"]["sw_data"] = json.dumps(o["data"]["sw_data"], ensure_ascii=False, separators=(",", ":"))
    o["data"]["sw_ui"] = json.dumps(o["data"]["sw_ui"], ensure_ascii=False, separators=(",", ":"))
    return "SW1." + base64.b64encode(json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode()).decode()


def test_config(out_dir):
    """config.json with `settings` reduced to the registration flags: the test must not depend on the
    最紅自主/Guru values of a private config (those are exercised through patched snapshots instead)."""
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    cfg["settings"] = {k: v for k, v in cfg["settings"].items() if k.endswith("Reg")}
    path = os.path.join(out_dir, "config-test.json")
    json.dump(cfg, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return path


def run_case(name, existing_path, out_dir):
    py_out = os.path.join(out_dir, name)
    cmd = [sys.executable, os.path.join(ROOT, "planto2sw.py"), "--tx", CASES, "--config", test_config(out_dir),
           "--out", py_out, "--app-data", APP_DATA] + (["--existing", existing_path] if existing_path else [])
    subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8")
    js = subprocess.run(["node", os.path.join(ROOT, "tests", "harness.mjs"), os.path.join(ROOT, "index.html"), CASES, APP_DATA]
                        + ([existing_path] if existing_path else []), check=True, capture_output=True, text=True, encoding="utf-8")
    js = json.loads(js.stdout)
    sw = json.loads(json.load(open(os.path.join(py_out, "swipewhich-backup.json"), encoding="utf-8"))["data"]["sw_data"])
    review = {int(r["row"]): r for r in csv.DictReader(open(os.path.join(py_out, "review.csv"), encoding="utf-8-sig"))}
    seeded = {l["id"] for l in SEED_LOGS} if name == "with-guru" else set()   # planted snapshot logs are not "generated"
    py_logs = {l["id"]: l for l in sw["logs"] if "[auto]" in str(l.get("memo", "")) and l["id"] not in seeded}
    return js, py_logs, review


def diff_case(name, js, py_logs, review):
    errs = []
    jl = {l["id"]: l for l in js["logs"]}
    if set(jl) != set(py_logs):
        errs.append(f"log id sets differ: only JS {sorted(set(jl) - set(py_logs))}, only PY {sorted(set(py_logs) - set(jl))}")
    for i in sorted(set(jl) & set(py_logs)):
        for k in LOG_FIELDS:
            if jl[i].get(k) != py_logs[i].get(k):
                errs.append(f"id {i} {k}: JS={jl[i].get(k)!r} PY={py_logs[i].get(k)!r}")
    for r in js["rows"]:
        p = review.get(r["row"])
        if not p:
            errs.append(f"row {r['row']}: missing from review.csv")
            continue
        if STATUS.get(r["status"], r["status"]) != p["status"]:
            errs.append(f"row {r['row']} status: JS={r['status']} PY={p['status']}")
        if r["status"] == "ok" and (r["scenario"] != p["scenario"] or float(p["rate"]) != r["rate"]):
            errs.append(f"row {r['row']} scenario/rate: JS={r['scenario']}/{r['rate']} PY={p['scenario']}/{p['rate']}")
    return [f"[{name}] {e}" for e in errs]


def golden(name, js):
    """Hard expectations pinning down the behaviours the two tools were once inconsistent on."""
    errs = []
    by_row = {r["row"]: r for r in js["rows"]}

    def expect(row, **kw):
        r = by_row[row]
        for k, v in kw.items():
            got = r.get(k)
            same = abs(got - v) < 1e-9 if isinstance(v, float) and isinstance(got, (int, float)) else got == v
            if not same:
                errs.append(f"[{name}] row {row} expected {k}={v!r}, got {got!r}")

    expect(18, status="ok", cardId="hsbc_gold")        # HSBC Gold account is mapped
    expect(12, scenario="dining")                       # Sushiro via English name
    if name != "with-guru":
        expect(16, scenario="onlineFX")                 # AMAZON.CO.JP -> Amazon, not "tokyo" alias of 東京生活館
    expect(17, scenario="physicalFX", rate=0.025 if name != "with-guru" else 0.065)   # DEMO KONBINI TOKYO: EveryMile 2.5%, +Guru L2 4% because all eligible HSBC cards pool (T&C 9c)
    expect(19, scenario="local", layer="兜底 ⚠")        # "hong" alias must not match HONG KONG
    expect(22, scenario="local", layer="兜底 ⚠")
    expect(4, status="ok", rate=0.004 if name != "with-guru" else 0.044)   # Pulse via WeChat: no +2%/賞世界; Guru L2 4% still applies (pooled, T&C 9c)
    expect(7, status="ok", scenario="travelCN")         # unmatched refund -> negative log
    neg = next((l for l in js["logs"] if "RETURN: DEMO MART" in l["memo"] and l["amount"] < 0), None)
    if not neg or neg["amount"] != -58.0 or neg["rebate"] >= 0:
        errs.append(f"[{name}] unmatched refund must become a -58.00 log with negative rebate, got {neg}")
    expect(25, status="ok", cardId="hsbc_pulse", scenario="supermarket")   # Pulse HKD-side account maps to the same card; 惠康 via alias
    expect(26, status="ok", cardId="cncbi_gba", scenario="travelCN")       # CNCBI CNY-side account
    expect(27, status="ok", scenario="travelCN")                           # ELEME -> channel rule
    expect(28, status="ok", scenario="travelCN")                           # DEMO RIDE HAILING -> channel rule
    for row in (29, 30, 31, 32, 33):                                       # PAYMENT REVERSAL / LATE CHARGE (+REV) / IBANKING / INTEREST
        expect(row, status="excluded")
    amt = next(l["amount"] for l in js["logs"] if "ODD ROUNDING" in l["memo"])
    if amt != 1.13:
        errs.append(f"[{name}] 1.125 HKD must round half-up to 1.13, got {amt}")
    if any("[check]" in l["memo"] for l in js["logs"]):
        errs.append(f"[{name}] [check] must not be written into memo")
    if name in ("no-existing", "with-existing"):
        expect(2, status="ok", rate=0.024)              # Pulse travelCN Apple Pay: 0.4% base + 2% registered, no 最紅自主/Guru
    if name == "with-existing":
        expect(23, status="dup-manual")                 # already logged by hand in the snapshot
    if name == "with-guru":                             # snapshot patched: 賞世界 x3 + Guru L2 since 2026-01-01
        expect(2, status="ok", rate=0.076)              # 0.4% x (1 + 3) + Pulse 2% + Guru L2 4%
        expect(16, status="kept")                       # app already has it as physicalFX -> not regenerated, app copy wins
        # row 24 (HK$46,400 on 2026-08-30) crosses the L2 annual cap of 1,200 RC. Strictly chronological replay,
        # all eligible HSBC cards pooled (T&C 9c), so RC earned before it is
        # Pulse (78.88 + 174.0 + 34.8 + 29.0 - 58.0 + 46.4) * 0.04 = 12.2032 (rows 2, 3, 27, 28, the row-7 refund, row 4)
        # + EveryMile (160.0 + 49.0) * 0.04 = 8.36 (row 16 as kept in the app, row 17) = 20.5632;
        # the snapshot's manual log is dated 09-10 and does not count yet
        # -> remaining 1179.4368 -> r = 29485.92 -> blended 0.036 + 0.04 * 29485.92 / 46400 = 0.0614189
        # (the refuted monthly top-card reading would give 0.0615991, so the tolerance must stay far below 1.8e-4)
        r24 = by_row[24]["rate"]
        if r24 is None or abs(r24 - 0.0614189) > 1e-6:
            errs.append(f"[{name}] row 24 expected pooled Guru cap-blended rate 0.0614189, got {r24}")
    return errs


def recon_check(py_out):
    """rewardcash_recon.py: the RMB-side expected RewardCash must subtract an unmatched CNY refund (row 7 becomes a
    log with a negative amount while its memo amount stays positive). Oracle: the fixture's own signed CNY amounts
    x the rates planto2sw.py reported in review.csv, summed per statement period."""
    sw = json.loads(json.load(open(os.path.join(py_out, "swipewhich-backup.json"), encoding="utf-8"))["data"]["sw_data"])
    sw["cardSettings"] = {"hsbc_pulse": {"statementDay": 25}}
    cny = [r for r in csv.DictReader(open(os.path.join(py_out, "review.csv"), encoding="utf-8-sig"))
           if r["status"] == "converted" and r["cardId"] == "hsbc_pulse" and r["cur"] == "CNY"]
    errs = []
    if not any(float(r["amount"]) > 0 for r in cny):
        errs.append("[recon] the fixture no longer has an unmatched CNY refund, so the refund sign is untested")
    for start, end, _, _, rc_cny, _, _ in expected_by_statement(sw)["hsbc_pulse"]:
        want = sum(-float(r["amount"]) * float(r["rate"]) for r in cny if start.isoformat() <= r["date"] <= end.isoformat())
        if abs(rc_cny - want) > 1e-9:
            errs.append(f"[recon] hsbc_pulse {start}..{end}: RMB-side expected RC {rc_cny:.4f}, want {want:.4f}")
    return errs


def mirror_check(js):
    """index.html carries its own copy of the rule constants; they must equal config.example.json."""
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    errs = []
    for k, v in js["mirror"].items():
        c = cfg.get(k)
        if k == "rate_overrides":
            continue
        if v != c:
            errs.append(f"[mirror] index.html {k} != config.example.json {k}:\n    JS  = {json.dumps(v, ensure_ascii=False)}"
                        f"\n    CFG = {json.dumps(c, ensure_ascii=False)}")
    return errs


DISCLAIMER_EN = "Unofficial tool. Not affiliated with, endorsed by, or supported by Planto or SwipeWhich."


def disclaimer_check():
    """AGENTS.md invariant: the notice must survive on every surface a user lands on."""
    errs = []

    def need(label, text, needle):
        if needle not in text:
            errs.append("[disclaimer] " + label + " is missing " + repr(needle) + " (see the AGENTS.md invariant)")

    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    need("README.md", readme, DISCLAIMER_EN)
    if readme.count("非官方") < 2:
        errs.append("[disclaimer] README.md must repeat the notice inside each language section, not only once")
    need("index.html", open(os.path.join(ROOT, "index.html"), encoding="utf-8").read(), "非官方")
    for script in ("planto2sw.py", "rewardcash_recon.py"):
        out = subprocess.run([sys.executable, os.path.join(ROOT, script), "--help"],
                             capture_output=True, text=True, encoding="utf-8").stdout or ""
        need(script + " --help", out, "非官方")
    return errs


def main():
    if not os.path.isfile(APP_DATA):
        raise SystemExit(
            "missing " + APP_DATA
            + " -- both tools need a user-supplied app-data.json and nothing downloads it."
            + " Open https://www.swipewhich.com/app-data.json in a browser and save it there."
        )
    errs = []
    with tempfile.TemporaryDirectory() as tmp:
        decoded = os.path.join(ROOT, "docs", "sample-backup-decoded.json")
        existing = os.path.join(tmp, "existing.txt")
        open(existing, "w", encoding="utf-8").write(sw1_from_decoded(decoded))
        guru = os.path.join(tmp, "existing-guru.txt")
        base_logs = json.load(open(decoded, encoding="utf-8"))["data"]["sw_data"]["logs"]
        open(guru, "w", encoding="utf-8").write(sw1_from_decoded(decoded, {
            "vs": {"world": 3, "savour": 0, "home": 0, "lifestyle": 0, "shopping": 0},
            "guru": "L2", "guruStartDate": "2026-01-01", "guruRcBaseline": 0, "guruRcBaselineDate": "",
            "logs": base_logs + SEED_LOGS}))
        for name, ex in [("no-existing", None), ("with-existing", existing), ("with-guru", guru)]:
            js, py_logs, review = run_case(name, ex, tmp)
            errs += diff_case(name, js, py_logs, review) + golden(name, js)
            if name == "no-existing":
                errs += mirror_check(js) + disclaimer_check() + recon_check(os.path.join(tmp, name))
            print(f"{name}: {len(js['logs'])} logs, {sum(1 for r in js['rows'] if r['status'] == 'ok')} ok rows")
    if errs:
        print("\n".join(errs))
        print(f"\nFAIL: {len(errs)} difference(s)")
        sys.exit(1)
    print("PASS: index.html and planto2sw.py agree")


if __name__ == "__main__":
    main()
