import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useUrlState } from "../lib/hooks";
import { count, fmtDate } from "../lib/format";
import { previousPeriod } from "../lib/period";
import { PageHeader } from "../components/Layout";
import { lobLabel } from "../components/ClientForm";
import { NewClientDialog } from "../components/NewClientDialog";
import { Button, EmptyState, ErrorNote, Input, Panel, TableSkeleton, Tag } from "../components/ui";
import { IconPlus, IconSearch } from "../components/icons";

export default function Clients() {
  const q = useQuery({ queryKey: ["clients"], queryFn: api.clients });
  const [{ q: search }, setUrl] = useUrlState(["q"] as const);
  const [open, setOpen] = useState(false);
  const nav = useNavigate();
  const rows = useMemo(() => {
    const n = search.trim().toLowerCase();
    return (q.data ?? []).filter((c) => !n || c.name.toLowerCase().includes(n) || c.gstin.toLowerCase().includes(n) || c.trade_name.toLowerCase().includes(n));
  }, [q.data, search]);
  const prev = previousPeriod();

  return (
    <div className="pb-10">
      <PageHeader
        title="Clients"
        subtitle={q.data ? `${count(q.data.length)} clients` : undefined}
        actions={
          <Button variant="primary" onClick={() => setOpen(true)}>
            <IconPlus /> New client
          </Button>
        }
      />
      <div className="px-6">
        <ErrorNote error={q.error} />
        <Panel
          flush
          actions={
            <div className="relative">
              <IconSearch className="absolute left-2 top-1/2 -translate-y-1/2 text-faint" size={14} />
              <Input value={search} onChange={(e) => setUrl({ q: e.target.value })} placeholder="Find client or GSTIN" className="h-7 pl-7 w-64 text-sm" />
            </div>
          }
          title="All clients"
        >
          {q.isLoading ? (
            <TableSkeleton rows={6} cols={5} />
          ) : rows.length === 0 ? (
            <EmptyState title={search ? "No client matches that search" : "No clients yet"} action={!search && <Button variant="primary" onClick={() => setOpen(true)}>Add a client</Button>} />
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>Client</th>
                  <th>GSTIN</th>
                  <th>Line of business</th>
                  <th>Not-in-books policy</th>
                  <th>Vendor master</th>
                  <th>Added</th>
                  <th className="r" />
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id} className="hoverable cursor-pointer" onClick={() => nav(`/clients/${c.id}`)}>
                    <td>
                      <Link to={`/clients/${c.id}`} className="font-medium hover:text-accent" onClick={(e) => e.stopPropagation()}>
                        {c.name}
                      </Link>
                      {c.trade_name && <div className="text-xs text-muted">{c.trade_name}</div>}
                    </td>
                    <td className="code text-xs">{c.gstin}</td>
                    <td className="text-sm">
                      <div className="flex gap-1 flex-wrap">{c.settings.line_of_business.length ? c.settings.line_of_business.map((t) => <Tag key={t}>{lobLabel(t)}</Tag>) : <span className="text-faint">–</span>}</div>
                    </td>
                    <td className="text-sm">{c.settings.policy === "pending" ? "Keep pending" : "Claim and reverse"}</td>
                    <td className="text-sm">{c.has_vendor_master ? <span className="text-ok">Stored</span> : <span className="text-faint">None</span>}</td>
                    <td className="text-sm text-muted">{fmtDate(c.created_at.slice(0, 10))}</td>
                    <td className="r" onClick={(e) => e.stopPropagation()}>
                      <Link to={`/clients/${c.id}/${prev}/overview`} className="text-sm text-accent hover:underline">
                        Open last month
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
      <NewClientDialog open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
