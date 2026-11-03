"""Regressions for the issues found by the second independent review (real-file features, Table 4)."""
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook

from taxmind import Config, Side, load_file, reconcile
from taxmind import narration as N
from taxmind.gstr3b import LedgerItem
from taxmind.models import Action, Doc, DocType, Status
from taxmind.prepare import resolve_missing_gstins

from test_real_patterns import BOOKS_HDR, S1, S2, S4, TWOB_HDR, _b, _p

G = "27AAACA1234A1Z5"


def D(side, no, cg, period="062026", dt=date(2026, 6, 10), typ=DocType.INVOICE, g=G, **kw):
    return Doc(side=side, uid=f"{side.value}{no}{period}{kw.get('amends', '')}", supplier_gstin=g, doc_no=no,
               doc_date=dt, taxable=round(cg * 2 / 0.18, 2), cgst=cg, sgst=cg, period=period, doc_type=typ,
               supplier_name="ACME", **kw)


def t4(res):
    return {ln.code: ln for ln in res.table4["lines"]}


def _wb(path, books, twob, sheets=True):
    wb = Workbook()
    ws = wb.active
    ws.title = "Purchase Jun-26"
    ws.append(BOOKS_HDR)
    for r in books:
        ws.append(r)
    if twob is not None:
        ws = wb.create_sheet("GSTR-2B Jun-26")
        ws.append(TWOB_HDR)
        for r in twob:
            ws.append(r)
    wb.save(path)
    return path


def test_handmade_sheet_date_is_the_invoice_date(tmp_path):
    # Voucher No + Narration columns, but the narration carries no date: 'Date' is the invoice date
    books = [_b(datetime(2026, 6, 1 + i), "Acme", 10 + i, S1, f"AC/10{i}", "Purchase of spares", 11800, 10000, 0,
                900, 900) for i in range(5)]
    twob = [_p(S1, "ACME", "Regular", f"AC/10{i}", datetime(2026, 6, 1 + i), 10000, 0, 900, 900) for i in range(5)]
    x = _wb(tmp_path / "hm.xlsx", books, twob)
    res = reconcile(load_file(x, Side.BOOKS)[0], load_file(x, Side.PORTAL, period="062026")[0], period="062026")
    assert [f.status for f in res.findings] == [Status.EXACT] * 5


