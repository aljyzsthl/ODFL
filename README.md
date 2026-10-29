# OrderFlow

PO processing tool for the Samsung Electronics America home-appliance Order Desk.
Collects PO emails from Outlook, classifies them by customer, extracts Material Code · quantity ·
unit price from the attached PO PDFs, and produces the ERP Standard Order Upload spreadsheet.

> **Public repository checkout:** customer/domain masters, the ERP template,
> material-code reference data, machine settings, mail data, extraction caches
> and real PO documents are intentionally not committed. Obtain the approved
> private files for your environment and place them under `config\` and
> `CodeExtract\` before processing production orders. Never commit
> `config\settings.json` or customer documents.

**POs are read by the Claude API.** Each PDF attachment (and a DRM file's
recovered text) is sent to the **SEA private inference endpoint**
(`https://seadev-claude.sec.samsung.net:8081`, per the "SEA Claude API Guide")
and the ordered line items come back as JSON. **One attachment may hold several
POs** — each is read as its own order, with its own number, printed total,
delivery date and address, and every written row keeps the ones it was printed
on. Everything else - Outlook, the customer master, the ERP file - runs on the PC. **Master data still decides**: a
material code the Material Code list does not carry is set aside for a human and
never reaches ERP, so the model's output is a proposal, not an instruction. See
`docs/HANDOVER.md` chapter 4.

⚠️ **A purchase order leaves the PC on every extraction.** That is the trade
for not maintaining a 7,200-line local PDF engine (retired into
`CodeExtract/_legacy/`). Two things must be configured, both on the Settings
screen under **PO reading** — or via `$ANTHROPIC_BASE_URL` /
`$ANTHROPIC_AUTH_TOKEN`:

- **the endpoint** — defaults to the address above, so normally leave it blank;
- **the auth token** — the key you were assigned. It is sent as
  `Authorization: Bearer …`, not `x-api-key`. **No token is shipped with this
  code; it has to be pasted in once.**

**A customer is identified by the DOMAIN — nothing else is consulted.** The customer data
is **two tables**, both from the ERP file and both editable by hand:

- `config\domain_master.json` — the **domain table**, the file's second sheet
  (`SOLD_TO_NAME` → `DOMAIN`). **The domain is the identity**, and it lives here.
- `config\ship_to_master.json` — the **pair table**, the **Ship To Locations** export,
  one row per `(Sold-To code, Ship-To code)` pair.

The two are joined by the customer **name** at read time (exact spelling first, then
case/punctuation/legal-suffix-normalised, then as a last resort the `SOLD_TO_CODE`), so
editing either table on its own never orphans the other. One domain owns many pairs, so a
mail is matched by its sender's domain, and a domain the table does not carry stays
unclassified and is listed on the Unmatched Domains card with a **+ Add a domain row**
button. Two spellings of one domain (`abt.com`, `www.abt.com`, `@ABT.com`) are the same
domain — `norm_domain()` is the only comparison — and the more specific domain wins when
both are present (`sea.samsung.com` beats `samsung.com` for that mail). There are no member
rows, no chips and no customer card any more: the Customer Master screen shows **both**
tables, each an editable grid with a search box, paging, **+ Add row**, **Clear all** and
inline cell editing.
See `docs/HANDOVER.md` 6.2 and 6.2.1.

The full form fills **P/O No. (A)**, Sales Org. `3101` (C), **Distr. Channel** (D),
Division `00` (E), Sold-To (F), Ship-To (G), Material (H), Sales Quantity (I), the email's
received date as **P/O Date (M)**, **Ship-to Name (N)** and **Sold-to Name2 (AI)** from the
Ship-To master, the **Ship-To block typed per order** — Name 2/3/4 (O/P/Q), Address (R),
Street 2–5 (S/T/U/V), Postal Code (W), City (X) and Region/state (AZ, a drop-down) — plus
EDI1 condition value (BE) and its currency **`USD` (BF)**. All resolved by header name, so a
re-labelled form still lines up.

