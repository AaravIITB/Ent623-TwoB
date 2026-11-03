import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type DashboardRow } from "../api";
import { useUser } from "../lib/auth";
import { useUrlState } from "../lib/hooks";
import { count, cx, inr0, inrCompact, timeAgo } from "../lib/format";
import { daysText, daysUntil, isPeriod, periodLabel, previousPeriod } from "../lib/period";
import { PageHeader } from "../components/Layout";
import { DeadlineStrip, nextAction, PeriodPicker } from "../components/period";
import { NewClientDialog } from "../components/NewClientDialog";
import { Button, btnCls, EmptyState, ErrorNote, Input, Panel, Skeleton, StatusChip, TableSkeleton, useToast } from "../components/ui";
import { IconPlus, IconSearch } from "../components/icons";

export default function Dashboard() {
  const user = useUser();
  const [{ period: urlPeriod, q }, setUrl] = useUrlState(["period", "q"] as const);
  const period = isPeriod(urlPeriod) ? urlPeriod : previousPeriod();
  const [newOpen, setNewOpen] = useState(false);
  const dash = useQuery({ queryKey: ["dashboard", period], queryFn: () => api.dashboard(period) });
  const activity = useQuery({ queryKey: ["activity"], queryFn: () => api.activity(30) });
  const qc = useQueryClient();
  const toast = useToast();
  const seed = useMutation({
    mutationFn: api.seedDemo,
    onSuccess: (r) => {
      toast(`Loaded ${r.clients} demo clients with Jun 2026 reconciled`, "ok");
      qc.invalidateQueries();
      setUrl({ period: "062026" });
    },
    onError: (e) => toast((e as Error).message, "error"),
  });

  const rows = useMemo(() => {
    const all = dash.data?.rows ?? [];
    const needle = q.trim().toLowerCase();
    const filtered = needle ? all.filter((r) => r.client.name.toLowerCase().includes(needle) || r.client.gstin.toLowerCase().includes(needle)) : all;
    return filtered;
  }, [dash.data, q]);

  const t = dash.data?.totals;

  return (
    <div className="pb-10">
      <PageHeader
        title={`${periodLabel(period, true)} returns`}
        subtitle="Every client's purchase register against GSTR-2B for this return month."
        actions={
          <>
            <PeriodPicker value={period} onChange={(p) => setUrl({ period: p })} />
            <Button variant="primary" onClick={() => setNewOpen(true)}>
              <IconPlus /> New client
            </Button>
          </>
        }
      />

      <div className="px-6 space-y-4">
        {dash.data && (
          <div className="flex items-center justify-between gap-4 flex-wrap bg-surface border border-rule rounded-lg px-4 py-3">
            <DeadlineStrip period={period} imsDeadline={dash.data.ims_deadline} gstr3bDeadline={dash.data.gstr3b_deadline} />
            <p className="text-sm text-muted max-w-sm">
              Anything left without an IMS action on the {Number(dash.data.ims_deadline.slice(8, 10))}th is deemed accepted when 2B is generated.
            </p>
          </div>
        )}

        <KpiStrip loading={dash.isLoading} totals={t} />

        <ErrorNote error={dash.error} />

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
          <Panel
            flush
            title={
              <span>
                Clients <span className="text-muted font-normal">{dash.data ? count(rows.length) : ""}</span>
              </span>
            }
            actions={
              <div className="relative">
                <IconSearch className="absolute left-2 top-1/2 -translate-y-1/2 text-faint" size={14} />
                <Input value={q} onChange={(e) => setUrl({ q: e.target.value })} placeholder="Find client or GSTIN" className="h-7 pl-7 w-56 text-sm" />
              </div>
            }
          >
            {dash.isLoading ? (
              <TableSkeleton rows={6} cols={7} />
            ) : rows.length === 0 && (dash.data?.rows.length ?? 0) === 0 ? (
              <EmptyState
                title="No clients yet"
                action={
                  <div className="flex gap-2 justify-center">
                    <Button variant="primary" onClick={() => setNewOpen(true)}>
                      <IconPlus /> Add your first client
                    </Button>
                    {user.role === "admin" && (
                      <Button busy={seed.isPending} onClick={() => seed.mutate()}>
                        Load six demo clients
                      </Button>
                    )}
                  </div>
                }
              >
                Add a client with its GSTIN, then upload its purchase register and GSTR-2B for the month.
              </EmptyState>
            ) : rows.length === 0 ? (
              <EmptyState title="No client matches that search" />
            ) : (
              <ClientTable rows={rows} period={period} deadline3b={dash.data?.gstr3b_deadline ?? ""} />
            )}
          </Panel>

          <Panel title="Recent activity" flush className="self-start">
            {activity.isLoading ? (
              <div className="p-4 space-y-3">
                {Array.from({ length: 5 }, (_, i) => (
                  <Skeleton key={i} className="h-8" />
                ))}
              </div>
            ) : (activity.data ?? []).length === 0 ? (
              <p className="p-4 text-sm text-muted">Uploads, reconciliations and approvals show up here.</p>
            ) : (
              <ol className="divide-y divide-rule max-h-[560px] overflow-auto">
                {(activity.data ?? []).map((a, i) => (
                  <li key={i} className="px-4 py-2.5 text-sm">
                    <div className="text-ink">
                      <span className="font-medium">{a.user}</span> {a.action}{" "}
                      <ActivityClient a={a} />
                    </div>
                    {a.detail && <div className="text-xs text-muted mt-0.5 line-clamp-2">{a.detail}</div>}
                    <div className="text-2xs text-faint mt-0.5">{timeAgo(a.at)}</div>
                  </li>
                ))}
              </ol>
            )}
          </Panel>
        </div>
      </div>

      <NewClientDialog open={newOpen} onClose={() => setNewOpen(false)} period={period} />
    </div>
  );
}

