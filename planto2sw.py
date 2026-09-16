#!/usr/bin/env python3
"""
planto2sw — convert a Planto transaction CSV into a SwipeWhich (碌邊張) backup file / transfer code.

Pipeline:  CSV → clean → refund-pairing → card map → scenario classify → rate → logs → merge → emit

Only the standard library is used. Tested against sw_data schema _v=12 (SwipeWhich 2.0.4).

Usage:
  python planto2sw.py --tx transaction_export.csv --existing backup.json|transfer_code.txt \
                      --config config.json --out ./out

The rate library (app-data.json) is never downloaded by this tool: save your own copy from
https://www.swipewhich.com/app-data.json into the folder you run this from, or point --app-data at it.
"""
import argparse, base64, csv, hashlib, json, os, re, sys, time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

APP_DATA_URL = "https://www.swipewhich.com/app-data.json"   # for the user's browser, never fetched here
APP_DATA_STALE_DAYS = 30
TRANSFER_PREFIX = "SW1."
AUTO_TAG = "[auto]"

DISCLAIMER = ("非官方工具，同 Planto 及碌邊張都冇任何關聯，亦唔係由佢哋提供支援。\n"
              "Unofficial tool. Not affiliated with, endorsed by, or supported by Planto or SwipeWhich.")
DISCLAIMER_LINE = "非官方工具，同 Planto 及碌邊張都冇任何關聯 · Unofficial tool, not affiliated with Planto or SwipeWhich."

# ----------------------------------------------------------------------------- helpers
def now_ms():
    return int(time.time() * 1000)

def det_id(*parts):
    """Deterministic numeric id in a range that cannot collide with Date.now()-style ids
    (9e14 + hash) and stays below JS Number.MAX_SAFE_INTEGER."""
    h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()
    return 900_000_000_000_000 + int(h[:12], 16) % 100_000_000_000_000

def load_existing(path_or_code):
    """Accepts a backup .json path, a transfer-code .txt path, or the raw SW1. string."""
    if path_or_code is None:
        return None
    raw = open(path_or_code, encoding="utf-8").read().strip() if os.path.exists(path_or_code) else path_or_code.strip()
    if raw.startswith(TRANSFER_PREFIX):
        raw = base64.b64decode(raw[len(TRANSFER_PREFIX):]).decode("utf-8")
    outer = json.loads(raw)
    assert outer.get("app") == "swipewhich", "not a SwipeWhich payload"
    outer["data"]["sw_data"] = json.loads(outer["data"].get("sw_data") or "{}")
    if isinstance(outer["data"].get("sw_ui"), str):
        try: outer["data"]["sw_ui"] = json.loads(outer["data"]["sw_ui"])
        except Exception: pass
    return outer

def app_data_age_days(generated_at):
    """Age of the app-data copy in days, from its top-level `generatedAt` (ISO-8601 UTC, ms). None if unreadable."""
    try:
        t = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
    except Exception:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400

