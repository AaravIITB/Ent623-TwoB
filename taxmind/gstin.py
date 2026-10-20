"""GSTIN validation (format + official check digit) and state lookup."""
from __future__ import annotations

import re

_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_FORMAT = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

STATES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu",
    "34": "Puducherry", "35": "Andaman & Nicobar", "36": "Telangana", "37": "Andhra Pradesh",
    "38": "Ladakh", "97": "Other Territory", "99": "Centre Jurisdiction",
}


def check_digit(first14: str) -> str:
    """Official GSTIN checksum (mod-36, alternating weights 1 and 2)."""
    total = 0
    for i, ch in enumerate(first14.upper()):
        prod = _CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += prod // 36 + prod % 36
    return _CHARS[(36 - total % 36) % 36]


def is_valid(gstin: str) -> bool:
    g = (gstin or "").strip().upper()
    if not _FORMAT.match(g):
        return False
    if g[:2] not in STATES:
        return False
    return check_digit(g[:14]) == g[14]


def clean(gstin) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(gstin or "")).upper()


def state_name(gstin: str) -> str:
    return STATES.get((gstin or "")[:2], "unknown state")


def pan(gstin: str) -> str:
    g = clean(gstin)
    return g[2:12] if len(g) == 15 else g
