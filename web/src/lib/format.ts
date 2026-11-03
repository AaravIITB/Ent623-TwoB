// Indian number formatting (lakh / crore grouping), dates and small text helpers.

/** Group an integer string the Indian way: 1234567 -> "12,34,567". */
export function groupIndian(intDigits: string): string {
  if (intDigits.length <= 3) return intDigits;
  const last3 = intDigits.slice(-3);
  let rest = intDigits.slice(0, -3);
  const parts: string[] = [];
  while (rest.length > 2) {
    parts.unshift(rest.slice(-2));
    rest = rest.slice(0, -2);
  }
  if (rest) parts.unshift(rest);
  return `${parts.join(",")},${last3}`;
}

/** 123456.5 -> "1,23,456.50" (no currency sign). Negative numbers get a leading minus. */
export function fmtNum(n: number | null | undefined, decimals = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "–";
  const neg = n < 0;
  const fixed = Math.abs(n).toFixed(decimals);
  const [int, frac] = fixed.split(".");
  const s = groupIndian(int) + (frac ? `.${frac}` : "");
  // Avoid "-0.00"
  const isZero = Number(fixed) === 0;
  return neg && !isZero ? `-${s}` : s;
}

/** ₹1,23,456.00 */
export function inr(n: number | null | undefined, decimals = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "–";
  const s = fmtNum(n, decimals);
  return s.startsWith("-") ? `-₹${s.slice(1)}` : `₹${s}`;
}

/** Whole rupees: ₹4,12,000 */
export function inr0(n: number | null | undefined): string {
  return inr(n === null || n === undefined ? n : Math.round(n), 0);
}

/** Compact for KPI cards: ₹4.2 L, ₹1.8 Cr, ₹85,400 below a lakh. */
export function inrCompact(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "–";
  const neg = n < 0;
  const a = Math.abs(n);
  let s: string;
  if (a >= 1e7) s = `₹${trim1(a / 1e7)} Cr`;
  else if (a >= 1e5) s = `₹${trim1(a / 1e5)} L`;
  else s = `₹${groupIndian(String(Math.round(a)))}`;
  return neg ? `-${s}` : s;
}

function trim1(x: number): string {
  // one decimal, but 2 significant digits for >= 100 ("₹125 Cr")
  if (x >= 100) return groupIndian(String(Math.round(x)));
  const s = x.toFixed(x >= 10 ? 1 : 2);
  return s.replace(/\.?0+$/, "");
}

/** Plain count: 1,500 -> "1,500"; 123456 -> "1,23,456" */
export function count(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  return fmtNum(n, 0);
}

export function plural(n: number, one: string, many?: string): string {
  return `${count(n)} ${n === 1 ? one : (many ?? `${one}s`)}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-07-20" -> "20 Jul 2026" */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
}

/** "2026-07-20" -> "20 Jul" */
export function fmtDateShort(iso: string | null | undefined): string {
  if (!iso) return "–";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}`;
}

/** Timestamp -> "20 Jul, 14:05" (local time) */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ${hh}:${mm}`;
}

/** "3 min ago", "yesterday", or a date */
export function timeAgo(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const s = Math.round((now.getTime() - d.getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 172800) return "yesterday";
  if (s < 7 * 86400) return `${Math.floor(s / 86400)} days ago`;
  return fmtDate(iso.slice(0, 10));
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function digitsOnly(s: string): string {
  return s.replace(/\D/g, "");
}

/** WhatsApp wants the number with country code and no symbols; assume India for 10-digit numbers. */
export function waNumber(phone: string): string {
  const d = digitsOnly(phone);
  if (d.length === 10) return `91${d}`;
  if (d.length === 11 && d.startsWith("0")) return `91${d.slice(1)}`;
  return d;
}

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

// Minimal class merge: later classes in the same group (width, height, padding, text size...) replace
// earlier ones, so component defaults can be overridden from the call site.
const SIZE_RE = /^text-(2xs|xs|sm|base|lg|xl|2xl|3xl|\[\d)/;
function groupOf(cls: string): string | null {
  const bare = cls.replace(/^!/, "");
  const colon = bare.lastIndexOf(":");
  const variant = colon >= 0 ? bare.slice(0, colon + 1) : "";
  const u = colon >= 0 ? bare.slice(colon + 1) : bare;
  if (SIZE_RE.test(u)) return variant + "text-size";
  const m = /^(min-w|max-w|w|min-h|max-h|h|px|py|pl|pr|pt|pb|p|mx|my|mt|mb|ml|mr|m|gap|rounded)-/.exec(u);
  if (m) return variant + m[1];
  if (/^(block|inline-block|inline-flex|flex|grid|hidden|inline)$/.test(u)) return variant + "display";
  return null;
}
export function tw(...parts: (string | false | null | undefined)[]): string {
  const list = parts.filter(Boolean).join(" ").split(/\s+/).filter(Boolean);
  const seen = new Set<string>();
  const out: string[] = [];
  for (let i = list.length - 1; i >= 0; i--) {
    const g = groupOf(list[i]);
    if (g) {
      if (seen.has(g)) continue;
      seen.add(g);
    }
    out.push(list[i]);
  }
  return out.reverse().join(" ");
}
