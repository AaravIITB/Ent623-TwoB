"""Fix up books entries before matching.

Real purchase registers leave gaps that a person fills from memory:
  * the supplier's GSTIN is blank on the voucher (ledger master not updated), but the
    name, PAN or invoice number makes the supplier obvious;
  * the entry carries no GST at all (diesel, rent paid to an individual, an advance
    against a proforma invoice), so there is nothing to find in 2B.
This module fills what can be filled, says so on the record, and never guesses
between two candidates.
"""
from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from .models import Doc
from .normalize import k1, k2

# only legal-form words are dropped: 'Services', 'Enterprises', 'India' tell suppliers apart
_SUFFIX = re.compile(r"\b(m/?s|messrs|the|private|pvt|p|limited|ltd|llp|inc|incorporated|corp|corporation|company|"
                     r"co|opc|plc)\b")
_BRANCH = re.compile(r"^(?:[a-z]{2}|unit|branch|plant|\d+)$")     # '- TN', 'unit 2'


def name_key(name: str) -> str:
    s = (name or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = _SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def name_score(a: str, b: str) -> float:
    """0..1 similarity of two supplier names after removing legal-form words."""
    ka, kb = name_key(a), name_key(b)
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    ta, tb = set(ka.split()), set(kb.split())
    jac = len(ta & tb) / len(ta | tb)
    seq = SequenceMatcher(None, ka, kb).ratio()
    first = ka.split()[0] == kb.split()[0]
    return max(jac, seq) * (1.0 if first else 0.8)


def same_name(a: str, b: str) -> bool:
    """Equal after removing legal-form words, or equal except for a branch / state tag ('Uno Minda - TN')."""
    ka, kb = name_key(a), name_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    ta, tb = ka.split(), kb.split()
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if long_[:len(short)] == short and all(_BRANCH.match(t) for t in long_[len(short):]):
        return True
    return False


def load_vendor_master(path) -> dict:
    """GSTIN -> {name, pan, activity, eligible} from a firm's vendor master (Excel/CSV, any layout with a GSTIN
    column and a name column)."""
    import pandas as pd
    from .loaders.common import clean_name, clean_text, norm_header, yes
    from . import gstin as G
    path = __import__("pathlib").Path(path)
    if path.suffix.lower() == ".csv":
        sheets = {"csv": pd.read_csv(path, header=None, dtype=object)}
    else:
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
    out = {}
    for df in sheets.values():
        for r in range(min(15, len(df))):
            heads = [norm_header(x) for x in df.iloc[r].tolist()]
            gi = next((i for i, h in enumerate(heads) if h in ("gstin", "gstinuin", "vendorgstin", "suppliergstin",
                                                              "gstinno", "partygstin")), None)
            ni = next((i for i, h in enumerate(heads) if h in ("vendorname", "suppliername", "name", "partyname",
                                                              "ledgername", "particulars", "legalname", "tradename")), None)
            if gi is None or ni is None:
                continue
            ai = next((i for i, h in enumerate(heads) if h in ("activity", "natureofactivity", "natureofexpense",
                                                              "expensehead", "category", "ledger")), None)
            ei = next((i for i, h in enumerate(heads) if h.startswith("itcelig") or h in ("eligibility", "eligible")),
                      None)
            pi = next((i for i, h in enumerate(heads) if h in ("pan", "panno", "pannumber")), None)
            for k in range(r + 1, len(df)):
                row = df.iloc[k].tolist()
                g = G.clean(row[gi]) if row[gi] is not None and str(row[gi]) != "nan" else ""
                if len(g) != 15:
                    continue
                out[g] = {"name": clean_name(row[ni]), "activity": clean_text(row[ai]) if ai is not None else "",
                          "eligible": yes(clean_text(row[ei])) if ei is not None else None,
                          "pan": clean_text(row[pi]).upper() if pi is not None else ""}
            break
    return out


def apply_vendor_master(docs: list[Doc], master: dict) -> None:
    """Give records the firm's Activity / eligibility when their own row has none."""
    for d in docs:
        m = master.get(d.supplier_gstin)
        if not m:
            continue
        if not d.ledger and m.get("activity"):
            d.ledger = m["activity"]
        if d.eligible is None and m.get("eligible") is not None:
            d.eligible = m["eligible"]


def resolve_missing_gstins(books: list[Doc], portal: list[Doc], known: list[Doc] | None = None,
                           master: dict | None = None, tol: float = 1.0) -> list[str]:
    """Fill a blank books GSTIN from (1) the PAN column, (2) the vendor master, (3) the same invoice number
    in 2B under a similar name and with the same tax, (4) a unique supplier whose name is the same once
    legal-form words are removed. Never chooses between two candidates."""
    notes = []
    missing = [b for b in books if not b.supplier_gstin]
    if not missing:
        return notes
    pool = [d for d in list(portal) + list(known or []) + [b for b in books if b.supplier_gstin]]
    by_pan = defaultdict(set)
    by_name = defaultdict(set)
    names = {}
    by_no = defaultdict(list)
    for d in pool:
        by_pan[d.pan].add(d.supplier_gstin)
        if d.supplier_name:
            by_name[name_key(d.supplier_name)].add(d.supplier_gstin)
            names.setdefault(d.supplier_gstin, d.supplier_name)
        for key in {k1(d.doc_no), k2(d.doc_no)}:
            if key and len(key) >= 3:
                by_no[key].append(d)
    for g, m in (master or {}).items():
        by_pan[g[2:12]].add(g)
        if m.get("name"):
            by_name[name_key(m["name"])].add(g)
            names.setdefault(g, m["name"])
    by_first = defaultdict(set)                     # first word -> GSTINs, keeps the name search small
    for k, gs in by_name.items():
        if k:
            by_first[k.split()[0]].update(gs)
    filled = 0
    for b in missing:
        pan = next((n[4:] for n in b.notes if n.startswith("pan:")), "")
        got, how = "", ""
        if pan and by_pan.get(pan):
            cands = by_pan[pan]
            if len(cands) > 1 and b.doc_no:
                hit = {d.supplier_gstin for key in {k1(b.doc_no), k2(b.doc_no)} for d in by_no.get(key, [])}
                cands = (cands & hit) or cands
            if len(cands) == 1:
                got, how = next(iter(cands)), f"PAN {pan}"
        if not got and b.doc_no:
            docs = {d.uid: d for key in {k1(b.doc_no), k2(b.doc_no)} for d in by_no.get(key, [])}.values()
            cands = set()
            for d in docs:
                sc = name_score(b.supplier_name, d.supplier_name or names.get(d.supplier_gstin, ""))
                same_tax = abs(abs(d.tax) - abs(b.tax)) <= max(tol, 0.001 * abs(b.tax))
                if sc >= 0.85 or (sc >= 0.6 and same_tax):
                    cands.add(d.supplier_gstin)
            if len(cands) == 1:
                g = next(iter(cands))
                got, how = g, f"invoice no. '{b.doc_no}' under '{names.get(g, g)}'"
        if not got and b.supplier_name:
            key = name_key(b.supplier_name)
            exact = by_name.get(key, set())
            if len(exact) == 1:
                g = next(iter(exact))
                got, how = g, f"supplier name '{names.get(g, '')}'"
            elif not exact and key:
                near = {g for g in by_first.get(key.split()[0], set()) if same_name(b.supplier_name, names.get(g, ""))}
                if len(near) == 1:
                    g = next(iter(near))
                    got, how = g, f"supplier name '{names.get(g)}' (branch tag differs)"
        if got:
            b.supplier_gstin = got
            b.notes.append(f"GSTIN {got} was blank in books; taken from {how}")
            filled += 1
    if filled:
        notes.append(f"{filled} of {len(missing)} books rows without a GSTIN were linked to a supplier by PAN, "
                     "vendor master, invoice no. or name - the record says how; update the ledger master.")
    left = len(missing) - filled
    if left:
        notes.append(f"{left} books rows still have no supplier GSTIN (unregistered suppliers or names not "
                     "found in 2B).")
    return notes
