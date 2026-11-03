import { useMemo } from "react";
import { Link, Navigate, NavLink, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { permissions, useUser } from "../../lib/auth";
import { count, cx } from "../../lib/format";
import { isPeriod, periodLabel } from "../../lib/period";
import { DeadlineStrip, nextAction, PeriodPicker, StatusStepper } from "../../components/period";
import { Banner, Button, btnCls, EmptyState, ErrorNote, Skeleton, useToast } from "../../components/ui";
import { invalidatePeriod, useWs, WsContext, type WorkspaceCtx } from "./shared";
import Overview from "./Overview";
import Review from "./Review";
import Blocked from "./Blocked";
import Followups from "./Followups";
import Table4View from "./Table4";
import Close from "./Close";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "review", label: "Review" },
  { id: "blocked", label: "Blocked credit" },
  { id: "followups", label: "Follow-ups" },
  { id: "table4", label: "3B Table 4" },
  { id: "close", label: "Close" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export default function Workspace() {
  const params = useParams();
  const cid = Number(params.cid);
  const p = params.period ?? "";
  const tab = (params.tab ?? "overview") as TabId;
  const user = useUser();
  const nav = useNavigate();

  const client = useQuery({ queryKey: ["client", cid], queryFn: () => api.client(cid), enabled: Number.isFinite(cid) });
  const period = useQuery({ queryKey: ["period", cid, p], queryFn: () => api.period(cid, p), enabled: Number.isFinite(cid) && isPeriod(p) });

  const ctx = useMemo<WorkspaceCtx | null>(() => {
    if (!client.data || !period.data) return null;
    return {
      cid,
      p,
      client: client.data,
      period: period.data,
      user,
      can: permissions(user, period.data.status),
      base: `/clients/${cid}/${p}`,
    };
  }, [client.data, period.data, cid, p, user]);

  if (!isPeriod(p) || !TABS.some((t) => t.id === tab)) return <Navigate to={`/clients/${cid}/${isPeriod(p) ? p : ""}`} replace />;

  if (client.error || period.error)
    return (
      <div className="p-6">
        <ErrorNote error={client.error ?? period.error} />
        <Link to="/" className="inline-block mt-3 text-accent text-sm">
          Back to the dashboard
        </Link>
      </div>
    );

  if (!ctx) return <WorkspaceSkeleton />;

  return (
    <WsContext.Provider value={ctx}>
      <div className="min-h-screen flex flex-col">
        <WorkspaceHeader tab={tab} onPeriod={(np) => nav(`/clients/${cid}/${np}/${tab}`)} />
        <div className="flex-1 min-h-0">
          {tab === "overview" && <Overview />}
          {tab === "review" && <Review />}
          {tab === "blocked" && <Blocked />}
          {tab === "followups" && <Followups />}
          {tab === "table4" && <Table4View />}
          {tab === "close" && <Close />}
        </div>
      </div>
    </WsContext.Provider>
  );
}

function WorkspaceHeader({ tab, onPeriod }: { tab: TabId; onPeriod: (p: string) => void }) {
  const { client, period, user, base, cid, p } = useWs();
  const s = period.summary;
  const open = s?.open ?? 0;
  const na = nextAction(period, open, user.role);
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const recon = useMutation({
    mutationFn: () => api.reconcile(cid, p),
    onSuccess: (np) => {
      qc.setQueryData(["period", cid, p], np);
      invalidatePeriod(qc, cid, p);
      toast(`Reconciled: ${count(np.summary?.open ?? 0)} need a person, ${count(np.summary?.auto_cleared ?? 0)} cleared automatically`, "ok");
      nav(`${base}/review`);
    },
    onError: (e) => toast((e as Error).message, "error"),
  });

  return (
    <div className="bg-surface border-b border-rule sticky top-0 z-20">
      <div className="px-6 pt-4 pb-3 flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="text-sm text-muted">
            <Link to="/" className="hover:text-ink">
              Dashboard
            </Link>
            <span className="mx-1.5 text-faint">/</span>
            <Link to={`/clients/${client.id}`} className="hover:text-ink">
              {client.name}
            </Link>
          </div>
          <div className="flex items-center gap-3 mt-1 flex-wrap">
            <h1 className="text-xl font-semibold tracking-[-0.015em] truncate max-w-[520px]" title={client.name}>
              {client.name}
            </h1>
            <span className="code text-sm text-muted">{client.gstin}</span>
            <PeriodPicker value={p} onChange={onPeriod} />
          </div>
          <div className="mt-2.5">
            <StatusStepper status={period.status} />
          </div>
        </div>
        <div className="flex items-center gap-5 flex-wrap">
          <DeadlineStrip compact period={p} imsDeadline={period.ims_deadline} gstr3bDeadline={period.gstr3b_deadline} filed3bOn={period.filed_3b_on} />
          {na.kind === "reconcile" && period.stale ? null : na.kind === "reconcile" ? (
            <Button variant="primary" busy={recon.isPending} onClick={() => recon.mutate()}>
              {recon.isPending ? "Reconciling…" : "Reconcile"}
            </Button>
          ) : na.kind === "done" ? (
            <span className="text-ok font-medium text-base">Closed ✓</span>
          ) : na.kind === "waiting" ? (
            <span className="text-muted text-sm">{na.label}</span>
          ) : na.tab !== tab ? (
            <Button variant="primary" onClick={() => nav(`${base}/${na.tab}`)}>
              {na.label}
            </Button>
          ) : null}
        </div>
      </div>
      {period.stale && (
        <div className="px-6 pb-3">
          <Banner
            tone="review"
            action={
              <Button size="sm" variant="primary" busy={recon.isPending} onClick={() => recon.mutate()}>
                Reconcile again
              </Button>
            }
          >
            Files changed since the last run. Reconcile again to bring the results up to date; your decisions, notes and assignees are kept.
          </Banner>
        </div>
      )}
      <nav className="px-4 flex gap-0.5 -mb-px" aria-label="Month workspace">
        {TABS.map((t) => (
          <NavLink
            key={t.id}
            to={`${base}/${t.id}`}
            className={({ isActive }) =>
              cx(
                "h-9 px-3 inline-flex items-center gap-1.5 text-base border-b-2",
                isActive ? "border-accent text-accent font-medium" : "border-transparent text-ink-2 hover:text-ink hover:border-rule-strong",
              )
            }
          >
            {t.label}
            <TabCount id={t.id} />
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

function TabCount({ id }: { id: TabId }) {
  const { period } = useWs();
  const s = period.summary;
  if (!s) return null;
  const n = id === "review" ? s.open : id === "blocked" ? s.blocked_review : 0;
  if (!n) return null;
  return <span className="text-xs num text-muted bg-sunken border border-rule rounded px-1">{count(n)}</span>;
}


function WorkspaceSkeleton() {
  return (
    <div>
      <div className="bg-surface border-b border-rule px-6 py-4 space-y-3">
        <Skeleton className="h-3 w-40" />
        <Skeleton className="h-6 w-80" />
        <Skeleton className="h-5 w-[520px]" />
      </div>
      <div className="p-6 grid grid-cols-3 gap-4">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
    </div>
  );
}

export function NotReconciled({ what }: { what: string }) {
  const { base, period } = useWs();
  return (
    <EmptyState
      className="mt-10"
      title={`Nothing to show in ${what} yet`}
      action={
        <Link to={`${base}/overview`} className={btnCls("primary")}>
          {period.status === "not_started" ? "Upload files" : "Go to Overview to reconcile"}
        </Link>
      }
    >
      {periodLabel(period.period)} hasn't been reconciled. Upload the purchase register and GSTR-2B, then reconcile.
    </EmptyState>
  );
}
