"""Read the supplier's invoice number and date out of a books narration.

Tally journal registers often carry only the voucher (booking) date and leave the
supplier's invoice number blank; the accountant types both into the narration:

  'Procurement of ... Invoice No & dtd - As per invoice no : 26-27/PNQ/41  4-Apr-2026'
  'Payment for supply of conveyor Inv No PX4/26-27/052 dtd 18 May 2026'
  'Lease Rent for the Period 01/06/2026 to 30/06/2026 Invoice no. KRL/013/26-27 dated 01/06/2026'
  'Credit note  no 2026-27/07, against invoice no 2025-26/731'

Everything here is a best guess and is reported back to the CA as such.
"""
from __future__ import annotations

import re
from datetime import date

_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                    "nov", "dec"], start=1)}

# A word that introduces a document number. 'bill' is weak (bill of entry, bill to) and needs 'no'.
_INV = r"(?:invoices?|invocie|incvoice|invioce|invoce|inv|bill)"
_KEY = re.compile(r"(?<![a-z])(?:tax\s+)?" + _INV + r"\s*\.?\s*(?:no|number|num|#)?\b\.?", re.I)
_CN_KEY = re.compile(r"(?<![a-z])(?:credit|cr)\s*\.?\s*note\s*\.?\s*(?:no|number|#)?\b\.?", re.I)
_DN_KEY = re.compile(r"(?<![a-z])(?:debit|dr)\s*\.?\s*note\s*\.?\s*(?:no|number|#)?\b\.?", re.I)
_AGAINST = re.compile(r"against\s+(?:our\s+|your\s+|the\s+)?(?:tax\s+)?(?:invoice|inv|bill)\s*\.?\s*(?:no|number)?\b\.?",
                      re.I)
# filler between the keyword and the number: ':', '-', '&', 'dtd', 'as per invoice no', ...
_FILL = re.compile(r"^(?:[\s:\-–#.,&]|and\b|dtd\b|dated\b|date\b|no\b|nos?\.|number\b|as\s+per\b|is\b|ref\b)*",
                   re.I)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9/\-_.]*")
_DATEISH = re.compile(r"^(0?[1-9]|[12]\d|3[01])([-/.])(0?[1-9]|1[0-2]|[A-Za-z]{3,9})\2(\d{2}|\d{4})$")

# dates: 15/05/2026, 30-Apr-26, 18 May 2026, 01st Jun 2026, 21/May/2026, 13-Feb -2026, 06.05.2026, May 21, 2026
_D_NUM = r"(?P<d1>\d{1,2})\s*[-/.]\s*(?P<m1>\d{1,2})\s*[-/.]\s*(?P<y1>\d{4}|\d{2})(?!\d)"
_MONTHS = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
           r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_D_TXT = (r"(?P<d2>\d{1,2})(?:st|nd|rd|th)?\s*[-/.]?\s*(?P<m2>" + _MONTHS + r")(?![a-z])\.?\s*[-/.,]?\s*"
          r"(?P<y2>\d{4}|\d{2})(?!\d)")
_D_US = r"(?P<m3>" + _MONTHS + r")\.?\s+(?P<d3>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y3>\d{4})(?!\d)"
_DATE = re.compile(rf"(?<!\d)(?:{_D_NUM}|{_D_TXT}|{_D_US})", re.I)
_DATED = re.compile(r"(?:dtd|dated|dt|date|d/t)\b\.?\s*[:\-–]?\s*$", re.I)
_PERIOD = re.compile(r"(?:period|from|for\s+the\s+month|to|till|upto|-)\s*$", re.I)

ADVANCE = re.compile(r"(?<![a-z])(advance|proforma|pro-forma|pro forma|mobilisation|mobilization)(?![a-z])", re.I)
CORRECTION = re.compile(r"(?:now|being|hence|is)\s+rectified|rectification\s+(?:entry|of\s+(?:booking|entry|error|"
                        r"excess|short|less))|rectified\s+(?:against|for|vide)|excess\s+booking|less\s+booking|"
                        r"short\s+booking|booked\s+(?:less|short|excess)|wrong(?:ly)?\s+booked|"
                        r"differen(?:ce|tial)\s+(?:in\s+)?(?:gst|tax|booking)|"
                        r"provision\s+(?:for\s+|of\s+)?(?:exp\w*\s+)?revers", re.I)
RCM = re.compile(r"(?<![a-z])(rcm|reverse\s+charge|under\s+reverse|import\s+of\s+services?)(?![a-z])", re.I)


def _mk(y: int, m: int, d: int) -> date | None:
    if y < 100:
        y += 2000
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _parse(m: re.Match, swap: bool = False) -> date | None:
    g = m.groupdict()
    if g.get("d1"):
        if swap:
            return _mk(int(g["y1"]), int(g["d1"]), int(g["m1"]))
        return _mk(int(g["y1"]), int(g["m1"]), int(g["d1"]))
    if g.get("d2"):
        mon = _MON.get(g["m2"][:3].lower())
        return _mk(int(g["y2"]), mon, int(g["d2"])) if mon else None
    if g.get("d3"):
        mon = _MON.get(g["m3"][:3].lower())
        return _mk(int(g["y3"]), mon, int(g["d3"])) if mon else None
    return None


