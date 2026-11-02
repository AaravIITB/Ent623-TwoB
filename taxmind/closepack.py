"""Month-close pack: a dated, tamper-evident record of how a month was reconciled.

Why: notices can arrive up to 42 months after the annual return due date (Sec 74A),
and the GST portal does not keep a history of IMS decisions - the latest action
overwrites earlier ones and accepted/rejected records leave IMS once GSTR-3B is filed.
The pack is what a CA shows when someone asks "why was this ITC claimed?"

The pack (a .zip) contains:
  record.html         the human-readable close record (print it to PDF if needed)
  record.pdf          same, as PDF (when the 'reportlab' package is installed)
  decisions.csv/.json every decision: recommendation, final decision, CA note, reason, ITC
  reconciliation.xlsx the full TwoB workbook
  inputs/             exact copies of the files the reconciliation was run on
  manifest.json       SHA-256 of every file + who / when; its own hash is the pack fingerprint
A changed file no longer matches its SHA-256. The 'pack fingerprint' (SHA-256 of manifest.json, also in the
zip comment) should be noted outside the pack - in the client file or the covering email - so that even a
rebuilt manifest is caught.
"""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .models import Action, Status
from .recommend import dt, inr

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:          # pragma: no cover
    IST = None

ACTIONS = [a.value for a in Action]
OTHER_PERIOD = (Status.LATE_FILED, Status.EARLIER_PERIOD)


@dataclass
class Decision:
    fid: str
    recommended: str
    final: str
    note: str = ""

    @property
    def overridden(self) -> bool:
        return self.final != self.recommended


@dataclass
class CloseInfo:
    preparer: str = ""
    reviewer: str = ""
    overrides: dict = field(default_factory=dict)      # fid -> (final action, note)
    closed_at: datetime | None = None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_overrides(path: str | Path) -> dict:
    """Read CA decisions from an edited TwoB workbook ('All findings' sheet) or a CSV
    with columns ID, Final decision, CA note."""
    import pandas as pd
    p = Path(path)
    if p.suffix.lower() == ".csv":
        df = pd.read_csv(p, dtype=str)
    else:
        sheets = pd.read_excel(p, sheet_name=None, dtype=str)
        df = sheets.get("All findings", next(iter(sheets.values())))
    cols = {c.strip().lower(): c for c in df.columns}
    idc, fc, nc = cols.get("id"), cols.get("final decision"), cols.get("ca note")
    if not idc or not fc:
        raise ValueError(f"{p.name}: needs columns 'ID' and 'Final decision'")
    out = {}
    for _, r in df.iterrows():
        fid, final = str(r[idc] or "").strip(), str(r[fc] or "").strip()
        if not fid or final.lower() in ("", "nan", "none"):
            continue
        match = next((a for a in ACTIONS if a.lower() == final.lower()), None)
        if not match:
            raise ValueError(f"{p.name}: '{final}' for {fid} is not one of {', '.join(ACTIONS)}")
        note = "" if not nc or str(r[nc]) in ("nan", "None") else str(r[nc]).strip()
        out[fid] = (match, note)
    return out


def final_decisions(res, overrides: dict) -> list[Decision]:
    out = []
    for f in res.findings:
        final, note = overrides.get(f.fid, (f.action.value, ""))
        out.append(Decision(f.fid, f.action.value, final, note))
    return out


def claim_with(status_name: str, recommended: str, final: str, itc_to_claim: float, itc_in_2b: float,
               has_portal: bool, all_available: bool) -> float:
    """ITC a decision claims once the CA's final action replaces TwoB's recommendation.

    The one rule used everywhere (close record, 3B Table 4, the web app's progress figures):
      unchanged                -> TwoB's amount
      Accept                   -> the 2B amount (if every record is available); a reclaim keeps its amount
      Reject / Pending         -> nothing this month
      No IMS action            -> TwoB's amount when it recommended Accept / no action (deemed accepted),
                                  otherwise nothing
    """
    if not final or final == recommended:
        return itc_to_claim
    if final == Action.ACCEPT.value:
        if status_name in ("LATE_FILED",):
            return 0.0
        if status_name == "EARLIER_PERIOD":
            return itc_to_claim if itc_to_claim else itc_in_2b
        return itc_in_2b if (has_portal and all_available) else 0.0
    if final == Action.NONE.value:
        return itc_to_claim if recommended in (Action.ACCEPT.value, Action.NONE.value) else 0.0
    return 0.0


def finding_claim(f, final: str | None) -> float:
    return claim_with(f.status.name, f.action.value, final or f.action.value, f.itc_to_claim, f.itc_in_2b,
                      bool(f.portal), all(p.itc_available is not False for p in f.portal))


