"""Run a full reconciliation for one client and one return period."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from .config import Config
from .matcher import find_duplicates, match_one_to_one, match_splits, repeated_amounts
from .models import Action, Doc, Finding, Status
from .recommend import (from_books_only, from_other_period, from_pair, from_portal_only,
                        period_key, period_label)


@dataclass
class Result:
    client: str
    period: str
    findings: list
    notes: list
    summary: dict
    checks: list = field(default_factory=list)
    supplier_messages: list = field(default_factory=list)
    client_questions: list = field(default_factory=list)
    config: Config = field(default_factory=Config)

    @property
    def period_label(self) -> str:
        return period_label(self.period)


def due_date_3b(period: str) -> date:
    m, y = int(period[:2]), int(period[2:])
    m, y = (1, y + 1) if m == 12 else (m + 1, y)
    return date(y, m, 20)


def clean_period(period: str) -> str:
    """Accept '092026', '09/2026', '2026-09', 'Sep 2026', 'Sep-26'; reject nonsense clearly."""
    if not period:
        return ""
    import re
    s = str(period).strip()
    m = re.fullmatch(r"(\d{1,2})\s*[-/.]\s*(\d{4})", s) or re.fullmatch(r"(\d{4})\s*[-/.]\s*(\d{1,2})", s)
    if m:
        a, b = m.groups()
        mm, yy = (a, b) if len(b) == 4 else (b, a)
        s = f"{int(mm):02d}{yy}"
    elif re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", s):
        s = s[4:] + s[:4]                       # 202609 -> 092026
    else:
        from .loaders.common import to_period
        s = to_period(s) or s
    if not re.fullmatch(r"(0[1-9]|1[0-2])20\d{2}", s):
        raise ValueError(f"Period '{period}' not understood - use month and year, e.g. 092026 or Sep 2026")
    return s


def reconcile(books: list[Doc], portal: list[Doc], period: str = "", client: str = "",
              cfg: Config | None = None, planned_itc: float | None = None,
              as_of: date | None = None, notes: list | None = None) -> Result:
    from .followup import build_client_questions, build_supplier_messages
    from .risk import run_checks

    cfg = cfg or Config()
    notes = list(notes or [])
    period = clean_period(period)
    periods = sorted({p.period for p in portal if p.period}, key=period_key)
    if not period:
        period = periods[0] if periods else ""
        if len(periods) > 1:
            notes.append(f"Several 2B periods loaded ({', '.join(period_label(p) for p in periods)}); "
                         f"reconciling {period_label(period)} and using the others to explain late filers.")
    target = [p for p in portal if p.period in (period, "")]
    other = [p for p in portal if p.period and p.period != period]
    if not target:
        notes.append(f"No 2B records found for {period_label(period)}.")

    # Books from months after the period: matched normally (a mis-keyed date still finds its
    # bill), but if still unmatched at the end they are left out as next month's entries.
    def after(b):
        months = [m for m in (b.period, b.doc_month) if m]
        return bool(period) and bool(months) and all(period_key(m) > period_key(period) for m in months)
    if period:
        earlier = sum(1 for b in books if b.doc_month and period_key(b.doc_month) < period_key(period)
                      and (not b.period or period_key(b.period) < period_key(period)))
        if earlier:
            notes.append(f"{earlier} books entries are from earlier months; they are checked against this 2B "
                         "too (e.g. bills still waiting for the supplier).")

    # 1. strong one-to-one pairs, 2. split/combined invoices, 3. weak pairs
    #    (amount differences, look-alikes), 4. other months' 2B for leftovers
    weak = {Status.VALUE_DIFF, Status.PROBABLE}
    repeats = repeated_amounts(target) | repeated_amounts(books)
    pairs, rest_b, rest_p = match_one_to_one(books, target, cfg, exclude=weak, repeats=repeats)
    # a duplicate copy whose twin already matched must not be paired loosely
    matched_b = {b.uid for pr in pairs for b in pr.books}
    twins = set()
    for group in find_duplicates(books):
        if any(b.uid in matched_b for b in group):
            twins.update(b.uid for b in group if b.uid not in matched_b)
    held = [b for b in rest_b if b.uid in twins]
    rest_b = [b for b in rest_b if b.uid not in twins]
    splits, rest_b, rest_p = match_splits(rest_b, rest_p, cfg)
    weak_pairs, rest_b, rest_p = match_one_to_one(rest_b, rest_p, cfg, repeats=repeats)
    pairs += weak_pairs
    rest_b += held
    other_pairs = []
    if other and rest_b:
        op, rest_b2, _ = match_one_to_one(rest_b, other, cfg, repeats=repeats | repeated_amounts(other))
        other_pairs = [p for p in op if p.score >= 50]
        keep = {p.books[0].uid for p in other_pairs}
        rest_b = [b for b in rest_b if b.uid not in keep]

    findings: list[Finding] = []

    def fid():
        return f"F{len(findings) + 1:04d}"

    for pr in sorted(pairs + splits, key=lambda x: -x.score):
        findings.append(from_pair(fid(), pr, cfg))
    for pr in other_pairs:
        findings.append(from_other_period(fid(), pr, period, cfg))

    known_g = {b.supplier_gstin for b in books}
    known_p = {b.pan for b in books}
    for p in rest_p:
        findings.append(from_portal_only(fid(), p, known_g, known_p, cfg))

    as_of = as_of or (due_date_3b(period) if period else date.today())
    dup_of: dict[str, Doc] = {}
    for group in find_duplicates(books):
        first = group[0]
        for extra in group[1:]:
            dup_of[extra.uid] = first
    later = [b for b in rest_b if after(b)]
    if later:
        notes.append(f"{len(later)} unmatched books entries are dated after {period_label(period)}; left out "
                     "as next month's bills.")
        rest_b = [b for b in rest_b if not after(b)]
        books = [b for b in books if b not in later]
    unmatched_ids = {b.uid for b in rest_b}
    for b in rest_b:
        original = dup_of.get(b.uid)
        if original is None:
            # if the 'first' copy is unmatched but a later copy matched, flag the first instead
            for extra_uid, orig in dup_of.items():
                if orig.uid == b.uid and extra_uid not in unmatched_ids:
                    original = next(d for d in books if d.uid == extra_uid)
                    break
        findings.append(from_books_only(fid(), b, as_of, cfg, duplicate_of=original))

    amend_delta = _apply_amendments(findings, portal, target, notes)
    summary = summarise(books, target, findings, period, amend_delta)
    res = Result(client=client, period=period, findings=findings, notes=notes, summary=summary, config=cfg)
    res.checks = run_checks(res, books, target, planned_itc, as_of, cfg)
    res.supplier_messages = build_supplier_messages(res, cfg)
    res.client_questions = build_client_questions(res)
    return res


def _apply_amendments(findings, portal, target, notes) -> dict:
    """2B amendments (b2ba/cdnra) of an earlier month change ITC only by the difference."""
    from .models import Confidence, Owner
    from .recommend import inr
    originals = {(p.supplier_gstin, p.doc_no): p for p in portal if not p.amends}
    delta: dict[str, float] = {}
    missing = 0
    for f in findings:
        for p in f.portal:
            if not p.amends or p not in target:
                continue
            orig = originals.get((p.supplier_gstin, p.amends))
            full = p.tax * p.itc_sign
            if orig is not None and orig is not p:
                d = round(full - orig.tax * orig.itc_sign, 2)
                f.flags.append(f"Amends {p.amends} from the {period_label(orig.period)} 2B "
                               f"({inr(orig.tax)} -> {inr(p.tax)}): only the difference {inr(d)} changes ITC.")
            else:
                d = 0.0
                missing += 1
                f.flags.append(f"Amends {p.amends} from an earlier 2B that was not loaded: only the difference "
                               "changes ITC - load that month's 2B or adjust by hand.")
            delta[p.uid] = d
            f.itc_in_2b = round(f.itc_in_2b - full + d, 2)
            if f.itc_to_claim:
                f.itc_to_claim = round(f.itc_to_claim - full + d, 2)
            if not f.books:                        # an amendment never needs 'booking' as a new bill
                f.action, f.owner, f.confidence = Action.PENDING, Owner.CA, Confidence.MEDIUM
                f.reason = (f"Amendment of {p.amends} by the supplier ({inr(p.tax)} tax now). Only the "
                            f"difference affects ITC. Update the original entry in books, then accept.")
                f.next_step = "Compare with the original bill; update books; accept."
    if missing:
        notes.append(f"{missing} amendments refer to invoices from 2B months not loaded; their ITC effect "
                     "is set to zero until checked.")
    return delta


def summarise(books, target, findings, period, amend_delta=None) -> dict:
    amend_delta = amend_delta or {}
    by_status = Counter(f.status.value for f in findings)
    by_action = Counter(f.action.value for f in findings)
    in_period = [b for b in books if not period or not b.doc_month or period_key(b.doc_month) >= period_key(period)
                 or b.period == period]
    itc_books = round(sum(b.tax * b.itc_sign for b in in_period), 2)        # reverse charge included,
    itc_2b = round(sum(amend_delta.get(p.uid, p.tax * p.itc_sign)          # as it is in 2B
                       for p in target if p.itc_available is not False), 2)
    claim = round(sum(f.itc_to_claim for f in findings), 2)
    human = [f for f in findings if f.needs_human]
    auto = [f for f in findings if not f.needs_human]
    deemed = [f for f in findings if f.portal and f.action != Action.ACCEPT
              and f.action != Action.NONE
              and all(p.ims_action in ("", "No action") for p in f.portal)]
    return {
        "period": period,
        "books_entries": len(books),
        "portal_records": len(target),
        "itc_books": itc_books,
        "itc_2b": itc_2b,
        "itc_to_claim": claim,
        "findings": len(findings),
        "auto_cleared": len(auto),
        "needs_human": len(human),
        "itc_needing_attention": round(sum(f.itc_at_stake for f in human), 2),
        "deemed_acceptance_records": len(deemed),
        "deemed_acceptance_itc": round(sum(abs(f.itc_in_2b) for f in deemed), 2),
        "by_status": dict(by_status),
        "by_action": dict(by_action),
        "exact": by_status.get(Status.EXACT.value, 0),
    }
