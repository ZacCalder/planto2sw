#!/usr/bin/env python3
"""Rate-engine regression: our ports (index.html swRate / planto2sw.py sw_rate) vs the cached, frozen SwipeWhich
2.0.4 bundle.

1. tests/oracle/grid.mjs loads the bundle cached in .cache/sw/ into Node, hydrates it with
   .cache/app-data.json and asks that engine for rates over ~200k
   (card, scenario, currency, amount, knobs) combinations.
2. Both ports must reproduce every rate. Exit 1 on any mismatch.

The ports are FROZEN at app 2.0.4 / chunk 2565-b2d113f70d98cb47 (2026-09-11, decision 22) and are never updated
again, so this check only ever runs against that cached bundle. It makes no network requests. The cache is a
private developer reference: .cache/ is git-ignored and not distributed, so without it the script exits.

usage: python3 tests/engine_check.py     (needs node >= 18)
"""
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SW_DIR = os.path.join(ROOT, ".cache", "sw")
APP_DATA = os.path.join(ROOT, ".cache", "app-data.json")
FROZEN_CHUNK = "2565-b2d113f70d98cb47.js"     # the 2.0.4 chunk holding the engine the ports were frozen against


def main():
    if not os.path.isfile(os.path.join(SW_DIR, FROZEN_CHUNK)) or not os.path.isfile(APP_DATA):
        raise SystemExit(
            "no cached SwipeWhich 2.0.4 bundle (.cache/sw/" + FROZEN_CHUNK + ") or no .cache/app-data.json.\n"
            "This check compares the ports with that cached, frozen 2.0.4 bundle, which is a private developer "
            "reference and is not distributed with this repository. Nothing is downloaded, so without the cache "
            "there is nothing to check. tests/compare.py does not need the bundle.")
    with tempfile.TemporaryDirectory() as tmp:
        grid = os.path.join(tmp, "grid.json")
        r = subprocess.run(["node", os.path.join(ROOT, "tests", "oracle", "grid.mjs"), SW_DIR, APP_DATA, grid],
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode:
            print(r.stdout, r.stderr[-2000:])
            raise SystemExit("oracle failed: .cache/sw does not load as the SwipeWhich 2.0.4 bundle the oracle expects "
                             "(modules 455 / 6822 / 6181, see docs/swipewhich-internals.md)")
        print(r.stdout.strip())
        g = json.load(open(grid, encoding="utf-8"))
        js = json.loads(subprocess.run(["node", os.path.join(ROOT, "tests", "engine_js.mjs"), os.path.join(ROOT, "index.html"), grid],
                                       check=True, capture_output=True, text=True, encoding="utf-8").stdout)
        sys.path.insert(0, ROOT)
        from planto2sw import sw_rate
        cards = {c["id"]: c for c in g["cards"]}
        bad_js, bad_py = [], []
        for i, (cid, sc, cur, amt, vi, exp) in enumerate(g["rows"]):
            if not (js[i] == exp or abs(js[i] - exp) < 1e-12):
                bad_js.append((cid, sc, cur, amt, vi, exp, js[i]))
            got = sw_rate(cards[cid], sc, amt, cur, g["variants"][vi])
            if not (got == exp or abs(got - exp) < 1e-12):
                bad_py.append((cid, sc, cur, amt, vi, exp, got))
    print(f"cases {len(g['rows'])}: index.html mismatches {len(bad_js)}, planto2sw.py mismatches {len(bad_py)}")
    for b in (bad_js + bad_py)[:20]:
        print("  ", b)
    if bad_js or bad_py:
        sys.exit(1)
    print("PASS: both ports match the frozen SwipeWhich 2.0.4 engine")


if __name__ == "__main__":
    main()
