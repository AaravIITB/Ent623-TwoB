import {
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import type { Action, CheckLevel, PeriodStatus } from "../api";
import { cx, tw } from "../lib/format";
import { IconX } from "./icons";

// ---------------------------------------------------------------------------------------------------------
// Buttons

type Variant = "primary" | "secondary" | "ghost" | "danger" | "quiet";
type Size = "xs" | "sm" | "md";

const variantCls: Record<Variant, string> = {
  primary: "bg-accent text-white hover:bg-accent-hover border border-accent disabled:bg-faint disabled:border-faint",
  secondary: "bg-surface text-ink border border-rule-strong hover:bg-sunken hover:border-faint disabled:text-faint",
  ghost: "bg-transparent text-ink-2 border border-transparent hover:bg-black/[.04] disabled:text-faint",
  quiet: "bg-transparent text-accent border border-transparent hover:bg-accent-soft disabled:text-faint",
  danger: "bg-surface text-high border border-rule-strong hover:bg-high-soft hover:border-high/40 disabled:text-faint",
};
const sizeCls: Record<Size, string> = {
  xs: "h-6 px-2 text-xs gap-1 rounded",
  sm: "h-7 px-2.5 text-sm gap-1.5 rounded-[5px]",
  md: "h-8.5 px-3.5 text-base gap-2 rounded-md",
};

/** Classes for a link that looks like a button (avoids a <button> inside an <a>). */
export function btnCls(variant: Variant = "secondary", size: Size = "md", extra?: string) {
  return tw("inline-flex items-center justify-center font-medium whitespace-nowrap select-none", variantCls[variant], sizeCls[size], extra);
}

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  busy?: boolean;
  /** When set, the button is disabled and this explains why (tooltip). */
  disabledReason?: string | null;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", busy, disabledReason, className, children, disabled, title, ...rest },
  ref,
) {
  const isDisabled = disabled || busy || !!disabledReason;
  return (
    <button
      ref={ref}
      type="button"
      disabled={isDisabled}
      title={disabledReason ?? title}
      className={tw(
        "inline-flex items-center justify-center font-medium whitespace-nowrap select-none disabled:cursor-not-allowed",
        variantCls[variant],
        sizeCls[size],
        className,
      )}
      {...rest}
    >
      {busy && <Spinner size={12} />}
      {children}
    </button>
  );
});

