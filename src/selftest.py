r"""
selftest.py - every dashboard regression test in one file

Run:
    python src\selftest.py              every suite
    python src\selftest.py po           PO-number extraction rules
    python src\selftest.py lines        quantity / unit price / amount cross-checks
    python src\selftest.py ui           dashboard JavaScript syntax (node --check)
    python src\selftest.py excel        Excel PO reader
    python src\selftest.py erp          ERP Order Upload column fill
    python src\selftest.py bridge       normalise_to_master matching
    python src\selftest.py classify     customer identification by sender domain

Exit code 0 only when every suite that ran passed. A suite that cannot run
because a package is missing is reported as SKIP, not as a failure.
"""
import os
import re
import sys
import json
import shutil
import tempfile
import subprocess
import inspect
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile


# ==========================================================================
#  SECTION: PO NUMBER RULES
#  (formerly selftest_po.py)
# ==========================================================================

# -*- coding: utf-8 -*-
r"""selftest_po.py - self-check for PO number extraction rules

Run:  python src\selftest_po.py
Checks the digits-only-in-subject case (like KB Home) and confirms that
existing customers are not affected.
"""

import orderflow as C   # noqa: E402

SETTINGS = {"po_regex_default":
            r"(?:P\.?O\.?|PURCHASE\s*ORDER)(?:\s*(?:NUMBER|NO|NUM))?"
            r"[\s#:.\-]*([A-Z]{0,4}[0-9][A-Z0-9\-]{3,19})"}

KB = {"po_regex": C.PO_PRESETS[1][0]}      # digits only (8-12 digits, subject only)
STD = {"po_regex": ""}                     # default rule

CASES = [
    # (subject, attachments, customer rule, expected)
    ("KB HOME - Park Forest LOT 046 - 9857 36TH AVE NE - 179140181",
     ["Park Forest-NA-0523.pdf"], KB, "179140181"),
    ("KB HOME - Park Forest LOT 030 - 9853 37TH AVE NE - 178838414",
     ["Park Forest-NA-0524.pdf"], KB, "178838414"),
    ("KB HOME - Park Forest LOT 016 - 3749 99TH PL NE - 179141307",
     ["Park Forest-NA-0525.pdf"], KB, "179141307"),
    # If no PO number in subject, look in attachment filename but skip dates (20260901)
    ("KB HOME - Park Forest LOT 046",
     ["Invoice-20260901-993388221.pdf"], KB, "993388221"),
    # If the attachment only has a date, do not use it as a PO number
    ("KB HOME - Park Forest LOT 046", ["Order-20260901.pdf"], KB, None),
    ("Weekly order", ["report_260901.pdf"], STD, None),
    # Existing customers must keep their rules unchanged
    ("New PO# 0901601ILKU for delivery", [], STD, "0901601ILKU"),
    ("Purchase Order 177772869 attached", [], STD, "177772869"),
    ("RE: PO 0806601VWBN revision", [], STD, "0806601VWBN"),
]


def main_po():
    fails = 0
    for subject, atts, entry, expected in CASES:
        got = C.extract_po_number(subject, atts, entry, SETTINGS)
        ok = got == expected
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {str(got):<14} "
              f"expected {str(expected):<14} | {subject[:50]}")

    # A malformed regex must not crash the app
    got = C.extract_po_number("PO# 12345678", [], {"po_regex": "([unclosed"},
                              SETTINGS)
    ok = got == "12345678"
    fails += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} broken pattern falls back -> {got}")

    print()
    print("ALL PASSED" if not fails else f"{fails} FAILURE(S)")
    return 1 if fails else 0


# ==========================================================================
#  SECTION: QUANTITY / PRICE / AMOUNT
#  (formerly selftest_lines.py)
# ==========================================================================

r"""selftest_lines.py - self-check for quantity / unit price / amount logic

Run:  python src\selftest_lines.py

Covers the quantity-from-text rules:
  - a unit of measure must not be read as a quantity ("6.0 cf" is a capacity)
  - a bare 4+ digit value with no unit is never a quantity
  - values pass through exactly as printed - the arithmetic cross-check
    (qty x price == amount) was removed on purpose
"""

import orderflow as E   # noqa: E402

QTY_CASES = [
    # (line, expected qty from text)
    ("MODEL DVE45T6000W 2 EA $521.00 $1,042.00", "2"),
    ("QTY: 4 RF28R7201SR", "4"),
    ("RF28R7201SR 1.00 EA 4,596.00", "1"),
    # A capacity is not a quantity - this shipped as quantity 6 before
    ("DVE50R5400W 7.4 cf Electric Dryer", ""),
    ("RF23DB9600QL 6.0 cu ft French Door", ""),
    ("NX60A6111SS 30 in Slide-In Range", ""),
    ("WF45B6300AP 120V 60Hz", ""),
]

# (qty, price, amount) -> (qty, price, amount)
# No cross-check any more: every value passes through exactly as printed.
PASS_THROUGH_CASES = [
    ((1, 959.00, 1918.00), (1, 959.00, 1918.00)),
    ((2, 959.00, 1918.00), (2, 959.00, 1918.00)),
    ((3, 100.00, None), (3, 100.00, None)),
    ((4, None, 200.00), (4, None, 200.00)),
    ((4, 5395.14, 21580.5), (4, 5395.14, 21580.5)),
    ((None, None, None), (None, None, None)),
]


def main_lines():
    fails = 0

    print("  -- quantity from a PO line --")
    for line, expected in QTY_CASES:
        got = E._qty_from_desc(line)
        ok = got == expected
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {str(got) or '(none)':<8} "
              f"expected {str(expected) or '(none)':<8} | {line[:46]}")

    print("\n  -- qty / price / amount pass through unchanged --")
    for src, expected in PASS_THROUGH_CASES:
        got = src
        ok = got == expected
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {str(got):<28} "
              f"expected {str(expected):<28}")

    print()
    print("ALL PASSED" if not fails else f"{fails} FAILURE(S)")
    return 1 if fails else 0


# ==========================================================================
#  SECTION: DASHBOARD UI
#  (formerly selftest_ui.py)
# ==========================================================================

r"""selftest_ui.py - dashboard UI code check

Run:  python src\selftest_ui.py
Verifies that the JavaScript in report.py is syntactically intact.
If node is installed, a real syntax check is performed as well.
"""

import report   # noqa: E402

MUST_CONTAIN = [
    # Material Codes
    "attmiss", "refetchAtt", "clearMaterials", "renderQuick", "wireDrop",
    "qConvert", "Quick Convert", "qDownload", "qEdit",
    "Download Order Upload", "quickDoneCard", "qReopen", "qScan",
    "PO folder", "set-attonly", "Unknown codes found in POs",
    "Material Code List", "fmtSeg", "toggleErpFmt", "erpFmts", "fmtChip",
    "/api/erp_format", "suffix_autofilled", "suffix added — verify",
    # Ship-To Locations: the master itself, editable
    "uploadErp", "Ship-To locations", "shipTable", "shipConfSet",
    "setShipCell", "addShipRow", "delShipRow", "clearShipMaster",
    "loadShip", "shipSearch", "shipPage", "/api/master_rows",
    "/api/master_add", "/api/master_del", "/api/master_set",
    "/api/master_clear", "ship_conflicts",
    # Sold-To / Ship-To pickers: the domain decides the range, the Sold-To
    # narrows the Ship-To list, and the pair fills columns N/R/W/X/AI and D.
    # Since 2026-10-28 the picker is a searchable combo box (`pcombo`), not a
    # <select>: 2,246 <option>s in a 120px cell was neither readable nor fast.
    "partyCell", "comboHTML", "pcItems", "pcOpen", "pcFill", "pcCommit",
    "pcKey", "rowParty", "needParty", "partyChannel",
    "domainKnown", "rowDomain", "/api/party_options", "qPartyRow",
    # A mail is matched by the sender's DOMAIN and nothing else
    "senderDomain", "addDomainRow"]

# Nothing may still reach for the deleted customer_master.csv / erp_accounts
# model: a leftover reference would be a second, contradicting source of truth,
# and the endpoints behind them no longer exist.
MUST_NOT_CONTAIN = [
    "memberFor", "m.members", "members:", "initials(",
    "update_member", "add_member", "selectHtml",
    "erp_accounts", "customer_master", "master_conflicts", "partyKeys",
    "linkAccounts", "unlinkAccount", "pickParty", "pickApplyList", "accSearch",
    "renameCustomer", "newCustomer", "claimDomain", "claimSelect",
    "dropDomain", "addDomain(", "setChannel", "typeChip", "delAccount",
    "saveAcc", "updRule", "updM(", "CUSTQ",
    "/api/account_distr", "/api/domain_add", "/api/domain_del",
    "/api/erp_search", "/api/erp_delete", "/api/customer_new",
    "/api/customer_rename", "/api/customer_accounts", "/api/po_rule"]


def main_ui():
    html = report.render_page()
    js = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
    print(f"  page: {len(html):,} chars, script: {len(js):,} chars")

    fails = 0
    for token in MUST_CONTAIN:
        ok = token in js or token in html
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} contains {token!r}")

    for token in MUST_NOT_CONTAIN:
        ok = token not in js and token not in html
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} free of {token!r} (member model removed)")

    # The screen rename has to reach the HTML body too, not just the script -
    # the nav button and the page title are markup, so a check inside `js`
    # would pass while the user still reads the old name on screen.
    for label, needle, want in (
            # The menu is a flat hover rail now (2026-10-25): one row per
            # screen, each with a lucide icon, because a collapsed rail has no
            # room for a parent row whose children would be text-only.
            ("the menu has a row for Inbox",
             '<button class="navbtn" data-tab="today"', 1),
            ("...labelled Inbox",
             '<span class="nlb">Inbox</span>', 1),
            ("...with a lucide icon, not an emoji",
             'stroke-linecap="round" stroke-linejoin="round"', None),
            ("the page title says Inbox",
             '<h1 id="title">Inbox</h1>', 1),
            ("no \"Today's PO\" string is left anywhere",
             "Today's PO", 0),
            # The rename has to be present, not counted: it appears in the menu,
            # the day strip, the Reports column and now the row's Discard
            # button, and pinning the number only breaks when a new sentence
            # mentions the screen.
            ("Discarded replaced Not My PO",
             "Discarded", None)):
        n = html.count(needle)
        ok = (n >= 1) if want is None else (n == want)
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {label} "
              f"({n} of {want if want is not None else 'at least 1'})")

    # ── The Inbox flow, its layout, and the menu (2026-10-23) ──────────────
    # Structure, not behaviour: these catch a piece being dropped from the page,
    # which is the failure mode for markup. The behaviour itself is exercised
    # through the Python side (order_preview / read_orders).
    for label, needle, want in (
            # 2026-10-28: ONE bar again. The four-step stepper is gone - the
            # three list tabs are the pipeline, so the same journey is no longer
            # drawn twice. Extract lands in Read, Generate lands in Output.
            ("there is exactly one bar at the top of the Inbox",
             'class="steps tabs" id="steps"', 0),
            ("...the three list tabs",
             "[[1, 'Inbox', n1], [2, 'Read', n2], [3, 'Output', n3]]", 1),
            ("...with a sliding indicator",
             'class="tsink"', 1),
            ("...positioned from --i so the first paint is correct",
             'id="itabs" style="--i:\'+(ITAB-1)', 1),
            # Two clip-paths remain, and both belong to the drop folder's
            # corner notches (2026-10-26). The chevron stepper used to clip
            # its own arrow heads; none of that is left.
            ("...and no arrow clip is left in the bar",
             "clip-path", 2),
            ("no step counter survives anywhere",
             "Step 3 of 4", 0),
            ("Extract sends the row to READ, not to a step of its own",
             "if (action === 'confirm') return startReading(id, index);", 1),
            ("...by switching the tab BEFORE the reading starts",
             "ITAB = 2;\n  MAILPAGE = 0;\n  render();\n  loadReads();", 1),
            ("...and the reading panel is what that tab then shows",
             "function readFlowPage(){", 1),
            ("the reading step is indeterminate, not a fake percentage",
             'class="radar"', 1),
            ("the Inbox has a search box beside the filters",
             'id="mailq"', 1),
            ("...which matches the fields a person searches by",
             "dispName(m), m.po_number, m.sender, m.subject", 1),
            # Identifiers, not markup: these appear wherever they are used, so
            # the check is "still referenced", not a count.
            ("the Inbox is paged",
             "PER_PAGE", None),
            ("...at 10-15 rows per page",
             "const PER_PAGE = 12", 1),
            ("...with a pager under the table",
             "pagerHTML(", None),
            # Now also in a comment about the sequence guard, hence "at least".
            ("the preview reads before it shows anything",
             "/api/order_preview", None),
            ("...and says so while it runs",
             "Reading the PO", 1),
            ("the format is chosen IN the preview (step 3)",
             "togglePreviewFmt(", None),
            ("completion offers the file it just wrote",
             "function outBanner(", 1),
            # ── The dashboard (2026-10-25) ──────────────────────────────
            # Reports was three lists that nobody read. What replaced it is a
            # completed-PO dashboard: three KPI cards, a 30-day trend, and the
            # customer split.
            ("Reports became a completed-PO dashboard",
             "function renderDashboard(", 1),
            ("...whose KPI cards are one recipe used three times",
             'class="kpi2', 1),
            ("...each carrying its own period-over-period delta",
             "function deltaHTML(", 1),
            ("...compared with the SAME number of days last week",
             "const prevMon = addDays(mon, -7);", 1),
            ("...over a fixed 30-day window",
             "const DASH_DAYS = 30;", 1),
            ("...drawn as hand-rolled SVG, because there is no build step",
             'svg class="trend"', 1),
            ("...locked to its viewBox so the dots stay round",
             "aspect-ratio:1000 / 260", 1),
            ("...and the share bar IS the percentage printed beside it",
             "Math.max(2, Math.round(r.n / total * 100))", 1),
            # ── Read / Output (2026-10-25) ─────────────────────────────
            # Two screens were missing from the Inbox: what has been read but
            # not written out, and what was. They are tabs, not top-level
            # screens, because they answer questions asked from the Inbox.
            ("the Inbox carries three list tabs",
             'id="itabs"', 1),
            ("...positioned from --i like the flow bar above them",
             "style=\"--i:'+(ITAB-1)", 1),
            ("Read is fed by the register of readings on disk",
             "/api/read_list", None),
            ("...and fetches a reading's detail per row, not with the list",
             "/api/read_detail", None),
            # The format is a switch, and writing is a button beside it
            # (2026-10-26). Flipping the switch used to write the file, which
            # made the choice impossible to review before committing to it.
            ("the two formats are one segmented control",
             'class="seg"', 1),
            ("...with a thumb that follows the checKED half",
             ".seg:has(.segopt:last-child input:checked) .segthumb", 1),
            # 2026-10-27: both halves ticked stretches the same thumb across the
            # track - the one visual addition, and the only honest way to draw
            # "both selected" with a single thumb.
            ("...and across the whole track when BOTH are ticked",
             ".seg:has(.segopt:first-of-type input:checked)"
             ":has(.segopt:last-of-type input:checked)", 1),
            ("...on the reference's overshoot curve",
             "cubic-bezier(.68,-.35,.27,1.35)", 1),
            # The switch is multi-select now, so "which one is on" comes from the
            # saved list, and that list defaults to Full when nothing is stored.
            ("Full is what a row starts on",
             "if (!picked.length) picked.push('full');", 1),
            # One caller only: the switch records the configuration, the button
            # is the thing that writes.
            ("and a separate button is what writes it",
             "readOutput(this)", 1),
            ("...fixed width, so Writing… cannot shove the switch",
             ".genbtn { width:76px;", 1),
            ("...with a spinner and a disabled state while it works",
             "btn.classList.add('working')", 1),
            ("...freezing the switch for the same stretch",
             "seg.classList.add('busy')", 1),
            # Without this the click would bubble to .rlmain and expand the row
            # instead of writing the file.
            ("...and neither control expands its own row",
             'onclick="event.stopPropagation()"', 1),
            ("a reading older than the address capture says so",
             "d.legacy", 1),
            # ── The "?" markers (2026-10-26) ───────────────────────────
            # Every explanatory paragraph and field hint became a marker. The
            # words are unchanged; what went is the row they each cost.
            ("the prose lives in one registry behind a marker",
             "const FAQ = {", 1),
            ("...with one marker builder and one bubble",
             "function faq(key, label){", 1),
            ("...drawn by the SAME element the buttons use",
             "function showFaqTip(m){", 1),
            ("...in its wide left-aligned layout",
             ".btntip.rich {", 1),
            ("...with the arrow moved when the bubble is clamped",
             "--arrow, 50%", 1),
            ("the list screens carry theirs in the page head",
             'id="titlefaq"', 1),
            ("...and the confirm flow does not inherit the list's",
             "function screenFaq(){", 1),
            ("each Settings card keeps its own",
             "faq('setapi')", 1),
            ("...and each Master Data card too",
             "faq('mastership')", 1),
            # Two left, and neither is an explanation: one is the "Output file"
            # heading on step 3, the other is a per-line extraction note.
            ("no field hint is left under an input",
             'class="fhint"', 2),
            # ── The drop folder (2026-10-26) ───────────────────────────
            # The emoji is gone; the drop area is a real illustrated folder.
            # It must open on drag, never on hover - otherwise the one animation
            # on the page means nothing.
            ("the drop area is drawn, not an emoji",
             'id="dzfold"', 1),
            ("...out of a back panel and three sheets",
             'class="dzleaf', 3),
            ("...each with the tab that makes the silhouette",
             ".dzfront::after, .dzfront::before {", 1),
            ("...on a perspective, so the fold has depth",
             "perspective:1500px", 1),
            ("it opens while a file is dragged over it",
             ".dropzone.over .dzfront { transform:rotateX(-46deg)", 1),
            ("...and never on a plain mouse hover",
             ".dzfold:hover", 0),
            ("...counting nested enters so the fold does not restart",
             "DRAGDEPTH = Math.max(0, DRAGDEPTH - 1)", 1),
            ("...and saying what letting go will do",
             "Let go to read", 1),
            # ── The rail (2026-10-25; click to open since 2026-10-28) ───
            ("the menu is a rail that reserves 62px",
             ".sidewrap { flex:0 0 62px;", 1),
            ("...and widens over the page instead of reflowing it",
             ".sidebar.open { width:238px;", 1),
            # It used to open on hover, which the pointer crossed on its way
            # to a table and a keyboard never reached. The plate is a button.
            ("...and it opens on a CLICK, not on hover",
             '.sidebar:hover', 0),
            ("the plate is the toggle: a real button, keyboard reachable",
             '<button type="button" class="brand" id="brandbtn"', 1),
            ("...with the labels fading in only while it is open",
             ".sidebar.open .nlb { opacity:1;", 1),
            ("Escape, an outside click and picking a screen all close it",
             "toggleSidebar(false);", None),
            ("...on an ease-out curve",
             "cubic-bezier(.16,1,.3,1)", None),
            ("...with the labels fading in after the plate moves",
             "transition-delay:.11s", None),
            ("...and a dot instead of a number while railed",
             ".sidebar:not(.open) .navbtn .badge:not(.zero)",
             1),
            # The label is absolutely positioned while railed, otherwise the
            # centred flex row measures it and every icon sits half a
            # label-width left of the rail's centre line.
            ("...with the label out of the flex line so the icon stays centred",
             ".sidebar:not(.open) .navbtn .nlb {\n"
             "    position:absolute;", 1),
            ("...and the row centring itself with no gap to account for",
             ".navbtn { justify-content:center;\n    padding:10px 0; gap:0; }", 1),
            ("Settings is split into an API card and an Email box card",
             "function apiSettingsCard(", 1),
            ("...with the mailbox half kept separate",
             "function emailSettingsCard(", 1),
            ("...and a model dropdown fed by the endpoint's own list",
             'id="set-clmodel"', 1),
            ("the menu footer carries the reset button",
             'class="rstrow"', 1),
            ("...which posts to the reset endpoint",
             "/api/settings_reset", 1),
            # ── Row actions, 2026-10-23 ────────────────────────────────
            # One blue Extract, one red Discard. The old ✓ / ✕ pair and the
            # trash icon are gone - three ways to say "no" in one row.
            ("the row's extract button is the blue one",
             'class="tbtn blue"', 1),
            ("...and discard is red",
             'class="tbtn red"', 1),
            ("Extract is what opens the preview",
             "actIdx(m,'confirm')", None),
            ("Discard is the toss (reversible from Discarded)",
             '''onclick="tossPO('+m.id+',1)"''', 1),
            ("the old round icon buttons are gone",
             'class="iconbtn', 0),
            ("...so no table starts with an empty header cell",
             '<tr><th></th>', 0),
            # The PO # column left the table in 2026-10-23 (the number is in
            # the subject, the tooltip and the preview); Actions is last.
            # Scoped to the Inbox header: the Completed table keeps its own
            # PO # column, which is a different table on a different screen.
            ("...the PO # column is gone from the Inbox",
             '<th>PO #</th><th>Actions</th>', 0),
            ("...and the last column is Actions",
             '<th>Actions</th></tr>', 1),
            # ── Mailbox: switchable from the Inbox, and collecting lands
            #    somewhere the user can see ─────────────────────────────
            ("the Inbox has its own mailbox picker",
             'id="inbox-mb"', 1),
            ("...which collects from the mailbox it switches to",
             "async function inboxMailbox(", 1),
            ("collecting is one shared path",
             "async function runCollect(", 1),
            ("...used by Settings as well as the Inbox",
             "await collectFromSettings()", 1),
            # The old inline copy only moved the date WHEN the server reported
            # one, which is why saving a mailbox looked like it did nothing.
            ("...and it always lands on the Inbox, not only when a date came "
             "back",
             "if (r.latest_date) SELDATE = r.latest_date;", 1),
            ("the content column no longer stops growing at 1400px",
             "max-width:1400px", 0),
            ("...and can shrink, which is what pushed the page sideways",
             "flex:1 1 auto; min-width:0", 1)):
        n = html.count(needle)
        ok = (n >= 1) if want is None else (n == want)
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {label} "
              f"({n} of {want if want is not None else 'at least 1'})")

    # ── The preview is a PAGE inside the READ tab (2026-10-23 / 10-28) ───────
    # It used to be a dialog, and inside that dialog the address block and the
    # format buttons sat below the fold. Two things have to stay true: it owns
    # the whole tab while it is open, and the format choice is the FIRST thing
    # on it.
    _i_fmt = html.index('class="fmtpick"')
    _i_pv = html.index('class="pvpage"')
    _body = html[html.index("function previewPanel("):html.index("function togglePreviewFmt(")]
    for label, ok, note in (
            ("the Read tab shows the reading, then the preview, then the list",
             "function readFlowPage(){" in html
             and "if (PREVIEW) return previewPanel();" in html
             and "if (READING) return readingPanel();" in html, ""),
            ("...and the register only when nothing is open",
             "const page = readFlowPage();\n  if (page) return page;" in html, ""),
            ("the preview is no longer a floating dialog",
             'id="preview"' not in html and ".pvbox" not in html, ""),
            ("the format choice sits ABOVE the address block",
             "Output file" in _body
             and _body.index("Output file") < _body.index('class="pvpage"')
             and _i_fmt < _i_pv, "%d / %d" % (_i_fmt, _i_pv)),
            ("...and each option says what the file contains",
             "FMT_SHORT[f]" in html, ""),
            ("the address block is two columns, so it never needs scrolling",
             ".pvpage { display:grid; grid-template-columns:1fr 1fr;" in html, ""),
            # 2026-10-27: the two cards are independent switches now, so BOTH
            # can be lit and two files are written - the state is a list.
            ("picking a format keeps the page open",
             "function togglePreviewFmt(f){" in html
             and "PREVIEW.fmts = cur" in html, ""),
            ("...and both cards can be lit at once",
             "fmts.indexOf(f) >= 0 ? ' on' : ''" in html, ""),
            ("...but the last lit one cannot be turned off",
             "Keep at least one version selected" in html, ""),
            ("Cancel drops the reading and its stale answer",
             "function cancelReading(){" in html
             and "PREVIEW_SEQ++;\n  PREVIEW = null;\n  READING = null;" in html, ""),
            ("an empty street line is left out instead of listed as missing",
             "OPTIONAL.indexOf(f) >= 0 && !r.value" in html, "")):
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {label}"
              + (f" ({note})" if note else ""))

    # ── The tab bar's state colours, and the API badge (2026-10-25) ─────────
    # What is left of the old step bar is the TAB half: one sliding line, the
    # active label darkened. The `.step`/`.snum` rules went with the stepper on
    # 2026-10-28, and the bug they were written for is worth remembering: a
    # `.snum::after { content:"<escape>" }` went through Python's OCTAL parser,
    # so the circle rendered a stray byte and a "3" instead of a tick - the user
    # saw "13". Nothing in this page may carry a bare CSS escape.
    for label, ok, note in (
            ("the step bar's number rules are gone with the stepper",
             ".tabs .step" not in html and ".snum" not in html, ""),
            ("the active tab darkens its label",
             ".tabs .ts.on { color:#1d4ed8; font-weight:700;" in html, ""),
            ("the line is one element, not a border per segment",
             ".tabs .tsink { position:absolute;" in html, ""),
            ("...centred on the active segment via --i",
             "(var(--i) + 0.5)" in html, ""),
            ("...and it slides on an ease-out curve",
             "transition:left .34s cubic-bezier(.16,1,.3,1);" in html, ""),
            # The trap itself: any CSS escape in PAGE is chewed by Python first.
            ("no stray octal byte leaked into the page",
             chr(0o271) not in html, ""),
            ("the API badge has a slot in the page head",
             'id="apiwarn"' in html, ""),
            ("...is painted by renderApiWarn()",
             "function renderApiWarn(){" in html, ""),
            ("...on every render", "renderApiWarn();" in html, ""),
            ("...only where a PO is read (Inbox / Quick Convert)",
             "TAB !== 'today' && TAB !== 'quick'" in html, ""),
            ("...and only while no token is stored",
             "CL.key_set" in html, ""),
            ("clicking it opens Settings > API",
             "function openApiSettings(){ TAB = 'settings'; render(); }" in html,
             "")):
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {label}"
              + (f" ({note})" if note else ""))

    # ── Button skin, and the table's column widths (2026-10-23) ────────────
    # Only the INBOX's colgroup - the Completed table has percentages too, and
    # summing both would look like a 200% table.
    _i0 = html.index('<table class="fixed"><colgroup>')
    _i1 = html.index('</colgroup>', _i0)
    _inbox_cols = html[_i0:_i1]
    _pct = [float(x) for x in re.findall(
        r'<col style="width:([\d.]+)%">', _inbox_cols)]
    for label, ok, note in (
            ("every .btn is the uiverse tile (white card, deep shadow)",
             "box-shadow:0 10px 10px rgba(0,0,0,.08)" in html, ""),
            ("...that fills with the blue gradient on hover",
             "background:linear-gradient(320deg, #034d92, #003cff)" in html, ""),
            ("...and lifts, then presses down",
             "transform:translateY(-1px)" in html
             and "transform:translateY(1px)" in html, ""),
            ("...at an intrinsic width, not the snippet's fixed 150x50",
             "min-height:38px" in html
             and "width:150px" not in html[html.index("  .btn {"):
                                        html.index("  .btn:hover")], ""),
            # The row buttons were explicitly excluded from this change.
            ("the blue/red row buttons are NOT restyled",
             ".tbtn" in html and "border-bottom:4px solid" in html, ""),
            ("the tooltip is one shared element, not one per button",
             "className = 'btntip'" in html, ""),
            ("...because a tooltip inside a card would be clipped",
             "overflow:hidden" in html, ""),
            ("...its text comes from the button's title",
             "b.removeAttribute('title')" in html, ""),
            ("table columns are percentages, not pixels",
             len(_pct) >= 10, f"{len(_pct)} cols"),
            ("...and they sum to 100", abs(sum(_pct) - 100.0) < 0.01,
             f"{sum(_pct)}"),
            # A <col> only honours `width`; a column left without one is the
            # AUTO column and swallows the surplus. That was the subject bug.
            # ...and no <col> is left without a width, which is what made the
            # subject the AUTO column. Scoped to the Inbox's own colgroup: the
            # other tables are checked by their own percentage totals below.
            ("no Inbox column is left auto (a <col> ignores min-width)",
             "min-width" not in _inbox_cols, "")):
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {label}"
              + (f" ({note})" if note else ""))

    # ── Where a finished order lands, preview overrides, labels, overlay ─────
    for label, ok, note in (
            # 2026-10-28: generate moves to the OUTPUT tab, and the banner with
            # the download links is drawn THERE - over the list the row just
            # joined, not over the Inbox it left.
            ("Generate sends the user to Output",
             "ITAB = 3;\n  MAILPAGE = 0;\n  render();" in html, ""),
            ("...with the files in a banner above that list",
             "LASTFILES ? outBanner() : ''" in html, ""),
            ("...and nothing left over the Inbox",
             "FLOW_STEP === 4" not in html and "doneBanner" not in html, ""),
            ("the button says where it is about to go",
             "' &#8594; Output</button>'" in html, ""),
            # A reading still in flight must not drag the user forward again.
            ("a late reading is dropped after the user walks away",
             "if (seq !== PREVIEW_SEQ) return;" in html, ""),
            # 2026-10-28: the picker became a searchable combo box. The list
            # row still leads with the ACCOUNT NUMBER and carries the ZIP (or
            # the TYPE, for a Sold-To) beside it - the name only in the meta
            # column, never as the value that gets written.
            ("the account list leads with the NUMBER, the ZIP beside it",
             "function pcMeta(s, kind){" in html
             and "'ZIP ' + s.zip" in html, ""),
            ("...and the popup's rows are the code plus that meta",
             '"><b>\'+esc(s.code)+\'</b>\'' in html
             and "esc(pcMeta(s, kind))" in html, ""),
            # 2026-10-28: a free-text box, so an account the master does not
            # carry can still be written - disclosed, not blocked. The "use as
            # typed" row is offered only for something shaped like an account
            # number, so a partial search does not sprout one above real hits.
            ("the account box accepts a typed number",
             "<b>'+esc(typed)+'</b>'" in html
             and "/^[0-9]{5,}$/.test(typed)" in html
             and "use as typed" in html, ""),
            ("...and marks an off-master number amber",
             "inp.classList.toggle('off', off)" in html, ""),
            ("the candidate list is CAPPED, not all 2,246 rows",
             "const PC_MAX = 50;" in html
             and "hits.slice(start, start + PC_MAX)" in html, ""),
            ("...and the header says how many were found",
             "' account number(s)'" in html, ""),
            ("opening the box does not filter by its own value",
             "pcFill(inp, '');" in html, ""),
            # Enter with no highlighted row writes what is typed; Escape puts
            # back what was saved rather than clearing the field.
            ("Escape restores the saved value",
             "inp.value = inp.dataset.pcval || '';" in html, ""),
            ("the preview's ship fields are inputs",
             'class="pvin"' in html, ""),
            ("...bound to PREVIEW.typed",
             "PREVIEW.typed = PREVIEW.typed || {};" in html, ""),
            ("...and blank means fall back to the PO",
             "else delete PREVIEW.typed[field];" in html, ""),
            ("the overlay has a ring for a known total and dots for none",
             "function busyState(st){" in html
             and 'class="fdots"' in html and 'class="ring"' in html, ""),
            ("...polled from the server's own counters",
             "await api('/api/sync_state')" in html, ""),
            ("...and the collect request is not awaited before the UI updates",
             "function runWithProgress(job, title, sub){" in html, ""),
            ("switching mailbox is one request, not two",
             "body: {mailbox: v}" in html, "")):
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {label}"
              + (f" ({note})" if note else ""))

    # The full/simple output switch has to reach BOTH places that build a file,
    # or one of them keeps producing the other version without saying so. A
    # substring check is weak on purpose - it catches the switch being dropped
    # or un-wired, which is the failure mode; the values themselves are covered
    # by the erp suite.
    js1 = js.replace('\\"', '"')      # the page is one Python string of HTML
    for label, needle, want in (
            # 2026-10-27: the choice travels as a LIST. Sending one value would
            # silently drop the second ticked version at generate time, which is
            # exactly what this checks.
            ("Confirm sends every ticked version",
             "body.format = want;", 1),
            ("the preview asks for the same list",
             "const body = {id: id, format: erpFmts()};", 1),
            # 2: Quick Convert's download and the Read rows' Generate - both
            # send the list, because both write one file per ticked version.
            ("Quick Convert and the Read rows send the chosen versions",
             "format: want,", 2),
            ("Extract goes through the reading before anything is written",
             "if (action === 'confirm') return startReading", 1),
            # 2026-10-23: the accounts travel explicitly, and the ship block
            # comes from the preview's own boxes.
            ("the account numbers are sent with the action",
             "body.sold_to = snap.sold_to;", 1),
            ("and the ship block comes from the PREVIEW, not the row",
             "body.ship = Object.assign({}, (PREVIEW && PREVIEW.typed)", 1),
            # The output switch left the Inbox: the file is chosen on step 3,
            # where the columns it will contain are on screen.
            ("no output switch is left on the Inbox",
             "fmtSplit({id: 'today'", 0),
            # Quick Convert draws the SAME switch (2026-10-27): the split
            # button's "the other version" caret has nothing to point at when
            # both can be ticked.
            ("Quick Convert uses the same Full/Simple switch",
             "fmtSeg('quick')", 1),
            ("...and the split button is gone from the Order Upload side",
             "function fmtSplit(", 0),
            ("Sold-To / Ship-To go with the Quick Convert download, and are "
             "kept for Reopen",
             "QPARTY.sold_to, ship_to: QPARTY.ship_to", 2),
            ("the Inbox pickers save the chosen account to the row",
             "api('/api/update', {id: id, field: field, value: code})", 1),
            # The override block moved to the preview page (2026-10-23): the
            # table keeps only the two account pickers.
            ("the Inbox no longer has per-row address boxes",
             'class="addrin', 0),
            ("...nor their columns",
             "<th>Ship-to Name</th>", 0),
            ("the field list the preview builds its inputs from is still there",
             "['ship_to_name2',  'Name 2'", 1),
            ("...including the state field it offers", 
             "['ship_to_region', 'State / region',   'state'", 1),
            ("the preview renders an input per ship field",
             'class="pvin"', 1),
            ("...and typing one keeps the value without re-rendering",
             "function pvShip(field, value){", 1),
            # Cold Feet is gone, and its flag must not go on hiding mail.
            ("no Cold Feet screen is left",
             "renderColdFeet", 0),
            ("no Cold Feet nav entry is left",
             "b-coldfeet", 0),
            # Completed and Order Upload are one screen now.
            ("the merged screen shows the ERP file and the uploaded mark",
             "erpFileCell(m)", 2),
            ("...and the mark action",
             "erpMarkCell(m)", 2),
            ("the old Order Upload screen is gone",
             "renderUnprocessed", 0),
            # The dates are per order for the same reason, and follow the same
            # rule: type here to override what the PO printed.
            ("the two dates are on the preview page too",
             "['rdd',            'R.D.D'", 1)):
        n = js1.count(needle)
        ok = n == want
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {label} ({n} of {want})")

    node = shutil.which("node")
    if node:
        tmp = os.path.join(tempfile.mkdtemp(), "app.js")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(js)
        p = subprocess.run([node, "--check", tmp], capture_output=True,
                           text=True)
        ok = p.returncode == 0
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} node --check")
        if not ok:
            print(p.stderr[:1500])
    else:
        # A parser written in Python, so this machine still catches the failure
        # node was here for. It is what found the broken quote in the Ship-To
        # handlers: the page is one Python string, so a `\'` that should have
        # been `\\'` reaches the browser as a bare quote and closes the JS
        # string mid-expression. Substring tests cannot see that; only a parse
        # can. Optional because esprima is not a runtime dependency.
        try:
            import esprima
        except ImportError:
            esprima = None
        if esprima is not None:
            try:
                esprima.parseScript(js1)
                ok = True
            except Exception as e:
                ok = False
                # Point at the line, not just the message.
                msg = str(e)
                print(f"      {msg[:200]}")
                import re as _re
                m = _re.search(r"Line (\d+)", msg)
                if m:
                    _L = js1.split("\n")
                    _n = int(m.group(1))
                    for _i in range(max(0, _n - 2), min(len(_L), _n + 1)):
                        print(f"      {_i + 1}: {_L[_i][:120]}")
            fails += not ok
            print(f"  {'ok  ' if ok else 'FAIL'} JS parses (esprima)")
        else:
            print("  --  no node and no esprima - JS syntax NOT checked "
                  "(reload the dashboard to verify)")

    # ── The build stamp must be able to lie about nothing (2026-10-28) ────
    # It used to be a literal written at release time, so the sidebar said
    # "src-20260925-1123" a month after that date - and the stamp is exactly
    # what a report quotes. Three checks, because the failure has three parts:
    # the page shows a derived id, the derivation is what produces it, and
    # nothing overwrites the derivation with a literal again.
    m = re.search(r'class="buildtag"[^>]*>([^<]+)<', html)
    stamp = (m.group(1).strip() if m else "")
    ok = bool(re.fullmatch(r"src-\d{8}-\d{4}-[0-9a-f]{6}", stamp))
    fails += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} the sidebar stamp is derived "
          f"({stamp!r})")

    here = os.path.dirname(os.path.abspath(__file__))
    vsrc = open(os.path.join(here, "version.py"), encoding="utf-8").read()
    ok = "BUILD = build_id()" in vsrc and 'BUILD = "src-' not in vsrc
    fails += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} version.py derives it, never a literal")

    bat = open(os.path.join(os.path.dirname(here), "prepare_handover.bat"),
               encoding="utf-8", errors="replace").read()
    ok = "src\\version.py echo" not in bat
    fails += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} the release script does not "
          f"overwrite it")

    print()
    print("ALL PASSED" if not fails else f"{fails} FAILURE(S)")
    return 1 if fails else 0


