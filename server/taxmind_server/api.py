"""HTTP API. The contract is docs/API.md."""
from __future__ import annotations

import csv
import io
import shutil
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import __version__
from . import service as S
from .auth import (ROLES, check_password, current_user, get_db, hash_password, issue_token, require)
from .db import (ActivityRow, Client, DecisionRow, FollowUpRow, Period, StoredFile, Token, User, jdump, jload,
                 now)
from .settings import FILES, MAX_UPLOAD_MB, PACKS

from taxmind import gstin as G
from taxmind.blocked import LINES_OF_BUSINESS

router = APIRouter(prefix="/api")
EDITABLE = ("reconciled", "in_review")
FOLLOWUP_STATUSES = ("to_send", "sent", "replied", "resolved", "no_response")
PERIOD_STATUSES = ["not_started", "files_uploaded", "reconciled", "in_review", "approved", "closed"]


# ── serialisers ─────────────────────────────────────────────────────────────

def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "name": u.name or u.username, "role": u.role, "active": u.active}


def client_out(c: Client) -> dict:
    return {"id": c.id, "name": c.name, "gstin": c.gstin, "trade_name": c.trade_name, "notes": c.notes,
            "settings": S.settings_of(c), "has_vendor_master": bool(c.vendor_master_path),
            "created_at": S.iso(c.created_at)}


def file_out(f: StoredFile) -> dict:
    return {"id": f.id, "role": f.role, "filename": f.filename, "size": f.size, "sha256": f.sha256,
            "uploaded_at": S.iso(f.uploaded_at), "uploaded_by": f.uploaded_by, "period_hint": f.period_hint}


def summary_out(db: Session, p: Period) -> dict | None:
    s = jload(p.summary_json)
    if not s:
        return None
    rows = db.query(DecisionRow).filter_by(period_id=p.id).all()
    s = dict(s)
    s["open"] = sum(1 for d in rows if S.is_open(d))
    s["decided"] = sum(1 for d in rows if d.final)
    s["itc_after_decisions"] = round(sum(S.claim_after(d) for d in rows), 2)
    s["history_suggestions"] = sum(1 for d in rows if S.is_open(d) and '"history"' in (d.data_json or ""))
    return s


def period_out(db: Session, p: Period) -> dict:
    ims, g3 = S.deadlines(p.period)
    return {"id": p.id, "client_id": p.client_id, "period": p.period, "label": S.label(p.period), "status": p.status,
            "ims_deadline": ims.isoformat(), "gstr3b_deadline": g3.isoformat(),
            "filed_3b_on": p.filed_3b_on.isoformat() if p.filed_3b_on else None,
            "files": [file_out(f) for f in p.files], "summary": summary_out(db, p),
            "checks": jload(p.checks_json, []) if p.run_no else [], "notes": jload(p.notes_json, []),
            "run_at": S.iso(p.run_at), "run_by": p.run_by, "submitted_by": p.submitted_by,
            "submitted_at": S.iso(p.submitted_at), "approved_by": p.approved_by, "approved_at": S.iso(p.approved_at),
            "closed_by": p.closed_by, "closed_at": S.iso(p.closed_at), "pack_fingerprint": p.pack_fingerprint,
            "review_note": p.review_note or "", "stale": bool(p.stale),
            "checks_ack": {"by": p.checks_ack_by, "at": S.iso(p.checks_ack_at)} if p.checks_ack_by else None,
            "prior_ledger_items": len(jload(p.prior_ledger_json, []) or []) if p.run_no
            else len(S.previous_ledger(db, p))}


def decision_out(d: DecisionRow) -> dict:
    data = jload(d.data_json, {})
    return {"id": d.id, "key": d.key, "fid": d.fid, "status": d.status, "status_code": d.status_code,
            "recommended": d.recommended, "final": d.final, "effective": S.effective(d),
            "confidence": d.confidence, "owner": d.owner, "needs_human": d.needs_human,
            "done": (not d.needs_human) or d.final is not None,
            "supplier_gstin": d.supplier_gstin, "supplier_name": d.supplier_name,
            "books": data.get("books", []), "portal": data.get("portal", []),
            "itc_in_2b": d.itc_in_2b, "itc_in_books": d.itc_in_books, "itc_to_claim": d.itc_to_claim,
            "itc_at_stake": d.itc_at_stake, "reason": data.get("reason", ""), "next_step": data.get("next_step", ""),
            "flags": data.get("flags", []), "blocked": data.get("blocked", []), "note": d.note or "",
            "history": data.get("history"),
            "assignee": {"id": d.assignee.id, "name": d.assignee.name or d.assignee.username} if d.assignee else None,
            "updated_by": d.updated_by, "updated_at": S.iso(d.updated_at)}


def followup_out(f: FollowUpRow) -> dict:
    return {"id": f.id, "supplier_gstin": f.supplier_gstin, "supplier_name": f.supplier_name, "items": f.items,
            "itc_at_stake": f.itc_at_stake, "whatsapp": f.whatsapp, "email_subject": f.email_subject,
            "email_body": f.email_body, "contact_email": f.contact_email, "contact_phone": f.contact_phone,
            "status": f.status, "note": f.note, "sent_at": S.iso(f.sent_at), "updated_by": f.updated_by,
            "updated_at": S.iso(f.updated_at)}


def uname(u: User) -> str:
    return u.name or u.username


# ── lookups ─────────────────────────────────────────────────────────────────

