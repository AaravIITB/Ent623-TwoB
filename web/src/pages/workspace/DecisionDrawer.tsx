import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ACTIONS, api, type Action, type Decision, type DocOut } from "../../api";
import { useAssignableUsers } from "../../lib/hooks";
import { cx, fmtDate, fmtDateTime, fmtNum, inr } from "../../lib/format";
import { periodLabel } from "../../lib/period";
import { ACTION_KEY, ActionText, Button, Drawer, Kbd, Select, Tag, Textarea } from "../../components/ui";
import { IconChevronLeft, IconChevronRight } from "../../components/icons";
import { useDecisionActions } from "./decisions";
import { useWs } from "./shared";

export function DecisionDrawer({
  decision,
  onClose,
  onPrev,
  onNext,
  position,
}: {
  decision: Decision;
  onClose: () => void;
  onPrev?: () => void;
  onNext?: () => void;
  position?: string;
}) {
  const { cid, p, can, user } = useWs();
  const { patch } = useDecisionActions(cid, p);
  // Fresh copy (another user may have changed it); the list row is the placeholder.
  const fresh = useQuery({
    queryKey: ["decision", cid, p, decision.id],
    queryFn: () => api.decision(cid, p, decision.id),
    placeholderData: decision,
    staleTime: 5_000,
  });
  const d = fresh.data ?? decision;
  const users = useAssignableUsers(user);
  const [note, setNote] = useState(d.note);
  useEffect(() => setNote(d.note), [d.id, d.note]);
  const locked = can.decide;

  const setFinal = (final: Action | null | "recommended" | "history") => patch.mutate({ id: d.id, final, prev: d });

  return (
    <Drawer
      open
      onClose={onClose}
      width={720}
      title={
        <span className="flex items-center gap-2">
          {d.status}
          {d.blocked.length > 0 && <Tag tone="review">Blocked credit?</Tag>}
        </span>
      }
      subtitle={
        <span>
          {d.supplier_name || "Unknown supplier"} <span className="code ml-1">{d.supplier_gstin || "(no GSTIN)"}</span>
          <span className="ml-2 text-faint">{d.fid}</span>
        </span>
      }
      footer={
        <div className="flex items-center justify-between gap-3 text-xs text-muted">
          <span>{d.updated_by ? `Last changed by ${d.updated_by}, ${fmtDateTime(d.updated_at)}` : "Not changed by anyone yet"}</span>
          <span className="flex items-center gap-1.5">
            {position && <span className="mr-1">{position}</span>}
            <Button size="xs" variant="secondary" onClick={onPrev} disabled={!onPrev} title="Previous (k)">
              <IconChevronLeft size={12} /> Prev
            </Button>
            <Button size="xs" variant="secondary" onClick={onNext} disabled={!onNext} title="Next (j)">
              Next <IconChevronRight size={12} />
            </Button>
          </span>
        </div>
      }
    >
      <div className="px-5 py-4 space-y-5">
        {/* Decision */}
        <section className="rounded-md border border-rule bg-sunken p-3.5">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="text-sm">
              TaxMind recommends <ActionText action={d.recommended} />
              <span className="text-muted">
                {" "}
                · {d.confidence} confidence · who acts: <b className="font-medium text-ink-2">{d.owner}</b>
              </span>
            </div>
            {d.final === null ? <Tag>No final decision yet</Tag> : <Tag tone="accent">Final: {d.final}</Tag>}
          </div>
          <div className="mt-3 flex items-center gap-1.5 flex-wrap">
            {ACTIONS.map((a) => (
              <Button
                key={a}
                size="sm"
                variant={d.final === a ? "primary" : "secondary"}
                disabledReason={locked}
                onClick={() => setFinal(d.final === a ? null : a)}
                title={`${a} (${ACTION_KEY[a]})`}
              >
                {a} <Kbd>{ACTION_KEY[a]}</Kbd>
              </Button>
            ))}
            <span className="w-px h-5 bg-rule-strong mx-1" />
            <Button size="sm" variant="quiet" disabledReason={locked} onClick={() => setFinal("recommended")} title="Use the recommendation (u)">
              Use recommendation
            </Button>
            {d.final !== null && (
              <Button size="sm" variant="ghost" disabledReason={locked} onClick={() => setFinal(null)}>
                Clear
              </Button>
            )}
          </div>
          {d.history && (
            <div className="mt-3 flex items-center gap-2 text-sm flex-wrap">
              <HistoryChip h={d.history} />
              {d.history.note && <span className="text-muted italic truncate max-w-[340px]">"{d.history.note}"</span>}
              <Button size="xs" variant="quiet" disabledReason={locked} onClick={() => setFinal("history")} title="Same as last month (h)">
                Same as last month
              </Button>
            </div>
          )}
        </section>

        <section>
          <h3 className="text-sm font-semibold text-ink mb-1">Why</h3>
          <p className="text-base text-ink-2 leading-relaxed">{d.reason}</p>
          {d.next_step && (
            <>
              <h3 className="text-sm font-semibold text-ink mt-3 mb-1">Next step</h3>
              <p className="text-base text-ink-2 leading-relaxed">{d.next_step}</p>
            </>
          )}
        </section>

        <ItcRow d={d} />

        {d.blocked.length > 0 && (
          <section>
            <h3 className="text-sm font-semibold text-ink mb-2">Possible blocked credit (Sec 17(5))</h3>
            <div className="space-y-2">
              {d.blocked.map((b) => (
                <div key={b.rid} className="rounded-md border border-review/30 bg-review-soft/50 p-3 text-sm">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-ink">{b.label}</span>
                    <span className="text-muted">{b.section}</span>
                    <Tag tone={b.confidence === "Likely" ? "high" : "review"}>{b.confidence}</Tag>
                  </div>
                  {b.evidence && <div className="mt-1 text-ink-2">Evidence: {b.evidence}</div>}
                  {b.advice && <div className="mt-1.5 text-ink-2">{b.advice}</div>}
                  {b.exceptions && (
                    <details className="mt-1.5">
                      <summary className="cursor-pointer text-accent text-xs">Exceptions</summary>
                      <p className="mt-1 text-ink-2 text-xs leading-relaxed">{b.exceptions}</p>
                    </details>
                  )}
                </div>
              ))}
            </div>
            <p className="text-xs text-muted mt-1.5">TaxMind never reverses ITC by itself. Record your view in the note.</p>
          </section>
        )}

        <DocsCompare books={d.books} portal={d.portal} />

        {d.flags.length > 0 && (
          <section>
            <h3 className="text-sm font-semibold text-ink mb-1">Flags</h3>
            <ul className="space-y-1 text-sm text-ink-2">
              {d.flags.map((f, i) => (
                <li key={i} className="pl-3 relative before:content-[''] before:absolute before:left-0 before:top-[0.6em] before:w-1 before:h-1 before:rounded-full before:bg-faint">
                  {f}
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="grid grid-cols-[1fr_220px] gap-4">
          <label className="block">
            <span className="block text-sm font-semibold text-ink mb-1">Note</span>
            <Textarea
              rows={3}
              value={note}
              disabled={!!locked}
              placeholder="Why you decided this (goes into the close pack)"
              onChange={(e) => setNote(e.target.value)}
              onBlur={() => note !== d.note && patch.mutate({ id: d.id, note })}
            />
            <span className="text-2xs text-muted">Saved when you leave the box.</span>
          </label>
          <label className="block">
            <span className="block text-sm font-semibold text-ink mb-1">Assigned to</span>
            <Select
              value={d.assignee?.id ?? ""}
              disabled={!!locked}
              onChange={(e) => patch.mutate({ id: d.id, assignee_id: e.target.value ? Number(e.target.value) : null })}
            >
              <option value="">Nobody</option>
              {(users.data ?? []).map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                  {u.id === user.id ? " (me)" : ""}
                </option>
              ))}
              {d.assignee && !(users.data ?? []).some((u) => u.id === d.assignee!.id) && <option value={d.assignee.id}>{d.assignee.name}</option>}
            </Select>
          </label>
        </section>
      </div>
    </Drawer>
  );
}

export function HistoryChip({ h, compact }: { h: NonNullable<Decision["history"]>; compact?: boolean }) {
  return (
    <span
      className={cx("inline-flex items-center gap-1 rounded border border-accent-line bg-accent-soft text-accent whitespace-nowrap", compact ? "h-4.5 px-1 text-2xs" : "h-5.5 px-1.5 text-xs")}
      title={`${h.label || periodLabel(h.period)}: staff chose ${h.final} for ${h.count} similar record${h.count === 1 ? "" : "s"} from this supplier`}
    >
      {compact ? "Last month" : `${h.label || "Last month"}`}: <b className="font-semibold">{h.final === "No IMS action" ? "No IMS" : h.final}</b>
      <span className="opacity-70">({h.count})</span>
    </span>
  );
}

function ItcRow({ d }: { d: Decision }) {
  const cells = [
    { label: "ITC in 2B", v: d.itc_in_2b },
    { label: "ITC in books", v: d.itc_in_books },
    { label: "To claim", v: d.itc_to_claim, strong: true },
    { label: "At stake", v: d.itc_at_stake },
  ];
  return (
    <div className="grid grid-cols-4 border border-rule rounded-md divide-x divide-rule">
      {cells.map((c) => (
        <div key={c.label} className="px-3 py-2">
          <div className="text-xs text-muted">{c.label}</div>
          <div className={cx("num", c.strong ? "font-semibold text-base" : "text-base")}>{inr(c.v)}</div>
        </div>
      ))}
    </div>
  );
}

type FieldDef = { key: keyof DocOut; label: string; kind: "text" | "amount" | "date" | "bool" | "code" };
const FIELDS: FieldDef[] = [
  { key: "doc_no", label: "Document no.", kind: "code" },
  { key: "doc_date", label: "Date", kind: "date" },
  { key: "doc_type", label: "Type", kind: "text" },
  { key: "supplier_gstin", label: "Supplier GSTIN", kind: "code" },
  { key: "supplier_name", label: "Supplier name", kind: "text" },
  { key: "taxable", label: "Taxable", kind: "amount" },
  { key: "igst", label: "IGST", kind: "amount" },
  { key: "cgst", label: "CGST", kind: "amount" },
  { key: "sgst", label: "SGST", kind: "amount" },
  { key: "cess", label: "Cess", kind: "amount" },
  { key: "tax", label: "Total tax", kind: "amount" },
  { key: "period", label: "Return month", kind: "text" },
  { key: "itc_available", label: "ITC available", kind: "bool" },
  { key: "reverse_charge", label: "Reverse charge", kind: "bool" },
  { key: "ledger", label: "Ledger", kind: "text" },
  { key: "description", label: "Narration", kind: "text" },
  { key: "voucher_no", label: "Voucher no.", kind: "text" },
  { key: "source", label: "Source", kind: "text" },
  { key: "row_ref", label: "Row", kind: "text" },
];
// Fields worth comparing between books and 2B.
const COMPARE = new Set<keyof DocOut>(["doc_no", "doc_date", "doc_type", "supplier_gstin", "taxable", "igst", "cgst", "sgst", "cess", "tax"]);

function norm(v: unknown): string {
  return String(v ?? "").replace(/[^A-Za-z0-9]/g, "").replace(/^0+/, "").toUpperCase();
}

function differs(f: FieldDef, books: DocOut[], portal: DocOut[]): boolean {
  if (!COMPARE.has(f.key) || !books.length || !portal.length) return false;
  if (f.kind === "amount") {
    const sb = books.reduce((s, d) => s + Number(d[f.key] ?? 0), 0);
    const sp = portal.reduce((s, d) => s + Number(d[f.key] ?? 0), 0);
    return Math.abs(sb - sp) > 0.5;
  }
  const a = new Set(books.map((d) => (f.key === "doc_no" ? norm(d[f.key]) : String(d[f.key] ?? ""))));
  const b = new Set(portal.map((d) => (f.key === "doc_no" ? norm(d[f.key]) : String(d[f.key] ?? ""))));
  if (a.size !== b.size) return true;
  for (const x of a) if (!b.has(x)) return true;
  return false;
}

function show(f: FieldDef, d: DocOut): React.ReactNode {
  const v = d[f.key];
  if (f.kind === "amount") return <span className="num">{fmtNum(Number(v ?? 0))}</span>;
  if (f.kind === "date") return fmtDate(v as string | null);
  if (f.kind === "bool") return v === null || v === undefined ? "–" : v ? "Yes" : "No";
  if (f.key === "period") return v ? periodLabel(String(v)) : "–";
  if (f.kind === "code") return <span className="code">{String(v || "–")}</span>;
  const s = String(v ?? "");
  return s ? s : <span className="text-faint">–</span>;
}

function DocsCompare({ books, portal }: { books: DocOut[]; portal: DocOut[] }) {
  type Col = { d: DocOut | null; side: "Books" | "2B"; n: number };
  const cols: Col[] = [
    ...(books.length ? books.map((d, i) => ({ d, side: "Books" as const, n: i + 1 })) : [{ d: null, side: "Books" as const, n: 0 }]),
    ...(portal.length ? portal.map((d, i) => ({ d, side: "2B" as const, n: i + 1 })) : [{ d: null, side: "2B" as const, n: 0 }]),
  ];
  const real = cols.filter((c) => c.d);
  if (!real.length) return null;
  const rows = FIELDS.filter((f) =>
    real.some((c) => {
      const v = c.d![f.key];
      return v !== "" && v !== null && v !== undefined && !(f.key === "cess" && v === 0);
    }),
  );
  const both = books.length > 0 && portal.length > 0;
  const anyDiff = rows.some((f) => differs(f, books, portal));
  const firstPortal = cols.findIndex((c) => c.side === "2B");
  const colW = `${Math.floor(100 / cols.length)}%`;
  return (
    <section>
      <div className="flex items-baseline justify-between mb-1.5">
        <h3 className="text-sm font-semibold text-ink">Books and 2B</h3>
        {both && <span className="text-xs text-muted">{anyDiff ? "Fields that differ are highlighted" : "No differences in the compared fields"}</span>}
      </div>
      <div className="border border-rule rounded-md overflow-x-auto">
        <table className="tbl" style={{ tableLayout: "fixed" }}>
          <colgroup>
            <col style={{ width: 118 }} />
            {cols.map((_, i) => (
              <col key={i} style={{ width: colW }} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th />
              {cols.map((c, i) => (
                <th key={i} className={cx(i === firstPortal && "border-l border-rule-strong", !c.d && "text-faint")}>
                  {c.side}
                  {(c.side === "Books" ? books : portal).length > 1 ? ` ${c.n}` : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => {
              const diff = differs(f, books, portal);
              return (
                <tr key={f.key}>
                  <td className={cx("text-muted text-xs", diff && "text-review font-medium")}>{f.label}</td>
                  {cols.map((c, i) => (
                    <td
                      key={i}
                      className={cx(
                        f.kind === "amount" && "r",
                        diff && "bg-review-soft text-ink font-medium",
                        i === firstPortal && "border-l border-rule-strong",
                        "break-words",
                        (f.key === "description" || f.key === "source") && "text-xs",
                      )}
                    >
                      {c.d ? show(f, c.d) : f.key === "doc_no" ? <span className="text-faint text-xs">{c.side === "Books" ? "Not in books" : "Not in 2B"}</span> : null}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {real.some((c) => c.d!.notes.length > 0) && (
        <ul className="mt-2 space-y-0.5 text-xs text-muted">
          {real.flatMap((c, i) => c.d!.notes.map((n, j) => <li key={`${i}-${j}`}>{c.side}: {n}</li>))}
        </ul>
      )}
    </section>
  );
}
