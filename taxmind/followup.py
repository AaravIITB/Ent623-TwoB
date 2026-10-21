"""Draft messages: one per supplier who must fix something, and one list of
questions for the client. The client sends supplier messages (the CA does not
own the supplier relationship), so they are written in the client's voice."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from .config import Config
from .models import Owner, Status
from .recommend import dt, inr, period_label


@dataclass
class SupplierMessage:
    supplier_gstin: str
    supplier_name: str
    items: int
    itc_at_stake: float
    whatsapp: str
    email_subject: str
    email_body: str


def _fix_by(period: str, cfg: Config) -> date:
    m, y = int(period[:2]), int(period[2:])
    m += 2
    if m > 12:
        m, y = m - 12, y + 1
    return date(y, m, cfg.supplier_fix_day)


def _next_period(period: str) -> str:
    m, y = int(period[:2]), int(period[2:])
    m, y = (1, y + 1) if m == 12 else (m + 1, y)
    return f"{m:02d}{y}"


def _line(f) -> str:
    b = f.books[0] if f.books else None
    p = f.portal[0] if f.portal else None
    kind = "Credit note" if (b or p).doc_type.value == "CN" else "Invoice"
    if f.status == Status.BOOKS_ONLY:
        return f"{kind} {b.doc_no} dated {dt(b.doc_date)}, GST {inr(b.tax)}: not reported in your GSTR-1."
    if f.status == Status.VALUE_DIFF:
        return (f"{kind} {b.doc_no} dated {dt(b.doc_date)}: you reported GST {inr(p.tax)}, our copy "
                f"shows {inr(b.tax)}. Please amend.")
    if f.status == Status.HEAD_MISMATCH:
        ph = "IGST" if p.igst else "CGST+SGST"
        bh = "IGST" if b.igst else "CGST+SGST"
        return f"Invoice {b.doc_no} dated {dt(b.doc_date)}: reported as {ph}, invoice charges {bh}. Please amend."
    if f.status == Status.OTHER_GSTIN:
        return (f"Invoice {b.doc_no} dated {dt(b.doc_date)}: reported under GSTIN {p.supplier_gstin}, "
                f"invoice shows {b.supplier_gstin}. Please confirm the correct GSTIN.")
    return f"{(b or p).doc_no}: {f.reason}"


def build_supplier_messages(res, cfg: Config) -> list[SupplierMessage]:
    if not res.period:
        return []
    groups = defaultdict(list)
    for f in res.findings:
        if f.owner == Owner.SUPPLIER and f.books:
            groups[f.books[0].supplier_gstin].append(f)
    fix_by = _fix_by(res.period, cfg)
    claim_in = period_label(_next_period(res.period))
    who = res.client or "our company"
    out = []
    for g, fs in sorted(groups.items(), key=lambda kv: -sum(f.itc_at_stake for f in kv[1])):
        name = next((d.supplier_name for f in fs for d in f.books + f.portal if d.supplier_name), g)
        total = round(sum(f.itc_at_stake for f in fs), 2)
        claimable = round(sum(f.itc_at_stake for f in fs if f.books[0].doc_type.value != "CN"), 2)
        ask = (f"so we can claim the GST credit of {inr(claimable)} in our {claim_in} return" if claimable
               else "so that our GST records match yours")
        lines = [_line(f) for f in sorted(fs, key=lambda f: f.books[0].doc_date or date.min)]
        bullets = "\n".join(f"• {x}" for x in lines)
        wa = (f"Hello {name}, this is {who}, your customer.\n"
              f"While reconciling our GSTR-2B for {period_label(res.period)}, we found:\n{bullets}\n"
              f"Please report/correct these in your GSTR-1 (or GSTR-1A) by {dt(fix_by)}, {ask}. Thank you.")
        subject = f"GST: {len(fs)} invoice(s) to report/correct for {period_label(res.period)} - {who}"
        body = (f"Dear {name},\n\nWhile reconciling our GSTR-2B for {period_label(res.period)}, we found "
                f"the following differences with invoices you issued to us (your GSTIN {g}):\n\n{bullets}\n\n"
                f"Total GST credit affected: {inr(total)}.\n\nPlease report or correct these in your "
                f"GSTR-1 / GSTR-1A by {dt(fix_by)}, {ask}. "
                f"If you think our records are wrong, please send us a copy of the invoice.\n\n"
                f"Regards,\n{who}")
        out.append(SupplierMessage(g, name, len(fs), total, wa, subject, body))
    return out


def build_client_questions(res) -> list[dict]:
    qs = []
    for f in res.findings:
        if f.owner != Owner.CLIENT:
            continue
        d = (f.portal or f.books)[0]
        qs.append({
            "id": f.fid, "supplier": f.supplier_name or d.supplier_gstin, "gstin": d.supplier_gstin,
            "document": d.doc_no, "date": dt(d.doc_date), "itc": f.itc_at_stake,
            "question": f.next_step, "context": f.reason, "recommended": f.action.value,
        })
    qs.sort(key=lambda q: -q["itc"])
    return qs
