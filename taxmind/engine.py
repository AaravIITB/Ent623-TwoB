"""Run a full reconciliation for one client and one return period."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from .config import Config
from .matcher import find_duplicates, match_one_to_one, match_splits
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


def reconcile(books: list[Doc], portal: list[Doc], period: str = "", client: str = "",
              cfg: Config | None = None, planned_itc: float | None = None,
              as_of: date | None = None, notes: list | None = None) -> Result:
    from .followup import build_client_questions, build_supplier_messages
    from .risk import run_checks

    cfg = cfg or Config()
    notes = list(notes or [])
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

    # 1. strong one-to-one pairs, 2. split/combined invoices, 3. weak pairs
    #    (amount differences, look-alikes), 4. other months' 2B for leftovers
    weak = {Status.VALUE_DIFF, Status.PROBABLE}
    pairs, rest_b, rest_p = match_one_to_one(books, target, cfg, exclude=weak)
    # a duplicate copy whose twin already matched must not be paired loosely
    matched_b = {b.uid for pr in pairs for b in pr.books}
    twins = set()
    for group in find_duplicates(books):
        if any(b.uid in matched_b for b in group):
            twins.update(b.uid for b in group if b.uid not in matched_b)
    held = [b for b in rest_b if b.uid in twins]
    rest_b = [b for b in rest_b if b.uid not in twins]
    splits, rest_b, rest_p = match_splits(rest_b, rest_p, cfg)
    weak_pairs, rest_b, rest_p = match_one_to_one(rest_b, rest_p, cfg)
    pairs += weak_pairs
    rest_b += held
    other_pairs = []
    if other and rest_b:
        op, rest_b2, _ = match_one_to_one(rest_b, other, cfg)
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

    summary = summarise(books, target, findings, period)
    res = Result(client=client, period=period, findings=findings, notes=notes, summary=summary, config=cfg)
    res.checks = run_checks(res, books, target, planned_itc, as_of, cfg)
    res.supplier_messages = build_supplier_messages(res, cfg)
    res.client_questions = build_client_questions(res)
    return res


def summarise(books, target, findings, period) -> dict:
    by_status = Counter(f.status.value for f in findings)
    by_action = Counter(f.action.value for f in findings)
    itc_books = round(sum(b.tax * b.itc_sign for b in books if not b.reverse_charge), 2)
    itc_2b = round(sum(p.tax * p.itc_sign for p in target if p.itc_available is not False), 2)
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
