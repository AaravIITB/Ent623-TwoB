import { useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Check, type ClientSettings, type FileInfo, type Period, type Summary } from "../../api";
import { count, cx, fmtBytes, fmtDateTime, inr0, inrCompact, plural } from "../../lib/format";
import { periodLabel, recentPeriods } from "../../lib/period";
import { Button, btnCls, ErrorNote, LevelBadge, Panel, ProgressBar, Select, Spinner, useToast } from "../../components/ui";
import { IconFile, IconTrash, IconUpload } from "../../components/icons";
import { lobLabel, POLICY_TEXT, SettingsFields } from "../../components/ClientForm";
import { invalidatePeriod, useWs } from "./shared";

export default function Overview() {
  const { period } = useWs();
  const s = period.summary;
  return (
    <div className="p-6 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px] items-start">
      <div className="space-y-4 min-w-0">
        {s ? (
          <>
            <SummaryPanel s={s} />
            <ChecksPanel checks={period.checks} />
            <FilesPanel />
            <NotesPanel notes={period.notes} />
          </>
        ) : (
          <>
            <FilesPanel />
            <NotesPanel notes={period.notes} />
          </>
        )}
      </div>
      <div className="space-y-4">
        <SettingsPanel />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------

function SummaryPanel({ s }: { s: Summary }) {
  const { base } = useWs();
  const needs = s.needs_human;
  const total = s.findings || s.auto_cleared + s.needs_human;
  return (
    <Panel
      title="Where this month stands"
      actions={
        s.open > 0 ? (
          <Link to={`${base}/review`} className={btnCls("primary", "sm")}>
            Review {count(s.open)} open
          </Link>
        ) : null
      }
    >
      <div className="grid md:grid-cols-[1fr_1.4fr] gap-6">
        <div>
          <div className="flex items-baseline gap-6">
            <div>
              <div className="text-3xl font-semibold num tracking-[-0.02em]">{count(s.auto_cleared)}</div>
              <div className="text-sm text-muted">cleared automatically</div>
            </div>
            <div>
              <div className="text-3xl font-semibold num tracking-[-0.02em] text-accent">{count(needs)}</div>
              <div className="text-sm text-muted">need a person</div>
            </div>
          </div>
          <div className="mt-4">
            <div className="flex justify-between text-sm mb-1.5">
              <span>
                <b className="font-semibold num">{count(s.decided)}</b> decided
              </span>
              <span className={s.open === 0 ? "text-ok font-medium" : "text-ink-2"}>{s.open === 0 ? "All decided" : `${count(s.open)} open`}</span>
            </div>
            <ProgressBar value={Math.min(s.decided, needs)} max={needs} tone={s.open === 0 ? "ok" : "accent"} />
          </div>
          <ul className="mt-4 space-y-1 text-sm text-ink-2">
            <li>
              {plural(total, "record")} from {count(s.books_entries)} books entries and {count(s.portal_records)} 2B records.
            </li>
            {s.supplier_groups > 0 && (
              <li>
                Open items come down to <b className="font-semibold">{plural(s.supplier_groups, "supplier-level decision")}</b>.
              </li>
            )}
            {s.blocked_review > 0 && (
              <li>
                <Link to={`${base}/blocked`} className="text-accent hover:underline">
                  {plural(s.blocked_review, "possible blocked-credit item")}
                </Link>{" "}
                ({inr0(s.blocked_review_itc)} ITC) to check.
              </li>
            )}
            {s.deemed_acceptance_records > 0 && (
              <li className="text-high">
                {plural(s.deemed_acceptance_records, "record")} ({inr0(s.deemed_acceptance_itc)}) will be deemed accepted unless acted on in IMS.
              </li>
            )}
          </ul>
        </div>
        <ItcLadder s={s} />
      </div>
    </Panel>
  );
}

function ItcLadder({ s }: { s: Summary }) {
  const rows: { label: string; value: number; note?: string; strong?: boolean }[] = [
    { label: "ITC in books", value: s.itc_books },
    { label: "ITC in 2B", value: s.itc_2b },
    { label: "To claim (TaxMind)", value: s.itc_to_claim },
    { label: "After your decisions", value: s.itc_after_decisions, strong: true, note: "before 17(5) reversal" },
  ];
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 1);
  return (
    <div>
      <div className="text-sm font-medium text-ink-2 mb-2">ITC this month</div>
      <div className="space-y-2.5">
        {rows.map((r) => (
          <div key={r.label} className="grid grid-cols-[150px_1fr_auto] items-center gap-3">
            <span className={cx("text-sm leading-tight", r.strong ? "font-semibold text-ink" : "text-ink-2")}>
              {r.label}
              {r.note && <span className="block text-2xs font-normal text-muted">{r.note}</span>}
            </span>
            <div className="h-2 bg-sunken rounded-sm overflow-hidden">
              <div className={cx("h-full rounded-sm", r.strong ? "bg-accent" : "bg-rule-strong")} style={{ width: `${(Math.abs(r.value) / max) * 100}%` }} />
            </div>
            <span className={cx("num text-right w-[120px]", r.strong ? "font-semibold text-base" : "text-sm")} title={inr0(r.value)}>
              {inr0(r.value)}
            </span>
          </div>
        ))}
      </div>
      <p className="text-xs text-muted mt-3">
        {s.itc_needing_attention > 0 && <>{inrCompact(s.itc_needing_attention)} of ITC sits on records that need a person. </>}
        "After your decisions" is the ITC to claim with your final decisions (else TaxMind's recommendation), before any Sec 17(5) reversal: Table 4 shows it as 4(C) + 4(B)(1).
      </p>
    </div>
  );
}

function ChecksPanel({ checks }: { checks: Check[] }) {
  const order = { High: 0, Review: 1, OK: 2 } as const;
  const sorted = [...checks].sort((a, b) => order[a.level] - order[b.level]);
  const highs = checks.filter((c) => c.level === "High").length;
  return (
    <Panel
      flush
      title={
        <span>
          Pre-filing checks{" "}
          {highs > 0 && <span className="text-high font-normal text-sm ml-1">{count(highs)} high</span>}
        </span>
      }
    >
      {sorted.length === 0 ? (
        <p className="p-4 text-sm text-muted">No checks were produced for this month.</p>
      ) : (
        <ul className="divide-y divide-rule">
          {sorted.map((c, i) => (
            <li key={i} className={cx("px-4 py-2.5 grid grid-cols-[64px_1fr_auto] gap-3 items-start", c.level === "High" && "bg-high-soft/40")}>
              <LevelBadge level={c.level} />
              <div className="min-w-0">
                <div className="text-base font-medium text-ink">{c.name}</div>
                <div className="text-sm text-ink-2 mt-0.5">{c.detail}</div>
              </div>
              <div className="text-right text-sm num text-muted">
                {c.amount ? <div className="text-ink">{inr0(c.amount)}</div> : null}
                {c.count ? <div>{plural(c.count, "record")}</div> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function NotesPanel({ notes }: { notes: string[] }) {
  if (!notes.length) return null;
  return (
    <details className="bg-surface border border-rule rounded-lg group">
      <summary className="px-4 h-11 flex items-center justify-between cursor-pointer list-none">
        <span className="text-base font-semibold">
          Loading notes <span className="text-muted font-normal text-sm ml-1">{count(notes.length)}</span>
        </span>
        <span className="text-sm text-accent group-open:hidden">Show</span>
        <span className="text-sm text-accent hidden group-open:inline">Hide</span>
      </summary>
      <ul className="border-t border-rule px-4 py-3 space-y-1 text-sm text-ink-2 max-h-80 overflow-auto">
        {notes.map((n, i) => (
          <li key={i} className="pl-3 relative before:content-[''] before:absolute before:left-0 before:top-[0.6em] before:w-1 before:h-1 before:rounded-full before:bg-faint">
            {n}
          </li>
        ))}
      </ul>
    </details>
  );
}

// ---------------------------------------------------------------------------------------------------------
// Files and reconcile

function FilesPanel() {
  const { period, cid, p, can, client, base } = useWs();
  const qc = useQueryClient();
  const toast = useToast();
  const books = period.files.filter((f) => f.role === "books");
  const portal = period.files.filter((f) => f.role === "portal");
  const [hint, setHint] = useState("");

  const setPeriod = (np: Period) => {
    qc.setQueryData(["period", cid, p], np);
    invalidatePeriod(qc, cid, p, { decisions: false });
  };
  const upload = useMutation({
    mutationFn: (v: { role: "books" | "portal"; files: File[]; hint?: string }) => api.uploadFiles(cid, p, v.role, v.files, v.hint),
    onSuccess: (np, v) => {
      setPeriod(np);
      toast(`Uploaded ${plural(v.files.length, "file")}`, "ok");
    },
    onError: (e) => toast((e as Error).message, "error"),
  });
  const del = useMutation({
    mutationFn: (fid: number) => api.deleteFile(cid, p, fid),
    onSuccess: (np) => setPeriod(np),
    onError: (e) => toast((e as Error).message, "error"),
  });
  const recon = useMutation({
    mutationFn: () => api.reconcile(cid, p),
    onSuccess: (np) => {
      qc.setQueryData(["period", cid, p], np);
      invalidatePeriod(qc, cid, p);
      toast(`Reconciled: ${count(np.summary?.needs_human ?? 0)} need a person, ${count(np.summary?.auto_cleared ?? 0)} cleared automatically`, "ok");
    },
  });
  const vendor = useMutation({
    mutationFn: (f: File) => api.uploadVendorMaster(cid, f),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client", cid] });
      toast("Vendor master saved. Reconcile again to use it.", "ok");
    },
    onError: (e) => toast((e as Error).message, "error"),
  });

  const missing = !books.length ? "Upload the purchase register first." : !portal.length ? "Upload at least this month's GSTR-2B." : null;
  const reconcileBlocked = can.reconcile ?? missing;
  const wasRun = !!period.run_at;

  return (
    <Panel title="Files for this month">
      <div className="grid md:grid-cols-2 gap-4">
        <UploadZone
          title="Purchase register"
          formats="Excel, CSV or Tally XML (Day Book)"
          accept=".xlsx,.xls,.xlsm,.csv,.xml"
          files={books}
          disabled={can.upload}
          busy={upload.isPending && upload.variables?.role === "books"}
          onFiles={(files) => upload.mutate({ role: "books", files })}
          onDelete={(f) => del.mutate(f.id)}
        />
        <UploadZone
          title="GSTR-2B / IMS"
          formats="JSON or Excel. Add earlier months for reclaims and next month for late filers."
          accept=".json,.xlsx,.xls,.csv,.zip"
          multiple
          files={portal}
          disabled={can.upload}
          busy={upload.isPending && upload.variables?.role === "portal"}
          onFiles={(files) => upload.mutate({ role: "portal", files, hint: hint || undefined })}
          onDelete={(f) => del.mutate(f.id)}
          showMonth
          extra={
            <label className="flex items-center gap-2 text-xs text-muted whitespace-nowrap">
              Month of the next upload
              <Select value={hint} onChange={(e) => setHint(e.target.value)} className="h-6.5 text-xs w-auto">
                <option value="">Read from the file</option>
                {recentPeriods(15).map((x) => (
                  <option key={x} value={x}>
                    {periodLabel(x)}
                  </option>
                ))}
              </Select>
            </label>
          }
        />
      </div>

      <div className="mt-4 flex items-center justify-between gap-3 flex-wrap rounded-md bg-sunken border border-rule px-3 py-2.5">
        <div className="text-sm">
          <span className="font-medium">Vendor master</span>{" "}
          {client.has_vendor_master ? <span className="text-ok">stored for this client</span> : <span className="text-muted">not uploaded (optional)</span>}
          <span className="text-muted"> · fills blank GSTINs and marks known suppliers.</span>
        </div>
        <FilePickButton accept=".xlsx,.xls,.csv" busy={vendor.isPending} onFile={(f) => vendor.mutate(f)} label={client.has_vendor_master ? "Replace vendor master" : "Upload vendor master"} />
      </div>

      <div className="mt-4 flex items-center gap-4 flex-wrap border-t border-rule pt-4">
        <Button variant="primary" busy={recon.isPending} disabledReason={recon.isPending ? null : reconcileBlocked} onClick={() => recon.mutate()}>
          {recon.isPending ? "Reconciling…" : wasRun ? "Reconcile again" : "Reconcile"}
        </Button>
        <div className="text-sm text-muted flex-1 min-w-[240px]">
          {recon.isPending ? (
            <span className="inline-flex items-center gap-2 text-ink-2">
              <Spinner /> Matching books against 2B. Large months take up to a minute.
            </span>
          ) : reconcileBlocked ? (
            reconcileBlocked
          ) : wasRun ? (
            <>
              Last run {fmtDateTime(period.run_at)} by {period.run_by}. Decisions, notes and assignees carry over for unchanged records.
              {period.status === "in_review" && " Reconciling sends the month back to Reconciled."}
            </>
          ) : (
            "Runs the match with this client's settings, vendor master and last closed month's reversal ledger."
          )}
        </div>
        {period.status !== "not_started" && period.summary && (
          <Link to={`${base}/review`} className="text-sm text-accent hover:underline">
            Go to Review
          </Link>
        )}
      </div>
      {recon.error && <ErrorNote className="mt-3" error={recon.error} />}
      {period.prior_ledger_items > 0 && (
        <p className="mt-2 text-xs text-muted">{plural(period.prior_ledger_items, "open reversal-ledger item")} brought from the last closed month.</p>
      )}
    </Panel>
  );
}

function UploadZone({
  title,
  formats,
  accept,
  multiple,
  files,
  disabled,
  busy,
  onFiles,
  onDelete,
  showMonth,
  extra,
}: {
  title: string;
  formats: string;
  accept: string;
  multiple?: boolean;
  files: FileInfo[];
  disabled: string | null;
  busy: boolean;
  onFiles: (f: File[]) => void;
  onDelete: (f: FileInfo) => void;
  showMonth?: boolean;
  extra?: ReactNode;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1.5">
        <h3 className="text-base font-medium">{title}</h3>
        <span className="text-xs text-muted">{files.length ? plural(files.length, "file") : "none yet"}</span>
      </div>
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={!!disabled}
        title={disabled ?? undefined}
        onClick={() => !disabled && input.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !disabled) {
            e.preventDefault();
            input.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          if (disabled) return;
          const fs = Array.from(e.dataTransfer.files);
          if (fs.length) onFiles(multiple ? fs : fs.slice(0, 1));
        }}
        className={cx(
          "rounded-md border border-dashed px-4 py-4 text-center",
          disabled ? "border-rule bg-sunken text-faint cursor-not-allowed" : over ? "border-accent bg-accent-soft" : "border-rule-strong hover:border-accent hover:bg-accent-soft/40",
        )}
      >
        {busy ? (
          <span className="inline-flex items-center gap-2 text-sm text-ink-2">
            <Spinner /> Uploading…
          </span>
        ) : (
          <>
            <div className="inline-flex items-center gap-1.5 text-sm font-medium text-accent">
              <IconUpload size={14} /> {files.length && !multiple ? "Replace file" : "Drop files or browse"}
            </div>
            <div className="text-xs text-muted mt-0.5">{formats}</div>
          </>
        )}
        <input
          ref={input}
          type="file"
          hidden
          accept={accept}
          multiple={multiple}
          onChange={(e) => {
            const fs = Array.from(e.target.files ?? []);
            if (fs.length) onFiles(fs);
            e.target.value = "";
          }}
        />
      </div>
      {extra && <div className="mt-2">{extra}</div>}
      {files.length > 0 && (
        <ul className="mt-2 divide-y divide-rule border border-rule rounded-md">
          {files.map((f) => (
            <li key={f.id} className="flex items-center gap-2 px-2.5 py-1.5 text-sm">
              <IconFile size={14} className="text-faint shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="truncate" title={f.filename}>
                  {f.filename}
                </div>
                <div className="text-2xs text-muted">
                  {fmtBytes(f.size)} · {f.uploaded_by}
                </div>
              </div>
              {showMonth && (
                <span className={cx("text-xs whitespace-nowrap", f.period_hint ? "text-ink-2" : "text-review")} title={f.period_hint ? "Month read from the file" : "Month not found in the file; the run month is used"}>
                  {f.period_hint ? periodLabel(f.period_hint) : "Month not found"}
                </span>
              )}
              <button
                type="button"
                className="p-1 text-faint hover:text-high disabled:opacity-40"
                disabled={!!disabled}
                title={disabled ?? `Remove ${f.filename}`}
                aria-label={`Remove ${f.filename}`}
                onClick={() => onDelete(f)}
              >
                <IconTrash size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function FilePickButton({ accept, busy, onFile, label }: { accept: string; busy?: boolean; onFile: (f: File) => void; label: string }) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <>
      <Button size="sm" busy={busy} onClick={() => ref.current?.click()}>
        <IconUpload size={13} /> {label}
      </Button>
      <input
        ref={ref}
        type="file"
        hidden
        accept={accept}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
    </>
  );
}

// ---------------------------------------------------------------------------------------------------------

function SettingsPanel() {
  const { client, cid, period } = useWs();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<ClientSettings>(client.settings);
  const qc = useQueryClient();
  const toast = useToast();
  const save = useMutation({
    mutationFn: () => api.updateClient(cid, { settings: draft }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client", cid] });
      setEditing(false);
      toast(period.summary ? "Settings saved. Reconcile again to apply them." : "Settings saved", "ok");
    },
    onError: (e) => toast((e as Error).message, "error"),
  });
  const st = client.settings;
  return (
    <Panel
      title="Client settings"
      actions={
        !editing && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setDraft(client.settings);
              setEditing(true);
            }}
          >
            Edit
          </Button>
        )
      }
    >
      {editing ? (
        <div>
          <SettingsFields value={draft} onChange={setDraft} />
          <div className="flex justify-end gap-2 mt-4">
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button size="sm" variant="primary" busy={save.isPending} onClick={() => save.mutate()}>
              Save settings
            </Button>
          </div>
        </div>
      ) : (
        <dl className="text-sm space-y-3">
          <div>
            <dt className="text-muted text-xs">Line of business</dt>
            <dd className="mt-0.5">{st.line_of_business.length ? st.line_of_business.map(lobLabel).join(", ") : "Not set: every Sec 17(5) block applies"}</dd>
          </div>
          <div>
            <dt className="text-muted text-xs">2B bills not in the books</dt>
            <dd className="mt-0.5">
              <span className="font-medium">{st.policy === "pending" ? "Keep pending" : "Claim and reverse"}</span>
              <span className="block text-xs text-muted mt-0.5">{POLICY_TEXT[st.policy]}</span>
            </dd>
          </div>
          <div>
            <dt className="text-muted text-xs">Tolerance</dt>
            <dd className="mt-0.5 num">
              ₹{st.tolerance} or {st.tolerance_pct}%, whichever is larger
            </dd>
          </div>
          <div className="pt-2 border-t border-rule">
            <Link to={`/clients/${client.id}`} className="text-accent hover:underline">
              All months and client details
            </Link>
          </div>
        </dl>
      )}
    </Panel>
  );
}
