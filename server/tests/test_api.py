"""API tests: the whole month workflow on a small fictional client, plus the demo seed."""
import io
import random
from datetime import date

from openpyxl import Workbook

from taxmind.synth import make_gstin

RNG = random.Random(5)
CLIENT_G = make_gstin(RNG, "27")
S1, S2, S3 = make_gstin(RNG, "27"), make_gstin(RNG, "27"), make_gstin(RNG, "29")


def xlsx(rows, header):
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


BOOKS = xlsx([["A-101", date(2026, 6, 5), S1, "Alpha Steel", 100000, 9000, 9000, 0, "Raw material"],
              ["A-102", date(2026, 6, 6), S1, "Alpha Steel", 50000, 4500, 4500, 0, "Raw material"],
              ["B/77", date(2026, 6, 9), S2, "Beta Cabs", 10000, 250, 250, 0, "Car hire for staff"],
              ["C-9", date(2026, 6, 10), S2, "Beta Cabs", 2000, 50, 50, 0, "Car hire for staff"]],
             ["Supplier Invoice No", "Invoice Date", "GSTIN of Supplier", "Party Name", "Taxable Value", "CGST",
              "SGST", "IGST", "Purchase Ledger"])
TWOB = xlsx([[S1, "ALPHA STEEL", "A-101", date(2026, 6, 5), 100000, 0, 9000, 9000],
             [S1, "ALPHA STEEL", "A/102", date(2026, 6, 6), 50000, 0, 4500, 4500],
             [S2, "BETA CABS", "B/77", date(2026, 6, 9), 10000, 0, 250, 250],
             [S3, "GAMMA AIR", "G1", date(2026, 6, 12), 4000, 200, 0, 0],
             [S3, "GAMMA AIR", "G2", date(2026, 6, 13), 4000, 200, 0, 0]],
            ["GSTIN of supplier", "Trade/Legal name", "Invoice number", "Invoice Date", "Taxable Value",
             "Integrated Tax", "Central Tax", "State/UT Tax"])


def test_health_and_auth(client):
    assert client.get("/api/health").json()["ok"]
    assert client.get("/api/clients").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "x"}).status_code == 401


def test_users_and_roles(client, admin):
    r = client.post("/api/users", headers=admin, json={"username": "prep", "name": "Prep", "role": "preparer",
                                                       "password": "secret1"})
    assert r.status_code == 200
    r = client.post("/api/users", headers=admin, json={"username": "rev", "name": "Rev", "role": "reviewer",
                                                       "password": "secret1"})
    assert r.status_code == 200
    tok = client.post("/api/auth/login", json={"username": "prep", "password": "secret1"}).json()["token"]
    prep = {"Authorization": "Bearer " + tok}
    assert client.post("/api/users", headers=prep, json={"username": "x", "role": "admin", "password": "secret1"}
                       ).status_code == 403


def _login(client, u):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": "secret1"}
                                                     ).json()["token"]}


