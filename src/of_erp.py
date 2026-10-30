# -*- coding: utf-8 -*-
"""of_erp.py

OrderFlow ERP output: builds the Standard Order Upload workbook (full ERP form or the plain four-column sheet).

Split out of the former single-file orderflow.py at its SECTION
boundaries; the code is byte-for-byte what used to live there.
The facade namespaces (store, collector, ...) are still built by
orderflow.py, which also late-binds sibling facade names into this
module's globals.
"""

import sys
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import csv
import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import traceback
import webbrowser


# ==========================================================================
#  SECTION: ERP EXCEL - build the Standard Order Upload file
#  (formerly erp_excel.py)
# ==========================================================================

# -*- coding: utf-8 -*-
"""erp_excel.py - generate the ERP upload file in the Standard Order Upload format

Opens config/erp_template.XLSX (Standard Order Upload format) as a template and
fills in data rows only; every other column, the header row, the column widths
and the cell styles are kept exactly as the template has them.

The columns are found by HEADER NAME, not by a hard-coded letter (see
column_map). That is what keeps "put the value in the right column" true even
though the ERP form has been relabelled over time - the shipped form calls the
unit-price column "EDI1 condition value(O)", while an older copy of the same
form called it "Cost". A field whose header cannot be found falls back to the
position this form has always used, and says so in the log:
  P/O No.(M)              A  (1)   PO #        PDF-extracted value, else the mail value
  Sales Org.(M)           C  (3)   Sales Org   always 3101 (SALES_ORG)
  Distr. Channel(M)       D  (4)   Channel     the master row's TYPE - see below
  Division(M)             E  (5)   Division    always 00 (DIVISION)
  Sold To Party(M)        F  (6)   Sold-To     picked on the PO screen
  Ship To Paty(O)         G  (7)   Ship-To     picked on the PO screen
  Material(O)             H  (8)   Material    extractor result, normalised to the master
  Sales Quantity(M)       I  (9)   Quantity    extractor result, else corrected from the text
  Ship-to Name(O)         N  (14)  Site name   } from the Ship-To master row of the
  Ship-to Address(O)      R  (18)  Address     } (Sold-To, Ship-To) pair picked on screen
  Ship-to Postal Code(O)  W  (23)  ZIP         }
  Ship-to City(O)         X  (24)  City        }
  Sold-to Name2(O)        AI (35)  Sold-To nm. }
  EDI1 condition value(O) BE (57)  Unit price  the contract price printed on the PO

The (Sold-To, Ship-To) pair is the composite key the six columns above come
from - one row of config/ship_to_master.json carries the site's name, address,
city and postal code and the Sold-To's own name. That row's TYPE decides the
Distribution Channel: exactly "Builder" is 11, everything else is 10 (see
ship_master.channel_for_type).

When the pair is not in the master, or its rows disagree about those details,
the cells are left EMPTY and the log says which of the two it is - never
guessed at. An empty mandatory column is a loud failure at upload time; a
wrong channel is a silent one.

Note the header text is used as written on the form, typo included
("Ship To Paty").
"""

TEMPLATE_REL = os.path.join("config", "erp_template.xlsx")

# The sales area every line of this order flow is uploaded under. Sales
# Organisation and Division are the same for every customer and every order, so
# they are constants rather than data anybody has to keep up to date.
# Distribution Channel is NOT fixed: it follows the TYPE of the Ship-To master
# row (ship_master.channel_for_type), so it stays a per-line value.
SALES_ORG = "3101"
DIVISION = "00"

# The currency the EDI1 condition value (the unit price, column BE) is expressed
# in - column BF, "EDI1 condition currency". Every price this tool writes is a
# USD contract price, so BF is filled with USD on every line instead of being
# left blank on the form.
CURRENCY = "USD"

# The form's fields: (name, header spellings to look for, column to use when the
# header cannot be found). The spellings are matched after punctuation, case and
# the trailing "(M)" / "(O)" marker are removed, and the aliases of one field are
# tried in order - so which column wins does not depend on column order.
COLUMNS = (
    ("po",      ("P/O No", "PO No"),                          1),   # A
    ("sales_org", ("Sales Org", "Sales Organization"),        3),   # C
    ("distr_channel", ("Distr. Channel", "Distribution Channel",
                       "Distr Channel"),                      4),   # D
    ("division", ("Division",),                               5),   # E
    ("sold_to", ("Sold To Party", "Sold-to Party"),           6),   # F
    ("ship_to", ("Ship To Paty", "Ship To Party"),            7),   # G
    ("code",    ("Material", "Material Code"),                8),   # H
    ("qty",     ("Sales Quantity", "Quantity"),               9),   # I
    # K, "R.D.D" - the REQUIRED DELIVERY DATE. Read off the PO ("Required
    # Date" / "ETA Date"); when the document prints none it defaults to the PO
    # date plus six working days (claude_engine.RDD_DEFAULT_NOTE). A date the
    # operator typed for this order always wins.
    ("rdd",     ("R.D.D", "RDD", "Required Delivery Date",
                 "Requested Delivery Date"),                 11),   # K
    ("po_date", ("P/O Date", "PO Date", "Purchase Order Date"),
                                                             13),   # M
    ("ship_to_name", ("Ship-to Name",),                      14),   # N
    # The numbered name lines and the street lines are separate columns on the
    # form; each is looked up by its own header ("Ship-to Name 2" is a
    # different key from "Ship-to Name", so the plain lookup cannot confuse
    # them). They are typed per order - folded away on the Inbox row because
    # most deliveries only need N and R.
    ("ship_to_name2", ("Ship-to Name 2",),                   15),   # O
    ("ship_to_name3", ("Ship-to Name 3",),                   16),   # P
    ("ship_to_name4", ("Ship-to Name 4",),                   17),   # Q
    ("ship_to_address", ("Ship-to Address",),                18),   # R
    ("ship_to_street2", ("Ship-to Street 2",),               19),   # S
    ("ship_to_street3", ("Ship-to Street 3",),               20),   # T
    ("ship_to_street4", ("Ship-to Street 4",),               21),   # U
    ("ship_to_street5", ("Ship-to Street 5",),               22),   # V
    ("ship_to_zip", ("Ship-to Postal Code",),                23),   # W
    ("ship_to_city", ("Ship-to City",),                      24),   # X
    # AZ, "Ship-to Region" - the state. A per-order choice from a fixed list,
    # not a free-text box, so a two-letter code cannot be mistyped into an
    # address line the ERP would reject.
    ("ship_to_region", ("Ship-to Region",),                  52),   # AZ
    ("sold_to_name", ("Sold-to Name2", "Sold To Name2"),     35),   # AI
    ("cost",    ("EDI1 condition value", "Condition Value",
                 "Unit Cost", "Cost"),                       57),   # BE
    # The currency OF the EDI1 condition value above. The aliases name the EDI1
    # column specifically: a bare "Currency" would match column BD
    # ("Currency(O)"), which is a different field, and BD comes first on the
    # form, so the lookup would land there.
    ("currency", ("EDI1 condition currency", "Condition Currency"),
                                                             58),   # BF
)

# Fields written as TEXT even though they look numeric. Sales Org 3101 and
# Division 00 are codes, not numbers: as a number "00" becomes 0, which is a
# different sales area. The ship-to postal code is text too - 08861 typed as a
# number loses its leading zero. "USD" is text by nature, but it is listed here
# so every code column is written the same way. Kept in one place so write_line
# and the tests agree.
TEXT_FIELDS = ("po", "sales_org", "distr_channel", "division", "currency",
               "sold_to_name", "ship_to_name", "ship_to_name2",
               "ship_to_name3", "ship_to_name4", "ship_to_address",
               "ship_to_street2", "ship_to_street3", "ship_to_street4",
               "ship_to_street5", "ship_to_city", "ship_to_zip",
               "ship_to_region")

# Without these three the workbook is not the Standard Order Upload form at all.
_REQUIRED = ("po", "code", "qty")
MAX_HEADER_ROW = 10      # give up looking for the header row after this

# --------------------------------------------------------------------------
#  Output format - the full ERP form, or a plain four-column sheet
# --------------------------------------------------------------------------
# "full"   the Standard Order Upload form above: every column the ERP asks for,
#          filled into config/erp_template.XLSX. This is what gets uploaded.
# "simple" a plain workbook holding just the four values somebody has to read
#          or retype: PO #, Material, Sales Quantity, Unit Price. Built from
#          scratch, so no template - and therefore no DRM-protected form - can
#          block it.
FORMAT_FULL = "full"
FORMAT_SIMPLE = "simple"

