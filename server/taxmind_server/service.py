"""Bridge between the web app and the TaxMind engine.

A reconciliation run is deterministic for the same files, settings, vendor master and prior ledger,
so everything needed to repeat it exactly is stored on the period (run_settings_json). The engine's
Result is kept in a small in-memory cache and rebuilt on demand (exports, Table 4, close pack).
Staff decisions live in the database and are tied to findings by a stable key, so they survive re-runs.
"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from .db import ActivityRow, Client, DecisionRow, FollowUpRow, Period, jdump, jload, now

import taxmind  # noqa: E402  (path set by settings)
from taxmind import Config, Side, load_file, reconcile
from taxmind.closepack import Decision as CloseDecision
from taxmind.gstr3b import LedgerItem, after_decisions
from taxmind.models import Action, Status
from taxmind.prepare import load_vendor_master
from taxmind.recommend import period_label

ACTIONS = [a.value for a in Action]
STATUS_LABELS = {s.name: s.value for s in Status}
_STATUS_CODE = {s.value: s.name for s in Status}
DEFAULT_SETTINGS = {"tolerance": 1.0, "tolerance_pct": 0.0, "line_of_business": [], "policy": "pending"}

_cache: "OrderedDict[tuple, object]" = OrderedDict()
_lock = threading.Lock()


# ── small helpers ────────────────────────────────────────────────────────────

def settings_of(client: Client) -> dict:
    s = dict(DEFAULT_SETTINGS)
    s.update(jload(client.settings_json, {}) or {})
    return s


def deadlines(period: str) -> tuple[date, date]:
    m, y = int(period[:2]), int(period[2:])
    m, y = (1, y + 1) if m == 12 else (m + 1, y)
    return date(y, m, 14), date(y, m, 20)


def prev_month(period: str) -> str:
    m, y = int(period[:2]), int(period[2:])
    return f"{12 if m == 1 else m - 1:02d}{y - (m == 1)}"


def pkey(p: str) -> str:
    return p[2:] + p[:2]


def default_period(today: date | None = None) -> str:
    t = today or date.today()
    return prev_month(f"{t.month:02d}{t.year}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def log(db: Session, user: str, client: Client | None, period: str, action: str, detail: str = ""):
    db.add(ActivityRow(user=user, client_id=client.id if client else None, client=client.name if client else "",
                       period=period, action=action, detail=detail[:2000]))


def doc_key(d) -> str:
    """What a record IS (supplier, type, number, date, tax) - not where it sits in a file, so inserting a
    row or renaming a file doesn't detach a staff decision, but a changed amount does."""
    from taxmind.normalize import k2
    dd = d.doc_date.isoformat() if d.doc_date else ""
    return f"{d.side.value}|{d.supplier_gstin}|{d.doc_type.value}|{k2(d.doc_no) or d.doc_no}|{dd}|{round(d.tax)}"


def finding_key(f) -> str:
    return "||".join(sorted(doc_key(d) for d in f.books + f.portal))[:560]


_running: set = set()


def is_running(period_id: int) -> bool:
    return period_id in _running


def doc_out(d) -> dict:
    return {"side": d.side.value, "doc_no": d.doc_no, "doc_date": d.doc_date.isoformat() if d.doc_date else None,
            "doc_type": d.doc_type.value, "supplier_gstin": d.supplier_gstin, "supplier_name": d.supplier_name,
            "taxable": round(d.taxable, 2), "igst": round(d.igst, 2), "cgst": round(d.cgst, 2),
            "sgst": round(d.sgst, 2), "cess": round(d.cess, 2), "tax": round(d.tax, 2), "period": d.period,
            "itc_available": d.itc_available, "reverse_charge": bool(d.reverse_charge), "source": d.source,
            "row_ref": d.row_ref, "ledger": d.ledger or "", "description": (d.description or "")[:500],
            "voucher_no": getattr(d, "voucher_no", "") or "",
            "notes": [n for n in getattr(d, "notes", []) if not n.startswith("pan:")]}


# ── running the engine ──────────────────────────────────────────────────────

def _load_inputs(spec: dict):
    books, portal, notes = [], [], []
    for i, f in enumerate(spec["books"]):
        d, n = load_file(f["path"], Side.BOOKS, f"B{i + 1}-")
        books += d
        notes += n
    for i, f in enumerate(spec["portal"]):
        d, n = load_file(f["path"], Side.PORTAL, f"P{i + 1}-", f.get("period_hint") or "")
        portal += d
        notes += n
    return books, portal, notes


