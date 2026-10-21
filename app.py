"""TaxMind - Streamlit app.

Run:  streamlit run app.py
Pages:
  1. 2B / IMS reconciliation  (the engine)
  2. Invoice reader           (Module 1: OCR of invoices)
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from taxmind import Config, Side, load_many, reconcile
from taxmind.models import Status
from taxmind.recommend import dt, inr
from taxmind.report import write_excel, write_html

HERE = Path(__file__).parent
SAMPLE = HERE / "sample_data"

st.set_page_config(page_title="TaxMind", page_icon="🧾", layout="wide")

with st.sidebar:
    st.markdown("### TaxMind")
    st.caption("GSTR-2B / IMS reconciliation for CA firms")
    page = st.radio("Page", ["2B / IMS reconciliation", "Invoice reader (Module 1)"], label_visibility="collapsed")
    st.divider()
    st.caption("Recommendations are defaults for a CA to review, not filing advice.")


# ══════════════════════════════════════════════════════════════════════════════
# Reconciliation
# ══════════════════════════════════════════════════════════════════════════════
def _save_uploads(files, folder: Path) -> list[Path]:
    """Each upload in its own sub-folder, so two files with the same name don't overwrite."""
    out = []
    for i, f in enumerate(files or []):
        sub = folder / f"{i:02d}"
        sub.mkdir(parents=True, exist_ok=True)
        p = sub / f.name
        p.write_bytes(f.getbuffer())
        out.append(p)
    return out


def _ensure_sample():
    if not (SAMPLE / "truth.json").exists():
        from taxmind.synth import generate
        generate(SAMPLE)


def _run(book_paths, portal_paths, client, period, planned, tol):
    books, n1 = load_many(book_paths, Side.BOOKS)
    portal, n2 = load_many(portal_paths, Side.PORTAL, period=period or "")
    res = reconcile(books, portal, period=period or "", client=client, cfg=Config(amount_tolerance=tol),
                    planned_itc=planned, notes=n1 + n2)
    tmp = Path(tempfile.mkdtemp())
    st.session_state.res = res
    st.session_state.xlsx = write_excel(res, tmp / f"taxmind_{res.period}.xlsx").read_bytes()
    st.session_state.html = write_html(res, tmp / f"taxmind_{res.period}_prefiling.html").read_bytes()