SIMPLE_SHEET = "Order Upload"
# (field, header text, column width), written left to right in this order
SIMPLE_COLUMNS = (
    ("po",   "PO #",           16),
    ("code", "Material",       22),
    ("qty",  "Sales Quantity", 15),
    ("cost", "Unit Price",     13),
)


def output_formats(value, default=FORMAT_FULL):
    """Normalise a format choice - ONE value or a LIST of them - to a list.

    Since 2026-10-27 the two versions are not exclusive: a user who uploads the
    full form to ERP and also wants the four-column sheet for keying by hand
    ticks both, and both files are written. So the stored setting is a LIST
    (["full"], ["simple"] or ["full", "simple"]), and this is the one place that
    decides what a value means.

    Returns at least one entry, in the fixed order full -> simple, so a caller
    can always treat element 0 as the primary file. A typo never changes the
    shape of what is uploaded: anything unrecognised falls back to `default`,
    and a list whose entries are all junk does the same.
    """
    if isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = [value]
    picked = []
    for v in raw:
        s = str(v or "").strip().lower()
        if not s:
            continue
        f = FORMAT_SIMPLE if s.startswith("s") else FORMAT_FULL
        if f not in picked:
            picked.append(f)
    if not picked:
        d = str(default or "").strip().lower()
        picked = [FORMAT_SIMPLE if d.startswith("s") else FORMAT_FULL]
    return [f for f in (FORMAT_FULL, FORMAT_SIMPLE) if f in picked]


def output_format(value, default=FORMAT_FULL):
    """The PRIMARY format of a choice - the first of `output_formats()`.

    Kept for the callers that legitimately want one file (the preview's heading,
    a single-format build). Anything that WRITES should loop over
    `output_formats()` instead, or the second ticked version is silently lost.
    """
    return output_formats(value, default)[0]


def is_simple(value):
    """True when the caller asked for the four-column sheet ONLY."""
    fmts = output_formats(value)
    return len(fmts) == 1 and fmts[0] == FORMAT_SIMPLE

# "QTY: 2" form
_QTY_LABEL = re.compile(r"\bQTY\.?\s*:?\s*(\d{1,4})(?:\.\d+)?\b", re.IGNORECASE)
# "... 2 $959 $1918" (price list layout, e.g. Abt)
_QTY_MONEY = re.compile(r"(?<!\S)(\d{1,4})\s+\$\s*[\d,]+(?:\.\d+)?\s+\$")
# "... 1.00 EA 104.00" / "2 EA" (decimal quantities, e.g. KB Home)
_QTY_UNIT = re.compile(
    r"(?<![\d.])(\d{1,4})(?:\.\d{1,2})?\s*(?:EA|EACH|PCS?|UNITS?)\b",
    re.IGNORECASE)
# Last fallback: "1.00" / "2.0" form (max 3 digits to avoid confusion with unit price/amount).
# A unit of measure must NOT follow: "6.0 cf" is a 6 cubic-foot capacity, not 6 pieces.
# This was a real defect - POs for a 6.0 cf dryer were uploaded with quantity 6.
_QTY_DECIMAL = re.compile(
    r"(?<![\d.])(\d{1,3})\.0{1,2}(?![\d.])"
    r"(?!\s*(?:cf|cu\.?\s?ft|cuft|ft|in(?:ch)?|\"|lb|kg|oz|v|w|hz|amp|a|mm|cm|"
    r"gal|qt|db|rpm)\b)", re.IGNORECASE)

# Money value anywhere on a line - used to recover the extended amount so that
# qty x unit price can be cross-checked against what the PO actually printed.
_MONEY_ANY = re.compile(r"\$?\s*([\d,]+\.\d{2})(?![\d])")

# No OCR digit repair any more. It rewrote a value the document had printed
# ("S4" -> 54) and PO reading is a document read now, not an OCR pass: the
# reader returns the digits it saw, and a value we are not sure of goes to the
# review list instead of being silently rewritten (chapter 4, rule 1).

# Unit price extraction: 959 from "2 $959 $1918" (first amount after qty = unit price, second = total)
_COST_MONEY = re.compile(
    r"(?<!\S)\d{1,4}\s+\$\s*([\d,]+(?:\.\d+)?)\s+\$")
# "1.00 EA 104.00 EA 9.10 113.10" form: first amount after the unit.
#
# ⚠️ Only valid when the unit word is followed by the PRICE. Samsung's ERP
# prints the UOM in its own column BETWEEN the code and the quantity, so the
# printed line reads "ME17R7021ES EA 85.00 199.00" - the amount after "EA" is
# the QUANTITY, and matching it published 85 as the unit price (and even
# recorded it as a "correction" of the engine's 199.00). The caller therefore
# only trusts this when the engine has no price of its own (see
# prepare_lines), so a price the engine read from a named column always wins.
_COST_UNIT = re.compile(
    r"(?:EA|EACH|PCS?|UNITS?)\s+([\d,]+\.\d{2})", re.IGNORECASE)


def _cost_from_desc(desc, currency_only=False):
    """Extract the unit price from description text (per-unit price, not the total)

    currency_only restricts the search to the currency-anchored pattern
    (_COST_MONEY), which is the only one of the two that is unambiguous: a
    figure printed after a $ sign is the price column. _COST_UNIT keys off a
    unit word, and Samsung's ERP prints "ME17R7021ES EA 85.00 199.00" - the
    UOM column, then the QUANTITY, then the price - so the amount after "EA"
    is the count. The unit-word pattern is therefore only consulted when the
    engine has no price of its own (see prepare_lines).
    """
    if not desc:
        return None
    rxs = (_COST_MONEY,) if currency_only else (_COST_MONEY, _COST_UNIT)
    for rx in rxs:
        mo = rx.search(desc)
        if mo:
            return _num(mo.group(1))
    return None


def _dedupe_records(records):
    """Split records into (kept, dropped) - see dedupe_line_records()."""
    groups, order = {}, []
    for r in records:
        desc = re.sub(r"\s+", " ", (r.get("description") or "")).strip()
        if not desc:                     # no description, cannot decide - keep as is
            key = "__keep__" + str(id(r))
        else:
            # Same line = same description AND same quantity and unit price.
            # A model quoted inside an item description sits on that item's
            # row, so it inherits the row's figures. Description alone is not
            # enough: when the code list carries no description of its own,
            # the engine labels every code in a block with the block's text,
            # and six real order lines collapsed into three.
            key = (desc, str(r.get("quantity") or "").strip(),
                   str(r.get("unit_price") or "").strip())
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)

    kept, dropped = [], []
    for key in order:
        g = groups[key]
        if len(g) == 1:
            kept.append(g[0])
            continue
        text = key[0].upper() if isinstance(key, tuple) else ""
        best, best_pos = g[0], -2
        for r in g:
            code = str(r.get("material_code") or "")
            pos = text.rfind(code.upper()) if code else -1
            if pos > best_pos:
                best, best_pos = r, pos
        for r in g:
            (kept if r is best else dropped).append(r)
    return kept, dropped


def dedupe_line_records(records):
    """When several codes are extracted from the same line (description), keep only one.

    In a PO table the actual ordered code (VIN/Model column) comes right before
    the qty/unit price columns, while model names quoted inside the item description
    (e.g. "TRIM KIT FOR MS19M8000AS") come earlier. So the last code in the line text is chosen.
    Returns: (cleaned records, list of removed codes)
    """
    kept, dropped = _dedupe_records(records)
    return kept, [str(r.get("material_code") or "?") for r in dropped]


def _qty_from_desc(desc):
    """Fallback extraction of qty from description text when the engine missed it"""
    if not desc:
        return ""
    for rx in (_QTY_LABEL, _QTY_MONEY, _QTY_UNIT):
        mo = rx.search(desc)
        if mo:
            return mo.group(1)
    # The qty column precedes unit price/amount, so take the first decimal value
    mo = _QTY_DECIMAL.search(desc)
    return mo.group(1) if mo else ""


def _amount_from_line(line):
    """Extended amount = the last money value printed on the line."""
    if not line:
        return None
    vals = _MONEY_ANY.findall(line)
    return _num(vals[-1]) if vals else None


def _num(q):
    try:
        f = float(str(q).replace(",", "").strip())
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return q if q not in (None, "") else ""


