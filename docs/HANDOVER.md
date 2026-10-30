# OrderFlow — Developer Handover

> Audience: a developer joining the project to **strengthen the logic that extracts Material Code,
> quantity and unit price from PO files**.
> Based on the source as of 2026-09-09. `file:line` references are valid for that snapshot and will
> drift as you edit.

---

## 1. What the program does

Samsung Electronics America's home-appliance Order Desk receives PO emails from 47 customers
(≤50/day, ~780/month) and keys them into ERP by hand. OrderFlow replaces that loop:

```
Outlook inbox ──▶ collect & classify by customer ──▶ extract code / qty / unit price from PO PDF
                                                          │
                     Standard Order Upload .xlsx ◀────────┘   (bulk ERP upload)
```

### Hard constraints — never break these
| Constraint | Why | What it means in code |
|---|---|---|
| ⚠️ **A PO leaves the PC to be read** (2026-10-21) | Customer orders are commercially sensitive, and the trade was made deliberately — see 4.0 principle 6 | The PDF goes to the Claude API. **Master data still decides which codes are published**; the key is a credential and is scrubbed from every release copy. Outlook, the masters and the ERP file stay local |
| Outlook access is **COM (pywin32)** only | Graph API not approved | Classic Outlook required; New Outlook has no COM |
| Corporate proxy blocks pip | Security | Prefer the standard library. Add dependencies deliberately |
| Users are US-based non-developers | | **All UI text in English**, run from source (`python src\orderflow.py`), minimal settings |
| **NASCA DRM** files cannot be read by Python | Corporate document security | Files starting `<## NASCA DRM FILE` are read through Excel/Outlook (authorised processes) |
| **A customer is the set of email domains that mail for it** | Identity follows the sender, not the person: one customer has many senders, many domains and many account numbers | `match_customer()` matches `norm_domain(sender)` only — no address lookup, no member rows. One domain ⇒ exactly one customer; ambiguity is reported, never guessed (6.2, 6.2.1) |

---

## 2. Folder layout

```
OrderFlow\
├─ src\                      dashboard (Python + one HTML page)
│   ├─ orderflow.py          entry point: settings, wiring, the namespace facades (2.1)
│   ├─ of_core.py            STORE · CLASSIFIER · DEDUP
│   ├─ of_outlook.py         COLLECTOR · HOUSEKEEPING · WIN FOCUS · SCHEDULER
│   ├─ of_master.py          MATERIAL MASTER · DATA SCHEMA · DATA EXPORT / Ship-To table
│   ├─ of_erp.py             ERP EXCEL — the Standard Order Upload builder
│   ├─ of_pdf.py             PDF ACCESS · QUICK CONVERT · EXTRACTOR BRIDGE
│   ├─ of_server.py          SERVER — the dashboard HTTP API
│   ├─ report.py             the whole UI. HTML+CSS+JS inside one Python string PAGE (see 3.3!)
│   ├─ selftest.py           all regression suites, one entry point   → python src\selftest.py [suite]
│   └─ version.py            build id, DERIVED from the source files (mtime + sha1) - nothing stamps it
├─ CodeExtract\              ★★ reading a purchase order (chapter 4)
│   ├─ claude_engine.py      ★ the extractor: PDF/text → Claude API → line items → gate → cache
│   ├─ code_rules.py         ★ what a material code IS and how spellings match (BackboneIndex)
│   ├─ claude_config.json    model, timeouts, size caps (no key — see 4.8)
│   ├─ material_codes_reference.csv  mirror of Master Data > Material Codes
│   ├─ data_cache\           one file per document: reading, review entries, md5 + config sig
│   ├─ data_upload\          real PO PDFs to try it on
│   └─ _legacy\              the retired 7,193-line local engine. NOT imported.
├─ config\
│   ├─ settings.default.json factory defaults, shipped in every release
│   ├─ settings.json         THIS machine's settings (outlook, sync, claude, port …).
│   │                        Written by the Settings screen; NOT shipped in a release,
│   │                        so an update cannot overwrite a configured machine (4.8.1)
│   ├─ ship_to_master.json   the PAIR table — one row per (Sold-To, Ship-To) pair,
│   │                        14 columns in the ERP file's own order (see 6.2)
│   ├─ domain_master.json    ★ the DOMAIN table — one row per customer name,
│   │                        SOLD_TO_NAME → DOMAIN. The identity lives here.
│   ├─ material_master.json  Material Code master, in the Product Mapping
│   │                        Table shape: {"codes": {normalised FULL SKU:
│   │                        {code, product, cate1, cate2}}, "sku_map":
│   │                        {normalised short: {short, full, group, group2}},
│   │                        "sku_conflicts": {…ambiguous shorts…}} (see 4.15)
│   └─ erp_template.XLSX     Standard Order Upload template (headers/format kept, data rows filled)
│                            the optional simple version needs no template — see 6.8
├─ data\                     runtime data (excluded from sharing): po_mail.db, attachments\YYYY-MM\, erp_upload\, export\, tmp\
├─ docs\HANDOVER.md          this document
├─ Upload_Template_MaterialCodes.xlsx     fill-in template for the Material Codes upload (see 6.9)
├─ Upload_Template_ShipToLocations.xlsx   fill-in template for the pair table (see 6.9)
├─ Upload_Template_Domains.xlsx           fill-in template for the domain table (see 6.9)
├─ make_release.bat          zip a source copy (no compiled .exe) → ..\OrderFlow_src_<timestamp>.zip
├─ prepare_handover.bat      strip one-off scripts / outputs before handing over the source (called by make_release.bat)
├─ tools\                    one-off dev scripts, NOT shipped by make_release
│                             split_domain_master.py   the one-table → two-table migration
│                             make_upload_templates.py regenerate the Upload_Template_*.xlsx from DATA_SCHEMAS
│                             check_two_table_master.py drive both tables over the real HTTP handler
└─ run_dashboard.bat         developer run (python src\orderflow.py)
```

★ = directly relevant to extraction work.

**The tree is PORTABLE — it can be moved or renamed without editing anything.**
`orderflow.BASE` is `dirname(dirname(abspath(__file__)))` (or the exe's folder
when frozen), and every other path in `config\settings.json` is relative to it
(`data/po_mail.db`, `data/attachments`). Nothing in `src\`, `CodeExtract\` or
`tools\` stores an absolute path — checked 2026-10-28 after the tree was copied
from `…\Documents\1021` to `…\Documents\1021 2\1021`: the only absolute paths
left were inside `CodeExtract\data_cache\index.json`, a manifest written by the
**retired** engine (nothing reads it), and those are relative now.

Two rules that keep it portable, and one that keeps it runnable on Windows:

- **Store paths relative to `BASE`.** `resolve_attachment()` re-roots an old
  `data/attachments/...` entry, which is why a database copied from another PC
  still opens its files.
- **`.bat` files are CRLF, everything else is LF.** `cmd.exe` mis-parses an
  LF-only `.bat` around labels and `goto`; Python and Markdown do not care, and
  an editor on either platform should keep them that way.
- A fresh machine needs `openpyxl` (+ `pywin32` on Windows) — see
  `requirements.txt` — and an auth token before any PO can be read (4.8.1).

### 2.1 The consolidation, and the six modules

The tree was consolidated on 2026-09-26 and the dashboard split again on
2026-10-10. Both passes moved code **verbatim** — no behaviour was rewritten.

| Former module | Now lives in | Note |
|---|---|---|
| `main.py`, `server.py` | `src/orderflow.py` (entry) + `src/of_server.py` (SERVER) | `orderflow.py` is the entry point and keeps the namespace facades; the HTTP API is `of_server.py` |
| `collector.py`, `scheduler.py`, `housekeeping.py`, `win_focus.py` | `src/of_outlook.py` | one module, four `# SECTION:` blocks |
| `store.py`, `classifier.py`, `dedup.py`, `text_records.py` | `src/of_core.py` | one module, four `# SECTION:` blocks |
| `material_master.py`, `ship_master.py` | `src/of_master.py` | MATERIAL MASTER / DATA SCHEMA / DATA EXPORT |
| `erp_excel.py` | `src/of_erp.py` | ERP EXCEL |
| `pdf_access.py`, `quick_convert.py`, `extractor_bridge.py` | `src/of_pdf.py` | PDF ACCESS / QUICK CONVERT / EXTRACTOR BRIDGE |
| `selftest_po/lines/ui/excel/bridge.py` | `src/selftest.py` | run one suite: `python src\selftest.py excel`; no argument runs all 13 · `erp` suite added 2026-09-30, rewritten 2026-10-07 for the Ship-To master (column fill **and** the full/simple output switch, 6.8) · `classify` suite added 2026-10-03 (domain-only customer identity; rewritten 2026-10-07 — 6.2/6.2.1) · `p0`, `p3`, `sku`, `extract`, `mailbox` added later · `multipo` added 2026-10-28 (one PDF can hold several POs, 4.7.1) |
| `extractor.py`, `code_matcher.py`, `table_parser.py`, `ocr_engine.py` | `CodeExtract/engine.py` | `from engine import extract_material_codes` |
| `selftest.py`, `template_editor.py`, `lang.py` | `CodeExtract/devtools.py` | one file, sub-commands: `python devtools.py` (tests, default) · `devtools.py template` |

⚠️ **`erp_accounts.py` was deleted** in the 2026-10-07 refactor (6.10.1). So were
`config\customer_master.csv` and `config\erp_accounts.json`.

**The names still work, but they are not files.** `src\orderflow.py` builds one
namespace object (`store`, `classifier`, `erp_excel`, `quick_convert`,
`extractor_bridge`, `pdf_access`, `material_master`, `ship_master`, …) per
former module, so `extractor_bridge.run_extractor(...)`
and `material_master.load(...)` keep resolving — but there is no
`src\extractor_bridge.py` to import or open. New code should call the section in
the `of_*.py` module above. A doc or comment that says "see
`src\extractor_bridge.py`" means "the EXTRACTOR BRIDGE section of
`src\of_pdf.py`".

Two consequences worth knowing:

- **Name collisions were renamed.** Where two modules defined the same name,
  the second one got a prefix — `material_master.load/save/upload` are now
  `mm_load/mm_save/mm_upload`, `ship_master.load/save` are `load/save` (it came
  second, so `material_master` took the prefix), `ship_master.clear` is
  **`st_clear`**, `pdf_access.status` is `pdf_status`, `quick_convert._num` is
  `qc_num`. Inside `orderflow.py` the facades hide this; only a script that
  imports the module directly and uses an old name has to be updated.
  ⚠️ **A new module-level name inside a SECTION must be added to that section's
  `_bind((…))` tuple**, or `ship_master.new_name(...)` raises `AttributeError` —
  and a name that already exists globally (like `clear`) silently takes over the
  *other* section's binding, which is how `st_clear` got its name.
  **This is now enforced**: after the facades are built, `orderflow.py` checks
  `_FACADE_MISSING` and raises at import time if a name did not resolve. The
  only entries allowed to be absent are the three that are absent by design
  (`erp_excel -> erp_excel`, `material_master -> material_master`, which the
  `setdefault` lines right below fill in, and `args`, which lives in a disabled
  `if __name__ == ...` block). Before this check the miss was collected into a
  list nobody read, so the first symptom was an `AttributeError` from inside a
  request handler — which is exactly how `store.order_attachments` went missing
  the first time it was added.
- **`config_signature()` invalidates the extraction cache on the right things.**
  Editing `CodeExtract/claude_engine.py`, `claude_config.json` or the
  material-code CSV changes the signature, so a cached reading taken under
  different rules can never be handed back.

- ~~**`CodeExtract\devtools.py` keeps the old module names alive internally.**~~
  The `verify_golden` section and its `vg` namespace were **removed on 2026-10-19**
  along with the rest of the golden-set scorer (4.11).

Also removed: the root `neutral` leftover, `data\webview` (Edge WebView2 cache),
`src\check_pdf.py`, `src\webview_probe.py`,
`CodeExtract\debug_po.*`, `CodeExtract\version_check.*`,
`CodeExtract\selftest.bat` / `verify_golden.bat` (both are now `devtools.bat`; the golden
scorer itself was deleted 2026-10-19),
and the empty `CodeExtract\master_list` / `offline_packages` folders.

### 2.2 The 2026-10-10 split and the cross-check removal

**The split.** `src\orderflow.py` is cut at its SECTION boundaries into six
modules, the code moved verbatim: `of_core.py` (STORE · CLASSIFIER · DEDUP),
`of_outlook.py` (COLLECTOR · HOUSEKEEPING · WIN FOCUS ·
SCHEDULER), `of_master.py` (MATERIAL MASTER · DATA SCHEMA · DATA EXPORT /
Ship-To table), `of_erp.py` (ERP EXCEL), `of_pdf.py` (PDF ACCESS · QUICK
CONVERT · EXTRACTOR BRIDGE) and `of_server.py` (SERVER). `orderflow.py` stays
the entry point: it imports the six, re-publishes their globals into one
namespace in the old concatenation order, builds the facades exactly as
before, then **late-binds** every facade name and the few bare cross-section
names (`classify`, `check_duplicate`, `collect`, `contract_ok`, `export_data`,
`is_cancellation`, `test_outlook`, `_hkey`) into each module. One import-time
cross reference survives as an explicit import: `of_server.py` reads
scheduler's `LOCK` (`SYNC_LOCK = of_outlook.LOCK`). `report.py` is unchanged —
a single HTML+CSS+JS string cannot be split meaningfully.

**The cross-check removal (by request).** The arithmetic machinery that
derived or "repaired" one of quantity / unit price / extended cost from the
other two (`qty × price == amount`) is gone from both sides:
`engine.reconcile_money`, `finalize_money`, `qty_from_money`,
`is_clipped_amount`, `_lost_leading_char`, `_money_line_score`'s arithmetic
branch, the pair-preference loop in `enrich_money_from_pages`, the arithmetic
signal in `_fused_reading_is_better`, `find_document_total_qty` /
`doc_total_qty`, and the src-side `erp_excel.reconcile` + `is_clipped_amount`
with their calls in `prepare_lines`. Values now pass through exactly as printed;
the convention "last two money tokens = price, amount" is the only rule, and
the `extract` suite asserts pass-through (`src\selftest.py`).

**Engine fixes kept from 4.10.** `_TOKEN` cap raised `{2,29} → {2,39}`
(30+ char codes no longer truncated); the unitless single-number fallback in
`parse_quantity` is capped by `MAX_BARE_QTY` (999), so a bare 4+ digit value
(UPC tail, serial) can no longer become the quantity; `_CONFUSE_MAP` folding
now keeps every folded code, and an ambiguous folded key (two listed codes
sharing one folded form) returns nothing instead of whichever registered
first; `repair_wrapped_codes` skips window lines that carry their own
backbone-confirmed code, so another item's qty/money cannot be attached;
`exclude_patterns` are honoured on every extraction path via one choke point
(`apply_exclusions`); line-path records carry a `source_line` field (the
printed row), so consumers no longer need to re-parse the PDF.

**Port allocation.** `serve()` no longer dies with "taskkill /f /im
python.exe" advice. Order: configured port free → bind; an OrderFlow instance
owns it (`looks_like_orderflow` HTTP probe) → refuse with the listener PID and
start nothing; another program owns it → move to the next free port
(`find_free_port`) and say so. Probe: `python .workbuddy\port_probe.py`.

---


## 3. Dashboard architecture (brief)

### 3.1 Data flow
```
collector.collect_outlook()      Items.Restrict(ReceivedTime ≥ lookback) → _to_record()
   │  message_id (PR_INTERNET_MESSAGE_ID), sender (SMTP-resolved), subject, attachments[], pdf_paths[]
   ▼
classifier.classify()            match_customer (domain of the sender only) + extract_po_number()
   ▼
dedup.check_duplicate()          same (customer, po_number) → is_duplicate; cancel/revision tags
   ▼
store.insert_mail()                mails table. Emails with ≥2 PDFs are shown as one order per attachment
                                 (per-attachment status/erp_file kept in the att_states JSON column)
   ▼
[user clicks Confirm]  server /api/action → extractor_bridge.run_extractor(paths, settings, master_values)
                                          → erp_excel.build_upload() → data/erp_upload/OrderUpload_<PO>_<ts>.xlsx
```

⚠️ The names in that diagram are **namespace facades built by `src\orderflow.py`**,
not files (2.1). `extractor_bridge` / `erp_excel` / `quick_convert` resolve to the
EXTRACTOR BRIDGE, ERP EXCEL and QUICK CONVERT sections of `src\of_pdf.py` and
`src\of_erp.py`.

`paths` here is every saved attachment (PDF or Excel - "pdf_paths" is a legacy
column name, it is not PDF-only). `run_extractor()` splits it internally:
PDFs go through the CodeExtract engine as before; Excel attachments go
through `quick_convert.parse_excel_pos()` - the same reader Quick Convert
uses, so a PO gives identical codes either way. Before this split existed,
`/api/action` filtered the attachment list to `.pdf` only, so a PO that
arrived as a spreadsheet was silently dropped: the mail still flipped to
"Done", but `run_extractor()` received an empty list and no Order Upload
file was ever produced. Any future attachment kind added here needs a branch
in both this filter and `run_extractor()`, or it will fail the same way.

### 3.2 Screens and where they live (report.py)

**The Inbox is three tabs — Inbox / Read / Output — and they ARE the pipeline**
(2026-10-28, 4.3a). One `ITAB` decides which is drawn; there is no step bar any
more. `Extract` on a row sends it to **Read** (radar, then the preview with the
format choice), `Generate` lands in **Output** with the file(s) on a banner.

| Screen | Render function | Notes |
|---|---|---|
| Inbox **tab 1** | `inboxList` | POs by date. Status (Not yet/Pending/Done/Rejected/Not a PO), attachment links, **Extract** / **Discard**. Carries the **customer multi-pick** (multi-select tick list), the **Sold-To / Ship-To drop-downs** in columns F/G (6.7.2) with the site's ZIP under the Ship-To one, and the **editable Address** box beside them (6.7.2). The Customer column holds the **domain**. The output format is chosen later, on the preview |
| Read **tab 2** | `readPanel` | the extraction-cache register (`/api/read_list`), one row per ORDER with its own Full/Simple switch and **Generate**. While a reading is open it is replaced by `readFlowPage()`: the radar, then the preview |
| Output **tab 3** | `renderCompleted` | **one screen for Completed and Order Upload** (they were the same rows seen from two ends): every confirmed PO of the day, its generated Order Upload file(s) (badged Full form / Simple) and its ERP status, with **Mark uploaded** / **Undo** in the row. `outBanner()` sits on top for the write that just happened |
| Discarded | `renderNotMyPO` | non-PO mail (`excluded=1`), with **Rescue** to put one back |
| **Quick Convert** | `renderQuick` | drop a PO file → code/qty/unit cost only → Order Upload; the same Full/Simple switch plus a Domain / Sold-To / Ship-To picker on the review card (only when Simple is not the only version — the simple sheet has no account columns) |
| Customer Master | `renderMaster` | the **upload card** (ERP Ship To Locations → rebuild the table) + the **editable grid** over `config\ship_to_master.json`: a search box, Prev/Next paging, Export split button, and one `<input>` per cell that saves on blur. Conflicting `(Sold-To, Ship-To)` rows are **red** with a legend under the table. **+ Add row**, **Re-match stored mail**, **Clear all**. Then the Unmatched Domains card. All 15 columns come from `DATA.schemas` via the dashboard's `ship_columns` — the grid and the upload template can never drift |
| Unmatched Domains | `renderUnmatchedSection` | mails no domain could claim, **grouped by domain** — one row per domain with its email count, an example sender and **+ Add a Ship-To row**, which adds the row and jumps to it (6.2.1) |
| Material Codes | `renderCodes` | upload (price sheet **or** Product Mapping Table) → code tree (MATERIAL GROUP > MATERIAL GROUP 2 > code). The mapping table also loads the short SKU → FULL SKU rewrite (4.15) |
| Settings | `renderSettings` | mail source, mailbox, lookback, sync schedule |

**Two screens were removed in 2026-10-15, and one renamed.**

