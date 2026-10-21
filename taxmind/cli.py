"""Command line.

  python -m taxmind reconcile --books purchase_register.xlsx --portal gstr2b_092026.json gstr2b_102026.json \\
                              --client "ABC Pvt Ltd" --out output/
  python -m taxmind sample --out sample_data [--hard]
  python -m taxmind benchmark --data sample_data
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
    cfg = Config(amount_tolerance=a.tolerance)
    books, n1 = load_many(a.books, Side.BOOKS)
    portal, n2 = load_many(a.portal, Side.PORTAL, period=a.period or "")
    res = reconcile(books, portal, period=a.period or "", client=a.client, cfg=cfg,
                    planned_itc=a.planned_itc, notes=n1 + n2)
    from .report import write_excel, write_html
    out = Path(a.out)
    import re
    stem = f"taxmind_{re.sub(r'[^A-Za-z0-9]+', '_', a.client or 'client').strip('_')}_{res.period}"
    x = write_excel(res, out / f"{stem}.xlsx")
    h = write_html(res, out / f"{stem}_prefiling.html")
    s = res.summary
    print(f"\nTaxMind - {res.client or 'client'} - {res.period_label}")
    for n in res.notes:
        print(f"  note: {n}")
    print(f"  books entries {s['books_entries']}, 2B records {s['portal_records']}")
    print(f"  ITC books {inr(s['itc_books'])} | ITC 2B {inr(s['itc_2b'])} | recommended claim {inr(s['itc_to_claim'])}")
    print(f"  {s['auto_cleared']} cleared automatically, {s['needs_human']} need a person "
          f"({inr(s['itc_needing_attention'])} ITC)")
    for c in res.checks:
        if c.level != "OK":
            print(f"  [{c.level}] {c.name}: {c.detail}")
    print(f"\n  Excel:  {x}\n  Report: {h}")


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
                                                        "wrong_accepts", "by_case")}}, indent=1))
    if acc["failures"]:
        print(f"\n{len(acc['failures'])} failures, first 10:")
        for f in acc["failures"][:10]:
            print(" ", f)


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
    r.add_argument("--out", default="output", help="output folder")
    r.set_defaults(fn=_reconcile)
    s = sub.add_parser("sample", help="generate synthetic sample data with known answers")
    s.add_argument("--out", default="sample_data")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--hard", action="store_true", help="a messier client")
    s.set_defaults(fn=_sample)
    b = sub.add_parser("benchmark", help="score the engine on sample data")
    b.add_argument("--data", default="sample_data")
    b.set_defaults(fn=_benchmark)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
