"""
TaxMind Module 1 — Streamlit App (wired to real OCR engine)
"""
import sys
sys.path.insert(0, "/home/claude/taxmind")

import streamlit as st
import tempfile, os, time
from pathlib import Path
from extractor import process_document, ExtractionResult

st.set_page_config(
    page_title="TaxMind — Module 1",
    page_icon="📥",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stSidebar"] { background:#f7f7f5; }
[data-testid="stMetric"]  { background:#f3f3f0; border-radius:10px; padding:12px 16px; border:0.5px solid #ddd; }
.conf-high { color:#2d7a2d; font-weight:600; }
.conf-med  { color:#a06000; font-weight:600; }
.conf-low  { color:#c0392b; font-weight:600; }
.field-box { background:#f8f8f6; border-radius:8px; padding:8px 12px; margin:4px 0; border:0.5px solid #e0e0da; }
.flagged   { border-color:#e74c3c !important; background:#fff5f5 !important; }
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
if "results" not in st.session_state:
    st.session_state.results = []   # list of ExtractionResult
if "selected" not in st.session_state:
    st.session_state.selected = 0

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🧠 TaxMind")
    st.caption("CA Intelligence Platform")
    st.divider()
    st.markdown("**→ 📥 Document Ingestion**")
    st.markdown("&nbsp;&nbsp;&nbsp;🏷️ Categoriser")
    st.markdown("&nbsp;&nbsp;&nbsp;🔄 GSTR-2B Recon")
    st.markdown("&nbsp;&nbsp;&nbsp;⚠️ Risk Engine")
    st.markdown("&nbsp;&nbsp;&nbsp;📄 Advisory Report")
    st.markdown("&nbsp;&nbsp;&nbsp;📋 Workflow")
    st.divider()
    st.caption("Module 1 — Live OCR Pipeline")
    st.caption("Engine: PyMuPDF + Tesseract OCR")

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## 📥 Module 1 — Document Ingestion Engine")
st.caption("Upload any Indian invoice, bank statement, GSTR JSON, or Tally XML — fields are extracted automatically.")

# ── Stats ─────────────────────────────────────────────────────────────────────
results = st.session_state.results
n_total     = len(results)
n_approved  = sum(1 for r in results if not r.needs_review)
n_review    = sum(1 for r in results if r.needs_review)
avg_conf    = round(sum(r.overall_confidence for r in results) / max(1, n_total) * 100)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Documents processed", n_total)
c2.metric("Auto-approved ✓",     n_approved)
c3.metric("Needs review ⚠️",     n_review)
c4.metric("Avg. confidence",     f"{avg_conf}%" if n_total else "—")

st.divider()

left, right = st.columns([1.5, 1], gap="large")

# ══════════════════════════════════════════════════════════════════════════════
# LEFT — Upload + Queue
# ══════════════════════════════════════════════════════════════════════════════
with left:
    # ── Upload ────────────────────────────────────────────────────────────────
    st.markdown("#### Upload documents")
    st.caption("Accepted: PDF (digital or scanned), JPG/PNG (invoice photos), XLSX (bank statements), JSON (GSTR exports), XML (Tally exports)")

    uploaded = st.file_uploader(
        "Drop files here",
        accept_multiple_files=True,
        type=["pdf", "jpg", "jpeg", "png", "xlsx", "json", "xml"],
        label_visibility="collapsed",
    )

    if uploaded:
        new_files = [f for f in uploaded if f.name not in [r.filename for r in results]]
        if new_files:
            progress = st.progress(0, text="Starting pipeline…")
            for i, f in enumerate(new_files):
                progress.progress(int((i / len(new_files)) * 80), text=f"Processing {f.name}…")

                # Save to temp file
                suffix = Path(f.name).suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(f.read())
                    tmp_path = tmp.name

                try:
                    result = process_document(tmp_path)
                    result.filename = f.name   # restore original name
                    st.session_state.results.append(result)
                except Exception as e:
                    st.error(f"Failed to process {f.name}: {e}")
                finally:
                    os.unlink(tmp_path)

            progress.progress(100, text="Done ✓")
            time.sleep(0.5)
            progress.empty()
            st.session_state.selected = len(st.session_state.results) - 1
            st.rerun()

    # ── Queue ─────────────────────────────────────────────────────────────────
    if results:
        st.markdown("#### Processing queue")

        for i, r in enumerate(results):
            conf_pct = int(r.overall_confidence * 100)
            status   = "✓ Auto-approved" if not r.needs_review else "⚠ Needs review"
            color    = "#2d7a2d" if not r.needs_review else "#c0392b"
            selected = "→ " if i == st.session_state.selected else "　"

            col_a, col_b = st.columns([4, 1])
            with col_a:
                st.markdown(
                    f"<div style='padding:8px 12px;border-radius:8px;border:0.5px solid #e0e0da;"
                    f"background:{'#f0fff0' if not r.needs_review else '#fff5f5'};margin:3px 0'>"
                    f"<b>{selected}{r.filename}</b><br>"
                    f"<span style='font-size:12px;color:#888'>{r.doc_type} / {r.source_type}</span> &nbsp;"
                    f"<span style='font-size:12px;color:{color}'>{status} ({conf_pct}%)</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )
            with col_b:
                if st.button("View", key=f"view_{i}"):
                    st.session_state.selected = i
                    st.rerun()

        if st.button("🗑 Clear all"):
            st.session_state.results = []
            st.session_state.selected = 0
            st.rerun()
    else:
        st.info("No documents yet — upload a file above to get started.")

# ══════════════════════════════════════════════════════════════════════════════
# RIGHT — Extracted fields for selected document
# ══════════════════════════════════════════════════════════════════════════════
with right:
    if not results:
        st.markdown("#### Extracted fields")
        st.caption("Upload a document on the left to see extracted fields here.")
    else:
        r = results[st.session_state.selected]
        st.markdown(f"#### {r.filename}")

        overall_pct = int(r.overall_confidence * 100)
        if r.needs_review:
            st.error(f"⚠ Overall confidence: {overall_pct}% — human review required")
        else:
            st.success(f"✓ Overall confidence: {overall_pct}% — auto-approved")

        tabs = st.tabs(["📋 Fields", "📦 Line items", "📄 Raw text"])

        # ── Tab 1: Fields ─────────────────────────────────────────────────────
        with tabs[0]:
            def render_field(label, extracted_field):
                if not extracted_field or not extracted_field.value:
                    st.markdown(
                        f"<div class='field-box' style='color:#aaa'>"
                        f"<b style='font-size:11px;color:#aaa'>{label}</b><br>Not found"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                    return

                f = extracted_field
                pct = int(f.confidence * 100)
                if pct >= 85:
                    color, cls = "#2d7a2d", "conf-high"
                elif pct >= 70:
                    color, cls = "#a06000", "conf-med"
                else:
                    color, cls = "#c0392b", "conf-low"

                flag_html = " <span style='color:#c0392b;font-size:11px'>⚠ verify</span>" if f.flagged else ""
                bar_fill = int(f.confidence * 10)
                bar = "█" * bar_fill + "░" * (10 - bar_fill)

                box_class = "field-box flagged" if f.flagged else "field-box"
                st.markdown(
                    f"<div class='{box_class}'>"
                    f"<span style='font-size:11px;color:#888'>{label}</span>{flag_html}<br>"
                    f"<b style='font-size:14px'>{f.value}</b>"
                    f"<span style='float:right;font-size:12px;color:{color};font-family:monospace'>"
                    f"{bar} {pct}%</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )

            st.markdown("**Parties**")
            render_field("Supplier GSTIN", r.supplier_gstin)
            render_field("Buyer GSTIN",    r.buyer_gstin)

            st.markdown("**Invoice details**")
            render_field("Invoice No.",  r.invoice_number)
            render_field("Invoice Date", r.invoice_date)
            render_field("HSN Code",     r.hsn_code)

            st.markdown("**Tax amounts**")
            render_field("Taxable Value", r.taxable_value)
            render_field("CGST",          r.cgst)
            render_field("SGST",          r.sgst)
            render_field("IGST",          r.igst)
            render_field("Total Amount",  r.total_amount)

            st.divider()
            col1, col2 = st.columns(2)
            col1.button("✅ Approve",    use_container_width=True, key="approve")
            col2.button("✏️ Edit fields", use_container_width=True, key="edit")

            if r.errors:
                st.warning(f"Extraction warnings: {'; '.join(r.errors)}")

        # ── Tab 2: Line items ─────────────────────────────────────────────────
        with tabs[1]:
            if r.line_items:
                data = {
                    "Description": [i.description[:40] for i in r.line_items],
                    "HSN":         [i.hsn_code or "—" for i in r.line_items],
                    "Qty":         [i.quantity  or "—" for i in r.line_items],
                    "Amount":      [i.amount    or "—" for i in r.line_items],
                }
                st.dataframe(data, use_container_width=True, hide_index=True)
            else:
                st.caption("No line items extracted for this document type.")

        # ── Tab 3: Raw text ───────────────────────────────────────────────────
        with tabs[2]:
            st.caption("Raw text extracted before field parsing")
            raw = r.raw_text[:3000] + ("…" if len(r.raw_text) > 3000 else "")
            st.text_area("", value=raw, height=300, label_visibility="collapsed")
