"""Outputs: an Excel workbook for the CA and a one-page HTML pre-filing report."""
from __future__ import annotations

import html
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import Action, Status
from .recommend import dt, inr

HEAD = PatternFill("solid", fgColor="1F4E5A")
HEAD_FONT = Font(bold=True, color="FFFFFF")
ACTION_FILL = {
    "Accept": PatternFill("solid", fgColor="DDF0DD"),
    "Reject": PatternFill("solid", fgColor="F8D7D7"),
    "Pending": PatternFill("solid", fgColor="FCEBC7"),
    "No IMS action": PatternFill("solid", fgColor="EEEEEE"),
}
LEVEL_FILL = {"High": ACTION_FILL["Reject"], "Review": ACTION_FILL["Pending"], "OK": ACTION_FILL["Accept"]}
WRAP = Alignment(wrap_text=True, vertical="top")
OTHER_PERIOD = (Status.LATE_FILED, Status.EARLIER_PERIOD)


def _table(ws, headers, rows, widths, start_row=1, wrap_cols=(), action_col=None):
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=start_row, column=c, value=h)
        cell.fill, cell.font, cell.alignment = HEAD, HEAD_FONT, Alignment(wrap_text=True, vertical="center")
    for r, row in enumerate(rows, start_row + 1):
        for c, v in enumerate(row, 1):
            cell = ws.cell(row=r, column=c, value=v)
            if headers[c - 1] in wrap_cols:
                cell.alignment = WRAP
            else:
                cell.alignment = Alignment(vertical="top")
            if isinstance(v, float):
                cell.number_format = "#,##,##0.00"
        if action_col is not None:
            v = row[action_col]
            if v in ACTION_FILL:
                ws.cell(row=r, column=action_col + 1).fill = ACTION_FILL[v]
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
    if rows:
        ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(headers))}{start_row + len(rows)}"