def _config(spec: dict) -> Config:
    s = spec["settings"]
    return Config(amount_tolerance=float(s.get("tolerance", 1.0)), amount_tolerance_pct=float(s.get("tolerance_pct", 0)),
                  line_of_business=",".join(s.get("line_of_business") or []), client_gstin=spec.get("client_gstin", ""),
                  not_in_books_policy=s.get("policy", "pending"))


def _run(spec: dict):
    books, portal, notes = _load_inputs(spec)
    master = load_vendor_master(spec["vendor_master"]) if spec.get("vendor_master") and \
        Path(spec["vendor_master"]).exists() else None
    fields = ("gstin", "doc_no", "doc_date", "period_reversed", "igst", "cgst", "sgst", "cess", "reason", "supplier")
    prior = [LedgerItem(**{k: it.get(k, "" if k in ("gstin", "doc_no", "doc_date", "period_reversed", "reason",
                                                     "supplier") else 0.0) for k in fields})
             for it in spec.get("prior_ledger", [])] or None
    res = reconcile(books, portal, period=spec["period"], client=spec.get("client_name", ""), cfg=_config(spec),
                    notes=notes, prior_ledger=prior, vendor_master=master)
    return res


def result_for(period: Period):
    """The engine Result of the period's latest run (cached; re-run from the stored spec if needed)."""
    if not period.run_no:
        return None
    k = (period.id, period.run_no)
    with _lock:
        if k in _cache:
            _cache.move_to_end(k)
            return _cache[k]
    res = _run(jload(period.run_settings_json, {}))
    with _lock:
        _cache[k] = res
        while len(_cache) > 12:
            _cache.popitem(last=False)
    return res


def previous_ledger(db: Session, period: Period) -> list[dict]:
    """Open reversal-ledger items from the month just before this one, if that month is closed."""
    prev = next((p for p in period.client.periods if p.period == prev_month(period.period)), None)
    if prev is None or prev.status != "closed":
        return []
    return jload(prev.ledger_json, []) or []


def ledger_warning(period: Period) -> str:
    prev = next((p for p in period.client.periods if p.period == prev_month(period.period)), None)
    if prev is not None and prev.status != "closed" and prev.run_no:
        return (f"{label(prev.period)} is not closed, so its reversal ledger was not brought into this month. "
                f"Close {label(prev.period)} and reconcile again to reclaim its reversals.")
    return ""


_run_locks: dict = {}


def run_period(db: Session, period: Period, user: str) -> Period:
    """One run at a time per month: a second click waits for the first instead of racing it."""
    with _lock:
        lk = _run_locks.setdefault(period.id, threading.Lock())
    with lk:
        _running.add(period.id)
        try:
            db.refresh(period)
            return _run_period(db, period, user)
        finally:
            _running.discard(period.id)


