# TaxMind web API (v1)

FastAPI backend in `server/`, React app in `web/`. This file is the contract between the two. All
amounts are rupees (float, 2 dp). Dates are ISO `YYYY-MM-DD`; timestamps ISO with offset. Periods are
`MMYYYY` strings (`"062026"`).

Base URL `/api`. Every endpoint except `POST /api/auth/login` and `GET /api/health` needs
`Authorization: Bearer <token>`. Errors: HTTP 4xx/5xx with `{"detail": "<plain-English message>"}`.

## Roles

| role | can |
|---|---|
| `admin` | everything, incl. users and deleting clients |
| `reviewer` | everything a preparer can, plus approve / send back / close a month |
| `preparer` | upload, reconcile, decide, follow up, submit for review |

## Period workflow (`status`)

`not_started` → `files_uploaded` → `reconciled` → `in_review` → `approved` → `closed`

- uploading files moves `not_started` → `files_uploaded`
- `POST .../reconcile` moves to `reconciled` (allowed from `files_uploaded`, `reconciled`, or `in_review`
  (sends it back to `reconciled`); refused when `approved`/`closed` - reopen first)
- `submit` (preparer) → `in_review`; `send-back` (reviewer, with a note) → `reconciled`;
  `approve` (reviewer) → `approved`; `close` (reviewer) → `closed` (builds the close pack, stores the
  reversal ledger for next month); `reopen` (reviewer/admin) → `reconciled`
- `filed_3b_on` is a separate date the staff record when 3B is filed (any status).
- Decisions can be edited only while status is `reconciled` or `in_review`.

Deadlines for period P (monthly filer): IMS action before 2B is generated on the **14th** of the next
month; GSTR-3B due the **20th** of the next month.

## Objects

