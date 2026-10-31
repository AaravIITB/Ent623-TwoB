// Return periods are "MMYYYY" strings ("062026" = Jun 2026).

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export function isPeriod(p: string | undefined | null): p is string {
  return !!p && /^(0[1-9]|1[0-2])\d{4}$/.test(p);
}

export function parsePeriod(p: string): { month: number; year: number } {
  return { month: Number(p.slice(0, 2)), year: Number(p.slice(2)) };
}

export function makePeriod(month: number, year: number): string {
  return `${String(month).padStart(2, "0")}${year}`;
}

export function shiftPeriod(p: string, delta: number): string {
  const { month, year } = parsePeriod(p);
  const idx = year * 12 + (month - 1) + delta;
  return makePeriod((idx % 12) + 1, Math.floor(idx / 12));
}

export function periodLabel(p: string, long = false): string {
  if (!isPeriod(p)) return p;
  const { month, year } = parsePeriod(p);
  return `${(long ? MONTHS_LONG : MONTHS)[month - 1]} ${year}`;
}

/** The month before `today` (the return month staff are working on by default). */
export function previousPeriod(today: Date = new Date()): string {
  return shiftPeriod(makePeriod(today.getMonth() + 1, today.getFullYear()), -1);
}

/** Last `n` periods ending with the month before today, newest first. */
export function recentPeriods(n = 15, today: Date = new Date()): string[] {
  const start = shiftPeriod(previousPeriod(today), 1); // include current month too
  return Array.from({ length: n }, (_, i) => shiftPeriod(start, -i));
}

/** Whole days from `today` to ISO date `iso` (negative = past). */
export function daysUntil(iso: string, today: Date = new Date()): number {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const target = Date.UTC(y, m - 1, d);
  const t = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((target - t) / 86400000);
}

export function daysText(days: number): string {
  if (days === 0) return "due today";
  if (days === 1) return "1 day left";
  if (days > 1) return `${days} days left`;
  if (days === -1) return "1 day overdue";
  return `${-days} days overdue`;
}

/** Filing window for period p: the 11th to 20th of the following month, with key dates. */
export function filingWindow(p: string): { month: number; year: number; label: string } {
  const next = shiftPeriod(p, 1);
  const { month, year } = parsePeriod(next);
  return { month, year, label: `${MONTHS[month - 1]} ${year}` };
}
