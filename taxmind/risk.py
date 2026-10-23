"""Pre-filing checks: what could go wrong if GSTR-3B is filed as things stand.

Rule-based only: every check is explainable and uses data the CA already has.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from .config import Config
from .models import Action, Confidence, Finding, Status
from .recommend import dt, inr, period_label


@dataclass
class Check:
    name: str
    level: str          # "OK", "Review", "High"
    detail: str
    amount: float = 0.0
    count: int = 0


def run_checks(res, books, target, planned_itc, as_of: date, cfg: Config) -> list[Check]:
    s = res.summary
    F: list[Finding] = res.findings
    out: list[Check] = []
    itc_2b, claim = s["itc_2b"], s["itc_to_claim"]

    # 1. 3B claim vs 2B (DRC-01C)
    planned = planned_itc if planned_itc is not None else s["itc_books"]
    basis = "the ITC you plan to claim" if planned_itc is not None else "ITC as per books"
    excess = round(planned - itc_2b, 2)
    if excess <= cfg.amount_tolerance:
        out.append(Check("3B claim vs 2B (DRC-01C)", "OK",
                         f"{basis[0].upper() + basis[1:]} ({inr(planned)}) does not exceed 2B ITC ({inr(itc_2b)}).",
                         0.0))
    else:
        pct = excess / itc_2b if itc_2b else 1.0
        trig = excess > cfg.drc01c_abs and pct > cfg.drc01c_pct
        out.append(Check(
            "3B claim vs 2B (DRC-01C)", "High" if trig else "Review",
            (f"Claiming {basis} ({inr(planned)}) would exceed 2B ITC ({inr(itc_2b)}) by {inr(excess)} "
             f"({pct:.0%}). " +
             ("This crosses both DRC-01C limits (above ₹25 lakh and 20%): expect an automatic notice, "
              "and the next GSTR-1 is blocked if not answered in 7 days." if trig else
              "Below the automatic DRC-01C limits, but any excess over 2B is not allowed and can be "
              "picked up in scrutiny with interest.") +
             f" Recommended claim: {inr(claim)}."), excess))

    # 2. Deemed acceptance
    n, amt = s["deemed_acceptance_records"], s["deemed_acceptance_itc"]
    out.append(Check(
        "Deemed acceptance in IMS", "High" if n and amt > 0 else "OK",
        (f"{n} records ({inr(amt)} ITC) should be rejected or kept pending but have no IMS action yet. "
         "Anything left untouched is deemed accepted when 2B is generated on the 14th.") if n else
        "No record that should be rejected or held is sitting without an IMS action.", amt, n))

    # 3. Unknown suppliers
    unk = [f for f in F if f.status == Status.PORTAL_ONLY_UNKNOWN]
    a = sum(abs(f.itc_in_2b) for f in unk)
    out.append(Check("Unknown suppliers in 2B", "High" if unk else "OK",
                     (f"{len(unk)} records ({inr(a)} ITC) from suppliers never seen in the books - "
                      "possible wrong GSTIN or fake invoices.") if unk else "None.", a, len(unk)))

    # 4. Duplicates in books
    dup = [f for f in F if f.status == Status.BOOKS_DUPLICATE]
    a = sum(abs(f.itc_in_books) for f in dup)
    out.append(Check("Duplicate entries in books", "High" if dup else "OK",
                     f"{len(dup)} entries booked twice ({inr(a)} ITC)." if dup else "None found.", a, len(dup)))

    # 5. ITC in books not supported by 2B
    bo = [f for f in F if f.status == Status.BOOKS_ONLY]
    a = sum(abs(f.itc_in_books) for f in bo)
    out.append(Check("Books ITC missing from 2B", "Review" if bo else "OK",
                     (f"{len(bo)} purchases ({inr(a)} ITC) are in books but not in this 2B. Do not claim "
                      "them this month; chase the suppliers.") if bo else "None.", a, len(bo)))

    # 6. Sec 16(4) time limit
    old = [f for f in F if any("Sec 16(4)" in x for x in f.flags)]
    a = sum(abs(f.itc_in_books) for f in old)
    lost = [f for f in old if any("passed" in x for x in f.flags)]
    out.append(Check("Sec 16(4) time limit", "High" if lost else ("Review" if old else "OK"),
                     (f"{len(old)} unclaimed purchases ({inr(a)} ITC) are near or past the 30 November "
                      f"deadline ({len(lost)} past).") if old else "No unclaimed ITC near the deadline.",
                     a, len(old)))

    # 7. Earlier-period records (double-claim risk)
    early = [f for f in F if f.status == Status.EARLIER_PERIOD]
    if early:
        a = sum(abs(f.itc_in_books) for f in early)
        out.append(Check("Possible double claim", "Review",
                         f"{len(early)} books entries ({inr(a)} ITC) already appeared in an earlier 2B. "
                         "Confirm they were not claimed before.", a, len(early)))

    # 8. Wrong tax head
    head = [f for f in F if f.status == Status.HEAD_MISMATCH]
    if head:
        a = sum(abs(f.itc_in_2b) for f in head)
        out.append(Check("IGST vs CGST/SGST mismatch", "Review",
                         f"{len(head)} invoices ({inr(a)} ITC) reported under a different tax head than "
                         "booked. ITC under the wrong head can be denied.", a, len(head)))

    # 9. Credit notes waiting
    cn = [f for f in F if f.status == Status.PORTAL_ONLY_CN]
    if cn:
        a = sum(abs(f.itc_in_2b) for f in cn)
        out.append(Check("Supplier credit notes not booked", "Review",
                         f"{len(cn)} credit notes ({inr(a)} tax) need a decision; credit notes can stay "
                         "Pending for one month only.", a, len(cn)))

    # 10. Matches that need a glance
    soft = [f for f in F if f.action == Action.ACCEPT and f.confidence != Confidence.HIGH]
    if soft:
        a = sum(abs(f.itc_in_2b) for f in soft)
        out.append(Check("Accepts that need a quick check", "Review",
                         f"{len(soft)} recommended accepts rest on a probable match (typo, split invoice, "
                         "or amount difference). Glance at these before accepting.", a, len(soft)))

    # 11. Concentration
    by_sup = defaultdict(float)
    for f in F:
        by_sup[(f.supplier_gstin, f.supplier_name)] += max(f.itc_to_claim, 0)
    total = sum(by_sup.values())
    if total > 0:
        (g, name), top = max(by_sup.items(), key=lambda kv: kv[1])
        if top / total > cfg.concentration_pct:
            out.append(Check("ITC concentration", "Review",
                             f"{name or g} accounts for {top / total:.0%} of the ITC to be claimed "
                             f"({inr(top)}). Make sure this supplier is genuine and active.", top, 1))
        big = [f for f in F if f.itc_to_claim > cfg.large_invoice_pct * total]
        if big:
            out.append(Check("Large single invoices", "Review",
                             f"{len(big)} invoices each carry over {cfg.large_invoice_pct:.0%} of this "
                             "month's ITC: " + ", ".join(f.portal[0].doc_no for f in big[:5]) + ".",
                             sum(f.itc_to_claim for f in big), len(big)))

    # 12. Blocked credit (Sec 17(5)) - matched in 2B does not mean eligible
    bl = [f for f in F if f.blocked]
    if bl:
        a = sum(max(f.itc_to_claim, f.itc_in_books, 0) for f in bl)
        kinds = sorted({fl.label for f in bl for fl in f.blocked})
        likely = sum(1 for f in bl if any(fl.confidence != "Possible" for fl in f.blocked))
        out.append(Check("Possible blocked credit (Sec 17(5))", "High" if likely else "Review",
                         f"{len(bl)} invoices ({inr(a)} ITC) look like blocked credit: " + ", ".join(kinds[:5]) +
                         ". GSTR-2B does not check this. Review each; reverse blocked ITC in 3B Table 4(B)(1).",
                         a, len(bl)))
    else:
        out.append(Check("Possible blocked credit (Sec 17(5))", "OK",
                         "No purchase looks like blocked credit from its ledger, description, HSN/SAC or "
                         "supplier name. Without ledger or HSN columns this check is weak.", 0.0, 0))

    order = {"High": 0, "Review": 1, "OK": 2}
    out.sort(key=lambda c: order[c.level])
    return out
