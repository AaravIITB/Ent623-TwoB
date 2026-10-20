"""Pick the right loader for a file."""
from __future__ import annotations

from pathlib import Path

from ..models import Doc, Side
from . import portal_json, tabular, tally_xml


def load_file(path: str | Path, side: Side, uid_prefix: str | None = None,
              period: str = "") -> tuple[list[Doc], list[str]]:
    """Load one file as books (purchase register) or portal (GSTR-2B / IMS)."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".json":
        if side != Side.PORTAL:
            raise ValueError(f"{p.name}: JSON files are read as portal data (GSTR-2B / IMS)")
        docs, notes = portal_json.load(p, uid_prefix or "P")
        if period:
            for d in docs:
                d.period = d.period or period
        return docs, notes
    if ext == ".xml":
        if side != Side.BOOKS:
            raise ValueError(f"{p.name}: XML files are read as Tally books exports")
        return tally_xml.load(p, uid_prefix or "B")
    if ext in (".xlsx", ".xlsm", ".xls", ".csv"):
        return tabular.load(p, side, uid_prefix, period)
    raise ValueError(f"{p.name}: unsupported file type {ext}")


def load_many(paths, side: Side, period: str = "") -> tuple[list[Doc], list[str]]:
    docs, notes = [], []
    for i, path in enumerate(paths):
        prefix = ("B" if side == Side.BOOKS else "P") + f"{i + 1}-"
        d, n = load_file(path, side, prefix, period)
        docs += d
        notes += n
    return docs, notes
