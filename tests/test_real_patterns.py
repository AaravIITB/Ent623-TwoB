"""Patterns seen in a real CA firm's month (Tally journal register + the firm's flattened 2B sheet).

All names, GSTINs and numbers here are invented; only the layouts and habits are real.
Run with:  python -m pytest -q
"""
import random
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook

from taxmind import Config, Side, load_file, reconcile
from taxmind import narration as N
from taxmind.blocked import apply as apply_blocked
from taxmind.gstr3b import LedgerItem, load_ledger, write_ledger
from taxmind.models import Action, Doc, DocType, Finding, Status
from taxmind.synth import make_gstin

RNG = random.Random(42)
S1 = make_gstin(RNG, "27")          # big equipment supplier, often keyed without GSTIN
S2 = make_gstin(RNG, "06")          # paint-shop contractor, inter-state
S3 = make_gstin(RNG, "27")          # coffee vendor (books keep it without GST)
S4 = make_gstin(RNG, "27")          # cab operator
S5 = make_gstin(RNG, "27")          # tours: credit notes
S6 = make_gstin(RNG, "29")          # airline never in this register
CLIENT = make_gstin(RNG, "27")

BOOKS_HDR = ["Date", "Particulars", "Address", "Voucher Type", "Voucher No.", "Voucher Ref. No.", "Voucher Ref. Date",
             "GSTIN/UIN", "Sales Tax No.", "Service Tax No.", "PAN No.", "CST No.", "Invoice No", "Narration",
             "Gross Total", "Taxable", "IGST", "CGST", "SGST", "Total Tax", "Rate", "Lookup", "Remark", "Activity",
             "ITC ELIGIBLITY"]
TWOB_HDR = ["Period", "GSTIN of supplier", "Trade/Legal name", "POS", "Invoice Type", "Reverse Charge", "Invoice No",
            "Invoice Date", "Invoice Value", "Taxable Value", "Tax Rate", "IGST", "CGST", "SGST", "Total Tax", "Cess",
            "GSTR-1/5 Filling Period", "GSTR-1/5 Filling Date", "ITC Availibility", "E-Invoice Applicable", "Lookup",
            "Remark", "Activity", "ITC ELIGIBLITY"]


def _b(d, name, vno, gstin, no, narr, gross, taxable, igst, cgst, sgst, vtype="Journal", act="Raw Material",
       elig="Yes", pan=None):
    return [d, name, None, vtype, vno, "#N/A", None, gstin, None, None, pan, None, no, narr, gross, taxable, igst, cgst,
            sgst, igst + cgst + sgst, None, "#N/A", None, act, elig]


def _p(gstin, name, typ, no, d, taxable, igst, cgst, sgst, period="June,2026", act="#N/A", elig="#N/A"):
    v = taxable + igst + cgst + sgst
    return [period, gstin, name, "27-Maharashtra", typ, "No", no, d, v, taxable, 0, igst, cgst, sgst, igst + cgst + sgst,
            0, "June,2026", datetime(2026, 7, 11), "Yes", "Yes", "#N/A", None, act, elig]