def clean(text) -> str:
    s = "" if text is None else str(text)
    s = s.replace("_x000D_", " ").replace("\t", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", s).strip()


def _number_after(text: str, pos: int) -> tuple[str, int] | None:
    rest = text[pos:]
    lead = _FILL.match(rest)
    start = lead.end() if lead else 0
    m = _TOKEN.match(rest, start)
    if not m:
        return None
    tok = re.sub(r"(?i)(?<=\d)(dtd|dated|dt)$", "", m.group(0)).rstrip(".-/_,")
    if not re.search(r"\d", tok) or _DATEISH.match(tok) or len(tok) > 30:
        return None
    if re.fullmatch(r"\d{1,2}", tok):            # 'invoice no 5 dated' is possible but 'inv 2 nos' is not: need 3+
        if not re.match(r"\s*(?:,|dt|dated|dtd|$|\d{1,2}\s*[-/.]\s*(?:\d{1,2}|[A-Za-z]{3}))", rest[m.end():], re.I):
            return None
    return tok, pos + m.end()


_BARE = re.compile(r"(?<![A-Za-z0-9/\-])([A-Za-z]{1,8}[A-Za-z0-9]*[/\-]?[A-Za-z0-9/\-]*\d{3,}[A-Za-z0-9/\-]*)"
                   r"\s*,?\s*(?:dtd|dated|dt)?\.?\s*[:\-]?\s*(?=\d{1,2}\s*[-/.]\s*(?:\d{1,2}|[A-Za-z]{3}))")


def invoice_no(text) -> str:
    """The supplier's invoice number in a narration, or ''."""
    return invoice_no_how(text)[0]


# tokens that look like numbers but are not invoices: PO / GRN / DC / quotation / HSN numbers, vehicle
# registrations (MH12AB1234), e-way bills, months ('June2026')
_NOT_INV = re.compile(r"^(?:po|pr|grn|mrn|srn|hsn|sac|dc|dn|so|wo|q|qtn|quot|lr|gr|ewb|eway|ch|chln|challan|"
                      r"order|ref|frn|vch|jv|rfq|boe|be|awb|pnr|bg|lc)(?:[^a-z]|$)", re.I)
_VEHICLE = re.compile(r"^[A-Z]{2}\s?-?\d{1,2}\s?-?[A-Z]{0,3}\s?-?\d{3,4}$", re.I)
_MONTHY = re.compile(r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[-/]?\d{2,4}$", re.I)


def bare_number(text) -> str:
    """A document number written without 'invoice no' right before a date. Weaker evidence:
    callers should treat it as a hint (it is never used to call two entries duplicates)."""
    s = clean(text)
    if ADVANCE.search(s):
        return ""
    for m in _BARE.finditer(s):
        tok = m.group(1).rstrip("-/")
        before = s[max(0, m.start() - 14):m.start()].lower()
        if (not re.search(r"[A-Za-z]", tok) or _NOT_INV.match(tok) or _VEHICLE.match(tok) or _MONTHY.match(tok)
                or re.search(r"quotation|order|challan|vehicle|truck|po\b|grn|lr\b|e-?way", before)):
            continue
        return tok
    return ""


def invoice_no_how(text) -> tuple[str, str]:
    """(number, 'keyword' | 'bare' | '')."""
    s = clean(text)
    saved = _bare_disabled(s)
    if saved:
        return saved, "keyword"
    b = bare_number(s)
    return (b, "bare") if b else ("", "")


def _bare_disabled(s: str) -> str:
    """Keyword path. 'invoice'/'inv' beats 'bill' ('RA bill 26, Tax Inv No. 26-27/MUM/114')."""
    weak = ""
    for m in _KEY.finditer(s):
        if re.search(r"(?:proforma|pro-forma|pro forma|against|quotation|e-?\s?way|eway|lorry|delivery|"
                     r"of\s+entry)\s*$", s[:m.start()], re.I) or re.match(r"\s*of\s+(?:entry|lading)", s[m.end():], re.I):
            continue
        got = _number_after(s, m.end())
        if got:
            if re.match(r"\s*(?:tax\s+)?bill", m.group(0), re.I):
                weak = weak or got[0]
                continue
            return got[0]
    return weak


def credit_note(text) -> tuple[str, str]:
    """(credit note no., original invoice no.) when the narration describes a credit note."""
    s = clean(text)
    cn = ""
    for m in _CN_KEY.finditer(s):
        got = _number_after(s, m.end())
        if got:
            cn = got[0]
            break
    orig = ""
    m = _AGAINST.search(s)
    if m:
        got = _number_after(s, m.end())
        orig = got[0] if got else ""
    return cn, orig


def invoice_date(text, near: str = "", booked: date | None = None) -> date | None:
    """The invoice date in a narration. Prefers a date introduced by 'dtd'/'dated' or the one right
    after the invoice number; ignores service-period dates ('for the period 01/06 to 30/06').
    Dates more than a month after the booking date or over 3 years before it are ignored."""
    s = clean(text)
    cands = []
    anchor = s.upper().find(near.upper()) + len(near) if near and near.upper() in s.upper() else -1
    def plausible(d):
        return d and not (booked and ((d - booked).days > 31 or (booked - d).days > 3 * 366))
    for m in _DATE.finditer(s):
        d = _parse(m)
        if not plausible(d):
            d = _parse(m, swap=True) if m.groupdict().get("d1") else None   # 03-09-2026 typed month-first
            if not plausible(d):
                continue
        before = s[max(0, m.start() - 25):m.start()]
        score = 0
        if _DATED.search(before):
            score += 3
        if anchor >= 0 and 0 <= m.start() - anchor <= 25:
            score += 2
        if _PERIOD.search(before) and not _DATED.search(before):
            score -= 3
        cands.append((score, -m.start(), d))
    if not cands:
        return None
    cands.sort(reverse=True)
    best = cands[0]
    if best[0] < 0:
        return None
    return best[2]
