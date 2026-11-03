"""Command line.

  python -m taxmind reconcile --books purchase_register.xlsx --portal gstr2b_092026.json gstr2b_102026.json \\
                              --client "ABC Pvt Ltd" --out output/
  python -m taxmind sample --out sample_data [--hard]
  python -m taxmind benchmark --data sample_data
  python -m taxmind reconcile ... --close-pack --preparer "Riya" --reviewer "CA Mehta" [--decisions edited.xlsx]
  python -m taxmind verify output/twob_..._close_pack.zip
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Config
from .engine import reconcile
from .loaders import load_many
from .models import Side
from .recommend import inr


def _reconcile(a):
    from .loaders.tabular import detect_client_gstin
    gstin = a.gstin or next((g for g in (detect_client_gstin(x) for x in list(a.books) + list(a.portal)) if g), "")
    cfg = Config(amount_tolerance=a.tolerance, amount_tolerance_pct=a.tolerance_pct,
                 line_of_business=a.line_of_business or "", client_gstin=gstin, not_in_books_policy=a.policy)
    books, n1 = load_many(a.books, Side.BOOKS)
    portal, n2 = load_many(a.portal, Side.PORTAL, period=a.period or "")
    prior = None
    if a.prior_ledger:
        from .gstr3b import load_ledger
        prior = load_ledger(a.prior_ledger)
    master = None
    if a.vendor_master:
        from .prepare import load_vendor_master
        master = load_vendor_master(a.vendor_master)
    res = reconcile(books, portal, period=a.period or "", client=a.client, cfg=cfg,
                    planned_itc=a.planned_itc, notes=n1 + n2, prior_ledger=prior, vendor_master=master)
    from .report import write_excel, write_html
    out = Path(a.out)
    import re
    stem = f"twob_{re.sub(r'[^A-Za-z0-9]+', '_', a.client or 'client').strip('_')}_{res.period}"
    x = write_excel(res, out / f"{stem}.xlsx")
    h = write_html(res, out / f"{stem}_prefiling.html")
    s = res.summary
    print(f"\nTwoB - {res.client or 'client'} - {res.period_label}")
    for n in res.notes:
        print(f"  note: {n}")
    print(f"  books entries {s['books_entries']}, 2B records {s['portal_records']}")
    print(f"  ITC books {inr(s['itc_books'])} | ITC 2B {inr(s['itc_2b'])} | recommended claim {inr(s['itc_to_claim'])}")
    print(f"  {s['auto_cleared']} cleared automatically, {s['needs_human']} need a person "
          f"({inr(s['itc_needing_attention'])} ITC) - {s.get('supplier_groups', 0)} supplier-level decisions")
    for c in res.checks:
        if c.level != "OK":
            print(f"  [{c.level}] {c.name}: {c.detail}")
    from .gstr3b import write_ledger
    led = write_ledger(res.table4.get("ledger", []), out / f"{stem}_itc_reversal_ledger.csv")
    for ln in res.table4.get("lines", []):
        if ln.code in ("4(A)(5)", "4(B)(1)", "4(B)(2)", "4(C)", "4(D)(1)"):
            print(f"  3B {ln.code:8} {inr(ln.total):>16}  {ln.label}")
    print(f"\n  Excel:  {x}\n  Report: {h}\n  Reversal ledger (load next month with --prior-ledger): {led}")
    if a.close_pack:
        from .closepack import CloseInfo, build_close_pack, load_overrides, pack_fingerprint
        overrides = load_overrides(a.decisions) if a.decisions else {}
        z = build_close_pack(res, out / f"{stem}_close_pack.zip", input_files=list(a.books) + list(a.portal),
                             info=CloseInfo(preparer=a.preparer, reviewer=a.reviewer, overrides=overrides))
        print(f"  Month-close pack: {z}  ({len(overrides)} CA decisions read)")
        print(f"  Pack fingerprint (note it in the client file / covering email): {pack_fingerprint(z)}")


def _verify(a):
    from .closepack import verify_pack
    ok, problems = verify_pack(a.pack, a.fingerprint or "")
    print("Pack intact: every file matches manifest.json." if ok else "Pack has been changed:")
    for x in problems:
        print("  -", x)
    return 0 if ok else 1


def _sample(a):
    from .synth import generate
    meta = generate(a.out, seed=a.seed, hard=a.hard)
    print(json.dumps(meta, indent=1))


def _benchmark(a):
    from .benchmark import run
    r = run(a.data)
    acc = r["accuracy"]
    print(json.dumps({"baseline (Tally-style exact rules)": r["baseline"], "engine": r["engine"],
                      "accuracy": {k: acc[k] for k in ("cases", "correct", "accuracy", "wrong_pairings",
                                                        "wrong_accepts", "by_case")},
                      "blocked_credit (Sec 17(5))": {k: v for k, v in acc["blocked_credit"].items()
                                                     if k != "failures"}}, indent=1))
    if acc["failures"]:
        print(f"\n{len(acc['failures'])} failures, first 10:")
        for f in acc["failures"][:10]:
            print(" ", f)
    for f in acc["blocked_credit"]["failures"][:10]:
        print("  blocked-credit miss/false flag:", f)


def main(argv=None):
    p = argparse.ArgumentParser(prog="taxmind", description="GSTR-2B / IMS reconciliation engine")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reconcile", help="reconcile books with GSTR-2B / IMS")
    r.add_argument("--books", nargs="+", required=True, help="purchase register: Excel/CSV or Tally XML")
    r.add_argument("--portal", nargs="+", required=True, help="GSTR-2B / IMS: JSON or Excel (several months allowed)")
    r.add_argument("--period", help="return period MMYYYY, e.g. 092026 (default: earliest 2B loaded)")
    r.add_argument("--client", default="", help="client name for reports and messages")
    r.add_argument("--planned-itc", type=float, help="ITC you plan to claim in 3B (for the DRC-01C check)")
    r.add_argument("--tolerance", type=float, default=1.0, help="rounding tolerance in rupees (default 1)")
    r.add_argument("--tolerance-pct", type=float, default=0.0,
                   help="also allow this %% of the amount as rounding, whichever is larger (default 0 = off)")
    r.add_argument("--gstin", default="", help="the client's own GSTIN (default: read from a 3B summary sheet)")
    r.add_argument("--line-of-business", default="",
                   help="comma list: vehicle_maker, vehicle_dealer, caterer, hotel, works_contractor, insurer, "
                        "travel_operator, gym_club (switches off blocked-credit flags that don't apply)")
    r.add_argument("--policy", choices=("pending", "reverse"), default="pending",
                   help="2B bills not in books: keep Pending in IMS (default) or accept and reverse in 3B 4(B)(2)")
    r.add_argument("--prior-ledger", help="last month's ITC reversal ledger CSV, to reclaim bills booked now")
    r.add_argument("--vendor-master", help="the firm's vendor master (Excel/CSV with GSTIN, name, and optionally "
                                           "Activity / ITC eligibility): fills blank GSTINs, recognises suppliers "
                                           "booked in another register, feeds the blocked-credit check")
    r.add_argument("--out", default="output", help="output folder")
    r.add_argument("--close-pack", action="store_true", help="also write a dated month-close pack (.zip)")
    r.add_argument("--decisions", help="CA's final decisions: the TwoB workbook with 'Final decision' / "
                                       "'CA note' filled in, or a CSV with ID, Final decision, CA note")
    r.add_argument("--preparer", default="", help="name of the person who prepared the reconciliation")
    r.add_argument("--reviewer", default="", help="name of the CA who reviewed it")
    r.set_defaults(fn=_reconcile)
    v = sub.add_parser("verify", help="check a month-close pack has not been changed")
    v.add_argument("pack")
    v.add_argument("--fingerprint", help="the pack fingerprint noted when the month was closed")
    v.set_defaults(fn=_verify)
    s = sub.add_parser("sample", help="generate synthetic sample data with known answers")
    s.add_argument("--out", default="sample_data")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--hard", action="store_true", help="a messier client")
    s.set_defaults(fn=_sample)
    b = sub.add_parser("benchmark", help="score the engine on sample data")
    b.add_argument("--data", default="sample_data")
    b.set_defaults(fn=_benchmark)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
