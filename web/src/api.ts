// Typed client for the TaxMind web API (docs/API.md, v1).

export type Role = "admin" | "reviewer" | "preparer";
export type User = { id: number; username: string; name: string; role: Role; active?: boolean };

export type Policy = "pending" | "reverse";
export type ClientSettings = {
  tolerance: number;
  tolerance_pct: number;
  line_of_business: string[];
  policy: Policy;
};
export type Client = {
  id: number;
  name: string;
  gstin: string;
  trade_name: string;
  notes: string;
  settings: ClientSettings;
  has_vendor_master: boolean;
  created_at: string;
};

export type FileRole = "books" | "portal" | "vendor_master";
export type FileInfo = {
  id: number;
  role: FileRole;
  filename: string;
  size: number;
  sha256: string;
  uploaded_at: string;
  uploaded_by: string;
  period_hint: string;
};

export type Summary = {
  books_entries: number;
  portal_records: number;
  itc_books: number;
  itc_2b: number;
  itc_to_claim: number;
  findings: number;
  auto_cleared: number;
  needs_human: number;
  itc_needing_attention: number;
  supplier_groups: number;
  deemed_acceptance_records: number;
  deemed_acceptance_itc: number;
  blocked_review: number;
  blocked_review_itc: number;
  by_status: Record<string, number>;
  open: number;
  decided: number;
  itc_after_decisions: number;
  /** Open decisions that have a "same as last month" suggestion. */
  history_suggestions?: number;
};
export type CheckLevel = "High" | "Review" | "OK";
export type Check = { name: string; level: CheckLevel; detail: string; amount: number; count: number };

export const PERIOD_STATUSES = [
  "not_started",
  "files_uploaded",
  "reconciled",
  "in_review",
  "approved",
  "closed",
] as const;
export type PeriodStatus = (typeof PERIOD_STATUSES)[number];

export type Period = {
  id: number;
  client_id: number;
  period: string;
  label: string;
  status: PeriodStatus;
  /** Files changed since the last run: back to files_uploaded until reconciled again. */
  stale?: boolean;
  ims_deadline: string;
  gstr3b_deadline: string;
  filed_3b_on: string | null;
  files: FileInfo[];
  summary: Summary | null;
  checks: Check[];
  notes: string[];
  run_at: string | null;
  run_by: string | null;
  submitted_by: string | null;
  submitted_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  closed_by: string | null;
  closed_at: string | null;
  pack_fingerprint: string | null;
  checks_ack: { by: string; at: string } | null;
  review_note: string;
  prior_ledger_items: number;
};

export type DocOut = {
  side: "books" | "portal";
  doc_no: string;
  doc_date: string | null;
  doc_type: "INV" | "CN" | "DN";
  supplier_gstin: string;
  supplier_name: string;
  taxable: number;
  igst: number;
  cgst: number;
  sgst: number;
  cess: number;
  tax: number;
  period: string;
  itc_available: boolean | null;
  reverse_charge: boolean;
  source: string;
  row_ref: string;
  ledger: string;
  description: string;
  voucher_no: string;
  notes: string[];
};
export type BlockedFlag = {
  rid: string;
  label: string;
  section: string;
  confidence: "Likely" | "Possible" | "Review";
  evidence: string;
  advice: string;
  exceptions: string;
};
export const ACTIONS = ["Accept", "Reject", "Pending", "No IMS action"] as const;
export type Action = (typeof ACTIONS)[number];
export type Owner = "Nobody" | "CA" | "Client" | "Supplier";
export type Confidence = "High" | "Medium" | "Low";

export type Decision = {
  id: number;
  key: string;
  fid: string;
  status: string;
  status_code: string;
  recommended: Action;
  final: Action | null;
  effective: Action;
  confidence: Confidence;
  owner: Owner;
  needs_human: boolean;
  done: boolean;
  supplier_gstin: string;
  supplier_name: string;
  books: DocOut[];
  portal: DocOut[];
  itc_in_2b: number;
  itc_in_books: number;
  itc_to_claim: number;
  itc_at_stake: number;
  reason: string;
  next_step: string;
  flags: string[];
  blocked: BlockedFlag[];
  note: string;
  assignee: { id: number; name: string } | null;
  updated_by: string | null;
  updated_at: string | null;
  /** What staff decided last month for the same supplier in the same situation. */
  history: DecisionHistory | null;
};
export type DecisionHistory = { final: Action; count: number; period: string; label: string; note: string };
export type Page<T> = { items: T[]; total: number; offset: number; limit: number };

export type FollowUpStatus = "to_send" | "sent" | "replied" | "resolved" | "no_response";
export type FollowUp = {
  id: number;
  supplier_gstin: string;
  supplier_name: string;
  items: number;
  itc_at_stake: number;
  whatsapp: string;
  email_subject: string;
  email_body: string;
  contact_email: string;
  contact_phone: string;
  status: FollowUpStatus;
  note: string;
  sent_at: string | null;
  updated_by: string | null;
  updated_at: string | null;
};

