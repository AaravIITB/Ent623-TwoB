# TwoB: GSTR-2B / IMS reconciliation engine

TwoB matches a client's purchase register against GSTR-2B / IMS and recommends **Accept / Reject / Pending** for every record. Each recommendation comes with a plain-English reason, the person who has to act (nobody, CA, client or supplier), and how much ITC is at stake.

It also runs pre-filing checks before GSTR-3B is filed, flags possible **Sec 17(5) blocked credit** on invoices that match perfectly, drafts WhatsApp/email messages for suppliers who need to fix something, writes an Excel workbook for the CA with a ready **GSTR-3B Table 4 working**, carries a month-to-month **ITC reversal ledger** so reversed ITC is reclaimed when the bill is finally booked, and produces a dated **month-close pack** recording the CA's final decisions.

Built by team TwoB for ENT 623. The recommendations are defaults for a CA to review, not filing advice.

## The product: TwoB web app

A web app for a CA firm's GST team: one login per staff member, every client on one dashboard, and each client's month taken from upload to a closed, signed-off record.

```bash
scripts/run.sh                     # installs, builds the web app once, serves http://localhost:8000
# or: docker compose up --build    # same, in a container; data kept in the 'taxmind-data' volume
```

The first start creates the user `admin` with password `admin123` (set `TAXMIND_ADMIN_PASSWORD` before the first start to choose another). To try it with data, log in as admin and press **Load demo clients**, or call `POST /api/demo/seed`. This adds six fictional clients from `test_data/`, with Jun 2026 reconciled, plus demo users `riya` / `aman` (preparers) and `camehta` (reviewer), all with password `demo123`.

| Step | Who | What the app does |
|---|---|---|
| Dashboard | everyone | All clients for the month: status, open items, ITC at risk, high-risk checks, follow-ups, days to the IMS (14th) and 3B (20th) deadlines |
| Upload | preparer | Purchase register (Excel / CSV / Tally XML) and GSTR-2B / IMS for this and nearby months. The vendor master is stored once per client |
| Reconcile | preparer | Runs the engine with the client's settings and last month's reversal ledger. Re-running keeps decisions already taken |
| Review | preparer | Works supplier by supplier: bulk Accept / Reject / Pending / No IMS action, use the recommendation, notes, assign to a colleague, keyboard shortcuts, and *same as last month* suggestions taken from the previous month's decisions |
| Follow-ups | preparer | One message per supplier (WhatsApp / email), contact details remembered, status to send → sent → replied → resolved |
| 3B Table 4 | everyone | Live from the final decisions, with the reversal ledger |
| Sign-off | reviewer | Submit → approve or send back with a note → close. Closing builds the month-close pack (SHA-256 fingerprint) and carries the reversal ledger into next month. 3B filing date recorded; reopen with a reason |
| Exports | everyone | Workbook with the final decisions, IMS actions CSV, pre-filing report, ledger CSV, close pack |

Roles: `preparer` (do the work), `reviewer` (also approve, send back, close, reopen) and `admin` (also users, delete clients). Every action is logged on the activity feed.

Architecture:
- `server/taxmind_server/` is FastAPI + SQLAlchemy on SQLite: one file in `data/` (or `TAXMIND_DATA`) with the uploads and packs next to it.
- The API contract is `docs/API.md`; the live docs are at `/api/docs`.
- `web/` is React + TypeScript (Vite), served by the same process.
- Each run stores the exact files, settings, vendor master and prior ledger it used, so exports and the close pack always describe exactly what was reviewed.
- Back up the `data/` folder.

Tests: `python -m pytest -q` (engine) and `python -m pytest -q server/tests` (API). For the web app, run `cd web && npm run typecheck && npm test`.

The older Streamlit demo (`streamlit run app.py`) still works for a quick single-user look.

## Quick start (engine)

