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
        f.reason = (f"Same invoice no. and amounts; only the date differs ({dt(p0.doc_date)} in 2B, "
                    f"{dt(b0.doc_date)} in books).")
        f.next_step = "Optional: correct the date in books."
        f.itc_to_claim = f.itc_in_2b
    elif s == Status.TYPO:
        f.action, f.confidence, f.owner = Action.ACCEPT, Confidence.MEDIUM, Owner.CA
        f.reason = (f"Probably the same invoice: numbers differ by one character ('{p0.doc_no}' vs "
                    f"'{b0.doc_no}'); same supplier and amounts, "
                    + ("same date." if not pr.date_gap else f"dates {pr.date_gap} days apart."))
        f.next_step = "Glance at the physical invoice, then accept and fix the number in books."
        f.itc_to_claim = f.itc_in_2b
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
        if diff > 0:
            f.action, f.confidence, f.owner = Action.PENDING, Confidence.MEDIUM, Owner.CLIENT
            f.reason = (f"Supplier reported {inr(diff)} more tax than your books "
                        f"({inr(p0.tax)} in 2B vs {inr(b0.tax)} in books; taxable "
                        f"{inr(p0.taxable)} vs {inr(b0.taxable)}).")
            f.next_step = ("Check whether the purchase was under-booked. If books are right, ask the "
                           "supplier to amend before accepting.")
        else:
            f.action, f.confidence, f.owner = Action.ACCEPT, Confidence.MEDIUM, Owner.SUPPLIER
            f.reason = (f"Supplier reported {inr(-diff)} less tax than your books "
                        f"({inr(p0.tax)} in 2B vs {inr(b0.tax)} in books). Only the 2B amount can be "
                        "claimed.")
            f.next_step = (f"Accept and claim {inr(p0.tax)}. Ask the supplier to amend for the "
                           f"balance {inr(-diff)}, or correct books if they are wrong.")
            f.itc_to_claim = f.itc_in_2b
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
        f.reason = (f"Not in the {period_label(target)} 2B: the supplier reported it late, in "
                    f"{period_label(p0.period)} 2B. ITC can be claimed only in that month. ({detail})")
        f.next_step = f"Defer this ITC to the {period_label(p0.period)} return."
    else:
        f.status = Status.EARLIER_PERIOD
        f.action, f.owner, f.confidence = Action.NONE, Owner.CA, Confidence.MEDIUM
        f.reason = (f"Already appeared in the {period_label(p0.period)} 2B. Check it was claimed then "
                    f"and is not being claimed twice. ({detail})")
        f.next_step = "Confirm it was claimed in the earlier return; do not claim again."
    f.itc_to_claim = 0.0
    return f


def _apply_common_flags(f: Finding, cfg: Config):
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

def from_portal_only(fid: str, p: Doc, known_gstins: set, known_pans: set, cfg: Config) -> Finding:
    f = Finding(fid=fid, status=Status.PORTAL_ONLY_KNOWN, portal=[p], itc_in_2b=_signed([p]))
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
    elif p.supplier_gstin in known_gstins or p.pan in known_pans:
        f.action, f.confidence, f.owner = Action.PENDING, Confidence.MEDIUM, Owner.CLIENT
        f.reason = (f"In 2B but not in your books ({inr(p.tax)} tax). This supplier is a regular vendor, "
                    "so the bill may simply not be booked yet.")
        f.next_step = ("Ask the client if goods/services were received. If yes, book it and accept; "
                       "if not, reject. Left alone, it will be deemed accepted.")
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


def from_books_only(fid: str, b: Doc, as_of: date, cfg: Config, duplicate_of: Doc | None = None) -> Finding:
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
                    "Table 3.1(d), then claim the ITC.")
        f.next_step = "Include in 3B reverse-charge tables."
        return f
    f.confidence, f.owner = Confidence.HIGH, Owner.SUPPLIER
    f.reason = (f"In your books but not in this 2B ({inr(b.tax)} tax). The supplier has not reported it "
                "(or reported it to a different GSTIN). This ITC cannot be claimed this month.")
    f.next_step = "Ask the supplier to report it in GSTR-1; claim the ITC in the month it appears in 2B."
    dl = sec16_deadline(b.doc_date)
    if dl:
        left = (dl - as_of).days
        if left < 0:
            f.flags.append(f"Sec 16(4) deadline {dt(dl)} has passed - this ITC is lost.")
        elif left <= cfg.sec16_warn_days:
            f.flags.append(f"Sec 16(4) deadline {dt(dl)} is {left} days away.")
    return f