# ==========================================================================
#  SECTION: EXCEL PO READER
#  (formerly selftest_excel.py)
# ==========================================================================

# -*- coding: utf-8 -*-
r"""selftest_excel.py - regression tests for the Excel PO reader

Run:
    python src\selftest_excel.py

Builds throwaway workbooks that reproduce the shapes real customer POs arrive
in, reads them back through quick_convert, and checks what came out. No
external fixture files, so this runs on any PC with openpyxl.

What each case guards against is written next to it. When one fails, the
message names the workbook shape and the value that was wrong, so the failure
points at the reader rather than at this file.
"""


import orderflow as quick_convert  # noqa: E402

# Codes the fixtures use. They have to exist in the master, because the reader
# finds the code column by looking every cell up - that is the design and this
# test must not work around it.
CODES = ["RF23A9671SR", "WF45T6000AW", "NE63T8111SS", "DW80CG4021SR"]


# --------------------------------------------------------------------------- #
# fixture helpers
# --------------------------------------------------------------------------- #

def make_master(base):
    """Write a Material Code master holding the fixture codes."""
    import orderflow as material_master
    cfg = os.path.join(base, "config")
    os.makedirs(cfg, exist_ok=True)
    codes = {material_master.norm(c): {"code": c, "product": "DA",
                                       "cate1": "", "cate2": "",
                                       "added_at": "2026-01-01"}
             for c in CODES}
    with open(os.path.join(cfg, "material_master.json"), "w",
              encoding="utf-8") as f:
        json.dump({"codes": codes}, f)


def write_wb(path, sheets):
    """sheets: {name: [[cell, ...], ...]} -> one .xlsx"""
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(list(row))
    wb.save(path)
    return path


# --------------------------------------------------------------------------- #
# the workbook shapes
# --------------------------------------------------------------------------- #

def fx_basic():
    """Plain table. The baseline every other case is a variation of."""
    return {"Sheet1": [
        ["Model", "Description", "Qty", "Unit Price", "Total"],
        ["RF23A9671SR", "23CF FRENCH DOOR REF", 2, 959.00, 1918.00],
        ["WF45T6000AW", "4.5CF FRONT LOAD WASHER", 3, 500.00, 1500.00],
    ]}


def fx_metadata():
    """A metadata block sits above the table, as most customer forms have."""
    return {"Sheet1": [
        ["PURCHASE ORDER", None, None, None, None],
        ["PO Number:", "4501234567", None, None, None],
        ["Ship To:", "ABT WAREHOUSE", None, None, None],
        ["Order Date:", "09/01/2026", None, None, None],
        [None, None, None, None, None],
        ["Material Code", "Description", "Order Qty", "Net Cost", "Extended"],
        ["NE63T8111SS", "30IN ELECTRIC RANGE", 4, 700.00, 2800.00],
    ]}


def fx_blank_rows():
    """Templates leave pre-filled 0.00 rows under the last real item."""
    return {"Sheet1": [
        ["Model", "Description", "Qty", "Unit Price", "Total"],
        ["RF23A9671SR", "23CF FRENCH DOOR REF", 2, 959.00, 1918.00],
        [None, None, 0, 0.00, 0.00],
        [None, None, 0, 0.00, 0.00],
    ]}


def fx_price_list():
    """A reference sheet: model and a price, but NO quantity column.

    This is the one that must not be read as a PO - doing so would invent an
    order for every line of a price list.
    """
    return {"Sheet1": [
        ["Model", "Net Invoice"],
        ["RF23A9671SR", 959.00],
        ["WF45T6000AW", 500.00],
        ["NE63T8111SS", 700.00],
    ]}


def fx_multi_sheet():
    """One workbook, two POs and a reference sheet mixed in."""
    return {
        "SMA8673": [
            ["Model", "Description", "Qty", "Unit Price", "Total"],
            ["RF23A9671SR", "23CF FRENCH DOOR REF", 2, 959.00, 1918.00],
        ],
        "SMA8674": [
            ["Model", "Description", "Qty", "Unit Price", "Total"],
            ["WF45T6000AW", "4.5CF FRONT LOAD WASHER", 5, 500.00, 2500.00],
        ],
        "PriceList": [
            ["Model", "Net Invoice"],
            ["NE63T8111SS", 700.00],
        ],
    }


def fx_footer():
    """Totals and free text follow the table."""
    return {"Sheet1": [
        ["Model", "Description", "Qty", "Unit Price", "Total"],
        ["RF23A9671SR", "23CF FRENCH DOOR REF", 2, 959.00, 1918.00],
        ["DW80CG4021SR", "24IN DISHWASHER", 1, 400.00, 400.00],
        ["Total", None, 3, None, 2318.00],
        ["Notes: deliver to dock 4", None, None, None, None],
    ]}


def fx_headerless():
    """A PO with no header row the reader recognises.

    These do arrive, and the reader used to handle them by reading the
    numbers to the right of the code by position. Tightening the table
    detection to "a quantity header AND a money header" broke them - the
    sheet was refused outright. The loose pass exists for exactly this.
    """
    return {"Sheet1": [
        ["RF23A9671SR", "23CF FRENCH DOOR REF", 2, 959.00, 1918.00],
        ["WF45T6000AW", "4.5CF FRONT LOAD WASHER", 3, 500.00, 1500.00],
    ]}


def fx_qty_trap():
    """Qty column holds a capacity that a naive reader would take (23 from
    '23CF'). Without the arithmetic cross-check, values pass through exactly
    as printed - the trap documents that no correction happens either."""
    return {"Sheet1": [
        ["Model", "Description", "Qty", "Unit Price", "Extended Cost"],
        ["RF23A9671SR", "23CF FRENCH DOOR REF", 23, 959.00, 1918.00],
    ]}


# --------------------------------------------------------------------------- #
# running
# --------------------------------------------------------------------------- #

def read_pos(path, settings):
    """Every PO in one workbook, whichever API the reader exposes."""
    fn = getattr(quick_convert, "parse_excel_pos", None)
    if fn:
        return fn(path, settings)
    return [quick_convert.parse_excel_po(path, settings)]


def codes_of(res):
    return [r.get("material_code") for r in res.get("records", [])]


def run_excel():
    base = tempfile.mkdtemp(prefix="ofx_")
    settings = {"_base": base}
    make_master(base)
    work = os.path.join(base, "wb")
    os.makedirs(work, exist_ok=True)
    checks, failed = [], 0

    def check(label, ok, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, label, detail))

    def build(name, sheets):
        return write_wb(os.path.join(work, name + ".xlsx"), sheets)

    try:
        # 1 - baseline table
        res = read_pos(build("basic", fx_basic()), settings)
        got = codes_of(res[0]) if res else []
        check("basic: both line items read",
              got == ["RF23A9671SR", "WF45T6000AW"], f"got {got}")
        rec = (res[0]["records"][0] if res and res[0]["records"] else {})
        check("basic: quantity read", rec.get("quantity") == 2,
              f"got {rec.get('quantity')!r}")
        check("basic: unit price read", rec.get("unit_price") == 959.0,
              f"got {rec.get('unit_price')!r}")
        check("basic: extended amount carried through as printed",
              rec.get("amount") == 1918.0, f"got {rec.get('amount')!r}")

        # 2 - metadata block above the table
        res = read_pos(build("meta", fx_metadata()), settings)
        got = codes_of(res[0]) if res else []
        check("metadata: item below the header block read",
              got == ["NE63T8111SS"], f"got {got}")
        check("metadata: PO number taken from the label",
              res and res[0].get("po_number") == "4501234567",
              f"got {res[0].get('po_number')!r}" if res else "no result")

        # 3 - pre-filled blank rows
        res = read_pos(build("blank", fx_blank_rows()), settings)
        got = codes_of(res[0]) if res else []
        check("blank rows: 0.00 template rows not read as items",
              got == ["RF23A9671SR"], f"got {got}")

        # 4 - a price list must not become an order
        try:
            res = read_pos(build("prices", fx_price_list()), settings)
            n = sum(len(r.get("records", [])) for r in res)
            check("price list: not read as a PO", n == 0,
                  f"read {n} line item(s) from a sheet with no quantity column")
        except Exception as e:
            check("price list: not read as a PO", True, f"rejected: {e}")

        # 5 - several POs in one workbook
        res = read_pos(build("multi", fx_multi_sheet()), settings)
        pos = [r for r in res if r.get("records")]
        check("multi-sheet: both PO sheets read", len(pos) == 2,
              f"got {len(pos)} PO(s)")
        if len(pos) == 2:
            check("multi-sheet: reference sheet skipped",
                  sorted(c for p in pos for c in codes_of(p)) ==
                  ["RF23A9671SR", "WF45T6000AW"],
                  f"got {[codes_of(p) for p in pos]}")
            check("multi-sheet: sheet name used as the PO number",
                  pos[0].get("po_number") == "SMA8673",
                  f"got {pos[0].get('po_number')!r}")

        # 5b - a PO with no recognisable header must still be read
        res = read_pos(build("headerless", fx_headerless()), settings)
        got = codes_of(res[0]) if res else []
        check("no header row: still read by position",
              got == ["RF23A9671SR", "WF45T6000AW"], f"got {got}")
        rec = (res[0]["records"][0] if res and res[0]["records"] else {})
        check("no header row: quantity read by position",
              rec.get("quantity") == 2, f"got {rec.get('quantity')!r}")
        check("no header row: unit price read by position",
              rec.get("unit_price") == 959.0,
              f"got {rec.get('unit_price')!r}")

        # 6 - totals and notes under the table
        res = read_pos(build("footer", fx_footer()), settings)
        got = codes_of(res[0]) if res else []
        check("footer: total and notes rows not read as items",
              got == ["RF23A9671SR", "DW80CG4021SR"], f"got {got}")

        # 7 - no arithmetic any more: the printed values pass through as-is
        import orderflow as erp_excel
        res = read_pos(build("trap", fx_qty_trap()), settings)
        lines, _nq, _nc, _dr, fixes = erp_excel.prepare_lines(res)
        qty = lines[0]["qty"] if lines else None
        check("qty trap: no arithmetic correction, printed value passes "
              "through", str(qty) == "23" and not fixes,
              f"got {qty!r}; fixes={fixes}")

        # 8 - dedupe: a shared block description alone does not merge lines.
        # PO BM736499: six real lines, every record labelled with the same
        # block text because the code list carries no descriptions.
        blk = "DW80CG4051S 24 SAMSU UPC R ME16A4021AS 24 SAMSU UPC"
        mk = lambda c, p: {"material_code": c, "description": blk,
                           "quantity": 24, "unit_price": p}
        kept, dropped = erp_excel.dedupe_line_records(
            [mk("DW80CG4051SRAA", 383.2), mk("ME16A4021AS/AA", 171.2)])
        check("dedupe: same text, different prices -> both kept",
              len(kept) == 2 and not dropped, f"dropped={dropped}")
        quoted = "TRIM KIT FOR MS19M8000AS  MK-TRIM30"
        kept, dropped = erp_excel.dedupe_line_records(
            [{"material_code": "MS19M8000AS", "description": quoted,
              "quantity": 1, "unit_price": 99.0},
             {"material_code": "MK-TRIM30", "description": quoted,
              "quantity": 1, "unit_price": 99.0}])
        check("dedupe: model quoted on the same row -> dropped",
              [r["material_code"] for r in kept] == ["MK-TRIM30"]
              and dropped == ["MS19M8000AS"], f"kept={kept} dropped={dropped}")
        lines, _nq, _nc, dr, _fx = erp_excel.prepare_lines(
            [{"records": [{"material_code": "MS19M8000AS",
                           "description": quoted, "quantity": 1,
                           "unit_price": 99.0},
                          {"material_code": "MK-TRIM30",
                           "description": quoted, "quantity": 1,
                           "unit_price": 99.0}]}], keep_dropped=True)
        check("keep_dropped: the quoted model comes back unticked",
              [(l["code"], l["include"]) for l in lines] ==
              [("MK-TRIM30", True), ("MS19M8000AS", False)],
              f"got {[(l['code'], l['include']) for l in lines]}")

        # 9 - Master Data > Material Codes upload (the ONLY code list now).
        # These cases used to be tested against CodeExtract/backbone_import,
        # retired when the two lists were merged into this one.
        import orderflow as material_master
        mbase = tempfile.mkdtemp(prefix="ofm_")
        mset = {"_base": mbase}
        try:
            # 9a - the company layout: Product / Type1 columns filled in on
            # the first row of a group, labelled and service entries,
            # a digit-free part code, both suffix spellings.
            r = material_master.mm_upload(mset, build("company", {"Sheet1": [
                ["", "Branch Office", "Product", "Type1", "Material Code"],
                ["", "SEA", "Refrigerator", "FDR", "RF18A5101SR/AA"],
                ["", "", "", "", "RF29BB8600QLAA"],
                ["", "", "Dishwasher", "BI", "DW80CG4051SRAA"],
                ["", "", "Service", "INST", "Model E3-DW"],
                ["", "", "", "", "Labor REF"],
                ["", "", "Accessory", "Filter", "HAFQIN"],
            ]}))
            got = {v["code"]: (v["product"], v["cate1"]) for v in
                   material_master.mm_load(mset)["codes"].values()}
            want = {"RF18A5101SR/AA": ("Refrigerator", "FDR"),
                    "RF29BB8600QLAA": ("Refrigerator", "FDR"),
                    "DW80CG4051SRAA": ("Dishwasher", "BI"),
                    "E3-DW": ("Service", "INST"),
                    "LABOR-REF": ("Service", "INST"),
                    "HAFQIN": ("Accessory", "Filter")}
            check("master upload: company layout, categories filled down",
                  got == want, f"got {got}")
            check("master upload: category columns reported",
                  r.get("category_columns") == "Product=C, Type1=D",
                  f"got {r.get('category_columns')!r}")

            # 9b - re-upload with the other suffix spelling: same code, the
            # newest file's spelling is kept
            material_master.mm_upload(mset, build("respell", {"Sheet1": [
                ["Product", "Type1", "Material Code"],
                ["Dishwasher", "BI", "DW80CG4051SR/AA"],
            ]}))
            got = [v["code"] for v in material_master.mm_load(mset)["codes"]
                   .values() if v["code"].startswith("DW80CG4051")]
            check("master re-upload: spelling follows the newest file",
                  got == ["DW80CG4051SR/AA"], f"got {got}")

            # 9c - header below title rows
            material_master.clear(mset)
            material_master.mm_upload(mset, build("title", {"Sheet1": [
                ["Samsung Electronics America"],
                [None],
                ["Plant", "Material Code", "Material Description",
                 "Product Group"],
                ["1010", "NE63A6111SS", "Range Electric", "MDA"],
            ]}))
            hit = material_master.lookup(mset, "NE63A6111SS") or {}
            check("master upload: header below title rows",
                  hit.get("product") == "MDA", f"got {hit}")

            # 9d - several sheets: every sheet read, sheet name as Product,
            # a sheet without a code column skipped
            material_master.clear(mset)
            material_master.mm_upload(mset, build("multi", {
                "Refrigerator": [["Material Code", "Description"],
                                 ["RF28T5001SR", "French Door 28cf"]],
                "Install": [["Material Code", "Description"],
                            ["E3-DW", "DW Install"]],
                "Notes": [["This file is maintained by the SEA office"]],
            }))
            got = {v["code"]: v["product"] for v in
                   material_master.mm_load(mset)["codes"].values()}
            check("master upload: every sheet read, sheet name as Product",
                  got == {"RF28T5001SR": "Refrigerator", "E3-DW": "Install"},
                  f"got {got}")
        finally:
            shutil.rmtree(mbase, ignore_errors=True)

    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("=" * 68)
    print("Excel PO reader - regression tests")
    print("=" * 68)
    for ok, label, detail in checks:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {label}")
        if not ok and detail:
            print(f"         {detail}")
    print("-" * 68)
    print(f"  {len(checks) - failed}/{len(checks)} passed")
    if failed:
        print(f"  {failed} FAILED")
    return 1 if failed else 0


# ==========================================================================
#  SECTION: NORMALISE TO MASTER
#  (formerly selftest_bridge.py)
# ==========================================================================

# -*- coding: utf-8 -*-
r"""selftest_bridge.py - regression tests for extractor_bridge.normalise_to_master

Run:  python src\selftest_bridge.py

Covers the base/market-suffix matching added after a real complaint: a PO
often prints a code without its market suffix ("RF23A9671SR" where the
master lists "RF23A9671SR/AA"), and the master lookup used to be an exact
string match only, so the short code shipped straight through to column H
of the Order Upload file instead of the full one.

The rules under test (the match uses the engine's own BackboneIndex):
  - a short code resolves to the master's full listing, whether the suffix
    is written with a slash ("RF23A9671SR/AA") or glued ("DW80CG4051SRAA")
  - several market variants sharing a base: /AA is chosen, because customers
    who order on manual POs only ever take /AA
  - several variants and none of them /AA: left alone rather than guessed -
    the same "never invent a value" principle the whole pipeline follows
"""

import orderflow as B  # noqa: E402


