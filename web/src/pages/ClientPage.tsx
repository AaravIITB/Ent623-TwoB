import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type ClientSettings } from "../api";
import { useUser } from "../lib/auth";
import { count, fmtDate, fmtDateTime, inr0 } from "../lib/format";
import { periodLabel, previousPeriod } from "../lib/period";
import { PageHeader } from "../components/Layout";
import { SettingsFields } from "../components/ClientForm";
import { PeriodPicker } from "../components/period";
import { Button, btnCls, Dialog, EmptyState, ErrorNote, Field, Input, Panel, Skeleton, StatusChip, Textarea, useToast } from "../components/ui";
import { FilePickButton } from "./workspace/Overview";

export default function ClientPage() {
  const cid = Number(useParams().cid);
  const user = useUser();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["client", cid], queryFn: () => api.client(cid) });
  const c = q.data;

  const [name, setName] = useState("");
  const [gstin, setGstin] = useState("");
  const [trade, setTrade] = useState("");
  const [notes, setNotes] = useState("");
  const [settings, setSettings] = useState<ClientSettings | null>(null);
  const [gstinError, setGstinError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [openMonth, setOpenMonth] = useState(previousPeriod());

  useEffect(() => {
    if (!c) return;
    setName(c.name);
    setGstin(c.gstin);
    setTrade(c.trade_name);
    setNotes(c.notes);
    setSettings(c.settings);
  }, [c]);

  const dirty = !!c && !!settings && (name !== c.name || gstin !== c.gstin || trade !== c.trade_name || notes !== c.notes || JSON.stringify(settings) !== JSON.stringify(c.settings));

  const save = useMutation({
    mutationFn: () => api.updateClient(cid, { name: name.trim(), gstin: gstin.trim().toUpperCase(), trade_name: trade, notes, settings: settings! }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client", cid] });
      qc.invalidateQueries({ queryKey: ["clients"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast("Client saved. Reconcile a month again to apply new settings.", "ok");
    },
    onError: (e) => {
      if (e instanceof ApiError && /gstin/i.test(e.message)) setGstinError(e.message);
      else toast((e as Error).message, "error");
    },
  });
  const vendor = useMutation({
    mutationFn: (f: File) => api.uploadVendorMaster(cid, f),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client", cid] });
      toast("Vendor master saved", "ok");
    },
    onError: (e) => toast((e as Error).message, "error"),
  });
  const del = useMutation({
    mutationFn: () => api.deleteClient(cid),
    onSuccess: () => {
      qc.invalidateQueries();
      toast("Client deleted", "ok");
      nav("/clients");
    },
    onError: (e) => toast((e as Error).message, "error"),
  });

  if (q.error)
    return (
      <div className="p-6">
        <ErrorNote error={q.error} />
      </div>
    );
  if (!c || !settings)
    return (
      <div className="p-6 space-y-3">
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-64" />
      </div>
    );

  return (
    <div className="pb-10">
      <PageHeader
        title={c.name}
        subtitle={
          <span>
            <span className="code">{c.gstin}</span>
            {c.trade_name && <span> · {c.trade_name}</span>}
          </span>
        }
        actions={
          <>
            <PeriodPicker value={openMonth} onChange={setOpenMonth} />
            <Link to={`/clients/${cid}/${openMonth}/overview`} className={btnCls("primary")}>
              Open {periodLabel(openMonth)}
            </Link>
          </>
        }
      />
      <div className="px-6 grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px] items-start">
        <Panel flush title="Months">
          {c.periods.length === 0 ? (
            <EmptyState title="No months started">Open a month above and upload its files to start.</EmptyState>
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>Month</th>
                  <th>Status</th>
                  <th className="r">Open</th>
                  <th className="r">ITC to claim ₹</th>
                  <th>3B filed</th>
                  <th>Last run</th>
                  <th>Closed</th>
                </tr>
              </thead>
              <tbody>
                {c.periods.map((pr) => (
                  <tr key={pr.id} className="hoverable cursor-pointer" onClick={() => nav(`/clients/${cid}/${pr.period}/overview`)}>
                    <td className="font-medium">
                      <Link to={`/clients/${cid}/${pr.period}/overview`} onClick={(e) => e.stopPropagation()} className="hover:text-accent">
                        {pr.label || periodLabel(pr.period)}
                      </Link>
                    </td>
                    <td>
                      <StatusChip status={pr.status} />
                    </td>
                    <td className="r num">{pr.summary ? count(pr.summary.open) : "–"}</td>
                    <td className="r num">{pr.summary ? inr0(pr.summary.itc_after_decisions).slice(1) : "–"}</td>
                    <td className="text-sm">{pr.filed_3b_on ? fmtDate(pr.filed_3b_on) : <span className="text-faint">–</span>}</td>
                    <td className="text-sm text-muted">{pr.run_at ? fmtDateTime(pr.run_at) : "–"}</td>
                    <td className="text-sm text-muted">{pr.closed_at ? `${fmtDate(pr.closed_at.slice(0, 10))}, ${pr.closed_by}` : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <div className="space-y-4">
          <Panel title="Client details">
            <div className="space-y-3">
              <Field label="Name">
                <Input value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="GSTIN" error={gstinError}>
                  <Input
                    value={gstin}
                    maxLength={15}
                    invalid={!!gstinError}
                    className="code uppercase"
                    onChange={(e) => {
                      setGstin(e.target.value.toUpperCase());
                      setGstinError(null);
                    }}
                  />
                </Field>
                <Field label="Trade name">
                  <Input value={trade} onChange={(e) => setTrade(e.target.value)} />
                </Field>
              </div>
              <Field label="Notes">
                <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} className="w-full" />
              </Field>
              <div className="pt-2 border-t border-rule">
                <SettingsFields value={settings} onChange={setSettings} />
              </div>
              <div className="flex justify-end gap-2 pt-1">
                {dirty && (
                  <Button variant="ghost" onClick={() => c && (setName(c.name), setGstin(c.gstin), setTrade(c.trade_name), setNotes(c.notes), setSettings(c.settings))}>
                    Discard
                  </Button>
                )}
                <Button variant="primary" disabled={!dirty} busy={save.isPending} onClick={() => save.mutate()}>
                  Save client
                </Button>
              </div>
            </div>
          </Panel>

          <Panel title="Vendor master">
            <p className="text-sm text-ink-2">
              GSTIN and name, optionally Activity and ITC eligibility. Fills blank GSTINs, marks suppliers booked in another register as known, and feeds the blocked-credit check.
            </p>
            <div className="mt-3 flex items-center justify-between">
              <span className="text-sm">{c.has_vendor_master ? <span className="text-ok font-medium">Stored for this client</span> : <span className="text-muted">Not uploaded</span>}</span>
              <FilePickButton accept=".xlsx,.xls,.csv" busy={vendor.isPending} onFile={(f) => vendor.mutate(f)} label={c.has_vendor_master ? "Replace" : "Upload vendor master"} />
            </div>
          </Panel>

          {user.role === "admin" && (
            <Panel title="Delete client">
              <p className="text-sm text-ink-2">Removes the client, every month, file and decision. Close packs you downloaded are not affected.</p>
              <Button variant="danger" className="mt-3" onClick={() => setConfirmDelete(true)}>
                Delete {c.name}
              </Button>
            </Panel>
          )}
        </div>
      </div>
      <Dialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Delete this client?"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
            <Button variant="danger" busy={del.isPending} onClick={() => del.mutate()}>
              Delete client
            </Button>
          </>
        }
      >
        <p className="text-base">
          {c.name} and its {count(c.periods.length)} months will be deleted. This can't be undone.
        </p>
      </Dialog>
    </div>
  );
}