def get_client(db: Session, cid: int) -> Client:
    c = db.get(Client, cid)
    if c is None:
        raise HTTPException(404, "Client not found.")
    return c


def check_period(p: str) -> str:
    if len(p) != 6 or not p.isdigit() or not (1 <= int(p[:2]) <= 12) or not (2017 <= int(p[2:]) <= 2100):
        raise HTTPException(400, f"Period '{p}' is not MMYYYY (e.g. 062026).")
    return p


def get_period(db: Session, cid: int, p: str, create: bool = True) -> Period:
    check_period(p)
    c = get_client(db, cid)
    row = db.query(Period).filter_by(client_id=c.id, period=p).first()
    if row is None:
        if not create:
            raise HTTPException(404, "Nothing has been done for this month yet.")
        row = Period(client_id=c.id, period=p)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def editable(p: Period):
    if S.is_running(p.id):
        raise HTTPException(409, "TwoB is reconciling this month right now; try again in a moment.")
    if p.status not in EDITABLE:
        raise HTTPException(409, {"approved": "This month is approved; reopen it to change decisions.",
                                  "closed": "This month is closed; reopen it to change decisions."}.get(
            p.status, "Reconcile this month first."))


# ── meta / auth / users ─────────────────────────────────────────────────────

@router.get("/health")
def health():
    return {"ok": True, "version": __version__}


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.query(User).filter(func.lower(User.username) == body.username.strip().lower()).first()
    if u is None or not u.active or not check_password(body.password, u.password_hash):
        raise HTTPException(401, "Wrong username or password.")
    return {"token": issue_token(db, u), "user": user_out(u)}