def load_app_data(path):
    """Read SwipeWhich's rate library from a local file. No network access: the user downloads
    app-data.json themselves, and we report how old their copy is."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise SystemExit(
            f"cannot read app-data.json at {os.path.abspath(path)} ({e})\n"
            f"  1. open {APP_DATA_URL} in a browser and save it as app-data.json\n"
            f"  2. run this tool from the folder holding it (the default is ./app-data.json), or pass --app-data <path>\n"
            f"  This tool never downloads it for you.")
    age = app_data_age_days(data.get("generatedAt"))
    age_txt = "age unknown" if age is None else f"{age:.1f} days old"
    print(f"app-data: {os.path.abspath(path)} (schema {data.get('schemaVersion')}, "
          f"generated {data.get('generatedAt')}, {age_txt})")
    if age is not None and age > APP_DATA_STALE_DAYS:
        print(f"WARNING: this app-data.json is {age:.0f} days old. SwipeWhich revises the rate data regularly — "
              f"download a fresh copy from {APP_DATA_URL}, otherwise the rates below are wrong.")
    print("rate engine: frozen at SwipeWhich app 2.0.4 (2026-09-11); rates may differ from the live app, "
          "whose figures are authoritative. Per-card spend caps are not applied, so rebates on spend past a cap "
          "are overstated.")
    return data

def fmt_amount(x):
    return f"{x:,.2f}"

def js_round(v):
    """JS Math.round for v >= 0: nearest integer, ties toward +inf. Used so that
    amount/rebate are bit-identical to index.html (Math.round(x*100)/100)."""
    import math
    f = math.floor(v)
    return f + 1 if v - f >= 0.5 else f

# ====================================================================================================
# BEGIN SwipeWhich-derived rate engine
# Everything from here down to the matching END marker is derived from SwipeWhich's front-end and is
# NOT covered by this repository's MIT license. See LICENSE.
# ====================================================================================================
# ----------------------------------------------------------------------------- rate engine
# Why this exists: SwipeWhich's import stores each log exactly as written and never recomputes its category or reward
# afterwards, so rate/rebate must be computed here, before import.
# Port of SwipeWhich bundle module 455 `FC` (cashback rate) / `L` / `G`. Inferred from bundle 2.0.4
# (2026-09-11). FROZEN at app 2.0.4 (decision 22): matched chunk 2565-b2d113f70d98cb47 exactly over 209,664
# combinations and is never updated again. Base rates and merchant offers come from the user's app-data.json; the
# calculation logic (per-card branches, Travel Guru annual RC cap, EveryMile quarterly tier) is hard-coded here.
# Per-card spend caps (capAmt / sharedCap / post-cap rates) are NOT modelled: rebates on spend past such a cap are
# overstated. tests/engine_check.py checks this port against the cached, frozen SwipeWhich 2.0.4 bundle only.
# Mirrors index.html swRate(). card: {id, issuer, net, cashback, otaFromFXcb}; knobs: see sw_rate_g.
SW_VS_CB = {"world": ["onlineFX", "physicalFX", "travelJKSTA", "travelTW", "travelCN", "flightDirect", "hotelDirect"],
            "savour": ["dining"], "home": ["supermarket"],
            "lifestyle": ["fitness", "transport", "fuel", "flightOTA", "hotelOTA", "cinema"], "shopping": []}
SW_VS0 = {"world": 0, "savour": 0, "home": 0, "lifestyle": 0, "shopping": 0}
SW_FX4 = ["physicalFX", "travelJKSTA", "travelTW", "travelCN"]
SW_FX5 = ["onlineFX", "physicalFX", "travelJKSTA", "travelTW", "travelCN"]
SW_FX_ALL = SW_FX5 + ["flightDirect", "flightOTA", "hotelDirect", "hotelOTA"]
SW_AE_EXPLORER_SCS = SW_FX_ALL + ["local", "dining", "onlineHKD", "supermarket", "transport", "fuel", "mobilePay", "fitness", "medical", "pet", "cinema"]
SW_HSBC_FAMILY = ["hsbc_vs", "hsbc_plat", "hsbc_gold", "hsbc_pulse", "hsbc_easy", "hsbc_student", "hsbc_premier"]
SW_VS_BONUS_SCS = ["onlineFX", "physicalFX", "travelJKSTA", "travelTW", "dining", "supermarket", "flightDirect", "flightOTA", "hotelDirect", "hotelOTA", "fitness", "transport", "fuel", "cinema"]
SW_GURU = {"L1": .03, "L2": .04, "L3": .06}
SW_GURU_CAP = {"L1": 500, "L2": 1200, "L3": 2200}
SW_WEWA_CATS = {"overseas": SW_FX5, "mobilePay": ["mobilePay"], "travel": ["flightDirect", "flightOTA", "hotelDirect", "hotelOTA"]}
SW_WEWA_Q3 = {"start": "2026-07-01", "end": "2026-09-30", "scs": SW_FX4}
SW_NO_RENT = {"ae_explorer", "ae_plat_cc", "ae_plat_charge", "ae_blue", "bea_jcb", "aeon_purple_jcb"}
SW_RENT_FEE_OVERRIDE = {"ds_ba": .019, "ds_ana": .015, "ds_oneplus": .015, "ds_myauto": .019, "ds_kitty": .019, "fubon_in": .019,
                        "fubon_insb": .019, "fubon_plat": .019, "fubon_infinite": .019, "sim_card": .015, "sim_world": .015}
SW_PULSE_PROMO_END, SW_DS_TRAVEL_PROMO_END = "2026-12-31", "2026-04-19"
SW_REG_KEYS = ["everyMileReg", "pulseReg", "aeExplorerReg", "aeChargeReg", "mmpowerReg", "travelPlusReg",
               "dbsEminentReg", "beaWorldReg", "ccbEyeReg", "wewaQ3Reg"]
_HKT = timezone(timedelta(hours=8))

def sw_today():
    return datetime.now(_HKT).date().isoformat()

def sw_vs_norm(e):
    if not e:
        return dict(SW_VS0)
    if isinstance(e, str):
        return dict(SW_VS0) if e == "none" else {**SW_VS0, e: 5}
    if isinstance(e, list):
        a = [x for x in e if x and x != "none"]
        if not a:
            return dict(SW_VS0)
        n, t = 5 // len(a), 5 - (5 // len(a)) * len(a)
        o = dict(SW_VS0)
        for i, k in enumerate(a):
            o[k] = n + (1 if i < t else 0)
        return o
    return {**SW_VS0, **e} if isinstance(e, dict) else dict(SW_VS0)

def sw_vs_slots(vs, sc):
    t = sw_vs_norm(vs)
    for k, scs in SW_VS_CB.items():
        if sc in scs:
            return t.get(k) or 0
    return 0

def sw_guru_blend(base, g, amt, rem):
    if rem is None or rem <= 0:
        return base
    r = rem / g
    return base + g if amt <= r else (r * (base + g) + (amt - r) * base) / amt

def sw_em_tier(amt, q):
    if q is None or amt <= 0:
        return .025
    if q >= 15000:
        return .01
    if q + amt <= 15000:
        return .025
    n = 15000 - q
    return (.025 * n + (amt - n) * .01) / amt

def sw_rent_fee(card):
    if card["id"] in SW_RENT_FEE_OVERRIDE:
        return SW_RENT_FEE_OVERRIDE[card["id"]]
    net = card.get("net")
    if not net:
        return .02
    return 0 if "Amex" in net else .016 if "Mastercard" in net else .02

def sw_mox_unlocked_mpd():
    return 4 if "2026-06-30" >= sw_today() else 5

def _reg_false(p, k):      # JS `p && p.k === false`
    return bool(p) and p.get(k) is False

def _reg_off(p, k):        # JS `p && !p.k`
    return bool(p) and not p.get(k)

def sw_rate_g(card, a, amt, cur, k):
    v = a
    p, t, r, o, l, n = k.get("regs"), k.get("guru"), k.get("moxTier"), k.get("dbsLfFx"), k.get("wewaCat"), k.get("vs")
    g, f = amt or 0, cur or ""
    b, y, _ = k.get("guruRemainingRc"), k.get("emFxQuarterSpent"), k.get("hsbcCat")
    cid = card["id"]
    if f in ("HKD", "") and a in ("hotelOTA", "flightOTA") and (card.get("otaFromFXcb") or {}).get(a):
        a = "onlineHKD"
    if cid == "ae_explorer" and a in SW_AE_EXPLORER_SCS and _reg_false(p, "aeExplorerReg"):
        return .006
    if cid == "ae_plat_charge" and a in SW_FX_ALL and _reg_off(p, "aeChargeReg"):
        return .008 if a in SW_FX5 else .004
    if cid == "hs_mmpower" and _reg_off(p, "mmpowerReg") or cid == "hs_travel" and _reg_off(p, "travelPlusReg"):
        return .004
    if cid in ("dbs_eminent_vs", "dbs_eminent_plat") and a in ("dining", "medical", "fitness") and (_reg_off(p, "dbsEminentReg") or 0 < g < 300):
        return .01
    if cid == "bea_world" and _reg_off(p, "beaWorldReg"):
        return .004
    if cid == "ccb_eye" and a == "dining" and _reg_off(p, "ccbEyeReg"):
        return .02
    if cid == "ccb_eye" and a == "dining" and 0 < g < 500:
        return .04
    if cid in ("mox_cb", "mox_miles") and a in ("octopus", "octopusManual"):
        return 0
    if cid == "mox_cb" and r:
        return .03 if a == "supermarket" else .02
    if cid == "mox_miles" and r:
        return .04 / sw_mox_unlocked_mpd()
    if cid == "sc_smart" and p and p.get("scSmartTier"):
        if p["scSmartTier"] == "low":
            return 0
        if p["scSmartTier"] == "high":
            return .012
    if cid == "dbs_live":
        if o == "none":
            return .01 if a == "onlineFX" else .004
        if o == "fx" and a == "onlineFX":
            return .06
        if o == "fx" and a == "onlineHKD":
            return .004
        if o == "travel" and v in ("flightDirect", "flightOTA", "hotelDirect", "hotelOTA"):
            return .05
        if o == "travel" and a == "onlineFX":
            return .01
        if o == "travel" and a == "onlineHKD":
            return .004
    if cid in ("ds_wewa_vs", "ds_wewa_up"):
        if isinstance(l, dict):
            cat = l.get(cid)
            cat = "none" if cat is None else cat
        else:
            cat = l
        n2 = .04 if a in SW_WEWA_CATS.get(cat or "overseas", []) else .004
        today = sw_today()
        if a in SW_WEWA_Q3["scs"] and SW_WEWA_Q3["start"] <= today <= SW_WEWA_Q3["end"] and not _reg_false(p, "wewaQ3Reg"):
            return .1
        return n2 + .05 if cid == "ds_wewa_up" and a in ("travelJKSTA", "travelTW", "travelCN") and SW_DS_TRAVEL_PROMO_END >= today else n2
    if cid == "ds_earnmore" and a in ("travelJKSTA", "travelTW", "travelCN") and SW_DS_TRAVEL_PROMO_END >= sw_today():
        return .07
    if cid == "hsbc_everymile" and a in SW_FX5:
        e = .01 if _reg_off(p, "everyMileReg") else sw_em_tier(g, y)
        if not t or t == "none" or a == "onlineFX":
            return e
        n2 = SW_GURU[t]
        return sw_guru_blend(e, n2, g, b) if b is not None else e + n2
    if cid in SW_HSBC_FAMILY:
        r2 = (sw_vs_norm(n).get(_) or 0) if _ else sw_vs_slots(n, a)
        pulse_on = SW_PULSE_PROMO_END >= sw_today() and not _reg_false(p, "pulseReg")
        if cid == "hsbc_pulse" and a == "onlineFX" and f == "CNY":
            e = (1 + r2) * .004
            return e + .02 if pulse_on else e
        if a in SW_FX4:
            n2 = (4 + r2) * .004 if cid == "hsbc_vs" else (1 + r2) * .004
            if cid == "hsbc_pulse" and a == "travelCN" and pulse_on:
                n2 += .02
            if t and t != "none":
                e = SW_GURU[t]
                return sw_guru_blend(n2, e, g, b) if b is not None else n2 + e
            return n2
        if r2 > 0:
            return (4 + r2) * .004 if cid == "hsbc_vs" else (1 + r2) * .004
        if cid == "hsbc_vs" and (_ or a in SW_VS_BONUS_SCS):
            return .016
    return (card.get("cashback") or {}).get(a) or 0

def sw_rate(card, sc, amt, cur, k=None):
    if sc == "rent" and card["id"] in SW_NO_RENT:
        return 0
    f = sw_rate_g(card, sc, amt, cur, k or {})
    return max(0, f - sw_rent_fee(card)) if sc == "rent" else f

def sw_add_year(d):
    """JS `setMonth(+12)` semantics: same day next year, Feb 29 overflows to Mar 1."""
    y, m, dd = (int(x) for x in d.split("-"))
    try:
        return date(y + 1, m, dd).isoformat()
    except ValueError:
        return (date(y + 1, m, 1) + timedelta(days=dd - 1)).isoformat()

def sw_guru_window(sw):
    """Active Travel Guru year (app's hz memo): cap, guru rate, and the date window whose FX logs count."""
    start, guru = sw.get("guruStartDate") or "", sw.get("guru")
    if not guru or guru == "none" or not re.match(r"^\d{4}-\d{2}-\d{2}$", start):
        return None
    end, today = sw_add_year(start), sw_today()
    if today < start or today >= end:
        return {"active": False}
    bd = sw.get("guruRcBaselineDate") or ""
    return {"active": True, "start": start, "from": bd if start <= bd < end else start, "end": end,
            "cap": SW_GURU_CAP[guru], "rate": SW_GURU[guru], "baseline": float(sw.get("guruRcBaseline") or 0)}

# ====================================================================================================
# END SwipeWhich-derived rate engine
# ====================================================================================================

def sw_quarter_of(day):
    y, q = int(day[:4]), (int(day[5:7]) - 1) // 3
    return f"{y}-{3 * q + 1:02d}-01", (f"{y + 1}-01-01" if q == 3 else f"{y}-{3 * q + 4:02d}-01")

# ----------------------------------------------------------------------------- pipeline
class Converter:
    def __init__(self, cfg, app_data, existing, refresh_rates=False, since=None):
        self.cfg = cfg
        self.refresh_rates = refresh_rates
        self.since = since
        self.refreshed = 0
        self.app = app_data
        self.existing = existing
        self.promos = app_data["cardData"]["cardPromos"]
        self.merchants = app_data["cardData"]["merchantOffers"]
        self.review = []
        # rates the user logged by hand: (cardId, scenario) -> rate; only used to warn when the engine disagrees
        self.learned = {}
        if existing:
            for lg in existing["data"]["sw_data"].get("logs", []):
                k = (lg.get("cardId"), lg.get("scenario"))
                if k not in self.learned and lg.get("amount") and lg.get("rate") is not None:
                    self.learned[k] = lg["rate"]
        # settings the engine runs with: snapshot values overlaid with config.settings (same as merge() writes)
        self.sw_settings = dict(existing["data"]["sw_data"]) if existing else {}
        self.sw_settings.update({k: v for k, v in (cfg.get("settings") or {}).items() if not k.startswith("_")})
        cards_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "swipewhich-cards.json")
        self.cards = {c["id"]: c for c in json.load(open(cards_path, encoding="utf-8"))} if os.path.exists(cards_path) else {}

    # --- 0. engine inputs (mirror index.html swCard / swKnobs / computeEngine) ---
    def card_obj(self, card_id):
        c, p = self.cards.get(card_id, {}), self.promos.get(card_id) or {}
        return {"id": card_id, "issuer": c.get("issuer"), "net": c.get("net"),
                "cashback": p.get("cashback") or {}, "otaFromFXcb": p.get("otaFromFXcb")}

    def knobs(self):
        sw = self.sw_settings
        regs = {k: sw.get(k) is not False for k in SW_REG_KEYS}
        regs["scSmartTier"] = sw.get("scSmartTier") or "mid"
        regs["promoRegs"] = sw.get("promoRegs") or {}
        return {"vs": sw.get("vs") or {}, "guru": sw.get("guru") or "none", "moxTier": bool(sw.get("moxTier")),
                "dbsLfFx": sw.get("dbsLfFx") or "none", "wewaCat": sw.get("wewaCategory") or "none", "regs": regs, "hsbcCat": None}

    def replay_rates(self, rows):
        """Replay snapshot logs + new rows strictly in date order, as if typed into the app one by one
        (mirrors index.html computeEngine). Travel Guru pools all eligible HSBC cards (HSBC T&C 9c): every
        eligible FX row earns the bonus and consumes the shared annual RC cap. config guru_monthly_top_card=true
        re-creates the old, refuted reading (only the month's top FX card earns). EveryMile's FX quarter total
        accumulates in order too. Sets r['_rate_eng']."""
        base, guru = self.knobs(), sw_guru_window(self.sw_settings)
        hsbc_ids = {cid for cid, c in self.cards.items() if c.get("issuer") == "HSBC"}
        regen = {r["_id"] for r in rows}      # snapshot copies of the rows being regenerated must not count twice
        items = [{"day": str(lg.get("day") or lg.get("date") or "")[:10], "cardId": lg.get("cardId"),
                  "scenario": lg.get("scenario"), "amount": float(lg.get("amount") or 0), "row": None}
                 for lg in (self.existing["data"]["sw_data"].get("logs", []) if self.existing else [])
                 if lg.get("id") not in regen]
        items += [{"day": r["Transaction Date"], "cardId": r["_card"], "scenario": r["_sc"],
                   "amount": self.row_hkd(r), "row": r} for r in rows]
        items.sort(key=lambda it: (it["day"], it["row"]["_row"] if it["row"] else 0))
        active = bool(guru and guru["active"])

        def eligible(it):
            return active and it["cardId"] in hsbc_ids and it["scenario"] in SW_FX4 and guru["start"] <= it["day"] < guru["end"]

        top = {}       # month -> card with the highest eligible FX spend that month (whole month, even before the baseline date)
        if active:
            m = defaultdict(lambda: defaultdict(float))
            for it in items:
                if eligible(it):
                    m[it["day"][:7]][it["cardId"]] += it["amount"]
            top = {k: max(v.items(), key=lambda x: x[1])[0] for k, v in m.items()}
        # earns / consumes RC only from the baseline date on; guru_monthly_top_card absent/false -> pooled (T&C 9c)
        top_rule = self.cfg.get("guru_monthly_top_card", False)
        is_guru = lambda it: eligible(it) and it["day"] >= guru["from"] and (not top_rule or top.get(it["day"][:7]) == it["cardId"])
        earned = guru["baseline"] if active else 0.0
        em_q = defaultdict(float)
        for it in items:
            r = it["row"]
            if r is not None:
                k = dict(base)
                if active:
                    if is_guru(it):
                        k["guruRemainingRc"] = max(0, guru["cap"] - min(earned, guru["cap"]))
                    else:
                        k["guru"] = "none"
                if r["_card"] == "hsbc_everymile":
                    k["emFxQuarterSpent"] = em_q[sw_quarter_of(it["day"])[0]]
                cr = self.channel_rule(r)
                if cr and cr.get("rate") == "no-bonus":      # channel without Pulse +2% / 最紅自主, Guru still applies
                    k["regs"] = {**k["regs"], "pulseReg": False}
                    k["vs"] = {}
                r["_rate_eng"] = sw_rate(self.card_obj(r["_card"]), r["_sc"], it["amount"], r["_cur"], k)
            if is_guru(it):
                earned += it["amount"] * guru["rate"]
            if it["cardId"] == "hsbc_everymile" and it["scenario"] in SW_FX5:
                em_q[sw_quarter_of(it["day"])[0]] += it["amount"]

    # --- 1. read + clean -------------------------------------------------------
    def read(self, path):
        rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
        out = []
        for i, r in enumerate(rows):
            r = {k.strip(): (v or "").strip() for k, v in r.items()}
            r["_row"] = i + 2
            r["_desc"] = re.sub(r"\s+", " ", r["Original Description"] or r["Description"]).strip()
            r["_amt"] = float(r["Amount"] or 0)
            r["_hkd"] = float(r["Amount in HKD"] or 0)
            r["_cur"] = r["Currency"].upper()
            out.append(r)
        return out

    def excluded_reason(self, r):
        for pat in self.cfg["exclude_patterns"]:
            if re.search(pat, r["_desc"], re.I):
                return pat
        return None

    # --- 2. refund pairing -----------------------------------------------------
    def pair_refunds(self, rows):
        refunds = [r for r in rows if r["_amt"] > 0 and re.match(r"^RETURN:", r["_desc"], re.I)]
        spends = [r for r in rows if r["_amt"] < 0]
        window = self.cfg.get("refund_window_days", 90)
        dropped = set()
        for rf in refunds:
            rd = date.fromisoformat(rf["Transaction Date"])
            cands = [s for s in spends
                     if id(s) not in dropped and s["Account Name"] == rf["Account Name"]
                     and abs(abs(s["_amt"]) - rf["_amt"]) < 0.005
                     and 0 <= (rd - date.fromisoformat(s["Transaction Date"])).days <= window]
            if cands:
                s = max(cands, key=lambda s: s["Transaction Date"])
                dropped.add(id(s)); dropped.add(id(rf))
                self.note(rf, "refund-paired", f"cancels row {s['_row']}: {s['_desc']}")
                self.note(s, "refunded", f"refund row {rf['_row']}")
            else:
                rf["_neg"] = True     # unmatched refund -> written as a negative log (the app nets it; verified 2026-09-11)
        return [r for r in rows if id(r) not in dropped]

    # --- 3. card map -----------------------------------------------------------
    def card_for(self, r):
        for pat, cid in self.cfg["card_map"].items():
            if re.search(pat, r["Account Name"], re.I):
                return cid
        return None

    # --- 4. scenario classification -------------------------------------------
    PAY_PREFIX = re.compile(r"^(APPLEPAY|SALES:|QR|RETURN:)\s*", re.I)

    def merchant_text(self, r):
        desc = self.PAY_PREFIX.sub("", r["_desc"])
        return f"{r['Merchant Name']} {desc}".lower()

    def classify(self, r, card_id):
        text = self.merchant_text(r)
        cur = r["_cur"]
        # ① user rules (always win)
        for pat, sc in self.cfg.get("merchant_rules", {}).items():
            if re.search(pat, text, re.I):
                return sc, "1:user-rule"
        # ② region: mainland-China spend is a scenario of its own in bank T&Cs
        if cur == "CNY" and re.search(r"\bCHN\b|\bCN\b|shenzhen|beijing|shanghai|guangzhou", r["_desc"], re.I):
            return "travelCN", "2:CNY+CN"
        # ③ SwipeWhich merchant library — whole-word match, longest key wins
        for pat, m, k in self.merchant_keys():
            if pat.search(text) and m.get("sc"):
                return m["sc"][0], f"3:merchant-lib({m['n']})"
        # ④ other foreign currency
        if cur != "HKD":
            online = any(k in text for k in self.cfg.get("online_hints", []))
            return ("onlineFX" if online else self.cfg.get("fx_default", "physicalFX")), f"4:fx({cur})"
        # ⑤ payment-method prefix (HKD only)
        for pat, sc in self.cfg.get("prefix_rules", {}).items():
            if re.match(pat, r["_desc"], re.I):
                return sc, "5:prefix"
        return self.cfg.get("local_default", "local"), "6:fallback"

    def merchant_keys(self):
        """[(regex, merchant, key)] sorted longest key first. Keys: Chinese name, English name
        (>= 4 chars), and alias tokens that are unique in the library, not a stop word (place
        names / generic words, config merchant_alias_stop) and not a bare number. Mirrors
        index.html merchantKeys()."""
        if getattr(self, "_mkeys", None) is not None:
            return self._mkeys
        stop = {t.lower() for t in self.cfg.get("merchant_alias_stop", [])}
        toks = [{t.lower() for t in (m.get("a") or "").split() if len(t) >= 4} for m in self.merchants]
        count = defaultdict(int)
        for ts in toks:
            for t in ts: count[t] += 1
        keys = []
        for m, ts in zip(self.merchants, toks):
            ks = {k.lower() for k in (m.get("n"), m.get("en")) if k and len(k) >= 4}
            ks |= {t for t in ts if count[t] == 1 and t not in stop and not t.isdigit()}
            for k in sorted(ks):
                keys.append((k, m))
        keys.sort(key=lambda x: -len(x[0]))          # stable: equal length keeps library order
        self._mkeys = [(re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])"), m, k) for k, m in keys]
        return self._mkeys

    def validate_scenario(self, card_id, sc):
        cb = (self.promos.get(card_id) or {}).get("cashback") or {}
        if sc in cb:
            return sc, False
        for fb in self.cfg["scenario_fallback"].get(sc, ["local"]):
            if fb in cb:
                return fb, True
        return "local", True

    # --- 5. rate ---------------------------------------------------------------
    def base_rate(self, card_id, sc):
        return ((self.promos.get(card_id) or {}).get("cashback") or {}).get(sc, 0)

    def channel_rule(self, r):
        for cr in self.cfg.get("channel_rules", []):
            if cr["cardId"] == r["_card"] and cr["scenario"] == r["_sc"] and re.search(cr["pattern"], r["_desc"], re.I):
                return cr
        return None

    def rate_for(self, r):
        """Priority (mirrors index.html rowRate): channel rule > config rate_overrides > engine."""
        card_id, sc = r["_card"], r["_sc"]
        cr = self.channel_rule(r)
        if cr:      # "base" = app-data base rate; "no-bonus" = engine without Pulse +2%/最紅自主 (set in replay); or a number
            mode = cr.get("rate")
            if mode == "base":
                rate = self.base_rate(card_id, sc)
            elif mode == "no-bonus":
                rate = r.get("_rate_eng", self.base_rate(card_id, sc))
            else:
                rate = mode
            return rate, f"channel-rule ({cr.get('note', cr['pattern'])})"
        ov = self.cfg.get("rate_overrides", {}).get(card_id, {}).get(sc)
        if ov is not None:
            return ov, "config-override"
        eng = r.get("_rate_eng", self.base_rate(card_id, sc))
        learned = self.learned.get((card_id, sc))
        if learned is not None and abs(learned - eng) > 1e-9:
            return eng, f"engine (you logged {learned} by hand for this card/scenario - check settings)"
        return eng, "engine"

    # --- 6. build log ----------------------------------------------------------
    @staticmethod
    def row_hkd(r):
        """Log amount in HKD: 2 dp, JS rounding; negative for an unmatched refund (mirrors index.html rowHkd)."""
        v = js_round(abs(r["_hkd"]) * 100) / 100
        return -v if r.get("_neg") else v

    def build_log(self, r):
        card_id, sc, layer, fell_back = r["_card"], r["_sc"], r["_layer"], r["_fb"]
        if r.get("_neg"):
            layer += " (unmatched refund -> negative log)"
        rate, rate_src = self.rate_for(r)
        hkd = self.row_hkd(r)
        merchant = r["Merchant Name"] or r["_desc"]
        memo = merchant
        if r["_cur"] != "HKD":
            memo = f"{r['_cur']} {fmt_amount(abs(r['_amt']))} · {merchant}"   # SwipeWhich fx memo convention
        memo = f"{memo} {AUTO_TAG}"
        log = {
            "u": now_ms(),
            "id": r.get("_id") or det_id(r["Account Name"], r["Transaction Date"], r["Amount"], r["_cur"], r["_desc"]),
            "day": r["Transaction Date"],
            "date": f"{r['Transaction Date']}T04:00:00.000Z",
            "memo": memo,
            "rate": rate,
            "miles": 0,
            "amount": hkd,
            "cardId": card_id,
            "rebate": js_round(hkd * rate * 10000) / 10000,
            "isMiles": False,
            "cardName": self.cfg["card_names"].get(card_id, card_id),
            "scenario": sc,
        }
        self.note(r, "converted", f"{card_id} {sc} via {layer}{' (fallback)' if fell_back else ''}; rate {rate} [{rate_src}]", log)
        return log

    # --- review ----------------------------------------------------------------
    def note(self, r, status, detail, log=None):
        self.review.append({
            "row": r["_row"], "date": r["Transaction Date"], "account": r["Account Name"],
            "desc": r["_desc"], "amount": r["_amt"], "cur": r["_cur"], "hkd": r["_hkd"],
            "status": status, "detail": detail,
            "cardId": log["cardId"] if log else "", "scenario": log["scenario"] if log else "",
            "rate": log["rate"] if log else "", "log_id": log["id"] if log else "",
        })

    # --- manual-log dedupe -----------------------------------------------------
    FX_MEMO = re.compile(r"^([A-Z]{3})\s([\d,]+(?:\.\d+)?)")

    def manual_dup(self, r, card_id):
        """A log the user typed by hand (no [auto] tag) that looks like this row."""
        if not self.existing:
            return None
        rd = date.fromisoformat(r["Transaction Date"])
        for lg in self.existing["data"]["sw_data"].get("logs", []):
            if AUTO_TAG in str(lg.get("memo") or "") or lg.get("cardId") != card_id:
                continue
            try:
                ld = date.fromisoformat(str(lg.get("day") or lg.get("date"))[:10])
            except ValueError:
                continue
            if abs((ld - rd).days) > 1.5:
                continue
            m = self.FX_MEMO.match(lg.get("memo") or "")
            if m and m.group(1) == r["_cur"]:
                if abs(float(m.group(2).replace(",", "")) - abs(r["_amt"])) < 0.01:
                    return lg
                continue
            if abs((lg.get("amount") or 0) - abs(r["_hkd"])) <= max(1, abs(r["_hkd"]) * 0.01):
                return lg
        return None

    # --- run -------------------------------------------------------------------
    def run(self, tx_path):
        rows = self.read(tx_path)
        kept = []
        for r in rows:
            why = self.excluded_reason(r)
            if why: self.note(r, "excluded", why); continue
            if not r["Account Name"] or self.card_for(r) is None:
                self.note(r, "no-card-map", "account not in card_map"); continue
            kept.append(r)
        kept = self.pair_refunds(kept)
        existing = {lg.get("id"): lg for lg in (self.existing["data"]["sw_data"].get("logs", []) if self.existing else [])}
        todo = []
        for r in kept:
            if r["_amt"] >= 0 and not r.get("_neg"):
                self.note(r, "credit-skipped", "positive amount not a refund pattern"); continue
            if self.since and r["Transaction Date"] < self.since:
                self.note(r, "before-since", f"older than --since {self.since}"); continue
            r["_card"] = self.card_for(r)
            dup = None if r.get("_neg") else self.manual_dup(r, r["_card"])
            if dup:
                self.note(r, "dup-manual", f"already logged by hand: {dup.get('memo') or dup.get('cardName')}"); continue
            sc, r["_layer"] = self.classify(r, r["_card"])
            r["_sc"], r["_fb"] = self.validate_scenario(r["_card"], sc)
            r["_id"] = det_id(r["Account Name"], r["Transaction Date"], r["Amount"], r["_cur"], r["_desc"])
            old = existing.get(r["_id"])
            if old and old.get("scenario") != r["_sc"]:
                # the app's copy wins (user may have re-categorised it there); it also stays in the replay as-is
                self.note(r, "kept-existing", f"already in SwipeWhich as {old.get('scenario')} (we would say {r['_sc']}); kept"); continue
            todo.append(r)
        self.replay_rates(todo)
        return [self.build_log(r) for r in todo]

    def merge(self, new_logs):
        if self.existing:
            outer = self.existing
        else:
            outer = {"v": 1, "app": "swipewhich", "ts": 0,
                     "data": {"sw_data": {"_v": 12, "own": [], "logs": [], "recurring": [],
                                          "customPromos": [], "customMilestones": [], "cardSettings": {}}}}
        sw = outer["data"]["sw_data"]
        by_id = {lg["id"]: lg for lg in sw.get("logs", [])}
        added = 0
        refreshed = 0
        for lg in new_logs:
            old = by_id.get(lg["id"])
            if old is None:
                by_id[lg["id"]] = lg; added += 1
            elif self.refresh_rates and old.get("rate") != lg["rate"] and old.get("scenario") == lg["scenario"]:
                # app never recomputes stored rebate; keep user's scenario/memo, refresh rate/rebate only
                old.update(rate=lg["rate"], rebate=js_round(old["amount"] * lg["rate"] * 10000) / 10000, u=now_ms()); refreshed += 1
        self.refreshed = refreshed
        sw["logs"] = sorted(by_id.values(), key=lambda x: (x.get("day", ""), x.get("id", 0)))
        own = set(sw.get("own", [])) | {lg["cardId"] for lg in new_logs}
        sw["own"] = sorted(own)
        # user-declared card option / registration settings (not derivable from Planto)
        applied = self.apply_settings(sw)
        sw["_su"] = now_ms()
        outer["ts"] = now_ms()
        return outer, added, applied

    KNOWN_SETTINGS = {
        "everyMileReg", "pulseReg", "aeExplorerReg", "aeChargeReg", "mmpowerReg", "travelPlusReg",
        "dbsEminentReg", "beaWorldReg", "ccbEyeReg", "wewaQ3Reg",
        "vs", "guru", "guruStartDate", "guruRcBaseline", "guruRcBaselineDate", "hsbcDining",
        "scSmartTier", "dbsLfFx", "wewaCategory", "bocMs", "bocMf", "moxTier",
        "promoRegs", "milestoneEnroll", "mileValue", "mode", "enabledExtras",
    }
    def apply_settings(self, sw):
        applied = []
        for k, v in (self.cfg.get("settings") or {}).items():
            if k.startswith("_"):
                continue
            if k not in self.KNOWN_SETTINGS:
                print(f"WARNING: settings.{k} is not a known SwipeWhich option key — written anyway", file=sys.stderr)
            if sw.get(k) != v:
                sw[k] = v; applied.append(k)
        return applied

    @staticmethod
    def settings_summary(sw):
        regs = {k: sw.get(k) for k in sorted(k for k in sw if k.endswith("Reg"))}
        return {
            "registrations": regs,
            "vs (最紅自主)": sw.get("vs"), "guru": sw.get("guru"), "hsbcDining": sw.get("hsbcDining"),
            "scSmartTier": sw.get("scSmartTier"), "promoRegs": sw.get("promoRegs"),
            "milestoneEnroll": sw.get("milestoneEnroll"), "mode": sw.get("mode"), "mileValue": sw.get("mileValue"),
        }