**The address is no longer copied from the master.** A PO's delivery address is routinely
not the account's billing site, so R/S–V/W/X are typed on the Inbox row (or the Quick
Convert card) instead of being inherited. Only **N** and **R** show on the row; the other
ten fields fold away behind a *More ship-to fields* disclosure.
**Three are fixed constants**: C, E and the BF currency. M is the email's received date.
**N, AI and D are filled from the composite key**
`(Sold-To, Ship-To)`, looked up in the Ship-To master — and **D is derived from that row's
`TYPE`: exactly `Builder` → `11`, everything else → `10`** (`Builder Others`, `Regionals`,
`BBY`, `Wayfair`, `Accrual` and a literal `NULL` are all 10). A pair the master does not
carry, or one listed twice with **different** details, leaves those cells **empty with a
line on the console** naming the pair rather than guessing. See `docs/HANDOVER.md` 6.7 and
6.7.1.

The output comes in two versions, ticked side by side on the Inbox and Quick
Convert screens (both can be on at once — one reading then writes one file per
version; the choice is remembered per machine): the full ERP form, or a plain
four-column sheet — `PO # · Material · Sales Quantity · Unit Price` — which needs no template. Because
one domain owns several pairs, Sold-To and Ship-To are **drop-downs** on both screens
(Ship-To narrowed by the chosen Sold-To), and the Ship-To choices show their channel.
See `docs/HANDOVER.md` 6.7.2 and 6.8.

The menu is a **floating island**: a dark blue gradient plate, detached from the window
edges, that sticks and scrolls with its own rounded frame while the tables scroll past.
The content area stays light. See `docs/HANDOVER.md` 3.2.1.

**Material Codes come from the Product Mapping Table.** Upload Samsung's mapping workbook on
Master Data > Material Codes and OrderFlow reads four of its columns by header name —
`FULL SKU` (A), `short skus` (B), `MatG` (D) and `MatG II` (E) — then groups the code tree by
**MATERIAL GROUP**. Because a PO prints the *short* SKU while ERP is keyed on the *FULL* SKU,
the table is also the **rewrite rule**: a code read as `RAF18DBB12` becomes `RA-F18DBB12/AA`
before it reaches the Order Upload. A short SKU that stands for **more than one** FULL SKU is
never guessed — it is left as printed and listed for a human. Customer price sheets still
upload unchanged. See `docs/HANDOVER.md` 4.15.

**Material Codes and Ship-To Locations can be exported** back out — **Export all** or
**Export what is listed** (for the grid, the rows the search box is showing). The exported
file is the twin of the upload template, so it re-imports with no edits; the template, the
export, the on-screen grid and the importers all read **one column definition**
(`DATA_SCHEMAS`), checked at start-up against the real importers. An empty list is an
**error, not an empty file**. See `docs/HANDOVER.md` 6.9.

## Documents
- **`docs/HANDOVER.md`** — architecture, folder layout, **the PO extraction pipeline in detail**, known weaknesses, how to verify. Developers start here.

## Developer run
```
pip install pywin32 openpyxl
run_dashboard.bat            # python src\orderflow.py → http://127.0.0.1:8766
```
If the corporate proxy blocks pip, run `set HTTP_PROXY=` and `set HTTPS_PROXY=` in the same console and retry.
Classic Outlook (LTSC) must be installed and already running.
PO reading additionally needs the **auth token** for the endpoint — paste it on the
Settings screen under **PO reading** (or set `$ANTHROPIC_AUTH_TOKEN`). Without one
every PO comes back with zero codes. Press **Test PO reading** there to confirm the
address, the token and the model before trusting a real order.

If a relaunch shows the **previous** interface, a leftover instance still owns the port
(8766): OrderFlow now says so on the console, prints the listener PID
(`taskkill /f /pid <pid>` closes it) and opens no window, instead of silently pointing
a new window at the old process. If the port is taken by some OTHER program, the
dashboard moves to the next free port automatically and says which one it picked.
See `docs\HANDOVER.md` 6.5.

**A scanned PO needs nothing installed.** It used to need a page rasteriser
(PyMuPDF or `pypdfium2`) *and* an OCR engine (RapidOCR, or Tesseract +
`pytesseract`), and a scan whose OCR lost the small digits came back with zero
codes and no error. The PDF now goes to the API as a document, so there is no
rasteriser, no OCR engine and no `install_ocr.bat` any more.

**A DRM-protected PO** (`<##` on disk, read for us by Acrobat or Word) is
handled the same way: a re-exported plain PDF is sent as a PDF, and a document
that could only be recovered as text is sent as text. One call, one set of
rules - the "two routes must agree" problem does not exist any more.

