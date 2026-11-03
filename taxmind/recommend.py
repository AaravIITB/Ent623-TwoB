"""Turn matched pairs and leftovers into decisions a CA can act on.

Every Finding answers four questions:
  what to do in IMS (Accept / Reject / Pending / nothing),
  why (one plain sentence quoting the actual numbers),
  who has to act next (nobody / CA / client / supplier),
  how sure we are (High / Medium / Low).
These are default policies; a firm can change them here.
"""
from __future__ import annotations

from datetime import date

from . import gstin as G
from .config import Config
from .matcher import Pair
from .models import Action, Confidence, Doc, DocType, Finding, Owner, Status
from .normalize import k3


# ── formatting ───────────────────────────────────────────────────────────────

def inr(x: float) -> str:
    """Indian digit grouping: 1,18,000."""
    neg = x < 0
    x = abs(round(x))
    s = str(int(x))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-₹" if neg else "₹") + s


def dt(d: date | None) -> str:
    return d.strftime("%d-%m-%Y") if d else "no date"


def period_label(p: str) -> str:
    if len(p) != 6:
        return p or "unknown period"
    return date(int(p[2:]), int(p[:2]), 1).strftime("%b %Y")


def period_key(p: str) -> str:
    return p[2:] + p[:2] if len(p) == 6 else p


def _signed(docs: list[Doc]) -> float:
    return round(sum(d.tax * d.itc_sign for d in docs), 2)


def _kind(d: Doc) -> str:
    return {"CN": "credit note", "DN": "debit note"}.get(d.doc_type.value, "invoice")


def sec16_deadline(d: date | None) -> date | None:
    """ITC for an invoice must be claimed by 30 Nov after the end of its financial year."""
    if not d:
        return None
    fy_end_year = d.year + 1 if d.month >= 4 else d.year
    return date(fy_end_year, 11, 30)


# ── matched pairs ────────────────────────────────────────────────────────────