def make_workbook(path: Path, client_gstin=CLIENT) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = "FORM GSTR-3B"
    ws["B6"], ws["C6"] = "GSTIN ", client_gstin
    jun = datetime(2026, 6, 20)
    books = [
        # 1 exact match; invoice date only in the narration
        _b(jun, "M/s Paintline Systems Pvt Ltd\t\t\n", 1949, S2, "26-27/PNQ/41",
           "Procurement of Material for Paint Shop, Invoice No & dtd - As per invoice no : 26-27/PNQ/41\t4-Jun-2026\n",
           900000, 1000000, 180000, 0, 0),
        # 2 GSTIN blank, name differs in form from 2B; invoice no. column filled
        _b(jun, "Kaveri Compressors India Limited\t\t\n", 2183, None, 55810432,
           "Procurement of Compressed Package, Tax Invoice No - as per invoice no 55810432\t02-Jun-26\n",
           700000, 500000, 0, 45000, 45000, act="Plant & Machinery"),
        # 3 invoice no. blank, in the narration with a glued 'dtd'
        _b(jun, "Kaveri Compressors India Limited", 2184, S1, None,
           "Supply of air dryer Invoice No - 55810477dtd - 05-jun-2026", 59000, 50000, 0, 4500, 4500),
        # 4 booked without GST (coffee) though the vendor charged 5%
        _b(jun, "Brewbean Trading", 2300, S3, "BT/26-27/817", "Coffee beans for pantry, invoice no BT/26-27/817, dtd 19 June 2026",
           17850, 17850, 0, 0, 0, act="Pantry", elig="No"),
        # 5 rent to an individual: no GSTIN, no GST
        _b(jun, "Asha Landlord", 2301, None, None, "Payment of monthly rent for June 2026 for Guest House", 63000, 63000,
           0, 0, 0, act="Rent"),
        # 6 advance against proforma
        _b(jun, "Toolcraft Moulds", 2302, S1, "PI/09", "25% Advance payment as per Proforma Invoice No. PI/09 dtd 03-Jun-2026",
           0, 0, 0, 0, 0),
        # 7 cab hire, firm marks ineligible; number only before a date
        _b(jun, "Swift Cabs Pvt Ltd", 2400, S4, None, "Car Hire Charges for A. Sharma - Pune Visit, SC2627-006617 06-Jun-2026",
           2205, 2100, 0, 52.5, 52.5, act="Car Hire Exp out", elig="NO"),
        # 8 older bill (April) booked in June: not in the June 2B
        _b(jun, "M/s Paintline Systems Pvt Ltd", 1950, S2, "26-27/PNQ/3",
           "Procurement of Material for Paint Shop, Invoice No: 26-27/PNQ/3 09-Apr-2026", 450000, 500000, 90000, 0, 0),
        # 9 credit note: voucher Debit Note, Invoice No column holds the ORIGINAL invoice
        _b(jun, "Holiday Tours & Travels", 2500, S5, "2025-26/731",
           "Credit note  no 2026-27/07, against invoice no 2025-26/731", 40020, -34500, 0, -3105, -3105,
           vtype="Debit Note", act="Travel"),
        # 10 correction entry for an earlier invoice
        _b(jun, "Paintline Systems", 2600, S2, None,
           "Excess booking now rectified against FRN 7731, for invoice no : 26-27/PNQ/1", 0, 270, -48, 0, 0),
        # 11 a keying error: 17.5%
        _b(jun, "Kaveri Compressors India Limited", 2185, S1, "55810519", "Spares, Invoice No - 55810519 dtd 06-Jun-2026",
           11750, 10000, 0, 875, 875),
    ]
    ws = wb.create_sheet("Purchase Jun-26")
    ws.append([])
    ws.append([])
    ws.append([None] * 16 + ["=SUBTOTAL(9,Q5:Q99)"])
    ws.append(BOOKS_HDR)
    for r in books:
        ws.append(r)
    twob = [
        _p(S2, "PAINTLINE SYSTEMS PRIVATE LIMITED", "Regular", "26-27/PNQ/41", datetime(2026, 6, 4), 1000000, 180000, 0, 0),
        _p(S1, "KAVERI COMPRESSORS INDIA LTD", "Regular", "55810432", datetime(2026, 6, 2), 500000, 0, 45000, 45000),
        _p(S1, "KAVERI COMPRESSORS INDIA LTD", "Regular", "55810477", datetime(2026, 6, 5), 50000, 0, 4500, 4500),
        _p(S1, "KAVERI COMPRESSORS INDIA LTD", "Regular", "55810519", datetime(2026, 6, 6), 10000, 0, 875, 875),
        _p(S3, "BREWBEAN TRADING", "Regular", "BT/26-27/817", datetime(2026, 6, 19), 17000, 0, 425, 425),
        _p(S4, "SWIFT CABS PRIVATE LIMITED", "Regular", "SC2627-006617", datetime(2026, 6, 6), 2100, 0, 52.5, 52.5),
        _p(S5, "HOLIDAY TOURS AND TRAVELS", "Credit", "2026-27/07", datetime(2026, 6, 10), -34500, 0, -3105, -3105),
        _p(S5, "HOLIDAY TOURS AND TRAVELS", "B2BA", "2026-27/77", datetime(2026, 6, 12), 1000, 0, 90, 90),
        _p(S5, "HOLIDAY TOURS AND TRAVELS", "Deemed Exports", "2026-27/78", datetime(2026, 6, 12), 1000, 0, 90, 90),
    ] + [_p(S6, "SKYWAYS AVIATION LIMITED", "Regular", f"SK{i:05d}", datetime(2026, 6, 1 + i % 28), 4000, 200, 0, 0,
            act="Airline") for i in range(30)]
    ws = wb.create_sheet("GSTR-2B Jun-26")
    ws.append([])
    ws.append([])
    ws.append([])
    ws.append([None] * 9 + ["=SUBTOTAL(9,J6:J99)"])
    ws.append(TWOB_HDR)
    for r in twob:
        ws.append(r)
    wb.save(path)
    return path


