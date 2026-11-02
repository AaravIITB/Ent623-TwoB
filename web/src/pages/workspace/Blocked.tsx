import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type BlockedFlag, type Decision } from "../../api";
import { count, cx, fmtDateShort, fmtNum, inr0, plural } from "../../lib/format";
import { ActionText, Banner, EmptyState, ErrorNote, Panel, TableSkeleton, Tag } from "../../components/ui";
import { DecisionDrawer } from "./DecisionDrawer";
import { useWs } from "./shared";
import { NotReconciled } from "./Workspace";

export default function Blocked() {
  const { period } = useWs();
  if (!period.summary) return <NotReconciled what="Blocked credit" />;
  return <BlockedInner />;
}

type Group = { label: string; section: string; flag: BlockedFlag; rows: { d: Decision; f: BlockedFlag }[]; itc: number; likely: number };

async function fetchAllBlocked(cid: number, p: string): Promise<Decision[]> {
  const out: Decision[] = [];
  let offset = 0;
  for (;;) {
    const pg = await api.decisions(cid, p, { view: "blocked" }, offset, 500);
    out.push(...pg.items);
    offset += pg.items.length;
    if (offset >= pg.total || pg.items.length === 0) break;
  }
  return out;
}

function BlockedInner() {
  const { cid, p, period } = useWs();
  const q = useQuery({ queryKey: ["decisions", cid, p, "blocked-all"], queryFn: () => fetchAllBlocked(cid, p) });
  const [open, setOpen] = useState<Decision | null>(null);

  const groups = useMemo(() => {
    const m = new Map<string, Group>();
    for (const d of q.data ?? []) {
      for (const f of d.blocked) {
        let g = m.get(f.label);
        if (!g) {
          g = { label: f.label, section: f.section, flag: f, rows: [], itc: 0, likely: 0 };
          m.set(f.label, g);
        }
        g.rows.push({ d, f });
        g.itc += d.itc_to_claim;
        if (f.confidence === "Likely") g.likely++;
      }
    }
    return [...m.values()].sort((a, b) => b.itc - a.itc);
  }, [q.data]);

  const totalItc = (q.data ?? []).reduce((s, d) => s + d.itc_to_claim, 0);

  return (
    <div className="p-6 space-y-4 max-w-[1280px]">
      <Banner tone="accent">
        These bills may carry ITC that Sec 17(5) blocks even though they match 2B. <b className="font-semibold">TwoB never reverses ITC by itself</b>: Likely items are
        proposed for Table 4(B)(1), Possible and Review items stay out of the totals until you decide. Open a row to read the exceptions and record your view in the note.
      </Banner>

      {q.isLoading ? (
        <Panel flush>
          <TableSkeleton rows={8} cols={6} />
        </Panel>
      ) : q.error ? (
        <ErrorNote error={q.error} />
      ) : groups.length === 0 ? (
        <Panel>
          <EmptyState title="No possible blocked credit this month">
            Nothing in the ledgers, narrations or HSN/SAC points to a Sec 17(5) block
            {period.summary && period.summary.blocked_review === 0 ? "" : " for the records loaded"}.
          </EmptyState>
        </Panel>
      ) : (
        <>
          <div className="text-sm text-ink-2">
            <b className="font-semibold">{plural(q.data?.length ?? 0, "record")}</b> in {plural(groups.length, "category", "categories")} · {inr0(totalItc)} ITC being claimed on them
          </div>
          {groups.map((g) => (
            <Panel
              key={g.label}
              flush
              title={
                <span className="flex items-center gap-2 flex-wrap">
                  {g.label}
                  <span className="text-sm text-muted font-normal">{g.section}</span>
                </span>
              }
              actions={
                <span className="text-sm num">
                  {plural(g.rows.length, "record")} · <b className="font-semibold">{inr0(g.itc)}</b>
                  {g.likely > 0 && <span className="text-muted"> · {count(g.likely)} likely</span>}
                </span>
              }
            >
              <div className="px-4 py-2.5 text-sm text-ink-2 border-b border-rule bg-sunken">
                {g.flag.advice}
                {g.flag.exceptions && (
                  <details className="mt-1">
                    <summary className="cursor-pointer text-accent text-xs">Exceptions to this block</summary>
                    <p className="mt-1 text-xs leading-relaxed max-w-[90ch]">{g.flag.exceptions}</p>
                  </details>
                )}
              </div>
              <div className="overflow-x-auto">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Supplier</th>
                      <th>Doc no.</th>
                      <th>Date</th>
                      <th>Evidence</th>
                      <th>Confidence</th>
                      <th>IMS action</th>
                      <th className="r">ITC to claim ₹</th>
                      <th>Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {g.rows.map(({ d, f }) => {
                      const doc = d.books[0] ?? d.portal[0];
                      return (
                        <tr key={d.id} className="hoverable cursor-pointer" onClick={() => setOpen(d)}>
                          <td className="max-w-[240px] truncate">{d.supplier_name}</td>
                          <td className="code text-xs">{doc?.doc_no ?? "–"}</td>
                          <td className="text-xs num">{fmtDateShort(doc?.doc_date)}</td>
                          <td className="text-xs text-ink-2 max-w-[280px] truncate" title={f.evidence}>
                            {f.evidence}
                          </td>
                          <td>
                            <Tag tone={f.confidence === "Likely" ? "high" : "review"}>{f.confidence}</Tag>
                          </td>
                          <td>
                            <ActionText action={d.effective} className="text-sm" />
                            {d.final === null && <span className="text-2xs text-faint ml-1">rec.</span>}
                          </td>
                          <td className="r num font-medium">{fmtNum(d.itc_to_claim)}</td>
                          <td className={cx("text-xs max-w-[220px] truncate", d.note ? "text-ink-2" : "text-faint")}>{d.note || "No note"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Panel>
          ))}
        </>
      )}
      {open && <DecisionDrawer decision={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