def from_pair(fid: str, pr: Pair, cfg: Config) -> Finding:
    b, p = pr.books, pr.portal
    b0, p0 = b[0], p[0]
    f = Finding(fid=fid, status=pr.status, books=b, portal=p, match_score=pr.score,
                itc_in_2b=_signed(p), itc_in_books=_signed(b))
    s = pr.status
    if s == Status.EXACT:
        f.action, f.confidence, f.owner = Action.ACCEPT, Confidence.HIGH, Owner.NONE
        f.reason = "Matches your books exactly: GSTIN, invoice no., date and amounts agree."
        f.itc_to_claim = f.itc_in_2b
    elif s == Status.FORMAT_DIFF:
        f.action, f.confidence, f.owner = Action.ACCEPT, Confidence.HIGH, Owner.NONE
        f.reason = (f"Same {_kind(p0)}: the number is written differently ('{p0.doc_no}' in 2B, "
                    f"'{b0.doc_no}' in books); GSTIN and amounts agree"
                    + ("." if pr.date_gap == 0 else f", dates {pr.date_gap} days apart."))
        f.next_step = "Optional: correct the reference in books to the supplier's number."
        f.itc_to_claim = f.itc_in_2b
    elif s == Status.DATE_DIFF:
        f.action, f.confidence, f.owner = Action.ACCEPT, Confidence.HIGH, Owner.NONE
        if pr.date_gap is None:
            f.confidence, f.owner = Confidence.MEDIUM, Owner.CA
            missing = "books" if b0.doc_date is None else "2B"
            f.reason = (f"Same invoice no. and amounts; the date is missing in {missing} "
                        f"(2B: {dt(p0.doc_date)}, books: {dt(b0.doc_date)}).")
            f.next_step = "Add the invoice date in books, then accept."
        else:
            f.reason = (f"Same invoice no. and amounts; only the date differs ({dt(p0.doc_date)} in 2B, "
                        f"{dt(b0.doc_date)} in books).")
            f.next_step = "Optional: correct the date in books."
            if pr.date_gap > 45:
                f.confidence, f.owner = Confidence.MEDIUM, Owner.CA
                f.reason += f" The dates are {pr.date_gap} days apart - check it is the same bill."
                f.next_step = "Check the invoice copy before accepting."
        f.itc_to_claim = f.itc_in_2b
    elif s == Status.TYPO:
        f.action, f.confidence, f.owner = Action.ACCEPT, Confidence.MEDIUM, Owner.CA
        f.reason = (f"Probably the same invoice: numbers differ by one character ('{p0.doc_no}' vs "
                    f"'{b0.doc_no}'); same supplier and amounts, "
                    + ("same date." if not pr.date_gap else f"dates {pr.date_gap} days apart."))
        f.next_step = "Glance at the physical invoice, then accept and fix the number in books."
        f.itc_to_claim = f.itc_in_2b
        a_core, b_core = k3(p0.doc_no), k3(b0.doc_no)
        if pr.repeat_amount:
            f.action, f.confidence = Action.PENDING, Confidence.LOW
            f.reason += (" But this supplier bills the same amount repeatedly, so matching amounts "
                         "do not confirm it is the same bill.")
            f.next_step = "Check the invoice copy: same bill -> accept and fix books; different bill -> book it."
            f.itc_to_claim = 0.0
        elif a_core.isdigit() and b_core.isdigit() and 0 < abs(int(a_core) - int(b_core)) <= 3:
            # 1203 vs 1204: as likely to be the supplier's next bill (e.g. recurring rent) as a typo
            f.action, f.confidence = Action.PENDING, Confidence.LOW
            f.reason += (" The numbers are next to each other in sequence, so this may be a different "
                         "(consecutive) bill rather than a typo.")
            f.next_step = "Check the invoice copy: same bill -> accept and fix books; different bill -> book it."
            f.itc_to_claim = 0.0
    elif s == Status.PROBABLE:
        f.action, f.confidence, f.owner = Action.PENDING, Confidence.LOW, Owner.CA
        f.reason = (f"Same supplier, same date and same amounts ({inr(p0.tax)} tax), but the numbers "
                    f"don't resemble each other ('{p0.doc_no}' vs '{b0.doc_no}'). Books may be using "
                    "an internal number.")
        f.next_step = "Check the supplier's invoice copy; if it is the same bill, accept and fix books."
    elif s == Status.OTHER_GSTIN:
        f.action, f.confidence, f.owner = Action.PENDING, Confidence.MEDIUM, Owner.CLIENT
        f.reason = (f"Same invoice, but the supplier reported it under GSTIN {p0.supplier_gstin} "
                    f"({G.state_name(p0.supplier_gstin)}) while books show {b0.supplier_gstin} "
                    f"({G.state_name(b0.supplier_gstin)}) - same company (PAN {p0.pan}).")
        f.next_step = ("Check the GSTIN printed on the invoice. If books are wrong, correct books and "
                       "accept. If the supplier used the wrong registration, ask them to amend.")
    elif s == Status.HEAD_MISMATCH:
        f.action, f.confidence, f.owner = Action.PENDING, Confidence.MEDIUM, Owner.SUPPLIER
        bh = "IGST" if b0.igst > cfg.amount_tolerance else "CGST+SGST"
        ph = "IGST" if p0.igst > cfg.amount_tolerance else "CGST+SGST"
        f.reason = (f"Tax amount agrees ({inr(p0.tax)}) but the supplier reported {ph} while books "
                    f"show {bh}. ITC taken under the wrong head can be denied.")
        f.next_step = ("Check the place of supply. If the supplier is wrong, ask them to amend in "
                       "GSTR-1A; if books are wrong, correct books and accept.")
    elif s == Status.VALUE_DIFF:
        diff = round(p0.tax - b0.tax, 2)
        doc = _kind(p0)
        if abs(diff) <= max(cfg.amount_tolerance, cfg.tol(p0.tax)):
            # tax agrees; only the taxable value differs (freight / insurance / non-GST charges in books)
            small = abs(p0.taxable - b0.taxable) <= 0.05 * max(abs(p0.taxable), 1)
            f.action = Action.ACCEPT
            f.confidence, f.owner = (Confidence.HIGH, Owner.NONE) if small else (Confidence.MEDIUM, Owner.CA)
            f.reason = (f"Same {doc} and the tax agrees ({inr(p0.tax)}); only the taxable value differs "
                        f"({inr(p0.taxable)} in 2B vs {inr(b0.taxable)} in books) - books probably include non-GST "
                        "charges such as freight, insurance or a TDS/retention adjustment.")
            f.next_step = "Optional: book non-GST charges in a separate ledger."
            f.itc_to_claim = f.itc_in_2b
        elif p0.doc_type == DocType.CREDIT_NOTE:
            f.action, f.confidence, f.owner = Action.PENDING, Confidence.MEDIUM, Owner.CLIENT
            f.reason = (f"Credit note amounts differ: {inr(p0.tax)} tax in 2B vs {inr(b0.tax)} in books. "
                        "Accepting it reduces your ITC by the 2B amount.")
            f.next_step = ("Check the credit note copy. If 2B is right, correct books and accept; if books "
                           "are right, ask the supplier to amend first.")
        elif 0 < diff <= cfg.small_excess:
            f.action, f.confidence, f.owner = Action.ACCEPT, Confidence.MEDIUM, Owner.NONE
            f.reason = (f"Supplier reported {inr(diff)} more tax than your books ({inr(p0.tax)} vs {inr(b0.tax)}) - "
                        "a rounding-size difference. Accept, and claim the books amount.")
            f.next_step = f"Accept; claim {inr(b0.tax)} (the extra {inr(diff)} is reversed in 3B 4(B)(2))."
            f.itc_to_claim = round(b0.tax * b0.itc_sign, 2)
        elif diff > 0 and cfg.not_in_books_policy == "reverse":
            f.action, f.confidence, f.owner = Action.ACCEPT, Confidence.MEDIUM, Owner.CLIENT
            f.reason = (f"Supplier reported {inr(diff)} more tax on this {doc} than your books ({inr(p0.tax)} in 2B vs "
                        f"{inr(b0.tax)} in books). Accept it and claim only the books amount; the excess is reversed "
                        "in 3B Table 4(B)(2) until the difference is explained.")
            f.next_step = ("Check whether the purchase was under-booked; if so, correct books and reclaim. Otherwise "
                           "ask the supplier to amend.")
            f.itc_to_claim = round(b0.tax * b0.itc_sign, 2)
        elif diff > 0:
            f.action, f.confidence, f.owner = Action.PENDING, Confidence.MEDIUM, Owner.CLIENT
            f.reason = (f"Supplier reported {inr(diff)} more tax on this {doc} than your books "
                        f"({inr(p0.tax)} in 2B vs {inr(b0.tax)} in books; taxable "
                        f"{inr(p0.taxable)} vs {inr(b0.taxable)}).")
            f.next_step = ("Check whether the purchase was under-booked. If books are right, ask the "
                           "supplier to amend before accepting.")
        else:
            f.action, f.confidence, f.owner = Action.ACCEPT, Confidence.MEDIUM, Owner.SUPPLIER
            f.reason = (f"Supplier reported {inr(-diff)} less tax on this {doc} than your books "
                        f"({inr(p0.tax)} in 2B vs {inr(b0.tax)} in books). Only the 2B amount can be "
                        "claimed.")
            f.next_step = (f"Accept and claim {inr(p0.tax)}. Ask the supplier to amend for the "
                           f"balance {inr(-diff)}, or correct books if they are wrong.")
            f.itc_to_claim = f.itc_in_2b
    elif s == Status.RCM:
        f.action, f.confidence, f.owner = Action.NONE, Confidence.HIGH, Owner.CA
        f.reason = (f"Reverse-charge bill ({inr(p0.tax)} tax on {inr(p0.taxable)}): it does not go through IMS. Pay "
                    "the tax in cash in 3B Table 3.1(d); the ITC is claimed in Table 4(A)(3) once paid.")
        f.next_step = "Include in 3B 3.1(d) and 4(A)(3)."
        f.itc_to_claim = f.itc_in_2b
    elif s == Status.BOOKED_NO_GST:
        f.action, f.confidence, f.owner = Action.ACCEPT, Confidence.MEDIUM, Owner.CA
        f.reason = (f"The supplier reported this {_kind(p0)} with {inr(p0.tax)} tax, but books recorded it with no "
                    f"GST (taxable {inr(b0.taxable)} in books vs {inr(p0.taxable)} in 2B). The bill is genuine, so "
                    "accept it in IMS; no ITC is claimed because books did not take any.")
        f.next_step = ("If the ITC is eligible, correct the books entry and claim it (before the Sec 16(4) deadline); "
                       "if it is blocked or the client chose to expense it, reverse it in 3B Table 4(B).")
        f.itc_to_claim = 0.0
        f.reverse_4b2 = f.itc_in_2b
        f.itc_in_books = 0.0
    elif s == Status.SPLIT:
        f.action, f.confidence, f.owner = Action.ACCEPT, Confidence.MEDIUM, Owner.CA
        if len(b) == 1:
            f.reason = (f"Books entry '{b0.doc_no}' ({inr(b0.tax)} tax) equals the total of "
                        f"{len(p)} supplier invoices in 2B: " + ", ".join(d.doc_no for d in p) + ".")
        else:
            f.reason = (f"{len(b)} books entries (" + ", ".join(d.doc_no for d in b) + ") add up to "
                        f"one supplier invoice '{p0.doc_no}' ({inr(p0.tax)} tax).")
        f.next_step = "Confirm the bills, accept, and book them one-for-one next time."
        f.itc_to_claim = f.itc_in_2b
    _apply_common_flags(f, cfg)
    return f