def run(tmp_path, **cfg):
    x = make_workbook(tmp_path / "XYZ_GSTR-3B_Jun-26.xlsx")
    books, n1 = load_file(x, Side.BOOKS)
    portal, n2 = load_file(x, Side.PORTAL)                  # no period given: read from the 'Period' column
    res = reconcile(books, portal, cfg=Config(client_gstin=CLIENT, **cfg), notes=n1 + n2)
    return res, books, portal


def _by_doc(res, no):
    return next(f for f in res.findings if any(d.doc_no == no for d in f.books + f.portal))


# ── narration parsing ───────────────────────────────────────────────────────
def test_narration_invoice_numbers():
    cases = {
        "Invoice No & dtd - As per invoice no : 26-27/PNQ/41\t4-Apr-2026": "26-27/PNQ/41",
        "conveyor Inv No PX4/26-27/052 dtd 18 May 2026": "PX4/26-27/052",
        "for the Period 01/06/2026 to 30/06/2026 Invoice no. KRL/013/26-27 dated 01/06/2026": "KRL/013/26-27",
        "as per invoices : PRC/2026-27/214 18-05-2026": "PRC/2026-27/214",
        "Tax Invoice No - As per INVOCIE NO :25-26/9133 16-Jan-26": "25-26/9133",
        "Bunch Invoice No - 3170452291dtd - 27-jan-2026": "3170452291",
        "invoice no - INV-26-310457 dated 25-05-2026": "INV-26-310457",
        "Car Hire Charges for X - Pune Visit, SC2627-008841 16-May-2026": "SC2627-008841",
        "25% Advance payment, as per Proforma Invoice No. 00001 dated 20th May": "",
        "Provision for exp reversed for FRN 2003": "",
    }
    for text, want in cases.items():
        assert N.invoice_no(text) == want, text


def test_narration_dates_prefer_dated_and_skip_service_period():
    b = date(2026, 6, 18)
    assert N.invoice_date("Lease for the Period 01/05/2026 to 31/05/2026 Invoice no. K/31 dated 02/06/2026", "K/31", b) \
        == date(2026, 6, 2)
    assert N.invoice_date("Invoice No - 16 dtd - 25/May/2026", "16", b) == date(2026, 5, 25)
    assert N.invoice_date("Invoice no 470385512908 date- 28May 2026", "", b) == date(2026, 5, 28)
    assert N.invoice_date("Invoice no : QPR2526/7710 03-09-2026", "", b) == date(2026, 3, 9)   # month typed first
    assert N.invoice_date("Invoice No: 26-27/PNQ/65 16-Apr-2206", "", b) is None             # year typo: ignored
    assert N.credit_note("Credit note  no 2026-27/07, against invoice no 2025-26/731") == ("2026-27/07", "2025-26/731")


# ── one workbook with both registers, Tally journal layout ─────────────────
def test_combined_workbook_loads_each_sheet_once(tmp_path):
    res, books, portal = run(tmp_path)
    assert {d.source.split(":")[1] for d in books} == {"Purchase Jun-26"}
    assert {d.source.split(":")[1] for d in portal} == {"GSTR-2B Jun-26"}
    assert len(books) == 11                                   # nothing silently dropped
    assert res.period == "062026"                             # from the 'Period' column ('June,2026')
    assert any("narration" in n for n in res.notes)