- **Cold Feet is gone.** It was a view over `cancel_flag=1` (subjects matching
  `cancel_keywords`), and that flag *also* hid those mails from `today`, `history`,
  `unprocessed` and the report counts. Deleting the screen while leaving the flag would
  have made cancellation mail invisible with nowhere left to review it, so the flag **no
  longer hides anything** - the queries in `store.dashboard_data()` filter on `excluded`
  only. Cancellation mail now lands in the Inbox like any other mail.
  `is_cancellation()` and the `cancel_flag` column are **kept**: `check_duplicate()` still
  uses the keyword as a *reason* on a real re-receipt ("PO number received again —
  cancellation candidate"), which is independent of the screen and still useful.
  The `cancels` payload key is gone; nothing reads it.
- **"Not My PO" is now "Discarded"** - the nav button, the page title (`TITLES.notmypo`),
  the Inbox KPI card and the Reports breakdown column. The tab id stays `notmypo`, and the
  per-row status chip still reads "Not a PO", which is a different thing (the state of one
  mail, not the name of the list).
- **Completed and Order Upload are one screen.** They were always the same rows - a
  confirmed PO is "completed" when written and "uploaded" once keyed into ERP - split over
  two screens that each showed half the state. `renderCompleted()` now lists every
  `status='Done'` PO of the day with both halves in the row: `erpFileCell(m)` (the
  generated file, badged Full form / Simple, or *Extracting…*, or why it failed) and
  `erpMarkCell(m)` (**Mark uploaded** / uploaded + **Undo**). The `unprocessed` payload key
  and the `renderUnprocessed` / `unprocessedOrders` functions are gone.
  ⚠️ The old badge read a mail-level SQL count while the list was per **attachment**, so on
  a mail split into two orders it never reached zero; the merged screen and its badge both
  count `DATA.history.filter(m => m.status === 'Done')`, so that class of drift cannot come
  back.

### 3.2.1 The shell: the sidebar is a floating island
The app is a single light theme. The menu is the one deliberate exception — a dark
blue plate that is *detached from the window edges*:

- `.layout` is a flex row with a page gutter (`--isl-gut`, 16px) and a matching gap;
  `align-items:flex-start` so the island can stick while the content scrolls.
- `.sidebar` carries its own radius, elevation and a three-stop gradient
  (`--isl-1/2/3`), is `position:sticky` at the gutter, and is sized to
  `calc(100vh - gut*2)` with `overflow-y:auto` — so Settings and Sync stay reachable
  while a long table scrolls, instead of scrolling off with the page.
- The section headers were tightened (not the nav rows: those keep their 44px+ hit
  height) so the whole menu fits a 900px-tall window.

Two rules that are easy to break and hard to notice:

1. **Every island rule must be scoped with `.sidebar`.** An unscoped override
   repaints the light content area — tables, cards, buttons — and it only shows up
   visually, later.
2. **The plate is a gradient, so a colour has to be checked against every stop, not
   against one average swatch.** The muted tokens clear 4.5:1 at the dark top *and*
   at the lighter bottom; `#94a3b8` (the old `--muted`) does not — it lands at 4.0:1
   at the bottom of the ramp. `--danger` likewise measures 3.3:1 on the plate, which
   is why the sync error line uses `class="syncline err"` and an island-local red
   instead of an inline `color:var(--danger)`.

`tableSpace()` (which hides secondary table columns) reads the gutters back out of
the stylesheet with `getComputedStyle` rather than hard-coding `240 + 32`, so the
column hiding cannot drift away from `--isl-gut`.

Railed behaviour is unchanged: below 1400px (or when the user collapses it) the
island is `display:none` and the content takes the full width minus the gutter.

⚠️ **`.workbuddy\sidebar_probe.py` is not in this snapshot.** It used to render the page
and check that the tokens exist, that the ramp runs dark→lighter, every text/dot colour
against all three stops, that no island rule escaped its `.sidebar` scope, and that the
JS still measures the gutters rather than guessing them. The only thing left in the tree
is `python src\selftest.py ui` (3.3), which extracts the embedded script and runs
`node --check` — it proves the page parses, not that the contract holds. The contrast
check in particular has to be re-created before any restyle.

### 3.3 ⚠️ Whenever you touch report.py
The entire UI is inside a Python string, so **JavaScript `\'` and `\n` must be written `\\'` and `\\n`**.
A single missed backslash has taken the whole dashboard down twice.
After editing run `python src\selftest.py ui` — it extracts the script and runs `node --check`.

### 3.4 ⚠️ Whenever you touch the SERVER section
The four rules the HTTP handler keeps, all of them learned the hard way:

1. **Open the browser only after the bind succeeded.** `serve()` arms the opener after
   `ThreadingHTTPServer(...)` returned, never before. Binding first and opening second is
   the whole reason a second `run_dashboard.bat` no longer shows you the previous
   instance (6.5).
2. **Nothing is cacheable.** `_send()` adds `Cache-Control: no-store, must-revalidate` to
   every response — the page is rebuilt from `report.py` on each request and the JSON is
   live database state, so a cached copy is always wrong. A cached page after an update
   cannot be told apart from "the change did not work".
3. **Route on the path, not on `self.path`.** `do_GET` / `do_POST` strip the query string
   first. Every branch matches exactly, so `/?tab=today` (a bookmark, a tracking
   parameter) used to fall through all of them and answer a raw JSON 404 instead of the app.
4. **`allow_reuse_address = False` is deliberate** — it refuses a second instance on the
   same port instead of sharing it. The cost: a leftover process blocks the next launch,
   and the only fix is to end it (`netstat -ano | findstr 8766` → `taskkill /f /pid <pid>`).

⚠️ The probe that covered 1–3 (`.workbuddy\serve_probe.py`) is **not in this snapshot**.
The surviving half of it is `python .workbuddy\port_probe.py`, which exercises the
mechanism itself — `port_in_use` / `find_free_port`, `looks_like_orderflow` telling a
real dashboard from a foreign server, and `serve()` refusing to shadow an
OrderFlow-owned port instead of opening a second window. Rules 2–4 are only covered by
`serve()`'s own code; re-create the probe before changing them.

---

## 4. ★★ Reading a purchase order (CodeExtract)

This chapter is the core of your work. Read it before the code, and keep it open while reading.

### 4.0 Why it is built this way — read before changing anything here

The rest of this chapter describes *how* a PO is read. This section is *why*,
because the mechanics are easy to read and the reasoning behind them is not.
These are design decisions taken deliberately by the project owner (Jacob Baek)
over the 2026 build, each one after a failure that cost something. Reverse them
only with a reason better than "this would be simpler".

**1. Extraction proposes, master data decides.**
A model that reads a code beautifully has not identified a model code — it has
produced a *candidate*. The authority is `BackboneIndex` over
`material_codes_reference.csv`: every candidate is looked up there, and anything
that fails is moved to `review` and dropped from `records`. This inversion —
reference data is the truth, the document and the model are the noisy signal —
is the difference between a demo and something an order desk can use. A code
that does not exist must never reach ERP.

> **This principle is what made the change safe.** Moving the reading to the
> Claude API did not weaken it: the model is now the thing that proposes, and
> the gate is untouched. A hallucinated model number is the easiest failure to
> imagine, and it is the one failure the gate makes impossible.

**2. Never invent a value.**
An ambiguous code base is left unresolved rather than extended to one of two
market variants. A line that does not balance is annotated, not silently
corrected. Escalating to a human is a success path. The metric that matters is
the false-accept rate, not the automation rate: a wrong quantity on an appliance
PO is a truckload delivered to the wrong place, freight both ways, and a
customer relationship. Optimise for zero bad orders first; automation follows
once the error rate is proven.

> ⚠️ **This principle is now enforced by doing less.** The arithmetic repairs
> that used to "complete" a clipped amount (`is_clipped_amount`,
> `reconcile_money`) were **removed on purpose** in 2026-10 (see 2.2): a value
> that is not printed is now left empty or passed through as printed, and the
> operator corrects it. The trade is deliberate — a derived price that is
> wrong is worse than a price that is visibly missing, and a missing price is
> caught before upload while a plausible wrong one is not. Do not reintroduce
> derivation without the owner's agreement.
> The API is instructed the same way (4.3, rules 3 and 7): it must leave a
> field empty rather than fill it in.

**3. Per-customer *data*, not per-customer *parsers*.**
This is the one principle whose mechanism changed. It used to mean
`customer_templates.json` — coordinate rectangles and a fingerprint, so adding
a customer was data, not code. It was tested against the alternative at the
time: a colleague's toolkit carrying one hand-written row regex per vendor was
reviewed in detail and its extraction core deliberately not adopted — eight
layouts would have covered eight of ~47 accounts, with every new customer
requiring a new parser.
The API supersedes the mechanism while keeping the principle: layout knowledge
is not in the code at all any more, so there are no zone boxes to draw, no
template editor and no per-customer branch anywhere.

**4. Every correction must be visible.**
`prepare_lines()` returns `fixes` — human-readable notes for every value the
system changed and why. A silent correction is indistinguishable from a bug.
The extraction engine adds its own `diagnostics` for the same reason, including
every line whose numbers do not balance (4.5). If you add a repair, add its note.

**5. The regression tests are the licence to refactor.**
`src\selftest.py` encodes bugs that actually shipped. Run it before and after
every change (4.11). The `extract` suite covers the gate, the "values as
printed" rule and the cache without calling the API, so it runs offline and in
CI; the API call itself has no automated coverage and is verified by converting
a real PO.

**6. ⚠️ A purchase order leaves the PC.**
Every extraction sends a customer's PO to Anthropic. That is a real change from
"runs 100% locally — nothing leaves the PC", and it was accepted deliberately:
the alternative was maintaining a 7,193-line local PDF engine whose accuracy
depended on which OCR engine happened to be installed on that machine.
Two consequences are permanent:
- **No PO can be read without a key and a network.** There is no offline
  fallback. The retired engine is in `CodeExtract/_legacy/` if that ever has
  to be revisited.
- **The key is a credential.** It is scrubbed from every release copy
  (`prepare_handover.bat`) and the Settings screen never sends it back to the
  page — only whether one is stored.

### 4.1 File map

| File | Lines | Role | Needed at dashboard runtime |
|---|---|---|---|
| **`claude_engine.py`** | ~520 | the extractor: document → API → line items → gate → cache. Entry points `extract_material_codes()` and `from_text()` | yes (called from `src\of_pdf.py`, sections QUICK CONVERT and EXTRACTOR BRIDGE) |
| **`code_rules.py`** | ~430 | what a material code IS and how two spellings match (`normalize`, `clean_code_cell`, `BackboneIndex`). The only part of the old engine that survived | yes |
| `claude_config.json` | | model, `max_tokens`, timeout, size caps | yes |
| `material_codes_reference.csv` | 7,256 | mirror of Master Data > Material Codes, rebuilt by `material_master.sync_to_engine()` on every dashboard start. Carries each FULL SKU **and** its unambiguous short SKUs (4.15) | yes |
| `data_cache/<stem>.json` | | one file per document: the reading, its `review` entries, and the md5 + config signature that decide whether it is still valid. `material_master.pending_reviews()` reads the `review` entries back out for the Code Learning screen | yes |
| `data_upload\*.pdf` | | real POs to try it on | no (test corpus) |
| `_legacy\` | 11,247 | the retired local engine. **Not imported by anything** — see its README | no |

### 4.2 Call graph (one page)

```
extract_material_codes(pdf_path, force=False, customer_name="", progress_callback=None)
│
├─ load_config / config_signature / file_md5
├─ cache check (data_cache/<stem>.json, md5 + config_signature)
│     NB: the dashboard always calls with force=True → cache bypassed in production   of_pdf.py:1669
│
├─ _pdf_blocks()      read the bytes, refuse anything that is not a PDF
│                     or bigger than claude_config.max_pdf_bytes
│
├─ _call()            POST /v1/messages, forced tool_choice -> JSON line items
│     system prompt : the nine rules + the forced tool schema (4.3)
│     retries       : 429 / 500 / 502 / 503 / 529, three attempts
│
└─ _finalise()
      ├─ _records_from()   payload -> records, _clean_num() on every figure
      ├─ apply_gate()      BackboneIndex decides which codes are published (4.4)
      ├─ dedupe_records()
      ├─ check_arithmetic()  qty x unit_price == amount, REPORTED not repaired (4.5)
      └─ save_cache()
```

`from_text(text, source)` is the same call with the document as a `<po_text>`
block instead of a PDF. It exists because a DRM-protected file can only be
recovered as text (`pdf_access` L4a/L4b). **It is not a second parser** — the
old engine needed one, and keeping two reading implementations in step was the
single most expensive maintenance problem in the project. Now there is one call,
one prompt and one gate, so the same PO reads the same either way by
construction.

### 4.3 The preset prompt, and why each rule is there

**Yes, a preset prompt is required — and it already exists.** Nothing about a
Messages API call says "return the ordered line items of a purchase order": the
model would happily summarise the document in prose. So the extraction is
pinned down twice, and both halves live in `claude_engine.py`:

1. **`_SYSTEM`** — the fourteen rules below, sent as the `system` field.
2. **`_TOOL`** — a JSON schema emitted by a **forced tool call**
   (`tool_choice`), so the reply is a structured payload or an error, never a
   paragraph. The reply is `orders[]`, one entry per PO in the document (4.7.1),
   each with `po_number`, `document_total`, `po_date`, `rdd`, `ship_to` and
   `lines[]` of `material_code / description / quantity / unit / unit_price /
   amount / po_line / page / source_line`.

Both halves are part of `config_signature()`, so editing either one invalidates
the cache by itself (4.6) — no manual version bump to forget.

The prompt is **not** customer-specific and should not become so. Everything
that differs between customers (which code is valid, how a short SKU maps to a
FULL SKU, which market suffix applies) is master data and is decided afterwards
by `apply_gate()` (4.4). Prompting per customer would put a second authority
next to the Material Code list, which is exactly the split this project spent
2026-10 removing.

Every rule exists because of a failure the local engine had; do not trim one
without knowing which.

| Rule | Prevents |
|---|---|
| 1. one `orders[]` entry per DISTINCT PO | four POs in one PDF published as one order under the first one's number (4.7.1) |
| 2. copy values exactly as printed | a reformatted amount changing the value |
| 3. never invent a value — empty beats plausible | a missing quantity being filled with something a human cannot distinguish from a real one (principle 2) |
| 4. skip subtotal / total / tax / freight rows | a summary row becoming an order line |
| 5. skip a model named inside another item's description | "…includes RF28R7201SR…" producing a phantom line — the bug class the old engine spent the most code on |
| 6. the identifier alone, no description words | `WF45B6300APPLATINUM` in the Material Code column |
| 7. one money figure → `unit_price`, `amount` empty, do not multiply | an invented extended amount |
| 8. `page` and `source_line` | a reading nobody can verify against the document |
| 9. `po_number` / `document_total` | no total to check the lines against (4.5) |
| 10. `po_date` and `rdd` are two different dates | a "required by" date being published as the order date (or the reverse), which moves a delivery promise |
| 11. `ship_to` is the DELIVERY address | the bill-to block or the seller's own address being shipped to |
| 12. per order: its own number, total, dates and address | one order's R.D.D and total applied to three others (4.7.1) |
| 13. a line belongs to the order whose header is nearest ABOVE it | a page continuing a table being read as a new order, or its lines landing in the next one |
| 14. the buyer block is letterhead, not an order | four entries per order because four addresses were printed |

Rules 12-14 were added 2026-10-28 with multi-PO support (4.7.1). Rules 10 and 11
were added 2026-10-22 with the header block. Both name the
labels they are looking for ("Required Date", "RDD", "ETA Date"; "Ship To",
"Deliver To", "Consignee") instead of leaving the model to guess which date and
which address block are meant, and both prefer an empty string to a guess — the
same rule 3 the line items follow.

The response is a **forced tool call** (`tool_choice`), not prose with JSON in
it. That is what makes the gate possible: the engine always gets a structured
payload, or an error — never a paragraph it has to parse.

### 4.3a Extract is two steps: read+preview, then generate (2026-10-22/23/28)

**The order of work is in the three Inbox tabs — there is no stepper any more.**

```
Inbox      the list, filters + search            → Extract on a row
Read       first the radar (one API call),       → pick the format, Generate
           then the preview: format at the top,
           then the columns the file will hold
Output     the file(s) on a banner, the row in the list below
```

**2026-10-28: the four-step bar is gone.** It drew the same journey a second
time, on top of the tabs that already describe it, and the two could disagree
(`1 Choose the email / 2 Read the PO / 3 Check & pick format / 4 Completed`
versus `Inbox / Read / Output`). The state is now just `ITAB`:

- `startReading(id, index)` sets `READING`, switches to `ITAB = 2` **before** the
  request, and renders. `readFlowPage()` is what the Read tab draws: the radar
  while `READING` is set, the preview once `PREVIEW` is, the register otherwise.
- `generateOrder()` writes the file(s), sets `LASTFILES`, switches to
  `ITAB = 3` and re-renders — `outBanner()` is drawn above the Output list, over
  the rows the order has just joined.
- `cancelReading()` (Cancel on either panel, and the ✕) bumps `PREVIEW_SEQ`,
  clears both states and renders: a slow `/api/order_preview` that lands after
  the user walked away is dropped, not shown.

**The preview is a PAGE, not a dialog** (2026-10-23). It owns the whole Read tab
while it is open, so the format tiles and the address block have the screen. The
old floating box was the reason the preview was reported as having no address: it
had one, four hundred pixels below the fold, together with the format buttons.
Concretely:

- **the format choice is the first thing on the page** (`.fmtpick`, two tiles
  with a description of what each file contains) - it is what that page is for;
- the header block is a **two-column grid** (`.pvpage`), grouped
  *Order / Delivery address / Dates*, so R, W, X and AZ are on screen without
  scrolling;
- empty continuation street lines (S-V) are **left out** instead of printed as
  "not printed on the PO" - they were pushing the real address down the page;
- a failed Generate leaves the user on the preview with `PREVIEW` intact, so they
  can press again instead of re-opening it.

The reading is `POST /api/order_preview`, which **reads the document**. It has
to: the delivery address and the two dates are printed on the PO, so a preview
that skipped the reading could not show the columns it exists to confirm.
Generate is `POST /api/action` with `force=False`, which finds that reading in
the cache and **does not call the API again** - the reading is paid for once, by
the preview.
`selftest.py extract` asserts both halves of that: `force=True` from the preview,
`force=False` from the generate.

`read_orders()` is the split: it returns `(results, msgs, ok)` and writes no
file; `run_extractor()` calls it and then builds. Both the mail path and Quick
Convert go through them, so there is still one reading implementation.

`Confirm` no longer builds the file on the click. It opens a **preview** of the
columns, and the preview's own button generates:

```
Confirm → POST /api/order_preview → dialog → "Generate Order Upload"
                                              → POST /api/action {action:'confirm'}
```

`act()` intercepts `action === 'confirm'` and calls `showPreview()`;
`generateOrder()` is the old body and is only reachable from the dialog.

**What the preview shows, and what it deliberately does not.** It lists only the
per-order columns: A P/O No., F Sold-To, G Ship-To, D Distr. Channel, N Ship-to
Name, R-S-V Address, W ZIP, X City, AZ Region, K R.D.D, M P/O Date. It omits

- the **fixed constants** (C Sales Org 3101, E Division 00, BF currency) — the
  same on every line, and noise in a confirmation;
- **H Material, I Quantity, BE Unit price** — they do not exist yet. They come
  from the extraction this button is about to start, and they are reviewed line
  by line on Quick Convert afterwards.

Each row carries where its value came from (`picked on this row` / `from the
customer master` / `from the PO` / `default: PO date + 6 working days`), and a
column with no value says WHY, in three different ways:

| state | what the cell says |
|---|---|
| the document was read and does not print it | `not printed on the PO` |
| the document could not be read at all | `the document could not be read` (+ a warning at the top) |
| not read yet | `read from the PO, else PO date + 6 working days` |
The letters are read off the real template (`column_map`), so AZ is AZ because
the form says so, not because this file guesses.

**The deliver-to block is parsed defensively** (`claude_engine._ship_block`,
2026-10-23). A model asked for `address_lines` / `postal_code` / `state` will
sometimes answer `address` / `zip` / `region`, or flatten the whole address into
one string. All three shapes now land in R-S-V / W / X / AZ:

| what came back | what happens |
|---|---|
| the documented object | used as-is |
| `zip` / `region` / `address` / `street` | recognised (synonyms, `_SHIP_KEYS`) |
| `address_lines` as a string | split on newlines |
| one string `"9 ONE-OFF WAY, NEWARK, NJ 07102"` | split, then the tail is read backwards into city / state / zip |
| city on the tail line of a list | popped out of the STREET columns into X |
| an unreadable shape | a diagnostic, not a silent empty block |

The tail parser (`_consume_tail`) works **from the end**, which is what makes
`[... , "NJ 07102"]` (city on the line before) distinguishable from
`[... , "NEWARK, NJ 07102"]` (city on the tail). Getting this wrong puts a city
in S (street 2), which is a real mistake on an ERP form.

`order_preview()` runs **no file write**, and no extraction of its own. That is the point:
it answers "is this the right party, channel and delivery block?" for free,
before an API call is spent.

**The account numbers now travel WITH the request, like the ship block.** This
is a bug fix, not a refactor: the Inbox pickers `<select>` a value the page
derives (`rowPick()` — the stored code if the domain still owns it, else the one
code the domain has), and `/api/update` only fires when the user CHANGES the
dropdown. A row that arrived with a single account on file therefore *showed*
F and G, saved nothing, and Confirm built the file from an empty mail row — so
F, G and the channel in D came out blank even though both accounts were on
screen. `rowSnapshot()` sends `sold_to` / `ship_to` with the action and
`_typed_party()` writes them down before the file is built, exactly as
`_typed_ship()` does for the address. `_typed_party()` returns only the keys the
request actually carried, so an omitted field cannot blank a stored account.

### 4.3a-2 Navigating the flow, and where an override is typed (2026-10-23)

**Leaving a reading is Cancel, the ✕, or another tab** (2026-10-28 - the
clickable stepper is gone, see 4.3a). Reading one PO is regularly interrupted by
another arriving, so the way out is always one click and writes nothing:
`cancelReading()` clears `READING` / `PREVIEW` and drops the user back on the
register. `PREVIEW_SEQ` is bumped on every open and every back-out, so a slow
`/api/order_preview` that lands afterwards is **dropped** instead of pushing the
user into a preview for the order they just walked away from.

⚠️ Clicking another tab does NOT cancel a reading in flight - it keeps running
and its preview is waiting when you come back to Read. Only `startReading()` on
a different row, or Cancel, supersedes it.

**The per-row Ship-To boxes are gone from the Inbox.** Name / Name 2-4, the
street lines, postal code, city, state and the two dates are inputs **on the
preview page**, bound to `PREVIEW.typed`:

| | |
|---|---|
| box value | what you typed (`PREVIEW.typed[field]`) |
| placeholder | what the PO printed (or the computed default for R.D.D) |
| blank box | falls back to the document - `pvShip()` deletes the key |
| what Generate sends | `body.ship = PREVIEW.typed` (not the row) |

Typing does **not** re-render: the page would be rebuilt per keystroke and the
caret would jump. `previewPanel()` reads the current value when it next renders.

The five `rowShip` / `shipFieldInput` / `shipNameCell` / `shipAddrCell` /
`refreshShipName` functions were deleted with the cells - `of_server._typed_ship`
still accepts the keys, which is how the preview's values reach the file.

### 4.3b "API not connected", and what a missing token really does

`renderApiWarn()` puts a badge in the page head of **Inbox** and **Quick
Convert** while `settings.claude.key_set` is false. The value comes from the
server, computed exactly as the reader resolves the token, so the badge cannot
disagree with whether a PO would be read. Hover or focus shows the reason and
the fix; clicking opens Settings → API.

On 2026-10-23 a session was spent looking for a preview bug that was really a
missing token, so this is worth stating plainly rather than in a footnote:

**No token → every PO returns zero material codes and nothing raises.** There is
no exception, no red text, no failed request in the log. The preview simply has
nothing to show, and it reads as "the reader is broken".

⚠️ **Do not write a CSS escape in `PAGE`.** `PAGE` in `report.py` is a normal,
non-raw Python string, so `content:"\2713"` is parsed by PYTHON first: `\271`
is an octal escape (byte 185) and the `3` is literal, so the page receives a
stray character plus "3". That is what turned the finished stepper's circle into
**"13"**. Write the character itself, or an HTML entity. `selftest.py ui`
asserts the stray byte never comes back.

### 4.3c Buttons, and the Inbox table's column rules (2026-10-23)

**The Inbox table is ten columns**: Status, Received, Customer, Sender, Subject,
Attachments, Role, Sold-To, Ship-To, Actions. The **PO #** column went (the
number is in the subject, the row tooltip and the preview), and so did the
**Ship-to Name / Ship-to Address** columns now that those are typed on the
preview. Their share of the width went to Customer (12%), Sender (13%), Subject
(23.5%) and Actions (12.5% - it has to hold two buttons, ~150px at the floor).

The account `<select>` shows **the number only**. It used to append the type /
channel / site name, which in a 90px cell was ellipsised anyway - the user read
"1000006 · 10 · Buil…". The detail moved to the option's `title`.

**The output-format switch is no longer in the Inbox filter bar.** It is on step
3 of the flow, next to the columns it decides, which is the moment the choice is
being made. Quick Convert keeps its own.

### 4.3c-2 Collecting with a real progress indicator (2026-10-23)

`/api/collect` used to be awaited by the page: the request was in flight for as
long as Outlook took, and the only feedback was a toast that never changed. Now:

```
inboxMailbox(v) -> runCollect({body:{mailbox:v}})
                 -> POST /api/collect (mailbox saved and read in ONE request)
                 -> while it runs: GET /api/sync_state every 350ms
                 -> overlay: ring at done/total, or three dots when total is 0
```

- `collect_outlook(..., progress=cb)` calls `cb(done, total, phase)` every 5
  items. `total` is Outlook's own restricted count, and **0 when the store will
  not report one** - which is exactly when the dots show. No invented
  percentage.
- `_progress()` in `of_server` writes those into `SYNC`; `/api/sync_state`
  publishes it.
- The mailbox is saved **inside** the collect request (`body.mailbox`), so
  switching is one round trip. As two, the page re-rendered the whole table
  against the old mailbox before the collect had started - most of what made it
  feel slow.
- `store.connect()` applies the SQLite schema **once per process** instead of on
  every call. It is called once per HTTP request, so the DDL, the PRAGMA and a
  dozen conditional `ALTER`s were being re-run dozens of times per page view.
  Deleting `data\po_mail.db` while the app runs now needs a restart to be
  picked up.

### 4.3c-3 Buttons, and the table's column rules (earlier same day)

**All `.btn` share the "uiverse" look**: white card, `0 10px 10px` shadow,
`border-radius:10px`, hover → `linear-gradient(320deg,#034d92,#003cff)` + a 1px
lift, active → press down. `.btn.primary` carries the gradient at rest;
`.btn.danger` turns red on hover. **`.tbtn` is separate on purpose** — the blue
Extract / red Discard in the table keep their 3D-key style.

The hover tooltip is one shared `#.btntip` element positioned from
`getBoundingClientRect()`, not a child of each button. Reason: `.card` uses
`overflow:hidden` for its rounded corners, so a nested tooltip is clipped on
every button inside a card — which is most of them. `initBtnTips()` moves each
`title` into `data-tip` (and to `aria-label`), and `showBtnTip()` adopts a `title`
from a button injected later, so nothing shows two tooltips.

**The table's columns are percentages summing to 100.** They were pixels with the
Subject column left `auto`, which under `table-layout:fixed` means "take whatever
is left". On a maximised window that made Subject the only column that grew — it
reached 500px+, with every other column frozen at its minimum. Percentages scale
the table as a whole. What is still true: `table.fixed { min-width:1198px }` is a
floor for the editable Ship-To inputs, and below it the cardbody scrolls.

⚠️ **A floor that is larger than the card is a silent crop, not a scrollbar you
notice** (2026-10-27). The Completed / Order Upload table carried its own
`min-width:1320px` while the content column is ~930px on a 1600-wide display, so
its last column — the ERP buttons — sat against the card edge and wrapped into a
column half its width. A **text-only** table has no inputs to protect and can use
a lower floor: that one is `min-width:920px` now, with the percentages re-cut
against the longest value each column actually holds (Status 6 / Received 7 /
Customer 9 / Sender 9 / Subject 20 / Attachments 8 / PO# 7 / Upload File 21 /
ERP 13). Anything that holds a control keeps the 1198 floor.

⚠️ A `<col>` only honours `width`. `min-width` / `max-width` there do nothing,
and a column with no `width` becomes the flexible one. That is the whole bug.

### 4.4 The gate — master data decides what is PUBLISHED

`apply_gate()` runs on every record before anything is published. **Since
2026-10-22 it no longer decides what is SHOWN.** The distinction is the whole
rule:

| | confirmed code | code the list does not carry |
|---|---|---|
| in `records` (on screen) | yes | **yes** — with its quantity and price |
| flagged | `match_type` = exact/variant/... | `needs_review` = True + `review_reason` |
| `include` from `prepare_lines` | True | **False** |
| written to the Order Upload | yes | **only after a human ticks it** |
| on the Code Learning card | — | yes, still offered for approval |

- The candidate is looked up in `BackboneIndex` (9 stages: exact → market
  suffix → `BASE/MARKET` → base-only → suffix cut → prefix growth → category
  prefix → glued description word → OCR character confusion).
- Confirmed → `backbone_code` set, `material_code` set to `printed_form()`,
  published.
- Not confirmed → **kept in `records`, flagged**, and also listed in `review`
  with the reason. It is visible so nothing silently disappears; it is not
  published, so a wrong model still cannot reach ERP on its own.
- No code printed at all → same treatment, reason "no material code printed".
- The list is missing on this machine → publish as read, with a diagnostic
  saying so. Dropping every line of every PO is worse.

Why the change: an operator was looking at a PO, seeing nine lines in the file
and eleven on the document, and having to go back to the PDF to work out which
two had vanished. Now the two are on screen, amber, unticked, with the reason.
The safety property is unchanged — the line still needs a human — but the human
can now see what they are deciding about.

#### 4.4a Exact SKU-prefix suffix completion

Before the Product Mapping Table's short-SKU rewrite, `normalise_to_master()`
now checks the Material Code list itself for one stricter case: the PO code must
equal, character-for-character (case aside), the complete text before a known
suffix. For example, `RF23CB9900QK` resolves to `RF23CB9900QKAA` when that is
the only FULL SKU with the literal base; the same rule covers slash forms such
as `/A3`. It does not strip arbitrary characters or grow prefixes.

This rule deliberately bypasses `sku_map`, so a missing or stale short-SKU row
cannot block the exact data-backed repair. If more than one FULL SKU has the
same literal base, this new rule does not choose between them. A successful
repair is included automatically because the result is an exact Material Code,
but carries `suffix_autofilled`, `suffix_original`, and
`normalisation_warning` through `prepare_lines()` to Quick Convert. The row and
its summary note stay amber with **suffix added — verify**, satisfying the rule
that every correction must be visible.

Confirm (the mail path) has no per-line checkbox, so there a flagged line is
shown in the message and **left out** of the file: "3 line(s) NOT written —
their code is not in the Material Code list: …". Quick Convert is where you
tick one in, and ticking is what writes it.

`'26'` must not resolve to the listed `'26A'`: PO 25407327's line read
"… Apr 18th, 26", and the old engine had to be taught that a bare digit is a
date, not a model. `MIN_SHORT_PREFIX_LEN` still enforces it.

### 4.4a Short SKU → FULL SKU, and the two automatic repairs (2026-10-22)

**One short SKU, several FULL SKUs: one is chosen.** `of_master._pick_full()`,
in this order:

1. **`/AC` is never chosen.** That variant is not sellable on this desk's
   flows, so picking it produces a code ERP rejects or books against the wrong
   SKU. It is removed from the pool first.
2. **`/AA` wins when it is in the pool** — manual POs are only ever placed on
   /AA, so it is the correct answer rather than a lucky one.
3. **Otherwise a stable pick per short SKU** (md5 of the short code), not
   `random.choice()`. It still spreads across the candidates, but the same
   short SKU always resolves to the same FULL SKU — a real random pick would
   flip the model on every re-read of the same PO, which breaks the cache and
   makes "why did it change?" unanswerable. The alternatives are kept on the
   mapping row (`alternatives`, `pick_note`).
4. A short SKU whose candidates are ALL `/AC` is left unresolved and goes to
   `sku_conflicts` for a human.

**A code printed without its `/` is repaired.** `BackboneIndex.printed_form()`
publishes the LISTED spelling when the token matches the listed code with the
separators dropped: a PO printing `DDW24M999UMDA` while the list carries
`DDW24M999UM/DA` now uploads `DDW24M999UM/DA`. It used to keep the document's
spelling, which is exactly the code that then failed to match in ERP. A token
that is only the BASE (`DVE45T6000W` for `DVE45T6000W/A3`) still keeps the
document's spelling — it is shorter, not wrong.

### 4.5 Values as printed; arithmetic reported

Numbers are published exactly as the document prints them, minus the currency
mark and the thousands separator (`_clean_num`) — `1060.0000` stays
`1060.0000`. Nothing past the decimal point is ever touched.

`qty × unit_price == amount` needs no reference data and catches a large share
of misread rows, so `check_arithmetic()` runs it with a tolerance of
`max(0.02, 0.2% of amount)` — a scan loses a trailing zero, and the API is no
different. It also compares the lines' sum against the printed
`document_total`, which is what catches a whole line having been missed.

**It only ever reports.** Both figures go into `diagnostics` and both stay in
the record as printed. This is 4.0 principle 2 and the 2.2 decision, and it is
the easiest thing in the codebase to "improve" by mistake. Don't.

**Displayed to two decimals, stored as read (2026-10-27).** Column BE (the unit
price) and the Simple sheet's Unit Price cell carry the number format
`#,##0.00`. That is a FORMAT, never a round: `write_line()` still writes the
value `_num()` produced, so a whole-dollar contract price stays `1532` in the
cell and reads as `1,532.00`, and a three-decimal price keeps all three
(`selftest.py erp` asserts both halves). Under the template's own General
format a price printed `1198` looked like a different number next to the PO.

### 4.6 The cache

`data_cache/<stem>.json` holds the whole result dict. A re-read is skipped when
the document's md5 **and** `config_signature()` are unchanged — one API call per
document, not per click on Confirm.

`config_signature()` = md5 of **`claude_config.json` + the material-code CSV +
`_SYSTEM` + `_TOOL` + `prompt_version`**. It hashes the prompt and the tool
schema *by content*, not by a version number, because a version number is a
thing you forget: the first version of this function hashed only
`prompt_version`, so editing rule 2 ("never recalculate") left every cached
reading valid and the edit looked like it had done nothing. `selftest.py
extract` now asserts that touching either one moves the signature.

Note that both UI paths pass `force=True`, so in the dashboard the cache is
bypassed anyway — it exists for the `--force`-less script call and for the
`extract` suite, not as a speed-up on Confirm.

The dashboard always passes `force=True`, because Confirm is re-run precisely
when the master has just changed and the new master must be applied.

Two consumers depend on these files beyond caching:
- `material_master.pending_reviews()` reads the `review` entries for the Code
  Learning screen.
- `engine_audit.py`-style spot checks read `records` to compare a reading with
  the printed total.

### 4.7 Shape of the result dict (consumers must use `.get()`)
```python
{
  "source_file": str, "md5": str, "config_sig": str,
  "po_number": str,                             # the ONLY order's number; "" when the
                                                # document holds several (4.7.1)
  "po_numbers": [str],                          # every number, in reading order
  "order_count": int,                           # 1 for a normal document
  "customer": str,                              # the name passed in ("" possible)
  "extraction_mode": "claude",
  "records": [ {
      "material_code": str,      # the listed spelling when the gate confirmed it
      "backbone_code": str,      # what the list matched; "" when unconfirmed
      "description": str,        # the API's own description of the line
      "source_line": str,        # the row as printed - always present on this path
      "category": str, "quantity": str, "unit": str,
      "unit_price": str, "amount": str,         # strings, commas and $ removed
      "po_line": str, "page": int, "source_file": str,
      "po_number": str,          # the order THIS line was printed on
      "order_index": int,        # index into `orders[]`
      "match_type": str,         # "exact" | "variant" | "glued" | "unconfirmed"
      "needs_review": bool,      # True = shown, but not published until ticked (4.4)
      "review_reason": str,      # why, for the amber row on screen
      "extracted_at": str } ],

  # ── the header block: per ORDER, not per line (2026-10-22) ──────────────
  # EMPTY when `order_count > 1`: with four orders there is no "the" address
  # and no "the" R.D.D, and one order's value would be presented as if it
  # applied to all four. Read `orders[]` for those (4.7.1).
  "po_date": "YYYY-MM-DD",       # what the DOCUMENT printed in its header
  "rdd": "YYYY-MM-DD",           # required delivery date, or the default below
  "rdd_source": str,             # "read from the PO" | the default note
  "rdd_defaulted": bool,         # True = computed, not printed - say so on screen
  "ship_to_name": str,           # the DELIVERY site's name (not the account's)
  "ship_to_address": str,        # R
  "ship_to_street2": str,        # S
  "ship_to_street3": str,        # T
  "ship_to_street4": str,        # U
  "ship_to_street5": str,        # V
  "ship_to_city": str,           # X
  "ship_to_region": str,         # AZ (upper-cased, 2 letters)
  "ship_to_zip": str,            # W

  # ── one block per ORDER (2026-10-28) - see 4.7.1 ────────────────────────
  "orders": [ {
      "index": int,              # matches `records[].order_index`
      "po_number": str,          # this order's own number
      "document_total": str,     # THIS order's printed total, digits only
      "line_count": int, "review_count": int,
      "po_date", "rdd", "rdd_source", "rdd_defaulted",
      "ship_to_name", "ship_to_address", ... "ship_to_zip",   # as above
      "diagnostics": [str] } ],  # prefixed "PO <number>: " when there are several

  "review": [ {"candidate", "score", "match", "reason", "context", "page",
               "source_file", "po_number", "order_index"} ],
  "diagnostics": [str],                         # arithmetic mismatches, review counts
  "processed_at": str, "page_count": int,       # page_count is 0: never needed
  "stats": {"total", "reference_matched", "review_count", "backbone_size",
             "orders"},
  "error": str                                  # failure paths only
}
```
Keys added by the dashboard: `_pdf_path` (EXTRACTOR BRIDGE, `of_pdf.py`).

`source_line` and `po_line` are now **always** set, because every record comes
through the same call, and they are what `of_erp.prepare_lines()` falls back on
when the reader left a quantity or a price empty. It used to re-open the PDF
with pdfplumber to find that row; that is gone, which is why pdfplumber is no
longer a dependency of anything.

**The header block is how the three per-order values reach ERP:**

| Result key | ERP column | If the document prints nothing |
|---|---|---|
| `po_date` | M · P/O Date | the email's received date (last resort, was the only source before 2026-10-22) |
| `rdd` | K · R.D.D | PO date **+ 6 working days**, flagged `rdd_defaulted` |
| `ship_to_address` … `ship_to_zip` | R, S-V, W, X, AZ | the cell stays empty; the Ship-To master is never used for these |

Every one of them can be overridden per order — on the Inbox row behind **More
ship-to fields**, and on the Quick Convert card as two date boxes with the PO's
value as the placeholder. Precedence, one rule for all of them:

```
typed on the row  >  what the PO printed  >  computed default
```

R.D.D's default deliberately skips weekends and **does not model holidays**:
there is no calendar on this PC that knows a customer's shutdown week, and
inventing one would move a real delivery promise on a guess. It is a floor, and
`rdd_defaulted` is what lets the screen say so instead of presenting a computed
date as if the customer had printed it.

### 4.7.1 One attachment, several POs (2026-10-28)

Curacao mails four POs stapled into one PDF (`Curacao 4 PO's 5-12-26.pdf`:
ALRRY-A / ALRT2-A / ALRT5-A / ALRT8-A, one buyer, one ship-to, four delivery
dates). Until this change the reader treated a document AS an order, so all four
came back as one: the first order's number on every row of column A, the first
order's R.D.D on all hundred rows, and one merged total checked against each
order's own lines. **Nothing raised.** The file simply said the wrong thing on
three quarters of its rows — the worst shape a failure can take here.

The chain, in the order it runs:

| Step | Where | What it does |
|---|---|---|
| 1. read | `claude_engine._SYSTEM` / `_TOOL` | One `orders[]` entry per DISTINCT order number. A line belongs to the order whose header is nearest **above** it; a page printing no new header continues the order before it |
| 2. assemble | `claude_engine._finalise()` | One block per order (number, printed total, dates, address, its own lines). The gate and the arithmetic check run **per order**; records carry `order_index`; a diagnostic is prefixed `PO <number>: ` so it is attributable |
| 3. split | `of_pdf.expand_orders()` | A multi-order reading becomes **one result per order** before anything downstream looks at it, so six call sites keep their "one result = one order" assumption. A one-order document comes back as the very same object |
| 4. lines | `of_erp.prepare_lines()` | Each line carries its own `po` and the `order` block it came from |
| 5. write | `of_erp.build_upload()` / `build_upload_lines()` | Column A gets **that row's** P/O No.; K and M get that order's R.D.D and P/O date; the address block gets that order's address. `_fill_for()` builds a fill per order from a shared base, so order 2 cannot inherit order 1's street |
| 6. name | `of_erp._po_tag()` | `ALRRY-A_and3more` — a file holding four orders named after one of them is a file nobody finds later |

Why the split is in step 3 and not in the writer: `BackboneIndex` labels a line
with the order's number, `prepare_lines` stamps that number on the line, the
writer puts it in column A, and the address and the two dates are read once per
reading. Splitting once is one place to get right; teaching six call sites about
`orders` is six.

**Two traps that were real, not theoretical:**

* **Dedupe must be per order, not per document.** Curacao's four POs repeat the
  same 25 models on every page. `dedupe_records()` keeps
  `(po_number, code, qty, price, po_line, page)` as the identity — a
  document-wide key deleted three orders' worth of rows as "duplicates".
* **One fill per FILE is wrong once a file is several orders.** `build_upload()`
  used to build one `fill` dict and splat it over every row, which is correct
  only while a file is one order.

**What is deliberately still one value for the whole file:** the Sold-To /
Ship-To codes and the Distribution Channel (they come from the master row the
operator picked), and any ship-to field TYPED on the Inbox row or the Quick
Convert card. Typed values win over what any PO printed — which is what you want
when four POs share a delivery point, and is why the boxes are left empty when
they do not. The step-3 preview says `each PO has its own` for a field the orders
disagree on instead of showing one of them as if it were theirs.

**Where it surfaces:** the step-3 preview lists the orders above the column
table; the Inbox row says `4 POs`; the Read tab shows the list in place of the
single address block (`_cache_orders()`), and the Quick Convert card grows a
P/O column. All four read the same `orders[]`, so they cannot disagree.

**Not handled on purpose:** one attachment holding four orders AND four
different Sold-To accounts. The upload carries one Sold-To per file (column F),
so that document has to be split by hand, and the preview's warning is where
that becomes visible.

### 4.8 The endpoint, the key, and `claude_config.json`

**This does not talk to `api.anthropic.com`.** It talks to the SEA private
inference endpoint documented in **"SEA Claude API Guide"**, which implements
the standard Messages API but differs in two ways — both of which fail
*silently and identically to a bad key* if you get them wrong:

| | Public Anthropic API | This endpoint |
|---|---|---|
| Base URL | `https://api.anthropic.com` | `https://seadev-claude.sec.samsung.net:8081` |
| Auth header | `x-api-key: <key>` | **`Authorization: Bearer <token>`** |
| Everything else | `POST /v1/messages`, `anthropic-version: 2023-06-01`, `content-type: application/json`, JSON body, JSON reply | same |

`claude_engine.auth_header()` is the only place the auth form is built, and
`messages_url()` the only place the URL is built — there is exactly one
implementation, so the two can never disagree.

Request shape (`_call`), which is the standard Messages API plus a forced tool:

```json
{ "model": "claude-sonnet-5",
  "max_tokens": 8000,
  "system": "<the extraction rules>",
  "tools": [{"name": "return_line_items", "input_schema": {...}}],
  "tool_choice": {"type": "tool", "name": "return_line_items"},
  "messages": [{"role": "user", "content": [<document block>, <text block>]}] }
```

The reply is read from the `tool_use` block's `input`. Forcing a tool is what
makes the gate possible at all: a prose reply cannot be argued with.

Models offered by this endpoint (from the guide). `model` must be one of these
exactly — anything else is a bare HTTP 400:

| Model ID | Guide's note |
|---|---|
| `claude-sonnet-5` | Default / general-purpose (1M context) — **the default here** |
| `claude-opus-5` | Higher-capability tier (1M context) |
| `claude-sonnet-4-6` | Previous-generation Sonnet (1M context) |
| `claude-haiku-4-5` | Fastest / lowest-latency tier |

Sonnet 5 is enough: the material code is confirmed against the Material Code
list afterwards, so a weaker model degrades *speed*, not the correctness of a
published code. Move up to `claude-opus-5` only if whole line items are being
missed.

| Key in `claude_config.json` | Default | Controls |
|---|---|---|
| `base_url` | `https://seadev-claude.sec.samsung.net:8081` | the endpoint root. `/v1/messages` is appended; a value that already ends in it is trimmed |
| `model` | `claude-sonnet-5` | must be one of the four above |
| `max_tokens` | 8000 | headroom for a long PO |
| `timeout_sec` | 180 | one HTTP attempt |
| `max_pdf_bytes` | 20,000,000 | refuse rather than fail obscurely (request limit is 32 MB / 600 pages) |
| `max_input_chars` | 200,000 | the recovered-text path (DRM) |
| `prompt_version` | 1 | a manual cache nudge. Not needed to invalidate a prompt edit any more — `config_signature()` hashes `_SYSTEM` and `_TOOL` themselves |

**The token is not in this file and is not shipped.** First one found wins:

1. `config/settings.json` → `{"claude": {"api_key": "…"}}` — what the Settings
   screen writes (the field is labelled "PO reading"; the guide calls the same
   secret `auth_token`)
2. `$ANTHROPIC_AUTH_TOKEN`
3. `$ANTHROPIC_API_KEY`
4. `CodeExtract/.api_key`

`base_url` resolves in a different order on purpose — the file sits *below* the
two places an operator actually edits:

1. `config/settings.json` → `claude.base_url` (Settings screen; blank = use the default)
2. `$ANTHROPIC_BASE_URL`
3. `claude_config.json` → `base_url`
4. `DEFAULT_BASE_URL`

### 4.8.1 Where a machine's configuration lives — configure once

`config/settings.json` is the only file that holds this machine's own settings:
the PO-reading endpoint, the token, the mailbox, the port and the desktop
choices. It is read at start-up and rewritten by every Save; nothing else has to
be re-entered after the first run.

Two rules make that hold across deployments, and both are deliberate:

* **The release does not ship `settings.json`.** `make_release.bat` excludes it
  (`/XF settings.json`) and ships `config/settings.default.json` instead. The
  app merges the defaults *under* whatever `settings.json` exists
  (`orderflow.load_settings`), so a fresh zip starts from factory values while a
  machine that has already been configured keeps its endpoint and token even
  when the folder is unzipped over.
* **`settings.json` is optional.** With no file at all the app starts on the
  defaults and writes the file on the first Save. The one case that still fails
  loudly is a *corrupt* file: starting from defaults there would silently throw
  the stored credential away.

To pre-configure a deployment, drop a `settings.json` next to the app with the
`claude` block filled in — `"base_url"` and `"api_key"` — and it is ready on the
first launch. `Settings → Reset for Re-testing` deliberately does NOT clear the
`claude` block: it resets processing, not the machine.

No key → `_load_module()` raises with a message that says exactly where to put
one, and `setup_python_env.bat` warns at install time. The failure mode to
avoid is a PO coming back with zero codes and nothing explaining why.

**Settings → "Test PO reading"** is the answer to "is it wired up?". It sends a
16-token message through the same `_post` an extraction uses — so a green result
means the address, the token and the model all work — and renders
endpoint / model / round-trip / reply, or the error plus what to do about it.
It tries whatever is typed in the boxes, not only what was saved. `_plain_error()`
turns a 401/404/400/413 into the specific fix ("rejected the key — it is sent as
`Authorization: Bearer`", "no API at … — the base URL is wrong", "does not offer
that model — available: …"), because the raw body does not say which mistake
was made.

Python standard library only (`urllib`). No package to install on a locked-down
corporate PC, and nothing in `requirements.txt` for it.

### 4.9 Known weaknesses and risks

Ordered by how much they can cost.

1. **A plausible but wrong NUMBER is the one failure the gate cannot catch.**
   The gate proves a material code exists; nothing proves the quantity or the
   price is the document's. `check_arithmetic()` catches the cases where the
   line's own arithmetic or the document's total disagrees, and those are the
   majority — but a self-consistent misread is indistinguishable from a correct
   one. This is why `source_line` is required: a human can check it in two
   seconds. **Do not remove it to save tokens.**
2. **`page_count` is 0.** No PDF library is used, so the document's length is
   unknown until it is sent. Nothing consumes it.
3. **A PO bigger than `max_pdf_bytes` is refused.** Raise the cap rather than
   truncating: half a PO silently produces a half order.
4. **Cost and latency.** One call per document, cached. A re-Confirm with
   `force=True` pays again by design.
5. **A PO leaves the PC** (4.0 principle 6). Accepted deliberately; revisit only
   with the owner.
6. **DRM files still depend on Acrobat/Word.** `pdf_access` is unchanged: if an
   allow-listed application cannot open the file, nothing can be read from it,
   and the file is reported as such rather than guessed at.
7. **`material_master` normalisation still runs after the gate**
   (`normalise_to_master`). The gate confirms against the reference CSV; the
   bridge then applies the Product Mapping Table's short→FULL rewrite. Two
   steps, two authorities, in that order — see 4.15 for why the mapping table
   cannot be folded into the gate.

### 4.10 Retired with the local engine

These sections described mechanisms that no longer exist. Kept as a list so a
reader who remembers them knows they were removed on purpose, not lost:

- **4.10 Known weaknesses (geometric)** — column misalignment, OCR digit loss,
  per-PO special cases. `docs/COLUMN_ALIGNMENT.md` is the write-up; it is now
  history, not a live risk.
- **4.11 the golden set / `engine_baseline.py`** — replaced by the `extract`
  suite (offline, no API key) plus spot checks on `data_upload\*.pdf`.
- **4.12 the four fallback paths** (zone / pattern / hybrid / extract_from_text)
  — one call now.
- **4.13 "reading numbers the document printed badly"** — `repair_ocr_digits`,
  `_fuse_split_figures`, kerning repair, and `of_erp.ocr_digits` (which rewrote
  "S4" to 54 on the way into the upload file). All OCR-input losses; there is no
  OCR. A value the reader is unsure of goes to `review`, never rewritten.
- **4.14 scanned PDFs** — no rasteriser, no OCR engine, no DPI tuning. A scan
  is sent as a PDF like any other.
- **`customer_templates.json` and `devtools.py template`** — no zone boxes.

### 4.11 Verification workflow — run before and after every change

```
python src\selftest.py extract      # the gate, values as printed, the cache (offline)
python src\selftest.py              # every suite
```

Then, once, by hand — there is no automated coverage of the API call itself:

1. Quick Convert → drop a PDF from `CodeExtract\data_upload\` (start with a
   scanned one).
2. Check **every** line against the document, not just the count: a missed line
   and a phantom line both look like "it worked".
3. Check that a code you know is **not** in the Material Code list was set aside
   rather than published. That is the gate doing its job.
4. Read the console: the arithmetic diagnostics name anything that did not
   balance.

**Regression tests are the licence to refactor.** `selftest.py` encodes bugs
that actually shipped; the `extract` suite encodes this chapter's invariants.

### 4.15 The Product Mapping Table — short SKU → FULL SKU

A PO prints the **short SKU** (`RAF18DBB12`); ERP is keyed on the **FULL SKU**
(`RA-F18DBB12/AA`). The mapping between them comes from Samsung's marketing
mapping workbook, uploaded on Master Data > Material Codes. It is read by
`parse_mapping()` in the MATERIAL MASTER section of `src/of_master.py`.

**Which columns are read.** Only four, by header name — never by position:

| Col | Header | Field | Becomes |
|---|---|---|---|
| A | `FULL SKU` | `full` | the code itself |
| B | `short skus` | `short` | the rewrite key |
| D | `MatG` | `group` | `product` |
| E | `MatG II` | `group2` | `cate1` |

C (`MATERIAL GROUP CODE`) and the other 30 columns are ignored. Header spellings
are folded by `_map_head()`, so `FULL SKU` / `Full Sku` / `FULL_SKU` all resolve,
and `MATG` / `Material Group` / `MatG II` / `Material Group 2` likewise. The two
group columns are optional; `FULL SKU` + `short skus` are not — **that pair IS
the mapping**, and a file without both is not a mapping table.

**Layout detection is by header, not by a setting.** `mm_upload()` tries
`parse_mapping()` first; if the header does not name both SKU columns it falls
through to the price-sheet reader (`parse_excel()`), so the existing customer
price sheets keep working untouched. A mapping upload **REPLACES** the stored
mapping (an upload re-publishes the whole table); a price-sheet upload leaves it
alone. `merge(…, sku_map=…)` is the only writer.

**The ambiguity rule — the important part.** 403 of the real workbook's short
SKUs stand for **more than one** FULL SKU (`L-DLVY` → `/E1`…`/E5`; `AX300T9080W`
→ two different models, one of which looks like a typo in the source). Those are
**not** rewrite rules:

- `parse_mapping()` returns **three** things: `codes`, `sku_map`, `conflicts`.
  `sku_map` holds only the **unambiguous** rewrites; an ambiguous short SKU is
  kept **out** of it and listed in `conflicts` instead.
- `sku_full()` therefore returns `""` for an ambiguous short SKU, so nothing can
  ever pick one for it. A wrong FULL SKU is a wrong order line.
- `sku_conflicts()` exposes them, and the upload message counts them, so the
  human can fix the workbook.

`sku_full()` uses the **mapping table, never a string rule**: 110 of the real
rows have a short SKU that is not a prefix of its FULL SKU (`RAF18DBB12` →
`RA-F18DBB12/AA` drops the hyphen), so "strip the market suffix" would be wrong
often enough to matter.

**Where the rewrite happens.** In `normalise_to_master()` (EXTRACTOR BRIDGE,
`src/of_pdf.py`), which runs on both the mail Confirm path and Quick Convert, so
a PDF gives identical codes either way. Order: **short → FULL** first, then the
existing master-spelling match. A rewritten code is reported in the `fixed`
list, which the Confirm message prints.

**`sync_to_engine()` writes both spellings.** The generated
`material_codes_reference.csv` carries each FULL SKU **and** its unambiguous
short SKUs (carrying the same material group), so the engine's `BackboneIndex`
confirms a short SKU on sight and `printed_form()` keeps it as printed. Ambiguous
shorts are deliberately **not** written: they stay unconfirmed, which sends them
to the engine's `review` list — the existing "a human decides" path.

⚠️ **`MatG` spelling is unified.** The workbook carries both `ref` and `REF`;
`_canon_group()` folds a known alias so the codes tree shows one group, not two.

**Still open.** Ambiguity is *reported*, not *resolved* — a short SKU that stands
for several FULL SKUs reaches the review list and waits. The real fix is in the
source workbook (the `AX300T9080W` row points at a different model number), and
until then those PO lines need a person.

**Tests:** `python src\selftest.py sku` (17 checks) covers the header detection,
the column-to-group mapping, the `ref`/`REF` fold, the non-prefix row, the
ambiguity refusal, `normalise_to_master`, and the export → re-import round trip.

---

## 5. Quick Convert (file only, no email) — the QUICK CONVERT section of `src/of_pdf.py`
- PDF → the chapter-4 engine unchanged (`extractor_bridge._load_engine`).
- Excel PO → `parse_excel_pos()`: one result per worksheet, because a workbook routinely holds several POs (one per tab) beside reference sheets that are not orders.
  - `_header_row()` runs two passes. **Strict**: a header naming a quantity column *and* a money column — that pair is what tells an order table apart from a price list (`Model | Net Invoice`: a price, no quantity). **Loose**: any single qty/money header, or no header at all with the numbers read by position — real POs do arrive like that, and an earlier version that accepted only the strict pass regressed them into "no purchase-order table found". A sheet matched only by the loose pass must then show a real quantity in at least one row before it is accepted, and positional inference refuses to call a *lone* number beside a code a quantity (that is a price-list row). Between them those two rules keep price lists out without losing headerless POs. `python src\selftest.py excel` covers both directions.
  - Codes are still found by `material_master.lookup()` per cell, never by column position or regex. Codes absent from the master are reported as `unknown`.
  - qty / unit price / **extended amount** are read by header (`QTY_HEADERS` / `COST_HEADERS` / `TOTAL_HEADERS`), falling back to the numbers right of the code. The amount used to be what let `erp_excel.reconcile()` prove the quantity (see 4.10); that cross-check was **removed on purpose** (2026-10, see 2.2), so the amount is now only carried through to the workbook.
  - Rows with no quantity and no money are skipped (order templates leave pre-filled zero rows), and `_is_footer()` closes the table at the first total/notes row.
  - PO number: `_find_po()` reads a label with the value beside or below it (`_po_value()` requires a digit, so a "PURCHASE ORDER" title is not read as the value). Failing that the sheet name is used and flagged `_po_from_sheet_name`, which the screen reports.
- Both paths produce the same `records[]` shape and hand it to `erp_excel.build_upload()`.
- Excel layouts differ per customer; expect to extend the header vocabularies. `src\selftest.py` (suite `excel`) builds throwaway workbooks for each shape seen so far — add a case there before changing the reader.
- `extractor_bridge.normalise_to_master()` — shared by this path and by the mail Confirm path — falls back to matching a code's base (the part before "/") against the master's own bases when the exact string doesn't match, but only when exactly one master entry shares that base; an ambiguous base (two market variants) is left unresolved rather than guessed. Regression test: `python src\selftest.py bridge`.

---

## 6. Dashboard-side things worth knowing

### 6.1 PO-number rules (the CLASSIFIER section of `src/of_core.py`)
Rules are tried in this order, first match wins:
1. the per-customer `entry["po_regex"]`, if one is ever set
2. `settings.po_regex_default` — the token after a `PO#` / `Purchase Order` label
3. `settings.po_regex` — the **machine-wide preset** chosen on the Settings screen
4. last resort: a 7–12-digit number in the attachment filename, with
   **`looks_like_date()` rejecting dates (20260901 etc.)**.

- `"subject:"`-prefixed presets in `PO_PRESETS` restrict the regex to **the subject
  only** (KB Home prints a bare number in the subject and has no `PO#` label anywhere).
- **The labelled rule runs BEFORE the preset, deliberately.** A digits-only preset
  matches any 8–12 digit run, which includes a date ("Order 20260901 for PO 12345"),
  so running it first would corrupt mail the label rule reads correctly. As a
  fallback it adds a rule for customers that have no label and leaves every labelled
  mail byte-identical.
- ⚠️ **This was broken between the 2026-10-07 refactor and 2026-10-11.** The presets
  were still sent to the browser (`/api/dashboard` → `po_presets`) but nothing read
  them: `domain_master()` always emits `po_regex: ""`, so rule 3 did not exist and
  **KB Home POs could not be read at all** — a silent capability regression, since
  the branch itself worked and had tests. The Settings screen now has a **PO number**
  selector, `/api/settings` accepts `po_regex` (validated against `PO_PRESET_VALUES`,
  so a typo falls back to the standard rule rather than disabling PO reading), and
  the payload carries the active value. Tests: `python src\selftest.py po` and
  `p3`.
- ⚠️ The **per-customer `po_regex` is still gone** (2026-10 refactor): it lived in
  `customer_master.csv`, which no longer exists, and the Ship-To master is an ERP extract
  with no rule column. The rule is machine-wide, so switching it affects every
  customer — the ordering above is what keeps that safe.

### 6.2 The customer master — two tables, joined by the customer name

**Identity is the DOMAIN, and the domain lives in exactly one place:**
`config\domain_master.json` — the ERP file's **second sheet** (`SOLD_TO_NAME` →
`DOMAIN`), uploaded on its own.

The customer data is **two tables**, because that is how ERP ships it and because
a domain belongs to the *customer*, not to each of its ship-to sites:

```json
config\ship_to_master.json   {"uploaded_at", "source_file",
                              "rows": [ {..the 14 pair columns..}, … ]}
config\domain_master.json    {"uploaded_at", "source_file",
                              "rows": [ {sold_to_name, domain}, … ]}
```

The 14 pair columns are `ST_COLUMNS` in the SHIP-TO MASTER SECTION of
`src\of_master.py`, in the ERP file's own order; `ST_KEYS` / `ST_HEADERS` are
derived from it:

| # | key | header | # | key | header |
|---|---|---|---|---|---|
| 1 | `sold_to_code` | `SOLD_TO_CODE` | 8 | `zip` | `SHIP_TO_ZIPCODE` |
| 2 | `sold_to_name` | `SOLD_TO_NAME` | 9 | `dlv_plant` | `DLV_PLANT` |
| 3 | `ship_to_code` | `SHIP_TO_CODE` | 10 | `state` | `SHIP_TO_ST` |
| 4 | `ship_to_name` | `SHIP_TO_NAME` | 11 | `account_manager` | `ACCOUNT_MANAGER` |
| 5 | `address` | `SHIP_TO_ADDRESS` | 12 | `district` | `DISTRICT` |
| 6 | `city` | `SHIP_TO_CITY` | 13 | `region` | `REGION` |
| 7 | — | — | 14 | **`type`** | **`TYPE`** |

…plus `sub_type` / `SUB_TYPE`. **The `domain` column that used to sit here at
position C is gone** — it moved to `domain_master.json`. The domain table has
two columns (`DM_COLUMNS`): `sold_to_name` → `domain`.

**The two tables are joined at read time, never baked in at import.**
`ship_master.domain_of(settings, pair)` resolves one pair row's domain, in order:

1. **`SOLD_TO_NAME`, exactly as spelled** — the domain sheet is keyed by it, so a
   name the two tables spell identically gets the domain uploaded against that
   spelling. Tried **first**, because two customers can share a normalised name
   while spelling theirs differently (`BILL SMITH` vs `BILL SMITH INC.` are two
   accounts with two domains, and collapsing them hands one the other's).
2. **`SOLD_TO_NAME`, normalised** — `_norm_name()` drops case, punctuation and
   the legal suffix, so `1847 GOEDEKER, INC.` matches `1847 Goedeker Inc`. The
   two source files spell the same customer differently far more often than not.
3. **`SOLD_TO_CODE`** — a name the domain table does not carry can still be owned
   by a code that does. Only a fallback: one code can carry several names, so a
   code-first match would hand the wrong domain to a name that has its own entry.

Resolving on the way *in* would freeze a match made against one spelling; both
tables are meant to be edited by hand afterwards, and a stale join would
silently orphan rows. `_dm_cached()` memoises the whole index (`dm_index()` and
`dm_exact()` are thin readers of it) on the two files' mtime+size — this is on
the path of every row of every drop-down, over a 3 MB pair file. ⚠️ The cache
key is built with `_stat_key()`, which returns `None` for a **missing** file:
building it from a stat that *raises* used to disable caching entirely until the
domain table was written for the first time. ⚠️ A lookup must cost one stat
pair and nothing else — `domain_of()` is called once per pair-table row, so any
filesystem *write* on this path is paid 7 000 times over (6.5).

A pair that resolves to nothing has no customer — honest, and the same rule the
old empty-domain rows followed. On the real 2026-10-01 master that is 2 rows out
of 7,428 (`VFP`, `Viking Forest Products LLC`).

**One row = one (Sold-To code, Ship-To code) pair**, and
`(sold_to_code, ship_to_code)` is the composite key the ERP columns are filled
from (6.7).

- **`classifier.match_customer()`** walks `ship_master.domain_master()`, which returns
  **one entry per domain**: `{customer: <the domain>, domains: [d],
  role, sold_to_list, ship_to_list}`. The two lists are the **union** of the domain's pairs
  and feed the F/G drop-downs. `role` is `"Builder"` **only when every pair of the domain is**
  Builder, else `"Retail"` — a **screen label only**, because column D reads each row's own
  TYPE (6.7). Order comes from the domain table, so the list on screen matches the order the
  domains were uploaded in.
- **Column D follows the TYPE, not a stored channel:**
  `channel_for_type(v)` = `"11"` when `_clean(v).lower() == "builder"` **exactly**, else
  `"10"`. So `Regionals`, `BBY`, `Wayfair`, `Accrual`, a literal `NULL` **and
  `Builder Others`** are all 10.
- **Nothing in the old model survives.** `config\customer_master.csv` and
  `config\erp_accounts.json` were **deleted**, along with `load_master()` / `save_master()` /
  `add_domain()` / `del_domain()` / `add_member()` / `update_member()` /
  `ship_lookup()` / `distr_channel_of()` / `fold_channels()` / `normalize_type()` and the
  `FIELDNAMES` / member-column machinery. There is no per-member row, no per-customer
  `po_regex`, and **no hand-recorded distribution channel at all.**

**Importing.** Each table has its own parser and its own upload, and neither
touches the other's file:

- `parse_file(path)` reads the **active sheet only** (via
  `material_master._read_rows`), finds every column **by header text** through `ST_HINTS`
  (so `_hkey()` drops punctuation, case and the `(M)`/`(O)` marker), and needs at least 3
  recognised headers or it raises. It skips a row that names none of `sold_to_code`,
  `sold_to_name`, `ship_to_code`. `upload()` then **REPLACES** the whole pair table and
  returns `{rows, domains, sold_tos, ship_tos, types, conflict_count, conflicts, file}` —
  `domains` is counted through the resolver, so it is only as good as the domain table.
- `dm_parse_file(path)` is the same idea for the domain sheet, through `DM_HINTS`
  (`SOLD_TO_NAME` / `DOMAIN`; `Domain Name` and `Email Domain` are accepted aliases, so an
  older single-table export still imports). It needs **both** columns or it raises, and
  `dm_upload()` **REPLACES** the domain table only, returning
  `{rows, domains, named, unmatched_names, file}` — **`unmatched_names`** is how many
  `SOLD_TO_NAME`s the pair table carries that this file does not, i.e. how many pairs are
  about to be unowned. It is reported because it is the one way this table can quietly lose
  a customer.

**Hand editing.** The Customer Master screen has **two** editable grids over the same two
tables:

| | pair table | domain table |
|---|---|---|
| window | `page(settings, q, limit, offset)` | `dm_page(settings, q, limit, offset)` |
| search | `matches(rec, q)` (Sold-To / Ship-To code+name) | `dm_matches(rec, q)` (name / domain) |
| writes | `add_row` / `set_cell` / `delete_row` / **`st_clear`** | `dm_add` / `dm_set_cell` / `dm_delete_row` / `dm_clear` |

Each row carries `_i`, its stored position, which is what every write addresses it by.
`add_row(blank=True)` / `dm_add(blank=True)` are the grids' **+ Add row** (an empty row is
the point); a programmatic add still has to name something. ⚠️ `matches()` no longer
searches the domain — that is the other table's column now, which is why a Ship-To search
for a domain returns nothing.

⚠️ **`st_clear`, not `clear`.** `orderflow.py` is a concatenation, and `material_master`
already owns a module-level `clear` whose facade binds that global name — a second
`def clear` silently took it over, which made `material_master.clear()` return Ship-To rows.

**Endpoint surface** (`/api/…`):

| Pair table | Domain table | Both |
|---|---|---|
| `erp_upload` | `domain_table_upload` | `master_clear` (clears **both**) |
| `master_rows` / `_add` / `_set` / `_del` | `domain_row_list` / `_add` / `_set` / `_del` / `_clear` | `master_apply` |
| | | `party_options` (6.7.2), `master_export` (6.9) |

⚠️ The domain endpoints are named `domain_row_*` / `domain_table_upload`, **not**
`domain_add` / `domain_del`: those names belonged to the retired member model, and reusing
them would look like the old card-claim API coming back. `selftest.py ui` asserts they stay
absent. `master_apply` re-runs `match_customer` over every stored mail — only `customer`
and `retail_builder` are written back; the Sold-To / Ship-To pair picked on a row is never
touched. **Removed with the old model:** `/api/master`,
`/api/domain_add`, `/api/domain_del`, `/api/assign`, `/api/account_distr`,
`/api/customer_new`, `/api/customer_rename`, `/api/customer_accounts`, `/api/po_rule`.
Calling one of those is a bug, not a deprecation.

⚠️ **The identity list must not be cached across a write.** `main()` computes
`ship_master.domain_master()` once, but the table is edited **from the browser** — upload,
+ Add row, a cell edit, Clear — and a domain that arrives that way has to be recognised on
the very next request. `make_handler()` therefore wraps it in a `_master()` accessor keyed on
`ship_master.master_key(settings)` — the **mtime + size of BOTH files** (pair table *and*
domain table): two `stat()`s per request, a re-read only when either actually changed. Every
route inside the handler uses `_master()`, never the closure parameter. A list captured at
start-up would leave a freshly uploaded domain invisible until the process restarted.

⚠️ **Both files, not just the pair table** (2026-10-27). A customer is a *domain*, and only
the DOMAIN table can give a domain its customer name — so "add a domain row" changes the
identity list without touching the pair table. Keyed on `st_path()` alone, that row was
invisible until a restart: the Inbox kept drawing the old list and offered no Sold-To /
Ship-To for the customer that had just been created.

⚠️ **The browser mirrors it in two places.** `forgetParty()` drops the per-domain account
cache in `report.py` after any write to either table, and now also calls
`refreshMasterList()` — `/api/master_list` returns just `master` / `erp` /
`domain_status` / `ship_conflicts` (a few KB) instead of the whole 140 KB dashboard, because
`DATA.master` is what `domainKnown()` reads before it will draw a picker at all. And a cell
drawn *before* the account list arrives is a `data-pwait` placeholder, not a `<select>`:
`patchParty()` rebuilds those cells too, so a picker appears when the answer lands instead of
waiting for the 60 s poll (see 6.5).

Rapid grid edits are a third cache boundary. A second Domain cell can be saved while the
refresh caused by the first is still running; `MASTER_DIRTY` records that later write and
forces another `/api/master_list` pass. Completion always redraws Inbox because the detailed
`PARTY` cache may have changed even when the four-key identity summary is identical. An
already rendered picker can also refill its own domain through `pcLoad()` if it is opened in
the short interval between invalidation and the redraw.

Domain-table writes also call `_reclassify_stored_mails()` on the server. Adding or uploading
a domain therefore claims mail that was collected before the row existed without requiring a
separate **Apply master** click; deleting or clearing a domain symmetrically removes stale
classifications. The browser waits for the small master refresh and reloads dashboard mail
after an inline Domain edit, so the change is visible as soon as the user returns to Inbox.

### 6.2.1 One domain, one customer — the ambiguity rules

Domain identity is only safe if a domain cannot mean two things, so the model defends that
invariant instead of picking a winner by luck:

- **Longest suffix wins.** `domain_owners()` takes an exact match first, otherwise the
  **longest** registered domain that the mail's domain ends with (`d.endswith("." + dom)`), so
  a mail from `sea.samsung.com` resolves to the customer holding `sea.samsung.com` and never
  to the one holding the bare `samsung.com`. `domain_conflicts()` / `match_customer()` keep
  the "two owners ⇒ unclassified" rule; `domain_master()` groups by domain, so a domain
  cannot appear twice and the rule is a backstop rather than a live path.
- **A claim is a row.** There is no "claim" endpoint any more: the domain is known because a
  Ship-To row carries it. The Unmatched list's **+ Add a Ship-To row** button posts
  `/api/master_add {row:{domain}}`, switches to the Customer Master tab and filters to that
  domain, so the codes get typed next to the name. Until the Sold-To / Ship-To codes are
  filled in, the domain is known but `party_options` offers **nothing** — a row with no
  account number cannot put a wrong one on an order.
- **A pair repeated with different details is a CONFLICT, and the export refuses to guess.**
  See 6.7. The grid marks those rows **red** and the legend explains it; `set_cell()` answers
  with the refreshed list so the red clears the moment the copy is fixed.
- **Public mail providers are still called out** (`PUBLIC_DOMAINS` / `public_domain()`) —
  nothing stops a row for `gmail.com`, but the screen says so.


### 6.3 Attachment saving
- `collector._save_pdfs()`: saves only `SAVE_EXT`, skips signature images, handles the 260-char path limit. **Failures are printed as `[ATT]` on the console** — never swallow them silently.
- The UI links only `pdf_paths`. A document attachment that failed to save shows as ⚠ and, when clicked, is re-fetched from Outlook via `/api/refetch_att`.

### 6.4 Build & release
The PyInstaller-based `.exe` beta build (`build_beta.bat`, `build_beta_lite.bat`, `clean_beta.bat`,
`README_BETA.txt`) was retired: NASCA DRM allow-lists `python.exe` but not an unsigned custom `.exe`
(see the retired incident below), so a compiled build could not read DRM-protected PDFs. Running
from Python source sidesteps that entirely.
```
make_release.bat  → ..\OrderFlow_src_<timestamp>.zip  (source copy, calls prepare_handover.bat)
```
Share the zip; colleagues run `python src\orderflow.py` (or `run_dashboard.bat`).

### 6.5 Incidents that happened (so they don't happen again)
| Symptom | Cause | Guard |
|---|---|---|
| Dashboard does not render at all | unescaped `\'` in JS inside report.py | `python src\selftest.py ui` |
| "File is not a zip file" | NASCA DRM file | `material_master._read_rows` goes through Excel COM |
| All 29 .eml files parsed empty | DRM | `_is_drm()` detects and explains |
| JSON BOM error | PowerShell saved with a BOM | write without BOM + read with `utf-8-sig` |
| Quantity 6 (actual 2) | "6.0 cf" read as a quantity | 4.10-1 — **still open, first task** |
| (retired) Quick Convert couldn't read a PO that the dev build read fine | NASCA DRM decides by **process identity**, not by code. `python.exe` was on the allow-list, the unsigned packaged `.exe` was not, so the same bytes came back encrypted | resolved by retiring the `.exe` build — everyone now runs `python src\orderflow.py`, which is already allow-listed |
| Confirm marks a mail Done but no Order Upload file appears | `/api/action` filtered attachments to `.pdf` only before calling `run_extractor()`, so a PO that arrived as an Excel attachment was silently dropped | `run_extractor()` now splits PDF vs Excel itself and routes Excel through `quick_convert.parse_excel_pos()` |
| Column H gets the PO's short code instead of the master's full code | `material_master.lookup()` is an exact-string match; a code missing its market suffix (`RF23A9671SR` vs master's `RF23A9671SR/AA`) never matches | `normalise_to_master()` now also matches on the code's base (before the `/`), but only when exactly one master entry shares that base — an ambiguous base is left alone, not guessed |
| Outlook mailbox picked in Settings gets silently reverted, sync reads a different mailbox | the 3-second poll that runs while a background collection is active called `load()`, which re-renders the whole page — including the Settings form — from the server's last-saved values | `pollDuringSync()` refreshes the sync banner/badges only and skips `render()` while `TAB === 'settings'` (or `'codes'`), matching the slower 60s poll's existing guard |
| The Order Upload file is the wrong version (4 columns instead of the ERP form, or the other way round) | the full/simple choice is per machine and is remembered — `erp_format` in `config\settings.json` — so it can be left on the wrong setting from an earlier session, and Confirm silently produces that version | both screens show a split button whose menu marks the active version with ✓ and whose main half names it, the mail list says in words which file Confirm will write, and each generated file is badged **Full form / Simple** in the Order Upload and Quick Convert lists; pick the other version and reconfirm |
| A generated file has the wrong column D (Distr. Channel) | D follows the row's own **TYPE**, not a stored channel: it is `11` only for an exact `Builder`, and `10` for everything else — including `Builder Others`, `Regionals`, `BBY`, `Wayfair`, `Accrual` and a literal `NULL` | `ship_master.channel_for_type()` is the single rule; fix the TYPE in the master (or the row) — there is no hand-recorded channel any more (6.2, 6.7.1) |
| N/AI/D come out empty although the account numbers are on the order | the `(Sold-To, Ship-To)` pair is **not in the Ship-To master**, so there is nothing honest to write | `ship_master.site()` returns `None` and the writer leaves those cells EMPTY and prints `[ERP] no Ship-To master row for Sold-To … / Ship-To …`; upload the ERP file or add the row (6.7.1). Address columns are typed per order and are unaffected |
| The same cells are empty and the console names a pair that *is* in the master | the pair is listed **more than once with different details**, so any of the two answers would be a guess | `conflicts()` reports it, both rows go **red** on the Customer Master grid with a legend under the table, `/api/dashboard` carries `ship_conflicts`, and the writer prints `[ERP] … appears more than once in the Ship-To master with different details … left empty`; fix one copy (6.7.1) |
| A domain that was just uploaded / added is not recognised | the identity list was captured **once at start-up** while the table is edited from the browser | `make_handler()`'s `_master()` re-reads on the stored file's mtime+size change, and every route uses it; the retired `domain_probe.py` asserted "visible without a restart" after `master_add` **and** after `erp_upload` — `selftest.py classify` covers the same model in-process now (6.2) |
| Emptying the Ship-To master also empties the Material Codes | `orderflow.py` is a concatenation: a second `def clear` silently takes over the global name the `material_master` facade is bound to | the function is **`st_clear`** and the facade binds `("clear", "st_clear")`; `python src\selftest.py excel` catches it immediately (6.2) |
| An old `config\customer_master.csv` or `config\erp_accounts.json` is still on disk | they were **deleted** in the 2026-10 refactor and nothing reads them | nothing to do — remove them by hand; the only customer data is `config\ship_to_master.json` + `config\domain_master.json` (6.2) |
| A domain is a public mail provider (gmail.com …) | identity is domain-wide, so a row for it hands **every** sender of that provider to one customer | `PUBLIC_DOMAINS` + `public_domain()`; the Unmatched card and the master screen say so, and nothing prevents it if the user means it (6.2.1) |
| A generated file has F or G empty | no Sold-To / Ship-To was chosen (or the chosen pair is not in the Ship-To master), and the writer leaves the cell empty rather than inventing an account | pick the pair in the drop-downs on the row (Inbox) or on the review card (Quick Convert) — the pickers only offer pairs the master actually carries (6.7.2) |
| Two rows carry the same domain with different spellings | `norm_domain()` is the only comparison, so `abt.com`, `@ABT.com` and `www.abt.com` are one domain | `domain_master()` groups by the normalised value, so the table can hold at most one entry per domain and `domain_owners()` / `match_customer()` keep the "exactly one owner" rule as a backstop (6.2.1) |
| After an update the dashboard still renders the **old** interface | an **older dashboard process was still holding the port** (`server.port`, 8766 here). `main()` armed the browser opener *before* trying to bind, so a second launch printed `[ERROR] Port 8766 is already in use`, gave up — and still opened a window, onto the old process. Opened with `--app=` there is no address bar and no reload button, so a stale page is indistinguishable from "the change did nothing" | the opener is now armed only **after** the bind succeeds, so a launch that loses the race exits without opening anything; every response carries `Cache-Control: no-store`, so even a normal refresh cannot resurrect a cached page; `.workbuddy\port_probe.py` asserts the port half, but the "no window onto a stale instance" and `no-store` checks that `.workbuddy\serve_probe.py` used to cover are asserted only by the code itself (3.4). A leftover instance is cleared with `netstat -ano \| findstr 8766` → `taskkill /f /pid <pid>` |
| Every stored mail suddenly has **no customer**, and the Customer Master looks empty | a master JSON that could not be parsed was returned as an **empty** master. One truncated write was therefore indistinguishable from "no customers yet": the app came up unclassified and the next edit saved that emptiness back over the good file | `of_master._read_json()` tells *missing* (ordinary, empty) from *unreadable* (a hard error). A corrupt file raises, is left on disk untouched, and a `.corrupt-<stamp>` copy is kept; `main()` prints it and exits, the HTTP handler answers 500 with the reason. `mm_save` / `save` / `_save_settings` now write a temp file and `os.replace()` it, so a partial file cannot exist. `python src\selftest.py p0` covers it |
| A row in Inbox confirms or opens the **wrong attachment** (a price sheet instead of the PO) | three different filters over one list: the browser kept `.pdf` only, Confirm kept `.pdf/.xlsx/.xlsm/.xls/.csv`, and `/api/open` kept everything. For `[quote.xlsx, order.pdf]` the row on screen was `order.pdf` at index 0, while the server's index 0 was `quote.xlsx` — and a Confirm with no index extracted **both** | `store.order_attachments()` / `order_att_list()` are the one definition, shared by all three. They return the **stored** index (the space `att_states` and `split_by_attachment`'s `#N` keys use), and the page reads `att_docs` from `/api/dashboard` instead of filtering `pdf_paths` itself. A row with no order document now answers 404 instead of being marked Done with no file. `python src\selftest.py p0` covers it |
| The **Order Upload** list never empties and its sidebar badge only grows | nothing in the codebase ever set `erp_uploaded=1` — the button was a `alert('Coming Soon')` stub — while the list filters on `!erp_uploaded`. The badge came from a mail-level SQL query and the list from per-attachment state, so the two also disagreed on a split mail | `erpUpload(id, index)` writes `erp_uploaded=1` through the existing `/api/update` (already an editable field), the button reads **Mark uploaded** and passes the attachment index, `undoDone()` clears the flag again, and `unprocessedOrders()` is now the single definition used by both the screen and the badge |
| The **"Sync this date"** button never appears, and the empty day offers no way to fetch it | the page gates both on `DATA.settings.source === 'outlook'`, but `/api/dashboard` never sent a `source` key — it sent only `outlook`/`sync`/`retention` | the payload now carries `settings.source` (defaulting to `outlook`, the only collector that exists), so the button and the empty-state prompt render and `/api/sync_date` is reachable from the UI |
| A unit price is **silently truncated** — `1198.00` published as `119` | two copies of "what an amount looks like" drifted apart. `_MONEY_CELL` was corrected to accept bare four-digit amounts (COLUMN_ALIGNMENT P0-4), but `_extract_price` — the fallback used by `extract_from_text` — kept its own `\d{1,3}` copy. It did not reject the amount, it matched the first three digits and returned them | the shape is defined **once** as `engine._AMOUNT` and shared by `_MONEY_CELL` and `_extract_price`. `_ITEM_HINT` had the same stale `\d{1,3}` and was widened too — a bare four-digit price made a line fail the "looks like an item line" test, so loose matching was skipped on exactly the layouts that need it. `python src\selftest.py p3` covers it |
| A brand-new PO is flagged as a **duplicate** because its subject says UPDATE | `check_duplicate()` returned `True` both for a real re-receipt *and* for a first receipt whose subject merely contained a revision/cancellation word, so the two were indistinguishable on screen — same amber row, same red glyph. A false positive on every "REV"/"UPDATE"/"수정" mail teaches the user to ignore the flag | the weaker signal is now separate: `is_duplicate` means **only** a real re-receipt, and a new `dup_kind` column (`repeat` / `keyword`) travels with it. The screen draws a red ⚠ for `repeat` and a muted ℹ for `keyword`, and the Duplicates payload holds no keyword-only rows. `python src\selftest.py p3` covers it |
| The `fixes` list — "every correction must be visible" (4.0 principle 5) — is always empty | the parameter survived the 2026-10 removal of the arithmetic cross-check, but every `fixes.append` went with it, while `prepare_lines()` still recovers quantities, prefers the printed price over the price list, and repairs OCR digits **silently** | `prepare_lines()` now records those three, so the Confirm message and the Quick Convert card list them again. A value that merely passes through is **not** a fix and is not listed. The dead `amount` computation (and the user-facing "corrected by cross-check" wording) is gone. `python src\selftest.py p3` covers it |
| A parenthesised code with a **market suffix** (`DVE45T6000W/A3`, `ME16A4021AS/A2`) is dropped as "scrambled text" | `looks_like_scrambled()` counted letter↔digit transitions across the **raw** string, so the `/` and `-` separators each added a flip: `DVE45T6000W/A3` scored 7 transitions against a threshold of 6.3 instead of its real 5. Every `/A3`, `/A5`, `/A2` code was rejected on the parenthesised path — silently, because the guard runs *before* the backbone lookup — while the backbone path found the same codes fine | transitions are counted over the **alphanumeric characters only**, since a separator is structure rather than interleaving. Real market-suffix codes are read again and genuine junk (`DISWH8W0ACSGH4E0R5`) is still blocked. Regression: `t_matching` in `devtools.py` |
| The dashboard takes ~35 s to come up, and ~35 s again after every Ship-To/domain upload — the console sits on `Ship-To master: … loaded` or the page spins | **`os.makedirs(exist_ok=True)` was in every `*_path()` helper**, i.e. on the READ path. On the deployment filesystem that call costs ~2.3 ms — the expensive half is the `mkdir` that FAILS with EEXIST, not the stat — and `domain_master()` calls `domain_of()` once per row of the pair table (7 418 rows), which touched four paths per row: ~30 000 makedirs of directories that already existed. Measured 34.1 s for 465 domains | **reads stat, only writes create.** `of_master._ensure_dir()` is called from `_write_json()` (the single write funnel); `mm_path` / `st_path` / `dm_path` / `dismissed_path` are pure path joins again. `domain_of()` also takes **one** cache lookup instead of two (`_dm_cached()`), so the index is built once and then one stat pair per row. 34.1 s → 0.15 s; a 7 418-row walk 34.4 s → 0.03 s. `python src\selftest.py classify` asserts "reading the masters creates no directory" and "the index is built once for 40 lookups". **Rule: never put makedirs/side effects in a path helper or any other read path** |
| "I add a **domain row** on the Customer Master and the Inbox still offers no Sold-To / Ship-To for that customer" | two independent staleness bugs on the same path. 1) The server's `_master()` cache was keyed on the **pair table only**, so a DOMAIN row — the only thing that gives a domain its customer — was invisible until a restart. 2) The Inbox draws a picker only for a domain in `DATA.master`, and a cell drawn before `/api/party_options` answered was a bare "…" **placeholder with no `<select>`** — `patchParty()` could not patch what was not there, so the row sat on "…" until the 60-second poll re-rendered the page | 1) `ship_master.master_key()` = mtime+size of **both** files, and `_master()` keys on it. 2) `forgetParty()` also calls `refreshMasterList()`, which re-reads `/api/master_list` (`master`/`erp`/`domain_status`/`ship_conflicts`, a few KB, not the 140 KB dashboard) and redraws the Inbox when the list actually changed. 3) the placeholder now carries `data-pwait`/`data-pkind`/`data-pstored`/`data-psold`/`data-pid`, and `patchParty()` rebuilds those cells with `partyCellRaw()` when the answer lands. Driven end-to-end on a copy of the workspace: add a pair row + a domain row through the real endpoints, then `/api/master_list` and `/api/party_options` already answer for them. `selftest.py classify` covers `master_key()`; `p0` covers the endpoint and the page wiring |
| The **customer filter** in the Inbox could only hold one customer | it was a `<select>` with one value, so comparing three customers meant re-picking three times | a tick panel: `CUSTPICK` is an array, `custPickHTML()` draws a `All customers ▾` button plus a checkbox list that stays open across the re-render (`CUSTOPEN`), and clicks outside close it. `selftest.py p0` asserts the panel exists and that `CUSTFILTER` is gone |
| A whole-dollar unit price shows in the generated file as `1198`, not `1198.00` | column BE carried the template's own General format and the value `_num()` produces is an int when it is integral (`1198.0` → `1198`), so Excel painted it with no decimals | `write_line()` sets `number_format = "#,##0.00"` on the cost cell — a FORMAT, not a round, so the ERP still imports exactly what the PO printed (4.5). `selftest.py erp` asserts the format on a whole price and that a 3-decimal price keeps its value |
| Both versions ticked, but the switch still draws its thumb on one half | the "both ticked" rule was written `.segopt:first-child`, and the first child of `.seg` is the thumb `<span>` — no label is ever a `:first-child`, so the rule matched nothing and was silently dropped. A `:has()` that matches nothing looks exactly like working CSS | `.segopt:first-of-type` / `:last-of-type`, and the rule is verified against a real render (three states: left / right / **spanning**), not just against the source text. `selftest.py ui` pins the selector; the state itself is checked by screenshotting step 3 and the Quick Convert card |

### 6.6 NASCA DRM and process identity — read this before debugging "it works in dev"

**Authorisation — read this first if you are wondering whether any of this is
allowed.** It is. Reading DRM-protected POs through `python.exe` was confirmed
by the corporate IT Security team and approved by the responsible executive;
the per-PC permission is granted through IT4U under the exact wording
**"NASCA Decrypt with Python"**. OrderFlow works *within* the control rather
than around it — there is no password stripping, no keystroke simulation, no
screen scraping anywhere in this codebase, and those techniques were reviewed
and deliberately rejected (see the backlog notes). If an audit ever asks, the
answer is the approval record, not this file. _(Approval reference: TODO —
fill in the IT4U ticket / approval number.)_

#### The principle: handle the control, do not work around it

This took a month to learn and is the most transferable thing in this
codebase, so it is written down rather than left to be rediscovered.

Every DRM failure in this project looked like a file problem and was actually
a **process** problem. The document was never broken; the wrong program was
reading it. Once that clicked, every fix took the same shape — change *who
does the reading*, never attack the protection.

The decision procedure, in order. Work down it; stop at the first that applies.

1. **Which process is reading the bytes?** Not "which file is this" — that is
   almost never the answer. OrderFlow runs as `python.exe`, which is granted.
   A browser is not. An unsigned packaged `.exe` was not, which is why that
   build was retired.
2. **Can an already-authorised application do the read instead?** Excel reads
   DRM price sheets through COM (`material_master._rows_via_excel`); Outlook
   decrypts attachments as it saves them; Acrobat/Word can be asked for a PDF
   (`pdf_access`). Read values in memory, write nothing, and the protection
   is preserved rather than defeated.
3. **Can the container be handed to an authorised reader?** A DRM container is
   self-describing and survives a byte copy. Writing one to disk and reading
   it back as `python.exe` returns the document (§ measured 2026-09-24,
   below). This is what makes drag-and-drop work.
4. **Only then, ask IT for a permission** — through IT4U, on the record. Never
   reach for a workaround because a request feels slow.

Two rules that fall out of this, both violated at some point and both costly:

- **Never pre-refuse.** A `<##` first-bytes check is for *explaining* a
  failure after the fact, never for blocking an attempt before it is made. A
  guard that refused to even try is what made DRM drag-and-drop look
  impossible for weeks; removing it was the whole fix.
- **Never test "did the bytes stay the same".** Ask "can we read this now".
  When decryption succeeds the bytes are *supposed* to change. An equality
  check rejects exactly the successful case — see `quick_convert._usable()`.

Deliberately not built, after review: password/encryption stripping (pypdf
empty-password decrypt, pikepdf/qpdf re-save), simulated Ctrl+A/Ctrl+C into a
viewer, and screen-capture OCR of a rendered document. All three defeat the
control instead of working inside it. They are an audit exposure regardless of
intent, and this tool is too visible to carry one. If a future change seems to
need any of them, the design is wrong — go back to step 1.

---

The corporate DRM agent decrypts a file only for processes on its allow-list.
This produces behaviour that looks like a code bug but is not:

- The mail path works everywhere because **Outlook** (allow-listed) decrypts the
  attachment when it writes it to `data\attachments`; OrderFlow only reads the
  plain file afterwards.
- Price-sheet Excel works because `material_master._read_rows` hands DRM files
  to **Excel COM** and reads the values in memory (nothing is written, so
  nothing is re-encrypted).
- Quick Convert on a DRM PDF used to fail in the packaged `.exe` build while
  succeeding under `python src\orderflow.py`, because the process opening the file
  differed and there was no PDF equivalent of the Excel COM trick. The `.exe`
  build is now retired for this reason (among others) — everyone runs from
  source, which is already allow-listed, so this no longer comes up.

When something reads as garbage, check the first bytes: `<##` means NASCA DRM,
`%PDF` means a real PDF, `PK` means a real .xlsx. `quick_convert.save_input()`
and `material_master._read_rows()` already do this and say which case it is.

**The grant follows the process, not a list of files — measured 2026-09-24.**
This is the single most useful fact in this chapter, and it was assumed wrong
for weeks. The experiment (run on 2026-09-24, with the since-deleted
`src\check_pdf.py`; the numbers are from that run):

```
copy A104085.pdf test_copy.pdf     (cmd - not allow-listed, so it copies ciphertext)
py src\check_pdf.py "test_copy.pdf"
  first 16  : b'%PDF-1.7 ...'
  pdfplumber: opened, 4 page(s), 2250 chars of text on page 1
```

A byte-for-byte copy of a protected PO, made by a process that cannot decrypt,
**opened as a plain PDF when read by `python.exe`**. So a DRM container is
self-describing: the agent decrypts any container for an allow-listed reader,
and copying one does not strip its protection or its readability.

⚠️ `src\check_pdf.py` is gone, so this cannot be re-run here. The nearest
substitute is the PDF ACCESS report (see the comment at the top of that section
in `src\of_pdf.py`), which answers the same two questions — "can this process
read the file" and "which authorised applications are installed" — for a file you
hand it.

Two consequences, both now relied on in code:

- A file dropped into the browser uploads as its raw container (the browser is
  not allow-listed). Writing those bytes to disk and reading them back as
  `python.exe` yields the document. Drag-and-drop therefore works for DRM
  files — `quick_convert._usable()` is what accepts it, by asking "can we read
  this?" instead of "are the bytes unchanged?". The old equality check
  rejected precisely the successful case, which is why dropping a DRM PO was
  impossible before.
- Do not add a "this file is DRM, refuse it" guard anywhere. Try the read.
  The first-bytes check is for *explaining* a failure, never for pre-empting
  an attempt.

**The rule that decides what works here: read in memory, never write a copy.**
An allow-listed application can *read* a protected file for us, but anything it
*writes* is re-protected by the agent on the way out — Excel's own `SaveAs` of the
ERP template comes back wrapped again. So every working route returns values or text
through the object model (`Range.Value`, `Document.Content.Text`, Acrobat's
`getPageNthWord`) and never asks the application to produce a file. This is why
`erp_excel._plain_template_copy()` reads the template's header block through Excel and
rebuilds it with openpyxl rather than copying it, and why the L3 re-export routes in the
PDF ACCESS section of `src\of_pdf.py` usually fail on such a PC while the L4 text
routes can still succeed.

**The PDF ACCESS section of `src\of_pdf.py` is the mitigation.** When a PO PDF is
DRM-wrapped it asks an application that *is* allow-listed to read it, through that
application's published automation interface — the same pattern
`material_master._read_rows()` uses for Excel:

- **L3** Acrobat / WPS / Word re-exports a plain PDF — sent to the API as a PDF.
- **L4a** Acrobat hands over the text: its Save-As-Text converter first, then a
  per-word walk (`getPageNthWord`) that also returns each word's position, so
  `_lines_from_words()` can rebuild the line structure. Writes no file, so nothing
  gets re-encrypted on the way out.
- **L4b** Word / WPS `Document.Content.Text`.

L4a/L4b yield text with no page coordinates. **Both routes then make the same API
call** — `claude_engine.extract_material_codes()` for a PDF,
`claude_engine.from_text()` for recovered text — through the same prompt and the
same gate.

Until 2026-10-21 these were two parsers, and keeping them in step was the most
expensive maintenance problem in the project. The text route looked codes up in
`config\material_master.json` (4,726) while the engine used
`CodeExtract\material_codes_reference.csv` (7,259) — a strict **subset** — so
**2,533 listed codes** were "unknown" there and their whole line was dropped:
`A106538` and `Samsung PO 514` returned **ZERO** records on one route and 11 / 1
on the other. The unit price was published as the extended cost on every Google
Express row, a model quoted in a description became an order line, and a format
difference (`199` vs `199.00`) made one amount look like two.

One call removed all of it at once: there is no second parser left to disagree
with the first. `python src\selftest.py text` was retired with it —
`python src\selftest.py extract` covers what both routes now share (4.11).


Codes absent from the master are still skipped here, so a
current master matters much more on this path.

Deliberately **not** implemented, and it should stay that way: password stripping
(pypdf `decrypt("")`, qpdf re-save) and UI scraping (SendKeys Ctrl+A/Ctrl+C, screenshot
+ OCR of the viewer window). Those defeat the control rather than working within it,
which is an audit problem regardless of intent. Everything in the PDF ACCESS section of
`src\of_pdf.py` fails closed: if the authorised application refuses, OrderFlow reports
it and stops.

### 6.7 The ERP Order Upload template — `config\erp_template.XLSX`

The last step of the pipeline: `erp_excel` opens the template, keeps its header row
and formatting untouched, and writes one row per order line below it.
`python src\selftest.py erp` covers all of this.

**Columns are found by HEADER NAME, not by column letter.** `column_map()` reads the
template's header row and resolves sixteen fields — PO, sales org, distribution channel,
division, sold-to, ship-to, material, quantity, **the P/O date**, unit price **and the five
Ship-To details plus the Sold-To name**, plus the **currency of that unit price (BF)** — so a form that has
been relabelled or re-ordered still receives
each value in the column that carries its header. Only when a header cannot be found at all
does a field fall back to the position this form has always used, and that fallback is
printed (`[ERP] column cost: no matching header, using column 57`), so it is visible in the
log rather than silent. The header row itself is located by looking for those names
(`header_row()`), so a title or instruction block above the header is tolerated.

| Field | Header on the shipped form | Column | Fallback | Value |
|---|---|---|---|---|
| PO number | `P/O No.(M)` | A (1) | yes | the PO |
| Sales Org. | `Sales Org.(M)` | C (3) | yes | **always `3101`** |
| Distr. Channel | `Distr. Channel(M)` | D (4) | yes | **from the pair's TYPE** — exact `Builder`→`11`, else `10` (6.7.1) |
| Division | `Division(M)` | E (5) | yes | **always `00`** |
| Sold-To | `Sold To Party(M)` | F (6) | yes | the account number chosen on screen |
| Ship-To | `Ship To Paty(O)` | G (7) | yes | the account number chosen on screen |
| Material Code | `Material(O)` | H (8) | yes | the extracted code |
| Quantity | `Sales Quantity(M)` | I (9) | yes | `""` when the document printed none |
| P/O Date | `P/O Date(O)` | M (13) | yes | **the email's received date** — written as a real date, so the template's `mm-dd-yy` applies. Empty on Quick Convert (no mail) and when the date cannot be read |
| Ship-to Name | `Ship-to Name(O)` | N (14) | yes | master `SHIP_TO_NAME` of the pair (6.7.1), **editable per order** |
| Ship-to Name 2/3/4 | `Ship-to Name 2/3/4(O)` | O/P/Q (15/16/17) | — | **typed per order**, folded on screen |
| Ship-to Address | `Ship-to Address(O)` | R (18) | — | **typed per order** (no master fallback) |
| Ship-to Street 2–5 | `Ship-to Street 2–5(O)` | S/T/U/V (19–22) | — | **typed per order**, folded |
| Ship-to Postal Code | `Ship-to Postal Code(O)` | W (23) | — | **typed per order** (text!) |
| Ship-to City | `Ship-to City(O)` | X (24) | — | **typed per order** |
| Ship-to Region | `Ship-to Region(O)` | AZ (52) | — | **typed per order** from a state list, folded |
| Sold-to Name2 | `Sold-to Name2(O)` | AI (35) | yes | master `SOLD_TO_NAME` |
| Unit price | `EDI1 condition value(O)` | BE (57) | yes | `""` when the document printed none |
| Unit price currency | `EDI1 condition currency(O)` | BF (58) | yes | **always `USD`** |

Note the spelling: the form says **"Paty"**, and the older revision called column BE
**"Cost"** — both spellings are accepted, which is exactly why the lookup is by name.
Aliases are deliberately loose about punctuation and the `(M)`/`(O)` suffix, so
`Sales Org.`, `Sales Org`, `Sales Organization` all resolve to column C.

⚠️ **BF's aliases name the EDI1 column specifically** (`EDI1 condition currency`,
`Condition Currency`) and deliberately do **not** include a bare `Currency`. The form has
**two** currency columns — BD `Currency(O)` at 56 and BF `EDI1 condition currency(O)` at
58 — and BD comes first, so a bare alias would match BD and the USD would land in the wrong
field. Only BF is written; BD is left untouched.