def final_claim(res, decisions: list[Decision]) -> float:
    """ITC to claim after the CA's decisions (recommended amount where unchanged)."""
    by = {d.fid: d for d in decisions}
    return round(sum(finding_claim(f, by[f.fid].final if f.fid in by else None) for f in res.findings), 2)


def _rows(res, decisions):
    by = {d.fid: d for d in decisions}
    for f in res.findings:
        d = by[f.fid]
        yield {
            "ID": f.fid, "Status": f.status.value, "Recommended": d.recommended, "Final decision": d.final,
            "Changed by CA": "Yes" if d.overridden else "", "CA note": d.note,
            "Confidence": f.confidence.value, "Who acts": f.owner.value,
            "Supplier GSTIN": f.supplier_gstin, "Supplier": f.supplier_name,
            "2B doc(s)": " + ".join(x.doc_no for x in f.portal),
            "2B date": dt(f.portal[0].doc_date) if f.portal else "",
            "Books doc(s)": " + ".join(x.doc_no for x in f.books),
            "Books date": dt(f.books[0].doc_date) if f.books else "",
            "ITC in 2B": f.itc_in_2b, "ITC in books": f.itc_in_books, "ITC to claim (recommended)": f.itc_to_claim,
            "Reason": f.reason, "Next step": f.next_step,
            "Blocked credit": "; ".join(f"{b.label} ({b.section}, {b.confidence})" for b in f.blocked),
            "Flags": "; ".join(f.flags),
        }


def _record_html(res, info, decisions, inputs, fingerprint_note, claim_final) -> str:
    e = html.escape
    s = res.summary
    over = [d for d in decisions if d.overridden]
    by_f = {f.fid: f for f in res.findings}
    lvl = {"High": "#b42318", "Review": "#b54708", "OK": "#067647"}
    checks = "".join(f"<tr><td><b style='color:{lvl[c.level]}'>{c.level}</b></td><td>{e(c.name)}</td>"
                     f"<td>{e(c.detail)}</td></tr>" for c in res.checks)
    overs = "".join(f"<tr><td>{d.fid}</td><td>{e(by_f[d.fid].supplier_name or by_f[d.fid].supplier_gstin)}</td>"
                    f"<td>{e(((by_f[d.fid].portal or by_f[d.fid].books)[0]).doc_no)}</td><td>{d.recommended}</td>"
                    f"<td><b>{d.final}</b></td><td>{e(d.note)}</td></tr>" for d in over) or \
        "<tr><td colspan='6'>None - all recommendations accepted as made.</td></tr>"
    blocked = "".join(
        f"<tr><td>{f.fid}</td><td>{e(f.supplier_name or f.supplier_gstin)}</td>"
        f"<td>{e(((f.books or f.portal)[0]).doc_no)}</td><td>{e(b.label)} ({e(b.section)})</td>"
        f"<td>{e(b.confidence)}</td><td>{e(b.evidence)}</td></tr>"
        for f in res.findings for b in f.blocked) or "<tr><td colspan='6'>None flagged.</td></tr>"
    files = "".join(f"<tr><td>{e(n)}</td><td>{sz:,} bytes</td><td><code>{h}</code></td></tr>" for n, sz, h in inputs)
    when = info.closed_at.strftime("%d %b %Y, %H:%M %Z") if info.closed_at else ""
    counts = {}
    for d in decisions:
        counts[d.final] = counts.get(d.final, 0) + 1
    count_txt = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Month-close record - {e(res.client)} - {e(res.period_label)}</title>