function ActivityClient({ a }: { a: { client: string; period: string; client_id?: number } }) {
  const label = (
    <>
      {a.client}
      {a.period && isPeriod(a.period) ? `, ${periodLabel(a.period)}` : ""}
    </>
  );
  if (a.client_id && isPeriod(a.period))
    return (
      <Link className="text-accent hover:underline" to={`/clients/${a.client_id}/${a.period}/overview`}>
        {label}
      </Link>
    );
  return <span className="text-ink-2">{label}</span>;
}

function KpiStrip({ totals, loading }: { totals?: { clients: number; not_started: number; in_progress: number; in_review: number; closed: number; open_items: number; itc_at_risk: number }; loading: boolean }) {
  const cells: { label: string; value: string; tone?: string; title?: string }[] = totals
    ? [
        { label: "Clients", value: count(totals.clients) },
        { label: "Not started", value: count(totals.not_started) },
        { label: "In progress", value: count(totals.in_progress) },
        { label: "In review", value: count(totals.in_review) },
        { label: "Closed", value: count(totals.closed), tone: totals.closed > 0 ? "text-ok" : undefined },
        { label: "Open items", value: count(totals.open_items) },
        { label: "ITC at risk", value: inrCompact(totals.itc_at_risk), tone: totals.itc_at_risk > 0 ? "text-high" : undefined, title: inr0(totals.itc_at_risk) },
      ]
    : [];
  return (
    <div className="grid grid-cols-4 md:grid-cols-7 bg-surface border border-rule rounded-lg divide-x divide-rule">
      {loading || !totals
        ? Array.from({ length: 7 }, (_, i) => (
            <div key={i} className="px-4 py-3">
              <Skeleton className="h-3 w-16 mb-2" />
              <Skeleton className="h-6 w-12" />
            </div>
          ))
        : cells.map((c) => (
            <div key={c.label} className="px-4 py-3" title={c.title}>
              <div className="text-xs text-muted">{c.label}</div>
              <div className={cx("text-2xl font-semibold num tracking-[-0.02em] mt-0.5", c.tone ?? "text-ink")}>{c.value}</div>
            </div>
          ))}
    </div>
  );
}

function ClientTable({ rows, period, deadline3b }: { rows: DashboardRow[]; period: string; deadline3b: string }) {
  const user = useUser();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [running, setRunning] = useState<number | null>(null);

  async function reconcile(cid: number) {
    setRunning(cid);
    try {
      const p = await api.reconcile(cid, period);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast(`Reconciled: ${count(p.summary?.open ?? 0)} open items`, "ok");
      nav(`/clients/${cid}/${period}/review`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setRunning(null);
    }
  }

  return (
    <div className="overflow-x-auto">
      <table className="tbl">
        <thead>
          <tr>
            <th>Client</th>
            <th>Status</th>
            <th className="r">Open items</th>
            <th className="r">ITC at risk ₹</th>
            <th className="r">High checks</th>
            <th className="r">Follow-ups open</th>
            <th className="r">3B due</th>
            <th className="r">Next step</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const na = nextAction(r.period, r.open, user.role);
            const href = `/clients/${r.client.id}/${period}/${na.tab}`;
            const closedOrFiled = r.period?.status === "closed" || !!r.period?.filed_3b_on;
            // Same clock as the deadline strip above (the server's days_to_3b can differ by a day across time zones).
            const days = daysUntil(r.period?.gstr3b_deadline ?? deadline3b);
            return (
              <tr key={r.client.id} className="hoverable cursor-pointer" onClick={() => nav(`/clients/${r.client.id}/${period}/overview`)}>
                <td className="max-w-[300px]">
                  <Link to={`/clients/${r.client.id}/${period}/overview`} className="font-medium text-ink hover:text-accent block truncate" onClick={(e) => e.stopPropagation()}>
                    {r.client.name}
                  </Link>
                  <div className="code text-xs text-muted">{r.client.gstin}</div>
                </td>
                <td>
                  <StatusChip status={r.period?.status} />
                </td>
                <td className="r num">{r.open > 0 ? count(r.open) : <span className="text-faint">0</span>}</td>
                <td className={cx("r num", r.itc_at_risk > 0 && "text-ink")}>{r.itc_at_risk > 0 ? inr0(r.itc_at_risk).slice(1) : <span className="text-faint">–</span>}</td>
                <td className="r num">{r.high_checks > 0 ? <span className="text-high font-semibold">{r.high_checks}</span> : <span className="text-faint">0</span>}</td>
                <td className="r num">{r.followups_open > 0 ? count(r.followups_open) : <span className="text-faint">0</span>}</td>
                <td className={cx("r num", !closedOrFiled && days < 0 && "text-high", !closedOrFiled && days >= 0 && days <= 3 && "text-review font-medium")}>
                  {r.period?.filed_3b_on ? <span className="text-ok">Filed</span> : r.period?.status === "closed" ? <span className="text-muted">–</span> : daysText(days)}
                </td>
                <td className="r" onClick={(e) => e.stopPropagation()}>
                  {na.kind === "reconcile" ? (
                    <Button size="sm" variant="primary" busy={running === r.client.id} onClick={() => reconcile(r.client.id)}>
                      Reconcile
                    </Button>
                  ) : na.kind === "done" ? (
                    <Link to={href} className="text-sm text-ok font-medium px-2.5">
                      Closed ✓
                    </Link>
                  ) : na.kind === "waiting" ? (
                    <Link to={href} className="text-sm text-muted px-2.5 hover:text-ink">
                      {na.label}
                    </Link>
                  ) : (
                    <Link to={href} title={na.hint} className={btnCls("secondary", "sm", "!text-accent")}>
                      {na.label}
                    </Link>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