def _run_period(db: Session, period: Period, user: str) -> Period:
    client = period.client
    books = [f for f in period.files if f.role == "books"]
    portal = [f for f in period.files if f.role == "portal"]
    if not books or not portal:
        raise ValueError("Upload the purchase register and at least one GSTR-2B / IMS file first.")
    spec = {
        "period": period.period, "client_name": client.name, "client_gstin": client.gstin,
        "settings": settings_of(client),
        "books": [{"path": f.path, "name": f.filename} for f in books],
        "portal": [{"path": f.path, "name": f.filename, "period_hint": f.period_hint} for f in portal],
        "vendor_master": client.vendor_master_path or "",
        "prior_ledger": previous_ledger(db, period),
    }
    res = _run(spec)
    if not any(True for _ in res.findings):
        raise ValueError("Nothing was read from the files - check that they are a purchase register and a GSTR-2B.")
    s0 = res.summary
    if not s0["books_entries"]:
        raise ValueError("No purchase entries were read from the books file(s). Check the file: it needs the "
                         "supplier GSTIN or name, invoice no. and tax columns.")
    if not s0["portal_records"]:
        raise ValueError(f"No GSTR-2B records for {label(period.period)} were read. Check that the 2B file is for "
                         "this month (or enter its month when uploading).")
    old: dict = {}
    for d in db.query(DecisionRow).filter_by(period_id=period.id).order_by(DecisionRow.id):
        old.setdefault(d.key, []).append(d)
    old_fu = {f.supplier_gstin: f for f in db.query(FollowUpRow).filter_by(period_id=period.id)}
    db.query(FollowUpRow).filter_by(period_id=period.id).delete()
    carried = changed = 0
    memory = history(db, period)
    seen: dict = {}
    keep_ids = set()
    for f in res.findings:
        new = decision_row(period, f)
        n = seen.get(new.key, 0)
        seen[new.key] = n + 1
        if n:                                   # the same record twice in one run (e.g. booked twice)
            new.key = f"{new.key}#{n}"[:600]
        h = memory.get((new.supplier_gstin, new.status_code))
        if h:
            data = jload(new.data_json, {})
            data["history"] = h
            new.data_json = jdump(data)
        prevs = old.get(new.key) or []
        prev = prevs.pop(0) if prevs else None
        if prev is None:
            db.add(new)
            continue
        # update in place: the decision keeps its id, so open screens and links stay valid
        old_status = prev.status_code
        for col in ("fid", "status", "status_code", "recommended", "confidence", "owner", "needs_human", "blocked",
                    "supplier_gstin", "supplier_name", "itc_in_2b", "itc_in_books", "itc_to_claim", "itc_at_stake",
                    "in_period_2b", "all_available", "search", "data_json"):
            setattr(prev, col, getattr(new, col))
        keep_ids.add(prev.id)
        if prev.final and old_status != new.status_code:
            # same records, but the situation changed (e.g. now a tax-head mismatch): ask again
            prev.note = (f"[Earlier decision '{prev.final}' cleared: the situation changed to '{new.status}'.] "
                         + (prev.note or ""))[:2000]
            prev.final = None
            changed += 1
        elif prev.final or prev.note or prev.assignee_id:
            carried += 1
        if prev.final and prev.final not in ACTIONS:
            prev.final = None
    for rows in old.values():
        for d in rows:
            if d.id not in keep_ids:
                if d.final or d.note:
                    changed += 1
                db.delete(d)
    contacts = _known_contacts(db, client, period)
    for m in res.supplier_messages:
        prev = old_fu.get(m.supplier_gstin)
        c = contacts.get(m.supplier_gstin, ("", ""))
        db.add(FollowUpRow(period_id=period.id, supplier_gstin=m.supplier_gstin, supplier_name=m.supplier_name,
                           items=m.items, itc_at_stake=round(m.itc_at_stake, 2), whatsapp=m.whatsapp,
                           email_subject=m.email_subject, email_body=m.email_body,
                           contact_email=prev.contact_email if prev else c[0],
                           contact_phone=prev.contact_phone if prev else c[1],
                           status=prev.status if prev else "to_send", note=prev.note if prev else "",
                           sent_at=prev.sent_at if prev else None))
    period.run_no += 1
    period.run_at, period.run_by = now(), user
    period.run_settings_json = jdump(spec)
    period.prior_ledger_json = jdump(spec["prior_ledger"])
    period.summary_json = jdump(res.summary)
    period.checks_json = jdump([c.__dict__ for c in res.checks])
    extra = [f"{carried} decisions from the previous run were kept."] if carried else []
    if changed:
        extra.append(f"{changed} earlier decisions were dropped because their records changed (amount, date or "
                     "number) or are no longer in the files - check those suppliers again.")
    warn = ledger_warning(period)
    if warn:
        extra.append(warn)
    period.notes_json = jdump(res.notes + extra)
    period.stale = False
    period.status = "reconciled"
    with _lock:
        _cache[(period.id, period.run_no)] = res
    log(db, user, client, period.period, "reconciled",
        f"{res.summary['findings']} decisions, {res.summary['needs_human']} need a person, "
        f"{res.summary['auto_cleared']} cleared automatically")
    db.commit()
    return period


def _known_contacts(db: Session, client: Client, period: Period) -> dict:
    ids = [p.id for p in client.periods if p.id != period.id]
    out = {}
    if not ids:
        return out
    for f in db.query(FollowUpRow).filter(FollowUpRow.period_id.in_(ids)).order_by(FollowUpRow.id):
        if f.contact_email or f.contact_phone:
            out[f.supplier_gstin] = (f.contact_email, f.contact_phone)
    return out


def decision_row(period: Period, f) -> DecisionRow:
    tp = [p for p in f.portal if p.period in (period.period, "")]
    data = {"books": [doc_out(d) for d in f.books], "portal": [doc_out(d) for d in f.portal],
            "reason": f.reason, "next_step": f.next_step, "flags": list(f.flags),
            "blocked": [{"rid": b.rid, "label": b.label, "section": b.section, "confidence": b.confidence,
                         "evidence": b.evidence, "advice": b.advice, "exceptions": b.exceptions} for b in f.blocked]}
    docs = f.books + f.portal
    search = " ".join([f.supplier_name, f.supplier_gstin] + [d.doc_no for d in docs] + [f.reason]).lower()
    return DecisionRow(period_id=period.id, key=finding_key(f), fid=f.fid, status=f.status.value,
                       status_code=f.status.name, recommended=f.action.value, final=None,
                       confidence=f.confidence.value, owner=f.owner.value, needs_human=bool(f.needs_human),
                       blocked=bool(f.blocked), supplier_gstin=f.supplier_gstin or "(no GSTIN)",
                       supplier_name=f.supplier_name or "", itc_in_2b=f.itc_in_2b, itc_in_books=f.itc_in_books,
                       itc_to_claim=f.itc_to_claim, itc_at_stake=f.itc_at_stake, in_period_2b=bool(tp),
                       all_available=all(p.itc_available is not False for p in f.portal),
                       search=search[:4000], data_json=jdump(data))


