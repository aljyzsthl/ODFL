# -*- coding: utf-8 -*-
"""of_master.py

OrderFlow master data: the Material Code master, the upload-file column contract and the master-data export / Ship-To (customer) table.

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
#  SECTION: MATERIAL MASTER - the Material Code master
#  (formerly material_master.py)
# ==========================================================================

# -*- coding: utf-8 -*-
"""material_master.py - Material Code master (codes only)

Extracts only the Material Codes from price list Excels sent by customers and
manages them as a single master. Prices and customer distinctions are not stored.

The Excel contains section rows that indicate the category, like:
    REFRIGERATION - FRENCH DOOR - 3DR      -> Product / Cate1 / Cate2
    Laundry                                -> Product
    LAUNDRY - COMBO                        -> Product / Cate1
When such a row is met, the codes below it are tagged with that category.

**The Product Mapping Table** (the Samsung marketing mapping workbook) is the
other accepted layout, and it carries two things a price sheet does not:

    FULL SKU (A) · short skus (B) · MATERIAL GROUP CODE (C) · MatG (D) · MatG II (E)

- **`short skus` → `FULL SKU`** is a *rewrite table*. A PO prints the short SKU,
  ERP is keyed on the FULL SKU, so a code read as short is normalised to full
  before anything downstream sees it (6.2, `sku_full()` below).
- **`MatG` / `MatG II`** are the grouping columns: they replace Product /
  Type1 / Type2 for this layout, so the codes screen groups by material group.

Storage: config/material_master.json
    {"codes": {normalized_code: {code, product, cate1, cate2, added_at}},
     "sku_map": {normalized_short: {"short": …, "full": …, "groups": …}}}
Each mm_upload adds only new codes; existing codes are kept (no duplicates).
"""
import sys

mm_REL = os.path.join("config", "material_master.json")


def code_rules(base=""):
    """CodeExtract/code_rules.py - what a material code IS and how two
    spellings match.

    ONE set of rules, shared by this master's mm_upload, the Full-code rewrite
    (extractor_bridge) and the extraction engine itself. It is the only part of
    the retired local engine that survived: reading a PO moved to the Claude
    API, deciding whether a code is real did not.
    Looked up next to the app, then next to this source file.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for b in (base, here):
        ce = os.path.join(b or "", "CodeExtract")
        if os.path.isfile(os.path.join(ce, "code_rules.py")):
            if ce not in sys.path:
                sys.path.insert(0, ce)
            import code_rules
            return code_rules
    raise RuntimeError("CodeExtract/code_rules.py not found")

CODE_HEADERS = ("model", "material", "sku", "item", "code", "part")
# Words that disqualify a row as a section row (totals, notes, etc.)
SECTION_STOP = ("total", "subtotal", "note", "page", "effective", "updated",
                "price", "discount", "sheet")

# ──────────────────────────────────────────────
# The Product Mapping Table layout
# ──────────────────────────────────────────────
# Header spellings for the four columns that are read. Compared through
# `_map_head()`, so "FULL SKU", "Full Sku" and "FULL_SKU" all resolve.
# (Not `_norm_head` further down: that one strips separators entirely, which
# would collapse "MATERIAL GROUP 2" and "MATERIALGROUPCODE" onto each other.)
MAP_HEADERS = {
    "full":    ("FULL SKU", "FULL_SKU", "FULLSKU", "FULL SKU CODE"),
    "short":   ("SHORT SKUS", "SHORT_SKUS", "SHORTSKUS", "SHORT SKU",
                "SHORT_SKU", "SHORTSKU", "SHORT SKU CODE"),
    "group":   ("MATERIAL GROUP", "MATERIAL_GROUP", "MATERIALGROUP",
                "MATG", "MATERIAL GROUP CODE"),
    "group2":  ("MATERIAL GROUP 2", "MATERIAL_GROUP_2", "MATERIALGROUP2",
                "MATG II", "MATGII", "MATG 2"),
}


def _map_head(text):
    """A header cell folded for comparison: lowercase, separators to spaces."""
    t = re.sub(r"[^A-Za-z0-9]+", " ", str(text or "").strip().lower())
    return re.sub(r"\s+", " ", t).strip()

# The other half of the import contract: the four headers of the Material
# Codes upload file, and which of them is the code column. DATA_SCHEMAS
# derives the export from this list, so an export can never grow or rename a
# column that the import below would not recognise.
#
# The Material Codes file is the PRODUCT MAPPING TABLE shape: FULL SKU and
# short skus are the mapping's two halves, and MatG / MatG II are the grouping
# that replaces Product / Type1 / Type2 for this layout.
MM_HEADERS = {
    "full": "FULL SKU",
    "short": "short skus",
    "group": "MATERIAL GROUP",
    "group2": "MATERIAL GROUP 2",
}
MM_CAT_HEADER = {"group": "MATERIAL GROUP", "group2": "MATERIAL GROUP 2"}


def contract_ok(name):
    """Whether this module still parses the file DATA_SCHEMAS describes.

    Checked once when the server starts; a mismatch is printed, because it
    means an exported file would no longer import cleanly.
    """
    bad = []
    if name == "materials":
        # The importer is parse_mapping(), which finds its four columns by
        # header text through MAP_HEADERS. An exported file therefore only
        # re-imports if each schema header is one of the spellings that parser
        # looks for - and both halves of the mapping need a column.
        want = dict(MM_HEADERS)                 # key -> header
        known = {_map_head(s) for spellings in MAP_HEADERS.values()
                 for s in spellings}
        for c in DATA_SCHEMAS["materials"]["columns"]:
            if want.get(c["key"]) != c["header"]:
                bad.append(f"{c['key']}: import expects "
                           f"{want.get(c['key'])!r}, schema says "
                           f"{c['header']!r}")
            if _map_head(c["header"]) not in known:
                bad.append(f"{c['header']}: header is not one of "
                           f"MAP_HEADERS — parse_mapping would skip it")
        keys = {c["key"] for c in DATA_SCHEMAS["materials"]["columns"]}
        for key in ("full", "short"):
            if key not in keys:
                bad.append(f"{key}: parse_mapping needs it, the schema has "
                           f"no such column — the mapping could not be read")
        for key, head in MM_CAT_HEADER.items():
            col = next((c for c in DATA_SCHEMAS["materials"]["columns"]
                        if c["key"] == key), None)
            if col and col["header"] != head:
                bad.append(f"{key}: import reads column {head!r}, "
                           f"schema writes {col['header']!r}")
    elif name == "customers":
        # The importer is ship_master.parse_file(), which finds every column by
        # header text (ST_HINTS). An exported file therefore only re-imports if
        # each schema header is one of the spellings the parser looks for - and
        # every field the parser reads needs a column in the schema.
        known = {_hkey(h) for hints in ship_master.ST_HINTS.values()
                 for h in hints}
        cols = DATA_SCHEMAS["customers"]["columns"]
        for c in cols:
            if _hkey(c["header"]) not in known:
                bad.append(f"{c['key']}: header {c['header']!r} is not one of "
                           f"ship_master.ST_HINTS — the importer would skip it")
        keys = {c["key"] for c in cols}
        for key in ship_master.ST_KEYS:
            if key not in keys:
                bad.append(f"{key}: the importer reads it, the schema has no "
                           f"such column")
    elif name == "domains":
        # Same contract against ship_master.dm_parse_file() / DM_HINTS.
        known = {_hkey(h) for hints in ship_master.DM_HINTS.values()
                 for h in hints}
        cols = DATA_SCHEMAS["domains"]["columns"]
        for c in cols:
            if _hkey(c["header"]) not in known:
                bad.append(f"{c['key']}: header {c['header']!r} is not one of "
                           f"ship_master.DM_HINTS — the importer would skip it")
        keys = {c["key"] for c in cols}
        for key in ship_master.DM_KEYS:
            if key not in keys:
                bad.append(f"{key}: the importer reads it, the schema has no "
                           f"such column")
    return bad


def mm_path(settings):
    # Pure path: no makedirs. Callers read far more often than they write, and
    # a failing mkdir is ~2 300x the cost of the stat it is meant to protect.
    # `_write_json()` creates the directory when something is actually saved.
    return os.path.join(settings.get("_base", ""), mm_REL)


def norm(code):
    """Normalize for comparison: uppercase + strip spaces/hyphens/slashes"""
    return re.sub(r"[\s\-/]", "", str(code or "")).upper()


def _read_json(path, default):
    """Read a master JSON file, telling 'missing' apart from 'unreadable'.

    A missing file is the ordinary first-run state, so it yields `default`.

    A file that exists but cannot be parsed is NOT an empty master. It used to
    be reported as one, which is how a single truncated write turned into
    permanent loss: the app came up with no customer table, every stored mail
    lost its customer, and the next save wrote that emptiness back over the
    file.

    So this fails closed and stays failed: the bad bytes are left exactly where
    they are (a copy is taken beside them for safety) and every read keeps
    raising until a deliberate write replaces the file. Moving the file aside
    instead would have "fixed" the first read and left the second one silently
    empty - the same bug, one request later.

    Read with utf-8-sig: PowerShell has saved these files with a BOM before,
    and a BOM makes plain utf-8 raise.
    """
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        keep = f"{path}.corrupt-{datetime.datetime.now():%Y%m%d-%H%M%S}"
        try:
            shutil.copy2(path, keep)
        except OSError:
            keep = "(copy failed - the original is untouched)"
        raise RuntimeError(
            f"{os.path.basename(path)} could not be read ({e}). It was NOT "
            f"treated as empty: an empty master would silently unclassify "
            f"every stored mail and then be saved over the good data. The "
            f"file has been left in place and a copy kept as:\n    {keep}\n"
            f"Restore it from a backup, or upload the master from ERP again "
            f"(which replaces the file and clears this)."
        ) from e


def _ensure_dir(path):
    """Make the directory that will hold `path`. Write paths only.

    `os.makedirs(..., exist_ok=True)` costs ~2.3 ms on the filesystems this
    runs on: the expense is the `mkdir` that FAILS with EEXIST, not the stat
    that follows it (a plain `os.stat` is ~1 us). The `*_path()` helpers below
    used to call it on every READ, and `domain_master()` walks one row of the
    7 000-row pair table per `domain_of()` - four path lookups per row, so
    ~30 000 makedirs of directories that already existed. That alone was 34 s
    of pure syscalls for a screen showing 465 domains.

    So: reads only stat, and the one place that writes creates the directory.
    """
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def _write_json(path, data):
    """Write a master JSON file in one step.

    The old `open(path, "w")` truncated the real file before dumping, so a
    crash, a full disk or a second writer in that window left a half-written
    master behind. Writing a sibling temp file and renaming it over the target
    is atomic on the same volume: a reader sees either the old file or the new
    one, never a partial one.

    This is also the only place that creates the config/ directory - see
    `_ensure_dir()` for why the readers must not.
    """
    _ensure_dir(path)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def mm_load(settings):
    d = _read_json(mm_path(settings), {"codes": {}})
    d.setdefault("codes", {})
    return d


def mm_save(settings, data):
    _write_json(mm_path(settings), data)


def looks_like_code(v):
    """Decide whether a value looks like a model code.

    A code is a 4-40 char token without spaces that satisfies one of:
      - contains a digit                          (RF90F23AECEAA, SKK-8K)
      - contains a hyphen/slash and no lowercase  (HAF-DIN/EXP, SKK-RWG)
    Category names like 'WINE', 'Laundry', 'ACCESSORIES' have neither a separator
    nor digits, so they are not codes. Pure numbers (amounts, quantities) are excluded too.
    """
    s = str(v or "").strip()
    if len(s) < 4 or len(s) > 40 or " " in s:
        return False
    if not re.match(r"^[A-Za-z0-9\-/._]+$", s):
        return False
    if not re.search(r"[A-Za-z]", s):    # no letters means amount/quantity
        return False
    if re.search(r"\d", s):
        return True
    # Code without digits: accepted only if it has a separator and is all uppercase
    return bool(re.search(r"[-/]", s)) and s == s.upper()