## Tests
```
python src\selftest.py                # every suite (po, lines, ui, excel, erp, bridge, sku,
                                       # classify, p0, p3, extract)
                                       # needs a writable TEMP: the suites build fixtures with mkdtemp()
python src\selftest.py classify       # or just one suite — customer identity by the domain in the master
python src\selftest.py sku            # the Product Mapping Table: short SKU → FULL SKU, material groups
python src\selftest.py extract        # PO reading: the accuracy gate, values as printed, the cache
python src\selftest.py p0             # the four P0 fixes: master atomicity, attachment index, ERP mark, mail source
python src\selftest.py p3             # the P3 residuals: duplicate kind, PO rule, corrections
python .workbuddy\port_probe.py       # port allocation: stale-instance refusal, foreign-port relocation

The `extract` suite runs offline: it drives the engine's post-processing with the
payload the API would have returned, so the gate, the "publish as printed" rule
and the cache are covered without a key and without a network call. The API
call itself is not covered by any automated test - verify it by converting a
real PO on the Quick Convert screen.
```
The other `.workbuddy\*_probe.py` scripts named in earlier revisions of this file
(`scan_probe`, `erp_column_probe`, `erp_format_probe`, `domain_probe`, `serve_probe`,
`upload_template_probe`, `export_probe`, `export_http_probe`, `export_wiring_probe`,
`sidebar_probe`, `column_probe`, `accuracy_probe`, `ui_preview`, `install_erp_template`)
are **not in this snapshot** — only `port_probe.py` shipped. Their coverage now lives in
`python src\selftest.py` (all 13 suites).

## Release
```
make_release.bat   # → ..\OrderFlow_src_<timestamp>.zip (source copy, no compiled exe)
```
Share the zip; colleagues run it the same way as under "Developer run" above.

## Folders
```
src\           dashboard (Python + a single HTML page)
               orderflow.py  entry point: settings, facades, wiring
               of_core.py    store, classifier, dedup
               of_outlook.py collector, housekeeping, win focus, scheduler
               of_master.py  material master, data schema, data export
               of_erp.py     ERP upload builder
               of_pdf.py     DRM pdf access, quick convert, extractor bridge
               of_server.py  dashboard HTTP API (port allocation lives here)
               report.py     the UI: one HTML+CSS+JS string
               selftest.py   regression suites
CodeExtract\   PO reading
               claude_engine.py  the extractor: PDF/text -> Claude API -> line items
               code_rules.py     what a material code IS and how spellings match
               claude_config.json  model, timeouts, size caps
               material_codes_reference.csv  mirror of Master Data > Material Codes
               data_upload\    real PO PDFs to try it on
               _legacy\        the retired local engine (7,193 lines) - not imported
config\        settings.json, ship_to_master.json, domain_master.json,
               material_master.json, erp_template.XLSX,
               unknown_dismissed.json (codes cleared from the "unknown codes
               found in POs" list - dismissing is not approving)
data\          runtime data (not shared); po_mail.db and the folders below it are
               recreated on start, so an empty data\ is a valid state
docs\          HANDOVER.md, SETUP.md, COLUMN_ALIGNMENT.md, DRM_meeting_notes.md
tools\         one-off dev scripts (domain-table migration, template generator,
               two-table HTTP check) — not shipped by make_release.bat
.workbuddy\    port_probe.py only (see HANDOVER 7 — the rest was removed)
```
`Upload_Template_MaterialCodes.xlsx`, `Upload_Template_ShipToLocations.xlsx` and
`Upload_Template_Domains.xlsx` at the root are the three fill-in templates (see
HANDOVER 6.9) — one per upload, mirroring the three schemas. ⚠️ Uploading the **blank**
pair or domain template **wipes that table** — an upload replaces it wholesale; the two
tables are separate files, so each is lost on its own.

## Layout history
**2026-10-23 (evening) — the flow is navigable, overrides moved to the preview,
and mailbox reading shows real progress.**

- **A finished step in the stepper is a button.** Clicking "Choose the email"
  (or pressing Enter on it) drops back to the list, so an order that arrives
  while another is being read does not have to wait. Nothing is saved or lost,
  and a reading still in flight is discarded rather than dragging you forward
  again.