- **`3101`, `00` and `USD` are constants, not lookups** — `SALES_ORG` / `DIVISION` /
  `CURRENCY` in the ERP EXCEL section of `src\of_erp.py`, applied in `write_line()`. They
  are written as **text**, which matters for `00`:
  written as a number it becomes `0`, a different sales area to the ERP. For the same
  reason `TEXT_FIELDS` covers every code column — `po`, `sales_org`, `distr_channel`,
  `division`, **`currency`** and the five master-fed text columns (`sold_to_name`,
  `ship_to_name`, `ship_to_address`, `ship_to_city`, `ship_to_zip`) — all of them may start
  with a zero or must not be rounded.

- **The template must be a blank form.** Any row under the header is treated as an
  order line and copied into every generated file. The template in this snapshot was
  produced from a previous Order Upload file by the since-deleted
  `.workbuddy\install_erp_template.py`, which cleared the data rows and verified the
  headers before installing it. No tool in the tree rebuilds it now: if the headers
  change in ERP, copy a fresh blank form out of the portal and let
  `validate_template()` accept it, or write a replacement builder.
- **A template that is not this form is refused** (`validate_template()`), instead of
  its data being written into whatever happens to sit in columns 1/8/9 — a value the
  ERP might accept as a different field.
- **A missing quantity or price leaves the cell EMPTY**, never `0`: a 0 quantity is a
  real order line to the ERP. ⚠️ **The currency is the one exception** — it is a constant,
  not data, so BF is filled with `USD` on every line, including one whose price the
  document did not print. A currency next to a blank price is a half-filled row the ERP
  would reject, and a person correcting it by hand is exactly the work this tool removes.
  `write_line(..., currency=None)` writes the constant; pass `""` to leave it blank.
