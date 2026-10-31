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
from .common import (clean_doc_no, clean_name, clean_text, ims_action, is_error, norm_header, tax_kind,
                     to_date, to_float, to_period, yes)
from .. import narration as NR

# Exact header names (after lower-casing and removing spaces/punctuation), in priority order.
SYNONYMS = {
    "gstin": ["gstinofsupplier", "suppliergstin", "gstinuinofsupplier", "partygstinuin", "partygstin",
              "gstinuin", "gstin", "ctin", "suppliersgstin", "gstinno", "vendorgstin"],
    "name": ["tradelegalname", "tradename", "legalname", "suppliername", "nameofsupplier", "partyname",
             "partyledgername", "vendorname", "particulars", "party", "ledgername"],
    "doc_no": ["supplierinvoiceno", "supplierinvoicenumber", "supplierinvno", "supplierbillno",
               "invoicenumber", "invoiceno", "invno", "billno", "billnumber", "notenumber", "noteno",
               "creditdebitnotenumber", "documentnumber", "documentno", "docno", "referenceno",
               "refno", "reference", "inum", "voucherrefno", "supplierrefno", "vchrefno"],
    "voucher_no": ["voucherno", "vouchernumber", "vchno"],
    "date": ["supplierinvoicedate", "invoicedate", "billdate", "notedate", "documentdate", "docdate",
             "referencedate", "invdate", "voucherrefdate", "vchrefdate", "dt", "date", "voucherdate"],
    "taxable": ["taxablevalue", "taxableamount", "taxable", "assessablevalue", "assessableamount", "txval"],
    "value": ["invoicevalue", "totalinvoicevalue", "notevalue", "grosstotal", "invoiceamount",
              "totalamount", "total", "billamount", "val", "value"],
    "pos": ["placeofsupply", "pos"],
    "rcm": ["supplyattractreversecharge", "reversecharge", "rcm", "rev"],
    "itc": ["itcavailability", "itcavailibility", "itcavailabilty", "itcavailable", "itcavl", "eligibleforitc"],
    "reason": ["reason", "rsn", "reasonforitcunavailability"],
    "period": ["gstr1iffgstr5period", "gstr1period", "returnperiod", "taxperiod", "supprd", "period"],
    "filing_date": ["gstr1iffgstr5filingdate", "gstr1filingdate", "filingdate", "supfildt"],
    "irn": ["irn"],
    "note_type": ["notetype", "typeofnote", "ntty", "notetypecreditdebit", "invoicetype", "documenttype",
                  "typeofdocument", "doctype", "invtyp"],
    "voucher_type": ["vouchertype", "vchtype", "transactiontype"],
    "ims": ["imsaction", "actiontaken", "action", "imsstatus", "currentaction"],
    "ledger": ["purchaseledger", "expenseledger", "expensehead", "accounthead", "ledger", "account",
               "glaccount", "natureofexpense", "expensetype", "category", "activity", "natureofactivity"],
    "description": ["itemdescription", "descriptionofgoods", "descriptionofgoodsservices", "goodsdescription",
                    "description", "itemname", "item", "stockitem", "productname", "narration", "remarks"],
    "hsn": ["hsnsac", "hsnsaccode", "hsncode", "saccode", "hsn", "sac", "hsnorsac"],
    "eligible": ["itceligiblity", "itceligibility", "itceligible", "eligibility", "eligibleitc", "itcclaimable",
                 "itcelig", "eligible"],
    "pan": ["panno", "pan", "pannumber", "supplierpan", "partypan", "itpan"],
}
# a column headed just 'Period' in a firm's flattened 2B sheet is the 2B month ('June,2026');
# the supplier's GSTR-1 period has its own header.
TWOB_PERIOD = ("period", "2bperiod", "gstr2bperiod", "itcperiod")
# Columnar registers (Tally) put each purchase/expense ledger in its own amount column.
# A non-zero amount under a header we don't otherwise recognise is read as that ledger.
_NOT_LEDGER = re.compile(r"total|value|amount|gross|net|round|rate|qty|quantity|balance|tds|tcs|voucher|"
                         r"address|lookup|remark|tax\s*no|cst|\bpan\b|\btin\b|uin|narration|status|"
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


def _alternates(labels: list[str], field: str, chosen: int | None) -> list[int]:
    """Other columns that could also hold `field`, best first (used when the chosen one is blank)."""
    names = SYNONYMS[field]
    alts = [(names.index(norm_header(l)), i) for i, l in enumerate(labels)
            if norm_header(l) in names and i != chosen]
    return [i for _, i in sorted(alts)]


def _sheet_role(sheet: str, labels: list[str], cols: dict) -> str:
    """'portal', 'books' or '' (can't tell) - so one workbook can hold both registers."""
    heads = {norm_header(l) for l in labels}
    name = norm_header(sheet)
    portal = ("filing_date" in cols or "itc" in cols or any(h.startswith(("gstr1", "gstr15")) for h in heads)
              or "gstinofsupplier" in heads or re.search(r"2b|2a|ims|portal", name) is not None)
    books = ("voucher_type" in cols or "voucher_no" in cols or "narration" in heads or "particulars" in heads
             or re.search(r"purchase|register|books|ledger|daybook|pr$", name) is not None)
    if portal and not books:
        return "portal"
    if books and not portal:
        return "books"
    if re.search(r"2b|2a|ims", name):
        return "portal"
    if re.search(r"purchase|register|books", name):
        return "books"
    return ""


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
        if t in ("d", "dn", "dr") or t.startswith("debit"):
            return DocType.DEBIT_NOTE           # not 'Deemed Exports'
        if t in ("c", "cn", "cr") or t.startswith("credit"):
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


_TOTAL_ROW = re.compile(r"^\s*(grand\s*)?(sub\s*)?total\b", re.I)
_GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b")


def _numeric(v) -> bool:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v == v and v != 0
    return bool(re.fullmatch(r"\s*\(?-?[\d,]+(\.\d+)?\)?\s*", str(v or ""))) and to_float(v) != 0


def load(path: str | Path, side: Side, uid_prefix: str | None = None,
         period: str = "") -> tuple[list[Doc], list[str]]:
    path = Path(path)
    prefix = uid_prefix or ("B" if side == Side.BOOKS else "P")
    notes: list[str] = []
    if path.suffix.lower() == ".csv":
        sheets = {"csv": _read_csv(path)}
    else:
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
    sheets = {k: v.map(lambda x: None if is_error(x) else x) for k, v in sheets.items()}
    file_period = ""
    hint = to_period(period) if side == Side.PORTAL else ""
    if side == Side.PORTAL:
        # the file's own month wins over the period typed for the run: several months' 2B are often
        # loaded together (earlier months for reclaims, next month for late filers)
        file_period = _detect_period(sheets, path)
    docs: list[Doc] = []
    n = negatives = dated_numbers = 0
    no_gstin = no_number = from_narr_no = from_narr_date = 0
    sheet_periods: list[str] = []
    # which sheets belong to which side: a sheet is skipped for looking like the other side only when the
    # workbook also has a sheet that looks like this side (a one-sheet books file is always read)
    roles = {}
    for sheet, df in sheets.items():
        if df.empty or any(k in sheet.lower() for k in _SKIP_SHEETS):
            continue
        h, c, lab = _find_header(df)
        if h is not None and "gstin" in c and ("doc_no" in c or "voucher_no" in c):
            roles[sheet] = _sheet_role(sheet, lab, c)
    mine = [k for k, v in roles.items() if v == side.value]
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
        role = roles.get(sheet, "")
        if role and role != side.value:
            what = "2B / portal data" if role == "portal" else "a purchase register"
            if mine:
                notes.append(f"{path.name}/{sheet}: looks like {what} - not read as {'books' if side == Side.BOOKS else '2B'}")
                continue
            notes.append(f"{path.name}/{sheet}: looks like {what} but was given as "
                         f"{'books' if side == Side.BOOKS else '2B'} - read anyway; check the right file was uploaded")
        if "doc_no" not in cols:
            cols["doc_no"] = cols["voucher_no"]
            notes.append(f"{path.name}/{sheet}: no supplier invoice no. column; using voucher no. "
                         "(matching will be weak - export the supplier invoice number)")
        no_cols = [cols["doc_no"]] + _alternates(labels, "doc_no", cols["doc_no"])
        no_cols = [i for i in no_cols if i != cols.get("voucher_no")]
        date_cols = ([cols["date"]] + _alternates(labels, "date", cols["date"])) if "date" in cols else []
        vdate = next((i for i, lab in enumerate(labels) if norm_header(lab) in VOUCHER_DATE
                      and i != cols.get("date")), None)
        narr_col = next((i for i, lab in enumerate(labels) if norm_header(lab) in ("narration", "remarks", "remark",
                                                                                 "particularsnarration")), None)
        if narr_col is None and "description" in cols:
            narr_col = cols["description"]
        # In a Tally journal / day-book register the only date is the voucher (booking) date; the
        # supplier's invoice date, if anywhere, is in the narration.
        register_like = (side == Side.BOOKS and ("voucher_type" in cols or "voucher_no" in cols)
                         and narr_col is not None)
        generic = set(VOUCHER_DATE) | {"dt"}
        inv_date_cols = [i for i in date_cols if norm_header(labels[i]) not in generic]
        vch_date_cols = [i for i in date_cols if norm_header(labels[i]) in generic]
        if vdate is not None and vdate not in vch_date_cols:
            vch_date_cols.append(vdate)
        gst_alt = [i for i, lab in enumerate(labels) if i != cols["gstin"] and
                   re.search(r"gst|tax\s*no|tin|uin|registration", str(lab), re.I)]
        tp_col = next((i for i, lab in enumerate(labels) if norm_header(lab) in TWOB_PERIOD), None) \
            if side == Side.PORTAL else None
        used_cols = {v for v in cols.values() if not isinstance(v, list)} | \
                    {i for v in cols.values() if isinstance(v, list) for i in v} | set(no_cols) | set(date_cols)
        ledger_cols = [i for i, lab in enumerate(labels) if i not in used_cols and i != vdate and i != narr_col
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

            def val(f):
                return row[cols[f]] if f in cols and not isinstance(cols[f], list) else None

            def tax(f):
                return sum(to_float(row[i]) for i in cols.get(f, []))

            g = G.clean(row[cols["gstin"]]) if pd.notna(row[cols["gstin"]]) else ""
            if len(g) != 15 and side == Side.BOOKS:
                for i in gst_alt:                       # GSTIN keyed into 'Sales Tax No.' and the like
                    m = _GSTIN_RE.search(clean_text(row[i]).upper())
                    if m:
                        g = m.group(0)
                        break
            no, raw_used = "", None
            for i in no_cols:
                raw_no = row[i]
                if raw_no is None or (not isinstance(raw_no, str) and pd.isna(raw_no)):
                    continue
                if hasattr(raw_no, "year") and not isinstance(raw_no, str):
                    dated_numbers += 1                          # Excel turned '1-12' into a date
                    raw_no = raw_no.strftime("%d-%m-%Y") if hasattr(raw_no, "strftime") else str(raw_no)
                no = clean_doc_no(raw_no)
                if no:
                    raw_used = i
                    break
            name = clean_name(val("name"))
            taxable = to_float(val("taxable"))
            igst, cgst, sgst, cess = tax("igst"), tax("cgst"), tax("sgst"), tax("cess")
            total = to_float(val("value")) if "value" in cols and val("value") is not None else None
            narration = clean_text(row[narr_col]) if narr_col is not None else ""
            row_notes = []
            if side == Side.PORTAL:
                if not g or not no or len(g) != 15:
                    continue
            else:
                if _TOTAL_ROW.match(name or "") or (not name and len(g) != 15):
                    continue
                if len(g) != 15:
                    g = ""
                if not any(abs(x) > 0.004 for x in (taxable, igst, cgst, sgst, cess)) and not no and not narration:
                    continue                                    # blank / separator line
            n += 1
            used += 1
            heads = [x for x in (igst, cgst, sgst, cess) if abs(x) > 0.004]
            mixed = any(x < 0 for x in heads) and any(x > 0 for x in heads)
            doc_type = _row_doc_type(row, cols, sheet_type, side)
            if doc_type == DocType.INVOICE and (taxable + igst + cgst + sgst + cess < 0 or
                                                igst + cgst + sgst + cess < -0.004 or
                                                (total is not None and total < 0 and taxable <= 0)):
                doc_type = DocType.CREDIT_NOTE                  # a negative row is a return / credit note
                negatives += 1
            raw_date = next((to_date(row[i]) for i in inv_date_cols if to_date(row[i])), None)
            vch_date = next((to_date(row[i]) for i in vch_date_cols if to_date(row[i])), None)
            booking_date_only = raw_date is None and register_like
            if raw_date is None and not register_like:
                raw_date = vch_date
            d = Doc(
                side=side, uid=f"{prefix}{n}", supplier_gstin=g, doc_no=no,
                doc_date=raw_date,
                taxable=round(abs(taxable), 2),
                igst=round(abs(igst), 2), cgst=round(abs(cgst), 2), sgst=round(abs(sgst), 2),
                cess=round(abs(cess), 2), doc_type=doc_type,
                supplier_name=name,
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
            if side == Side.PORTAL and not file_period and tp_col is not None:
                rp = to_period(clean_text(row[tp_col]))
                if rp:
                    sheet_periods.append(rp)
            if "note_type" in cols and side == Side.PORTAL:
                t = norm_header(row[cols["note_type"]])
                if t in ("b2ba", "cdnra", "amended", "amendment") or t.endswith("amendment"):
                    d.amends = d.amends or "(original no. not given)"
                    # a firm's flattened sheet lists only the difference, signed, with no original no.
                    if "amends" not in cols:
                        d.amend_is_delta = True
                        d.doc_type = DocType.INVOICE
                        d.taxable, d.igst, d.cgst, d.sgst, d.cess = (round(x, 2) for x in (taxable, igst, cgst, sgst, cess))
            if mixed and side == Side.BOOKS:
                # e.g. a journal moving tax from IGST to CGST/SGST: keep the signs, it is not a bill
                d.doc_type = DocType.INVOICE
                d.igst, d.cgst, d.sgst, d.cess = (round(x, 2) for x in (igst, cgst, sgst, cess))
                d.adjustment = True
                d.notes.append("tax heads have mixed signs (a tax-head transfer or correction journal?)")
                if abs(igst + cgst + sgst + cess) < 0.5:
                    d.no_itc_reason = "tax-head transfer journal, nets to zero"
            led = clean_text(val("ledger"))
            d.ledger = led
            d.eligible = yes(clean_text(val("eligible"))) if "eligible" in cols else None
            if side == Side.BOOKS:
                d.description = clean_text(val("description")) or narration
                h = val("hsn")
                d.hsn = "" if h is None or pd.isna(h) else str(h).strip().removesuffix(".0")
                extra = [str(labels[i]).strip() for i in ledger_cols if _numeric(row[i])]
                if extra:
                    d.ledger = "; ".join(x for x in [d.ledger] + extra if x)
                if "voucher_no" in cols:
                    d.voucher_no = clean_doc_no(row[cols["voucher_no"]])
                pan = clean_text(val("pan")).upper() if "pan" in cols else ""
                if not g and re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", pan):
                    d.notes.append(f"pan:{pan}")
                d.voucher_date = vch_date if (register_like or inv_date_cols) else None
                # credit note described in the narration: 'Credit note no 2026-27/07, against invoice no 2025-26/731'
                cn, orig = NR.credit_note(narration)
                if cn and doc_type == DocType.CREDIT_NOTE:
                    if no and no != cn:
                        d.ref_doc_no = no
                    d.doc_no = cn
                    d.doc_type = DocType.CREDIT_NOTE
                    d.ref_doc_no = orig or d.ref_doc_no
                    row_notes.append(f"credit note no. '{cn}' read from the narration")
                elif not no and narration:
                    got, how = NR.invoice_no_how(narration)
                    if got:
                        d.doc_no = got
                        from_narr_no += 1
                        row_notes.append(f"invoice no. '{got}' read from the narration"
                                         + (" (no 'invoice no' keyword - a guess)" if how == "bare" else ""))
                if NR.RCM.search(narration) or NR.RCM.search(d.ledger or ""):
                    d.reverse_charge = True
                if d.doc_date is None and narration:
                    nd = NR.invoice_date(narration, near=d.doc_no, booked=d.voucher_date)
                    if nd:
                        d.doc_date = nd
                        from_narr_date += 1
                        row_notes.append(f"invoice date {nd.strftime('%d-%m-%Y')} read from the narration")
                if d.doc_date is None and booking_date_only and d.voucher_date:
                    # no date in the narration: the register's date is the best we have (in a hand-made
                    # sheet it usually IS the invoice date)
                    d.doc_date = d.voucher_date
                    row_notes.append("invoice date not in the narration; using the register date "
                                     f"{d.voucher_date.strftime('%d-%m-%Y')}")
                if NR.CORRECTION.search(narration):
                    d.adjustment = True
                    d.ref_doc_no = d.ref_doc_no or d.doc_no or NR.invoice_no(narration)
                if d.tax < 0.5 and not mixed and abs(d.tax) < 0.5:
                    d.no_itc_reason = ("advance / proforma - no tax invoice yet" if NR.ADVANCE.search(narration)
                                       else "provision entry" if re.search(r"provision", narration, re.I)
                                       else "no GST charged" if g else "no GST charged, supplier unregistered")
                elif NR.ADVANCE.search(narration) and re.search(r"proforma|pro-forma|pro forma", narration, re.I):
                    row_notes.append("narration says advance against a proforma invoice: no ITC until the tax invoice")
                if not g:
                    no_gstin += 1
                if not d.doc_no:
                    no_number += 1
                d.notes.extend(row_notes)
            if amendment_sheet:
                orig = val("amends")
                d.amends = "" if orig is None or pd.isna(orig) else str(orig).strip()
                d.amends = d.amends or "(original no. not given)"
            if "taxable" not in cols and d.total_value:
                d.taxable = round(d.total_value - d.tax, 2)      # value minus tax
            if side == Side.BOOKS:
                vd = d.voucher_date
                d.period = (vd or d.doc_date).strftime("%m%Y") if (vd or d.doc_date) else ""
            docs.append(d)
        if used:
            notes.append(f"{path.name}/{sheet}: {used} rows read (header on row {hdr + 1})")
    if side == Side.PORTAL and not file_period:
        if sheet_periods and hint and hint not in sheet_periods:
            notes.append(f"{path.name}: its 'Period' column says {max(set(sheet_periods), key=sheet_periods.count)}, "
                         f"not the {hint[:2]}/{hint[2:]} entered; the file's own month is used")
        if not sheet_periods and hint:
            for d in docs:
                d.period = d.period or hint
        elif sheet_periods:
            # one sheet = one 2B download: the most common 'Period' label is the month; stray labels
            # (a record carried over from an older month) stay with this 2B
            common = max(set(sheet_periods), key=sheet_periods.count)
            odd = sum(1 for x in sheet_periods if x != common)
            if odd > 0.1 * len(sheet_periods):
                notes.append(f"{path.name}: the 'Period' column holds several months ({', '.join(sorted(set(sheet_periods)))}); "
                             "enter the 2B month, or load one month per file. All rows were taken as the most common month.")
            for d in docs:
                d.period = d.period or common
            notes.append(f"{path.name}: 2B period {common[:2]}/{common[2:]} read from the 'Period' column"
                         + (f" ({odd} rows carry another month's label and are kept with it)" if odd else ""))
        if not sheet_periods and not hint:
            notes.append(f"{path.name}: could not tell which month's 2B this is - enter the period")
    if negatives:
        notes.append(f"{path.name}: {negatives} negative rows read as credit notes / returns")
    if dated_numbers:
        notes.append(f"{path.name}: {dated_numbers} invoice numbers were stored by Excel as dates; "
                     "they may not match - format that column as text before exporting")
    if from_narr_no:
        notes.append(f"{path.name}: {from_narr_no} invoice numbers were blank and were read from the narration")
    if from_narr_date:
        notes.append(f"{path.name}: {from_narr_date} invoice dates were read from the narration")
    if no_gstin:
        notes.append(f"{path.name}: {no_gstin} books rows have no supplier GSTIN; TaxMind looks the supplier up "
                     "by name and PAN (fill the GSTIN in the ledger master to make this certain)")
    return docs, notes


def detect_client_gstin(path) -> str:
    """The client's own GSTIN from a GSTR-3B / summary sheet ('GSTIN' label next to the number)."""
    path = Path(path)
    if path.suffix.lower() not in (".xlsx", ".xlsm", ".xls"):
        return ""
    try:
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object, nrows=15)
    except Exception:
        return ""
    for name, df in sheets.items():
        if not re.search(r"summary|3b|basic|details", name, re.I):
            continue
        for r in range(len(df)):
            cells = [clean_text(x) for x in df.iloc[r].tolist()]
            for i, c in enumerate(cells):
                if norm_header(c) in ("gstin", "gstinofthetaxpayer", "gstinuin"):
                    for nxt in cells[i + 1:i + 6]:
                        if re.match(r"^\d{2}[A-Z]{5}\d{4}[A-Z0-9]", nxt.upper()):
                            return nxt.upper()
    return ""
