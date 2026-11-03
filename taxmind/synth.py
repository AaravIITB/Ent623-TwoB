"""Generate a realistic synthetic month of purchase data with known answers.

Writes, for a fictional client:
  gstr2b_092026.json / gstr2b_102026.json   portal layout (data.docdata.b2b / cdnr)
  gstr2b_092026.xlsx                         portal Excel layout (title rows, 2-row header)
  purchase_register_092026.xlsx              Tally-style purchase register
  tally_daybook_092026.xml                   Tally XML export of the same vouchers
  truth.json                                 the correct status (and any Sec 17(5) block) for every case

All names and GSTINs are invented (GSTINs carry valid check digits).
"""
from __future__ import annotations

import json
import random
import string
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook

from .gstin import check_digit
from .models import DocType, Status

WORDS_A = ["Shree", "Vardhan", "Apex", "Kaveri", "Sahyadri", "Orion", "Navkar", "Indus", "Trident", "Mahalaxmi",
           "Prism", "Saraswati", "Unity", "Deccan", "Bharat", "Crescent", "Everest", "Ganesh", "Jyoti", "Konark",
           "Lotus", "Matrix", "Nirmal", "Omkar", "Pioneer", "Riddhi", "Sunrise", "Tulsi", "Vertex", "Zenith"]
WORDS_B = ["Steel", "Polymers", "Packaging", "Logistics", "Fasteners", "Chemicals", "Electricals", "Castings",
           "Traders", "Tooling", "Paints", "Hydraulics", "Bearings", "Rubber", "Wires", "Office Supplies"]
SUFFIX = ["Pvt Ltd", "LLP", "Enterprises", "Industries", "Pvt Ltd", "& Co"]
# Purchase / expense ledgers. Normal ones carry full ITC; the second list are Sec 17(5) cases with the
# block TwoB should flag ('' = looks risky but is allowed, so it must NOT be flagged).
NORMAL_LEDGERS = [("Purchase @18%", "7318"), ("Raw Material Purchase", "7208"), ("Packing Material", "4819"),
                  ("Freight Inward", "996511"), ("Consumables", "8207"), ("Repairs - Plant & Machinery", "998719"),
                  ("Professional Fees", "998221"), ("Purchase @5%", "3901"), ("Job Work Charges", "998898")]
BLOCKED_LEDGERS = [("Staff Welfare - Food", "996334", "food"), ("Hotel - Food & Beverages", "996332", "food"),
                   ("Car Repairs & Maintenance", "998714", "motor_vehicle"), ("Cab Hire Charges", "996601", "motor_vehicle"),
                   ("Club Membership Fees", "999652", "club"), ("Group Health Insurance", "997133", "insurance"),
                   ("Diwali Gifts to Customers", "9505", "gifts"), ("CSR Expenses", "999799", "csr"),
                   ("Leave Travel Concession", "998552", "travel_vacation"),
                   ("Office Building Construction", "995411", "construction")]
LOOKALIKE_LEDGERS = [("Lodging - Business Travel", "996311", ""), ("Goods Vehicle Hire", "996601", ""),
                     ("Fire Insurance - Factory", "997135", ""), ("Truck Freight Charges", "996511", "")]
STATES = ["27"] * 6 + ["24", "29", "33", "07", "09", "36", "06", "08"]


def make_gstin(rng, state: str, pan: str | None = None) -> str:
    if pan is None:
        pan = ("".join(rng.choice(string.ascii_uppercase) for _ in range(3)) + rng.choice("CFP") +
               rng.choice(string.ascii_uppercase) + f"{rng.randint(1000, 9999)}" + rng.choice(string.ascii_uppercase))
    first = f"{state}{pan}1Z"
    return first + check_digit(first)


@dataclass
class Supplier:
    gstin: str
    name: str
    style: int
    prefix: str
    seq: int
    alt_gstin: str = ""


@dataclass
class Inv:
    gstin: str
    name: str
    no: str
    dt: date
    taxable: float
    igst: float
    cgst: float
    sgst: float
    typ: str = "INV"
    rev: str = "N"
    itcavl: str = "Y"
    rsn: str = ""
    period: str = "092026"
    ledger: str = ""
    hsn: str = ""
    blocked: str = ""            # Sec 17(5) rule TwoB should flag ('' = none)


