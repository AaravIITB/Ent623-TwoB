# TaxMind: GSTR-2B / IMS reconciliation engine

TaxMind matches a client's purchase register against GSTR-2B / IMS and recommends **Accept / Reject / Pending** for every record. Each recommendation comes with a plain-English reason, the person who has to act (nobody, CA, client or supplier), and how much ITC is at stake.

It also runs pre-filing checks before GSTR-3B is filed, flags possible **Sec 17(5) blocked credit** on invoices that match perfectly, drafts WhatsApp/email messages for suppliers who need to fix something, writes an Excel workbook for the CA, and produces a dated **month-close pack** recording the CA's final decisions.

Built by team TwoB for ENT 623. The recommendations are defaults for a CA to review, not filing advice.

## Quick start

```bash
pip install -r requirements.txt

# the app (upload files, or click "Try with sample data")
streamlit run app.py

# command line
python -m taxmind sample --out sample_data            # make a synthetic month with known answers
python -m taxmind reconcile \
    --books  sample_data/purchase_register_092026.xlsx \
    --portal sample_data/gstr2b_092026.json sample_data/gstr2b_102026.json \
    --client "Sharma Auto Components" --out output
python -m taxmind reconcile ... --close-pack --preparer "Riya" --reviewer "CA Mehta" \
    [--decisions output/edited_workbook.xlsx]          # also write the month-close pack
python -m taxmind verify output/..._close_pack.zip --fingerprint <hash>   # check a pack later
python -m taxmind benchmark --data sample_data        # score against the known answers
python -m pytest -q                                   # tests
```

## Inputs

| Side | Formats read | Notes |
|---|---|---|
| Books (purchase register) | Excel/CSV export from Tally, Busy, Zoho or a hand-made sheet; Tally XML (Day Book) | Must include the **supplier's invoice number**. Tally's voucher no. matches poorly. |
| Portal | GSTR-2B JSON, GSTR-2B Excel, GSTR-2A JSON, IMS JSON/Excel | Load **this month and next month**, so late filers are explained rather than chased. |

Columns are recognised by name, the header row is found automatically, and tax split across rate-wise columns (e.g. "Input CGST 9%", "Input CGST 2.5%") is summed.

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
6. **Follow up** (`followup.py`): one message per supplier, written in the client's voice, plus a list of questions for the client.
7. **Blocked credit** (`blocked.py`): every decision is checked for likely Sec 17(5) items (see below).
8. **Report** (`report.py`): an Excel workbook (Summary, IMS decisions, Books not in 2B, Supplier follow-ups, Client questions, Blocked credit review, All findings) and a one-page HTML pre-filing report. The "All findings" sheet has blank **Final decision** and **CA note** columns for the CA to fill in.
9. **Month-close pack** (`closepack.py`): see below.

## Blocked credit (Sec 17(5))

A bill can match 2B exactly and still carry ITC the law blocks. GSTR-2B only marks place-of-supply and Sec 16(4) cases as "ITC not available", so nothing on the portal catches these. TaxMind flags them **for review** and never reverses ITC itself, because most blocks have exceptions (a caterer buying food to resell, a car dealer buying cars, insurance an employer must provide by law).

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
| Supplier reported more tax than books | Pending | Client checks books |
| Wrong tax head (IGST vs CGST/SGST) | Pending | Supplier amends |
| Supplier used another GSTIN (same PAN) | Pending | Client checks invoice |
| Same amounts, unrelated number | Pending (low) | CA checks |
| In 2B, not in books, known supplier | Pending | Client: received? |
| In 2B, not in books, unknown supplier | Reject (confirm) | Client |
| Supplier credit note not in books | Pending (one month max) | Client |
| In books, not in 2B | Don't claim this month | Supplier files |
| Found in a later 2B | Claim in that month | Nobody |
| Duplicate in books | Delete duplicate | CA |

The policies live in `recommend.py` and the thresholds in `config.py`, so a firm can change them.

## Accuracy so far

These figures come from synthetic data only, generated by `taxmind/synth.py` with known answers. The data includes a "hard" mode with heavy mismatch rates, recurring same-amount bills and plain-numbered invoices.

