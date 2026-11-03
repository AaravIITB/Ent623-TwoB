"""Run a full reconciliation for one client and one return period."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from .config import Config
from .matcher import find_duplicates, match_one_to_one, match_splits, repeated_amounts
from .models import Action, Doc, Finding, Status
from .recommend import inr
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
    table4: dict = field(default_factory=dict)        # GSTR-3B Table 4 working (gstr3b.build)
    suppliers: list = field(default_factory=list)     # per-supplier roll-up

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
              as_of: date | None = None, notes: list | None = None, prior_ledger: list | None = None,
              vendor_master: dict | None = None) -> Result:
    from .followup import build_client_questions, build_supplier_messages
    from .risk import run_checks

    cfg = cfg or Config()
    notes = list(notes or [])
    period = clean_period(period)
    from .prepare import apply_vendor_master, resolve_missing_gstins
    master = vendor_master or {}
    notes += resolve_missing_gstins(books, portal, master=master, tol=cfg.amount_tolerance)
    if master:
        apply_vendor_master(list(books) + list(portal), master)
        notes.append(f"Vendor master: {len(master)} suppliers; used for GSTINs, activity and ITC eligibility.")
    all_books = books
    # entries that carry no ITC, correction entries and suppliers we could not identify are kept
    # out of the matching (they get their own decisions below)
    no_gst = [b for b in books if b.no_itc_reason]
    adjust = [b for b in books if b.adjustment and not b.no_itc_reason]
    no_gstin = [b for b in books if not b.supplier_gstin and not b.no_itc_reason and not b.adjustment
                and not b.reverse_charge]
    side_ids = {b.uid for b in no_gst + adjust + no_gstin}
    books = [b for b in books if b.uid not in side_ids]
    periods = sorted({p.period for p in portal if p.period}, key=period_key)
    if not period:
        period = periods[0] if periods else ""
        if len(periods) > 1:
            notes.append(f"Several 2B periods loaded ({', '.join(period_label(p) for p in periods)}); "
                         f"reconciling {period_label(period)} and using the others to explain late filers.")
    target = [p for p in portal if p.period in (period, "")]
    other = [p for p in portal if p.period and p.period != period and not p.amend_is_delta]
    deltas = [p for p in target if p.amend_is_delta]          # difference-only amendment rows: not bills to match
    target_match = [p for p in target if not p.amend_is_delta]
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
    repeats = repeated_amounts(target_match) | repeated_amounts(books)
    pairs, rest_b, rest_p = match_one_to_one(books, target_match, cfg, exclude=weak, repeats=repeats)
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
    # bills booked with no GST that the supplier reported with tax
    cand, _, _ = match_one_to_one([b for b in no_gst if b.supplier_gstin], rest_p, cfg)
    nogst_pairs = [pr for pr in cand if pr.status in (Status.BOOKED_NO_GST, Status.RCM)]
    # a 'correction' narration on an entry that matches a 2B bill outright is just a bill
    cand, _, _ = match_one_to_one([b for b in adjust if b.supplier_gstin], [p for p in rest_p if p.uid not in
                                  {q.uid for pr in nogst_pairs for q in pr.portal}], cfg)
    rescued = [pr for pr in cand if pr.score >= 90]
    for pr in rescued:
        pr.books[0].adjustment = False
    adjust = [b for b in adjust if b.adjustment]
    nogst_pairs += rescued
    used_p = {p.uid for pr in nogst_pairs for p in pr.portal}
    rest_p = [p for p in rest_p if p.uid not in used_p]
    kept = {b.uid for pr in nogst_pairs for b in pr.books}
    no_gst_left = [b for b in no_gst if b.uid not in kept]
    pairs += nogst_pairs
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

    known_g = {b.supplier_gstin for b in all_books if b.supplier_gstin}
    known_p = {b.pan for b in all_books if b.supplier_gstin}
    for p in rest_p + deltas:
        findings.append(from_portal_only(fid(), p, known_g, known_p, cfg, master))

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
        findings.append(from_books_only(fid(), b, as_of, cfg, duplicate_of=original, period=period,
                                        loaded=periods))

    from .recommend import from_adjustment, from_no_gst, from_no_gstin
    for b in no_gstin:
        findings.append(from_no_gstin(fid(), b, cfg))
    for b in adjust:
        findings.append(from_adjustment(fid(), b, findings, cfg))
    for b in no_gst_left:
        findings.append(from_no_gst(fid(), b))
    books = [b for b in all_books if b not in later]

    _guard_partial_register(findings, cfg, notes)
    _cap_inferred_gstin(findings)
    amend_delta = _apply_amendments(findings, portal, target, notes, cfg.not_in_books_policy == "reverse")
    from . import blocked
    blocked.apply(findings, cfg.line_of_business)
    res = Result(client=client, period=period, findings=findings, notes=notes, summary={}, config=cfg)
    from . import gstr3b
    t4 = gstr3b.build(res, prior_ledger, cfg.not_in_books_policy)
    if prior_ledger:
        notes.append(f"Reversal ledger: {t4['reclaimed']} earlier 4(B)(2) reversals are booked now and reclaimed; "
                     f"{t4['carried']} still open.")
        if t4.get("expired"):
            notes.append(f"Reversal ledger: {len(t4['expired'])} items are past the Sec 16(4) date and were dropped "
                         f"({inr(sum(i.tax for i in t4['expired']))} ITC lost): " +
                         ", ".join(f"{i.doc_no}" for i in t4["expired"][:8]))
    summary = summarise(books, target, findings, period, amend_delta)
    res.summary = summary
    res.suppliers = supplier_rollup(findings)
    res.checks = run_checks(res, books, target, planned_itc, as_of, cfg)
    res.supplier_messages = build_supplier_messages(res, cfg)
    res.client_questions = build_client_questions(res)
    return res


def _cap_inferred_gstin(findings):
    """A GSTIN TwoB filled in from a name or an invoice number is a good guess, not a fact:
    such decisions are never cleared without a person looking."""
    from .models import Confidence, Owner
    for f in findings:
        guessed = [n for b in f.books for n in b.notes if n.startswith("GSTIN ") and "from PAN" not in n]
        if guessed and not f.needs_human:
            f.confidence, f.owner = Confidence.MEDIUM, Owner.CA
            f.next_step = ("Confirm the supplier GSTIN on the invoice and add it to the ledger master. "
                           + (f.next_step or ""))


def _guard_partial_register(findings, cfg, notes):
    """When most 2B records come from suppliers the books never mention, the register loaded is
    probably partial (one voucher type, one branch). Rejecting those bills would throw away genuine
    ITC, so they are held Pending instead of Reject."""
    unk = [f for f in findings if f.status == Status.PORTAL_ONLY_UNKNOWN]
    n2b = sum(len(f.portal) for f in findings) or 1
    itc2b = sum(abs(f.itc_in_2b) for f in findings if f.portal) or 1.0
    share = max(len(unk) / n2b, sum(abs(f.itc_in_2b) for f in unk) / itc2b)
    if not unk or share <= cfg.partial_register_pct:
        return
    from .models import Confidence
    for f in unk:
        if f.action == Action.REJECT:
            f.action, f.confidence = Action.PENDING, Confidence.LOW
            f.flags.append("Held Pending, not Reject: the register loaded looks partial, so an unknown supplier "
                           "may simply be booked elsewhere.")
    notes.append(f"{share:.0%} of 2B comes from suppliers never seen in these books: the register looks partial, "
                 f"so {len(unk)} such records are held Pending instead of Reject.")


def _apply_amendments(findings, portal, target, notes, reverse_policy: bool = False) -> dict:
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
            if p.amend_is_delta:
                d = round(full, 2)
                f.flags.append(f"Amendment row carrying only the difference ({inr(d)} tax).")
            elif orig is not None and orig is not p:
                d = round(full - orig.tax * orig.itc_sign, 2)
                f.flags.append(f"Amends {p.amends} from the {period_label(orig.period)} 2B "
                               f"({inr(orig.tax)} -> {inr(p.tax)}): only the difference {inr(d)} changes ITC.")
            else:
                d = 0.0
                missing += 1
                f.flags.append(f"Amends {p.amends} from an earlier 2B that was not loaded: only the difference "
                               "changes ITC - load that month's 2B or adjust by hand.")
            delta[p.uid] = d
            if p.amend_is_delta:
                if not f.books:
                    f.action, f.owner, f.confidence = Action.PENDING, Owner.CA, Confidence.MEDIUM
                    f.reason = (f"Supplier amended an earlier invoice{' ' + p.doc_no if p.doc_no else ''}: the change "
                                f"is {inr(d)} tax. Update the original entry in books, then accept.")
                    f.next_step = "Compare with the original bill; update books; accept."
                    if reverse_policy:
                        f.action = Action.NONE
                        f.itc_to_claim = d if d < 0 else 0.0      # a cut lowers ITC now; a rise waits for books
                        f.reason += " Under your method it is left to be deemed accepted."
                continue
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
        # the same supplier + the same situation is usually one decision for staff (e.g. 200 airline tickets)
        "supplier_groups": len({(f.supplier_gstin, f.status, f.action) for f in human}),
        "deemed_acceptance_records": len(deemed),
        "deemed_acceptance_itc": round(sum(abs(f.itc_in_2b) for f in deemed), 2),
        "by_status": dict(by_status),
        "by_action": dict(by_action),
        "exact": by_status.get(Status.EXACT.value, 0),
        "no_gst_entries": by_status.get(Status.NO_ITC.value, 0),
        "gstin_filled": sum(1 for b in books if any(n.startswith("GSTIN ") for n in b.notes)),
        "from_narration": sum(1 for b in books if any("narration" in n for n in b.notes)),
        "blocked_review": sum(1 for f in findings if f.blocked),
        "blocked_review_itc": round(sum(max(f.itc_to_claim, f.itc_in_books, 0) for f in findings if f.blocked), 2),
    }


def supplier_rollup(findings) -> list[dict]:
    """One line per supplier: what matched, what is open, and how much ITC each part carries.
    Staff decide many 2B-only records at once this way (e.g. 200 airline tickets)."""
    from .models import Owner
    rows: dict = {}
    for f in findings:
        g = f.supplier_gstin or "(no GSTIN)"
        r = rows.setdefault(g, {"gstin": g, "name": f.supplier_name, "records_2b": 0, "entries_books": 0,
                                "matched": 0, "open": 0, "itc_2b": 0.0, "itc_books": 0.0, "itc_claim": 0.0,
                                "itc_open": 0.0, "statuses": Counter(), "in_books": False})
        r["name"] = r["name"] or f.supplier_name
        r["records_2b"] += len(f.portal)
        r["entries_books"] += len(f.books)
        r["in_books"] = r["in_books"] or bool(f.books)
        both = bool(f.books and f.portal)
        r["matched"] += both
        if f.needs_human:
            r["open"] += 1
            r["itc_open"] += f.itc_at_stake
        r["itc_2b"] += f.itc_in_2b
        r["itc_books"] += f.itc_in_books
        r["itc_claim"] += f.itc_to_claim
        r["statuses"][f.status.value] += 1
    out = []
    for r in rows.values():
        r["main_status"] = r["statuses"].most_common(1)[0][0]
        r["statuses"] = "; ".join(f"{k}: {v}" for k, v in r["statuses"].most_common())
        for k in ("itc_2b", "itc_books", "itc_claim", "itc_open"):
            r[k] = round(r[k], 2)
        if not r["in_books"] and r["records_2b"]:
            r["suggestion"] = ("Never in these books: confirm with the client once for all "
                               f"{r['records_2b']} records (e.g. expenses booked in another register), then accept "
                               "or reject them together.")
        elif r["open"]:
            r["suggestion"] = "Open items - see the decisions for this supplier."
        else:
            r["suggestion"] = "All clear."
        out.append(r)
    out.sort(key=lambda r: -abs(r["itc_open"]))
    return out