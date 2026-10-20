"""Small parsing helpers shared by the loaders."""
from __future__ import annotations

import math
import re
from datetime import date, datetime

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return 0.0 if (isinstance(v, float) and math.isnan(v)) else float(v)
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "-", "na", "n/a"):
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^0-9.\-]", "", s)
    if s in ("", "-", ".", "-."):
        return 0.0
    try:
        x = float(s)
    except ValueError:
        return 0.0
    return -x if neg else x


def to_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if hasattr(v, "to_pydatetime"):          # pandas Timestamp
        try:
            return v.to_pydatetime().date()
        except Exception:
            return None
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v).strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return None
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)                       # 20260905 (Tally)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T].*)?", s)  # 2026-09-05
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)       # 05-09-2026 (Indian order)
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        return _mk(y, int(m.group(2)), int(m.group(1)))
    m = re.fullmatch(r"(\d{1,2})[-/ ]([A-Za-z]{3})[A-Za-z]*[-/ ,]*(\d{2,4})", s)  # 5-Sep-2026
    if m and m.group(2).lower() in _MONTHS:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        return _mk(y, _MONTHS[m.group(2).lower()], int(m.group(1)))
    return None


def _mk(y, mo, d):
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def to_period(v) -> str:
    """Normalise a return period to MMYYYY ('092026')."""
    if v is None:
        return ""
    s = re.sub(r"\s", "", str(v))
    if re.fullmatch(r"\d{6}", s):
        return s
    m = re.fullmatch(r"([A-Za-z]{3})[A-Za-z]*[-/']?(\d{2,4})", s)       # Sep-26, September2026
    if m and m.group(1).lower() in _MONTHS:
        y = int(m.group(2))
        y = y + 2000 if y < 100 else y
        return f"{_MONTHS[m.group(1).lower()]:02d}{y}"
    d = to_date(s)
    return d.strftime("%m%Y") if d else ""


def norm_header(h) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


def yes(v) -> bool | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("y", "yes", "true", "1"):
        return True
    if s in ("n", "no", "false", "0"):
        return False
    return None


IMS_ACTIONS = {"a": "Accepted", "accept": "Accepted", "accepted": "Accepted",
               "r": "Rejected", "reject": "Rejected", "rejected": "Rejected",
               "p": "Pending", "pending": "Pending",
               "n": "No action", "noaction": "No action", "": "No action"}


def ims_action(v) -> str:
    return IMS_ACTIONS.get(norm_header(v), "")