@dataclass
class Case:
    case: str
    expected: list
    books: list = field(default_factory=list)      # list[Inv]
    portal: list = field(default_factory=list)     # list[Inv]


def _number(s: Supplier, n: int) -> str:
    if s.style == 0:
        return f"{s.prefix}/26-27/{n:04d}"
    if s.style == 1:
        return f"{s.prefix}-{n}"
    if s.style == 2:
        return str(n)
    if s.style == 3:
        return f"GST/2026-27/{n:03d}"
    if s.style == 4:
        return f"{s.prefix}{n:05d}"
    return f"{s.prefix}/{n}/26-27"


def _books_variant(no: str, rng) -> str:
    """How an accountant might shorten a supplier's number."""
    from .normalize import k3
    last = k3(no) or no
    options = [last, no.replace("/", "-"), no.replace("2026-27/", "").replace("26-27/", ""),
               no.lower().replace("/", ""), last.zfill(5)]
    options = [o for o in options if o and o != no]
    return rng.choice(options)


def _typo_seq(n: int, rng) -> int:
    """A keying mistake in the serial number: swap two adjacent digits or change one."""
    d = list(str(n))
    if len(d) >= 2 and rng.random() < 0.5:
        i = rng.randrange(len(d) - 1)
        if d[i] != d[i + 1] and not (i == 0 and d[1] == "0"):
            d[i], d[i + 1] = d[i + 1], d[i]
            return int("".join(d))
    i = rng.randrange(len(d))
    d[i] = str((int(d[i]) + rng.randint(1, 8)) % 10)
    m = int("".join(d))
    # a leading 0 would silently drop digits (604 -> 004 -> 4): that is not a one-key typo
    return m if m != n and len(str(m)) == len(str(n)) else n + 10


def _tax(rng, taxable, intra, rate=None):
    rate = rate or rng.choice([5, 18, 18, 18, 18, 40])
    t = round(taxable * rate / 100, 2)
    if intra:
        half = round(t / 2, 2)
        return 0.0, half, half
    return t, 0.0, 0.0