def make_settings(codes, sku_map=None):
    """Build a temporary Material Code master, optionally with short mappings."""
    import orderflow as material_master
    base = tempfile.mkdtemp(prefix="ofb_")
    cfg = os.path.join(base, "config")
    os.makedirs(cfg, exist_ok=True)
    data = {"codes": {}, "sku_map": sku_map or {}}
    for full in codes:
        data["codes"][material_master.norm(full)] = {
            "code": full, "product": "DA", "cate1": "", "cate2": "",
            "added_at": "2026-01-01"}
    with open(os.path.join(cfg, "material_master.json"), "w",
              encoding="utf-8") as f:
        json.dump(data, f)
    return {"_base": base}, base


def rec(code):
    return {"file": "t.pdf", "records": [{"material_code": code,
            "quantity": 1, "unit_price": 1, "amount": 1}]}


def run_bridge():
    checks, failed = [], 0

    def check(label, ok, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, label, detail))

    # 1 - exact match already correct: nothing to fix, not reported as fixed
    settings, base = make_settings(["RF23A9671SR/AA"])
    try:
        results = [rec("RF23A9671SR/AA")]
        fixed, unknown, err = B.normalise_to_master(results, settings)
        check("exact match: code unchanged", not fixed and not unknown,
              f"fixed={fixed} unknown={unknown} err={err}")
        check("exact match: record still correct",
              results[0]["records"][0]["material_code"] == "RF23A9671SR/AA")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 0 - the collection progress plumbing (2026-10-23). The page draws a
    #     percentage from SYNC.done/total, so the collector has to be able to
    #     report both, and the route that publishes them has to exist.
    # NOTE: OF.server is a facade namespace (_NS), not a module - inspect needs
    # the real module behind one of its functions.
    _srv_src = inspect.getsource(
        sys.modules[OF.server.make_handler.__module__])
    _col_src = inspect.getsource(OF.collector.collect_outlook)
    check("the collector accepts a progress callback",
          "progress=None" in _col_src)
    check("...and calls it while walking the folder",
          "progress(n, total" in _col_src)
    check("the server publishes done/total through _progress",
          "def _progress(" in _srv_src, "")
    check("...on a route the page can poll",
          "/api/sync_state" in _srv_src)
    check("a mailbox can be saved and read in ONE request",
          'body.get("mailbox")' in _srv_src)

    # 2 - short code, exactly one master entry shares the base -> extended
    settings, base = make_settings(["RF23A9671SR/AA"])
    try:
        results = [rec("RF23A9671SR")]
        fixed, unknown, err = B.normalise_to_master(results, settings)
        got = results[0]["records"][0]["material_code"]
        check("unique base: short code extended to the full listing",
              got == "RF23A9671SR/AA", f"got {got!r}, fixed={fixed}")
        check("unique base: reported in the fixed list", bool(fixed),
              f"fixed={fixed}")
        repaired = results[0]["records"][0]
        check("unique base: repair carries an amber-review marker",
              repaired.get("suffix_autofilled") is True
              and repaired.get("suffix_original") == "RF23A9671SR"
              and "Verify" in repaired.get("normalisation_warning", ""),
              str(repaired))
        prepared, _nq, _nc, _dropped, _fixes = (
            B.erp_excel.prepare_lines(results, {}, keep_dropped=True))
        check("unique base: included automatically and marker survives export prep",
              prepared[0]["include"] is True
              and prepared[0].get("suffix_autofilled") is True,
              str(prepared[0]))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2b - the exact, unique Material Code relationship outranks a stale
    # short-SKU mapping. This is the point of running the new rule first.
    import orderflow as material_master
    stale_map = {
        material_master.norm("RF23CB9900QK"): {
            "short": "RF23CB9900QK", "full": "WRONGSKU/AA",
            "group": "", "group2": ""}}
    settings, base = make_settings(
        ["RF23CB9900QKAA", "WRONGSKU/AA"], stale_map)
    try:
        results = [rec("RF23CB9900QK")]
        results[0]["records"][0].update({
            "needs_review": True, "review_reason": "old gate warning"})
        fixed, unknown, err = B.normalise_to_master(results, settings)
        repaired = results[0]["records"][0]
        check("exact glued base bypasses a stale short-SKU mapping",
              repaired["material_code"] == "RF23CB9900QKAA",
              f"record={repaired}, fixed={fixed}, unknown={unknown}, err={err}")
        check("safe suffix repair clears the old hold but stays highlighted",
              not repaired.get("needs_review")
              and repaired.get("suffix_autofilled")
              and repaired.get("match_type") == "suffix_autofill",
              str(repaired))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2c - not just /AA: any unique slash suffix in the master follows the
    # same exact-prefix rule.
    settings, base = make_settings(["RF23A9671SR/A3"])
    try:
        results = [rec("RF23A9671SR")]
        B.normalise_to_master(results, settings)
        repaired = results[0]["records"][0]
        check("unique /A3 suffix is completed and highlighted",
              repaired["material_code"] == "RF23A9671SR/A3"
              and repaired.get("suffix_autofilled") is True,
              str(repaired))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 3 - short code, /AA and /A3 share the base -> /AA (either list order)
    for order in (["RF23A9671SR/AA", "RF23A9671SR/A3"],
                  ["RF23A9671SR/A3", "RF23A9671SR/AA"]):
        settings, base = make_settings(order)
        try:
            results = [rec("RF23A9671SR")]
            fixed, unknown, err = B.normalise_to_master(results, settings)
            got = results[0]["records"][0]["material_code"]
            check(f"/AA and /A3 ({order[0][-3:]} listed first): /AA chosen",
                  got == "RF23A9671SR/AA" and not unknown,
                  f"got {got!r}, unknown={unknown}, err={err}")
            check("ambiguous exact suffix candidates do not use the new rule",
                  not results[0]["records"][0].get("suffix_autofilled"),
                  str(results[0]["records"][0]))
        finally:
            shutil.rmtree(base, ignore_errors=True)

    # 3b - several variants, none of them /AA -> left alone, flagged
    settings, base = make_settings(["RF23A9671SR/A3", "RF23A9671SR/A0"])
    try:
        results = [rec("RF23A9671SR")]
        fixed, unknown, err = B.normalise_to_master(results, settings)
        got = results[0]["records"][0]["material_code"]
        check("variants without /AA: short code NOT guessed",
              got == "RF23A9671SR", f"got {got!r} (should be unchanged)")
        check("variants without /AA: flagged as unknown for a human",
              "RF23A9671SR" in unknown, f"unknown={unknown}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 3c - glued market suffix: the reported bug. A PO wraps "DW80CG4051S"
    # / "R" over two lines, the engine rejoins it, and the master lists the
    # model as DW80CG4051SRAA (no slash). It used to stay "DW80CG4051SR".
    settings, base = make_settings(["DW80CG4051SRAA", "ME16A4021AS/AA"])
    try:
        results = [rec("DW80CG4051SR"), rec("ME16A4021AS")]
        fixed, unknown, err = B.normalise_to_master(results, settings)
        got = [r["records"][0]["material_code"] for r in results]
        check("glued suffix: DW80CG4051SR -> DW80CG4051SRAA",
              got[0] == "DW80CG4051SRAA", f"got {got[0]!r}, err={err}")
        check("slash suffix still works: ME16A4021AS -> ME16A4021AS/AA",
              got[1] == "ME16A4021AS/AA", f"got {got[1]!r}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 4 - code with no base match at all -> unknown, untouched
    settings, base = make_settings(["RF23A9671SR/AA"])
    try:
        results = [rec("WF45T6000AW")]
        fixed, unknown, err = B.normalise_to_master(results, settings)
        got = results[0]["records"][0]["material_code"]
        check("no match: code left as extracted", got == "WF45T6000AW",
              f"got {got!r}")
        check("no match: reported as unknown", "WF45T6000AW" in unknown,
              f"unknown={unknown}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 5 - empty master: a no-op, not an error
    settings, base = make_settings([])
    try:
        results = [rec("RF23A9671SR")]
        fixed, unknown, err = B.normalise_to_master(results, settings)
        check("empty master: no-op", not fixed and not unknown and not err,
              f"fixed={fixed} unknown={unknown} err={err!r}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("=" * 62)
    print("normalise_to_master - regression tests")
    print("=" * 62)
    for ok, label, detail in checks:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {label}")
        if not ok and detail:
            print(f"         {detail}")
    print("-" * 62)
    print(f"  {len(checks) - failed}/{len(checks)} passed")
    return 1 if failed else 0

# ==========================================================================
#  SECTION: ERP UPLOAD COLUMNS
#  (new - 2026-09-30)
# ==========================================================================

# -*- coding: utf-8 -*-
r"""selftest_erp.py - regression tests for the Order Upload column fill

Run:  python src\selftest.py erp

The ERP template is the 106-column SAP Standard Order Upload form, and the
writer used to place its six values at hard-coded column numbers
(A / F / G / H / I / BE). A form gets relabelled from one revision to the next -
the unit-price column is "EDI1 condition value(O)" on the copy that ships in
this snapshot - so the writer now resolves every column from the header NAME,
keeping the old number only as a fallback.

What these tests hold in place:
  - the headers resolve to A / C / D / E / F / G / H / I / BE / BF
  - a template carrying the same headers in a different ORDER still gets each
    value in the column that carries its header  (that is the point of the change)
  - a renamed price header falls back to BE and REPORTS it, instead of dropping
    the unit price into a blank column
  - a workbook that is not the form at all is refused, not written into
  - a missing quantity or price leaves the cell EMPTY - never a 0, which the ERP
    would read as a real order line
  - the P/O No. is written on the Quick Convert path too: the column is marked
    mandatory on the form, and Quick Convert does have the number on screen
  - the SALES AREA: Sales Org 3101 and Division 00 are constants written as
    TEXT ("00" as a number is 0 - a different division), while Distr. Channel
    follows the Sold-To account number and stays EMPTY, with a note, when that
    number has no channel recorded
  - the shipped config\erp_template.XLSX resolves, whichever way it is spelt
  - the OPT-IN simple version (PO # / Material / Sales Quantity / Unit Price)
    needs no template at all, keeps the four headers in that order, and is
    only produced when "simple" was actually asked for - an omitted or
    misspelled format must still mean the full ERP form
"""

import orderflow as OF  # noqa: E402

# Header text and column, exactly as the shipped form spells them.
# The Ship-To block is N (name), O-Q (three more name lines), R (address),
# S-V (four more street lines), W (postal), X (city) and AZ (region/state).
FORM = (("P/O No.(M)", 1), ("Sales Org.(M)", 3), ("Distr. Channel(M)", 4),
        ("Division(M)", 5), ("Sold To Party(M)", 6), ("Ship To Paty(O)", 7),
        ("Material(O)", 8), ("Sales Quantity(M)", 9),
        ("R.D.D(O)", 11),
        ("P/O Date(O)", 13),
        ("Ship-to Name(O)", 14), ("Ship-to Name 2(O)", 15),
        ("Ship-to Name 3(O)", 16), ("Ship-to Name 4(O)", 17),
        ("Ship-to Address(O)", 18),
        ("Ship-to Street 2(O)", 19), ("Ship-to Street 3(O)", 20),
        ("Ship-to Street 4(O)", 21), ("Ship-to Street 5(O)", 22),
        ("Ship-to Postal Code(O)", 23), ("Ship-to City(O)", 24),
        ("Sold-to Name2(O)", 35),
        ("EDI1 condition value(O)", 57),
        ("EDI1 condition currency(O)", 58),
        ("Ship-to Region(O)", 52))
MAP = {"po": 1, "sales_org": 3, "distr_channel": 4, "division": 5,
       "sold_to": 6, "ship_to": 7, "code": 8, "qty": 9, "rdd": 11,
       "po_date": 13,
       "cost": 57, "currency": 58,
       "ship_to_name": 14, "ship_to_name2": 15, "ship_to_name3": 16,
       "ship_to_name4": 17, "ship_to_address": 18,
       "ship_to_street2": 19, "ship_to_street3": 20,
       "ship_to_street4": 21, "ship_to_street5": 22,
       "ship_to_zip": 23, "ship_to_city": 24, "ship_to_region": 52,
       "sold_to_name": 35}


def write_form(path, form=FORM):
    """A workbook carrying just those (header, column) pairs."""
    import openpyxl
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    for text, col in form:
        ws.cell(row=1, column=col, value=text)
    wb.save(path)
    return path


def erp_base(form=FORM, name=None):
    """A temp project holding `form` as its ERP template."""
    base = tempfile.mkdtemp(prefix="oferp_")
    name = name or os.path.basename(OF.erp_excel.TEMPLATE_REL)
    write_form(os.path.join(base, "config", name), form)
    return base


def erp_export(base, lines, tag="T", po=""):
    """Run the real Quick Convert export and read the result back."""
    import openpyxl
    path, n = OF.erp_excel.build_upload_lines(lines, {"_base": base},
                                              tag=tag, po=po)
    ws = openpyxl.load_workbook(path).active
    cmap, _notes = OF.erp_excel.column_map(ws)
    rows, r = [], OF.erp_excel.header_row(ws) + 1
    while any(ws.cell(row=r, column=cmap[k]).value not in (None, "")
              for k in ("po", "code", "qty")):
        rows.append({k: ws.cell(row=r, column=c).value for k, c in cmap.items()})
        r += 1
    return ws, cmap, rows, n


def run_erp():
    import openpyxl
    checks, failed = [], 0

    def check(label, ok, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, label, detail))

    # 1 - the headers resolve to the columns the form has always used
    base = erp_base()
    try:
        base_cmap, notes = OF.erp_excel.column_map(
            __import__("openpyxl").load_workbook(
                os.path.join(base, "config", "erp_template.xlsx")).active)
        check("Standard Order Upload headers -> A / C / D / E / F / G / H / I / BE / BF",
              base_cmap == MAP, f"got {base_cmap}")
        check("every column matched by name, none fell back",
              not notes, f"{notes}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2 - the values land in those columns
    base = erp_base()
    try:
        _ws, cmap, rows, n = erp_export(base, [
            {"code": "RF28R7201SR", "qty": 3, "cost": 1532.0},
            {"code": "WF45B6300AP", "qty": 7, "cost": 720.0}], po="4048073")
        check("two lines written", n == 2 and len(rows) == 2, f"n={n}, {rows}")
        check("row 1: code / qty / cost in H / I / BE",
              (rows[0]["code"], rows[0]["qty"], rows[0]["cost"])
              == ("RF28R7201SR", 3, 1532.0), f"{rows[0]}")
        check("P/O No. written to the mandatory column A",
              all(r["po"] == "4048073" for r in rows),
              f"{[r['po'] for r in rows]}")
        check("quantity and price written as numbers, not text",
              all(isinstance(r["qty"], (int, float))
                  and isinstance(r["cost"], (int, float)) for r in rows),
              f"{rows}")
        # The unit price must DISPLAY two decimals (2026-10-27). Under the
        # template's own General format a whole-dollar contract price printed
        # as "1532", which reads as a different number next to the PO.
        _c = cmap["cost"]
        check("BE: the unit price is formatted to two decimals",
              all(_ws.cell(row=r, column=_c).number_format == "#,##0.00"
                  for r in (2, 3)),
              f"{[_ws.cell(row=r, column=_c).number_format for r in (2, 3)]}")
        check("...and the VALUE is untouched - a format, not a round",
              [_ws.cell(row=r, column=_c).value for r in (2, 3)]
              == [1532.0, 720.0],
              f"{[_ws.cell(row=r, column=_c).value for r in (2, 3)]}")
        # The sales area: two constants and one look-up
        check("Sales Org 3101 in C on every row",
              all(r["sales_org"] == "3101" for r in rows),
              f"{[r['sales_org'] for r in rows]}")
        check("Division 00 in E on every row",
              all(r["division"] == "00" for r in rows),
              f"{[r['division'] for r in rows]}")
        check("no Sold-To given -> Distr. Channel stays empty, never guessed",
              all(r["distr_channel"] in (None, "") for r in rows),
              f"{[r['distr_channel'] for r in rows]}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2b - Division is written as TEXT. As a number "00" is 0, which is a
    # different division - and that difference would only show up at upload.
    base = erp_base()
    try:
        p, _n = OF.erp_excel.build_upload_lines(
            [{"code": "RF28R7201SR", "qty": 1, "cost": 10.0}],
            {"_base": base}, tag="t", po="1")
        ws2b = openpyxl.load_workbook(p).active
        check("Division 00 is stored as text, so the leading zero survives",
              ws2b.cell(row=2, column=5).data_type == "s"
              and ws2b.cell(row=2, column=5).value == "00",
              f"{ws2b.cell(row=2, column=5).value!r} "
              f"type={ws2b.cell(row=2, column=5).data_type}")
        check("Sales Org 3101 is stored as text too",
              ws2b.cell(row=2, column=3).value == "3101",
              repr(ws2b.cell(row=2, column=3).value))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2c - the two-decimal format must never ROUND the value. The ERP imports
    # the cell, not what Excel paints, so a 3-decimal price has to survive
    # exactly while still being shown to two places.
    base = erp_base()
    try:
        p, _n = OF.erp_excel.build_upload_lines(
            [{"code": "RF28R7201SR", "qty": 1, "cost": 1198.375}],
            {"_base": base}, tag="t", po="1")
        ws2c = openpyxl.load_workbook(p).active
        c2c = ws2c.cell(row=2, column=57)
        check("a 3-decimal price keeps its exact value in BE",
              c2c.value == 1198.375, repr(c2c.value))
        check("...while still displaying two decimals",
              c2c.number_format == "#,##0.00", c2c.number_format)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2c - BF, "EDI1 condition currency", is USD on every line. It is the
    # currency of the unit price in BE, and every price on this flow is a USD
    # contract price, so the cell is a constant rather than per-line data - and
    # it is filled even on a line that printed no price, because a currency
    # sitting next to a blank price (or the reverse) is a half-filled row.
    base = erp_base()
    try:
        p, _n = OF.erp_excel.build_upload_lines(
            [{"code": "RF28R7201SR", "qty": 1, "cost": 10.0}],
            {"_base": base}, tag="t", po="1")
        ws2c = openpyxl.load_workbook(p).active
        check("BF (EDI1 condition currency) is USD",
              ws2c.cell(row=2, column=58).value == "USD",
              repr(ws2c.cell(row=2, column=58).value))
        check("...written as text, not as a number or a date",
              ws2c.cell(row=2, column=58).data_type == "s",
              f"type={ws2c.cell(row=2, column=58).data_type}")
        check("BD (the form's other Currency column) is left alone",
              ws2c.cell(row=2, column=56).value in (None, ""),
              repr(ws2c.cell(row=2, column=56).value))
        check("the constant is the one the writer uses",
              OF.erp_excel.CURRENCY == "USD", repr(OF.erp_excel.CURRENCY))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2c2 - M, "P/O Date", is the email's received date, written as a REAL date
    # so the template's own 'mm-dd-yy' format applies to it rather than as text
    # a person would have to convert. An unreadable value leaves it EMPTY - the
    # same rule the quantity and price follow, and for the same reason: a wrong
    # date is worse than a blank one.
    base = erp_base()
    try:
        res = [{"file": "po.pdf", "po_number": "4048073", "records": [
            {"material_code": "RF28R7201SR", "quantity": "1",
             "unit_price": "10.00", "amount": "10.00", "description": "REF"}]}]
        mail = {"po_number": "4048073", "sold_to": "", "ship_to": "",
                "received_at": "2026-10-14T17:20:58"}
        p, n, _a, _b, _c, _d = OF.erp_excel.build_upload(
            res, mail, {"_base": base}, fmt="full")
        wsm = openpyxl.load_workbook(p).active
        cell = wsm.cell(row=2, column=13)
        check("M (P/O Date) is the email's received date",
              str(cell.value).startswith("2026-10-14"), repr(cell.value))
        check("...written as a real date, not text",
              cell.data_type == "d", f"type={cell.data_type}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2c2e - the two account numbers reach columns F and G, and the channel
    #       (D) follows from the pair. The Inbox pickers DISPLAY a value the
    #       page derives from the master and only save it when it is changed,
    #       so Confirm has to take them from the request - without that, a row
    #       that arrived with one account on file produced F/G/D empty.
    typed = OF.server._typed_party({"sold_to": " 1000006 ",
                                    "ship_to": "1000006"})
    check("the picked account numbers are read off the Confirm request",
          typed == {"sold_to": "1000006", "ship_to": "1000006"}, f"{typed}")
    check("...and nothing is returned for a row that sent neither",
          OF.server._typed_party({}) == {}, f"{OF.server._typed_party({})}")
    check("...so an omitted key cannot blank a stored account",
          "ship_to" not in OF.server._typed_party({"sold_to": "1"}))
    base = erp_base()
    try:
        res = [{"po_number": "P1", "records": [
            {"material_code": "RF28R7201SR", "quantity": "1",
             "unit_price": "100.00", "description": ""}]}]
        path, _n, _a, _b, _c, _d = OF.erp_excel.build_upload(
            res, {"po_number": "P1", "sold_to": "1000006",
                  "ship_to": "1000006"}, {"_base": base})
        ws3 = openpyxl.load_workbook(path).active
        check("F gets the Sold-To the row was showing",
              str(ws3.cell(row=2, column=6).value) == "1000006",
              repr(ws3.cell(row=2, column=6).value))
        check("G gets the Ship-To the row was showing",
              str(ws3.cell(row=2, column=7).value) == "1000006",
              repr(ws3.cell(row=2, column=7).value))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2c2f - Ship-to Name (N) comes from the customer master, never from the PO.
    _tmp2 = tempfile.mkdtemp(prefix="ofpv_")
    fill, _note = OF.erp_excel._party_fill({"_base": _tmp2}, "", "NOT-A-PAIR")
    OF.erp_excel._po_ship(fill, [{"ship_to_name": "FROM THE PO",
                                  "ship_to_address": "9 ONE-OFF WAY"}])
    check("Ship-to Name is NOT taken from the PO",
          "ship_to_name" not in fill, f"{fill}")
    check("...while the PO still supplies the street address",
          fill.get("ship_to_address") == "9 ONE-OFF WAY", f"{fill}")
    shutil.rmtree(_tmp2, ignore_errors=True)

    # 2c2g - the preview before generating.
    base = erp_base()
    try:
        pv = OF.erp_excel.order_preview(
            {"po_number": "4512889"}, {"_base": base},
            sold_to="1000006", ship_to="1000006")
        letters = [r["letter"] for r in pv["rows"]]
        check("the preview lists the party / channel / address / date columns",
              {"F", "G", "D", "N", "R", "K", "M"} <= set(letters), f"{letters}")
        check("...and NOT the fixed constants",
              not ({"C", "E", "BF"} & set(letters)), f"{letters}")
        check("...and NOT Material / Quantity / Unit price",
              not ({"H", "I", "BE"} & set(letters)), f"{letters}")
        check("a column nobody has filled yet says where it will come from",
              all(r["pending"] for r in pv["rows"]
                  if r["letter"] in ("R", "K", "M")),
              f"{[(r['letter'], r['pending']) for r in pv['rows']]}")
        check("an unfilled address is never shown as an empty value",
              all(r["value"] == "" for r in pv["rows"]
                  if r["letter"] in ("R", "S", "W", "X")))
        _pv0 = OF.erp_excel.order_preview({"po_number": "1"},
                                          {"_base": base})["warnings"]
        check("the preview warns when no Ship-To is picked",
              any("no Ship-To Party" in w for w in _pv0), f"{_pv0}")
        # Once the document HAS been read, an empty column means the PO does
        # not print that value - it must not still say "will be read from the
        # PO", which promises something that already happened.
        pv2 = OF.erp_excel.order_preview(
            {"po_number": "1"}, {"_base": base}, sold_to="1000006",
            ship_to="1000006",
            results=[{"po_number": "1", "po_date": "2026-10-14", "rdd": "",
                      "records": [], "ship_to_address": "9 WAY"}])
        blank = [r for r in pv2["rows"]
                 if r["letter"] in ("S", "T", "U", "V")]
        check("a column the PO does not print says so, after the reading",
              all(r["pending"] == "not printed on the PO" for r in blank),
              f"{[(r['letter'], r['pending']) for r in blank]}")
        check("...while a column it DOES print is filled from it",
              any(r["letter"] == "R" and r["value"] == "9 WAY"
                  and r["source"] == "from the PO" for r in pv2["rows"]),
              f"{[(r['letter'], r['value'], r['source']) for r in pv2['rows']]}")

        check("the preview reads the real letters off the template",
              [r["letter"] for r in pv["rows"] if r["field"] == "ship_to_region"]
              == ["AZ"],
              f"{[r['letter'] for r in pv['rows'] if r['field'] == 'ship_to_region']}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2c2d - K (R.D.D) and M (P/O Date) obey ONE precedence:
    #        typed on the row > what the PO printed > computed default.
    base = erp_base()
    try:
        res = [{"file": "po.pdf", "po_number": "P1",
                "po_date": "2026-10-14", "rdd": "2026-11-02",
                "rdd_defaulted": False,
                "ship_to_address": "9 ONE-OFF WAY",
                "ship_to_street2": "DOCK 4", "ship_to_city": "Newark",
                "ship_to_region": "NJ", "ship_to_zip": "07102",
                "records": [{"material_code": "RF28R7201SR", "quantity": "1",
                             "unit_price": "100.00", "description": ""}]}]
        path, _n, _a, _b, _c, _d = OF.erp_excel.build_upload(
            res, {"po_number": "P1"}, {"_base": base})
        ws2 = openpyxl.load_workbook(path).active
        k = ws2.cell(row=2, column=11).value
        m = ws2.cell(row=2, column=13).value
        r_addr = ws2.cell(row=2, column=18).value
        check("K (R.D.D) carries the date the PO printed",
              k is not None and k.strftime("%Y-%m-%d") == "2026-11-02",
              repr(k))
        check("M (P/O Date) carries the PO's own date, not the email's",
              m is not None and m.strftime("%Y-%m-%d") == "2026-10-14", repr(m))
        check("R carries the PO's delivery address",
              r_addr == "9 ONE-OFF WAY", repr(r_addr))

        # A date typed on the row overrides the document's.
        po_d, rdd_d, notes = OF.erp_excel._order_dates(
            res, {"po_date": "2026-10-20", "rdd": "2026-11-20"})
        check("a typed PO date overrides the printed one",
              po_d == "2026-10-20", po_d)
        check("a typed R.D.D overrides the printed one",
              rdd_d == "2026-11-20", rdd_d)
        check("...and the override is reported, not silent",
              any("typed for this order" in n for n in notes), f"{notes}")

        # Nothing printed and nothing typed: the email date is the last resort
        # for M, and K stays empty rather than inventing a delivery promise.
        po_d, rdd_d, _ = OF.erp_excel._order_dates(
            [{"po_number": "P1"}], {"received_at": "2026-10-14T09:00:00"})
        check("M falls back to the email date when the PO prints none",
              po_d == "2026-10-14T09:00:00", po_d)
        check("K is left empty when nothing gives a delivery date",
              rdd_d == "", rdd_d)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2c3 - an unreadable received date leaves M EMPTY rather than writing
    # something wrong.
    base = erp_base()
    try:
        res = [{"file": "po.pdf", "po_number": "P1", "records": [
            {"material_code": "RF28R7201SR", "quantity": "1",
             "unit_price": "10.00", "amount": "10.00", "description": "REF"}]}]
        for bad in ("not a date", "", None):
            mail = {"po_number": "P1", "sold_to": "", "ship_to": "",
                    "received_at": bad}
            p, _n, _a, _b, _c, _d = OF.erp_excel.build_upload(
                res, mail, {"_base": base}, fmt="full")
            wsb = openpyxl.load_workbook(p).active
            got = wsb.cell(row=2, column=13).value
            check(f"an unreadable received date ({bad!r}) leaves M empty",
                  got in (None, ""), repr(got))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2c4 - Quick Convert has no mail and no received date: M stays empty
    # rather than being filled with today's, which would be a guess.
    base = erp_base()
    try:
        p, _n = OF.erp_excel.build_upload_lines(
            [{"code": "RF28R7201SR", "qty": 1, "cost": 10.0}],
            {"_base": base}, tag="t", po="1")
        wsq = openpyxl.load_workbook(p).active
        got = wsq.cell(row=2, column=13).value
        check("Quick Convert (no mail) leaves M empty, does not invent a date",
              got in (None, ""), repr(got))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2c5 - the received date survives _master_values(); without that the mail
    # row never reaches the writer with the date on it and M is always blank.
    settings_mv = {"_base": erp_base()}
    try:
        mv = OF.server._master_values(
            {"po_number": "P1", "ship_to": "", "sold_to": "",
             "customer": "abt.com", "received_at": "2026-10-14T17:20:58"}, [])
        check("the server passes the received date through to the writer",
              mv.get("received_at") == "2026-10-14T17:20:58", f"{mv}")
    finally:
        shutil.rmtree(settings_mv["_base"], ignore_errors=True)

    # 2c5b - ...and so does EVERY field typed on the Inbox row. Confirm builds
    # its Order Upload from _master_values()'s return value, so a field this
    # function forgets is a field the ERP file never receives: the Ship-To
    # boxes showed "9 ONE-OFF WAY", Confirm ran, and column R came out empty
    # because the dict was a fixed five keys. Driven by the tuple, so a field
    # added to SHIP_DETAIL_FIELDS later cannot be silently left behind.
    typed = {f: f"V-{i}" for i, f in enumerate(OF.store.SHIP_DETAIL_FIELDS)}
    mv = OF.server._master_values(
        dict(typed, po_number="P1", ship_to="", sold_to="",
             customer="abt.com"), [])
    missing = [f for f in OF.store.SHIP_DETAIL_FIELDS if mv.get(f) != typed[f]]
    check("every Ship-To field typed on the row survives _master_values",
          not missing, f"dropped: {missing}")

    # 2c5c - and an EMPTY box is simply absent, so the ERP cell stays blank
    # instead of receiving an empty string.
    mv = OF.server._master_values(
        {"po_number": "P1", "ship_to": "", "sold_to": "", "customer": "x",
         "ship_to_address": "   "}, [])
    check("a blank Ship-To box passes no value at all",
          "ship_to_address" not in mv, f"{mv}")

    # 2c5d - the whole Confirm path, end to end: row -> _master_values ->
    # build_upload -> the workbook. This is the bug exactly as it reached the
    # user (an address typed on the Inbox row never appeared in the Order
    # Upload); 2c6 below only proves the writer accepts it when handed the row
    # directly, which is why it passed while the app did not.
    base = erp_base()
    try:
        res = [{"file": "po.pdf", "po_number": "P1", "records": [
            {"material_code": "RF28R7201SR", "quantity": "1",
             "unit_price": "10.00", "amount": "10.00", "description": "REF"}]}]
        row = {"po_number": "P1", "ship_to": "", "sold_to": "",
               "customer": "abt.com", "received_at": "2026-10-14T17:20:58",
               "ship_to_name": "ACME / JOB 12",
               "ship_to_name2": "C/O SITE OFFICE",
               "ship_to_address": "9 ONE-OFF WAY",
               "ship_to_street2": "UNIT 7",
               "ship_to_zip": "08861", "ship_to_city": "PERTH AMBOY",
               "ship_to_region": "NJ"}
        p, _n, _a, _b, _c, _d = OF.erp_excel.build_upload(
            res, OF.server._master_values(row, []), {"_base": base}, fmt="full")
        wsc = openpyxl.load_workbook(p).active
        # column letter -> index, so the check reads like the form does
        for letter, idx, want in (("N", 14, "ACME / JOB 12"),
                                  ("O", 15, "C/O SITE OFFICE"),
                                  ("R", 18, "9 ONE-OFF WAY"),
                                  ("S", 19, "UNIT 7"),
                                  ("W", 23, "08861"),
                                  ("X", 24, "PERTH AMBOY"),
                                  ("AZ", 52, "NJ")):
            got = wsc.cell(row=2, column=idx).value
            check(f"Confirm writes the typed {letter} into the Order Upload",
                  (got or "") == want, f"got {got!r}, want {want!r}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2c6 - an address typed on the Inbox row overrides the master's. This is
    # the per-order escape hatch: a one-off delivery address, or a site the
    # master has wrong. An EMPTY box must fall back to the master rather than
    # writing a blank into column R.
    base = erp_base()
    try:
        res = [{"file": "po.pdf", "po_number": "P1", "records": [
            {"material_code": "RF28R7201SR", "quantity": "1",
             "unit_price": "10.00", "amount": "10.00", "description": "REF"}]}]
        for label, addr, want in (
                ("a typed address overrides the master",
                 "9 ONE-OFF WAY", "9 ONE-OFF WAY"),
                ("...and an empty box falls back to the master",
                 "", "")):
            mail = {"po_number": "P1", "sold_to": "", "ship_to": "",
                    "ship_to_address": addr}
            p, _n, _a, _b, _c, _d = OF.erp_excel.build_upload(
                res, mail, {"_base": base}, fmt="full")
            wsa = openpyxl.load_workbook(p).active
            got = wsa.cell(row=2, column=18).value
            check(label, (got or "") == want, repr(got))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2c7 - ship_to_address is editable through the store, or the text box in
    # the Inbox row cannot save anything.
    base = erp_base()
    try:
        import orderflow as _OF
        conn = _OF.store.connect(os.path.join(base, "po_mail.db"))
        try:
            _OF.store.insert_mail(conn, {
                "message_id": "m1", "received_at": "2026-10-14T09:00:00",
                "sender": "a@b.com", "sender_domain": "b.com",
                "subject": "PO 1", "attachments": [], "pdf_paths": []})
            row = conn.execute("SELECT id FROM mails").fetchone()
            _OF.store.update_field(conn, row["id"], "ship_to_address",
                                   "5 TEST AVE")
            back = conn.execute(
                "SELECT ship_to_address FROM mails WHERE id=?",
                (row["id"],)).fetchone()["ship_to_address"]
            check("ship_to_address is an editable field on the mail row",
                  back == "5 TEST AVE", repr(back))

            # 2c7b - Confirm carries the on-screen block with its request and
            # writes it down before extracting. The box saves itself on blur,
            # which is the same click, so without this the two requests race
            # and the file can be built from a row that has no address yet.
            typed = _OF.server._typed_ship({"ship": {
                "ship_to_address": "  9 ONE-OFF WAY ", "ship_to_city": "PERTH",
                # not a Ship-To field: must be ignored, never written
                "status": "Done", "po_number": "HACK"}})
            check("Confirm accepts only the twelve Ship-To fields",
                  typed == {"ship_to_address": "9 ONE-OFF WAY",
                            "ship_to_city": "PERTH"}, f"{typed}")
            check("...and strips the spaces a person types",
                  typed.get("ship_to_address") == "9 ONE-OFF WAY", f"{typed}")

            _OF.server._persist_typed_ship(conn, row["id"], typed)
            got = conn.execute(
                "SELECT ship_to_address, status, po_number FROM mails "
                "WHERE id=?", (row["id"],)).fetchone()
            check("Confirm writes the typed block onto the row before building",
                  got["ship_to_address"] == "9 ONE-OFF WAY", repr(got["ship_to_address"]))
            check("...and writes nothing else from the request",
                  (got["status"] or "") != "Done" and
                  (got["po_number"] or "") != "HACK",
                  f"status={got['status']!r} po={got['po_number']!r}")

            # An emptied box must be written too, or a later re-Confirm puts
            # the address the user just cleared back into the file.
            _OF.server._persist_typed_ship(conn, row["id"],
                                           {"ship_to_address": ""})
            cleared = conn.execute(
                "SELECT ship_to_address FROM mails WHERE id=?",
                (row["id"],)).fetchone()["ship_to_address"]
            check("a cleared address is cleared on the row too",
                  (cleared or "") == "", repr(cleared))
        finally:
            conn.close()
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2d - ...including a line whose price is missing: the currency is a
    # constant, so it does not depend on the price having been found.
    base = erp_base()
    try:
        p, _n = OF.erp_excel.build_upload_lines(
            [{"code": "RF28R7201SR", "qty": 1}],
            {"_base": base}, tag="t", po="1")
        ws2d = openpyxl.load_workbook(p).active
        check("a line with no price still gets its currency",
              ws2d.cell(row=2, column=57).value in (None, "")
              and ws2d.cell(row=2, column=58).value == "USD",
              f"BE={ws2d.cell(row=2, column=57).value!r} "
              f"BF={ws2d.cell(row=2, column=58).value!r}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 2e - the SIMPLE sheet is four columns and has no currency column: the
    # request was for the full form, and adding one would change that file's
    # shape for every reader of it.
    base = erp_base()
    try:
        p, _n = OF.erp_excel.build_simple_lines(
            [{"code": "RF28R7201SR", "qty": 1, "cost": 10.0}],
            {"_base": base}, tag="t", po="1")
        ws2e = openpyxl.load_workbook(p).active
        heads = [c.value for c in next(ws2e.iter_rows(max_row=1))]
        check("the simple sheet keeps its four columns",
              ws2e.max_column == 4
              and heads == ["PO #", "Material", "Sales Quantity", "Unit Price"],
              f"{ws2e.max_column} cols: {heads}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 3 - the point of the change: the same headers in another ORDER
    # The six Ship-To columns are shuffled in too, and deliberately NOT at the
    # positions the template puts them (14 / 18 / 23 / 24 / 35), so a column
    # that resolved by position instead of by name would land in the wrong one.
    shuffled = (("Material(O)", 1), ("Division(M)", 2), ("Sales Quantity(M)", 3),
                ("Distr. Channel(M)", 4), ("EDI1 condition value(O)", 5),
                ("Sales Org.(M)", 6), ("Sold To Party(M)", 7),
                ("Ship To Paty(O)", 8), ("P/O No.(M)", 9),
                ("Ship-to City(O)", 10), ("Sold-to Name2(O)", 11),
                ("Ship-to Name(O)", 12), ("Ship-to Postal Code(O)", 13),
                ("EDI1 condition currency(O)", 14),
                ("Ship-to Address(O)", 15), ("P/O Date(O)", 16),
                ("Ship-to Name 2(O)", 17), ("Ship-to Name 3(O)", 18),
                ("Ship-to Name 4(O)", 19), ("Ship-to Street 2(O)", 20),
                ("Ship-to Street 3(O)", 21), ("Ship-to Street 4(O)", 22),
                ("Ship-to Street 5(O)", 23), ("Ship-to Region(O)", 24))
    base = erp_base(shuffled)
    try:
        _ws, cmap, rows, n = erp_export(
            base, [{"code": "WF45B6300AP", "qty": 2, "cost": 599.0}],
            po="95778")
        check("reordered form: each header found where it now sits",
              cmap == {"po": 9, "sales_org": 6, "distr_channel": 4,
                       "division": 2, "sold_to": 7, "ship_to": 8,
                       "code": 1, "qty": 3, "cost": 5, "currency": 14,
                       "ship_to_city": 10, "sold_to_name": 11,
                       "ship_to_name": 12, "ship_to_zip": 13,
                       "ship_to_address": 15, "po_date": 16,
                       "ship_to_name2": 17, "ship_to_name3": 18,
                       "ship_to_name4": 19, "ship_to_street2": 20,
                       "ship_to_street3": 21, "ship_to_street4": 22,
                       "ship_to_street5": 23, "ship_to_region": 24},
              f"got {cmap}")
        check("reordered form: values follow the headers",
              (rows[0]["code"], rows[0]["qty"], rows[0]["cost"],
               rows[0]["po"]) == ("WF45B6300AP", 2, 599.0, "95778"),
              f"{rows[0]}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 3b - a title/instruction block above the header row
    base = erp_base()
    try:
        p = os.path.join(base, "config", "erp_template.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(row=1, column=1, value="Standard Order Upload - instructions")
        ws.cell(row=2, column=1, value="Fill only the shaded columns")
        for text, col in FORM:
            ws.cell(row=3, column=col, value=text)
        wb.save(p)
        cmap2, notes2 = OF.erp_excel.column_map(wb.active)
        _ws2, cmap3, rows3, _n3 = erp_export(
            base, [{"code": "NE63T8111SS", "qty": 8, "cost": 911.0}],
            po="12345")
        check("a header row below a title block is still found",
              cmap2 == MAP and cmap3 == MAP, f"{cmap2} / {cmap3}")
        check("data starts under the header, not over the title block",
              rows3[0]["code"] == "NE63T8111SS" and rows3[0]["qty"] == 8,
              f"{rows3}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 4 - an UNKNOWN price header: keep the value at BE, but report it
    # ("Cost" would not do here - it is already one of the accepted spellings,
    #  which is exactly why an older form with that label kept working.)
    renamed = tuple((("Net value(O)", 57) if t.startswith("EDI1") else (t, c))
                    for t, c in FORM)
    base = erp_base(renamed)
    try:
        _ws, _cmap, rows, _n = erp_export(
            base, [{"code": "RF22A4221SR", "qty": 1, "cost": 1169.0}])
        check("unrecognised price header still receives the unit price",
              rows[0]["cost"] == 1169.0, f"{rows[0]}")
        notes = OF.erp_excel.column_map(
            openpyxl.load_workbook(
                os.path.join(base, "config", "erp_template.xlsx")).active)[1]
        check("unrecognised price header is reported, not silent",
              any("cost" in x for x in notes), f"notes={notes}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 4b - the label an older revision of the form used is understood as-is.
    # Only the PRICE header is renamed: matching on a bare "EDI1" would rename
    # the currency header too, and two headers cannot share one column.
    legacy = tuple((("Cost", 57) if t.startswith("EDI1 condition value")
                    else (t, c)) for t, c in FORM)
    base = erp_base(legacy)
    try:
        _ws, _cmap, rows, _n = erp_export(
            base, [{"code": "RF22A4221SR", "qty": 1, "cost": 1169.0}])
        notes = OF.erp_excel.column_map(
            openpyxl.load_workbook(
                os.path.join(base, "config", "erp_template.xlsx")).active)[1]
        check("a form labelled 'Cost' is understood with no fallback",
              rows[0]["cost"] == 1169.0 and not notes, f"{rows[0]}, notes={notes}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 5 - a missing qty or price stays EMPTY (a 0 would be a real order line)
    base = erp_base()
    try:
        _ws, _cmap, rows, _n = erp_export(
            base, [{"code": "WE402NP", "qty": "", "cost": ""}])
        check("no quantity / no price -> empty cells, not zeros",
              rows[0]["qty"] in (None, "") and rows[0]["cost"] in (None, ""),
              f"{rows[0]}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 6 - a line with no code is not written at all
    base = erp_base()
    try:
        _ws, _cmap, rows, n = erp_export(
            base, [{"code": "", "qty": 5, "cost": 100.0},
                   {"code": "DVE45B6300P", "qty": 2, "cost": 599.0}])
        check("a code-less line is skipped, the next one is not",
              n == 1 and rows[0]["code"] == "DVE45B6300P", f"n={n}, {rows}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 7 - a workbook that is not the form is refused, not written into
    base = tempfile.mkdtemp(prefix="oferp_")
    try:
        p = write_form(os.path.join(base, "config", "erp_template.xlsx"),
                       (("Totally different sheet", 1),))
        ok, why = OF.erp_excel.template_status({"_base": base})
        check("a non-ERP workbook is refused", not ok, f"ok={ok}")
        check("the refusal names the form, not just 'invalid file'",
              "Standard Order Upload" in why, why)
        try:
            OF.erp_excel.open_template({"_base": base})
            raised = False
        except RuntimeError:
            raised = True
        check("open_template raises for it instead of returning a worksheet",
              raised, f"path={p}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 8 - the shipped template, when this PC can read it
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tpl = OF.erp_excel.template_path(root)
    if not os.path.exists(tpl):
        check("shipped template present", False, f"missing: {tpl}")
    else:
        with open(tpl, "rb") as f:
            drm = f.read(2) != b"PK"
        if drm:
            print("  (shipped template is DRM-wrapped on this PC - "
                  "the column checks above used a generated one)")
        else:
            ws = openpyxl.load_workbook(tpl).active
            cmap, notes = OF.erp_excel.column_map(ws)
            ok, why = OF.erp_excel.validate_template(ws)
            check("shipped template: passes the format check", ok, why)
            check("shipped template: headers resolve to A / C / D / E / F / G / H / I / BE / BF",
                  cmap == MAP, f"got {cmap}, notes={notes}")
            left = sum(1 for r in range(2, ws.max_row + 1)
                       for c in range(1, ws.max_column + 1)
                       if ws.cell(row=r, column=c).value not in (None, ""))
            check("shipped template: data area is empty (a template, not an order)",
                  left == 0, f"{left} leftover cell(s) would be uploaded too")

    # 9 - the .XLSX spelling, which is how the shipped file is named, opens too
    # (Windows resolves either case, so this asserts the file is REACHED, not
    #  which spelling came back)
    base = erp_base(name="erp_template.XLSX")
    try:
        try:
            _wb, ws9 = OF.erp_excel.open_template({"_base": base})
            cmap9, _notes9 = OF.erp_excel.column_map(ws9)
            check("a template named erp_template.XLSX is opened",
                  cmap9 == MAP, f"got {cmap9}")
        except Exception as e:
            check("a template named erp_template.XLSX is opened", False, str(e))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # ------------------------------------------------------------------
    # 10 - the SIMPLE output: four columns, no template, opt-in only
    # ------------------------------------------------------------------
    E = OF.erp_excel

    # 10a - which string means which format. The dashboard sends "full" /
    # "simple", but the mapping must be explicit rather than "anything not
    # exactly 'full' means simple", or a typo would silently shrink the file.
    check("'simple' (any case) selects the four-column sheet",
          all(E.output_format(v) == "simple"
              for v in ("simple", "SIMPLE", "Simple", "simple-4col")),
          str([E.output_format(v) for v in ("simple", "SIMPLE", "Simple")]))
    check("'full' and anything unrecognised stay on the ERP form",
          all(E.output_format(v) == "full"
              for v in ("full", "FULL", "", None, "banana", "1", "xml")),
          str([E.output_format(v) for v in ("full", "", None, "banana")]))
    check("no value at all means the saved choice, then the full form",
          E.output_format("", "simple") == "simple"
          and E.output_format(None, "simple") == "simple"
          and E.output_format("banana", "simple") == "full")

    # 10a-2 - the choice is a LIST since 2026-10-27: both versions can be
    # ticked, and `output_formats()` is the ONE place that decides what a value
    # means. `output_format()` stays as its first entry for the corners that can
    # only draw one file.
    check("a single value normalises to a one-entry list",
          E.output_formats("simple") == ["simple"]
          and E.output_formats("full") == ["full"]
          and E.output_formats(None) == ["full"]
          and E.output_formats("") == ["full"]
          and E.output_formats("banana") == ["full"],
          str([E.output_formats(v) for v in ("simple", "full", None, "banana")]))
    check("a list keeps every version, deduped, in full-then-simple order",
          E.output_formats(["full", "simple"]) == ["full", "simple"]
          and E.output_formats(["simple", "full"]) == ["full", "simple"]
          and E.output_formats(["SIMPLE", "simple", "", "full"])
          == ["full", "simple"],
          str(E.output_formats(["simple", "full"])))
    check("an empty or junk list still yields one usable format",
          E.output_formats([]) == ["full"]
          and E.output_formats([None, ""]) == ["full"]
          and E.output_formats([], "simple") == ["simple"],
          str([E.output_formats([]), E.output_formats([None, ""])]))
    check("is_simple() means SIMPLE ONLY, not 'simple is one of them'",
          E.is_simple("simple") and not E.is_simple(["full", "simple"])
          and not E.is_simple("full"))
    check("output_format() is the FIRST of the list",
          E.output_format(["full", "simple"]) == "full"
          and E.output_format(["simple"]) == "simple")

    # ...and both files really are written from the same lines. This is the
    # whole point of the multi-select: one set of reviewed lines, two files.
    base = erp_base()
    try:
        lines = [{"code": "RF28R7201SR", "qty": 2, "cost": 1532.0}]
        made = [OF.quick_convert.export(lines, {"_base": base}, "t", "95778",
                                        one)
                for one in E.output_formats(["full", "simple"])]
        names = [os.path.basename(p) for p, _n in made]
        check("both ticked versions are written from one set of lines",
              len(names) == 2
              and names[0].startswith("OrderUpload_")
              and names[1].startswith("OrderUploadSimple_"), str(names))
        check("...each carrying the same single line",
              [n for _p, n in made] == [1, 1], str([n for _p, n in made]))
        simple_ws = openpyxl.load_workbook(made[1][0]).active
        check("...and the simple one really is four columns",
              simple_ws.max_column == 4, str(simple_ws.max_column))

        # The Confirm path (run_extractor_multi) does the same, off ONE reading
        # of the document. The reader is stubbed: this is about how many files
        # the loop writes and which format each one carries, not about
        # extraction (that is the `extract` suite).
        ONE = [{"po_number": "95778",
                "records": [{"material_code": "RF28R7201SR", "quantity": 2,
                             "unit_price": 1532.0,
                             "source_line": "RF28R7201SR EA 2 1532.00"}]}]
        real = OF.of_pdf.read_orders
        OF.of_pdf.read_orders = lambda paths, settings, force=True: (
            ONE, ["stub"], True)
        try:
            _ok, _msg, both = OF.extractor_bridge.run_extractor_multi(
                ["x.pdf"], {"_base": base}, {"po_number": "95778"},
                ["full", "simple"], force=False)
            check("one reading, two files, each labelled with its format",
                  [f for f, _p in both] == ["full", "simple"], str(both))
            _ok, _msg, one = OF.extractor_bridge.run_extractor_multi(
                ["x.pdf"], {"_base": base}, {"po_number": "95778"},
                "simple", force=False)
            check("asking for ONE version writes exactly one",
                  [f for f, _p in one] == ["simple"], str(one))
            # run_extractor() is the single-file wrapper the older callers use.
            _ok, _msg, p = OF.extractor_bridge.run_extractor(
                ["x.pdf"], {"_base": base}, {"po_number": "95778"},
                ["full", "simple"], force=False)
            check("run_extractor() returns the FIRST file as a plain path",
                  isinstance(p, str) and p.endswith(".xlsx")
                  and "Simple" not in os.path.basename(p),
                  repr(p))
        finally:
            OF.of_pdf.read_orders = real
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # 10b - a base with NO config\erp_template at all: the simple sheet must
    # not need one, which is the whole point of generating it from scratch.
    base = tempfile.mkdtemp(prefix="ofsimple_")
    try:
        simple_rows = [{"code": "RF28R7201SR", "qty": 2, "cost": 1532.0},
                       {"code": "WF45B6300AP", "qty": 3, "cost": 720.0}]
        p10, n10 = E.build_upload_lines(simple_rows, {"_base": base},
                                        tag="95778", po="95778", fmt="simple")
        ws10 = openpyxl.load_workbook(p10).active
        heads = [ws10.cell(row=1, column=c).value for c in range(1, 5)]
        check("simple sheet: exactly the four headers, in order",
              heads == ["PO #", "Material", "Sales Quantity", "Unit Price"]
              and ws10.max_column == 4, f"{heads}, max_col={ws10.max_column}")
        check("simple sheet is written without any ERP template present",
              os.path.exists(p10) and not os.path.exists(
                  os.path.join(base, "config", "erp_template.XLSX")),
              f"file={os.path.exists(p10)}")
        check("simple sheet: a line per row", n10 == 2 and ws10.max_row == 3,
              f"n={n10}, max_row={ws10.max_row}")
        got10 = [[ws10.cell(row=r, column=c).value for c in range(1, 5)]
                 for r in (2, 3)]
        check("simple sheet: PO # / Material / Quantity / Unit Price in A-D",
              got10 == [["95778", "RF28R7201SR", 2, 1532.0],
                        ["95778", "WF45B6300AP", 3, 720.0]], f"{got10}")
        check("simple sheet: quantity and price are numbers, not text",
              all(isinstance(ws10.cell(row=r, column=c).value, (int, float))
                  for r in (2, 3) for c in (3, 4)), f"{got10}")
        check("simple sheet: the price cell is formatted as money",
              ws10.cell(row=2, column=4).number_format == "#,##0.00",
              ws10.cell(row=2, column=4).number_format)
        check("simple sheet: file name says it is the simple version",
              os.path.basename(p10).startswith("OrderUploadSimple_")
              and "95778" in os.path.basename(p10),
              os.path.basename(p10))

        # 10c - a missing quantity stays an EMPTY cell. A 0 here would be
        # uploaded as a real order line of zero pieces.
        p10b, _n = E.build_upload_lines(
            [{"code": "NE63T8111SS", "qty": "", "cost": 911.0}],
            {"_base": base}, tag="t", po="", fmt="simple")
        ws10b = openpyxl.load_workbook(p10b).active
        check("simple sheet: an unknown quantity stays empty, never 0",
              ws10b.cell(row=2, column=3).value in (None, ""),
              repr(ws10b.cell(row=2, column=3).value))

        # 10d - the same call WITHOUT fmt must still want the ERP template:
        # the default has to stay the full form, so an older caller cannot
        # start producing the simple file just because this code exists.
        try:
            E.build_upload_lines(simple_rows, {"_base": base}, tag="t")
            check("omitting fmt still means the full ERP form", False,
                  "it produced a file without complaining about the missing "
                  "template - the default flipped to simple")
        except Exception as e:
            check("omitting fmt still means the full ERP form",
                  "template" in str(e).lower(), f"raised {e!r}")

        # 10e - and 'full' explicitly still uses the form when it IS there
        base_ok = erp_base()
        try:
            p10c, _n = E.build_upload_lines(
                simple_rows, {"_base": base_ok}, tag="t", po="4048073",
                fmt="full")
            check("fmt='full' still writes the ERP form, not the simple one",
                  not os.path.basename(p10c).startswith("OrderUploadSimple")
                  and openpyxl.load_workbook(p10c).active.max_column >= 57,
                  openpyxl.load_workbook(p10c).active.max_column)
        finally:
            shutil.rmtree(base_ok, ignore_errors=True)

        # 10f - the Confirm path (build_upload) shares the same switch, and
        # still leaves out the columns the simple sheet has no room for
        res10 = [{"po_number": "95778", "records": [
            {"material_code": "RF28R7201SR", "quantity": "2",
             "unit_price": "1532.00", "amount": "3064.00"},
            {"material_code": "WF45B6300AP", "quantity": "1",
             "unit_price": "720.00", "amount": "720.00"}]}]
        out10, n10b, noq10, noc10, _dr, _fx = E.build_upload(
            res10, {"po_number": "95778", "sold_to": "ACME",
                    "ship_to": "ACME #2"}, {"_base": base}, "simple")
        ws10c = openpyxl.load_workbook(out10).active
        rows10c = [[ws10c.cell(row=r, column=c).value for c in range(1, 6)]
                   for r in range(1, ws10c.max_row + 1)]
        check("Confirm path: same four columns, no Sold-To / Ship-To",
              rows10c == [["PO #", "Material", "Sales Quantity", "Unit Price",
                           None],
                          ["95778", "RF28R7201SR", 2, 1532.0, None],
                          ["95778", "WF45B6300AP", 1, 720.0, None]],
              f"{rows10c}")
        check("Confirm path: the four values pass through the same way",
              n10b == 2 and not noq10 and not noc10,
              f"n={n10b} no_qty={noq10} no_cost={noc10}")

        # 10g - a line without a Material Code is not written in either form
        try:
            E.build_upload_lines([{"code": "  ", "qty": 1, "cost": 1}],
                                 {"_base": base}, tag="t", fmt="simple")
            check("simple sheet: a blank Material Code is refused", False,
                  "an empty sheet was written")
        except Exception as e:
            check("simple sheet: a blank Material Code is refused",
                  "Material Code" in str(e), f"raised {e!r}")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 11 - the Ship-To master: the ONE customer table
    # ------------------------------------------------------------------
    # config/ship_to_master.json is the only customer data there is. Column C is
    # the DOMAIN - the identity a mail is matched by; the pair (SOLD_TO_CODE,
    # SHIP_TO_CODE) is the composite key the six ERP columns are filled from;
    # TYPE decides column D (exactly "Builder" -> 11, anything else -> 10).
    # config/ship_to_master.json holds the (SOLD_TO_CODE, SHIP_TO_CODE) pairs;
    # config/domain_master.json holds the domains, keyed by SOLD_TO_NAME. The
    # pair is the composite key the six ERP columns are filled from; TYPE
    # decides column D (exactly "Builder" -> 11, anything else -> 10); the
    # DOMAIN is the identity a mail is matched by, resolved from the second
    # table rather than stored per row.
    st_keys = [k for k, _h in OF.ship_master.ST_COLUMNS]

    def raises(fn, *a, **kw):
        """True when the call raises - for the refusals below."""
        try:
            fn(*a, **kw)
        except Exception:
            return True
        return False

    def st_row(sold, sold_name, domain, ship, ship_name, addr, city, zipc,
               typ, state="", plant="", mgr="", district="", region="",
               sub=""):
        rec = dict(zip(st_keys, (sold, sold_name, ship, ship_name,
                                 addr, city, zipc, plant, state, mgr,
                                 district, region, typ, sub)))
        rec["_domain"] = domain
        return rec

    def st_write(base, recs):
        cfg = os.path.join(base, "config")
        os.makedirs(cfg, exist_ok=True)
        pairs = [{k: v for k, v in r.items() if k != "_domain"} for r in recs]
        with open(os.path.join(cfg, "ship_to_master.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"uploaded_at": "2026-01-01T00:00:00",
                       "source_file": "test", "rows": pairs}, f)
        # One domain row per distinct (SOLD_TO_NAME, domain): the shape the ERP
        # file's second sheet arrives in.
        doms, seen = [], set()
        for r in recs:
            k = (r.get("sold_to_name"), r.get("_domain"))
            if r.get("_domain") and k not in seen:
                seen.add(k)
                doms.append({"sold_to_name": r.get("sold_to_name"),
                             "domain": r.get("_domain")})
        with open(os.path.join(cfg, "domain_master.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"uploaded_at": "2026-01-01T00:00:00",
                       "source_file": "test", "rows": doms}, f)

    ABT = st_row("1473893", "ABT ELECTRONICS, INC.", "abt.com", "1473894",
                 "ABT WAREHOUSE", "1200 MILWAUKEE AVE", "LINCOLNSHIRE",
                 "60069", "Builder")
    ABT2 = st_row("1462100", "ABT ELECTRONICS, INC.", "abt.com", "1462101",
                  "ABT CHICAGO", "1000 N MILWAUKEE AVE", "CHICAGO", "60642",
                  "Regionals")
    DIRECT = st_row("2430087", "ABT DIRECT", "abt-direct.com", "2430088",
                    "ABT DIRECT DC", "1 DIRECT WAY", "BOLINGBROOK", "60440",
                    "Builder Others")

    base = erp_base()
    try:
        settings = {"_base": base}
        st_write(base, [ABT, ABT2, DIRECT])

        # 11a - the composite key
        info, conflict = OF.ship_master.site(settings, "1473893", "1473894")
        check("the pair (Sold-To, Ship-To) resolves to its master row",
              bool(info) and info["ship_to_name"] == "ABT WAREHOUSE"
              and conflict is False, f"{info} / conflict={conflict}")
        check("the Sold-To name comes from that same row",
              info and info["sold_to_name"] == "ABT ELECTRONICS, INC.",
              f"{info}")
        check("the same Ship-To under another Sold-To is a different row",
              OF.ship_master.site(settings, "1462100", "1462101")[0]
              ["ship_to_name"] == "ABT CHICAGO")
        check("a pair that is not in the master -> (None, False)",
              OF.ship_master.site(settings, "1473893", "9999999")
              == (None, False))
        check("half a key -> (None, False) too",
              OF.ship_master.site(settings, "1473893", "") == (None, False))

        # 11b - column D: only an exact Builder is 11
        for raw, want in (("Builder", "11"), ("builder", "11"),
                          (" Builder ", "11"), ("Builder Others", "10"),
                          ("Regionals", "10"), ("BBY", "10"),
                          ("Accrual", "10"), ("NULL", "10"), ("", "10"),
                          (None, "10")):
            got = OF.ship_master.channel_for_type(raw)
            check(f"channel_for_type({raw!r}) -> {want}", got == want, got)

        # 11c - the six ERP columns on the Quick Convert path
        def read_row(path):
            ws = openpyxl.load_workbook(path).active
            cols = {"C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "N": 14, "R": 18,
                    "W": 23, "X": 24, "AI": 35}
            return {k: ws.cell(row=2, column=c).value for k, c in cols.items()}

        p, _n = OF.erp_excel.build_upload_lines(
            [{"code": "RF28R7201SR", "qty": 2, "cost": 1532.0}], settings,
            tag="95778", po="95778", sold_to="1473893", ship_to="1473894")
        got = read_row(p)
        check("Builder -> D = 11", got["D"] == "11", f"{got}")
        # N comes from the master (the account's name). R/W/X deliberately do
        # NOT: the master holds the billing site and a PO's delivery address is
        # routinely somewhere else, so those cells stay empty until they are
        # typed on the order.
        check("the Ship-To half of the key fills N only",
              got["N"] == "ABT WAREHOUSE", f"{got}")
        check("...and leaves R / W / X empty - typed, not inherited",
              (got["R"], got["W"], got["X"]) == (None, None, None), f"{got}")
        check("the Sold-To half fills AI",
              got["AI"] == "ABT ELECTRONICS, INC.", f"{got}")
        check("F / G still carry the two codes",
              (got["F"], got["G"]) == ("1473893", "1473894"), f"{got}")
        check("C / E are still the fixed sales area",
              (got["C"], got["E"]) == ("3101", "00"), f"{got}")
        check("the postal code is written as TEXT, so a leading zero survives",
              OF.erp_excel.write_line and "ship_to_zip" in
              OF.erp_excel.TEXT_FIELDS, f"{OF.erp_excel.TEXT_FIELDS}")

        # the same customer, another site: its OWN channel and address
        p2, _n2 = OF.erp_excel.build_upload_lines(
            [{"code": "RF28R7201SR", "qty": 1, "cost": 10.0}], settings,
            tag="95780", po="95780", sold_to="1462100", ship_to="1462101")
        got2 = read_row(p2)
        check("Regionals -> D = 10, off the same customer",
              got2["D"] == "10", f"{got2}")
        check("...and it brings its own NAME, still no inherited address",
              (got2["N"], got2["R"], got2["W"], got2["X"])
              == ("ABT CHICAGO", None, None, None), f"{got2}")

        # Typed on the order: the whole Ship-To block reaches its own columns.
        typed = {"ship_to_name": "DELIVERY DC", "ship_to_name2": "DOCK 4",
                 "ship_to_name3": "RECEIVING", "ship_to_name4": "C/O JOE",
                 "ship_to_address": "123 MAIN ST", "ship_to_street2": "UNIT 7",
                 "ship_to_street3": "BLDG B", "ship_to_street4": "GATE 2",
                 "ship_to_street5": "NORTH", "ship_to_zip": "08861",
                 "ship_to_city": "PERTH AMBOY", "ship_to_region": "NJ"}
        p_t, _nt = OF.erp_excel.build_upload_lines(
            [{"code": "RF28R7201SR", "qty": 1, "cost": 10.0}], settings,
            tag="95790", po="95790", sold_to="1473893", ship_to="1473894",
            ship=typed)
        _ws_t = openpyxl.load_workbook(p_t).active
        # column letter -> (header, expected value)
        for letter, want in (("N", "DELIVERY DC"), ("O", "DOCK 4"),
                             ("P", "RECEIVING"), ("Q", "C/O JOE"),
                             ("R", "123 MAIN ST"), ("S", "UNIT 7"),
                             ("T", "BLDG B"), ("U", "GATE 2"),
                             ("V", "NORTH"), ("W", "08861"),
                             ("X", "PERTH AMBOY"), ("AZ", "NJ")):
            c = openpyxl.utils.column_index_from_string(letter)
            got_t = _ws_t.cell(row=2, column=c).value
            check(f"typed ship-to writes column {letter}",
                  got_t == want, f"{letter}: {got_t!r} != {want!r}")
        check("'Builder Others' is NOT a Builder -> D = 10",
              OF.erp_excel.build_upload_lines(
                  [{"code": "RF28R7201SR", "qty": 1, "cost": 10.0}], settings,
                  tag="95781", po="95781", sold_to="2430087",
                  ship_to="2430088")[0]
              and read_row(OF.erp_excel.build_upload_lines(
                  [{"code": "RF28R7201SR", "qty": 1, "cost": 10.0}], settings,
                  tag="95782", po="95782", sold_to="2430087",
                  ship_to="2430088")[0])["D"] == "10")

        # a pair the master does not know: the six stay EMPTY, F / G still go
        p3, _n3 = OF.erp_excel.build_upload_lines(
            [{"code": "RF28R7201SR", "qty": 1, "cost": 10.0}], settings,
            tag="95783", po="95783", sold_to="1473893", ship_to="9999999")
        got3 = read_row(p3)
        check("an unknown pair leaves N / R / W / X / AI / D empty",
              all(got3[k] in (None, "") for k in ("D", "N", "R", "W", "X", "AI")),
              f"{got3}")
        check("...but the codes the user picked are still written",
              (got3["F"], got3["G"]) == ("1473893", "9999999"), f"{got3}")

        # ...and the Confirm path takes the same pair off the mail row
        res = [{"po_number": "95778", "records": [
            {"material_code": "RF28R7201SR", "quantity": "2",
             "unit_price": "1532.00", "amount": "3064.00"}]}]
        out, _a, _b, _c, _d, _e = OF.erp_excel.build_upload(
            res, {"po_number": "95778", "sold_to": "1473893",
                  "ship_to": "1473894"}, settings, "full")
        ws4 = openpyxl.load_workbook(out).active
        check("Confirm path: C / D / E / F / G / N / AI all filled",
              [ws4.cell(row=2, column=c).value for c in (3, 4, 5, 6, 7, 14, 35)]
              == ["3101", "11", "00", "1473893", "1473894", "ABT WAREHOUSE",
                  "ABT ELECTRONICS, INC."],
              f"{[ws4.cell(row=2, column=c).value for c in (3, 4, 5, 6, 7, 14, 35)]}")

        # 11d - a pair listed twice with DIFFERENT details is a conflict: the six
        # cells stay empty and the pair is reported, never guessed at.
        conf_recs = [dict(ABT), dict(ABT, ship_to_name="ABT WAREHOUSE #2")]
        st_write(base, conf_recs)
        info2, conflict2 = OF.ship_master.site(settings, "1473893", "1473894")
        check("a repeated pair with different details reports conflict=True",
              bool(info2) and conflict2 is True, f"{info2} / {conflict2}")
        check("conflicts() names the pair",
              OF.ship_master.conflicts(conf_recs) == [("1473893", "1473894", 2)],
              f"{OF.ship_master.conflicts(conf_recs)}")
        pc, _nc = OF.erp_excel.build_upload_lines(
            [{"code": "RF28R7201SR", "qty": 1, "cost": 10.0}], settings,
            tag="conf", po="conf", sold_to="1473893", ship_to="1473894")
        gotc = read_row(pc)
        check("a conflicting pair leaves every one of the six cells empty",
              all(gotc[k] in (None, "") for k in ("D", "N", "R", "W", "X", "AI")),
              f"{gotc}")
        st_write(base, [dict(ABT), dict(ABT)])      # same details twice
        check("an exact duplicate is NOT a conflict - it is the same row twice",
              OF.ship_master.conflicts([dict(ABT), dict(ABT)]) == []
              and OF.ship_master.site(settings, "1473893", "1473894")[1] is False)

        # 11e - the drop-downs: the domain decides the range, then the Sold-To
        st_write(base, [ABT, ABT2, DIRECT])
        sold = OF.ship_master.sold_options(settings, "@ABT.com")
        check("sold_options lists only this domain's Sold-To codes",
              [s["code"] for s in sold] == ["1462100", "1473893"],
              f"{[s['code'] for s in sold]}")
        check("...each carrying its TYPE and the channel D will get",
              [(s["code"], s["type"], s["channel"]) for s in sold]
              == [("1462100", "Regionals", "10"),
                  ("1473893", "Builder", "11")],
              f"{sold}")
        check("another domain gets its own list",
              [s["code"] for s in OF.ship_master.sold_options(
                  settings, "abt-direct.com")] == ["2430087"])
        check("a domain the master does not carry gets nothing",
              OF.ship_master.sold_options(settings, "nope.com") == [])
        ships = OF.ship_master.ship_options(settings, "abt.com")
        check("ship_options lists both of the domain's sites",
              [s["code"] for s in ships] == ["1462101", "1473894"],
              f"{[s['code'] for s in ships]}")
        check("...and carries the channel to show in the label",
              [(s["code"], s["channel"]) for s in ships]
              == [("1462101", "10"), ("1473894", "11")], f"{ships}")
        narrowed = OF.ship_master.ship_options(settings, "abt.com", "1473893")
        check("picking a Sold-To narrows the Ship-To list to its own sites",
              [s["code"] for s in narrowed] == ["1473894"],
              f"{[s['code'] for s in narrowed]}")
        check("...and the other Sold-To gives the other site",
              [s["code"] for s in OF.ship_master.ship_options(
                  settings, "abt.com", "1462100")] == ["1462101"])

        # 11f - the editor the Customer Master table drives
        check("page() hands out the row's position, which is what edits use",
              [r["_i"] for r in OF.ship_master.page(settings, "", 10, 0)[0]]
              == [0, 1, 2] and OF.ship_master.page(settings, "", 10, 0)[1] == 3)
        check("page() windows without losing the absolute index",
              [r["_i"] for r in OF.ship_master.page(settings, "", 1, 1)[0]] == [1])
        check("page(): the search box matches a Ship-To name",
              OF.ship_master.page(settings, "chicago", 10, 0)[1] == 1)
        check("page(): the domain is NOT searched here - it is the other table",
              OF.ship_master.page(settings, "abt-direct", 10, 0)[1] == 0)
        check("dm_page(): ...and the domain table's own search box",
              OF.ship_master.dm_page(settings, "direct", 10, 0)[1] == 1
              and OF.ship_master.dm_page(settings, "abt", 10, 0)[1] == 2)
        check("matches() is the same test, for the filtered export",
              OF.ship_master.matches(ABT, "ABT WAREHOUSE")
              and not OF.ship_master.matches(ABT, "chicago"))
        at = OF.ship_master.add_row(settings, blank=True)
        check("add_row(blank) appends an empty row and returns its index",
              at == 3 and OF.ship_master.rows(settings)[at]["sold_to_code"] == "")
        check("add_row refuses a row that names nothing, unless blank is asked",
              raises(OF.ship_master.add_row, settings, {}))
        OF.ship_master.set_cell(settings, at, "ship_to_name", "NEW SITE")
        check("set_cell writes one field of one row",
              OF.ship_master.rows(settings)[at]["ship_to_name"] == "NEW SITE")
        check("set_cell refuses a field that is not a column",
              OF.ship_master.set_cell(settings, at, "nope", "x") is False)
        check("set_cell refuses the old per-row domain column",
              OF.ship_master.set_cell(settings, at, "domain", "x") is False)
        check("set_cell refuses a row that is not there",
              OF.ship_master.set_cell(settings, 99, "ship_to_name", "x") is False)
        check("delete_row removes it",
              OF.ship_master.delete_row(settings, at)
              and len(OF.ship_master.rows(settings)) == 3)
        check("delete_row on a row that is not there -> False",
              OF.ship_master.delete_row(settings, 99) is False)

        # -- the DOMAIN table is editable in its own right -------------------
        # Two rows, not three: the two ABT pairs share a SOLD_TO_NAME and a
        # domain, and one row per (name, domain) is what the ERP sheet carries.
        check("the domain table is a separate file with its own rows",
              [r["domain"] for r in OF.ship_master.dm_rows(settings)]
              == ["abt.com", "abt-direct.com"])
        dat = OF.ship_master.dm_add(settings, {"sold_to_name": "NEWCO",
                                               "domain": "newco.com"})
        check("dm_add appends and returns its index",
              dat == 2 and OF.ship_master.dm_rows(settings)[dat]["domain"]
              == "newco.com")
        check("dm_add refuses a row that names nothing, unless blank is asked",
              raises(OF.ship_master.dm_add, settings, {}))
        OF.ship_master.dm_set_cell(settings, dat, "domain", "NewCo.com")
        check("dm_set_cell writes one field of one row",
              OF.ship_master.dm_rows(settings)[dat]["domain"] == "NewCo.com")
        check("dm_set_cell refuses a field that is not a column",
              OF.ship_master.dm_set_cell(settings, dat, "nope", "x") is False)
        check("dm_set_cell refuses a row that is not there",
              OF.ship_master.dm_set_cell(settings, 99, "domain", "x") is False)
        check("dm_delete_row removes it",
              OF.ship_master.dm_delete_row(settings, dat)
              and len(OF.ship_master.dm_rows(settings)) == 2)
        check("dm_delete_row on a row that is not there -> False",
              OF.ship_master.dm_delete_row(settings, 99) is False)
        check("dm_clear empties only the domain table",
              OF.ship_master.dm_clear(settings) == 2
              and not OF.ship_master.dm_rows(settings)
              and len(OF.ship_master.rows(settings)) == 3)
        check("...and the pairs survive, unowned, which is honest",
              OF.ship_master.site(settings, "1473893", "1473894")[0]["domain"]
              == "")
        check("dm_page()/dm_matches() serve the domain grid",
              OF.ship_master.dm_page(settings, "", 10, 0)[1] == 0
              and OF.ship_master.dm_page(settings, "zzz", 10, 0)[1] == 0)
        check("clear() empties the table and says how many went",
              OF.ship_master.clear(settings) == 3
              and OF.ship_master.rows(settings) == [])
        check("status() counts what is left",
              OF.ship_master.status(settings)["total"] == 0
              and OF.ship_master.status(settings)["domains"] == 0)

        # 11g - reading the uploaded file: by HEADER NAME, on the real sheet
        cfg = os.path.join(base, "config")
        # The pair sheet carries no Domain column any more; the domain lives on
        # its own sheet, exactly as ERP ships it.
        sheet = [list(OF.ship_master.ST_HEADERS)]
        sheet.append(["1473893", "ABT ELECTRONICS, INC.", "1473894",
                      "ABT WAREHOUSE", "1200 MILWAUKEE AVE", "LINCOLNSHIRE",
                      "60069", "1010", "IL", "R. SMITH", "MIDWEST", "NORTH",
                      "Builder", "Big Box"])
        sheet.append(["", "", "", "", "", "", "", "", "", "", "", "", "", ""])
        path = write_wb(os.path.join(base, "st.xlsx"), {"Sheet1": sheet})
        recs = OF.ship_master.parse_file(path)
        check("parse_file reads the file's own header by name",
              len(recs) == 1 and recs[0]["ship_to_name"] == "ABT WAREHOUSE",
              f"{recs}")
        check("...and drops the trailing blank row",
              recs[0]["zip"] == "60069" and recs[0]["type"] == "Builder",
              f"{recs}")
        r = OF.ship_master.upload(settings, path, "st.xlsx")
        check("upload rebuilds the table and reports what it read",
              r["rows"] == 1 and r["domains"] == 0 and r["sold_tos"] == 1
              and r["ship_tos"] == 1, f"{r}")
        check("...including the TYPE breakdown and the conflict count",
              r["types"] == {"Builder": 1} and r["conflict_count"] == 0, f"{r}")
        check("upload refuses a file that is not the Ship-To master",
              raises(OF.ship_master.parse_file,
                      write_wb(os.path.join(base, "junk.xlsx"),
                               {"Sheet1": [["a", "b"], ["1", "2"]]})))

        # 11h - the DOMAIN sheet: its own header, its own upload
        dsheet = [list(OF.ship_master.DM_HEADERS)]
        dsheet.append(["ABT ELECTRONICS, INC.", "abt.com"])
        dsheet.append(["", ""])
        dpath = write_wb(os.path.join(base, "dm.xlsx"), {"Sheet1": dsheet})
        drecs = OF.ship_master.dm_parse_file(dpath)
        check("dm_parse_file reads its own header by name",
              drecs == [{"sold_to_name": "ABT ELECTRONICS, INC.",
                         "domain": "abt.com"}], f"{drecs}")
        dr = OF.ship_master.dm_upload(settings, dpath, "dm.xlsx")
        check("dm_upload rebuilds the domain table and reports what it read",
              dr["rows"] == 1 and dr["domains"] == 1
              and dr["named"] == 1 and dr["unmatched_names"] == 0, f"{dr}")
        check("...and the pair now resolves to that domain",
              OF.ship_master.site(settings, "1473893", "1473894")[0]["domain"]
              == "abt.com")
        check("a domain-only upload leaves the pair table alone",
              len(OF.ship_master.rows(settings)) == 1)
        check("dm_parse_file refuses a file that is not the domain table",
              raises(OF.ship_master.dm_parse_file,
                      write_wb(os.path.join(base, "junk2.xlsx"),
                               {"Sheet1": [["a", "b"], ["1", "2"]]})))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("=" * 68)
    print("ERP Upload columns - regression tests")
    print("=" * 68)
    for ok, label, detail in checks:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {label}")
        if not ok and detail:
            print(f"         {detail}")
    print("-" * 68)
    print(f"  {len(checks) - failed}/{len(checks)} passed")
    if failed:
        print(f"  {failed} FAILED")
    return 1 if failed else 0


# ==========================================================================
#  SECTION: CUSTOMER CLASSIFICATION - the domain, and nothing else
#  (formerly selftest_classify.py). There is no customer file any more: the
#  identity list IS the Ship-To master, one entry per DOMAIN (column C).
# ==========================================================================

def run_classify():
    import orderflow as CL

    checks, failed = [], 0

    def check(label, ok, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, label, detail))

    C = CL.classifier

    # 1 - whatever the user types, one domain comes out
    for raw, want in (("abt.com", "abt.com"), ("@abt.com", "abt.com"),
                      ("ABT.COM", "abt.com"), (" www.abt.com ", "abt.com"),
                      ("builderpos@abt.com", "abt.com"),
                      ("Bob Smith <bob@abt.com>", "abt.com"),
                      ("abt.com.", "abt.com"), ("", ""), (None, "")):
        got = C.norm_domain(raw)
        check(f"norm_domain({raw!r}) -> {want!r}", got == want, f"got {got!r}")

    base = tempfile.mkdtemp(prefix="ofcls_")
    try:
        settings = {"_base": base}
        keys = [k for k, _h in CL.ship_master.ST_COLUMNS]

        def seed(recs):
            cfg = os.path.join(base, "config")
            os.makedirs(cfg, exist_ok=True)
            pairs = [{k: v for k, v in r.items() if k != "_domain"}
                     for r in recs]
            with open(os.path.join(cfg, "ship_to_master.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"uploaded_at": "2026-01-01T00:00:00",
                           "source_file": "test", "rows": pairs}, f)
            doms, seen = [], set()
            for r in recs:
                k = (r.get("sold_to_name"), r.get("_domain"))
                if r.get("_domain") and k not in seen:
                    seen.add(k)
                    doms.append({"sold_to_name": r.get("sold_to_name"),
                                 "domain": r.get("_domain")})
            with open(os.path.join(cfg, "domain_master.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"uploaded_at": "2026-01-01T00:00:00",
                           "source_file": "test", "rows": doms}, f)
            return CL.ship_master.domain_master(settings)

        def row(sold, sold_name, domain, ship, ship_name, typ):
            rec = dict(zip(keys, (sold, sold_name, ship, ship_name,
                                  "", "", "", "", "", "", "", "", typ, "")))
            rec["_domain"] = domain
            return rec

        # 2 - the master folds the table down to one entry per DOMAIN
        m = seed([
            row("1473893", "ABT ELECTRONICS, INC.", "abt.com", "1473894",
                "ABT WAREHOUSE", "Builder"),
            row("1462100", "ABT ELECTRONICS, INC.", "abt.com", "1462101",
                "ABT CHICAGO", "Builder"),
            row("9000001", "CLAYTON HOMES", "claytonhomes.com", "9000002",
                "CLAYTON YARD", "Regionals"),
            row("9000003", "OAKWOOD HOMES", "oakwoodhomesco.com", "9000004",
                "OAKWOOD YARD", "Builder"),
        ])
        check("one entry per DOMAIN, in first-seen order",
              [g["customer"] for g in m]
              == ["abt.com", "claytonhomes.com", "oakwoodhomesco.com"],
              f"{[g['customer'] for g in m]}")
        abt = m[0]
        check("the domain is the entry's identity AND its domain list",
              abt["domains"] == ["abt.com"], f"{abt['domains']}")
        check("the entry unions the domain's Sold-To / Ship-To codes",
              abt["sold_to_list"] == ["1473893", "1462100"]
              and abt["ship_to_list"] == ["1473894", "1462101"],
              f"{abt['sold_to_list']} / {abt['ship_to_list']}")
        check("Builder only when EVERY row of the domain is a Builder",
              abt["role"] == "Builder" and m[1]["role"] == "Retail",
              f"{abt['role']!r} / {m[1]['role']!r}")
        check("a domain of two different companies stays two entries",
              len(m) == 3)
        check("a row with no domain is not an identity at all",
              all(g["customer"] for g in seed([
                  row("1", "X", "", "2", "Y", "Builder")])))

        # 3 - matching: the domain, and nothing else
        def who(addr, dom=""):
            e = C.match_customer(addr, dom, m)
            return e["customer"] if e else None

        check("a brand new person at a known domain is recognised",
              who("someone.new@abt.com") == "abt.com", f"{who('someone.new@abt.com')}")
        check("the address itself is ignored: every @abt.com sender matches",
              who("builderpos@abt.com") == who("random@abt.com") == "abt.com")
        check("a subdomain belongs to the domain that owns the parent",
              who("orders@mail.abt.com") == "abt.com")
        check("the customer's other domain matches too",
              who("todd@oakwoodhomesco.com") == "oakwoodhomesco.com")
        check("stored sender_domain is used when the address is missing",
              who("", "claytonhomes.com") == "claytonhomes.com")
        check("an unknown domain stays unclassified", who("a@nope.com") is None)
        check("an empty sender is not a match", who("") is None)
        check("a contact address outside the domain does not match",
              who("logistics@transgroup.com") is None)

        # 4 - the most specific domain wins over its parent
        both = m + [
            dict(m[0], customer="sea.samsung.com", domains=["sea.samsung.com"]),
            dict(m[0], customer="samsung.com", domains=["samsung.com"])]
        check("mail.sea.samsung.com -> the more specific domain",
              C.match_customer("a@mail.sea.samsung.com", "", both)["customer"]
              == "sea.samsung.com")
        check("plain samsung.com -> the parent",
              C.match_customer("a@samsung.com", "", both)["customer"]
              == "samsung.com")
        check("the other domains still match alongside them",
              C.match_customer("a@abt.com", "", both)["customer"] == "abt.com")

        # 5 - a domain that somehow appears twice cannot decide anything
        clash = [dict(g) for g in m] + [
            dict(m[0], customer="Impostor", domains=["abt.com"])]
        check("a domain claimed twice classifies as nobody",
              C.match_customer("x@abt.com", "", clash) is None)
        check("...and is reported so it can be fixed",
              C.domain_conflicts(clash)
              == [("abt.com", ["abt.com", "Impostor"])],
              f"{C.domain_conflicts(clash)}")
        check("the other domains still match while one is in conflict",
              C.match_customer("x@claytonhomes.com", "", clash)["customer"]
              == "claytonhomes.com")
        check("a clean master has no conflicts",
              C.domain_conflicts(m) == [])

        # 6 - classify() end to end: the domain, then the DEFAULT PO rule
        cust, po, entry = C.classify(
            {"sender": "new.person@claytonhomes.com",
             "sender_domain": "claytonhomes.com",
             "subject": "Purchase Order 177772869 attached", "attachments": []},
            m, SETTINGS)
        check("classify(): the domain picks the customer, the default rule the PO",
              (cust, po) == ("claytonhomes.com", "177772869"), f"{cust} / {po}")
        check("classify(): the entry is the master row itself",
              entry is m[1], f"{entry and entry['customer']}")
        cust, po, entry = C.classify(
            {"sender": "a@nope.com", "sender_domain": "nope.com",
             "subject": "Purchase Order 177772869", "attachments": []},
            m, SETTINGS)
        check("classify(): unknown domain -> no customer, PO still read",
              cust is None and po == "177772869", f"{cust} / {po}")

        # 7 - public providers are flagged: claiming one hands over everybody
        check("gmail.com is a public provider", C.public_domain("gmail.com"))
        check("abt.com is not", not C.public_domain("abt.com"))
        check("the provider list survives a full address",
              C.public_domain("@GMail.com"))

        # 8 - mail_domain prefers the address over a stored column
        check("mail_domain reads the address",
              C.mail_domain("bob@abt.com", "wrong.com") == "abt.com")
        check("...and falls back to the stored column when there is none",
              C.mail_domain("", "claytonhomes.com") == "claytonhomes.com")
        check("both empty -> empty", C.mail_domain("", "") == "")

        # 9 - the identity list is rebuilt from the table, so a re-upload
        # re-classifies everything with no second file to keep in step
        m2 = seed([row("9000001", "CLAYTON HOMES", "claytonhomes.com",
                       "9000002", "CLAYTON YARD", "Regionals")])
        check("dropping a domain from the table drops the customer",
              [g["customer"] for g in m2] == ["claytonhomes.com"]
              and C.match_customer("a@abt.com", "", m2) is None)

        # 10 - READING a master must not touch the disk (2026-10-27).
        #
        # The `*_path()` helpers each ran os.makedirs(exist_ok=True). That
        # syscall costs ~2.3 ms on the target filesystem (the expensive part
        # is the mkdir that FAILS), and `domain_master()` calls
        # `domain_of()` once per row of the pair table - so a screen that
        # shows 465 domains spent 34 seconds creating "config" over and over.
        # The rule is now: reads stat, writes create. This asserts the rule,
        # not a stopwatch, so it cannot go flaky on a fast machine.
        base2 = tempfile.mkdtemp(prefix="ofcls_ro_")
        try:
            s2 = {"_base": base2}
            cfg2 = os.path.join(base2, "config")
            ST, MM = CL.ship_master, CL.material_master
            MOD = CL.of_master          # for the private index builder
            # every read entry point the dashboard actually hits
            ST._path(s2)                # st_path
            ST.dm_path(s2)
            MM._path(s2)                # mm_path
            MM.dismissed_path(s2)
            ST.load(s2)
            ST.dm_load(s2)
            ST.rows(s2)
            ST.dm_rows(s2)
            ST.domain_master(s2)
            ST.status(s2)
            MM.load(s2)                 # mm_load
            MM.dismissed_codes(s2)
            ST.domain_of(s2, {"sold_to_name": "ACME", "sold_to_code": "1"})
            check("reading the masters creates no directory",
                  not os.path.isdir(cfg2))

            ST.save(s2, {"rows": [{"sold_to_name": "ACME INC",
                                  "sold_to_code": "7"}]})
            ST.dm_save(s2, {"rows": [{"sold_to_name": "ACME INC",
                                      "domain": "acme.com"}]})
            check("...saving one does create it", os.path.isdir(cfg2))
            check("...and the row reads back",
                  ST.domain_of(s2, {"sold_to_name": "Acme Inc"}) == "acme.com")

            # The index is built ONCE and then reused: 40 lookups, 1 build.
            # It used to be re-checked twice per call (dm_exact + dm_index).
            builds = []
            real = MOD._dm_build
            MOD._DM_CACHE = {"key": None, "by_name": {}, "by_code": {},
                             "by_exact": {}}

            def counting(settings_, key):
                builds.append(key)
                return real(settings_, key)

            MOD._dm_build = counting
            try:
                for _ in range(40):
                    ST.domain_of(s2, {"sold_to_name": "Acme Inc",
                                      "sold_to_code": "7"})
            finally:
                MOD._dm_build = real
            check("the domain index is built once for 40 lookups",
                  len(builds) == 1, f"built {len(builds)}x")

            # 11 - the change signal must cover BOTH tables (2026-10-27).
            # A customer is a DOMAIN, and only the domain table can give one a
            # customer name - so writing THAT file has to move the signal the
            # server caches the identity list on. Keyed on the pair table alone,
            # "add a domain row" did nothing visible in the Inbox until the
            # server was restarted.
            k1 = ST.master_key(s2)
            ST.dm_save(s2, {"rows": [{"sold_to_name": "OTHER CO",
                                      "domain": "other.com"}]})
            check("writing the DOMAIN table moves master_key()",
                  ST.master_key(s2) != k1)
            check("...and the new domain is in the list immediately",
                  [g["customer"] for g in ST.domain_master(s2)]
                  == ["other.com"],
                  f"{[g['customer'] for g in ST.domain_master(s2)]}")
        finally:
            shutil.rmtree(base2, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    for ok, label, detail in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {label}"
              + (f"   [{detail}]" if not ok and detail else ""))
    print(f"\n  {len(checks) - failed}/{len(checks)} passed")
    return failed


# ==========================================================================
#  SECTION: P0 FIXES - the four defects fixed on 2026-10-11
#
#  Each of these was a silent failure, which is why none of them had a test:
#    1  a master file that cannot be parsed was read as an EMPTY master, so one
#       truncated write unclassified every stored mail and was then saved back
#    2  the browser, Confirm and /api/open each narrowed the attachment list
#       differently, so one row index meant three different files
#    3  nothing ever set erp_uploaded, so the Order Upload list could not drain
#    4  settings.source was never sent, so "Sync this date" never rendered
# ==========================================================================

def run_p0():
    import orderflow as OF

    checks, failed = [], 0

    def check(label, ok, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, label, detail))

    store = OF.store

    # ---- 1. master files: atomic write, never "empty" when unreadable ----
    base = tempfile.mkdtemp(prefix="ofp0_")
    try:
        os.makedirs(os.path.join(base, "config"), exist_ok=True)
        settings = {"_base": base}
        mm, sm = OF.material_master, OF.ship_master

        check("a missing master is still the ordinary empty state",
              mm.load(settings) == {"codes": {}}
              and sm.load(settings)["rows"] == [])

        mm.save(settings, {"codes": {"A1": {"code": "A1"}}})
        check("material master round-trips",
              mm.load(settings)["codes"]["A1"]["code"] == "A1")

        # No .tmp left behind: the atomic write must always clean up.
        left = [f for f in os.listdir(os.path.join(base, "config"))
                if f.endswith(".tmp")]
        check("the atomic write leaves no .tmp file", left == [], str(left))

        # The actual defect: truncated JSON must NOT read as empty.
        sp = sm._path(settings)
        with open(sp, "w", encoding="utf-8") as f:
            f.write('{"rows": [{"domain": "abt.com"')      # cut mid-write
        raised = False
        try:
            sm.load(settings)
        except RuntimeError as e:
            raised = True
            check("the corrupt-master error names the backup copy",
                  ".corrupt-" in str(e))
        check("a corrupt master raises instead of reading as empty", raised)
        check("the unreadable bytes are left on disk, not destroyed",
              os.path.exists(sp))

        # ...and it must STAY raised: a "move it aside" fix would have let the
        # second read succeed with an empty table, which is the same bug one
        # request later.
        still = False
        try:
            sm.load(settings)
        except RuntimeError:
            still = True
        check("the corrupt state is sticky across reads", still)

        # The documented recovery must work.
        sm.save(settings, {"uploaded_at": "t", "source_file": "f",
                           "rows": [{"domain": "sea.samsung.com"}]})
        check("re-uploading a master recovers from the corrupt state",
              sm.load(settings)["rows"][0]["domain"] == "sea.samsung.com")

        # The domain table is a second master file and must fail closed the
        # same way: a truncated write cannot read as "no customers".
        dp = sm.dm_path(settings)
        with open(dp, "w", encoding="utf-8") as f:
            f.write('{"rows": [{"domain": "abt.com"')
        raised_dm = False
        try:
            sm.dm_load(settings)
        except RuntimeError as e:
            raised_dm = True
            check("a corrupt domain table raises too", ".corrupt-" in str(e))
        check("...and is not read as an empty table", raised_dm)
        sm.dm_save(settings, {"uploaded_at": "t", "source_file": "f",
                              "rows": [{"sold_to_name": "ABT",
                                        "domain": "abt.com"}]})
        check("re-uploading the domain table recovers",
              sm.dm_rows(settings)[0]["domain"] == "abt.com")

        # A BOM must still parse (PowerShell has written one before).
        with open(mm._path(settings), "w", encoding="utf-8-sig") as f:
            json.dump({"codes": {"B2": {"code": "B2"}}}, f)
        check("utf-8-sig BOM is tolerated",
              mm.load(settings)["codes"]["B2"]["code"] == "B2")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # ---- 2. one attachment list, one index space ----
    # A price sheet saved BEFORE the PO is the shape that broke: the page
    # narrowed to ".pdf" (index 0 = order.pdf) while the server narrowed to
    # four kinds (index 0 = quote.xlsx).
    paths = ["data/attachments/2026-10/aaaaaaaa_quote.xlsx",
             "data/attachments/2026-10/bbbbbbbb_order.pdf"]
    docs = store.order_attachments(paths)
    check("both a price sheet and a PO count as order documents",
          [i for i, _p in docs] == [0, 1], str(docs))
    check("index 0 stays the xlsx that was saved first",
          docs[0][1].endswith("quote.xlsx"), docs[0][1])

    # A non-order file must not renumber the ones after it.
    mixed = ["data/attachments/2026-10/cccccccc_notes.txt",
             "data/attachments/2026-10/dddddddd_order.pdf",
             "data/attachments/2026-10/eeeeeeee_spec.xlsx"]
    docs = store.order_attachments(mixed)
    check("a .txt is not an order document", len(docs) == 2, str(docs))
    check("indices stay in the STORED space (1 and 2, not 0 and 1)",
          [i for i, _p in docs] == [1, 2], str(docs))

    # The page and the server must agree index for index.
    check("the browser list uses the same indices as the server",
          [d["i"] for d in store.order_att_list(mixed)]
          == [i for i, _p in store.order_attachments(mixed)])
    check("the browser list carries display names",
          store.order_att_list(mixed)[0]["name"] == "order.pdf")

    # Every kind the extractor reads, and nothing else.
    for ext in (".pdf", ".xlsx", ".xlsm", ".xls", ".csv"):
        check(f"{ext} is an order document",
              len(store.order_attachments([f"x{ext}"])) == 1)
    for ext in (".txt", ".docx", ".zip", ".png"):
        check(f"{ext} is NOT an order document",
              len(store.order_attachments([f"x{ext}"])) == 0)

    # ---- 3. erp_uploaded can actually be set ----
    # The list, its badge and the write path must all name the same field.
    check("erp_uploaded is a writable mail field",
          "erp_uploaded" in OF.EDITABLE_FIELDS)
    check("erp_uploaded is a writable per-attachment field",
          "erp_uploaded" in OF.ATT_FIELDS)

    # The page must render a real handler, not the old "Coming Soon" stub.
    page = OF.report.render_page()
    check("erpUpload() no longer just shows a Coming Soon alert",
          "Coming Soon" not in page)
    check("erpUpload() writes erp_uploaded through /api/update",
          "field:'erp_uploaded'" in page)
    check("the Order Upload button is wired to the attachment index",
          "erpUpload('+m.id+" in page and "att_index===undefined" in page)
    check("Undo clears erp_uploaded so a reprocessed PO comes back",
          page.count("field:'erp_uploaded', value:0") == 1)
    check("the Completed badge and screen count the same set",
          "DATA.history.filter(m => m.status === 'Done')" in page
          and "filter(m => m.status === 'Done')" in page)

    # ---- 4. settings.source reaches the page ----
    check("the page gates Sync-this-date on settings.source",
          "(DATA.settings||{}).source === 'outlook'" in page)
    # The server must actually put the key in the payload; the page reading a
    # key nobody sends is exactly how this stayed broken.
    src = open(os.path.join(os.path.dirname(
        os.path.abspath(__file__)), "of_server.py"), encoding="utf-8").read()
    check("the dashboard payload includes settings.source",
          '"source": settings.get("source", "outlook")' in src)

    # ---- 5. a master edit reaches the Inbox without a reload (2026-10-27) ----
    # "I added a domain row and the Inbox still offers no Sold-To / Ship-To."
    # Two halves: the server cached the identity list on the PAIR table only, so
    # a DOMAIN row was invisible; and the page kept its own copy (DATA.master),
    # which decides whether a picker is drawn at all.
    check("the identity list is cached on BOTH customer tables",
          "key = ship_master.master_key(settings)" in src)
    check("...and there is an endpoint to re-read it alone",
          '"/api/master_list"' in src)
    check("the page re-reads it whenever the account cache is dropped",
          "function refreshMasterList(){" in page
          and "  refreshMasterList();" in page)
    # The customer filter became a multi-pick: a desk compares two or three
    # customers at a time, and a single-select forced a re-pick for each one.
    check("the customer filter is a multi-pick",
          "let CUSTPICK = [];" in page
          and "function custPickHTML(names){" in page
          and "function pickCust(name, on){" in page)
    check("...and the old single-value filter is gone",
          "CUSTFILTER" not in page and "setCustFilter" not in page)
    # The Inbox shows the master's ZIP beside the Ship-To picker so two sites of
    # one customer can be told apart. Display only - the order's postal code is
    # the one printed on the PO.
    check("the Ship-To picker shows the master's ZIP",
          "function siteZip(domain, code, sold){" in page
          and "zipCapHtml(siteZip(domain, cur, sold))" in page)
    check("...in the candidate list too, beside the number",
          "'ZIP ' + s.zip" in page)

    # ---- 6. full + simple are both selectable (2026-10-27) ----
    # The version choice became a LIST: three places draw a switch (step 3, the
    # Read rows, Quick Convert) and all three write to the same state, so a
    # page where only two of them were converted would silently desync.
    check("the version state is a list, defaulting to full",
          "let ERPFMTS = null;" in page
          and "if (!picked.length) picked.push('full');" in page)
    check("...saved as a list and read back as one",
          'settings["erp_format"] = want' in src
          and 'data["erp_formats"] = erp_excel.output_formats(' in src)
    check("...and both the switch and the preview cards are multi-select",
          'checkbox" name="' in page            # the seg's inputs, not radios
          and "function togglePreviewFmt(f){" in page
          and "function fmtSeg(name, extra){" in page)
    check("a row can hold the SECOND generated file",
          "erp_file2" in src
          and '"erp_file2" if which == 2 else "erp_file"' in src)
    check("both files come back to the page",
          '"files": [{"fmt": f,' in src and 'files: made,' in page)

    # ---- 7. the account lists are fetched in ONE request (2026-10-28) ----
    # "Sold-To / Ship-To takes seconds to fill in." It was N requests - one per
    # domain on the page - and every one of them re-read the 2.8 MB pair file
    # twice. Measured on a 12-domain page: 1.5 s wall / 8 s of CPU before,
    # 75 ms after.
    check("the page asks for every domain in one request",
          "api('/api/party_options', {domains: want})" in page
          and "{domain: c, role: ''}" not in page)
    check("...and the route answers a LIST of domains",
          'many = body.get("domains")' in src
          and 'self._json({"options": out})' in src)
    check("the pickers are refilled in one pass, not one per domain",
          "function patchParties(domains){" in page
          and "patchParties(want);" in page)
    # The grouping is a pure function of the two master files, so it is kept
    # until either of them changes - and it MUST be keyed on the location too,
    # or two temp masters with the same mtime+size share one index.
    msrc = open(os.path.join(os.path.dirname(
        os.path.abspath(__file__)), "of_master.py"), encoding="utf-8").read()
    check("the by-domain index is memoised on the master files",
          "_PAIRS_CACHE" in msrc and "_pairs_key(settings)" in msrc)
    check("...keyed on the folder as well as mtime/size",
          'return (settings.get("_base", ""),) + tuple(master_key(settings))'
          in msrc)
    _base = tempfile.mkdtemp(prefix="ofcache_")
    # `ship_master` is a facade namespace, and the grouping is private to the
    # module: reach the real module through one of its own functions.
    _SM = sys.modules[OF.ship_master.save.__module__]
    try:
        os.makedirs(os.path.join(_base, "config"), exist_ok=True)
        _s = {"_base": _base}
        OF.ship_master.dm_add(_s, {"domain": "abt.com",
                                   "sold_to_name": "ABT"})
        _row = {"domain": "abt.com", "sold_to_code": "1462100",
                "ship_to_code": "1462101", "sold_to_name": "ABT",
                "type": "Builder", "state": "IL"}
        OF.ship_master.save(_s, {"rows": [dict(_row), dict(_row)]})
        _one = _SM._pairs_by_domain(_s)
        _two = _SM._pairs_by_domain(_s)
        check("the index is built once and then reused", _one is _two)
        check("...and it really carries the domain's rows",
              len(_one.get("abt.com") or []) == 2, str(list(_one)))
        # A write from the browser must invalidate it, or a newly added
        # Sold-To would stay invisible until the server restarted.
        OF.ship_master.save(_s, {"rows": [dict(_row)]})
        _three = _SM._pairs_by_domain(_s)
        check("...and is rebuilt as soon as the master changes",
              _three is not _one and len(_three.get("abt.com") or []) == 1,
              str(len(_three.get("abt.com") or [])))
        # The AZ state list is memoised on the same signal. It claimed to be
        # and was not (`st_path()` returns a string; `.stat()` on it raised and
        # the except swallowed it), so the dashboard re-read the whole pair
        # file for 52 state codes - see of_master.states().
        _st1 = OF.ship_master.states(_s)
        _st2 = OF.ship_master.states(_s)
        check("the state list really is memoised", _st1 is _st2, f"{_st1}")
        check("...and still answers with the codes the master carries",
              _st1 == ["IL"], f"{_st1}")
    finally:
        shutil.rmtree(_base, ignore_errors=True)

    # The placeholder in a waiting cell is the three-dot pulse, not a "…".
    check("a waiting picker shows the dots animation",
          "function dotsHTML(){" in page
          and 'class="dots-container dots-sm"' in page
          and "dotsHTML()+'</span>'" in page)
    # ⚠️ The snippet as published styles a bare `.dot`, and this page already
    # uses `.dot` for the 9px status pip - unscoped it turns every status pip
    # into a 20px throbbing blob.
    check("the dots rules are scoped away from the status pips",
          ".dots-container .dot {" in page
          and "\n  .dot { height:20px" not in page)
    check("...and are scaled down to sit inside a table cell",
          ".dots-container.dots-sm .dot { height:6px;" in page)

    for ok, label, detail in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {label}"
              + (f"   [{detail}]" if not ok and detail else ""))
    print(f"\n  {len(checks) - failed}/{len(checks)} passed")
    return failed


# ==========================================================================
#  SECTION: P3 RESIDUALS - four defects the docs had declared fixed
#
#  Each was a leftover from the 2026-10 removal of the arithmetic cross-check
#  or from the customer-model refactor, and each was invisible in production:
#   16  a second copy of the amount regex truncated prices ("1198.00" -> "119")
#   17  a first receipt whose subject said UPDATE was stored as a duplicate
#   18  PO_PRESETS was sent to the browser but never read, so the customers it
#       exists for (KB Home: a bare number in the subject) could not be read
#   19  prepare_lines' `fixes` was always empty, breaking the "every correction
#       must be visible" rule while the recoveries still happened silently
# ==========================================================================

def run_p3():
    import orderflow as OF

    checks, failed = [], 0

    def check(label, ok, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, label, detail))


    # ---- 17. a keyword hint is not a duplicate ----
    base = tempfile.mkdtemp(prefix="ofp3_")
    try:
        conn = OF.store.connect(os.path.join(base, "t.db"))
        settings = {"revision_keywords": ["REVISED", "REV", "UPDATE", "수정"],
                    "cancel_keywords": ["CANCEL", "VOID"]}

        f, kind, why = OF.dedup.check_duplicate(
            conn, "abt.com", "12345",
            {"message_id": "a", "subject": "PO 12345 UPDATE"}, settings)
        check("a first receipt whose subject says UPDATE is NOT a duplicate",
              f is False, str(f))
        check("...it is reported as a keyword hint", kind == "keyword", kind)

        f, kind, why = OF.dedup.check_duplicate(
            conn, "abt.com", "777", {"message_id": "b", "subject": "PO 777"},
            settings)
        check("an ordinary new PO raises nothing",
              (f, kind) == (False, ""), f"{f} {kind}")

        OF.store.insert_mail(conn, {
            "message_id": "old", "received_at": "2026-10-01T00:00:00",
            "sender": "x@abt.com", "sender_domain": "abt.com",
            "subject": "PO 12345", "attachments": [], "pdf_paths": [],
            "customer": "abt.com", "po_number": "12345"})
        f, kind, why = OF.dedup.check_duplicate(
            conn, "abt.com", "12345", {"message_id": "c", "subject": "PO 12345"},
            settings)
        check("a real re-receipt IS a duplicate with kind 'repeat'",
              f is True and kind == "repeat", f"{f} {kind}")
        check("...and the reason says the PO arrived again",
              "received again" in why, why)

        f, kind, why = OF.dedup.check_duplicate(
            conn, "other.com", "12345", {"message_id": "d", "subject": "PO 12345"},
            settings)
        check("the same PO under another customer is not a duplicate",
              f is False, f"{f} {why}")

        check("dup_kind is a column that persists",
              "dup_kind" in [r[1] for r in
                             conn.execute("PRAGMA table_info(mails)")])
        conn.close()
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # ---- 18. the PO-number rule is reachable ----
    STD = {"po_regex_default":
           r"(?:P\.?O\.?|PURCHASE\s*ORDER)(?:\s*(?:NUMBER|NO|NUM))?"
           r"[\s#:.\-]*([A-Z]{0,4}[0-9][A-Z0-9\-]{3,19})",
           "po_attachment_regex": r"(\d{7,12})"}
    kb_subj = "KB HOME - Park Forest LOT 046 - 9857 36TH AVE NE - 179140181"
    kb_atts = ["Park Forest-NA-0523.pdf"]

    check("without the preset, the KB Home shape is unreadable",
          OF.extract_po_number(kb_subj, kb_atts, {}, dict(STD)) is None)
    check("the 'number only' preset reads it",
          OF.extract_po_number(kb_subj, kb_atts, {},
                               dict(STD, po_regex=OF.PO_PRESETS[1][0]))
          == "179140181")
    # The labelled rule runs first, so a date cannot be taken as the PO number.
    check("labelled mail is unaffected by the preset",
          OF.extract_po_number("Order 20260901 for PO 12345", [], {},
                               dict(STD, po_regex=OF.PO_PRESETS[1][0]))
          == "12345")
    check("a malformed stored rule is skipped, not fatal",
          OF.extract_po_number("PO 12345", [], {},
                               dict(STD, po_regex="([unclosed")) == "12345")
    srv = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "of_server.py"), encoding="utf-8").read()
    check("the settings route accepts only an offered preset",
          "want in classifier.PO_PRESET_VALUES" in srv)
    check("the payload sends the active rule",
          'data["po_regex"] = settings.get("po_regex", "")' in srv)
    page = OF.report.render_page()
    check("the Settings screen renders the PO-number selector",
          'id="set-poregex"' in page)
    check("saving settings sends the chosen rule",
          "body.po_regex = val('set-poregex')" in page)

    # ---- 19. corrections are reported again ----
    erp = OF.erp_excel
    res = [{"po_number": "1", "records": [
        {"material_code": "RF23A9671SR", "quantity": "23",
         "unit_price": "959.00", "description": "23CF FRENCH DOOR REF"}]}]
    lines, _nq, _nc, _dr, fixes = erp.prepare_lines(res)
    check("a clean pass-through reports no fix",
          lines[0]["qty"] == "23" and fixes == [], f"{lines[0]} {fixes}")

    res = [{"po_number": "2", "records": [
        {"material_code": "DW80CG4051SR", "quantity": "",
         "unit_price": "599.00", "description": "DW80CG4051SR 12 EA 599.00"}]}]
    lines, _nq, _nc, _dr, fixes = erp.prepare_lines(res)
    check("a recovered quantity is reported",
          lines[0]["qty"] == "12" and any("recovered" in f for f in fixes),
          f"{lines[0]} {fixes}")

    # The reader's price stands. Samsung prints "code EA <qty> <price>"; the old
    # re-derivation read the amount after "EA" and published the QUANTITY as the
    # unit price on PO 514. Nothing in prepare_lines may override the reader.
    res = [{"po_number": "4", "records": [
        {"material_code": "ME17R7021ES", "quantity": "85",
         "unit_price": "199.00", "description": "",
         "source_line": "ME17R7021ES EA 85.00 199.00"}]}]
    lines, _nq, _nc, _dr, fixes = erp.prepare_lines(res)
    check("the reader's unit price is never overridden by the printed line",
          str(lines[0]["cost"]) in ("199.0", "199"), str(lines[0]["cost"]))
    check("...and it is not reported as a fix either",
          fixes == [], str(fixes))

    # No price from the reader: the printed line is the only place left.
    res = [{"po_number": "3", "records": [
        {"material_code": "WF45B6300AP", "quantity": "2", "unit_price": "",
         "description": "", "source_line": "WF45B6300AP 2 $599.00 $1198.00"}]}]
    lines, _nq, _nc, _dr, fixes = erp.prepare_lines(res)
    check("a price recovered from the printed line is reported",
          any("printed line" in f for f in fixes), str(fixes))
    check("...and the recovered price is what gets written",
          str(lines[0]["cost"]) in ("599.0", "599"), str(lines[0]["cost"]))

    # ---- 19b. a zero is a VALUE, not a blank -----------------------------
    # `str(rec.get("quantity") or "")` turned a reported 0 into "the reader had
    # none", so the printed line's number overwrote it - the same mistake that
    # once published a quantity as the unit price. Contract 5: a recovery only
    # fills a blank the reader left.
    res = [{"po_number": "5", "records": [
        {"material_code": "RF23A9671SR", "quantity": 0,
         "unit_price": "959.00", "description": "",
         "source_line": "RF23A9671SR 4 EA 959.00"}]}]
    lines, _nq, _nc, _dr, fixes = erp.prepare_lines(res)
    check("a reported quantity of 0 is kept, not replaced from the printed line",
          str(lines[0]["qty"]) == "0" and lines[0]["qty"] != 4,
          f"{lines[0]} {fixes}")
    check("...and it is not listed as a recovery",
          not any("quantity" in f for f in fixes), str(fixes))

    res = [{"po_number": "6", "records": [
        {"material_code": "RF23A9671SR", "quantity": "0",
         "unit_price": "959.00", "description": "",
         "source_line": "RF23A9671SR 4 EA 959.00"}]}]
    lines, _nq, _nc, _dr, fixes = erp.prepare_lines(res)
    check("...the same for a string '0'",
          str(lines[0]["qty"]) == "0", f"{lines[0]} {fixes}")

    # A whitespace-only quantity is a blank and MAY be recovered - it is not a
    # value the reader reported.
    res = [{"po_number": "7", "records": [
        {"material_code": "DW80CG4051SR", "quantity": "   ",
         "unit_price": "599.00", "description": "",
         "source_line": "DW80CG4051SR 12 EA 599.00"}]}]
    lines, _nq, _nc, _dr, fixes = erp.prepare_lines(res)
    check("a whitespace-only quantity is treated as blank and recovered",
          str(lines[0]["qty"]) == "12", f"{lines[0]} {fixes}")

    # ---- 19c. 0.00 is NOT a price ---------------------------------------
    # Discount columns print 0.00 to the LEFT of the unit price. Publishing it
    # as the price put a zero-cost line into ERP. Contract 6: 0.00 means "no
    # price here" - leave the cell empty and report it.
    res = [{"po_number": "8", "records": [
        {"material_code": "ME17R7021ES", "quantity": "2",
         "unit_price": "0.00", "description": "",
         "source_line": "ME17R7021ES 0.00 199.00"}]}]
    lines, nq, nc, _dr, fixes = erp.prepare_lines(res)
    check("a printed 0.00 is not published as the unit price",
          lines[0]["cost"] in ("", None), f"{lines[0]}")
    check("...it is reported as a missing price instead",
          "ME17R7021ES" in nc, f"no_cost={nc}")

    res = [{"po_number": "9", "records": [
        {"material_code": "ME17R7021ES", "quantity": "2",
         "unit_price": 0, "description": "",
         "source_line": "ME17R7021ES 0.00 199.00"}]}]
    lines, nq, nc, _dr, fixes = erp.prepare_lines(res)
    check("...the same for a numeric 0",
          lines[0]["cost"] in ("", None) and "ME17R7021ES" in nc,
          f"{lines[0]} no_cost={nc}")

    body = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "of_erp.py"), encoding="utf-8").read()
    body = body.split("def prepare_lines")[1].split("\ndef ")[0]
    check("the unused 'amount' computation is gone", "amount = " not in body)
    check("prepare_lines never re-opens the PDF",
          "import pdfplumber" not in body)
    check("prepare_lines no longer swallows a reported 0 with `or ''`",
          'qty = str(rec.get("quantity") or "")' not in body)
    check("the user-facing text no longer claims a cross-check",
          "Corrected by cross-check" not in OF.report.render_page())

    for ok, label, detail in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {label}"
              + (f"   [{detail}]" if not ok and detail else ""))
    print(f"\n  {len(checks) - failed}/{len(checks)} passed")
    return failed


def run_extract():
    """PO extraction through the Claude API: the gate, the values, the cache.

    The API is NOT called - these checks drive the engine's own
    post-processing with the payload the API would have returned, so the suite
    runs offline and on a machine with no key.

    What they guard is everything that used to be the local engine's job and is
    not the API's:

      * master data decides which codes are published     (HANDOVER 4.0 #1)
      * values are published as printed, never repaired              (#3)
      * `qty x unit_price == amount` is REPORTED, never used to overwrite
      * one call per document, not per click             (the cache)
    """
    import orderflow as OF
    checks, failed = [], 0

    def check(label, ok, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, label, detail))

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ce = os.path.join(base, "CodeExtract")
    if ce not in sys.path:
        sys.path.insert(0, ce)
    import claude_engine

    # ---- the reference list is loaded, and it decides --------------------
    bb = claude_engine.get_backbone()
    check("the Material Code list is loadable", bb.enabled, "not loadable")
    for code in ("RF22A4111SR", "NE63D6511SR", "DW80CG4021SR"):
        check(f"{code} is confirmed by the list", bb.lookup(code)[0] == code,
              f"got {bb.lookup(code)}")

    def rec(code, qty="1", price="100.00", amount="100.00"):
        return {"material_code": code, "backbone_code": "", "description": "",
                "source_line": f"{code} {qty} {price}", "category": "",
                "quantity": qty, "unit": "EA", "unit_price": price,
                "amount": amount, "po_line": "", "po_number": "1",
                "page": 1, "source_file": "t.pdf", "match_type": "claude"}

    # ---- a code the list does not carry is SHOWN but not published --------
    # 2026-10-22: the line stays visible (with its quantity and price) and is
    # flagged for review; `include` is what decides whether it is written, and
    # prepare_lines sets that from `needs_review`.
    kept, review = claude_engine.apply_gate(
        [rec("RF22A4111SR"), rec("NOT-A-REAL-MODEL")], bb, "t.pdf", "1")
    check("a listed code is confirmed",
          [r["material_code"] for r in kept
           if not r.get("needs_review")] == ["RF22A4111SR"],
          f"{[(r['material_code'], r.get('needs_review')) for r in kept]}")

    prefixed, prefixed_review = claude_engine.apply_gate(
        [rec("51E-863-RT16A6195SR")], bb, "curacao.pdf", "ALRRY-A")
    check("a retailer ITEM ID publishes its master-confirmed SKU suffix",
          prefixed[0]["material_code"] == "RT16A6195SR"
          and prefixed[0]["backbone_code"] == "RT16A6195SR"
          and not prefixed[0].get("needs_review"), str(prefixed[0]))
    check("...and preserves the complete printed ITEM ID for audit",
          prefixed[0].get("raw_material_code") == "51E-863-RT16A6195SR"
          and not prefixed_review, str(prefixed_review))
    check("a code the list does not carry is still SHOWN",
          any(r["material_code"] == "NOT-A-REAL-MODEL" for r in kept),
          f"{[r['material_code'] for r in kept]}")
    check("...and is flagged needs_review, so it is not published",
          all(r.get("needs_review") for r in kept
               if r["material_code"] == "NOT-A-REAL-MODEL"))
    check("...with the reason the screen shows",
          any(r.get("review_reason") == "not in the Material Code list"
              for r in kept))
    check("...and is listed for review as well",
          any(r["candidate"] == "NOT-A-REAL-MODEL" for r in review),
          f"{review}")
    check("...with the reason a human needs",
          any("not in the Material Code list" in r["reason"] for r in review))

    # ---- a bare number is not a model -------------------------------------
    # PO 25407327's line read "... Apr 18th, 26" and '26' alone looked up to
    # the listed '26A' / '2612' appliances.
    kept, review = claude_engine.apply_gate([rec("26")], bb, "t.pdf", "1")
    check("'26' is not confirmed as a material code",
          all(r.get("needs_review") for r in kept)
          and any(r["candidate"] == "26" for r in review),
          f"{[(r['material_code'], r.get('needs_review')) for r in kept]}")

    # ---- a line with no printed code is set aside, not guessed ------------
    kept, review = claude_engine.apply_gate([rec("")], bb, "t.pdf", "1")
    check("a line with no printed code is flagged, never guessed",
          all(r.get("needs_review") for r in kept)
          and any("no material code" in r["reason"] for r in review))

    # ---- the listed spelling wins -----------------------------------------
    kept, _ = claude_engine.apply_gate([rec("DVE45T6000W")], bb, "t.pdf", "1")
    check("a printed base is confirmed and keeps its printed spelling",
          bool(kept) and kept[0]["backbone_code"], f"{kept}")

    # ---- values are published as printed ----------------------------------
    for raw, want in (("$ 1,198.00", "1198.00"), ("1060.0000", "1060.0000"),
                      ("465", "465"), ("199.00", "199.00"), ("", "")):
        check(f"_clean_num({raw!r}) -> {want!r}",
              claude_engine._clean_num(raw) == want,
              f"got {claude_engine._clean_num(raw)!r}")
    check("no pennies are invented for a printed 465",
          claude_engine._clean_num("465") == "465")

    # ---- arithmetic is proof, and only ever a report ----------------------
    rows = [rec("RF22A4111SR", "2", "100.00", "250.00")]
    diags = claude_engine.check_arithmetic(rows, "")
    check("a line that does not balance is reported",
          any("2 x 100" in d for d in diags), f"{diags}")
    check("...and its values are left exactly as printed",
          rows[0]["quantity"] == "2" and rows[0]["unit_price"] == "100.00"
          and rows[0]["amount"] == "250.00", f"{rows[0]}")
    check("a line that balances is not reported",
          claude_engine.check_arithmetic(
              [rec("RF22A4111SR", "2", "100.00", "200.00")], "") == [])

    diags = claude_engine.check_arithmetic(
        [rec("RF22A4111SR", "2", "100.00", "200.00")], "300.00")
    check("lines that do not add up to the printed total are reported",
          any("total" in d for d in diags), f"{diags}")

    # ---- the result dict keeps the shape the dashboard reads --------------
    payload = {"po_number": "4512", "document_total": "300.00",
               "po_date": "", "rdd": "", "ship_to": None,
               "lines": [{"material_code": "RF22A4111SR", "description": "REF",
                          "quantity": "2", "unit": "EA",
                          "unit_price": "100.00", "amount": "200.00",
                          "po_line": "10", "page": "1",
                          "source_line": "RF22A4111SR 2 100.00 200.00"}]}
    tmp = tempfile.mkdtemp(prefix="ofextract_")
    try:
        cache = os.path.join(tmp, "t.json")
        res = claude_engine._finalise(payload, "t.pdf", cache, "", "")
        for key in ("source_file", "po_number", "records", "review",
                    "diagnostics", "stats", "extraction_mode"):
            check(f"the result dict carries {key}", key in res)
        check("the PO number the document printed is published",
              res["po_number"] == "4512", res.get("po_number"))
        check("the confirmed code is published with its backbone spelling",
              res["records"][0]["backbone_code"] == "RF22A4111SR",
              f"{res['records']}")
        check("extraction_mode says where the reading came from",
              res["extraction_mode"] == "deepseek")
        check("the extraction is cached, so a re-run costs no API call",
              (claude_engine.load_cache(cache) or {}).get("po_number")
              == "4512")

        # ---- the header block: two dates and the delivery address --------
        # 2026-10-22. All three are per-ORDER values: they reach ERP columns
        # K, M and R-S-V / W / X / AZ, and every one of them can be overridden
        # on screen.
        hp = {"po_number": "1", "document_total": "",
              "po_date": "10/14/26", "rdd": "",
              "ship_to": {"name": "ACME DC #12",
                          "address_lines": ["9 ONE-OFF WAY", "DOCK 4"],
                          "city": "Newark", "state": "nj",
                          "postal_code": "07102"},
              "lines": []}
        hres = claude_engine._finalise(hp, "h.pdf",
                                       os.path.join(tmp, "h.json"), "", "")
        check("the printed PO date is read and normalised",
              hres.get("po_date") == "2026-10-14", hres.get("po_date"))
        check("a PO with no required date defaults to +6 working days",
              hres.get("rdd") == "2026-10-22", hres.get("rdd"))
        check("...and the default is flagged, not passed off as printed",
              hres.get("rdd_defaulted") is True
              and "working days" in str(hres.get("rdd_source")),
              f"{hres.get('rdd_defaulted')} {hres.get('rdd_source')}")
        check("a defaulted R.D.D is reported as a diagnostic",
              any("R.D.D defaulted" in d for d in hres.get("diagnostics", [])),
              f"{hres.get('diagnostics')}")
        check("the delivery address lands on R and its continuation lines",
              hres.get("ship_to_address") == "9 ONE-OFF WAY"
              and hres.get("ship_to_street2") == "DOCK 4",
              f"{hres.get('ship_to_address')!r} {hres.get('ship_to_street2')!r}")
        check("...with city / state / postcode in their own columns",
              (hres.get("ship_to_city"), hres.get("ship_to_region"),
               hres.get("ship_to_zip")) == ("Newark", "NJ", "07102"),
              f"{hres.get('ship_to_city')} {hres.get('ship_to_region')} "
              f"{hres.get('ship_to_zip')}")

        hp2 = dict(hp, po_date="", rdd="2026-11-02", ship_to=None)
        hres2 = claude_engine._finalise(hp2, "h2.pdf",
                                        os.path.join(tmp, "h2.json"), "", "")
        check("a printed R.D.D is used as-is and not defaulted",
              hres2.get("rdd") == "2026-11-02"
              and hres2.get("rdd_defaulted") is False,
              f"{hres2.get('rdd')} {hres2.get('rdd_defaulted')}")
        check("no date on the document at all leaves both cells empty",
              hres2.get("po_date") == "" and hres2.get("rdd") == "2026-11-02",
              f"{hres2.get('po_date')!r} {hres2.get('rdd')!r}")

        # ---- the deliver-to block, in every shape a model returns it --------
        # 2026-10-23. A preview with no address is useless, and the address was
        # being lost in three different ways: a string ship_to was dropped
        # wholesale, "zip"/"region" were not recognised, and a city printed on
        # the tail line ("NEWARK, NJ 07102") stayed in the STREET columns.
        for label, ship, want in (
                ("the documented object",
                 {"address_lines": ["9 ONE-OFF WAY"], "city": "Newark",
                  "state": "nj", "postal_code": "07102"},
                 ("9 ONE-OFF WAY", "07102", "Newark", "NJ")),
                ("synonym keys (zip / region)",
                 {"address_lines": ["9 ONE-OFF WAY"], "city": "Newark",
                  "region": "NJ", "zip": "07102"},
                 ("9 ONE-OFF WAY", "07102", "Newark", "NJ")),
                ("address_lines as one string",
                 {"address_lines": "9 ONE-OFF WAY\nDOCK 4", "city": "Newark",
                  "state": "NJ", "postal_code": "07102"},
                 ("9 ONE-OFF WAY", "07102", "Newark", "NJ")),
                ("the whole address as one string",
                 "9 ONE-OFF WAY, NEWARK, NJ 07102",
                 ("9 ONE-OFF WAY", "07102", "NEWARK", "NJ")),
                ("city on the tail line",
                 {"address_lines": ["9 ONE-OFF WAY", "NEWARK, NJ 07102"]},
                 ("9 ONE-OFF WAY", "07102", "NEWARK", "NJ")),
                ("state and postcode on their own line",
                 {"address_lines": ["9 ONE-OFF WAY", "NEWARK", "NJ 07102"]},
                 ("9 ONE-OFF WAY", "07102", "NEWARK", "NJ"))):
            got, _n = claude_engine._ship_block(ship)
            three = (got["ship_to_address"], got["ship_to_zip"],
                     got["ship_to_city"], got["ship_to_region"])
            check(f"the address survives as {label}", three == want,
                  f"{three} != {want}")
        check("...and the city never lands in a STREET column",
              claude_engine._ship_block(
                  {"address_lines": ["9 ONE-OFF WAY", "NEWARK, NJ 07102"]}
              )[0]["ship_to_street2"] == "")
        check("a PO with no deliver-to block is reported as such",
              claude_engine._ship_block(None)[0]["ship_to_address"] == ""
              and claude_engine._ship_block(None)[1] == "")
        check("a ship block in an unreadable shape says so instead of "
              "pretending the PO printed nothing",
              "could not be read" in claude_engine._ship_block({"foo": 1})[1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- editing the PROMPT invalidates the cache -------------------------
    # Hashing `prompt_version` alone made a prompt edit invisible: the change
    # was real, the cached reading stayed valid, and nothing said so.
    sig0 = claude_engine.config_signature()
    sys_orig, tool_orig = claude_engine._SYSTEM, claude_engine._TOOL
    try:
        claude_engine._SYSTEM = sys_orig + "\n10. An extra rule."
        check("editing the system prompt changes the cache signature",
              claude_engine.config_signature() != sig0)
        claude_engine._SYSTEM = sys_orig
        check("restoring it restores the signature",
              claude_engine.config_signature() == sig0)
        import copy
        bumped = copy.deepcopy(tool_orig)
        bumped["input_schema"]["properties"]["zzz_probe"] = {"type": "string"}
        claude_engine._TOOL = bumped
        check("editing the tool schema changes the cache signature",
              claude_engine.config_signature() != sig0)
    finally:
        claude_engine._SYSTEM, claude_engine._TOOL = sys_orig, tool_orig
    check("the signature is back to where it started",
          claude_engine.config_signature() == sig0)

    # ---- the model can be chosen on the Settings screen -------------------
    # 2026-10-23. The dropdown wins over claude_config.json, and an ID the
    # endpoint does not serve is ignored rather than sent (a wrong ID is a bare
    # HTTP 400 with no reading behind it).
    cfg_now = claude_engine.load_config()
    base_model = cfg_now.get("model")
    tmpcfg = tempfile.mkdtemp(prefix="ofmodel_")
    try:
        sp = os.path.join(tmpcfg, "settings.json")
        old_path = claude_engine.SETTINGS_PATH
        try:
            claude_engine.SETTINGS_PATH = sp
            import json as _json
            with open(sp, "w", encoding="utf-8") as f:
                _json.dump({"deepseek": {"model": "deepseek-flash"}}, f)
            check("the Settings model overrides the config file",
                  claude_engine.load_config().get("model")
                  == "deepseek-flash",
                  claude_engine.load_config().get("model"))
            with open(sp, "w", encoding="utf-8") as f:
                _json.dump({"deepseek": {"model": "not-a-model"}}, f)
            check("an unknown model ID is ignored, not sent",
                  claude_engine.load_config().get("model") == base_model,
                  claude_engine.load_config().get("model"))
        finally:
            claude_engine.SETTINGS_PATH = old_path
    finally:
        shutil.rmtree(tmpcfg, ignore_errors=True)

    # ---- reading once, generating from that reading -----------------------
    # The preview pays for the API call; Confirm must not pay again. `force`
    # is what makes the difference, so check the flag actually reaches the
    # engine instead of being dropped on the way.
    seen_forces = []

    def _stub_extract(path, force=False, customer_name="",
                      progress_callback=None):
        seen_forces.append(force)
        return {"source_file": os.path.basename(path), "md5": "",
                "config_sig": "", "po_number": "1", "customer": "",
                "extraction_mode": "claude", "records": [], "review": [],
                "diagnostics": [], "stats": {}, "page_count": 0,
                "po_date": "", "rdd": ""}

    tmp2 = tempfile.mkdtemp(prefix="ofread_")
    try:
        pdf = os.path.join(tmp2, "PO 1.pdf")
        with open(pdf, "wb") as f:
            f.write(b"%PDF-1.4\n%%EOF\n")
        # The facade is a snapshot of names, not a live link, so the engine
        # has to be swapped on the MODULE that _load_engine() reads.
        import of_pdf as _mod
        old_engine, old_mod = _mod._ENGINE, _mod._ENGINE_MOD
        try:
            _mod._ENGINE = _stub_extract
            _mod._ENGINE_MOD = type("M", (), {"api_key": staticmethod(
                lambda: "k")})()
            OF.extractor_bridge.read_orders([pdf], {"_base": tmp2}, force=True)
            OF.extractor_bridge.read_orders([pdf], {"_base": tmp2}, force=False)
            check("the preview reads with force=True",
                  seen_forces[:1] == [True], f"{seen_forces}")
            check("...and generating re-reads with force=False (cache, no "
                  "second API call)",
                  seen_forces[1:2] == [False], f"{seen_forces}")
        finally:
            _mod._ENGINE, _mod._ENGINE_MOD = old_engine, old_mod
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)

    # ---- the DeepSeek Anthropic-compatible endpoint contract ---------------
    hdr = claude_engine.auth_header("T0K3N")
    check("the key is sent as x-api-key",
          hdr.get("x-api-key") == "T0K3N", f"{hdr}")
    check("...and NOT as a Bearer token",
          "Authorization" not in hdr, f"{hdr}")
    check("the compatibility version header is still sent",
          claude_engine.API_VERSION == "2023-06-01",
          claude_engine.API_VERSION)

    for raw, want in (
            ("https://h:8081", "https://h:8081/v1/messages"),
            ("https://h:8081/", "https://h:8081/v1/messages"),
            ("https://h:8081/v1/messages", "https://h:8081/v1/messages"),
            ("https://h/v1/messages/", "https://h/v1/messages"),
            ("https://h/v1", "https://h/v1/messages")):
        got = claude_engine._resolve_url(raw)
        check(f"endpoint {raw} -> {want}", got == want, f"got {got}")

    check("the shipped endpoint is DeepSeek's Anthropic-compatible root",
          claude_engine.DEFAULT_BASE_URL
          == "https://api.deepseek.com/anthropic",
          claude_engine.DEFAULT_BASE_URL)
    check("only the vision-capable DeepSeek model is offered",
          {"deepseek-flash"} == set(claude_engine.KNOWN_MODELS),
          f"{sorted(claude_engine.KNOWN_MODELS)}")
    check("the default model is one the guide lists",
          claude_engine.DEFAULTS["model"] in claude_engine.KNOWN_MODELS,
          claude_engine.DEFAULTS["model"])

    # DeepSeek rejects a forced named tool_choice while thinking is enabled.
    # Capture the outgoing extraction payload without making a network call.
    sent = {}
    old_post = claude_engine._post
    try:
        def _capture_post(payload, cfg, **_kwargs):
            sent.update(payload)
            return {"content": [{"type": "tool_use", "input": {"orders": []}}]}
        claude_engine._post = _capture_post
        claude_engine._call(
            [{"type": "text", "text": "probe"}]
            + [{"type": "image"} for _ in range(4)],
            claude_engine.load_config())
    finally:
        claude_engine._post = old_post
    check("DeepSeek extraction disables thinking for forced tool_choice",
          sent.get("thinking") == {"type": "disabled"}, str(sent.get("thinking")))
    check("the extraction tool remains explicitly forced",
          sent.get("tool_choice", {}).get("type") == "tool")
    check("multi-page PDFs get enough room for their structured line items",
          sent.get("max_tokens") >= 20_000, str(sent.get("max_tokens")))

    # A rejected key must say x-api-key, because that is the wire format.
    msg = claude_engine._plain_error(401, "invalid token", "https://h/v1/messages")
    check("a 401 tells you the token is the problem", "rejected the key" in msg, msg)
    check("...and names the header form to check", "x-api-key" in msg, msg)
    msg = claude_engine._plain_error(404, "", "https://h/v1/messages")
    check("a 404 says the base URL is wrong", "base URL" in msg, msg)
    msg = claude_engine._plain_error(400, '{"error":"model not found"}',
                                     "https://h/v1/messages")
    check("an unknown model names the ones that work",
          "deepseek-flash" in msg, msg)

    # ---- a document that is not a PDF is refused plainly -----------------
    junk = os.path.join(tempfile.mkdtemp(prefix="ofextract_"), "x.pdf")
    try:
        with open(junk, "wb") as f:
            f.write(b"<## not a pdf")
        try:
            claude_engine._pdf_blocks(junk, claude_engine.load_config())
            check("a non-PDF is refused", False, "no error raised")
        except RuntimeError as e:
            check("a non-PDF is refused with a plain message",
                  "not a PDF" in str(e), str(e))
    finally:
        shutil.rmtree(os.path.dirname(junk), ignore_errors=True)

    # DeepSeek has no PDF document block. A valid PDF must become one image
    # block per page, plus the instruction text, before it reaches /messages.
    rendered = tempfile.mkdtemp(prefix="ofdeepseek_")
    try:
        import pymupdf as fitz
        pdf = os.path.join(rendered, "two-pages.pdf")
        doc = fitz.open()
        for label in ("PAGE ONE", "PAGE TWO"):
            page = doc.new_page(width=300, height=400)
            page.insert_text((40, 80), label)
        doc.save(pdf)
        doc.close()
        blocks = claude_engine._pdf_blocks(
            pdf, dict(claude_engine.load_config(), pdf_dpi=72))
        images = [b for b in blocks if b.get("type") == "image"]
        check("a PDF is rendered to one DeepSeek image per page",
              len(images) == 2, f"{len(images)} images")
        check("rendered pages are inline JPEG blocks",
              all(i.get("source", {}).get("media_type") == "image/jpeg"
                  and i.get("source", {}).get("type") == "base64"
                  and i.get("source", {}).get("data") for i in images))
        check("the PDF document block is gone",
              not any(b.get("type") == "document" for b in blocks))
        markers = [b.get("text") for b in blocks
                   if b.get("type") == "text"
                   and "BEGIN PDF PAGE" in b.get("text", "")]
        check("every rendered image has an explicit page-boundary marker",
              markers == ["--- BEGIN PDF PAGE 1 OF 2 ---",
                          "--- BEGIN PDF PAGE 2 OF 2 ---"], str(markers))
    finally:
        shutil.rmtree(rendered, ignore_errors=True)

    print("=" * 68)
    print("PO extraction - gate, values, cache")
    print("=" * 68)
    for ok, label, detail in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {label}"
              + (f"   [{detail}]" if not ok and detail else ""))
    print(f"\n  {len(checks) - failed}/{len(checks)} passed")
    return failed


def run_sku():
    """The Product Mapping Table: columns A/B/D/E and the short→FULL rewrite.

    A PO prints a short SKU ('RAF18DBB12'); ERP is keyed on the FULL SKU
    ('RA-F18DBB12/AA'). The mapping table is the authority for that rewrite,
    and a short SKU that stands for more than one FULL SKU must be LEFT ALONE -
    choosing one would put a wrong model on the order.
    """
    import orderflow as OF
    from openpyxl import Workbook

    checks, failed = [], 0

    def check(label, ok, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, label, detail))

    def write_map(base, rows):
        """rows: [(FULL SKU, short skus, MATERIAL GROUP, MATERIAL GROUP 2)]"""
        wb = Workbook()
        ws = wb.active
        ws.append(["FULL SKU", "short skus", "MATERIAL GROUP CODE",
                   "MatG", "MatG II"])
        for r in rows:
            ws.append([r[0], r[1], "AAA0A", r[2], r[3]])
        p = os.path.join(base, "map.xlsx")
        wb.save(p)
        return p

    base = tempfile.mkdtemp(prefix="ofsku_")
    try:
        settings = {"_base": base}
        os.makedirs(os.path.join(base, "config"), exist_ok=True)

        # 1 - the header is found by name, and only A/B/D/E are read
        wb = Workbook()
        ws = wb.active
        ws.append(["FULL SKU", "short skus", "MATERIAL GROUP CODE",
                   "MatG", "MatG II"])
        ws.append(["RAF18DBB12/AA", "RAF18DBB12", "AAA0A", "REF", "REF"])
        ws.append(["AX26BG3100GGAA", "AX26BG3100GG", "AAA0A", "SA", "SA"])
        p = os.path.join(base, "m.xlsx")
        wb.save(p)
        info = {}
        codes, smap, conf = OF.material_master.parse_mapping(p, info=info)
        check("parse_mapping reads FULL SKU / short skus / MatG / MatG II",
              len(codes) == 2 and len(smap) == 2 and not conf, f"{info}")
        check("...the code column is A and the groups come from D and E",
              info.get("code_column") == "A"
              and "MatG=D" in info.get("category_columns", ""),
              f"{info}")

        # 2 - the groups land on the codes, so the tree groups by material group
        got = codes[OF.material_master.norm("RAF18DBB12/AA")]
        check("MatG / MatG II become product / cate1",
              got["product"] == "REF" and got["cate1"] == "REF", f"{got}")

        # 3 - a lone 'ref' spelling is folded onto 'REF' rather than splitting
        p2 = write_map(base, [("RF18HFENBBC/AA", "RF18HFENBBC", "ref", "ref")])
        c2, s2, _ = OF.material_master.parse_mapping(p2)
        check("'ref' and 'REF' are one group, not two",
              c2[OF.material_master.norm("RF18HFENBBC/AA")]["product"] == "REF",
              f"{c2}")

        # 4 - a short SKU that is NOT a prefix of its FULL SKU still maps.
        #     This is why the mapping table, not a string rule, is the authority.
        p3 = write_map(base, [("RA-F18DBB12/AA", "RAF18DBB12", "REF", "REF")])
        OF.material_master.upload(settings, p3)
        check("a short SKU that is not a prefix of its FULL SKU still maps",
              OF.material_master.sku_full(settings, "RAF18DBB12")
              == "RA-F18DBB12/AA",
              f"{OF.material_master.sku_full(settings, 'RAF18DBB12')!r}")

        # 5 - one short SKU, two different FULL SKUs -> ONE is chosen now
        #     (2026-10-22). /AA wins when offered; /AC is never chosen; the
        #     same short SKU always resolves to the same FULL SKU.
        p4 = write_map(base, [
            ("AX300T9080W/AA", "AX300T9080W", "SA", "SA"),
            ("AX350A9350N/A3", "AX300T9080W", "SA", "SA"),
        ])
        r = OF.material_master.upload(settings, p4)
        check("a short SKU with several FULL SKUs is counted as picked",
              r["sku_picked"] == 1 and r["sku_mapped"] == 1, f"{r}")
        check("...and /AA is the one chosen",
              OF.material_master.sku_full(settings, "AX300T9080W")
              == "AX300T9080W/AA",
              f"{OF.material_master.sku_full(settings, 'AX300T9080W')!r}")

        # 5a - /AC is never chosen, even when it is the only other candidate
        p4b = write_map(base, [
            ("DVE50R5400W/AC", "DVE50R5400W", "LA", "DRY"),
            ("DVE50R5400W/A3", "DVE50R5400W", "LA", "DRY"),
        ])
        OF.material_master.upload(settings, p4b)
        check("/AC is never the chosen variant",
              OF.material_master.sku_full(settings, "DVE50R5400W")
              == "DVE50R5400W/A3",
              f"{OF.material_master.sku_full(settings, 'DVE50R5400W')!r}")

        # 5b - only /AC candidates: nothing sellable to choose, so the short
        #      SKU stays unresolved and a human decides.
        p4c = write_map(base, [
            ("NE63A6111SS/AC", "NE63A6111SS", "RA", "RANGE"),
            ("NE63A6711SS/AC", "NE63A6111SS", "RA", "RANGE"),
        ])
        r = OF.material_master.upload(settings, p4c)
        check("a short SKU whose only candidates are /AC is left alone",
              r["sku_ambiguous"] == 1 and r["sku_picked"] == 0, f"{r}")
        check("...and sku_full() refuses to choose for it",
              OF.material_master.sku_full(settings, "NE63A6111SS") == "",
              f"{OF.material_master.sku_full(settings, 'NE63A6111SS')!r}")
        check("...while the conflict is kept so it can be reported",
              OF.material_master.norm("NE63A6111SS")
              in OF.material_master.sku_conflicts(settings))

        # 6 - sku_groups answers for the short spelling too
        p5 = write_map(base, [("WA46CG3305AWA4", "WA6CG3305AW",
                               "LAUNDRY", "WASHER")])
        OF.material_master.upload(settings, p5)
        check("sku_groups() resolves through the short spelling",
              OF.material_master.sku_groups(settings, "WA6CG3305AW")
              == ("LAUNDRY", "WASHER"),
              f"{OF.material_master.sku_groups(settings, 'WA6CG3305AW')}")
        check("...and through the FULL spelling it was rewritten to",
              OF.material_master.sku_groups(settings, "WA46CG3305AWA4")
              == ("LAUNDRY", "WASHER"),
              f"{OF.material_master.sku_groups(settings, 'WA46CG3305AWA4')}")

        # 7 - a price list is NOT read as a mapping table (and the other way)
        wb = Workbook()
        ws = wb.active
        ws.append(["Model", "Description", "Price"])
        ws.append(["DW80CG4051SRAA", "DISHWASHER", "599.00"])
        pl = os.path.join(base, "price.xlsx")
        wb.save(pl)
        r = OF.material_master.upload(settings, pl)
        check("a price list still takes the price-sheet path",
              r["layout"] == "price list", f"{r.get('layout')}")
        check("...and it leaves the mapping alone",
              OF.material_master.sku_full(settings, "WA6CG3305AW")
              == "WA46CG3305AWA4")

        # 8 - normalise_to_master applies the rewrite on a real extraction result
        OF.material_master.upload(settings, p5)
        results = [{"file": "t.pdf", "records": [
            {"material_code": "WA6CG3305AW"}]}]
        fixed, unknown, err = OF.extractor_bridge.normalise_to_master(
            results, settings)
        check("normalise_to_master rewrites a short SKU to its FULL SKU",
              results[0]["records"][0]["material_code"] == "WA46CG3305AWA4"
              and not unknown and not err,
              f"{results[0]['records'][0]['material_code']!r} "
              f"fixed={fixed} unknown={unknown} err={err}")
        check("...and says so in the fixed list",
              any("short SKU" in f for f in fixed), f"{fixed}")

        # 9 - the export is the twin of the upload: same columns, same rows
        data, fn, n = OF.data_export.export_data(settings, "materials")
        ex = os.path.join(base, "export.xlsx")
        with open(ex, "wb") as f:
            f.write(data)
        b2 = tempfile.mkdtemp(prefix="ofsku2_")
        try:
            s2 = {"_base": b2}
            os.makedirs(os.path.join(b2, "config"), exist_ok=True)
            OF.material_master.upload(s2, ex)
            # Compare the STORED state, not the per-upload counts: `settings`
            # was built up over several uploads, so its stored master is what
            # the export has to reproduce.
            a_codes = {OF.material_master.norm(v["code"])
                       for v in OF.material_master.items(settings)}
            b_codes = {OF.material_master.norm(v["code"])
                       for v in OF.material_master.items(s2)}
            a_map = OF.material_master.sku_map(settings)
            b_map = OF.material_master.sku_map(s2)
            check("export -> re-import keeps every code",
                  a_codes == b_codes, f"{len(a_codes)} vs {len(b_codes)}")
            check("...and every mapping, with the same targets",
                  {k: v["full"] for k, v in a_map.items()}
                  == {k: v["full"] for k, v in b_map.items()},
                  f"{len(a_map)} vs {len(b_map)}")
            check("...and re-derives the same ambiguity",
                  len(OF.material_master.sku_conflicts(settings))
                  == len(OF.material_master.sku_conflicts(s2)),
                  f"{len(OF.material_master.sku_conflicts(settings))} vs "
                  f"{len(OF.material_master.sku_conflicts(s2))}")
            check("the materials schema matches its importer",
                  OF.data_export.contract_ok("materials") == [],
                  f"{OF.data_export.contract_ok('materials')}")

            # 9 - "Unknown codes found in POs" -> Clear all.
            #     Clearing is NOT approving: the codes stop being listed, the
            #     extraction cache is untouched, and a cleared code still fails
            #     the gate on the next PO.
            cache = os.path.join(b2, "CodeExtract", "data_cache")
            os.makedirs(cache, exist_ok=True)
            for nm, code in (("PO 1.json", "ZZ99FAKE000"),
                             ("PO 2.json", "QQ11NOPE")):
                with open(os.path.join(cache, nm), "w", encoding="utf-8") as f:
                    json.dump({"review": [{"candidate": code,
                                           "reason": "not in the Material "
                                                     "Code list",
                                           "context": "", "po_number": "1"}]},
                              f)
            before = [r["code"] for r in
                      OF.material_master.pending_reviews(s2)]
            check("unknown codes are listed to begin with",
                  before == ["ZZ99FAKE000", "QQ11NOPE"] or
                  sorted(before) == ["QQ11NOPE", "ZZ99FAKE000"], f"{before}")
            n_cleared = OF.material_master.dismiss_reviews(s2)
            check("Clear all empties the list", n_cleared == 2, f"{n_cleared}")
            check("...and it stays empty",
                  OF.material_master.pending_reviews(s2) == [])
            check("...without touching the extraction cache",
                  sorted(os.listdir(cache)) == ["PO 1.json", "PO 2.json"],
                  f"{os.listdir(cache)}")
            check("...and clearing twice does nothing more",
                  OF.material_master.dismiss_reviews(s2) == 0)
        finally:
            shutil.rmtree(b2, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("=" * 68)
    print("Product Mapping Table - regression tests")
    print("=" * 68)
    for ok, label, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok and detail:
            print(f"         {detail}")
    print("-" * 68)
    print(f"  {len(checks) - failed}/{len(checks)} passed")
    if failed:
        print(f"  {failed} FAILED")
    return 1 if failed else 0


# ==========================================================================
#  SECTION: dispatcher
# ==========================================================================
def run_mailbox():
    """The Inbox is scoped to one mailbox - and a missing settings file is not
    a broken install.

    Both are 2026-10-26 changes that fail quietly rather than loudly: a list
    that leaks another store's mail looks like data, and an app that starts with
    no endpoint looks like "it forgot my settings again".
    """
    import orderflow as OF

    checks, failed = [], 0

    def check(label, ok, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, label, detail))

    base = tempfile.mkdtemp(prefix="ofmb_")
    try:
        conn = OF.store.connect(os.path.join(base, "t.db"))
        import datetime
        now = datetime.datetime.now().isoformat(timespec="seconds")

        def add(mid, mb, store="STORE-A"):
            OF.store.insert_mail(conn, {
                "message_id": mid, "received_at": now, "sender": "a@x.com",
                "sender_domain": "x.com", "subject": "PO " + mid,
                "attachments": [], "pdf_paths": [], "customer": "ACME",
                "po_number": mid, "source_ref": f"entryid:E{mid}:{store}",
                "mailbox": mb})

        add("m1", "OrderDesk")
        add("m2", "OrderDesk")
        add("m3", "rong.geniu")
        add("m4", "")
        add("old1", "", store="STORE-B")

        def ids(mb):
            d = OF.store.dashboard_data(conn, 1, mailbox=mb)
            return sorted(x["message_id"] for x in d["history"])

        check("insert_mail keeps the mailbox",
              ids("OrderDesk") == ["m1", "m2"], str(ids("OrderDesk")))
        check("another mailbox's mail does not leak in",
              "m3" not in ids("OrderDesk") and "m4" not in ids("OrderDesk"))
        check("the match ignores case, like the picker does",
              ids("orderdesk") == ["m1", "m2"], str(ids("orderdesk")))
        check('"" means the default inbox, not "everything"',
              ids("") == ["m4", "old1"], str(ids("")))
        check("None means unscoped",
              ids(None) == ["m1", "m2", "m3", "m4", "old1"], str(ids(None)))
        check("...and the day list is scoped with it",
              sorted(x["message_id"] for x in
                     OF.store.dashboard_data(conn, 1, mailbox="OrderDesk")["today"])
              == ["m1", "m2"])

        check("mail with no mailbox is counted so the page can say so",
              OF.store.dashboard_data(conn, 1, mailbox="OrderDesk")["unclaimed"]
              == 2)

        n = OF.store.backfill_mailbox(conn, "OtherBox", "STORE-B")
        check("backfill claims the rows from that store only", n == 1, str(n))
        check("...and they then show up under it",
              ids("OtherBox") == ["old1"], str(ids("OtherBox")))
        check("backfill is idempotent",
              OF.store.backfill_mailbox(conn, "OtherBox", "STORE-B") == 0)
        check("no store id means no guessing",
              OF.store.backfill_mailbox(conn, "X", "") == 0)
        check("the claimed row left the default inbox",
              ids("") == ["m4"], str(ids("")))
        conn.close()

        # ---- settings: defaults under the user's file ----
        merged = OF._merge_settings(
            {"outlook": {"mailbox_name": "", "lookback_days": 1},
             "server": {"port": 8000}, "sync": {"mode": "interval"}},
            {"outlook": {"mailbox_name": "OrderDesk"},
             "claude": {"base_url": "https://x", "api_key": "k"}})
        check("a nested block is merged, not replaced",
              merged["outlook"] == {"mailbox_name": "OrderDesk",
                                    "lookback_days": 1}, str(merged["outlook"]))
        check("a key only the user file has survives",
              merged["claude"]["base_url"] == "https://x")
        check("an untouched default survives",
              merged["server"]["port"] == 8000)

        live = OF.load_settings()
        check("the live settings file loads and carries its path",
              bool(live.get("_settings_path")) and bool(live.get("_base")))
        check("...with the defaults filled in, not just what was typed",
              "outlook" in live and "server" in live and "sync" in live)

        # ---- the picker markup ----
        html = OF.report.render_page()
        check("the Data file picker is the styled one",
              html.count('class="docbtn"') == 1 and
              html.count("docPick('erp-file'") == 1, str(html.count('class="docbtn"')))
        check("...and the native control is still there, hidden",
              'accept=".xlsx,.xlsm,.xls" hidden' in html and
              'onchange="docPicked(this)"' in html)
        check("the inbox can file the mail collected before the column",
              "/api/claim_mailbox" in html and "function claimMailbox(" in html)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print()
    print("=" * 68)
    print("Mailbox scoping + settings defaults - regression tests")
    print("=" * 68)
    for ok, label, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}")
        if not ok and detail:
            print(f"         {detail}")
    print("-" * 68)
    print(f"  {len(checks) - failed}/{len(checks)} passed")
    return 1 if failed else 0


def run_multipo():
    """One attachment, several POs (2026-10-28).

    Curacao mails four POs stapled into a single PDF. The reader used to
    assume a document WAS an order, so four orders came back as one: the first
    order's number in column A of every row, the first order's R.D.D on all of
    them, and one merged total checked against each order's own lines. Nothing
    raised - the file simply said the wrong thing on three quarters of its
    rows, which is the worst shape a failure can take here.

    These checks are the contract that replaced it: the reading keeps a block
    per PO, the writer stamps every row with THAT row's order, and a document
    holding one order is untouched.
    """
    import orderflow as OF

    checks, failed = [], 0

    def check(label, ok, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, label, detail))

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ce_dir = os.path.join(base_dir, "CodeExtract")
    if ce_dir not in sys.path:
        sys.path.insert(0, ce_dir)
    import claude_engine

    # ---- the schema asks for ORDERS, not for one order -------------------
    props = claude_engine._TOOL["input_schema"]["properties"]
    check("the tool returns a list of orders",
          list(props) == ["orders"] and
          props["orders"].get("type") == "array", str(list(props)))
    check("...required, so a single-order document still answers in it",
          claude_engine._TOOL["input_schema"]["required"] == ["orders"])
    check("...one entry per DISTINCT order, said in the prompt",
          "DISTINCT PURCHASE ORDER" in claude_engine._SYSTEM)
    check("...and which order a line belongs to (the nearest header above)",
          "nearest one ABOVE" in claude_engine._SYSTEM)
    check("...first inventories every page before extracting lines",
          "FIRST PASS" in claude_engine._SYSTEM
          and "inspect EVERY PAGE" in claude_engine._SYSTEM)
    check("...verifies the returned order count against explicit PO numbers",
          "exactly one entry for every distinct explicit order number"
          in claude_engine._SYSTEM)
    check("...does not deduplicate repeated products across different POs",
          "Do not deduplicate across orders" in claude_engine._SYSTEM)
    item = props["orders"]["items"]["properties"]
    check("each order carries its own number, total, dates and address",
          all(k in item for k in ("po_number", "document_total", "po_date",
                                  "rdd", "ship_to", "lines")), str(sorted(item)))
    check("...and its own line items",
          "material_code" in item["lines"]["items"]["properties"])

    def line(code, qty, price, page=1):
        return {"material_code": code, "description": "SAMSUNG " + code,
                "quantity": qty, "unit": "EA", "unit_price": price,
                "amount": "", "po_line": "", "page": str(page),
                "source_line": f"{code} {qty} {price}"}

    SHIP = {"name": "", "address_lines": ["4444-46 AYERS AVE"],
            "city": "VERNON", "state": "CA", "postal_code": "90058"}
    # The four POs of "Curacao 4 PO's 5-12-26.pdf": one buyer, one ship-to,
    # four numbers and four different delivery dates. The first two lines are
    # the SAME model, quantity and price on the SAME page in two different
    # orders - which is exactly what a document-wide dedupe would eat.
    payload = {"orders": [
        {"po_number": "ALRRY-A", "document_total": "128970.00",
         "po_date": "04/29/26", "rdd": "06/05/26", "ship_to": SHIP,
         "lines": [line("RT16A6195SR", "15", "519.00"),
                   line("RS27T5200SG", "8", "959.00")]},
        {"po_number": "ALRT2-A", "document_total": "117091.00",
         "po_date": "04/29/26", "rdd": "06/18/26", "ship_to": SHIP,
         "lines": [line("RT16A6195SR", "15", "519.00"),
                   line("RS27T5200SG", "7", "959.00")]},
        {"po_number": "ALRT5-A", "document_total": "135867.00",
         "po_date": "04/29/26", "rdd": "07/06/26", "ship_to": SHIP,
         "lines": [line("RT16A6195SR", "15", "519.00")]},
        {"po_number": "ALRT8-A", "document_total": "117091.00",
         "po_date": "04/29/26", "rdd": "07/20/26", "ship_to": SHIP,
         "lines": [line("RS27T5200SG", "3", "959.00")]},
    ]}

    tmp = tempfile.mkdtemp(prefix="ofmpo_")
    try:
        res = claude_engine._finalise(
            payload, "Curacao 4 PO's 5-12-26.pdf",
            claude_engine.Path(tmp) / "c.json", "md5", "ADIR/CURACAO")

        check("four POs in one document are read as four",
              res["order_count"] == 4, str(res["order_count"]))
        check("...each with its own number",
              res["po_numbers"] == ["ALRRY-A", "ALRT2-A", "ALRT5-A", "ALRT8-A"],
              str(res["po_numbers"]))
        check("...and its own delivery date",
              [o["rdd"] for o in res["orders"]] ==
              ["2026-06-05", "2026-06-18", "2026-07-06", "2026-07-20"],
              str([o["rdd"] for o in res["orders"]]))
        check("...and its own printed total",
              [o["document_total"] for o in res["orders"]] ==
              ["128970.00", "117091.00", "135867.00", "117091.00"])

        by_po = {}
        for r in res["records"]:
            by_po.setdefault(r["po_number"], []).append(r)
        check("every line knows the order it was printed on",
              set(by_po) == {"ALRRY-A", "ALRT2-A", "ALRT5-A", "ALRT8-A"},
              str(sorted(by_po)))
        check("...and keeps that order's index",
              [r["order_index"] for r in res["records"]] ==
              [0, 0, 1, 1, 2, 3], str([r["order_index"] for r in res["records"]]))
        check("the same line in two orders survives in both",
              len([r for r in by_po["ALRRY-A"]
                   if r["material_code"] == "RT16A6195SR"]) == 1 and
              len([r for r in by_po["ALRT2-A"]
                   if r["material_code"] == "RT16A6195SR"]) == 1,
              str(len(res["records"])))
        check("no single number is claimed for a multi-PO document",
              res["po_number"] == "", repr(res["po_number"]))
        check("...and no single address either - 'the' R.D.D does not exist",
              res["rdd"] == "" and res["ship_to_zip"] == "",
              f"{res['rdd']!r} / {res['ship_to_zip']!r}")
        check("a note about one order says which order it is about",
              not res["diagnostics"] or
              res["diagnostics"][0].startswith("PO "),
              str(res["diagnostics"][:2]))

        # ---- a single-order document is untouched ------------------------
        one = {"orders": [dict(payload["orders"][0])]}
        r1 = claude_engine._finalise(one, "one.pdf",
                                     claude_engine.Path(tmp) / "one.json", "m2")
        check("a one-order document still reports its own number",
              r1["order_count"] == 1 and r1["po_number"] == "ALRRY-A")
        check("...and its own dates and address at the top, as before",
              r1["po_date"] == "2026-04-29" and r1["rdd"] == "2026-06-05"
              and r1["ship_to_zip"] == "90058")
        check("...and its diagnostics are not prefixed with a PO",
              all(not d.startswith("PO ") for d in r1["diagnostics"]),
              str(r1["diagnostics"][:2]))
        same = OF.extractor_bridge.expand_orders([r1])
        check("expanding a one-order reading hands back the same object",
              len(same) == 1 and same[0] is r1)

        # ---- the split, and what the writer does with it -----------------
        parts = OF.extractor_bridge.expand_orders([res])
        check("the document splits into one result per order",
              len(parts) == 4, str(len(parts)))
        check("...each holding only its own lines",
              [len(p["records"]) for p in parts] == [2, 2, 1, 1],
              str([len(p["records"]) for p in parts]))
        check("...and its own dates, not the first order's",
              [p["rdd"] for p in parts] ==
              ["2026-06-05", "2026-06-18", "2026-07-06", "2026-07-20"])

        prepared, _nq, _nc, _dr, fixes = OF.erp_excel.prepare_lines(parts, {})
        check("every review line carries its own P/O No.",
              [l["po"] for l in prepared] ==
              ["ALRRY-A", "ALRRY-A", "ALRT2-A", "ALRT2-A", "ALRT5-A", "ALRT8-A"],
              str([l["po"] for l in prepared]))
        check("...and the order block it came from",
              all(l.get("order") for l in prepared))

        from openpyxl.utils import get_column_letter  # noqa: F401
        base = tempfile.mkdtemp(prefix="ofmpo2_")
        try:
            os.makedirs(os.path.join(base, "config"), exist_ok=True)
            os.makedirs(os.path.join(base, "data"), exist_ok=True)
            tpl = os.path.join(base_dir, "config", "erp_template.XLSX")
            if os.path.exists(tpl):
                shutil.copy2(tpl, os.path.join(base, "config",
                                               "erp_template.XLSX"))
                settings = {"_base": base, "erp_format": "full"}
                written = OF.erp_excel.build_upload(
                    parts, {"sold_to": "", "ship_to": ""}, settings)
                out, n, up_fixes = written[0], written[1], written[5]
                import openpyxl
                wb = openpyxl.load_workbook(out)
                ws = wb.active
                cmap, _ = OF.erp_excel.column_map(ws)
                first = OF.erp_excel.first_empty_row(ws, cmap) - n

                def col(row, field):
                    return ws.cell(row=row, column=cmap[field]).value

                rows = [(col(first + i, "po"), col(first + i, "rdd"))
                        for i in range(n)]
                check("the file gets every order's lines", n == 6, str(n))
                check("column A carries each row's own P/O No.",
                      [r[0] for r in rows] ==
                      ["ALRRY-A", "ALRRY-A", "ALRT2-A", "ALRT2-A",
                       "ALRT5-A", "ALRT8-A"], str([r[0] for r in rows]))
                check("column K carries each row's own R.D.D",
                      len({str(r[1])[:10] for r in rows}) == 4,
                      str(sorted({str(r[1])[:10] for r in rows})))
                check("...and the differing dates are reported, not hidden",
                      any("different R.D.D" in f for f in up_fixes),
                      str(up_fixes[:2]))
                wb.close()

                # The four-column sheet carries the P/O No. too (column A), so
                # it has the same job to do with less room to do it in.
                smp = OF.erp_excel.build_simple(parts, {}, settings)
                wb2 = openpyxl.load_workbook(smp[0])
                ws2 = wb2.active
                po_col = [ws2.cell(row=r, column=1).value
                          for r in range(2, 2 + smp[1])]
                check("the simple sheet keeps each row's own P/O No.",
                      po_col == ["ALRRY-A", "ALRRY-A", "ALRT2-A", "ALRT2-A",
                                 "ALRT5-A", "ALRT8-A"], str(po_col))
                wb2.close()
            check("the output file is named for the first PO and the count",
                  OF.erp_excel._po_tag(parts, {}) == "ALRRY-A_and3more",
                  OF.erp_excel._po_tag(parts, {}))
        finally:
            shutil.rmtree(base, ignore_errors=True)

        # ---- the preview and the Read tab show the list ------------------
        prev = OF.erp_excel.order_preview(
            {"sold_to": "", "ship_to": ""}, {"_base": tmp}, results=parts)
        check("the step-3 preview lists all four orders",
              len(prev.get("orders") or []) == 4, str(prev.get("orders")))
        rowmap = {r["field"]: r for r in prev["rows"]}
        check("...and says the dates are per PO instead of showing one",
              rowmap["rdd"]["pending"] == "each PO has its own",
              str(rowmap["rdd"]))
        check("...while an address every order shares is shown once",
              rowmap["ship_to_address"]["value"] == "4444-46 AYERS AVE",
              str(rowmap["ship_to_address"]))
        check("...with one warning that says what the file will contain",
              any("4 separate POs" in w for w in prev["warnings"]),
              str(prev["warnings"][:2]))

        prev1 = OF.erp_excel.order_preview(
            {"sold_to": "", "ship_to": ""}, {"_base": tmp}, results=[r1])
        check("a one-order preview is unchanged (no list, no warning)",
              prev1["orders"] == [] and
              not any("separate POs" in w for w in prev1["warnings"]))

        caches = OF.extractor_bridge._cache_orders(res)
        check("the Read tab can list the orders without the lines",
              [c["po"] for c in caches] ==
              ["ALRRY-A", "ALRT2-A", "ALRT5-A", "ALRT8-A"], str(caches))
        check("...each with its own line count and date",
              [c["lines"] for c in caches] == [2, 2, 1, 1] and
              caches[3]["rdd"] == "2026-07-20", str([c["lines"] for c in caches]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 68)
    print("One attachment, several POs - regression tests")
    print("=" * 68)
    for ok, label, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}")
        if not ok and detail:
            print(f"         {detail}")
    print("-" * 68)
    print(f"  {len(checks) - failed}/{len(checks)} passed")
    return 1 if failed else 0


SUITES = [
    ("po", main_po, "PO-number extraction rules"),
    ("lines", main_lines, "quantity, unit price and amount cross-checks"),
    ("ui", main_ui, "dashboard JavaScript syntax"),
    ("excel", run_excel, "Excel PO reader"),
    ("erp", run_erp, "ERP Order Upload column fill"),
    ("bridge", run_bridge, "normalise_to_master base / market-suffix matching"),
    ("sku", run_sku, "Product Mapping Table: short SKU -> FULL SKU, material groups"),
    ("classify", run_classify, "customer identification by sender domain"),
    ("p0", run_p0, "P0 fixes: master atomicity, attachment index, ERP mark, source"),
    ("p3", run_p3, "P3 residuals: amount shape, duplicate kind, PO rule, corrections"),
    ("extract", run_extract, "PO extraction: the accuracy gate, values as printed, the cache"),
    ("mailbox", run_mailbox, "Inbox mailbox scoping, backfill, settings defaults"),
    ("multipo", run_multipo, "one attachment holding several POs, end to end"),
]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    wanted = [a for a in argv if not a.startswith('-')]
    chosen = [s for s in SUITES if not wanted or s[0] in wanted]

    if wanted and not chosen:
        print('No such suite: ' + ', '.join(wanted))
        print('Available: ' + ', '.join(s[0] for s in SUITES))
        return 2

    failed = 0
    for name, fn, desc in chosen:
        print()
        print('=' * 68)
        print('  ' + name + ' - ' + desc)
        print('=' * 68)
        try:
            failed += 1 if fn() else 0
        except ImportError as e:
            print('  SKIP - a package is missing: ' + str(e))
        except Exception:
            traceback.print_exc()
            failed += 1

    print()
    print('ALL SUITES PASSED' if not failed else str(failed) + ' SUITE(S) FAILED')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