- **The per-row address boxes are gone.** Ship-to Name / Name 2-4, the street
  lines, postal code, city, state and the two dates are now **typed on the
  preview page** (step 3), with the PO's own value shown as the placeholder — so
  what you are overriding stays visible. Blank means "use the document's".
- The Inbox table is down to **ten columns**: the PO # column and the two
  address columns left, their width going to Customer / Sender / Subject and to
  the Action column. The account dropdowns now show **the number only** (the
  type / channel / site name is on hover).
- The **output-format switch left the Inbox**; the file is chosen on step 3,
  next to the columns it will contain.
- Reading a mailbox now reports **real progress**: the page polls
  `/api/sync_state` and draws a ring when Outlook reports a count, three dots
  when it does not. Switching mailbox is **one request** (it was two, and the
  first one re-rendered the whole page against the old mailbox before the second
  had started), and the SQLite schema is applied once per process instead of on
  every request.

**2026-10-23 (later still 3) — one button look, and a bounded subject column.**

Every `.btn` (Download, Sync this date, Test connection, Save, Generate, the
pagers' buttons) now uses the "uiverse" tile the desk sent: white card, deep soft
shadow, lifts on hover and fills with a blue gradient, with the label's tooltip
sliding up above it. Two departures from the snippet, both because it is a card
rather than a button — no fixed 150×50 (the filter row carries four or five
buttons) and 12.5px type rather than 17px. The table's blue/red Extract/Discard
`.tbtn` keeps its own 3D-key look.

The tooltip is ONE shared element positioned in JS, not one per button: half of
these buttons sit inside a `.card`, and `.card` has `overflow:hidden` to round its
corners, which would slice the tooltip off at the edge.

**The Subject column was unbounded.** Its `<col>` carried `min-width:136px`,
which a `<col>` does not support — so under `table-layout:fixed` it was the only
AUTO column, and it absorbed every extra pixel of a maximised window (500px+)
while the rest stayed put. The columns are now percentages summing to 100, so the
table scales as a whole; Subject is 18% (≈215px at the floor, ≈287px on a
1600-wide screen).

**2026-10-23 (later still 2) — an "API not connected" badge, and a stepper fix.**

The Inbox and Quick Convert now carry a badge in the top corner while **no auth
token is stored**, because that is the one failure with no symptom: a PO comes
back with zero material codes and nothing raises, which looks exactly like a
parsing bug. Hover (or focus it — it is keyboard reachable) for the reason and
where to fix it; clicking opens Settings → API.

Stepper: a finished step used to swap its number for a tick, and the tick's CSS
escape went through Python's octal parser — the circle rendered a stray byte
plus "3", i.e. **"13"**. It now keeps its number and only turns green, and every
segment carries its own outline (a border cannot follow a `clip-path`, so the
outline is four 1px drop-shadows and the segments have a small gap).

**2026-10-23 (later still) — the preview became the third step's page.**

The preview is no longer a floating dialog: steps 2 and 3 of the stepper render
in the content column, replacing the list, so the page under the bar is the step
the bar names. That fixes the two things a dialog was hiding:

- **the delivery address and postal code were below the fold.** They were in the
  response all along; the box just ran past the bottom of the screen. The header
  block is now a two-column grid grouped Order / Delivery address / Dates.
- **the output-type choice is now the first thing on step 3** — two tiles that
  say what each file contains — instead of a row of buttons at the bottom of the
  dialog.

The address itself is also parsed more defensively: a model that returns
`zip` / `region` instead of `postal_code` / `state`, or flattens the address into
one string, used to produce an empty W and X with no warning. All of those
shapes now land in R-S-V / W / X / AZ, and a shape that really cannot be read
says so on the page.

**2026-10-23 (later) — two named buttons per row, and the mailbox is switchable
from the Inbox.**

The Inbox row had three ways to say "no" (a trash icon, a ✓ and a ✕). It now has
two buttons that say what they do: a **blue Extract** (opens the preview) and a
**red Discard** (moves the row to Discarded, where Rescue brings it back). The
styling follows the button the desk sent — thick bottom edge, brighten and lift
on hover, press down on click — rebuilt in plain CSS because this page has no
Tailwind build step. The `reject` action still exists on the server but no
longer has a button; Discard covers it.

Also fixed: **Save & Collect Now appeared to do nothing to the Inbox.** The
collect result was only applied when the server reported a latest date, and the
screen stayed on Settings either way — so a mailbox change looked like it had not
taken. Collecting is now one shared path (`runCollect`) that always lands on the
Inbox at the newest collected date and says when nothing was found. The Inbox
also has its own **mailbox dropdown** next to the filters, which saves the choice
and collects from it in one go.

**2026-10-23 — the Inbox became a four-step flow, and the page stopped
overflowing.**

`Confirm` now reads the PO first and previews what the columns will contain
(address, PO date, R.D.D — still not Material / Quantity / Unit Price, and not
the fixed constants), then asks which file to write, then writes it. A chevron
stepper across the top of the Inbox tracks it: choose the email → read the PO →
check & pick format → completed. The reading shows a radar sweep rather than a
progress bar, because the API answers once and there is no percentage to report.

Layout: the content column had `max-width:1400px` and, more importantly, no
`min-width:0` — a flex item defaults to `min-width:auto`, so the wide table
forced the whole layout past the viewport and the page scrolled sideways however
wide the window was. Both are fixed, the column widths are retuned (they used to
sum to more than the table's own floor), and the Inbox is paged at 12 rows with a
search box beside the customer filter and the date sort.

The menu is two levels (Inbox / Tools / Master Data / Insights / System), and
Settings is split into **API** (endpoint, token, and a model dropdown fed by the
models the endpoint actually serves) and **Email box** (mailbox, folder, the
collection rules). The refresh glyph on the System row clears every stored
preference — including the token — and keeps master data, mail and files.

**2026-10-22 (later) — Confirm shows a preview, and two account numbers were
being lost.**

`Confirm` is now two steps: it opens a preview of the columns and the preview's
own button generates. The preview covers the per-order columns only (P/O No.,
Sold-To, Ship-To, Distr. Channel, Ship-to Name/Address, the two dates) — the
fixed constants and the extracted Material / Quantity / Price are left out, the
latter because they do not exist until the extraction runs, and are reviewed
line by line on Quick Convert afterwards.

Fixed: **Sold-To and Ship-To were dropped from the Order Upload even when they
were on screen.** The Inbox pickers display a value the page derives from the
master and only save it when the user changes it, so a row that arrived with one
account on file showed both, saved neither, and Confirm built the file from an
empty row — leaving F, G and the Distribution Channel in D blank. Both codes now
travel with the Confirm request and are written down before the file is built.

Also: **Ship-to Name (N) is taken from the customer master only** — the PO's own
ship-to name is no longer used as a fallback.

**2026-10-22 — the PO's own address and dates, and two rule changes.**

The document now supplies the header as well as the line items: **P/O Date
(M)**, **R.D.D (K)** — the required delivery date, printed as "Required Date" /
"ETA Date" — and the **delivery address** (R, S-V, W, X, AZ). R.D.D defaults to
the PO date **+ 6 working days** when the document prints none, and says so.
All of them are still overridable per order; the precedence is one rule:
`typed on the row > what the PO printed > computed default`. Until today column
M was the *email's* received date, because nothing read the document's own date.

Three rule changes:

- **An unknown code is shown, not hidden.** It stays on the review list with its
  quantity and price, amber and unticked, and only reaches the Order Upload once
  a human ticks it. Before, it vanished from the screen and the operator had to
  diff the file against the PDF to find out what was missing.
- **A short SKU with several FULL SKUs now gets one chosen** (`/AC` never,
  `/AA` when offered, otherwise a fixed pick per short SKU — not `random`, so
  the same PO always reads the same). Before, those lines were dropped.
- **A code printed without its `/` is repaired** to the listed spelling:
  `DDW24M999UMDA` on the PO uploads as `DDW24M999UM/DA`.

"Unknown codes found in POs" also gained **Clear all**, which dismisses the list
without approving anything and without touching the extraction cache.

**2026-10-21 (later) — the endpoint is the SEA one, and it authenticates
differently.** The first cut of the API client aimed at `api.anthropic.com` with
`x-api-key`. The "SEA Claude API Guide" says otherwise: a private base URL
(`https://seadev-claude.sec.samsung.net:8081`) and
`Authorization: Bearer <token>`. Both are now settings
(`claude_engine.base_url()` / `auth_header()`), both are covered by the `extract`
suite — a wrong one of either produces a 401 on every PO and nothing in the UI
would have explained it — and both are testable from the Settings screen with
**Test PO reading**, which renders loading / success / failure in the same block
the Outlook test uses. The default model became `claude-sonnet-5`, which is the
one the guide offers; `claude-opus-5-5` from the first cut is not on its list.

**2026-10-21 — PO extraction moved to the Claude API.** `CodeExtract/engine.py`
(7,193 lines: OCR abstraction, page rasterising, word coordinates →
rows/columns/cells, the code matcher and ~3,100 lines of orchestration with four
fallback paths) was retired into `CodeExtract/_legacy/`, together with
`devtools.py` (3,163), `engine_audit.py`, `engine_baseline.py`,
`customer_templates.json` and the engine's `config.json`. `claude_engine.py`
(~520 lines, standard library only) replaces all of it. Two things were kept
on purpose: **the accuracy gate** (master data still decides which codes are
published - the model proposes, the Material Code list disposes) and **the rule
that values are published as printed and never repaired**. The matching rules
themselves survived as `code_rules.py`, because deciding what a code IS is a
master-data question, not a reading question. `src/of_core.py`'s TEXT RECORDS
section went with it: a PDF and a DRM document's recovered text now take one
route, so the "the two routes must read the same PO the same way" problem is
gone rather than fixed. `src/of_erp.py` lost its last PDF dependency with it:
`prepare_lines` used to re-open the PDF with pdfplumber to find the printed row
and could override the reader's unit price with a regex — Samsung's
`ME17R7021ES EA 85.00 199.00` made it publish the *quantity* as the price. It
now takes the printed line from the record and only recovers a value the reader
left empty. `requirements.txt` is down to **two packages** (`pywin32`,
`openpyxl`); pdfplumber, pymupdf, pypdfium2, pypdf, rapidocr and opencv are
gone, and `install_ocr.bat` with them.

**2026-09-26 — the engine and the UI were merged.** The dashboard's small modules were
concatenated, the four engine modules into `CodeExtract\engine.py`, and the five
`selftest_*.py` files into one `src\selftest.py` with sub-suites. No behaviour was
rewritten: each former module survives as a `# SECTION:` block, and `src\orderflow.py`
still publishes one same-named namespace object per section (`store.connect(...)`,
`material_master.load(...)`) so existing `module.function()` calls keep working.
See `docs\HANDOVER.md` §2.1 for the collision renames (`mm_*`, `ship_master.clear` →
`st_clear`, `pdf_access.status` → `pdf_status`, `quick_convert._num` → `qc_num`) and the
rule that a new module-level name inside a `# SECTION:` must be registered in that
section's `_bind((…))` tuple — `orderflow.py` raises at import time if it is not.

**2026-10-10 — the dashboard was split again**, into six cohesive modules, cut at the
SECTION boundaries with the code moved verbatim: `of_core.py` (store · classifier ·
dedup · text records), `of_outlook.py` (collector · housekeeping · win focus ·
scheduler), `of_master.py` (material master · data schema · data export / Ship-To
table), `of_erp.py` (ERP upload builder), `of_pdf.py` (DRM pdf access · quick convert ·
extractor bridge) and `of_server.py` (dashboard HTTP API). `orderflow.py` remains the
entry point: it imports the six, re-publishes their globals into one namespace, builds
the facades exactly as before and late-binds sibling names into each module.
`report.py` stays one file (a single HTML+CSS+JS string). The engine's
arithmetic cross-check (qty × price == amount derivation/repair) was removed
on purpose — values now pass through exactly as printed.

⚠️ **The facades kept the old module names alive, so `extractor_bridge.run_extractor(...)`,
`quick_convert.parse_excel_pos(...)` and `erp_excel.build_upload(...)` are still valid
calls** — but they are attributes of objects built in `src\orderflow.py`, not importable
files. There is no `src\extractor_bridge.py`, `src\quick_convert.py`, `src\erp_excel.py`,
`src\material_master.py`, `src\ship_master.py`, `src\pdf_access.py`, `src\text_records.py`
or `src\classifier.py` any more. Inside the tree the code lives in the `of_*.py` module
named above; write new code against those.
