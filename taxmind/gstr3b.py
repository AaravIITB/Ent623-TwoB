"""GSTR-3B Table 4 working and the ITC reversal ledger carried from month to month.

What the CA types into 3B Table 4, built from the decisions:

  2B ITC as generated                         (what IMS / 2B would auto-fill)
  less: kept Pending / Rejected in IMS        (drops out when 2B is recomputed)
  4(A)(5) All other ITC                       = the above + ITC reclaimed this month
  4(B)(1) Sec 17(5) / Rule 38, 42, 43         blocked credit the CA confirms (proposed: 'Likely' flags)
  4(B)(2) Others                              ITC in 2B that can't be claimed yet (booked without GST,
                                              not in books under the 'reverse' policy, ...) - reclaimable
  4(C)    Net ITC                             = 4(A) - 4(B)
  4(D)(1) Reclaimed (reversed earlier in 4(B)(2))
  4(D)(2) Ineligible: Sec 16(4) / place of supply (2B marks 'ITC not available')

Temporary 4(B)(2) reversals are written to a ledger file. Next month that file is loaded again,
and any of its bills that are now booked are reclaimed in 4(A)(5) and shown in 4(D)(1) - the
step CA staff otherwise track by hand in the 3B working sheet.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .models import Action, DocType, Finding, Status
from .normalize import k2
from .recommend import inr, period_label

HEADS = ("igst", "cgst", "sgst", "cess")


def _heads(docs, factor: float = 1.0) -> dict:
    out = dict.fromkeys(HEADS, 0.0)
    for d in docs:
        s = d.itc_sign
        for h in HEADS:
            out[h] += getattr(d, h) * s * factor
    return out


def _add(a: dict, b: dict, sign: float = 1.0) -> dict:
    return {h: round(a.get(h, 0.0) + sign * b.get(h, 0.0), 2) for h in HEADS}


def _total(d: dict) -> float:
    return round(sum(d.values()), 2)


@dataclass
class Line:
    code: str
    label: str
    amounts: dict = field(default_factory=lambda: dict.fromkeys(HEADS, 0.0))
    count: int = 0
    note: str = ""

    @property
    def total(self) -> float:
        return _total(self.amounts)


@dataclass
class LedgerItem:
    gstin: str
    doc_no: str
    doc_date: str
    period_reversed: str
    igst: float
    cgst: float
    sgst: float
    cess: float
    reason: str
    supplier: str = ""

    @property
    def tax(self) -> float:
        return round(self.igst + self.cgst + self.sgst + self.cess, 2)


LEDGER_FIELDS = ["gstin", "supplier", "doc_no", "doc_date", "period_reversed", "igst", "cgst", "sgst", "cess",
                 "reason"]


def load_ledger(path: str | Path) -> list[LedgerItem]:
    items = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            try:
                items.append(LedgerItem(gstin=(r.get("gstin") or "").strip().upper(), doc_no=(r.get("doc_no") or "").strip(),
                                        doc_date=r.get("doc_date") or "", period_reversed=r.get("period_reversed") or "",
                                        igst=float(r.get("igst") or 0), cgst=float(r.get("cgst") or 0),
                                        sgst=float(r.get("sgst") or 0), cess=float(r.get("cess") or 0),
                                        reason=r.get("reason") or "", supplier=r.get("supplier") or ""))
            except ValueError:
                continue
    return items


def write_ledger(items: list[LedgerItem], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_FIELDS)
        w.writeheader()
        for it in items:
            w.writerow({k: getattr(it, k) for k in LEDGER_FIELDS})
    return path


def apply_prior_ledger(findings: list[Finding], ledger: list[LedgerItem], period: str) -> tuple[list, list]:
    """Mark books entries that reclaim an earlier 4(B)(2) reversal. Returns (reclaimed, still_open)."""
    idx = {}
    for it in ledger:
        idx.setdefault((it.gstin, k2(it.doc_no)), []).append(it)
    reclaimed = []
    for f in findings:
        if not f.books or f.status in (Status.BOOKS_DUPLICATE, Status.NO_ITC, Status.BOOKED_NO_GST,
                                       Status.BOOKS_ADJUSTMENT):
            continue
        b = f.books[0]
        key = (b.supplier_gstin, k2(b.doc_no))
        hits = idx.get(key)
        if not hits:
            continue
        if any(p.period == period or not p.period for p in f.portal):
            # also in this month's 2B: its ITC comes in through 4(A)(5) already - never reclaim on top
            f.flags.append(f"Also on the reversal ledger from {period_label(hits[0].period_reversed)}: it is in this "
                           "month's 2B too, so it is not reclaimed again. Check the earlier reversal.")
            continue
        it = hits.pop(0)
        if not hits:
            idx.pop(key)
        reclaimed.append((f, it))
        f.reclaim = it.tax
        f.reclaim_item = it
        f.flags.append(f"Reversed in 3B Table 4(B)(2) for {period_label(it.period_reversed)} ({inr(it.tax)}; "
                       f"{it.reason}). Now in books: reclaim it in 4(A)(5) and show it in 4(D)(1).")
        if f.status in (Status.BOOKS_OLDER, Status.EARLIER_PERIOD, Status.BOOKS_ONLY, Status.BOOKS_NO_GSTIN):
            f.itc_to_claim = it.tax
            f.reason = (f"Reclaim: this bill was in the {period_label(it.period_reversed)} 2B and its ITC "
                        f"({inr(it.tax)}) was reversed then because it was not in books. It is booked now, so "
                        "reclaim it this month.")
            f.next_step = "Include in 3B 4(A)(5) and 4(D)(1)."
    still_open = [it for items in idx.values() for it in items]
    return reclaimed, still_open


def _expired(it: LedgerItem, period: str) -> bool:
    """Past the Sec 16(4) date (30 Nov after the invoice's financial year): it can no longer be reclaimed."""
    from datetime import date
    try:
        d = date.fromisoformat(it.doc_date[:10])
    except ValueError:
        return False
    fy_end = d.year + 1 if d.month >= 4 else d.year
    m, y = int(period[:2]), int(period[2:])
    return date(y, m, 1) > date(fy_end, 11, 30)


def build(res, prior_ledger: list[LedgerItem] | None = None, policy: str = "pending",
          carried: list[LedgerItem] | None = None, store: bool = True) -> dict:
    """Table 4 lines, plus the ledger to carry forward. Stores the result on res.table4.
    `carried`: open items already separated from a prior ledger (when rebuilding after CA decisions)."""
    period = res.period
    findings: list[Finding] = res.findings
    reclaimed, still_open = ([], list(carried or []))
    if prior_ledger:
        reclaimed, still_open = apply_prior_ledger(findings, list(prior_ledger), period)

    gen = Line("2B", f"ITC in the {period_label(period)} 2B as generated (available, forward charge)")
    removed = Line("IMS", "Less: kept Pending / Rejected in IMS (drops out when 2B is recomputed)")
    a3 = Line("4(A)(3)", "Inward supplies liable to reverse charge (tax paid in cash)")
    a5 = Line("4(A)(5)", "All other ITC")
    b1 = Line("4(B)(1)", "Reversed: Sec 17(5) blocked credit (proposed - 'Likely' flags; CA to confirm)")
    b1_review = Line("4(B)(1)?", "To decide: possible blocked credit not included above ('Possible' / 'Review')")
    b2 = Line("4(B)(2)", "Reversed: others - can be reclaimed later")
    d1 = Line("4(D)(1)", "ITC reclaimed which was reversed under 4(B)(2) earlier")
    d2 = Line("4(D)(2)", "Ineligible ITC: Sec 16(4) / place-of-supply (2B marks 'not available')")
    maybe_reclaim = Line("4(D)(1)?", "Possible reclaims: older bills booked now, not in this 2B (confirm "
                                     "against the earlier 3B working)")
    new_ledger: list[LedgerItem] = []

    def scaled(heads: dict, total: float) -> dict:
        t = _total(heads)
        if abs(t) < 0.005:
            return dict.fromkeys(HEADS, 0.0)
        return {h: round(v * total / t, 2) for h, v in heads.items()}

    for f in findings:
        tp = [p for p in f.portal if p.period == period or not p.period]
        avail = [p for p in tp if p.itc_available is not False and not p.reverse_charge]
        rcm = [p for p in tp if p.reverse_charge and p.itc_available is not False]
        na = [p for p in tp if p.itc_available is False]
        likely = any(fl.confidence == "Likely" for fl in f.blocked + list(getattr(f, "blocked_cn", [])))
        if na:
            d2.amounts = _add(d2.amounts, _heads(na))
            d2.count += len(na)
        if (rcm or (f.status == Status.RCM and not tp)) and f.itc_to_claim:
            src = rcm or f.books
            amt = scaled(_heads(src), f.itc_to_claim)
            a3.amounts = _add(a3.amounts, amt)
            a3.count += 1
            if likely:
                b1.amounts = _add(b1.amounts, amt)
                b1.count += 1
            continue
        if f.reclaim:
            it = getattr(f, "reclaim_item", None)
            amt = ({h: getattr(it, h) for h in HEADS} if it is not None
                   else scaled(_heads(f.portal or f.books), f.reclaim))
            d1.amounts = _add(d1.amounts, amt)
            d1.count += 1
            if likely:                                   # a reclaimed bill can still be blocked
                b1.amounts = _add(b1.amounts, amt)
                b1.count += 1
        elif f.status == Status.BOOKS_ONLY and f.books and f.books[0].doc_type == DocType.CREDIT_NOTE \
                and f.itc_to_claim < 0:
            amt = {h: -v for h, v in _heads(f.books).items()}          # CN heads are negative; reversal is positive
            b2.amounts = _add(b2.amounts, amt)
            b2.count += 1
        elif f.status in (Status.BOOKS_OLDER, Status.EARLIER_PERIOD):
            src = f.portal if f.status == Status.EARLIER_PERIOD else f.books
            maybe_reclaim.amounts = _add(maybe_reclaim.amounts, _heads(src))
            maybe_reclaim.count += 1
        if not avail:
            continue
        # amendments: the record's ITC effect is the difference worked out by the engine (f.itc_in_2b)
        h = _heads(avail)
        if any(p.amends and not p.amend_is_delta for p in avail):
            h = scaled(h, f.itc_in_2b)        # full amended values in 2B: only the difference counts
        gen.amounts = _add(gen.amounts, h)
        gen.count += len(avail)
        portal_only = not f.books
        reverse_instead = policy == "reverse" and portal_only and f.action == Action.NONE \
            and f.status in (Status.PORTAL_ONLY_KNOWN, Status.PORTAL_ONLY_UNKNOWN)
        if f.action in (Action.PENDING, Action.REJECT):
            removed.amounts = _add(removed.amounts, h)
            removed.count += len(avail)
            continue
        in2b = _total(h)
        claim = 0.0 if reverse_instead else f.itc_to_claim - (f.reclaim if f.status != Status.EARLIER_PERIOD else 0)
        if abs(in2b) < 0.005:
            factor = 0.0
        else:
            factor = max(0.0, min(1.0, claim / in2b))      # same sign -> share claimed; opposite sign -> none
        claimed = {k: round(v * factor, 2) for k, v in h.items()}
        not_now = _add(h, claimed, -1)
        if likely:
            # blocked: whatever comes into 4(A) from this bill is reversed permanently in 4(B)(1)
            b1.amounts = _add(b1.amounts, h)
            b1.count += 1
            continue
        if f.blocked and _total(claimed) > 0:
            b1_review.amounts = _add(b1_review.amounts, claimed)
            b1_review.count += 1
        if _total(not_now) > 0.5:
            b2.amounts = _add(b2.amounts, not_now)
            b2.count += 1
            reclaimable = f.status not in (Status.VALUE_DIFF,) or reverse_instead
            if reclaimable:
                p0 = avail[0]
                new_ledger.append(LedgerItem(
                    gstin=p0.supplier_gstin, supplier=p0.supplier_name, doc_no=p0.doc_no,
                    doc_date=p0.doc_date.isoformat() if p0.doc_date else "", period_reversed=period,
                    igst=not_now["igst"], cgst=not_now["cgst"], sgst=not_now["sgst"], cess=not_now["cess"],
                    reason=f"{f.status.value} ({f.fid})"))

    a5.amounts = _add(_add(gen.amounts, removed.amounts, -1), d1.amounts)
    a5.count = gen.count - removed.count
    a5.note = "2B as generated, less IMS Pending/Rejected, plus reclaims in 4(D)(1)"
    net = Line("4(C)", "Net ITC available (4A - 4B)",
               _add(_add(_add(a5.amounts, a3.amounts), b1.amounts, -1), b2.amounts, -1))
    lines = [gen, removed, a3, a5, b1, b2, net, d1, d2, b1_review, maybe_reclaim]
    expired = [it for it in still_open if _expired(it, period)]
    still_open = [it for it in still_open if it not in expired]
    ledger_out = still_open + new_ledger
    out = {"lines": lines, "ledger": ledger_out, "reclaimed": len(reclaimed), "carried": len(still_open),
           "expired": expired,
           "carried_items": still_open, "new_reversals": len(new_ledger), "policy": policy}
    if store:
        res.table4 = out
    return out


def after_decisions(res, decisions) -> dict:
    """Rebuild Table 4 and the ledger with the CA's final decisions instead of the recommendations."""
    import copy
    from types import SimpleNamespace
    by = {d.fid: d for d in decisions}
    fs = []
    for f in res.findings:
        g = copy.copy(f)
        d = by.get(f.fid)
        if d is not None and d.overridden and d.final in {a.value for a in Action}:
            from .closepack import finding_claim
            g.itc_to_claim = finding_claim(f, d.final)
            g.action = Action(d.final)
            if g.reclaim and g.itc_to_claim == 0:
                g.reclaim = 0.0
        fs.append(g)
    tmp = SimpleNamespace(period=res.period, findings=fs)
    t4 = res.table4 or {}
    return build(tmp, None, t4.get("policy", "pending"), carried=t4.get("carried_items"), store=False)


def table_csv(t4: dict) -> str:
    import io
    sio = io.StringIO()
    w = csv.writer(sio)
    w.writerow(["Table", "Line", "IGST", "CGST", "SGST/UTGST", "Cess", "Total", "Records"])
    for ln in t4.get("lines", []):
        w.writerow([ln.code, ln.label, ln.amounts["igst"], ln.amounts["cgst"], ln.amounts["sgst"], ln.amounts["cess"],
                    ln.total, ln.count])
    return sio.getvalue()
