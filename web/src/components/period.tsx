import { useMemo } from "react";
import type { Period, PeriodStatus, Role } from "../api";
import { cx, count, fmtDate, fmtDateShort } from "../lib/format";
import { daysText, daysUntil, filingWindow, isPeriod, parsePeriod, periodLabel, recentPeriods, shiftPeriod } from "../lib/period";
import { IconChevronLeft, IconChevronRight } from "./icons";
import { PERIOD_STATUS_LABEL } from "./ui";

/** Month picker: prev / select / next. */
export function PeriodPicker({ value, onChange }: { value: string; onChange: (p: string) => void }) {
  const options = useMemo(() => {
    const list = recentPeriods(18);
    if (isPeriod(value) && !list.includes(value)) list.push(value);
    return list.sort((a, b) => key(b) - key(a));
  }, [value]);
  return (
    <div className="inline-flex items-center rounded-md border border-rule-strong bg-surface h-8">
      <button type="button" className="px-2 h-full text-muted hover:text-ink border-r border-rule" onClick={() => onChange(shiftPeriod(value, -1))} aria-label="Previous month" title="Previous month">
        <IconChevronLeft />
      </button>
      <select
        aria-label="Return month"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-full bg-transparent pl-2.5 pr-1 text-base font-medium focus:outline-none"
      >
        {options.map((p) => (
          <option key={p} value={p}>
            {periodLabel(p)}
          </option>
        ))}
      </select>
      <button type="button" className="px-2 h-full text-muted hover:text-ink border-l border-rule" onClick={() => onChange(shiftPeriod(value, 1))} aria-label="Next month" title="Next month">
        <IconChevronRight />
      </button>
    </div>
  );
}
function key(p: string) {
  const { month, year } = parsePeriod(p);
  return year * 12 + month;
}

/**
 * The filing window for a return month: the 11th to the 20th of the next month, IMS on the 14th and 3B on
 * the 20th, elapsed days shaded and today ringed.
 */
export function DeadlineStrip({
  period,
  imsDeadline,
  gstr3bDeadline,
  filed3bOn,
  compact,
}: {
  period: string;
  imsDeadline: string;
  gstr3bDeadline: string;
  filed3bOn?: string | null;
  compact?: boolean;
}) {
  const today = new Date();
  const win = filingWindow(period);
  const imsDay = Number(imsDeadline.slice(8, 10));
  const gstrDay = Number(gstr3bDeadline.slice(8, 10));
  const sameMonth = today.getFullYear() === win.year && today.getMonth() + 1 === win.month;
  const before = today.getFullYear() * 12 + today.getMonth() + 1 < win.year * 12 + win.month;
  const todayDay = today.getDate();
  const d3b = daysUntil(gstr3bDeadline, today);
  const dIms = daysUntil(imsDeadline, today);
  const days = Array.from({ length: 10 }, (_, i) => 11 + i);

  return (
    <div className="flex items-center gap-4 flex-wrap">
      <div className="flex gap-[3px]" aria-hidden="true">
        {days.map((d) => {
          const elapsed = !before && (!sameMonth || d < todayDay);
          const isToday = sameMonth && d === todayDay;
          const mark = d === imsDay ? "IMS" : d === gstrDay ? "3B" : null;
          return (
            <div
              key={d}
              className={cx(
                "rounded-[3px] flex flex-col items-center justify-center num leading-none",
                compact ? "w-[22px] h-[28px] text-[10.5px]" : "w-[26px] h-[34px] text-xs",
                mark ? "bg-accent text-white font-semibold" : elapsed ? "bg-rule/70 text-faint" : "bg-surface border border-rule text-ink-2",
                mark && elapsed && "bg-accent/45",
                isToday && "ring-2 ring-ink ring-offset-1",
              )}
            >
              <span>{d}</span>
              {mark && <span className={cx("mt-0.5 font-medium", compact ? "text-[8.5px]" : "text-[9.5px]")}>{mark}</span>}
            </div>
          );
        })}
      </div>
      <div className={cx("leading-snug", compact ? "text-xs" : "text-sm")}>
        <div className="text-ink">
          IMS actions by <b className="font-semibold">{fmtDateShort(imsDeadline)}</b>
          <span className={cx("ml-1.5", dIms < 0 ? "text-muted" : dIms <= 3 ? "text-high font-medium" : "text-muted")}>
            {dIms < 0 ? "passed" : daysText(dIms)}
          </span>
        </div>
        <div className="text-ink">
          GSTR-3B by <b className="font-semibold">{fmtDateShort(gstr3bDeadline)}</b>
          {filed3bOn ? (
            <span className="ml-1.5 text-ok font-medium">filed {fmtDate(filed3bOn)}</span>
          ) : (
            <span className={cx("ml-1.5", d3b < 0 ? "text-high font-medium" : d3b <= 3 ? "text-high font-medium" : "text-muted")}>{daysText(d3b)}</span>
          )}
        </div>
      </div>
    </div>
  );
}

const STEPS: PeriodStatus[] = ["not_started", "files_uploaded", "reconciled", "in_review", "approved", "closed"];

export function StatusStepper({ status }: { status: PeriodStatus }) {
  const idx = STEPS.indexOf(status);
  return (
    <ol className="flex items-center gap-0" aria-label={`Status: ${PERIOD_STATUS_LABEL[status]}`}>
      {STEPS.map((s, i) => {
        const done = i < idx || status === "closed";
        const current = i === idx && status !== "closed";
        return (
          <li key={s} className="flex items-center">
            {i > 0 && <span className={cx("w-5 h-px", i <= idx ? "bg-accent" : "bg-rule-strong")} />}
            <span
              aria-current={current ? "step" : undefined}
              className={cx(
                "inline-flex items-center gap-1.5 h-6 px-2 rounded-full text-xs whitespace-nowrap",
                current ? "bg-accent text-white font-medium" : done ? "text-accent" : "text-faint",
              )}
            >
              <span
                className={cx(
                  "inline-block w-1.5 h-1.5 rounded-full",
                  current ? "bg-white" : done ? "bg-accent" : "bg-rule-strong",
                )}
              />
              {PERIOD_STATUS_LABEL[s]}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export type NextAction = { label: string; tab: string; kind: "link" | "reconcile" | "done" | "waiting"; hint?: string };

export function nextAction(period: Period | null, open: number, role: Role): NextAction {
  const isReviewer = role === "reviewer" || role === "admin";
  const status = period?.status ?? "not_started";
  const hasBooks = period?.files.some((f) => f.role === "books");
  const hasPortal = period?.files.some((f) => f.role === "portal");
  switch (status) {
    case "not_started":
      return { label: "Upload files", tab: "overview", kind: "link" };
    case "files_uploaded":
      if (!hasBooks || !hasPortal) return { label: "Upload files", tab: "overview", kind: "link", hint: !hasBooks ? "Purchase register missing" : "2B missing" };
      return { label: "Reconcile", tab: "overview", kind: "reconcile" };
    case "reconciled":
      return open > 0 ? { label: `Review ${count(open)} open`, tab: "review", kind: "link" } : { label: "Submit for review", tab: "close", kind: "link" };
    case "in_review":
      return isReviewer ? { label: "Approve", tab: "close", kind: "link" } : { label: "With reviewer", tab: "close", kind: "waiting" };
    case "approved":
      return isReviewer ? { label: "Close month", tab: "close", kind: "link" } : { label: "Approved", tab: "close", kind: "waiting" };
    case "closed":
      return { label: "Closed ✓", tab: "close", kind: "done" };
  }
}
