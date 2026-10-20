"""GSTR-2B / GSTR-2A / IMS JSON downloads from the GST portal.

GSTR-2B JSON nests documents as data -> docdata -> b2b[] -> inv[] (invoices) and
cdnr[] -> nt[] (credit/debit notes); amendments sit in b2ba / cdnra. Older GSTR-2A
and GSTR-1 style files put b2b at the top level with itms[].itm_det. Both are read.

IMS downloads are read by a tolerant walker that finds any record carrying a
supplier GSTIN and a document number, plus the IMS action if present.
NOTE: field names for IMS are best-effort until we see real files.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..models import Doc, DocType, Side
from .. import gstin as G
from .common import ims_action, to_date, to_float, to_period, yes

_DOC_KEYS = ("inum", "ntnum", "nt_num", "docnum", "doc_num", "invno", "invoice_number", "documentnumber")
_GSTIN_KEYS = ("ctin", "stin", "sgstin", "supplier_gstin", "suppliergstin", "gstin")
_TAX_KEYS = {
    "taxable": ("txval", "taxable_value", "taxablevalue"),
    "igst": ("igst", "iamt"),
    "cgst": ("cgst", "camt"),
    "sgst": ("sgst", "samt"),
    "cess": ("cess", "csamt"),
}


def _first(d: dict, keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _amounts(rec: dict) -> dict:
    """Invoice-level values if present, else sum the item rows."""
    out = {k: 0.0 for k in _TAX_KEYS}
    if any(k in rec for keys in _TAX_KEYS.values() for k in keys):
        for f, keys in _TAX_KEYS.items():
            out[f] = to_float(_first(rec, keys, 0))
        return out
    items = rec.get("items") or rec.get("itms") or []
    for it in items:
        det = it.get("itm_det", it) if isinstance(it, dict) else {}
        for f, keys in _TAX_KEYS.items():
            out[f] += to_float(_first(det, keys, 0))
    return out


def _make(rec, sup, period, source, uid, doc_type, n):
    amt = _amounts(rec)
    ctin = G.clean(_first(sup, _GSTIN_KEYS, "") or _first(rec, _GSTIN_KEYS, ""))
    itc = yes(rec.get("itcavl"))
    return Doc(
        side=Side.PORTAL, uid=f"{uid}{n}", supplier_gstin=ctin,
        doc_no=str(_first(rec, _DOC_KEYS, "")).strip(),
        doc_date=to_date(_first(rec, ("dt", "nt_dt", "idt", "docdt", "doc_date"))),
        taxable=round(amt["taxable"], 2), igst=round(amt["igst"], 2), cgst=round(amt["cgst"], 2),
        sgst=round(amt["sgst"], 2), cess=round(amt["cess"], 2), doc_type=doc_type,
        supplier_name=str(sup.get("trdnm") or sup.get("lglnm") or rec.get("trdnm") or ""),
        total_value=to_float(rec.get("val")) if rec.get("val") is not None else None,
        pos=str(rec.get("pos") or ""), reverse_charge=(yes(rec.get("rev")) is True),
        itc_available=itc, itc_unavailable_reason=str(rec.get("rsn") or ""),
        period=period, supplier_filing_date=to_date(sup.get("supfildt") or rec.get("supfildt")),
        irn=str(rec.get("irn") or ""),
        ims_action=ims_action(_first(rec, ("action", "actn", "ims_action", "imsactn"), "")) if
        _first(rec, ("action", "actn", "ims_action", "imsactn")) is not None else "",
        source=source,
    )


def _note_type(rec) -> DocType:
    t = str(_first(rec, ("typ", "ntty", "nttyp", "doctyp"), "C")).upper()
    return DocType.DEBIT_NOTE if t.startswith("D") else DocType.CREDIT_NOTE


def load(path: str | Path, uid_prefix: str = "P") -> tuple[list[Doc], list[str]]:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    notes: list[str] = []
    root = raw.get("data", raw) if isinstance(raw, dict) else {}
    period = to_period(root.get("rtnprd") or raw.get("rtnprd") or root.get("fp") or raw.get("fp") or "")
    docdata = root.get("docdata", root)
    known = {"b2b", "b2ba", "cdnr", "cdnra"}
    if not isinstance(docdata, dict) or not (known & set(docdata)):
        docs = _walk_generic(raw, path.name, uid_prefix, period)
        notes.append(f"{path.name}: read {len(docs)} records with the generic (IMS) reader")
        return docs, notes

    docs: list[Doc] = []
    n = 0
    sections = [("b2b", "inv", None), ("cdnr", "nt", "note"), ("b2ba", "inv", None), ("cdnra", "nt", "note")]
    amended: dict[tuple, Doc] = {}
    for sec, inner, kind in sections:
        for sup in docdata.get(sec, []) or []:
            sup_period = to_period(sup.get("supprd")) or period
            for rec in sup.get(inner, []) or []:
                n += 1
                dt = _note_type(rec) if kind else DocType.INVOICE
                d = _make(rec, sup, period or sup_period, f"{path.name}:{sec}", uid_prefix, dt, n)
                if sec.endswith("a"):
                    orig = str(rec.get("oinum") or rec.get("ontnum") or "")
                    amended[(d.supplier_gstin, orig)] = d
                    d.source += f" (amends {orig})"
                else:
                    docs.append(d)
    if amended:
        docs = [d for d in docs if (d.supplier_gstin, d.doc_no) not in amended] + list(amended.values())
        notes.append(f"{path.name}: applied {len(amended)} amendments (b2ba/cdnra)")
    skipped = [s for s in ("isd", "isda", "impg", "impgsez", "ecom", "ecoma") if docdata.get(s)]
    if skipped:
        notes.append(f"{path.name}: sections not reconciled here (imports/ISD/e-com): {', '.join(skipped)}")
    if not period:
        notes.append(f"{path.name}: no return period found in file; set it manually")
    return docs, notes


def _walk_generic(obj, fname, prefix, period, parent=None, out=None, ctx=None):
    """Find any dict with a document number and a supplier GSTIN (own or inherited)."""
    if out is None:
        out, ctx = [], {"n": 0}
    if isinstance(obj, dict):
        g = _first(obj, _GSTIN_KEYS)
        here_parent = obj if g else parent
        local_period = to_period(_first(obj, ("rtnprd", "fp", "supprd"), "")) or period
        if _first(obj, _DOC_KEYS) is not None and (g or (parent and _first(parent, _GSTIN_KEYS))):
            ctx["n"] += 1
            sup = obj if g else parent
            dt_raw = str(_first(obj, ("doctyp", "typ", "ntty", "doc_type"), "INV")).upper()
            dt = (DocType.CREDIT_NOTE if dt_raw in ("C", "CN", "CRN", "CREDIT NOTE") else
                  DocType.DEBIT_NOTE if dt_raw in ("D", "DN", "DBN", "DEBIT NOTE") else DocType.INVOICE)
            d = _make(obj, sup, local_period, f"{fname}:ims", prefix, dt, ctx["n"])
            if not d.ims_action:
                d.ims_action = ims_action(_first(obj, ("status", "act", "imsstatus"), "")) or ""
            out.append(d)
        else:
            for k, v in obj.items():
                _walk_generic(v, fname, prefix, local_period, here_parent, out, ctx)
    elif isinstance(obj, list):
        for v in obj:
            _walk_generic(v, fname, prefix, period, parent, out, ctx)
    return out