def from_other_period(fid: str, pr: Pair, target: str, cfg: Config) -> Finding:
    """A books entry with no partner in this 2B, found in another month's 2B."""
    f = from_pair(fid, pr, cfg)
    p0 = pr.portal[0]
    later = period_key(p0.period) > period_key(target)
    detail = f.reason
    if later:
        f.status = Status.LATE_FILED
        f.action, f.owner = Action.NONE, Owner.NONE
        f.confidence = Confidence.HIGH if pr.score >= 80 else Confidence.MEDIUM
        f.reason = (f"Not in the {period_label(target)} 2B: the supplier reported it late, in the "
                    f"{period_label(p0.period)} 2B. ITC can be claimed from that month's return onward "
                    f"(before the Sec 16(4) deadline), not in {period_label(target)}. ({detail})")
        f.next_step = f"Defer this ITC to the {period_label(p0.period)} return."
    elif cfg.not_in_books_policy == "reverse" and p0.itc_available is not False and f.itc_in_2b > 0 \
            and pr.status not in (Status.PROBABLE, Status.OTHER_GSTIN, Status.HEAD_MISMATCH, Status.BOOKED_NO_GST):
        # the firm's method: a 2B bill not in books was reversed in that month's 4(B)(2); booked now -> reclaim
        f.status = Status.EARLIER_PERIOD
        f.action, f.owner, f.confidence = Action.NONE, Owner.CA, Confidence.MEDIUM
        f.reason = (f"Appeared in the {period_label(p0.period)} 2B and is booked only now. Under your method its ITC "
                    f"was reversed in that month's 3B (Table 4(B)(2), not in books), so it is reclaimed now: "
                    f"Table 4(A)(5) and 4(D)(1). ({detail})")
        f.next_step = ("Confirm it was reversed (not claimed) in the earlier 3B working; if it was claimed then, "
                       "change this to 'No IMS action' with no claim.")
        f.reclaim = round(min(f.itc_in_2b, f.itc_in_books), 2) if f.itc_in_books > 0 else f.itc_in_2b
        f.itc_to_claim = f.reclaim
        return f
    else:
        f.status = Status.EARLIER_PERIOD
        f.action, f.owner, f.confidence = Action.NONE, Owner.CA, Confidence.MEDIUM
        f.reason = (f"Appeared in the {period_label(p0.period)} 2B and is booked only now. If its ITC was reversed "
                    f"in that month's 3B because it was not in books (Table 4(B)(2)), reclaim it now in Table 4(A)(5) "
                    f"and show it in Table 4(D)(1). If it was claimed then, do not claim it again. ({detail})")
        f.next_step = "Check the earlier 3B working: reversed then -> reclaim now; claimed then -> nothing to do."
    f.itc_to_claim = 0.0
    return f