def generate(out_dir: str | Path, seed: int = 7, n_suppliers: int = 45, n_invoices: int = 320,
             hard: bool = False) -> dict:
    rng = random.Random(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    client_gstin = make_gstin(rng, "27")
    client_name = "Sharma Auto Components Pvt Ltd (fictional)"

    sups: list[Supplier] = []
    used = set()
    for i in range(n_suppliers):
        while True:
            name = f"{rng.choice(WORDS_A)} {rng.choice(WORDS_B)} {rng.choice(SUFFIX)}"
            if name not in used:
                used.add(name)
                break
        g = make_gstin(rng, rng.choice(STATES))
        prefix = "".join(w[0] for w in name.split()[:2]).upper() + rng.choice(["", "I", "T"])
        style = 2 if (hard and rng.random() < 0.4) else rng.randint(0, 5)    # hard: many plain numbers
        sups.append(Supplier(g, name, style, prefix, rng.randint(1, 900)))
    for s in sups[:4]:                                  # multi-state suppliers
        other = rng.choice([x for x in ["27", "24", "29", "33"] if x != s.gstin[:2]])
        s.alt_gstin = make_gstin(rng, other, s.gstin[2:12])

    weights = {"exact": 64, "rounding": 4, "format": 9, "date": 3, "typo": 2, "value_down": 1.5,
               "value_up": 1.5, "head": 1, "other_gstin": 1.2, "split": 1.2, "late": 3, "not_filed": 3,
               "internal_no": 1, "dup": 0.6}
    if hard:   # a messy client: far more mismatches
        weights = {"exact": 38, "rounding": 5, "format": 14, "date": 5, "typo": 5, "value_down": 3,
                   "value_up": 3, "head": 2, "other_gstin": 3, "split": 3, "late": 6, "not_filed": 6,
                   "internal_no": 3, "dup": 2}
    kinds = list(weights)
    cases: list[Case] = []
    blocked_share = 0.10 if hard else 0.06

    def new_inv(s: Supplier, d: date, taxable=None, rate=None) -> Inv:
        s.seq += rng.randint(1, 4)
        taxable = taxable or round(rng.lognormvariate(10.6, 1.0), 2)
        taxable = min(max(taxable, 1500.0), 2_500_000.0)
        intra = s.gstin[:2] == client_gstin[:2]
        ig, cg, sg = _tax(rng, taxable, intra, rate)
        r = rng.random()
        if r < blocked_share:
            ledger, hsn, blk = rng.choice(BLOCKED_LEDGERS)
        elif r < blocked_share + 0.03:
            ledger, hsn, blk = rng.choice(LOOKALIKE_LEDGERS)
        else:
            (ledger, hsn), blk = rng.choice(NORMAL_LEDGERS), ""
        return Inv(s.gstin, s.name, _number(s, s.seq), d, taxable, ig, cg, sg, ledger=ledger, hsn=hsn, blocked=blk)

    def clone(x: Inv, **kw) -> Inv:
        y = Inv(**{**x.__dict__})
        for k, v in kw.items():
            setattr(y, k, v)
        return y

    def make_case(kind: str, s: Supplier, d: date):
        if kind == "other_gstin" and not s.alt_gstin:
            s = rng.choice([x for x in sups if x.alt_gstin])
        inv = new_inv(s, d)
        if kind == "exact":
            cases.append(Case(kind, [Status.EXACT], [inv], [clone(inv)]))
        elif kind == "rounding":
            p = clone(inv, taxable=round(inv.taxable + rng.choice([-0.4, 0.3, 0.5]), 2))
            cases.append(Case(kind, [Status.EXACT], [inv], [p]))
        elif kind == "format":
            cases.append(Case(kind, [Status.FORMAT_DIFF, Status.EXACT],
                              [clone(inv, no=_books_variant(inv.no, rng))], [inv]))
        elif kind == "date":
            cases.append(Case(kind, [Status.DATE_DIFF],
                              [clone(inv, dt=inv.dt + timedelta(days=rng.randint(1, 6)))], [inv]))
        elif kind == "typo":
            cases.append(Case(kind, [Status.TYPO], [clone(inv, no=_number(s, _typo_seq(s.seq, rng)))], [inv]))
        elif kind in ("value_down", "value_up"):
            f = rng.uniform(0.05, 0.4) * (1 if kind == "value_up" else -1)
            pt = round(inv.taxable * (1 + f), 2)
            r = (inv.igst + inv.cgst + inv.sgst) / inv.taxable
            p = clone(inv, taxable=pt, igst=round(pt * r, 2) if inv.igst else 0.0,
                      cgst=round(pt * r / 2, 2) if inv.cgst else 0.0, sgst=round(pt * r / 2, 2) if inv.sgst else 0.0)
            cases.append(Case(kind, [Status.VALUE_DIFF], [inv], [p]))
        elif kind == "head":
            t = inv.igst + inv.cgst + inv.sgst
            p = (clone(inv, igst=0.0, cgst=round(t / 2, 2), sgst=round(t / 2, 2)) if inv.igst
                 else clone(inv, igst=round(inv.cgst + inv.sgst, 2), cgst=0.0, sgst=0.0))
            cases.append(Case(kind, [Status.HEAD_MISMATCH], [inv], [p]))
        elif kind == "other_gstin":
            cases.append(Case(kind, [Status.OTHER_GSTIN], [inv], [clone(inv, gstin=s.alt_gstin)]))
        elif kind == "split":
            d = min(d, date(2026, 9, 27))           # all parts stay inside September
            parts = [new_inv(s, d + timedelta(days=k), rate=18) for k in range(rng.choice([2, 3]))]
            intra = s.gstin[:2] == client_gstin[:2]
            tot = round(sum(x.taxable for x in parts), 2)
            b = Inv(s.gstin, s.name, parts[-1].no, parts[-1].dt, tot,
                    round(sum(x.igst for x in parts), 2), round(sum(x.cgst for x in parts), 2),
                    round(sum(x.sgst for x in parts), 2), ledger=parts[0].ledger, hsn=parts[0].hsn,
                    blocked=parts[0].blocked)
            if rng.random() < 0.5:
                b.no = f"{parts[0].no} to {parts[-1].no}"
            cases.append(Case(kind, [Status.SPLIT], [b], parts))
        elif kind == "late":
            cases.append(Case(kind, [Status.LATE_FILED], [inv], [clone(inv, period="102026")]))
        elif kind == "not_filed":
            cases.append(Case(kind, [Status.BOOKS_ONLY], [inv], []))
        elif kind == "internal_no":
            cases.append(Case(kind, [Status.PROBABLE, Status.BOOKS_ONLY, Status.PORTAL_ONLY_KNOWN],
                              [clone(inv, no=f"PUR/{rng.randint(100, 999)}")], [inv]))
        elif kind == "dup":
            cases.append(Case(kind, [Status.EXACT, Status.BOOKS_DUPLICATE], [inv, clone(inv)], [clone(inv)]))


    counts = Counter()
    for _ in range(n_invoices):
        kind = rng.choices(kinds, weights=[weights[k] for k in kinds])[0]
        counts[kind] += 1
        make_case(kind, rng.choice(sups), date(2026, 9, rng.randint(1, 30)))
    for kind in kinds:                      # every mismatch type appears at least 3 times
        for _ in range(max(0, 3 - counts[kind])):
            make_case(kind, rng.choice(sups), date(2026, 9, rng.randint(1, 30)))
    if hard:                                # recurring same-amount bills (rent, AMC, transport)
        for s in rng.sample(sups, 4):
            amt = round(rng.uniform(20000, 90000), 2)
            for wk, kind in enumerate(rng.sample(["exact", "exact", "not_filed", "late", "exact"], 5)):
                inv = new_inv(s, date(2026, 9, 2 + 6 * wk), taxable=amt, rate=18)
                if kind == "exact":
                    cases.append(Case("recurring_exact", [Status.EXACT], [inv], [clone(inv)]))
                elif kind == "not_filed":
                    cases.append(Case("recurring_not_filed", [Status.BOOKS_ONLY], [inv], []))
                else:
                    cases.append(Case("recurring_late", [Status.LATE_FILED], [inv], [clone(inv, period="102026")]))

    # portal-only and credit notes
    in_books = sorted({b.gstin for c in cases for b in c.books})
    known = [x for x in sups if x.gstin in in_books]        # 'known' = the client has booked from them
    for _ in range(6):
        s = rng.choice(known)
        cases.append(Case("portal_known", [Status.PORTAL_ONLY_KNOWN], [], [new_inv(s, date(2026, 9, rng.randint(1, 30)))]))
    for _ in range(3):
        g = make_gstin(rng, rng.choice(STATES))
        stranger = Supplier(g, f"{rng.choice(WORDS_A)} Trading Co", 2, "X", rng.randint(1, 500))
        cases.append(Case("portal_unknown", [Status.PORTAL_ONLY_UNKNOWN], [],
                          [new_inv(stranger, date(2026, 9, rng.randint(1, 30)))]))
    for _ in range(3):
        s = rng.choice(sups)
        cn = new_inv(s, date(2026, 9, rng.randint(1, 30)), taxable=round(rng.uniform(2000, 40000), 2))
        cn.typ, cn.no = "CN", f"CN/{rng.randint(10, 99)}"
        cases.append(Case("portal_cn", [Status.PORTAL_ONLY_CN], [], [cn]))
    for _ in range(4):
        s = rng.choice(sups)
        cn = new_inv(s, date(2026, 9, rng.randint(1, 30)), taxable=round(rng.uniform(2000, 40000), 2))
        cn.typ, cn.no = "CN", f"CRN-{rng.randint(100, 999)}"
        cases.append(Case("books_cn", [Status.EXACT], [cn], [clone(cn)]))
    for _ in range(2):
        s = rng.choice(sups)
        b = new_inv(s, date(2026, 9, rng.randint(1, 30)))
        cases.append(Case("blocked", [Status.PORTAL_ITC_BLOCKED], [],
                          [clone(b, itcavl="N", rsn="POS and supplier state are same but recipient state is different")]))

    # noise in October 2B: genuine October invoices, nothing to do with September books
    oct_noise = [clone(new_inv(rng.choice(sups), date(2026, 10, rng.randint(1, 31))), period="102026") for _ in range(25)]

    books = [b for c in cases for b in c.books]
    portal = [p for c in cases for p in c.portal] + oct_noise
    rng.shuffle(books)

    for per in ("092026", "102026"):
        _write_2b_json(out / f"gstr2b_{per}.json", client_gstin, per, [p for p in portal if p.period == per])
    _write_2b_excel(out / "gstr2b_092026.xlsx", client_gstin, [p for p in portal if p.period == "092026"])
    _write_register(out / "purchase_register_092026.xlsx", client_name, books, columnar=hard)
    _write_tally_xml(out / "tally_daybook_092026.xml", books)

    truth = []
    for c in cases:
        truth.append({"case": c.case, "expected": [e.value for e in c.expected],
                      "books": [_key(b) for b in c.books], "portal": [_key(p) for p in c.portal],
                      "blocked": next((b.blocked for b in c.books if b.blocked and b.typ != "CN"), "")})
    meta = {"client_gstin": client_gstin, "client_name": client_name, "period": "092026",
            "books_entries": len(books), "portal_sep": sum(1 for p in portal if p.period == "092026"),
            "cases": len(cases), "seed": seed, "hard": hard}
    (out / "truth.json").write_text(json.dumps({"meta": meta, "cases": truth}, indent=1))
    return meta


def _key(x: Inv) -> list:
    return [x.gstin, x.no, x.dt.isoformat(), round(x.igst + x.cgst + x.sgst, 2), x.typ, x.period]


def _write_2b_json(path, client, period, invs):
    b2b, cdnr = {}, {}
    for x in invs:
        bucket = cdnr if x.typ == "CN" else b2b
        sup = bucket.setdefault(x.gstin, {"ctin": x.gstin, "trdnm": x.name, "supfildt": "10-10-2026",
                                          "supprd": period, "inv" if x.typ == "INV" else "nt": []})
        rec = {"dt": x.dt.strftime("%d-%m-%Y"), "val": round(x.taxable + x.igst + x.cgst + x.sgst, 2),
               "pos": client[:2], "rev": x.rev, "itcavl": x.itcavl, "rsn": x.rsn, "diffprcnt": 1,
               "srctyp": "", "irn": "", "irngendate": "",
               "items": [{"num": 1, "rt": 18, "txval": x.taxable, "igst": x.igst, "cgst": x.cgst,
                          "sgst": x.sgst, "cess": 0}]}
        if x.typ == "CN":
            rec.update({"ntnum": x.no, "typ": "C", "suptyp": "R"})
            sup["nt"].append(rec)
        else:
            rec.update({"inum": x.no, "typ": "R"})
            sup["inv"].append(rec)
    data = {"chksum": "synthetic", "data": {"gstin": client, "rtnprd": period, "version": "1.0",
                                            "gendt": "14-10-2026",
                                            "docdata": {"b2b": list(b2b.values()), "cdnr": list(cdnr.values())}}}
    Path(path).write_text(json.dumps(data, indent=1))


def _write_2b_excel(path, client, invs):
    wb = Workbook()
    ws = wb.active
    ws.title = "Read me"
    ws["A1"] = "Goods and Services Tax - GSTR-2B (synthetic sample)"
    for title, typ in (("B2B", "INV"), ("B2B-CDNR", "CN")):
        ws = wb.create_sheet(title)
        ws["A1"] = "Goods and Services Tax - GSTR 2B"
        ws["A2"] = f"Taxable inward supplies received from registered persons - {title}"
        top = ["GSTIN of supplier", "Trade/Legal name", "Invoice details", "", "", "", "Place of supply",
               "Supply Attract Reverse Charge", "Taxable Value (₹)", "Tax Amount", "", "", "",
               "GSTR-1/IFF/GSTR-5 Period", "GSTR-1/IFF/GSTR-5 Filing Date", "ITC Availability", "Reason"]
        sub = ["", "", "Invoice number", "Invoice type", "Invoice Date", "Invoice Value(₹)", "", "", "",
               "Integrated Tax(₹)", "Central Tax(₹)", "State/UT Tax(₹)", "Cess(₹)", "", "", "", ""]
        if typ == "CN":
            top[2] = "Credit note/Debit note details"
            sub[2:6] = ["Note number", "Note type", "Note date", "Note Value (₹)"]
        ws.append([])
        ws.append([])
        ws.append(top)
        ws.append(sub)
        for x in invs:
            if x.typ != typ:
                continue
            ws.append([x.gstin, x.name, x.no, "Credit Note" if typ == "CN" else "Regular",
                       x.dt.strftime("%d/%m/%Y"), round(x.taxable + x.igst + x.cgst + x.sgst, 2),
                       "Maharashtra", x.rev, x.taxable, x.igst, x.cgst, x.sgst, 0, "Sep'26", "10/10/2026",
                       "Yes" if x.itcavl == "Y" else "No", x.rsn])
    wb.save(path)


def _write_register(path, client_name, books, columnar=False):
    """columnar=False: one 'Purchase Ledger' + 'HSN/SAC' column (a typical Excel export).
    columnar=True: Tally's columnar register - every purchase/expense ledger is its own amount column."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Purchase Register"
    ws.append([client_name])
    ws.append(["Purchase Register", "1-Sep-26 to 30-Sep-26"])
    ws.append([])
    head = ["Date", "Particulars", "Voucher Type", "Voucher No.", "Supplier Invoice No.",
            "Supplier Invoice Date", "GSTIN/UIN", "Taxable Value", "Input CGST", "Input SGST", "Input IGST",
            "Gross Total"]
    ledgers = sorted({b.ledger for b in books if b.ledger}) if columnar else []
    ws.append(head + (ledgers if columnar else ["Purchase Ledger", "HSN/SAC"]))
    for i, b in enumerate(sorted(books, key=lambda x: x.dt), 1):
        vt = "Debit Note" if b.typ == "CN" else "Purchase"
        row = [b.dt + timedelta(days=1), b.name, vt, i, b.no, b.dt, b.gstin, b.taxable, b.cgst, b.sgst,
               b.igst, round(b.taxable + b.igst + b.cgst + b.sgst, 2)]
        if columnar:
            row += [b.taxable if b.ledger == lg else None for lg in ledgers]
        else:
            row += [b.ledger, b.hsn]
        ws.append(row)
    for row in ws.iter_rows(min_row=5):
        row[0].number_format = row[5].number_format = "dd-mmm-yy"
    wb.save(path)


def _write_tally_xml(path, books):
    out = ["<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>"
           "<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME></REQUESTDESC><REQUESTDATA>"]
    for i, b in enumerate(sorted(books, key=lambda x: x.dt), 1):
        vt = "Debit Note" if b.typ == "CN" else "Purchase"
        name = b.name.replace("&", "&amp;")
        total = round(b.taxable + b.igst + b.cgst + b.sgst, 2)
        led = [f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{name}</LEDGERNAME><AMOUNT>{total:.2f}</AMOUNT></ALLLEDGERENTRIES.LIST>",
               f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{(b.ledger or 'Purchase @ GST').replace('&', '&amp;')}</LEDGERNAME><AMOUNT>-{b.taxable:.2f}</AMOUNT></ALLLEDGERENTRIES.LIST>"]
        for ln, amt in (("Input IGST", b.igst), ("Input CGST", b.cgst), ("Input SGST", b.sgst)):
            if amt:
                led.append(f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{ln}</LEDGERNAME><AMOUNT>-{amt:.2f}</AMOUNT></ALLLEDGERENTRIES.LIST>")
        out.append(f'<TALLYMESSAGE><VOUCHER VCHTYPE="{vt}" ACTION="Create">'
                   f"<DATE>{(b.dt + timedelta(days=1)).strftime('%Y%m%d')}</DATE>"
                   f"<VOUCHERTYPENAME>{vt}</VOUCHERTYPENAME><VOUCHERNUMBER>{i}</VOUCHERNUMBER>"
                   f"<REFERENCE>{b.no}</REFERENCE><REFERENCEDATE>{b.dt.strftime('%Y%m%d')}</REFERENCEDATE>"
                   f"<PARTYLEDGERNAME>{name}</PARTYLEDGERNAME><PARTYGSTIN>{b.gstin}</PARTYGSTIN>"
                   + "".join(led) + "</VOUCHER></TALLYMESSAGE>")
    out.append("</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
    Path(path).write_text("\n".join(out), encoding="utf-8")
