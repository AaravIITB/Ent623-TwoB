"""TaxMind - GSTR-2B / IMS reconciliation engine for CA firms.

    from taxmind import load_many, reconcile, Side
    books, _ = load_many(["purchase_register.xlsx"], Side.BOOKS)
    portal, _ = load_many(["gstr2b_092026.json", "gstr2b_102026.json"], Side.PORTAL)
    result = reconcile(books, portal, client="ABC Pvt Ltd")
"""
from .config import Config
from .engine import Result, reconcile
from .loaders import load_file, load_many
from .models import Action, Doc, DocType, Finding, Side, Status

__all__ = ["Config", "Result", "reconcile", "load_file", "load_many", "Action", "Doc", "DocType",
           "Finding", "Side", "Status"]
__version__ = "0.2.0"