def _hkey(text):
    """A header cell reduced to a comparable key.

    "P/O No.(M)" and "P/O No" both become "PONO": punctuation and the
    mandatory/optional marker are dropped, because they carry no meaning for the
    lookup and the ERP adds them inconsistently from one form revision to the next.
    """
    t = re.sub(r"\((?:M|O)\)\s*$", "", str(text or "").strip(), flags=re.I)
    return re.sub(r"[^A-Za-z0-9]", "", t).upper()


def header_row(ws):
    """The row that holds the column names.

    Row 1 on every template seen so far, but a form can carry a title or an
    instruction block above the header - and _plain_template_copy() keeps such a
    leading block - so the row is found by looking for the required headers
    instead of being assumed. Falls back to 1, which makes an unrecognised
    workbook behave exactly as it did before.
    """
    if ws is None:
        return 1
    for r in range(1, min(ws.max_row, MAX_HEADER_ROW) + 1):
        keys = {_hkey(ws.cell(row=r, column=c).value)
                for c in range(1, ws.max_column + 1)}
        if all(any(_hkey(a) in keys for a in aliases)
               for name, aliases, _ in COLUMNS if name in _REQUIRED):
            return r
    return 1


def column_map(ws, row=None):
    """{field: column number} read off the template's header row.

    Returns (map, notes). `notes` names every field that had to fall back to the
    column this form has always used, so a renamed column is visible in the log
    instead of quietly landing the data somewhere unexpected.
    """
    row = row or header_row(ws)
    keys = {}
    for c in range(1, ws.max_column + 1):
        k = _hkey(ws.cell(row=row, column=c).value)
        if k and k not in keys:
            keys[k] = c
    out, notes = {}, []
    matched = {}
    for name, aliases, default in COLUMNS:
        for alias in aliases:
            if _hkey(alias) in keys:
                matched[name] = keys[_hkey(alias)]
                break
    taken = set(matched.values())
    for name, aliases, default in COLUMNS:
        if name in matched:
            out[name] = matched[name]
            continue
        # The positional fallback assumes the standard form. On a form that has
        # been reordered (or relabelled), that position can already belong to a
        # DIFFERENT field - and writing a date into, say, the Sold-To Name
        # column is worse than leaving the cell empty, because the ERP accepts
        # the file and the value lands somewhere nobody looks. So the fallback
        # is only used when the position is free.
        if default in taken:
            owner = next((n for n, c in matched.items() if c == default), "?")
            notes.append(f"{name}: no matching header, and column {default} "
                         f"(the position this form has always used) belongs to "
                         f"'{owner}' on this form - left EMPTY rather than "
                         "written into the wrong column")
            continue
        out[name] = default
        notes.append(f"{name}: no matching header, using column {default} "
                     f"(the position this form has always used)")
    return out, notes


def validate_template(ws):
    """Say whether this workbook really is the Standard Order Upload form.

    Without the check a template that is simply a different spreadsheet would be
    accepted and its data rows written into whatever happened to sit in columns
    1/8/9 - values the ERP would then reject or, worse, accept as something else.
    """
    found = [name for name, aliases, _ in COLUMNS
             if name in _REQUIRED
             and any(_hkey(a) in {_hkey(ws.cell(row=header_row(ws), column=c).value)
                                  for c in range(1, ws.max_column + 1)}
                     for a in aliases)]
    if found:
        return True, ""
    want = ", ".join(dict((n, None) for n, _a, _d in COLUMNS if n in _REQUIRED))
    return False, (f"config/erp_template.XLSX does not look like the Standard "
                   f"Order Upload form - none of its header names "
                   f"({want}) was found. Replace it with the ERP form.")


def template_status(settings):
    """Is the ERP template usable on this PC? For the startup check.
    Returns: (ok, message)"""
    try:
        open_template(settings)
        return True, ""
    except Exception as e:
        return False, str(e)


def template_path(base):
    """Where the template actually is.

    TEMPLATE_REL spells it erp_template.xlsx while the shipped file is
    erp_template.XLSX (the name the release step and the docs use). Windows hides
    the difference; a case-sensitive filesystem would not, so both are accepted.
    """
    want = os.path.join(base, TEMPLATE_REL)
    if os.path.exists(want):
        return want
    alt = os.path.join(base, TEMPLATE_REL[:-len(".xlsx")] + ".XLSX")
    return alt if os.path.exists(alt) else want


def open_template(settings):
    """Open the ERP template from config\\ and return (workbook, worksheet).

    The template that shipped in the first snapshots was an internal ERP form
    and therefore NASCA DRM protected; it has since been replaced by a plain
    workbook with the same Standard Order Upload layout. The DRM route is kept:
    a template copied from the ERP portal is protected again, and dropping a
    protected file would make the whole ERP step unusable on that PC.
    """
    base = settings.get("_base", "")
    tpl = template_path(base)
    if not os.path.exists(tpl):
        raise RuntimeError(
            "ERP template not found: config/erp_template.XLSX "
            "(copy the 'Standard Order Upload format' file there)")
    with open(tpl, "rb") as f:
        head = f.read(8)
    if head[:2] != b"PK":
        if head[:2] == b"<#":
            # The template is an internal ERP form, so it usually carries DRM.
            # Excel is an authorised application, so ask it for a plain working
            # copy - the same delegation used for customer price sheets.
            tpl = _plain_template_copy(tpl, settings)
        else:
            raise RuntimeError(
                "config/erp_template.XLSX is not a valid .xlsx file "
                f"(it starts with {head[:4]!r}). Replace it with the Standard "
                "Order Upload format workbook.")
    import openpyxl
    wb = openpyxl.load_workbook(tpl)
    ws = wb.active
    ok, why = validate_template(ws)
    if not ok:
        raise RuntimeError(why)
    return wb, ws


def _plain_template_copy(tpl, settings):
    """Rebuild the template as a plain workbook, and cache it.

    Asking Excel to *save* a copy does not work here: the security agent
    re-protects anything an authorised application writes to disk. Reading the
    cell VALUES through Excel does work, though - that is how customer price
    sheets are already read - because nothing is written.

    So the header block is read in memory and written out again by openpyxl,
    which produces a plain file because OrderFlow is not an authorised writer.
    Colours and column widths are lost; the ERP upload only reads values and
    column positions, so that costs nothing.
    """
    base = settings.get("_base", "")
    cache_dir = os.path.join(base, "data", "tmp")
    os.makedirs(cache_dir, exist_ok=True)
    cached = os.path.join(cache_dir, "erp_template_plain.xlsx")
    try:
        if (os.path.exists(cached)
                and os.path.getmtime(cached) >= os.path.getmtime(tpl)):
            with open(cached, "rb") as f:
                if f.read(2) == b"PK":
                    return cached
    except OSError:
        pass

    try:
        rows = material_master._rows_via_excel(tpl)
    except Exception as e:
        raise RuntimeError(_TEMPLATE_DRM_MSG.format(
            why=f"Excel could not read it either - {str(e).splitlines()[0][:90]}"))
    if not rows:
        raise RuntimeError(_TEMPLATE_DRM_MSG.format(
            why="Excel opened it but it looks empty"))

    # Excel can fail to decrypt and hand back the DRM envelope itself as text.
    # The NASCA add-in is licensed per machine, so this is exactly what a PC
    # that has not been granted access sees. Without this check the envelope
    # reaches openpyxl, which reports IllegalCharacterError - a message that
    # names neither the file nor the reason, so the operator cannot tell it is a
    # licensing problem on this one file.
    if str((rows[0] or [""])[0] or "").startswith("<## NASCA"):
        raise RuntimeError(_TEMPLATE_DRM_MSG.format(
            why="Excel returned the DRM envelope itself, so this PC is not "
                "able to decrypt it (the NASCA add-in is per-machine)"))

    # Keep the header block: every leading row up to the first empty one.
    header = []
    for row in rows:
        if not any(c not in (None, "") for c in row):
            break
        header.append(row)
    if not header:
        raise RuntimeError(_TEMPLATE_DRM_MSG.format(
            why="no header row could be found in it"))

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in header:
        ws.append(list(row))
    try:
        wb.save(cached)
    except Exception as e:
        raise RuntimeError(_TEMPLATE_DRM_MSG.format(
            why=f"the rebuilt copy could not be saved - "
                f"{str(e).splitlines()[0][:80]}"))

    with open(cached, "rb") as f:
        if f.read(2) != b"PK":
            raise RuntimeError(_TEMPLATE_DRM_MSG.format(
                why="even the rebuilt copy came back protected"))
    print(f"  [ERP] template rebuilt as a plain copy "
          f"({len(header)} header row(s), {len(header[0])} columns)")
    return cached