- **Column M ("P/O Date") is the email's received date**, not a date parsed off the PO:
  the mail row is the one source that always has it, and it is what the order desk keys
  in today. It is written as a **real date**, so the template's own `mm-dd-yy` format
  applies, rather than as text someone would have to convert. `_po_date()` accepts
  `2026-10-14T17:20:58`, a space instead of `T`, or a bare date, and returns `""` for
  anything it cannot read - so an unparseable value leaves M **EMPTY** instead of
  writing a wrong date.
  ⚠️ **Quick Convert has no mail**, so M stays empty there rather than being filled with
  today's, which would be a guess. The date reaches the writer through
  `server._master_values()`, which has to keep `received_at` on the mail dict - strip
  that and M goes blank everywhere with no error. (The same function is where the typed
  Ship-To block travels - it dropped that block for good until 2026-10-20; see the
  warning in 6.7.1.)
- `template_path()` accepts both `erp_template.XLSX` (how the file is actually named)
  and `erp_template.xlsx` (how `TEMPLATE_REL` spells it) — Windows hides the
  difference, a case-sensitive filesystem would not.
- Quick Convert writes the **P/O No.** as well (the form marks that column mandatory,
  and the number is on screen). Only unticked lines, or lines without a Material Code,
  are skipped.

#### 6.7.1 Where the master-fed columns come from — the composite key