# ----------------------------------------------------------------------------- emit
def emit(outer, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    o = json.loads(json.dumps(outer, ensure_ascii=False))
    o["data"]["sw_data"] = json.dumps(o["data"]["sw_data"], ensure_ascii=False, separators=(",", ":"))
    if isinstance(o["data"].get("sw_ui"), dict):
        o["data"]["sw_ui"] = json.dumps(o["data"]["sw_ui"], ensure_ascii=False, separators=(",", ":"))
    text = json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    open(os.path.join(out_dir, "swipewhich-backup.json"), "w", encoding="utf-8").write(text)
    code = TRANSFER_PREFIX + base64.b64encode(text.encode("utf-8")).decode("ascii")
    open(os.path.join(out_dir, "transfer_code.txt"), "w").write(code)
    return len(text), len(code)

def write_review(review, out_dir):
    path = os.path.join(out_dir, "review.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(review[0].keys()))
        w.writeheader(); w.writerows(sorted(review, key=lambda r: r["row"]))
    return path

def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0],
                                 epilog=DISCLAIMER, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tx", required=True, help="Planto transaction_export CSV")
    ap.add_argument("--existing", help="current SwipeWhich backup .json / transfer code .txt / SW1. string")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--out", default="out")
    ap.add_argument("--app-data", default="app-data.json",
                    help=f"your own copy of {APP_DATA_URL} (download it in a browser; this tool never fetches it)")
    ap.add_argument("--refresh-rates", action="store_true",
                    help="also rewrite rate/rebate of previously imported [auto] logs (same scenario) with the current rate")
    ap.add_argument("--since", help="ignore CSV rows dated before YYYY-MM-DD (incremental runs)")
    a = ap.parse_args()

    print(f"planto2sw · {DISCLAIMER_LINE}")
    cfg = json.load(open(a.config, encoding="utf-8"))
    app_data = load_app_data(a.app_data)
    existing = load_existing(a.existing)
    conv = Converter(cfg, app_data, existing, refresh_rates=a.refresh_rates, since=a.since)
    if existing:
        snap = Converter.settings_summary(existing["data"]["sw_data"])
        print("snapshot settings:", json.dumps(snap, ensure_ascii=False))
        vs = snap["vs (最紅自主)"] or {}
        if not any(vs.values()) and not snap["promoRegs"] and not snap["milestoneEnroll"]:
            print("WARNING: snapshot has no 最紅自主 picks / promo registrations / milestone enrolments — "
                  "is this the latest code from the device where you set them? (config.settings can override)")
    logs = conv.run(a.tx)
    outer, added, applied = conv.merge(logs)
    if applied:
        print("settings applied from config:", applied)
    print("effective settings:", json.dumps(Converter.settings_summary(outer["data"]["sw_data"]), ensure_ascii=False))
    jlen, clen = emit(outer, a.out)
    rpath = write_review(conv.review, a.out)

    from collections import Counter
    st = Counter(r["status"] for r in conv.review)
    print(f"rows: {dict(st)}")
    print(f"logs generated: {len(logs)}, newly added after merge: {added}, rates refreshed: {conv.refreshed}, total logs in backup: {len(outer['data']['sw_data']['logs'])}")
    per = defaultdict(float)
    for lg in logs: per[(lg['cardId'], lg['scenario'])] += lg['amount']
    for (c, s), v in sorted(per.items()): print(f"  {c:16s} {s:12s} HK${v:>10,.2f}")
    print(f"backup json {jlen:,} bytes; transfer code {clen:,} chars -> {a.out}/")
    print(f"review: {rpath}  (grep 'check settings' / 6:fallback / no-card-map before importing)")

if __name__ == "__main__":
    main()
