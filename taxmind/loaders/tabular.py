"""Excel / CSV loader for both sides.

Works for:
  * the GSTR-2B Excel download (two-row headers, sheets 'B2B', 'B2B-CDNR', ...)
  * Tally / Busy / Zoho purchase-register exports
  * any sheet a CA has built by hand, as long as the column names are recognisable.

Columns are recognised by name (see SYNONYMS). The header row is found
automatically; a header split over two rows (merged cells) is handled.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..models import Doc, DocType, Side
from .. import gstin as G
from .common import ims_action, norm_header, to_date, to_float, to_period, yes

# Exact header names (after lower-casing and removing spaces/punctuation), in priority order.
SYNONYMS = {
    "gstin": ["gstinofsupplier", "suppliergstin", "gstinuinofsupplier", "partygstinuin", "partygstin",
              "gstinuin", "gstin", "ctin", "suppliersgstin", "gstinno", "vendorgstin"],
    "name": ["tradelegalname", "tradename", "legalname", "suppliername", "nameofsupplier", "partyname",
             "partyledgername", "vendorname", "particulars", "party", "ledgername"],
    "doc_no": ["supplierinvoiceno", "supplierinvoicenumber", "supplierinvno", "supplierbillno",
               "invoicenumber", "invoiceno", "invno", "billno", "billnumber", "notenumber", "noteno",
               "creditdebitnotenumber", "documentnumber", "documentno", "docno", "referenceno",
               "refno", "reference", "inum"],
    "voucher_no": ["voucherno", "vouchernumber", "vchno"],
    "date": ["supplierinvoicedate", "invoicedate", "billdate", "notedate", "documentdate", "docdate",
             "referencedate", "invdate", "dt", "date", "voucherdate"],
    "taxable": ["taxablevalue", "taxableamount", "taxable", "assessablevalue", "assessableamount", "txval"],
    "value": ["invoicevalue", "totalinvoicevalue", "notevalue", "grosstotal", "invoiceamount",
              "totalamount", "total", "billamount", "val", "value"],
    "pos": ["placeofsupply", "pos"],
    "rcm": ["supplyattractreversecharge", "reversecharge", "rcm", "rev"],
    "itc": ["itcavailability", "itcavailable", "itcavl", "eligibleforitc"],
    "reason": ["reason", "rsn", "reasonforitcunavailability"],
    "period": ["gstr1iffgstr5period", "gstr1period", "returnperiod", "taxperiod", "supprd", "period"],
    "filing_date": ["gstr1iffgstr5filingdate", "gstr1filingdate", "filingdate", "supfildt"],
    "irn": ["irn"],
    "note_type": ["notetype", "typeofnote", "ntty", "notetypecreditdebit"],
    "voucher_type": ["vouchertype", "vchtype", "transactiontype"],
    "ims": ["imsaction", "actiontaken", "action", "imsstatus", "currentaction"],
}
# Tax columns are matched by substring because exports name them many ways.
TAX_PARTS = {
    "igst": ("igst", "integratedtax", "integrated"),
    "cgst": ("cgst", "centraltax", "central"),
    "sgst": ("sgst", "utgst", "stateuttax", "statetax", "uttax"),
    "cess": ("cess",),
}
# Skip 'Tax Rate', 'Applicable % of Tax Rate' etc. Whole words only: 'Integrated' contains 'rate'.
_TAX_EXCLUDE = re.compile(r"\brates?\b|applicable|percent", re.I)


def _classify(header: str) -> str | None:
    h = norm_header(header)
    if not h:
        return None
    for field, names in SYNONYMS.items():
        if h in names:
            return field
    if _TAX_EXCLUDE.search(str(header)):
        return None
    for field, parts in TAX_PARTS.items():
        if any(p in h for p in parts):
            return field
    return None


def _map_columns(labels: list[str]) -> dict:
    """One column per field (best synonym wins); tax fields may span several
    columns (e.g. 'Input CGST 9%' and 'Input CGST 6%'), which are summed."""
    found: dict[str, tuple[int, int]] = {}
    tax_cols: dict[str, list[int]] = {}
    for idx, lab in enumerate(labels):
        f = _classify(lab)
        if not f:
            continue
        if f in TAX_PARTS:
            tax_cols.setdefault(f, []).append(idx)
            continue
        h = norm_header(lab)
        rank = SYNONYMS[f].index(h) if h in SYNONYMS[f] else 50
        if f not in found or rank < found[f][0]:
            found[f] = (rank, idx)
    out: dict = {f: idx for f, (rank, idx) in found.items()}
    out.update(tax_cols)
    return out


def _find_header(df: pd.DataFrame, max_rows: int = 20):
    best = (0, None, None)
    rows = min(max_rows, len(df))
    for r in range(rows):
        cur = [str(x) if pd.notna(x) else "" for x in df.iloc[r].tolist()]
        prev = [str(x) if pd.notna(x) else "" for x in df.iloc[r - 1].tolist()] if r > 0 else [""] * len(cur)
        merged = [c if c.strip() else p for c, p in zip(cur, prev)]
        for labels in (cur, merged):
            cols = _map_columns(labels)
            score = len(cols) + (3 if "doc_no" in cols else 0) + (2 if "gstin" in cols else 0)
            if score > best[0]:
                best = (score, r, cols)
    return best[1], best[2]


def _sheet_doc_type(sheet: str) -> DocType | None:
    s = sheet.lower()
    if "cdn" in s or "credit" in s or "debit" in s or "note" in s:
        return DocType.CREDIT_NOTE
    return None


def _row_doc_type(row, cols, sheet_default, side: Side) -> DocType:
    if "note_type" in cols:
        t = str(row[cols["note_type"]]).strip().lower()
        if t.startswith("d"):
            return DocType.DEBIT_NOTE
        if t.startswith("c"):
            return DocType.CREDIT_NOTE
    if "voucher_type" in cols and side == Side.BOOKS:
        t = str(row[cols["voucher_type"]]).lower()
        # In the buyer's books a purchase return is a Debit Note voucher;
        # it corresponds to the supplier's credit note in GSTR-2B.
        if "return" in t or "debit note" in t or "credit note" in t:
            return DocType.CREDIT_NOTE
    return sheet_default or DocType.INVOICE


def load(path: str | Path, side: Side, uid_prefix: str | None = None,
         period: str = "") -> tuple[list[Doc], list[str]]:
    path = Path(path)
    prefix = uid_prefix or ("B" if side == Side.BOOKS else "P")
    notes: list[str] = []
    if path.suffix.lower() == ".csv":
        sheets = {"csv": pd.read_csv(path, header=None, dtype=object)}
    else:
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
    docs: list[Doc] = []
    n = 0
    for sheet, df in sheets.items():
        if df.empty:
            continue
        hdr, cols = _find_header(df)
        if hdr is None or ("doc_no" not in cols and "voucher_no" not in cols):
            continue
        if "gstin" not in cols:
            notes.append(f"{path.name}/{sheet}: no supplier GSTIN column found - sheet skipped")
            continue
        if "doc_no" not in cols:
            cols["doc_no"] = cols["voucher_no"]
            notes.append(f"{path.name}/{sheet}: no supplier invoice no. column; using voucher no. "
                         "(matching will be weak - export the supplier invoice number)")
        sheet_type = _sheet_doc_type(sheet)
        used = 0
        for r in range(hdr + 1, len(df)):
            row = df.iloc[r].tolist()
            g = G.clean(row[cols["gstin"]]) if pd.notna(row[cols["gstin"]]) else ""
            no = row[cols["doc_no"]]
            no = "" if pd.isna(no) else str(no).strip()
            if no.endswith(".0") and no[:-2].isdigit():
                no = no[:-2]                                    # Excel turned 45 into 45.0
            if not g or not no or len(g) != 15:
                continue
            n += 1
            used += 1

            def val(f):
                return row[cols[f]] if f in cols else None

            def tax(f):
                return sum(to_float(row[i]) for i in cols.get(f, []))

            d = Doc(
                side=side, uid=f"{prefix}{n}", supplier_gstin=g, doc_no=no,
                doc_date=to_date(val("date")),
                taxable=round(to_float(val("taxable")), 2),
                igst=round(tax("igst"), 2), cgst=round(tax("cgst"), 2),
                sgst=round(tax("sgst"), 2), cess=round(tax("cess"), 2),
                doc_type=_row_doc_type(row, cols, sheet_type, side),
                supplier_name="" if pd.isna(val("name")) else str(val("name") or "").strip(),
                total_value=to_float(val("value")) if "value" in cols else None,
                pos=str(val("pos") or "") if "pos" in cols and pd.notna(val("pos")) else "",
                reverse_charge=(yes(val("rcm")) is True),
                itc_available=yes(val("itc")) if "itc" in cols else None,
                itc_unavailable_reason=str(val("reason") or "") if "reason" in cols and pd.notna(val("reason")) else "",
                period=(to_period(val("period")) if side == Side.PORTAL and "period" in cols else "") or period,
                supplier_filing_date=to_date(val("filing_date")),
                irn=str(val("irn") or "") if "irn" in cols and pd.notna(val("irn")) else "",
                ims_action=ims_action(val("ims")) if "ims" in cols and pd.notna(val("ims")) else "",
                source=f"{path.name}:{sheet}", row_ref=f"row {r + 1}",
            )
            # Credit/debit notes are often exported as negative numbers; keep magnitudes.
            for f in ("taxable", "igst", "cgst", "sgst", "cess"):
                setattr(d, f, abs(getattr(d, f)))
            if d.total_value is not None:
                d.total_value = abs(d.total_value)
            if "taxable" not in cols and d.total_value:
                d.taxable = round(d.total_value - d.tax, 2)      # value minus tax
            if side == Side.BOOKS and not d.period and d.doc_date:
                d.period = d.doc_month
            docs.append(d)
        if used:
            notes.append(f"{path.name}/{sheet}: {used} rows read (header on row {hdr + 1})")
    return docs, notes
