"""Tally XML export (Day Book / voucher export) -> purchase register.

Reads Purchase vouchers (invoices) and Debit Note / purchase-return vouchers
(which correspond to the supplier's credit notes in GSTR-2B).

Key fields:
  REFERENCE / REFERENCEDATE  supplier's invoice number and date (what 2B shows)
  VOUCHERNUMBER              Tally's own running number (NOT used for matching)
  PARTYGSTIN / PARTYNAME     supplier
  ledger entries             tax ledgers recognised by name (IGST / CGST / SGST / Cess)
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..models import Doc, DocType, Side
from .. import gstin as G
from .common import to_date, to_float

_TAX = {
    "igst": ("igst", "integrated"),
    "cgst": ("cgst", "central"),
    "sgst": ("sgst", "utgst", "state tax", "sgst/utgst"),
    "cess": ("cess",),
}
_SKIP_LEDGER = ("round", "tds", "discount")


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
    # Tally writes control characters as &#4; etc., which are illegal in XML 1.0.
    text = re.sub(r"&#(?:[0-8]|1[124-9]|2\d|3[01]);", "", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def _txt(el, *tags):
    for t in tags:
        x = el.find(t)
        if x is not None and x.text and x.text.strip():
            return x.text.strip()
    return ""


def _tax_kind(ledger: str) -> str | None:
    l = ledger.lower()
    for kind, keys in _TAX.items():
        if any(k in l for k in keys):
            return kind
    return None


def load(path: str | Path, uid_prefix: str = "B") -> tuple[list[Doc], list[str]]:
    path = Path(path)
    root = ET.fromstring(_read_text(path))
    docs: list[Doc] = []
    notes: list[str] = []
    no_ref = 0
    n = 0
    for v in root.iter("VOUCHER"):
        vtype = (_txt(v, "VOUCHERTYPENAME") or v.get("VCHTYPE") or "").lower()
        if "purchase" in vtype and "order" not in vtype:
            dtype = DocType.INVOICE
            if "return" in vtype:
                dtype = DocType.CREDIT_NOTE
        elif "debit note" in vtype or "debit" in vtype:
            dtype = DocType.CREDIT_NOTE
        else:
            continue
        if (_txt(v, "ISCANCELLED") or "").lower() == "yes":
            continue
        party = _txt(v, "PARTYLEDGERNAME", "PARTYNAME")
        g = G.clean(_txt(v, "PARTYGSTIN", "GSTREGISTRATIONNUMBER"))
        ref = _txt(v, "REFERENCE", "SUPPLIERINVOICENO")
        vno = _txt(v, "VOUCHERNUMBER")
        if not ref:
            no_ref += 1
        amounts = {"igst": 0.0, "cgst": 0.0, "sgst": 0.0, "cess": 0.0}
        taxable = 0.0
        party_amt = None
        entries = list(v.iter("ALLLEDGERENTRIES.LIST")) + list(v.iter("LEDGERENTRIES.LIST"))
        for e in entries:
            led = _txt(e, "LEDGERNAME")
            amt = abs(to_float(_txt(e, "AMOUNT")))
            if not led:
                continue
            if party and led.strip().lower() == party.strip().lower():
                party_amt = amt
                continue
            kind = _tax_kind(led)
            if kind:
                amounts[kind] += amt
            elif not any(s in led.lower() for s in _SKIP_LEDGER):
                taxable += amt
        inv = list(v.iter("ALLINVENTORYENTRIES.LIST")) + list(v.iter("INVENTORYENTRIES.LIST"))
        inv_total = sum(abs(to_float(_txt(i, "AMOUNT"))) for i in inv)
        if inv_total and not taxable:
            taxable = inv_total
        if not g:
            continue
        n += 1
        d = Doc(
            side=Side.BOOKS, uid=f"{uid_prefix}{n}", supplier_gstin=g,
            doc_no=ref or vno,
            doc_date=to_date(_txt(v, "REFERENCEDATE") or _txt(v, "DATE")),
            taxable=round(taxable, 2), igst=round(amounts["igst"], 2), cgst=round(amounts["cgst"], 2),
            sgst=round(amounts["sgst"], 2), cess=round(amounts["cess"], 2), doc_type=dtype,
            supplier_name=party, total_value=party_amt,
            reverse_charge=(_txt(v, "ISREVERSECHARGEAPPLICABLE").lower() == "yes"),
            source=f"{path.name}:voucher {vno}", row_ref=f"Tally voucher {vno}",
        )
        voucher_date = to_date(_txt(v, "DATE"))
        d.period = (voucher_date or d.doc_date).strftime("%m%Y") if (voucher_date or d.doc_date) else ""
        docs.append(d)
    notes.append(f"{path.name}: {len(docs)} purchase/debit-note vouchers read")
    if no_ref:
        notes.append(f"{path.name}: {no_ref} vouchers have no supplier invoice no. (REFERENCE); "
                     "Tally voucher no. used instead - these will match poorly")
    return docs, notes