# ── decisions after staff input ─────────────────────────────────────────────

def effective(d: DecisionRow) -> str:
    return d.final or d.recommended


def claim_after(d: DecisionRow) -> float:
    """ITC this decision claims once the staff's final decision is applied (same rule as Table 4 and the pack)."""
    from taxmind.closepack import claim_with
    return claim_with(d.status_code, d.recommended, d.final or d.recommended, d.itc_to_claim, d.itc_in_2b,
                      d.in_period_2b or bool(jload(d.data_json, {}).get("portal")), d.all_available)


def is_open(d: DecisionRow) -> bool:
    return d.needs_human and d.final is None


def close_decisions(rows: list[DecisionRow], res) -> list[CloseDecision]:
    """Staff decisions mapped onto the engine's findings (by key), in the closepack format."""
    by_key = {r.key: r for r in rows}
    out = []
    for f in res.findings:
        r = by_key.get(finding_key(f))
        final = (r.final if r and r.final else f.action.value)
        out.append(CloseDecision(f.fid, f.action.value, final, (r.note if r else "") or ""))
    return out


def overrides(rows, res) -> dict:
    return {d.fid: (d.final, d.note) for d in close_decisions(rows, res) if d.overridden or d.note}


def table4(period: Period, rows: list[DecisionRow], basis: str = "final") -> dict:
    res = result_for(period)
    if res is None:
        return {"lines": [], "ledger": [], "reclaimed": 0, "carried": 0, "new_reversals": 0,
                "policy": "", "basis": "recommendations"}
    t = res.table4 if basis != "final" else after_decisions(res, close_decisions(rows, res))
    if basis == "final":
        t = dict(t)
        t["reclaimed"] = res.table4.get("reclaimed", 0)
    lines = [{"code": ln.code, "label": ln.label, **{h: round(ln.amounts[h], 2) for h in ("igst", "cgst", "sgst", "cess")},
              "total": round(ln.total, 2), "count": ln.count, "note": ln.note} for ln in t["lines"]]
    ledger = [{"gstin": it.gstin, "supplier": it.supplier, "doc_no": it.doc_no, "doc_date": it.doc_date,
               "period_reversed": it.period_reversed, "igst": it.igst, "cgst": it.cgst, "sgst": it.sgst,
               "cess": it.cess, "tax": it.tax, "reason": it.reason} for it in t["ledger"]]
    return {"lines": lines, "ledger": ledger, "reclaimed": t.get("reclaimed", 0), "carried": t.get("carried", 0),
            "new_reversals": t.get("new_reversals", 0), "policy": t.get("policy", ""),
            "basis": "final decisions" if basis == "final" else "recommendations"}


def label(period: str) -> str:
    return period_label(period)


def iso(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()
    return v.isoformat()


def history(db: Session, period: Period) -> dict:
    """What staff decided last time for the same supplier in the same situation.

    Looks at the latest earlier month of this client that has decisions. When every decided record of
    (supplier, status) got the same final action - e.g. all 236 airline tickets 'No IMS action, booked in
    the expense register' - that action is offered as a one-click suggestion this month. Never applied
    on its own."""
    earlier = [p for p in period.client.periods if p.run_no and pkey(p.period) < pkey(period.period)]
    if not earlier:
        return {}
    last = max(earlier, key=lambda p: pkey(p.period))
    groups: dict = {}
    for d in db.query(DecisionRow).filter(DecisionRow.period_id == last.id, DecisionRow.final.isnot(None)):
        g = groups.setdefault((d.supplier_gstin, d.status_code), {"finals": set(), "count": 0, "note": ""})
        g["finals"].add(d.final)
        g["count"] += 1
        g["note"] = g["note"] or d.note
    return {k: {"final": next(iter(g["finals"])), "count": g["count"], "period": last.period,
                "label": label(last.period), "note": g["note"]}
            for k, g in groups.items() if len(g["finals"]) == 1}
