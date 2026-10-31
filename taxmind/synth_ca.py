"""Realistic CA-firm test data: purchase register + GSTR-2B as CA staff actually receive them.

Mimics the *patterns* of one real (anonymised, confidential) month a CA firm shared: a Tally journal-register
export (header on row 4, SUBTOTAL row 3, junk in names, invoice date only in the narration, blank GSTIN /
invoice no., Gross Total net of TDS/retention, debit-note vouchers carrying the ORIGINAL invoice no., zero-GST
rows, rectification rows) and the firm's flattened GSTR-2B sheet (header row 5, 'Credit'/'Debit'/'B2BA' rows,
misspelt 'ITC Availibility', 'June,2026' periods). Every supplier, GSTIN, PAN, name, address and invoice number
here is invented (GSTINs carry valid check digits). Nothing is copied from the real file.

    from taxmind.synth_ca import generate
    generate("test_data")                                   # all six profiles
    python -m taxmind.synth_ca --out test_data [--profile a_manufacturer_plant] [--seed 11] [--stress]

Per profile folder:
    Purchase Register Jun-26.xlsx      books, CA layout (sheet 'Purchase Jun-26', header row 4)
    Purchase Register Jun-26.csv       same rows, same row numbers (CSV record N = Excel row N)
    GSTR-2B Apr-26.xlsx .. Jul-26.xlsx 2B per month, CA's flattened layout (sheet 'GSTR-2B Mon-26', header row 5)
    062026_<gstin>_GSTR2B_14072026.json  return-month 2B in the official JSON layout (b2b / cdnr / b2ba)
    GSTR-3B Working Jun-26.xlsx        combined workbook (Summary + Purchase + 2B sheets, CA remarks filled in)
    Vendor Master.xlsx                 GSTIN, name, Activity, ITC eligibility (as the firm keeps it)
    truth.json                         the answer key (see below)

Return month is June 2026 (062026); April and May 2B hold invoices booked late (reclaims), July 2B holds late filers.

CASE VOCABULARY (truth.json -> groups[].case). A group is one real-world document situation with its
books row(s) and 2B row(s).
  Books row(s) with a partner in the return-month (Jun) 2B:
    exact                    same GSTIN, invoice no. and amounts (books 'Date' is still the voucher date)
    round_off                tax or taxable differ by <= Rs 1
    round_1to6               a head differs by Rs 1-6 (Tally rounding per head)
    taxable_differs          tax agrees; books 'Taxable' includes non-GST charges (freight/insurance/visa fee)
    amount_less_in_2b        supplier reported less tax than books (incl. books rate-keying errors)
    amount_more_in_2b        supplier reported more tax than books
    invno_format             invoice no. written differently (slashes, FY suffix, leading zeros, prefix)
    invno_typo               one-character keying error in the invoice no.
    date_diff                invoice date in the narration differs from 2B (wrong day / dd-mm swapped)
    invno_missing_narration  'Invoice No' blank; the number is only in the narration
    gstin_missing_name       'GSTIN/UIN' blank; supplier resolvable by name / vendor master
    split                    one books line = 2-3 supplier invoices, or 2 books lines = 1 invoice
    wrong_head               books CGST+SGST vs 2B IGST (or the reverse)
    other_gstin_same_pan     supplier reported under its other-state GSTIN (same PAN)
    prior_fy_current_2b      FY 2025-26 invoice the supplier uploaded late, now in Jun 2B (claim before 30-Nov-2026)
    duplicate_in_books       the same line booked twice; one 2B record
    books_cn_matched         'Debit Note' voucher: Invoice No column = original invoice, CN no. only in narration
    books_cn_no_ref          'Debit Note' "Purchase Return" with no GSTIN / no number; 2B name differs
    booked_without_gst       books has the bill with 0 GST, 2B has tax (CA: 'Matched-Ineligible ITC-Booked with non-GST')
    rcm                      reverse charge (GTA with RCM flag in 2B; advocate / import of services not in 2B)
  Books row(s) with a partner in another month's 2B, or none:
    earlier_2b_reclaim       invoice was in the Apr/May 2B, not booked then (reversed in 4B2) -> reclaim now (4A5 + 4D1)
    late_filer_next_month    supplier filed late: invoice is in the Jul 2B -> no ITC in June
    prior_fy_not_in_2b       FY 2025-26 invoice in no loaded 2B; Sec 16(4) deadline 30-Nov-2026
    books_only_not_uploaded  supplier has not uploaded the invoice at all
    books_cn_not_in_2b       books debit note; supplier has not reported the credit note
    billed_to_other_branch   (multi-GSTIN client) invoice addressed to the client's other-state GSTIN, booked here
  Books rows that carry no ITC (excluded; groups[].excluded says why):
    excluded_nongst          diesel / liquor / electricity (outside GST) or nil-rated goods
    excluded_unregistered    rent etc. paid to unregistered individuals, no GSTIN, no tax
    excluded_advance         advance / proforma payment, 0 taxable
    excluded_provision       "Provision for exp reversed" rows (taxable is a provision amount, no tax)
    rectification            "Excess booking now rectified ..." / "Less booking made earlier ..." adjustments
  2B rows with no books row in June:
    portal_only_known        supplier is in this register; this bill is not booked (yet)
    portal_only_other_register  supplier is in the vendor master (airline, car hire, hotel, lease...) but its bills
                             are not carried by this register; CA reverses them in 4B2 ('No matching invoice in PR')
    portal_only_unknown      supplier appears nowhere (not in books, not in the vendor master)
    portal_cn_not_booked     supplier credit note not in books
    portal_dn_not_booked     supplier debit note ('Debit' rows) not in books
    portal_itc_unavailable   2B 'ITC Availibility' = No (PoS rule / Sec 16(4)) -> Table 4(D)(2)
    b2ba_amendment           B2BA row amending an earlier month's invoice (only the difference counts)
    other_month_noise        Apr/May/Jul 2B rows handled in their own month (must not be paired with June books)

ORTHOGONAL LABELS on each group: traits[] (gstin_blank, invno_blank, invno_int, pan_blank, name_junk,
name_differs, date_only_in_narration, no_invoice_date, taxable_inflated, gross_net, multi_line_voucher,
prior_fy, rate_keying_error, recurring_amount, prev_month_voucher, sgst_blank, late_supplier_filing),
blocked (Sec 17(5) rule id as in taxmind.blocked: construction, motor_vehicle, food, insurance, gifts, club,
csr, personal ...), blocked_exception (True for allowed look-alikes: plant & machinery, buses > 13 seats,
forklifts, factory canteen under the Factories Act, a hotel buying food, a works contractor buying cement,
a car dealer buying cars), lookalike_of (the rule an allowed item resembles).

ITC (truth groups[].itc_claim, signed, by head) is what the CA claims in the June GSTR-3B before 17(5)
reversals; bucket says where it goes (4A5_2b, 4A5_reclaim, 4A3_rcm, none). truth.table4 follows the CA's
Summary-sheet method: 4A5 = Jun 2B ITC (available, forward charge, net of credit notes and B2BA differences)
+ reclaims; 4B1 = Sec 17(5) items claimed this month (current + reclaimed); 4B2 = Jun 2B ITC not matched to
books ('No matching invoice found in PR', booked without GST, held for wrong head / other GSTIN, excess over
books); 4D1 = reclaims; 4D2 = 2B ITC marked not available.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import json
import random
import re
import string
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from .gstin import STATES as STATE_NAMES
from .gstin import check_digit

RETURN = "062026"
MONTHS = ["042026", "052026", "062026", "072026"]

CASES = [
    "exact", "round_off", "round_1to6", "taxable_differs", "amount_less_in_2b", "amount_more_in_2b",
    "invno_format", "invno_typo", "date_diff", "invno_missing_narration", "gstin_missing_name", "split",
    "wrong_head", "other_gstin_same_pan", "prior_fy_current_2b", "duplicate_in_books", "books_cn_matched",
    "books_cn_no_ref", "booked_without_gst", "rcm", "earlier_2b_reclaim", "late_filer_next_month",
    "prior_fy_not_in_2b", "books_only_not_uploaded", "books_cn_not_in_2b", "billed_to_other_branch",
    "excluded_nongst", "excluded_unregistered", "excluded_advance", "excluded_provision", "rectification",
    "portal_only_known", "portal_only_other_register", "portal_only_unknown", "portal_cn_not_booked",
    "portal_dn_not_booked", "portal_itc_unavailable", "b2ba_amendment", "other_month_noise",
]

BOOK_COLS = ["Date", "Particulars", "Address", "Voucher Type", "Voucher No.", "Voucher Ref. No.",
             "Voucher Ref. Date", "GSTIN/UIN", "Sales Tax No.", "Service Tax No.", "PAN No.", "CST No.",
             "Invoice No", "Narration", "Gross Total", "Taxable", "IGST", "CGST", "SGST", "Total Tax", "Rate",
             "Lookup", "Remark", "Activity", "ITC ELIGIBLITY"]
P2B_COLS = ["Period", "GSTIN of supplier", "Trade/Legal name", "POS", "Invoice Type", "Reverse Charge",
            "Invoice No", "Invoice Date", "Invoice Value", "Taxable Value", "Tax Rate", "IGST", "CGST", "SGST",
            "Total Tax", "Cess", "GSTR-1/5 Filling Period", "GSTR-1/5 Filling Date", "ITC Availibility",
            "E-Invoice Applicable", "Lookup", "Remark", "Activity", "ITC ELIGIBLITY"]
BOOKS_HEADER_ROW = 4
P2B_HEADER_ROW = 5

# ── small helpers ────────────────────────────────────────────────────────────────────────────────────────


def per_first(p: str) -> date:
    return date(int(p[2:]), int(p[:2]), 1)


def per_of(d: date) -> str:
    return d.strftime("%m%Y")


def per_add(p: str, k: int) -> str:
    m, y = int(p[:2]) - 1 + k, int(p[2:])
    return f"{m % 12 + 1:02d}{y + m // 12}"


def per_last(p: str) -> date:
    d = per_first(p)
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def month_full(p: str) -> str:
    return f"{calendar.month_name[int(p[:2])]},{p[2:]}"


def month_abbr(p: str) -> str:
    return f"{calendar.month_abbr[int(p[:2])]},{p[2:]}"


def mon_yy(p: str) -> str:
    return f"{calendar.month_abbr[int(p[:2])]}-{p[4:]}"


def _fy(d: date) -> int:
    return d.year if d.month >= 4 else d.year - 1


def fy_short(d):
    y = _fy(d)
    return f"{y % 100:02d}-{(y + 1) % 100:02d}"


def fy_long(d):
    y = _fy(d)
    return f"{y}-{(y + 1) % 100:02d}"


def fy_compact(d):
    y = _fy(d)
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def fy_full(d):
    y = _fy(d)
    return f"{y}-{y + 1}"


def r2(x):
    return round(x + 0.0, 2)


def _ordinal(n):
    return "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def narr_date(d: date, rng) -> str:
    """The many ways staff type a date into a narration."""
    opts = [d.strftime("%d/%m/%Y"), d.strftime("%d-%b-%Y"), f"{d.day}-{d:%b}-{d:%y}", d.strftime("%d-%b-%y"),
            f"{d.day} {d:%B} {d.year}", f"{d.day:02d}{_ordinal(d.day)} {d:%b} {d.year}", d.strftime("%d-%m-%Y"),
            f"{d.day:02d}/{d:%b}/{d.year}", f"{d.day}-{d:%b}-{d.year}", f"{d.day:02d}/{d:%B}/{d.year}",
            d.strftime("%d.%m.%Y"), f"{d.day} {d:%b} {d.year}"]
    return rng.choice(opts)


def rand_pan(rng, entity: str, initial: str | None = None) -> str:
    L = string.ascii_uppercase
    return ("".join(rng.choice(L) for _ in range(3)) + entity + (initial or rng.choice(L)) +
            f"{rng.randint(1000, 9999)}" + rng.choice(L))


def make_gstin(state: str, pan: str, entity_no: str = "1") -> str:
    first = f"{state}{pan}{entity_no}Z"
    return first + check_digit(first)


REFS = ["Invoice No - {no} dtd - {dt}\t\n", "invoice no : {no}\t{dt}\n", "Inv No {no} dtd {dt}",
        "as per invoice no : {no}\t{dt}\n", "Tax Invoice No - {no} dtd - {dt}\t\n", "Invoice No: {no}\t{dt}\n",
        "as per invoices : {no}\t{dt}\n", "Invoice No & dtd - As per invoice no : {no}\n, dtd {dt}",
        "Inv No. {no}, dtd {dt}", "as per Invoice No - {no} dtd - {dt}\t_x000D_\n", "invoice no : {no}, dtd {dt}",
        "vide bill no. {no} dated {dt}", "Tax Inv No. {no} dtd {dt}", "incvoice no : {no}, dtd {dt}",
        "Invoice no- {no} dtd {dt}\t\n", "As per INVOCIE NO :{no} \t{dt}\n"]
REFS_NODATE = ["as per invoice no : {no}\t\n", "Invoice No - {no} dtd -\t\n", "invoice no : , {no}\n",
               "Tax Invoice No - as per invoice no {no}\n"]
CITY3 = {"27": ["PUN", "MUM", "NSK", "AUR"], "29": ["BLR"], "24": ["AMD", "VAD"], "33": ["CHN"], "07": ["DEL"],
         "06": ["GGN"], "09": ["NOI"], "36": ["HYD"], "08": ["JAI"], "23": ["IND"], "19": ["KOL"]}
CITIES = {"27": ["Pune", "Mumbai", "Chh. Sambhajinagar", "Nashik", "Nagpur", "Ahilyanagar", "Thane"],
          "29": ["Bengaluru", "Mysuru"], "24": ["Ahmedabad", "Vadodara", "Rajkot"], "33": ["Chennai", "Hosur"],
          "07": ["New Delhi"], "06": ["Gurugram", "Faridabad"], "09": ["Noida", "Lucknow"], "36": ["Hyderabad"],
          "08": ["Jaipur"], "23": ["Indore", "Pithampur"], "19": ["Kolkata"], "03": ["Ludhiana"], "22": ["Raipur"]}
STATE_ALPHA = {"27": "MH", "24": "GJ", "29": "KA", "07": "DL", "33": "TN", "36": "TG", "09": "UP", "19": "WB",
               "22": "CG", "23": "MP", "06": "HR", "08": "RJ", "03": "PB"}
NAME_A = ["Sahyog", "Vighnaharta", "Aarohi", "Kesar", "Nandadeep", "Shubhankar", "Tejas", "Vedant", "Akshar",
          "Bhairav", "Chaitanya", "Dhruv", "Ekdant", "Gajraj", "Hiranya", "Ishaan", "Jaidev", "Lokmanya",
          "Mrugank", "Nakshatra", "Ojas", "Parijat", "Rajhans", "Sanket", "Tanmay", "Ujjwal", "Vasundhara",
          "Yashodhan", "Amrut", "Chintamani", "Devgiri", "Gomukh", "Harshal", "Indrayani", "Janhavi", "Kamdhenu",
          "Pushpak", "Sankalp", "Trimbak", "Varad", "Yojak", "Ajinkya", "Navdurga", "Suvidha", "Aadesh",
          "Karmveer", "Mayur", "Pranav", "Ruturaj", "Shardul", "Vinayak", "Advait", "Bhoomi", "Dnyanesh",
          "Girnar", "Kshitij", "Nilkanth", "Omkareshwar", "Rudra", "Saptashrungi", "Vaibhav", "Ashwamedh"]
FIRST = ["Rohan", "Sneha", "Amit", "Priya", "Vikas", "Kavita", "Nitin", "Meera", "Sachin", "Anjali", "Rahul",
         "Pooja", "Suresh", "Deepa", "Ganesh", "Swati", "Mahesh", "Neha", "Prakash", "Shilpa", "Ajay", "Rupali",
         "Sanjay", "Vaishali", "Kiran", "Manoj", "Asha", "Yogesh", "Rekha", "Tushar"]
LAST = ["Deshpande", "Kulkarni", "Patil", "Jadhav", "Shinde", "Pawar", "Gaikwad", "Bhosale", "Joshi", "Kale",
        "More", "Salunkhe", "Wagh", "Thorat", "Mane", "Sawant", "Kadam", "Nikam", "Bendre", "Iyer",
        "Menon", "Reddy", "Sharma", "Verma", "Agarwal", "Mehta", "Shah", "Naik", "Rao"]

# ── categories ───────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Cat:
    key: str
    activity: tuple            # vendor-master 'Activity' text options
    elig: str                  # vendor-master ITC eligibility (what the firm believes; may be wrong in law)
    rates: tuple
    median: float
    sigma: float
    bodies: tuple              # narration bodies
    nouns: tuple               # supplier-name nouns
    items: tuple = ("goods",)
    blocked: str = ""          # Sec 17(5) rule id (taxmind.blocked) when the law blocks it
    exception: bool = False    # looks like a blocked item but is allowed for this client
    lookalike: str = ""        # rule it resembles
    kind: str = "gst"          # gst | nongst | unreg | rcm_gta | rcm_unreg | advance | provision
    entity: str = "C"          # C company, F firm/LLP, P proprietor
    inter: float = 0.25        # share of suppliers outside the client's state
    styles: tuple = (0, 1, 3, 4, 5, 7, 8, 9)
    recurring: bool = False    # monthly bills (rent, lease, manpower): mostly matched in time
    inflate: float = 0.0       # share of rows where books 'Taxable' includes non-GST charges
    einv: float = 0.6
    note: str = ""


def C(key, activity, elig, rates, median, sigma, bodies, nouns, **kw):
    if isinstance(activity, str):
        activity = (activity,)
    return Cat(key, tuple(activity), elig, tuple(rates), median, sigma, tuple(bodies), tuple(nouns), **kw)


PROJECT = ["new e-Tractor Plant at Supa MIDC, Ahilyanagar", "Phase 2 expansion at Supa MIDC plant",
           "Battery Assembly Shop, Supa plant", "R&D Centre, Chakan"]
SHOP = ["Press Shop", "Body-in-White Shop", "Paint Shop", "Final Assembly Shop", "Battery Shop", "Utility Block"]

LIB = {
    # ---- manufacturer building a plant -------------------------------------------------------------------
    "raw_material": C("raw_material", ("Raw Material", "RAW MAT", "Raw Material", "HEX BOLTS M10 X 1.5 - STEEL, ZINC PLATED",
                      "WIRING HARNESS AND PARTS THEREOF", "RUBBER PROFILES, VULCANISED", "#N/A"), "Yes",
                      (18, 18, 18, 18, 5), 28000, 1.2,
                      ("Procurement of {item} for {project}", "Procurement of {n} Nos. {item} for proto tractors - R&D Centre",
                       "Procurement of {item} from M/s {other} / PO basic value Rs {po} / Cost per vehicle Rs {cpv} / Application - {appl}"),
                      ("Auto Components", "Precision Engineering", "Rubber Products", "Fasteners", "Wiring Systems",
                       "Glass Works", "Plastomers", "Forgings", "Pressings", "Polymers", "Castings"),
                      items=("LV wiring harness", "brake chamber assemblies", "hex bolts M10 x 55", "cabin glass sets",
                             "battery pack mounting brackets", "seat frames", "rubber door profiles", "LED tail lamps",
                             "hydraulic hoses", "tow hook blocks", "plain washers", "insulated clips"), inter=0.4,
                      styles=(0, 1, 3, 4, 5, 6, 6, 6, 2, 7, 8, 9)),
    "pm_capex": C("pm_capex", ("OTHER LIFTING HANDLING LOADING MACHINERY", "CNC MACHINE", "COMPRESSOR", "TRANSFORMER",
                  "#N/A", "Capital Goods"), "Yes", (18,), 1_400_000, 1.0,
                  ("Payment for supply and installation of {item} for {shop} at {project}",
                   "Procurement of {item} for {shop}, Installation and Commissioning at {project}",
                   "Payment for supply of {item} - {shop}, RA bill {n}"),
                  ("Machine Tools", "Automation Systems", "Hydraulics", "Electricals", "Material Handling Systems",
                   "Conveyors", "Cranes & Hoists", "Compressors", "Robotics"),
                  items=("110T CNC hydraulic press brake", "screw air compressor package with receiver",
                         "2000 kVA transformer and HT panel", "single slat conveyor for tractor assembly line",
                         "5T double girder EOT crane", "robotic welding cell", "wheel alignment test rig",
                         "paint booth exhaust blowers", "battery module stacking machine"), inter=0.45, inflate=0.5,
                  styles=(0, 6, 6, 2, 7, 9, 3)),
    "pm_lookalike": C("pm_lookalike", ("CRANE", "OTHER LIFTING HANDLING LOADING MACHINERY", "#N/A"), "Yes", (18,),
                      900_000, 0.8,
                      ("Supply and erection of structural supports and gantry girders for {item} in {shop} building",
                       "Machine foundation for {item} in {shop} (machinery foundation)",
                       "Supply of steel structural supports for {item}, {shop} - fixing of machinery"),
                      ("Cranes & Hoists", "Engineering Works", "Fabricators"),
                      items=("5T EOT crane", "800T servo press", "compressor skid", "paint booth conveyor"),
                      exception=True, lookalike="construction",
                      note="Foundation / structural supports used to fix plant & machinery are P&M (Explanation to Sec 17)."),
    "civil": C("civil", ("Civil", "CIVIL", "CivIL construction", "Construction Services", "Works Contract Services"), "No",
               (18,), 900_000, 1.0,
               ("Payment for Civil Works of {area} for {project} - RA bill {n}",
                "Construction of {area} at {project} site", "Payment for Supply of precast drain elements for Civil Works of {project}",
                "Works contract - {area}, {project}"),
               ("Infra Projects", "Buildcon", "Constructions", "Civil Engineers", "Infrastructure", "Structures"),
               items=("goods",), blocked="construction", inter=0.1, inflate=0.2),
    "peb": C("peb", ("CivIL construction", "PEB Structure"), "NO", (18,), 1_800_000, 0.8,
             ("Procurement of PEB Structures for {shop} building at {project}",),
             ("Steel Buildings", "Prefab Structures", "PEB Systems"), blocked="construction", inter=0.7, inflate=0.6),
    "paint_civil": C("paint_civil", ("CIVIL for Paint shop",), "NO", (18,), 3_000_000, 0.7,
                     ("Procurement of Material for Paint Shop building works at {project}",
                      "Paint Shop building - supply of civil & structural material, {project}"),
                     ("Engineering India", "Paint Systems", "Turnkey Projects"), blocked="construction", inter=1.0,
                     inflate=0.9, styles=(8,)),
    "transport": C("transport", ("Transportation",), "YES", (18, 18, 5), 25000, 0.9,
                   ("Transport Service Charges for {month} - {city} to {city2}",
                    "Freight charges for movement of {item} - {month}"),
                   ("Roadlines", "Logistics", "Transport Co", "Freight Carriers", "Cargo Movers", "Supply Solutions"),
                   items=("dies and fixtures", "proto tractors", "battery packs"), entity="F", styles=(9, 0, 1)),
    "gta_rcm": C("gta_rcm", ("Transportation", "GTA - RCM"), "Yes", (5,), 30000, 0.7,
                 ("GTA freight charges (RCM) - {city} to {city2}, LR no {n}",
                  "Freight inward under reverse charge - {item}, consignment {n}"),
                 ("Roadways", "Golden Transport", "Truck Carriers"), items=("steel coils", "castings"),
                 kind="rcm_gta", entity="F", styles=(2, 1)),
    "manpower": C("manpower", ("Manpower supply",), "Yes", (18,), 120000, 0.8,
                  ("Manpower supply charges for the month of {month}",
                   "Payment for shop floor manpower and travelling exp for {month} - {site}"),
                  ("Facility Services", "Manpower Solutions", "HR Services", "Workforce Solutions"), recurring=True),
    "security": C("security", ("Guard",), "Yes", (18,), 130000, 0.4,
                  ("Payment for monthly security guards service charges ({n} guards) for the month of {month} at {site}",),
                  ("Security Services", "Guarding Solutions"), recurring=True),
    "professional": C("professional", ("Professional Fees", "consltancy"), "Yes", (18,), 90000, 1.0,
                      ("Professional Fees - {item}",),
                      ("& Associates", "Consultants", "Advisory LLP", "& Co"),
                      items=("software development for BOM management tool", "statutory audit fees FY 25-26",
                             "transfer pricing study", "project management consultancy - plant", "ISO 14001 certification"),
                      entity="F", inter=0.3),
    "advocate_rcm": C("advocate_rcm", ("Legal Fees",), "Yes", (18,), 60000, 0.6,
                      ("Legal fees to Adv. {person} for {item} (RCM)",),
                      ("Advocate",), items=("land title verification", "labour court matter", "lease deed drafting"),
                      kind="rcm_unreg", entity="P"),
    "it_hw": C("it_hw", ("IT and Software", "#N/A"), "yes", (18,), 250000, 1.1,
               ("Procurement of {n} Nos. {item} for {site}", "Payment for supply and implementation of {item}"),
               ("Infotech", "Systems", "Computers", "Networks", "Technologies"),
               items=("computer workstations with monitor", "network switches and firewall", "CCTV cameras",
                      "servers and data centre racks"), inflate=0.3),
    "crane_service": C("crane_service", ("CRANE",), "Yes", (18,), 25000, 0.5,
                       ("Crane Service Charges for loading and unloading of heavy parts, blocks - {month}",),
                       ("Crane Service", "Cranes", "Hydra Services"), entity="P", styles=(2,)),
    "maintenance": C("maintenance", ("MAINTENANCE OR REPAIR SERVICE",), "Yes", (18,), 30000, 0.9,
                     ("Repair and maintenance of {item} at {site}",),
                     ("Engineering Services", "Electro Services", "Maintenance Services", "Cooling Solutions"),
                     items=("DG set", "air conditioners", "fire hydrant pumps", "factory shed roof sheets - revenue repairs")),
    "testing": C("testing", ("Testing",), "Yes", (18,), 60000, 0.8, ("Testing charges for {item}",),
                 ("Testing Labs", "Calibration Services", "Test House"),
                 items=("homologation of tractor model", "EMC test of battery pack", "calibration of gauges")),
    "hotel_room": C("hotel_room", ("Hotel",), "Yes", (5, 5, 18), 22000, 0.8,
                    ("Accomodation charges of Employees for {month}, {person} - {range}",
                     "Accommodation charges for {person} (room only) - {month}"),
                    ("Hotel {A} Residency", "{A} Hospitality", "Hotel {A} Inn"), styles=(0, 1, 9)),
    "hotel_food": C("hotel_food", ("Hotel",), "Yes", (5, 18), 35000, 0.6,
                    ("Food & beverages bill for {event} - {person}", "Lunch and dinner arranged for {event}"),
                    ("{A} Hospitality", "Hotel {A} Grand"), blocked="food", styles=(0, 1)),
    "car_lease": C("car_lease", ("Lease Rent",), "Yes", (18, 18, 18, 40, 5), 30000, 0.7,
                   ("Car Lease Rental Charges - {month} - {person_up}", "Car FMS Rental Charges - {month} - {person_up}"),
                   ("Fleet Leasing & Finance",), blocked="motor_vehicle", recurring=True, styles=(10,), einv=1.0),
    "forklift_lease": C("forklift_lease", ("Lease Rent",), "Yes", (18,), 60000, 0.3,
                        ("Lease rental for 3T electric forklift - {month}", "Rental of battery operated forklift - {month}"),
                        ("Equipment Rentals", "Material Handling Rentals"), exception=True, lookalike="motor_vehicle",
                        recurring=True),
    "staff_bus": C("staff_bus", ("Bus for Staff",), "Yes", (18, 5), 340000, 0.3,
                   ("Bus hire charges for staff transportation (32 seater, {n} buses) for {month}",),
                   ("Tours & Travels", "Travels"), exception=True, lookalike="motor_vehicle", entity="F",
                   recurring=True, styles=(5,)),
    "car_hire": C("car_hire", ("Car Hire Exp out",), "NO", (5,), 9000, 0.8,
                  ("Car hire charges for {person} - {city} visit {month}", "Cab hire charges for guests - {month}"),
                  ("Car Rentals", "Cabs", "Travel Solutions"), blocked="motor_vehicle", styles=(10,)),
    "canteen_stat": C("canteen_stat", ("Canteen",), "Yes", (5,), 180000, 0.3,
                      ("Factory canteen charges for {month} - canteen maintained under the Factories Act (u/s 46)",),
                      ("Caterers", "Food Services"), exception=True, lookalike="food", recurring=True),
    "staff_food": C("staff_food", ("Staff Welfare", "#N/A"), "Yes", (5, 18), 12000, 0.7,
                    ("Snacks, tea and lunch for {event}", "Staff welfare - refreshments for {event}"),
                    ("Caterers", "Sweets & Snacks", "Food Court"), blocked="food", entity="P", styles=(2, 1)),
    "truck_insurance": C("truck_insurance", ("Insurance",), "Yes", (18,), 25000, 0.5,
                         ("Insurance Premium payment for goods carriage policy - truck {veh}",
                          "Motor insurance premium for 32-seater staff bus {veh}"),
                         ("General Insurance",), exception=True, lookalike="motor_vehicle", styles=(6,)),
    "car_insurance": C("car_insurance", ("Insurance",), "Yes", (18,), 30000, 0.4,
                       ("Motor insurance premium for company car (sedan) {veh}",),
                       ("General Insurance",), blocked="motor_vehicle", styles=(6,)),
    "gifts": C("gifts", ("#N/A", "Business Promotion"), "Yes", (18, 5), 60000, 0.6,
               ("Diwali gift hampers for dealers and customers", "Gifts for dealers' meet - {city}"),
               ("Gift Gallery", "Corporate Gifting"), blocked="gifts", entity="P", styles=(2, 1)),
    "health_ins": C("health_ins", ("Insurance",), "Yes", (18,), 400000, 0.3,
                    ("Group mediclaim policy premium for employees FY 26-27",),
                    ("General Insurance",), blocked="insurance", styles=(6,)),
    "club": C("club", ("#N/A",), "#N/A", (18,), 90000, 0.3, ("Corporate club membership fees for MD - FY 26-27",),
              ("Gymkhana Club",), blocked="club", entity="F", styles=(2,)),
    "visa": C("visa", ("#N/A",), "#N/A", (18,), 1500, 0.4,
              ("{country} Visa for employee {person}",), ("Tours and Travels", "Visa Services"), entity="P",
              styles=(9,)),
    "diesel": C("diesel", ("#N/A",), "#N/A", (0,), 45000, 0.5,
                ("Supply of {n} Ltr. of Diesel @ Rs. {price} for DG sets at {site}",),
                ("Service Station", "Petroleum"), kind="nongst", entity="F", styles=(3,)),
    "rent_unreg": C("rent_unreg", ("#N/A",), "#N/A", (0,), 60000, 0.4,
                    ("Payment of monthly rent expenses for {month} for Guest House at {city} (Rs. {rent} pm)",),
                    ("",), kind="unreg", entity="P"),
    "advance": C("advance", ("#N/A",), "#N/A", (0,), 300000, 0.8,
                 ("Advance payment against proforma invoice no PI/{n} for {item}",
                  "Advance paid against PO {n} - {item}"),
                 ("",), items=("tooling", "conveyor spares", "software licences"), kind="advance"),
    "provision": C("provision", ("#N/A",), "#N/A", (0,), 300000, 1.0,
                   ("Provision for exp reversed for FRN {n}", "provision for exp reversed", "Provision of exp reversed"),
                   ("",), kind="provision"),
    # ---- trader ------------------------------------------------------------------------------------------
    "trade_goods": C("trade_goods", ("Trading Goods", "Purchase - Trading", "#N/A"), "Yes", (18, 18, 5, 40), 14000, 1.0,
                     ("Purchase of {item} for resale", "Purchase of {n} cartons {item}", "Being goods purchased - {item}"),
                     ("Traders", "Distributors", "Marketing", "Enterprises", "Agencies", "Sales Corporation"),
                     items=("electrical switches", "LED bulbs", "PVC conduits", "ceiling fans", "MCB distribution boards",
                            "copper wires", "water heaters", "extension boards"), entity="F", inter=0.2,
                     styles=(0, 1, 2, 5, 9), einv=0.3),
    "packing": C("packing", ("Packing Material",), "Yes", (18,), 8000, 0.6,
                 ("Purchase of corrugated boxes and packing tape", "Packing material - stretch film, boxes"),
                 ("Packaging", "Corrugators"), entity="P", styles=(2, 1, 0)),
    "rent_reg": C("rent_reg", ("Rent",), "Yes", (18,), 45000, 0.4, ("Shop rent for {month} - {city} godown",),
                  ("Estates", "Properties", "Realty"), entity="F", recurring=True, styles=(9, 5)),
    "electricity": C("electricity", ("#N/A",), "#N/A", (0,), 18000, 0.5, ("Electricity charges for {month} - consumer no {n}",),
                     ("State Electricity Distribution Co",), kind="nongst", styles=(6,)),
    "telephone": C("telephone", ("Telephone",), "Yes", (18,), 2500, 0.5, ("Broadband and mobile charges - {month}",),
                   ("Telelinks", "Broadband Services"), recurring=True, styles=(6, 4)),
    "car_repair": C("car_repair", ("Vehicle Exp",), "Yes", (18,), 15000, 0.6, ("Car servicing and repairs - owner's car {veh}",),
                    ("Motors", "Auto Service"), blocked="motor_vehicle", entity="F"),
    "tempo_hire": C("tempo_hire", ("Transportation",), "Yes", (18, 5), 9000, 0.5, ("Tempo hire for local delivery of goods - {month}",),
                    ("Tempo Services", "Transport"), exception=True, lookalike="motor_vehicle", entity="P", styles=(2,)),
    # ---- hotel / restaurant ------------------------------------------------------------------------------
    "food_provisions": C("food_provisions", ("Food Provisions", "Kitchen Purchase"), "Yes", (5, 5, 18), 22000, 0.9,
                         ("Purchase of {item} for kitchen - restaurant", "Kitchen provisions - {item}"),
                         ("Foods", "Provision Stores", "Dairy", "Agro Foods", "Spices"),
                         items=("paneer and dairy products", "basmati rice", "edible oil", "spices", "frozen seafood",
                                "chicken and meat", "bakery items"), exception=True, lookalike="food", entity="F",
                         styles=(0, 1, 2, 9)),
    "beverages": C("beverages", ("Beverages",), "Yes", (18, 40), 30000, 0.7, ("Purchase of {item} for restaurant & bar",),
                   ("Beverages", "Distributors"), items=("aerated drinks", "packaged juices", "mineral water"),
                   exception=True, lookalike="food"),
    "liquor": C("liquor", ("#N/A",), "#N/A", (0,), 120000, 0.6, ("Purchase of liquor for bar - TP no {n}",),
                ("Wines", "Liquor Distributors"), kind="nongst", entity="F", styles=(2,)),
    "vegetables": C("vegetables", ("#N/A",), "#N/A", (0,), 15000, 0.6, ("Fresh vegetables and fruits - week {n}",),
                    ("Vegetable Suppliers", "Fresh Farms"), kind="nongst", entity="P", styles=(2,)),
    "lpg": C("lpg", ("Fuel",), "Yes", (18,), 40000, 0.4, ("Commercial LPG cylinders (19 kg) - {n} Nos.",),
             ("Gas Agency", "Gas Distributors"), entity="F"),
    "laundry": C("laundry", ("Laundry",), "Yes", (18,), 25000, 0.5, ("Laundry charges for linen - {month}",),
                 ("Laundry Services", "Dry Cleaners"), entity="P", recurring=True),
    "housekeeping": C("housekeeping", ("Housekeeping",), "Yes", (18,), 18000, 0.6, ("Housekeeping material - {item}",),
                      ("Hygiene Solutions", "Cleaning Supplies"), items=("toiletries", "chemicals", "garbage bags")),
    "renovation": C("renovation", ("Civil",), "No", (18,), 700000, 0.6,
                    ("Renovation of guest rooms - civil and interior works (capitalised), RA bill {n}",
                     "Interior fit-out of banquet hall - capital work in progress"),
                    ("Interiors", "Constructions"), blocked="construction"),
    "repairs_revenue": C("repairs_revenue", ("Repairs",), "Yes", (18,), 25000, 0.6,
                         ("Repairs & maintenance - plumbing and painting of rooms (revenue)",),
                         ("Maintenance Services", "Engineering Services"), exception=True, lookalike="construction",
                         entity="P"),
    "staff_meals": C("staff_meals", ("Staff Welfare",), "Yes", (5,), 15000, 0.5,
                     ("Provisions for staff cafeteria - staff meals {month}",), ("Caterers", "Foods"), blocked="food",
                     entity="P", styles=(2,)),
    "guest_transport": C("guest_transport", ("Car Hire",), "Yes", (5,), 20000, 0.6,
                         ("Car hire for guest airport transfers billed to guests - {month}",),
                         ("Car Rentals", "Cabs"), exception=True, lookalike="motor_vehicle", entity="F", styles=(10,)),
    "owner_car": C("owner_car", ("Vehicle Exp",), "Yes", (18,), 25000, 0.6,
                   ("Car repairs and maintenance - director's car {veh}",), ("Motors", "Auto Service"),
                   blocked="motor_vehicle", entity="F"),
    # ---- works contractor ----------------------------------------------------------------------------------
    "cement": C("cement", ("Cement", "Raw Material"), "Yes", (18,), 180000, 0.8,
                ("Purchase of {n} bags OPC 53 grade cement for {project_c}",), ("Cement", "Building Materials"),
                exception=True, lookalike="construction", inter=0.3),
    "steel": C("steel", ("Steel", "Raw Material"), "Yes", (18,), 350000, 0.8,
               ("Purchase of TMT bars Fe 550D ({n} MT) for {project_c}",), ("Steels", "Ispat", "Metals"),
               exception=True, lookalike="construction", inter=0.3),
    "rmc": C("rmc", ("RMC",), "Yes", (18,), 250000, 0.7, ("Supply of ready mix concrete M25 - {n} cum for {project_c}",),
             ("Concrete", "RMC"), exception=True, lookalike="construction"),
    "sand_agg": C("sand_agg", ("Aggregates",), "Yes", (5,), 60000, 0.6, ("Supply of crushed sand and 20 mm aggregates for {project_c}",),
                  ("Stone Crushers", "Minerals"), entity="P", styles=(2, 1), exception=True, lookalike="construction"),
    "subcontract": C("subcontract", ("Works Contract Services", "Sub-contract"), "Yes", (18,), 600000, 0.8,
                     ("Sub-contract civil works for {project_c} - RA bill {n}",
                      "Sub-contract - construction of {area} for client project {project_c}"),
                     ("Constructions", "Infra", "Contractors"), exception=True, lookalike="construction", entity="F"),
    "equip_hire": C("equip_hire", ("Machinery Hire",), "Yes", (18,), 80000, 0.6,
                    ("Hire charges of JCB and hydra crane for {project_c} - {month}",), ("Earthmovers", "Equipment"),
                    entity="P", styles=(2, 1), exception=True, lookalike="construction"),
    "labour": C("labour", ("Labour Charges", "Manpower supply"), "Yes", (18,), 150000, 0.6,
                ("Labour supply charges for {project_c} - {month}",), ("Labour Contractors", "Manpower"),
                entity="P", recurring=True, exception=True, lookalike="construction"),
    "own_office": C("own_office", ("Civil",), "No", (18,), 900000, 0.6,
                    ("Construction of own office building at {city} (capitalised), RA bill {n}",),
                    ("Buildcon",), blocked="construction"),
    "camp_food": C("camp_food", ("Staff Welfare",), "Yes", (5,), 30000, 0.5, ("Food for staff at site - {month}",),
                   ("Caterers", "Mess"), blocked="food", entity="P", styles=(2,)),
    # ---- car dealer ------------------------------------------------------------------------------------------
    "cars_oem": C("cars_oem", ("Purchase - Vehicles",), "Yes", (18, 40), 900_000, 0.4,
                  ("Purchase of {n} Nos. {model} for resale - stock", "Purchase - Vehicles: {model}, chassis {chassis}"),
                  ("Motors India",), items=("goods",), exception=True, lookalike="motor_vehicle", inter=1.0,
                  styles=(6,), einv=1.0),
    "spares": C("spares", ("Spare Parts",), "Yes", (18,), 80000, 0.9, ("Purchase of spare parts for workshop stock",),
                ("Motors India", "Auto Parts"), inter=0.8, styles=(6, 4)),
    "lubes": C("lubes", ("Oil & Lubricants",), "Yes", (18,), 40000, 0.6, ("Engine oil and lubricants for workshop",),
               ("Lubricants",), styles=(4, 1)),
    "showroom_interior": C("showroom_interior", ("Civil",), "No", (18,), 800000, 0.5,
                           ("Showroom interior fit-out and civil works - new showroom at {city}",),
                           ("Interiors",), blocked="construction", entity="F"),
    "transit_ins": C("transit_ins", ("Insurance",), "Yes", (18,), 30000, 0.5,
                     ("Transit insurance for vehicle stock in trade - {month}",), ("General Insurance",),
                     exception=True, lookalike="motor_vehicle", styles=(6,)),
    "delivery_gifts": C("delivery_gifts", ("Business Promotion",), "Yes", (18,), 40000, 0.5,
                        ("Gift hampers for customers at car delivery - {month}",), ("Gift Gallery",),
                        blocked="gifts", entity="P", styles=(2,)),
    "md_car": C("md_car", ("Vehicle Exp",), "Yes", (18, 40), 1_100_000, 0.2,
                ("Car purchased for MD's personal use - capitalised",), ("Motors",), blocked="motor_vehicle"),
    # ---- professional services (multi-GSTIN) ---------------------------------------------------------------
    "office_rent": C("office_rent", ("Rent",), "Yes", (18,), 350000, 0.4, ("Office rent for {month} - {city} office",),
                     ("Realty", "Estates", "Business Parks"), recurring=True, styles=(9, 5)),
    "coworking": C("coworking", ("Rent",), "Yes", (18,), 120000, 0.4, ("Co-working seats ({n} seats) - {month}",),
                   ("Workspaces",), recurring=True, inter=0.6),
    "saas": C("saas", ("IT and Software",), "Yes", (18,), 60000, 0.8, ("Annual subscription - {item}",),
              ("Softech", "Cloud Solutions"), items=("audit software", "practice management software", "tax research database")),
    "import_saas": C("import_saas", ("IT and Software",), "Yes", (18,), 90000, 0.5,
                     ("Import of service - cloud storage subscription from overseas vendor (RCM IGST)",),
                     ("Overseas",), kind="rcm_unreg", styles=(2,)),
    "associates": C("associates", ("Professional Fees",), "Yes", (18,), 120000, 0.9,
                    ("Professional fees - associate firm for {item}",), ("& Associates", "& Co", "Advisors LLP"),
                    items=("tax audit support", "GST audit support", "valuation report", "due diligence"),
                    entity="F", inter=0.6),
    "laptops": C("laptops", ("IT and Software",), "Yes", (18,), 180000, 0.5, ("Purchase of {n} laptops for staff",),
                 ("Computers", "Infotech")),
    "office_fitout": C("office_fitout", ("Civil",), "No", (18,), 1_200_000, 0.4,
                       ("Interior fit-out of new office at {city} (capitalised)",), ("Interiors",), blocked="construction"),
    "team_lunch": C("team_lunch", ("Staff Welfare",), "Yes", (5, 18), 18000, 0.5, ("Team lunch - {event}",),
                    ("Restaurant", "Caterers"), blocked="food", entity="F", styles=(2,)),
    "cab_hire": C("cab_hire", ("Car Hire Exp out",), "NO", (5,), 7000, 0.7, ("Cab hire for partners - {city} - {month}",),
                  ("Cabs", "Car Rentals"), blocked="motor_vehicle", styles=(10,)),
    "airline_books": C("airline_books", ("Airline",), "Yes", (5, 18), 9000, 0.6, ("Air ticket for {person} - {city} to {city2}",),
                       ("Airways",), styles=(11,)),
    "venue": C("venue", ("Hotel",), "Yes", (18,), 80000, 0.4, ("Hall rent for client seminar at {city} (hall hire only)",),
               ("Hotel {A} Grand",), exception=True, lookalike="food"),
    "csr": C("csr", ("CSR",), "No", (18,), 250000, 0.3, ("Laptops donated to municipal school under CSR (Sec 135)",),
             ("Computers",), blocked="csr"),
    "telecom": C("telecom", ("Telephone",), "Yes", (18,), 15000, 0.6, ("Mobile and leased line charges - {month}",),
                 ("Telecom",), recurring=True, styles=(6,)),
}

# 2B-only categories (supplier in vendor master; bills booked elsewhere or not at all)
NOISE = {
    "airline": dict(activity="Airline", elig="Yes", rates=(5, 5, 5, 18), median=4500, sigma=0.6, kind="airline"),
    "car_hire": dict(activity="Car Hire Exp out", elig="NO", rates=(5,), median=6000, sigma=0.9, kind="cab"),
    "hotel": dict(activity="Hotel", elig="Yes", rates=(5, 5, 18), median=12000, sigma=0.9, kind="hotel"),
    "lease": dict(activity="Lease Rent", elig="Yes", rates=(18, 40, 5), median=25000, sigma=0.7, kind="lease"),
    "courier": dict(activity="#N/A", elig="#N/A", rates=(18,), median=900, sigma=0.8, kind="courier"),
    "telecom": dict(activity="IT and Software", elig="yes", rates=(18,), median=15000, sigma=0.8, kind="telecom"),
    "airport": dict(activity="Airport operation services", elig="Yes", rates=(5,), median=8000, sigma=0.4, kind="airport"),
    "misc": dict(activity="#N/A", elig="#N/A", rates=(18, 18, 5, 40), median=25000, sigma=1.3, kind="misc"),
}


@dataclass
class Profile:
    key: str
    title: str
    client: str
    state: str
    n_books: int                       # GST bills in the books (rows come out ~10-20% more)
    cats: dict                         # category -> weight
    case_w: dict                       # case -> weight (normal categories)
    noise: dict                        # per month: noise kind -> rows
    known_extra: int                   # per month: unbooked bills from suppliers in this register
    unknown: int
    cn: int
    dn: int
    itcn: int
    branches: tuple = ()               # client's other-state registrations
    fixed: dict = field(default_factory=dict)   # case -> minimum count
    description: str = ""


BASE_CASES = {"exact": 14, "round_off": 2.5, "round_1to6": 1.5, "taxable_differs": 1.5, "amount_less_in_2b": 1,
              "amount_more_in_2b": 0.8, "invno_format": 3, "invno_typo": 0.8, "date_diff": 0.6, "split": 0.8,
              "wrong_head": 0.5, "other_gstin_same_pan": 0.5, "late_filer_next_month": 3, "prior_fy_current_2b": 1.2,
              "prior_fy_not_in_2b": 0.6, "books_only_not_uploaded": 3, "duplicate_in_books": 0.6,
              "booked_without_gst": 0.5, "earlier_2b_reclaim": 40}
RECURRING_CASES = {"exact": 75, "round_off": 5, "invno_format": 4, "late_filer_next_month": 6,
                   "books_only_not_uploaded": 4, "earlier_2b_reclaim": 4, "duplicate_in_books": 1}
FIXED_COMMON = {"books_cn_matched": 2, "books_cn_no_ref": 1, "books_cn_not_in_2b": 1, "rectification": 5,
                "duplicate_in_books": 2, "split": 2, "wrong_head": 2, "other_gstin_same_pan": 2, "invno_typo": 2,
                "date_diff": 2, "booked_without_gst": 2, "amount_more_in_2b": 2, "amount_less_in_2b": 2,
                "prior_fy_current_2b": 2, "prior_fy_not_in_2b": 2, "round_1to6": 2, "taxable_differs": 2,
                "b2ba_amendment": 1}


def _w(base, **over):
    d = dict(base)
    d.update(over)
    return d


PROFILES = {
    "a_manufacturer_plant": Profile(
        "a_manufacturer_plant", "Manufacturer building a new plant (capex + civil heavy)",
        "Sahyadri e-Tractors Ltd", "27", 520,
        {"raw_material": 22, "pm_capex": 8, "pm_lookalike": 2, "civil": 9, "peb": 2, "paint_civil": 3, "transport": 5,
         "gta_rcm": 1, "manpower": 5, "security": 2, "professional": 3, "advocate_rcm": 0.5, "it_hw": 3,
         "crane_service": 2, "maintenance": 3, "testing": 1.5, "hotel_room": 2, "hotel_food": 0.7, "car_lease": 6,
         "forklift_lease": 1, "staff_bus": 1, "car_hire": 2, "canteen_stat": 0.8, "staff_food": 0.8,
         "truck_insurance": 0.5, "car_insurance": 0.5, "gifts": 0.4, "health_ins": 0.3, "club": 0.2, "visa": 0.5,
         "diesel": 1.5, "rent_unreg": 1.5, "advance": 1.2, "provision": 2.5},
        _w(BASE_CASES, exact=8),
        {"airline": 290, "car_hire": 60, "hotel": 45, "lease": 25, "courier": 25, "telecom": 6, "airport": 15,
         "misc": 300},
        known_extra=110, unknown=15, cn=50, dn=10, itcn=4,
        description="Like the firm's real client: a manufacturer building a new plant. Civil / PEB / paint-shop "
                    "building items are blocked (17(5)(c)/(d)); cranes, conveyors, transformers, machine "
                    "foundations are plant & machinery (allowed). 2B is dominated by airline, car-hire, hotel and "
                    "lease bills this register does not carry. Most books invoices are from earlier months' 2B."),
    "b_trader": Profile(
        "b_trader", "Trader with many small recurring invoices", "Kesarinath Electricals & Co", "27", 420,
        {"trade_goods": 60, "packing": 6, "gta_rcm": 4, "transport": 4, "rent_reg": 3, "electricity": 3,
         "telephone": 2, "staff_food": 1, "gifts": 1.5, "car_repair": 1, "tempo_hire": 2, "rent_unreg": 2,
         "advance": 1, "provision": 0.5, "professional": 1},
        _w(BASE_CASES, exact=45, earlier_2b_reclaim=12, invno_format=8, round_off=6, late_filer_next_month=5,
           books_only_not_uploaded=4, duplicate_in_books=1.2),
        {"misc": 40, "courier": 10, "telecom": 2},
        known_extra=80, unknown=10, cn=25, dn=5, itcn=2,
        description="Electrical-goods trader: small, frequent purchase bills (many plain numeric invoice nos., "
                    "same-amount recurring rent / broadband bills), GTA freight under RCM, trade-discount credit notes."),
    "c_hotel_restaurant": Profile(
        "c_hotel_restaurant", "Hotel with restaurant (specified premises, 18% with ITC)", "Hotel Nilkanth Heights Pvt Ltd",
        "27", 300,
        {"food_provisions": 30, "beverages": 6, "liquor": 4, "vegetables": 6, "lpg": 4, "laundry": 3,
         "housekeeping": 5, "renovation": 2, "repairs_revenue": 2, "staff_meals": 1.5, "guest_transport": 2,
         "owner_car": 0.7, "club": 0.3, "rent_unreg": 1, "professional": 2, "maintenance": 3, "advance": 1},
        _w(BASE_CASES, exact=35, earlier_2b_reclaim=15),
        {"misc": 30, "courier": 4, "telecom": 2},
        known_extra=40, unknown=6, cn=8, dn=2, itcn=2,
        description="Food and beverages bought to serve guests are allowed (outward supply of the same kind); "
                    "staff meals are blocked. Liquor and fresh vegetables carry no GST. Room renovation (capitalised) "
                    "is blocked; revenue repairs are allowed."),
    "d_works_contractor": Profile(
        "d_works_contractor", "Works contractor (cement / steel / sub-contracts)", "Devgiri Infracon Pvt Ltd", "27", 350,
        {"cement": 12, "steel": 12, "rmc": 6, "sand_agg": 5, "subcontract": 10, "equip_hire": 5, "labour": 5,
         "diesel": 5, "gta_rcm": 3, "own_office": 1, "owner_car": 0.5, "camp_food": 1, "gifts": 0.5,
         "professional": 2, "rent_unreg": 1, "advance": 2, "provision": 1},
        _w(BASE_CASES, exact=25, earlier_2b_reclaim=25),
        {"misc": 40, "courier": 3, "telecom": 2},
        known_extra=50, unknown=8, cn=10, dn=2, itcn=2,
        description="Inputs and sub-contracts for client projects are allowed (works contract supplied onward); "
                    "the contractor's own office building is blocked."),
    "e_car_dealer": Profile(
        "e_car_dealer", "Car dealer (buys cars for resale)", "Pushpak Motors Pvt Ltd", "27", 250,
        {"cars_oem": 30, "spares": 15, "lubes": 4, "showroom_interior": 1.5, "transit_ins": 2, "delivery_gifts": 1,
         "md_car": 0.5, "staff_food": 1, "rent_reg": 2, "professional": 1, "advance": 1, "maintenance": 2},
        _w(BASE_CASES, exact=30, earlier_2b_reclaim=20),
        {"misc": 15, "courier": 4},
        known_extra=30, unknown=5, cn=15, dn=3, itcn=1,
        description="Cars bought for resale (and their transit insurance) are allowed; the MD's car, showroom "
                    "construction and customer gifts are blocked. OEM issues incentive credit notes."),
    "f_professional_multi_gstin": Profile(
        "f_professional_multi_gstin", "Professional services firm with GSTINs in 3 states", "Ruturaj Advisory LLP",
        "27", 200,
        {"office_rent": 4, "coworking": 3, "saas": 4, "import_saas": 2, "associates": 10, "laptops": 3,
         "office_fitout": 1.5, "team_lunch": 1.5, "health_ins": 1, "cab_hire": 3, "hotel_room": 3,
         "airline_books": 3, "club": 0.5, "venue": 1, "csr": 0.5, "advocate_rcm": 1, "telecom": 2, "rent_unreg": 1,
         "advance": 1},
        _w(BASE_CASES, exact=30, earlier_2b_reclaim=12, other_gstin_same_pan=3, wrong_head=2,
           billed_to_other_branch=4),
        {"airline": 40, "hotel": 15, "car_hire": 10, "misc": 15},
        known_extra=30, unknown=5, cn=6, dn=2, itcn=4, branches=("29", "07"),
        description="Mumbai registration of a firm also registered in Karnataka and Delhi: IGST-heavy associate "
                    "fees, bills addressed to the other branches but booked here, supplier branches in several "
                    "states, out-of-state hotel stays where ITC is not available (PoS)."),
}

# ── records ─────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Sup:
    sid: int
    cat: str
    gstin: str
    pan: str
    legal: str               # name as in 2B
    books_name: str          # ledger name in Tally (messy)
    style: int
    prefix: str
    seq: int
    rate: int
    pan_in_books: bool = True
    gstin_in_books: bool = True
    in_master: bool = True
    master_activity: str = "#N/A"
    master_elig: str = "#N/A"
    alt_gstin: str = ""
    einv: str | None = "Yes"
    registered: bool = True
    city3: str = "PUN"
    in_books: bool = False
    used: set = field(default_factory=set)


@dataclass
class Bill:
    sup: Sup
    gstin: str
    no: str
    dt: date
    taxable: float
    igst: float
    cgst: float
    sgst: float
    typ: str = "INV"        # INV / CN / DN
    rate: int = 18
    rcm: bool = False

    @property
    def tax(self):
        return r2(self.igst + self.cgst + self.sgst)

    @property
    def heads(self):
        return (self.igst, self.cgst, self.sgst)


@dataclass
class Group:
    gid: str
    case: str
    cat: str
    sup: Sup | None
    books: list = field(default_factory=list)
    portal: list = field(default_factory=list)
    traits: list = field(default_factory=list)
    claim: tuple = (0.0, 0.0, 0.0)
    bucket: str = "none"
    blocked: str = ""
    exception: bool = False
    lookalike: str = ""
    excluded: str = ""
    note: str = ""
    master_elig: str = ""


# ── the generator ─────────────────────────────────────────────────────────────────────────────────────────


class Gen:
    def __init__(self, prof: Profile, seed: int, scale: float = 1.0, noise_scale: float | None = None):
        self.p = prof
        self.rng = random.Random(f"taxmind-ca-{seed}-{prof.key}")
        self.scale = scale
        self.noise_scale = scale if noise_scale is None else noise_scale
        rng = self.rng
        self.client_pan = rand_pan(rng, "F" if "LLP" in prof.client else "C", prof.client[0].upper())
        self.client_gstin = make_gstin(prof.state, self.client_pan)
        self.branch_gstins = [make_gstin(s, self.client_pan) for s in prof.branches]
        self.sups: dict[str, list[Sup]] = {}
        self.all_sups: list[Sup] = []
        self.groups: list[Group] = []
        self.legal_used: set = set()
        self.vchr = 2000 + rng.randint(0, 300)
        self.dn_vchr = 10 + rng.randint(0, 5)
        self.sup_vdate: dict = {}

    # ---- suppliers ---------------------------------------------------------------------------------------
    def _company_name(self, nouns, entity):
        rng = self.rng
        for _ in range(200):
            noun = rng.choice(nouns)
            a = rng.choice(NAME_A)
            if "{A}" in noun:
                base = noun.replace("{A}", a)
            elif noun.startswith("&"):
                base = f"{rng.choice(LAST)} {noun}"
            elif noun == "Advocate":
                base = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            elif noun == "":
                base = f"{rng.choice(LAST)} {rng.choice(FIRST)} {rng.choice(FIRST)}"
            else:
                base = f"{a} {noun}"
            if entity == "C" and not any(w in base for w in ("LLP", "Ltd", "Co")):
                legal = base + rng.choice([" Private Limited", " Private Limited", " Limited"] +
                                          ([] if "India" in base else [" India Private Limited"]))
            elif entity == "F" and not any(w in base for w in ("LLP", "& Co", "& Associates")):
                legal = base + rng.choice(["", " LLP", " & Co"])
            else:
                legal = base
            if legal.upper() not in self.legal_used:
                self.legal_used.add(legal.upper())
                return legal
        return legal + f" {rng.randint(2, 99)}"

    def _books_name(self, legal: str, proprietor_trade: str = "") -> str:
        rng = self.rng
        n = proprietor_trade or legal
        n = n.replace(" India Private Limited", " India Pvt Ltd").replace(" Private Limited",
                                                                            rng.choice([" Pvt Ltd", " Pvt. Ltd.", " (P) Ltd", " Private Ltd", " Pvt Ltd"]))
        n = n.replace(" Limited", rng.choice([" Ltd", " Limited", " Ltd."]))
        if rng.random() < 0.04:                                   # keying typo in the ledger name
            w = n.split()
            i = rng.randrange(len(w))
            if len(w[i]) > 4:
                j = rng.randrange(1, len(w[i]) - 2)
                w[i] = w[i][:j] + w[i][j + 1] + w[i][j] + w[i][j + 2:]
            n = " ".join(w)
        if rng.random() < 0.06:
            n = "M/s " + n
        if rng.random() < 0.1:
            n = n.upper()
        r = rng.random()
        if r < 0.1:
            n += "\t\t\n"
        elif r < 0.14:
            n += "\n"
        elif r < 0.16:
            n += "_x000D_\n"
        elif r < 0.18:
            n += "\t"
        return n

    def new_sup(self, cat: Cat | None, catkey: str, *, state=None, nouns=None, entity=None, rates=None,
                activity=None, elig=None, in_master=True, styles=None, einv=0.6, registered=True) -> Sup:
        rng = self.rng
        entity = entity or (cat.entity if cat else "C")
        nouns = nouns or (cat.nouns if cat else ("Industries",))
        if state is None:
            inter = cat.inter if cat else 0.3
            state = self.p.state if rng.random() > inter else rng.choice(
                ["24", "29", "33", "07", "06", "09", "36", "08", "23", "19", "03", "22"])
        legal = self._company_name(nouns, entity)
        trade = ""
        if entity == "P" and registered and not legal.endswith(("Enterprises", "Traders")) and rng.random() < 0.5:
            # proprietor: 2B shows the owner's legal name, books show the trade name
            trade = legal
            legal = f"{rng.choice(LAST)} {rng.choice(FIRST)} {rng.choice(FIRST)}"
        initial = (legal.split()[0][0] if entity == "P" else legal[0]).upper()
        if not initial.isalpha():
            initial = "A"
        pan = rand_pan(rng, entity, initial)
        g = make_gstin(state, pan) if registered else ""
        words = [w for w in re.findall(r"[A-Za-z]+", trade or legal) if w[0].isupper()]
        prefix = "".join(w[0] for w in words[:3]).upper() or "INV"
        styles = styles or (cat.styles if cat else (0, 1, 3, 4, 5, 7, 8, 9))
        act = activity or (rng.choice(cat.activity) if cat else "#N/A")
        el = elig or (cat.elig if cat else "#N/A")
        if el not in ("#N/A",):
            el = rng.choice([el, el, el.upper(), el.lower(), el.capitalize()])
        s = Sup(sid=len(self.all_sups) + 1, cat=catkey, gstin=g, pan=pan, legal=legal.upper() if rng.random() < 0.85 else legal,
                books_name=self._books_name(legal, trade), style=rng.choice(styles), prefix=prefix,
                seq=rng.randint(5, 900), rate=rng.choice(rates or (cat.rates if cat else (18,))),
                pan_in_books=rng.random() < 0.67, gstin_in_books=registered and rng.random() > 0.05,
                in_master=in_master and rng.random() < 0.9, master_activity=act, master_elig=el,
                einv=("Yes" if rng.random() < einv else rng.choice(["No", None])), registered=registered,
                city3=rng.choice(CITY3.get(state, ["HO"])))
        if registered and not s.gstin_in_books and in_master:
            s.in_master = True          # GSTIN missing in the ledger, but the firm's vendor master has it
        if not s.in_master:
            s.master_activity, s.master_elig = "#N/A", "#N/A"
        if trade:
            s.books_name = self._books_name(trade)
        self.all_sups.append(s)
        self.sups.setdefault(catkey, []).append(s)
        return s

    def sup_for(self, catkey: str) -> Sup:
        cat = LIB[catkey]
        pool = self.sups.setdefault(catkey, [])
        n_target = {"car_lease": 1, "paint_civil": 1, "peb": 2, "canteen_stat": 1, "health_ins": 1, "club": 1,
                    "visa": 1, "forklift_lease": 1, "security": 2, "staff_bus": 2, "md_car": 1, "csr": 1,
                    "cars_oem": 3, "electricity": 1, "import_saas": 1}.get(catkey)
        if n_target is None:
            n_target = max(2, int(len(pool) < 3) + int(6 * self.scale ** 0.5) + (12 if catkey in ("raw_material", "trade_goods", "food_provisions") else 0))
        if len(pool) < n_target and (not pool or self.rng.random() < 0.35):
            kind_entity = {"rent_unreg": "P", "advocate_rcm": "P"}.get(catkey)
            reg = cat.kind not in ("unreg", "rcm_unreg")
            return self.new_sup(cat, catkey, entity=kind_entity, registered=reg, einv=cat.einv,
                                state=self.p.state if catkey in ("rent_unreg", "diesel", "electricity", "vegetables") else None)
        weights = [1.0 / (i + 1) ** 0.8 for i in range(len(pool))]          # a few suppliers dominate
        return self.rng.choices(pool, weights=weights)[0]

    # ---- documents -----------------------------------------------------------------------------------------
    def inv_no(self, s: Sup, d: date) -> str:
        s.seq += self.rng.randint(1, 3)
        n = s.seq
        st = s.style
        if st == 0:
            no = f"{s.prefix}/{fy_short(d)}/{n:03d}"
        elif st == 1:
            no = f"{s.prefix}-{n}"
        elif st == 2:
            no = str(n)
        elif st == 3:
            no = f"{fy_long(d)}/{n:04d}"
        elif st == 4:
            no = f"{s.prefix}{n:05d}"
        elif st == 5:
            no = f"{n}/{fy_long(d)}"
        elif st == 6:
            no = f"{d.year % 100}{s.sid % 10}{n:07d}"
        elif st == 7:
            no = f"{s.prefix}/{s.city3}/{fy_compact(d)}/{n}"
        elif st == 8:
            no = f"{fy_short(d)}/{s.city3}/{n}"
        elif st == 9:
            no = f"{s.prefix}{n:03d}/{fy_long(d)}"
        elif st == 10:      # leasing / car hire: branch + month + running no.
            no = f"{s.prefix[:2]}{STATE_ALPHA.get(s.gstin[:2], 'MH')}{d:%m%y}{n:07d}"
        else:               # airline style
            no = f"{STATE_ALPHA.get(s.gstin[:2], 'MH')}{d:%y%m}{self.rng.choice(['AA', 'AB', 'BK', 'CX'])}{n:05d}"
        s.used.add(no)
        return no

    def heads(self, gstin, taxable, rate, inter=None):
        intra = gstin[:2] == self.p.state if inter is None else not inter
        t = taxable * rate / 100
        if intra:
            h = r2(t / 2)
            return 0.0, h, h
        return r2(t), 0.0, 0.0

    def amount(self, cat_or_med, sigma=None):
        if isinstance(cat_or_med, Cat):
            med, sigma = cat_or_med.median, cat_or_med.sigma
        else:
            med = cat_or_med
        x = self.rng.lognormvariate(0, sigma) * med
        x = min(max(x, 120), 9_000_000)
        return float(round(x)) if self.rng.random() < 0.8 else r2(x)

    def bill(self, s: Sup, d: date, taxable=None, rate=None, cat: Cat | None = None, gstin=None, typ="INV") -> Bill:
        rate = rate if rate is not None else (self.rng.choice(cat.rates) if cat and len(cat.rates) > 1 and self.rng.random() < 0.3 else s.rate)
        taxable = taxable if taxable is not None else self.amount(cat if cat else 25000, None if cat else 1.0)
        g = gstin or s.gstin
        ig, cg, sg = self.heads(g, taxable, rate) if g else self.heads(self.client_gstin, taxable, rate)
        return Bill(s, g, self.inv_no(s, d), d, taxable, ig, cg, sg, typ=typ, rate=rate)

    # ---- 2B rows ---------------------------------------------------------------------------------------------
    def prow(self, b: Bill, period: str, *, typ=None, itcavl="Yes", rsn="", sup_period=None, filing=None,
             heads=None, taxable=None, rcm=False, amends=None) -> dict:
        rng = self.rng
        typ = typ or {"INV": "Regular", "CN": "Credit", "DN": "Debit"}[b.typ]
        ig, cg, sg = heads if heads is not None else b.heads
        tx = b.taxable if taxable is None else taxable
        sign = -1 if typ == "Credit" else 1
        sup_period = sup_period or per_of(b.dt) if per_of(b.dt) in (period, per_add(period, -1)) else sup_period or period
        if filing is None:
            if sup_period == period:
                nxt = per_first(per_add(period, 1))
                filing = datetime(nxt.year, nxt.month, rng.choice([7, 8, 9, 10, 10, 10, 10, 11, 11, 11, 13]))
            else:
                cur = per_first(period)
                filing = datetime(cur.year, cur.month, rng.choice([12, 13, 13, 14]))
        tot = r2(ig + cg + sg)
        val = r2(tx + tot)
        row = {"Period": month_full(period), "GSTIN of supplier": b.gstin, "Trade/Legal name": b.sup.legal,
               "POS": f"{self.p.state}-{STATE_NAMES[self.p.state]}", "Invoice Type": typ,
               "Reverse Charge": "Yes" if rcm else "No", "Invoice No": b.no,
               "Invoice Date": datetime(b.dt.year, b.dt.month, b.dt.day),
               "Invoice Value": _num(sign * val), "Taxable Value": _num(sign * tx), "Tax Rate": 0,
               "IGST": _num(sign * ig), "CGST": _num(sign * cg), "SGST": _num(sign * sg), "Total Tax": _num(sign * tot),
               "Cess": 0, "GSTR-1/5 Filling Period": month_full(sup_period), "GSTR-1/5 Filling Date": filing,
               "ITC Availibility": itcavl, "E-Invoice Applicable": b.sup.einv, "Lookup": "#N/A", "Remark": None,
               "Activity": b.sup.master_activity, "ITC ELIGIBLITY": b.sup.master_elig}
        if amends:
            row["Period"] = month_abbr(amends["period"])
            row["GSTR-1/5 Filling Period"] = month_full(amends["period"])
            row["Invoice Value"] = row["Taxable Value"] = None
            row["GSTR-1/5 Filling Date"] = None
        meta = {"period": period, "bill": b, "typ": {"Regular": "INV", "Credit": "CN", "Debit": "DN", "B2BA": "INV"}[typ],
                "itcavl": itcavl == "Yes", "rsn": rsn, "rcm": rcm, "heads": (ig, cg, sg), "taxable": tx,
                "sup_period": sup_period, "amends": amends, "filing": filing}
        return {"v": row, "m": meta}

    # ---- books rows ------------------------------------------------------------------------------------------
    def _fill(self, cat: Cat | None, b: Bill | None) -> dict:
        rng = self.rng
        d = b.dt if b else per_first(RETURN)
        svc = per_add(per_of(d), -rng.choice([0, 0, 1]))
        st = self.p.state
        p1, p2 = rng.choice(FIRST), rng.choice(LAST)
        c1, c2 = rng.sample(CITIES.get(st, ["Pune"]) + ["Bengaluru", "Chennai", "Hosur", "Gurugram"], 2)
        return {"item": rng.choice(cat.items) if cat else "goods", "project": rng.choice(PROJECT),
                "project_c": rng.choice(["NH-160 bridge package", "MIDC water pipeline Phase 3", "Hospital building, Nashik",
                                         "Residential tower B, Wakad", "Warehouse project, Bhiwandi"]),
                "site": rng.choice(["R&D Centre, Chakan", "Supa MIDC plant", "Head Office, Pune", "Site office"]),
                "shop": rng.choice(SHOP), "month": f"{calendar.month_abbr[int(svc[:2])]} {svc[2:]}",
                "person": f"{p1} {p2}", "person_up": f"{p1} {p2}".upper(), "city": c1, "city2": c2,
                "n": rng.randint(2, 48), "range": f"{rng.randint(1, 12)} to {rng.randint(13, 28)} {d:%b} {d.year}",
                "event": rng.choice(["dealers' meet", "board meeting", "safety week", "plant visit by customer",
                                     "training programme", "annual day"]),
                "area": rng.choice(["boundary wall", "admin building", "internal roads and drains", "paint shop building",
                                    "canteen building", "security cabin and gate", "utility building"]),
                "veh": f"MH-{rng.randint(10, 50)}-{rng.choice(string.ascii_uppercase)}{rng.choice(string.ascii_uppercase)}-{rng.randint(1000, 9999)}",
                "country": rng.choice(["China", "Germany", "Japan", "Korea"]), "price": f"{rng.uniform(88, 96):.2f}",
                "rent": f"{rng.randint(20, 90) * 1000:,}", "po": f"{rng.randint(20, 900) * 1000:,}",
                "cpv": rng.randint(40, 4000), "appl": rng.choice(["12M bus", "45HP tractor", "proto tractors"]),
                "other": f"{rng.choice(NAME_A)} {rng.choice(['Fasteners', 'Forgings', 'Polymers'])}",
                "model": rng.choice(["compact SUV ZX", "sedan LX", "hatchback VX", "MUV 7-seater"]),
                "chassis": "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(10))}

    def narration(self, cat: Cat | None, b: Bill | None, no_txt, dt: date | None, body: str | None = None) -> str:
        rng = self.rng
        if body is None:
            body = rng.choice(cat.bodies).format(**self._fill(cat, b)) if cat else "Being expenses booked"
        if rng.random() < 0.1:
            body = body.replace(" ", "  ", 1)
        if no_txt is None:
            return body + rng.choice(["", "\t\n", "\n"])
        sep = rng.choice([", ", " , ", " - ", ", ", ",  ", " "])
        if dt is None:
            return body + sep + rng.choice(REFS_NODATE).format(no=no_txt)
        return body + sep + rng.choice(REFS).format(no=no_txt, dt=narr_date(dt, rng))

    def brow(self, g: Group, b: Bill, vdate: date, *, no="__bill__", gstin="__bill__", taxable=None, heads=None,
             narr=None, narr_no="__bill__", narr_dt="__bill__", vtype="Journal", gross=None, address=None,
             cat=None, inflate=None, igst_none=False, sgst_none=False, int_no=None) -> dict:
        rng = self.rng
        s = b.sup
        cat = cat or LIB.get(g.cat)
        traits = []
        g_cell = (b.gstin if s.gstin_in_books else None) if gstin == "__bill__" else gstin
        if g_cell is None:
            traits.append("gstin_blank")
        shown_no = b.no if no == "__bill__" else no
        if narr_no == "__bill__":
            narr_no = (b.no or None) if no is None else shown_no
        inv_dt = b.dt if narr_dt == "__bill__" else narr_dt
        if no is None:
            traits.append("invno_blank")
        cell_no = shown_no
        if cell_no is not None and re.fullmatch(r"\d{1,12}", str(cell_no)) and (int_no if int_no is not None else rng.random() < 0.7):
            cell_no = int(cell_no)
            traits.append("invno_int")
        ig, cg, sg = heads if heads is not None else b.heads
        tx = b.taxable if taxable is None else taxable
        if inflate is None:
            inflate = cat is not None and cat.inflate and rng.random() < cat.inflate and taxable is None
        if inflate:
            tx = float(round(tx * rng.choice([1.2, 1.1, 1.2])))
            traits.append("taxable_inflated")
        sign = -1 if vtype == "Debit Note" else 1
        tot = r2(ig + cg + sg)
        if narr is None:
            narr = self.narration(cat, b, narr_no, inv_dt)
        if inv_dt is None or "dtd -" in narr or narr_no is None:
            traits.append("no_invoice_date")
        else:
            traits.append("date_only_in_narration")
        if gross is None:
            base = (b.taxable if taxable is None else taxable) + tot    # what is payable, not the 'Taxable' column
            r = rng.random()
            if vtype == "Debit Note":
                gross = round(base - tx * rng.choice([0, 0.02, 0.01]))
            elif r < 0.5 and cat is not None and cat.key not in ("trade_goods", "food_provisions"):
                gross = round(base - tx * rng.choice([0.01, 0.02, 0.1, 0.02]))                       # TDS
                traits.append("gross_net")
            elif r < 0.6 and tx > 200000:
                ret = round(tx * rng.choice([0.05, 0.1]))
                gross = round(base - ret)
                narr = narr.rstrip("\n\t") + f", Retention of Rs {ret}"
                traits.append("gross_net")
            elif r < 0.66 and tx > 200000:
                gross = round(base - 0.9 * tx)
                narr = narr.rstrip("\n\t") + f" Less: 90% basic paid against FRN-{rng.randint(100, 2400)}"
                traits.append("gross_net")
            else:
                gross = round(base)
        if s.books_name != s.books_name.strip() or s.books_name.startswith("M/s"):
            traits.append("name_junk")
        if _simple(s.books_name) != _simple(s.legal):
            traits.append("name_differs")
        if not s.pan_in_books or g_cell is None:
            traits.append("pan_blank")
        row = {"Date": datetime(vdate.year, vdate.month, vdate.day), "Particulars": s.books_name,
               "Address": address if address is not None else (
                   f"Plot No. {rng.randint(1, 300)}, MIDC {rng.choice(['Chakan', 'Bhosari', 'Waluj', 'Ambad', 'Supa'])}, "
                   f"{rng.choice(CITIES['27'])} - 4{rng.randint(10000, 49999)}" if rng.random() < 0.12 else None),
               "Voucher Type": vtype, "Voucher No.": None, "Voucher Ref. No.": "#N/A", "Voucher Ref. Date": None,
               "GSTIN/UIN": g_cell, "Sales Tax No.": None, "Service Tax No.": None,
               "PAN No.": s.pan if (s.pan_in_books and g_cell) else None, "CST No.": None, "Invoice No": cell_no,
               "Narration": narr, "Gross Total": _num(gross), "Taxable": _num(sign * tx),
               "IGST": None if igst_none else _num(sign * ig), "CGST": _num(sign * cg),
               "SGST": None if sgst_none else _num(sign * sg), "Total Tax": _num(sign * tot),
               "Rate": r2(tot / tx * 100) if tx else ("#DIV/0!" if rng.random() < 0.6 else 0),
               "Lookup": "#N/A", "Remark": None,
               "Activity": s.master_activity if g_cell else "#N/A", "ITC ELIGIBLITY": s.master_elig if g_cell else "#N/A"}
        if isinstance(row["Rate"], float) and row["Rate"] == int(row["Rate"]):
            row["Rate"] = int(row["Rate"])
        if igst_none or sgst_none:
            traits.append("sgst_blank" if sgst_none else "prev_month_voucher")
        g.traits.extend(t for t in traits if t not in g.traits)
        s.in_books = True
        r = {"v": row, "m": {"vdate": vdate, "bill": b, "inv_date": b.dt, "tax": sign * tot, "sup": s}}
        g.books.append(r)
        return r

    # ---- groups / cases ---------------------------------------------------------------------------------------
    def group(self, case, catkey, sup) -> Group:
        g = Group(gid=f"G{len(self.groups) + 1:04d}", case=case, cat=catkey, sup=sup)
        cat = LIB.get(catkey)
        if cat:
            g.blocked, g.exception, g.lookalike, g.note = cat.blocked, cat.exception, cat.lookalike, cat.note
        if sup:
            g.master_elig = sup.master_elig
        self.groups.append(g)
        return g

    def vdate_for(self, inv: date) -> date:
        lo = max(inv, per_first(RETURN))
        hi = per_last(RETURN)
        d = lo + timedelta(days=self.rng.randint(0, 12))
        return min(d, hi)

    def inv_date(self, case) -> date:
        rng = self.rng
        jun = per_first(RETURN)
        if case in ("earlier_2b_reclaim",):
            return date(2026, 3, 25) + timedelta(days=rng.randint(0, 67))
        if case in ("prior_fy_current_2b", "prior_fy_not_in_2b"):
            return date(2025, 10, 1) + timedelta(days=rng.randint(0, 181))
        if case == "books_only_not_uploaded":
            return date(2026, 4, 1) + timedelta(days=rng.randint(0, 85))
        if case == "late_filer_next_month":
            return jun + timedelta(days=rng.randint(0, 27))
        return jun + timedelta(days=rng.randint(0, 24)) if rng.random() < 0.85 else date(2026, 5, 20) + timedelta(days=rng.randint(0, 11))

    @staticmethod
    def claim_of(heads, sign=1):
        return tuple(r2(sign * h) for h in heads)

    def make_case(self, case: str, catkey: str):
        rng = self.rng
        cat = LIB[catkey]
        if case == "other_gstin_same_pan":
            s = self.sup_with_alt(catkey)
        else:
            s = self.sup_for(catkey)
        if cat.kind != "gst":
            return self.make_special(cat, catkey, s)
        if case in ("other_gstin_same_pan", "wrong_head") and not s.gstin:
            case = "exact"
        if case == "billed_to_other_branch" and not self.branch_gstins:
            case = "books_only_not_uploaded"
        d = self.inv_date(case)
        b = self.bill(s, d, cat=cat)
        if catkey == "car_lease" or catkey == "forklift_lease" or (cat.recurring and rng.random() < 0.6):
            b.dt = d = per_first(per_of(d)) if case != "earlier_2b_reclaim" else d
        # vendor master / ledger messiness turns clean matches into their own cases
        if case in ("exact", "round_off") and not s.gstin_in_books:
            case = "gstin_missing_name"
        elif case == "exact" and rng.random() < 0.045:
            case = "invno_missing_narration"
        g = self.group(case, catkey, s)
        jun = RETURN
        vd = self.vdate_for(d)
        if cat.recurring or rng.random() < 0.3:
            fixed = self.sup_vdate.setdefault(s.sid, vd)
            vd = fixed if fixed >= d else vd
        heads = b.heads

        def cur(**kw):
            g.portal.append(self.prow(b, jun, **kw))

        if case in ("exact", "gstin_missing_name", "invno_missing_narration", "prior_fy_current_2b"):
            if case == "prior_fy_current_2b":
                g.traits.append("prior_fy")
                g.traits.append("late_supplier_filing")
                cur(sup_period=rng.choice(["032026", jun]))
            else:
                cur()
            self.brow(g, b, vd, no=None if case == "invno_missing_narration" else "__bill__")
            g.claim, g.bucket = heads, "4A5_2b"
        elif case == "round_off":
            bh = tuple(float(round(h)) if h else 0.0 for h in heads)
            if bh == heads:
                bh = tuple(r2(h + 0.4) if h else 0.0 for h in heads)
            cur()
            self.brow(g, b, vd, heads=bh, taxable=b.taxable if rng.random() < 0.5 else float(round(b.taxable + 0.4)))
            g.claim, g.bucket = _min_heads(heads, bh), "4A5_2b"
        elif case == "round_1to6":
            k = next((i for i, h in enumerate(heads) if h), 0)
            bh = list(heads)
            bh[k] = r2(bh[k] + rng.choice([-1, 1]) * rng.randint(2, 6))
            cur()
            self.brow(g, b, vd, heads=tuple(bh))
            g.claim, g.bucket = _min_heads(heads, tuple(bh)), "4A5_2b"
        elif case == "taxable_differs":
            cur()
            self.brow(g, b, vd, taxable=float(round(b.taxable * rng.choice([1.1, 1.2, 1.15]) + rng.randint(500, 5000))))
            if "taxable_inflated" not in g.traits:
                g.traits.append("taxable_inflated")
            g.claim, g.bucket = heads, "4A5_2b"
        elif case in ("amount_less_in_2b", "amount_more_in_2b"):
            if rng.random() < 0.4:                           # books keyed the wrong rate on one head
                g.traits.append("rate_keying_error")
                f = rng.choice([12 / 18, 28 / 18, 5 / 18]) if case == "amount_less_in_2b" else rng.choice([12 / 18, 5 / 18])
                bh = tuple(r2(h * f) if h else 0.0 for h in heads)
                if case == "amount_less_in_2b":             # books > 2B
                    if sum(bh) < sum(heads):
                        bh = tuple(r2(h * 28 / 18) if h else 0.0 for h in heads)
                    cur()
                    self.brow(g, b, vd, heads=bh)
                else:
                    cur()
                    self.brow(g, b, vd, heads=bh)
                g.claim = _min_heads(heads, bh)
            else:
                f = rng.uniform(0.08, 0.35)
                pt = r2(b.taxable * (1 - f if case == "amount_less_in_2b" else 1 + f))
                ph = self.heads(b.gstin, pt, b.rate)
                cur(heads=ph, taxable=pt)
                self.brow(g, b, vd)
                g.claim = _min_heads(heads, ph)
            g.bucket = "4A5_2b"
        elif case == "invno_format":
            cur()
            self.brow(g, b, vd, no=self.books_variant(b), narr_no="__bill__")
            g.books[-1]["v"]["Narration"] = self.narration(cat, b, g.books[-1]["v"]["Invoice No"], b.dt)
            g.claim, g.bucket = heads, "4A5_2b"
        elif case == "invno_typo":
            t = self.typo(b)
            cur()
            self.brow(g, b, vd, no=t, narr_no=t)
            g.claim, g.bucket = heads, "4A5_2b"
        elif case == "date_diff":
            wrong = b.dt + timedelta(days=rng.choice([-5, -3, -2, 1, 2, 4, 6]))
            if b.dt.day <= 12 and b.dt.day != b.dt.month and rng.random() < 0.4:
                wrong = date(b.dt.year, b.dt.day, b.dt.month)        # dd/mm swapped
            cur()
            self.brow(g, b, vd, narr_dt=wrong)
            g.claim, g.bucket = heads, "4A5_2b"
            g.note = f"narration date {wrong.isoformat()} vs 2B {b.dt.isoformat()}"
        elif case == "split":
            if rng.random() < 0.6:     # one books line for 2-3 invoices
                parts = [b] + [self.bill(s, min(b.dt + timedelta(days=k + 1), per_last(jun)), cat=cat, rate=b.rate)
                               for k in range(rng.choice([1, 2]))]
                tot = Bill(s, b.gstin, parts[0].no, b.dt, r2(sum(p.taxable for p in parts)),
                           r2(sum(p.igst for p in parts)), r2(sum(p.cgst for p in parts)), r2(sum(p.sgst for p in parts)),
                           rate=b.rate)
                for p in parts:
                    g.portal.append(self.prow(p, jun))
                shown = rng.choice([", ".join(p.no for p in parts), f"{parts[0].no} to {parts[-1].no}", parts[0].no])
                self.brow(g, tot, self.vdate_for(parts[-1].dt), no=shown, narr_no=shown)
                g.claim = tot.heads
            else:                      # material + installation booked separately for one invoice
                f = rng.uniform(0.55, 0.85)
                t1 = r2(b.taxable * f)
                h1 = self.heads(b.gstin, t1, b.rate)
                h2 = tuple(r2(x - y) for x, y in zip(heads, h1))
                cur()
                self.brow(g, b, vd, taxable=t1, heads=h1)
                self.brow(g, b, vd, taxable=r2(b.taxable - t1), heads=h2)
                g.claim = heads
            g.bucket = "4A5_2b"
        elif case == "wrong_head":
            t = b.tax
            ph = (0.0, r2(t / 2), r2(t / 2)) if b.igst else (t, 0.0, 0.0)
            cur(heads=ph)
            self.brow(g, b, vd)
            g.claim, g.bucket = (0.0, 0.0, 0.0), "none"
            g.note = "held until the supplier amends (GSTR-1A) or books are corrected"
        elif case == "other_gstin_same_pan":
            alt = Bill(s, s.alt_gstin, b.no, b.dt, b.taxable, *b.heads, rate=b.rate)
            g.portal.append(self.prow(alt, jun))
            self.brow(g, b, vd, gstin=b.gstin)
            g.claim, g.bucket = (0.0, 0.0, 0.0), "none"
            g.note = "held: check the GSTIN printed on the invoice"
        elif case == "duplicate_in_books":
            cur()
            r1 = self.brow(g, b, vd)
            r2_ = self.brow(g, b, vd)
            r2_["v"] = dict(r1["v"])
            r2_["m"] = dict(r1["m"])
            g.claim, g.bucket = heads, "4A5_2b"
        elif case == "booked_without_gst":
            cur(sup_period=per_add(jun, -1) if rng.random() < 0.5 else None)
            self.brow(g, b, vd, taxable=float(round(b.taxable + b.tax)), heads=(0.0, 0.0, 0.0))
            g.claim, g.bucket = (0.0, 0.0, 0.0), "none"
            g.note = "GST was booked into cost; 2B ITC reversed (4B2)"
        elif case == "earlier_2b_reclaim":
            per = per_of(d) if per_of(d) in MONTHS[:2] else MONTHS[0]
            if per_of(d) < "042026" and d.year == 2026 and d.month == 3:
                g.traits.append("prior_fy")
                g.traits.append("late_supplier_filing")
                g.portal.append(self.prow(b, per, sup_period="032026"))
            else:
                g.portal.append(self.prow(b, per))
            if rng.random() < 0.08:
                self.brow(g, b, vd, no=self.books_variant(b))
                g.traits.append("invno_format")
            else:
                self.brow(g, b, vd)
            g.claim, g.bucket = heads, "4A5_reclaim"
        elif case == "late_filer_next_month":
            nxt = per_add(jun, 1)
            g.portal.append(self.prow(b, nxt, sup_period=jun,
                                      filing=datetime(2026, 7, rng.randint(14, 30))))
            g.traits.append("late_supplier_filing")
            self.brow(g, b, vd)
        elif case == "prior_fy_not_in_2b":
            g.traits.append("prior_fy")
            self.brow(g, b, vd)
            g.note = "Sec 16(4) deadline 30-11-2026"
        elif case in ("books_only_not_uploaded",):
            self.brow(g, b, vd)
        elif case == "billed_to_other_branch":
            self.brow(g, b, vd, narr=self.narration(cat, b, b.no, b.dt) +
                      f" (bill addressed to {rng.choice(['Bengaluru', 'Delhi'])} branch)")
            g.note = "invoice billed to the client's other-state GSTIN; it is in that GSTIN's 2B"
        else:
            raise ValueError(case)
        if b.tax == 0 and g.bucket != "none":
            g.bucket = "none"
        if g.case == "exact" and "taxable_inflated" in g.traits:
            g.case = "taxable_differs"            # tax agrees; books 'Taxable' carries non-GST charges

    def sup_with_alt(self, catkey):
        s = self.sup_for(catkey)
        if not s.registered:
            return s
        if not s.alt_gstin:
            st = self.rng.choice([x for x in ("24", "29", "33", "06", "09") if x != s.gstin[:2]])
            s.alt_gstin = make_gstin(st, s.pan)
        return s

    def books_variant(self, b: Bill) -> str:
        no = b.no
        rng = self.rng
        opts = []
        opts.append(re.sub(r"[/\-]", "", no))
        stripped = re.sub(r"/?(20\d\d-\d\d|20\d\d-20\d\d|\d\d-\d\d)/?", "/", no).strip("/")
        stripped = re.sub(r"//+", "/", stripped)
        opts.append(stripped)
        if not re.search(r"\d\d-\d\d", no):
            opts.append(f"{no}/{fy_short(b.dt)}")
        m = re.search(r"(?:^|(?<=[^0-9]))0+(\d+)$", no)            # leading zeros of the serial: /045 -> /45
        if m:
            opts.append(no[:m.start()] + m.group(1))
        m = re.search(r"(?<=[^0-9\-])(\d{1,4})$", no)              # zero-padded serial (not an FY suffix)
        if m and not re.search(r"\d\d-\d\d$", no):
            opts.append(no[:m.start()] + m.group(1).zfill(5))
        opts.append(no.lower().replace("/", " / "))
        opts = [o for o in dict.fromkeys(opts) if o and o != no and o not in b.sup.used]
        return rng.choice(opts) if opts else no.replace("/", "-")

    def typo(self, b: Bill) -> str:
        """One keying error in the serial part (never in the FY part, never a +-3 neighbour, which would be
        indistinguishable from the supplier's next bill)."""
        rng = self.rng
        no = b.no
        fy = [m.span() for m in re.finditer(r"20\d\d-20\d\d|20\d\d-\d\d|\d\d-\d\d", no)]
        runs = [m for m in re.finditer(r"\d+", no) if not any(a <= m.start() < z for a, z in fy)
                and m.group() not in (fy_compact(b.dt),)]
        if not runs:
            return no + "1"
        run = runs[-1] if len(runs[-1].group()) >= 2 or len(runs) == 1 else max(runs, key=lambda m: len(m.group()))
        a, z = run.span()
        serial = run.group()
        for _ in range(40):
            ds = list(range(len(serial)))[-6:]
            i = rng.choice(ds)
            if rng.random() < 0.5 and i + 1 < len(serial) and serial[i] != serial[i + 1]:
                t = serial[:i] + serial[i + 1] + serial[i] + serial[i + 2:]
            else:
                t = serial[:i] + str((int(serial[i]) + rng.randint(1, 8)) % 10) + serial[i + 1:]
            if t == serial or (t[0] == "0" and serial[0] != "0") or abs(int(t) - int(serial)) <= 3:
                continue
            cand = no[:a] + t + no[z:]
            if cand not in b.sup.used:
                return cand
        return no[:a] + serial[::-1] + no[z:] if serial[::-1] != serial else no + "1"

    # ---- non-standard books rows ------------------------------------------------------------------------------
    def make_special(self, cat: Cat, catkey: str, s: Sup):
        rng = self.rng
        kind = cat.kind
        d = per_first(RETURN) + timedelta(days=rng.randint(0, 24)) if rng.random() < 0.6 else date(2026, 5, 1) + timedelta(days=rng.randint(0, 30))
        vd = self.vdate_for(d)
        if kind == "nongst":
            g = self.group("excluded_nongst", catkey, s)
            g.excluded = "non-GST / nil-rated supply"
            b = self.bill(s, d, cat=cat, rate=0)
            self.brow(g, b, vd)
        elif kind == "unreg":
            g = self.group("excluded_unregistered", catkey, s)
            g.excluded = "unregistered supplier, no GST charged"
            b = Bill(s, "", "", d, self.amount(cat), 0.0, 0.0, 0.0, rate=0)
            rent = b.taxable
            self.brow(g, b, vd, gstin=None, no=None, narr=cat.bodies[0].format(**{**self._fill(cat, b), "rent": f"{int(rent):,}"}) + "\t\n",
                      taxable=float(round(rent * 1.18)), gross=round(rent * 0.9), inflate=False)
        elif kind == "advance":
            sp = self.sup_for(rng.choice([k for k in self.p.cats if LIB[k].kind == "gst"]))
            g = self.group("excluded_advance", catkey, sp)
            g.excluded = "advance / proforma: no tax invoice yet"
            amt = self.amount(cat)
            b = Bill(sp, sp.gstin, "", d, 0.0, 0.0, 0.0, 0.0, rate=0)
            self.brow(g, b, vd, no=None, narr=self.narration(cat, b, None, None), taxable=0.0, gross=amt, inflate=False)
        elif kind == "provision":
            sp = self.sup_for(rng.choice([k for k in self.p.cats if LIB[k].kind == "gst" and LIB[k].recurring]
                                         or [k for k in self.p.cats if LIB[k].kind == "gst"]))
            g = self.group("excluded_provision", catkey, sp)
            g.excluded = "provision reversal: no invoice, no tax"
            amt = self.amount(cat)
            b = Bill(sp, sp.gstin, "", per_first(RETURN), amt, 0.0, 0.0, 0.0, rate=0)
            self.brow(g, b, per_first(RETURN), no=None, narr=self.narration(cat, b, None, None),
                      gross=round(amt * rng.choice([0.005, 0.01, 0.02, 0.05, 0.1])), inflate=False)
        elif kind == "rcm_gta":
            g = self.group("rcm", catkey, s)
            b = self.bill(s, per_first(RETURN) + timedelta(days=rng.randint(0, 24)), cat=cat, rate=5)
            b.rcm = True
            g.portal.append(self.prow(b, RETURN, rcm=True))
            self.brow(g, b, self.vdate_for(b.dt))
            g.claim, g.bucket = b.heads, "4A3_rcm"
        elif kind == "rcm_unreg":
            g = self.group("rcm", catkey, s)
            b = self.bill(s, d, cat=cat, rate=18, gstin=None)
            b.gstin = ""
            b.no = str(rng.randint(1, 60))
            if catkey == "import_saas":
                b.igst, b.cgst, b.sgst = r2(b.taxable * 0.18), 0.0, 0.0
            self.brow(g, b, vd, gstin=None)
            g.claim, g.bucket = b.heads, "4A3_rcm"
            g.note = "reverse charge; supplier unregistered / overseas, so not in 2B"
        else:
            raise ValueError(kind)

    def make_cn_cases(self):
        rng = self.rng
        gst_cats = [k for k in self.p.cats if LIB[k].kind == "gst" and not LIB[k].recurring] or list(self.p.cats)
        fixed = FIXED_COMMON
        for _ in range(self.n_fixed(fixed["books_cn_matched"])):
            ck = rng.choice(gst_cats)
            s = self.sup_for(ck)
            if not s.registered:
                continue
            g = self.group("books_cn_matched", ck, s)
            g.blocked, g.exception = "", False
            orig = self.bill(s, date(2026, 2, 1) + timedelta(days=rng.randint(0, 100)), cat=LIB[ck])
            cn = self.bill(s, per_first(RETURN) + timedelta(days=rng.randint(0, 20)), taxable=r2(orig.taxable * rng.uniform(0.2, 1)),
                           rate=orig.rate, typ="CN")
            cn.no = f"{fy_long(cn.dt)}/{rng.randint(1, 40):02d}" if rng.random() < 0.5 else f"CN/{fy_short(cn.dt)}/{rng.randint(1, 99):03d}"
            g.portal.append(self.prow(cn, RETURN))
            self.brow(g, cn, self.vdate_for(cn.dt), vtype="Debit Note", no=orig.no,
                      narr=f"Credit note  no {cn.no}, against invoice no {orig.no}")
            g.claim, g.bucket = self.claim_of(cn.heads, -1), "4A5_2b"
            g.note = f"Invoice No column holds the original invoice {orig.no}; CN no. only in narration"
        for _ in range(self.n_fixed(fixed["books_cn_no_ref"])):
            ck = rng.choice(gst_cats)
            s = self.new_sup(LIB[ck], ck, entity="P", state=self.p.state)
            if not s.books_name.strip().endswith(("Enterprises", "Traders")):
                s.books_name = f"{rng.choice(NAME_A).upper()} ENTERPRISES"
            s.legal = f"{rng.choice(LAST)} {rng.choice(FIRST)} {rng.choice(FIRST)}".upper()
            g = self.group("books_cn_no_ref", ck, s)
            g.blocked = ""
            cn = self.bill(s, per_first(RETURN) + timedelta(days=rng.randint(0, 25)), taxable=float(rng.randint(5, 60) * 210),
                           typ="CN")
            cn.no = f"CN/{fy_short(cn.dt)}/{rng.randint(1, 9):03d}"
            g.portal.append(self.prow(cn, RETURN))
            self.brow(g, cn, self.vdate_for(cn.dt), vtype="Debit Note", no=None, gstin=None, narr="Purchase Return")
            g.claim, g.bucket = self.claim_of(cn.heads, -1), "4A5_2b"
        for _ in range(self.n_fixed(fixed["books_cn_not_in_2b"])):
            ck = rng.choice(gst_cats)
            s = self.sup_for(ck)
            if not s.registered:
                continue
            g = self.group("books_cn_not_in_2b", ck, s)
            g.blocked = ""
            orig = self.bill(s, date(2026, 4, 1) + timedelta(days=rng.randint(0, 60)), cat=LIB[ck])
            cn = Bill(s, s.gstin, "", per_first(RETURN) + timedelta(days=rng.randint(0, 20)),
                      r2(orig.taxable * 0.1), *(r2(h * 0.1) for h in orig.heads), typ="CN", rate=orig.rate)
            self.brow(g, cn, self.vdate_for(cn.dt), vtype="Debit Note", no=orig.no, narr_no=None,
                      narr=f"Rate difference debit note against invoice no {orig.no} - supplier credit note awaited")
            g.claim, g.bucket = self.claim_of(cn.heads, -1), "4A5_2b_cn_books"
            g.note = "books reduce ITC; supplier has not reported the credit note"

    def n_fixed(self, n):
        return max(1, round(n * max(1.0, self.scale ** 0.5)))

    def make_prev_month_tail(self):
        """Previous-month vouchers entered late and appended at the end: GSTIN/PAN/Invoice No blank, IGST blank."""
        rng = self.rng
        cands = [g for g in self.groups if g.case in ("earlier_2b_reclaim", "books_only_not_uploaded")
                 and len(g.books) == 1 and g.books[0]["m"]["bill"].dt < date(2026, 5, 20)]
        rng.shuffle(cands)
        for g in cands[:self.n_fixed(6)]:
            r = g.books[0]
            b = r["m"]["bill"]
            vd = max(b.dt, date(2026, 5, 1)) + timedelta(days=rng.randint(0, 9))
            v = r["v"]
            v["Date"] = datetime(vd.year, vd.month, vd.day)
            v["GSTIN/UIN"] = v["PAN No."] = None
            v["Invoice No"] = ""
            v["Address"] = None
            if not v["IGST"]:
                v["IGST"] = None
            if not v["Narration"].rstrip().endswith("_x000D_"):
                v["Narration"] = v["Narration"].rstrip("\n") + "\t_x000D_\n"
            r["m"]["vdate"], r["m"]["tail"] = vd, True
            for t in ("prev_month_voucher", "gstin_blank", "invno_blank", "pan_blank"):
                if t not in g.traits:
                    g.traits.append(t)

    def make_rectifications(self):
        rng = self.rng
        gst_groups = [g for g in self.groups if g.books and g.sup and g.sup.registered and g.case in ("exact", "earlier_2b_reclaim")]
        for i in range(self.n_fixed(FIXED_COMMON["rectification"])):
            src = rng.choice(gst_groups)
            s = src.sup
            g = self.group("rectification", src.cat, s)
            g.blocked, g.exception = "", False
            g.excluded = "rectification of an earlier booking"
            b0 = src.books[0]["m"]["bill"]
            vd = date(2026, 5, rng.randint(4, 28)) if rng.random() < 0.6 else per_first(RETURN) + timedelta(days=rng.randint(0, 28))
            if i % 2 == 0:
                tx = float(rng.randint(150, 900))
                t = r2(tx * 0.18) if rng.random() < 0.5 else -float(rng.randint(20, 90))
                h = (t, 0.0, 0.0) if b0.igst else (0.0, abs(t) if t > 0 else t, 0.0)
                bb = Bill(s, s.gstin, "", vd, tx, *h)
                self.brow(g, bb, vd, gstin=None, no="", int_no=False,
                          narr=f"Excess booking now rectified aganist FRN {rng.randint(1500, 2400)}, for invoice no : {b0.no}",
                          heads=(-abs(h[0]), -abs(h[1]), 0.0), taxable=tx, igst_none=not b0.igst, sgst_none=True,
                          gross=round(tx * 1.18), inflate=False)
            else:
                bb = Bill(s, s.gstin, "", vd, 26.15, 0.0, 4.0, 4.0)
                self.brow(g, bb, vd, gstin=None, no="", int_no=False, igst_none=True, inflate=False, gross=27.15,
                          narr=f"Less booking made earlier, in {rng.choice(['March', 'April', 'May'])}, now rectified against FRN {rng.randint(1500, 2400)}")
            for r in g.books:
                r["m"]["tail"] = True

    # ---- 2B-only rows -------------------------------------------------------------------------------------------
    def noise_sups(self):
        """Suppliers that appear only in 2B (other registers): airlines with many state GSTINs, cab firms, hotels..."""
        rng = self.rng
        self.noise_pool: dict[str, list[Sup]] = {}
        airline_names = ["AEROLARK AVIATION LIMITED", "BLUEJAY AIRWAYS PRIVATE LIMITED", "NIMBUS AIR SERVICES LIMITED"]
        for kind, spec in NOISE.items():
            pool = []
            if kind == "airline":
                for nm in airline_names:
                    pan = rand_pan(rng, "C", nm[0])
                    for st in ("27", "24", "29", "07", "33", "36", "09", "22", "23"):
                        s = Sup(len(self.all_sups) + 1, "airline", make_gstin(st, pan), pan, nm, nm.title(), 11, "AL",
                                rng.randint(10000, 90000), 5, master_activity=spec["activity"],
                                master_elig=spec["elig"], einv=rng.choice(["Yes", "Yes", None]))
                        self.all_sups.append(s)
                        pool.append(s)
            else:
                n = {"car_hire": 3, "hotel": 10, "lease": 1, "courier": 2, "telecom": 2, "airport": 1}.get(kind, 0)
                if kind == "misc":
                    n = max(10, int(self.p.noise.get("misc", 0) / 3))
                for _ in range(n):
                    nouns = {"car_hire": ("Car Rentals", "Cabs"), "hotel": ("Hotel {A} Residency", "{A} Hospitality", "Hotel {A} Inn"),
                             "lease": ("Auto Lease",), "courier": ("Express Couriers",), "telecom": ("Telecom", "Broadband"),
                             "airport": ("Airport Services",),
                             "misc": ("Auto Components", "Engineering", "Industrial Supplies", "Electricals", "Tools",
                                      "Chemicals", "Safety Products", "Polymers", "Office Solutions")}[kind]
                    styles = {"car_hire": (10,), "lease": (10,), "courier": (6,), "telecom": (6,), "airport": (11,)}.get(kind)
                    s = self.new_sup(None, f"noise_{kind}", nouns=nouns, entity="C",
                                     state=self.p.state if kind in ("car_hire", "lease") else None,
                                     rates=spec["rates"], activity=spec["activity"], elig=spec["elig"], styles=styles,
                                     in_master=kind != "misc" or rng.random() < 0.8)
                    pool.append(s)
            self.noise_pool[kind] = pool
        # some of this register's own cab / hotel / lease suppliers also bill bills the register never carries
        for k in ("car_hire", "hotel_room", "car_lease"):
            for s in self.sups.get(k, []):
                self.noise_pool.setdefault({"car_hire": "car_hire", "hotel_room": "hotel", "car_lease": "lease"}[k], []).append(s)

    def noise_rows(self, period: str):
        rng = self.rng
        sc = self.noise_scale
        first, last = per_first(period), per_last(period)
        jun = period == RETURN

        def dt_in():
            if rng.random() < 0.07:                    # supplier's previous-month GSTR-1 filed late
                pp = per_add(period, -1)
                return per_first(pp) + timedelta(days=rng.randint(10, (per_last(pp) - per_first(pp)).days)), pp
            return first + timedelta(days=rng.randint(0, (last - first).days)), period

        def emit(case, s, b, sup_period, **kw):
            g = self.group(case if jun else "other_month_noise", s.cat, s)
            g.blocked = ""
            if jun and b.sup.master_elig.lower() == "no" and kind_of(s) in ("car_hire",):
                g.blocked = "motor_vehicle"
            g.portal.append(self.prow(b, period, sup_period=sup_period, **kw))
            r = g.portal[-1]["m"]
            if jun and r["itcavl"] and not r["rcm"] and r["typ"] == "CN":
                g.claim, g.bucket = self.claim_of(r["heads"], -1), "4A5_2b"   # auto-reduces 4A5
            return g

        def kind_of(s):
            return s.cat.replace("noise_", "")

        for kind, n in self.p.noise.items():
            pool = self.noise_pool.get(kind, [])
            if not pool:
                continue
            spec = NOISE[kind]
            n = int(round(n * sc * rng.uniform(0.85, 1.1)))
            if kind == "airline":
                w = [6 if s.legal.startswith("AERO") else 1.4 if s.legal.startswith("BLUE") else 0.8 for s in pool]
            else:
                w = [1.0 / (i + 1) ** 0.6 for i in range(len(pool))]
            for _ in range(n):
                s = rng.choices(pool, weights=w)[0]
                d, sp = dt_in()
                if kind == "lease":
                    d, sp = first, period
                b = self.bill(s, d, taxable=self.amount(spec["median"], spec["sigma"]), rate=rng.choice(spec["rates"]))
                if s.in_books:
                    case = "portal_only_known"
                else:
                    case = "portal_only_other_register" if s.in_master else "portal_only_unknown"
                if kind == "hotel" and self.p.branches and rng.random() < 0.2 and jun:
                    # out-of-state hotel charging its own state's CGST/SGST: ITC not available (PoS)
                    b.igst, b.cgst, b.sgst = 0.0, r2(b.taxable * b.rate / 200), r2(b.taxable * b.rate / 200)
                    emit("portal_itc_unavailable", s, b, sp, itcavl="No", rsn="P")
                    continue
                emit(case, s, b, sp)
        # unbooked bills from suppliers this register does carry
        books_sups = [s for k, v in self.sups.items() if LIB.get(k) and LIB[k].kind == "gst" for s in v if s.registered]
        for _ in range(int(round(self.p.known_extra * sc * rng.uniform(0.85, 1.1)))):
            if not books_sups:
                break
            s = rng.choice(books_sups)
            d, sp = dt_in()
            b = self.bill(s, d, cat=LIB.get(s.cat))
            emit("portal_only_known", s, b, sp)
        for _ in range(int(round(self.p.unknown * sc))):
            s = self.new_sup(None, "noise_unknown", nouns=("Trading Co", "Impex", "Enterprises", "Suppliers"), entity="F",
                             in_master=False)
            s.in_master, s.master_activity, s.master_elig = False, "#N/A", "#N/A"
            d, sp = dt_in()
            emit("portal_only_unknown", s, self.bill(s, d, taxable=self.amount(60000, 1.0)), sp)
        cn_pool = self.noise_pool.get("airline", []) + books_sups + self.noise_pool.get("misc", [])
        for i in range(int(round(self.p.cn * sc))):
            s = rng.choice(self.noise_pool["airline"]) if (self.noise_pool.get("airline") and i % 3 != 2) else rng.choice(cn_pool)
            d, sp = dt_in()
            b = self.bill(s, d, taxable=self.amount(5000 if s.cat == "airline" else 30000, 0.9), typ="CN")
            if s.style not in (11, 6, 10):
                b.no = f"CN/{fy_short(d)}/{rng.randint(1, 300):03d}"
            emit("portal_cn_not_booked", s, b, sp)
        dn_pool = self.noise_pool.get("airline", []) + self.noise_pool.get("airport", []) or books_sups
        for _ in range(int(round(self.p.dn * sc))):
            s = rng.choice(dn_pool)
            d, sp = dt_in()
            b = self.bill(s, d, taxable=float(rng.choice([237.14, 95, 2646, 6019, 41595])), rate=5, typ="DN")
            emit("portal_dn_not_booked", s, b, sp)
        if jun:
            for i in range(int(round(self.p.itcn * sc))):
                s = rng.choice(books_sups or self.all_sups)
                if i % 2 == 0:     # FY 2024-25 invoice uploaded now: Sec 16(4) time-barred
                    d = date(2024, 12, 1) + timedelta(days=rng.randint(0, 110))
                    b = self.bill(s, d, cat=LIB.get(s.cat))
                    emit("portal_itc_unavailable", s, b, "032025", itcavl="No", rsn="C")
                else:
                    d, sp = dt_in()
                    b = self.bill(s, d, cat=LIB.get(s.cat))
                    emit("portal_itc_unavailable", s, b, sp, itcavl="No", rsn="P")

    def make_b2ba(self):
        """Amendment in the Jun 2B of an invoice that sat in the May 2B (its books entry was in May)."""
        rng = self.rng
        books_sups = [s for k, v in self.sups.items() if LIB.get(k) and LIB[k].kind == "gst" for s in v
                      if s.registered and s.gstin[:2] != self.p.state]
        books_sups = books_sups or [s for s in self.all_sups if s.registered]
        for _ in range(self.n_fixed(FIXED_COMMON["b2ba_amendment"])):
            s = rng.choice(books_sups)
            d = date(2026, 5, rng.randint(2, 28))
            orig = self.bill(s, d, cat=LIB.get(s.cat))
            g0 = self.group("other_month_noise", s.cat, s)
            g0.blocked = ""
            g0.portal.append(self.prow(orig, "052026"))
            g = self.group("b2ba_amendment", s.cat, s)
            g.blocked = ""
            f = rng.uniform(0.3, 0.9)
            new_tx = r2(orig.taxable * f)
            nh = self.heads(orig.gstin, new_tx, orig.rate)
            delta = tuple(r2(n - o) for n, o in zip(nh, orig.heads))
            amended = Bill(s, orig.gstin, orig.no, orig.dt, new_tx, *nh, rate=orig.rate)
            r = self.prow(amended, RETURN, typ="B2BA", heads=delta, taxable=r2(new_tx - orig.taxable),
                          amends={"period": "052026", "no": orig.no, "dt": orig.dt, "full_heads": nh,
                                  "full_taxable": new_tx, "orig_gid": g0.gid})
            g.portal.append(r)
            g.claim, g.bucket = delta, "4A5_2b"
            g.note = f"amends {orig.no} of the May 2B: only the difference counts"

    # ---- assembly --------------------------------------------------------------------------------------------
    def build(self):
        rng = self.rng
        p = self.p
        n_bills = int(round(p.n_books * self.scale))
        cats = list(p.cats)
        cw = [p.cats[c] for c in cats]
        normal_cases = list(p.case_w)
        counts: dict[str, int] = {}
        planned = []
        for _ in range(n_bills):
            ck = rng.choices(cats, weights=cw)[0]
            cat = LIB[ck]
            weights = RECURRING_CASES if cat.recurring else p.case_w
            ks = list(weights)
            case = rng.choices(ks, weights=[weights[k] for k in ks])[0] if cat.kind == "gst" else cat.kind
            planned.append((case, ck))
            counts[case] = counts.get(case, 0) + 1
        gst_cats = [c for c in cats if LIB[c].kind == "gst" and not LIB[c].recurring]
        for case, mn in FIXED_COMMON.items():
            if case in normal_cases:
                for _ in range(max(0, self.n_fixed(mn) - counts.get(case, 0))):
                    planned.append((case, rng.choice(gst_cats)))
        if "billed_to_other_branch" in p.case_w:
            for _ in range(max(0, 3 - counts.get("billed_to_other_branch", 0))):
                planned.append(("billed_to_other_branch", rng.choice(gst_cats)))
        for case, ck in planned:
            self.make_case(case, ck)
        self.make_cn_cases()
        self.make_prev_month_tail()
        self.make_rectifications()
        self.noise_sups()
        for per in MONTHS:
            self.noise_rows(per)
        self.make_b2ba()
        self.assign_vouchers()
        self.remark()

    def assign_vouchers(self):
        rng = self.rng
        rows = [r for g in self.groups for r in g.books]
        tail = [r for r in rows if r["m"].get("tail")]
        body = [r for r in rows if not r["m"].get("tail")]
        # voucher = one party + one booking date (often several invoices on one journal)
        by_key: dict = {}
        for r in body:
            v = r["v"]
            k = (v["Particulars"], r["m"]["vdate"], v["Voucher Type"])
            by_key.setdefault(k, []).append(r)
        keys = list(by_key)
        rng.shuffle(keys)
        ordered = []
        for k in keys:
            group_rows = by_key[k]
            if len(group_rows) > 1 or rng.random() < 0.85:
                chunks = [group_rows]
            else:
                chunks = [[r] for r in group_rows]
            for ch in chunks:
                if ch[0]["v"]["Voucher Type"] == "Debit Note":
                    self.dn_vchr += 1
                    vno = self.dn_vchr
                else:
                    self.vchr += rng.randint(1, 3)
                    vno = self.vchr if rng.random() > 0.03 else f"{self.vchr}({rng.choice(['a', 'B', 'A'])})"
                for r in ch:
                    r["v"]["Voucher No."] = vno
                ordered.extend(ch)
        tail.sort(key=lambda r: (r["m"]["vdate"].month != 5, r["v"]["Particulars"]))
        for r in tail:
            self.vchr += 1
            r["v"]["Voucher No."] = rng.randint(1800, 2150) if r["m"]["vdate"].month == 5 else self.vchr
            r["v"]["Activity"] = r["v"]["ITC ELIGIBLITY"] = "#N/A"
        self.books_rows = ordered + tail
        vcount: dict = {}
        for r in self.books_rows:
            vcount[r["v"]["Voucher No."]] = vcount.get(r["v"]["Voucher No."], 0) + 1
        self.row_group = {}
        for g in self.groups:
            for r in g.books:
                self.row_group[id(r)] = g
                if vcount.get(r["v"]["Voucher No."], 0) > 1 and "multi_line_voucher" not in g.traits:
                    g.traits.append("multi_line_voucher")
                if isinstance(r["v"]["Voucher No."], str) and "voucher_no_suffix" not in g.traits:
                    g.traits.append("voucher_no_suffix")
            if g.cat in ("car_lease", "rent_reg", "office_rent", "telephone", "security") and "recurring_amount" not in g.traits:
                g.traits.append("recurring_amount")
        self.portal_rows = {per: [] for per in MONTHS}
        for g in self.groups:
            for r in g.portal:
                self.portal_rows[r["m"]["period"]].append(r)
                self.row_group[id(r)] = g
        for per in MONTHS:          # the firm sorts by supplier GSTIN, then date
            self.portal_rows[per].sort(key=lambda r: (r["v"]["GSTIN of supplier"], r["v"]["Invoice Date"], str(r["v"]["Invoice No"])))

    def remark(self):
        """CA remarks / lookups as in the completed working (combined workbook only)."""
        for g in self.groups:
            for r in g.portal:
                if r["m"]["period"] != RETURN:
                    continue
                rem = "Not in Books"
                if g.books and g.case not in ("other_month_noise",):
                    if g.case == "booked_without_gst":
                        rem = "Matched-Ineligible ITC-Booked with non-GST"
                    elif g.case in ("wrong_head", "other_gstin_same_pan"):
                        rem = "Wrong Booking"
                    elif g.blocked and not g.exception:
                        rem = "Matched-Ineligible ITC"
                    else:
                        rem = "Matched"
                    r["m"]["lookup"] = r["v"]["Invoice No"]
                r["m"]["remark"] = rem
            for r in g.books:
                look = "#N/A"
                if any(pr["m"]["period"] == RETURN for pr in g.portal):
                    look = str(g.portal[0]["v"]["Invoice No"])
                elif g.case in ("books_only_not_uploaded", "late_filer_next_month") and self.rng.random() < 0.5:
                    look = "Not in 2B"
                r["m"]["lookup"] = look

    # ---- table 4 ---------------------------------------------------------------------------------------------
    def table4(self) -> dict:
        z = lambda: [0.0, 0.0, 0.0]          # noqa: E731
        t = {k: z() for k in ("4A3_rcm", "4A5_auto_2b", "4A5_reclaim", "4A5_total", "4B1_current", "4B1_reclaimed",
                              "4B1_total", "4B2_not_in_books", "4D1_reclaimed", "4D2_not_available", "net_itc")}

        def add(k, h, sign=1):
            for i in range(3):
                t[k][i] = r2(t[k][i] + sign * h[i])
        for g in self.groups:
            for r in g.portal:
                m = r["m"]
                if m["period"] != RETURN:
                    continue
                h = m["heads"]
                sign = -1 if m["typ"] == "CN" else 1
                if not m["itcavl"]:
                    add("4D2_not_available", h, sign)
                elif not m["rcm"]:
                    add("4A5_auto_2b", h, sign)
            blocked = bool(g.blocked) and not g.exception
            if g.bucket == "4A5_2b" and blocked:
                add("4B1_current", g.claim)
            if g.bucket == "4A5_reclaim":
                add("4A5_reclaim", g.claim)
                add("4D1_reclaimed", g.claim)
                if blocked:
                    add("4B1_reclaimed", g.claim)
            if g.bucket == "4A3_rcm":
                add("4A3_rcm", g.claim)
            if g.bucket == "4A5_2b_cn_books":     # credit note only in books: CA reverses it (not in 2B yet)
                add("4B2_not_in_books", g.claim, -1)
        claimed_2b = z()
        for g in self.groups:
            if g.bucket == "4A5_2b":
                for i in range(3):
                    claimed_2b[i] += g.claim[i]
        for i in range(3):
            t["4B2_not_in_books"][i] = r2(t["4B2_not_in_books"][i] + t["4A5_auto_2b"][i] - claimed_2b[i])
            t["4A5_total"][i] = r2(t["4A5_auto_2b"][i] + t["4A5_reclaim"][i])
            t["4B1_total"][i] = r2(t["4B1_current"][i] + t["4B1_reclaimed"][i])
            t["net_itc"][i] = r2(t["4A5_total"][i] + t["4A3_rcm"][i] - t["4B1_total"][i] - t["4B2_not_in_books"][i])
        out = {k: {"igst": v[0], "cgst": v[1], "sgst": v[2], "total": r2(sum(v))} for k, v in t.items()}
        out["_method"] = ("4A5 = Jun 2B ITC (available, forward charge, net of credit notes / B2BA differences) + reclaims of "
                          "invoices found in Apr/May 2B that were reversed then; 4B1 = Sec 17(5) items claimed this month; "
                          "4B2 = Jun 2B ITC not taken (not in books, booked without GST, held for wrong head / other GSTIN, "
                          "excess over books) plus credit notes booked but not yet in 2B; 4D1 = reclaims; 4D2 = 2B ITC "
                          "not available. net_itc = 4A5 + 4A3 - 4B1 - 4B2.")
        return out

    # ---- writers ---------------------------------------------------------------------------------------------
    def files(self):
        mon = mon_yy(RETURN)
        return {"books_xlsx": f"Purchase Register {mon}.xlsx", "books_sheet": f"Purchase {mon}",
                "books_csv": f"Purchase Register {mon}.csv",
                "portal_xlsx": {p: f"GSTR-2B {mon_yy(p)}.xlsx" for p in MONTHS},
                "portal_sheet": {p: f"GSTR-2B {mon_yy(p)}" for p in MONTHS},
                "portal_json": {RETURN: f"{RETURN}_{self.client_gstin}_GSTR2B_14072026.json"},
                "combined": f"GSTR-3B Working {mon}.xlsx", "vendor_master": "Vendor Master.xlsx"}

    def write(self, out: Path):
        out.mkdir(parents=True, exist_ok=True)
        F = self.files()
        # books rows (positions fixed here)
        for i, r in enumerate(self.books_rows):
            r["m"]["row"] = BOOKS_HEADER_ROW + 1 + i
        for per in MONTHS:
            for i, r in enumerate(self.portal_rows[per]):
                r["m"]["row"] = P2B_HEADER_ROW + 1 + i
        wb = Workbook()
        ws = wb.active
        ws.title = F["books_sheet"]
        self._books_sheet(ws, completed=False)
        wb.save(out / F["books_xlsx"])
        self._books_csv(out / F["books_csv"])
        for per in MONTHS:
            wb = Workbook()
            ws = wb.active
            ws.title = F["portal_sheet"][per]
            self._p2b_sheet(ws, per, completed=False)
            wb.save(out / F["portal_xlsx"][per])
        self._json(out / F["portal_json"][RETURN], RETURN)
        wb = Workbook()
        ws = wb.active
        ws.title = "Summary"
        t4 = self.table4()
        self._summary(ws, t4)
        self._books_sheet(wb.create_sheet(F["books_sheet"]), completed=True)
        self._p2b_sheet(wb.create_sheet(F["portal_sheet"][RETURN]), RETURN, completed=True)
        wb.save(out / F["combined"])
        self._vendor_master(out / F["vendor_master"])
        truth = self.truth(F, t4)
        (out / "truth.json").write_text(json.dumps(truth, indent=1, default=str))
        return truth["meta"]

    def _books_sheet(self, ws, completed):
        rows = self.books_rows
        n = len(rows)
        last = BOOKS_HEADER_ROW + n
        sums = {}
        for c in ("IGST", "CGST", "SGST", "Total Tax"):
            sums[c] = r2(sum(_f(r["v"][c]) for r in rows))
        sub = [None] * len(BOOK_COLS)
        sub[BOOK_COLS.index("Gross Total")] = "#REF!"
        sub[BOOK_COLS.index("Taxable")] = "#REF!"
        for c, v in sums.items():
            sub[BOOK_COLS.index(c)] = v
        ws.append([None] * len(BOOK_COLS))
        ws.append([None] * len(BOOK_COLS))
        ws.append(sub)
        ws.append(BOOK_COLS)
        for c in ws[BOOKS_HEADER_ROW]:
            c.font = Font(bold=True)
        for r in rows:
            v = dict(r["v"])
            if completed:
                v["Lookup"] = r["m"].get("lookup", "#N/A")
            ws.append([v[c] for c in BOOK_COLS])
        for row in ws.iter_rows(min_row=BOOKS_HEADER_ROW + 1, max_row=last, max_col=1):
            row[0].number_format = "dd-mm-yyyy"
        ws.freeze_panes = "C5"

    def _books_csv(self, path):
        rows = self.books_rows
        sub = [""] * len(BOOK_COLS)
        sub[BOOK_COLS.index("Gross Total")] = "#REF!"
        sub[BOOK_COLS.index("Taxable")] = "#REF!"
        for c in ("IGST", "CGST", "SGST", "Total Tax"):
            sub[BOOK_COLS.index(c)] = str(r2(sum(_f(r["v"][c]) for r in rows)))
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow([""] * len(BOOK_COLS))
            w.writerow([""] * len(BOOK_COLS))
            w.writerow(sub)
            w.writerow(BOOK_COLS)
            for r in rows:
                out = []
                for c in BOOK_COLS:
                    x = r["v"][c]
                    if isinstance(x, datetime):
                        x = x.strftime("%d-%m-%Y")
                    out.append("" if x is None else x)
                w.writerow(out)

    def _p2b_sheet(self, ws, per, completed):
        rows = self.portal_rows[per]
        sub = [None] * len(P2B_COLS)
        for c in ("Taxable Value", "IGST", "CGST", "SGST", "Total Tax"):
            sub[P2B_COLS.index(c)] = r2(sum(_f(r["v"][c]) for r in rows))
        for _ in range(3):
            ws.append([None] * len(P2B_COLS))
        ws.append(sub)
        ws.append(P2B_COLS)
        for c in ws[P2B_HEADER_ROW]:
            c.font = Font(bold=True)
        for r in rows:
            v = dict(r["v"])
            if completed:
                v["Remark"] = r["m"].get("remark", "Not in Books")
                v["Lookup"] = r["m"].get("lookup", "#N/A")
            ws.append([v[c] for c in P2B_COLS])
        for row in ws.iter_rows(min_row=P2B_HEADER_ROW + 1, max_row=P2B_HEADER_ROW + len(rows)):
            row[7].number_format = "dd-mm-yyyy"
            row[17].number_format = "dd-mm-yyyy"
        ws.freeze_panes = "C6"

    def _json(self, path, per):
        b2b, cdnr, b2ba = {}, {}, {}
        for r in self.portal_rows[per]:
            m, v = r["m"], r["v"]
            b = m["bill"]
            heads = m["heads"]
            tx = m["taxable"]
            if m["amends"]:
                heads, tx = m["amends"]["full_heads"], m["amends"]["full_taxable"]
            fil = m["filing"]
            sup = {"ctin": b.gstin, "trdnm": b.sup.legal, "supfildt": fil.strftime("%d-%m-%Y") if fil else "",
                   "supprd": m["sup_period"]}
            rec = {"dt": b.dt.strftime("%d-%m-%Y"), "val": r2(abs(tx) + abs(sum(heads))), "pos": self.p.state,
                   "rev": "Y" if m["rcm"] else "N", "itcavl": "Y" if m["itcavl"] else "N", "rsn": m["rsn"],
                   "diffprcnt": 1, "srctyp": "e-Invoice" if v["E-Invoice Applicable"] == "Yes" else "",
                   "irn": "", "irngendate": "",
                   "items": [{"num": 1, "rt": b.rate, "txval": abs(tx), "igst": abs(heads[0]), "cgst": abs(heads[1]),
                              "sgst": abs(heads[2]), "cess": 0}]}
            key = (b.gstin, m["sup_period"])
            if m["amends"]:
                s = b2ba.setdefault(key, {**sup, "inv": []})
                rec.update({"oinum": m["amends"]["no"], "oidt": m["amends"]["dt"].strftime("%d-%m-%Y"),
                            "inum": b.no, "typ": "R"})
                s["inv"].append(rec)
            elif m["typ"] in ("CN", "DN"):
                s = cdnr.setdefault(key, {**sup, "nt": []})
                rec.update({"ntnum": b.no, "typ": "C" if m["typ"] == "CN" else "D", "suptyp": "R"})
                s["nt"].append(rec)
            else:
                s = b2b.setdefault(key, {**sup, "inv": []})
                rec.update({"inum": b.no, "typ": "R"})
                s["inv"].append(rec)
        data = {"chksum": "synthetic-ca", "data": {"gstin": self.client_gstin, "rtnprd": per, "version": "1.0",
                                                    "gendt": "14-07-2026",
                                                    "docdata": {"b2b": list(b2b.values()), "cdnr": list(cdnr.values()),
                                                                "b2ba": list(b2ba.values())}}}
        Path(path).write_text(json.dumps(data, indent=1))

    def _summary(self, ws, t4):
        ws.append(["FORM GSTR-3B \n[See rule 61(5)]"])
        ws.append([])
        ws.append([1, "Financial Year", "2026-2027", "Month", datetime(2026, 6, 1)])
        ws.append([2, "GSTIN ", self.client_gstin])
        ws.append(["3A", "Legal Name", self.p.client.upper()])
        ws.append([])
        ws.append(["4. Eligible ITC", None, None, None, None, None, "CA working (expected answer)", "IGST", "CGST", "SGST"])
        lines = [("(A)(3) Inward supplies liable to reverse charge", "4A3_rcm"),
                 ("(A)(5) All other ITC - auto-populated from GSTR-2B", "4A5_auto_2b"),
                 ("Reclaim ITC which was reversed in earlier period now found Matching with PR - 4(B)(2)", "4A5_reclaim"),
                 ("(A)(5) All other ITC - total", "4A5_total"),
                 ("(B)(1) Reversal ITC - Construction/Ineligible 17(5) of Jun-26", "4B1_current"),
                 ("(B)(1) Reversal ITC - Construction/Ineligible 17(5) of Previous month", "4B1_reclaimed"),
                 ("(B)(1) total", "4B1_total"),
                 ("(B)(2) Reversal - No Matching Invoice Found in PR", "4B2_not_in_books"),
                 ("(D)(1) ITC which was reversed in earlier period now found in PR", "4D1_reclaimed"),
                 ("(D)(2) Ineligible ITC under section 16(4) & ITC restricted due to PoS rules", "4D2_not_available"),
                 ("Net ITC Claimed", "net_itc")]
        for label, k in lines:
            v = t4[k]
            ws.append([label, None, None, None, None, None, k, v["igst"], v["cgst"], v["sgst"]])
        ws.column_dimensions["A"].width = 80

    def _vendor_master(self, path):
        wb = Workbook()
        ws = wb.active
        ws.title = "Vendor Master"
        ws.append(["Vendor Code", "Vendor Name", "GSTIN", "PAN", "State", "Activity", "ITC ELIGIBLITY", "Remarks"])
        seen = set()
        k = 0
        for s in self.all_sups:
            if not s.in_master or not s.registered or s.gstin in seen:
                continue
            seen.add(s.gstin)
            k += 1
            ws.append([f"V{k:05d}", s.books_name.strip().removeprefix("M/s ").strip(), s.gstin, s.pan,
                       STATE_NAMES.get(s.gstin[:2], ""), s.master_activity, s.master_elig, None])
        wb.save(path)

    # ---- truth -------------------------------------------------------------------------------------------------
    def truth(self, F, t4) -> dict:
        rows, groups = [], []
        bsrc = f"{F['books_xlsx']}:{F['books_sheet']}"
        for g in self.groups:
            brids, prids = [], []
            for r in g.books:
                m = r["m"]
                rid = f"B:{m['row']}"
                brids.append(rid)
                b = m["bill"]
                rows.append({"rid": rid, "side": "books", "gid": g.gid, "file": F["books_xlsx"], "sheet": F["books_sheet"],
                             "row": m["row"], "source": bsrc, "row_ref": f"row {m['row']}",
                             "gstin": b.gstin or "", "inv_no": b.no or "", "inv_date": b.dt.isoformat() if b.no else "",
                             "doc_type": b.typ, "tax": r2(m["tax"])})
            for r in g.portal:
                m = r["m"]
                per = m["period"]
                rid = f"P:{per}:{m['row']}"
                prids.append(rid)
                b = m["bill"]
                rows.append({"rid": rid, "side": "portal", "gid": g.gid, "period": per, "file": F["portal_xlsx"][per],
                             "sheet": F["portal_sheet"][per], "row": m["row"],
                             "source": f"{F['portal_xlsx'][per]}:{F['portal_sheet'][per]}", "row_ref": f"row {m['row']}",
                             "key": [b.gstin, b.no, m["typ"], per], "itc_available": m["itcavl"], "rcm": m["rcm"],
                             "amends": m["amends"]["no"] if m["amends"] else "",
                             "tax": r2((-1 if m["typ"] == "CN" else 1) * sum(m["heads"]))})
            cl = tuple(r2(x) for x in g.claim)
            groups.append({"gid": g.gid, "case": g.case, "category": g.cat, "supplier": (g.sup.legal if g.sup else ""),
                           "books": brids, "portal": prids,
                           "partner_periods": sorted({r["m"]["period"] for r in g.portal}),
                           "traits": sorted(set(g.traits)),
                           "itc_claim": {"igst": cl[0], "cgst": cl[1], "sgst": cl[2], "total": r2(sum(cl))},
                           "bucket": g.bucket, "blocked": g.blocked if not g.exception else "",
                           "blocked_exception": bool(g.exception), "lookalike_of": g.lookalike,
                           "excluded": g.excluded, "master_elig": g.master_elig, "note": g.note})
        case_counts: dict = {}
        for g in groups:
            case_counts[g["case"]] = case_counts.get(g["case"], 0) + 1
        meta = {"profile": self.p.key, "title": self.p.title, "description": self.p.description,
                "client_name": self.p.client, "client_gstin": self.client_gstin,
                "client_other_gstins": self.branch_gstins, "return_period": RETURN, "months": MONTHS,
                "books_rows": len(self.books_rows),
                "portal_rows": {p: len(self.portal_rows[p]) for p in MONTHS},
                "groups": len(groups), "case_counts": dict(sorted(case_counts.items())),
                "books_header_row": BOOKS_HEADER_ROW, "portal_header_row": P2B_HEADER_ROW,
                "scale": self.scale, "files": F}
        return {"meta": meta, "vocabulary": CASES, "groups": groups, "rows": rows, "table4": t4}


def _num(x):
    if x is None:
        return None
    x = r2(x)
    return int(x) if x == int(x) else x


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _simple(name: str) -> str:
    s = name.upper().replace("PRIVATE", "PVT").replace("LIMITED", "LTD").replace("(P)", "PVT")
    s = re.sub(r"^M/S\s+", "", s.strip())
    return re.sub(r"[^A-Z0-9]", "", s)


def _min_heads(a, b):
    return a if sum(a) <= sum(b) else b


def generate(out_dir="test_data", seed: int = 11, profile: str | list | None = None, months=None,
             stress: bool = False) -> dict:
    """Write one folder per profile under out_dir. Returns {profile: meta}.

    months: kept for API symmetry; the set is fixed to Apr-Jul 2026 with June as the return month.
    stress: also write 'stress_manufacturer' (~4,800 books rows, ~5,000 2B rows per month, ~25 MB)."""
    if months and list(months) != MONTHS:
        raise ValueError(f"months are fixed to {MONTHS} (return month {RETURN})")
    out = Path(out_dir)
    keys = [profile] if isinstance(profile, str) else (list(profile) if profile else list(PROFILES))
    metas = {}
    for k in keys:
        g = Gen(PROFILES[k], seed)
        g.build()
        metas[k] = g.write(out / k)
    if stress:
        g = Gen(PROFILES["a_manufacturer_plant"], seed, scale=9.0, noise_scale=4.5)
        g.build()
        metas["stress_manufacturer"] = g.write(out / "stress_manufacturer")
    return metas


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate CA-style TaxMind test data with answer keys")
    ap.add_argument("--out", default="test_data")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--profile", action="append", choices=list(PROFILES))
    ap.add_argument("--stress", action="store_true", help="also write a ~5,000-row stress dataset")
    a = ap.parse_args(argv)
    metas = generate(a.out, seed=a.seed, profile=a.profile, stress=a.stress)
    for k, m in metas.items():
        print(f"{k}: {m['books_rows']} books rows, 2B rows {m['portal_rows']}, {m['groups']} groups")


if __name__ == "__main__":
    main()
