"""Run with:  python -m pytest -q"""
from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from taxmind import Config, Side, load_file, load_many, reconcile
from taxmind import gstin as G
from taxmind.benchmark import run as run_benchmark
from taxmind.matcher import score_pair
from taxmind.models import Action, Doc, DocType, Status
from taxmind.normalize import doc_relation, k2, k3
from taxmind.recommend import inr, sec16_deadline
from taxmind.report import write_excel, write_html
from taxmind.synth import generate, make_gstin

import random

RNG = random.Random(1)
A = make_gstin(RNG, "27")                     # supplier, Maharashtra
A_KA = make_gstin(RNG, "29", A[2:12])         # same PAN, Karnataka
CLIENT = make_gstin(RNG, "27")


def doc(side, no, d=date(2026, 9, 5), taxable=100000.0, igst=0.0, cgst=9000.0, sgst=9000.0, g=A,
        typ=DocType.INVOICE, period="092026", uid=None):
    return Doc(side=side, uid=uid or f"{side.value}-{no}-{g}", supplier_gstin=g, doc_no=no, doc_date=d,
               taxable=taxable, igst=igst, cgst=cgst, sgst=sgst, doc_type=typ, period=period)


# ── GSTIN ────────────────────────────────────────────────────────────────────
def test_gstin_check_digit_round_trip_and_tamper():
    assert G.is_valid(A) and G.is_valid(A_KA)
    bad = A[:-1] + ("0" if A[-1] != "0" else "1")
    assert not G.is_valid(bad)
    assert not G.is_valid("27ABCDE1234F1Z")        # too short
    assert G.pan(A) == G.pan(A_KA)


# ── invoice numbers ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("a,b,rel", [
    ("INV/26-27/0045", "inv-26-27-0045", 1),
    ("INV/26-27/0045", "INV/0045", 2),
    ("GST/2026-27/045", "45", 3),
    ("VPT/159/26-27", "VPT/157/26-27", 4),     # one digit apart -> typo candidate
    ("SA-1203", "SA-1230", 4),                 # transposition
    ("INV/045", "PUR/912", 0),
    ("BILL/45-46", "45", 0),                   # 45-46 is not a financial year
])
def test_doc_relation(a, b, rel):
    assert doc_relation(a, b) == rel


def test_fy_stripping_keeps_serial():
    assert k3("VPT/159/26-27") == "159"        # regression: used to return '27'
    assert k2("FY2026-27/12") == "12"
    assert k2("INV202627-77") == "INV77"
    assert k3("O45") == "45"                   # letter O typed for zero


# ── pair scoring ─────────────────────────────────────────────────────────────
def test_pair_statuses():
    cfg = Config()
    B, P = Side.BOOKS, Side.PORTAL
    assert score_pair(doc(B, "INV/45"), doc(P, "INV/45"), cfg).status == Status.EXACT
    assert score_pair(doc(B, "45"), doc(P, "INV/26-27/0045"), cfg).status == Status.FORMAT_DIFF
    assert score_pair(doc(B, "INV/45", d=date(2026, 9, 8)), doc(P, "INV/45"), cfg).status == Status.DATE_DIFF
    assert score_pair(doc(B, "INV/1230"), doc(P, "INV/1203"), cfg).status == Status.TYPO
    assert score_pair(doc(B, "INV/45", taxable=90000, cgst=8100, sgst=8100), doc(P, "INV/45"),
                      cfg).status == Status.VALUE_DIFF
    assert score_pair(doc(B, "INV/45"), doc(P, "INV/45", igst=18000, cgst=0, sgst=0),
                      cfg).status == Status.HEAD_MISMATCH
    assert score_pair(doc(B, "INV/45"), doc(P, "INV/45", g=A_KA), cfg).status == Status.OTHER_GSTIN
    # next invoice of the same supplier with a different amount is NOT a pair
    assert score_pair(doc(B, "INV/276", taxable=5000, cgst=450, sgst=450), doc(P, "INV/266"), cfg) is None
    # credit note never pairs with an invoice
    assert score_pair(doc(B, "45", typ=DocType.CREDIT_NOTE), doc(P, "45"), cfg) is None


# ── end-to-end decisions ─────────────────────────────────────────────────────
def test_reconcile_core_decisions():
    B, P = Side.BOOKS, Side.PORTAL
    stranger = make_gstin(RNG, "07")
    books = [doc(B, "INV/1"), doc(B, "INV/2"), doc(B, "INV/3"),
             doc(B, "INV/9", taxable=50000, cgst=4500, sgst=4500),                       # split below
             doc(B, "INV/1", uid="dup")]                                                  # duplicate
    portal = [doc(P, "INV/1"), doc(P, "INV/2", period="102026"),                          # late filer
              doc(P, "INV/7", taxable=20000, cgst=1800, sgst=1800),
              doc(P, "INV/8", taxable=30000, cgst=2700, sgst=2700, d=date(2026, 9, 6)),   # 7+8 = books INV/9
              doc(P, "X-77", g=stranger)]                                                 # unknown supplier
    res = reconcile(books, portal, period="092026", client="Test")
    by = {f.status: f for f in res.findings}
    assert by[Status.EXACT].action == Action.ACCEPT
    assert by[Status.LATE_FILED].itc_to_claim == 0
    assert by[Status.SPLIT].action == Action.ACCEPT and len(by[Status.SPLIT].portal) == 2
    assert by[Status.BOOKS_DUPLICATE].action == Action.NONE
    assert by[Status.BOOKS_ONLY].books[0].doc_no == "INV/3"
    assert by[Status.PORTAL_ONLY_UNKNOWN].action == Action.REJECT
    assert any(c.name == "Unknown suppliers in 2B" and c.level == "High" for c in res.checks)
    assert res.summary["itc_to_claim"] == pytest.approx(18000 + 3600 + 5400)