def _rate_flags(f: Finding, cfg: Config):
    """Books keying errors a reviewer would spot: a rate that is no GST slab, CGST != SGST."""
    for b in f.books:
        if b.taxable > 100 and b.tax >= 1:
            rate = (b.igst + b.cgst + b.sgst) / b.taxable * 100
            if not any(abs(rate - r) <= cfg.rate_slack for r in cfg.rate_slabs):
                f.flags.append(f"Books: tax is {rate:.2f}% of the taxable value ({inr(b.tax)} on {inr(b.taxable)}) - "
                               "not a GST rate; check the entry for a keying error or a partly booked bill.")
        if (b.cgst or b.sgst) and abs(b.cgst - b.sgst) > max(1.0, cfg.amount_tolerance):
            f.flags.append(f"Books: CGST {inr(b.cgst)} and SGST {inr(b.sgst)} should be equal.")
        if b.igst > 1 and (b.cgst > 1 or b.sgst > 1):
            f.flags.append("Books: both IGST and CGST/SGST on one bill - check the tax head.")
        own = (cfg.client_gstin or "")[:2]
        sup = b.state_code
        if own.isdigit() and sup.isdigit() and not f.portal:
            if own == sup and b.igst > 1 and not (b.cgst or b.sgst):
                f.flags.append(f"Books: IGST charged by a supplier in your own state ({G.state_name(b.supplier_gstin)}); "
                               "an intra-state bill should carry CGST+SGST unless it is an SEZ or import supply.")
            elif own != sup and (b.cgst > 1 or b.sgst > 1) and not b.igst:
                f.flags.append(f"Books: CGST/SGST from a supplier in another state ({G.state_name(b.supplier_gstin)}); "
                               "check the place of supply (allowed when the supplier is registered in your state "
                               "too, e.g. a hotel).")


