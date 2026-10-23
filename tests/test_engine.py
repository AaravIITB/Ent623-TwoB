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
                             "Client questions", "Blocked credit review", "All findings"]
    assert "Pre-filing report" in h.read_text()
    assert res.supplier_messages and "GSTR-1" in res.supplier_messages[0].whatsapp


# ── regressions from the independent review ─────────────────────────────────
def test_year_suffix_invoices_are_not_paired():
    B, P = Side.BOOKS, Side.PORTAL
    res = reconcile([doc(B, "INV/045/2026")], [doc(P, "INV/051/2026", taxable=80000, cgst=7200, sgst=7200)],
                    period="092026")
    assert {f.status for f in res.findings} == {Status.BOOKS_ONLY, Status.PORTAL_ONLY_KNOWN}


def test_recurring_amounts_do_not_create_matches():
    B, P = Side.BOOKS, Side.PORTAL
    books = [doc(B, f"FUEL/{i}", d=date(2026, 9, 2 + i)) for i in (1, 2, 3, 4)]
    portal = [doc(P, f"FUEL/{i}", d=date(2026, 9, 2 + i)) for i in (1, 2, 3)] + \
             [doc(P, "FUEL/1004", d=date(2026, 9, 6))]          # one digit added, same recurring amount
    res = reconcile(books, portal, period="092026")
    odd = [f for f in res.findings if any(d.doc_no in ("FUEL/4", "FUEL/1004") for d in f.books + f.portal)]
    assert all(f.action != Action.ACCEPT for f in odd)


def test_period_formats_and_bad_period():
    from taxmind.engine import clean_period
    for p in ("092026", "09/2026", "2026-09", "202609", "Sep 2026", "Sep-26"):
        assert clean_period(p) == "092026"
    with pytest.raises(ValueError):
        clean_period("132026")


def test_amendment_counts_only_the_difference(tmp_path: Path):
    import json
    aug = {"data": {"rtnprd": "082026", "docdata": {"b2b": [{"ctin": A, "inv": [
        {"inum": "INV-5", "dt": "20-08-2026", "txval": 10000, "cgst": 900, "sgst": 900, "itcavl": "Y"}]}]}}}
    sep = {"data": {"rtnprd": "092026", "docdata": {"b2ba": [{"ctin": A, "inv": [
        {"oinum": "INV-5", "inum": "INV-5", "dt": "20-08-2026", "txval": 15000, "cgst": 1350, "sgst": 1350,
         "itcavl": "Y"}]}]}}}
    (tmp_path / "aug.json").write_text(json.dumps(aug))
    (tmp_path / "sep.json").write_text(json.dumps(sep))
    portal, _ = load_many([tmp_path / "aug.json", tmp_path / "sep.json"], Side.PORTAL)
    res = reconcile([], portal, period="092026")
    assert res.summary["itc_2b"] == pytest.approx(900)            # 2,700 - 1,800


def test_ims_credit_note_section(tmp_path: Path):
    import json
    ims = {"b2b": [{"stin": A, "inum": "INV-1", "dt": "05-09-2026", "txval": 10000, "cgst": 900, "sgst": 900}],
           "b2bcn": [{"stin": A, "inum": "CN-7", "dt": "06-09-2026", "txval": 5000, "cgst": 450, "sgst": 450}]}
    f = tmp_path / "ims.json"
    f.write_text(json.dumps(ims))
    docs, _ = load_file(f, Side.PORTAL, period="092026")
    assert {d.doc_no: d.doc_type for d in docs} == {"INV-1": DocType.INVOICE, "CN-7": DocType.CREDIT_NOTE}


def test_ledger_names_and_negative_rows(tmp_path: Path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Date", "Supplier Invoice No.", "GSTIN/UIN", "Taxable Value", "Purchase IGST 18%",
               "Processing Charges", "Input IGST"])
    ws.append([date(2026, 9, 5), "A1", A, 10000, 10000, 500, 1800])
    ws.append([date(2026, 9, 6), "R1", A, -5000, -5000, 0, -900])          # a return entered as minus
    f = tmp_path / "reg.xlsx"
    wb.save(f)
    docs, _ = load_file(f, Side.BOOKS)
    a1, r1 = docs
    assert a1.igst == 1800 and a1.cess == 0 and a1.doc_type == DocType.INVOICE
    assert r1.doc_type == DocType.CREDIT_NOTE and r1.igst == 900