```ts
type User = { id: number; username: string; name: string; role: "admin" | "reviewer" | "preparer" };

type ClientSettings = {
  tolerance: number;            // ₹, default 1
  tolerance_pct: number;        // %, default 0
  line_of_business: string[];   // tags from GET /api/meta (e.g. "vehicle_maker")
  policy: "pending" | "reverse";
};
type Client = {
  id: number; name: string; gstin: string; trade_name: string; notes: string;
  settings: ClientSettings;
  has_vendor_master: boolean;  // a vendor master file is stored for this client
  created_at: string;
};

type FileInfo = {
  id: number; role: "books" | "portal" | "vendor_master";
  filename: string; size: number; sha256: string; uploaded_at: string; uploaded_by: string;
  period_hint: string;        // portal: month detected or entered ("052026"), else ""
};

type Summary = {               // from the engine (taxmind.engine.summarise) + extras
  books_entries: number; portal_records: number; itc_books: number; itc_2b: number; itc_to_claim: number;
  findings: number; auto_cleared: number; needs_human: number; itc_needing_attention: number;
  supplier_groups: number; deemed_acceptance_records: number; deemed_acceptance_itc: number;
  blocked_review: number; blocked_review_itc: number; by_status: Record<string, number>;
  // progress after staff decisions:
  open: number;                // needs_human and no final decision yet
  decided: number;             // final decision recorded
  itc_after_decisions: number; // claim with final decisions applied
  history_suggestions: number; // open decisions that have a 'same as last month' suggestion
};
type Check = { name: string; level: "High" | "Review" | "OK"; detail: string; amount: number; count: number };
type Period = {
  id: number; client_id: number; period: string; label: string;   // "Jun 2026"
  status: "not_started" | "files_uploaded" | "reconciled" | "in_review" | "approved" | "closed";
  ims_deadline: string; gstr3b_deadline: string; filed_3b_on: string | null;
  files: FileInfo[];
  summary: Summary | null;      // null until reconciled
  checks: Check[];
  notes: string[];              // engine loading notes
  run_at: string | null; run_by: string | null;
  submitted_by: string | null; submitted_at: string | null;
  approved_by: string | null; approved_at: string | null;
  closed_by: string | null; closed_at: string | null; pack_fingerprint: string | null;
  review_note: string;          // last send-back / approval note
  prior_ledger_items: number;   // open reversal-ledger items brought from the previous closed month
};

type DocOut = {
  side: "books" | "portal"; doc_no: string; doc_date: string | null; doc_type: "INV" | "CN" | "DN";
  supplier_gstin: string; supplier_name: string;
  taxable: number; igst: number; cgst: number; sgst: number; cess: number; tax: number;
  period: string; itc_available: boolean | null; reverse_charge: boolean;
  source: string; row_ref: string;  // "file.xlsx:Sheet", "row 12"
  ledger: string; description: string; voucher_no: string; notes: string[];
};
type BlockedFlag = { rid: string; label: string; section: string; confidence: "Likely" | "Possible" | "Review";
                     evidence: string; advice: string; exceptions: string };
type Action = "Accept" | "Reject" | "Pending" | "No IMS action";
type Decision = {
  id: number; key: string; fid: string;
  status: string;            // human label, e.g. "Exact match"
  status_code: string;       // enum name, e.g. "EXACT", "PORTAL_ONLY_UNKNOWN"
  recommended: Action; final: Action | null; effective: Action;   // effective = final ?? recommended
  confidence: "High" | "Medium" | "Low"; owner: "Nobody" | "CA" | "Client" | "Supplier";
  needs_human: boolean;      // engine says a person must look
  done: boolean;             // !needs_human || final !== null || reviewed
  supplier_gstin: string; supplier_name: string;
  books: DocOut[]; portal: DocOut[];
  itc_in_2b: number; itc_in_books: number; itc_to_claim: number; itc_at_stake: number;
  reason: string; next_step: string; flags: string[]; blocked: BlockedFlag[];
  note: string; assignee: { id: number; name: string } | null;
  updated_by: string | null; updated_at: string | null;
  // what staff decided last month for the same supplier in the same situation (one-click suggestion)
  history: { final: Action; count: number; period: string; label: string; note: string } | null;
};
type Page<T> = { items: T[]; total: number; offset: number; limit: number };

type SupplierRow = {
  gstin: string; name: string; records_2b: number; entries_books: number; matched: number;
  open: number;              // decisions for this supplier still open (needs_human, no final)
  itc_2b: number; itc_books: number; itc_claim: number; itc_open: number;
  main_status: string; suggestion: string; statuses: string;
  in_books: boolean; followup_status: FollowUp["status"] | null;
};

type FollowUp = {
  id: number; supplier_gstin: string; supplier_name: string; items: number; itc_at_stake: number;
  whatsapp: string; email_subject: string; email_body: string;
  contact_email: string; contact_phone: string;
  status: "to_send" | "sent" | "replied" | "resolved" | "no_response";
  note: string; sent_at: string | null; updated_by: string | null; updated_at: string | null;
};

type Table4Line = { code: string; label: string; igst: number; cgst: number; sgst: number; cess: number;
                    total: number; count: number; note: string };
type LedgerItem = { gstin: string; supplier: string; doc_no: string; doc_date: string; period_reversed: string;
                    igst: number; cgst: number; sgst: number; cess: number; tax: number; reason: string };
type Table4 = { lines: Table4Line[]; ledger: LedgerItem[]; reclaimed: number; carried: number;
                new_reversals: number; policy: string; basis: "recommendations" | "final decisions" };

type DashboardRow = {
  client: Client;
  period: Period | null;        // the selected period for this client (null = not started)
  open: number; itc_at_risk: number; high_checks: number; followups_open: number;
  days_to_3b: number;           // negative = overdue
};
type Activity = { at: string; user: string; client: string; period: string; action: string; detail: string };
```

## Endpoints

### Meta / auth
- `GET /api/health` → `{ok: true, version}`
- `POST /api/auth/login` `{username, password}` → `{token, user: User}`
- `POST /api/auth/logout` → `{ok: true}`
- `GET /api/me` → `User`
- `GET /api/meta` → `{lines_of_business: {tag: description}, actions: Action[], statuses: {code: label},
  roles: [...], period_statuses: [...]}`

### Users (admin)
- `GET /api/users` → `User[]`
- `POST /api/users` `{username, name, role, password}` → `User`
- `PATCH /api/users/{id}` `{name?, role?, password?}` → `User`