export type SupplierRow = {
  gstin: string;
  name: string;
  records_2b: number;
  entries_books: number;
  matched: number;
  open: number;
  itc_2b: number;
  itc_books: number;
  itc_claim: number;
  itc_open: number;
  main_status: string;
  suggestion: string;
  statuses: string;
  in_books: boolean;
  followup_status: FollowUpStatus | null;
  history_final: Action | null;
  history_count: number;
};

export type Table4Line = {
  code: string;
  label: string;
  igst: number;
  cgst: number;
  sgst: number;
  cess: number;
  total: number;
  count: number;
  note: string;
};
export type LedgerItem = {
  gstin: string;
  supplier: string;
  doc_no: string;
  doc_date: string;
  period_reversed: string;
  igst: number;
  cgst: number;
  sgst: number;
  cess: number;
  tax: number;
  reason: string;
};
export type Table4 = {
  lines: Table4Line[];
  ledger: LedgerItem[];
  reclaimed: number;
  carried: number;
  new_reversals: number;
  policy: string;
  basis: "recommendations" | "final decisions";
};

export type DashboardRow = {
  client: Client;
  period: Period | null;
  open: number;
  itc_at_risk: number;
  high_checks: number;
  followups_open: number;
  days_to_3b: number;
};
export type Dashboard = {
  period: string;
  label: string;
  ims_deadline: string;
  gstr3b_deadline: string;
  rows: DashboardRow[];
  totals: {
    clients: number;
    not_started: number;
    in_progress: number;
    in_review: number;
    closed: number;
    open_items: number;
    itc_at_risk: number;
  };
};
export type Activity = { at: string; user: string; client: string; period: string; action: string; detail: string; client_id?: number };

export type Meta = {
  lines_of_business: Record<string, string>;
  actions: Action[];
  statuses: Record<string, string>;
  roles: Role[];
  period_statuses: PeriodStatus[];
};

export type DecisionView = "open" | "all" | "decided" | "auto" | "blocked";
export type DecisionSort = "itc" | "supplier" | "status";
export type DecisionFilter = {
  view?: DecisionView;
  supplier?: string;
  status_code?: string;
  action?: Action;
  owner?: Owner;
  assignee?: string; // "me" or a user id
  q?: string;
  sort?: DecisionSort;
};
export type FinalChoice = Action | null | "recommended" | "history";

// ---------------------------------------------------------------------------------------------------------
// Transport