_TEMPLATE_DRM_MSG = (
    "config/erp_template.XLSX is protected by NASCA DRM and a plain working "
    "copy could not be produced ({why}).\n\n"
    "Release the DRM on that one file - it is a blank form, not customer "
    "data - and put the unprotected copy directly in config/erp_template.XLSX. "
    "No build/packaging step is needed; the dashboard reads it from there "
    "at runtime.\n\n"
    "A plain workbook with the same header row works just as well: a previous "
    "Order Upload file, once its data rows are cleared, is the simplest source "
    "- that is how the template in this snapshot was produced.")


def first_empty_row(ws, cmap=None):
    """First data row of the template that is still empty.

    `cmap` is the map from column_map(); the fields it names are the ones a real
    data row can never leave blank on its own, so any of them being filled means
    the row is taken. Without a map the five legacy columns are used.
    """
    row = header_row(ws) + 1
    cols = (1, 6, 7, 8, 9) if not cmap else tuple(
        cmap[k] for k in ("po", "sold_to", "ship_to", "code", "qty") if k in cmap)
    while any(ws.cell(row=row, column=c).value not in (None, "") for c in cols):
        row += 1
    return row


def _po_date(value):
    """The email's received date as a value Excel will treat as a date.

    `received_at` is ISO ('2026-10-14T17:20:58'); M is written as a real date so
    the template's own 'mm-dd-yy' format applies to it, rather than as a string,
    which a person (or SAP) would then have to convert by hand.

    Returns "" for anything that cannot be read as a date, so an unparseable
    value leaves the cell EMPTY instead of writing something wrong - the same
    rule the quantity and price follow.
    """
    s = (value or "").strip()
    if not s:
        return ""
    if "T" in s:
        s = s.split("T", 1)[0]
    elif " " in s:
        s = s.split(" ", 1)[0]
    try:
        return datetime.datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return ""


def write_line(ws, row, cmap, po=None, sold_to=None, ship_to=None,
               code=None, qty=None, cost=None, distr_channel=None,
               sold_to_name=None, ship_to_name=None, ship_to_name2=None,
               ship_to_name3=None, ship_to_name4=None, ship_to_address=None,
               ship_to_street2=None, ship_to_street3=None,
               ship_to_street4=None, ship_to_street5=None,
               ship_to_city=None, ship_to_zip=None, ship_to_region=None,
               currency=None, po_date=None, rdd=None):
    """Write one order line by FIELD NAME, so the template decides the column.

    Nothing is written for a value that is empty: an absent quantity must stay
    an empty cell, not become a 0 the ERP would read as a real order line. The
    one exception is the currency, which is a constant rather than data - see
    below.

    Sales Org, Division and the EDI1 condition currency are the fixed
    constants; the Sold-To / Ship-To codes, the Ship-To name / address / city /
    postal code, the Sold-To name and the Distribution Channel all come from the
    Ship-To master row of the (Sold-To, Ship-To) pair the caller picked - see
    _party_fill(). Codes are written as text so a leading zero survives -
    Division "00" typed as a number is 0, which addresses a different sales
    area.

    **Column M ("P/O Date") is the email's received date.** It is written as a
    real date (not text) so the template's own format applies. A value that
    cannot be read as a date leaves the cell EMPTY rather than writing
    something wrong.

    **Column BF ("EDI1 condition currency") is always USD.** It is the currency
    of the unit price in BE, and every price on this flow is a USD contract
    price, so the cell is filled even on a line that printed no price: a blank
    currency next to a filled one is the kind of half-filled row the ERP
    rejects. `currency=None` writes the constant; pass "" to leave it blank.
    """
    sales_org, division = SALES_ORG, DIVISION
    if currency is None:
        currency = CURRENCY
    for field, value in (("po", po), ("sales_org", sales_org),
                         ("distr_channel", distr_channel),
                         ("division", division),
                         ("sold_to", sold_to), ("ship_to", ship_to),
                         ("code", code), ("qty", qty), ("cost", cost),
                         ("currency", currency), ("po_date", po_date),
                         ("rdd", rdd),
                         ("sold_to_name", sold_to_name),
                         ("ship_to_name", ship_to_name),
                         ("ship_to_name2", ship_to_name2),
                         ("ship_to_name3", ship_to_name3),
                         ("ship_to_name4", ship_to_name4),
                         ("ship_to_address", ship_to_address),
                         ("ship_to_street2", ship_to_street2),
                         ("ship_to_street3", ship_to_street3),
                         ("ship_to_street4", ship_to_street4),
                         ("ship_to_street5", ship_to_street5),
                         ("ship_to_city", ship_to_city),
                         ("ship_to_zip", ship_to_zip),
                         ("ship_to_region", ship_to_region)):
        col = cmap.get(field)
        if col is None:
            continue
        if field in ("qty", "cost"):
            value = _num(value)
        elif field in ("po_date", "rdd"):
            # Both are real dates on the form (K and M), so the template's own
            # date format applies instead of a string the ERP would have to
            # convert. An unreadable value leaves the cell empty.
            value = _po_date(value)
        if value in (None, ""):
            continue
        cell = ws.cell(row=row, column=col,
                       value=str(value) if field in TEXT_FIELDS else value)
        if field == "cost":
            # Column BE, "displayed to two decimals" (2026-10-27). A NUMBER
            # FORMAT, not a round: 1198.4 stays 1198.4 in the cell - the ERP
            # still imports exactly what the PO printed - and Excel shows it as
            # 1,198.40. Without this the template's own General format printed a
            # whole-dollar contract price as "1198", which reads as a different
            # number next to the PO.
            cell.number_format = "#,##0.00"


def output_path(base, prefix, tag):
    """Where a generated upload file goes: data\\erp_upload, timestamped.

    Both formats land in the same folder so the ERP step has one place to
    look; the file name is what says which one it is.
    """
    outdir = os.path.join(base, "data", "erp_upload")
    os.makedirs(outdir, exist_ok=True)
    safe = "".join(ch for ch in str(tag) if ch.isalnum() or ch in "-_")[:20]
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(outdir, f"{prefix}_{safe or 'QuickConvert'}_{ts}.xlsx")


