import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type FollowUp, type FollowUpStatus } from "../../api";
import { count, cx, fmtDateTime, inr0, waNumber } from "../../lib/format";
import { Button, btnCls, CopyButton, EmptyState, ErrorNote, Input, Panel, Select, Skeleton, Textarea, useToast } from "../../components/ui";
import { IconChat, IconCopy, IconMail } from "../../components/icons";
import { useWs } from "./shared";
import { NotReconciled } from "./Workspace";

export const FOLLOWUP_LABEL: Record<FollowUpStatus, string> = {
  to_send: "To send",
  sent: "Sent",
  replied: "Replied",
  resolved: "Resolved",
  no_response: "No response",
};
const STATUS_ORDER: FollowUpStatus[] = ["to_send", "sent", "replied", "no_response", "resolved"];
const STATUS_TONE: Record<FollowUpStatus, string> = {
  to_send: "text-accent",
  sent: "text-ink-2",
  replied: "text-review",
  resolved: "text-ok",
  no_response: "text-high",
};

export default function Followups() {
  const { period } = useWs();
  if (!period.summary) return <NotReconciled what="Follow-ups" />;
  return <FollowupsInner />;
}

function FollowupsInner() {
  const { cid, p } = useWs();
  const q = useQuery({ queryKey: ["followups", cid, p], queryFn: () => api.followups(cid, p) });
  const [status, setStatus] = useState<FollowUpStatus | "">("");
  const [search, setSearch] = useState("");
  const list = useMemo(() => {
    const n = search.trim().toLowerCase();
    return (q.data ?? []).filter((f) => (!status || f.status === status) && (!n || f.supplier_name.toLowerCase().includes(n) || f.supplier_gstin.toLowerCase().includes(n)));
  }, [q.data, status, search]);
  const counts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const f of q.data ?? []) m[f.status] = (m[f.status] ?? 0) + 1;
    return m;
  }, [q.data]);
  const openItc = (q.data ?? []).filter((f) => f.status !== "resolved").reduce((s, f) => s + f.itc_at_stake, 0);

  return (
    <div className="p-6 space-y-4 max-w-[1280px]">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-1 flex-wrap" role="tablist" aria-label="Follow-up status">
          <FilterTab on={status === ""} onClick={() => setStatus("")} label="All" n={q.data?.length ?? 0} />
          {STATUS_ORDER.map((s) => (
            <FilterTab key={s} on={status === s} onClick={() => setStatus(s)} label={FOLLOWUP_LABEL[s]} n={counts[s] ?? 0} />
          ))}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted">{inr0(openItc)} ITC waiting on suppliers</span>
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Find supplier" className="h-7 w-52 text-sm" />
        </div>
      </div>

      {q.isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      ) : q.error ? (
        <ErrorNote error={q.error} />
      ) : (q.data ?? []).length === 0 ? (
        <Panel>
          <EmptyState title="No supplier needs a message this month">Follow-ups appear when a supplier has to report or correct something in GSTR-1.</EmptyState>
        </Panel>
      ) : list.length === 0 ? (
        <Panel>
          <EmptyState title="No follow-up with this status" />
        </Panel>
      ) : (
        <div className="space-y-3">
          {list.map((f) => (
            <FollowupCard key={f.id} f={f} />
          ))}
        </div>
      )}
    </div>
  );
}

function FilterTab({ on, onClick, label, n }: { on: boolean; onClick: () => void; label: string; n: number }) {
  return (
    <button role="tab" aria-selected={on} onClick={onClick} className={cx("h-7 px-2.5 rounded-md text-sm", on ? "bg-ink text-white font-medium" : "text-ink-2 hover:bg-surface")}>
      {label} <span className={cx("num ml-0.5", on ? "text-white/70" : "text-muted")}>{count(n)}</span>
    </button>
  );
}