def write_excel(res, path: str | Path) -> Path:
    path = Path(path)
    wb = Workbook()
    s = res.summary

    # ── Summary ──
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = f"TaxMind reconciliation - {res.client or 'client'} - {res.period_label}"
    ws["A1"].font = Font(bold=True, size=14)
    rows = [
        ("Purchase entries in books", s["books_entries"]),
        ("Records in GSTR-2B for the period", s["portal_records"]),
        ("ITC as per books", s["itc_books"]),
        ("ITC as per 2B (available)", s["itc_2b"]),
        ("ITC recommended to claim", s["itc_to_claim"]),
        ("Decisions in total", s["findings"]),
        ("Cleared automatically (no action needed)", s["auto_cleared"]),
        ("Need a person (decide, check or chase)", s["needs_human"]),
        ("ITC in items that need a person", s["itc_needing_attention"]),
        ("...as supplier-level decisions (same supplier, same situation)", s.get("supplier_groups", 0)),
        ("Records at risk of deemed acceptance", s["deemed_acceptance_records"]),
        ("Possible blocked credit (Sec 17(5)) to review", s.get("blocked_review", 0)),
        ("ITC on possible blocked credit", s.get("blocked_review_itc", 0.0)),
        ("Books entries with no GST (excluded from matching)", s.get("no_gst_entries", 0)),
        ("Books entries whose GSTIN TaxMind filled in", s.get("gstin_filled", 0)),
        ("Books invoice nos. / dates read from the narration", s.get("from_narration", 0)),
    ]
    t4 = getattr(res, "table4", None) or {}
    for ln in t4.get("lines", []):
        if ln.code in ("4(A)(5)", "4(B)(1)", "4(B)(2)", "4(C)", "4(D)(1)"):
            rows.append((f"3B {ln.code} {ln.label.split(' (')[0]}", ln.total))
    for i, (k, v) in enumerate(rows, 3):
        ws.cell(row=i, column=1, value=k)
        c = ws.cell(row=i, column=2, value=v)
        if isinstance(v, float):
            c.number_format = "#,##,##0.00"
    r = len(rows) + 5
    ws.cell(row=r, column=1, value="Pre-filing checks").font = Font(bold=True, size=12)
    _table(ws, ["Level", "Check", "Detail", "Amount (₹)"],
           [(c.level, c.name, c.detail, c.amount) for c in res.checks],
           [44, 34, 90, 16], start_row=r + 1, wrap_cols=("Detail",))
    for i, c in enumerate(res.checks, r + 2):
        ws.cell(row=i, column=1).fill = LEVEL_FILL[c.level]
    r2 = r + len(res.checks) + 4
    ws.cell(row=r2, column=1, value="Decisions by status").font = Font(bold=True, size=12)
    for i, (k, v) in enumerate(sorted(s["by_status"].items(), key=lambda kv: -kv[1]), r2 + 1):
        ws.cell(row=i, column=1, value=k)
        ws.cell(row=i, column=2, value=v)
    r3 = r2 + len(s["by_status"]) + 3
    if res.notes:
        ws.cell(row=r3, column=1, value="Notes from loading").font = Font(bold=True, size=12)
        for i, n in enumerate(res.notes, r3 + 1):
            ws.cell(row=i, column=1, value=n)
    ws.freeze_panes = None

    # ── GSTR-3B Table 4 working ──
    t4 = getattr(res, "table4", None) or {}
    if t4.get("lines"):
        ws = wb.create_sheet("3B Table 4")
        ws["A1"] = f"GSTR-3B Table 4 working - {res.client or 'client'} - {res.period_label}"
        ws["A1"].font = Font(bold=True, size=13)
        ws["A2"] = ("Built from TaxMind's recommendations; it changes when the CA changes a decision. Lines marked "
                    "'?' are for the CA to decide and are not in the totals. Policy for 2B bills not in books: "
                    + ("keep Pending in IMS" if t4.get("policy") != "reverse" else "accept and reverse in 4(B)(2)") + ".")
        rows = [(ln.code, ln.label, ln.amounts["igst"], ln.amounts["cgst"], ln.amounts["sgst"], ln.amounts["cess"],
                 ln.total, ln.count, ln.note) for ln in t4["lines"]]
        _table(ws, ["Table", "Line", "IGST (₹)", "CGST (₹)", "SGST/UTGST (₹)", "Cess (₹)", "Total (₹)", "Records",
                    "Note"], rows, [10, 70, 15, 15, 15, 12, 16, 9, 50], start_row=4, wrap_cols=("Line", "Note"))
        for i in range(5, 5 + len(rows)):
            for c in range(3, 8):
                ws.cell(row=i, column=c).number_format = "#,##,##0.00"
            if rows[i - 5][0] in ("4(A)(5)", "4(C)"):
                for c in range(1, 8):
                    ws.cell(row=i, column=c).font = Font(bold=True)
        r = 6 + len(rows)
        ws.cell(row=r, column=1, value="Reversal ledger carried forward").font = Font(bold=True, size=12)
        ws.cell(row=r + 1, column=1, value=(f"{t4.get('new_reversals', 0)} reversed this month, {t4.get('carried', 0)} "
                                            f"open from earlier months, {t4.get('reclaimed', 0)} reclaimed. Load the "
                                            "ledger CSV next month (--prior-ledger) to reclaim bills once booked."))
        _table(ws, ["GSTIN", "Supplier", "Doc no.", "Doc date", "Reversed in", "IGST", "CGST", "SGST", "Cess",
                    "Why"], [(it.gstin, it.supplier, it.doc_no, it.doc_date, it.period_reversed, it.igst, it.cgst,
                              it.sgst, it.cess, it.reason) for it in t4["ledger"]],
               [18, 28, 18, 12, 11, 12, 12, 12, 10, 40], start_row=r + 3)

    # ── IMS decisions (one row per 2B record of the period) ──
    ws = wb.create_sheet("IMS decisions")
    hdr = ["Recommended", "Confidence", "Who acts", "Supplier", "Supplier GSTIN", "Type", "2B doc no.",
           "2B date", "Taxable (₹)", "Tax (₹)", "Books doc no.", "Books tax (₹)", "Current IMS action",
           "Status", "Reason", "Next step", "Flags", "ID"]
    rows = []
    for f in res.findings:
        if f.status in OTHER_PERIOD:
            continue
        for p in f.portal:
            b = f.books[0] if f.books else None
            rows.append([f.action.value, f.confidence.value, f.owner.value, p.supplier_name or f.supplier_name,
                         p.supplier_gstin, p.doc_type.value, p.doc_no, dt(p.doc_date), p.taxable, p.tax,
                         ", ".join(x.doc_no for x in f.books) if b else "", round(sum(x.tax for x in f.books), 2) if b else None,
                         p.ims_action or "", f.status.value, f.reason, f.next_step, "; ".join(f.flags), f.fid])
    order = {"Reject": 0, "Pending": 1, "Accept": 2, "No IMS action": 3}
    rows.sort(key=lambda r: (order.get(r[0], 9), r[1] == "High", -(r[9] or 0)))
    _table(ws, hdr, rows, [13, 11, 10, 26, 18, 6, 18, 11, 13, 12, 18, 12, 14, 28, 60, 50, 30, 8],
           wrap_cols=("Reason", "Next step", "Flags"), action_col=0)

    # ── By supplier ──
    if getattr(res, "suppliers", None):
        ws = wb.create_sheet("By supplier")
        _table(ws, ["Supplier", "GSTIN", "2B records", "Books entries", "Matched", "Open decisions", "ITC in 2B (₹)",
                    "ITC in books (₹)", "ITC to claim (₹)", "ITC in open items (₹)", "Main status", "Suggestion",
                    "All statuses"],
               [(r["name"], r["gstin"], r["records_2b"], r["entries_books"], r["matched"], r["open"], r["itc_2b"],
                 r["itc_books"], r["itc_claim"], r["itc_open"], r["main_status"], r["suggestion"], r["statuses"])
                for r in res.suppliers],
               [30, 18, 9, 9, 9, 9, 14, 14, 14, 14, 30, 60, 60], wrap_cols=("Suggestion", "All statuses"))

    # ── Books not in 2B ──
    ws = wb.create_sheet("Books not in 2B")
    hdr = ["Status", "Who acts", "Supplier", "Supplier GSTIN", "Doc no.", "Date", "Taxable (₹)", "Tax (₹)",
           "Reason", "Next step", "Flags", "Source", "ID"]
    rows = []
    for f in res.findings:
        if f.portal and f.status not in OTHER_PERIOD:
            continue
        for b in f.books:
            rows.append([f.status.value, f.owner.value, b.supplier_name, b.supplier_gstin, b.doc_no,
                         dt(b.doc_date), b.taxable, b.tax, f.reason, f.next_step, "; ".join(f.flags),
                         b.row_ref or b.source, f.fid])
    rows.sort(key=lambda r: -(r[7] or 0))
    _table(ws, hdr, rows, [30, 10, 26, 18, 18, 11, 13, 12, 60, 50, 30, 18, 8],
           wrap_cols=("Reason", "Next step", "Flags"))

    # ── Supplier follow-ups ──
    ws = wb.create_sheet("Supplier follow-ups")
    _table(ws, ["Supplier", "GSTIN", "Items", "ITC at stake (₹)", "WhatsApp message", "Email subject", "Email body"],
           [(m.supplier_name, m.supplier_gstin, m.items, m.itc_at_stake, m.whatsapp, m.email_subject, m.email_body)
            for m in res.supplier_messages],
           [26, 18, 7, 14, 70, 40, 80], wrap_cols=("WhatsApp message", "Email body"))

    # ── Client questions ──
    ws = wb.create_sheet("Client questions")
    _table(ws, ["Supplier", "GSTIN", "Document", "Date", "ITC (₹)", "Recommended", "What to ask / do", "Why", "ID"],
           [(q["supplier"], q["gstin"], q["document"], q["date"], q["itc"], q["recommended"], q["question"],
             q["context"], q["id"]) for q in res.client_questions],
           [26, 18, 18, 11, 12, 12, 60, 60, 8], wrap_cols=("What to ask / do", "Why"), action_col=5)

    # ── Blocked credit review ──
    ws = wb.create_sheet("Blocked credit review")
    rows = []
    for f in res.findings:
        for fl in f.blocked:
            d = (f.books or f.portal)[0]
            rows.append([fl.confidence, fl.label, fl.section, f.supplier_name or d.supplier_gstin, d.supplier_gstin,
                         d.doc_no, dt(d.doc_date), round(max(f.itc_to_claim, f.itc_in_books, 0), 2), fl.evidence,
                         fl.advice, fl.exceptions, f.action.value, f.fid])
    rows.sort(key=lambda r: ({"Likely": 0, "Review": 1, "Possible": 2}.get(r[0], 3), -(r[7] or 0)))
    _table(ws, ["Confidence", "Possible block", "Section", "Supplier", "GSTIN", "Doc no.", "Date", "ITC (₹)",
                "Why flagged", "What to do", "When ITC is still allowed", "IMS action", "ID"], rows,
           [11, 34, 22, 26, 18, 16, 11, 12, 40, 48, 60, 13, 8],
           wrap_cols=("Possible block", "Why flagged", "What to do", "When ITC is still allowed"))

    # ── All findings ──
    ws = wb.create_sheet("All findings")
    rows = []
    for f in res.findings:
        rows.append([f.fid, f.status.value, f.action.value, "", "", f.confidence.value, f.owner.value,
                     f.supplier_gstin, f.supplier_name,
                     " + ".join(d.doc_no for d in f.books), " + ".join(d.doc_no for d in f.portal),
                     f.itc_in_books, f.itc_in_2b, f.itc_to_claim, f.reason, f.next_step, "; ".join(f.flags),
                     f.match_score])
    _table(ws, ["ID", "Status", "Recommended", "Final decision", "CA note", "Confidence", "Who acts", "GSTIN",
                "Supplier", "Books doc(s)", "2B doc(s)", "ITC books (₹)", "ITC 2B (₹)", "ITC to claim (₹)", "Reason",
                "Next step", "Flags", "Match score"], rows,
           [8, 28, 13, 14, 30, 11, 10, 18, 24, 20, 20, 13, 13, 14, 60, 50, 30, 8],
           wrap_cols=("CA note", "Reason", "Next step", "Flags"), action_col=2)
    # The CA records any change here; the month-close pack reads these two columns back.
    ws["D1"].comment = Comment("Leave blank to keep the recommendation, or pick Accept / Reject / Pending / "
                               "No IMS action. Add the reason in 'CA note'. TaxMind's month-close pack reads "
                               "these columns back.", "TaxMind")
    if rows:
        dv = DataValidation(type="list", formula1='"Accept,Reject,Pending,No IMS action"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"D2:D{len(rows) + 1}")

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def write_html(res, path: str | Path) -> Path:
    """One-page pre-filing report a CA can read before filing GSTR-3B."""
    path = Path(path)
    s = res.summary
    e = html.escape
    lvl = {"High": "#b42318", "Review": "#b54708", "OK": "#067647"}
    checks = "".join(
        f"<tr><td><span class='pill' style='background:{lvl[c.level]}'>{c.level}</span></td>"
        f"<td><b>{e(c.name)}</b><br><span class='muted'>{e(c.detail)}</span></td></tr>"
        for c in res.checks)
    top = sorted([f for f in res.findings if f.needs_human], key=lambda f: -f.itc_at_stake)[:15]
    acts = "".join(
        f"<tr><td>{e(f.action.value)}</td><td>{e(f.supplier_name or f.supplier_gstin)}</td>"
        f"<td>{e((f.portal or f.books)[0].doc_no)}</td><td class='num'>{inr(f.itc_at_stake)}</td>"
        f"<td>{e(f.reason)}</td></tr>" for f in top)
    t4 = getattr(res, "table4", None) or {}
    t4rows = "".join(
        "<tr" + (" style='font-weight:600'" if ln.code in ("4(A)(5)", "4(C)") else "") + f"><td>{e(ln.code)}</td>"
        f"<td>{e(ln.label)}</td><td class='num'>{inr(ln.amounts['igst'])}</td><td class='num'>{inr(ln.amounts['cgst'])}</td>"
        f"<td class='num'>{inr(ln.amounts['sgst'])}</td><td class='num'>{inr(ln.total)}</td></tr>"
        for ln in t4.get("lines", []))
    t4html = (f"<h2>GSTR-3B Table 4 working</h2><div class='muted'>From the recommendations; lines marked '?' are "
              f"for the CA to decide and are not in the totals.</div><table><tr><th>Table</th><th>Line</th>"
              f"<th class='num'>IGST</th><th class='num'>CGST</th><th class='num'>SGST</th><th class='num'>Total</th>"
              f"</tr>{t4rows}</table>") if t4rows else ""
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pre-filing report - {e(res.client)} - {e(res.period_label)}</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:24px auto;max-width:960px;padding:0 16px;color:#1d2939;background:#fff}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:17px;margin:28px 0 8px}} .muted{{color:#667085;font-size:13px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-top:16px}}
.kpi{{border:1px solid #e4e7ec;border-radius:10px;padding:12px}} .kpi b{{display:block;font-size:20px}}
table{{border-collapse:collapse;width:100%;font-size:14px}} td,th{{border-bottom:1px solid #eaecf0;padding:8px;text-align:left;vertical-align:top}}
.pill{{color:#fff;border-radius:999px;padding:2px 10px;font-size:12px;white-space:nowrap}} .num{{text-align:right;white-space:nowrap}}
</style></head><body>
<h1>Pre-filing report: {e(res.client or 'Client')}, {e(res.period_label)}</h1>
<div class="muted">GSTR-3B input tax credit check, generated by TaxMind. Recommendations are defaults for a CA to review.</div>
<div class="grid">
<div class="kpi"><span class="muted">ITC as per books</span><b>{inr(s['itc_books'])}</b></div>
<div class="kpi"><span class="muted">ITC as per 2B</span><b>{inr(s['itc_2b'])}</b></div>
<div class="kpi"><span class="muted">Recommended claim</span><b>{inr(s['itc_to_claim'])}</b></div>
<div class="kpi"><span class="muted">Need a person</span><b>{s['needs_human']} of {s['findings']}</b></div>
</div>
<h2>Checks before filing</h2><table>{checks}</table>
{t4html}
<h2>Largest open items</h2>
<table><tr><th>Action</th><th>Supplier</th><th>Document</th><th class="num">ITC</th><th>Why</th></tr>{acts}</table>
</body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    return path