def recon_page():
    st.markdown("## GSTR-2B / IMS reconciliation")
    st.caption("Upload the client's purchase register and the GSTR-2B (this month, plus next month to catch "
               "late filers). TaxMind matches them and recommends Accept / Reject / Pending for every record, "
               "with the reason.")
    c1, c2 = st.columns(2)
    with c1:
        books_up = st.file_uploader("Purchase register (Excel / CSV / Tally XML)", accept_multiple_files=True,
                                    type=["xlsx", "xls", "csv", "xml"])
    with c2:
        portal_up = st.file_uploader("GSTR-2B / IMS (JSON or Excel from the portal)", accept_multiple_files=True,
                                     type=["json", "xlsx", "xls", "csv"])
    c3, c4, c5, c6 = st.columns([2, 1, 1, 1])
    client = c3.text_input("Client name", value="")
    period = c4.text_input("Period (MMYYYY)", value="", help="Leave blank to use the earliest 2B loaded")
    planned = c5.number_input("ITC you plan to claim (₹)", min_value=0.0, value=0.0, step=1000.0,
                              help="Optional. Used for the DRC-01C check; blank = ITC as per books")
    tol = c6.number_input("Rounding tolerance (₹)", min_value=0.0, value=1.0, step=0.5)
    b1, b2, _ = st.columns([1, 1.6, 4])
    if b1.button("Reconcile", type="primary", disabled=not (books_up and portal_up)):
        folder = Path(tempfile.mkdtemp())
        try:
            _run(_save_uploads(books_up, folder / "books"), _save_uploads(portal_up, folder / "portal"),
                 client, period, planned or None, tol)
        except ValueError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Could not read the files: {e}")
    if b2.button("Try with sample data"):
        _ensure_sample()
        try:
            _run([SAMPLE / "purchase_register_092026.xlsx"],
                 [SAMPLE / "gstr2b_092026.json", SAMPLE / "gstr2b_102026.json"],
                 client or "Sharma Auto Components (sample)", period, planned or None, tol)
        except ValueError as e:
            st.error(str(e))

    res = st.session_state.get("res")
    if not res:
        st.info("Upload files and press Reconcile, or try the sample data.")
        return
    s = res.summary
    st.divider()
    st.markdown(f"### {res.client or 'Client'} · {res.period_label}")
    m = st.columns(5)
    m[0].metric("ITC as per books", inr(s["itc_books"]))
    m[1].metric("ITC as per 2B", inr(s["itc_2b"]))
    m[2].metric("Recommended claim", inr(s["itc_to_claim"]))
    m[3].metric("Cleared automatically", f"{s['auto_cleared']} of {s['findings']}")
    m[4].metric("Need a person", s["needs_human"], help=f"{inr(s['itc_needing_attention'])} ITC")

    st.markdown("#### Before filing GSTR-3B")
    icon = {"High": "🔴", "Review": "🟠", "OK": "🟢"}
    for c in res.checks:
        st.markdown(f"{icon[c.level]} **{c.name}** — {c.detail}")

    tabs = st.tabs(["IMS decisions", "Books not in 2B", "Supplier messages", "Client questions",
                    "Downloads", "Loading notes"])
    other = (Status.LATE_FILED, Status.EARLIER_PERIOD)
    with tabs[0]:
        rows = []
        for f in res.findings:
            if f.status in other:
                continue
            for p in f.portal:
                rows.append({"Recommended": f.action.value, "Confidence": f.confidence.value,
                             "Who acts": f.owner.value, "Supplier": p.supplier_name or f.supplier_name,
                             "GSTIN": p.supplier_gstin, "2B doc no.": p.doc_no, "Date": dt(p.doc_date),
                             "Tax (₹)": round(p.tax, 2),
                             "Books doc no.": ", ".join(b.doc_no for b in f.books),
                             "Status": f.status.value, "Reason": f.reason, "Next step": f.next_step,
                             "Flags": "; ".join(f.flags), "_human": f.needs_human})
        df = pd.DataFrame(rows)
        if not df.empty:
            order = {"Reject": 0, "Pending": 1, "Accept": 2, "No IMS action": 3}
            df["_o"] = df["Recommended"].map(order).fillna(9) * 10 + df["Confidence"].map(
                {"Low": 0, "Medium": 1, "High": 2}).fillna(3)
            df = df.sort_values(["_o", "Tax (₹)"], ascending=[True, False])
            f1, f2, f3 = st.columns(3)
            act = f1.multiselect("Recommended", sorted(df["Recommended"].unique()))
            conf = f2.multiselect("Confidence", ["High", "Medium", "Low"])
            hide = f3.checkbox("Only items that need a person", value=True)
            view = df
            if act:
                view = view[view["Recommended"].isin(act)]
            if conf:
                view = view[view["Confidence"].isin(conf)]
            if hide:
                view = view[view["_human"]]
            st.caption(f"{len(view)} of {len(df)} records")
            st.dataframe(view.drop(columns=["_human", "_o"]), width="stretch", hide_index=True, height=480)
    with tabs[1]:
        rows = []
        for f in res.findings:
            if f.portal and f.status not in other:
                continue
            for b in f.books:
                rows.append({"Status": f.status.value, "Who acts": f.owner.value, "Supplier": b.supplier_name,
                             "GSTIN": b.supplier_gstin, "Doc no.": b.doc_no, "Date": dt(b.doc_date),
                             "Tax (₹)": round(b.tax, 2), "Reason": f.reason, "Next step": f.next_step,
                             "Flags": "; ".join(f.flags)})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=420)
    with tabs[2]:
        if not res.supplier_messages:
            st.caption("No supplier needs to fix anything.")
        for msg in res.supplier_messages:
            with st.expander(f"{msg.supplier_name} · {msg.items} item(s) · {inr(msg.itc_at_stake)} ITC"):
                st.text_area("WhatsApp", msg.whatsapp, height=180, key=f"wa_{msg.supplier_gstin}")
                st.text_input("Email subject", msg.email_subject, key=f"es_{msg.supplier_gstin}")
                st.text_area("Email body", msg.email_body, height=220, key=f"eb_{msg.supplier_gstin}")
    with tabs[3]:
        st.dataframe(pd.DataFrame(res.client_questions), width="stretch", hide_index=True)
    with tabs[4]:
        st.download_button("Download Excel workbook", st.session_state.xlsx,
                           file_name=f"taxmind_{res.period}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.download_button("Download pre-filing report (HTML)", st.session_state.html,
                           file_name=f"taxmind_{res.period}_prefiling.html", mime="text/html")
    with tabs[5]:
        for n in res.notes:
            st.markdown(f"- {n}")


# ══════════════════════════════════════════════════════════════════════════════
# Module 1 - invoice reader (OCR)
# ══════════════════════════════════════════════════════════════════════════════
def reader_page():
    st.markdown("## Invoice reader (Module 1)")
    st.caption("Upload invoice PDFs or photos to extract GSTIN, invoice no., date and tax. "
               "Needs Tesseract OCR installed for scanned files and photos.")
    try:
        from extractor import process_document
    except Exception as e:                     # PyMuPDF / pytesseract missing
        st.error(f"Module 1 dependencies are not installed: {e}")
        return
    up = st.file_uploader("Invoices", accept_multiple_files=True, type=["pdf", "jpg", "jpeg", "png"])
    if not up:
        return
    for f in up:
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(f.name).suffix) as tmp:
            tmp.write(f.getbuffer())
            path = tmp.name
        try:
            r = process_document(path)
        except Exception as e:
            st.error(f"{f.name}: {e}")
            continue
        finally:
            os.unlink(path)
        status = "needs review" if r.needs_review else "looks complete"
        with st.expander(f"{f.name} · {int(r.overall_confidence * 100)}% · {status}", expanded=r.needs_review):
            fields = [("Supplier GSTIN", r.supplier_gstin), ("Buyer GSTIN", r.buyer_gstin),
                      ("Invoice no.", r.invoice_number), ("Invoice date", r.invoice_date),
                      ("Taxable value", r.taxable_value), ("CGST", r.cgst), ("SGST", r.sgst),
                      ("IGST", r.igst), ("Total", r.total_amount), ("HSN", r.hsn_code)]
            st.dataframe(pd.DataFrame([{"Field": k, "Value": (v.value if v else None),
                                        "Confidence": (int(v.confidence * 100) if v and v.value else 0),
                                        "Check": "⚠" if (not v or v.flagged) else ""} for k, v in fields]),
                         hide_index=True, width="stretch")
            if r.errors:
                st.warning("; ".join(r.errors))


if page.startswith("2B"):
    recon_page()
else:
    reader_page()
