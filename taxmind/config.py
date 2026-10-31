"""Tunable settings. Every threshold the engine uses lives here."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Config:
    # Matching
    amount_tolerance: float = 1.0        # ₹ difference treated as rounding (taxable and tax separately)
    amount_tolerance_pct: float = 0.0    # ...or this % of the amount, whichever is larger (0 = off)
    date_window_days: int = 10           # max date gap for typo / probable matches
    split_window_days: int = 31          # max date spread for split / combined invoices
    split_max_parts: int = 4             # max invoices combined into one entry
    split_max_candidates: int = 18       # per supplier, to keep the search fast
    min_core_digits: int = 2             # trailing-number match needs at least this many digits

    # Pre-filing checks
    drc01c_abs: float = 25_00_000        # ₹25 lakh  } both must be crossed for DRC-01C
    drc01c_pct: float = 0.20             # 20%       }
    sec16_warn_days: int = 60            # warn when the Sec 16(4) deadline is this close
    concentration_pct: float = 0.30      # one supplier above this share of ITC is flagged
    large_invoice_pct: float = 0.15      # one invoice above this share of ITC is flagged

    # Client profile
    line_of_business: str = ""           # tags from blocked.LINES_OF_BUSINESS, e.g. "vehicle_maker,caterer"
    client_gstin: str = ""               # the client's own GSTIN (tax-head check against supplier state)
    not_in_books_policy: str = "pending" # 'pending': keep 2B-only bills Pending in IMS (default);
                                         # 'reverse': let them flow into 3B 4(A) and reverse in 4(B)(2)

    small_excess: float = 10.0           # 2B higher than books by up to this (₹): accept, claim the books amount

    # Books hygiene
    rate_slabs: tuple = (0.1, 0.25, 1, 1.5, 3, 5, 6, 7.5, 12, 18, 28, 40)   # GST rates (incl. GST 2.0 40%)
    rate_slack: float = 0.35             # percentage points of rounding allowed around a slab
    partial_register_pct: float = 0.5    # 2B ITC from suppliers never in books above this share -> partial register?

    # Follow-ups
    supplier_fix_day: int = 11           # ask suppliers to fix by the 11th (GSTR-1 due date)

    def tol(self, *amounts: float) -> float:
        """Rounding allowed when comparing these amounts."""
        base = self.amount_tolerance
        if self.amount_tolerance_pct and amounts:
            base = max(base, abs(max(amounts, key=abs)) * self.amount_tolerance_pct / 100)
        return base
