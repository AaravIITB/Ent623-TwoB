"""Tunable settings. Every threshold the engine uses lives here."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Config:
    # Matching
    amount_tolerance: float = 1.0        # ₹ difference treated as rounding (taxable and tax separately)
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

    # Follow-ups
    supplier_fix_day: int = 11           # ask suppliers to fix by the 11th (GSTR-1 due date)