const TOKEN_KEY = "taxmind.token";
const USER_KEY = "taxmind.user";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function getStoredUser(): User | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}
export function storeSession(token: string, user: User): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}
export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function redirectToLogin(): void {
  clearSession();
  if (window.location.pathname !== "/login") {
    const next = window.location.pathname + window.location.search;
    window.location.assign(`/login?next=${encodeURIComponent(next)}`);
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function qs(params?: Query): string {
  if (!params) return "";
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

async function request<T>(method: string, path: string, opts: { body?: unknown; query?: Query; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(`/api${path}${qs(opts.query)}`, { method, headers, body });
  } catch {
    throw new ApiError(0, "Can't reach the TaxMind server. Check your connection and try again.");
  }
  if (res.status === 401 && path !== "/auth/login") {
    redirectToLogin();
    throw new ApiError(401, "Your session has ended. Sign in again.");
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    throw new ApiError(res.status, detailMessage(data, res.status));
  }
  return data as T;
}

function detailMessage(data: unknown, status: number): string {
  if (data && typeof data === "object" && "detail" in data) {
    const d = (data as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    // FastAPI validation errors: [{loc, msg}]
    if (Array.isArray(d)) {
      return d
        .map((e) => (e && typeof e === "object" && "msg" in e ? String((e as { msg: unknown }).msg) : String(e)))
        .join("; ");
    }
  }
  if (typeof data === "string" && data.length < 300) return data;
  return `The server returned an error (${status}).`;
}

/** Link for a file download; the API accepts ?token= so plain <a href> works. */
export function downloadUrl(path: string): string {
  const token = getToken() ?? "";
  return `/api${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
}

const enc = encodeURIComponent;
const pp = (cid: number, p: string) => `/clients/${cid}/periods/${enc(p)}`;

function filterQuery(f: DecisionFilter): Query {
  return {
    view: f.view,
    supplier: f.supplier,
    status_code: f.status_code,
    action: f.action,
    owner: f.owner,
    assignee: f.assignee,
    q: f.q,
    sort: f.sort,
  };
}

export const api = {
  health: () => request<{ ok: boolean; version: string }>("GET", "/health"),
  login: (username: string, password: string) =>
    request<{ token: string; user: User }>("POST", "/auth/login", { body: { username, password } }),
  logout: () => request<{ ok: true }>("POST", "/auth/logout"),
  me: () => request<User>("GET", "/me"),
  meta: () => request<Meta>("GET", "/meta"),

  users: () => request<User[]>("GET", "/users"),
  createUser: (u: { username: string; name: string; role: Role; password: string }) =>
    request<User>("POST", "/users", { body: u }),
  updateUser: (id: number, u: { name?: string; role?: Role; password?: string; active?: boolean }) =>
    request<User>("PATCH", `/users/${id}`, { body: u }),

  clients: () => request<Client[]>("GET", "/clients"),
  createClient: (c: { name: string; gstin: string; trade_name?: string; notes?: string; settings?: ClientSettings }) =>
    request<Client>("POST", "/clients", { body: c }),
  client: (id: number) => request<Client & { periods: Period[] }>("GET", `/clients/${id}`),
  updateClient: (id: number, c: Partial<Pick<Client, "name" | "gstin" | "trade_name" | "notes">> & { settings?: ClientSettings }) =>
    request<Client>("PATCH", `/clients/${id}`, { body: c }),
  deleteClient: (id: number) => request<{ ok: true }>("DELETE", `/clients/${id}`),
  uploadVendorMaster: (id: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Client>("POST", `/clients/${id}/vendor-master`, { form });
  },

  dashboard: (period?: string) => request<Dashboard>("GET", "/dashboard", { query: { period } }),
  activity: (limit = 50) => request<Activity[]>("GET", "/activity", { query: { limit } }),

  period: (cid: number, p: string) => request<Period>("GET", pp(cid, p)),
  uploadFiles: (cid: number, p: string, role: "books" | "portal", files: File[], periodHint?: string) => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    form.append("role", role);
    if (periodHint) form.append("period_hint", periodHint);
    return request<Period>("POST", `${pp(cid, p)}/files`, { form });
  },
  deleteFile: (cid: number, p: string, fid: number) => request<Period>("DELETE", `${pp(cid, p)}/files/${fid}`),
  reconcile: (cid: number, p: string) => request<Period>("POST", `${pp(cid, p)}/reconcile`),

  decisions: (cid: number, p: string, f: DecisionFilter, offset = 0, limit = 200) =>
    request<Page<Decision>>("GET", `${pp(cid, p)}/decisions`, { query: { ...filterQuery(f), offset, limit } }),
  decision: (cid: number, p: string, id: number) => request<Decision>("GET", `${pp(cid, p)}/decisions/${id}`),
  updateDecision: (cid: number, p: string, id: number, body: { final?: Action | null | "history"; note?: string; assignee_id?: number | null }) =>
    request<Decision>("PATCH", `${pp(cid, p)}/decisions/${id}`, { body }),
  bulk: (
    cid: number,
    p: string,
    body: { ids?: number[]; filter?: DecisionFilter; final?: FinalChoice; note?: string; assignee_id?: number | null },
  ) => request<{ updated: number }>("POST", `${pp(cid, p)}/decisions/bulk`, { body }),

  suppliers: (cid: number, p: string, q?: string, onlyOpen?: boolean) =>
    request<SupplierRow[]>("GET", `${pp(cid, p)}/suppliers`, { query: { q, only_open: onlyOpen ? "true" : undefined } }),
  table4: (cid: number, p: string, basis: "final" | "recommended") =>
    request<Table4>("GET", `${pp(cid, p)}/table4`, { query: { basis } }),
  followups: (cid: number, p: string) => request<FollowUp[]>("GET", `${pp(cid, p)}/followups`),
  updateFollowup: (
    cid: number,
    p: string,
    id: number,
    body: { status?: FollowUpStatus; note?: string; contact_email?: string; contact_phone?: string },
  ) => request<FollowUp>("PATCH", `${pp(cid, p)}/followups/${id}`, { body }),

  submit: (cid: number, p: string, note?: string) => request<Period>("POST", `${pp(cid, p)}/submit`, { body: { note } }),
  sendBack: (cid: number, p: string, note: string) => request<Period>("POST", `${pp(cid, p)}/send-back`, { body: { note } }),
  approve: (cid: number, p: string, note?: string, force?: boolean) =>
    request<Period>("POST", `${pp(cid, p)}/approve`, { body: { note, force } }),
  close: (cid: number, p: string) => request<Period>("POST", `${pp(cid, p)}/close`),
  reopen: (cid: number, p: string, note: string) => request<Period>("POST", `${pp(cid, p)}/reopen`, { body: { note } }),
  ackChecks: (cid: number, p: string, ack: boolean) =>
    request<Period>("POST", `${pp(cid, p)}/checks/ack`, { body: { ack } }),
  filed: (cid: number, p: string, filed_3b_on: string | null) =>
    request<Period>("POST", `${pp(cid, p)}/filed`, { body: { filed_3b_on } }),

  exportUrl: (cid: number, p: string, what: "workbook" | "ims.csv" | "prefiling.html" | "ledger.csv" | "close-pack") =>
    downloadUrl(`${pp(cid, p)}/export/${what}`),

  seedDemo: () => request<{ clients: number }>("POST", "/demo/seed"),
};