def parse_section(text):
    """'REFRIGERATION - FRENCH DOOR - 3DR' -> (product, cate1, cate2)
    None if not a category row"""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s or len(s) > 80:
        return None
    low = s.lower()
    if any(w in low for w in SECTION_STOP):
        return None
    if looks_like_code(s):          # a code itself is not a category row
        return None
    # Exclude rows with almost no letters (digits/symbols only)
    if not re.search(r"[A-Za-z]{3,}", s):
        return None
    # The separator is ' - ' (surrounding spaces required).
    # Hyphens inside names like 'SIDE-BY-SIDE', 'BUILT-IN', 'SLIDE-IN-INDUCTION'
    # must not be split.
    parts = [p.strip() for p in re.split(r"\s+[-–—]\s+", s) if p.strip()]
    if not parts:
        return None
    parts = (parts + ["", ""])[:3]
    return parts[0], parts[1], parts[2]


def _rows_via_excel(path, sheet=None):
    """Read a sheet through the installed Excel.

    Files protected by NASCA DRM cannot be opened directly by Python, but Excel
    is an authorized program and can. Only values are read and the file is not
    saved, so the DRM state is preserved.
    """
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    xl = wb = None
    try:
        xl = win32com.client.DispatchEx("Excel.Application")
        xl.Visible = False
        xl.DisplayAlerts = False
        wb = xl.Workbooks.Open(os.path.abspath(path), UpdateLinks=0,
                               ReadOnly=True)
        ws = None
        if sheet:
            for s in wb.Worksheets:
                if s.Name == sheet:
                    ws = s
                    break
        ws = ws or wb.Worksheets(1)
        used = ws.UsedRange
        vals = used.Value          # 2-D tuple (scalar if a single cell)
        if vals is None:
            return []
        if not isinstance(vals, tuple):
            return [[vals]]
        rows = []
        for r in vals[:20000]:
            rows.append(list(r) if isinstance(r, tuple) else [r])
        return rows
    finally:
        try:
            if wb is not None:
                wb.Close(SaveChanges=False)
        except Exception:
            pass
        try:
            if xl is not None:
                xl.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


def _read_rows(path, sheet=None):
    """Read rows from a price list file.

    Normally read with openpyxl, but DRM-protected or legacy .xls files
    are read through the installed Excel.
    """
    with open(path, "rb") as f:
        head = f.read(8)
    name = os.path.basename(path)

    if head[:2] == b"PK":                       # regular .xlsx / .xlsm
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        try:
            ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.active
            return [list(r) for r in ws.iter_rows(max_row=20000,
                                                  values_only=True)]
        finally:
            wb.close()

    # DRM (<##...) or legacy .xls (OLE2) - hand off to Excel
    drm = head[:2] == b"<#"
    ole = head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    if drm or ole:
        try:
            rows = _rows_via_excel(path, sheet)
        except Exception as e:
            kind = ("protected by NASCA DRM" if drm
                    else "in the old Excel 97-2003 format")
            raise RuntimeError(
                f"'{name}' is {kind}, so it has to be opened through Excel, "
                f"and that failed:\n  {e}\n\n"
                "Make sure Excel is installed and closed, then try again. "
                "You can also open the file in Excel, copy everything into a "
                "new workbook, mm_save it as .xlsx and mm_upload that copy.")
        if not rows:
            raise RuntimeError(f"'{name}' opened in Excel but has no data.")
        return rows

    low = head.lstrip().lower()
    if low.startswith(b"<") or low.startswith(b"{\\rtf"):
        raise RuntimeError(
            f"'{name}' is not a real Excel file - it is a web page or report "
            "saved with an Excel extension.\n\nOpen it in Excel and use "
            "File > Save As > Excel Workbook (*.xlsx), then mm_upload again.")
    raise RuntimeError(
        f"'{name}' is not an Excel workbook.\n\nPlease mm_upload the price "
        "sheet as .xlsx (File > Save As > Excel Workbook in Excel).")


