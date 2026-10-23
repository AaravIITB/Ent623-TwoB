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
from .common import ims_action, norm_header, tax_kind, to_date, to_float, to_period, yes

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
    "ledger": ["purchaseledger", "expenseledger", "expensehead", "accounthead", "ledger", "account",
               "glaccount", "natureofexpense", "expensetype", "category"],
    "description": ["itemdescription", "descriptionofgoods", "descriptionofgoodsservices", "goodsdescription",
                    "description", "itemname", "item", "stockitem", "productname", "narration", "remarks"],
    "hsn": ["hsnsac", "hsnsaccode", "hsncode", "saccode", "hsn", "sac", "hsnorsac"],
}
# Columnar registers (Tally) put each purchase/expense ledger in its own amount column.
# A non-zero amount under a header we don't otherwise recognise is read as that ledger.
_NOT_LEDGER = re.compile(r"total|value|amount|gross|net|round|rate|qty|quantity|balance|tds|tcs|voucher|"
                         r"^\s*(sl|sr|s)\.?\s*no|number|date|gstin|invoice|bill|reference|period|place", re.I)
TAX_FIELDS = ("igst", "cgst", "sgst", "cess")
VOUCHER_DATE = ("date", "voucherdate", "vchdate", "postingdate", "accountingdate")
AMENDMENT_NO = ("originalinvoicenumber", "originalinvoiceno", "originalnotenumber", "originalnoteno",
                "oinum", "ontnum", "originaldocumentnumber")


def _classify(header: str) -> str | None:
    h = norm_header(header)
    if not h:
        return None
    for field, names in SYNONYMS.items():
        if h in names:
            return field
    if h in AMENDMENT_NO:
        return "amends"
    return tax_kind(header)


def _map_columns(labels: list[str]) -> dict:
    """One column per field (best synonym wins); tax fields may span several
    columns (e.g. 'Input CGST 9%' and 'Input CGST 6%'), which are summed."""
    found: dict[str, tuple[int, int]] = {}
    tax_cols: dict[str, list[int]] = {}
    for idx, lab in enumerate(labels):
        f = _classify(lab)
        if not f:
            continue
        if f in TAX_FIELDS:
            tax_cols.setdefault(f, []).append(idx)
            continue
        h = norm_header(lab)
        rank = SYNONYMS[f].index(h) if f in SYNONYMS and h in SYNONYMS[f] else 50
        if f not in found or rank < found[f][0]:
            found[f] = (rank, idx)
    out: dict = {f: idx for f, (rank, idx) in found.items()}
    out.update(tax_cols)
    return out


def _find_header(df: pd.DataFrame, max_rows: int = 20):
    best = (0, None, None, None)
    rows = min(max_rows, len(df))
    for r in range(rows):
        cur = [str(x) if pd.notna(x) else "" for x in df.iloc[r].tolist()]
        prev = [str(x) if pd.notna(x) else "" for x in df.iloc[r - 1].tolist()] if r > 0 else [""] * len(cur)
        merged = [c if c.strip() else p for c, p in zip(cur, prev)]
        for labels in (cur, merged):
            cols = _map_columns(labels)
            score = len(cols) + (3 if "doc_no" in cols else 0) + (2 if "gstin" in cols else 0)
            if score > best[0]:
                best = (score, r, cols, labels)
    return best[1], best[2], best[3]


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


_SKIP_SHEETS = ("reject", "reversal", "read me", "readme", "summary")
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _read_csv(path: Path) -> pd.DataFrame:
    """CSV exports often have title rows and Windows encoding; read row by row."""
    import csv
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.reader(text.splitlines()))
    width = max((len(r) for r in rows), default=0)
    return pd.DataFrame([r + [None] * (width - len(r)) for r in rows], dtype=object).replace({"": None})