def _apply_common_flags(f: Finding, cfg: Config):
    _rate_flags(f, cfg)
    for d in f.books:
        for n in d.notes:
            if not n.startswith("pan:"):
                f.flags.append(f"Books {d.row_ref}: {n}")
    for p in f.portal:
        if p.itc_available is False:
            f.flags.append(f"Portal: ITC not available ({p.itc_unavailable_reason or 'no reason given'})")
            f.itc_to_claim = 0.0
        if p.reverse_charge:
            f.flags.append("Reverse charge: not in IMS. Pay the tax in cash in 3B, then claim ITC.")
            f.action = Action.NONE
    if any(b.reverse_charge for b in f.books) and not any(p.reverse_charge for p in f.portal):
        f.flags.append("Books say reverse charge but the supplier reported forward charge.")
    want = {Action.ACCEPT: "Accepted", Action.REJECT: "Rejected", Action.PENDING: "Pending"}.get(f.action)
    for p in f.portal:
        if p.ims_action and want and p.ims_action not in (want, "No action"):
            f.flags.append(f"Currently '{p.ims_action}' in IMS; recommendation is '{f.action.value}'.")


# ── leftovers ────────────────────────────────────────────────────────────────

def from_portal_only(fid: str, p: Doc, known_gstins: set, known_pans: set, cfg: Config,
                     master: dict | None = None) -> Finding:
    f = Finding(fid=fid, status=Status.PORTAL_ONLY_KNOWN, portal=[p], itc_in_2b=_signed([p]))
    reverse = cfg.not_in_books_policy == "reverse"
    in_master = bool(master) and p.supplier_gstin in master
    if p.itc_available is False:
        f.status, f.action, f.confidence, f.owner = (Status.PORTAL_ITC_BLOCKED, Action.ACCEPT,
                                                     Confidence.MEDIUM, Owner.CA)
        f.reason = (f"Portal marks ITC as not available ({p.itc_unavailable_reason or 'no reason given'}). "
                    "Nothing to claim; record it only if the purchase is genuine.")
        f.next_step = "Do not claim this ITC."
    elif p.doc_type == DocType.CREDIT_NOTE:
        f.status, f.action, f.confidence, f.owner = (Status.PORTAL_ONLY_CN, Action.PENDING,
                                                     Confidence.MEDIUM, Owner.CLIENT)
        f.reason = (f"Supplier issued a credit note '{p.doc_no}' ({inr(p.tax)} tax) that is not in your "
                    "books. Accepting it reduces your ITC; rejecting it raises the supplier's tax.")
        f.next_step = ("Ask the client whether the credit note is genuine. If yes, book it and accept; "
                       "it can stay Pending for one month only.")
        f.itc_to_claim = 0.0
        if reverse:
            f.action, f.owner = Action.NONE, Owner.CLIENT
            f.reason += " Under your method it is left to be deemed accepted, so it reduces ITC now."
            f.next_step = "Book the credit note; reject it in IMS only if it is not genuine."
            f.itc_to_claim = f.itc_in_2b
    elif p.supplier_gstin in known_gstins or p.pan in known_pans or in_master:
        f.action, f.confidence, f.owner = Action.PENDING, Confidence.MEDIUM, Owner.CLIENT
        if p.supplier_gstin in known_gstins or p.pan in known_pans:
            f.reason = (f"In 2B but not in your books ({inr(p.tax)} tax). This supplier is a regular vendor, "
                        "so the bill may simply not be booked yet.")
        else:
            act = master[p.supplier_gstin].get("activity") or ""
            f.reason = (f"In 2B but not in this register ({inr(p.tax)} tax). The supplier is in your vendor master"
                        + (f" ({act})" if act else "") + " but has no entry in these books, so its bills are probably "
                        "booked in another register.")
        f.next_step = ("Ask the client if goods/services were received. If yes, book it and accept; "
                       "if not, reject. Left alone, it will be deemed accepted.")
        if reverse:
            f.action = Action.NONE
            f.reason += (" Under your method it is left in IMS (deemed accepted) and its ITC is reversed in "
                         "3B Table 4(B)(2) until booked; TwoB's reversal ledger reclaims it then.")
            f.next_step = "Reject in IMS only if it is not the client's bill; otherwise reverse in 4(B)(2)."
    else:
        f.status, f.action, f.confidence, f.owner = (Status.PORTAL_ONLY_UNKNOWN, Action.REJECT,
                                                     Confidence.LOW, Owner.CLIENT)
        f.reason = (f"Supplier {p.supplier_gstin} ({p.supplier_name or 'name not given'}) has never "
                    f"appeared in your books. {inr(p.tax)} of ITC from an unknown supplier may be a "
                    "wrong buyer GSTIN or a fake invoice.")
        f.next_step = ("Confirm with the client. If it is not theirs, reject it - otherwise it will be "
                       "deemed accepted into 2B.")
        f.flags.append("Unknown supplier")
    _apply_common_flags(f, cfg)
    return f