Once F (Sold-To) and G (Ship-To) are known, the Ship-To master (6.2) still supplies
**three** columns. The key is the **pair**, not either code on its own:

```
(SOLD_TO_CODE, SHIP_TO_CODE)
    AI  Sold-to Name2         <- sold_to_name
    N   Ship-to Name          <- ship_to_name   (editable per order)
    D   Distr. Channel        <- from TYPE: exactly "Builder" -> 11, else 10
```

**The address columns are NOT taken from the master any more** (changed 2026-10-19).
R, S–V, W and X are typed per order on the Inbox row / Quick Convert card, and AZ
(Ship-to Region, the state) is chosen from a list built from the master's own
`state` values. The reason is in the data: the master holds the *billing site* of a
pair, and the delivery address printed on a PO is routinely somewhere else — a job
site, a store, a one-off drop. Copying the master's street into R put the wrong
address on real orders, and the old "empty means use the master's" fallback made the
blank look like consent. N keeps its default because it names the account rather
than a place.

The six typed fields and their headers:

```
N   Ship-to Name        O/P/Q  Ship-to Name 2/3/4
R   Ship-to Address     S/T/U/V  Ship-to Street 2..5
W   Ship-to Postal Code X      Ship-to City
AZ  Ship-to Region (state, chosen from a list)
```

