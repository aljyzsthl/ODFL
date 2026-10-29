# -*- coding: utf-8 -*-
"""OrderFlow - PO processing tool for the Samsung home-appliance
Order Desk. This is the entry point.

Run:  python src\\orderflow.py   (or run_dashboard.bat)

The implementation lives in the of_*.py sibling modules, split out
of this former single file at its SECTION boundaries:

    of_core.py      store, classifier, dedup, text records
    of_outlook.py   collector, housekeeping, win focus, scheduler
    of_master.py    material master, data schema, data export
    of_erp.py       ERP upload builder
    of_pdf.py       pdf access, quick convert, extractor bridge
    of_server.py    dashboard HTTP server

orderflow.py keeps every name the merged file used to export: it
imports the modules, re-publishes their globals into one namespace
(same concatenation order as before), builds the facade objects
(store, collector, ...) exactly as it always did, and late-binds
sibling facade names into each module.
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
#  SECTION: MAIN - entry point
#  (formerly main.py)
# ==========================================================================

# -*- coding: utf-8 -*-
"""main.py - pipeline entry point
Usage:
    python src\\main.py                collect -> classify -> run dashboard server
    python src\\main.py --collect-only collect/classify only, then exit
    python src\\main.py --serve-only   run dashboard only, no collection
"""
import sys

sys.stdout.reconfigure(errors="replace")


if getattr(sys, "frozen", False):
    # PyInstaller executable: the folder containing the exe is the root (config/, data/, etc.)
    BASE = os.path.dirname(sys.executable)
else:
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _merge_settings(base, over):
    """Layer the user's file over the factory defaults, one level deep.

    One level is exactly what this file has (outlook / sync / retention /
    server / claude / extractor), and it is what lets a NEW default key reach an
    existing install: a shallow update would drop it as soon as the user's file
    carried its own `outlook` block.
    """
    out = dict(base or {})
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = dict(out[k])
            merged.update(v)
            out[k] = merged
        else:
            out[k] = v
    return out


def load_settings():
    """config/settings.json over config/settings.default.json.

    The user file is written by the Settings screen and is the ONLY place a
    deployed machine's endpoint and token live. It is deliberately optional:
    the release does not ship one, so an update can never overwrite the copy
    this machine was configured with - the thing that used to make every new
    deployment re-enter the endpoint and the token.
    """
    path = os.path.join(BASE, "config", "settings.json")
    defaults_path = os.path.join(BASE, "config", "settings.default.json")
    defaults = {}
    if os.path.exists(defaults_path):
        with open(defaults_path, encoding="utf-8-sig") as f:
            defaults = json.load(f) or {}
    user = {}
    if os.path.exists(path):
        # utf-8-sig: readable even when a BOM is present. A corrupt file still
        # raises here on purpose - silently starting from defaults would throw
        # the stored credential away without telling anyone.
        with open(path, encoding="utf-8-sig") as f:
            user = json.load(f) or {}
    s = _merge_settings(defaults, user)
    s["_settings_path"] = path
    s["_base"] = BASE
    return s


def run_pipeline(settings, conn, master):
    print("[1/2] Collecting emails from Outlook...")
    mails = collect(settings, conn, BASE)
    print(f"      {len(mails)} emails found")

    print("[2/2] Classifying / checking duplicates...")
    new_cnt = fail_cnt = dup_cnt = 0
    for m in mails:
        customer, po, _entry = classify(m, master, settings)
        m["customer"], m["po_number"] = customer, po
        is_dup, kind, reason = check_duplicate(conn, customer, po, m, settings)
        m["is_duplicate"], m["dup_kind"], m["dup_reason"] = int(is_dup), kind, reason
        m["cancel_flag"] = int(is_cancellation(m, settings))
        if store.insert_mail(conn, m):
            new_cnt += 1
            if not customer:
                fail_cnt += 1
            if is_dup:
                dup_cnt += 1
    print(f"      {new_cnt} new saved (unmatched {fail_cnt}, duplicate alerts {dup_cnt})")
    return new_cnt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect-only", action="store_true")
    ap.add_argument("--serve-only", action="store_true")
    args = ap.parse_args()

    settings = load_settings()
    db_path = os.path.join(BASE, settings.get("db_path", "data/po_mail.db"))
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # A master that exists but cannot be parsed is a hard stop, not an empty
    # table. Starting anyway would show every stored mail as unclassified, and
    # the next edit would save that emptiness over the file. of_master has
    # already moved the unreadable bytes aside; say so and stop.
    try:
        master = ship_master.domain_master(settings)
        st = ship_master.status(settings)
    except RuntimeError as e:
        print(f"\n[ERROR] {e}\n")
        sys.exit(1)
    print(f"Ship-To master: {st['total']} rows / {st['domains']} domains "
          f"loaded")

    # Check the ERP template now rather than at the first Confirm. On a PC
    # where document security blocks OrderFlow this is the first thing to fail.
    ok, why = erp_excel.template_status(settings)
    if not ok:
        print("\n  [WARN] Order Upload files cannot be created:")
        for line in why.splitlines():
            print("         " + line)
        print()

    if args.collect_only:
        conn = store.connect(db_path)
        try:
            run_pipeline(settings, conn, master)
        except RuntimeError as e:
            print(f"\n[ERROR] {e}\n")
            sys.exit(1)
        finally:
            conn.close()
        return

    # Collect in the background -- the dashboard comes up first, mails fill in afterwards
    if not args.serve_only:
        print("Starting dashboard… (collecting emails in the background)")
        threading.Thread(target=server.run_sync_bg,
                         args=(db_path, master, settings),
                         daemon=True).start()

    server.serve(db_path, master, settings)


def open_ui(port):
    """Open in Edge/Chrome app mode (standalone window without address bar). Falls back to default browser."""
    import subprocess
    url = f"http://127.0.0.1:{port}"
    candidates = (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    )
    for exe in candidates:
        if os.path.exists(exe):
            subprocess.Popen([exe, f"--app={url}",
                              "--window-size=1480,900"])
            return
    webbrowser.open(url)






# ====================== module split wiring ======================

_MODULES = ('of_core', 'of_outlook', 'of_master', 'of_erp', 'of_pdf',
            'of_server')
import of_core, of_outlook, of_master, of_erp, of_pdf, of_server  # noqa: E402

# Re-publish every module global into this namespace, in the same order
# the sections were concatenated in the merged file, so code that does
# 'import orderflow' still sees one flat namespace.
for _m in (of_core, of_outlook, of_master, of_erp, of_pdf, of_server):
    for _k, _v in list(vars(_m).items()):
        if not _k.startswith('__'):
            globals().setdefault(_k, _v)

# ==========================================================================
#  SECTION: namespace facades for the former modules
#  (so `store.connect(...)` and friends keep working)
# ==========================================================================

class _NS:
    pass


def _ns(**kw):
    n = _NS()
    n.__dict__.update(kw)
    return n


_FACADE_MISSING = []


def _bind(pairs):
    """Bind facade attribute -> merged global, skipping dead names.

    A name defined only inside a disabled `if __name__ == ...` block
    would raise NameError while the facades are being built.

    A miss is reported, not swallowed. A new function added to a section but
    not listed in its `_bind((...))` tuple otherwise disappears silently, and
    the first symptom is an AttributeError from inside a request handler -
    which is exactly how `store.order_attachments` went missing once.
    """
    g = globals()
    out = {}
    for attr, real in pairs:
        if real in g:
            out[attr] = g[real]
        else:
            _FACADE_MISSING.append(attr + ' -> ' + real)
    return out

store = _ns(**_bind((
    ("ATT_FIELDS", "ATT_FIELDS"), ("EDITABLE_FIELDS", "EDITABLE_FIELDS"), ("SHIP_DETAIL_FIELDS", "SHIP_DETAIL_FIELDS"), ("ORDER_FIELDS", "ORDER_FIELDS"), ("TYPED_FIELDS", "TYPED_FIELDS"), ("ORDER_DOC_EXT", "ORDER_DOC_EXT"), ("SCHEMA", "SCHEMA"), ("_rows", "_rows"), ("att_name", "att_name"), ("backfill_mailbox", "backfill_mailbox"), ("connect", "connect"), ("dashboard_data", "dashboard_data"), ("datetime", "datetime"), ("get_att_states", "get_att_states"), ("get_mail", "get_mail"), ("get_meta", "get_meta"), ("insert_mail", "insert_mail"), ("json", "json"), ("order_att_list", "order_att_list"), ("order_attachments", "order_attachments"), ("os", "os"), ("po_exists", "po_exists"), ("resolve_attachment", "resolve_attachment"), ("resolve_attachments", "resolve_attachments"), ("set_meta", "set_meta"), ("sqlite3", "sqlite3"), ("update_att_field", "update_att_field"), ("update_field", "update_field"))))

classifier = _ns(**_bind((
    ("PO_PRESETS", "PO_PRESETS"), ("PO_PRESET_VALUES", "PO_PRESET_VALUES"), ("PUBLIC_DOMAINS", "PUBLIC_DOMAINS"), ("_po_patterns", "_po_patterns"), ("classify", "classify"), ("csv", "csv"), ("domain_conflicts", "domain_conflicts"), ("domain_owners", "domain_owners"), ("extract_po_number", "extract_po_number"), ("looks_like_date", "looks_like_date"), ("mail_domain", "mail_domain"), ("match_customer", "match_customer"), ("norm_domain", "norm_domain"), ("public_domain", "public_domain"), ("re", "re"))))

dedup = _ns(**_bind((
    ("check_duplicate", "check_duplicate"), ("is_cancellation", "is_cancellation"), ("store", "store"))))

collector = _ns(**_bind((
    ("IMAGE_EXT", "IMAGE_EXT"), ("JUNK_ATT", "JUNK_ATT"), ("LAST_DIAG", "LAST_DIAG"), ("PR_INTERNET_MESSAGE_ID", "PR_INTERNET_MESSAGE_ID"), ("PR_SMTP_ADDRESS", "PR_SMTP_ADDRESS"), ("SAVE_EXT", "SAVE_EXT"), ("_domain", "_domain"), ("_has_document", "_has_document"), ("_message_id", "_message_id"), ("_resolve_folder", "_resolve_folder"), ("_save_pdfs", "_save_pdfs"), ("_smtp_sender", "_smtp_sender"), ("_to_record", "_to_record"), ("_want_save", "_want_save"), ("claim_mailbox", "claim_mailbox"), ("collect", "collect"), ("collect_outlook", "collect_outlook"), ("datetime", "datetime"), ("hashlib", "hashlib"), ("os", "os"), ("re", "re"), ("save_attachments", "save_attachments"), ("split_by_attachment", "split_by_attachment"), ("store", "store"), ("test_outlook", "test_outlook"))))

housekeeping = _ns(**_bind((
    ("_log_path", "_log_path"), ("_write_log", "_write_log"), ("cleanup_attachments", "cleanup_attachments"), ("datetime", "datetime"), ("disk_usage", "disk_usage"), ("json", "json"), ("os", "os"))))

win_focus = _ns(**_bind((
    ("ASFW_ANY", "ASFW_ANY"), ("_force_front", "_force_front"), ("_snapshot", "_snapshot"), ("allow_foreground", "allow_foreground"), ("open_and_focus", "open_and_focus"), ("raise_new_window", "raise_new_window"), ("threading", "threading"), ("time", "time"))))

scheduler = _ns(**_bind((
    ("LOCK", "LOCK"), ("_next_due", "_next_due"), ("_parse_times", "_parse_times"), ("_state", "_state"), ("datetime", "datetime"), ("refresh_next_due", "refresh_next_due"), ("run_once", "run_once"), ("start", "start"), ("state", "state"), ("threading", "threading"), ("traceback", "traceback"))))

material_master = _ns(**_bind((
    ("CODE_HEADERS", "CODE_HEADERS"), ("MAP_HEADERS", "MAP_HEADERS"),
    ("REL", "mm_REL"), ("SECTION_STOP", "SECTION_STOP"),
    ("_category_columns", "_category_columns"), ("_map_columns", "_map_columns"),
    ("_map_head", "_map_head"), ("_norm_head", "_norm_head"),
    ("_path", "mm_path"), ("_read_rows", "_read_rows"),
    ("_rows_via_excel", "_rows_via_excel"), ("add_one", "add_one"),
    ("clear", "clear"), ("code_rules", "code_rules"),
    ("datetime", "datetime"), ("delete", "mm_delete"),
    ("export_csv", "export_csv"), ("items", "items"), ("json", "json"),
    ("load", "mm_load"), ("looks_like_code", "looks_like_code"),
    ("lookup", "lookup"), ("merge", "merge"), ("norm", "norm"),
    ("os", "os"), ("parse_excel", "parse_excel"),
    ("parse_mapping", "parse_mapping"), ("parse_section", "parse_section"),
    ("pending_reviews", "pending_reviews"), ("dismissed_codes", "dismissed_codes"), ("dismiss_reviews", "dismiss_reviews"), ("dismissed_path", "dismissed_path"), ("DISMISSED_REL", "DISMISSED_REL"), ("re", "re"), ("save", "mm_save"),
    ("sheet_names", "sheet_names"), ("sku_conflicts", "sku_conflicts"),
    ("sku_full", "sku_full"), ("sku_groups", "sku_groups"),
    ("sku_map", "sku_map"),
    ("sync_to_engine", "sync_to_engine"), ("sys", "sys"),
    ("upload", "mm_upload"))))

ship_master = _ns(**_bind((
    ("ST_COLUMNS", "ST_COLUMNS"), ("ST_HEADERS", "ST_HEADERS"),
    ("ST_HINTS", "ST_HINTS"), ("ST_KEYS", "ST_KEYS"),
    ("ST_PAYLOAD", "ST_PAYLOAD"),
    ("DM_COLUMNS", "DM_COLUMNS"), ("DM_HEADERS", "DM_HEADERS"),
    ("DM_HINTS", "DM_HINTS"), ("DM_KEYS", "DM_KEYS"),
    ("_clean", "_clean"), ("_find_columns", "_find_columns"),
    ("_header_and_cols", "_header_and_cols"), ("_norm_name", "_norm_name"),
    ("_pair", "_pair"), ("_path", "st_path"), ("_payload", "_payload"),
    ("add_row", "add_row"), ("channel_for_type", "channel_for_type"), ("states", "states"),
    ("classifier", "classifier"), ("clear", "st_clear"),
    ("conflicts", "conflicts"), ("datetime", "datetime"),
    ("delete_row", "delete_row"), ("dm_add", "dm_add"),
    ("dm_clear", "dm_clear"), ("dm_count", "dm_count"),
    ("dm_delete_row", "dm_delete_row"), ("dm_index", "dm_index"),
    ("dm_load", "dm_load"), ("dm_matches", "dm_matches"),
    ("dm_page", "dm_page"), ("dm_parse_file", "dm_parse_file"),
    ("dm_path", "dm_path"), ("dm_rows", "dm_rows"),
    ("dm_save", "dm_save"), ("dm_set_cell", "dm_set_cell"),
    ("dm_upload", "dm_upload"), ("domain_master", "domain_master"),
    ("domain_of", "domain_of"), ("index_pairs", "index_pairs"),
    ("json", "json"), ("load", "load"), ("master_key", "master_key"),
    ("matches", "matches"),
    ("material_master", "material_master"), ("os", "os"), ("page", "page"),
    ("parse_file", "parse_file"), ("re", "re"), ("rows", "rows"),
    ("save", "save"), ("set_cell", "set_cell"),
    ("ship_options", "ship_options"), ("site", "site"),
    ("sold_options", "sold_options"), ("status", "status"),
    ("upload", "upload"))))

data_export = _ns(**_bind((
    ("DATA_SCHEMAS", "DATA_SCHEMAS"), ("EXPORT_DIR", "EXPORT_DIR"),
    ("KIND_ENUM", "KIND_ENUM"), ("KIND_NUMBER", "KIND_NUMBER"),
    ("KIND_TEXT", "KIND_TEXT"),
    ("build_export", "build_export"), ("contract_ok", "contract_ok"),
    ("customer_records", "customer_records"), ("domain_records", "domain_records"),
    ("export_data", "export_data"),
    ("export_path", "export_path"), ("export_rows", "export_rows"),
    ("material_records", "material_records"),
    ("missing_required", "missing_required"), ("norm_cell", "norm_cell"),
    ("norm_enum", "norm_enum"), ("schema", "schema"),
    ("schema_headers", "schema_headers"), ("write_export", "write_export"))))

erp_excel = _ns(**_bind((
    ("COLUMNS", "COLUMNS"), ("FORMAT_FULL", "FORMAT_FULL"),
    ("CURRENCY", "CURRENCY"), ("DIVISION", "DIVISION"),
    ("SALES_ORG", "SALES_ORG"),
    ("TEXT_FIELDS", "TEXT_FIELDS"),
    ("FORMAT_SIMPLE", "FORMAT_SIMPLE"), ("MAX_HEADER_ROW", "MAX_HEADER_ROW"),
    ("SIMPLE_COLUMNS", "SIMPLE_COLUMNS"), ("SIMPLE_SHEET", "SIMPLE_SHEET"),
    ("_REQUIRED", "_REQUIRED"), ("_po_tag", "_po_tag"),
    ("TEMPLATE_REL", "TEMPLATE_REL"), ("_COST_MONEY", "_COST_MONEY"), ("_COST_UNIT", "_COST_UNIT"), ("_MONEY_ANY", "_MONEY_ANY"), ("_QTY_DECIMAL", "_QTY_DECIMAL"), ("_QTY_LABEL", "_QTY_LABEL"), ("_QTY_MONEY", "_QTY_MONEY"), ("_QTY_UNIT", "_QTY_UNIT"), ("_TEMPLATE_DRM_MSG", "_TEMPLATE_DRM_MSG"), ("_amount_from_line", "_amount_from_line"), ("_cost_from_desc", "_cost_from_desc"), ("_dedupe_records", "_dedupe_records"), ("_hkey", "_hkey"), ("_num", "_num"), ("_party_fill", "_party_fill"), ("order_brief", "order_brief"), ("order_preview", "order_preview"), ("_order_dates", "_order_dates"), ("_po_header", "_po_header"), ("_order_blocks", "_order_blocks"), ("_po_ship", "_po_ship"), ("_po_ship_fields", "_PO_SHIP_FIELDS"), ("_plain_template_copy", "_plain_template_copy"), ("_qty_from_desc", "_qty_from_desc"), ("build_simple", "build_simple"), ("build_simple_lines", "build_simple_lines"), ("build_upload", "build_upload"), ("build_upload_lines", "build_upload_lines"), ("column_map", "column_map"), ("datetime", "datetime"), ("dedupe_line_records", "dedupe_line_records"), ("first_empty_row", "first_empty_row"), ("header_row", "header_row"), ("is_simple", "is_simple"), ("open_template", "open_template"), ("os", "os"), ("output_format", "output_format"), ("output_formats", "output_formats"), ("output_path", "output_path"), ("prepare_lines", "prepare_lines"), ("re", "re"), ("simple_workbook", "simple_workbook"), ("template_path", "template_path"), ("template_status", "template_status"), ("validate_template", "validate_template"), ("write_line", "write_line"), ("write_simple", "write_simple"))))

pdf_access = _ns(**_bind((
    ("ACROBAT_TEXT_CONVERTERS", "ACROBAT_TEXT_CONVERTERS"), ("COM_TIMEOUT", "COM_TIMEOUT"), ("CONVERT_TIMEOUT", "CONVERT_TIMEOUT"), ("EXPORT_CLIENTS", "EXPORT_CLIENTS"), ("LINE_TOLERANCE", "LINE_TOLERANCE"), ("MAX_WORDS", "MAX_WORDS"), ("TEXT_CLIENTS", "TEXT_CLIENTS"), ("TOTAL_BUDGET", "TOTAL_BUDGET"), ("WORD_WALK_TIMEOUT", "WORD_WALK_TIMEOUT"), ("_acrobat_close", "_acrobat_close"), ("_acrobat_open", "_acrobat_open"), ("_acrobat_running", "_acrobat_running"), ("_acrobat_save_as", "_acrobat_save_as"), ("_acrobat_walk_text", "_acrobat_walk_text"), ("_di_path", "_di_path"), ("_exe_of_progid", "_exe_of_progid"), ("_js_word", "_js_word"), ("_lines_from_words", "_lines_from_words"), ("_looks_like_text", "_looks_like_text"), ("_reg_value", "_reg_value"), ("_registered", "_registered"), ("_report", "_report"), ("_run_with_timeout", "_run_with_timeout"), ("_scan", "_scan"), ("_version_ok", "_version_ok"), ("acrobat_export", "acrobat_export"), ("acrobat_text", "acrobat_text"), ("args", "args"), ("is_drm", "is_drm"), ("office_export", "office_export"), ("office_text", "office_text"), ("os", "os"), ("re", "re"), ("resolve", "resolve"), ("shutil", "shutil"), ("status", "pdf_status"), ("sys", "sys"), ("tempfile", "tempfile"), ("threading", "threading"), ("time", "time"))))

quick_convert = _ns(**_bind((
    ("ALLOWED_EXT", "ALLOWED_EXT"), ("COST_HEADERS", "COST_HEADERS"), ("DRM_HEAD", "DRM_HEAD"), ("FOOTER_WORDS", "FOOTER_WORDS"), ("PO_HEADERS", "PO_HEADERS"), ("QTY_HEADERS", "QTY_HEADERS"), ("READABLE_HEADS", "READABLE_HEADS"), ("TOTAL_HEADERS", "TOTAL_HEADERS"), ("_find_po", "_find_po"), ("_head", "_head"), ("_header_row", "_header_row"), ("_is_footer", "_is_footer"), ("_num", "qc_num"), ("_po_value", "_po_value"), ("_usable", "_usable"), ("cleanup_inputs", "cleanup_inputs"), ("convert", "convert"), ("export", "export"), ("locate_by_name", "locate_by_name"), ("material_master", "material_master"), ("os", "os"), ("parse_excel_po", "parse_excel_po"), ("parse_excel_pos", "parse_excel_pos"), ("parse_excel_sheet", "parse_excel_sheet"), ("re", "re"), ("resolve_paths", "resolve_paths"), ("save_input", "save_input"), ("scan_folder", "scan_folder"))))

extractor_bridge = _ns(**_bind((
    ("EXCEL_EXT", "EXCEL_EXT"), ("_ENGINE", "_ENGINE"), ("_ENGINE_MOD", "_ENGINE_MOD"), ("_backbone_class", "_backbone_class"), ("_code_base", "_code_base"), ("_load_engine", "_load_engine"), ("_import_engine", "_import_engine"), ("_load_module", "_load_module"), ("_cache_orders", "_cache_orders"), ("cached_read", "cached_read"), ("expand_orders", "expand_orders"), ("normalise_to_master", "normalise_to_master"), ("os", "os"), ("preview_order", "preview_order"), ("po_reading_state", "po_reading_state"), ("read_detail", "read_detail"), ("read_orders", "read_orders"), ("read_summary", "read_summary"), ("run_extractor", "run_extractor"),
    ("run_extractor_multi", "run_extractor_multi"), ("sys", "sys"),
    ("test_po_reading", "test_po_reading"))))

server = _ns(**_bind((
    ("BaseHTTPRequestHandler", "BaseHTTPRequestHandler"), ("SYNC", "SYNC"), ("SYNC_LOCK", "SYNC_LOCK"), ("ThreadingHTTPServer", "ThreadingHTTPServer"), ("_master_values", "_master_values"), ("_persist_typed_ship", "_persist_typed_ship"), ("_run_pipeline", "_run_pipeline"), ("_save_settings", "_save_settings"), ("_typed_party", "_typed_party"), ("_typed_ship", "_typed_ship"), ("classifier", "classifier"), ("ship_master", "ship_master"), ("extractor_bridge", "extractor_bridge"), ("housekeeping", "housekeeping"), ("json", "json"), ("make_handler", "make_handler"), ("material_master", "material_master"), ("os", "os"), ("quick_convert", "quick_convert"), ("re", "re"), ("report", "report"), ("run_sync_bg", "run_sync_bg"), ("scheduler", "scheduler"), ("serve", "serve"), ("store", "store"), ("sync_status", "sync_status"), ("win_focus", "win_focus"))))


# A facade referring to itself is filled in here, after every facade above has
# been bound.
material_master.__dict__.setdefault("material_master", material_master)


# Every facade name above must resolve. This used to be collected into
# _FACADE_MISSING and never looked at, so a name that was not listed in its
# section's _bind((...)) tuple simply vanished from the facade - and the only
# symptom was an AttributeError raised later, from inside a request handler.
#
# The three entries below are genuinely absent and harmless:
#   erp_excel / material_master  a section referring to its own facade, which
#                                is filled in by the setdefault lines above
#   args                         lives in a disabled `if __name__ == ...` block
_ALLOWED_FACADE_MISSING = {"erp_excel -> erp_excel",
                           "material_master -> material_master",
                           "args -> args"}
_unexpected = [m for m in _FACADE_MISSING if m not in _ALLOWED_FACADE_MISSING]
if _unexpected:
    raise RuntimeError(
        "Facade name(s) did not resolve: " + ", ".join(_unexpected) +
        ". A module-level name added inside a `# SECTION:` has to be listed "
        "in that section's _bind((...)) tuple in src\\orderflow.py, or the "
        "facade silently loses it (see docs\\HANDOVER.md 2.1).")




# ---------------- late-binding of sibling names ----------------

# The split modules call sibling sections exactly as the merged file did:
# through the facade objects (store.connect(...), material_master.load(...))
# and, in a handful of places, by bare function name. Those names now live
# here, so bind them into each module's globals.
_FACADES = ('store', 'classifier', 'dedup', 'collector',
            'housekeeping', 'win_focus', 'scheduler', 'material_master',
            'ship_master', 'data_export', 'erp_excel', 'pdf_access',
            'quick_convert', 'extractor_bridge', 'server')

# Bare (non-facade) cross-section names each module references, per the
# static analysis done at split time.
_BARE = {
    'of_core': ('erp_excel', 'material_master'),
    'of_outlook': (),
    'of_master': ('_hkey',),
    'of_erp': (),
    'of_pdf': (),
    'of_server': ('classify', 'check_duplicate', 'collect', 'contract_ok',
                  'export_data', 'is_cancellation', 'open_ui', 'test_outlook'),
}

for _mname in _MODULES:
    _m = globals()[_mname]
    for _f in _FACADES:
        setattr(_m, _f, globals()[_f])
    for _n in _BARE.get(_mname, ()):
        setattr(_m, _n, globals()[_n])

# ==========================================================================
#  SECTION: entry point
#  Must stay last: every facade above has to be bound before main() runs.
# ==========================================================================

if __name__ == "__main__":
    main()