def test_tally_party_by_mailing_name(tmp_path: Path):
    xml = ("<ENVELOPE><VOUCHER VCHTYPE=\"Purchase\"><DATE>20260905</DATE><VOUCHERTYPENAME>Purchase</VOUCHERTYPENAME>"
           f"<REFERENCE>A3</REFERENCE><PARTYNAME>ABC Limited, Pune</PARTYNAME><PARTYGSTIN>{A}</PARTYGSTIN>"
           "<ALLLEDGERENTRIES.LIST><LEDGERNAME>ABC Ltd</LEDGERNAME><AMOUNT>11800</AMOUNT></ALLLEDGERENTRIES.LIST>"
           "<ALLLEDGERENTRIES.LIST><LEDGERNAME>Purchases @18%</LEDGERNAME><AMOUNT>-10000</AMOUNT></ALLLEDGERENTRIES.LIST>"
           "<ALLLEDGERENTRIES.LIST><LEDGERNAME>Input CGST</LEDGERNAME><AMOUNT>-900</AMOUNT></ALLLEDGERENTRIES.LIST>"
           "<ALLLEDGERENTRIES.LIST><LEDGERNAME>Input SGST</LEDGERNAME><AMOUNT>-900</AMOUNT></ALLLEDGERENTRIES.LIST>"
           "</VOUCHER></ENVELOPE>")
    f = tmp_path / "t.xml"
    f.write_text(xml)
    (d,), _ = load_file(f, Side.BOOKS)
    assert d.taxable == 10000 and d.tax == 1800


def test_same_number_in_two_years_is_not_a_duplicate():
    B = Side.BOOKS
    res = reconcile([doc(B, "RENT/25-26/001", d=date(2025, 9, 1)), doc(B, "RENT/26-27/001", d=date(2026, 9, 1))],
                    [], period="092026")
    assert all(f.status != Status.BOOKS_DUPLICATE for f in res.findings)


def test_books_credit_note_wording():
    B = Side.BOOKS
    res = reconcile([doc(B, "DN-3", typ=DocType.CREDIT_NOTE)], [], period="092026")
    f = res.findings[0]
    assert "Credit note" in f.reason and not f.flags


# ── Sec 17(5) blocked-credit flags ──────────────────────────────────────────
from taxmind.blocked import classify  # noqa: E402


def _rids(**kw):
    d = Doc(Side.BOOKS, "u", A, "1", date(2026, 9, 5), **kw)
    return {f.rid: f.confidence for f in classify([d])}


@pytest.mark.parametrize("kw,want", [
    (dict(ledger="Staff Welfare - Food"), {"food": "Likely"}),
    (dict(ledger="Travelling Expenses", supplier_name="Hotel Sagar Residency"), {"hotel_mixed": "Review"}),
    (dict(ledger="Lodging - Business Travel", supplier_name="Hotel Sagar Residency"), {}),
    (dict(hsn="996311"), {}),                                  # room only
    (dict(hsn="996331"), {"food": "Likely"}),
    (dict(ledger="Car Repairs & Maintenance"), {"motor_vehicle": "Likely"}),
    (dict(ledger="Goods Vehicle Hire", hsn="996601"), {}),     # SAC 9966 also covers trucks
    (dict(ledger="Car Spare Parts Purchase"), {}),             # auto-component maker's raw material
    (dict(hsn="87032291"), {"motor_vehicle": "Likely"}),
    (dict(ledger="Fire Insurance - Factory"), {}),
    (dict(ledger="Group Health Insurance"), {"insurance": "Likely"}),
    (dict(ledger="Medical Equipment Purchase"), {}),
    (dict(ledger="PPE Kits / Personal Protective Equipment"), {}),
    (dict(ledger="Diwali Gifts to Customers"), {"gifts": "Likely"}),
    (dict(ledger="CSR Expenses"), {"csr": "Likely"}),
    (dict(ledger="Office Expenses", supplier_name="Kaveri Caterers"), {"food": "Possible"}),
    (dict(ledger="Purchase @18%", supplier_name="Kaveri Caterers"), {}),        # trading purchase: for supply
    (dict(ledger="Hotel Exp", description="Room tariff (room only, no F&B)", hsn="996311"), {}),
    (dict(ledger="Canteen Exp", description="Statutory canteen u/s 46 Factories Act", hsn="996334"), {}),
    (dict(ledger="Lodging & Boarding", supplier_name="Ginger Hotels"), {"hotel_mixed": "Review"}),
    (dict(ledger="Purchase - Vehicles", description="Baleno - stock-in-trade", hsn="8703"), {}),
    (dict(ledger="Motor Car", description="Swift - dual control, driving school", hsn="8703"), {}),
    (dict(ledger="Repair & Maint - Bldg", description="Roof leakage repair", hsn="995419"), {}),
    (dict(ledger="Conveyance"), {"motor_vehicle": "Possible"}),
    (dict(ledger="Stock Written Off", description="Expired goods destroyed"), {"lost_destroyed": "Likely"}),
    (dict(ledger="Helicopter Charter", hsn="996603"), {"vessel_aircraft": "Likely"}),
    (dict(ledger="Staff Bus Hire", description="32 seater", hsn="996601"), {}),
    (dict(ledger="Lodging", description="Room with breakfast", supplier_name="Hotel Kohinoor"),
     {"hotel_mixed": "Review"}),
    (dict(ledger="Creche charges", hsn="999351"), {}),           # social care, not a health service
    (dict(ledger="Cartage Inward"), {}),
])
def test_blocked_rules(kw, want):
    assert _rids(**kw) == want