<style>body{{font-family:system-ui,Segoe UI,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#1d2939}}
h1{{font-size:22px;margin:0}} h2{{font-size:16px;margin:26px 0 8px}} table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border-bottom:1px solid #eaecf0;padding:6px 8px;text-align:left;vertical-align:top}} .muted{{color:#667085;font-size:13px}}
code{{font-size:11px;word-break:break-all}} .box{{border:1px solid #d0d5dd;border-radius:8px;padding:10px 14px;margin-top:12px}}</style></head><body>
<h1>Month-close record: {e(res.client or 'Client')}, {e(res.period_label)}</h1>
<div class="muted">GSTR-2B / IMS reconciliation closed with TwoB. Keep this pack with the client's GST file.</div>
<div class="box"><b>Closed:</b> {e(when)} &nbsp;·&nbsp; <b>Prepared by:</b> {e(info.preparer or '-')} &nbsp;·&nbsp;
<b>Reviewed by:</b> {e(info.reviewer or '-')}<br><b>Data fingerprint:</b> <code>{fingerprint_note}</code><br><span class="muted">One SHA-256 over every input
file, the decisions and the workbook in this pack. Note it in the client file or the email that sends this pack:
if any of those files is changed later, the fingerprint will no longer match.</span></div>
<h2>Result</h2><table>
<tr><td>Purchase entries in books</td><td>{s['books_entries']}</td></tr>
<tr><td>Records in GSTR-2B</td><td>{s['portal_records']}</td></tr>
<tr><td>ITC as per books / as per 2B</td><td>{inr(s['itc_books'])} / {inr(s['itc_2b'])}</td></tr>
<tr><td>ITC recommended by TwoB</td><td>{inr(s['itc_to_claim'])}</td></tr>
<tr><td><b>ITC after the CA's decisions</b></td><td><b>{inr(claim_final)}</b></td></tr>
<tr><td>Decisions</td><td>{len(decisions)} ({e(count_txt)}); changed by CA: {len(over)}</td></tr></table>
<h2>Decisions changed by the CA</h2><table><tr><th>ID</th><th>Supplier</th><th>Document</th><th>Recommended</th><th>Final</th><th>CA note</th></tr>{overs}</table>
<h2>Checks before filing</h2><table>{checks}</table>
<h2>Possible blocked credit (Sec 17(5)) reviewed</h2><table><tr><th>ID</th><th>Supplier</th><th>Document</th><th>Possible block</th><th>Confidence</th><th>Why flagged</th></tr>{blocked}</table>
<h2>Files this record is based on</h2><table><tr><th>File</th><th>Size</th><th>SHA-256</th></tr>{files}</table>
<p class="muted">Every decision, with its reason and ITC, is in decisions.csv / decisions.json. manifest.json lists the SHA-256 of
every file in this pack; if any file is changed later its hash will no longer match. Recommendations are TwoB's defaults;
final decisions are the CA's.</p></body></html>"""


def _record_pdf(res, info, decisions, claim_final, fingerprint) -> bytes | None:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table
    except Exception:
        return None
    buf = io.BytesIO()
    st = getSampleStyleSheet()
    s = res.summary
    over = [d for d in decisions if d.overridden]
    rs = "Rs "      # the PDF base font has no rupee glyph
    story = [Paragraph(f"Month-close record: {html.escape(res.client or 'Client')}, {res.period_label}", st["Title"]),
             Paragraph(f"Closed {info.closed_at.strftime('%d %b %Y %H:%M %Z') if info.closed_at else ''}; "
                       f"prepared by {html.escape(info.preparer or '-')}; reviewed by {html.escape(info.reviewer or '-')}",
                       st["Normal"]),
             Paragraph(f"Data fingerprint: {fingerprint}", st["Code"]), Spacer(1, 10)]
    rows = [["Purchase entries in books", str(s["books_entries"])], ["Records in GSTR-2B", str(s["portal_records"])],
            ["ITC as per books", rs + inr(s["itc_books"])[1:]], ["ITC as per 2B", rs + inr(s["itc_2b"])[1:]],
            ["ITC recommended", rs + inr(s["itc_to_claim"])[1:]], ["ITC after CA decisions", rs + inr(claim_final)[1:]],
            ["Decisions / changed by CA", f"{len(decisions)} / {len(over)}"]]
    story += [Table(rows, colWidths=[220, 200]), Spacer(1, 10), Paragraph("Checks before filing", st["Heading2"])]
    for c in res.checks:
        story.append(Paragraph(f"<b>{c.level}</b> - {html.escape(c.name)}: {html.escape(c.detail).replace(chr(8377), 'Rs ')}",
                               st["Normal"]))
    if over:
        story.append(Paragraph("Decisions changed by the CA", st["Heading2"]))
        for d in over:
            story.append(Paragraph(f"{d.fid}: {d.recommended} -> <b>{d.final}</b>. {html.escape(d.note)}", st["Normal"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Full decisions are in decisions.csv; file hashes are in manifest.json.", st["Italic"]))
    SimpleDocTemplate(buf, pagesize=A4, title=f"Month-close {res.period_label}").build(story)
    return buf.getvalue()


def build_close_pack(res, out_path: str | Path, input_files=(), info: CloseInfo | None = None) -> Path:
    from . import __version__
    from .report import write_excel
    info = info or CloseInfo()
    info.closed_at = info.closed_at or (datetime.now(IST) if IST else datetime.now())
    decisions = final_decisions(res, info.overrides)
    claim_final = final_claim(res, decisions)
    files: dict[str, bytes] = {}

    seen = set()
    inputs_meta = []
    resolved = set()
    for p in map(Path, input_files):
        if p.resolve() in resolved:               # the same workbook given as books and as 2B
            continue
        resolved.add(p.resolve())
        name = p.name
        while name in seen:                       # two inputs with the same name
            name = "_" + name
        seen.add(name)
        data = p.read_bytes()
        files[f"inputs/{name}"] = data
        inputs_meta.append((name, len(data), _sha(data)))

    rows = list(_rows(res, decisions))
    sio = io.StringIO()
    w = csv.DictWriter(sio, fieldnames=list(rows[0].keys()) if rows else ["ID"])
    w.writeheader()
    w.writerows(rows)
    files["decisions.csv"] = sio.getvalue().encode("utf-8-sig")
    files["decisions.json"] = json.dumps({
        "client": res.client, "period": res.period, "summary": res.summary, "itc_after_ca_decisions": claim_final,
        "checks": [c.__dict__ for c in res.checks], "decisions": rows, "notes": res.notes,
    }, indent=1, default=str, ensure_ascii=False).encode("utf-8")
    if getattr(res, "table4", None):
        from .gstr3b import LEDGER_FIELDS, after_decisions, table_csv
        t4 = after_decisions(res, decisions)
        files["gstr3b_table4.csv"] = table_csv(t4).encode("utf-8-sig")
        lio = io.StringIO()
        lw = csv.DictWriter(lio, fieldnames=LEDGER_FIELDS)
        lw.writeheader()
        for it in t4["ledger"]:
            lw.writerow({k: getattr(it, k) for k in LEDGER_FIELDS})
        files["itc_reversal_ledger.csv"] = lio.getvalue().encode("utf-8")
    tmp = Path(out_path).with_suffix(".tmp.xlsx")
    write_excel(res, tmp)
    files["reconciliation.xlsx"] = tmp.read_bytes()
    tmp.unlink()

    # Data fingerprint: one hash over the inputs, decisions and workbook. It is printed on the record,
    # so the record and the data it describes are tied together.
    data_fp = _sha("\n".join(f"{n}:{_sha(b)}" for n, b in sorted(files.items())).encode())
    files["record.html"] = _record_html(res, info, decisions, inputs_meta, data_fp, claim_final).encode("utf-8")
    pdf = _record_pdf(res, info, decisions, claim_final, data_fp)
    if pdf:
        files["record.pdf"] = pdf

    manifest = {
        "kind": "TwoB month-close pack", "engine_version": __version__,
        "client": res.client, "period": res.period, "closed_at": info.closed_at.isoformat(),
        "prepared_by": info.preparer, "reviewed_by": info.reviewer,
        "settings": {"amount_tolerance": res.config.amount_tolerance,
                     "amount_tolerance_pct": getattr(res.config, "amount_tolerance_pct", 0.0),
                     "line_of_business": getattr(res.config, "line_of_business", ""),
                     "not_in_books_policy": getattr(res.config, "not_in_books_policy", "pending")},
        "itc_recommended": res.summary["itc_to_claim"], "itc_after_ca_decisions": claim_final,
        "decisions": len(decisions), "changed_by_ca": sum(d.overridden for d in decisions),
        "data_fingerprint": data_fp,
        "files": {n: {"sha256": _sha(b), "bytes": len(b)} for n, b in sorted(files.items())},
    }
    mbytes = json.dumps(manifest, indent=1, ensure_ascii=False).encode("utf-8")
    fingerprint = _sha(mbytes)
    files["manifest.json"] = mbytes

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.comment = f"TwoB month-close pack {res.period} fingerprint {fingerprint}".encode()
        for n, b in files.items():
            z.writestr(n, b)
    return out


def pack_fingerprint(path: str | Path) -> str:
    with zipfile.ZipFile(path) as z:
        return _sha(z.read("manifest.json"))


def verify_pack(path: str | Path, expected_fingerprint: str = "") -> tuple[bool, list[str]]:
    """Re-check every file in a pack against manifest.json (and, if given, the fingerprint noted at close)."""
    problems = []
    with zipfile.ZipFile(path) as z:
        mbytes = z.read("manifest.json")
        manifest = json.loads(mbytes)
        if expected_fingerprint and _sha(mbytes) != expected_fingerprint.strip().lower():
            problems.append("manifest.json does not match the fingerprint noted when the month was closed")
        names = {n for n in z.namelist() if not n.endswith("/")}
        for name, meta in manifest["files"].items():
            if name not in names:
                problems.append(f"{name} is missing")
            elif _sha(z.read(name)) != meta["sha256"]:
                problems.append(f"{name} has been changed")
        data = {n: m["sha256"] for n, m in manifest["files"].items() if not n.startswith("record.")}
        if _sha("\n".join(f"{n}:{h}" for n, h in sorted(data.items())).encode()) != manifest.get("data_fingerprint"):
            problems.append("data fingerprint does not match the files listed in manifest.json")
        extra = names - set(manifest["files"]) - {"manifest.json"}
        problems += [f"{n} was added after the pack was made" for n in sorted(extra)]
    return (not problems), problems
