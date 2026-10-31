import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Period } from "../../api";
import { count, cx, fmtDate, fmtDateTime, plural } from "../../lib/format";
import { periodLabel } from "../../lib/period";
import { Banner, Button, btnCls, CopyButton, Dialog, ErrorNote, Input, Panel, Textarea, useToast } from "../../components/ui";
import { IconCheck, IconCopy, IconDownload, IconX } from "../../components/icons";
import { invalidatePeriod, useWs } from "./shared";

type Pending = null | { kind: "submit" | "approve" | "sendBack" | "close" | "reopen"; force?: boolean };

export default function Close() {
  const { period, cid, p, can, base } = useWs();
  const s = period.summary;
  const qc = useQueryClient();
  const toast = useToast();
  const followups = useQuery({ queryKey: ["followups", cid, p], queryFn: () => api.followups(cid, p), enabled: !!s });
  const [ack, setAckLocal] = useState(!!period.checks_ack);
  useEffect(() => setAckLocal(!!period.checks_ack), [period.checks_ack]);
  const setAck = (v: boolean) => {
    setAckLocal(v);                                   // tick at once; the server records who and when
    return api
      .ackChecks(cid, p, v)
      .then((np) => qc.setQueryData(["period", cid, p], np))
      .then(() => qc.invalidateQueries({ queryKey: ["period", cid, p] }))
      .catch((e: unknown) => {
        setAckLocal(!v);
        toast(e instanceof Error ? e.message : String(e), "error");
      });
  };
  const [dialog, setDialog] = useState<Pending>(null);

  const highs = period.checks.filter((c) => c.level === "High");
  const fuOpen = (followups.data ?? []).filter((f) => f.status === "to_send").length;
  const fuWaiting = (followups.data ?? []).filter((f) => f.status === "sent" || f.status === "no_response").length;

  const done = (np: Period, msg: string) => {
    qc.setQueryData(["period", cid, p], np);
    invalidatePeriod(qc, cid, p);
    qc.invalidateQueries({ queryKey: ["activity"] });
    toast(msg, "ok");
    setDialog(null);
  };

  const run = useMutation({
    mutationFn: async (v: { kind: NonNullable<Pending>["kind"]; note: string; force?: boolean }) => {
      switch (v.kind) {
        case "submit":
          return { np: await api.submit(cid, p, v.note || undefined), msg: "Submitted for review" };
        case "approve":
          return { np: await api.approve(cid, p, v.note || undefined, v.force), msg: "Approved" };
        case "sendBack":
          return { np: await api.sendBack(cid, p, v.note), msg: "Sent back to the preparer" };
        case "close":
          return { np: await api.close(cid, p), msg: "Month closed. The close pack is ready." };
        case "reopen":
          return { np: await api.reopen(cid, p, v.note), msg: "Month reopened" };
      }
    },
    onSuccess: (r) => done(r.np, r.msg),
    onError: (e, v) => {
      if (e instanceof ApiError && e.status === 409 && v.kind === "approve" && !v.force) {
        setDialog({ kind: "approve", force: true });
        return;
      }
      toast((e as Error).message, "error");
    },
  });

  const [filedOn, setFiledOn] = useState(period.filed_3b_on ?? "");
  useEffect(() => setFiledOn(period.filed_3b_on ?? ""), [period.filed_3b_on]);
  const filed = useMutation({
    mutationFn: (d: string | null) => api.filed(cid, p, d),
    onSuccess: (np) => done(np, np.filed_3b_on ? `3B marked filed on ${fmtDate(np.filed_3b_on)}` : "3B filing date cleared"),
    onError: (e) => toast((e as Error).message, "error"),
  });

  const st = period.status;

  return (
    <div className="p-6 grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px] items-start max-w-[1320px]">
      <div className="space-y-4 min-w-0">
        {period.review_note && (st === "reconciled" || st === "in_review" || st === "approved") && (
          <Banner tone={st === "reconciled" ? "review" : "neutral"}>
            <b className="font-semibold">Reviewer's note:</b> {period.review_note}
          </Banner>
        )}

        {st === "closed" && period.pack_fingerprint && (
          <section className="rounded-lg border border-ok/30 bg-ok-soft p-4">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div>
                <h2 className="text-base font-semibold text-ok">Closed {fmtDateTime(period.closed_at)} by {period.closed_by}</h2>
                <p className="text-sm text-ink-2 mt-0.5">Keep the fingerprint outside the pack (client file or covering email). It shows later whether any file in the pack was changed.</p>
              </div>
              <a className={btnCls("primary", "md")} href={api.exportUrl(cid, p, "close-pack")}>
                <IconDownload /> Download close pack
              </a>
            </div>
            <div className="mt-3 flex items-center gap-2 bg-surface border border-rule rounded-md px-3 py-2">
              <span className="text-xs text-muted shrink-0">Pack fingerprint (SHA-256)</span>
              <code className="code text-sm text-ink break-all flex-1">{period.pack_fingerprint}</code>
              <CopyButton text={period.pack_fingerprint} label="Copy" size="xs" icon={<IconCopy size={12} />} />
            </div>
          </section>
        )}
        <Panel title="Before you submit">
          {!s ? (
            <p className="text-sm text-muted">Reconcile the month first.</p>
          ) : (
            <ul className="space-y-3">
              <CheckItem ok={s.open === 0} title={s.open === 0 ? "Every decision is made" : `${plural(s.open, "open item")} left`}>
                {s.open === 0 ? (
                  `${count(s.decided)} decided by staff, ${count(s.auto_cleared)} cleared automatically.`
                ) : (
                  <Link className="text-accent hover:underline" to={`${base}/review`}>
                    Review the open items
                  </Link>
                )}
              </CheckItem>
              <CheckItem ok={highs.length === 0 || ack} title={highs.length === 0 ? "No high pre-filing checks" : `${plural(highs.length, "high check")} to acknowledge`}>
                {highs.length > 0 && (
                  <>
                    <ul className="text-sm text-ink-2 list-disc pl-4 mb-1.5">
                      {highs.map((h) => (
                        <li key={h.name}>{h.name}</li>
                      ))}
                    </ul>
                    <label className="inline-flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="accent-[var(--color-accent)]" />
                      I have read these and dealt with them
                    </label>
                    {period.checks_ack && (
                      <div className="text-xs text-muted mt-1">Acknowledged by {period.checks_ack.by}</div>
                    )}
                  </>
                )}
              </CheckItem>
              <CheckItem
                ok={fuOpen === 0}
                warn={fuOpen === 0 && fuWaiting > 0}
                title={fuOpen > 0 ? `${plural(fuOpen, "supplier message")} not sent` : fuWaiting > 0 ? `${plural(fuWaiting, "supplier")} yet to reply` : "Supplier follow-ups done"}
              >
                <Link className="text-accent hover:underline" to={`${base}/followups`}>
                  Open follow-ups
                </Link>
              </CheckItem>
              {s.blocked_review > 0 && (
                <CheckItem ok={null} title={`${plural(s.blocked_review, "possible blocked-credit item")} to look at`}>
                  <Link className="text-accent hover:underline" to={`${base}/blocked`}>
                    Blocked credit
                  </Link>
                </CheckItem>
              )}
            </ul>
          )}
        </Panel>

        <Panel title="Review and close">
          <Timeline period={period} />
          <div className="mt-4 pt-4 border-t border-rule flex items-center gap-2 flex-wrap">
            {(st === "reconciled" || st === "files_uploaded" || st === "not_started") && (
              <Button variant="primary" disabledReason={can.submit} onClick={() => setDialog({ kind: "submit" })}>
                Submit for review
              </Button>
            )}
            {st === "in_review" && (
              <>
                <Button variant="primary" disabledReason={can.approve} onClick={() => setDialog({ kind: "approve" })}>
                  Approve
                </Button>
                <Button disabledReason={can.sendBack} onClick={() => setDialog({ kind: "sendBack" })}>
                  Send back
                </Button>
              </>
            )}
            {st === "approved" && (
              <>
                <Button variant="primary" disabledReason={can.close} onClick={() => setDialog({ kind: "close" })}>
                  Close month
                </Button>
                <Button disabledReason={can.sendBack} onClick={() => setDialog({ kind: "sendBack" })}>
                  Send back
                </Button>
              </>
            )}
            {(st === "approved" || st === "closed") && (
              <Button variant="ghost" disabledReason={can.reopen} onClick={() => setDialog({ kind: "reopen" })}>
                Reopen
              </Button>
            )}
            {!can.isReviewer && (st === "in_review" || st === "approved") && <span className="text-sm text-muted">A reviewer approves and closes the month.</span>}
            {!can.isReviewer && st === "reconciled" && <span className="text-sm text-muted">After you submit, a reviewer approves and closes the month.</span>}
          </div>
        </Panel>

      </div>

      <div className="space-y-4">
        <Panel title="GSTR-3B filed">
          <div className="flex items-end gap-2">
            <label className="block flex-1">
              <span className="block text-xs text-muted mb-1">Filed on</span>
              <Input type="date" value={filedOn} onChange={(e) => setFiledOn(e.target.value)} />
            </label>
            <Button variant="primary" busy={filed.isPending} disabled={!filedOn || filedOn === period.filed_3b_on} onClick={() => filed.mutate(filedOn)}>
              Save
            </Button>
            {period.filed_3b_on && (
              <Button variant="ghost" onClick={() => filed.mutate(null)}>
                Clear
              </Button>
            )}
          </div>
          <p className="text-xs text-muted mt-2">
            {period.filed_3b_on ? `Recorded as filed on ${fmtDate(period.filed_3b_on)}.` : `Due ${fmtDate(period.gstr3b_deadline)}. Record the date once 3B is filed on the portal.`}
          </p>
        </Panel>

        <Panel title="Downloads" flush>
          <ul className="divide-y divide-rule">
            <Download href={api.exportUrl(cid, p, "workbook")} title="TaxMind workbook (.xlsx)" detail="All sheets, with your final decisions and notes" disabled={!s} />
            <Download href={api.exportUrl(cid, p, "ims.csv")} title="IMS actions (.csv)" detail="Accept / Reject / Pending to take on the portal" disabled={!s} />
            <Download href={api.exportUrl(cid, p, "prefiling.html")} title="Pre-filing report" detail="One page, opens in a new tab" disabled={!s} newTab />
            <Download href={api.exportUrl(cid, p, "ledger.csv")} title="Reversal ledger (.csv)" detail="4(B)(2) reversals to carry to next month" disabled={!s} />
            <Download href={api.exportUrl(cid, p, "close-pack")} title="Close pack (.zip)" detail={st === "closed" ? "Record, decisions, workbook, inputs and manifest" : "Available once the month is closed"} disabled={st !== "closed"} />
          </ul>
        </Panel>
      </div>

      <ActionDialog pending={dialog} busy={run.isPending} error={run.error} period={period} onClose={() => setDialog(null)} onConfirm={(note) => dialog && run.mutate({ kind: dialog.kind, note, force: dialog.force })} />
    </div>
  );
}