def from_books_only(fid: str, b: Doc, as_of: date, cfg: Config, duplicate_of: Doc | None = None,
                    period: str = "", loaded=()) -> Finding:
    f = Finding(fid=fid, status=Status.BOOKS_ONLY, books=[b], itc_in_books=_signed([b]),
                action=Action.NONE)
    if duplicate_of is not None:
        f.status, f.confidence, f.owner = Status.BOOKS_DUPLICATE, Confidence.HIGH, Owner.CA
        f.reason = (f"Booked twice: '{b.doc_no}' from this supplier also appears as "
                    f"'{duplicate_of.doc_no}' ({duplicate_of.row_ref or duplicate_of.uid}). "
                    f"{inr(b.tax)} of ITC would be claimed twice.")
        f.next_step = "Delete the duplicate entry in books."
        return f
    if b.reverse_charge:
        f.status, f.confidence, f.owner = Status.RCM, Confidence.HIGH, Owner.CA
        f.reason = ("Reverse-charge purchase: it does not pass through IMS. Pay the tax in cash in 3B "
                    "Table 3.1(d), then claim the ITC in Table 4(A)(3) (4(A)(2) if it is an import of services).")
        f.next_step = "Include in 3B reverse-charge tables."
        f.itc_to_claim = f.itc_in_books
        return f
    f.confidence, f.owner = Confidence.HIGH, Owner.SUPPLIER
    if b.doc_type == DocType.CREDIT_NOTE:
        f.reason = (f"Credit note '{b.doc_no}' ({inr(b.tax)} tax) is in your books but the supplier has not "
                    "reported it, so 2B still shows the full ITC on the original bill. The ITC it cancels "
                    "is reversed this month (3B Table 4(B)(2)).")
        f.next_step = "Ask the supplier to report the credit note in GSTR-1."
        f.itc_to_claim = f.itc_in_books          # negative: lowers the claim
        return f
    f.reason = (f"In your books but not in this 2B ({inr(b.tax)} tax). The supplier has not reported it "
                "(or reported it to a different GSTIN). This ITC cannot be claimed this month.")
    f.next_step = "Ask the supplier to report it in GSTR-1; claim the ITC in the month it appears in 2B."
    inv_month = b.doc_month
    if period and inv_month and period_key(inv_month) < period_key(period):
        # an old bill booked late: the supplier most likely reported it in an earlier 2B
        earlier_loaded = sorted({p for p in loaded if period_key(p) < period_key(period)
                                 and period_key(p) >= period_key(inv_month)}, key=period_key)
        f.status, f.confidence, f.owner = Status.BOOKS_OLDER, Confidence.MEDIUM, Owner.CA
        span = (period_label(inv_month) if _next_month(inv_month) == period
                else f"{period_label(inv_month)} - {period_label(_prev_month(period))}")
        if earlier_loaded:
            f.reason = (f"Invoice dated {dt(b.doc_date)} ({inr(b.tax)} tax), booked in {period_label(b.period)}. "
                        f"It is not in this 2B nor in the earlier 2B loaded ({', '.join(period_label(x) for x in earlier_loaded)}), "
                        "so the supplier has probably not reported it at all.")
            f.owner = Owner.SUPPLIER
            f.next_step = "Ask the supplier to report it in GSTR-1; claim when it appears in 2B."
        else:
            f.reason = (f"Invoice dated {dt(b.doc_date)} ({inr(b.tax)} tax), booked in {period_label(b.period)}. It is "
                        f"not in the {period_label(period)} 2B, so the supplier most likely reported it in an earlier "
                        f"2B ({span}). If its ITC was reversed then as 'not in books', it can be reclaimed now "
                        "(3B Table 4(A)(5) and 4(D)(1)); if it was claimed then, nothing more is due.")
            f.next_step = (f"Load the {span} 2B (or check GSTR-2A) to confirm; TwoB will then mark it "
                           "as a reclaim or as already claimed.")
    dl = sec16_deadline(b.doc_date)
    if dl:
        left = (dl - as_of).days
        if left < 0:
            f.flags.append(f"Sec 16(4) deadline {dt(dl)} has passed - this ITC is lost.")
        elif left <= cfg.sec16_warn_days:
            f.flags.append(f"Sec 16(4) deadline {dt(dl)} is {left} days away.")
    return f