def test_blocked_flags_reach_findings_and_report(tmp_path: Path):
    B, P = Side.BOOKS, Side.PORTAL
    b = doc(B, "H-1")
    b.ledger = "Hotel - Food & Beverages"
    res = reconcile([b], [doc(P, "H-1")], period="092026")
    f = res.findings[0]
    assert f.action == Action.ACCEPT                         # matched: IMS action unchanged
    assert [x.rid for x in f.blocked] == ["food"] and f.itc_to_claim == 18000   # never reversed automatically
    assert res.summary["blocked_review"] == 1 and res.summary["blocked_review_itc"] == 18000
    chk = next(c for c in res.checks if "Sec 17(5)" in c.name)
    assert chk.level == "High"
    ws = load_workbook(write_excel(res, tmp_path / "o.xlsx"))["Blocked credit review"]
    assert ws.cell(2, 1).value == "Likely" and ws.cell(2, 6).value == "H-1"


def test_blocked_credit_from_tally_and_columnar_register(tmp_path: Path):
    generate(tmp_path, seed=3, hard=True)            # hard = Tally-style columnar register
    for books in ("purchase_register_092026.xlsx", "tally_daybook_092026.xml"):
        r = run_benchmark(tmp_path, books_file=tmp_path / books)["accuracy"]["blocked_credit"]
        assert r["should_flag"] > 10 and r["recall"] == 1.0 and r["false_flags"] == 0


# ── month-close pack ────────────────────────────────────────────────────────
import json  # noqa: E402
import zipfile  # noqa: E402

from taxmind.closepack import CloseInfo, build_close_pack, load_overrides, pack_fingerprint, verify_pack  # noqa: E402


def test_close_pack_overrides_hashes_and_tamper(tmp_path: Path):
    generate(tmp_path, seed=2)
    bf, pf = tmp_path / "purchase_register_092026.xlsx", sorted(tmp_path.glob("gstr2b_*.json"))
    books, _ = load_many([bf], Side.BOOKS)
    portal, _ = load_many(pf, Side.PORTAL)
    res = reconcile(books, portal, client="Test client")
    # the CA edits the workbook: one held-back record accepted, one accept rejected
    x = write_excel(res, tmp_path / "out.xlsx")
    wb = load_workbook(x)
    ws = wb["All findings"]
    assert [c.value for c in ws[1]][2:5] == ["Recommended", "Final decision", "CA note"]
    by_id = {f.fid: f for f in res.findings}
    pend = next(r for r in range(2, ws.max_row + 1) if ws.cell(r, 3).value == "Pending"
                and by_id[ws.cell(r, 1).value].portal and by_id[ws.cell(r, 1).value].status != Status.LATE_FILED)
    acc = next(r for r in range(2, ws.max_row + 1) if ws.cell(r, 3).value == "Accept"
               and by_id[ws.cell(r, 1).value].itc_to_claim > 0)
    ws.cell(pend, 4).value, ws.cell(pend, 5).value = "accept", "Bill seen"
    ws.cell(acc, 4).value, ws.cell(acc, 5).value = "Reject", "Goods returned"
    wb.save(tmp_path / "edited.xlsx")
    ov = load_overrides(tmp_path / "edited.xlsx")
    assert len(ov) == 2 and ov[ws.cell(pend, 1).value] == ("Accept", "Bill seen")

    z = build_close_pack(res, tmp_path / "pack.zip", input_files=[bf, *pf],
                         info=CloseInfo(preparer="Riya", reviewer="CA Mehta", overrides=ov))
    fp = pack_fingerprint(z)
    assert verify_pack(z, fp) == (True, [])
    with zipfile.ZipFile(z) as zz:
        names = set(zz.namelist())
        assert {"manifest.json", "record.html", "decisions.csv", "decisions.json", "reconciliation.xlsx",
                f"inputs/{bf.name}"} <= names
        d = json.loads(zz.read("decisions.json"))
        m = json.loads(zz.read("manifest.json"))
        html = zz.read("record.html").decode()
    fp_ = by_id[ws.cell(pend, 1).value]
    fa = by_id[ws.cell(acc, 1).value]
    assert d["itc_after_ca_decisions"] == pytest.approx(res.summary["itc_to_claim"] + fp_.itc_in_2b - fa.itc_to_claim)
    assert m["changed_by_ca"] == 2 and m["prepared_by"] == "Riya" and m["data_fingerprint"] in html
    assert "Goods returned" in html

    # change one input inside the pack -> caught
    t = tmp_path / "tampered.zip"
    with zipfile.ZipFile(z) as src, zipfile.ZipFile(t, "w") as dst:
        for n in src.namelist():
            data = src.read(n)
            dst.writestr(n, data.replace(b'"inum"', b'"inum" ') if n.endswith(".json") and "inputs/" in n else data)
    ok, problems = verify_pack(t, fp)
    assert not ok and any("inputs/" in p for p in problems)


def test_bad_override_value_is_rejected(tmp_path: Path):
    f = tmp_path / "d.csv"
    f.write_text("ID,Final decision,CA note\nF0001,Maybe,\n")
    with pytest.raises(ValueError, match="not one of"):
        load_overrides(f)
