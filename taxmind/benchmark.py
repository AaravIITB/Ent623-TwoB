"""Measure the engine against (a) known answers and (b) a Tally-style baseline.

Baseline = what a rule-based exact matcher does today (TallyPrime documents
these options): same GSTIN, invoice number equal after ignoring leading zeros
and special characters, amounts within tolerance. Everything else lands in a
'mismatch' bucket for a person to investigate from scratch.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .config import Config
from .models import Action, Confidence, Owner, Side


def tally_key(no: str) -> str:
    s = re.sub(r"[^0-9A-Z]", "", str(no).upper())
    return re.sub(r"\d+", lambda m: m.group(0).lstrip("0") or "0", s)


def baseline(books, target, cfg: Config) -> dict:
    tol = cfg.amount_tolerance
    idx = defaultdict(list)
    for p in target:
        idx[(p.supplier_gstin, tally_key(p.doc_no), p.doc_type)].append(p)
    used, matched = set(), 0
    for b in books:
        for p in idx.get((b.supplier_gstin, tally_key(b.doc_no), b.doc_type), []):
            if p.uid in used:
                continue
            if abs(p.taxable - b.taxable) <= tol and abs(p.tax - b.tax) <= tol:
                used.add(p.uid)
                matched += 1
                break
    return {"auto_matched": matched,
            "left_for_a_person": (len(books) - matched) + (len(target) - matched),
            "explained": 0}


def _dkey(d, side):
    k = [d.supplier_gstin, d.doc_no, d.doc_date.isoformat() if d.doc_date else "", round(d.tax, 2),
         d.doc_type.value]
    if side == Side.PORTAL:
        k.append(d.period)
    return tuple(k)


def evaluate(res, books, portal, truth_path) -> dict:
    truth = json.loads(Path(truth_path).read_text())
    bidx, pidx = defaultdict(list), defaultdict(list)
    for d in books:
        bidx[_dkey(d, Side.BOOKS)].append(d.uid)
    for d in portal:
        pidx[_dkey(d, Side.PORTAL)].append(d.uid)
    finding_of = {}
    for f in res.findings:
        for d in f.books + f.portal:
            finding_of[d.uid] = f
    case_of = {}
    per_type = defaultdict(lambda: [0, 0])
    failures = []
    blk, blk_fail = Counter(), []
    for i, c in enumerate(truth["cases"]):
        b_uids = [u for k in c["books"] for u in bidx.get(tuple(k[:5]), [])]
        p_uids = [u for k in c["portal"] for u in pidx.get(tuple(k), [])]
        b_uids = list(dict.fromkeys(b_uids))
        p_uids = list(dict.fromkeys(p_uids))
        for u in b_uids + p_uids:
            case_of[u] = i
        fs = {id(finding_of[u]): finding_of[u] for u in b_uids + p_uids if u in finding_of}.values()
        statuses = {f.status.value for f in fs}
        ok = bool(fs) and statuses <= set(c["expected"])
        # pairing check: every finding must only contain this case's documents
        for f in fs:
            if any(case_of.get(d.uid, i) != i for d in f.books + f.portal):
                ok = False
        flagged = {fl.rid for f in fs for fl in f.blocked}
        flagged |= {"food"} if "hotel_mixed" in flagged else set()
        want = c.get("blocked", "")
        if want:
            blk["should_flag"] += 1
            blk["flagged"] += want in flagged
            if want not in flagged:
                blk_fail.append({"case": c["case"], "want": want, "got": sorted(flagged), "docs": c["books"]})
        elif flagged:
            blk["false_flags"] += 1
            blk_fail.append({"case": c["case"], "want": "", "got": sorted(flagged), "docs": c["books"] + c["portal"]})
        per_type[c["case"]][1] += 1
        if ok:
            per_type[c["case"]][0] += 1
        else:
            failures.append({"case": c["case"], "expected": c["expected"], "got": sorted(statuses),
                             "docs": [d for d in c["books"] + c["portal"]]})
    # wrong pairings (documents from two different cases in one finding)
    wrong, wrong_accepts = 0, 0
    for f in res.findings:
        ids = {case_of.get(d.uid) for d in f.books + f.portal}
        if len(f.books) and len(f.portal) and len(ids) > 1:
            wrong += 1
            if f.action == Action.ACCEPT:
                wrong_accepts += 1
    total = sum(v[1] for v in per_type.values())
    correct = sum(v[0] for v in per_type.values())
    return {"cases": total, "correct": correct, "accuracy": round(correct / total, 4) if total else 0,
            "wrong_pairings": wrong, "wrong_accepts": wrong_accepts,
            "by_case": {k: f"{v[0]}/{v[1]}" for k, v in sorted(per_type.items())},
            "failures": failures,
            "blocked_credit": {"should_flag": blk["should_flag"], "flagged": blk["flagged"],
                               "recall": round(blk["flagged"] / blk["should_flag"], 4) if blk["should_flag"] else None,
                               "false_flags": blk["false_flags"], "failures": blk_fail}}


def engine_effort(res) -> dict:
    F = res.findings
    auto = [f for f in F if not f.needs_human]
    judge = [f for f in F if f.needs_human and f.owner == Owner.CA and f.confidence != Confidence.HIGH]
    outreach = [f for f in F if f.owner in (Owner.CLIENT, Owner.SUPPLIER)]
    blocked = [f for f in F if f.blocked and f not in judge and f not in outreach]
    info = [f for f in F if f.needs_human and f not in judge and f not in outreach and f not in blocked]
    return {"decisions": len(F), "auto_cleared": len(auto), "quick_check_by_CA": len(judge),
            "ask_client_or_supplier": len(outreach), "blocked_credit_check": len(blocked),
            "info_or_housekeeping": len(info),
            "unexplained": sum(1 for f in F if not f.reason)}


def run(data_dir, books_file=None, portal_files=None, cfg: Config | None = None) -> dict:
    from .engine import reconcile
    from .loaders import load_many
    data_dir = Path(data_dir)
    cfg = cfg or Config()
    books_file = books_file or data_dir / "purchase_register_092026.xlsx"
    portal_files = portal_files or sorted(data_dir.glob("gstr2b_*.json"))
    books, n1 = load_many([books_file], Side.BOOKS)
    portal, n2 = load_many(portal_files, Side.PORTAL)
    res = reconcile(books, portal, client="Benchmark client", cfg=cfg, notes=n1 + n2)
    target = [p for p in portal if p.period == res.period]
    return {"files": {"books": str(books_file), "portal": [str(p) for p in portal_files]},
            "baseline": baseline(books, target, cfg), "engine": engine_effort(res),
            "accuracy": evaluate(res, books, portal, data_dir / "truth.json"),
            "summary": res.summary}