function FollowupCard({ f }: { f: FollowUp }) {
  const { cid, p, base, period } = useWs();
  const qc = useQueryClient();
  const toast = useToast();
  const [email, setEmail] = useState(f.contact_email);
  const [phone, setPhone] = useState(f.contact_phone);
  const [note, setNote] = useState(f.note);
  const [show, setShow] = useState<"whatsapp" | "email" | null>(null);
  useEffect(() => {
    setEmail(f.contact_email);
    setPhone(f.contact_phone);
    setNote(f.note);
  }, [f.contact_email, f.contact_phone, f.note]);
  const locked = period.status === "closed" ? "The month is closed. Reopen it to change follow-ups." : null;

  const save = useMutation({
    mutationFn: (body: Parameters<typeof api.updateFollowup>[3]) => api.updateFollowup(cid, p, f.id, body),
    onMutate: (body) => {
      qc.setQueryData<FollowUp[]>(["followups", cid, p], (old) => old?.map((x) => (x.id === f.id ? { ...x, ...body } : x)));
    },
    onSuccess: (srv) => {
      qc.setQueryData<FollowUp[]>(["followups", cid, p], (old) => old?.map((x) => (x.id === srv.id ? srv : x)));
      qc.invalidateQueries({ queryKey: ["suppliers", cid, p] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e) => {
      toast((e as Error).message, "error");
      qc.invalidateQueries({ queryKey: ["followups", cid, p] });
    },
  });

  const wa = waNumber(phone);
  const waUrl = `https://wa.me/${wa}?text=${encodeURIComponent(f.whatsapp)}`;
  const mailto = `mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent(f.email_subject)}&body=${encodeURIComponent(f.email_body)}`;
  const markSent = () => {
    if (f.status === "to_send") save.mutate({ status: "sent" });
  };

  return (
    <article className={cx("bg-surface border rounded-lg", f.status === "resolved" ? "border-rule opacity-80" : "border-rule")}>
      <header className="flex items-start justify-between gap-4 px-4 pt-3 pb-2.5 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-base font-semibold truncate max-w-[420px]">{f.supplier_name}</h3>
            <span className="code text-xs text-muted">{f.supplier_gstin}</span>
          </div>
          <div className="text-sm text-muted mt-0.5">
            <span className="num">{count(f.items)}</span> item{f.items === 1 ? "" : "s"} · <b className="font-semibold text-ink num">{inr0(f.itc_at_stake)}</b> ITC at stake
            <Link to={`${base}/review?supplier=${encodeURIComponent(f.supplier_gstin)}&view=all`} className="ml-2 text-accent hover:underline">
              See records
            </Link>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Select
            aria-label="Follow-up status"
            value={f.status}
            disabled={!!locked}
            onChange={(e) => save.mutate({ status: e.target.value as FollowUpStatus })}
            className={cx("h-7 text-sm w-auto font-medium", STATUS_TONE[f.status])}
          >
            {STATUS_ORDER.map((s) => (
              <option key={s} value={s}>
                {FOLLOWUP_LABEL[s]}
              </option>
            ))}
          </Select>
        </div>
      </header>

      <div className="px-4 pb-3 grid lg:grid-cols-[1fr_1fr] gap-3">
        <div className="grid grid-cols-2 gap-2">
          <label className="block">
            <span className="block text-xs text-muted mb-0.5">Phone (WhatsApp)</span>
            <Input
              value={phone}
              disabled={!!locked}
              inputMode="tel"
              placeholder="Add mobile number"
              onChange={(e) => setPhone(e.target.value)}
              onBlur={() => phone !== f.contact_phone && save.mutate({ contact_phone: phone })}
              className="h-7 text-sm"
            />
          </label>
          <label className="block">
            <span className="block text-xs text-muted mb-0.5">Email</span>
            <Input
              value={email}
              disabled={!!locked}
              type="email"
              placeholder="Add email address"
              onChange={(e) => setEmail(e.target.value)}
              onBlur={() => email !== f.contact_email && save.mutate({ contact_email: email })}
              className="h-7 text-sm"
            />
          </label>
          <div className="col-span-2 flex items-center gap-1.5 flex-wrap pt-1">
            <CopyButton text={f.whatsapp} label="Copy WhatsApp text" icon={<IconCopy size={13} />} />
            <a
              href={wa.length >= 10 ? waUrl : "#"}
              target="_blank"
              rel="noreferrer"
              className={btnCls("secondary", "sm")}
              title={wa.length < 10 ? "Add a phone number first" : `Opens WhatsApp for +${wa}`}
              onClick={(e) => {
                if (wa.length < 10) {
                  e.preventDefault();
                  toast("Add the supplier's phone number first.", "error");
                } else markSent();
              }}
            >
              <IconChat size={13} /> Open WhatsApp
            </a>
            <a href={mailto} onClick={markSent} className={btnCls("secondary", "sm")} title={email ? `Opens your mail app to ${email}` : "Opens your mail app (no address yet)"}>
              <IconMail size={13} /> Email
            </a>
            <Button size="sm" variant="ghost" onClick={() => setShow(show ? null : "whatsapp")}>
              {show ? "Hide message" : "Show message"}
            </Button>
          </div>
        </div>
        <label className="block">
          <span className="block text-xs text-muted mb-0.5">Note</span>
          <Textarea
            rows={2}
            value={note}
            disabled={!!locked}
            placeholder="e.g. Spoke to accounts, they will amend in next GSTR-1"
            onChange={(e) => setNote(e.target.value)}
            onBlur={() => note !== f.note && save.mutate({ note })}
            className="text-sm"
          />
          <span className="text-2xs text-faint">
            {f.sent_at ? `Sent ${fmtDateTime(f.sent_at)}` : ""}
            {f.updated_by ? `${f.sent_at ? " · " : ""}Updated by ${f.updated_by}, ${fmtDateTime(f.updated_at)}` : ""}
          </span>
        </label>
      </div>

      {show && (
        <div className="border-t border-rule px-4 py-3 bg-sunken rounded-b-lg">
          <div className="flex gap-1 mb-2">
            <Button size="xs" variant={show === "whatsapp" ? "primary" : "ghost"} onClick={() => setShow("whatsapp")}>
              WhatsApp
            </Button>
            <Button size="xs" variant={show === "email" ? "primary" : "ghost"} onClick={() => setShow("email")}>
              Email
            </Button>
          </div>
          {show === "whatsapp" ? (
            <pre className="whitespace-pre-wrap font-sans text-sm text-ink-2 max-w-[80ch]">{f.whatsapp}</pre>
          ) : (
            <div className="text-sm text-ink-2 max-w-[80ch]">
              <div className="font-medium text-ink mb-1">{f.email_subject}</div>
              <pre className="whitespace-pre-wrap font-sans">{f.email_body}</pre>
              <div className="mt-2">
                <CopyButton text={`${f.email_subject}\n\n${f.email_body}`} label="Copy email" size="xs" />
              </div>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