def test_month_workflow(client, admin):
    prep, rev = _login(client, "prep"), _login(client, "rev")
    assert client.post("/api/clients", headers=prep, json={"name": "Bad", "gstin": CLIENT_G[:-1] + ("0" if CLIENT_G[-1] != "0" else "1")}).status_code == 400
    c = client.post("/api/clients", headers=prep, json={"name": "Test Pvt Ltd", "gstin": CLIENT_G,
                                                         "settings": {"policy": "pending"}}).json()
    P = f"/api/clients/{c['id']}/periods/062026"
    per = client.get(P, headers=prep).json()
    assert per["status"] == "not_started" and per["ims_deadline"] == "2026-07-14" and per["gstr3b_deadline"] == "2026-07-20"
    assert client.post(P + "/reconcile", headers=prep).status_code == 400          # no files yet
    r = client.post(P + "/files", headers=prep, data={"role": "books"},
                    files={"files": ("purchase_register.xlsx", BOOKS)})
    assert r.json()["status"] == "files_uploaded"
    r = client.post(P + "/files", headers=prep, data={"role": "portal", "period_hint": "062026"},
                    files={"files": ("gstr2b_062026.xlsx", TWOB)})
    assert [f["role"] for f in r.json()["files"]] == ["books", "portal"]
    per = client.post(P + "/reconcile", headers=prep).json()
    assert per["status"] == "reconciled" and per["summary"]["findings"] >= 5
    s = per["summary"]
    assert s["open"] == s["needs_human"] and s["decided"] == 0

    # suppliers + open queue
    sup = client.get(P + "/suppliers", headers=prep).json()
    gamma = next(x for x in sup if x["gstin"] == S3)
    assert gamma["records_2b"] == 2 and not gamma["in_books"] and "Never in these books" in gamma["suggestion"]
    page = client.get(P + f"/decisions?supplier={S3}", headers=prep).json()
    assert page["total"] == 2 and all(d["recommended"] in ("Reject", "Pending") for d in page["items"])

    # bulk by filter, then a single edit with note and assignee
    r = client.post(P + "/decisions/bulk", headers=prep, json={"filter": {"view": "open", "supplier": S3},
                                                               "final": "Pending", "note": "ask client"})
    assert r.json()["updated"] == 2
    assert client.get(P + f"/decisions?supplier={S3}", headers=prep).json()["total"] == 0   # no longer open
    d = client.get(P + "/decisions?view=all&q=b/77", headers=prep).json()["items"][0]
    assert d["blocked"], "car hire should be flagged as possible blocked credit"
    me = client.get("/api/me", headers=prep).json()
    r = client.patch(P + f"/decisions/{d['id']}", headers=prep, json={"final": "Accept", "note": "ok",
                                                                      "assignee_id": me["id"]})
    assert r.json()["final"] == "Accept" and r.json()["assignee"]["id"] == me["id"]
    assert client.get(P + "/decisions?view=open&assignee=me", headers=prep).json()["total"] == 0
    assert client.get(P + "/decisions?view=decided&assignee=me", headers=prep).json()["total"] == 1
    assert client.patch(P + f"/decisions/{d['id']}", headers=prep, json={"final": "Maybe"}).status_code == 400

    # re-running keeps staff decisions
    per = client.post(P + "/reconcile", headers=prep).json()
    assert per["summary"]["decided"] == 3 and any("kept" in n for n in per["notes"])

    # table 4, follow-ups, exports
    t4 = client.get(P + "/table4", headers=prep).json()
    codes = {ln["code"]: ln for ln in t4["lines"]}
    assert t4["basis"] == "final decisions" and "4(C)" in codes
    assert client.get(P + "/table4?basis=recommended", headers=prep).json()["basis"] == "recommendations"
    tok = prep["Authorization"][7:]
    for path in ("workbook", "ims.csv", "prefiling.html", "ledger.csv"):
        r = client.get(P + f"/export/{path}?token={tok}")
        assert r.status_code == 200 and len(r.content) > 50, path
    assert "IMS action" in client.get(P + f"/export/ims.csv?token={tok}").text
    fu = client.get(P + "/followups", headers=prep).json()
    if fu:
        r = client.patch(P + f"/followups/{fu[0]['id']}", headers=prep, json={"status": "sent", "contact_phone": "98200 00000"})
        assert r.json()["sent_at"] and r.json()["contact_phone"] == "98200 00000"

    # review: preparer submits, cannot approve; reviewer approves (force), closes
    assert client.post(P + "/submit", headers=prep, json={}).json()["status"] == "in_review"
    assert client.post(P + "/approve", headers=prep, json={}).status_code == 403
    open_left = client.get(P, headers=rev).json()["summary"]["open"]
    if open_left:
        assert client.post(P + "/approve", headers=rev, json={}).status_code == 409
    assert client.post(P + "/send-back", headers=rev, json={"note": ""}).status_code == 400
    assert client.post(P + "/approve", headers=rev, json={"force": True}).json()["status"] == "approved"
    assert client.patch(P + f"/decisions/{d['id']}", headers=prep, json={"final": "Reject"}).status_code == 409
    per = client.post(P + "/close", headers=rev).json()
    assert per["status"] == "closed" and len(per["pack_fingerprint"]) == 64
    r = client.get(P + f"/export/close-pack?token={tok}")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert client.post(P + "/filed", headers=prep, json={"filed_3b_on": "2026-07-19"}).json()["filed_3b_on"] == "2026-07-19"

    # next month starts with the reversal ledger of the closed month
    led = client.get(P + f"/export/ledger.csv?token={tok}").text.strip().splitlines()
    jul = client.get(f"/api/clients/{c['id']}/periods/072026", headers=prep).json()
    assert jul["prior_ledger_items"] == len(led) - 1

    # reopen
    assert client.post(P + "/reopen", headers=rev, json={"note": "supplier amended"}).json()["status"] == "reconciled"

    dash = client.get("/api/dashboard?period=062026", headers=prep).json()
    row = next(r for r in dash["rows"] if r["client"]["id"] == c["id"])
    assert row["period"]["status"] == "reconciled" and dash["totals"]["clients"] >= 1
    acts = [a["action"] for a in client.get("/api/activity", headers=prep).json()]
    assert "closed" in acts and "reopened" in acts