def test_invoice_date_from_narration_gives_exact_match(tmp_path):
    res, books, _ = run(tmp_path)
    b = next(d for d in books if d.doc_no == "26-27/PNQ/41")
    assert b.doc_date == date(2026, 6, 4) and b.voucher_date == date(2026, 6, 20)
    assert b.supplier_name == "Paintline Systems Pvt Ltd"
    assert _by_doc(res, "26-27/PNQ/41").status == Status.EXACT


def test_blank_gstin_filled_from_2b_and_matched(tmp_path):
    res, books, _ = run(tmp_path)
    f = _by_doc(res, "55810432")
    assert f.books and f.portal and f.books[0].supplier_gstin == S1
    assert any("GSTIN" in x and "blank" in x for x in f.flags)


def test_blank_invoice_no_read_from_narration(tmp_path):
    res, _, _ = run(tmp_path)
    f = _by_doc(res, "55810477")
    assert f.books and f.portal and f.status == Status.EXACT


def test_booked_without_gst(tmp_path):
    res, _, _ = run(tmp_path)
    f = _by_doc(res, "BT/26-27/817")
    assert f.status == Status.BOOKED_NO_GST and f.action == Action.ACCEPT and f.itc_to_claim == 0
    assert f.reverse_4b2 == 850


def test_no_gst_rows_are_excluded_not_chased(tmp_path):
    res, _, _ = run(tmp_path)
    nogst = [f for f in res.findings if f.status == Status.NO_ITC]
    assert len(nogst) == 2 and not any(f.needs_human for f in nogst)
    assert any("advance" in f.reason for f in nogst)


def test_credit_note_number_from_narration_matches_2b_credit(tmp_path):
    res, books, portal = run(tmp_path)
    cn = next(d for d in books if d.doc_type == DocType.CREDIT_NOTE and d.adjustment is False)
    assert cn.doc_no == "2026-27/07" and cn.ref_doc_no == "2025-26/731"
    f = _by_doc(res, "2026-27/07")
    assert f.books and f.portal and f.portal[0].doc_type == DocType.CREDIT_NOTE


def test_invoice_type_column(tmp_path):
    _, _, portal = run(tmp_path)
    by = {d.doc_no: d for d in portal}
    assert by["2026-27/77"].amends                            # B2BA = amendment
    assert by["2026-27/78"].doc_type == DocType.INVOICE       # 'Deemed Exports' is not a debit note


def test_correction_entry(tmp_path):
    res, _, _ = run(tmp_path)
    f = next(f for f in res.findings if f.status == Status.BOOKS_ADJUSTMENT)
    assert "26-27/PNQ/1" in f.reason and f.itc_in_books < 0


def test_older_bill_is_not_a_supplier_chase(tmp_path):
    res, _, _ = run(tmp_path)
    f = _by_doc(res, "26-27/PNQ/3")
    assert f.status == Status.BOOKS_OLDER and "earlier" in f.reason
    assert f.owner.value == "CA"


def test_rate_keying_error_flag(tmp_path):
    res, _, _ = run(tmp_path)
    f = _by_doc(res, "55810519")
    assert any("not a GST rate" in x for x in f.flags)


def test_firm_eligibility_mark_raises_blocked_flag(tmp_path):
    res, _, _ = run(tmp_path)
    f = _by_doc(res, "SC2627-006617")
    assert f.blocked                                         # car hire: rule + firm says NO


def test_partial_register_check(tmp_path):
    res, _, _ = run(tmp_path)
    assert any(c.name == "Purchase register looks incomplete" for c in res.checks)
    sup = next(r for r in res.suppliers if r["gstin"] == S6)
    assert sup["records_2b"] == 30 and "Never in these books" in sup["suggestion"]
    air = [f for f in res.findings if f.supplier_gstin == S6]
    assert all(f.action == Action.PENDING for f in air)      # not mass-rejected: booked in another register


def test_client_gstin_read_from_summary_sheet(tmp_path):
    from taxmind.loaders.tabular import detect_client_gstin
    assert detect_client_gstin(make_workbook(tmp_path / "w.xlsx")) == CLIENT


# ── tolerance, line of business, Table 4, reversal ledger ──────────────────
def _d(side, no, tax, taxable=100000.0, g=S1, period="062026", d=date(2026, 6, 5)):
    return Doc(side=side, uid=f"{side.value}{no}", supplier_gstin=g, doc_no=no, doc_date=d, taxable=taxable,
               cgst=tax / 2, sgst=tax / 2, period=period)