function CheckItem({ ok, warn, title, children }: { ok: boolean | null; warn?: boolean; title: string; children?: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span
        className={cx(
          "mt-0.5 w-5 h-5 rounded-full flex items-center justify-center shrink-0",
          ok === null ? "bg-sunken border border-rule-strong text-muted" : ok ? (warn ? "bg-review-soft text-review" : "bg-ok-soft text-ok") : "bg-high-soft text-high",
        )}
        aria-label={ok ? "Done" : ok === null ? "To look at" : "Not done"}
      >
        {ok === null ? <span className="text-2xs font-bold">i</span> : ok ? <IconCheck size={12} /> : <IconX size={12} />}
      </span>
      <div className="min-w-0">
        <div className="text-base font-medium">{title}</div>
        {children && <div className="text-sm text-muted mt-0.5">{children}</div>}
      </div>
    </li>
  );
}

function Timeline({ period }: { period: Period }) {
  const items: [string, string | null, string | null][] = [
    ["Reconciled", period.run_by, period.run_at],
    ["Submitted for review", period.submitted_by, period.submitted_at],
    ["Approved", period.approved_by, period.approved_at],
    ["Closed", period.closed_by, period.closed_at],
  ];
  return (
    <ol className="grid sm:grid-cols-4 gap-3">
      {items.map(([label, by, at]) => (
        <li key={label} className={cx("rounded-md border px-3 py-2", by ? "border-accent-line bg-accent-soft/50" : "border-rule border-dashed")}>
          <div className={cx("text-sm font-medium", by ? "text-ink" : "text-faint")}>{label}</div>
          <div className="text-xs text-muted mt-0.5">{by ? `${by}, ${fmtDateTime(at)}` : "Not yet"}</div>
        </li>
      ))}
    </ol>
  );
}