- **30 generated months (15 normal, 15 hard), each run with Excel and with Tally XML books: 20,998 cases, all correct, 0 wrong pairings.**
- **The default sample:**
  - A Tally-style exact matcher (ignore zeros and special characters, amount tolerance) leaves **113 items unexplained**.
  - The engine clears **258 of 343** decisions automatically.
  - The other 85 each come with a reason and an owner: 16 need a quick check by the CA, 42 need the client or a supplier, 24 are possible blocked credit to review, and 3 are housekeeping.
- **Blocked credit:** on the generated data, 1,622 of 1,622 planted Sec 17(5) items were flagged with 0 false flags. This only shows the plumbing works: the generator uses ledger names the rules were written for.
- **Blocked credit, blind tests:** an agent that never saw the code wrote realistic Tally/Busy ledger names, narrations, HSN/SAC and suppliers, labelled by Sec 17(5) category, with many look-alikes that are allowed.
  - First set (150 rows): the rules caught 81% of blocked items and wrongly flagged 17% of allowed ones. The rules were then fixed (resale and statutory exceptions, room-only hotel bills, repairs vs construction, short names like "Vehicle Exp"), which gives 97% / 0% on that set, but that set is no longer blind.
  - **Second, fresh set (150 rows, 28% with ledger and supplier only), scored once after all fixes: 84% caught (56 of 67), 16% false flags (13 of 83).** Most false flags are businesses where the block doesn't apply because they supply the same thing onward: a restaurant buying meat, a works contractor buying cement, a car dealer's demo cars. A per-client "line of business" setting would remove most of these and is the next improvement.
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

Synthetic data reflects only the mismatch types we thought of. **These numbers must be re-measured on real client files** before they go in a pitch.

## Known limitations and assumptions

- **IMS file layout is unverified.** The IMS reader is tolerant: it finds any record with a GSTIN and a document number, and takes the doc type from the section name (`b2bcn` means credit note). It has not yet seen a real IMS download.
- **GSTR-2B JSON layout** follows the public structure (`data.docdata.b2b[].inv[]`, `cdnr[].nt[]`, `b2ba`/`cdnra`). Check it against a real download.
- **Amendments** (`b2ba`/`cdnra`) of an earlier month change ITC only by the difference. Load that month's 2B as well; otherwise the effect is set to zero and flagged.
- **2B month:** for 2B Excel files, the month is read from the "Tax period" cell or the file name (`..._092026.xlsx`), never from the supplier's GSTR-1 period column. If neither is found, enter the period.
- **Recurring bills:** when a supplier bills the same amount 3 or more times in the month, an amount match is not treated as evidence. Look-alike numbers are held as Pending rather than accepted.
- **Not yet reconciled:** imports (IMPG/BoE), ISD and e-commerce sections are noted but not matched.
- **Tally XML:**
  - Tax ledgers are recognised by whole words (IGST/CGST/SGST/UTGST/Cess, "Integrated/Central/State Tax").
  - Names containing purchase, sales, charges, freight or expense are never treated as tax.
  - The party ledger is found from `ISPARTYLEDGER`, else by name, else as the line that balances the voucher.
  - Older exports without a GSTIN on the voucher are skipped, with a note.
- **Buyer-side notes:** a purchase return, debit-note voucher or negative row in the books is treated as the supplier's credit note.
- **Books from other months:** books entries dated after the period are matched, so a mis-keyed date still finds its bill. If they stay unmatched, they are left out as next month's bills. Earlier-month entries are kept and noted.
- **Not yet implemented:**
  - pushing IMS actions to the portal (needs a GSP)
  - the 180-day payment rule (needs bank data)
  - a cross-client dashboard
  - learning from past decisions
  - splitting a hotel bill into room and food (needs the bill lines)

## Layout

```
app.py                  Streamlit app (reconciliation + Module 1 invoice reader)
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
  engine.py             reconcile()
  synth.py, benchmark.py
tests/                  pytest
sample_data/            generated sample month (fictional client)
```
