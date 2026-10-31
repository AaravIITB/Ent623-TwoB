import { useState } from "react";
import type { ClientSettings, Policy } from "../api";
import { useMeta } from "../lib/hooks";
import { cx } from "../lib/format";
import { Field, Input, Segmented } from "./ui";

export const DEFAULT_SETTINGS: ClientSettings = { tolerance: 1, tolerance_pct: 0, line_of_business: [], policy: "pending" };

export const POLICY_TEXT: Record<Policy, string> = {
  pending: "2B bills not in the books are kept Pending in IMS until the client confirms them.",
  reverse: "2B bills not in the books flow into 3B and are reversed in Table 4(B)(2), then reclaimed when booked.",
};

export const LOB_LABEL: Record<string, string> = {
  vehicle_maker: "Vehicle maker",
  vehicle_dealer: "Vehicle dealer",
  caterer: "Restaurant / caterer",
  hotel: "Hotel",
  works_contractor: "Works contractor",
  insurer: "Insurer",
  travel_operator: "Tour / cab operator",
  gym_club: "Club / gym",
};
export function lobLabel(tag: string) {
  return LOB_LABEL[tag] ?? tag.replace(/_/g, " ");
}

/** Settings fields shared by "New client", the client page and the Overview tab. */
export function SettingsFields({ value, onChange, disabled }: { value: ClientSettings; onChange: (s: ClientSettings) => void; disabled?: boolean }) {
  const meta = useMeta();
  const lobs = meta.data?.lines_of_business ?? {};
  const [tolText, setTolText] = useState(String(value.tolerance));
  const [pctText, setPctText] = useState(String(value.tolerance_pct));
  return (
    <div className="space-y-4">
      <div>
        <span className="block text-sm font-medium text-ink-2 mb-1">Line of business</span>
        <p className="text-xs text-muted mb-2">Switches off Sec 17(5) blocks that don't apply to what the client itself supplies.</p>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(lobs).map(([tag, desc]) => {
            const on = value.line_of_business.includes(tag);
            return (
              <button
                key={tag}
                type="button"
                disabled={disabled}
                title={desc}
                aria-pressed={on}
                onClick={() =>
                  onChange({
                    ...value,
                    line_of_business: on ? value.line_of_business.filter((t) => t !== tag) : [...value.line_of_business, tag],
                  })
                }
                className={cx(
                  "h-7 px-2.5 rounded-full border text-sm",
                  on ? "bg-accent-soft border-accent text-accent font-medium" : "bg-surface border-rule-strong text-ink-2 hover:border-faint",
                  disabled && "opacity-60",
                )}
              >
                {on && "✓ "}
                {lobLabel(tag)}
              </button>
            );
          })}
          {meta.isLoading && <span className="text-sm text-muted">Loading…</span>}
        </div>
      </div>
      <div>
        <span className="block text-sm font-medium text-ink-2 mb-1">2B bills not in the books</span>
        <Segmented<Policy>
          ariaLabel="Not-in-books policy"
          value={value.policy}
          onChange={(policy) => !disabled && onChange({ ...value, policy })}
          options={[
            { value: "pending", label: "Keep pending" },
            { value: "reverse", label: "Claim and reverse" },
          ]}
        />
        <p className="text-xs text-muted mt-1.5">{POLICY_TEXT[value.policy]}</p>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Rounding tolerance (₹)" hint="Amount differences up to this are ignored.">
          <Input
            inputMode="decimal"
            disabled={disabled}
            value={tolText}
            onChange={(e) => {
              setTolText(e.target.value);
              const n = Number(e.target.value);
              if (e.target.value !== "" && Number.isFinite(n) && n >= 0) onChange({ ...value, tolerance: n });
            }}
          />
        </Field>
        <Field label="Tolerance (%)" hint="The larger of ₹ and % is used.">
          <Input
            inputMode="decimal"
            disabled={disabled}
            value={pctText}
            onChange={(e) => {
              setPctText(e.target.value);
              const n = Number(e.target.value);
              if (e.target.value !== "" && Number.isFinite(n) && n >= 0) onChange({ ...value, tolerance_pct: n });
            }}
          />
        </Field>
      </div>
    </div>
  );
}