function Download({ href, title, detail, disabled, newTab }: { href: string; title: string; detail: string; disabled?: boolean; newTab?: boolean }) {
  const inner = (
    <>
      <IconDownload className={disabled ? "text-faint" : "text-accent"} />
      <div className="min-w-0">
        <div className={cx("text-sm font-medium", disabled ? "text-faint" : "text-ink")}>{title}</div>
        <div className="text-xs text-muted">{detail}</div>
      </div>
    </>
  );
  return (
    <li>
      {disabled ? (
        <div className="flex items-center gap-3 px-4 py-2.5 cursor-not-allowed">{inner}</div>
      ) : (
        <a href={href} target={newTab ? "_blank" : undefined} rel="noreferrer" className="flex items-center gap-3 px-4 py-2.5 hover:bg-sunken">
          {inner}
        </a>
      )}
    </li>
  );
}

function ActionDialog({
  pending,
  busy,
  error,
  period,
  onClose,
  onConfirm,
}: {
  pending: Pending;
  busy: boolean;
  error: unknown;
  period: Period;
  onClose: () => void;
  onConfirm: (note: string) => void;
}) {
  const [note, setNote] = useState("");
  useEffect(() => setNote(""), [pending?.kind]);
  if (!pending) return null;
  const open = period.summary?.open ?? 0;
  const cfg = {
    submit: { title: "Submit for review", confirm: "Submit for review", noteLabel: "Note for the reviewer (optional)", required: false, body: open > 0 ? `${plural(open, "item")} still open. The reviewer will see them.` : `Everything in ${periodLabel(period.period)} is decided.` },
    approve: pending.force
      ? { title: "Approve with open items?", confirm: "Approve anyway", noteLabel: "Why (optional)", required: false, body: `${plural(open, "item")} are still open. Approving now uses TaxMind's recommendation for them.` }
      : { title: "Approve this month", confirm: "Approve", noteLabel: "Note (optional)", required: false, body: "After approval decisions are locked until the month is reopened." },
    sendBack: { title: "Send back to the preparer", confirm: "Send back", noteLabel: "What needs fixing", required: true, body: "The month goes back to Reconciled so decisions can be changed." },
    close: { title: "Close the month", confirm: "Close month", noteLabel: null, required: false, body: "This builds the close pack (record, decisions, workbook, input files and a SHA-256 manifest) and stores the reversal ledger for next month." },
    reopen: { title: "Reopen the month", confirm: "Reopen", noteLabel: "Why it's being reopened", required: true, body: "The month goes back to Reconciled. If it was closed, a new pack is built when it is closed again." },
  }[pending.kind];
  return (
    <Dialog
      open
      onClose={onClose}
      title={cfg.title}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant={pending.kind === "sendBack" || pending.kind === "reopen" ? "secondary" : "primary"} busy={busy} disabled={cfg.required && !note.trim()} onClick={() => onConfirm(note.trim())}>
            {cfg.confirm}
          </Button>
        </>
      }
    >
      <p className="text-base text-ink-2">{cfg.body}</p>
      {cfg.noteLabel && (
        <label className="block mt-3">
          <span className="block text-sm font-medium text-ink-2 mb-1">{cfg.noteLabel}</span>
          <Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} className="w-full" />
        </label>
      )}
      {error && !(error instanceof ApiError && error.status === 409) ? <ErrorNote className="mt-3" error={error} /> : null}
    </Dialog>
  );
}
