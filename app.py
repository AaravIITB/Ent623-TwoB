"""TwoB - Streamlit app.

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

st.set_page_config(page_title="TwoB", page_icon="🧾", layout="wide")

with st.sidebar:
    st.markdown("### TwoB")
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


def _run(book_paths, portal_paths, client, period, planned, tol, opts=None):
    from taxmind.gstr3b import load_ledger
    from taxmind.loaders.tabular import detect_client_gstin
    opts = opts or {}
    books, n1 = load_many(book_paths, Side.BOOKS)
    portal, n2 = load_many(portal_paths, Side.PORTAL, period=period or "")
    gstin = opts.get("gstin") or next((g for g in (detect_client_gstin(x) for x in list(book_paths) + list(portal_paths))
                                       if g), "")
    cfg = Config(amount_tolerance=tol, amount_tolerance_pct=opts.get("tol_pct", 0.0),
                 line_of_business=",".join(opts.get("lob", [])), client_gstin=gstin,
                 not_in_books_policy=opts.get("policy", "pending"))
    prior = load_ledger(opts["ledger"]) if opts.get("ledger") else None
    master = None
    if opts.get("master"):
        from taxmind.prepare import load_vendor_master
        master = load_vendor_master(opts["master"])
    res = reconcile(books, portal, period=period or "", client=client, cfg=cfg,
                    planned_itc=planned, notes=n1 + n2, prior_ledger=prior, vendor_master=master)
    tmp = Path(tempfile.mkdtemp())
    st.session_state.res = res
    st.session_state.inputs = [Path(x) for x in list(book_paths) + list(portal_paths)]
    st.session_state.pop("pack", None)
    st.session_state.pop("imported", None)
    st.session_state.xlsx = write_excel(res, tmp / f"twob_{res.period}.xlsx").read_bytes()
    st.session_state.html = write_html(res, tmp / f"twob_{res.period}_prefiling.html").read_bytes()
    from taxmind.gstr3b import write_ledger
    st.session_state.ledger = write_ledger(res.table4.get("ledger", []),
                                           tmp / f"twob_{res.period}_itc_reversal_ledger.csv").read_bytes()


def recon_page():
    st.markdown("## GSTR-2B / IMS reconciliation")
    st.caption("Upload the client's purchase register and the GSTR-2B (this month, plus next month to catch "
               "late filers). TwoB matches them and recommends Accept / Reject / Pending for every record, "
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
    from taxmind.blocked import LINES_OF_BUSINESS
    opts = {}
    with st.expander("Client settings (tolerance %, line of business, last month's reversal ledger)"):
        e1, e2, e3 = st.columns([1, 1, 2])
        opts["tol_pct"] = e1.number_input("…or tolerance as % of amount", min_value=0.0, max_value=5.0, value=0.0,
                                          step=0.05, help="Whichever is larger of ₹ and % is treated as rounding")
        opts["gstin"] = e2.text_input("Client GSTIN", value="", help="Blank = read from a 3B summary sheet if present")
        opts["lob"] = e3.multiselect("Line of business (switches off blocks that don't apply)",
                                     list(LINES_OF_BUSINESS), help="; ".join(f"{k}: {v}" for k, v in LINES_OF_BUSINESS.items()))
        e4, e5 = st.columns([1, 2])
        opts["policy"] = e4.radio("2B bills not in books", ["pending", "reverse"],
                                  format_func=lambda x: "Keep Pending in IMS" if x == "pending"
                                  else "Accept, reverse in 4(B)(2)")
        led = e5.file_uploader("Last month's ITC reversal ledger (CSV from TwoB)", type=["csv"], key="led_up")
        if led is not None:
            lp = Path(tempfile.mkdtemp()) / led.name
            lp.write_bytes(led.getbuffer())
            opts["ledger"] = lp
        vm = st.file_uploader("Vendor master (GSTIN, name, Activity, ITC eligibility)", type=["xlsx", "xls", "csv"],
                              key="vm_up")
        if vm is not None:
            vp = Path(tempfile.mkdtemp()) / vm.name
            vp.write_bytes(vm.getbuffer())
            opts["master"] = vp
    b1, b2, _ = st.columns([1, 1.6, 4])
    if b1.button("Reconcile", type="primary", disabled=not (books_up and portal_up)):
        folder = Path(tempfile.mkdtemp())
        try:
            _run(_save_uploads(books_up, folder / "books"), _save_uploads(portal_up, folder / "portal"),
                 client, period, planned or None, tol, opts)
        except ValueError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Could not read the files: {e}")
    if b2.button("Try with sample data"):
        _ensure_sample()
        try:
            _run([SAMPLE / "purchase_register_092026.xlsx"],
                 [SAMPLE / "gstr2b_092026.json", SAMPLE / "gstr2b_102026.json"],
                 client or "Sharma Auto Components (sample)", period, planned or None, tol, opts)
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

    nb = sum(len(f.blocked) for f in res.findings)
    tabs = st.tabs(["IMS decisions", "Books not in 2B", f"Blocked credit ({nb})", "3B Table 4", "By supplier",
                    "Supplier messages", "Client questions", "Month-close", "Downloads", "Loading notes"])
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
        blocked_tab(res)
    with tabs[3]:
        t4 = res.table4 or {}
        st.caption("What to enter in GSTR-3B Table 4, from the current recommendations. Lines ending in '?' are "
                   "for the CA to decide and are not in the totals.")
        st.dataframe(pd.DataFrame([{"Table": ln.code, "Line": ln.label, "IGST": ln.amounts["igst"],
                                    "CGST": ln.amounts["cgst"], "SGST/UTGST": ln.amounts["sgst"],
                                    "Cess": ln.amounts["cess"], "Total": ln.total, "Records": ln.count}
                                   for ln in t4.get("lines", [])]), width="stretch", hide_index=True)
        st.caption(f"Reversal ledger: {t4.get('new_reversals', 0)} reversed this month, {t4.get('carried', 0)} carried "
                   f"from earlier months, {t4.get('reclaimed', 0)} reclaimed now. Download it from Downloads and "
                   "load it next month.")
    with tabs[4]:
        st.caption("One line per supplier. Use it to decide many records at once - e.g. every ticket from an "
                   "airline that the client books in another register.")
        st.dataframe(pd.DataFrame(res.suppliers).drop(columns=["in_books"], errors="ignore"), width="stretch",
                     hide_index=True, height=480)
    with tabs[5]:
        if not res.supplier_messages:
            st.caption("No supplier needs to fix anything.")
        for msg in res.supplier_messages:
            with st.expander(f"{msg.supplier_name} · {msg.items} item(s) · {inr(msg.itc_at_stake)} ITC"):
                st.text_area("WhatsApp", msg.whatsapp, height=180, key=f"wa_{msg.supplier_gstin}")
                st.text_input("Email subject", msg.email_subject, key=f"es_{msg.supplier_gstin}")
                st.text_area("Email body", msg.email_body, height=220, key=f"eb_{msg.supplier_gstin}")
    with tabs[6]:
        st.dataframe(pd.DataFrame(res.client_questions), width="stretch", hide_index=True)
    with tabs[7]:
        close_tab(res)
    with tabs[8]:
        st.download_button("Download Excel workbook", st.session_state.xlsx,
                           file_name=f"twob_{res.period}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.download_button("Download pre-filing report (HTML)", st.session_state.html,
                           file_name=f"twob_{res.period}_prefiling.html", mime="text/html")
        if st.session_state.get("ledger"):
            st.download_button("Download ITC reversal ledger (load next month)", st.session_state.ledger,
                               file_name=f"twob_{res.period}_itc_reversal_ledger.csv", mime="text/csv")
    with tabs[9]:
        for n in res.notes:
            st.markdown(f"- {n}")


def blocked_tab(res):
    st.caption("Invoices that match 2B can still carry ITC the law blocks under Sec 17(5) — food, motor "
               "vehicles, club fees, gifts, CSR, construction. TwoB reads the ledger, item description, "
               "HSN/SAC and supplier name and flags these for review. It does not reverse anything itself: "
               "most blocks have exceptions.")
    rows = []
    for f in res.findings:
        for fl in f.blocked:
            d = (f.books or f.portal)[0]
            rows.append({"Confidence": fl.confidence, "Possible block": fl.label, "Section": fl.section,
                         "Supplier": f.supplier_name or d.supplier_gstin, "Doc no.": d.doc_no,
                         "Date": dt(d.doc_date), "ITC (₹)": round(max(f.itc_to_claim, f.itc_in_books, 0), 2),
                         "Why flagged": fl.evidence, "What to do": fl.advice,
                         "When ITC is still allowed": fl.exceptions, "IMS action": f.action.value, "ID": f.fid})
    if not rows:
        st.success("Nothing in this month's purchases looks like blocked credit. (Needs ledger names, item "
                   "descriptions or HSN/SAC in the books to check properly.)")
        return
    df = pd.DataFrame(rows)
    df["_o"] = df["Confidence"].map({"Likely": 0, "Review": 1, "Possible": 2})
    df = df.sort_values(["_o", "ITC (₹)"], ascending=[True, False]).drop(columns="_o")
    st.metric("ITC on possible blocked credit", inr(df["ITC (₹)"].sum()), help=f"{len(df)} flags")
    st.dataframe(df, width="stretch", hide_index=True, height=420)


def close_tab(res):
    from taxmind.closepack import ACTIONS, CloseInfo, build_close_pack, final_claim, final_decisions, load_overrides, \
        pack_fingerprint
    st.caption("Record the final decision for each item, then create a dated month-close pack: the decisions, "
               "the reasons, who prepared and reviewed it, and exact copies of the files used, each with a "
               "SHA-256 hash. Keep it with the client file — notices can come up to 42 months later, and the "
               "portal does not keep a history of IMS actions.")
    with st.expander("Import decisions from an edited TwoB workbook"):
        up = st.file_uploader("Workbook with 'Final decision' / 'CA note' filled in on the All findings sheet",
                              type=["xlsx", "csv"], key="dec_up")
        if up is not None:
            tmp = Path(tempfile.mkdtemp()) / up.name
            tmp.write_bytes(up.getbuffer())
            try:
                st.session_state.imported = load_overrides(tmp)
                st.success(f"Read {len(st.session_state.imported)} decisions.")
            except ValueError as e:
                st.error(str(e))
    imported = st.session_state.get("imported", {})
    rows = []
    for f in res.findings:
        fin, note = imported.get(f.fid, (f.action.value, ""))
        d = (f.portal or f.books)[0]
        rows.append({"ID": f.fid, "Needs a person": "Yes" if f.needs_human else "", "Recommended": f.action.value,
                     "Final decision": fin, "CA note": note, "Supplier": f.supplier_name or f.supplier_gstin,
                     "Document": d.doc_no, "ITC to claim (₹)": f.itc_to_claim, "Status": f.status.value,
                     "Reason": f.reason})
    df = pd.DataFrame(rows).sort_values(["Needs a person", "ITC to claim (₹)"], ascending=[False, False])
    ed = st.data_editor(df, hide_index=True, width="stretch", height=420, key=f"close_ed_{len(imported)}",
                        disabled=[c for c in df.columns if c not in ("Final decision", "CA note")],
                        column_config={"Final decision": st.column_config.SelectboxColumn(options=ACTIONS,
                                                                                          required=True),
                                       "CA note": st.column_config.TextColumn(width="medium")})
    overrides = {r["ID"]: (r["Final decision"], r["CA note"] or "") for _, r in ed.iterrows()
                 if r["Final decision"] != r["Recommended"] or (r["CA note"] or "").strip()}
    decisions = final_decisions(res, overrides)
    changed = sum(d.overridden for d in decisions)
    c1, c2, c3 = st.columns([1, 1, 1])
    c1.metric("Changed by CA", changed)
    c2.metric("ITC after CA decisions", inr(final_claim(res, decisions)),
              delta=None if not changed else inr(final_claim(res, decisions) - res.summary["itc_to_claim"]))
    n1, n2, n3 = st.columns([1, 1, 1])
    prep = n1.text_input("Prepared by", key="prep")
    rev = n2.text_input("Reviewed by (CA)", key="rev")
    n3.write("")
    if n3.button("Create month-close pack", type="primary", disabled=not prep.strip()):
        out = Path(tempfile.mkdtemp()) / f"twob_{res.period}_close_pack.zip"
        build_close_pack(res, out, input_files=st.session_state.get("inputs", []),
                         info=CloseInfo(preparer=prep.strip(), reviewer=rev.strip(), overrides=overrides))
        st.session_state.pack = (out.read_bytes(), pack_fingerprint(out), out.name)
    if not prep.strip():
        st.caption("Enter who prepared it to create the pack.")
    if st.session_state.get("pack"):
        data, fp, name = st.session_state.pack
        st.download_button("Download month-close pack (.zip)", data, file_name=name, mime="application/zip")
        st.markdown(f"**Pack fingerprint** — note it in the client file or the covering email:  \n`{fp}`")
        st.caption("To check a pack later: `python -m taxmind verify <pack.zip> --fingerprint <fingerprint>`")


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