def sheet_names(path):
    """Every worksheet name in a workbook, in tab order.

    Returns [] when the file has no sheets to speak of (a .csv), which callers
    read as "there is exactly one unnamed sheet". Never raises: a workbook that
    cannot be listed is still readable through _read_rows() with sheet=None.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return []

    if head[:2] == b"PK":                       # regular .xlsx / .xlsm
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
            try:
                return list(wb.sheetnames)
            finally:
                wb.close()
        except Exception:
            return []

    # DRM (<##...) or legacy .xls (OLE2) - only Excel itself can list these
    if head[:2] == b"<#" or head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            xl = wb = None
            try:
                xl = win32com.client.DispatchEx("Excel.Application")
                xl.Visible = False
                xl.DisplayAlerts = False
                wb = xl.Workbooks.Open(os.path.abspath(path), UpdateLinks=0,
                                       ReadOnly=True)
                return [s.Name for s in wb.Worksheets]
            finally:
                try:
                    if wb is not None:
                        wb.Close(SaveChanges=False)
                except Exception:
                    pass
                try:
                    if xl is not None:
                        xl.Quit()
                except Exception:
                    pass
                pythoncom.CoUninitialize()
        except Exception:
            return []
    return []


def _norm_head(c):
    """Header text reduced to letters/digits: 'Type 1 (구분)' -> 'type1구분'"""
    return re.sub(r"[^0-9a-z가-힣]", "", str(c or "").lower())


def _category_columns(header):
    """Product / Type1 / Type2 columns in a header row.

    The company master (SamsungCodestructor_*.xlsx) carries the category in
    its own columns (Product | Type1 | Material Code) and fills a value in
    only on the first row of each group. Header spelling varies between
    versions, so the match is loose: 'Product', 'Product Group',
    'Type 1', 'TYPE1(구분)' all count. Returns (product_idx, type1_idx,
    type2_idx); None where a column is absent.
    """
    pi = t1i = t2i = None
    for j, c in enumerate(header or []):
        t = _norm_head(c)
        if not t:
            continue
        if pi is None and (
                t in ("category", "제품", "제품군", "품목")
                or (t.startswith("product") and not any(
                    w in t for w in ("code", "name", "desc", "no")))):
            pi = j
        elif t1i is None and (
                t.startswith(("type1", "cate1", "category1", "유형1", "타입1"))
                or t in ("type", "subtype", "subcategory")):
            t1i = j
        elif t2i is None and t.startswith(
                ("type2", "cate2", "category2", "유형2", "타입2")):
            t2i = j
    return pi, t1i, t2i


def parse_excel(path, code_col=None, sheet=None, product_col=None,
                type1_col=None, info=None):
    """Extract only (code + category) from a code list / price list Excel.

    Two layouts are understood:
      - category COLUMNS (Product / Type1 / Type2), filled in on the first row
        of a group and blank below it - the company master layout
      - category SECTION rows ("REFRIGERATION - FRENCH DOOR - 3DR") above the
        codes they cover - the customer price sheet layout
    Returns: {normalized_code: {code, product, cate1, cate2}}"""
    from openpyxl.utils import column_index_from_string

    rows = _read_rows(path, sheet)

    ci = column_index_from_string(code_col) - 1 if code_col else None
    header_row = 0
    if ci is None:
        # Find the code column from the header
        for idx, row in enumerate(rows[:40]):
            for j, c in enumerate(row):
                t = str(c).strip().lower() if c is not None else ""
                if t and any(k in t for k in CODE_HEADERS):
                    ci, header_row = j, idx + 1
                    break
            if ci is not None:
                break
    if ci is None:
        # Without a header, pick the column with the most codes
        score = {}
        for row in rows[:400]:
            for j, c in enumerate(row):
                if looks_like_code(c):
                    score[j] = score.get(j, 0) + 1
        if not score:
            raise RuntimeError("No model-code column found in this file.")
        ci = max(score, key=score.get)

    from openpyxl.utils import get_column_letter

    # Category columns: typed in by the user, else found by header name.
    # The header search is independent of how the code column was found -
    # typing the code column by hand used to switch it off entirely.
    pi = column_index_from_string(product_col) - 1 if product_col else None
    t1i = column_index_from_string(type1_col) - 1 if type1_col else None
    t2i = None
    cat_row = None
    if pi is None and t1i is None:
        for idx, row in enumerate(rows[:40]):
            cols = tuple(None if i == ci else i
                         for i in _category_columns(row))
            # A Product column is required: a lone "Type" column on a
            # customer price sheet must not switch off its section rows.
            if cols[0] is not None:
                (pi, t1i, t2i), cat_row = cols, idx
                break
    by_column = any(i is not None for i in (pi, t1i, t2i))
    if cat_row is not None:
        header_row = max(header_row, cat_row + 1)

    if info is not None:
        named = [f"{n}={get_column_letter(i + 1)}" for n, i in
                 (("Product", pi), ("Type1", t1i), ("Type2", t2i))
                 if i is not None]
        info["code_column"] = get_column_letter(ci + 1)
        info["category_columns"] = (", ".join(named) if named else
                                    "none found - section rows used")

    def _at(row, i):
        if i is None or i >= len(row) or row[i] in (None, ""):
            return ""
        return str(row[i]).strip()

    out = {}
    product = cate1 = cate2 = ""
    for row in rows[header_row:]:
        if by_column:
            # Fill-down: a blank cell keeps the group above it. A new Product
            # starts a new group, so its Type values are reset first.
            p, a, b = _at(row, pi), _at(row, t1i), _at(row, t2i)
            if p and p != product:
                product, cate1, cate2 = p, "", ""
            if a and a != cate1:
                cate1, cate2 = a, ""
            if b:
                cate2 = b
        if ci >= len(row):
            continue
        cell = row[ci]
        # First check whether this is a section (category) row.
        # Section rows have merged cells and contain no codes. The text may sit in
        # column A or a middle column rather than the code column, so scan the whole row.
        if not by_column and not any(looks_like_code(x) for x in row):
            cand = cell if cell not in (None, "") else None
            if cand is None:
                for x in row:
                    if x not in (None, "") and isinstance(x, str) and x.strip():
                        cand = x
                        break
            if cand is not None:
                sec = parse_section(cand)
                if sec:
                    product, cate1, cate2 = sec
            continue
        if by_column:
            # Company code list: the code column holds only codes, including
            # labelled and service entries ('Model E3-DW', 'Labor REF') and
            # digit-free part codes ('HAFQIN'). The engine's rules read them.
            code = code_rules().clean_code_cell(cell)
            if not code:
                continue
        else:
            if cell is None or not looks_like_code(cell):
                continue
            code = str(cell).strip()
        key = norm(code)
        if key in out:
            continue
        out[key] = {"code": code, "product": product,
                    "cate1": cate1, "cate2": cate2}
    return out


# --------------------------------------------------------------------------
#  The Product Mapping Table: short SKU -> FULL SKU, plus the material groups
# --------------------------------------------------------------------------

def _map_columns(rows, max_scan=20):
    """({field: column index}, header row index) for the mapping table.

    Returns ({}, 0) when the file is not a mapping table, so the caller can
    fall through to the price-sheet parser instead of failing. Both returns
    are two-tuples: the failure path used to hand back three values while the
    success path handed back two, and unpacking it raised ValueError instead
    of the RuntimeError the caller catches.
    """
    for i, row in enumerate(rows[:max_scan]):
        folded = {}
        for j, c in enumerate(row):
            h = _map_head(c)
            if h:
                folded.setdefault(h, j)
        if not folded:
            continue
        cols = {}
        for field, spellings in MAP_HEADERS.items():
            for s in spellings:
                j = folded.get(_map_head(s))
                if j is not None:
                    cols[field] = j
                    break
        # FULL SKU and short skus are both required: that pair IS the mapping.
        # The group columns are optional (a table without them still rewrites).
        if "full" in cols and "short" in cols:
            return cols, i
    return {}, 0


def _pick_full(short, fulls):
    """(full, note) - one FULL SKU for a short SKU that maps to several.

    Returns ("", "") only when there is nothing to choose from.

    The order of preference, and why:

    1. **A market suffix of `/AC` is never chosen.** That variant is not
       sellable on this desk's flows, so picking it produces a code ERP will
       reject or, worse, book against the wrong SKU. It is removed from the
       pool before anything else happens.
    2. **`/AA` wins when it is in the pool.** Manual POs are only ever placed
       on /AA, so it is the correct answer rather than a lucky one -
       `BackboneIndex._put` already makes the same choice for the same reason.
    3. **Otherwise one is picked, and the pick is STABLE per short SKU.** It
       spreads across the candidates (so a family of short SKUs does not all
       collapse onto the first row of the table) but the same short SKU always
       resolves to the same FULL SKU. `random.choice()` would flip the model on
       every re-read of the same PO, which breaks the extraction cache, makes
       two runs over one document disagree, and turns a support question
       ("why did it change?") into an unanswerable one.

    The alternatives are kept on the sku_map entry so the screen can show what
    was passed over - a choice nobody can see is a guess.
    """
    pool = [f for f in (fulls or []) if str(f or "").strip()]
    if not pool:
        return "", ""
    if len(pool) == 1:
        return pool[0], ""

    def suffix(code):
        return str(code).upper().rsplit("/", 1)[-1] if "/" in str(code) else ""

    usable = [f for f in pool if suffix(f) != "AC"]
    dropped = [f for f in pool if suffix(f) == "AC"]
    if not usable:
        # Every candidate is /AC. Picking one would publish a variant this desk
        # does not sell, so the short SKU stays unresolved and a human decides.
        return "", ""
    if len(usable) == 1:
        return usable[0], (
            "only non-/AC candidate" + (" (/AC candidates excluded)" if dropped
                                        else ""))
    aa = next((f for f in usable if suffix(f) == "AA"), None)
    if aa:
        return aa, f"chose /AA from {len(usable)} candidates"
    idx = int(hashlib.md5(norm(short).encode("utf-8")).hexdigest(), 16) % len(usable)
    return usable[idx], f"chose 1 of {len(usable)} candidates"


def parse_mapping(path, sheet=None, info=None):
    """The Product Mapping Table -> (codes, sku_map, conflicts).

    codes:     {normalized FULL SKU: {code, product, cate1, cate2}} where the
               grouping columns are MatG (product) and MatG II (cate1) - the
               codes screen then groups by material group.
    sku_map:   {normalized short: {"short", "full", "group", "group2"}} -
               **only the unambiguous rewrites**. A short SKU that stands for
               more than one FULL SKU is deliberately absent, so `sku_full()`
               can never pick one for it.
    conflicts: {normalized short: {"short", "fulls": [...], "group", "group2"}}
               - the ambiguous ones, listed so the screen can name them and a
               human can resolve them in the workbook.

    Raises when the file is not a mapping table, so `mm_upload` can say so
    rather than silently reading it as a price sheet.
    """
    from openpyxl.utils import get_column_letter

    rows = _read_rows(path, sheet)
    cols, at = _map_columns(rows)
    if not cols:
        raise RuntimeError(
            "This is not a Product Mapping Table: its header row should name "
            "FULL SKU and short skus (the two columns the mapping needs).")

    def _at(row, field):
        j = cols.get(field)
        if j is None or j >= len(row):
            return ""
        v = row[j]
        return "" if v is None else str(v).strip()

    codes = {}
    seen = {}               # normalized short -> {"short", "fulls", groups}
    order = []
    for row in rows[at + 1:]:
        full, short = _at(row, "full"), _at(row, "short")
        if not full:
            continue
        group, group2 = _at(row, "group"), _at(row, "group2")

        # Group notation is unified so 'ref' and 'REF' do not split into two
        # groups on the codes screen (the workbook carries both spellings).
        group = _canon_group(group)
        group2 = _canon_group(group2) or group

        key = norm(full)
        if key not in codes:
            codes[key] = {"code": full, "product": group,
                          "cate1": group2, "cate2": ""}

        if not short:
            continue
        sk = norm(short)
        rec = seen.get(sk)
        if rec is None:
            rec = {"short": short, "fulls": [], "group": group,
                   "group2": group2}
            seen[sk] = rec
            order.append(sk)
        if key not in {norm(f) for f in rec["fulls"]}:
            rec["fulls"].append(full)

    # One short SKU with several FULL SKUs: the desk now wants ONE of them
    # picked rather than the line dropped (2026-10-22). The pick is not free -
    # see `_pick_full()` for why /AC is excluded and why the choice is stable
    # instead of真random.
    sku_map, conflicts = {}, {}
    for sk in order:
        rec = seen[sk]
        picked, note = _pick_full(rec["short"], rec["fulls"])
        if picked:
            sku_map[sk] = {"short": rec["short"], "full": picked,
                           "group": rec["group"], "group2": rec["group2"],
                           "alternatives": [f for f in rec["fulls"]
                                            if f != picked],
                           "pick_note": note}
        else:
            conflicts[sk] = rec

    if not codes:
        raise RuntimeError("The mapping table has a header row but no rows.")

    if info is not None:
        info["code_column"] = get_column_letter(cols["full"] + 1)
        info["category_columns"] = ", ".join(
            f"{n}={get_column_letter(cols[f] + 1)}"
            for n, f in (("MatG", "group"), ("MatG II", "group2"))
            if f in cols) or "none found"
        info["sku_map"] = len(sku_map)
        info["ambiguous"] = len(conflicts)
        # Short SKUs that had several FULL SKUs and now carry a chosen one.
        # Reported separately from `ambiguous` (which is now only the cases
        # with no usable candidate at all), because "we picked" and "we could
        # not pick" are different things for whoever reads the upload summary.
        info["picked"] = sum(1 for v in sku_map.values()
                             if v.get("alternatives"))
    return codes, sku_map, conflicts


_GROUP_CANON = {"ref": "REF"}


def _canon_group(v):
    """One spelling per material group.

    The workbook carries both 'ref' and 'REF' (and the same for other groups),
    which would otherwise show as two groups holding the same products. Only a
    known alias is folded; anything else is upper-cased as-is.
    """
    t = (v or "").strip()
    if not t:
        return ""
    return _GROUP_CANON.get(t.lower(), t.upper())


def sku_map(settings):
    """{normalized short SKU: {"short", "full", "group", "group2"}}.

    The rewrites that are SAFE to apply - a short SKU that stands for several
    FULL SKUs is not here (see `sku_conflicts()`)."""
    return (mm_load(settings).get("sku_map") or {})


def sku_conflicts(settings):
    """{normalized short SKU: {"short", "fulls": [...], ...}} - the ambiguous
    ones, kept so the screen can name them and the export can round-trip them.
    Nothing rewrites from this dict."""
    return (mm_load(settings).get("sku_conflicts") or {})


def sku_full(settings, code):
    """The FULL SKU a short SKU stands for, or "" when it is not a short SKU.

    The authority is the uploaded mapping table, never a string rule: 110 rows
    of the real table have a short SKU that is NOT a prefix of its FULL SKU
    ('RAF18DBB12' -> 'RA-F18DBB12/AA' drops the hyphen, and six rows are
    genuinely different codes), so "strip the suffix" would be wrong often
    enough to matter.

    A short SKU that maps to several FULL SKUs gets ONE of them, chosen by
    `_pick_full()`: /AC is never chosen, /AA wins when present, otherwise a
    stable pick spreads across the candidates. The alternatives stay on the
    sku_map entry (`alternatives`, `pick_note`) so the choice can be shown and
    argued with. Only a short SKU whose candidates are ALL /AC is left alone.
    """
    c = (code or "").strip()
    if not c:
        return ""
    m = sku_map(settings).get(norm(c))
    if not m:
        return ""
    return (m.get("full") or "").strip()


def sku_groups(settings, code):
    """(material group, material group 2) for a code, or ("", "").

    Accepts any of the three spellings a caller may hold:

    - the **short SKU** a PO printed,
    - the **FULL SKU** it was rewritten to (from `sku_map`'s group columns),
    - a code that is only in the code list (a price-sheet upload, or a FULL SKU
      whose short row is not in the map) - then its own `product` / `cate1`,
      which for the mapping layout ARE MatG and MatG II.
    """
    c = (code or "").strip()
    if not c:
        return "", ""
    m = sku_map(settings)
    hit = m.get(norm(c))
    if not hit:
        full = sku_full(settings, c)
        if full:
            hit = m.get(norm(full))
            c = full
    if hit:
        return (hit.get("group") or ""), (hit.get("group2") or "")
    # Not a mapped short SKU: the code's own row carries the groups.
    entry = lookup(settings, c) or {}
    return (entry.get("product") or ""), (entry.get("cate1") or "")


def merge(settings, parsed, sku_map=None, sku_conflicts=None):
    """Add new codes only. Returns: (added, existing, total)

    `sku_map` is the Product Mapping Table's short→FULL rewrite table. When one
    is supplied it REPLACES the stored one: an upload of the mapping table is a
    re-publish of that whole table, and appending would leave yesterday's
    mappings - including deleted SKUs - matchable. It is kept even when the
    mapping lists no new codes, so re-uploading the same file is harmless.

    `sku_conflicts` are the short SKUs that stand for more than one FULL SKU.
    They are stored separately and never used for a rewrite - see
    `parse_mapping()`.
    """
    data = mm_load(settings)
    codes = data["codes"]
    before = len(codes)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    added = 0

    # Unify notation so 'Laundry' and 'LAUNDRY' do not split into different groups
    canon = {}
    for v in codes.values():
        for f in ("product", "cate1", "cate2"):
            t = v.get(f) or ""
            if t:
                canon.setdefault(t.upper(), t)
    for v in parsed.values():
        for f in ("product", "cate1", "cate2"):
            t = v.get(f) or ""
            if t:
                v[f] = canon.setdefault(t.upper(), t)

    for key, v in parsed.items():
        if key in codes:
            # Category is refreshed from the latest price list.
            # (Re-uploading after a parser fix corrects wrong categories)
            cur = codes[key]
            # So is the spelling: "DW80CG4051SR/AA" and "DW80CG4051SRAA" are
            # the same key, and the file uploaded last is the one ERP wants.
            if v.get("code") and cur.get("code") != v["code"]:
                cur["code"] = v["code"]
            if any(v.get(f) for f in ("product", "cate1", "cate2")):
                for f in ("product", "cate1", "cate2"):
                    cur[f] = v.get(f, "")
            continue
        v = dict(v)
        v["added_at"] = now
        codes[key] = v
        added += 1
    if sku_map is not None:
        data["sku_map"] = sku_map
        data["sku_conflicts"] = sku_conflicts or {}
    mm_save(settings, data)
    return added, before, len(codes)


def mm_upload(settings, path, code_col=None, product_col=None, type1_col=None):
    """Rebuild the code list from an uploaded file.

    Two layouts are accepted, and which one a file is follows from its header
    row rather than from a setting:

      - **Product Mapping Table** (`FULL SKU` + `short skus`) — also carries the
        short→FULL rewrite table and the MatG / MatG II grouping, and REPLACES
        the stored mapping.
      - **a price list / code list** — Product / Type1 / Type2 columns or
        category section rows; adds codes only and leaves the mapping alone.
    """
    # The mapping table is detected first: it is a single-sheet workbook whose
    # header names both SKU columns, and reading it as a price sheet would drop
    # the short SKUs and the groups.
    map_info = {}
    try:
        map_codes, sku, conflicts = parse_mapping(path, info=map_info)
    except RuntimeError:
        map_codes, sku, conflicts = None, None, None

    if map_codes is not None:
        added, before, total = merge(settings, map_codes, sku, conflicts)
        sync_to_engine(settings)
        sample = [{"code": v["code"], "product": v.get("product", ""),
                   "cate1": v.get("cate1", ""), "cate2": v.get("cate2", "")}
                  for v in list(map_codes.values())[:5]]
        groups = sorted({v.get("product", "") for v in map_codes.values()
                         if v.get("product")})
        return {"parsed": len(map_codes), "added": added,
                "existing": before, "total": total,
                "sample": sample, "groups": groups[:12],
                "group_count": len(groups),
                "code_column": map_info.get("code_column", ""),
                "category_columns": map_info.get("category_columns", ""),
                "sku_mapped": map_info.get("sku_map", 0),
                "sku_ambiguous": map_info.get("ambiguous", 0),
                "sku_picked": map_info.get("picked", 0),
                "layout": "mapping"}

    # Every sheet is read. A sheet with no code column (a cover page, notes)
    # is skipped; in a one-sheet-per-product workbook the sheet name stands
    # in for a missing Product. The first sheet to list a code wins it.
    info, parsed = {}, {}
    names = sheet_names(path) or [None]
    errors = []
    for sh in names:
        part_info = {}
        try:
            part = parse_excel(path, code_col, sheet=sh,
                               product_col=product_col,
                               type1_col=type1_col, info=part_info)
        except RuntimeError as e:
            errors.append(f"{sh or 'sheet'}: {e}")
            continue
        for k, v in part.items():
            if sh and len(names) > 1 and not v.get("product"):
                v["product"] = sh
            parsed.setdefault(k, v)
        if not info and part:
            info = part_info
    if not parsed:
        raise RuntimeError("No codes found. " + " | ".join(errors))
    added, before, total = merge(settings, parsed)   # after notation is unified
    # Return a sample too so the user can visually verify categories were detected correctly
    sample = [{"code": v["code"], "product": v.get("product", ""),
               "cate1": v.get("cate1", ""), "cate2": v.get("cate2", "")}
              for v in list(parsed.values())[:5]]
    groups = sorted({v.get("product", "") for v in parsed.values() if
                     v.get("product")})
    sync_to_engine(settings)
    return {"parsed": len(parsed), "added": added,
            "existing": before, "total": total,
            "sample": sample, "groups": groups[:12],
            "group_count": len(groups),
            "code_column": info.get("code_column", ""),
            "category_columns": info.get("category_columns", ""),
            "layout": "price list"}


def items(settings):
    """Sorted list of codes"""
    codes = mm_load(settings)["codes"].values()
    return sorted(codes, key=lambda x: (x.get("product", ""),
                                        x.get("cate1", ""),
                                        x.get("code", "")))


def add_one(settings, code, product="", cate1="", cate2=""):
    code = (code or "").strip()
    if not code:
        return False, "Code is empty."
    data = mm_load(settings)
    key = norm(code)
    if key in data["codes"]:
        return False, f"{code} is already in the list."
    data["codes"][key] = {
        "code": code, "product": product.strip(), "cate1": cate1.strip(),
        "cate2": cate2.strip(),
        "added_at": datetime.datetime.now().isoformat(timespec="seconds")}
    mm_save(settings, data)
    sync_to_engine(settings)
    return True, f"{code} added."


def mm_delete(settings, code):
    data = mm_load(settings)
    if data["codes"].pop(norm(code), None) is None:
        return False
    mm_save(settings, data)
    sync_to_engine(settings)
    return True


def lookup(settings_or_data, code):
    """Look up a code in the master (normalized notation comparison)"""
    data = (settings_or_data if isinstance(settings_or_data, dict)
            and "codes" in settings_or_data else None)
    if data is None:
        data = mm_load(settings_or_data)
    return data["codes"].get(norm(code))


def sync_to_engine(settings):
    """Rebuild the extraction engine's reference list from this master.

    CodeExtract/material_codes_reference.csv is a generated MIRROR of the
    Material Code master - never edited by hand, never a second source. It is
    rewritten in full on every change and on every app start, so a deleted or
    cleared code also leaves the engine. (The old sync only ever appended,
    which let the two lists drift apart: removed codes stayed matchable, and
    a code could be spelled one way in the engine and another in the master.)

    When a Product Mapping Table is loaded, **both spellings of a mapped SKU are
    written**: the FULL SKU (what ERP is keyed on) and the short SKU the PO
    actually prints, each carrying the same material group. The engine's
    `BackboneIndex` then confirms a short SKU on sight and resolves it to the
    FULL SKU through `printed_form()`, so a PO line is recognised before the
    short→full rewrite even runs.

    Returns the number of rows written, or -1 when there is no engine folder.
    """
    import csv
    ref = os.path.join(settings.get("_base", ""), "CodeExtract",
                       "material_codes_reference.csv")
    if not os.path.isdir(os.path.dirname(ref)):
        return -1
    rows = [v for v in items(settings) if (v.get("code") or "").strip()]
    smap = sku_map(settings)

    def cat(v):
        return " - ".join([x for x in (v.get("product"), v.get("cate1"),
                                       v.get("cate2")) if x])

    # short SKU -> the code entry it maps to, so the extra rows carry the same
    # group text as their FULL SKU. A short SKU that is itself a listed code is
    # skipped: it already has a row.
    by_norm = {norm(v["code"]): v for v in rows}
    extra = []
    for sk, m in smap.items():
        if sk in by_norm:
            continue
        full = (m.get("full") or "").strip()
        owner = by_norm.get(norm(full))
        if owner is None:
            continue
        extra.append({"code": (m.get("short") or "").strip() or full,
                      "product": owner.get("product", ""),
                      "cate1": owner.get("cate1", ""),
                      "cate2": owner.get("cate2", "")})

    tmp = ref + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["material_code", "description", "category"])
        f.write("# " + "-" * 66 + "\n"
                "# GENERATED from Master Data > Material Codes - do not edit.\n"
                "# Upload, add or mm_delete codes on that screen; this file follows.\n"
                "# " + "-" * 66 + "\n")
        for v in rows + extra:
            w.writerow([v["code"].strip(), "", cat(v)])
    # Replace in one step: the engine never reads a half-written list
    os.replace(tmp, ref)
    return len(rows) + len(extra)


DISMISSED_REL = os.path.join("config", "unknown_dismissed.json")


def dismissed_path(settings):
    # Pure path - see `mm_path()`.
    return os.path.join(settings.get("_base", ""), DISMISSED_REL)


def dismissed_codes(settings):
    """The codes a human has already looked at and dismissed."""
    d = _read_json(dismissed_path(settings), {})
    return set(d.get("codes") or [])


def dismiss_reviews(settings, codes=None):
    """Forget the 'unknown code' entries - all of them, or just `codes`.

    "Clear" does NOT delete the extraction cache and does NOT add anything to
    the Material Code list: the codes are recorded on a DISMISSED list, and
    `pending_reviews()` stops offering them. That distinction matters:

      * the cache is the record of what each PO actually said, and deleting it
        would re-bill an API call and lose the evidence;
      * the list stays the authority, so a dismissed code is still NOT
        publishable - it is simply no longer nagging.

    Returns the number of codes newly dismissed. Idempotent.
    """
    before = dismissed_codes(settings)
    if codes is None:
        target = {r["code"] for r in pending_reviews(settings, include_dismissed=True)
                  if r.get("code")}
    else:
        target = {str(c).strip() for c in codes if str(c or "").strip()}
    kept = before | target
    if kept != before:
        _write_json(dismissed_path(settings),
                    {"codes": sorted(kept),
                     "updated_at": datetime.datetime.now().isoformat(
                         timespec="seconds")})
    return len(kept - before)


def pending_reviews(settings, include_dismissed=False):
    """Code candidates the engine set aside as 'not in the list' during
    extraction, minus any that have since been added to this master.
    Read from the engine's data_cache/*.json review entries, deduped by code.
    (Moved here from the retired code_learning.py: the master is the list
    they are checked against.)

    Codes on `unknown_dismissed.json` are left out unless `include_dismissed`
    is set - that is what the card's Clear button writes. Dismissing is not
    approving: a dismissed code still fails the gate on the next PO.
    """
    import glob
    cache = os.path.join(settings.get("_base", ""), "CodeExtract",
                         "data_cache")
    known = set(mm_load(settings)["codes"])
    skip = set() if include_dismissed else {
        norm(c) for c in dismissed_codes(settings)}
    out = {}
    for p in glob.glob(os.path.join(cache, "*.json")):
        if os.path.basename(p) == "index.json":
            continue
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        for r in data.get("review", []) or []:
            code = (r.get("candidate") or "").strip()
            if not code or norm(code) in known or norm(code) in skip:
                continue
            cur = out.setdefault(code, {
                "code": code, "reason": r.get("reason", ""),
                "context": r.get("context", ""),
                "po_numbers": [], "count": 0,
            })
            cur["count"] += 1
            po = r.get("po_number") or ""
            if po and po not in cur["po_numbers"]:
                cur["po_numbers"].append(po)
    return sorted(out.values(), key=lambda x: -x["count"])


def clear(settings):
    """Empty the master (to clear bad accumulated data and re-mm_upload)"""
    n = len(mm_load(settings)["codes"])
    mm_save(settings, {"codes": {}})
    sync_to_engine(settings)
    return n


def export_csv(settings):
    """Export the master to CSV, in the same shape as the xlsx export.

    Read from DATA_SCHEMAS like every other export, so the CSV, the workbook
    and the upload template cannot disagree about the columns.
    """
    import csv
    outdir = os.path.join(settings.get("_base", ""), *EXPORT_DIR)
    os.makedirs(outdir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(outdir, f"MaterialCodes_{ts}.csv")
    cols = DATA_SCHEMAS["materials"]["columns"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([c["header"] for c in cols])
        for rec in material_records(settings):
            w.writerow([rec.get(c["key"], "") for c in cols])
    return path


# ==========================================================================
#  SECTION: DATA SCHEMA - the upload-file contract, in ONE place
#  Used by BOTH the export feature and the importers, so a column can never
#  exist on one side only. The importers still own the *parsing* (so their
#  behaviour cannot change underneath existing files); everything that
#  describes the file - order, header text, type, enum, required flag - is
#  defined here and nowhere else.
# ==========================================================================

# Column kinds:
#   text    free text, written as a string cell and imported with str()
#   enum    one of COL["values"]; anything else normalises to the default
#   number  written as a number, imported with str() (order numbers are long
#           enough that int/float handling would corrupt their last digits)
KIND_TEXT, KIND_ENUM, KIND_NUMBER = "text", "enum", "number"

# `hint` is not decoration: it is the substring material_master.parse_excel()
# looks for in a header cell to find the code column (CODE_HEADERS). Without it
# an exported file is read back as "no code column".
DATA_SCHEMAS = {
    "materials": {
        "title": "Material Codes",
        "endpoint": "mm_upload",
        "prefix": "MaterialCodes",
        "note": "The Product Mapping Table. One row = one (FULL SKU, short "
                "SKU) pair; a short SKU on a PO is rewritten to its FULL SKU.",
        "columns": [
            {"key": "full", "header": "FULL SKU", "kind": KIND_TEXT,
             "required": True, "hint": "sku", "width": 30,
             "title": "Required. The model code exactly as ERP spells it - "
                      "the spelling an Order Upload row carries."},
            {"key": "short", "header": "short skus", "kind": KIND_TEXT,
             "width": 26,
             "title": "What a PO prints for this model. Read on a PO and "
                      "rewritten to the FULL SKU. Leave blank for a code with "
                      "no separate short form."},
            {"key": "group", "header": "MATERIAL GROUP", "kind": KIND_TEXT,
             "width": 18,
             "title": "Top level of the codes tree. Replaces Product for this "
                      "layout."},
            {"key": "group2", "header": "MATERIAL GROUP 2", "kind": KIND_TEXT,
             "width": 20,
             "title": "Second level of the codes tree (Washer, Dryer, "
                      "ELEC RANGE ...)."},
        ],
    },
    "customers": {
        "title": "Ship To Locations",
        "endpoint": "erp_upload",
        "prefix": "ShipToLocations",
        "note": "Sheet 'Ship To Locations' - the ERP Ship-To master. "
                "One row = one (Sold-To, Ship-To) pair. The DOMAIN lives in "
                "the 'Domains' table, joined by SOLD_TO_NAME at read time.",
        "columns": [
            {"key": "sold_to_code", "header": "SOLD_TO_CODE", "kind": KIND_TEXT,
             "width": 14},
            {"key": "sold_to_name", "header": "SOLD_TO_NAME", "kind": KIND_TEXT,
             "width": 42},
            {"key": "ship_to_code", "header": "SHIP_TO_CODE", "kind": KIND_TEXT,
             "width": 14},
            {"key": "ship_to_name", "header": "SHIP_TO_NAME", "kind": KIND_TEXT,
             "width": 34},
            {"key": "address", "header": "SHIP_TO_ADDRESS", "kind": KIND_TEXT,
             "width": 34},
            {"key": "city", "header": "SHIP_TO_CITY", "kind": KIND_TEXT,
             "width": 18},
            {"key": "zip", "header": "SHIP_TO_ZIPCODE", "kind": KIND_TEXT,
             "width": 14,
             "title": "Text cell: a postal code that starts with 0 has to "
                      "stay text."},
            {"key": "dlv_plant", "header": "DLV_PLANT", "kind": KIND_TEXT,
             "width": 11},
            {"key": "state", "header": "SHIP_TO_ST", "kind": KIND_TEXT,
             "width": 16},
            {"key": "account_manager", "header": "ACCOUNT_MANAGER",
             "kind": KIND_TEXT, "width": 18},
            {"key": "district", "header": "DISTRICT", "kind": KIND_TEXT,
             "width": 18},
            {"key": "region", "header": "REGION", "kind": KIND_TEXT,
             "width": 18},
            {"key": "type", "header": "TYPE", "kind": KIND_TEXT, "width": 12,
             "title": "Column D of the Order Upload: exactly 'Builder' -> 11, "
                      "everything else -> 10."},
            {"key": "sub_type", "header": "SUB_TYPE", "kind": KIND_TEXT,
             "width": 14},
        ],
    },
    "domains": {
        "title": "Domains",
        "endpoint": "domain_upload",
        "prefix": "Domains",
        "note": "Sheet 'Domains' - the customer DOMAIN table. One row = one "
                "customer name; the domain is what mail is matched by. "
                "Joined to 'Ship To Locations' by SOLD_TO_NAME.",
        "columns": [
            {"key": "sold_to_name", "header": "SOLD_TO_NAME", "kind": KIND_TEXT,
             "width": 46,
             "title": "The customer name as the Ship-To master spells it - "
                      "the join key. Spelling differences are tolerated "
                      "(case, punctuation, legal suffix)."},
            {"key": "domain", "header": "DOMAIN", "kind": KIND_TEXT,
             "width": 28,
             "title": "The domain mail is matched by - the customer identity."},
        ],
    },
}


def schema(name):
    """The column contract for one upload file
    ('materials' | 'customers' | 'domains')."""
    s = DATA_SCHEMAS.get(name)
    if not s:
        raise KeyError(f"unknown data schema: {name!r}")
    return s


def schema_headers(name):
    return [c["header"] for c in schema(name)["columns"]]


def norm_enum(col, value):
    """Normalise an enum column the way the importer will read it back.

    An enum column whose reader folds values would rewrite one that is not
    in the enum, so an exported file would not read back as written. Neither
    schema declares an enum column today - the check stays for the next one
    that does.
    """
    vals = col.get("values") or []
    s = str(value or "").strip()
    for v in vals:
        if s.lower() == v.lower():
            return v
    for v in vals:
        if s and v.lower() in s.lower():
            return v
    return col.get("default", "")


def norm_cell(col, value):
    """One cell as the importer will store it."""
    kind = col.get("kind")
    if kind == KIND_ENUM:
        return norm_enum(col, value)
    s = "" if value is None else str(value).strip()
    if s.lower() in ("none", "nan"):
        return ""
    if kind == KIND_NUMBER:
        # pasted out of Excel as 1472521.0 - and _clean() would not fix '1e+06'
        m = re.match(r"^(\d+)\.0+$", s)
        if m:
            return m.group(1)
        if re.match(r"^\d+(\.\d+)?[eE][+-]?\d+$", s):
            try:
                return f"{float(s):.0f}"
            except ValueError:
                return s
    return s


def missing_required(name, row):
    """Headers of the required columns this row leaves empty."""
    return [c["header"] for c in schema(name)["columns"]
            if c.get("required") and not norm_cell(c, row.get(c["key"]))]


# ==========================================================================
#  SECTION: DATA EXPORT - write the master data back out in upload shape
#  The file it produces IS the upload file: same workbook, same sheet name,
#  same headers in the same order, same text/number/enum handling, same
#  required columns. Re-importing it must change nothing.
#
#  There are now THREE schemas - materials, customers (the Ship-To pairs) and
#  domains - because the customer data is two tables. Each export is the twin
#  of its own upload: `export` returns one workbook for one schema.
#
#  Layout notes that are load-bearing:
#   - The data sheet is FIRST and ACTIVE. Both importers read the active sheet
#     only (ship_master.parse_file(), ship_master.dm_parse_file() and
#     material_master.parse_excel()), so a sheet in front of it would be
#     imported instead.
#   - Headers must satisfy the matchers (CODE_HEADERS + _category_columns
#     for materials, ST_HINTS for customers, DM_HINTS for domains), which is
#     what the optional `hint` in DATA_SCHEMAS is for.
#   - Account / channel numbers go in text cells: 3101 and 01 stay strings,
#     and a 7-digit account number cannot lose its last digits to a float.
# ==========================================================================

EXPORT_DIR = ("data", "export")


def export_rows(name, records):
    """Apply the schema to raw records -> one dict per row, importer's view.

    Enum values are folded (Builder/Retail) and numbers are stripped of the
    '.0' Excel adds, so what is written is what the importer will store.
    """
    cols = schema(name)["columns"]
    return [{c["key"]: norm_cell(c, (rec or {}).get(c["key"]))
             for c in cols} for rec in records]


def build_export(name, records, sheet=None):
    """The upload-shaped xlsx as bytes. Raises when there is nothing to write."""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    spec = schema(name)
    cols = spec["columns"]
    rows = export_rows(name, records)
    if not rows:
        raise RuntimeError("There is nothing to export — the list is empty"
                           + (" for the current filter."
                              if spec.get("filtered") else "."))

    wb = Workbook()
    ws = wb.active
    ws.title = sheet or spec["title"]

    head_fill = PatternFill("solid", fgColor="DDEBF7")
    head_font = Font(bold=True, color="1F3864")
    line = Side(style="thin", color="B4C6E7")
    for j, c in enumerate(cols, start=1):
        cell = ws.cell(1, j, c["header"])
        cell.fill, cell.font = head_fill, head_font
        cell.border = Border(bottom=line)
        cell.alignment = Alignment(vertical="center")
        ws.column_dimensions[cell.column_letter].width = c.get("width", 18)
        if c.get("title"):
            cell.comment = None
        # All data cells are text EXCEPT where the importer reads a number.
        # Writing everything as text would be the single most likely way to
        # break a re-import, so the format follows the column kind.
        fmt = "General" if c.get("kind") == KIND_NUMBER else "@"
        for r in range(2, len(rows) + 2):
            ws.cell(r, j).number_format = fmt
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"

    for i, row in enumerate(rows, start=2):
        for j, c in enumerate(cols, start=1):
            v = row.get(c["key"], "")
            if v == "" and not c.get("required") and c.get("kind") != KIND_TEXT:
                continue                      # leave the cell truly empty
            ws.cell(i, j, v if v != "" else None)
        for c in cols:
            if c.get("required") and not row.get(c["key"]):
                ws.cell(i, cols.index(c) + 1).fill = PatternFill(
                    "solid", fgColor="FCE4E4")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_path(settings, name, stamp=None):
    """Where the export lands: data\\export\\<Prefix>_<stamp>.xlsx"""
    outdir = os.path.join(settings.get("_base", ""), *EXPORT_DIR)
    os.makedirs(outdir, exist_ok=True)
    ts = stamp or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(outdir, f"{schema(name)['prefix']}_{ts}.xlsx")


def write_export(settings, name, records, filtered=False):
    """Write the file and return (bytes, filename). Does not touch the disk
    unless the caller asks - the server streams it straight to the browser."""
    spec = dict(schema(name))
    spec["filtered"] = filtered
    DATA_SCHEMAS[name]["filtered"] = filtered
    data = build_export(name, records)
    fn = os.path.basename(export_path(settings, name))
    return data, fn


def export_data(settings, name, scope="all", customers=None, codes=None,
                q=""):
    """(bytes, filename, count) for one export, or raises when empty.

    scope="all"    every record (ignores customers/codes/q)
    scope="filter" only what the list on screen is showing
    """
    filtered = scope == "filter"
    if name == "materials":
        recs = material_records(settings)
        if filtered and codes is not None:
            # The codes screen lists FULL SKUs (`code` on each item), and the
            # export rows are keyed by `full` - match on both spellings so
            # "export what is listed" picks up every row of a selected model,
            # including the ones whose only difference is the short SKU.
            want = {material_master.norm(c) for c in codes if str(c).strip()}
            recs = [r for r in recs
                    if material_master.norm(r["full"]) in want
                    or material_master.norm(r.get("short", "")) in want]
    elif name == "customers":
        recs = customer_records(settings,
                                customers if filtered and customers is not None
                                else None,
                                q if filtered else "")
    elif name == "domains":
        recs = domain_records(settings,
                              customers if filtered and customers is not None
                              else None,
                              q if filtered else "")
    else:
        raise KeyError(f"unknown data schema: {name!r}")
    data, fn = write_export(settings, name, recs, filtered=filtered)
    return data, fn, len(recs)


def material_records(settings):
    """Every code in the master, in the PRODUCT MAPPING TABLE shape.

    The export is the twin of the upload, so the file re-imports through
    `parse_mapping()` with no edits: FULL SKU / short skus / MATERIAL GROUP /
    MATERIAL GROUP 2.

    **One row per (FULL SKU, short SKU) pair**, because that pair IS the
    mapping. A code with no separate short form gets one row with the short
    cell blank - `parse_mapping()` still reads the code from it, so nothing is
    lost and nothing is invented.
    """
    codes = material_master.items(settings)
    smap = material_master.sku_map(settings)
    conflicts = material_master.sku_conflicts(settings)

    # FULL SKU -> [short SKU, ...], so a code can carry several short forms
    # (the workbook has two FULL SKUs with more than one short).
    by_full = {}
    for m in smap.values():
        f = material_master.norm(m.get("full") or "")
        if f:
            by_full.setdefault(f, []).append((m.get("short") or "").strip())

    out, seen_full = [], set()
    for v in codes:
        code = (v.get("code") or "").strip()
        if not code:
            continue
        key = material_master.norm(code)
        seen_full.add(key)
        shorts = by_full.get(key) or [""]
        for s in shorts:
            out.append({"full": code, "short": s,
                        "group": v.get("product", ""),
                        "group2": v.get("cate1", "")})
    # A mapping whose FULL SKU is no longer a listed code is still part of the
    # table (the code may have been deleted by hand): emit it rather than
    # silently dropping the rewrite on the next round trip.
    for m in smap.values():
        f = (m.get("full") or "").strip()
        if not f or material_master.norm(f) in seen_full:
            continue
        seen_full.add(material_master.norm(f))
        out.append({"full": f, "short": (m.get("short") or "").strip(),
                    "group": m.get("group", ""), "group2": m.get("group2", "")})

    # The ambiguous short SKUs, one row per competing FULL SKU. They cannot be
    # rewritten, but they ARE part of the table - exporting them keeps the file
    # a faithful twin, so a re-import re-derives the same ambiguity instead of
    # silently turning one of the candidates into a rule.
    for rec in conflicts.values():
        for f in rec.get("fulls") or []:
            f = (f or "").strip()
            if not f:
                continue
            v = next((c for c in codes
                      if material_master.norm(c.get("code", ""))
                      == material_master.norm(f)), None)
            out.append({"full": f, "short": (rec.get("short") or "").strip(),
                        "group": (v or {}).get("product", rec.get("group", "")),
                        "group2": (v or {}).get("cate1", rec.get("group2", ""))})
    return out


def customer_records(settings, customers=None, q=""):
    """Every row of the Ship-To master, in the shape the importer expects.

    This file IS the upload file - same columns, same order - so the rows come
    straight back out of ship_master. `customers` is a list of DOMAINS and `q`
    is the search box text: together they limit the export to exactly what the
    grid on screen is showing.
    """
    recs = ship_master.rows(settings)
    if customers is not None:
        want = {classifier.norm_domain(c) for c in customers}
        recs = [r for r in recs
                if classifier.norm_domain(
                    ship_master.domain_of(settings, r)) in want]
    if q:
        recs = [r for r in recs if ship_master.matches(r, q)]
    cols = DATA_SCHEMAS["customers"]["columns"]
    return [{c["key"]: ship_master._clean(r.get(c["key"])) for c in cols}
            for r in recs]


def domain_records(settings, customers=None, q=""):
    """Every row of the domain table, in the shape the importer expects.

    The mirror of `customer_records()` for the second table. `customers` is a
    list of DOMAINS and `q` the grid's search box, so "export what is listed"
    and the list itself cannot disagree.
    """
    recs = ship_master.dm_rows(settings)
    if customers is not None:
        want = {classifier.norm_domain(c) for c in customers}
        recs = [r for r in recs
                if classifier.norm_domain(r.get("domain")) in want]
    if q:
        recs = [r for r in recs if ship_master.dm_matches(r, q)]
    cols = DATA_SCHEMAS["domains"]["columns"]
    return [{c["key"]: ship_master._clean(r.get(c["key"])) for c in cols}
            for r in recs]


# ==========================================================================
#  SECTION: SHIP-TO MASTER - the ONE customer table
#  (formerly ship_master.py)
# ==========================================================================

# -*- coding: utf-8 -*-
"""ship_master.py - the Ship-To location master (the pair table)

The customer data used to be ONE flat table with a Domain column inside every
row. It is now TWO tables, because that is how ERP actually ships it, and
because a domain is a property of the *customer*, not of each of its
ship-to sites:

    config/ship_to_master.json   the pairs (the ERP "Ship To Locations"
                                  export) - one row per (Sold-To, Ship-To)
    config/domain_master.json    the domains - one row per customer name,
                                  keyed by SOLD_TO_NAME

**The join is resolved at read time, never baked in at import.** `domain_of()`
resolves a pair's domain, in order: by SOLD_TO_NAME, then by SOLD_TO_CODE
(a name the domain table does not carry can still be owned by a code that is).
Resolving on the way in would freeze a match made against one particular
spelling of a name; either table is meant to be edited by hand afterwards, and
a stale join would silently orphan rows.

Both tables are independently editable from the Customer Master screen: each
has its own grid, its own "+ Add row" / delete / inline edit, its own upload
and its own export. There is no schema coupling between them beyond the name.

Identity is the DOMAIN (classifier.match_customer walks the domain table). One
domain owns many pairs, so the PO screens offer a Sold-To drop-down and, under
it, a Ship-To drop-down. The pair is the composite key the ERP Order Upload
columns are filled from:

    (SOLD_TO_CODE, SHIP_TO_CODE)
        AI  Sold-to Name2         <- sold_to_name
        N   Ship-to Name          <- ship_to_name
        R   Ship-to Address       <- address
        X   Ship-to City          <- city
        W   Ship-to Postal Code   <- zip
        D   Distr. Channel        <- from TYPE: exactly "Builder" -> 11,
                                     anything else -> 10

The pair is NOT unique in the ERP file (many of them repeat). A pair whose rows
disagree about the fields above is a *conflict*: those cells are left EMPTY
and named in the log, never guessed at - the same rule the old Distribution
Channel table used.
"""

st_REL = os.path.join("config", "ship_to_master.json")
dm_REL = os.path.join("config", "domain_master.json")

# The 14 columns of the pair table, in the ERP file's own order (the Domain
# column used to sit here, at position C; it moved to its own table - see
# domain_master.py below).
ST_COLUMNS = (
    ("sold_to_code",    "SOLD_TO_CODE"),
    ("sold_to_name",    "SOLD_TO_NAME"),
    ("ship_to_code",    "SHIP_TO_CODE"),
    ("ship_to_name",    "SHIP_TO_NAME"),
    ("address",         "SHIP_TO_ADDRESS"),
    ("city",            "SHIP_TO_CITY"),
    ("zip",             "SHIP_TO_ZIPCODE"),
    ("dlv_plant",       "DLV_PLANT"),
    ("state",           "SHIP_TO_ST"),
    ("account_manager", "ACCOUNT_MANAGER"),
    ("district",        "DISTRICT"),
    ("region",          "REGION"),
    ("type",            "TYPE"),
    ("sub_type",        "SUB_TYPE"),
)
ST_KEYS = tuple(k for k, _h in ST_COLUMNS)
ST_HEADERS = tuple(h for _k, h in ST_COLUMNS)

# The fields an ERP export reads out of a pair. Two rows of the same pair that
# agree on all of these are simply the source listing it twice; if any differs
# the pair is a conflict.
ST_PAYLOAD = ("sold_to_name", "ship_to_name", "address", "city", "zip", "type")

# Header aliases the uploaded file is recognised by (compared through _hkey(),
# so punctuation, case and the (M)/(O) marker do not matter).
ST_HINTS = {
    "sold_to_code":    ("SOLD_TO_CODE", "SOLD TO CODE", "SOLDTOCODE"),
    "sold_to_name":    ("SOLD_TO_NAME", "SOLD TO NAME"),
    "ship_to_code":    ("SHIP_TO_CODE", "SHIP TO CODE", "SHIPTOCODE"),
    "ship_to_name":    ("SHIP_TO_NAME", "SHIP TO NAME"),
    "address":         ("SHIP_TO_ADDRESS", "SHIP TO ADDRESS"),
    "city":            ("SHIP_TO_CITY", "SHIP TO CITY"),
    "zip":             ("SHIP_TO_ZIPCODE", "SHIP TO ZIPCODE", "POSTAL CODE"),
    "dlv_plant":       ("DLV_PLANT", "DLV PLANT"),
    "state":           ("SHIP_TO_ST", "SHIP TO ST"),
    "account_manager": ("ACCOUNT_MANAGER", "ACCOUNT MANAGER"),
    "district":        ("DISTRICT",),
    "region":          ("REGION",),
    "type":            ("TYPE",),
    "sub_type":        ("SUB_TYPE", "SUB TYPE"),
}

MAX_HEADER_ROWS = 15      # give up looking for the header row after this


def _clean(v):
    """One cell as text, with the noise Excel adds removed."""
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("none", "nan"):
        return ""
    # Account codes pasted out of Excel arrive as 2479684.0
    if re.match(r"^\d+\.0+$", s):
        s = s.split(".", 1)[0]
    elif re.match(r"^\d+(\.\d+)?[eE][+-]?\d+$", s):
        try:
            s = f"{float(s):.0f}"
        except ValueError:
            pass
    return s


def st_path(settings):
    # Pure path - see `mm_path()`. This one is on the hot path of every
    # `domain_of()` call, so a mkdir here is a mkdir per pair-table row.
    return os.path.join(settings.get("_base", ""), st_REL)


def load(settings):
    d = _read_json(st_path(settings),
                   {"uploaded_at": "", "source_file": "", "rows": []})
    d.setdefault("rows", [])
    return d


def save(settings, data):
    _write_json(st_path(settings), data)


def rows(settings):
    """Every row, in file order."""
    return load(settings)["rows"]


def _pair(rec):
    return (_clean(rec.get("sold_to_code")), _clean(rec.get("ship_to_code")))


def _payload(rec):
    return tuple(_clean(rec.get(k)) for k in ST_PAYLOAD)


def index_pairs(records):
    """{(Sold-To, Ship-To): [row, ...]} - a list, because the pair repeats."""
    out = {}
    for r in records or []:
        out.setdefault(_pair(r), []).append(r)
    return out


def conflicts(records):
    """[(sold_to, ship_to, row_count)] - pairs whose rows disagree.

    A pair listed twice with IDENTICAL details is not a conflict; only rows
    that would fill the ERP columns differently are, because then there is no
    honest answer to give.
    """
    out = []
    for (sold, ship), rs in index_pairs(records).items():
        if len(rs) < 2 or (not sold and not ship):
            continue
        first = _payload(rs[0])
        if any(_payload(r) != first for r in rs[1:]):
            out.append((sold, ship, len(rs)))
    return sorted(out)


def site(settings, sold_to, ship_to, pairs=None):
    """(info, conflict) for one composite key.

    `info` is the pair's ERP-facing fields **plus the resolved `domain`**, or
    None when the pair is not in the master at all. `conflict` is True when the
    pair repeats with different details, in which case the caller must leave
    the cells empty.

    The domain is resolved here rather than stored per row, so the two tables
    stay independent - see the section docstring.
    """
    key = (_clean(sold_to), _clean(ship_to))
    if not key[0] and not key[1]:
        return None, False
    if pairs is None:
        pairs = index_pairs(rows(settings))
    hits = pairs.get(key) or []
    if not hits:
        return None, False
    first = hits[0]
    conflict = any(_payload(h) != _payload(first) for h in hits[1:])
    info = {k: _clean(first.get(k)) for k in ST_PAYLOAD}
    info["domain"] = domain_of(settings, first)
    return info, conflict


_STATE_CACHE = {"key": None, "value": []}


def states(settings):
    """The distinct state codes the Ship-To master carries, sorted.

    Feeds the AZ "Ship-to Region" drop-down. Taken from the data rather than a
    hard-coded 50-state list so the codes actually in use are offered - the
    master carries territorial values (PR, VI) that a US-only list would hide -
    and so a typo can never be chosen in the first place.

    Memoised on the master file's mtime: this is called on every dashboard
    render and the table has thousands of rows.

    ⚠️ The memo did not work until 2026-10-28, and silently: the key was built
    with `st_path(settings).stat()`, but `st_path()` returns a STRING, so that
    raised AttributeError, the `except` swallowed it, `key` became None and the
    "if key is not None" guard skipped the cache on every single call. The
    dashboard therefore re-read the 2.8 MB pair file and walked all 7,418 rows
    to produce 52 state codes - ~17 ms per request, 60 s poll included, and
    every 3 s while a collection was running. `_stat_key()` is the helper that
    was written for exactly this; it also treats a MISSING master as the
    cacheable state it is, instead of disabling the memo again.
    """
    p = st_path(settings)
    key = (p, _stat_key(p))     # the folder too - see `_pairs_key()`
    if _STATE_CACHE["key"] == key:
        return _STATE_CACHE["value"]

    seen = set()
    for r in rows(settings):
        s = _clean(r.get("state")).upper()
        # Two letters only. The table carries stray non-codes ('0', blanks and
        # a few free-text entries); offering those in a state drop-down would
        # reinvent the typo it exists to prevent.
        if len(s) == 2 and s.isalpha():
            seen.add(s)
    out = sorted(seen)
    _STATE_CACHE["key"] = key
    _STATE_CACHE["value"] = out
    return out


def channel_for_type(value):
    """Column D: exactly 'Builder' -> 11, everything else -> 10.

    The ERP file also carries Regionals, BBY, Wayfair, Accrual, a 'Builder
    Others' and a literal 'NULL'; all of those are 10.
    """
    return "11" if _clean(value).lower() == "builder" else "10"


_PAIRS_CACHE = {"key": None, "value": {}}


def _pairs_key(settings):
    """Cache key for the grouped-by-domain index: the files AND their location.

    `master_key()` already carries both tables' mtime+size, so any write from
    the browser invalidates this for free. The base directory goes in as well
    because the tests build masters in throwaway folders, and two of those can
    easily end up with identical mtime+size - which would then be served the
    other one's rows.
    """
    return (settings.get("_base", ""),) + tuple(master_key(settings))


def _pairs_by_domain(settings):
    """{normalised domain: [pair row, ...]} - the pair table grouped by domain.

    MEMOISED (2026-10-28). This used to be rebuilt on every call, and every
    call re-read and re-parsed the 2.8 MB pair file: `sold_options()` and
    `ship_options()` each call it once, so ONE `/api/party_options` request
    parsed that file twice and walked all 7,418 rows twice - about 75 ms of
    CPU per customer, serialised behind the GIL while the Inbox waited for its
    Sold-To / Ship-To drop-downs. The index is a pure function of the two
    master files, so it is built once and kept until either of them changes.

    Returns the cached dict itself, not a copy - callers only read it (the
    option builders append to lists they create, never to these rows).
    """
    key = _pairs_key(settings)
    if _PAIRS_CACHE["key"] == key:
        return _PAIRS_CACHE["value"]
    out = {}
    for r in rows(settings):
        d = classifier.norm_domain(domain_of(settings, r))
        if d:
            out.setdefault(d, []).append(r)
    _PAIRS_CACHE["key"] = key
    _PAIRS_CACHE["value"] = out
    return out


def sold_options(settings, domain):
    """The Sold-To codes a domain owns, for the PO screen's first drop-down."""
    d = classifier.norm_domain(domain)
    seen, out = set(), []
    for r in _pairs_by_domain(settings).get(d, []):
        c = _clean(r.get("sold_to_code"))
        if not c or c in seen:
            continue
        seen.add(c)
        out.append({"code": c, "name": _clean(r.get("sold_to_name")),
                    "type": _clean(r.get("type")),
                    "channel": channel_for_type(r.get("type"))})
    out.sort(key=lambda x: (x["name"], x["code"]))
    return out


def ship_options(settings, domain, sold_to=""):
    """The Ship-To sites under a Sold-To, for the second drop-down.

    Filtered by the chosen Sold-To because the two together are the key the
    ERP columns are filled from.
    """
    d = classifier.norm_domain(domain)
    want = _clean(sold_to)
    seen, out = set(), []
    for r in _pairs_by_domain(settings).get(d, []):
        sold = _clean(r.get("sold_to_code"))
        if want and sold != want:
            continue
        c = _clean(r.get("ship_to_code"))
        k = (sold, c)
        if not c or k in seen:
            continue
        seen.add(k)
        out.append({"code": c, "sold_to": sold,
                    "name": _clean(r.get("ship_to_name")),
                    "address": _clean(r.get("address")),
                    "city": _clean(r.get("city")),
                    "zip": _clean(r.get("zip")),
                    "type": _clean(r.get("type")),
                    "channel": channel_for_type(r.get("type"))})
    out.sort(key=lambda x: (x["sold_to"], x["code"]))
    return out


# --------------------------------------------------------------------------
#  Reading the uploaded file
# --------------------------------------------------------------------------

def _find_columns(row):
    """{field: column index} read off one row of the uploaded file."""
    keys = {}
    for j, cell in enumerate(row):
        k = _hkey(cell)
        if k and k not in keys:
            keys[k] = j
    out = {}
    for field, hints in ST_HINTS.items():
        for h in hints:
            j = keys.get(_hkey(h))
            if j is not None:
                out[field] = j
                break
    return out


def _header_and_cols(raw):
    """(columns, header row index, how many fields were recognised)."""
    best, best_hits, best_at = {}, 0, 0
    for i, row in enumerate(raw[:MAX_HEADER_ROWS]):
        if not any(str(c or "").strip() for c in row):
            continue
        cols = _find_columns(row)
        if len(cols) > best_hits:
            best, best_hits, best_at = cols, len(cols), i
    return best, best_at, best_hits


def parse_file(path):
    """The uploaded Ship-To master -> [row dicts]. Raises when it is not one."""
    raw = material_master._read_rows(path)
    if not raw:
        raise RuntimeError("The file has no rows.")
    cols, at, hits = _header_and_cols(raw)
    if hits < 3:
        raise RuntimeError(
            "This does not look like the Ship-To location master: its header "
            "row should name at least " + ", ".join(ST_HEADERS[:3]) +
            f" (only {hits} known column(s) were found).")
    out = []
    for row in raw[at + 1:]:
        def get(field):
            j = cols.get(field)
            return _clean(row[j]) if j is not None and j < len(row) else ""
        rec = {k: get(k) for k in ST_KEYS}
        if not any(rec.get(k) for k in ("sold_to_code", "ship_to_code",
                                        "sold_to_name")):
            continue
        out.append(rec)
    if not out:
        raise RuntimeError("The file has a header row but no data rows.")
    return out


def upload(settings, path, filename=""):
    """Rebuild the pair table from an uploaded file. The table is REPLACED.

    Only the pair table is touched: the domain table is a separate upload (the
    ERP file's second sheet). An upload of one must not silently drop the
    other's rows - that is how a customer would lose its identity.
    """
    recs = parse_file(path)
    data = {
        "uploaded_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_file": filename or os.path.basename(path),
        "rows": recs,
    }
    save(settings, data)
    doms = {classifier.norm_domain(domain_of(settings, r)) for r in recs}
    doms.discard("")
    types = {}
    for r in recs:
        t = _clean(r.get("type")) or "(blank)"
        types[t] = types.get(t, 0) + 1
    conf = conflicts(recs)
    return {
        "rows": len(recs), "domains": len(doms),
        "sold_tos": len({_clean(r.get("sold_to_code")) for r in recs} - {""}),
        "ship_tos": len({_clean(r.get("ship_to_code")) for r in recs} - {""}),
        "types": types,
        "conflict_count": len(conf),
        "conflicts": [{"sold_to": a, "ship_to": b, "rows": n}
                      for a, b, n in conf[:8]],
        "file": data["source_file"],
    }


# --------------------------------------------------------------------------
#  Editing the master by hand (the Customer Master table)
# --------------------------------------------------------------------------

def st_clear(settings):
    """Empty the master. Returns how many rows went.

    Named `st_clear`, not `clear`: this file is a concatenation, and
    material_master already owns a module-level `clear` whose facade binds that
    very global name - a second `def clear` would silently take it over.
    """
    n = len(rows(settings))
    save(settings, {"uploaded_at": "", "source_file": "", "rows": []})
    return n


def add_row(settings, row=None, blank=False):
    """Append one row. Returns its index.

    `blank` is the grid's "+ Add row": an empty row is exactly what the user is
    about to type into. A programmatic add still has to name something, so a
    call that fills nothing but also does not ask for a blank row is refused.
    """
    data = load(settings)
    rec = {k: _clean((row or {}).get(k)) for k in ST_KEYS}
    if not blank and not any(rec.get(k) for k in
                             ("sold_to_code", "ship_to_code", "domain")):
        raise ValueError("A row needs at least a Sold-To code, a Ship-To code "
                         "or a Domain Name.")
    data["rows"].append(rec)
    save(settings, data)
    return len(data["rows"]) - 1


def delete_row(settings, at):
    """Delete one row by its position in the master."""
    data = load(settings)
    try:
        i = int(at)
    except (TypeError, ValueError):
        return False
    if not 0 <= i < len(data["rows"]):
        return False
    data["rows"].pop(i)
    save(settings, data)
    return True


def set_cell(settings, at, key, value):
    """Set one cell of one row (the table's inline edit)."""
    if key not in ST_KEYS:
        return False
    data = load(settings)
    try:
        i = int(at)
    except (TypeError, ValueError):
        return False
    if not 0 <= i < len(data["rows"]):
        return False
    data["rows"][i][key] = _clean(value)
    save(settings, data)
    return True


def matches(rec, q):
    """Whether one row answers a search box query.

    The same test the on-screen grid uses, so "export what is listed" and the
    list itself can never disagree: the domain, the Sold-To code/name and the
    Ship-To code/name are all searched.
    """
    q = (q or "").strip().lower()
    if not q:
        return True
    hay = " ".join(_clean(rec.get(k)).lower() for k in
                   ("sold_to_code", "sold_to_name",
                    "ship_to_code", "ship_to_name"))
    return q in hay


def page(settings, q="", limit=300, offset=0):
    """A window of the master for the Customer Master table.

    `q` matches the domain, the Sold-To code/name or the Ship-To code/name.
    Returns (rows, total matched); each row carries `_i`, its position in the
    stored table, which is what the edit / delete calls address it by.
    """
    out, total = [], 0
    for i, r in enumerate(rows(settings)):
        if not matches(r, q):
            continue
        total += 1
        if total <= offset:
            continue
        if len(out) < limit:
            r2 = {k: _clean(r.get(k)) for k in ST_KEYS}
            r2["_i"] = i
            out.append(r2)
    return out, total


def status(settings):
    """Headline numbers for the dashboard."""
    d = load(settings)
    recs = d.get("rows") or []
    return {"total": len(recs), "domains": len(dm_count(settings)),
            "sold_tos": len({_clean(r.get("sold_to_code")) for r in recs} - {""}),
            "ship_tos": len({_clean(r.get("ship_to_code")) for r in recs} - {""}),
            "uploaded_at": d.get("uploaded_at", ""),
            "source_file": d.get("source_file", ""),
            "conflict_count": len(conflicts(recs))}


def domain_master(settings):
    """The classifier's master: one entry per DOMAIN, in first-seen order.

    The domain IS the customer identity, so this is what match_customer()
    walks. `sold_to_list` / `ship_to_list` are the union of the domain's pairs
    and are shown on the customer card; `role` is display-only now that column
    D follows each row's own TYPE.

    Order comes from the domain table when it has one, so the list on screen
    matches the order the domains were uploaded in; domains that only the pair
    table knows about are appended.
    """
    groups, order = {}, []

    def group(d):
        g = groups.get(d)
        if g is None:
            g = {"customer": d, "domains": [d], "role": "", "sold_to_list": [],
                 "ship_to_list": [], "po_regex": "",
                 "builder": False, "other": False}
            groups[d] = g
            order.append(d)
        return g

    for rec in dm_rows(settings):
        d = classifier.norm_domain(rec.get("domain"))
        if d:
            group(d)
    for r in rows(settings):
        d = classifier.norm_domain(domain_of(settings, r))
        if not d:
            continue
        g = group(d)
        for key, col in (("sold_to_list", "sold_to_code"),
                         ("ship_to_list", "ship_to_code")):
            v = _clean(r.get(col))
            if v and v not in g[key]:
                g[key].append(v)
        if _clean(r.get("type")).lower() == "builder":
            g["builder"] = True
        else:
            g["other"] = True
    out = []
    for d in order:
        g = groups[d]
        # Builder only when EVERY row of the domain is Builder; this label is
        # for the screen, the ERP column reads each row's own TYPE.
        g["role"] = "Builder" if (g.pop("builder") and not g["other"]) else "Retail"
        g.pop("other", None)
        out.append(g)
    return out


# --------------------------------------------------------------------------
#  The DOMAIN table - the second half of the customer data
# --------------------------------------------------------------------------
#  This is the ERP file's second sheet: SOLD_TO_NAME -> DOMAIN. It is its own
#  table, with its own grid, upload and export, because a domain belongs to
#  the customer and not to each of its ship-to sites - and because a row that
#  is edited by hand must not have to be re-derived from the other table.

DM_COLUMNS = (
    ("sold_to_name", "SOLD_TO_NAME"),
    ("domain",       "DOMAIN"),
)
DM_KEYS = tuple(k for k, _h in DM_COLUMNS)
DM_HEADERS = tuple(h for _k, h in DM_COLUMNS)

# Alias spellings, matched through _hkey(). "Domain Name" is what this app has
# always called the column, so an older single-table export still imports.
DM_HINTS = {
    "sold_to_name": ("SOLD_TO_NAME", "SOLD TO NAME", "SOLDTO NAME", "CUSTOMER",
                     "CUSTOMER NAME", "SOLD TO"),
    "domain":       ("DOMAIN", "DOMAIN NAME", "EMAIL DOMAIN", "E-MAIL DOMAIN"),
}


def dm_path(settings):
    # Pure path - see `mm_path()`.
    return os.path.join(settings.get("_base", ""), dm_REL)


def dm_load(settings):
    d = _read_json(dm_path(settings),
                   {"uploaded_at": "", "source_file": "", "rows": []})
    d.setdefault("rows", [])
    return d


def dm_save(settings, data):
    _write_json(dm_path(settings), data)


def dm_rows(settings):
    """Every domain row, in file order."""
    return dm_load(settings)["rows"]


def dm_count(settings):
    """The distinct normalised domains the table names."""
    out = set()
    for r in dm_rows(settings):
        d = classifier.norm_domain(r.get("domain"))
        if d:
            out.add(d)
    return out


def dm_parse_file(path):
    """The uploaded domain sheet -> [row dicts]. Raises when it is not one."""
    raw = material_master._read_rows(path)
    if not raw:
        raise RuntimeError("The file has no rows.")
    best, best_hits, best_at = {}, 0, 0
    for i, row in enumerate(raw[:MAX_HEADER_ROWS]):
        if not any(str(c or "").strip() for c in row):
            continue
        keys = {}
        for j, cell in enumerate(row):
            k = _hkey(cell)
            if k and k not in keys:
                keys[k] = j
        cols = {}
        for field, hints in DM_HINTS.items():
            for h in hints:
                j = keys.get(_hkey(h))
                if j is not None:
                    cols[field] = j
                    break
        if len(cols) > best_hits:
            best, best_hits, best_at = cols, len(cols), i
    if best_hits < 2:
        raise RuntimeError(
            "This does not look like the domain table: its header row should "
            "name a customer column and a domain column (only "
            f"{best_hits} known column(s) were found).")
    out = []
    for row in raw[best_at + 1:]:
        def get(field):
            j = best.get(field)
            return _clean(row[j]) if j is not None and j < len(row) else ""
        rec = {k: get(k) for k in DM_KEYS}
        if not any(rec.get(k) for k in DM_KEYS):
            continue
        out.append(rec)
    if not out:
        raise RuntimeError("The file has a header row but no data rows.")
    return out


def dm_upload(settings, path, filename=""):
    """Rebuild the domain table from an uploaded file. The table is REPLACED."""
    recs = dm_parse_file(path)
    data = {
        "uploaded_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_file": filename or os.path.basename(path),
        "rows": recs,
    }
    dm_save(settings, data)
    named = {_norm_name(r.get("sold_to_name")) for r in recs}
    named.discard("")
    pairs = {_norm_name(r.get("sold_to_name")) for r in rows(settings)}
    pairs.discard("")
    return {
        "rows": len(recs), "domains": len(dm_count(settings)),
        "named": len(named),
        # Names the pair table carries but this table does not: those pairs
        # are unowned until someone adds a row or a shared Sold-To code
        # resolves them. Reported, because it is the one way this table can
        # quietly lose a customer.
        "unmatched_names": len(pairs - named),
        "file": data["source_file"],
    }


def _norm_name(v):
    """A SOLD_TO_NAME reduced to something two spellings can share.

    The ERP export and the domain sheet are two different files, and the same
    customer is spelled differently in them more often than not. Case,
    surrounding space, punctuation and the legal suffix are all dropped, so
    '1847 GOEDEKER, INC.' and '1847 Goedeker Inc' are one key.
    """
    s = _clean(v).upper()
    if not s:
        return ""
    s = re.sub(r"[^A-Z0-9]+", " ", s).strip()
    s = re.sub(r"\b(?:INC|LLC|LTD|CO|CORP|CORPORATION|COMPANY|LLP|LP|"
               r"DBA|D\s?B\s?A|THE)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_DM_CACHE = {"key": None, "by_name": {}, "by_code": {}, "by_exact": {}}


def _stat_key(path):
    """(mtime_ns, size) for the cache key, or None when the file is absent.

    A MISSING file is a cacheable state, not a reason to skip the cache.
    Building the key from a stat that RAISED used to set it to None, which
    disabled caching entirely - and this is on the path of every row of every
    drop-down, over a 3 MB pair file, so the whole dashboard crawled until the
    domain table was written for the first time.
    """
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def master_key(settings):
    """The change signal for the CUSTOMER DATA as a whole: both tables.

    (mtime_ns, size) of the pair table and of the domain table. Either file
    changes what a domain owns: the pair table says which (Sold-To, Ship-To)
    codes exist, the domain table says which customer name owns which domain -
    and `domain_of()` needs both to answer.

    ⚠️ The server's identity-list cache used to watch the PAIR table only, so a
    row added to the DOMAIN table was invisible until a restart: the Inbox kept
    drawing the old list, and a domain that had just been given a customer name
    still offered no Sold-To / Ship-To at all (2026-10-27). Anything that
    memoises `domain_master()` must key on this, not on `st_path()`.
    """
    return tuple(_stat_key(p) for p in (st_path(settings), dm_path(settings)))


def _dm_build(settings, key):
    """Rebuild the whole domain index for `key` in one pass over both tables."""
    global _DM_CACHE
    by_name, by_exact, by_code = {}, {}, {}
    for r in dm_rows(settings):
        d = classifier.norm_domain(r.get("domain"))
        if not d:
            continue
        nm = _norm_name(r.get("sold_to_name"))
        if nm:
            # First row wins a name. A name listed twice with different
            # domains is a conflict in the source; picking either one would be
            # a guess, so the first is used and the row stays visible in the
            # grid for a human to fix.
            by_name.setdefault(nm, d)
        # The name EXACTLY as it is stored, too. Two customers can share a
        # normalised name while spelling theirs differently - 'BILL SMITH' and
        # 'BILL SMITH INC.' are two accounts with two domains, and collapsing
        # them would hand one of them the other's domain. Exact spelling is
        # therefore tried first, before the normalised key.
        raw = _clean(r.get("sold_to_name"))
        if raw:
            by_exact.setdefault(raw.upper(), d)
    for r in rows(settings):
        nm = _norm_name(r.get("sold_to_name"))
        code = _clean(r.get("sold_to_code"))
        d = by_name.get(nm) if nm else ""
        if d and code:
            by_code.setdefault(code, d)
    _DM_CACHE = {"key": key, "by_name": by_name, "by_code": by_code,
                 "by_exact": by_exact}


def _dm_cached(settings):
    """The whole index for the files as they are right now.

    ONE stat pair per call, and the same dict serves all three maps. The three
    public accessors below used to stat on their own, so `domain_of()` - which
    wants two of them - paid four stats and two cache checks per pair-table
    row, and `domain_master()` walks every row.
    """
    key = master_key(settings)
    if _DM_CACHE["key"] != key:
        _dm_build(settings, key)
    return _DM_CACHE


def dm_index(settings):
    """(by normalised name, by Sold-To code) -> normalised domain.

    Built once per process and invalidated by the two files' mtime+size, the
    same way `_master()` does it: this is on the path of every row of every
    drop-down, and the pair table has thousands of rows.
    """
    c = _dm_cached(settings)
    return c["by_name"], c["by_code"]


def dm_exact(settings):
    """{UPPERCASE SOLD_TO_NAME -> domain}, straight from the domain table.

    No normalising at all, so a name the two tables spell identically resolves
    to the domain uploaded against that spelling. Part of the same cache as
    `dm_index()` - it costs nothing extra to keep.
    """
    return _dm_cached(settings)["by_exact"]


def domain_of(settings, pair):
    """The domain that owns one pair row, or "" when nothing does.

    Resolution order, and why it is this way round:

    1. **SOLD_TO_NAME, exactly as spelled.** The domain sheet is keyed by it,
       so a name the two tables spell identically gets the domain uploaded
       against that spelling. This is tried FIRST because two customers can
       share a normalised name while spelling theirs differently - 'BILL SMITH'
       and 'BILL SMITH INC.' are two accounts with two domains, and collapsing
       them would hand one of them the other's.
    2. **SOLD_TO_NAME, normalised.** Case, punctuation and the legal suffix are
       ignored, so '1847 GOEDEKER, INC.' matches '1847 Goedeker Inc' - the two
       source files spell the same customer differently far more often than not.
    3. **SOLD_TO_CODE.** A name the domain table does not carry can still be
       owned by a code that does. Only a fallback, because one code can carry
       several names and a code-first match would hand the wrong domain to a
       name that has its own entry.
    """
    # One lookup serves all three passes below. `domain_master()` calls this
    # once per row of the pair table (7 000+), so this must stay one stat pair
    # and no rebuild when nothing changed.
    c = _dm_cached(settings)
    raw = _clean(pair.get("sold_to_name"))
    if raw:
        d = c["by_exact"].get(raw.upper())
        if d:
            return d
    nm = _norm_name(raw)
    if nm:
        d = c["by_name"].get(nm)
        if d:
            return d
    code = _clean(pair.get("sold_to_code"))
    return c["by_code"].get(code, "") if code else ""


def dm_add(settings, row=None, blank=False):
    """Append one domain row. Returns its index.

    `blank` is the grid's "+ Add row". A row that names nothing at all is only
    accepted when it is blank - the user is about to type into it.
    """
    data = dm_load(settings)
    rec = {k: _clean((row or {}).get(k)) for k in DM_KEYS}
    if not blank and not any(rec.get(k) for k in DM_KEYS):
        raise ValueError("A domain row needs a customer name or a domain.")
    data["rows"].append(rec)
    dm_save(settings, data)
    return len(data["rows"]) - 1


def dm_delete_row(settings, at):
    data = dm_load(settings)
    try:
        i = int(at)
    except (TypeError, ValueError):
        return False
    if not 0 <= i < len(data["rows"]):
        return False
    data["rows"].pop(i)
    dm_save(settings, data)
    return True


def dm_set_cell(settings, at, key, value):
    """Set one cell of one domain row (the table's inline edit)."""
    if key not in DM_KEYS:
        return False
    data = dm_load(settings)
    try:
        i = int(at)
    except (TypeError, ValueError):
        return False
    if not 0 <= i < len(data["rows"]):
        return False
    data["rows"][i][key] = _clean(value)
    dm_save(settings, data)
    return True


def dm_matches(rec, q):
    """Whether one domain row answers a search box query."""
    q = (q or "").strip().lower()
    if not q:
        return True
    hay = " ".join(_clean(rec.get(k)).lower() for k in DM_KEYS)
    return q in hay


def dm_page(settings, q="", limit=300, offset=0):
    """A window of the domain table for its grid. (rows, total matched)."""
    out, total = [], 0
    for i, r in enumerate(dm_rows(settings)):
        if not dm_matches(r, q):
            continue
        total += 1
        if total <= offset:
            continue
        if len(out) < limit:
            r2 = {k: _clean(r.get(k)) for k in DM_KEYS}
            r2["_i"] = i
            out.append(r2)
    return out, total


def dm_clear(settings):
    """Empty the domain table. Returns how many rows went."""
    n = len(dm_rows(settings))
    dm_save(settings, {"uploaded_at": "", "source_file": "", "rows": []})
    return n


