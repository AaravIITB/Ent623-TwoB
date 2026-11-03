"""Paths and environment settings."""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]          # repo root (holds taxmind/, web/, test_data/)
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))                   # make the engine importable

DATA = Path(os.environ.get("TAXMIND_DATA", REPO / "data")).resolve()
FILES = DATA / "files"
PACKS = DATA / "packs"
DB_URL = os.environ.get("TAXMIND_DB", f"sqlite:///{DATA / 'taxmind.db'}")
WEB_DIST = Path(os.environ.get("TAXMIND_WEB", REPO / "web" / "dist"))
TEST_DATA = REPO / "test_data"
ADMIN_PASSWORD = os.environ.get("TAXMIND_ADMIN_PASSWORD", "admin123")
TOKEN_DAYS = int(os.environ.get("TAXMIND_TOKEN_DAYS", "14"))
MAX_UPLOAD_MB = int(os.environ.get("TAXMIND_MAX_UPLOAD_MB", "60"))

for d in (DATA, FILES, PACKS):
    d.mkdir(parents=True, exist_ok=True)
