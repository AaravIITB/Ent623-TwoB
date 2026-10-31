"""Database: SQLite through SQLAlchemy 2.0. One file, no server to run."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
                        create_engine, event)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .settings import DB_URL

engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    if DB_URL.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class JSONText(Text):
    pass


def jload(s, default=None):
    if not s:
        return default
    try:
        return json.loads(s)
    except ValueError:
        return default


def jdump(v) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(20), default="preparer")
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Token(Base):
    __tablename__ = "tokens"
    token: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    user: Mapped[User] = relationship()


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    gstin: Mapped[str] = mapped_column(String(15), default="")
    trade_name: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    settings_json: Mapped[str] = mapped_column(Text, default="{}")
    vendor_master_path: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    periods: Mapped[list["Period"]] = relationship(back_populates="client", cascade="all, delete-orphan")


class Period(Base):
    __tablename__ = "periods"
    __table_args__ = (UniqueConstraint("client_id", "period"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    period: Mapped[str] = mapped_column(String(6))
    status: Mapped[str] = mapped_column(String(20), default="not_started")
    run_no: Mapped[int] = mapped_column(Integer, default=0)
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    run_settings_json: Mapped[str] = mapped_column(Text, default="")   # settings + files used, for exact re-runs
    summary_json: Mapped[str] = mapped_column(Text, default="")
    checks_json: Mapped[str] = mapped_column(Text, default="[]")
    notes_json: Mapped[str] = mapped_column(Text, default="[]")
    prior_ledger_json: Mapped[str] = mapped_column(Text, default="[]")
    ledger_json: Mapped[str] = mapped_column(Text, default="")        # set at close: carried to next month
    submitted_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pack_path: Mapped[str] = mapped_column(String(500), default="")
    pack_fingerprint: Mapped[str | None] = mapped_column(String(80), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    filed_3b_on: Mapped[object | None] = mapped_column(Date, nullable=True)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)       # files changed since the last run
    checks_ack_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    checks_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    client: Mapped[Client] = relationship(back_populates="periods")
    files: Mapped[list["StoredFile"]] = relationship(back_populates="period", cascade="all, delete-orphan",
                                                     order_by="StoredFile.id")


class StoredFile(Base):
    __tablename__ = "files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(300))
    path: Mapped[str] = mapped_column(String(600))
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    period_hint: Mapped[str] = mapped_column(String(6), default="")
    uploaded_by: Mapped[str] = mapped_column(String(120), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    period: Mapped[Period] = relationship(back_populates="files")


class DecisionRow(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(600), index=True)
    fid: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(80))
    status_code: Mapped[str] = mapped_column(String(40), index=True)
    recommended: Mapped[str] = mapped_column(String(20))
    final: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[str] = mapped_column(String(10))
    owner: Mapped[str] = mapped_column(String(20))
    needs_human: Mapped[bool] = mapped_column(Boolean)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    supplier_gstin: Mapped[str] = mapped_column(String(20), index=True)
    supplier_name: Mapped[str] = mapped_column(String(300), default="")
    itc_in_2b: Mapped[float] = mapped_column(Float, default=0.0)
    itc_in_books: Mapped[float] = mapped_column(Float, default=0.0)
    itc_to_claim: Mapped[float] = mapped_column(Float, default=0.0)
    itc_at_stake: Mapped[float] = mapped_column(Float, default=0.0)
    in_period_2b: Mapped[bool] = mapped_column(Boolean, default=False)
    all_available: Mapped[bool] = mapped_column(Boolean, default=True)
    search: Mapped[str] = mapped_column(Text, default="")
    data_json: Mapped[str] = mapped_column(Text, default="{}")       # docs, reason, flags, blocked ...
    note: Mapped[str] = mapped_column(Text, default="")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignee: Mapped[User | None] = relationship()


class FollowUpRow(Base):
    __tablename__ = "followups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id", ondelete="CASCADE"), index=True)
    supplier_gstin: Mapped[str] = mapped_column(String(20))
    supplier_name: Mapped[str] = mapped_column(String(300), default="")
    items: Mapped[int] = mapped_column(Integer, default=0)
    itc_at_stake: Mapped[float] = mapped_column(Float, default=0.0)
    whatsapp: Mapped[str] = mapped_column(Text, default="")
    email_subject: Mapped[str] = mapped_column(Text, default="")
    email_body: Mapped[str] = mapped_column(Text, default="")
    contact_email: Mapped[str] = mapped_column(String(200), default="")
    contact_phone: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(20), default="to_send")
    note: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActivityRow(Base):
    __tablename__ = "activity"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    user: Mapped[str] = mapped_column(String(120), default="")
    client_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client: Mapped[str] = mapped_column(String(200), default="")
    period: Mapped[str] = mapped_column(String(6), default="")
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(Text, default="")


def init_db():
    """Create tables, and add columns that newer versions introduced (SQLite has no migrations tool here)."""
    from sqlalchemy import inspect, text
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = col.type.compile(engine.dialect)
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                dflt = "" if default is None else f" DEFAULT {int(default) if isinstance(default, bool) else repr(default)}"
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl}{dflt}'))