On screen only **N** and **R** are shown per row; the other ten sit behind a
"More ship-to fields" disclosure in the address cell, because twelve inputs on every
Inbox row would make the table unreadable and most orders need nothing beyond N/R.

⚠️ **The block has to survive two hops to reach the file** (both were broken once, fixed
2026-10-20):

1. **`server._master_values()` must carry it.** Confirm builds the Order Upload from that
   function's return value, and it used to assemble a fixed five-key dict
   (`po_number, ship_to, sold_to, customer, received_at`) — so every typed field was
   dropped on the floor and the file came out with R/S–V/W/X/AZ **empty while the boxes on
   screen were filled**. It now copies every name in `store.SHIP_DETAIL_FIELDS`, which is
   the same tuple the store uses for the columns: add a field there and it travels, with
   no second list to forget. Regression tests: `selftest.py` 2c5b/2c5c/2c5d (the last one
   runs row → `_master_values` → `build_upload` → the workbook, i.e. the colour of the
   actual bug; 2c6 only proved the writer accepts the row when handed it directly, which
   is why the suite stayed green while the app was broken).
2. **The box saves on `onchange`, i.e. on blur — the same click that starts Confirm.**
   The save is a separate `/api/update` request, so on a slow disk the file could be built
   from a row that did not have the address yet. `act()` therefore sends the on-screen
   block as `body.ship` with Confirm; `server._typed_ship(body)` accepts **only** those
   twelve names, and `_persist_typed_ship()` writes them to the row *before* extraction
   starts, so the file and the row can never disagree. A cleared box is written as `""`
   there (the file skips empties, the row must lose the old address). Tests: 2c7b.