@router.post("/auth/logout")
def logout(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.query(Token).filter_by(user_id=user.id).delete()
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.get("/meta")
def meta(user: User = Depends(current_user)):
    return {"lines_of_business": LINES_OF_BUSINESS, "actions": S.ACTIONS, "statuses": S.STATUS_LABELS,
            "roles": list(ROLES), "period_statuses": PERIOD_STATUSES, "followup_statuses": list(FOLLOWUP_STATUSES)}


class UserIn(BaseModel):
    username: str
    name: str = ""
    role: str = "preparer"
    password: str


class UserPatch(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None
    active: Optional[bool] = None


@router.get("/users")
def users(db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = db.query(User)
    if user.role != "admin":
        q = q.filter_by(active=True)
    return [user_out(u) for u in q.order_by(User.name)]


@router.post("/users")
def add_user(body: UserIn, db: Session = Depends(get_db), user: User = Depends(require("admin"))):
    if body.role not in ROLES:
        raise HTTPException(400, f"Role must be one of {', '.join(ROLES)}.")
    if len(body.password) < 6:
        raise HTTPException(400, "Use a password of at least 6 characters.")
    if not body.username.strip():
        raise HTTPException(400, "Enter a username.")
    if db.query(User).filter(func.lower(User.username) == body.username.strip().lower()).first():
        raise HTTPException(400, "That username is taken.")
    u = User(username=body.username.strip(), name=body.name.strip(), role=body.role,
             password_hash=hash_password(body.password))
    db.add(u)
    db.commit()
    return user_out(u)


@router.patch("/users/{uid}")
def edit_user(uid: int, body: UserPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "User not found.")
    if user.role != "admin" and (user.id != uid or body.role is not None or body.active is not None):
        raise HTTPException(403, "Only an admin can change other users or roles.")
    if body.name is not None:
        u.name = body.name
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(400, f"Role must be one of {', '.join(ROLES)}.")
        if u.role == "admin" and body.role != "admin" and db.query(User).filter_by(role="admin", active=True).count() <= 1:
            raise HTTPException(400, "Keep at least one admin.")
        u.role = body.role
    if body.password:
        if len(body.password) < 6:
            raise HTTPException(400, "Use a password of at least 6 characters.")
        u.password_hash = hash_password(body.password)
        db.query(Token).filter(Token.user_id == u.id).delete()
    if body.active is not None:
        if not body.active and u.role == "admin" and \
                db.query(User).filter_by(role="admin", active=True).count() <= 1:
            raise HTTPException(400, "Keep at least one active admin.")
        if not body.active and u.id == user.id:
            raise HTTPException(400, "You can't disable your own account.")
        u.active = body.active
        if not body.active:
            db.query(Token).filter(Token.user_id == u.id).delete()
    db.commit()
    return user_out(u)


# ── clients ─────────────────────────────────────────────────────────────────

class SettingsIn(BaseModel):
    tolerance: Optional[float] = None
    tolerance_pct: Optional[float] = None
    line_of_business: Optional[list[str]] = None
    policy: Optional[str] = None


class ClientIn(BaseModel):
    name: str
    gstin: str = ""
    trade_name: str = ""
    notes: str = ""
    settings: Optional[SettingsIn] = None


class ClientPatch(BaseModel):
    name: Optional[str] = None
    gstin: Optional[str] = None
    trade_name: Optional[str] = None
    notes: Optional[str] = None
    settings: Optional[SettingsIn] = None


def _clean_gstin(g: str) -> str:
    g = (g or "").strip().upper()
    if not g:
        return ""
    if not G.is_valid(g):
        raise HTTPException(400, f"GSTIN '{g}' is not valid (15 characters with a correct check digit).")
    return g


def _apply_settings(c: Client, s: SettingsIn | None):
    if s is None:
        return
    cur = S.settings_of(c)
    if s.tolerance is not None:
        if not 0 <= s.tolerance <= 1000:
            raise HTTPException(400, "Tolerance must be between ₹0 and ₹1,000.")
        cur["tolerance"] = s.tolerance
    if s.tolerance_pct is not None:
        if not 0 <= s.tolerance_pct <= 5:
            raise HTTPException(400, "Tolerance % must be between 0 and 5.")
        cur["tolerance_pct"] = s.tolerance_pct
    if s.line_of_business is not None:
        bad = [t for t in s.line_of_business if t not in LINES_OF_BUSINESS]
        if bad:
            raise HTTPException(400, f"Unknown line of business: {', '.join(bad)}.")
        cur["line_of_business"] = s.line_of_business
    if s.policy is not None:
        if s.policy not in ("pending", "reverse"):
            raise HTTPException(400, "Policy must be 'pending' or 'reverse'.")
        cur["policy"] = s.policy
    c.settings_json = jdump(cur)


@router.get("/clients")
def clients(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [client_out(c) for c in db.query(Client).order_by(Client.name)]


@router.post("/clients")
def add_client(body: ClientIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not body.name.strip():
        raise HTTPException(400, "Enter the client's name.")
    c = Client(name=body.name.strip(), gstin=_clean_gstin(body.gstin), trade_name=body.trade_name.strip(),
               notes=body.notes, settings_json=jdump(S.DEFAULT_SETTINGS))
    _apply_settings(c, body.settings)
    db.add(c)
    db.flush()
    S.log(db, uname(user), c, "", "client added", c.gstin)
    db.commit()
    return client_out(c)


@router.get("/clients/{cid}")
def client_detail(cid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = get_client(db, cid)
    out = client_out(c)
    out["periods"] = [period_out(db, p) for p in sorted(c.periods, key=lambda p: S.pkey(p.period), reverse=True)]
    return out


@router.patch("/clients/{cid}")
def edit_client(cid: int, body: ClientPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = get_client(db, cid)
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(400, "Enter the client's name.")
        c.name = body.name.strip()
    if body.gstin is not None:
        c.gstin = _clean_gstin(body.gstin)
    if body.trade_name is not None:
        c.trade_name = body.trade_name
    if body.notes is not None:
        c.notes = body.notes
    _apply_settings(c, body.settings)
    S.log(db, uname(user), c, "", "client settings changed")
    db.commit()
    return client_out(c)


@router.delete("/clients/{cid}")
def delete_client(cid: int, db: Session = Depends(get_db), user: User = Depends(require("admin"))):
    c = get_client(db, cid)
    S.log(db, uname(user), None, "", "client deleted", c.name)
    db.delete(c)
    db.commit()
    shutil.rmtree(FILES / str(cid), ignore_errors=True)
    shutil.rmtree(PACKS / str(cid), ignore_errors=True)
    return {"ok": True}


def _save_upload(up: UploadFile, folder: Path) -> tuple[Path, int, str]:
    name = Path(up.filename or "upload").name
    if Path(name).suffix.lower() not in (".xlsx", ".xlsm", ".xls", ".csv", ".json", ".xml"):
        raise HTTPException(400, f"{name}: use Excel, CSV, JSON or Tally XML files.")
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / name
    size = 0
    with open(dest, "wb") as out:
        while chunk := up.file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_MB << 20:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"{name} is larger than {MAX_UPLOAD_MB} MB.")
            out.write(chunk)
    return dest, size, S.sha256_file(dest)


@router.post("/clients/{cid}/vendor-master")
def upload_vendor_master(cid: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                         user: User = Depends(current_user)):
    c = get_client(db, cid)
    folder = FILES / str(cid) / "vendor_master" / now().strftime("%Y%m%d%H%M%S%f")
    dest, _, _ = _save_upload(file, folder)
    if dest.suffix.lower() not in (".xlsx", ".xls", ".xlsm", ".csv"):
        raise HTTPException(400, "The vendor master must be Excel or CSV.")
    from taxmind.prepare import load_vendor_master
    try:
        n = len(load_vendor_master(dest))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not read the vendor master: {e}")
    if not n:
        raise HTTPException(400, "No supplier rows found: the vendor master needs a GSTIN column and a name column.")
    c.vendor_master_path = str(dest)
    S.log(db, uname(user), c, "", "vendor master uploaded", f"{n} suppliers")
    db.commit()
    return client_out(c)


# ── dashboard / activity ────────────────────────────────────────────────────

@router.get("/dashboard")
def dashboard(period: str = "", db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = check_period(period) if period else S.default_period()
    ims, g3 = S.deadlines(p)
    rows, tot = [], {"clients": 0, "not_started": 0, "in_progress": 0, "in_review": 0, "closed": 0,
                     "open_items": 0, "itc_at_risk": 0.0}
    for c in db.query(Client).order_by(Client.name):
        per = db.query(Period).filter_by(client_id=c.id, period=p).first()
        open_n, risk, high, fu = 0, 0.0, 0, 0
        if per and per.run_no:
            for d in db.query(DecisionRow).filter_by(period_id=per.id, needs_human=True, final=None):
                open_n += 1
                risk += d.itc_at_stake
            high = sum(1 for ch in jload(per.checks_json, []) if ch.get("level") == "High")
            fu = db.query(FollowUpRow).filter(FollowUpRow.period_id == per.id,
                                              FollowUpRow.status.in_(("to_send", "sent", "no_response"))).count()
        st = per.status if per else "not_started"
        tot["clients"] += 1
        tot["not_started" if st in ("not_started",) else "in_review" if st in ("in_review", "approved")
            else "closed" if st == "closed" else "in_progress"] += 1
        tot["open_items"] += open_n
        tot["itc_at_risk"] += risk
        rows.append({"client": client_out(c), "period": period_out(db, per) if per else None, "open": open_n,
                     "itc_at_risk": round(risk, 2), "high_checks": high, "followups_open": fu,
                     "days_to_3b": (g3 - date.today()).days})
    tot["itc_at_risk"] = round(tot["itc_at_risk"], 2)
    return {"period": p, "label": S.label(p), "ims_deadline": ims.isoformat(), "gstr3b_deadline": g3.isoformat(),
            "rows": rows, "totals": tot}


@router.get("/activity")
def activity(limit: int = 50, client_id: Optional[int] = None, db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    q = db.query(ActivityRow)
    if client_id:
        q = q.filter_by(client_id=client_id)
    return [{"at": S.iso(a.at), "user": a.user, "client": a.client, "client_id": a.client_id, "period": a.period,
             "action": a.action, "detail": a.detail} for a in q.order_by(ActivityRow.id.desc()).limit(min(limit, 500))]


# ── periods ─────────────────────────────────────────────────────────────────

@router.get("/clients/{cid}/periods/{p}")
def period_detail(cid: int, p: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return period_out(db, get_period(db, cid, p))


@router.post("/clients/{cid}/periods/{p}/files")
def upload_files(cid: int, p: str, role: str = Form(...), period_hint: str = Form(""),
                 files: list[UploadFile] = File(...), db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    if per.status in ("approved", "closed"):
        raise HTTPException(409, "This month is approved or closed; reopen it to change the files.")
    if role not in ("books", "portal"):
        raise HTTPException(400, "role must be 'books' or 'portal'.")
    hint = ""
    if period_hint:
        hint = check_period(period_hint)
    for up in files:
        _check_name(up)
    names, saved = [], []
    have = {f.sha256: f.filename for f in per.files if f.role == role}
    try:
        for up in files:
            folder = FILES / str(cid) / p / now().strftime("%Y%m%d%H%M%S%f")
            dest, size, sha = _save_upload(up, folder)
            saved.append(dest)
            if sha in have:
                raise HTTPException(409, f"{dest.name} is the same file as {have[sha]}, already uploaded here.")
            have[sha] = dest.name
            f = StoredFile(period_id=per.id, role=role, filename=dest.name, path=str(dest), size=size, sha256=sha,
                           period_hint=hint or (_detect_month(dest) if role == "portal" else ""),
                           uploaded_by=uname(user))
            db.add(f)
            names.append(dest.name)
    except HTTPException:
        db.rollback()
        for d in saved:
            shutil.rmtree(d.parent, ignore_errors=True)
        raise
    _files_changed(per)
    S.log(db, uname(user), per.client, p, "files uploaded", f"{role}: {', '.join(names)}")
    db.commit()
    db.refresh(per)
    return period_out(db, per)


def _check_name(up: UploadFile):
    name = Path(up.filename or "upload").name
    if Path(name).suffix.lower() not in (".xlsx", ".xlsm", ".xls", ".csv", ".json", ".xml"):
        raise HTTPException(400, f"{name}: use Excel, CSV, JSON or Tally XML files.")


def _files_changed(per: Period):
    """New or removed files make the last run out of date: the month goes back to 'files uploaded' until it
    is reconciled again (decisions are kept and carried over by that run)."""
    if per.status == "not_started":
        per.status = "files_uploaded"
    elif per.status in ("reconciled", "in_review"):
        per.status, per.stale = "files_uploaded", True


def _detect_month(path: Path) -> str:
    """Best-effort month of a 2B file, shown next to it (the engine decides again when it runs)."""
    try:
        from taxmind.loaders import load_file
        from taxmind.models import Side
        docs, _ = load_file(path, Side.PORTAL)
        ps = [d.period for d in docs if d.period]
        return max(set(ps), key=ps.count) if ps else ""
    except Exception:  # noqa: BLE001
        return ""


@router.delete("/clients/{cid}/periods/{p}/files/{fid}")
def delete_file(cid: int, p: str, fid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    if per.status in ("approved", "closed"):
        raise HTTPException(409, "This month is approved or closed; reopen it to change the files.")
    f = db.get(StoredFile, fid)
    if f is None or f.period_id != per.id:
        raise HTTPException(404, "File not found.")
    S.log(db, uname(user), per.client, p, "file removed", f.filename)
    db.delete(f)
    db.flush()
    db.refresh(per)
    if per.files:
        _files_changed(per)
    elif per.status in ("files_uploaded", "reconciled", "in_review"):
        per.status, per.stale = ("files_uploaded", True) if per.run_no else ("not_started", False)
    db.commit()
    return period_out(db, per)


@router.post("/clients/{cid}/periods/{p}/reconcile")
def reconcile_period(cid: int, p: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    if per.status in ("approved", "closed"):
        raise HTTPException(409, "This month is approved or closed; reopen it before reconciling again.")
    try:
        S.run_period(db, per, uname(user))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        db.rollback()
        msg = str(e)
        if "format cannot be determined" in msg or "zip file" in msg.lower() or "codec" in msg:
            msg = "one of the files is not a valid Excel / CSV / JSON / Tally XML file"
        raise HTTPException(422, f"TwoB could not read the files: {msg}.")
    db.refresh(per)
    return period_out(db, per)


# ── decisions ───────────────────────────────────────────────────────────────

def _decision_query(db: Session, per: Period, user: User, view="open", supplier="", status_code="", action="",
                    owner="", assignee="", q=""):
    qry = db.query(DecisionRow).filter(DecisionRow.period_id == per.id)
    if view == "open":
        qry = qry.filter(DecisionRow.needs_human.is_(True), DecisionRow.final.is_(None))
    elif view == "decided":
        qry = qry.filter(DecisionRow.final.isnot(None))
    elif view == "auto":
        qry = qry.filter(DecisionRow.needs_human.is_(False))
    elif view == "blocked":
        qry = qry.filter(DecisionRow.blocked.is_(True))
    elif view != "all":
        raise HTTPException(400, "view must be open, all, decided, auto or blocked.")
    if supplier:
        qry = qry.filter(DecisionRow.supplier_gstin == supplier)
    if status_code:
        qry = qry.filter(DecisionRow.status_code.in_([s.strip() for s in status_code.split(",") if s.strip()]))
    if action:
        acts = [a.strip() for a in action.split(",") if a.strip()]
        qry = qry.filter(or_(DecisionRow.final.in_(acts),
                             (DecisionRow.final.is_(None)) & DecisionRow.recommended.in_(acts)))
    if owner:
        qry = qry.filter(DecisionRow.owner.in_([o.strip() for o in owner.split(",")]))
    if assignee:
        if assignee != "me" and not assignee.isdigit():
            raise HTTPException(400, "assignee must be 'me' or a user id.")
        qry = qry.filter(DecisionRow.assignee_id == (user.id if assignee == "me" else int(assignee)))
    if q:
        for word in q.lower().split():
            qry = qry.filter(DecisionRow.search.contains(word))
    return qry


@router.get("/clients/{cid}/periods/{p}/decisions")
def decisions(cid: int, p: str, view: str = "open", supplier: str = "", status_code: str = "", action: str = "",
              owner: str = "", assignee: str = "", q: str = "", sort: str = "itc", offset: int = 0,
              limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    qry = _decision_query(db, per, user, view, supplier, status_code, action, owner, assignee, q)
    total = qry.count()
    order = {"itc": (DecisionRow.itc_at_stake.desc(), DecisionRow.id),
             "supplier": (DecisionRow.supplier_name, DecisionRow.itc_at_stake.desc()),
             "status": (DecisionRow.status_code, DecisionRow.itc_at_stake.desc())}.get(sort)
    if order is None:
        raise HTTPException(400, "sort must be itc, supplier or status.")
    offset = max(offset, 0)
    items = qry.order_by(*order).offset(offset).limit(limit).all()
    return {"items": [decision_out(d) for d in items], "total": total, "offset": offset, "limit": limit}


@router.get("/clients/{cid}/periods/{p}/decisions/{did}")
def decision(cid: int, p: str, did: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    d = db.get(DecisionRow, did)
    if d is None or d.period_id != per.id:
        raise HTTPException(404, "Decision not found.")
    return decision_out(d)


def _check_assignee(db: Session, aid):
    if aid in (-1, None):
        return
    u = db.get(User, aid)
    if u is None or not u.active:
        raise HTTPException(400, "No such active user to assign.")


class DecisionPatch(BaseModel):
    final: Optional[str] = "__unset__"
    note: Optional[str] = None
    assignee_id: Optional[int] = -1


def _apply(d: DecisionRow, final, note, assignee_id, user: User):
    if final != "__unset__":
        if final == "history":
            h = jload(d.data_json, {}).get("history")
            if not h:
                return False
            d.final = h["final"]
            if note is None and h.get("note") and not d.note:
                d.note = f"As in {h['label']}: {h['note']}"[:2000]
        elif final == "recommended":
            d.final = d.recommended
        elif final is None or final == "":
            d.final = None
        elif final in S.ACTIONS:
            d.final = final
        else:
            raise HTTPException(400, f"final must be one of {', '.join(S.ACTIONS)}, 'recommended', 'history' or null.")
    if note is not None:
        d.note = note[:2000]
    if assignee_id != -1:
        d.assignee_id = assignee_id
    d.updated_by, d.updated_at = uname(user), now()
    return True


@router.patch("/clients/{cid}/periods/{p}/decisions/{did}")
def edit_decision(cid: int, p: str, did: int, body: DecisionPatch, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    editable(per)
    d = db.get(DecisionRow, did)
    if d is None or d.period_id != per.id:
        raise HTTPException(404, "Decision not found.")
    _check_assignee(db, body.assignee_id)
    _apply(d, body.final, body.note, body.assignee_id, user)
    db.commit()
    db.refresh(d)
    return decision_out(d)


class BulkFilter(BaseModel):
    view: str = "open"
    supplier: str = ""
    status_code: str = ""
    action: str = ""
    owner: str = ""
    assignee: str = ""
    q: str = ""


class BulkIn(BaseModel):
    ids: Optional[list[int]] = None
    filter: Optional[BulkFilter] = None
    final: Optional[str] = "__unset__"
    note: Optional[str] = None
    assignee_id: Optional[int] = -1


@router.post("/clients/{cid}/periods/{p}/decisions/bulk")
def bulk(cid: int, p: str, body: BulkIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    editable(per)
    if body.ids is None and body.filter is None:
        raise HTTPException(400, "Give ids or a filter.")
    _check_assignee(db, body.assignee_id)
    if body.ids is not None:
        rows = db.query(DecisionRow).filter(DecisionRow.period_id == per.id, DecisionRow.id.in_(body.ids)).all()
    else:
        f = body.filter
        rows = _decision_query(db, per, user, f.view, f.supplier, f.status_code, f.action, f.owner, f.assignee,
                               f.q).all()
    rows = [d for d in rows if _apply(d, body.final, body.note, body.assignee_id, user)]
    if rows:
        what = body.final if body.final != "__unset__" else ("note" if body.note is not None else "assignee")
        S.log(db, uname(user), per.client, p, "bulk decision", f"{len(rows)} records: {what}")
    db.commit()
    return {"updated": len(rows)}


@router.get("/clients/{cid}/periods/{p}/suppliers")
def suppliers(cid: int, p: str, q: str = "", only_open: bool = False, db: Session = Depends(get_db),
              user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    rows = db.query(DecisionRow).filter_by(period_id=per.id).all()
    fu = {f.supplier_gstin: f.status for f in db.query(FollowUpRow).filter_by(period_id=per.id)}
    out: dict = {}
    hist_by: dict = {}
    from collections import Counter
    for d in rows:
        r = out.setdefault(d.supplier_gstin, {"gstin": d.supplier_gstin, "name": d.supplier_name, "records_2b": 0,
                                              "entries_books": 0, "matched": 0, "open": 0, "itc_2b": 0.0,
                                              "itc_books": 0.0, "itc_claim": 0.0, "itc_open": 0.0,
                                              "_st": Counter(), "in_books": False})
        data = jload(d.data_json, {})
        nb, npo = len(data.get("books", [])), len(data.get("portal", []))
        r["name"] = r["name"] or d.supplier_name
        r["records_2b"] += npo
        r["entries_books"] += nb
        r["in_books"] = r["in_books"] or nb > 0
        r["matched"] += bool(nb and npo)
        if S.is_open(d):
            r["open"] += 1
            r["itc_open"] += d.itc_at_stake
            h = data.get("history")
            if h:
                hist_by.setdefault(d.supplier_gstin, Counter())[h["final"]] += 1
        r["itc_2b"] += d.itc_in_2b
        r["itc_books"] += d.itc_in_books
        r["itc_claim"] += S.claim_after(d)
        r["_st"][d.status] += 1
    res = []
    ql = q.lower().strip()
    for r in out.values():
        st = r.pop("_st")
        r["main_status"] = st.most_common(1)[0][0]
        r["statuses"] = "; ".join(f"{k}: {v}" for k, v in st.most_common())
        for k in ("itc_2b", "itc_books", "itc_claim", "itc_open"):
            r[k] = round(r[k], 2)
        if not r["in_books"] and r["records_2b"]:
            r["suggestion"] = (f"Never in these books: confirm with the client once for all {r['records_2b']} "
                               "records, then decide them together.")
        elif r["open"]:
            r["suggestion"] = f"{r['open']} open - see the decisions."
        else:
            r["suggestion"] = "All clear."
        r["followup_status"] = fu.get(r["gstin"])
        hist = hist_by.get(r["gstin"])
        r["history_final"], r["history_count"] = (hist.most_common(1)[0] if hist else (None, 0))
        if only_open and not r["open"]:
            continue
        if ql and ql not in r["name"].lower() and ql not in r["gstin"].lower():
            continue
        res.append(r)
    res.sort(key=lambda r: (-r["itc_open"], -r["open"], r["name"]))
    return res


@router.get("/clients/{cid}/periods/{p}/table4")
def table4(cid: int, p: str, basis: str = "final", db: Session = Depends(get_db), user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    rows = db.query(DecisionRow).filter_by(period_id=per.id).all()
    return S.table4(per, rows, "final" if basis != "recommended" else "recommended")


# ── follow-ups ──────────────────────────────────────────────────────────────

@router.get("/clients/{cid}/periods/{p}/followups")
def followups(cid: int, p: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    rows = db.query(FollowUpRow).filter_by(period_id=per.id).order_by(FollowUpRow.itc_at_stake.desc()).all()
    return [followup_out(f) for f in rows]


class FollowUpPatch(BaseModel):
    status: Optional[str] = None
    note: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None


@router.patch("/clients/{cid}/periods/{p}/followups/{fid}")
def edit_followup(cid: int, p: str, fid: int, body: FollowUpPatch, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    f = db.get(FollowUpRow, fid)
    if f is None or f.period_id != per.id:
        raise HTTPException(404, "Follow-up not found.")
    if per.status == "closed":
        raise HTTPException(409, "This month is closed; follow up from the next month's list.")
    if body.status is not None:
        if body.status not in FOLLOWUP_STATUSES:
            raise HTTPException(400, f"status must be one of {', '.join(FOLLOWUP_STATUSES)}.")
        if body.status == "sent" and f.status != "sent":
            f.sent_at = now()
        f.status = body.status
        S.log(db, uname(user), per.client, p, "follow-up " + body.status, f.supplier_name)
    if body.note is not None:
        f.note = body.note[:2000]
    if body.contact_email is not None:
        f.contact_email = body.contact_email.strip()[:200]
    if body.contact_phone is not None:
        f.contact_phone = body.contact_phone.strip()[:40]
    f.updated_by, f.updated_at = uname(user), now()
    db.commit()
    return followup_out(f)


# ── review workflow ─────────────────────────────────────────────────────────

class NoteIn(BaseModel):
    note: str = ""
    force: bool = False


def _open_count(db: Session, per: Period) -> int:
    return db.query(DecisionRow).filter_by(period_id=per.id, needs_human=True, final=None).count()


@router.post("/clients/{cid}/periods/{p}/submit")
def submit(cid: int, p: str, body: NoteIn = NoteIn(), db: Session = Depends(get_db), user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    if per.status != "reconciled":
        raise HTTPException(409, "Only a reconciled month can be sent for review.")
    per.status, per.submitted_by, per.submitted_at = "in_review", uname(user), now()
    if body.note:
        per.review_note = body.note
    S.log(db, uname(user), per.client, p, "sent for review", f"{_open_count(db, per)} open items. {body.note}")
    db.commit()
    return period_out(db, per)


@router.post("/clients/{cid}/periods/{p}/send-back")
def send_back(cid: int, p: str, body: NoteIn, db: Session = Depends(get_db), user: User = Depends(require("reviewer"))):
    per = get_period(db, cid, p)
    if per.status not in ("in_review", "approved"):
        raise HTTPException(409, "Only a month in review can be sent back.")
    if not body.note.strip():
        raise HTTPException(400, "Say what needs to change.")
    per.status, per.review_note = "reconciled", body.note
    per.approved_by = per.approved_at = None
    S.log(db, uname(user), per.client, p, "sent back", body.note)
    db.commit()
    return period_out(db, per)


@router.post("/clients/{cid}/periods/{p}/approve")
def approve(cid: int, p: str, body: NoteIn = NoteIn(), db: Session = Depends(get_db),
            user: User = Depends(require("reviewer"))):
    per = get_period(db, cid, p)
    if per.status not in ("in_review", "reconciled"):
        raise HTTPException(409, "Reconcile and send the month for review first.")
    n = _open_count(db, per)
    if n and not body.force:
        raise HTTPException(409, f"{n} items still have no decision. Decide them, or approve anyway.")
    per.status, per.approved_by, per.approved_at = "approved", uname(user), now()
    per.review_note = body.note or per.review_note
    if not per.submitted_by:
        per.submitted_by, per.submitted_at = uname(user), now()
    S.log(db, uname(user), per.client, p, "approved", (f"{n} items left undecided. " if n else "") + body.note)
    db.commit()
    return period_out(db, per)


@router.post("/clients/{cid}/periods/{p}/close")
def close(cid: int, p: str, db: Session = Depends(get_db), user: User = Depends(require("reviewer"))):
    from taxmind.closepack import CloseInfo, build_close_pack, pack_fingerprint
    per = get_period(db, cid, p)
    if per.status != "approved":
        raise HTTPException(409, "Approve the month before closing it.")
    if per.stale:
        raise HTTPException(409, "Files changed after the last reconciliation; reopen and reconcile again.")
    res = S.result_for(per)
    rows = db.query(DecisionRow).filter_by(period_id=per.id).all()
    out = PACKS / str(cid) / f"twob_{per.client.id}_{p}_close_pack.zip"
    spec = jload(per.run_settings_json, {})
    files = [f["path"] for f in spec.get("books", []) + spec.get("portal", [])] + \
        ([spec["vendor_master"]] if spec.get("vendor_master") else [])
    z = build_close_pack(res, out, input_files=[x for x in files if Path(x).exists()],
                         info=CloseInfo(preparer=per.submitted_by or per.run_by or "", reviewer=uname(user),
                                        overrides=S.overrides(rows, res)))
    t4 = S.table4(per, rows, "final")
    per.ledger_json = jdump([{k: v for k, v in it.items() if k != "tax"} for it in t4["ledger"]])
    per.pack_path, per.pack_fingerprint = str(z), pack_fingerprint(z)
    per.status, per.closed_by, per.closed_at = "closed", uname(user), now()
    S.log(db, uname(user), per.client, p, "closed", f"fingerprint {per.pack_fingerprint}; "
                                                   f"{len(t4['ledger'])} reversals carried to next month")
    db.commit()
    return period_out(db, per)


@router.post("/clients/{cid}/periods/{p}/reopen")
def reopen(cid: int, p: str, body: NoteIn, db: Session = Depends(get_db), user: User = Depends(require("reviewer"))):
    per = get_period(db, cid, p)
    if per.status not in ("approved", "closed", "in_review"):
        raise HTTPException(409, "This month is already open.")
    if not body.note.strip():
        raise HTTPException(400, "Say why the month is reopened.")
    was = per.status
    per.status = "reconciled" if per.run_no else ("files_uploaded" if per.files else "not_started")
    per.approved_by = per.approved_at = per.closed_by = per.closed_at = None
    per.pack_fingerprint, per.ledger_json = None, ""      # the old pack stays on disk; a new close makes a new one
    per.review_note = body.note
    S.log(db, uname(user), per.client, p, "reopened", f"was {was}: {body.note}")
    db.commit()
    return period_out(db, per)


class AckIn(BaseModel):
    ack: bool = True


@router.post("/clients/{cid}/periods/{p}/checks/ack")
def ack_checks(cid: int, p: str, body: AckIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    if not per.run_no:
        raise HTTPException(409, "Reconcile this month first.")
    if body.ack:
        per.checks_ack_by, per.checks_ack_at = uname(user), now()
        highs = [c["name"] for c in jload(per.checks_json, []) if c.get("level") == "High"]
        S.log(db, uname(user), per.client, p, "checks acknowledged", "; ".join(highs))
    else:
        per.checks_ack_by = per.checks_ack_at = None
    db.commit()
    return period_out(db, per)


class FiledIn(BaseModel):
    filed_3b_on: Optional[date] = None


@router.post("/clients/{cid}/periods/{p}/filed")
def filed(cid: int, p: str, body: FiledIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    per.filed_3b_on = body.filed_3b_on
    S.log(db, uname(user), per.client, p, "3B filed" if body.filed_3b_on else "3B filing date cleared",
          body.filed_3b_on.isoformat() if body.filed_3b_on else "")
    db.commit()
    return period_out(db, per)


# ── exports ─────────────────────────────────────────────────────────────────

def _need_result(per: Period):
    res = S.result_for(per)
    if res is None:
        raise HTTPException(409, "Reconcile this month first.")
    return res


def _fname(per: Period, suffix: str) -> str:
    import re
    return f"twob_{re.sub(r'[^A-Za-z0-9]+', '_', per.client.name).strip('_')}_{per.period}{suffix}"


@router.get("/clients/{cid}/periods/{p}/export/workbook")
def export_workbook(cid: int, p: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    import tempfile
    from openpyxl import load_workbook
    from taxmind.report import write_excel
    per = get_period(db, cid, p)
    res = _need_result(per)
    rows = db.query(DecisionRow).filter_by(period_id=per.id).all()
    ov = S.overrides(rows, res)
    tmp = Path(tempfile.mkdtemp()) / _fname(per, ".xlsx")
    write_excel(res, tmp)
    wb = load_workbook(tmp)
    ws = wb["All findings"]
    for r in range(2, ws.max_row + 1):
        fid = ws.cell(r, 1).value
        if fid in ov:
            ws.cell(r, 4).value, ws.cell(r, 5).value = ov[fid]
    wb.save(tmp)
    return FileResponse(tmp, filename=tmp.name, background=BackgroundTask(shutil.rmtree, tmp.parent, True),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/clients/{cid}/periods/{p}/export/ims.csv")
def export_ims(cid: int, p: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    rows = db.query(DecisionRow).filter_by(period_id=per.id).all()
    sio = io.StringIO()
    w = csv.writer(sio)
    w.writerow(["Supplier GSTIN", "Supplier", "Doc type", "Doc no.", "Doc date", "Taxable", "Tax", "IMS action",
                "Decided by", "Reason"])
    for d in sorted(rows, key=lambda d: (d.supplier_name, d.id)):
        act = S.effective(d)
        if act not in ("Accept", "Reject", "Pending"):
            continue
        for doc in jload(d.data_json, {}).get("portal", []):
            if doc["period"] not in (per.period, ""):
                continue
            w.writerow([doc["supplier_gstin"], doc["supplier_name"] or d.supplier_name, doc["doc_type"], doc["doc_no"],
                        doc["doc_date"] or "", doc["taxable"], doc["tax"], act,
                        d.updated_by if d.final else "TwoB", jload(d.data_json, {}).get("reason", "")[:300]])
    return Response(sio.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{_fname(per, "_ims_actions.csv")}"'})


@router.get("/clients/{cid}/periods/{p}/export/prefiling.html")
def export_prefiling(cid: int, p: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    import tempfile
    from taxmind.report import write_html
    per = get_period(db, cid, p)
    res = _need_result(per)
    tmp = Path(tempfile.mkdtemp()) / _fname(per, "_prefiling.html")
    write_html(res, tmp)
    return FileResponse(tmp, filename=tmp.name, media_type="text/html",
                        background=BackgroundTask(shutil.rmtree, tmp.parent, True))


@router.get("/clients/{cid}/periods/{p}/export/ledger.csv")
def export_ledger(cid: int, p: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    rows = db.query(DecisionRow).filter_by(period_id=per.id).all()
    items = jload(per.ledger_json, None) if per.status == "closed" else None
    if items is None:
        items = S.table4(per, rows, "final")["ledger"]
    sio = io.StringIO()
    fields = ["gstin", "supplier", "doc_no", "doc_date", "period_reversed", "igst", "cgst", "sgst", "cess", "reason"]
    w = csv.DictWriter(sio, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for it in items:
        w.writerow(it)
    return Response(sio.getvalue().encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{_fname(per, "_itc_reversal_ledger.csv")}"'})


@router.get("/clients/{cid}/periods/{p}/export/close-pack")
def export_pack(cid: int, p: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    per = get_period(db, cid, p)
    if per.status != "closed" or not per.pack_path or not Path(per.pack_path).exists():
        raise HTTPException(409, "Close the month to create its pack.")
    return FileResponse(per.pack_path, filename=Path(per.pack_path).name, media_type="application/zip")


# ── demo data ───────────────────────────────────────────────────────────────

@router.post("/demo/seed")
def demo_seed(db: Session = Depends(get_db), user: User = Depends(require("admin"))):
    from .demo import seed
    try:
        n = seed(db, uname(user))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return {"clients": n}