def _next_month(p: str) -> str:
    m, y = int(p[:2]), int(p[2:])
    return f"{(m % 12) + 1:02d}{y + (m == 12)}"


def _prev_month(p: str) -> str:
    m, y = int(p[:2]), int(p[2:])
    return f"{12 if m == 1 else m - 1:02d}{y - (m == 1)}"


# ── books entries that are not ordinary bills ───────────────────────────────

def from_no_gst(fid: str, b: Doc) -> Finding:
    """An entry with no GST on it: nothing to match in 2B and no ITC."""
    f = Finding(fid=fid, status=Status.NO_ITC, books=[b], action=Action.NONE, confidence=Confidence.HIGH,
                owner=Owner.NONE, itc_in_books=0.0)
    f.reason = (f"No GST on this entry ({b.no_itc_reason}); taxable/amount {inr(b.taxable or (b.total_value or 0))}. "
                "Nothing to match in 2B and no ITC to claim.")
    if b.supplier_gstin and "advance" not in b.no_itc_reason:
        f.next_step = "If the supplier's bill does show GST, correct the entry."
    for n in b.notes:
        if not n.startswith("pan:"):
            f.flags.append(f"Books {b.row_ref}: {n}")
    return f


def from_no_gstin(fid: str, b: Doc, cfg: Config) -> Finding:
    f = Finding(fid=fid, status=Status.BOOKS_NO_GSTIN, books=[b], itc_in_books=_signed([b]),
                action=Action.NONE, confidence=Confidence.HIGH, owner=Owner.CLIENT)
    f.reason = (f"Books carry {inr(b.tax)} of GST from '{b.supplier_name or 'unnamed party'}' but no supplier GSTIN, "
                "and the supplier could not be identified in 2B by name, PAN or invoice no. It cannot be matched "
                "and its ITC should not be claimed until the GSTIN is known.")
    f.next_step = ("Get the GSTIN from the invoice and add it to the ledger master. If the supplier is unregistered, "
                   "the GST in books is wrong (or the purchase falls under reverse charge).")
    if b.doc_date and b.period and period_key(b.doc_month) < period_key(b.period):
        f.reason += (f" The invoice is dated {dt(b.doc_date)}, so the supplier probably reported it in an earlier 2B, "
                     "which is why the name could not be found in this one.")
    _apply_common_flags(f, cfg)
    return f


