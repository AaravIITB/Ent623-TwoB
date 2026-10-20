"""Pair books entries with portal (2B / IMS) records.

Approach
  1. Block by supplier PAN and document type (only compare plausible pairs).
  2. Score every candidate pair and give it a status (exact, format difference,
     typo, other GSTIN, amount difference, ...).
  3. Assign pairs one-to-one, strongest first, so a weak guess never steals a
     record that has a strong partner.
  4. On what is left, look for split / combined invoices (one entry in books =
     several on the portal, or the reverse).
Everything still unmatched is classified later by the recommendation step.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from .config import Config
from .models import Doc, Status
from .normalize import days_apart, doc_relation, is_typo, k3


@dataclass
class Pair:
    books: list
    portal: list
    status: Status
    score: float
    rel: int = 0
    date_gap: int | None = None
    tax_diff: float = 0.0
    taxable_diff: float = 0.0


def _amounts_equal(a: Doc, b: Doc, tol: float) -> bool:
    return abs(a.taxable - b.taxable) <= tol and abs(a.tax - b.tax) <= tol


def _head_mismatch(a: Doc, b: Doc, tol: float) -> bool:
    """Same total tax, but one side IGST and the other CGST+SGST."""
    a_inter = a.igst > tol
    b_inter = b.igst > tol
    return a_inter != b_inter and abs(a.tax - b.tax) <= tol and abs(a.taxable - b.taxable) <= tol


def score_pair(bk: Doc, pt: Doc, cfg: Config) -> Pair | None:
    if bk.pan != pt.pan or bk.doc_type != pt.doc_type:
        return None
    tol = cfg.amount_tolerance
    rel = doc_relation(bk.doc_no, pt.doc_no)
    if rel == 3 and len(_core(bk.doc_no)) < cfg.min_core_digits:
        rel = 0
    gap = days_apart(bk.doc_date, pt.doc_date)
    same_gstin = bk.supplier_gstin == pt.supplier_gstin
    eq = _amounts_equal(bk, pt, tol)
    head = _head_mismatch(bk, pt, tol)
    near = gap is not None and gap <= cfg.date_window_days

    def mk(status, score):
        return Pair([bk], [pt], status, score, rel, gap,
                    round(pt.tax - bk.tax, 2), round(pt.taxable - bk.taxable, 2))

    if not same_gstin:
        if rel in (1, 2, 3) and (eq or head):
            return mk(Status.OTHER_GSTIN, 70 - rel)
        return None
    if head and rel in (1, 2, 3, 4):
        return mk(Status.HEAD_MISMATCH, 76 - rel)
    if eq:
        if rel == 1:
            return mk(Status.EXACT, 100) if gap == 0 else mk(Status.DATE_DIFF, 94)
        if rel in (2, 3):
            return mk(Status.FORMAT_DIFF, 92 - rel) if (gap is None or gap <= 45) else None
        if rel == 4 and (near or gap is None):
            return mk(Status.TYPO, 80)
        if rel == 0 and gap == 0 and k3(bk.doc_no) and k3(bk.doc_no) == k3(pt.doc_no):
            return mk(Status.FORMAT_DIFF, 85)   # e.g. '4' vs 'NO/4/26-27' on the same day, same amounts
        if rel == 0 and gap == 0 and is_typo(bk.doc_no, pt.doc_no, min_len=2):
            return mk(Status.TYPO, 78)          # short numbers: only with same date and amounts
        if rel == 0 and gap == 0:
            return mk(Status.PROBABLE, 40)
        return None
    # Amount differences only when the invoice number itself agrees. A number that is
    # one digit off with a different amount is usually the supplier's NEXT invoice.
    if rel in (1, 2) or (rel == 3 and gap is not None and gap <= 31):
        return mk(Status.VALUE_DIFF, 60 - rel)
    return None


def _core(doc_no: str) -> str:
    from .normalize import k3
    return k3(doc_no)


def match_one_to_one(books: list[Doc], portal: list[Doc], cfg: Config, exclude: set | None = None):
    """Assign pairs one-to-one, strongest first. `exclude` skips statuses
    (used to hold weak pairings back until split invoices are found)."""
    by_key = defaultdict(list)
    for p in portal:
        by_key[(p.pan, p.doc_type)].append(p)
    cands: list[Pair] = []
    for b in books:
        for p in by_key.get((b.pan, b.doc_type), []):
            pr = score_pair(b, p, cfg)
            if pr and not (exclude and pr.status in exclude):
                cands.append(pr)
    # strongest first; ties -> closer dates, smaller differences
    cands.sort(key=lambda c: (-c.score, c.date_gap if c.date_gap is not None else 999,
                              abs(c.tax_diff) + abs(c.taxable_diff)))
    used_b, used_p, pairs = set(), set(), []
    for c in cands:
        b, p = c.books[0], c.portal[0]
        if b.uid in used_b or p.uid in used_p:
            continue
        used_b.add(b.uid)
        used_p.add(p.uid)
        pairs.append(c)
    rest_b = [b for b in books if b.uid not in used_b]
    rest_p = [p for p in portal if p.uid not in used_p]
    return pairs, rest_b, rest_p


def _subset_match(target: Doc, pool: list[Doc], cfg: Config):
    tol = cfg.amount_tolerance
    pool = [d for d in pool
            if d.doc_type == target.doc_type
            and (days_apart(d.doc_date, target.doc_date) or 0) <= cfg.split_window_days
            and d.taxable <= target.taxable + tol and d.tax <= target.tax + tol]
    pool = sorted(pool, key=lambda d: days_apart(d.doc_date, target.doc_date) or 0)[:cfg.split_max_candidates]
    for size in range(2, cfg.split_max_parts + 1):
        for combo in combinations(pool, size):
            if (abs(sum(d.taxable for d in combo) - target.taxable) <= tol * size and
                    abs(sum(d.tax for d in combo) - target.tax) <= tol * size):
                return list(combo)
    return None


def match_splits(books: list[Doc], portal: list[Doc], cfg: Config):
    """One books entry = several portal invoices (or the reverse), same GSTIN."""
    pairs = []
    used_b, used_p = set(), set()
    p_by_g = defaultdict(list)
    b_by_g = defaultdict(list)
    for p in portal:
        p_by_g[p.supplier_gstin].append(p)
    for b in books:
        b_by_g[b.supplier_gstin].append(b)
    for b in sorted(books, key=lambda d: -d.tax):
        pool = [p for p in p_by_g.get(b.supplier_gstin, []) if p.uid not in used_p]
        if len(pool) < 2:
            continue
        combo = _subset_match(b, pool, cfg)
        if combo:
            used_b.add(b.uid)
            used_p.update(p.uid for p in combo)
            pairs.append(Pair([b], combo, Status.SPLIT, 65))
    for p in sorted(portal, key=lambda d: -d.tax):
        if p.uid in used_p:
            continue
        pool = [b for b in b_by_g.get(p.supplier_gstin, []) if b.uid not in used_b]
        if len(pool) < 2:
            continue
        combo = _subset_match(p, pool, cfg)
        if combo:
            used_p.add(p.uid)
            used_b.update(b.uid for b in combo)
            pairs.append(Pair(combo, [p], Status.SPLIT, 65))
    return pairs, [b for b in books if b.uid not in used_b], [p for p in portal if p.uid not in used_p]


def find_duplicates(books: list[Doc]) -> list[list[Doc]]:
    """Same supplier GSTIN + same normalised invoice no. + same type + same tax, booked twice."""
    from .normalize import k2
    groups = defaultdict(list)
    for b in books:
        groups[(b.supplier_gstin, k2(b.doc_no), b.doc_type, round(b.tax))].append(b)
    return [g for g in groups.values() if len(g) > 1]