export function Spinner({ size = 14, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      className={cx("animate-spin motion-reduce:animate-none", className)}
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeOpacity=".25" strokeWidth="2" />
      <path d="M14 8a6 6 0 0 0-6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

// ---------------------------------------------------------------------------------------------------------
// Form controls

const fieldBase =
  "w-full bg-surface border border-rule-strong rounded-[5px] text-ink placeholder:text-faint focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/15 disabled:bg-sunken disabled:text-muted";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(
  function Input({ className, invalid, ...rest }, ref) {
    return (
      <input
        ref={ref}
        className={tw(fieldBase, "h-8 px-2.5 text-base", invalid && "border-high focus:border-high focus:ring-high/15", className)}
        {...rest}
      />
    );
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, children, ...rest },
  ref,
) {
  return (
    <select ref={ref} className={tw(fieldBase, "h-8 pl-2 pr-7 text-base appearance-auto", className)} {...rest}>
      {children}
    </select>
  );
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, ...rest },
  ref,
) {
  return <textarea ref={ref} className={tw(fieldBase, "px-2.5 py-1.5 text-base leading-snug", className)} {...rest} />;
});

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cx("block", className)}>
      <span className="block text-sm font-medium text-ink-2 mb-1">{label}</span>
      {children}
      {error ? (
        <span className="block text-xs text-high mt-1">{error}</span>
      ) : hint ? (
        <span className="block text-xs text-muted mt-1">{hint}</span>
      ) : null}
    </label>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  size = "sm",
  ariaLabel,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode; title?: string }[];
  size?: "xs" | "sm";
  ariaLabel?: string;
}) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} className="inline-flex rounded-md border border-rule-strong bg-surface p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          title={o.title}
          onClick={() => onChange(o.value)}
          className={cx(
            "rounded-[4px] font-medium whitespace-nowrap",
            size === "xs" ? "h-5.5 px-2 text-xs" : "h-6.5 px-2.5 text-sm",
            value === o.value ? "bg-accent text-white" : "text-ink-2 hover:bg-sunken",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------
// Chips and badges

export const PERIOD_STATUS_LABEL: Record<PeriodStatus, string> = {
  not_started: "Not started",
  files_uploaded: "Files uploaded",
  reconciled: "Reconciled",
  in_review: "In review",
  approved: "Approved",
  closed: "Closed",
};

export function StatusChip({ status }: { status: PeriodStatus | null | undefined }) {
  const s = status ?? "not_started";
  const cls: Record<PeriodStatus, string> = {
    not_started: "text-muted bg-sunken border-rule",
    files_uploaded: "text-ink-2 bg-surface border-rule-strong",
    reconciled: "text-accent bg-accent-soft border-accent-line",
    in_review: "text-review bg-review-soft border-review/25",
    approved: "text-ok bg-ok-soft border-ok/25",
    closed: "text-white bg-ok border-ok",
  };
  return (
    <span className={cx("inline-flex items-center h-5.5 px-2 rounded-full border text-xs font-medium whitespace-nowrap", cls[s])}>
      {s === "closed" && <span className="mr-1">✓</span>}
      {PERIOD_STATUS_LABEL[s]}
    </span>
  );
}

export function LevelBadge({ level, children }: { level: CheckLevel; children?: ReactNode }) {
  const cls: Record<CheckLevel, string> = {
    High: "text-high bg-high-soft",
    Review: "text-review bg-review-soft",
    OK: "text-ok bg-ok-soft",
  };
  return (
    <span className={cx("inline-flex items-center h-5 px-1.5 rounded text-xs font-semibold whitespace-nowrap", cls[level])}>
      {children ?? level}
    </span>
  );
}

const ACTION_CLS: Record<Action, string> = {
  Accept: "text-ok",
  Reject: "text-high",
  Pending: "text-review",
  "No IMS action": "text-muted",
};
export const ACTION_SHORT: Record<Action, string> = {
  Accept: "Accept",
  Reject: "Reject",
  Pending: "Pending",
  "No IMS action": "No IMS",
};
export const ACTION_KEY: Record<Action, string> = { Accept: "a", Reject: "r", Pending: "p", "No IMS action": "n" };

export function ActionText({ action, className }: { action: Action; className?: string }) {
  return <span className={cx("font-medium whitespace-nowrap", ACTION_CLS[action], className)}>{ACTION_SHORT[action]}</span>;
}

export function Tag({ children, tone = "neutral", title }: { children: ReactNode; tone?: "neutral" | "accent" | "high" | "review" | "ok"; title?: string }) {
  const cls = {
    neutral: "bg-sunken text-ink-2 border-rule",
    accent: "bg-accent-soft text-accent border-accent-line",
    high: "bg-high-soft text-high border-high/20",
    review: "bg-review-soft text-review border-review/20",
    ok: "bg-ok-soft text-ok border-ok/20",
  }[tone];
  return (
    <span title={title} className={cx("inline-flex items-center h-5 px-1.5 rounded border text-2xs font-medium whitespace-nowrap", cls)}>
      {children}
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded border border-rule-strong border-b-2 bg-surface text-[10.5px] font-mono text-ink-2 leading-none">
      {children}
    </kbd>
  );
}

// ---------------------------------------------------------------------------------------------------------
// Layout helpers

export function Panel({ children, className, title, actions, flush }: { children: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode; flush?: boolean }) {
  return (
    <section className={cx("bg-surface border border-rule rounded-lg", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 px-4 h-11 border-b border-rule">
          <h2 className="text-base font-semibold text-ink">{title}</h2>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={flush ? "" : "p-4"}>{children}</div>
    </section>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton", className)} />;
}

export function TableSkeleton({ rows = 8, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="p-3 space-y-2.5" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex gap-3">
          {Array.from({ length: cols }, (_, j) => (
            <Skeleton key={j} className={cx("h-4", j === 0 ? "w-1/4" : "flex-1")} />
          ))}
        </div>
      ))}
    </div>
  );
}

export function EmptyState({ title, children, action, className }: { title: string; children?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cx("flex flex-col items-center justify-center text-center px-6 py-12", className)}>
      <p className="text-lg font-medium text-ink">{title}</p>
      {children && <div className="mt-1.5 max-w-md text-sm text-muted">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorNote({ error, className }: { error: unknown; className?: string }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className={cx("rounded-md border border-high/25 bg-high-soft px-3 py-2 text-sm text-high", className)}>
      {msg}
    </div>
  );
}

export function Banner({ tone = "neutral", children, icon, action }: { tone?: "neutral" | "review" | "high" | "ok" | "accent"; children: ReactNode; icon?: ReactNode; action?: ReactNode }) {
  const cls = {
    neutral: "bg-sunken border-rule text-ink-2",
    review: "bg-review-soft border-review/25 text-[#6e4105]",
    high: "bg-high-soft border-high/25 text-high",
    ok: "bg-ok-soft border-ok/25 text-ok",
    accent: "bg-accent-soft border-accent-line text-accent",
  }[tone];
  return (
    <div className={cx("flex items-center gap-2.5 rounded-md border px-3 py-2 text-sm", cls)}>
      {icon}
      <div className="flex-1 min-w-0">{children}</div>
      {action}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------
// Overlays

function useEscape(onClose: () => void, active: boolean) {
  useEffect(() => {
    if (!active) return;
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [onClose, active]);
}

export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
  width = 520,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  useEscape(onClose, open);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) {
      const prev = document.activeElement as HTMLElement | null;
      const first = ref.current?.querySelector<HTMLElement>("input,select,textarea,button:not([data-close])");
      first?.focus();
      return () => prev?.focus?.();
    }
  }, [open]);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[10vh] px-4">
      <div className="absolute inset-0 bg-ink/30" onClick={onClose} />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative w-full bg-surface rounded-lg shadow-[0_12px_40px_rgba(24,33,44,.18)] border border-rule max-h-[80vh] flex flex-col"
        style={{ maxWidth: width }}
      >
        <header className="flex items-center justify-between px-5 h-12 border-b border-rule shrink-0">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button data-close type="button" onClick={onClose} className="p-1 rounded text-muted hover:text-ink hover:bg-sunken" aria-label="Close">
            <IconX />
          </button>
        </header>
        <div className="px-5 py-4 overflow-auto">{children}</div>
        {footer && <footer className="flex justify-end gap-2 px-5 py-3 border-t border-rule bg-sunken rounded-b-lg shrink-0">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  width = 640,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  useEscape(onClose, open);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-40 pointer-events-none">
      <aside
        role="dialog"
        aria-label={typeof title === "string" ? title : "Details"}
        className="pointer-events-auto absolute right-0 top-0 h-full bg-surface border-l border-rule shadow-[-8px_0_30px_rgba(24,33,44,.10)] flex flex-col"
        style={{ width: `min(${width}px, 100vw)` }}
      >
        <header className="flex items-start justify-between gap-3 px-5 pt-4 pb-3 border-b border-rule shrink-0">
          <div className="min-w-0">
            <div className="text-lg font-semibold leading-tight">{title}</div>
            {subtitle && <div className="mt-0.5 text-sm text-muted">{subtitle}</div>}
          </div>
          <button type="button" onClick={onClose} className="p-1 rounded text-muted hover:text-ink hover:bg-sunken" aria-label="Close (Esc)" title="Close (Esc)">
            <IconX />
          </button>
        </header>
        <div className="flex-1 overflow-auto">{children}</div>
        {footer && <footer className="px-5 py-3 border-t border-rule bg-sunken shrink-0">{footer}</footer>}
      </aside>
    </div>,
    document.body,
  );
}

// ---------------------------------------------------------------------------------------------------------
// Toasts

type Toast = { id: number; text: ReactNode; tone: "neutral" | "error" | "ok" };
const ToastCtx = createContext<(text: ReactNode, tone?: Toast["tone"]) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const idRef = useRef(0);
  const push = useCallback((text: ReactNode, tone: Toast["tone"] = "neutral") => {
    const id = ++idRef.current;
    setToasts((t) => [...t.slice(-3), { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "error" ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      {createPortal(
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[60] flex flex-col items-center gap-2" aria-live="polite">
          {toasts.map((t) => (
            <div
              key={t.id}
              className={cx(
                "rounded-md px-3.5 py-2 text-sm shadow-[0_6px_20px_rgba(24,33,44,.2)] max-w-[560px]",
                t.tone === "error" ? "bg-high text-white" : t.tone === "ok" ? "bg-ink text-white" : "bg-ink text-white",
              )}
            >
              {t.tone === "ok" && <span className="mr-1.5 text-[#8fd1a9]">✓</span>}
              {t.text}
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastCtx.Provider>
  );
}

export function useToast() {
  return useContext(ToastCtx);
}

// ---------------------------------------------------------------------------------------------------------

export function CopyButton({ text, label = "Copy", copiedLabel = "Copied", size = "sm", variant = "secondary", icon }: { text: string; label?: string; copiedLabel?: string; size?: Size; variant?: Variant; icon?: ReactNode }) {
  const [done, setDone] = useState(false);
  const toast = useToast();
  return (
    <Button
      size={size}
      variant={variant}
      onClick={async () => {
        const ok = await copyText(text);
        if (ok) {
          setDone(true);
          setTimeout(() => setDone(false), 1600);
        } else toast("Couldn't copy. Select the text and press Ctrl+C.", "error");
      }}
    >
      {icon}
      {done ? copiedLabel : label}
    </Button>
  );
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    } catch {
      return false;
    }
  }
}

export function ProgressBar({ value, max, tone = "accent", className }: { value: number; max: number; tone?: "accent" | "ok"; className?: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className={cx("h-1.5 rounded-full bg-rule overflow-hidden", className)} role="progressbar" aria-valuenow={value} aria-valuemax={max}>
      <div className={cx("h-full rounded-full", tone === "ok" ? "bg-ok" : "bg-accent")} style={{ width: `${pct}%` }} />
    </div>
  );
}
