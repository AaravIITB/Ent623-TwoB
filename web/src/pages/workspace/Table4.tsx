import { useQuery } from "@tanstack/react-query";
import { api, type Table4Line } from "../../api";
import { useUrlState } from "../../lib/hooks";
import { count, cx, fmtDate, fmtNum, inr0, plural } from "../../lib/format";
import { periodLabel } from "../../lib/period";
import { btnCls, EmptyState, ErrorNote, Panel, Segmented, TableSkeleton } from "../../components/ui";
import { IconDownload } from "../../components/icons";
import { useWs } from "./shared";
import { NotReconciled } from "./Workspace";

const BOLD = new Set(["4(A)(5)", "4(C)"]);

export default function Table4View() {
  const { period } = useWs();
  if (!period.summary) return <NotReconciled what="3B Table 4" />;
  return <Table4Inner />;
}

function Table4Inner() {
  const { cid, p } = useWs();
  const [{ basis: b }, setUrl] = useUrlState(["basis"] as const);
  const basis = b === "recommended" ? "recommended" : "final";
  const q = useQuery({ queryKey: ["table4", cid, p, basis], queryFn: () => api.table4(cid, p, basis), placeholderData: (prev) => prev });
  const t = q.data;

  return (
    <div className="p-6 space-y-4 max-w-[1280px]">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <Segmented
            ariaLabel="Basis"
            value={basis}
            onChange={(v) => setUrl({ basis: v === "final" ? null : v })}
            options={[
              { value: "final", label: "Your final decisions", title: "Final decisions where made, else the recommendation" },
              { value: "recommended", label: "TaxMind's recommendation" },
            ]}
          />
          {t && <span className="text-sm text-muted">Policy for 2B bills not in books: {t.policy === "reverse" ? "claim and reverse" : "keep pending"}</span>}
        </div>
        <a className={btnCls("secondary", "sm")} href={api.exportUrl(cid, p, "ledger.csv")}>
          <IconDownload size={13} /> Download reversal ledger CSV
        </a>
      </div>

      <Panel flush title={`GSTR-3B Table 4, ${periodLabel(p)}`} actions={q.isFetching ? <span className="text-xs text-muted">Updating…</span> : null}>
        {q.isLoading ? (
          <TableSkeleton rows={9} cols={7} />
        ) : q.error ? (
          <div className="p-4">
            <ErrorNote error={q.error} />
          </div>
        ) : t ? (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th className="w-[90px]">Line</th>
                  <th>What goes in it</th>
                  <th className="r">IGST ₹</th>
                  <th className="r">CGST ₹</th>
                  <th className="r">SGST ₹</th>
                  <th className="r">Cess ₹</th>
                  <th className="r">Total ₹</th>
                  <th className="r">Records</th>
                </tr>
              </thead>
              <tbody>{t.lines.map((l) => <Line key={l.code} l={l} />)}</tbody>
            </table>
          </div>
        ) : null}
      </Panel>
      <p className="text-xs text-muted max-w-[90ch]">
        Rule 38/42/43 reversals, imports (4(A)(1)) and ISD (4(A)(4)) are not computed and must be added by the CA. Lines marked "to decide" are not in the totals.
      </p>

      {t && (
        <Panel
          flush
          title={
            <span>
              Reversal ledger <span className="text-sm font-normal text-muted ml-1">carried to next month</span>
            </span>
          }
          actions={
            <span className="text-sm text-muted">
              {plural(t.new_reversals, "new reversal")} · {plural(t.reclaimed, "reclaim")} · {count(t.carried)} carried forward
            </span>
          }
        >
          {t.ledger.length === 0 ? (
            <EmptyState title="Nothing to carry forward">No ITC is reversed in 4(B)(2) this month on this basis.</EmptyState>
          ) : (
            <div className="overflow-auto max-h-[520px]">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Supplier</th>
                    <th>GSTIN</th>
                    <th>Doc no.</th>
                    <th>Date</th>
                    <th>Reversed in</th>
                    <th className="r">IGST ₹</th>
                    <th className="r">CGST ₹</th>
                    <th className="r">SGST ₹</th>
                    <th className="r">Cess ₹</th>
                    <th className="r">Tax ₹</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {t.ledger.map((x, i) => (
                    <tr key={i} className="hoverable">
                      <td className="max-w-[220px] truncate">{x.supplier}</td>
                      <td className="code text-xs text-muted">{x.gstin}</td>
                      <td className="code text-xs">{x.doc_no}</td>
                      <td className="text-xs num">{fmtDate(x.doc_date)}</td>
                      <td className="text-xs">{periodLabel(x.period_reversed)}</td>
                      <td className="r num">{fmtNum(x.igst)}</td>
                      <td className="r num">{fmtNum(x.cgst)}</td>
                      <td className="r num">{fmtNum(x.sgst)}</td>
                      <td className="r num">{fmtNum(x.cess)}</td>
                      <td className="r num font-medium">{fmtNum(x.tax)}</td>
                      <td className="text-xs text-ink-2 max-w-[260px] truncate" title={x.reason}>
                        {x.reason}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={9} className="text-sm font-medium border-t border-rule-strong">
                      Total reversed
                    </td>
                    <td className="r num font-semibold border-t border-rule-strong">{inr0(t.ledger.reduce((s, x) => s + x.tax, 0)).slice(1)}</td>
                    <td className="border-t border-rule-strong" />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}

function Line({ l }: { l: Table4Line }) {
  const toDecide = l.code.endsWith("?");
  const bold = BOLD.has(l.code);
  const cell = (n: number) => (
    <td className={cx("r num", bold && "font-semibold text-ink", toDecide && "text-faint")}>{n === 0 && !bold ? <span className="text-faint">–</span> : fmtNum(n)}</td>
  );
  return (
    <tr className={cx(bold && "[&>td]:bg-accent-soft/60", l.code === "4(C)" && "[&>td]:border-t-2 [&>td]:border-t-accent-line")}>
      <td className={cx("whitespace-nowrap", bold ? "font-semibold text-ink" : toDecide ? "text-faint" : "text-ink-2")}>{toDecide ? l.code.slice(0, -1) : l.code}</td>
      <td className={cx(toDecide ? "text-muted" : bold ? "font-semibold" : "")}>
        {l.label}
        {toDecide && <span className="ml-2 text-2xs font-medium text-review bg-review-soft rounded px-1.5 py-0.5 whitespace-nowrap">to decide, not in totals</span>}
        {l.note && <div className="text-xs text-muted font-normal">{l.note}</div>}
      </td>
      {cell(l.igst)}
      {cell(l.cgst)}
      {cell(l.sgst)}
      {cell(l.cess)}
      {cell(l.total)}
      <td className={cx("r num text-xs", toDecide ? "text-faint" : "text-muted")}>{l.count ? count(l.count) : ""}</td>
    </tr>
  );
}