def simple_workbook():
    """A fresh four-column workbook - PO #, Material, Sales Quantity, Unit Price.

    Built from scratch instead of from a template: "simple" means those four
    values and nothing else, and a generated sheet cannot be blocked by a
    DRM-protected form the way config/erp_template.XLSX could.
    """
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SIMPLE_SHEET
    fill = PatternFill("solid", fgColor="DCE6F1")
    for i, (_field, head, width) in enumerate(SIMPLE_COLUMNS, start=1):
        cell = ws.cell(row=1, column=i, value=head)
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.alignment = Alignment(horizontal="left", vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"
    return wb, ws


def write_simple(ws, row, po=None, code=None, qty=None, cost=None):
    """One line in the simple sheet.

    Same rule as write_line(): an empty value stays an empty cell, never a 0
    the ERP would read as a real order line.
    """
    values = {"po": po, "code": code, "qty": qty, "cost": cost}
    for i, (field, _head, _width) in enumerate(SIMPLE_COLUMNS, start=1):
        value = values.get(field)
        if field in ("qty", "cost"):
            value = _num(value)
        if value in (None, ""):
            continue
        cell = ws.cell(row=row, column=i,
                       value=str(value) if field == "po" else value)
        if field == "cost":
            cell.number_format = "#,##0.00"


def prepare_lines(results, mail=None, keep_dropped=False):
    """Turn extractor results into upload lines without writing a file.

    Applies the same clean-up build_upload always did: drop models quoted
    inside descriptions, recover quantity from the original PDF line, and
    prefer the unit price printed on the PO over the price-list value.
    No arithmetic is applied: a value is published only where the document
    actually printed one.
    keep_dropped: also return the models judged to be quoted inside another
      item's description, with include=False, so a reviewer can tick them
      back in (Quick Convert). The mail Confirm path leaves them out.
    Returns: (lines, no_qty, no_cost, dropped, fixes)
      lines: [{po, code, qty, cost, include, needs_review, review_reason,
               suffix_autofilled, suffix_original, normalisation_warning,
               order}]
      fixes: human-readable notes about every value that was corrected

    `include` is False for a line whose code the Material Code list does not
    carry: it is still returned (so the operator sees it) but it must be ticked
    before it is written. `needs_review` / `review_reason` are what the screen
    highlights; `include` is what the writer obeys.

    `fixes` is not decoration. HANDOVER 4.0 puts it as principle 5: "Every
    correction must be visible - a silent correction is indistinguishable from
    a bug." The parameter survived the 2026-10 removal of the arithmetic
    cross-check, but every `fixes.append` went with it, so the list was always
    empty while the recoveries below still happened silently. It now records
    the two recoveries that remain: a quantity, or a unit price, taken from the
    printed line because the reader had none. Nothing overrides a value the
    reader did report, and a value that merely passes through is NOT a fix and
    is not listed.
    """
    mail = mail or {}
    out, no_qty, no_cost, dropped_all, fixes = [], [], [], [], []
    for res in results:
        # The P/O No. this result belongs to. `expand_orders()` has already made
        # one result per order, so a multi-PO document reaches here as several
        # results and each keeps its own number on its own lines.
        po = res.get("po_number") or mail.get("po_number") or ""
        kept, dropped = _dedupe_records(res.get("records", []))
        dropped_all.extend(str(r.get("material_code") or "?") for r in dropped)
        # A code the Material Code list does not carry is SHOWN but not
        # included (2026-10-22). `needs_review` comes from the gate; it means
        # "a human has to tick this before it is uploaded", which is different
        # from `dropped` (a line whose model was only quoted in a description).
        recs = [(r, not r.get("needs_review")) for r in kept]
        if keep_dropped:
            recs += [(r, False) for r in dropped]
        for rec, include in recs:
            # The printed line as the reader reported it. This used to be re-read
            # out of the PDF with pdfplumber (to find the row the code came from),
            # which is one more PDF dependency and one more place to disagree.
            # The reader hands the line over with the record, so it is simply
            # taken from there.
            src = str(rec.get("source_line") or rec.get("description") or "")
            code = rec.get("material_code", "")

            # ── Quantity ──
            # `str(rec.get("quantity") or "")` used to swallow a real 0:
            # `0 or ""` is `""`, so a line the reader reported with quantity 0
            # looked like "the reader had none" and the number recovered from
            # the printed line OVERWROTE it - the same shape of mistake that
            # once published Samsung's "ME17R7021ES EA 85.00 199.00" quantity
            # (85) as the unit price. Contract 5: a recovery may only fill a
            # blank the reader left, never replace a value it reported.
            # Distinguish "reported 0" from "reported nothing", and treat
            # whitespace as nothing.
            raw_qty = rec.get("quantity")
            qty = None if raw_qty in (None, "") else str(raw_qty).strip()
            if qty == "":
                qty = None
            if qty is None:
                # The reader found no quantity; try the printed line.
                qty = _qty_from_desc(src) or None
                if qty is not None:
                    fixes.append(f"{code or '?'}: quantity {qty} recovered "
                                 f"from the printed line")

            # BE = unit price, exactly as the reader read it.
            #
            # Until 2026-10-21 this re-derived the price from the printed line
            # and let that override the reader's, on the grounds that "the
            # printed price is the contract price". That was written when the
            # two came from different places (a price list vs the document).
            # They do not any more: the reader reads the document, so the
            # override could only ever replace a right value with a wrong one -
            # and it did, Samsung's "ME17R7021ES EA 85.00 199.00" (UOM, then
            # the QUANTITY, then the price) published 85 as the unit price.
            # The recovery below therefore runs ONLY when the reader has no
            # price at all, and the ambiguous unit-word pattern last.
            #
            # Contract 6: 0.00 is NOT a price. Discount columns print 0.00 to
            # the LEFT of the unit price, and publishing that as the price put
            # a zero-cost line into ERP. A printed 0.00 means "no price here",
            # so it is left empty and reported like any other missing price.
            cost = _num(rec.get("unit_price"))
            if cost == 0:
                cost = None
            if cost in (None, ""):
                cost = _cost_from_desc(src, currency_only=True)
                if cost in (None, ""):
                    cost = _cost_from_desc(src)      # only source left
                if cost == 0:
                    cost = None
                if cost not in (None, ""):
                    fixes.append(f"{code or '?'}: unit price {cost} recovered "
                                 f"from the printed line")

            if include:
                if qty in (None, ""):
                    no_qty.append(code or "?")
                if cost in (None, ""):
                    no_cost.append(code or "?")
            out.append({"po": str(rec.get("po_number") or po),
                        "code": code,
                        "qty": "" if qty is None else qty,
                        "cost": "" if cost is None else cost,
                        "include": include,
                        "needs_review": bool(rec.get("needs_review")),
                        "review_reason": str(rec.get("review_reason") or ""),
                        # A safe, unique suffix completion is included, but it
                        # remains visibly amber so the operator can verify the
                        # inferred FULL SKU before download.
                        "suffix_autofilled": bool(
                            rec.get("suffix_autofilled")),
                        "suffix_original": str(
                            rec.get("suffix_original") or ""),
                        "normalisation_warning": str(
                            rec.get("normalisation_warning") or ""),
                        # The order this line was printed on, so the writer can
                        # give the row that order's address and dates instead of
                        # one set borrowed from the first order in the document.
                        "order": res})
    return out, no_qty, no_cost, dropped_all, fixes


def _party_fill(settings, sold_to, ship_to, pairs=None):
    """(fill, note) - what the Ship-To master may still supply for one pair.

    The pair IS the composite key, and it fills

        AI Sold-to Name2 · N Ship-to Name · D Distr. Channel

    (D comes from the row's TYPE - see ship_master.channel_for_type.)

    **The address columns are deliberately NOT taken from the master any more.**
    R (Ship-to Address), S-V (Street 2-5), W (Postal Code) and X (City) are
    typed per order instead. The master holds the *billing site* of a
    (Sold-To, Ship-To) pair, and the delivery address printed on a PO is
    routinely a different place - a job site, a store, a one-off drop. Copying
    the master's address into R put the wrong street on real orders, and an
    "empty means use the master's" fallback made the blank look like consent.
    N (Ship-to Name) keeps its default because it names the account rather than
    a place, and it stays editable per order.

    When a cell has to stay empty `note` says why: the pair is not in the
    master at all, or its rows disagree about the details. Nothing is guessed
    at - the same rule the old Distribution Channel lookup followed.
    """
    info, conflict = ship_master.site(settings, sold_to, ship_to, pairs)
    if info is None:
        return {}, (f"no Ship-To master row for Sold-To {sold_to or '—'} / "
                    f"Ship-To {ship_to or '—'} — N, AI and D left empty")
    if conflict:
        return {}, (f"Sold-To {sold_to} / Ship-To {ship_to} appears more than "
                    f"once in the Ship-To master with different details — "
                    f"N, AI and D left empty")
    return {
        "sold_to_name":  info.get("sold_to_name", ""),
        "ship_to_name":  info.get("ship_to_name", ""),
        "distr_channel": ship_master.channel_for_type(info.get("type")),
    }, ""


# The ship-to columns the PO may supply. Column N is deliberately NOT in this
# list: the master's Ship-to Name identifies the ACCOUNT, while the document's
# ship-to name identifies a delivery point, and letting the document displace
# the master's would rename the customer. N falls back to the document only when
# neither the row nor the master has one.
_PO_SHIP_FIELDS = ("ship_to_address", "ship_to_street2", "ship_to_street3",
                   "ship_to_street4", "ship_to_street5", "ship_to_city",
                   "ship_to_zip", "ship_to_region")


def _po_header(results, date_notes=True):
    """(header, notes) - the per-order values the PO(s) printed.

    One order document -> one header. Several attachments on one email are
    normally one order split across files, so the first non-empty value wins
    and a DISAGREEMENT is reported rather than averaged: two different PO dates
    mean the operator has to look, and silently taking one of them is how the
    wrong date reaches ERP.

    `date_notes=False` suppresses the two date notes, so the address caller
    does not repeat what `_order_dates()` reports once.
    """
    header, notes = {}, []
    for r in results or []:
        for key in ("po_date", "rdd", "rdd_source", "rdd_defaulted",
                    "ship_to_name") + _PO_SHIP_FIELDS:
            v = r.get(key)
            if isinstance(v, str):
                v = v.strip()
            if not v:
                continue
            if header.get(key) and str(header[key]) != str(v):
                if date_notes and key in ("po_date", "rdd"):
                    notes.append(
                        f"two documents give different {key.replace('_', ' ')}"
                        f"s ({header[key]} vs {v}) - {header[key]} was used")
                continue
            header.setdefault(key, v)
    if date_notes and header.get("rdd_defaulted"):
        notes.append(f"R.D.D {header.get('rdd')} is a DEFAULT "
                     f"({header.get('rdd_source')}) - change it if the "
                     "customer asked for another date")
    return header, notes


def _typed_dates(source):
    """(po_date, rdd) as typed on the row, '' when not typed."""
    source = source or {}
    return (str(source.get("po_date") or "").strip(),
            str(source.get("rdd") or "").strip())


def _order_dates(results, mail):
    """(po_date, rdd, notes) - the two dates by the one documented precedence.

        what the operator typed  >  what the PO printed  >  computed default

    The default for RDD is computed by the reader (PO date + 6 working days),
    so by the time it reaches here `rdd` is either printed or defaulted and the
    note says which. `po_date` has a last resort the reader cannot know: the
    email's received date, which is what column M used before the document was
    read at all. Using it as a FALLBACK keeps a date on the form when a customer
    prints none, and it is only reached when both the box and the PO are empty.
    """
    header, notes = _po_header(results)
    typed_po, typed_rdd = _typed_dates(mail)
    po_date = typed_po or header.get("po_date") or \
        str((mail or {}).get("received_at") or "").strip()
    rdd = typed_rdd or header.get("rdd") or ""
    if typed_po and typed_po != header.get("po_date"):
        notes.append(f"PO date {typed_po} typed for this order "
                     f"(the document printed {header.get('po_date') or 'none'})")
    if typed_rdd and typed_rdd != header.get("rdd"):
        what = ("defaulted to " + str(header.get("rdd"))
                if header.get("rdd_defaulted")
                else "printed " + str(header.get("rdd") or "none"))
        notes.append(f"R.D.D {typed_rdd} typed for this order "
                     f"(the document {what})")
    if not po_date:
        notes.append("no PO date on the document and none typed - column M "
                     "left empty")
    if not rdd:
        notes.append("no R.D.D on the document and none typed - column K left "
                     "empty")
    return po_date, rdd, notes


def _ship_details(source):
    """
    The Ship-To block typed on the order, as {field: value} for write_line.

    `source` is the mail record (Confirm path) or the export payload (Quick
    Convert). Only NON-EMPTY values are returned, so splatting this over the
    PO's values means "typed wins, the document's value stays when the box is
    empty" - which is what the Inbox box promises.

    The two DATES are deliberately not returned here: they are not part of the
    Ship-To block and have their own precedence (including a computed default),
    which `_order_dates()` owns. Returning them here too would pass `po_date`
    to write_line twice.
    """
    try:
        fields = store.TYPED_FIELDS
    except Exception:                              # pragma: no cover
        return {}
    out = {}
    for f in fields:
        if f in store.ORDER_FIELDS:
            continue
        v = str((source or {}).get(f) or "").strip()
        if v:
            out[f] = v
    return out


def _po_ship(fill, results):
    """Overlay the PO's delivery address UNDER the typed values.

    Called before `_ship_details()`, so a typed box always wins. Only the
    address columns are taken (see _PO_SHIP_FIELDS): the Ship-to NAME keeps the
    master's meaning and is used from the document only as a last resort.
    """
    header, notes = _po_header(results, date_notes=False)
    for f in _PO_SHIP_FIELDS:
        if header.get(f) and not fill.get(f):
            fill[f] = header[f]
    return notes


def _note_once(seen, note):
    """Print a note the first time it is seen; keep the list for the caller."""
    if not note:
        return
    if seen is None:
        print(f"  [ERP] {note}")
        return
    if note not in seen:
        seen.append(note)
        print(f"  [ERP] {note}")


def _fill_for(base, order, typed_ship=None, seen=None):
    """ONE order's fill: the party block, then that order's address, then dates.

    `base` already carries the master defaults and whatever was typed on the
    row. This adds what THE ORDER printed - its delivery address and its two
    dates - and returns a NEW dict, so the second order of a multi-PO document
    cannot inherit the first one's street or delivery date. A typed value still
    wins, because `_po_ship()` only fills what is empty.

    Before 2026-10-28 there was one fill per FILE, built once and splatted over
    every row: fine while a file was one order, wrong the moment Curacao stapled
    four into one PDF (every row of all four got the first order's R.D.D).
    """
    fill = dict(base or {})
    for n in _po_ship(fill, [order] if order else []):
        _note_once(seen, n)
    po_date, rdd, date_notes = _order_dates([order] if order else [], typed_ship)
    for n in date_notes:
        _note_once(seen, n)
    if po_date:
        fill["po_date"] = po_date
    if rdd:
        fill["rdd"] = rdd
    return fill


def _order_blocks(results):
    """The orders behind `results`, one block each, in reading order.

    `of_pdf.expand_orders()` normally hands over one result per order, so this
    is one block per result. A result that still carries its own `orders` list
    (a reading that was never expanded) contributes those blocks as they are.
    """
    out = []
    for r in results or []:
        blocks = r.get("orders") or []
        if len(blocks) > 1:
            out.extend(blocks)
        else:
            out.append(r)
    return out


def order_brief(block):
    """One order's header values, without its lines.

    Sent back with every reviewed line so `build_upload_lines()` can give each
    ROW its own address and dates. The page must not be handed the whole
    reading: a 300-line document would go over the wire twice.
    """
    block = block or {}
    keys = ("po_number", "document_total", "po_date", "rdd", "rdd_source",
            "rdd_defaulted", "ship_to_name") + _PO_SHIP_FIELDS
    return {k: block.get(k, "") for k in keys if k in block}


def _order_spread(results):
    """Notes about values that DIFFER between the orders of one document.

    A disagreement used to be reported by `_po_header()` and one value used for
    every row. Now each row carries its own order's value, so nothing is picked
    silently - but a sheet whose rows print two different delivery dates still
    has to say so, or nobody will look at it.
    """
    blocks = _order_blocks(results)
    if len(blocks) < 2:
        return []
    notes = []
    for field, label in (("po_date", "P/O date"), ("rdd", "R.D.D")):
        vals = []
        for b in blocks:
            v = str(b.get(field) or "").strip()
            if v and v not in vals:
                vals.append(v)
        if len(vals) > 1:
            notes.append(f"the {len(blocks)} orders print different {label}s "
                         f"({', '.join(vals[:4])}) - each row carries its own")
    return notes


# What the pre-generation preview shows, and in what order.
#
# DELIBERATELY INCOMPLETE. Two kinds of column are left out:
#
#   * the fixed constants (C Sales Org 3101, E Division 00, BF currency USD) -
#     they are the same on every line and only add noise to a confirmation;
#   * the line columns (H Material, I Quantity, BE Unit price) - they come from
#     the extraction, which has not run yet, and they are reviewed line by line
#     on the Quick Convert card afterwards.
#
# What is left is exactly what a person can still get wrong at this point: the
# two account numbers, the channel they imply, the delivery name and address,
# and the two dates. That is the decision the preview asks for.
_PREVIEW_FIELDS = (
    ("po",               "A",  "P/O No."),
    ("sold_to",          "F",  "Sold To Party"),
    ("ship_to",          "G",  "Ship To Paty"),
    ("distr_channel",    "D",  "Distr. Channel"),
    ("ship_to_name",     "N",  "Ship-to Name"),
    ("ship_to_address",  "R",  "Ship-to Address"),
    ("ship_to_street2",  "S",  "Ship-to Street 2"),
    ("ship_to_street3",  "T",  "Ship-to Street 3"),
    ("ship_to_street4",  "U",  "Ship-to Street 4"),
    ("ship_to_street5",  "V",  "Ship-to Street 5"),
    ("ship_to_zip",      "W",  "Ship-to Postal Code"),
    ("ship_to_city",     "X",  "Ship-to City"),
    ("ship_to_region",   "AZ", "Ship-to Region"),
    ("rdd",              "K",  "R.D.D"),
    ("po_date",          "M",  "P/O Date"),
)

# What the preview says about a value that is not known yet. Phrased as where it
# WILL come from, because "empty" would read as "this will be blank".
_PENDING = {
    "ship_to_address": "read from the PO",
    "ship_to_street2": "read from the PO",
    "ship_to_street3": "read from the PO",
    "ship_to_street4": "read from the PO",
    "ship_to_street5": "read from the PO",
    "ship_to_zip": "read from the PO",
    "ship_to_city": "read from the PO",
    "ship_to_region": "read from the PO",
    "rdd": "read from the PO, else PO date + 6 working days",
    "po_date": "read from the PO, else the email date",
}


def order_preview(mail, settings, typed_ship=None, sold_to="", ship_to="",
                  fmt=FORMAT_FULL, results=None, read_ok=None):
    """What the Order Upload will contain, shown BEFORE the file is written.

    `results` is what the reader got out of the document(s). Pass it: the
    delivery address and the two dates are printed ON the PO, so a preview
    without them would be guessing at exactly the columns it exists to confirm.
    No results (an unreadable attachment) is allowed - those columns then say
    where they WOULD have come from instead of showing a blank.

    What it still never contains: the line values (Material, Quantity, Unit
    price) and the fixed constants. The lines are reviewed on Quick Convert
    after the reading, and a constant is not a decision.

    Precedence is the writer's, exactly: typed on the row > what the PO printed
    > the master / the computed default.

    read_ok: False when the caller TRIED to read and got nothing. It only
    changes the wording of the empty columns ("the document could not be read"
    instead of "will be read"), so the preview never promises a pending step.

    Returns {rows, warnings, channel, pair_found, sold_to, ship_to, format,
             stats}:
      rows: [{field, letter, header, value, source, pending}] in ERP order
      stats: {lines, codes, needs_review} - counts only, no material codes
    """
    mail = dict(mail or {})
    results = results or []
    sold_to = str(sold_to or mail.get("sold_to") or "").strip()
    ship_to = str(ship_to or mail.get("ship_to") or "").strip()

    fill, note = _party_fill(settings, sold_to, ship_to)
    for np in _po_ship(fill, results):
        pass
    fill.update(_ship_details(dict(mail, **(typed_ship or {}))))
    fill["po"] = str(mail.get("po_number") or "").strip()
    po_date, rdd, date_notes = _order_dates(results, typed_ship or {})
    if po_date:
        fill["po_date"] = po_date
    if rdd:
        fill["rdd"] = rdd

    warnings = list(date_notes)
    if note:
        warnings.append(note)
    if not sold_to:
        warnings.append("no Sold-To Party chosen - column F will be empty, and "
                        "the Ship-To master row for the pair cannot be found")
    if not ship_to:
        warnings.append("no Ship-To Party chosen - column G will be empty, and "
                        "column D (the Distribution Channel) cannot be derived")
    if not (fill.get("distr_channel") or "").strip() and sold_to and ship_to:
        warnings.append("this (Sold-To, Ship-To) pair has no TYPE in the "
                        "Ship-To master, so column D stays empty")

    # Real column numbers off the template, so the letter shown is the letter
    # the value will actually land on.
    letters = {}
    try:
        wb, ws = open_template(settings)
        cmap, _ = column_map(ws)
        try:
            from openpyxl.utils import get_column_letter
            letters = {f: get_column_letter(c) for f, c in cmap.items()}
        finally:
            try:
                wb.close()
            except Exception:
                pass
    except Exception as exc:                     # template missing / protected
        warnings.append(f"could not read the ERP template ({exc}) - the "
                        "letters below are the form's usual positions")

    # What the DOCUMENT printed, so a value can say where it came from. Without
    # this every address would be labelled "from the customer master", which is
    # the one thing the address columns are NOT taken from.
    po_vals = _po_header(results, date_notes=False)[0] if results else {}
    po_ship = {f: str(po_vals.get(f) or "").strip() for f in _PO_SHIP_FIELDS}
    rdd_defaulted = bool(po_vals.get("rdd_defaulted"))

    # A document may hold several POs (2026-10-28). Then there is no such thing
    # as "the" P/O date: each row is written with its own order's. A field is
    # shown once only when every order agrees on it - which is the common case
    # for the delivery address (four POs to the same warehouse) and the rare
    # case for the dates.
    blocks = _order_blocks(results)
    multi = len(blocks) > 1
    per_order = ("po_date", "rdd", "ship_to_name") + _PO_SHIP_FIELDS
    shared = {}
    if multi:
        for f in per_order:
            vals = {str(b.get(f) or "").strip() for b in blocks}
            if len(vals) == 1:
                v = vals.pop()
                if v:
                    shared[f] = v

    rows = []
    for field, letter, header in _PREVIEW_FIELDS:
        value = str(fill.get(field) or "").strip()
        if field == "sold_to":
            value = sold_to
        elif field == "ship_to":
            value = ship_to
        typed_val = str((typed_ship or {}).get(field) or "").strip()
        src, pending = "", ""
        if value:
            if typed_val and typed_val == value:
                src = "typed on this row"
            elif field in ("sold_to", "ship_to"):
                src = "picked on this row"
            elif field in po_ship and po_ship.get(field) == value:
                src = "from the PO"
            elif field == "po_date" and po_vals.get("po_date") == value:
                src = "from the PO"
            elif field == "rdd" and rdd_defaulted:
                src = "default: PO date + 6 working days"
            elif field == "rdd" and po_vals.get("rdd") == value:
                src = "from the PO"
            elif field in ("distr_channel", "ship_to_name"):
                src = "from the customer master"
            elif field == "po":
                src = "from the email"
            else:
                src = "from the customer master"
        else:
            pending = _PENDING.get(field, "")
            # "read from the PO" is only true BEFORE the reading. Once the
            # document has been read, an empty column means the document does
            # not print one - saying "will be read from the PO" at that point
            # would promise something that already happened and found nothing.
            if pending and results:
                pending = "not printed on the PO"
                src = "empty"
            elif pending and read_ok is False:
                # The reading was attempted and produced nothing. Saying "will
                # be read from the PO" here would promise a step that has
                # already run and failed.
                pending = "the document could not be read"
                src = "not read"
            else:
                src = "empty" if not pending else "not read yet"
        if multi:
            if field == "po":
                value, src = "", ""
                pending = f"{len(blocks)} POs - listed below"
            elif field in per_order:
                if field in shared:
                    value, src, pending = (shared[field],
                                           f"same on all {len(blocks)} POs", "")
                else:
                    value, src, pending = "", "", "each PO has its own"
        rows.append({"field": field, "letter": letters.get(field, letter),
                     "header": header, "value": value, "source": src,
                     "pending": pending})

    # Counts only. The codes themselves are deliberately NOT returned: the
    # preview is about the order's header, and the line values are reviewed on
    # Quick Convert where they can be corrected.
    codes = [str(r.get("material_code") or "") for res in results
             for r in (res.get("records") or [])]
    stats = {"lines": len(codes),
             "codes": sum(1 for c in codes if c),
             "needs_review": sum(1 for res in results
                                 for r in (res.get("records") or [])
                                 if r.get("needs_review"))}
    order_rows = [{
        "po": str(b.get("po_number") or ""),
        "po_date": str(b.get("po_date") or ""),
        "rdd": str(b.get("rdd") or ""),
        "rdd_defaulted": bool(b.get("rdd_defaulted")),
        "lines": len(b.get("records") or []),
        "total": str(b.get("document_total") or ""),
        "address": str(b.get("ship_to_address") or ""),
        "city": str(b.get("ship_to_city") or ""),
        "zip": str(b.get("ship_to_zip") or ""),
    } for b in blocks]

    if multi:
        # The merged-header notes ("two documents give different R.D.D - X was
        # used") are wrong here: nothing was picked, each row carries its own.
        warnings = [w for w in warnings
                    if not w.startswith("two documents give different")]
        warnings.insert(0,
            f"{len(blocks)} separate POs in one document - every row is written "
            f"with its own P/O No., its own delivery address and its own two "
            f"dates. Still one file per format, {stats['lines']} line(s) in "
            "total.")

    return {"rows": rows, "warnings": warnings,
            "channel": str(fill.get("distr_channel") or ""),
            "pair_found": bool(note == ""),
            "sold_to": sold_to, "ship_to": ship_to,
            # The per-order list the page shows when there is more than one, so
            # the reading is visible as four orders rather than one blob.
            "orders": order_rows if multi else [],
            "format": output_format(fmt), "stats": stats}


def build_upload_lines(lines, settings, tag="QuickConvert", po="",
                       sold_to="", ship_to="", fmt=FORMAT_FULL,
                       ship=None, order=None):
    """Write reviewed lines into the Standard Order Upload template.

    Quick Convert path. Material Code, Quantity and Unit Cost are written for
    every line that has a code; the P/O No. is written as well when the caller
    knows it (`po`, or a `po` on the line), because the ERP marks that column
    mandatory and Quick Convert does have the number on screen. Sales Org /
    Division are the fixed constants; the Distribution Channel follows the
    Ship-To that was picked (`ship_to`, column G), which is written to G, and
    `sold_to` goes to F. Every other column is left as the template has it.
    fmt: "full" (default) for that form, "simple" for the four-column sheet -
      the same lines either way, only the file changes. See build_simple_lines.
    `order` is the header the PO printed ({po_date, rdd, ship_to_address, ...});
      it fills K, M and the address block, and what was typed on the card
      overrides it. None means "nothing was read" - typed values only.
    lines: [{code, qty, cost, po?}]. Returns (path, line count).
    """
    if is_simple(fmt):
        return build_simple_lines(lines, settings, tag, po)
    base = settings.get("_base", "")
    wb, ws = open_template(settings)
    cmap, notes = column_map(ws)
    for n in notes:
        print(f"  [ERP] column {n}")
    # master default -> what was typed on the card. Both are the same for every
    # line; the PO's own address and dates are added per line below, because a
    # dropped file may hold more than one order.
    party, note = _party_fill(settings, sold_to, ship_to)
    if note:
        print(f"  [ERP] {note}")
    party.update(_ship_details(ship))
    seen = []
    # Only built when some line arrives WITHOUT an order of its own (a row the
    # operator added by hand, or an Excel PO). Building it unconditionally also
    # printed "no PO date on the document" over a document that does print one -
    # on every line but the fallback's.
    doc_fill = (_fill_for(party, order, ship, seen)
                if any(not ln.get("order") for ln in lines) else None)
    row = first_empty_row(ws, cmap)
    n = 0
    for ln in lines:
        code = str(ln.get("code") or "").strip()
        if not code:
            continue
        fill = (_fill_for(party, ln.get("order"), ship, seen)
                if ln.get("order") else doc_fill)
        write_line(ws, row, cmap, po=str(ln.get("po") or po or "").strip(),
                   sold_to=sold_to, ship_to=ship_to, code=code,
                   qty=ln.get("qty"), cost=ln.get("cost"), **fill)
        row += 1
        n += 1
    if not n:
        raise RuntimeError("No lines with a Material Code to write.")
    out = output_path(base, "OrderUpload", tag)
    wb.save(out)
    return out, n


def build_simple_lines(lines, settings, tag="QuickConvert", po=""):
    """The Quick Convert lines written as the four-column sheet.

    Same input and same return shape as build_upload_lines, so the caller does
    not have to know which format it asked for.
    """
    base = settings.get("_base", "")
    wb, ws = simple_workbook()
    row, n = 2, 0
    for ln in lines:
        code = str(ln.get("code") or "").strip()
        if not code:
            continue
        write_simple(ws, row, po=str(ln.get("po") or po or "").strip(),
                     code=code, qty=ln.get("qty"), cost=ln.get("cost"))
        row += 1
        n += 1
    if not n:
        raise RuntimeError("No lines with a Material Code to write.")
    out = output_path(base, "OrderUploadSimple", tag)
    wb.save(out)
    return out, n


def build_upload(results, mail, settings, fmt=FORMAT_FULL):
    """results: list of extractor results, mail: {po_number, ship_to, sold_to}
    fmt: "full" (default, the ERP form) or "simple" (the four-column sheet).
    Returns: (output file path, number of lines written, ...)

    Three layers, in this order, for every per-order value:

        typed on the row   >   what the PO printed   >   computed default

    so an operator's box always wins, and the document fills in what nobody
    typed. The address block (R, S-V, W, X, AZ) and both dates (K R.D.D,
    M P/O Date) follow it. Column N keeps the master's meaning - see
    _PO_SHIP_FIELDS.
    """
    if is_simple(fmt):
        return build_simple(results, mail, settings)
    base = settings.get("_base", "")
    wb, ws = open_template(settings)
    # Header stays as in the template; data goes in the first empty row
    cmap, notes = column_map(ws)
    for note in notes:
        print(f"  [ERP] column {note}")
    sold_to = mail.get("sold_to") or ""
    ship_to = mail.get("ship_to") or ""
    # 1. the master's defaults, 2. what was typed on the row. Both are the same
    # for every line, so they are resolved once - see _fill_for() for the third
    # layer, which is per ORDER.
    party, note = _party_fill(settings, sold_to, ship_to)
    if note:
        print(f"  [ERP] {note}")
    party.update(_ship_details(mail))
    seen = []
    row = first_empty_row(ws, cmap)

    orders = _order_blocks(results)
    multi = len(orders) > 1

    # The document-level values, for a line that carries no order of its own.
    # A multi-PO document must NOT report "two documents give different R.D.D -
    # X was used": nothing was picked, each row carries its own, and
    # _order_spread() below says that instead.
    header, doc_notes = _po_header(results)
    for d in (doc_notes if not multi else []):
        _note_once(seen, d)
    doc_fill = dict(party)
    for f in _PO_SHIP_FIELDS:
        if header.get(f) and not doc_fill.get(f):
            doc_fill[f] = header[f]
    po_date, rdd, date_notes = _order_dates(results, mail)
    if multi:
        date_notes = [d for d in date_notes
                      if not d.startswith("two documents give different")]
    for d in date_notes:
        _note_once(seen, d)
    if po_date:
        doc_fill["po_date"] = po_date
    if rdd:
        doc_fill["rdd"] = rdd

    n = 0
    prepared, no_qty, no_cost, dropped_all, fixes = prepare_lines(results, mail)
    # The dates are as visible as any corrected value: a defaulted R.D.D is a
    # guess the operator has to be able to see and change (principle 5 - a
    # silent correction is indistinguishable from a bug). Same channel.
    fixes = list(fixes) + [f"K/M: {d}" for d in date_notes]
    fixes += _order_spread(results)
    held = [ln for ln in prepared if not ln.get("include")]
    for ln in prepared:
        # A line whose code is not in the Material Code list is NOT written
        # here. Confirm has no per-line checkbox, so "not ticked" and "left
        # out" are the same thing - the operator either approves the code on
        # Master Data, or ticks the line in Quick Convert.
        if not ln.get("include"):
            continue
        # Each row's own order: its P/O No. in column A (ln["po"]), its own
        # delivery address and its own two dates. On a single-order document
        # this is the same fill as before, byte for byte.
        fill = (_fill_for(party, ln.get("order"), mail, seen)
                if ln.get("order") else doc_fill)
        write_line(ws, row, cmap, po=ln["po"], sold_to=sold_to,
                   ship_to=ship_to, code=ln["code"],
                   qty=ln["qty"], cost=ln["cost"], **fill)
        row += 1
        n += 1
    if held:
        fixes.append(
            f"{len(held)} line(s) NOT written - their code is not in the "
            "Material Code list: " +
            ", ".join(str(x.get("code") or "?") for x in held[:5]) +
            (" …" if len(held) > 5 else "") +
            ". Approve the code on Master Data, or tick the line in Quick "
            "Convert.")

    out = output_path(base, "OrderUpload", _po_tag(results, mail))
    wb.save(out)
    return out, n, no_qty, no_cost, dropped_all, fixes


def _po_tag(results, mail):
    """The PO number used in the output file name.

    One order -> its number, as before. Several -> the first one plus the count,
    because a file holding four orders named after only one of them is a file
    nobody can find later ("ALRRY-A_and3more").
    """
    clean = lambda v: "".join(ch for ch in str(v or "")
                              if ch.isalnum() or ch in "-_")
    numbers = []
    for r in results or []:
        n = clean(r.get("po_number"))
        if n and n not in numbers:
            numbers.append(n)
    if len(numbers) > 1:
        return numbers[0][:14] + f"_and{len(numbers) - 1}more"
    return (numbers[0] if numbers
            else clean((mail or {}).get("po_number") or "PO"))[:20]


def build_simple(results, mail, settings):
    """The mail/Confirm path written as the four-column sheet.

    Same clean-up, same reconciliation and same return shape as build_upload();
    only the workbook differs, so the caller does not have to know which
    format ran.
    """
    mail = mail or {}
    base = settings.get("_base", "")
    prepared, no_qty, no_cost, dropped, fixes = prepare_lines(results, mail)
    wb, ws = simple_workbook()
    row, n = 2, 0
    held = [ln for ln in prepared if not ln.get("include")]
    for ln in prepared:
        # Unconfirmed code = shown, not written (same rule as build_upload).
        if not ln.get("include"):
            continue
        write_simple(ws, row, po=ln["po"], code=ln["code"],
                     qty=ln["qty"], cost=ln["cost"])
        row += 1
        n += 1
    if held:
        fixes = list(fixes) + [
            f"{len(held)} line(s) NOT written - their code is not in the "
            "Material Code list: " +
            ", ".join(str(x.get("code") or "?") for x in held[:5]) +
            ". Approve the code on Master Data, or tick the line in Quick "
            "Convert."]
    out = output_path(base, "OrderUploadSimple", _po_tag(results, mail))
    wb.save(out)
    return out, n, no_qty, no_cost, dropped, fixes


