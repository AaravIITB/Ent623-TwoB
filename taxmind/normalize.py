"""Invoice-number normalisation and similarity.

Suppliers and accountants write the same invoice number in many ways:
  'INV/26-27/0045', 'INV-0045', 'inv 45', '45', 'GST/2026-27/045', 'O45' (letter O).
We build three keys, from strict to loose:
  k1  upper-case, separators removed          'INV/26-27/0045' -> 'INV26270045'
  k2  k1 minus financial-year tokens and
      leading zeros in digit runs             -> 'INV45'
  k3  the last run of digits, no leading 0s   -> '45'
"""
from __future__ import annotations

import re
from datetime import date
from functools import lru_cache

_SEP = re.compile(r"[^0-9A-Z]")
def _is_year(t: str) -> bool:
    if len(t) == 2:
        return 15 <= int(t) <= 45
    return len(t) == 4 and t.startswith("20") and 15 <= int(t[2:]) <= 45


def _consecutive(a: str, b: str) -> bool:
    return (int(a[-2:]) + 1) % 100 == int(b[-2:])


def _strip_fy(s: str) -> str:
    """Remove financial-year tokens: '26-27', '2026-27', '2026/2027', 'FY 26-27', '202627'.

    Works on digit runs so that '159/26-27' correctly loses only '26-27'.
    """
    s = re.sub(r"FY\s*(?=\d)", "", s)
    parts = re.split(r"(\d+)", s)            # text, digits, text, digits, ...
    digit_at = list(range(1, len(parts), 2))
    drop = set()
    for i, j in zip(digit_at, digit_at[1:]):
        if i in drop:
            continue
        sep = parts[i + 1].strip()
        if sep in ("-", "/") and _is_year(parts[i]) and _is_year(parts[j]) and _consecutive(parts[i], parts[j]):
            drop.update((i, j))
            parts[i + 1] = ""
    for i in digit_at:
        t = parts[i]
        if i not in drop and len(t) in (6, 8) and t.startswith("20"):
            y1, y2 = t[:4], t[4:]
            if _is_year(y1) and _is_year(y2) and _consecutive(y1, y2):
                drop.add(i)
    return "".join("" if i in drop else x for i, x in enumerate(parts))


def _fix_ocr_letters(s: str) -> str:
    """Letter O / I / L sitting between digits is almost always 0 / 1."""
    s = re.sub(r"(?<=\d)O|O(?=\d)", "0", s)
    s = re.sub(r"(?<=\d)[IL](?=\d)", "1", s)
    return s


@lru_cache(maxsize=200_000)
def k1(doc_no: str) -> str:
    return _SEP.sub("", str(doc_no or "").upper())


@lru_cache(maxsize=200_000)
def k2(doc_no: str) -> str:
    s = str(doc_no or "").upper()
    s = _strip_fy(s)
    s = _fix_ocr_letters(s)
    s = _SEP.sub("", s)
    s = re.sub(r"\d+", lambda m: m.group(0).lstrip("0") or "0", s)
    return s


@lru_cache(maxsize=200_000)
def serial_runs(doc_no: str) -> tuple:
    """Digit runs that make up the serial: financial years and standalone years removed.
    'INV/045/2026' -> ('45',), 'SEP/0012/26' -> ('12',), 'SA-1203' -> ('1203',)."""
    s = _fix_ocr_letters(_strip_fy(str(doc_no or "").upper()))
    runs = re.findall(r"\d+", s)
    trailing_yy = re.search(r"[-/]\s*(\d{2})\s*$", s)     # '.../26' at the very end
    if len(runs) > 1:
        keep = []
        for i, r in enumerate(runs):
            is_year = (len(r) == 4 and r.startswith("20") and 15 <= int(r[2:]) <= 45) or \
                      (len(r) == 2 and i == len(runs) - 1 and trailing_yy and 15 <= int(r) <= 45)
            if not is_year:
                keep.append(r)
        runs = keep or runs
    return tuple(r.lstrip("0") or "0" for r in runs)


def k3(doc_no: str) -> str:
    """The core serial number (last serial digit run)."""
    runs = serial_runs(doc_no)
    return runs[-1] if runs else ""


def digits(doc_no: str) -> str:
    """All serial digits in order, e.g. 'PO12/INV45' -> '1245'."""
    return "".join(serial_runs(doc_no))


def edit_distance(a: str, b: str, cap: int = 3) -> int:
    """Damerau-Levenshtein (optimal string alignment), early exit above cap."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    la, lb = len(a), len(b)
    prev2 = None
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and prev2 is not None and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > cap:
            return cap + 1
        prev2, prev = prev, cur
    return prev[lb]


@lru_cache(maxsize=500_000)
def doc_relation(a: str, b: str) -> int:
    """How strongly two invoice numbers look like the same document.

    1 = identical ignoring separators/case
    2 = identical after removing FY tokens / leading zeros / O-vs-0
    3 = same trailing number (prefixes differ, e.g. 'INV/045' vs '45')
    4 = one character apart (typo / transposition)
    0 = unrelated
    """
    a1, b1 = k1(a), k1(b)
    if not a1 or not b1:
        return 0
    if a1 == b1:
        return 1
    a2, b2 = k2(a), k2(b)
    if a2 and a2 == b2:
        return 2
    a3, b3 = k3(a), k3(b)
    if a3 and a3 == b3 and len(a3) >= 2 and digits(a) == digits(b):
        return 3
    if is_typo(a, b, min_len=4):
        return 4
    return 0


@lru_cache(maxsize=200_000)
def _kz(doc_no: str) -> str:
    """Like k2 but keeps leading zeros (so 1083 vs 0083 is one edit, not two)."""
    s = _fix_ocr_letters(_strip_fy(str(doc_no or "").upper()))
    return _SEP.sub("", s)


def within_one(x: str, y: str) -> bool:
    """True if x and y differ by at most one substitution, insertion, deletion or
    adjacent swap. Linear time (no full edit-distance table)."""
    if x == y:
        return True
    lx, ly = len(x), len(y)
    if abs(lx - ly) > 1:
        return False
    i = 0
    while i < min(lx, ly) and x[i] == y[i]:
        i += 1
    if lx == ly:
        if x[i + 1:] == y[i + 1:]:
            return True                                   # substitution
        return i + 1 < lx and x[i] == y[i + 1] and x[i + 1] == y[i] and x[i + 2:] == y[i + 2:]  # swap
    if lx > ly:
        return x[i + 1:] == y[i:]                         # deletion
    return x[i:] == y[i + 1:]                             # insertion


@lru_cache(maxsize=500_000)
def is_typo(a: str, b: str, min_len: int = 4) -> bool:
    """One character apart (substitution, insertion, deletion or swap)."""
    for x, y in ((k2(a), k2(b)), (_kz(a), _kz(b))):
        if x and y and max(len(x), len(y)) >= min_len and within_one(x, y):
            return True
    return False


def days_apart(d1: date | None, d2: date | None) -> int | None:
    if d1 is None or d2 is None:
        return None
    return abs((d1 - d2).days)
