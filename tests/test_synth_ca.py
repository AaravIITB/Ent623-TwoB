"""Sanity tests for the CA-style test-data generator (taxmind.synth_ca). Generator only - no engine."""
import csv
import json

import openpyxl
import pytest

from taxmind import gstin as G
from taxmind.synth_ca import (BOOK_COLS, BOOKS_HEADER_ROW, CASES, MONTHS, P2B_COLS, P2B_HEADER_ROW, RETURN,
                              generate)

PROFILE = "e_car_dealer"          # the smallest profile keeps these tests fast


@pytest.fixture(scope="module")
def ds(tmp_path_factory):
    a = tmp_path_factory.mktemp("a")
    b = tmp_path_factory.mktemp("b")
    generate(a, seed=5, profile=PROFILE)
    generate(b, seed=5, profile=PROFILE)
    return a / PROFILE, b / PROFILE


def _truth(d):
    return json.loads((d / "truth.json").read_text())


def _sheet_rows(path, header_row):
    ws = openpyxl.load_workbook(path).active
    rows = list(ws.iter_rows(values_only=True))
    return rows[header_row - 1], [(i + header_row + 1, r) for i, r in enumerate(rows[header_row:])]


def test_deterministic_for_seed(ds, tmp_path):
    a, b = ds
    assert (a / "truth.json").read_text() == (b / "truth.json").read_text()
    t = _truth(a)
    assert (a / t["meta"]["files"]["books_csv"]).read_bytes() == (b / t["meta"]["files"]["books_csv"]).read_bytes()
    generate(tmp_path, seed=6, profile=PROFILE)
    assert (tmp_path / PROFILE / "truth.json").read_text() != (a / "truth.json").read_text()


def test_layouts_and_files(ds):
    d, _ = ds
    F = _truth(d)["meta"]["files"]
    head, _ = _sheet_rows(d / F["books_xlsx"], BOOKS_HEADER_ROW)
    assert list(head) == BOOK_COLS
    for per in MONTHS:
        head, _ = _sheet_rows(d / F["portal_xlsx"][per], P2B_HEADER_ROW)
        assert list(head) == P2B_COLS
    wb = openpyxl.load_workbook(d / F["combined"])
    assert wb.sheetnames == ["Summary", F["books_sheet"], F["portal_sheet"][RETURN]]
    js = json.loads((d / F["portal_json"][RETURN]).read_text())
    assert js["data"]["rtnprd"] == RETURN and js["data"]["docdata"]["b2b"]
    assert (d / F["vendor_master"]).exists()


def test_gstins_valid(ds):
    d, _ = ds
    t = _truth(d)
    assert G.is_valid(t["meta"]["client_gstin"])
    for r in t["rows"]:
        if r["side"] == "portal":
            assert G.is_valid(r["key"][0]), r
        elif r["gstin"]:
            assert G.is_valid(r["gstin"]), r
    ws = openpyxl.load_workbook(d / t["meta"]["files"]["vendor_master"]).active
    for row in list(ws.iter_rows(values_only=True))[1:]:
        assert G.is_valid(row[2])
    _, rows = _sheet_rows(d / t["meta"]["files"]["books_xlsx"], BOOKS_HEADER_ROW)
    for _, r in rows:
        if r[7]:
            assert G.is_valid(r[7])


def test_truth_covers_every_row(ds):
    d, _ = ds
    t = _truth(d)
    F = t["meta"]["files"]
    rids = {r["rid"] for r in t["rows"]}
    assert len(rids) == len(t["rows"])
    _, rows = _sheet_rows(d / F["books_xlsx"], BOOKS_HEADER_ROW)
    assert {f"B:{n}" for n, _ in rows} == {r for r in rids if r.startswith("B:")}
    for per in MONTHS:
        _, rows = _sheet_rows(d / F["portal_xlsx"][per], P2B_HEADER_ROW)
        assert {f"P:{per}:{n}" for n, _ in rows} == {r for r in rids if r.startswith(f"P:{per}:")}
    # CSV record N is Excel row N
    with open(d / F["books_csv"], encoding="utf-8-sig", newline="") as fh:
        recs = list(csv.reader(fh))
    n_books = sum(1 for r in rids if r.startswith("B:"))
    assert recs[BOOKS_HEADER_ROW - 1] == BOOK_COLS and len(recs) == BOOKS_HEADER_ROW + n_books
    in_groups = {x for g in t["groups"] for x in g["books"] + g["portal"]}
    assert in_groups == rids
    assert {g["case"] for g in t["groups"]} <= set(CASES)


def test_cases_present(ds):
    d, _ = ds
    counts = _truth(d)["meta"]["case_counts"]
    for case in ("exact", "earlier_2b_reclaim", "late_filer_next_month", "duplicate_in_books", "books_cn_matched",
                 "booked_without_gst", "rectification", "portal_only_unknown", "portal_cn_not_booked",
                 "portal_itc_unavailable", "b2ba_amendment", "other_gstin_same_pan", "wrong_head", "split"):
        assert counts.get(case, 0) >= 1, case


def test_totals_balance(ds):
    d, _ = ds
    t = _truth(d)
    F = t["meta"]["files"]
    ws = openpyxl.load_workbook(d / F["books_xlsx"]).active
    rows = list(ws.iter_rows(values_only=True))
    sub, data = rows[BOOKS_HEADER_ROW - 2], rows[BOOKS_HEADER_ROW:]
    for col in ("IGST", "CGST", "SGST", "Total Tax"):
        j = BOOK_COLS.index(col)
        assert abs(sub[j] - sum(float(r[j] or 0) for r in data)) < 0.05
    for r in data:      # Total Tax column = sum of heads
        assert abs(float(r[BOOK_COLS.index("Total Tax")] or 0) -
                   sum(float(r[BOOK_COLS.index(c)] or 0) for c in ("IGST", "CGST", "SGST"))) < 0.02
    ws = openpyxl.load_workbook(d / F["portal_xlsx"][RETURN]).active
    rows = list(ws.iter_rows(values_only=True))
    sub, data = rows[P2B_HEADER_ROW - 2], rows[P2B_HEADER_ROW:]
    j = P2B_COLS.index("Total Tax")
    assert abs(sub[j] - sum(float(r[j] or 0) for r in data)) < 0.05
    t4 = t["table4"]
    tot = lambda k: t4[k]["total"]                                     # noqa: E731
    assert abs(tot("4A5_total") - tot("4A5_auto_2b") - tot("4A5_reclaim")) < 0.05
    assert abs(tot("4D1_reclaimed") - tot("4A5_reclaim")) < 0.05
    claims = sum(g["itc_claim"]["total"] for g in t["groups"])
    blocked = sum(g["itc_claim"]["total"] for g in t["groups"]
                  if g["blocked"] and g["bucket"] in ("4A5_2b", "4A5_reclaim"))
    assert abs(tot("net_itc") - (claims - blocked)) < 1.0
    # 2B rows in the return month carry the signed tax the 2B shows
    auto = sum(r["tax"] for r in t["rows"] if r["side"] == "portal" and r["period"] == RETURN
               and r["itc_available"] and not r["rcm"])
    assert abs(auto - tot("4A5_auto_2b")) < 1.0
    for g in t["groups"]:
        if g["excluded"]:
            assert g["itc_claim"]["total"] == 0 and not g["portal"]