### Clients
- `GET /api/clients` → `Client[]`
- `POST /api/clients` `{name, gstin, trade_name?, notes?, settings?}` → `Client` (GSTIN validated; 400 if invalid)
- `GET /api/clients/{id}` → `Client & {periods: Period[]}` (newest first, without `files`' detail cut)
- `PATCH /api/clients/{id}` `{name?, gstin?, trade_name?, notes?, settings?}` → `Client`
- `DELETE /api/clients/{id}` (admin) → `{ok: true}`
- `POST /api/clients/{id}/vendor-master` multipart `file` → `Client` (replaces the stored vendor master)

### Dashboard
- `GET /api/dashboard?period=MMYYYY` (default: the month before today) → `{period, label, ims_deadline,
  gstr3b_deadline, rows: DashboardRow[], totals: {clients, not_started, in_progress, in_review, closed,
  open_items, itc_at_risk}}`
- `GET /api/activity?limit=50` → `Activity[]`

### Periods (one client, one return month)
`{cid}` client id, `{p}` period `MMYYYY`. A period row is created on first use.
- `GET /api/clients/{cid}/periods/{p}` → `Period`
- `POST /api/clients/{cid}/periods/{p}/files` multipart `files[]` + form `role` (`books`|`portal`) and
  optional `period_hint` → `Period`. Portal files may be several months (earlier months for reclaims,
  next month for late filers); the engine reads each file's own month.
- `DELETE /api/clients/{cid}/periods/{p}/files/{fid}` → `Period`
- `POST /api/clients/{cid}/periods/{p}/reconcile` → `Period`. Runs the engine with the client settings,
  the stored vendor master and the reversal ledger of the previous closed period. Final decisions, notes
  and assignees from a previous run are carried over to findings with the same `key`.
- `GET /api/clients/{cid}/periods/{p}/decisions` → `Page<Decision>`. Query params (all optional):
  `view` = `open` (default: needs_human && no final) | `all` | `decided` | `auto` | `blocked`;
  `supplier` (GSTIN; `"(no GSTIN)"` allowed); `status_code` (comma list); `action` (effective action);
  `owner`; `assignee` (`me` or user id); `q` (search in supplier/doc no/reason); `sort` = `itc` (default,
  desc) | `supplier` | `status`; `offset` (0), `limit` (100, max 500).
- `GET /api/clients/{cid}/periods/{p}/decisions/{id}` → `Decision`
- `PATCH /api/clients/{cid}/periods/{p}/decisions/{id}` `{final?: Action | null, note?, assignee_id?: number|null}` → `Decision`
- `POST /api/clients/{cid}/periods/{p}/decisions/bulk` `{ids?: number[], filter?: <same params as GET>,
  final?: Action | null | "recommended", note?, assignee_id?}` → `{updated: number}`.
  `final: "recommended"` = accept TaxMind's recommendation as the final decision.
  `final: "history"` = apply last month's decision where `history` exists (others are skipped; the
  count of records actually changed is returned). Also accepted by PATCH.
- `GET /api/clients/{cid}/periods/{p}/suppliers?q=&only_open=true` → `SupplierRow[]` (sorted by itc_open desc)
- `GET /api/clients/{cid}/periods/{p}/table4?basis=final` → `Table4` (`basis=recommended` for TaxMind's own)
- `GET /api/clients/{cid}/periods/{p}/followups` → `FollowUp[]`
- `PATCH /api/clients/{cid}/periods/{p}/followups/{id}` `{status?, note?, contact_email?, contact_phone?}` → `FollowUp`
- `POST /api/clients/{cid}/periods/{p}/submit` `{note?}` → `Period`
- `POST /api/clients/{cid}/periods/{p}/send-back` `{note}` → `Period` (reviewer)
- `POST /api/clients/{cid}/periods/{p}/approve` `{note?}` → `Period` (reviewer). 409 if open items remain
  unless `{force: true}`.
- `POST /api/clients/{cid}/periods/{p}/close` → `Period` (reviewer; status must be `approved`)
- `POST /api/clients/{cid}/periods/{p}/reopen` `{note}` → `Period` (reviewer)
- `POST /api/clients/{cid}/periods/{p}/filed` `{filed_3b_on: "YYYY-MM-DD" | null}` → `Period`

### Downloads (return files; `?token=` query param accepted instead of the header so links work)
- `GET .../export/workbook` → xlsx (TaxMind workbook with the final decisions in "Final decision"/"CA note")
- `GET .../export/ims.csv` → CSV of IMS actions to take: GSTIN, supplier, doc type, doc no, date, taxable,
  tax, action (effective), reason - only records in this period's 2B whose action is Accept/Reject/Pending
- `GET .../export/prefiling.html` → the one-page pre-filing report
- `GET .../export/ledger.csv` → reversal ledger to carry forward (after final decisions)
- `GET .../export/close-pack` → the month-close pack zip (status `closed` only)

### Demo
- `POST /api/demo/seed` (admin) → `{clients: number}`: creates demo clients from `test_data/` (six
  profiles, files uploaded, Jun 2026 reconciled) so the app can be tried at once.