def test_single_sheet_books_with_2b_like_headers_is_read(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Invoice No", "Invoice Date", "GSTIN of supplier", "Taxable Value", "CGST", "SGST", "ITC Availability"])
    ws.append(["A1", "05-06-2026", S1, 10000, 900, 900, "Yes"])
    wb.save(tmp_path / "pr.xlsx")
    books, notes = load_file(tmp_path / "pr.xlsx", Side.BOOKS)
    assert len(books) == 1 and any("read anyway" in n for n in notes)


def test_reclaim_not_counted_twice_when_bill_is_in_this_2b():
    led = [LedgerItem(G, "B200", "2026-05-28", "052026", 0, 900, 900, 0, "not in books")]
    res = reconcile([D(Side.BOOKS, "B200", 900)], [D(Side.PORTAL, "B200", 900)], period="062026", prior_ledger=led)
    t = t4(res)
    assert t["4(A)(5)"].total == 1800 and t["4(D)(1)"].total == 0 and res.summary["itc_to_claim"] == 1800
    assert res.table4["carried"] == 1                       # the ledger item stays open, with a flag


def test_reclaim_uses_the_ledger_heads():
    led = [LedgerItem(G, "B300", "2026-05-28", "052026", 1800, 0, 0, 0, "not in books")]
    res = reconcile([D(Side.BOOKS, "B300", 900, dt=date(2026, 5, 28))], [], period="062026", prior_ledger=led)
    assert t4(res)["4(D)(1)"].amounts["igst"] == 1800


def test_downward_amendment_in_table4():
    books = [D(Side.BOOKS, "A100", 500)]
    portal = [D(Side.PORTAL, "A100", 900, period="052026", dt=date(2026, 5, 10)),
              D(Side.PORTAL, "A100", 500, dt=date(2026, 5, 10), amends="A100")]
    res = reconcile(books, portal, period="062026")
    t = t4(res)
    assert t["4(C)"].total == -800 and not res.table4["ledger"]


def test_blocked_bill_booked_without_gst_goes_to_4b1_not_ledger():
    b = D(Side.BOOKS, "F1", 0)
    b.taxable, b.no_itc_reason, b.ledger = 17000, "no GST charged", "Staff Welfare - Food"
    p = D(Side.PORTAL, "F1", 425)
    p.taxable = 17000
    res = reconcile([b], [p], period="062026")
    t = t4(res)
    assert t["4(B)(1)"].total == 850 and t["4(B)(2)"].total == 0 and not res.table4["ledger"]


def test_reverse_charge_goes_to_4a3():
    p = Doc(Side.PORTAL, "p1", G, "GTA/1", date(2026, 6, 5), taxable=100000, igst=5000, reverse_charge=True,
            period="062026")
    b = Doc(Side.BOOKS, "b1", G, "GTA/1", date(2026, 6, 5), taxable=100000, period="062026",
            no_itc_reason="no GST charged")
    res = reconcile([b], [p], period="062026")
    t = t4(res)
    assert t["4(A)(3)"].total == 5000 and t["4(A)(5)"].total == 0 and not res.table4["ledger"]
    assert res.findings[0].status == Status.RCM and "IMS" in res.findings[0].reason


def test_reverse_policy_ims_action_matches_table4():
    res = reconcile([D(Side.BOOKS, "A1", 900)], [D(Side.PORTAL, "A1", 900), D(Side.PORTAL, "A2", 900)],
                    period="062026", cfg=Config(not_in_books_policy="reverse"))
    f = next(f for f in res.findings if not f.books)
    assert f.action == Action.NONE                            # left for deemed acceptance, reversed in 4(B)(2)
    assert t4(res)["4(B)(2)"].total == 1800 and len(res.table4["ledger"]) == 1


def test_gstin_not_filled_from_a_different_supplier():
    def bk(name, no, tax):
        return Doc(Side.BOOKS, name, "", no, date(2026, 6, 5), taxable=10000, cgst=tax / 2, sgst=tax / 2,
                   supplier_name=name)
    portal = [Doc(Side.PORTAL, "p1", S1, "4512", date(2026, 6, 5), taxable=6000, cgst=540, sgst=540,
                  supplier_name="OM TRANSPORT"),
              Doc(Side.PORTAL, "p2", S2, "X1", date(2026, 6, 5), taxable=1, cgst=1, sgst=1,
                  supplier_name="Shiv Shakti Enterprises"),
              Doc(Side.PORTAL, "p3", S4, "X2", date(2026, 6, 5), taxable=1, cgst=1, sgst=1,
                  supplier_name="Kumar Electronics")]
    books = [bk("Om Traders", "4512", 1800), bk("Shiv Shakti Services", "Q9", 1800), bk("Kumar Electricals", "Q8", 18)]
    resolve_missing_gstins(books, portal)
    assert [b.supplier_gstin for b in books] == ["", "", ""]
    tn = bk("Uno Minda Limited - TN", "Q7", 18)
    resolve_missing_gstins([tn], [Doc(Side.PORTAL, "p4", S1, "Z", None, supplier_name="UNO MINDA LIMITED")])
    assert tn.supplier_gstin == S1                           # a branch tag is not a different supplier


def test_narration_ignores_non_invoice_numbers():
    for t in ["Freight for truck MH12AB1234 06-Jun-2026", "PO4500012345 dated 05-06-2026",
              "GRN2026001 10-06-2026", "E-way bill no 351234567890 dtd 2-6-2026",
              "as per Quotation Q-2026-45 dtd 1-6-26", "supply in June2026 01-06-2026"]:
        assert N.invoice_no(t) == "", t
    assert N.invoice_no("Sub-contract - RA bill 26, Tax Inv No. 26-27/MUM/114 dtd 2-Jun-26") == "26-27/MUM/114"
    assert N.invoice_no("Tempo hire, as per invoice no : 91\t05/06/2026") == "91"


def test_invoice_mentioning_a_credit_note_stays_an_invoice(tmp_path):
    books = [_b(datetime(2026, 6, 20), "Alpha Metals", 1, S1, "AM/789",
                "inv no AM/789 dtd 05-06-2026 after adjusting credit note no CN/12 against invoice no AM/456",
                200000, 100000, 18000, 0, 0)]
    x = _wb(tmp_path / "c.xlsx", books, None)
    b = load_file(x, Side.BOOKS)[0][0]
    assert b.doc_type == DocType.INVOICE and b.doc_no == "AM/789"


def test_rectification_work_is_a_bill(tmp_path):
    books = [_b(datetime(2026, 6, 20), "Power Gen", 1, S1, "RW/2026/45",
                "Being rectification work of DG set, inv no RW/2026/45 dtd 03-06-2026", 11800, 10000, 0, 900, 900)]
    twob = [_p(S1, "POWER GEN", "Regular", "RW/2026/45", datetime(2026, 6, 3), 10000, 0, 900, 900)]
    x = _wb(tmp_path / "r.xlsx", books, twob)
    res = reconcile(load_file(x, Side.BOOKS)[0], load_file(x, Side.PORTAL, period="062026")[0], period="062026")
    assert res.findings[0].status == Status.EXACT


def test_tax_head_transfer_journal_nets_to_zero(tmp_path):
    books = [_b(datetime(2026, 6, 20), "Alpha Metals", 1, S1, "AM/789", "Being IGST reclassified to CGST and SGST",
                0, 0, -1800, 900, 900)]
    x = _wb(tmp_path / "m.xlsx", books, None)
    b = load_file(x, Side.BOOKS)[0][0]
    assert b.tax == 0 and b.no_itc_reason


def test_books_credit_note_not_in_2b_lowers_the_claim():
    res = reconcile([D(Side.BOOKS, "CN9", 100, typ=DocType.CREDIT_NOTE)], [D(Side.PORTAL, "Z1", 900, g=S2)],
                    period="062026")
    f = next(f for f in res.findings if f.books)
    assert f.itc_to_claim == -200 and t4(res)["4(B)(2)"].total == 200