def test_bad_inputs(client, admin):
    c = client.post("/api/clients", headers=admin, json={"name": "X"}).json()
    assert client.get(f"/api/clients/{c['id']}/periods/132026", headers=admin).status_code == 400
    r = client.post(f"/api/clients/{c['id']}/periods/062026/files", headers=admin, data={"role": "books"},
                    files={"files": ("notes.pdf", b"%PDF")})
    assert r.status_code == 400
    r = client.patch(f"/api/clients/{c['id']}", headers=admin, json={"settings": {"line_of_business": ["spaceship"]}})
    assert r.status_code == 400
    assert client.get("/api/clients/99999", headers=admin).status_code == 404


def test_demo_seed(client, admin):
    r = client.post("/api/demo/seed", headers=admin)
    assert r.status_code == 200 and r.json()["clients"] == 6
    dash = client.get("/api/dashboard?period=062026", headers=admin).json()
    assert sum(1 for r in dash["rows"] if r["period"] and r["period"]["status"] == "reconciled") >= 6
    assert client.post("/api/demo/seed", headers=admin).json()["clients"] == 0      # idempotent


def test_history_suggestion_next_month(client, admin):
    c = client.post("/api/clients", headers=admin, json={"name": "History Co", "gstin": make_gstin(RNG, "27")}).json()
    for per in ("052026", "062026"):
        P = f"/api/clients/{c['id']}/periods/{per}"
        client.post(P + "/files", headers=admin, data={"role": "books"}, files={"files": ("pr.xlsx", BOOKS)})
        client.post(P + "/files", headers=admin, data={"role": "portal", "period_hint": per},
                    files={"files": (f"gstr2b_{per}.xlsx", TWOB)})
        client.post(P + "/reconcile", headers=admin)
        if per == "052026":
            r = client.post(P + "/decisions/bulk", headers=admin, json={"filter": {"view": "all", "supplier": S3},
                                                                        "final": "No IMS action",
                                                                        "note": "booked in expense register"})
            assert r.json()["updated"] == 2
    P = f"/api/clients/{c['id']}/periods/062026"
    items = client.get(P + f"/decisions?supplier={S3}", headers=admin).json()["items"]
    assert items and all(d["history"]["final"] == "No IMS action" for d in items)
    assert client.get(P, headers=admin).json()["summary"]["history_suggestions"] == len(items)
    r = client.post(P + "/decisions/bulk", headers=admin, json={"filter": {"view": "open"}, "final": "history"})
    assert r.json()["updated"] == len(items)
    d = client.get(P + f"/decisions?view=decided&supplier={S3}", headers=admin).json()["items"][0]
    assert d["final"] == "No IMS action" and "booked in expense register" in d["note"]