`ship_master.site(settings, sold_to, ship_to, pairs=None)` is the single entry point and
returns **`(info, conflict)`**:

- **`(None, False)` — the pair is not in the master.** The three cells stay **EMPTY** and the
  console says
  `[ERP] no Ship-To master row for Sold-To 5199939 / Ship-To 9999999 — N, AI and D left empty`.
  Half an address is worse than none: the ERP would accept it.
- **`(info, True)` — the pair repeats with DIFFERENT details.** The three stay **EMPTY** and
  the console names it:
  `[ERP] Sold-To 1400200 / Ship-To 3912418 appears more than once in the Ship-To master with different details — N, AI and D left empty`.
  `conflicts()` decides this by comparing `ST_PAYLOAD = (sold_to_name, ship_to_name, address,
  city, zip, type)`: a pair listed twice with **identical** details is simply the source
  listing it twice and resolves normally. In the 7,422-row master shipped with this
  snapshot that is **24 conflicting pairs** (and 24 pairs repeat at all).
- Otherwise `info` carries those six fields **plus `domain`, resolved through
  `domain_of()`** (6.2) — the pair table no longer stores one — and D is computed from
  `info["type"]` by `channel_for_type()`.

**Why the pair and not the Ship-To alone.** A Ship-To code is **not** unique in the pair
table — 5,537 distinct codes spread over 7,422 rows, with many codes owned by more than
Sold-To. Looking a code up on its own would have to pick one owner, so the pair is what is
matched, and a code that appears under several pairs simply means the user must pick the
right row (the drop-downs in 6.7.2 present exactly the pairs the table carries).

**Builder is exact.** `channel_for_type(v)` compares `_clean(v).lower() == "builder"`. The
real master also carries `Regionals`, `BBY`, `Wayfair`, `Accrual`, `Builder Others` and a
literal `NULL` — **all of those are 10.** A stub that merely *contains* "Builder" would
quietly book those orders into the wrong sales area, so the comparison is equality, and it
is asserted (`selftest.py erp` has ten `channel_for_type` cases).

**Maintained in Customer Master.** There is nothing to type: the grid is the master, and a
cell saves as you leave the box (`/api/master_set`). To fix a conflict, edit one of the two
red rows until it agrees with the other (or delete one) — the red clears as soon as
`conflicts()` stops reporting the pair. From the Unmatched card, **+ Add a Ship-To row**
adds a row carrying just the domain so the codes can be typed next to it.

**Nothing to carry over.** Because the channel is derived and not stored, an ERP re-upload
(`/api/erp_upload` **REPLACES** the whole table) cannot lose anything hand-typed — there is
nothing hand-typed to lose. That is the whole point of the 2026-10 refactor: the earlier
model kept a channel per Ship-To in `config\erp_accounts.json` and needed `fold_channels()`
plus `channels_carried` bookkeeping to survive a re-upload.

#### 6.7.2 Choosing the account numbers — Sold-To / Ship-To searchable boxes

Same reason as above: **one domain owns many (Sold-To, Ship-To) pairs**, so F and G cannot
be filled from the customer name alone. Both screens that build a file show a real
searchable box (a combo, since 2026-10-28 — see the last bullets) for Sold-To and Ship-To
rather than a text field.

- **Options are keyed by DOMAIN**, which is the identity: `POST /api/party_options`
  `{domain, sold_to}` → `{domain, sold_tos: [...], ship_tos: [...]}` from
  `ship_master.sold_options(settings, domain)` and `ship_options(settings, domain, sold_to)`.
  `ship_to` is **narrowed by the chosen Sold-To**, because the two together are the key.
  The old `customer` parameter spelling is still accepted.
- **…and the Inbox asks for the WHOLE PAGE in one request (2026-10-28).**
  `POST /api/party_options {domains: ["abt.com", "ferguson.com", …]}` →
  `{options: {domain: {domain, sold_tos, ship_tos}}}`. The single-`domain` form is still
  there — Quick Convert and the Reopen card use it — and the batch route is the same two
  calls in a loop, so nothing can drift between them.
  ⚠️ **The account lists used to take seconds to fill in**, and the cause was not the
  network. `_pairs_by_domain()` grouped all 7,418 pair rows by domain *on every call*, and
  each call re-read and re-parsed the 2.8 MB `ship_to_master.json`; one
  `/api/party_options` calls it twice (`sold_options` and `ship_options`), and the Inbox
  fired one request per domain — one per customer on screen. Measured on a page with 12
  rows / 9 domains the master knows (headless Chrome against a real server, clocked by the
  server because `--virtual-time-budget` makes `performance.now()` return virtual time):

  | | requests | wall time | server CPU | `<option>` DOM |
  |---|---|---|---|---|
  | before | 9 (one per domain) | **1,572 ms** | **8,015 ms** | 4,699 |
  | after | 1 (batched) | **75 ms** | 75 ms | 4,699 |

  Three things did it, in this order of importance: the index is **memoised** on
  `master_key()` (`_pairs_by_domain`, invalidated by either master file's mtime+size — and
  by the folder, or two temp masters with identical stats share one index); the page asks
  **once**; and `ship_conflicts` + `ship_master.states()` are cached on the same signal.
  `states()` is worth a note of its own: it *claimed* to be memoised but built its cache key
  with `st_path(settings).stat()`, and `st_path()` returns a **string** — the AttributeError
  was swallowed by a bare `except`, so the memo never engaged and every dashboard request
  re-read the 2.8 MB file for 52 state codes. It now uses `_stat_key()`.
- ⚠️ **Send `domain` as a list-free string.** `urlencode(..., doseq=True)` on the export
  side is mandatory for the repeating `code` / `customer` parameters; here the body is JSON,
  so a list would arrive as `"['abt.com']"` and match nothing — which looks exactly like a
  server bug.
- **Inbox** — F and G are searchable account boxes per row (`partyCell(m, 'sold')` /
  `partyCell(m, 'ship')` in a wider `td.ptd`), and an **Address** text box sits beside them
  (`addrCell(m)`), showing the `SHIP_TO_ADDRESS` of the picked pair.
- **The Address box is editable per order.** `rowAddr()` saves what is typed to the mail
  row's `ship_to_address` column and `build_upload()` lets it **override** the master's
  address in the ERP form. It is the per-order escape hatch: a one-off delivery address, or
  a site the master has wrong.
  ⚠️ **An EMPTY box means "use the master's", not "no address".** The box is muted while it
  still shows the master's value, and clearing what was typed falls back to that value
  rather than writing a blank into column R - so delete is safe and reversible.
  `rowAddr()` stores only what the user typed: saving the master's own value back as an
  override would pin the address to the master row as it is today and stop the order
  following a later correction to that row.
  The column is added by a migration in `store.connect()` and `ship_to_address` is in
  `EDITABLE_FIELDS` so `/api/update` will write it. Strip either and the box silently stops
  saving.
- **Quick Convert** — a Domain / Sold-To / Ship-To picker row sits above the review table
  (`qPartyRow()`), and the chosen pair is what gets posted. It only appears in the **full**
  version; the simple four-column sheet has no account columns to fill.
- **Options are fetched on demand** — `needParty(mails)` collects the domains on screen that
  `domainKnown()` recognises and that are not cached, calls `/api/party_options` **once** for
  all of them, then `patchParties(domains)` swaps the loading placeholders in a single pass
  over the document. `PARTY` is the cache, `PARTYQ` is what stops a re-render from asking
  twice while the answer is in flight.
  ⚠️ **`forgetParty()` must be called after any write to the master** (upload, + Add row,
  cell edit, delete, Clear): the options *are* rows of that table, so a cached list
  describes a table that no longer exists. `rowDomain(m)` is the domain a row is matched by,
  falling back to the sender's own domain for a mail that predates the master.
- **A cell whose list is still on its way shows three pulsing dots, not "…"** (2026-10-28).
  The markup is `dotsHTML()` + `.dots-container` / `.dots-sm` (a Uiverse snippet), and the
  cell keeps its `data-pwait` attributes so `patchParties()` can rebuild it in place.
  ⚠️ **The dots rules are scoped to `.dots-container .dot`.** The snippet as published
  styles a bare `.dot` — and this page already uses `.dot` for the 9px status pip in every
  Inbox row, so pasting it in unchanged turns every status pip into a 20px throbbing blob.
  `.dots-sm` (6px) is what keeps the placeholder inside a table cell instead of making that
  row taller than its neighbours. The same component, at full size, is the **first paint**:
  `#content` ships with the dots so the frame before `/api/dashboard` answers is not blank.
- **The picker is a SEARCHABLE COMBO BOX, not a `<select>` (2026-10-28).**
  `comboHTML()` draws `<span class="pcombo">` + `<input class="pcinput">` + a caret;
  `pcOpen` / `pcFill` / `pcKey` / `pcCommit` are the behaviour. Why it changed: one customer
  owns thousands of sites (`ferguson.com` 2,246; `rentacenter.com` 1,861), so every one of
  them used to be an `<option>` — **4,699 `<option>` elements on one Inbox page**, rendered
  so that one could be looked at, inside a 120px-wide cell.
  - **The candidate list is built when the box is opened**, filtered as you type (code
    prefix → code substring → name / ZIP / TYPE) and **capped at `PC_MAX` (50) rows**; the
    header says how many were found and how many are shown. Opening does **not** filter by
    the value already in the box — that would leave exactly one row — it shows the whole
    list with the current value highlighted, and scrolls the window to it when the value
    sits past row 50.
  - **It accepts a number typed by hand.** This is not a hole in the accuracy rule (1): that
    rule is about what the EXTRACTOR proposes. A human typing the account the customer gave
    them is the authority on that account. A number the master does not carry turns the box
    **amber** and its `title` says it will be written as typed, and while it is being typed
    the first row of the popup is **`<number> · use as typed`** — disclosed, never guessed,
    never blocked.
  - Keyboard: ↑/↓ move, Enter takes the highlighted row (or, with nothing highlighted, keeps
    what is typed), Escape puts back what was saved rather than clearing the field, Tab
    closes. `change` on blur saves, guarded by `data-pcval` so an untouched box writes
    nothing.
  - ⚠️ **The popup is `#pcmenu`, shipped in the page at the end of `<body>`.** Not inside the
    cell: `table.fixed td { overflow:hidden }` would clip it, and the table scrolls sideways
    inside `.cardbody`. It is `position:fixed` with viewport coordinates and a high stacking
    level; `pcPlace()` clamps it to the visible window and flips it above the input when
    needed. This avoids a Ship-To menu being positioned outside the visible card after its
    horizontally scrolled Sold-To row changes. It is **closed on any scroll, resize or
    outside click** — a popup anchored to a rect cannot follow its cell.
  - The Quick Convert card uses the same component (`qPartyCombo`, `data-pquick`), where a
    commit calls `qPartySet()` instead of saving to a mail row.
- **Each row of the popup leads with the account number and carries the ZIP —
  `1393019` · `ZIP 38134 · ch 11 · ABT WAREHOUSE`** (`pcMeta`, 2026-10-27). A bare code does
  not tell two sites of one customer apart while the list is open, and the ZIP is the
  shortest thing that does. The **value** written is never the label: the row's bold part is
  the code, `pcPick` takes `s.code`.
  The chosen site's ZIP also sits on a one-line caption under the box (`siteZip()` /
  `zipCapHtml()`), which is what makes "is this the Memphis yard?" answerable without
  opening the list at all.
- ⚠️ **That ZIP is DISPLAY ONLY. It must never reach the ERP.** N/R/W/X/AZ come from what the
  PO printed, or from what was typed on the preview (4.5, 6.7.1). The master's ZIP is read
  by `siteZip()` and used in exactly two places: the candidate row (`pcMeta`) and the
  caption.
- **Precedence** (`rowPick()`): the value already saved for the row → the matching pair from
  the master for this domain → blank. Blank is a legitimate state; the writer then leaves the
  cell empty rather than inventing an account.
  ⚠️ **A stored number the master no longer carries is still SHOWN** (2026-10-28), amber,
  rather than rendered as an empty box: the row will write that number into F/G, so a blank
  input would read as "this order has no account" while it quietly keeps its old one. Only
  when the column holds exactly ONE number is it shown this way - a cell listing several
  ("123;456") stays blank and keeps the amber "several — pick one" warning, because picking
  one of them for the user would be a guess.
- Tests: `src\selftest.py` suite `ui` asserts the markup and both API paths — including the
  2026-10-28 combo (the `PC_MAX` cap, the "use as typed" row, opening without filtering,
  Escape restoring the saved value);
  `src\selftest.py erp` / `classify` cover the cascade in-process. Suite `p0` pins the
  2026-10-28 loading work: the batch call site, the route that answers a list of domains,
  `patchParties()`, the memoised `_pairs_by_domain()` (same object twice, rebuilt after a
  write) and that the dots rules stay scoped away from `.dot`. The retired
  `.workbuddy\domain_probe.py` used to drive the real endpoints end-to-end, including the
  Sold-To→Ship-To cascade and the "nothing for a domain the master does not carry" case.

### 6.8 Two output versions — full ERP form or simple four-column sheet

The same reviewed lines can be written two ways, and the user picks per machine with a
**split button** — one action that downloads/confirms in the version currently selected,
plus a caret that opens a small menu with the other one. It appears in both places that
build a file — the Inbox screen (what the ✓ Confirm button produces) and the Quick
Convert review card (what **Download Order Upload** produces) — and the choice is stored
as `erp_format` in `config\settings.json`, so it survives a restart and applies to both.

| | `full` (default) | `simple` |
|---|---|---|
| What it is | the Standard Order Upload form | a plain four-column sheet |
| Columns | all 106 kept as the template has them; **A C D E F G H I** (the order), **M** (the P/O date from the email), **N AI** (Ship-To name and Sold-To name, from the master), **O–Q R S–V W X AZ** (the Ship-To block, typed per order) and **BE + BF** (unit price and its `USD` currency) | `PO #` · `Material` · `Sales Quantity` · `Unit Price` |
| Source | `config\erp_template.XLSX` | generated with openpyxl — **no template** |
| File name | `OrderUpload_<PO>_<stamp>.xlsx` | `OrderUploadSimple_<PO>_<stamp>.xlsx` |

- **Both versions can be ticked at once (2026-10-27).** The choice is a **list**:
  `["full"]` (the default), `["simple"]`, or `["full", "simple"]`. One Confirm / one
  Download then writes **two files** from the SAME reading — the desk uploads the full form
  to ERP and keeps the four-column sheet for keying by hand, without paying for the
  document twice.
  - Server: `erp_excel.output_formats(value)` is the ONE place that decides what a value
    means (single value or list → ordered, deduped, never empty). `output_format()` survives
    as *its first entry* for the corners that can only draw one file; `is_simple()` now means
    **simple only**. `settings.erp_format` holds the list.
  - Writes loop: `run_extractor_multi()` (Confirm) and `/api/quick_export` each build one
    file per format and return `files: [{fmt, name, url}]`. `run_extractor()` remains the
    single-file wrapper. One version failing is reported beside the one that worked.
  - Storage: `mails.erp_file` is the primary (full when written), **`mails.erp_file2`** the
    second. Both are cleared by Undo, and `/api/openerp` takes `which` (1|2).
  - UI: the **same `.seg` switch** in all three places (step 3's two cards, the Read rows,
    Quick Convert) — same track, thumb and labels, but the inputs are checkboxes. The thumb
    sits left / right / **stretched across the whole track** when both are ticked. The last
    ticked one cannot be unticked (`Keep at least one version selected`): an empty choice
    has no file to write, and silently falling back to full would contradict the switch.
- **The split button is gone from the Order Upload side.** Its caret offered "the *other*
  version", which has nothing to point at once both can be ticked. Quick Convert now shows
  the switch plus one **Download Order Upload** button that writes everything ticked; the
  Master Data export cards still use a split button (there the choice really is one of two).


- **The same data, either way.** Both paths go through `prepare_lines()`, so
  quantity and price are cleaned up identically; only the workbook
  differs. `build_upload_lines()` / `build_upload()` take a `fmt` argument and dispatch,
  so a caller does not have to know which one ran, and both return the same shape.
- **`simple` needs no template** — which is also why it is a useful fallback: a template
  copied fresh from the ERP portal (and therefore DRM-protected again) blocks `full` on
  that PC, not `simple`.
- **A misspelled or missing format means `full`.** `output_formats()` only accepts
  something that starts with `s` as simple, so a typo cannot silently shrink the file
  that gets uploaded. An omitted format falls back to the saved `erp_format`, then to
  `full`; an all-junk LIST does the same. That is what keeps an older caller from changing
  behaviour by accident.
- Both land in `data\erp_upload\`; the file name says which version it is, and the
  screens show a **Full form / Simple** badge next to each generated file (the Quick
  Convert session list and the Order Upload list). Reopening a converted file from that
  list restores the version it was made in rather than switching to the current choice.
- Tests: `python src\selftest.py erp` (format mapping **and the list rules**, both files
  written from one set of lines, `run_extractor_multi` writing one per ticked version, the
  four headers and their order, writing with no template present, an empty quantity staying
  empty, `fmt` omitted still meaning the full form, the C/D/E values, and the channel
  resolving **from the Ship-To** to column D — 11a–11f in that suite) and
  `python src\selftest.py ui` (the switch in all three places, the thumb rule for both
  ticked, and that every writer sends the LIST rather than one value).
- ⚠️ `.workbuddy\make_sample_uploads.py` (which regenerated a matched pair from the real
  PO 95778 result so the two versions could be compared side by side) is **gone**. The
  equivalent is now the `erp` suite's synthetic result (4.11).

### 6.9 Master-data export — the mirror of the upload templates

**Three** Master-Data sets can be exported: **Material Codes**, **Ship-To Locations**
(the pair table) and **Domains** (the domain table). The requirement is the strong one —
the exported file must be the *twin of the upload template* so it can be re-imported with
**no edits at all** — and it must not be possible for the template, the export and the
importers to drift apart.

#### One schema, five consumers

`# SECTION: DATA SCHEMAS` in `src\of_master.py` is the **single list of columns**:

```python
DATA_SCHEMAS = {
  "materials": {title, endpoint:"mm_upload", prefix:"MaterialCodes", columns:[
     code→"Material Code" (text, required, hint="code"),
     product→"Product", cate1→"Type1", cate2→"Type2"]},
  "customers": {title:"Ship To Locations", endpoint:"erp_upload",
     prefix:"ShipToLocations", columns:[
       14 columns, in the ERP file's order — see the table in 6.2.
       sold_to_code→"SOLD_TO_CODE", sold_to_name→"SOLD_TO_NAME", ship_to_code,
       ship_to_name, address→"SHIP_TO_ADDRESS", city, zip→"SHIP_TO_ZIPCODE",
       dlv_plant, state→"SHIP_TO_ST", account_manager, district, region,
       type→"TYPE", sub_type]},
  "domains": {title:"Domains", endpoint:"domain_table_upload",
     prefix:"Domains", columns:[
       sold_to_name→"SOLD_TO_NAME" (the join key), domain→"DOMAIN"]},
}
```

