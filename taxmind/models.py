"""Canonical records shared by every loader and by the matcher.

Every input (GSTR-2B JSON, IMS download, Tally XML, Excel purchase register)
is converted into a list of `Doc` objects. The rest of the engine only ever
sees `Doc`s, so supporting a new file format means writing one loader.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BOOKS = "books"      # client's purchase register
    PORTAL = "portal"    # GSTR-2B / IMS (what suppliers reported)


class DocType(str, Enum):
    INVOICE = "INV"
    CREDIT_NOTE = "CN"   # supplier's credit note (reduces buyer's ITC)
    DEBIT_NOTE = "DN"    # supplier's debit note (adds ITC)


@dataclass
class Doc:
    side: Side
    uid: str                         # unique id within the run
    supplier_gstin: str
    doc_no: str
    doc_date: Optional[date]
    taxable: float = 0.0
    igst: float = 0.0
    cgst: float = 0.0
    sgst: float = 0.0
    cess: float = 0.0
    doc_type: DocType = DocType.INVOICE
    supplier_name: str = ""
    total_value: Optional[float] = None
    pos: str = ""                    # place of supply (state code)
    reverse_charge: bool = False
    itc_available: Optional[bool] = None
    itc_unavailable_reason: str = ""
    period: str = ""                 # return period MMYYYY (portal: the 2B it came from)
    supplier_filing_date: Optional[date] = None
    irn: str = ""
    ims_action: str = ""             # current IMS action if known: Accepted/Rejected/Pending/No action
    amends: str = ""                 # for 2B amendments (b2ba/cdnra): the original document no.
    ledger: str = ""                 # books: purchase / expense ledger(s) used
    description: str = ""            # books: item description or narration
    hsn: str = ""                    # HSN / SAC code(s)
    source: str = ""                 # file + section, for traceability
    row_ref: str = ""                # row / voucher reference inside the source

    @property
    def tax(self) -> float:
        return round(self.igst + self.cgst + self.sgst + self.cess, 2)

    @property
    def pan(self) -> str:
        g = (self.supplier_gstin or "").upper()
        return g[2:12] if len(g) == 15 else g

    @property
    def state_code(self) -> str:
        g = (self.supplier_gstin or "")
        return g[:2] if len(g) >= 2 else ""

    @property
    def itc_sign(self) -> int:
        """Credit notes reduce ITC."""
        return -1 if self.doc_type == DocType.CREDIT_NOTE else 1

    @property
    def doc_month(self) -> str:
        return self.doc_date.strftime("%m%Y") if self.doc_date else ""

    def label(self) -> str:
        d = self.doc_date.strftime("%d-%m-%Y") if self.doc_date else "no date"
        return f"{self.doc_no} dt {d}"


class Status(str, Enum):
    EXACT = "Exact match"
    FORMAT_DIFF = "Invoice no. format differs"
    DATE_DIFF = "Date differs"
    TYPO = "Probable typo in invoice no."
    PROBABLE = "Same amounts, different invoice no."
    OTHER_GSTIN = "Supplier used another GSTIN (same PAN)"
    HEAD_MISMATCH = "Wrong tax head (IGST vs CGST/SGST)"
    VALUE_DIFF = "Amount differs"
    SPLIT = "Split / combined invoices"
    LATE_FILED = "Found in a later 2B (supplier filed late)"
    EARLIER_PERIOD = "Found in an earlier 2B"
    PORTAL_ONLY_KNOWN = "In 2B, not in books (known supplier)"
    PORTAL_ONLY_UNKNOWN = "In 2B, not in books (unknown supplier)"
    PORTAL_ONLY_CN = "Supplier credit note not in books"
    PORTAL_ITC_BLOCKED = "Portal says ITC not available"
    BOOKS_ONLY = "In books, not in 2B"
    BOOKS_DUPLICATE = "Duplicate entry in books"
    RCM = "Reverse charge (outside IMS)"


class Action(str, Enum):
    ACCEPT = "Accept"
    REJECT = "Reject"
    PENDING = "Pending"
    NONE = "No IMS action"          # books-only items: nothing to do in IMS


class Owner(str, Enum):
    NONE = "Nobody"
    CA = "CA"
    CLIENT = "Client"
    SUPPLIER = "Supplier"


class Confidence(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


@dataclass
class Finding:
    """One decision the CA has to take, with the engine's recommendation."""
    fid: str
    status: Status
    books: list = field(default_factory=list)     # list[Doc]
    portal: list = field(default_factory=list)    # list[Doc]
    action: Action = Action.PENDING
    confidence: Confidence = Confidence.MEDIUM
    owner: Owner = Owner.CA
    reason: str = ""
    next_step: str = ""
    itc_in_2b: float = 0.0          # signed ITC the portal record(s) carry
    itc_in_books: float = 0.0       # signed ITC in books
    itc_to_claim: float = 0.0       # signed ITC we recommend claiming this period
    flags: list = field(default_factory=list)
    match_score: float = 0.0
    blocked: list = field(default_factory=list)   # blocked-credit (Sec 17(5)) flags for review

    @property
    def supplier_gstin(self) -> str:
        d = (self.portal or self.books)
        return d[0].supplier_gstin if d else ""

    @property
    def supplier_name(self) -> str:
        for d in self.books + self.portal:
            if d.supplier_name:
                return d.supplier_name
        return ""

    @property
    def itc_at_stake(self) -> float:
        return round(max(abs(self.itc_in_2b), abs(self.itc_in_books)), 2)

    @property
    def needs_human(self) -> bool:
        """True when a person has to decide or act (not just glance)."""
        if self.blocked:                 # possible Sec 17(5) block: a CA has to look, even on a clean match
            return True
        return not (self.action in (Action.ACCEPT, Action.NONE) and self.confidence == Confidence.HIGH
                    and self.owner == Owner.NONE)