def from_adjustment(fid: str, b: Doc, findings: list, cfg: Config) -> Finding:
    """A correction entry ('excess booking rectified', 'less booking made earlier')."""
    f = Finding(fid=fid, status=Status.BOOKS_ADJUSTMENT, books=[b], itc_in_books=_signed([b]),
                action=Action.NONE, confidence=Confidence.HIGH, owner=Owner.CA)
    ref = b.ref_doc_no or b.doc_no
    linked = None
    if ref:
        from .normalize import k2
        key = k2(ref)
        for g in findings:
            if any(k2(d.doc_no) == key and (not b.supplier_gstin or d.pan == b.pan) for d in g.books + g.portal):
                linked = g
                break
    sign = "reduces" if b.itc_sign * b.tax < 0 or b.doc_type == DocType.CREDIT_NOTE else "adds"
    f.reason = (f"Correction entry in books ({inr(b.tax)} tax, {sign} ITC) for "
                + (f"invoice '{ref}'" if ref else "an earlier entry") + ". It is not a new bill, so there is "
                "nothing separate to find in 2B.")
    if linked is not None:
        f.reason += f" The invoice is on decision {linked.fid} ({linked.status.value})."
        f.flags.append(f"Linked to {linked.fid}")
    f.next_step = "Check the original entry plus this correction equals the supplier's bill / 2B."
    _apply_common_flags(f, cfg)
    return f