Each column is `{key, header, kind, required, hint, width, title?}`, `kind` ∈
`KIND_TEXT` / `KIND_ENUM` / `KIND_NUMBER`. **Five consumers read the same dict**: the three
fill-in templates committed at the root (`Upload_Template_*.xlsx`), the export builder
(`build_export()`), and the start-up self-check — **plus the two on-screen grids**, which the
dashboard ships as `ship_columns` / `domain_columns`, so each table on the Customer Master
screen, its upload template and its export can never disagree. The **importers keep their own
parsing code** — that must not change, or a previously-good file would start behaving
differently.

⚠️ `materials` is now the **Product Mapping Table** shape (`FULL SKU` / `short skus` /
`MATERIAL GROUP` / `MATERIAL GROUP 2`, 4.15), not the old `Material Code` / `Product` /
`Type1` / `Type2` list, because that is the file the user actually uploads. `material_records()`
emits one row per **(FULL SKU, short SKU) pair** — a code with no short form gets a blank
short cell, and the ambiguous short SKUs are emitted once per competing FULL SKU, so the
export stays a faithful twin and a re-import re-derives the same ambiguity.

**`contract_ok(name)`** turns "the export must match the import" into an executable
contract, and now covers all three: for `materials` it checks each schema header against
`MAP_HEADERS` (so `parse_mapping()` would find it) and requires the `full` and `short`
columns to be present — without both, the mapping could not be read; for `customers` it
requires each schema header to
be one of the spellings in `ship_master.ST_HINTS` **and** every `ship_master.ST_KEYS` field
to have a column — so a renamed header, a missing column or a stray one is reported.
`serve()` prints `[WARN] export contract (…): …`; the template builder that used to abort on the
same failure is gone with it.

⚠️ The old **column-order trap is gone**: it existed because the Material-Codes matcher is
prefix-based (`t == hint or t.startswith(hint)`), so `"Sold To Name"` could be read as the
account-number column. The Ship-To importer matches headers **exactly** through `_hkey()`
(punctuation and the `(M)`/`(O)` marker ignored, but the words must be all there), so
`SOLD_TO_NAME` and `SOLD_TO_CODE` cannot be confused whatever the order. The header list is
still asserted against `ST_HINTS` rather than assumed.

Formats follow the same reasoning as ERP columns C/E: `KIND_NUMBER` writes `General` so a
15-digit account number is not rounded, everything else writes `number_format="@"` so a
leading zero — a postal code of `08861` — survives.

#### The endpoint

```
GET /api/master_export?set=materials|customers|domains&scope=all|filter&code=…&customer=…&q=…
```

- `set`/`scope` accept any spelling that starts the right way — `customers` **or `ship`**
  (the file is the Ship-To master, so either name picks it), `d…` picks the **domain** table,
  anything else `materials`; `filter`/`f…`. Anything unrecognised falls back to
  `materials` / `all`, so an omitted parameter can never pick the other file.
- `code` / `customer` may repeat and are honoured **only** under `scope=filter`. `customer`
  is a list of **domains**. `q` is the Customer Master **search box** text of the grid being
  exported, so "export what is listed" and the grid cannot disagree (`matches()` /
  `dm_matches()` is the shared predicate for each). ⚠️ `doExport()` reads the *right* box —
  it used `SHIP.q` for every non-materials set, so exporting the domain table filtered on
  the Ship-To search instead.
- ⚠️ **`urlencode(..., doseq=True)` is mandatory** for the repeating parameters, or a list
  becomes `"['Abt Electronics']"` — which matches nothing and looks exactly like a server bug.
- Response: the workbook as an attachment — `Content-Disposition: attachment;
  filename="MaterialCodes_<stamp>.xlsx"` / `"ShipToLocations_<stamp>.xlsx"` /
  `"Domains_<stamp>.xlsx"`,
  `X-Row-Count: <n>`, the usual `no-store` / `Pragma: no-cache`.
- **Empty is an error, not an empty file**: `build_export()` raises
  `RuntimeError("There is nothing to export …")` and the route answers **400 JSON**. A
  filter that matches nothing does the same, **including a `scope=filter` with the search
  box empty** — the UI refuses that one before it navigates. Blank *required* cells in the
  sheet are filled `FCE4E4` so a problem is visible in the file, not only in a log.
  (Both customer schemas declare **no** required column: a pair qualifies by naming *any* of
  its identifying fields, which no single column can express — `parse_file()` and
  `add_row()` enforce it instead.)
- `customer_records()` emits **every row of the pair table, unchanged**, in the shape the
  importer expects, and `domain_records()` is its mirror for the domain table — both resolve
  through `domain_of()` / `dm_rows()` rather than re-deriving anything;
  `export_data(setting, name, scope, customers, codes, q)` is the single entry point and
  returns `(bytes, filename, count)`.

⚠️ **`export_data()` lives inside a block that looks like a duplicate.** The file is a
concatenation, and the Ship-To section's docstring sits immediately after `customer_records()`.
Deleting that "duplicate" block broke the whole route (`BadZipFile`, `X-Row-Count: None`).
**Diff before removing anything that looks repeated.**

#### In the UI

`exportSplit()` is an **Export** button plus a caret menu (**Export all** / **Export what is
listed**) on the Material Codes card and on the Ship-To grid card. `doExport()` builds the
query with `URLSearchParams` and then navigates to the URL, so the **browser** performs the
download. For `filter` it appends exactly what the list is currently showing — the listed
codes for materials (`shownCodes()` mirrors the table's own filter), and for the grid the
**search text** as `q`, because the grid filters on the **server** and enumerating thousands
of rows into the URL would be pointless. The Ship-To grid has **no** `shownCustomers()`
equivalent, and its filter travelling unchanged is the reason.

**The card must not clip.** `.card` carries `overflow:hidden` so the wide tables in
`.cardbody` take the card's rounded corners. The split menu is an absolute panel that drops
*below* its button, and both export buttons sit at the very bottom of their card, so that
same rule made the menu **vanish**. It is switched off per card by
`.card:has(.split) { overflow:visible; }` (plus an explicit `.ov` class as a belt-and-braces
marker), and an open menu is lifted above later cards with
`.split:has(.splitmenu:not([hidden])) { z-index:70; }` — `.split` otherwise has no stacking
context, so its inner `z-index:60` only orders it against its own siblings. Inbox's copy
of the split button lives in `.filterbar`, outside any card, which is why it never showed the
bug; Quick Convert's is inside a card and is covered by the same `:has()` rule. **The Ship-To
grid's card holds the search box and the split button, so it needed the same treatment** —
verified with the retired `.workbuddy\ui_preview.py` (`?tab=mastermenu`); there is no cover for
that visual check in the tree now.

Menu ids differ by builder: `exportSplit()` emits `exp-<id>` (`exp-codes`, `exp-ship`) while
`fmtSplit()` emits `split-<id>` — the caret's `onclick` and the menu `id` must share the
prefix, or the menu silently stays hidden.

#### Verification

⚠️ **None of the four probes listed below is in this snapshot** (4.11, section 7). They are
recorded here as the specification of what the route must still do. What can be run now is
`python src\selftest.py excel` (the parser-level half) plus the start-up
`of_master.contract_ok()` warning, which checks that the schema and the importers still
agree — it is what `serve()` prints as `[WARN] export contract (…): …`.

- `python .workbuddy\export_probe.py` (49 checks) proves the round trip through the **real
  parsers**: 937 materials compared field by field; **all 7,422 Ship-To rows re-parsed**, with
  the **(Sold-To, Ship-To) pair** and all 15 fields identical and the sheet's text format
  intact; export → import → export returns exactly the same records; a filtered export is a
  subset; an empty list raises; required columns, enum folding and the `.0` / `1.472521E+06`
  / `01` cleaning behave.
- `python .workbuddy\export_http_probe.py` (35 checks) drives the real route: status,
  content type, `Content-Disposition`, `X-Row-Count`, `no-store`, sheet name, headers, that
  the **active sheet is the data sheet**, that `scope=filter` by domain and by search text
  contains only the matching rows and **still re-imports**, that an empty result is a **400**,
  and every spelling of `set` / `scope`.
- `python .workbuddy\upload_template_probe.py` (56 checks) keeps the templates themselves
  honest, since they are built from the same schema: the 15 headers, the text formats, four
  sample rows parsed back with the right composite keys, the blank row skipped, a non-master
  file refused, and the whole grid/edit/clear API. ⚠️ That was **two** templates with a
  Domain column; there are **three** now and the pair template has no domain column, so the
  check list would have to be re-written against the two-table shape.
- `node .workbuddy\export_wiring_probe.js` (7 checks) evaluates the real `shownCodes` /
  `doExport` in a stub DOM and asserts the URL shapes, the encoded search text, and the
  "nothing listed → alert, no navigation" cases, so a broken menu→export handler is caught
  without a browser.

### 6.10 Dead-code cleanup (2026-10-06) — behaviour-preserving

A pass over the sources with no functional change. What went, and the rule each case teaches:

- **`src\orderflow.py`**: removed a whole **duplicated `# SECTION: DATA EXPORT`** block
  (the older of two pastes, ~180 lines Python silently shadowed anyway) and the dead local
  `gone` in `do_POST`. **Lesson:** `export_data()` had only ever been defined **inside that
  older block**, so deleting it broke `/api/master_export` (`BadZipFile`, `X-Row-Count: None`).
  Diff two "duplicate" blocks before deleting one — the later paste is not always a superset.
  The function was restored from `.workbuddy\backup\orderflow.py.before_dedup`.
- **`src\report.py`**: removed six JS helpers that had **no call site at all** — `hasParty`,
  `chipList`, `assignSender`, `upd`, `historyTable`, `renderDuplicates`. `initRail` was **kept**:
  it is written `(function initRail(){…})()` and runs immediately, so "no call site" is wrong for
  an IIFE. Backup: `.workbuddy\backup\report.py.before_deadjs` (166,495 → 164,133 bytes).
- **`.workbuddy\accuracy_probe.py`**: dropped an unused `import os`.
- **Deliberately left alone** (look like candidates but are load-bearing): in-function
  `import pythoncom` (lazy COM import), the `found, new, empty, latest` unpacking (the
  `_run_pipeline` contract — the caller uses `latest`), the thin wrapper pairs each with its
  own SECTION constant and facade name, and `.card.ov` (kept as an explicit fallback for
  engines without CSS `:has()`).
- **Not dead:** `CodeExtract\devtools.py`'s `t_*` functions are dispatched by a `RESULTS`
  registry, and `engine.py` helpers are called cross-file by `devtools.py` (no probe does that
  any more).

### 6.10.1 The 2026-10-07 Ship-To refactor — what it deleted

The customer model was replaced, and with it a lot of code. Everything below is **gone**;
a reference to any of it is a bug, not a deprecation:

| Deleted | Why it can go |
|---|---|
| `config\customer_master.csv`, `config\erp_accounts.json` | one customer table now (`config\ship_to_master.json`); the channel is derived, not stored |
| `classifier.load_master` / `save_master` / `add_domain` / `del_domain` / `add_customer` / `rename_customer` / `set_field` / `set_erp_accounts` / `set_po_regex` / `FIELDNAMES` / `_split` | the CSV they read and wrote no longer exists |
| `add_member` / `update_member` and every per-member row | identity is the domain; there are no people to store |
| `erp_accounts` (the whole module) — `parse_file`, `upload`, `save`, `load`, `ship_lookup`, `distr_channel_of`, `fold_channels`, `set_distr_channel`, `channel_for`, `channel_note`, `first_code`, `normalize_type`, `acct_*` | the six ERP columns come from the Ship-To master's composite key, and D from `TYPE` |
| `/api/master`, `/api/domain_add`, `/api/domain_del`, `/api/assign`, `/api/account_distr`, `/api/customer_new`, `/api/customer_rename`, `/api/customer_accounts`, `/api/erp_search`, `/api/erp_delete`, `/api/po_rule` | no cards, no chips, no claims — a claim is a row (`/api/master_add`) |
| `report.py`: `renderMaster`'s card UI, `claimSelect`, `claimDomain`, `updM`, `addDomain`, `dropDomain`, `updRule`, `newCustomer`, `typeChip(s)`, `PICK`/`pickParty`/`pickRow`/`pickFilter`/`pickAllShip`/`pickToggle`/`pickApplyList`, `renameCustomer`, `ACCPICK`, `linkAccounts`, `closeAcc`, `accSearch`, `accToggle`, `accCount`, `delAccount`, `unlinkAccount`, `setChannel`, `saveAcc`, `erpCard`, `shownCustomers`, `CUSTQ`, and the `partyKeys()`/`masterFor()`/`ship_to_list` fallbacks | replaced by the Ship-To grid (`loadShip`/`shipTable`/`setShipCell`/`addShipRow`/`delShipRow`/`clearShipMaster`/`uploadErp`) and `domainKnown()`/`rowDomain()` |
| `data["master_conflicts"]` in the dashboard payload | the identity list is one entry per domain, so `domain_conflicts()` can never fire from it and `report.py` had no consumer left (see 6.2.1) |
| ~300 lines of CSS (`.mgrid` `.mcard` `.chip` `.domx` `.acclist` `.pickwrap` `.modalwrap` `.tchip` `.chnrow` …) | nothing emits those class names any more; `.shipbody` / `.shipwrap` / `.shiptable` / `.scell` / `.shipconf` replaced them |
| `Upload_Template_CustomerAccounts.xlsx` | replaced by `Upload_Template_ShipToLocations.xlsx` (moved to `.workbuddy\backup\old_config\`) |

**Kept on purpose:** `domain_owners()` and `domain_conflicts()` (the "exactly one owner" rule,
still the honest answer if the model ever allows two claims; `selftest classify` covers them),
`PUBLIC_DOMAINS` / `public_domain()`, and `PO_PRESETS` — minus the per-customer rule.
- **How to check the embedded JS**: never regex `<script>` straight out of `report.py` — it is a
  Python string with `\\'` escapes, so `node --check` reports phantom syntax errors. Render
  first with `report.render_page()`, then extract.
- **Regression after the pass:** `python src\selftest.py` ALL SUITES PASSED; every probe was
  green at the time (export 45 / export_http 25 / upload_template 40 / erp_format 22 / sidebar 84 /
  serve 12 / domain 31 / erp_column 30 / scan 14 / accuracy 8 / JS wiring 5). **All of those probes
  except `port_probe.py` are gone from this snapshot** (section 7) — the numbers are the record of
  what the pass proved, not commands that still run.

---

## 7. Dead-code cleanup (2026-10-11)

Everything below was **proven unreferenced** before deletion — a whole-word search across every
`.py`/`.md`/`.bat`/`.json`/`.txt`/`.js`/`.csv` in the tree, plus a check for dynamic use
(`getattr`, `globals()[...]`, string names, decorator registries). This repo has **no git
history**, so the deletions are not recoverable; the two things that were load-bearing but
looked dead are recorded here so they are not "cleaned up" again.

**Deleted — code (95 lines):**

| What | Where | Why it was dead |
|---|---|---|
| `render_available()` | `engine.py` | superseded by `render_backend()`; no caller |
| `ocr_zones()` (plural) | `engine.py` | the singular `ocr_zone()` is what every path calls |
| `best_code_for_row()` | `engine.py` | "compatibility wrapper" over `select_row_codes()`, which is called directly in 2 places |
| `clean_material_code()` + `MC_NOISE` + `MC_GLUED_LABEL` | `engine.py` | the zone parser uses `clean_code_cell()`/`is_code_cell()` instead |
| `process_folder()` | `engine.py` | the retired CLI entry point; the dashboard calls `extract_material_codes()` per file |
| `current_language()`, `set_language()` | `devtools.py` | language is read once into `_CURRENT` by `_load_language()`; nothing switched it at runtime |
| `FILE_HEADERS` | `devtools.py` | leftover vocabulary, no reader |
| `import io` | `engine.py` | never used |

**Deleted — files:**

| What | Note |
|---|---|
| 15 × `._*` AppleDouble files | macOS metadata (`Mac OS X` magic), not project content |
| `data/orderflow.db` | 0 bytes, referenced by nothing (`settings.db_path` points at `po_mail.db`) |
| `CodeExtract/data_cache/*.json` (24) | extraction cache; **rebuilt on first run**. ⚠️ it is not *only* a cache — `of_master.pending_reviews()` reads the `review` arrays to build the "Unknown codes" card, so that card is empty until something is extracted again |
| `CodeExtract/data_cache/_selftest/` | empty scratch dirs left by earlier test runs (`devtools.py` removes its own on exit) |
| `.workbuddy/backup_20261010/*.bak` (4) | pre-split originals; the refactor is done and covered by the suites |
| `.workbuddy/split_orderflow.py`, `analyze_split.py`, `memory/` | one-off tools and work notes; `prepare_handover.bat` already deleted `memory/` at release |
| `data/erp_upload/*.xlsx` (2) | sample output from PO 95778; regenerated by Confirm |
| `Upload_Template_CustomerAccounts.xlsx.new` | the superseded template (6.10.1); the live one is `Upload_Template_ShipToLocations.xlsx` |
| `data/po_mail.db` | empty (0 mails); recreated by `store.connect()` on start |
| `docs/DRM_meeting_script.md` | the demo script; `DRM_meeting_notes.md` (the IT/security brief) is kept |

**Kept, although nothing references them** — do not delete these as "dead":

- `port_probe.py` — named in the README test list.
- `CodeExtract/data_upload/*.pdf` (5) — the reference PDFs `engine_baseline.py` measures,
  named by `prepare_handover.bat` as kept on purpose. (`golden_set*.xlsx` was deleted
  2026-10-19 with the golden-set scorer.)
- `UPLOAD_DIR` / `OUTPUT_DIR` in `engine.py` — `process_folder()` was their main reader, but
  the start-up `for d in [CACHE_DIR, UPLOAD_DIR, OUTPUT_DIR]` still creates those folders.
- `src/version.py` — read by `report.render_page()` for the sidebar build id. It is
  **derived**, not maintained: `build_id()` takes the newest source mtime plus the first
  6 hex of a content sha1, so the stamp cannot go stale (that is what used to happen —
  a hard-coded `BUILD` stayed at the day it was written for a month).
- The stdlib imports repeated in every `of_*.py` — see 2.1. They look unused inside their own
  module, but `orderflow.py` re-publishes each module's globals and binds them into the facades
  (`store.sqlite3`, `collector.hashlib`, `pdf_access.shutil`, …), so removing one can break a
  caller in another module. Verify with `_FACADE_MISSING` before touching them.

**Verified after the cleanup:** `python src\selftest.py` **ALL SUITES PASSED** (52 assertions over
13 suites), `CodeExtract\devtools.py` **53 passed / 0 failed**, and a fresh start (no DB, no cache)
boots, recreates the schema, rebuilds `material_codes_reference.csv` and serves `/api/dashboard`.

⚠️ **That run was made on 2026-10-20 under a restricted harness in which the suites could not
create their own temporary directories** (`PermissionError` on `...\ofx_xxx\config`, from a
deny-all entry inherited by `tempfile.mkdtemp()`). They passed from a normal console. If they
fail that way on your machine, that is the first thing to check — not the code.

---

## 8. Backlog
- [ ] **Measure the API against the retired engine.** Run both over
      `CodeExtract\data_upload\` and compare line by line. Until that is done,
      "the API is better" is an assumption. The engine is in `CodeExtract\_legacy\`
      and its README says how to run it again.
- [ ] **Cover the API call itself.** `selftest.py extract` runs offline by
      design, so nothing automated catches a prompt regression, a model change
      or a schema drift. A recorded-response fixture would.
- [ ] **A wrong number is still the open risk** (4.9 #1). The gate proves the
      code; nothing proves the quantity. Cheapest real mitigation: show
      `source_line` next to every line on the review screen so a human can
      check it in two seconds.
- [ ] **AJ Madison scans** (`PO 25407327`, `PO 25475097`) — the two worst
      scans in the corpus. They are the best test of whether the API really
      handles a bad scan; run them first.
- [ ] **`scrub sidecars`** — every copy of the tree that comes from a Mac carries `._` files;
      `is_mac_sidecar()` skips them in the sweeps, but `data_upload\` should not carry them
- [ ] Re-verify PO# 0806601VWBN once the ABT Builder price sheet is uploaded
- [ ] Flow for a customer with **two accounts of the same type** (ABT has two Builder accounts): pick the account on the Inbox row → remember it for that customer
- [ ] Extend Quick Convert Excel header vocabulary after collecting customer layouts
- [ ] Switch to the OrderDesk@sea.samsung.com shared mailbox once ITVOC access is granted