```bash
pip install -r requirements.txt

# the Streamlit demo (upload files, or click "Try with sample data")
streamlit run app.py

# command line
python -m taxmind sample --out sample_data            # make a synthetic month with known answers
python -m taxmind reconcile \
    --books  sample_data/purchase_register_092026.xlsx \
    --portal sample_data/gstr2b_092026.json sample_data/gstr2b_102026.json \
    --client "Sharma Auto Components" --out output
# a CA firm's own working file: one workbook with the 3B summary, purchase register and 2B sheet
python -m taxmind reconcile --books client_GSTR-3B_Jun-26.xlsx --portal client_GSTR-3B_Jun-26.xlsx \
    --line-of-business vehicle_maker --prior-ledger output/..._052026_itc_reversal_ledger.csv
python -m taxmind reconcile ... --close-pack --preparer "Riya" --reviewer "CA Mehta" \
    [--decisions output/edited_workbook.xlsx]          # also write the month-close pack
python -m taxmind verify output/..._close_pack.zip --fingerprint <hash>   # check a pack later
python -m taxmind benchmark --data sample_data        # score against the known answers
python -c "from taxmind.bench_ca import run; run('test_data')"   # realistic CA-style data, 6 clients
python -m pytest -q                                   # tests
```

## Inputs

| Side | Formats read | Notes |
|---|---|---|
| Books (purchase register) | Excel/CSV export from Tally, Busy, Zoho or a hand-made sheet; Tally XML (Day Book) | Must include the **supplier's invoice number**. Tally's voucher no. matches poorly. |
| Portal | GSTR-2B JSON, GSTR-2B Excel, GSTR-2A JSON, IMS JSON/Excel | Load **this month and next month**, so late filers are explained rather than chased. |

Columns are recognised by name, the header row is found automatically, and tax split across rate-wise columns (e.g. "Input CGST 9%", "Input CGST 2.5%") is summed.