def test_percentage_tolerance():
    b = _d(Side.BOOKS, "A1", 18000)
    p = _d(Side.PORTAL, "A1", 18000 + 12)
    assert reconcile([b], [p], period="062026").findings[0].status == Status.VALUE_DIFF
    r = reconcile([_d(Side.BOOKS, "A1", 18000)], [_d(Side.PORTAL, "A1", 18012)], period="062026",
                  cfg=Config(amount_tolerance_pct=0.1))
    assert r.findings[0].status == Status.EXACT


def test_line_of_business_switches_off_blocks():
    def f():
        b = _d(Side.BOOKS, "R1", 1800)
        b.ledger = "Vehicle repairs"
        return Finding(fid="F1", status=Status.EXACT, books=[b], itc_to_claim=1800)
    plain, maker = f(), f()
    apply_blocked([plain])
    apply_blocked([maker], "vehicle_maker")
    assert plain.blocked and not maker.blocked
    hire = f()
    hire.books[0].ledger = "Car hire charges"
    apply_blocked([hire], "vehicle_maker")
    assert hire.blocked                                   # hire of cabs stays blocked for a maker


def test_table4_and_reversal_ledger_round_trip(tmp_path):
    # June: one matched bill, one 2B bill not in books (kept pending), one booked-without-GST
    b1, p1 = _d(Side.BOOKS, "M1", 1800), _d(Side.PORTAL, "M1", 1800)
    p2 = _d(Side.PORTAL, "X9", 900, taxable=5000)
    res = reconcile([b1], [p1, p2], period="062026")
    t = {ln.code: ln for ln in res.table4["lines"]}
    assert t["2B"].total == 2700 and t["IMS"].total == 900 and t["4(A)(5)"].total == 1800 and t["4(C)"].total == 1800
    # same month under the 'reverse' policy: X9 flows into 4(A) and is reversed in 4(B)(2)
    res2 = reconcile([_d(Side.BOOKS, "M1", 1800)], [_d(Side.PORTAL, "M1", 1800), _d(Side.PORTAL, "X9", 900, 5000)],
                     period="062026", cfg=Config(not_in_books_policy="reverse"))
    t2 = {ln.code: ln for ln in res2.table4["lines"]}
    assert t2["4(A)(5)"].total == 2700 and t2["4(B)(2)"].total == 900 and t2["4(C)"].total == 1800
    led = write_ledger(res2.table4["ledger"], tmp_path / "ledger.csv")
    items = load_ledger(led)
    assert [(i.doc_no, i.tax) for i in items] == [("X9", 900.0)]
    # July: X9 is booked now (no July 2B for it) -> reclaimed in 4(A)(5) and 4(D)(1)
    b_x9 = _d(Side.BOOKS, "X9", 900, 5000, period="072026", d=date(2026, 6, 5))
    jul = reconcile([b_x9], [_d(Side.PORTAL, "J1", 100, 1000, g=S2, period="072026", d=date(2026, 7, 2))],
                    period="072026", prior_ledger=items)
    t3 = {ln.code: ln for ln in jul.table4["lines"]}
    assert t3["4(D)(1)"].total == 900 and jul.table4["reclaimed"] == 1
    f = _by_doc(jul, "X9")
    assert f.itc_to_claim == 900 and "Reclaim" in f.reason
    assert not jul.table4["ledger"]                      # nothing left open
    assert t3["4(A)(5)"].total == 900                    # J1 kept pending (not in books) + reclaim 900


def test_close_pack_has_table4_and_ledger(tmp_path):
    import zipfile
    from taxmind.closepack import CloseInfo, build_close_pack
    res, _, _ = run(tmp_path)
    z = build_close_pack(res, tmp_path / "pack.zip", input_files=[tmp_path / "XYZ_GSTR-3B_Jun-26.xlsx"] * 2,
                         info=CloseInfo(preparer="A", reviewer="B"))
    names = zipfile.ZipFile(z).namelist()
    assert "gstr3b_table4.csv" in names and "itc_reversal_ledger.csv" in names
    assert sum(n.startswith("inputs/") for n in names) == 1   # same file given twice is stored once