def _detect_period(sheets: dict, path: Path) -> str:
    """The 2B return period: from a 'Tax period' cell, else from the file name."""
    month = fy = ""
    for df in sheets.values():
        for r in range(min(15, len(df))):
            cells = [str(x).strip() for x in df.iloc[r].tolist() if pd.notna(x) and str(x).strip()]
            for i, c in enumerate(cells[:-1]):
                key = norm_header(c)
                if key in ("taxperiod", "returnperiod", "period") and not month:
                    nxt = cells[i + 1]
                    if to_period(nxt):
                        return to_period(nxt)
                    month = nxt[:3].lower()
                if key in ("financialyear", "fy") and not fy:
                    fy = cells[i + 1]
    if month in _MONTHS and fy:
        m = _MONTHS.index(month) + 1
        years = re.findall(r"\d{2,4}", fy)
        if years:
            y = int(years[0]) if len(years[0]) == 4 else 2000 + int(years[0])
            return f"{m:02d}{y if m >= 4 else y + 1}"
    m = re.search(r"(?<!\d)(0[1-9]|1[0-2])[-_]?(20\d{2})(?!\d)", path.stem)
    if m:
        return m.group(1) + m.group(2)
    return ""


def load(path: str | Path, side: Side, uid_prefix: str | None = None,
         period: str = "") -> tuple[list[Doc], list[str]]:
    path = Path(path)
    prefix = uid_prefix or ("B" if side == Side.BOOKS else "P")
    notes: list[str] = []
    if path.suffix.lower() == ".csv":
        sheets = {"csv": _read_csv(path)}
    else:
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
    file_period = ""
    if side == Side.PORTAL:
        file_period = to_period(period) or _detect_period(sheets, path)
        if not file_period:
            notes.append(f"{path.name}: could not tell which month's 2B this is - enter the period")
    docs: list[Doc] = []
    n = negatives = dated_numbers = 0
    for sheet, df in sheets.items():
        if df.empty:
            continue
        if any(k in sheet.lower() for k in _SKIP_SHEETS):
            if side == Side.PORTAL and any(k in sheet.lower() for k in ("reject", "reversal")):
                notes.append(f"{path.name}/{sheet}: skipped (rejected / reversal records are not ITC to match)")
            continue
        hdr, cols, labels = _find_header(df)
        if hdr is None or ("doc_no" not in cols and "voucher_no" not in cols):
            continue
        if "gstin" not in cols:
            notes.append(f"{path.name}/{sheet}: no supplier GSTIN column found - sheet skipped")
            continue
        if "doc_no" not in cols:
            cols["doc_no"] = cols["voucher_no"]
            notes.append(f"{path.name}/{sheet}: no supplier invoice no. column; using voucher no. "
                         "(matching will be weak - export the supplier invoice number)")
        vdate = next((i for i, lab in enumerate(labels) if norm_header(lab) in VOUCHER_DATE
                      and i != cols.get("date")), None)
        used_cols = {v for v in cols.values() if not isinstance(v, list)} | \
                    {i for v in cols.values() if isinstance(v, list) for i in v}
        ledger_cols = [i for i, lab in enumerate(labels) if i not in used_cols and i != vdate
                       and str(lab).strip() and str(lab).strip().lower() != "nan"
                       and not _NOT_LEDGER.search(str(lab))] if side == Side.BOOKS else []
        sheet_type = _sheet_doc_type(sheet)
        low = sheet.lower()
        amendment_sheet = side == Side.PORTAL and ("b2ba" in norm_header(low) or "cdnra" in norm_header(low)
                                                   or "amend" in low)
        not_available_sheet = side == Side.PORTAL and ("not available" in low or "ineligible" in low)
        used = 0
        for r in range(hdr + 1, len(df)):
            row = df.iloc[r].tolist()
            g = G.clean(row[cols["gstin"]]) if pd.notna(row[cols["gstin"]]) else ""
            raw_no = row[cols["doc_no"]]
            if hasattr(raw_no, "year") and not isinstance(raw_no, str):
                dated_numbers += 1                              # Excel turned '1-12' into a date
                raw_no = raw_no.strftime("%d-%m-%Y") if hasattr(raw_no, "strftime") else str(raw_no)
            no = "" if pd.isna(raw_no) else str(raw_no).strip()
            if no.endswith(".0") and no[:-2].isdigit():
                no = no[:-2]                                    # Excel turned 45 into 45.0
            if not g or not no or len(g) != 15:
                continue
            n += 1
            used += 1

            def val(f):
                return row[cols[f]] if f in cols and not isinstance(cols[f], list) else None

            def tax(f):
                return sum(to_float(row[i]) for i in cols.get(f, []))

            taxable = to_float(val("taxable"))
            igst, cgst, sgst, cess = tax("igst"), tax("cgst"), tax("sgst"), tax("cess")
            total = to_float(val("value")) if "value" in cols else None
            doc_type = _row_doc_type(row, cols, sheet_type, side)
            if doc_type == DocType.INVOICE and (taxable + igst + cgst + sgst + cess < 0 or
                                                (total is not None and total < 0)):
                doc_type = DocType.CREDIT_NOTE                  # a negative row is a return / credit note
                negatives += 1
            d = Doc(
                side=side, uid=f"{prefix}{n}", supplier_gstin=g, doc_no=no,
                doc_date=to_date(val("date")),
                taxable=round(abs(taxable), 2),
                igst=round(abs(igst), 2), cgst=round(abs(cgst), 2), sgst=round(abs(sgst), 2),
                cess=round(abs(cess), 2), doc_type=doc_type,
                supplier_name="" if pd.isna(val("name")) else str(val("name") or "").strip(),
                total_value=abs(total) if total is not None else None,
                pos=str(val("pos") or "") if "pos" in cols and pd.notna(val("pos")) else "",
                reverse_charge=(yes(val("rcm")) is True),
                itc_available=(False if not_available_sheet else yes(val("itc")) if "itc" in cols else None),
                itc_unavailable_reason=str(val("reason") or "") if "reason" in cols and pd.notna(val("reason")) else "",
                # Portal: the month of THIS 2B (never the supplier's GSTR-1 period column).
                period=file_period if side == Side.PORTAL else "",
                supplier_filing_date=to_date(val("filing_date")),
                irn=str(val("irn") or "") if "irn" in cols and pd.notna(val("irn")) else "",
                ims_action=ims_action(val("ims")) if "ims" in cols and pd.notna(val("ims")) else "",
                source=f"{path.name}:{sheet}", row_ref=f"row {r + 1}",
            )
            if side == Side.BOOKS:
                d.ledger = "" if val("ledger") is None or pd.isna(val("ledger")) else str(val("ledger")).strip()
                d.description = ("" if val("description") is None or pd.isna(val("description"))
                                 else str(val("description")).strip())
                h = val("hsn")
                d.hsn = "" if h is None or pd.isna(h) else str(h).strip().removesuffix(".0")
                extra = [str(labels[i]).strip() for i in ledger_cols if to_float(row[i])]
                if extra:
                    d.ledger = "; ".join(x for x in [d.ledger] + extra if x)
            if amendment_sheet:
                orig = val("amends")
                d.amends = "" if orig is None or pd.isna(orig) else str(orig).strip()
                d.amends = d.amends or "(original no. not given)"
            if "taxable" not in cols and d.total_value:
                d.taxable = round(d.total_value - d.tax, 2)      # value minus tax
            if side == Side.BOOKS:
                vd = to_date(row[vdate]) if vdate is not None else None
                d.period = (vd or d.doc_date).strftime("%m%Y") if (vd or d.doc_date) else ""
            docs.append(d)
        if used:
            notes.append(f"{path.name}/{sheet}: {used} rows read (header on row {hdr + 1})")
    if negatives:
        notes.append(f"{path.name}: {negatives} negative rows read as credit notes / returns")
    if dated_numbers:
        notes.append(f"{path.name}: {dated_numbers} invoice numbers were stored by Excel as dates; "
                     "they may not match - format that column as text before exporting")
    return docs, notes