What real registers look like, and how TwoB copes (built from a CA firm's actual month, see "Accuracy"):

- **One workbook, both sides.** A firm's working file often holds a 3B Summary, the purchase register and its own flattened 2B sheet. Pass the same file as books and as portal; each sheet is read by the side it belongs to (by its headers and name), the Summary is skipped, and the client's GSTIN is read from it.
- **Tally journal registers.** When the register's only date is the voucher (booking) date, the **supplier's invoice date is read from the narration** ("dtd 18 May 2026", "\t30-Apr-26", "dated 01st Jun 2026"; service-period dates are ignored). A blank **Invoice No is read from the narration** too ("Inv No PX4/26-27/052 dtd ...", "as per invoices : X", typos like "INVOCIE"). Junk such as "No-ABX123", "_x000D_", tabs and "M/s" is cleaned.
- **Blank GSTINs** are kept, not dropped: TwoB fills them from the PAN column, from the same invoice number in 2B under a similar name, or from a unique supplier name, and says so on the record. The rest become "Supplier GSTIN missing in books".
- **Entries with no GST** (diesel, rent to an individual, advances against proforma invoices, provision reversals) are listed as "No GST on this entry" and kept out of matching.
- **Debit Note vouchers** whose Invoice No column holds the original invoice: the credit note no. is read from the narration ("Credit note no X, against invoice no Y").
- **Correction entries** ("excess booking rectified", "less booking made earlier") are shown as corrections of the invoice they name, not as new bills.
- **The firm's own columns**: an "ITC ELIGIBLITY" Yes/No column (vendor master) and an "Activity" column feed the blocked-credit check; 2B "Invoice Type" (Regular / Credit / Debit / B2BA) and a "Period" column like "June,2026" are understood; Excel errors (#N/A, #REF!) are ignored.

For the blocked-credit check the books should also carry at least one of: the **purchase / expense ledger** (a "Purchase Ledger" column, or Tally's columnar register where each ledger is its own amount column), an **item description / narration**, or the **HSN/SAC**. Tally XML gives the ledgers, stock items, narration and HSN automatically.

## How it works

1. **Load:** every file becomes a list of `Doc` records (`taxmind/loaders/`).
2. **Normalise invoice numbers** (`normalize.py`). For example, `INV/26-27/0045`, `inv-0045` and `45` all reduce to the same serial. Financial-year suffixes, leading zeros, separators and O-vs-0 are handled.
3. **Match** (`matcher.py`). Records are compared only within the same supplier PAN and document type. Pairs are scored, then assigned one-to-one with the strongest evidence first. Split or combined invoices are tried before weak pairings. Leftover books entries are then checked against other months' 2B.
4. **Recommend** (`recommend.py`): each pair or leftover becomes a `Finding` with an action, reason, owner, confidence and ITC.
5. **Check before filing** (`risk.py`):
   - 3B ITC vs 2B against the DRC-01C limits (>₹25 lakh **and** >20%)
   - deemed-acceptance exposure
   - unknown suppliers
   - duplicates
   - Sec 16(4) deadline
   - possible double claims
   - wrong tax head
   - credit notes not booked
   - concentration
   - a purchase register that covers only part of the purchases (most 2B suppliers never in the books)
   - books entries without a GSTIN, bills booked without GST, older bills booked late, tax keyed at a non-GST rate
6. **Follow up** (`followup.py`): one message per supplier, written in the client's voice, plus a list of questions for the client.
7. **Blocked credit** (`blocked.py`): every decision is checked for likely Sec 17(5) items (see below).
8. **3B Table 4** (`gstr3b.py`): see below.
9. **Report** (`report.py`): an Excel workbook (Summary, 3B Table 4, IMS decisions, By supplier, Books not in 2B, Supplier follow-ups, Client questions, Blocked credit review, All findings) and a one-page HTML pre-filing report. The "All findings" sheet has blank **Final decision** and **CA note** columns for the CA to fill in.
10. **Month-close pack** (`closepack.py`): see below.

## Blocked credit (Sec 17(5))

A bill can match 2B exactly and still carry ITC the law blocks. GSTR-2B only marks place-of-supply and Sec 16(4) cases as "ITC not available", so nothing on the portal catches these. TwoB flags them **for review** and never reverses ITC itself, because most blocks have exceptions (a caterer buying food to resell, a car dealer buying cars, insurance an employer must provide by law).

| Flag | Section | Typical evidence |
|---|---|---|
| Food and beverages / outdoor catering | 17(5)(b)(i) | "Staff Welfare - Food", "Canteen", SAC 99633x |
| Hotel bill, room vs food unclear | 17(5)(b)(i) | hotel supplier on a travel ledger, "Lodging & Boarding", room with breakfast (Review). Room-only stays and hall rent are not flagged |
| Beauty / health services | 17(5)(b)(i) | "Medical Expenses", "Doctor / OPD", SAC 9993 (not 99932-99935 social care), 999721-2 |
| Life / health insurance | 17(5)(b)(i) | "Group Health Insurance", "Mediclaim" |
| Vessels and aircraft | 17(5)(aa) | "Helicopter Charter", HSN 8802 / 8901 / 8903, SAC 996602-3 |
| Motor vehicles up to 13 seats: purchase, hire, repair, insurance | 17(5)(a), (ab), (b)(i) | "Car Repairs", "Cab Hire", "Vehicle Exp - Innova", HSN 8703 / 8711, SAC 9966; "Conveyance" only as Possible. Not flagged for goods vehicles, trucks, buses, more than 13 seats, parts, driving schools, tourist taxis |
| Club / fitness membership | 17(5)(b)(ii) | "Club Membership", "Gym", SAC 999723 |
| Employee vacation travel | 17(5)(b)(iii) | "LTC", "Leave Travel", "Staff Picnic" |
| Construction of immovable property | 17(5)(c), (d) | "Building Construction", "Civil Works", "Shed", SAC 9954 (not repairs charged to P&L, machinery foundations, rent) |
| CSR | 17(5)(fa) | "CSR Expenses" |
| Personal consumption | 17(5)(g) | "Personal", "Residence", "Director's family" |
| Gifts / free samples | 17(5)(h) | "Diwali Gifts", "Free Samples"; "Business Promotion" only as Possible |
| Goods lost, stolen, destroyed, written off | 17(5)(h) | "Stock Written Off", "Theft", "Expired stock" |

Confidence is **Likely** when the ledger, description or HSN/SAC points to it, **Possible** when only the supplier's name or a vague ledger ("Conveyance", "Business Promotion") does, and **Review** for mixed hotel bills. Goods explicitly bought for resale or assembly, trading "Purchase - ..." ledgers, and statutory obligations (e.g. a canteen under the Factories Act) are not flagged, since those are exceptions to the blocks. Not covered, because the invoice can't show them: (e) composition, (f) non-resident persons, (i) tax paid under Sec 74. Flagged items are counted as needing a person, appear on the "Blocked credit review" sheet with the exceptions spelt out, and raise a pre-filing check. The 57th GST Council (8 Oct 2026) recommended removing several blocks (outdoor catering, life/health insurance, telecom towers, pipelines outside the factory, free samples, shelf-life write-offs). That needs a law amendment and is not applied. The rules and exception texts were checked by an independent legal review against the Act and CBIC circulars 92/2019, 170/2022 and 172/2022.

## GSTR-3B Table 4 and the reversal ledger

The "3B Table 4" sheet (also in the HTML report and the app) turns the decisions into what is typed into 3B, head by head (IGST / CGST / SGST / Cess):

| Line | What goes in it |
|---|---|
| 2B as generated | ITC in this month's 2B marked available |
| less: IMS Pending / Rejected | records the recommendations hold back; they drop out when 2B is recomputed |
| **4(A)(5)** | the above, plus reclaims |
| **4(B)(1)** | proposed Sec 17(5) reversal: decisions being claimed that carry a *Likely* blocked-credit flag (the CA confirms) |
| **4(B)(2)** | ITC in 2B that can't be claimed yet: booked without GST, supplier reported more than books, and (under the `reverse` policy) 2B bills not in books |
| **4(C)** | net ITC |
| **4(D)(1)** | reclaims of earlier 4(B)(2) reversals, now booked |
| **4(D)(2)** | 2B "ITC not available" (Sec 16(4) / place of supply) |
| `?` lines | not in the totals: *Possible/Review* blocked credit, and older bills booked late that may be reclaims |

Every 4(B)(2) reversal is written to `..._itc_reversal_ledger.csv`. Load it next month (`--prior-ledger`, or the upload in the app's client settings): bills from it that are now booked are reclaimed in 4(A)(5) and shown in 4(D)(1), and the rest are carried forward. This is the step CA staff otherwise track by hand in the 3B working ("Reclaim ITC which was reversed in earlier period now found matching with PR").

`--policy pending` (default) keeps 2B bills that aren't in the books Pending in IMS. `--policy reverse` follows firms that let them flow into 3B and reverse them in 4(B)(2), which puts them on the ledger. The month-close pack rebuilds Table 4 and the ledger with the CA's final decisions.

## Client settings

| Setting | CLI | What it does |
|---|---|---|
| % tolerance | `--tolerance-pct 0.1` | rounding allowed is the larger of the ₹ tolerance and this % of the amount (interviews asked for amount-based tolerance) |
| Line of business | `--line-of-business vehicle_maker,caterer` | switches off Sec 17(5) blocks that don't apply to what the client itself supplies: `vehicle_maker`, `vehicle_dealer`, `caterer`, `hotel`, `works_contractor`, `insurer`, `travel_operator`, `gym_club` (cab hire stays blocked for a vehicle maker) |
| Client GSTIN | `--gstin` (or read from a 3B summary sheet) | flags IGST from a same-state supplier, or CGST/SGST from another state, on bills not yet in 2B |
| Not-in-books policy | `--policy pending/reverse` | see above |
| Prior ledger | `--prior-ledger file.csv` | see above |
| Vendor master | `--vendor-master vendors.xlsx` | GSTIN + name (+ Activity, ITC eligibility): fills blank GSTINs (also proprietor vs trade names), marks suppliers whose bills are booked in another register as known, and feeds the blocked-credit check |

When most 2B records come from suppliers the books never mention, the register is probably partial (e.g. only journal vouchers). TwoB then says so, holds those records **Pending instead of Reject** (rejecting genuine airline or hotel bills would lose ITC), and the **By supplier** sheet lets staff decide them one supplier at a time: the summary shows how many supplier-level decisions the open items reduce to.

## Month-close pack

IMS keeps only the latest action, and accepted / rejected records leave IMS once GSTR-3B is filed, while notices can come up to 42 months later (Sec 74A). The pack is the firm's own record of what was decided and why. It is a `.zip` with:

- `record.html` / `record.pdf`: the close record (who prepared and reviewed it, when, ITC recommended vs ITC after the CA's decisions, every decision the CA changed with the note, the pre-filing checks, the blocked-credit items reviewed)
- `decisions.csv` / `decisions.json`: every decision with the recommendation, final decision, CA note, reason and ITC
- `reconciliation.xlsx`: the full workbook
- `inputs/`: exact copies of the files the reconciliation was run on
- `manifest.json`: SHA-256 of every file, engine version and settings

The CA's decisions come from the app's Month-close tab (an editable table), or from the workbook's "Final decision" / "CA note" columns (`--decisions`). The CLI and app print a **pack fingerprint** (SHA-256 of `manifest.json`). Note it in the client file or the covering email; `taxmind verify` then shows whether any file in the pack was changed later. The hashes make changes detectable; they do not stop someone from rebuilding a whole pack, which is why the fingerprint should be kept outside it.

## What it decides

| Status | Default action | Who acts |
|---|---|---|
| Exact match / number format differs / date differs | Accept (high confidence) | Nobody |
| Probable typo in invoice no. | Accept (medium) | CA glances at invoice |
| Split / combined invoices | Accept (medium) | CA confirms |
| Supplier reported less tax than books | Accept, claim 2B amount | Supplier amends balance |
| Supplier reported more tax than books | Pending; up to ₹10 more: Accept and claim the books amount | Client checks books |
| Same tax, only the taxable value differs (freight / non-GST charges in books) | Accept | Nobody |
| Wrong tax head (IGST vs CGST/SGST) | Pending | Supplier amends |
| Supplier used another GSTIN (same PAN) | Pending | Client checks invoice |
| Same amounts, unrelated number | Pending (low) | CA checks |
| In 2B, not in books, known supplier | Pending | Client: received? |
| In 2B, not in books, unknown supplier | Reject (confirm); Pending when the register looks partial | Client |
| Reverse charge | No IMS action; pay in cash, claim in 4(A)(3) | CA |
| Supplier credit note not in books | Pending (one month max) | Client |
| In books, not in 2B | Don't claim this month | Supplier files |
| Credit note in books, not in 2B | Reverse the ITC it cancels now (4(B)(2)) | Supplier reports it |
| Found in a later 2B | Claim in that month | Nobody |
| Duplicate in books | Delete duplicate | CA |
| Older bill, not in this 2B (invoice dated before the month) | Nothing in IMS; likely in an earlier 2B, possible reclaim | CA (load earlier 2B / ledger) |
| Found in an earlier 2B | Reclaim if reversed then; don't claim twice | CA |
| Booked without GST (2B has tax, books none) | Accept; ITC not claimed (4(B)(2)) unless books are corrected | CA |
| Supplier GSTIN missing in books (not found by PAN/name/invoice no.) | Don't claim until the GSTIN is known | Client |
| Correction entry in books | Nothing separate to match | CA glances |
| No GST on this entry | Excluded | Nobody |

Under `--policy reverse` (the firm's method of reversing what isn't booked), 2B bills not in books and supplier credit notes are left for deemed acceptance. Bills where the supplier reported more tax are accepted with the books amount claimed and the excess reversed in 4(B)(2). Bills found in an earlier 2B are reclaimed.

The policies live in `recommend.py` and the thresholds in `config.py`, so a firm can change them.

## Accuracy so far

### On a real CA firm's month (Jun 2026, client anonymised as "XYZ Ltd")

A CA firm shared its working file for one client: a 537-line Tally journal register, the firm's 1,099-row flattened 2B, and its own GSTR-3B Table 4 working. Some rows had the firm's own **Remark** (Matched / Not in Books / Matched-Ineligible ITC / Booked with non-GST) and ITC-eligibility marks, and these were used as the answer key. The file is confidential and is not in this repo.

| | Before this round | Now |
|---|---|---|
| Books rows read | 477 of 537 (60 dropped without a note: blank GSTIN or invoice no., some carrying ₹10 lakh+ IGST each) | 537 of 537 |
| The firm's 88 matched pairs found | 84 | **88**, plus 2 more pairs the firm's VLOOKUP missed (a one-digit typo, and a purchase return with no number). Both are held for a CA check |
| Matched as exact (invoice date read from the narration) | 1 (67 shown as "date differs") | 70 |
| Bills the firm marked "booked with non-GST" | missed | 3 of 3 caught as *Booked without GST* |
| Firm says ITC ineligible → TwoB flags it | | 115 of 116 |
| Firm says eligible → TwoB still flags it | | 58 of 274 (car-lease rentals, which TwoB reads as blocked under Sec 17(5); hotel bills to split; works contracts marked *Possible*) |
| Speed | 0.4 s | about 1 s |

On this file, TwoB's proposed 4(B)(1) reversal covers the same items the firm marked ineligible (precast drains for the new plant, cab hire). It adds ₹1.44 lakh of car-lease rentals that the firm's sheet treats as eligible, which is worth a CA's look.

The file also showed something synthetic data never would. 58% of the 2B records come from 177 suppliers who never appear in this register (airlines, hotels, car hire): the register is partial. TwoB now says so, does not recommend mass rejection, and lets staff decide those suppliers one at a time on the "By supplier" sheet. The 1,500 open items come down to about 430 supplier-level decisions.

### Realistic generated data (`test_data/`, `taxmind/synth_ca.py`, `taxmind/bench_ca.py`)

This data has six client profiles (plant-building manufacturer, trader, hotel, works contractor, car dealer, multi-GSTIN professional firm). Each has four months of 2B (Apr-Jul) in the firm's layout plus JSON, the books in xlsx and CSV, a combined workbook, a vendor master, and an answer key covering every row and the Table 4 figures. It copies the *patterns* of the real file, never its names. Run it with `python -c "from taxmind.bench_ca import run; run('test_data')"`. Each client is run with its line of business, the firm's `reverse` method and the vendor master:

| | Engine before this round | Now |
|---|---|---|
| Graded cases right (3,618 across 37 case types) | 53.0% | **99.8%** |
| Books rows dropped by the loader | 255 | 0 |
| Pair recall / precision | 89-94% / 100% | 99.4-100% / 100% |
| ITC to claim vs answer key (all six clients, ₹9.89 cr) | ₹5.08 cr | within ₹4,000 per client |
| Net ITC 4(C) vs the firm's method | not computed | within 0.25% for five clients (manufacturer ₹1,81,84,083 vs ₹1,81,83,886); 1.9% for the multi-GSTIN firm (blocked-credit calls on out-of-state hotels) |
| Sec 17(5) recall / false flags on allowed look-alikes | 79-99% / up to 63% | 100% / 0% |

Caveats:
- The answer key reflects one firm's method and our reading of the law. The listed judgement calls are in `test_data/README.md`.
- The engine was fixed against this data, so it is **no longer a blind test**.
- The 4(A)(5) and 4(B)(2) lines differ from the key, because TwoB takes records held Pending out of 2B rather than reversing them; the net 4(C) agrees.
- Stress set (4,760 books rows, ~5,300 2B rows a month): it takes 8 s and pairs at 99.8% precision / 99.5% recall. Split invoices are under-found at that size (`split_max_candidates`).

### Original synthetic data (`taxmind/synth.py`)

These figures come from synthetic data generated with known answers. The data includes a "hard" mode with heavy mismatch rates, recurring same-amount bills and plain-numbered invoices. They still hold after this round: 16 generated months gave 5,597 of 5,597 cases right, 0 wrong pairings, and 438 of 438 blocked items flagged with 0 false flags.

- **30 generated months (15 normal, 15 hard), each run with Excel and with Tally XML books: 20,998 cases, all correct, 0 wrong pairings.**
- **The default sample:**
  - A Tally-style exact matcher (ignore zeros and special characters, amount tolerance) leaves **113 items unexplained**.
  - The engine clears **258 of 343** decisions automatically.
  - The other 85 each come with a reason and an owner: 16 need a quick check by the CA, 42 need the client or a supplier, 24 are possible blocked credit to review, and 3 are housekeeping.
- **Blocked credit:** on the generated data, 1,622 of 1,622 planted Sec 17(5) items were flagged with 0 false flags. This only shows the plumbing works: the generator uses ledger names the rules were written for.
- **Blocked credit, blind tests:** an agent that never saw the code wrote realistic Tally/Busy ledger names, narrations, HSN/SAC and suppliers, labelled by Sec 17(5) category, with many look-alikes that are allowed.
  - First set (150 rows): the rules caught 81% of blocked items and wrongly flagged 17% of allowed ones. The rules were then fixed (resale and statutory exceptions, room-only hotel bills, repairs vs construction, short names like "Vehicle Exp"), which gives 97% / 0% on that set, but that set is no longer blind.
  - **Second, fresh set (150 rows, 28% with ledger and supplier only), scored once after all fixes: 84% caught (56 of 67), 16% false flags (13 of 83).** Most false flags are businesses where the block doesn't apply because they supply the same thing onward: a restaurant buying meat, a works contractor buying cement, a car dealer's demo cars. The per-client "line of business" setting (see Client settings) now removes these.
- **Speed:**
  - A 4,000-invoice client takes under 2 seconds (0.5 s on the build machine).
  - A worst case of 3,000 invoices from one supplier, with only 3 distinct amounts, takes about 18 seconds.

An independent code review tried to break the engine with realistic edge cases. It found 15 issues, and all are fixed with regression tests in `tests/`:
- year-suffix invoice numbers
- amendments
- IMS credit notes
- ledger names
- negative rows
- Tally mailing names
- reverse charge in the DRC-01C check
- speed
- recurring amounts
- period formats

A second independent review targeted the real-file features. It found 12 bugs, all now fixed with regression tests in `tests/test_review_regressions.py`:
- a reclaim counted twice
- amendments and RCM in Table 4
- blocked credit landing in 4(B)(2)
- GSTINs filled from the wrong supplier
- PO / vehicle numbers read as invoice numbers
- hand-made sheets losing their dates

The tests (101) pass on Python 3.10 and 3.13.

Synthetic data reflects only the mismatch types we thought of. **Re-measure on more real client files** before these numbers go in a pitch.

## Known limitations and assumptions

- **IMS file layout is unverified.** The IMS reader is tolerant: it finds any record with a GSTIN and a document number, and takes the doc type from the section name (`b2bcn` means credit note). It has not yet seen a real IMS download.
- **GSTR-2B JSON layout** follows the public structure (`data.docdata.b2b[].inv[]`, `cdnr[].nt[]`, `b2ba`/`cdnra`). Check it against a real download.
- **Amendments** (`b2ba`/`cdnra`) of an earlier month change ITC only by the difference. Load that month's 2B as well; otherwise the effect is set to zero and flagged.
- **2B month:** for 2B Excel files, the month is read from the "Tax period" cell, the file name (`..._092026.xlsx`) or a firm's "Period" column ("June,2026"), never from the supplier's GSTR-1 period column. The file's own month beats the period typed for the run, so earlier and later months' 2B can be loaded together. If none is found, the typed period is used.
- **Recurring bills:** when a supplier bills the same amount 3 or more times in the month, an amount match is not treated as evidence. Look-alike numbers are held as Pending rather than accepted.
- **Not yet reconciled:** imports (IMPG/BoE), ISD and e-commerce sections are noted but not matched.
- **Tally XML:**
  - Tax ledgers are recognised by whole words (IGST/CGST/SGST/UTGST/Cess, "Integrated/Central/State Tax").
  - Names containing purchase, sales, charges, freight or expense are never treated as tax.
  - The party ledger is found from `ISPARTYLEDGER`, else by name, else as the line that balances the voucher.
  - Older exports without a GSTIN on the voucher are skipped, with a note.
- **Buyer-side notes:** a purchase return, debit-note voucher or negative row in the books is treated as the supplier's credit note.
- **Books from other months:** books entries dated after the period are matched, so a mis-keyed date still finds its bill. If they stay unmatched, they are left out as next month's bills. Earlier-month entries are kept and noted; when not in this 2B they become "Older bill" (likely in an earlier 2B) rather than a supplier chase. Load the earlier months' 2B, or last month's reversal ledger, to settle them.
- **Narration reading is a best guess.** Every number or date taken from a narration is noted on the record. When the Invoice No column and the narration disagree, the column wins.
- **GSTIN filling** never chooses between two candidates; ambiguous rows stay "GSTIN missing".
- **Table 4** is built from the recommendations. Rule 38/42/43 reversals, imports (4(A)(1)) and ISD (4(A)(4)) are not computed and must be added by the CA. Reverse charge is put in 4(A)(3) from the 2B RCM records and the books entries marked RCM (a narration saying "RCM" / "reverse charge" counts).
- **At scale**, split invoices are searched among the 18 nearest-dated bills per supplier, so very busy suppliers' splits can be missed.
- **Not yet implemented:**
  - pushing IMS actions to the portal (needs a GSP)
  - the 180-day payment rule (needs bank data)
  - splitting a hotel bill into room and food (needs the bill lines)

## Layout

```
server/taxmind_server/  web backend: FastAPI app (api.py), database (db.py), engine bridge (service.py), auth, demo
server/tests/           API tests
web/                    React + TypeScript front end (Vite)
docs/API.md             API contract between web/ and server/
Dockerfile, docker-compose.yml, scripts/run.sh
app.py                  Streamlit demo (reconciliation + Module 1 invoice reader)
extractor.py            Module 1: OCR / PDF field extraction (Tesseract + PyMuPDF)
taxmind/
  models.py             Doc, Finding, Status, Action ...
  gstin.py              GSTIN check digit, state names
  normalize.py          invoice-number keys, typo distance
  loaders/              portal_json, tabular (Excel/CSV), tally_xml
  matcher.py            scoring, one-to-one assignment, split invoices, duplicates
  recommend.py          decisions and reasons
  risk.py               pre-filing checks
  followup.py           supplier messages, client questions
  report.py             Excel + HTML
  blocked.py            Sec 17(5) blocked-credit flags
  closepack.py          month-close pack: final decisions, record, SHA-256 manifest, verify
  gstr3b.py             3B Table 4 working, ITC reversal ledger (reclaims)
  narration.py          invoice no. / date / credit note read from a books narration
  prepare.py            fill blank books GSTINs from PAN, invoice no. or supplier name
  engine.py             reconcile(), supplier roll-up
  synth.py, benchmark.py
  synth_ca.py, bench_ca.py   realistic CA-style test data (6 client profiles, 4 months) and its scorer
tests/                  pytest
sample_data/            generated sample month (fictional client)
test_data/              realistic generated datasets with answer keys (see test_data/README.md)
```
