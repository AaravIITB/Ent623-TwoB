"""Score the engine on the CA-style datasets made by taxmind.synth_ca.

    from taxmind.bench_ca import run
    run("test_data")                     # every folder with a truth.json; prints a report,
                                         # writes test_data/bench_report.json

For each dataset three input variants are run:
    xlsx   books .xlsx + 2B .xlsx for Apr-Jul               (the main variant; full per-case table)
    csv    books .csv  + 2B .xlsx
    json   books .xlsx + Jun 2B official JSON + Apr/May/Jul .xlsx
2B Excel files are named like the firm names them ('GSTR-2B Jun-26.xlsx'); the engine cannot always tell
the month from that, so the period is passed as a hint (period_detected_without_hint reports whether it
could). The combined workbook is loaded as-is to show what the loader does with it (informational).

Scoring (all defensive: unknown Status values, missing attributes and new fields never crash it):
  links       books row <-> 2B row pairs from each Finding's .books / .portal; precision / recall against
              the truth links (a duplicate books line counts as its twin)
  per case    for every truth group: found (all rows in some finding), pair_ok (exactly the truth links,
              none outside), status_ok / action_ok (EXPECT below), itc_ok (engine ITC within Rs 1 / 0.5%)
  dropped     truth books rows the loader did not read, or that are in no finding
  itc         engine sum(itc_to_claim, or .reclaim when itc_to_claim is 0) vs truth sum(itc_claim);
              engine res.table4 lines (if present) vs truth table4
  blocked     Sec 17(5): recall on rows the law blocks, false flags on allowed rows (split: profile
              exceptions / look-alikes vs ordinary rows)
  dates       books docs whose doc_date equals the real invoice date (from narration)
  doc types   2B 'Debit' rows read as DN, 'Credit' as CN, 'B2BA' as an amendment
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path

# Expected engine outcome per case, by Status / Action *member name* (values may be reworded).
# "<absent>" = the row appears in no finding. None = any action is acceptable.
M = {"EXACT", "FORMAT_DIFF", "DATE_DIFF"}
_BOOKS_LEFT = {"BOOKS_ONLY", "BOOKS_OLDER"}
_NOITC = {"NO_ITC", "<absent>"}
EXPECT = {
    "exact": (M, {"ACCEPT"}),
    "round_off": (M, {"ACCEPT"}),
    "round_1to6": (M | {"VALUE_DIFF"}, {"ACCEPT"}),
    "taxable_differs": (M | {"VALUE_DIFF"}, {"ACCEPT"}),
    "amount_less_in_2b": ({"VALUE_DIFF"}, {"ACCEPT"}),
    # under the firm's 'reverse' method a 2B excess is accepted and the books amount claimed
    "amount_more_in_2b": ({"VALUE_DIFF"}, {"PENDING", "ACCEPT"}),
    "invno_format": (M, {"ACCEPT"}),
    "invno_typo": (M | {"TYPO"}, {"ACCEPT", "PENDING"}),
    "date_diff": (M, {"ACCEPT"}),
    "invno_missing_narration": (M, {"ACCEPT"}),
    "gstin_missing_name": (M, {"ACCEPT"}),
    "split": ({"SPLIT"}, {"ACCEPT"}),
    "wrong_head": ({"HEAD_MISMATCH"}, {"PENDING"}),
    "other_gstin_same_pan": ({"OTHER_GSTIN"}, {"PENDING"}),
    "prior_fy_current_2b": (M, {"ACCEPT"}),
    "duplicate_in_books": (M | {"BOOKS_DUPLICATE"}, {"ACCEPT", "NONE"}),
    "books_cn_matched": (M, {"ACCEPT"}),
    "books_cn_no_ref": (M | {"PROBABLE"}, {"ACCEPT", "PENDING"}),
    "booked_without_gst": ({"BOOKED_NO_GST", "VALUE_DIFF"}, None),
    "rcm": ({"RCM"} | M, {"NONE"}),          # a pair with a 2B row flagged reverse charge may stay 'Exact' (no IMS action)
    "earlier_2b_reclaim": ({"EARLIER_PERIOD"}, None),
    "late_filer_next_month": ({"LATE_FILED"}, {"NONE"}),
    "prior_fy_not_in_2b": (_BOOKS_LEFT, {"NONE"}),
    "books_only_not_uploaded": (_BOOKS_LEFT, {"NONE"}),
    "books_cn_not_in_2b": ({"BOOKS_ONLY"}, {"NONE"}),
    "billed_to_other_branch": (_BOOKS_LEFT, {"NONE"}),
    "excluded_nongst": (_NOITC, None),
    "excluded_unregistered": (_NOITC, None),
    "excluded_advance": (_NOITC, None),
    "excluded_provision": (_NOITC | {"BOOKS_ADJUSTMENT"}, None),
    "rectification": (_NOITC | {"BOOKS_ADJUSTMENT"}, None),
    # NONE = left for deemed acceptance and reversed in 4(B)(2): the firm's 'reverse' method
    "portal_only_known": ({"PORTAL_ONLY_KNOWN"}, {"PENDING", "NONE"}),
    "portal_only_other_register": ({"PORTAL_ONLY_KNOWN", "PORTAL_ONLY_UNKNOWN"}, {"PENDING", "ACCEPT", "NONE"}),
    "portal_only_unknown": ({"PORTAL_ONLY_UNKNOWN"}, {"REJECT", "PENDING"}),
    "portal_cn_not_booked": ({"PORTAL_ONLY_CN"}, {"PENDING", "ACCEPT", "NONE"}),
    "portal_dn_not_booked": ({"PORTAL_ONLY_KNOWN", "PORTAL_ONLY_UNKNOWN"}, {"PENDING", "ACCEPT", "NONE"}),
    "portal_itc_unavailable": ({"PORTAL_ITC_BLOCKED"}, None),
    "b2ba_amendment": (None, None),
    "other_month_noise": (None, None),
}
NOT_PAIRED_OK = {"excluded_nongst", "excluded_unregistered", "excluded_advance", "excluded_provision", "rectification"}
T4_MAP = {"4(A)(5)": "4A5_total", "4(B)(1)": "4B1_total", "4(B)(2)": "4B2_not_in_books", "4(D)(1)": "4D1_reclaimed",
          "4(D)(2)": "4D2_not_available"}


def _name(x) -> str:
    if x is None:
        return "None"
    return str(getattr(x, "name", None) or getattr(x, "value", None) or x)


def _num(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _eff_itc(f) -> float:
    itc = _num(getattr(f, "itc_to_claim", 0))
    return itc if abs(itc) > 0.005 else _num(getattr(f, "reclaim", 0))


def _pct(a, b):
    return round(100.0 * a / b, 1) if b else None


class _Map:
    """Engine Doc -> truth row id."""

    def __init__(self, truth, variant):
        F = truth["meta"]["files"]
        self.by_src = {}
        self.by_key = defaultdict(list)
        self.rows = {r["rid"]: r for r in truth["rows"]}
        for r in truth["rows"]:
            if r["side"] == "books":
                self.by_src[(r["source"], r["row_ref"])] = r["rid"]
                self.by_src[(f"{F['books_csv']}:csv", r["row_ref"])] = r["rid"]
                self.by_src[(f"{F['combined']}:{F['books_sheet']}", r["row_ref"])] = r["rid"]
            else:
                self.by_src[(r["source"], r["row_ref"])] = r["rid"]
                if r["period"] == truth["meta"]["return_period"]:
                    self.by_src[(f"{F['combined']}:{r['sheet']}", r["row_ref"])] = r["rid"]
                g, no, typ, per = r["key"]
                self.by_key[(g, str(no).strip().upper(), per)].append(r["rid"])
        self.taken = set()
        self.cache = {}

    def rid(self, d):
        k = id(d)
        if k in self.cache:
            return self.cache[k]
        src, ref = str(getattr(d, "source", "") or ""), str(getattr(d, "row_ref", "") or "")
        rid = self.by_src.get((src, ref))
        if rid is None and src.lower().split(":")[0].endswith(".json"):
            key = (str(getattr(d, "supplier_gstin", "")), str(getattr(d, "doc_no", "")).strip().upper(),
                   str(getattr(d, "period", "")))
            for c in self.by_key.get(key, []):
                if c not in self.taken:
                    rid = c
                    self.taken.add(c)
                    break
        self.cache[k] = rid
        return rid


def _load_variant(ddir: Path, truth, variant):
    from .loaders import load_file
    from .models import Side
    F = truth["meta"]["files"]
    ret = truth["meta"]["return_period"]
    books_file = ddir / (F["books_csv"] if variant == "csv" else F["books_xlsx"])
    books, notes = load_file(books_file, Side.BOOKS, "B")
    portal = []
    for i, per in enumerate(truth["meta"]["months"]):
        if variant == "json" and per in F.get("portal_json", {}):
            p, n = load_file(ddir / F["portal_json"][per], Side.PORTAL, f"P{i + 1}-", per)
        else:
            p, n = load_file(ddir / F["portal_xlsx"][per], Side.PORTAL, f"P{i + 1}-", per)
        portal += p
        notes += n
    return books, portal, notes, ret


# What a firm would set for each client before running (the engine's client settings). The answer key
# follows the firm's own 3B method (2B bills not in books are reversed in 4(B)(2), reclaimed when booked),
# which is the engine's 'reverse' policy.
PROFILE_SETTINGS = {
    "a_manufacturer_plant": {"line_of_business": ""},
    "b_trader": {"line_of_business": ""},
    "c_hotel_restaurant": {"line_of_business": "hotel,caterer"},
    "d_works_contractor": {"line_of_business": "works_contractor"},
    "e_car_dealer": {"line_of_business": "vehicle_dealer"},
    "f_professional_multi_gstin": {"line_of_business": ""},
}


def score(ddir, variant="xlsx", detail=True, use_settings=True) -> dict:
    from .config import Config
    from .engine import reconcile
    from .prepare import load_vendor_master
    ddir = Path(ddir)
    truth = json.loads((ddir / "truth.json").read_text())
    t0 = time.time()
    books, portal, notes, ret = _load_variant(ddir, truth, variant)
    t1 = time.time()
    cfg, master = Config(), None
    if use_settings:
        st = PROFILE_SETTINGS.get(truth["meta"]["profile"], {})
        cfg = Config(line_of_business=st.get("line_of_business", ""), not_in_books_policy="reverse",
                     client_gstin=truth["meta"].get("client_gstin", ""))
        vm = truth["meta"]["files"].get("vendor_master")
        if vm and (ddir / vm).exists():
            master = load_vendor_master(ddir / vm)
    res = reconcile(books, portal, period=ret, client=truth["meta"]["client_name"], notes=notes, cfg=cfg,
                    vendor_master=master)
    t2 = time.time()
    mp = _Map(truth, variant)
    groups = {g["gid"]: g for g in truth["groups"]}
    rows = mp.rows
    gid_of = {r["rid"]: r["gid"] for r in truth["rows"]}

    # canonical ids: a duplicate books line is its twin
    canon = {}
    for g in truth["groups"]:
        if g["case"] == "duplicate_in_books" and g["books"]:
            for b in g["books"]:
                canon[b] = g["books"][0]

    def cn(r):
        return canon.get(r, r)

    findings = list(getattr(res, "findings", []) or [])
    in_finding = defaultdict(list)       # rid -> findings
    elinks = set()
    unmapped = 0
    owner = {}
    for f in findings:
        fb = [mp.rid(d) for d in (getattr(f, "books", None) or [])]
        fp = [mp.rid(d) for d in (getattr(f, "portal", None) or [])]
        unmapped += sum(1 for x in fb + fp if x is None)
        for x in fb + fp:
            if x:
                in_finding[x].append(f)
        for b in fb:
            for p in fp:
                if b and p:
                    elinks.add((cn(b), p))
        first = next((x for x in fb + fp if x), None)
        owner[id(f)] = gid_of.get(first)
    tlinks = set()
    for g in truth["groups"]:
        for b in g["books"]:
            for p in g["portal"]:
                tlinks.add((cn(b), p))
    tp = len(elinks & tlinks)
    loaded_b = {mp.rid(d) for d in books} - {None}
    loaded_p = {mp.rid(d) for d in portal} - {None}

    # per-group evaluation
    eng_itc = defaultdict(float)
    for f in findings:
        if owner.get(id(f)):
            eng_itc[owner[id(f)]] += _eff_itc(f)
    per_case = defaultdict(lambda: Counter())
    fails = defaultdict(list)
    status_seen = defaultdict(Counter)
    traits_tab = defaultdict(Counter)
    itc_case = defaultdict(lambda: [0.0, 0.0])
    blk = Counter()
    blk_by_rule = defaultdict(Counter)
    blk_fail = []
    noise_paired = 0
    for g in truth["groups"]:
        case = g["case"]
        rids = g["books"] + g["portal"]
        fs = {id(f): f for r in rids for f in in_finding.get(r, [])}.values()
        if case == "other_month_noise":
            if any(getattr(f, "books", None) for f in fs):
                noise_paired += 1
            continue
        st = {_name(getattr(f, "status", None)) for f in fs} or {"<absent>"}
        if any(r not in in_finding for r in rids) and fs:
            st = st | {"<absent>"}
        ac = {_name(getattr(f, "action", None)) for f in fs} or {"<none>"}
        allowed_s, allowed_a = EXPECT.get(case, (None, None))
        if allowed_s is not None and M <= allowed_s and "taxable_inflated" in g["traits"]:
            allowed_s = allowed_s | {"VALUE_DIFF"}      # tax agrees; books 'Taxable' carries non-GST charges
        status_ok = allowed_s is None or st <= allowed_s
        if case == "duplicate_in_books":
            status_ok = status_ok and "BOOKS_DUPLICATE" in st
        action_ok = allowed_a is None or not fs or ac <= allowed_a
        if allowed_a is not None and not fs:
            action_ok = False
        # links touching this group's rows
        mine = set(cn(r) for r in rids)
        g_el = {(b, p) for (b, p) in elinks if b in mine or p in mine}
        g_tl = {(cn(b), p) for b in g["books"] for p in g["portal"]}
        pair_ok = g_el == g_tl
        found = all(r in in_finding for r in rids)
        if case in NOT_PAIRED_OK:
            found = True
        t_itc = _num(g["itc_claim"]["total"])
        e_itc = round(eng_itc.get(g["gid"], 0.0), 2)
        itc_ok = abs(e_itc - t_itc) <= max(1.0, 0.005 * abs(t_itc))
        ok = pair_ok and status_ok and action_ok and itc_ok
        c = per_case[case]
        c["n"] += 1
        c["found"] += found
        c["pair_ok"] += pair_ok
        c["status_ok"] += status_ok
        c["action_ok"] += action_ok
        c["itc_ok"] += itc_ok
        c["ok"] += ok
        itc_case[case][0] += t_itc
        itc_case[case][1] += e_itc
        status_seen[case][" + ".join(sorted(st))] += 1
        for t in g["traits"]:
            traits_tab[t]["n"] += 1
            traits_tab[t]["ok"] += ok
        if not ok and len(fails[case]) < 4:
            f0 = next(iter(fs), None)
            fails[case].append({"gid": g["gid"], "rows": rids[:4], "statuses": sorted(st), "actions": sorted(ac),
                                "pair_ok": pair_ok, "itc_truth": t_itc, "itc_engine": e_itc,
                                "traits": g["traits"], "reason": str(getattr(f0, "reason", ""))[:200] if f0 else ""})
        # blocked credit, only for groups the client booked
        if g["books"] and case not in NOT_PAIRED_OK and not case.startswith("books_cn"):
            flagged = set()
            for f in fs:
                for fl in getattr(f, "blocked", None) or []:
                    rid_ = str(getattr(fl, "rid", fl))
                    flagged.add("food" if rid_ == "hotel_mixed" else rid_)
            want = g["blocked"]
            if want:
                blk["should_flag"] += 1
                blk_by_rule[want]["n"] += 1
                hit = want in flagged
                blk["caught"] += hit
                blk_by_rule[want]["caught"] += hit
                if not hit and len(blk_fail) < 40:
                    blk_fail.append({"gid": g["gid"], "want": want, "got": sorted(flagged), "category": g["category"]})
            else:
                key = "exception_rows" if g["blocked_exception"] else "plain_rows"
                blk[key] += 1
                if flagged:
                    blk[key + "_flagged"] += 1
                    blk_by_rule[f"false:{'/'.join(sorted(flagged))}"]["n"] += 1
                    if len(blk_fail) < 40:
                        blk_fail.append({"gid": g["gid"], "want": "", "got": sorted(flagged), "category": g["category"],
                                         "exception_of": g["lookalike_of"]})

    # rows dropped / never reported
    books_truth = [r for r in truth["rows"] if r["side"] == "books"]
    not_loaded = [r for r in books_truth if r["rid"] not in loaded_b]
    no_finding = [r for r in books_truth if r["rid"] in loaded_b and r["rid"] not in in_finding]
    drop_case = Counter(groups[r["gid"]]["case"] for r in not_loaded + no_finding)
    gst_drop = [r for r in not_loaded + no_finding if groups[r["gid"]]["case"] not in NOT_PAIRED_OK]
    ret_rows = [r for r in truth["rows"] if r["side"] == "portal" and r["period"] == truth["meta"]["return_period"]]
    portal_no_finding = sum(1 for r in ret_rows if r["rid"] not in in_finding)

    # dates and doc types
    date_ok = date_n = 0
    for d in books:
        rid = mp.rid(d)
        if rid and rows[rid].get("inv_date"):
            date_n += 1
            dd = getattr(d, "doc_date", None)
            date_ok += bool(dd) and dd.isoformat() == rows[rid]["inv_date"]
    dtype = Counter()
    for d in portal:
        rid = mp.rid(d)
        if not rid:
            continue
        r = rows[rid]
        want = r["key"][2]
        got = _name(getattr(d, "doc_type", None))
        if r.get("amends"):
            dtype["b2ba_n"] += 1
            dtype["b2ba_ok"] += bool(getattr(d, "amends", ""))
        elif want == "DN":
            dtype["dn_n"] += 1
            dtype["dn_ok"] += got in ("DEBIT_NOTE", "DN")
        elif want == "CN":
            dtype["cn_n"] += 1
            dtype["cn_ok"] += got in ("CREDIT_NOTE", "CN")
        if r["period"] == truth["meta"]["return_period"] and r["itc_available"] is False:
            dtype["itcn_n"] += 1
            dtype["itcn_ok"] += getattr(d, "itc_available", None) is False

    t_total = round(sum(_num(g["itc_claim"]["total"]) for g in truth["groups"]), 2)
    e_total = round(sum(_eff_itc(f) for f in findings), 2)
    t_blocked = round(sum(_num(g["itc_claim"]["total"]) for g in truth["groups"] if g["blocked"]
                          and g["bucket"] in ("4A5_2b", "4A5_reclaim")), 2)
    eng_t4 = {}
    t4 = getattr(res, "table4", None)
    if isinstance(t4, dict):
        for ln in t4.get("lines", []) or []:
            code = str(getattr(ln, "code", "") or (ln.get("code") if isinstance(ln, dict) else ""))
            amts = getattr(ln, "amounts", None) if not isinstance(ln, dict) else ln.get("amounts")
            if code in T4_MAP and isinstance(amts, dict):
                eng_t4[code] = round(sum(_num(v) for v in amts.values()), 2)
    t4cmp = {code: {"truth": truth["table4"][k]["total"], "engine": eng_t4.get(code)} for code, k in T4_MAP.items()}

    out = {
        "dataset": ddir.name, "variant": variant,
        "rows": {"books_truth": len(books_truth), "books_loaded": len(loaded_b), "portal_loaded": len(loaded_p),
                 "portal_truth": sum(1 for r in truth["rows"] if r["side"] == "portal"),
                 "findings": len(findings), "unmapped_docs_in_findings": unmapped},
        "links": {"truth": len(tlinks), "engine": len(elinks), "correct": tp,
                  "precision": _pct(tp, len(elinks)), "recall": _pct(tp, len(tlinks)),
                  "noise_rows_paired_with_june_books": noise_paired},
        "dropped": {"books_not_loaded": len(not_loaded), "books_loaded_but_in_no_finding": len(no_finding),
                    "gst_rows_dropped": len(gst_drop), "by_case": dict(drop_case.most_common()),
                    "return_month_2b_rows_in_no_finding": portal_no_finding},
        "itc": {"truth_claim_total": t_total, "engine_claim_total": e_total, "diff": round(e_total - t_total, 2),
                "truth_reclaim_4D1": truth["table4"]["4D1_reclaimed"]["total"],
                "engine_reclaim": round(sum(_num(getattr(f, "reclaim", 0)) for f in findings), 2),
                "truth_17_5_reversal_4B1": t_blocked,
                "summary_itc_to_claim": (getattr(res, "summary", {}) or {}).get("itc_to_claim"),
                "table4": t4cmp,
                "by_case": {k: {"truth": round(v[0], 2), "engine": round(v[1], 2)} for k, v in sorted(itc_case.items())}},
        "blocked": {"should_flag": blk["should_flag"], "caught": blk["caught"],
                    "recall": _pct(blk["caught"], blk["should_flag"]),
                    "plain_rows": blk["plain_rows"], "plain_false_flags": blk["plain_rows_flagged"],
                    "plain_false_flag_rate": _pct(blk["plain_rows_flagged"], blk["plain_rows"]),
                    "exception_rows": blk["exception_rows"], "exception_false_flags": blk["exception_rows_flagged"],
                    "exception_false_flag_rate": _pct(blk["exception_rows_flagged"], blk["exception_rows"]),
                    "by_rule": {k: dict(v) for k, v in sorted(blk_by_rule.items())},
                    "failures": blk_fail if detail else []},
        "dates": {"books_with_invoice_date": date_n, "doc_date_equals_invoice_date": date_ok,
                  "pct": _pct(date_ok, date_n)},
        "doc_types": dict(dtype),
        "per_case": {k: dict(v) for k, v in sorted(per_case.items())},
        "status_seen": {k: dict(v.most_common(5)) for k, v in sorted(status_seen.items())},
        "traits": {k: {"n": v["n"], "ok_pct": _pct(v["ok"], v["n"])} for k, v in sorted(traits_tab.items())},
        "failures": dict(fails) if detail else {},
        "runtime_s": {"load": round(t1 - t0, 3), "reconcile": round(t2 - t1, 3)},
        "notes": list(getattr(res, "notes", []) or [])[:30],
    }
    return out


def _period_detection(ddir: Path, truth) -> dict:
    from .loaders import load_file
    from .models import Side
    out = {}
    F = truth["meta"]["files"]
    for per in truth["meta"]["months"]:
        try:
            docs, _ = load_file(ddir / F["portal_xlsx"][per], Side.PORTAL, "X")
            got = Counter(getattr(d, "period", "") for d in docs).most_common(1)
            out[per] = got[0][0] if got else ""
        except Exception as e:      # noqa: BLE001
            out[per] = f"error: {e}"
    return {"expected_vs_detected": out, "all_ok": all(k == v for k, v in out.items())}


def _combined(ddir: Path, truth) -> dict:
    from .loaders import load_file
    from .models import Side
    F = truth["meta"]["files"]
    out = {}
    for side in (Side.BOOKS, Side.PORTAL):
        try:
            docs, notes = load_file(ddir / F["combined"], side, "K")
            out[side.value] = dict(Counter(str(getattr(d, "source", "")).split(":", 1)[-1] for d in docs))
        except Exception as e:      # noqa: BLE001
            out[side.value] = f"error: {e}"
    return out


def run(data_dir="test_data", variants=("xlsx", "csv", "json"), write=True, verbose=True) -> dict:
    data_dir = Path(data_dir)
    dirs = [data_dir] if (data_dir / "truth.json").exists() else sorted(p for p in data_dir.iterdir()
                                                                       if (p / "truth.json").exists())
    report = {"datasets": {}, "aggregate": {}}
    agg = defaultdict(Counter)
    agg_itc = defaultdict(lambda: [0.0, 0.0])
    for d in dirs:
        truth = json.loads((d / "truth.json").read_text())
        entry = {"meta": {k: truth["meta"][k] for k in ("profile", "title", "books_rows", "portal_rows", "case_counts")}}
        for v in variants:
            try:
                entry[v] = score(d, v, detail=(v == "xlsx"))
            except Exception as e:      # noqa: BLE001 - a crashing variant is itself a finding
                import traceback
                entry[v] = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
        entry["period_detection"] = _period_detection(d, truth)
        entry["combined_workbook"] = _combined(d, truth)
        report["datasets"][d.name] = entry
        main = entry.get("xlsx", {})
        for case, c in (main.get("per_case") or {}).items():
            agg[case].update(c)
        for case, v in ((main.get("itc") or {}).get("by_case") or {}).items():
            agg_itc[case][0] += v["truth"]
            agg_itc[case][1] += v["engine"]
    report["aggregate"] = {k: {**dict(v), "ok_pct": _pct(v["ok"], v["n"]),
                               "itc_truth": round(agg_itc[k][0], 2), "itc_engine": round(agg_itc[k][1], 2)}
                           for k, v in sorted(agg.items())}
    if write:
        (data_dir / "bench_report.json").write_text(json.dumps(report, indent=1, default=str))
    if verbose:
        print(format_report(report))
    return report


def _f(x):
    return "-" if x is None else (f"{x:,.0f}" if isinstance(x, (int, float)) else str(x))


def format_report(report) -> str:
    L = []
    L.append("TaxMind on CA-style test data (bench_ca)")
    L.append("=" * 100)
    for name, e in report["datasets"].items():
        L.append(f"\n## {name}: {e['meta']['title']}  (books {e['meta']['books_rows']} rows; 2B {e['meta']['portal_rows']})")
        for v in ("xlsx", "csv", "json"):
            s = e.get(v)
            if not s:
                continue
            if "error" in s:
                L.append(f"  [{v}] CRASH {s['error']}")
                continue
            lk, dr, it, bl = s["links"], s["dropped"], s["itc"], s["blocked"]
            L.append(f"  [{v:4}] links P/R {lk['precision']}%/{lk['recall']}% ({lk['correct']}/{lk['truth']}); "
                     f"books not loaded {dr['books_not_loaded']}, in no finding {dr['books_loaded_but_in_no_finding']} "
                     f"(GST rows {dr['gst_rows_dropped']}); ITC engine {_f(it['engine_claim_total'])} vs truth "
                     f"{_f(it['truth_claim_total'])}; 17(5) recall {bl['recall']}%, false flags plain "
                     f"{bl['plain_false_flag_rate']}% / exceptions {bl['exception_false_flag_rate']}%; "
                     f"{s['runtime_s']['reconcile']}s")
        s = e.get("xlsx")
        if s and "error" not in s:
            L.append(f"  dates from narration: {s['dates']['pct']}% of {s['dates']['books_with_invoice_date']}; doc types {s['doc_types']}")
            L.append(f"  period detected without hint: {e['period_detection']['expected_vs_detected']}")
            L.append(f"  combined workbook read as: {e['combined_workbook']}")
            L.append(f"  Table 4 truth vs engine: " + "; ".join(
                f"{k} {_f(v['truth'])} / {_f(v['engine'])}" for k, v in s["itc"]["table4"].items()))
            if s["dropped"]["by_case"]:
                L.append(f"  dropped/unreported books rows by case: {s['dropped']['by_case']}")
    L.append("\n## Per case, all datasets (xlsx variant): n | ok% | pair% | status% | action% | itc% | ITC truth / engine")
    for case, v in report["aggregate"].items():
        n = v.get("n", 0)
        L.append(f"  {case:28} {n:5} | {_pct(v.get('ok', 0), n):5} | {_pct(v.get('pair_ok', 0), n):5} | "
                 f"{_pct(v.get('status_ok', 0), n):5} | {_pct(v.get('action_ok', 0), n):5} | "
                 f"{_pct(v.get('itc_ok', 0), n):5} | {_f(v['itc_truth'])} / {_f(v['itc_engine'])}")
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    run(sys.argv[1] if len(sys.argv) > 1 else "test_data")