def test_drc01c_trigger_needs_both_limits():
    B, P = Side.BOOKS, Side.PORTAL
    books = [doc(B, f"INV/{i}", taxable=1_000_000, cgst=90_000, sgst=90_000) for i in range(10)]
    portal = [doc(P, f"INV/{i}", taxable=1_000_000, cgst=90_000, sgst=90_000) for i in range(7)]
    res = reconcile(books, portal, period="092026")           # excess ₹5.4L (43%) -> below ₹25L
    c = next(c for c in res.checks if c.name.startswith("3B claim"))
    assert c.level == "Review"
    res = reconcile(books, portal, period="092026", planned_itc=1_260_000 + 3_000_000)
    c = next(c for c in res.checks if c.name.startswith("3B claim"))
    assert c.level == "High"


def test_helpers():
    assert inr(118000) == "₹1,18,000"
    assert inr(4732204.4) == "₹47,32,204"
    assert sec16_deadline(date(2026, 9, 5)) == date(2027, 11, 30)
    assert sec16_deadline(date(2026, 2, 5)) == date(2026, 11, 30)


# ── loaders ──────────────────────────────────────────────────────────────────
def test_excel_register_sums_rate_wise_tax_columns(tmp_path: Path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Purchase Register"])
    ws.append(["Date", "Particulars", "Supplier Invoice No.", "GSTIN/UIN", "Taxable Value",
               "Input CGST 9%", "Input CGST 2.5%", "Input SGST 9%", "Input SGST 2.5%", "IGST Rate"])
    ws.append([date(2026, 9, 5), "Supplier A", 45, A, 1000, 90, 0, 90, 0, 18])
    f = tmp_path / "reg.xlsx"
    wb.save(f)
    docs, _ = load_file(f, Side.BOOKS)
    assert len(docs) == 1
    d = docs[0]
    assert d.doc_no == "45" and d.cgst == 90 and d.sgst == 90 and d.igst == 0   # 'IGST Rate' ignored


def test_tally_utf16_with_control_chars(tmp_path: Path):
    xml = ("<ENVELOPE><BODY><DATA><TALLYMESSAGE><VOUCHER VCHTYPE=\"Purchase\">"
           "<DATE>20260906</DATE><VOUCHERTYPENAME>Purchase</VOUCHERTYPENAME><VOUCHERNUMBER>12</VOUCHERNUMBER>"
           "<REFERENCE>INV/45</REFERENCE><REFERENCEDATE>20260905</REFERENCEDATE>"
           f"<PARTYLEDGERNAME>Supplier &#4; A</PARTYLEDGERNAME><PARTYGSTIN>{A}</PARTYGSTIN>"
           "<ALLLEDGERENTRIES.LIST><LEDGERNAME>Purchase 18%</LEDGERNAME><AMOUNT>-1000.00</AMOUNT></ALLLEDGERENTRIES.LIST>"
           "<ALLLEDGERENTRIES.LIST><LEDGERNAME>Input IGST</LEDGERNAME><AMOUNT>-180.00</AMOUNT></ALLLEDGERENTRIES.LIST>"
           "</VOUCHER></TALLYMESSAGE></DATA></BODY></ENVELOPE>")
    f = tmp_path / "daybook.xml"
    f.write_bytes(xml.encode("utf-16"))
    docs, _ = load_file(f, Side.BOOKS)
    assert len(docs) == 1
    d = docs[0]
    assert d.doc_no == "INV/45" and d.doc_date == date(2026, 9, 5)       # supplier's no., not voucher 12
    assert d.taxable == 1000 and d.igst == 180


# ── whole-system benchmark on generated data ────────────────────────────────
@pytest.mark.parametrize("hard,seed", [(False, 3), (True, 5)])
def test_benchmark_all_formats(tmp_path: Path, hard, seed):
    generate(tmp_path, seed=seed, hard=hard)
    combos = [(tmp_path / "purchase_register_092026.xlsx", sorted(tmp_path.glob("gstr2b_*.json"))),
              (tmp_path / "tally_daybook_092026.xml", [tmp_path / "gstr2b_092026.xlsx",
                                                       tmp_path / "gstr2b_102026.json"])]
    results = []
    for books, portal in combos:
        r = run_benchmark(tmp_path, books, portal)
        acc = r["accuracy"]
        assert acc["wrong_accepts"] == 0
        assert acc["accuracy"] >= 0.99, acc["failures"][:5]
        results.append(r["summary"]["itc_to_claim"])
    assert results[0] == pytest.approx(results[1])         # every format gives the same answer


def test_reports(tmp_path: Path):
    generate(tmp_path, seed=2)
    books, _ = load_many([tmp_path / "purchase_register_092026.xlsx"], Side.BOOKS)
    portal, _ = load_many(sorted(tmp_path.glob("gstr2b_*.json")), Side.PORTAL)
    res = reconcile(books, portal, client="Test client")
    x = write_excel(res, tmp_path / "out.xlsx")
    h = write_html(res, tmp_path / "out.html")
    wb = load_workbook(x)
    assert wb.sheetnames == ["Summary", "IMS decisions", "Books not in 2B", "Supplier follow-ups",
                             "Client questions", "All findings"]
    assert "Pre-filing report" in h.read_text()
    assert res.supplier_messages and "GSTR-1" in res.supplier_messages[0].whatsapp
