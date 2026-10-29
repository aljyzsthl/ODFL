# -*- coding: utf-8 -*-
"""
devtools.py - every developer tool for the Material Code Extractor, in one file.

Run it from this folder (or use devtools.bat):

    python devtools.py               engine regression tests  (the default)
    python devtools.py selftest      same thing, spelled out
    python devtools.py template      zone-template editor (GUI, needs PyMuPDF)

Exit code 0 = clean. The regression suite is the licence to refactor the
engine: it encodes bugs that actually shipped, one test each.

Sections, in order:
    lang             UI strings (English default, Korean available)
    template editor  draw/edit the per-customer zones in customer_templates.json
    self test        the regression suite
    dispatcher       this file's own command line

Merged on 2026-09-26 from four files. Nothing was rewritten - each former
module is a section below, with the only real name collision (`main`) renamed
to st_main / tpl_main.

The golden-set scorer (formerly `verify_golden.py`) was removed on 2026-10-19
and replaced by the baseline snapshot comparison in engine_baseline.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


# ==========================================================================
#  SECTION: lang  (formerly lang.py)
# ==========================================================================
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"

DEFAULT_LANG = "en"

STRINGS = {
    "en": {
        # ── App shell ──────────────────────────
        "app_title":        "Samsung Material Code Extractor",
        "app_subtitle":     "Home Appliance | North America Sales",
        "version":          "v3.0",
        "ready":            "Ready",

        # ── Navigation ─────────────────────────
        # Grouped into three sections so the learning loop is visible: what the
        # app RUNS, what it LEARNS FROM, and how accurate that learning is.
        "nav_sec_extract":  "EXTRACT",
        "nav_sec_learning": "LEARNING",
        "nav_sec_system":   "SYSTEM",

        "nav_upload":       "Upload & Extract",
        "nav_cache":        "Processing History",
        "nav_backbone":     "Code Learning",
        "nav_templates":    "PO Layout Learning",
        "nav_settings":     "Preferences",
        "nav_help":         "Help",

        # Sidebar badges - what the app has learned so far
        "nav_badge_codes":     "{n} codes",
        "nav_badge_layouts":   "{n} customers",
        "nav_badge_none":      "not set up",

        # ── Backbone list ──────────────────────
        "bb_title":         "Backbone Material Code List",
        "bb_desc":          ("Codes listed here are the source of truth. They are matched first and "
                             "override pattern guessing, which removes false hits such as PO numbers.\n"
                             "Matching ignores case and separators, and tolerates market suffixes "
                             "(enter DW80CG4051SR to also match DW80CG4051SRAA)."),
        "bb_count":         "{n} code(s) loaded",
        "bb_empty":         "No codes loaded - extraction will fall back to pattern matching",
        "bb_save":          "Save List",
        "bb_reload":        "Reload",
        "bb_open_csv":      "Open in Excel",
        "bb_saved":         "Backbone list saved ({n} codes). Re-run extraction to apply.",
        "bb_col_code":      "Material Code",
        "bb_col_desc":      "Description",
        "bb_col_cat":       "Category",
        "bb_editor_hint":   "One code per line:  material_code,description,category",

        # Master list panel
        "ml_title":         "Company Master List",
        "ml_desc":          ("Drop your subsidiary's master code file (e.g. "
                             "SamsungCodestructor_xxxxxx.xlsx) into the master_list folder. "
                             "Every sheet is read; sheet names and section headings become "
                             "the product category. When the file changes, the extractor "
                             "re-learns from it automatically at startup."),
        "ml_file":          "Master file",
        "ml_none":          "No master file yet - click [Upload Master File] or drop one into the master_list folder",
        "ml_synced":        "In sync - {n} codes learned ({t})",
        "ml_outdated":      "File changed - click [Sync Now] to re-learn",
        "ml_upload":        "Upload Master File",
        "ml_sync":          "Sync Now",
        "ml_open_folder":   "Open master_list Folder",
        "ml_syncing":       "Learning master list...",
        "ml_sync_done":     "Master list learned: {n} codes from {f}",
        "ml_sync_fail":     "Master list sync failed",
        "ml_sheets":        "Sheets imported",
        "ml_auto_synced":   "Master list updated - re-learned {n} codes automatically",

        # Import
        "bb_import":        "Import from Excel / CSV",
        "bb_import_title":  "Import Material Code Master List",
        "bb_import_pick":   "Select your material code master file",
        "bb_import_reading": "Reading file...",
        "bb_import_result": "Import Preview",
        "bb_import_rows":   "Rows read",
        "bb_import_ok":     "Codes found",
        "bb_import_dup":    "Duplicates skipped",
        "bb_import_skip":   "Rows skipped",
        "bb_import_cols":   "Detected columns",
        "bb_import_sample": "Sample of imported codes",
        "bb_import_apply":  "Replace list with these codes",
        "bb_import_merge":  "Add to existing list",
        "bb_import_cancel": "Cancel",
        "bb_import_done":   "Imported {n} codes. Re-run extraction to apply.",
        "bb_import_fail":   "Import failed",
        "bb_import_note":   ("Accepts .xlsx / .csv / .tsv exported from SAP or Excel.\n"
                             "The header row is located automatically and only the code, "
                             "description and category columns are kept."),

        # ── Upload screen ──────────────────────
        "upload_title":     "PDF Upload & Extraction",
        "btn_add_pdf":      "Add PDF",
        "btn_open_folder":  "Open Upload Folder",
        "btn_refresh":      "Refresh",
        "btn_remove":       "Remove Selected",
        "btn_select_all":   "Select All",
        "btn_diagnose":     "Diagnose PDF",
        "btn_extract":      "Extract Codes",
        "btn_export":       "Export to Excel",
        "chk_force":        "Ignore cache (force reprocess)",

        "col_file":         "File Name",
        "col_size":         "Size",
        "col_status":       "Status",
        "col_codes":        "Codes",
        "status_processed": "Processed",
        "status_pending":   "Pending",
        "no_pdfs":          "No PDF files. Click [Add PDF] or copy files into the data_upload folder.",

        "dlg_select_pdf":   "Select PDF files",
        "files_added":      "{n} file(s) added",
        "no_selection":     "No selection",
        "select_pdf_first": "Please select at least one PDF.",
        "confirm_delete":   "Confirm Delete",
        "delete_n_files":   "Delete {n} file(s)?",

        # ── Extraction ─────────────────────────
        "extract_start":    "Starting extraction...",
        "extract_done":     "Extraction Complete",
        "extract_failed":   "Extraction failed",
        "total_extracted": "{n} material code(s) extracted",
        "export_prompt":    "Export to Excel?",
        "problem_files":    "{n} file(s) need attention.\n   Use [Zone Templates] > [Test] to diagnose extraction areas.",
        "loaded_cache":     "Loaded from cache",
        "pages_analyzing":  "Analyzing page {i}/{n}...",
        "po_extracting":    "Extracting PO Number...",
        "text_extracting":  "Extracting PDF text...",

        # ── Export ─────────────────────────────
        "no_data":          "No Data",
        "process_first":    "Please process PDF files first.",
        "excel_saved":      "Excel saved: {name}",
        "save_complete":    "Save Complete",
        "open_file_prompt": "Excel file saved:\n{path}\n\nOpen the file?",
        "excel_error":      "Excel Error",
        "excel_save_failed": "Failed to save Excel file",

        # ── Zone Templates ─────────────────────
        "tmpl_title":       "Zone Templates (Customer-specific extraction areas)",
        "tmpl_col_customer": "Customer",
        "tmpl_col_zones":   "Zones",
        "tmpl_col_sample":  "Sample PDF",
        "tmpl_col_updated": "Updated",
        "tmpl_btn_edit":    "Edit",
        "tmpl_btn_test":    "Test",
        "tmpl_btn_new":     "+ New Template",
        "tmpl_none":        "No customer templates registered.\nClick [+ New Template] to add one.",
        "tmpl_hint":        "Tip: Click [Test] to preview what is actually extracted from each defined area.",
        "tmpl_optional": (
            "Templates are OPTIONAL - a form of layout learning.\n"
            "PDFs without a matching template are still processed automatically "
            "using the backbone list. Add a template only for customers whose "
            "layout is read incorrectly; do it once and every future PO from "
            "that customer reuses it.\n"
            "Matching is automatic: first by customer name in the filename, "
            "then by document content."),
        "tmpl_matched_by":  "Matched by",
        "tmpl_match_name":  "filename",
        "tmpl_match_print": "content",
        "tmpl_test_title":  "Zone Test",
        "tmpl_test_header": "Zone extraction results: {customer}",
        "tmpl_extracting":  "Extracting zones... (scanned PDFs take longer due to OCR)",
        "tmpl_test_done":   "Zone test complete",
        "file_not_found":   "File Not Found",
        "sample_missing":   "Sample PDF not found:\n{path}",
        "extract_error":    "Extraction Error",
        "no_zone_content":  ("No content extracted.\n\n"
                             "Possible causes:\n"
                             "  - The zone points to an area with no text\n"
                             "  - The PDF is a scanned image and OCR is unavailable\n"
                             "  - Coordinate mismatch\n"),
        "raw_text":         "RAW TEXT",
        "empty_value":      "(empty)",
        "tables_detected":  "TABLES: {n} detected",
        "parsed_po":        "Parsed PO Number",
        "parsed_codes":     "Parsed Material Codes",
        "parse_failed":     "(not found)",
        "ocr_processed":    "OCR processed",
        "btn_close":        "Close",

        # ── Template Editor ────────────────────
        "editor_title":     "Zone Template Editor",
        "editor_customer":  "Customer:",
        "editor_open_pdf":  "Open PDF",
        "editor_save":      "Save Template",
        "editor_step1":     "1. Zone Type",
        "editor_step2":     "2. Draw on PDF",
        "editor_step2_hint": "Click and drag to\ndefine extraction zone",
        "editor_step3":     "3. Defined Zones",
        "editor_delete_zone": "Delete Selected Zone",
        "editor_page":      "Page {cur}/{total}",
        "editor_zones_on_page": "({n} zone)",
        "editor_status_init": "Open a PDF to check its text layer status.",
        "editor_zone_count": "{n} zone(s)",
        "editor_missing":   "Missing: {types}",
        "zone_name_title":  "Zone Name",
        "zone_name_prompt": "Enter a name for this zone (e.g. Item Code Column):",
        "keep_zones_title": "Keep Zones?",
        "keep_zones_msg":   ("{n} zone(s) are currently defined.\n\n"
                             "[Yes] Keep existing zones and open the new PDF\n"
                             "[No] Clear all zones and start fresh"),
        "sample_pdf_missing_title": "Sample PDF Not Found",
        "sample_pdf_missing_msg": ("The sample PDF for '{customer}' could not be found.\n"
                                   "Click [Open PDF] to load a PDF and view existing zones.\n\n"
                                   "Registered zones: {n}"),
        "input_error":      "Input Error",
        "enter_customer":   "Please enter a customer name.",
        "no_zones_title":   "No Zones",
        "no_zones_msg":     "Define at least one zone before saving.",
        "save_ok_title":    "Saved",
        "save_ok_msg":      "Template '{customer}' saved ({n} zone(s)).",

        # Zone types
        "zone_line_items":    "Line Items Table",
        "zone_material_code": "Material Code",
        "zone_po_number":     "PO Number",
        "zone_description":   "Description",
        "zone_quantity":      "Quantity",
        "zone_unit_price":    "Unit Price",
        "zone_amount":        "Amount",

        "editor_recommended": "RECOMMENDED",
        "editor_group_simple": "Recommended - draw 2 boxes",
        "editor_group_manual": "Advanced - column by column",
        "editor_li_hint": ("Draw ONE box around the whole item table, including\n"
                           "the header row (Qty / Unit / Price). Rows and columns\n"
                           "are detected automatically, so each code keeps its own\n"
                           "quantity. No separate Quantity box is needed."),
        "editor_manual_hint": ("Use these only when the document has no table\n"
                               "header. Each box must line up vertically with\n"
                               "the others, row by row."),

        # ── Text layer status ──────────────────
        "text_layer_ok":    "Text layer OK ({n} chars)",
        "text_layer_ocr_ready": "Scanned PDF - will be processed with OCR automatically (engine: {engine}). Define zones to OCR only those areas.",
        "text_layer_no_ocr": "Scanned PDF - no OCR engine. Run: pip install rapidocr-onnxruntime",
        "ocr_standby":      "OCR ready: {engine}",

        # ── Preferences (was: Settings) ────────
        "settings_title":   "Preferences",
        "settings_desc":    ("The few settings worth changing day to day. Everything else is "
                             "tuned for accuracy and is best left alone."),
        "pref_language":    "Language",
        "pref_lang_hint":   "Takes effect after restarting the application",
        "pref_ocr_dpi":     "Scan quality (OCR)",
        "pref_ocr_dpi_hint": ("Higher is more accurate on faint or skewed scans, and slower. "
                              "300 suits a clean fax; raise it when codes come out garbled."),
        "pref_dpi_300":     "300 - Standard (fastest)",
        "pref_dpi_400":     "400 - High",
        "pref_dpi_600":     "600 - Maximum (slowest)",
        "pref_folders":     "Folders",
        "pref_folder_up":   "PDFs to process",
        "pref_folder_out":  "Excel output",
        "pref_folder_master": "Master code list",
        "pref_open":        "Open",
        "pref_advanced":    "Advanced - extraction rules (edit only if you know the format)",
        "pref_adv_show":    "Show advanced settings",
        "pref_adv_hide":    "Hide advanced settings",
        "pref_adv_warn":    ("These are the raw extraction rules. A typo here can stop the "
                             "application from starting. A backup is saved before each change."),
        "settings_config":  "config.json (Extraction Rules & Patterns)",
        "btn_save_config":  "Save Config",
        "config_saved":     "Configuration saved",
        "pref_saved":       "Preferences saved",
        "json_error":       "JSON Error",
        "json_invalid":     "Invalid JSON format:\n{err}",

        # ── Processing History (was: Cache Viewer) ──
        "cache_title":      "Processing History",
        "cache_desc":       ("Every PDF already processed, with what was found. Results are "
                             "kept so the same file is not read twice - re-reading a PDF is "
                             "only needed after the learning data changes."),
        "cache_none":       "Nothing processed yet. Start from [Upload & Extract].",
        "cache_col_file":   "File Name",
        "cache_col_codes":  "Codes Found",
        "cache_col_po":     "PO Number",
        "cache_col_time":   "Processed At",
        "btn_clear_cache":  "Re-read All Files",
        "confirm":          "Confirm",
        "clear_cache_msg":  ("Discard the saved results and read every PDF again from scratch?\n\n"
                             "Nothing is lost - the PDFs and the learning data stay as they are. "
                             "The next extraction will simply take longer."),
        "cache_cleared":    "Saved results discarded - files will be read again on the next run",

        # ── OCR ────────────────────────────────
        "ocr_badge_ready":  "OCR: {engine}",
        "ocr_badge_none":   "OCR: not installed (click)",
        "ocr_status_title": "OCR Engine Status",
        "ocr_available":    "Available - {engine}",
        "ocr_available_desc": ("Scanned PDFs are processed automatically.\n"
                              "No extra steps or confirmation required.\n\n"
                              "To improve accuracy, increase ocr_dpi to\n"
                              "400-600 in Settings (slower processing)."),
        "ocr_unavailable":  "OCR engine is not installed",
        "ocr_unavailable_desc": ("Scanned image PDFs cannot be read without OCR.\n"
                                "Use the button below to install it.\n"
                                "No external program installation is required."),
        "ocr_install_btn":  "Install OCR Engine",
        "ocr_installing":   "Installing... This runs once and may take a few minutes.",
        "ocr_install_ok":   "Installed. Restart the application to enable OCR.",
        "ocr_install_fail": "Installation failed.\n{err}\n\nA corporate proxy may be blocking PyPI. Connect to a mobile hotspot and retry.",
        "ocr_install_timeout": "Installation timed out. Check your network connection.",

        # ── Diagnostics ────────────────────────
        "diag_title":       "PDF Diagnostic Results",
        "diag_header":      "PDF Diagnostic Results",
        "diag_running":     "Diagnosing: {name}",
        "diag_done":        "Diagnosis complete",
        "diag_failed":      "Diagnosis failed",
        "diag_verdict":     "Verdict",
        "diag_ok":          "Extractable",
        "diag_scanned":     "Not extractable (scanned PDF)",
        "diag_unreadable":  "Cannot open file",
        "diag_engine":      "Engine",
        "diag_pages":       "Pages: {n} ({t} with text)",
        "diag_chars":       "Total characters: {n}",
        "diag_tables":      "Tables detected: {n}",
        "diag_issues":      "Issues found:",
        "diag_recommend":   "Recommended actions:",
        "diag_sample":      "Extracted text sample:",

        # ── Help ───────────────────────────────
        "help_title":       "Help & Usage",
        "help_body": """
HOW TO USE

1. Add PDFs
   Click [Add PDF] to select purchase order or invoice PDFs,
   or copy files directly into the data_upload folder and click [Refresh].

2. Define Zone Templates (recommended)
   Go to [Zone Templates] > [+ New Template].
   Load a sample PDF from the customer, then drag to mark where
   Material Codes and PO Numbers appear. Save the template.
   Files whose names contain the customer name will use it automatically.

3. Extract Material Codes
   Select files and click [Extract Codes].
   Results are cached as JSON in the data_cache folder.

4. Export to Excel
   Click [Export to Excel]. Files are written to data_output.
   The workbook contains a consolidated sheet, a summary sheet,
   and one sheet per source file.

5. Improve Accuracy
   - Fill material_codes_reference.csv with your actual material code list
   - Define Material Code zones for each customer template
   - Adjust patterns in Settings (config.json)

EXTRACTION PRIORITY

   1. Zone Template   - crops only the defined area
   2. Reference List  - matches codes from material_codes_reference.csv
   3. Table Structure - detects header columns
   4. Pattern Match   - regular expressions from config.json

The Match Type column in Excel shows which method was used.

SCANNED PDFs

Scanned image PDFs are detected and processed with OCR automatically.
Click the OCR badge in the header to check status or install the engine.

FOLDERS

   data_upload   - drop PDF files here
   data_cache    - JSON cache (prevents reprocessing)
   data_output   - Excel output files
""",
    },

    "ko": {
        "app_title":        "Samsung Material Code Extractor",
        "app_subtitle":     "생활가전 | 북미 영업",
        "version":          "v3.0",
        "ready":            "준비",
        # ── Sidebar ─────────────────────────────
        "nav_sec_extract":  "추출",
        "nav_sec_learning": "학습",
        "nav_sec_system":   "시스템",

        "nav_upload":       "PDF 업로드 · 추출",
        "nav_cache":        "처리 이력",
        "nav_backbone":     "코드 학습",
        "nav_templates":    "PO 레이아웃 학습",
        "nav_settings":     "환경 설정",
        "nav_help":         "도움말",

        "nav_badge_codes":     "{n}개 코드",
        "nav_badge_layouts":   "거래선 {n}곳",
        "nav_badge_none":      "미설정",

        # ── Processing history ──────────────────
        "cache_title":      "처리 이력",
        "cache_desc":       ("이미 처리한 PDF와 추출 결과입니다. 같은 파일을 두 번 읽지 않도록 "
                             "결과를 보관하며, 학습 데이터가 바뀐 경우에만 다시 읽으면 됩니다."),
        "cache_none":       "처리한 파일이 없습니다. [PDF 업로드 · 추출]에서 시작하세요.",
        "cache_col_file":   "파일명",
        "cache_col_codes":  "추출 코드 수",
        "cache_col_po":     "PO 번호",
        "cache_col_time":   "처리 시각",
        "btn_clear_cache":  "전체 다시 읽기",
        "clear_cache_msg":  ("보관된 결과를 지우고 모든 PDF를 처음부터 다시 읽을까요?\n\n"
                             "PDF와 학습 데이터는 그대로 유지되므로 잃는 것은 없습니다. "
                             "다음 추출이 조금 더 오래 걸릴 뿐입니다."),
        "cache_cleared":    "보관 결과를 지웠습니다 - 다음 실행 시 다시 읽습니다",

        # ── Settings ────────────────────────────
        "settings_title":   "환경 설정",
        "settings_desc":    ("평소에 바꿀 만한 항목만 모았습니다. 나머지는 정확도 기준으로 "
                             "맞춰져 있어 그대로 두는 편이 좋습니다."),
        "pref_language":    "언어",
        "pref_lang_hint":   "프로그램을 다시 시작하면 적용됩니다",
        "pref_ocr_dpi":     "스캔 화질 (OCR)",
        "pref_ocr_dpi_hint": ("값이 높으면 흐리거나 기울어진 스캔에서 정확하지만 느립니다. "
                              "깨끗한 팩스는 300으로 충분하고, 코드가 깨져 나올 때 올리세요."),
        "pref_dpi_300":     "300 - 표준 (가장 빠름)",
        "pref_dpi_400":     "400 - 고화질",
        "pref_dpi_600":     "600 - 최대 (가장 느림)",
        "pref_folders":     "폴더",
        "pref_folder_up":   "처리할 PDF",
        "pref_folder_out":  "Excel 결과물",
        "pref_folder_master": "마스터 코드 리스트",
        "pref_open":        "열기",
        "pref_advanced":    "고급 - 추출 규칙 (형식을 아는 경우에만 수정)",
        "pref_adv_show":    "고급 설정 보기",
        "pref_adv_hide":    "고급 설정 숨기기",
        "pref_adv_warn":    ("추출 규칙 원본입니다. 오타 하나로 프로그램이 실행되지 않을 수 "
                             "있습니다. 변경 전 백업이 자동 저장됩니다."),
        "pref_saved":       "환경 설정을 저장했습니다",

        "upload_title":     "PDF 업로드 및 추출",
        "btn_add_pdf":      "PDF 추가",
        "btn_open_folder":  "업로드 폴더 열기",
        "btn_refresh":      "새로고침",
        "btn_remove":       "선택 삭제",
        "btn_select_all":   "전체 선택",
        "btn_diagnose":     "PDF 진단",
        "btn_extract":      "코드 추출",
        "btn_export":       "Excel 내보내기",
        "chk_force":        "캐시 무시 (강제 재처리)",
        "col_file":         "파일명",
        "col_size":         "크기",
        "col_status":       "상태",
        "col_codes":        "코드",
        "status_processed": "처리됨",
        "status_pending":   "대기",
        "no_pdfs":         "PDF 파일이 없습니다. [PDF 추가] 또는 data_upload 폴더에 복사하세요.",
        "btn_close":        "닫기",
        "help_title":       "도움말",
        "help_body":        "자세한 사용법은 README.md를 참조하세요.",
    },
}


def _load_language() -> str:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        lang = str(cfg.get("language", DEFAULT_LANG)).lower()
        return lang if lang in STRINGS else DEFAULT_LANG
    except Exception:
        return DEFAULT_LANG


_CURRENT = _load_language()


def T(key: str, **kwargs) -> str:
    """Translate a key. Falls back to English, then to the key itself."""
    table = STRINGS.get(_CURRENT, STRINGS[DEFAULT_LANG])
    text = table.get(key) or STRINGS[DEFAULT_LANG].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


# ==========================================================================
#  SECTION: template editor  (formerly template_editor.py)
# ==========================================================================

import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path
from datetime import datetime

# (lang is now part of this file - T is defined above)

try:
    import pymupdf as fitz
    FITZ_AVAILABLE = True
except ImportError:
    try:
        import fitz
        FITZ_AVAILABLE = True
    except ImportError:
        FITZ_AVAILABLE = False

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

BASE_DIR = Path(__file__).parent
TEMPLATES_PATH = BASE_DIR / "customer_templates.json"

ZONE_TYPES = {
    "line_items":    {"key": "zone_line_items",    "color": "#B91C1C"},
    "po_number":     {"key": "zone_po_number",     "color": "#059669"},
    "material_code": {"key": "zone_material_code", "color": "#1428A0"},
    "quantity":      {"key": "zone_quantity",      "color": "#7C3AED"},
    "description":   {"key": "zone_description",   "color": "#D97706"},
    "unit_price":    {"key": "zone_unit_price",    "color": "#DC2626"},
    "amount":        {"key": "zone_amount",        "color": "#0891B2"},
}

# Zone types shown in the recommended group vs the advanced group
SIMPLE_TYPES = ["line_items", "po_number"]
MANUAL_TYPES = ["material_code", "quantity", "description", "unit_price", "amount"]


def zone_label(ztype: str) -> str:
    info = ZONE_TYPES.get(ztype, ZONE_TYPES["material_code"])
    return T(info["key"])


def zone_color(ztype: str) -> str:
    return ZONE_TYPES.get(ztype, ZONE_TYPES["material_code"])["color"]


class TemplateEditor(tk.Toplevel):
    def __init__(self, parent, customer_name: str = "", pdf_path: str = ""):
        super().__init__(parent)
        self.title(T("editor_title"))
        self.geometry("1220x820")
        self.minsize(1000, 700)
        self.configure(bg="#F4F6FB")

        self.customer_name = customer_name
        self.pdf_path = pdf_path
        self.current_page = 0
        self.total_pages = 0
        self.tk_image = None
        self.scale = 1.0
        self.pdf_page_size = (0, 0)

        self.zones = []
        self.drawing = False
        self.drag_start = None
        self.current_rect = None
        self.selected_zone_type = tk.StringVar(value="line_items")

        self._load_existing_template()
        self._build_ui()
        self._refresh_zone_list()

        if self.pdf_path:
            self._load_pdf(self.pdf_path, keep_zones=True)
        elif self.zones:
            messagebox.showinfo(
                T("sample_pdf_missing_title"),
                T("sample_pdf_missing_msg",
                  customer=self.customer_name, n=len(self.zones))
            )

    # ══════════════════════════════════════════
    # Template load
    # ══════════════════════════════════════════
    def _load_existing_template(self):
        if not TEMPLATES_PATH.exists():
            return
        try:
            data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
            tmpl = data.get("customers", {}).get(self.customer_name)
            if tmpl:
                self.zones = [dict(z) for z in tmpl.get("zones", [])]
                if not self.pdf_path:
                    sample = tmpl.get("sample_pdf", "")
                    if sample and Path(sample).exists():
                        self.pdf_path = sample
        except Exception as e:
            print(f"Template load error: {e}")

    # ══════════════════════════════════════════
    # UI
    # ══════════════════════════════════════════
    def _build_ui(self):
        toolbar = tk.Frame(self, bg="#001E62", height=48)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        tk.Label(toolbar, text=T("editor_title"),
                 bg="#001E62", fg="white",
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=16, pady=10)

        tk.Label(toolbar, text=T("editor_customer"), bg="#001E62", fg="#8FA0CC",
                 font=("Segoe UI", 10)).pack(side="left", padx=(16, 4))
        self.customer_var = tk.StringVar(value=self.customer_name)
        tk.Entry(toolbar, textvariable=self.customer_var,
                 font=("Segoe UI", 10), width=22).pack(side="left", pady=10)

        self._tbtn(toolbar, f"\U0001F4C2 {T('editor_open_pdf')}",
                   self._open_pdf).pack(side="left", padx=8)
        self._tbtn(toolbar, f"\U0001F4BE {T('editor_save')}",
                   self._save_template, "#059669").pack(side="left", padx=4)

        # status bar
        status = tk.Frame(self, bg="#E8EEFF", height=26)
        status.pack(fill="x")
        status.pack_propagate(False)
        self.text_status = tk.Label(status, text=T("editor_status_init"),
                                    bg="#E8EEFF", fg="#6B7280",
                                    font=("Segoe UI", 9), anchor="w", padx=12)
        self.text_status.pack(side="left", fill="y")
        self.zone_count_label = tk.Label(status, text="", bg="#E8EEFF",
                                         fg="#1428A0", font=("Segoe UI", 9, "bold"),
                                         padx=12)
        self.zone_count_label.pack(side="right", fill="y")

        body = tk.Frame(self, bg="#F4F6FB")
        body.pack(fill="both", expand=True)
        self._build_side(body)
        self._build_canvas(body)

    def _build_side(self, parent):
        side = tk.Frame(parent, bg="#FFFFFF", width=250,
                        highlightbackground="#C8CFDE", highlightthickness=1)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        tk.Label(side, text=T("editor_step1"), bg="#FFFFFF",
                 font=("Segoe UI", 10, "bold"),
                 fg="#001E62").pack(anchor="w", padx=12, pady=(12, 2))

        # --- Recommended group -------------------------------------
        tk.Label(side, text=T("editor_group_simple"), bg="#FFFFFF",
                 fg="#059669", font=("Segoe UI", 8, "bold")
                 ).pack(anchor="w", padx=12, pady=(4, 2))

        for key in SIMPLE_TYPES:
            info = ZONE_TYPES[key]
            label = f"  {T(info['key'])}"
            if key == "line_items":
                label += f"   ★"
            tk.Radiobutton(
                side, text=label,
                variable=self.selected_zone_type, value=key,
                bg="#FFFFFF", fg=info["color"],
                font=("Segoe UI", 10, "bold"),
                selectcolor="#E8EEFF", activebackground="#FFFFFF",
                cursor="hand2", anchor="w",
                command=self._on_zone_type_change
            ).pack(anchor="w", padx=14, pady=1, fill="x")

        self.type_hint = tk.Label(
            side, text=T("editor_li_hint"), bg="#F0FDF4", fg="#166534",
            font=("Segoe UI", 8), justify="left", wraplength=222,
            padx=8, pady=6, anchor="w"
        )
        self.type_hint.pack(fill="x", padx=10, pady=(4, 6))

        # --- Advanced group (collapsed by default) -----------------
        self.show_manual = tk.BooleanVar(value=False)
        self.manual_toggle = tk.Button(
            side, text=f"▸  {T('editor_group_manual')}",
            bg="#FFFFFF", fg="#6B7280", font=("Segoe UI", 8),
            relief="flat", anchor="w", padx=10, cursor="hand2",
            command=self._toggle_manual
        )
        self.manual_toggle.pack(fill="x", padx=4)

        self.manual_frame = tk.Frame(side, bg="#FFFFFF")
        for key in MANUAL_TYPES:
            info = ZONE_TYPES[key]
            tk.Radiobutton(
                self.manual_frame, text=f"  {T(info['key'])}",
                variable=self.selected_zone_type, value=key,
                bg="#FFFFFF", fg=info["color"],
                font=("Segoe UI", 9),
                selectcolor="#E8EEFF", activebackground="#FFFFFF",
                cursor="hand2", anchor="w",
                command=self._on_zone_type_change
            ).pack(anchor="w", padx=20, pady=1, fill="x")

        ttk.Separator(side, orient="horizontal").pack(fill="x", pady=8, padx=8)

        tk.Label(side, text=T("editor_step3"), bg="#FFFFFF",
                 font=("Segoe UI", 10, "bold"),
                 fg="#001E62").pack(anchor="w", padx=12, pady=(0, 4))

        lf = tk.Frame(side, bg="#FFFFFF")
        lf.pack(fill="both", expand=True, padx=8)
        sb = ttk.Scrollbar(lf)
        sb.pack(side="right", fill="y")
        self.zone_listbox = tk.Listbox(
            lf, font=("Segoe UI", 9), bg="#F8F9FC", relief="flat",
            selectbackground="#E8EEFF", selectforeground="#1428A0",
            height=12, yscrollcommand=sb.set
        )
        self.zone_listbox.pack(fill="both", expand=True)
        sb.config(command=self.zone_listbox.yview)
        self.zone_listbox.bind("<<ListboxSelect>>", self._on_zone_select)

        tk.Button(side, text=f"\U0001F5D1 {T('editor_delete_zone')}",
                  command=self._delete_zone,
                  bg="#FEE2E2", fg="#DC2626", font=("Segoe UI", 9),
                  relief="flat", padx=8, pady=6,
                  cursor="hand2").pack(fill="x", padx=8, pady=6)

        nav = tk.Frame(side, bg="#FFFFFF")
        nav.pack(fill="x", padx=8, pady=(0, 8))
        tk.Button(nav, text="◀", command=self._prev_page,
                  bg="#E8EEFF", fg="#1428A0", relief="flat",
                  font=("Segoe UI", 10, "bold"), width=3,
                  cursor="hand2").pack(side="left")
        self.page_label = tk.Label(nav, text=T("editor_page", cur=1, total=1),
                                   bg="#FFFFFF", fg="#6B7280", font=("Segoe UI", 9))
        self.page_label.pack(side="left", expand=True)
        tk.Button(nav, text="▶", command=self._next_page,
                  bg="#E8EEFF", fg="#1428A0", relief="flat",
                  font=("Segoe UI", 10, "bold"), width=3,
                  cursor="hand2").pack(side="right")

    def _toggle_manual(self):
        """Show or hide the advanced column-by-column zone types."""
        self.show_manual.set(not self.show_manual.get())
        if self.show_manual.get():
            self.manual_frame.pack(fill="x", after=self.manual_toggle)
            self.manual_toggle.config(text=f"▾  {T('editor_group_manual')}")
        else:
            self.manual_frame.pack_forget()
            self.manual_toggle.config(text=f"▸  {T('editor_group_manual')}")

    def _on_zone_type_change(self):
        """Update the contextual hint for the selected zone type."""
        z = self.selected_zone_type.get()
        if z == "line_items":
            self.type_hint.config(text=T("editor_li_hint"),
                                  bg="#F0FDF4", fg="#166534")
        elif z == "po_number":
            self.type_hint.config(text=T("editor_step2_hint"),
                                  bg="#F0FDF4", fg="#166534")
        else:
            self.type_hint.config(text=T("editor_manual_hint"),
                                  bg="#FFF7ED", fg="#9A3412")

    def _build_canvas(self, parent):
        frame = tk.Frame(parent, bg="#525252")
        frame.pack(side="left", fill="both", expand=True)

        hs = ttk.Scrollbar(frame, orient="horizontal")
        vs = ttk.Scrollbar(frame, orient="vertical")
        hs.pack(side="bottom", fill="x")
        vs.pack(side="right", fill="y")

        self.canvas = tk.Canvas(frame, bg="#525252",
                                xscrollcommand=hs.set, yscrollcommand=vs.set,
                                cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        hs.config(command=self.canvas.xview)
        vs.config(command=self.canvas.yview)

        self.canvas.bind("<ButtonPress-1>",  self._on_drag_start)
        self.canvas.bind("<B1-Motion>",       self._on_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self.canvas.bind("<Motion>",          self._on_mouse_move)

        self.coord_label = tk.Label(frame, text="x: 0  y: 0",
                                    bg="#374151", fg="#9CA3AF",
                                    font=("Consolas", 9), anchor="w")
        self.coord_label.place(relx=0, rely=1, anchor="sw", x=4, y=-2)

    # ══════════════════════════════════════════
    # PDF load & render
    # ══════════════════════════════════════════
    def _open_pdf(self):
        path = filedialog.askopenfilename(
            title=T("dlg_select_pdf"),
            filetypes=[("PDF", "*.pdf"), ("All Files", "*.*")]
        )
        if path:
            self._load_pdf(path)

    def _load_pdf(self, path: str, keep_zones: bool = False):
        if not FITZ_AVAILABLE:
            messagebox.showerror("Missing Library",
                                 "PyMuPDF is required.\n\npip install PyMuPDF")
            return
        if not PIL_AVAILABLE:
            messagebox.showerror("Missing Library",
                                 "Pillow is required.\n\npip install Pillow")
            return

        if not keep_zones and self.zones and path != self.pdf_path:
            if not messagebox.askyesno(T("keep_zones_title"),
                                       T("keep_zones_msg", n=len(self.zones))):
                self.zones = []

        self.pdf_path = path
        self.pdf_doc = fitz.open(path)
        self.total_pages = len(self.pdf_doc)
        self.current_page = 0

        if not self.customer_var.get():
            import re
            stem = Path(path).stem
            name = re.sub(r"[_\-]?\d{4,}", "", stem).strip("_- .")
            self.customer_var.set(name or stem)

        self._render_page()
        self._refresh_zone_list()
        self._check_text_layer()

    def _check_text_layer(self):
        """Report text-layer status in the status bar only (no popup)."""
        if not hasattr(self, "pdf_doc"):
            return
        total_chars = sum(len(p.get_text().strip()) for p in self.pdf_doc)

        engine, ready = "", False
        try:
            import engine as ocr_engine
            st = ocr_engine.status_summary()
            ready, engine = st["available"], st["engine"]
        except Exception:
            pass

        if total_chars < 20:
            if ready:
                self.text_status.config(
                    text="\U0001F50D " + T("text_layer_ocr_ready", engine=engine),
                    fg="#1428A0")
            else:
                self.text_status.config(
                    text="⚠ " + T("text_layer_no_ocr"), fg="#D97706")
        else:
            msg = "✅ " + T("text_layer_ok", n=format(total_chars, ","))
            if ready:
                msg += "   |   " + T("ocr_standby", engine=engine)
            self.text_status.config(text=msg, fg="#059669")

    def _render_page(self):
        if not FITZ_AVAILABLE or not hasattr(self, "pdf_doc"):
            return

        page = self.pdf_doc[self.current_page]
        self.pdf_page_size = (page.rect.width, page.rect.height)

        RENDER_DPI = 120
        mat = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)
        pix = page.get_pixmap(matrix=mat)
        self.scale = 72 / RENDER_DPI

        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        self.tk_image = ImageTk.PhotoImage(img)

        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_image)
        self.canvas.configure(scrollregion=(0, 0, pix.width, pix.height))

        self._redraw_zones()

        n = sum(1 for z in self.zones if z.get("page") == self.current_page)
        label = T("editor_page", cur=self.current_page + 1, total=self.total_pages)
        if n:
            label += "  " + T("editor_zones_on_page", n=n)
        self.page_label.config(text=label)

    def _redraw_zones(self):
        """Repaint every zone on the current page. Clears all overlay layers
        first so selection highlights and drag previews cannot linger."""
        self.canvas.delete("zone")
        self.canvas.delete("highlight")
        self.canvas.delete("preview")

        sel = self.zone_listbox.curselection() if hasattr(self, "zone_listbox") else ()
        sel_idx = sel[0] if sel else -1

        for i, z in enumerate(self.zones):
            if z.get("page") == self.current_page:
                self._draw_zone_rect(z, selected=(i == sel_idx))

    def _draw_zone_rect(self, zone: dict, selected: bool = False):
        """
        Draw one zone as a single solid rectangle with a title tab.
        Selection is shown by thickening the same rectangle - no extra dashed
        box is drawn, so nothing can be mistaken for a second zone.
        """
        s = 1 / self.scale if self.scale else 1
        cx0, cy0 = zone["x0"] * s, zone["y0"] * s
        cx1, cy1 = zone["x1"] * s, zone["y1"] * s
        color = zone_color(zone.get("type"))
        label = zone_label(zone.get("type"))

        self.canvas.create_rectangle(
            cx0, cy0, cx1, cy1,
            outline=color, width=3 if selected else 2,
            fill="", tags="zone"
        )

        tw = len(label) * 6 + 10
        self.canvas.create_rectangle(cx0, cy0 - 15, cx0 + tw, cy0,
                                     fill=color, outline=color, tags="zone")
        self.canvas.create_text(cx0 + 5, cy0 - 13, text=label, anchor="nw",
                                fill="#FFFFFF", font=("Segoe UI", 8, "bold"),
                                tags="zone")

    # ══════════════════════════════════════════
    # Drag events
    # ══════════════════════════════════════════
    def _on_drag_start(self, event):
        if not hasattr(self, "pdf_doc"):
            return
        self.drawing = True
        self.drag_start = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))

    def _on_drag_move(self, event):
        if not self.drawing or not self.drag_start:
            return
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self.canvas.delete("preview")
        self.current_rect = self.canvas.create_rectangle(
            self.drag_start[0], self.drag_start[1], cx, cy,
            outline=zone_color(self.selected_zone_type.get()),
            width=2, dash=(4, 2), tags="preview"
        )

    def _on_drag_end(self, event):
        if not self.drawing or not self.drag_start:
            return
        self.drawing = False
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

        self.canvas.delete("preview")
        self.current_rect = None

        if abs(cx - self.drag_start[0]) < 10 or abs(cy - self.drag_start[1]) < 10:
            return

        x0 = round(min(self.drag_start[0], cx) * self.scale, 2)
        y0 = round(min(self.drag_start[1], cy) * self.scale, 2)
        x1 = round(max(self.drag_start[0], cx) * self.scale, 2)
        y1 = round(max(self.drag_start[1], cy) * self.scale, 2)

        ztype = self.selected_zone_type.get()
        name = simpledialog.askstring(
            T("zone_name_title"), T("zone_name_prompt"),
            parent=self, initialvalue=zone_label(ztype)
        )
        if name is None:
            return

        zone = {"type": ztype, "label": name, "page": self.current_page,
                "x0": x0, "y0": y0, "x1": x1, "y1": y1}
        self.zones.append(zone)
        self._refresh_zone_list()
        self._redraw_zones()

    def _on_mouse_move(self, event):
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self.coord_label.config(
            text=f"PDF: x={round(cx * self.scale, 1)}  y={round(cy * self.scale, 1)}"
                 f"   |   Canvas: x={int(cx)}  y={int(cy)}"
        )

    # ══════════════════════════════════════════
    # Zone list
    # ══════════════════════════════════════════
    def _refresh_zone_list(self):
        if not hasattr(self, "zone_listbox"):
            return
        self.zone_listbox.delete(0, "end")

        for i, z in enumerate(self.zones):
            pg = z.get("page", 0) + 1
            w = round(z.get("x1", 0) - z.get("x0", 0))
            h = round(z.get("y1", 0) - z.get("y0", 0))
            self.zone_listbox.insert("end", f"[P{pg}] {zone_label(z.get('type'))} · {w}×{h}")
            self.zone_listbox.itemconfig(i, foreground=zone_color(z.get("type")))

        if hasattr(self, "zone_count_label"):
            present = {z.get("type") for z in self.zones}
            missing = []
            if not ({"line_items", "material_code"} & present):
                missing.append(T("zone_line_items"))
            if "po_number" not in present:
                missing.append(T("zone_po_number"))

            txt = T("editor_zone_count", n=len(self.zones))
            if missing:
                txt += "   ⚠ " + T("editor_missing", types=", ".join(missing))
            self.zone_count_label.config(
                text=txt, fg="#D97706" if missing else "#059669")

    def _on_zone_select(self, event=None):
        """Selecting a zone jumps to its page, thickens its outline and
        scrolls it into view. No additional shape is drawn."""
        sel = self.zone_listbox.curselection()
        if not sel:
            return
        zone = self.zones[sel[0]]
        if zone.get("page", 0) != self.current_page:
            self.current_page = zone.get("page", 0)
            self._render_page()
        else:
            self._redraw_zones()
        self._scroll_to_zone(zone)

    def _scroll_to_zone(self, zone: dict):
        s = 1 / self.scale if self.scale else 1
        try:
            bbox = self.canvas.bbox("all")
            if bbox and bbox[2] and bbox[3]:
                self.canvas.xview_moveto(max(0, (zone["x0"] * s - 120) / bbox[2]))
                self.canvas.yview_moveto(max(0, (zone["y0"] * s - 120) / bbox[3]))
        except Exception:
            pass

    def _delete_zone(self):
        sel = self.zone_listbox.curselection()
        if not sel:
            return
        self.zones.pop(sel[0])
        self._refresh_zone_list()
        self._redraw_zones()

    def _prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._render_page()
            self._refresh_zone_list()

    def _next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._render_page()
            self._refresh_zone_list()

    # ══════════════════════════════════════════
    # Save
    # ══════════════════════════════════════════
    def _save_template(self):
        customer = self.customer_var.get().strip()
        if not customer:
            messagebox.showwarning(T("input_error"), T("enter_customer"))
            return
        if not self.zones:
            messagebox.showwarning(T("no_zones_title"), T("no_zones_msg"))
            return

        if TEMPLATES_PATH.exists():
            try:
                data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
            except Exception:
                data = {"_version": "3.0", "customers": {}}
        else:
            data = {
                "_readme": "Customer-specific PDF extraction zone templates. "
                           "Generated by Template Editor.",
                "_version": "3.0",
                "customers": {}
            }

        # Store a content fingerprint so this template can still be recognised
        # when a future PDF's filename does not contain the customer name.
        fingerprint = []
        try:
            from engine import build_fingerprint
            if hasattr(self, "pdf_doc"):
                head = "\n".join(self.pdf_doc[i].get_text()
                                 for i in range(min(2, len(self.pdf_doc))))
                fingerprint = build_fingerprint(head)
        except Exception as e:
            print(f"Fingerprint build failed: {e}")

        data.setdefault("customers", {})[customer] = {
            "sample_pdf": str(self.pdf_path),
            "pdf_size": {"width": self.pdf_page_size[0], "height": self.pdf_page_size[1]},
            "fingerprint": fingerprint,
            "zones": self.zones,
            "updated_at": datetime.now().isoformat(),
        }

        TEMPLATES_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        messagebox.showinfo(T("save_ok_title"),
                            T("save_ok_msg", customer=customer, n=len(self.zones)))
        self.destroy()

    # ══════════════════════════════════════════
    def _tbtn(self, parent, text, cmd, bg="#1428A0"):
        return tk.Button(parent, text=text, command=cmd,
                         bg=bg, fg="white", font=("Segoe UI", 9, "bold"),
                         relief="flat", padx=12, pady=6, cursor="hand2", bd=0,
                         activebackground="#0D1FA0", activeforeground="white")


def tpl_main():
    """Open the zone-template editor window."""
    root = tk.Tk()
    root.withdraw()
    TemplateEditor(root).mainloop()


# ==========================================================================
#  SECTION: self test  (formerly selftest.py)
# ==========================================================================

import sys
import os
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

VERBOSE = "-v" in sys.argv
RESULTS = []

# Each run gets its own scratch directory, created INSIDE the project rather
# than in the shared OS temp folder. On managed Windows PCs that temp path is
# often redirected (e.g. C:\Users\Public\Documents\...\CreatorTemp) and watched
# by a real-time scanner that opens every new .xlsx the instant it appears,
# producing WinError 32 for reasons unrelated to the code. The directory is
# removed when the run finishes.
def _make_scratch() -> Path:
    base = Path(__file__).parent / "data_cache" / "_selftest"
    try:
        base.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="run_", dir=base))
    except OSError:
        return Path(tempfile.mkdtemp(prefix="mce_selftest_"))


_SCRATCH = _make_scratch()


def scratch(name: str) -> Path:
    """A unique, writable path inside this run's scratch directory."""
    return _SCRATCH / name


def check(name):
    def deco(fn):
        RESULTS.append((name, fn))
        return fn
    return deco


# ══════════════════════════════════════════════
# 1. Imports & dependencies
# ══════════════════════════════════════════════
@check("Dependencies installed")
def t_deps():
    """
    The rasteriser is an either/or requirement, not a PyMuPDF requirement.

    This test used to import `pymupdf` (or `fitz`) directly, so it failed on a
    machine that had pypdfium2 - while the engine itself was perfectly happy
    with either. A test that disagrees with the code about what is installed
    teaches people to ignore it.
    """
    import pdfplumber, pypdf, openpyxl          # noqa
    from PIL import Image                        # noqa

    import engine as ex
    if not ex.render_backend():
        raise ImportError(
            "no PDF rasteriser - install PyMuPDF or pypdfium2 (needed to read "
            "scanned POs, and to crop zone templates out of any PDF)"
        )


@check("Application modules import")
def t_modules():
    import engine      # noqa
    import engine                              # noqa  (lang is now in this file)
    import engine as ocr_engine                     # noqa


# ══════════════════════════════════════════════
# 2. PO number parsing
# ══════════════════════════════════════════════
@check("PO number parsing")
def t_po():
    from engine import clean_po_from_zone
    cases = [
        ("Purchase Order Number\n0736499", "0736499"),
        ("PO #: 4046792  Date: 6/19/2026", "4046792"),
        ("P.O. Number: 2170541", "2170541"),
        ("PO Number\nPhone: (201) 229-4000\n4046792", "4046792"),
        ("PO No. BM736499", "BM736499"),
        ("Date: 5/28/2026", ""),
        ("Phone", ""),
        ("PURCHASE ORDER\nP.O. # 0736499\nPage 1 of 1", "0736499"),
    ]
    for text, want in cases:
        got = clean_po_from_zone(text)
        assert got == want, f"{text!r}: want {want!r}, got {got!r}"


# ══════════════════════════════════════════════
# 3. Code matching / ghost-code rejection
# ══════════════════════════════════════════════
@check("Backbone matching & ghost-code rejection")
def t_matching():
    from engine import (BackboneIndex, extract_codes_from_line,
                              looks_like_scrambled)
    REF = {"DW80CG4051SR": {"description": "DW", "category": "MDA"},
           "E3-DW": {"description": "Install", "category": "Service"}}
    bb = BackboneIndex(REF)

    # variant + printed-form preservation
    r = extract_codes_from_line(
        'Samsung - Dishwasher - (DW80CG4051SRAA) DISWH8W0ACSGH4E0R5 1 EA', bb, None)
    codes = [x["code"] for x in r]
    assert "DW80CG4051SRAA" in codes, codes
    assert "DISWH8W0ACSGH4E0R5" not in codes, "ghost code leaked"

    # hyphen-wrapped code
    r2 = extract_codes_from_line('DISHWASHER Dacor (Model E3- DW) - Install', bb, None)
    assert any(x["code"] == "E3-DW" for x in r2), r2

    assert looks_like_scrambled("DISWH8W0ACSGH4E0R5")
    assert not looks_like_scrambled("DW80CG4051SRAA")

    # A market suffix is structure, not interleaving. Counting transitions
    # across the raw string made '/' and '-' count as letter<->digit flips, so
    # every '/A3', '/A5', '/A2' code was reported as scrambled and dropped from
    # the parenthesised path - silently, before the backbone lookup ran.
    for real in ("DVE45T6000W/A3", "ME16A4021AS/A2", "WF45T6000AW/A5",
                 "L-INST/E3-DW", "RF18A5101SR/AA", "DVG45T6000W/A3"):
        assert not looks_like_scrambled(real), \
            f"real market-suffix code flagged as scrambled: {real}"
    # ...and genuine interleaved junk is still rejected.
    for junk in ("DISWH8W0ACSGH4E0R5", "W0ACSGH4E0R5DW80CG"):
        assert looks_like_scrambled(junk), f"ghost code not caught: {junk}"

    # The end-to-end consequence: with NO backbone list, a parenthesised
    # market-suffix code must still be reported (it used to come back empty).
    empty = BackboneIndex({})
    for real in ("DVE45T6000W/A3", "ME16A4021AS/A2", "WF45T6000AW/A5"):
        got = extract_codes_from_line(f"DISHWASHER ({real}) 1 EA", empty)
        assert any(x["code"] == real for x in got), f"{real} lost: {got}"


@check("One code per quantity (row rule)")
def t_one_per_row():
    from engine import BackboneIndex
    from engine import extract_lines_with_backbone, load_config, compile_patterns
    REF = {"DW80CG4051SR": {"description": "DW", "category": "MDA"},
           "ME21DG6300SR": {"description": "MW", "category": "MDA"}}
    inc, _ = compile_patterns(load_config())
    page = ('A - (DW80CG4051SRAA) 1 EA $ 411.00\n'
            'B - (ME21DG6300SRAA) 2 EA $ 209.00\n')
    rev = []
    recs = extract_lines_with_backbone(page, [], BackboneIndex(REF), inc,
                                       "PO1", 1, "t.pdf", 24, review=rev)
    got = {(r["material_code"], r["quantity"]) for r in recs}
    assert got == {("DW80CG4051SRAA", "1"), ("ME21DG6300SRAA", "2")}, got


# ══════════════════════════════════════════════
# 4. Line-items table parsing
# ══════════════════════════════════════════════
@check("Multiple confirmed codes in one block are ALL kept")
def t_multi_confirmed():
    """
    Mirrors PO 56098288: three real (backbone-confirmed) codes end up in one
    merged block. All three must be emitted, each with the quantity from its
    own row - not just the longest one.
    """
    from engine import BackboneIndex, select_row_codes, extract_codes_from_line
    from engine import extract_lines_with_backbone, load_config, compile_patterns

    REF = {"DVE45T6000W": {"description": "Dryer", "category": "Dryer"},
           "RS22T5201SR": {"description": "Fridge SBS", "category": "Refrigerator"},
           "WF45T6000AW": {"description": "Washer", "category": "Washer"}}
    bb = BackboneIndex(REF)

    # select_row_codes: all confirmed kept, ghost rejected
    cands = extract_codes_from_line(
        "DVE45T6000W RS22T5201SR/AA WF45T6000AW GH0STC0DE99XX 1 EA", bb, None)
    keep, rejected = select_row_codes(cands, bb)
    kept = {c["code"] for c in keep}
    assert {"DVE45T6000W", "RS22T5201SR/AA", "WF45T6000AW"} <= kept, kept
    assert all(c.get("backbone_code") for c in keep)

    # end-to-end: each code keeps the qty on its own line
    page = ("Dryer DVE45T6000W 1 EA\n"
            "Refrigerator RS22T5201SR/AA 1 EA\n"
            "Washer WF45T6000AW 1 EA\n")
    inc, _ = compile_patterns(load_config())
    recs = extract_lines_with_backbone(page, [], bb, inc, "56098288", 1,
                                       "t.pdf", 24, review=[])
    got = {(r["material_code"], r["quantity"]) for r in recs}
    want = {("DVE45T6000W", "1"), ("RS22T5201SR/AA", "1"), ("WF45T6000AW", "1")}
    assert got == want, got


@check("Real-PO failure modes: base / glued / OCR-confusion / wrapped")
def t_failure_modes():
    """
    The four failure modes found in production debugging:
      56098288 : PO prints base model, backbone stores BASE/MARKET
      246155   : OCR glues code to description; OCR swaps 5<->S
      BM736499 : narrow MODEL column wraps the code across lines
    """
    from engine import BackboneIndex, extract_codes_from_line
    from engine import (extract_lines_with_backbone, repair_wrapped_codes,
                           load_config, compile_patterns)

    REF = {"DVE45T6000W/A3": {"description": "Dryer", "category": "Laundry"},
           "WF45B6300AP/US": {"description": "Washer", "category": "Laundry"},
           "DW80CG4051SRAA": {"description": "DW", "category": "Dishwasher"}}
    bb = BackboneIndex(REF)

    def hit(text):
        r = extract_codes_from_line(text, bb, None)
        return r[0]["backbone_code"] if r else ""

    # 1) base model printed, backbone stores BASE/MARKET
    assert hit("Samsung Dryer DVE45T6000W EA 1") == "DVE45T6000W/A3"
    # 2) code glued to a description word (OCR lost the space)
    assert hit("2 EA SSW WF45B6300APPLATINUM 599.00") == "WF45B6300AP/US"
    # 3) OCR character confusion (5 -> S)
    assert hit("2 EA SSW WF4SB6300AP PLATIN 599.00") == "WF45B6300AP/US"

    # 4) wrapped code + leading-count quantity (BrandsMart layout)
    lines = ["51DBA/HYBRD/3RDRCK/AUTRL",
             "DW80CG4051S",
             "24 SAMSU UPC: 887276772905 FDC $383.20 $383.20 $9,196.80",
             "R",
             "Part #:"]
    repaired = repair_wrapped_codes(lines, bb)
    joined = "\n".join(repaired)
    assert "DW80CG4051SR" in joined, repaired
    # originals must survive untouched (non-destructive repair)
    for orig in lines:
        assert orig in repaired, f"original line lost: {orig!r}"

    inc, _ = compile_patterns(load_config())
    recs = extract_lines_with_backbone("\n".join(lines), [], bb, inc,
                                       "BM736499", 1, "t.pdf", 24, review=[])
    got = {(r["material_code"], r["quantity"]) for r in recs}
    assert ("DW80CG4051SR", "24") in got, got


@check("Output code is clean (no description glued, no OCR misread)")
def t_clean_printed_code():
    """
    246155: OCR produced 'WF45B6300APPLATINUM' and 'WF4SB6300AP'.
    The backbone match is correct, but the PUBLISHED code must be the model
    number only - 'PLATINUM' is a colour word, not part of the code.
    """
    from engine import BackboneIndex, extract_codes_from_line
    REF = {"WF45B6300AP/US": {"description": "Washer", "category": "Laundry"},
           "DVE45B6300P/A3": {"description": "Dryer", "category": "Laundry"},
           "DW80CG4051SRAA": {"description": "DW", "category": "Dishwasher"}}
    bb = BackboneIndex(REF)

    def printed(text):
        r = extract_codes_from_line(text, bb, None)
        return r[0]["code"] if r else ""

    # glued description word must be stripped from the OUTPUT
    assert printed("0008 EA SSw WF45B6300APPLATINUM 599.00") == "WF45B6300AP"
    assert printed("2 EA ssw DVE45B6300PPLATINUM 599.00") == "DVE45B6300P"
    # OCR character swap must not be published either
    assert printed("2 EA SSW WF4SB6300AP PLATIN 599.00") == "WF45B6300AP"
    # a genuine market suffix in the document IS preserved
    assert printed("Samsung - (DW80CG4051SRAA) 1 EA") == "DW80CG4051SRAA"


@check("Quantity rejects MFG numbers and line numbers")
def t_qty_sanity():
    from engine import parse_quantity
    import engine as tp

    # MFG number next to EA must not become the quantity
    q, _ = parse_quantity("0008  12816  EA  SSw  WF45B6300APPLATINUM  599.00")
    assert q != "12816", q
    # genuine leading count still works
    assert parse_quantity("0006  12816  2 EA SSW  WF4SB6300AP")[0] == "2"
    assert parse_quantity("24 SAMSU DW80CG4051SR")[0] in ("24", "")
    # cell-level validation
    assert tp.is_quantity_anchor({"cells": {"quantity": "2"}})
    assert not tp.is_quantity_anchor({"cells": {"quantity": "12816"}})
    assert not tp.is_quantity_anchor({"cells": {"quantity": "0008"}})


@check("PO number recovery without a label")
def t_po_recovery():
    """
    BM736499: heading row and value row are separate, so no label-anchored
    pattern can work. Recovery uses the filename plus body repetition.
    """
    from engine import po_from_filename_and_text

    body = ("P.O. Date P.O. Number P.O. Type\n"
            "Bill To: Interbond of America 04/16/2026 BM736499 Standard\n"
            "BM736499 4/16/2026 Page 1 of 1\n")
    assert po_from_filename_and_text("PO_0736499.pdf", body) == "BM736499"

    body2 = ("SAMSUNG ELECTRONICS\n"
             "Order 4046792 dated 06/19/2026\n"
             "10 EA 06/19/2026 RF18A5101SR 816.00\n"
             "4046792 Page 1 of 3\n")
    assert po_from_filename_and_text(
        "SAMSUNGNJ.PO4046792.06192026.pdf", body2) == "4046792"

    # nothing plausible -> empty, never a guess
    assert po_from_filename_and_text("x.pdf", "no numbers here") == ""


@check("Glued description word is trimmed from the code")
def t_glued_trim():
    """WF45B6300APPLATINUM must be reported as WF45B6300AP, not with PLATINUM."""
    from engine import BackboneIndex, extract_codes_from_line
    REF = {"WF45B6300AP/US": {"description": "Washer", "category": "Laundry"},
           "DVE45B6300P/A3": {"description": "Dryer", "category": "Laundry"}}
    bb = BackboneIndex(REF)
    for text, want in [
        ("0008 12816 EA SSw WF45B6300APPLATINUM 599.00", "WF45B6300AP"),
        ("0009 12839 2 EA SSW DVE45B6300PPLATINUM 599.00", "DVE45B6300P"),
    ]:
        r = extract_codes_from_line(text, bb, None)
        assert r, text
        got = r[0]["code"]
        assert got == want, f"{text}: want {want}, got {got}"
        assert "PLATIN" not in got


@check("Quantity guards: MFG number rejected, money fallback")
def t_qty_guards():
    from engine import parse_quantity
    # 12816 sits next to EA but is a manufacturer number, not a quantity
    q, _ = parse_quantity("0008 12816 EA SSw WF45B6300AP 599.00")
    assert q != "12816", f"MFG number accepted as qty: {q}"
    # normal cases still work
    assert parse_quantity("2 EA SSW DVG45B6300P")[0] == "2"
    assert parse_quantity("24 SAMSU DW80CG4051SR")[0] == "24"
    # a bare 4+ digit value with no unit is never a quantity (MAX_BARE_QTY)
    assert parse_quantity("0008 SSW WF45B6300AP 12816")[0] == ""


@check("Money columns: Unit Cost beats PO Cost, Extended Cost is amount")
def t_money_roles():
    from engine import classify_header
    assert classify_header("Unit Cost") == "unit_price"
    assert classify_header("Unit Price") == "unit_price"
    assert classify_header("PO COST") == "unit_price"
    assert classify_header("EXT COST") == "amount"
    assert classify_header("Extended Cost") == "amount"
    assert classify_header("Cost") in ("unit_price", "amount")


@check("Money recovered from page text when zone misses cost columns")
def t_money_enrich():
    from engine import enrich_money_from_pages
    from engine import BackboneIndex
    bb = BackboneIndex({"DVE45T6000W/A3": {"description": "", "category": ""}})
    recs = [{"material_code": "DVE45T6000W", "backbone_code": "DVE45T6000W/A3",
             "quantity": "1", "unit_price": "", "amount": "", "page": 1}]
    pages = [{"page_num": 1, "text":
              "583-DVE45T6000W Samsung Dryer DVE45T6000W EA 1 $ 521.00 "
              "$ 521.00 $ 38.29"}]
    n = enrich_money_from_pages(recs, pages, bb)
    assert n == 1, n
    # No arithmetic cross-check any more: the LAST two printed money tokens
    # are unit price and amount, exactly as the line prints them.
    assert recs[0]["unit_price"] == "521.00", recs[0]
    assert recs[0]["amount"] == "38.29", recs[0]


@check("Money on a NEIGHBOURING line (PO 2170541 layout)")
def t_money_adjacent_line():
    """
    2170541 prints the code on its own line and the qty/price on the line
    above it:
        Samsung - Dishwasher 24" - Stainless -   1 EA  $ 411.00  $ 411.00
        (DW80CG4051SRAA)
    The money must still be attached to the code.
    """
    from engine import enrich_money_from_pages
    from engine import BackboneIndex
    bb = BackboneIndex({"DW80CG4051SRAA": {"description": "", "category": ""}})
    recs = [{"material_code": "DW80CG4051SRAA",
             "backbone_code": "DW80CG4051SRAA",
             "quantity": "", "unit_price": "", "amount": "", "page": 1}]
    pages = [{"page_num": 1, "text":
              'Option Selection Style/Color Qty Unit Unit Cost Cost\n'
              'Samsung - Dishwasher 24" - Stainless - 1 EA $ 411.00 $ 411.00 *\n'
              '(DW80CG4051SRAA)\n'
              'Dishwasher/ 3-cycle Dishwasher Front Controls -\n'}]
    enrich_money_from_pages(recs, pages, bb)
    assert recs[0]["unit_price"] == "411.00", recs[0]
    assert recs[0]["amount"] == "411.00", recs[0]
    assert recs[0]["quantity"] == "1", recs[0]


@check("Spec figures on a neighbouring line are not read as a price")
def t_money_spec_line_rejected():
    """
    PO BM736499 wraps the code across lines and prints the spec text ABOVE it,
    the cost columns BELOW:

        2.1CF/LEDDIS/AUTCONN/GLSCNT          <- capacity, not money
        ME21DG6300S
        24 SAMSU UPC: 887276827308 FDC $263.20 $263.20 $6,316.80

    Taking the nearest neighbour containing a number made 2.1 the unit cost, so
    a $263.20 microwave was reported at $2.10. Two defences: a figure glued to
    a unit ('2.1CF') is not money, and 24 x 263.20 = 6,316.80 identifies the
    real cost line whichever side of the code it sits on.
    """
    from engine import enrich_money_from_pages, money_values
    from engine import BackboneIndex

    # spec figures are rejected outright
    assert money_values("2.1CF/LEDDIS/AUTCONN/GLSCNT") == []
    assert money_values("30IN 120V 4.5CF") == []
    # a currency word may still trail a real amount
    assert money_values("TOTAL 263.20USD") == ["263.20"]
    # UPC / part numbers are not prices when cents are required
    assert money_values("UPC: 887276827308", cents_only=True) == []

    bb = BackboneIndex({"ME21DG6300SR": {"description": "", "category": ""}})
    recs = [{"material_code": "ME21DG6300SR", "backbone_code": "ME21DG6300SR",
             "quantity": "24", "unit_price": "", "amount": "", "page": 1}]
    pages = [{"page_num": 1, "text":
              "Part #:\n"
              "2.1CF/LEDDIS/AUTCONN/GLSCNT\n"
              "ME21DG6300S\n"
              "24 SAMSU UPC: 887276827308 FDC $263.20 $263.20 $6,316.80\n"
              "R\n"}]
    enrich_money_from_pages(recs, pages, bb)
    assert recs[0]["unit_price"] == "263.20", recs[0]
    assert recs[0]["amount"] == "6316.80", recs[0]


@check("Cache key includes extraction logic")
def t_cache_key_logic():
    """
    Editing the extraction code must invalidate cached results, otherwise the
    app keeps serving stale output after an improvement.
    """
    import engine as ex
    sig1 = ex.config_signature()
    src = ex.BASE_DIR / "engine.py"
    st = src.stat()
    try:
        # Touch the file (content unchanged) and confirm the signature moves
        os.utime(src, (st.st_atime, st.st_mtime + 1))
        ex._SIG_CACHE["key"] = None          # drop the memo
        sig2 = ex.config_signature()
        assert sig1 != sig2, "logic change did not invalidate the cache"
    finally:
        os.utime(src, (st.st_atime, st.st_mtime))
        ex._SIG_CACHE["key"] = None


@check("Confirmed codes survive with or without a quantity")
def t_confirmed_survive_without_qty():
    """
    A line with no parseable quantity must still yield its confirmed codes.
    Regression guard: tying the ghost filter to quantity detection caused an
    extraction-rate drop across several POs.
    """
    from engine import BackboneIndex
    from engine import (extract_lines_with_backbone, load_config,
                           compile_patterns)
    REF = {"ME16A4021AS/AA": {"description": "MW", "category": "Cooking"},
           "NE63A6111SS/AA": {"description": "Range", "category": "Cooking"}}
    bb = BackboneIndex(REF)
    inc, _ = compile_patterns(load_config())
    page = ("24 SAMSU ME16A4021AS UPC: 887276532936 FDC $169.00\n"
            "24 SAMSU NE63A6111SS UPC: 887276509358 FDC $503.20\n")
    recs = extract_lines_with_backbone(page, [], bb, inc, "BM736499", 1,
                                      "t.pdf", 24, review=[])
    codes = {r["material_code"] for r in recs}
    assert {"ME16A4021AS", "NE63A6111SS"} <= codes, codes


@check("Quantity next to a code is never fused into it")
def t_no_qty_fusion():
    """
    'DVE45T6000W 1 EA' must not become 'DVE45T6000W1'. A bare digit is not a
    market suffix, and a token that already matches on its own is complete.
    """
    from engine import BackboneIndex, MARKET_SUFFIX
    from engine import repair_wrapped_codes

    assert not MARKET_SUFFIX.fullmatch("1"), "bare digit accepted as suffix"
    assert MARKET_SUFFIX.fullmatch("AA")
    assert MARKET_SUFFIX.fullmatch("A3")

    bb = BackboneIndex({"DVE45T6000W": {"description": "", "category": ""},
                        "WF45T6000AW": {"description": "", "category": ""}})
    assert bb.lookup("DVE45T6000W1")[0] == "", "quantity-fused code matched"

    lines = ["Dryer DVE45T6000W 1 EA", "Washer WF45T6000AW 1 EA"]
    out = repair_wrapped_codes(lines, bb)
    joined = " ".join(out)
    for ghost in ("DVE45T6000W1", "WF45T6000AW1"):
        assert ghost not in joined, f"{ghost} invented: {out}"


@check("Zone template also repairs wrapped codes (PO BM736499)")
def t_zone_wrapped_repair():
    """
    A zone template must not lose items the no-template path finds. BM736499
    wraps codes inside the MODEL column:
        DW80CG4051S
        24 SAMSU UPC: ... $9,196.80
        R
    The zone path previously skipped the repair and returned 3 of 6 items.
    """
    from engine import BackboneIndex
    from engine import parse_line_items_zone

    REF = {"DW80CG4051SRAA": {"description": "", "category": "Dishwasher"},
           "ME16A4021AS/AA": {"description": "", "category": "Microwave"}}
    bb = BackboneIndex(REF)

    def W(t, x0, x1, top):
        return {"text": t, "x0": x0, "x1": x1, "top": top, "bottom": top + 9}

    # header + one wrapped item + one intact item
    words = [W("QTY", 60, 85, 50), W("MODEL", 150, 195, 50),
             W("EXT", 400, 425, 50), W("COST", 430, 465, 50),
             W("DW80CG4051S", 150, 240, 70),
             W("24", 60, 75, 82), W("SAMSU", 90, 130, 82),
             W("9,196.80", 400, 460, 82),
             W("R", 150, 158, 94),
             W("24", 60, 75, 118), W("SAMSU", 90, 130, 118),
             W("ME16A4021AS", 150, 245, 118), W("4,056.00", 400, 460, 118)]

    zone = {"type": "line_items", "label": "LI", "page": 0,
            "x0": 40, "y0": 40, "x1": 500, "y1": 200}
    recs = parse_line_items_zone(zone, words, bb, None, "BM736499",
                                 "t.pdf", 24, review=[])
    codes = {r["material_code"] for r in recs}
    assert "DW80CG4051SR" in codes, f"wrapped code lost in zone path: {codes}"
    assert "ME16A4021AS" in codes, codes


@check("Same model on separate order lines stays separate")
def t_same_model_two_lines():
    """
    PO 246155 orders WF45B6300AP on line 0006 AND line 0008, 2 EA each.
    Merging them into one record loses a quantity - total 4 EA becomes 2 EA.
    """
    from engine import BackboneIndex
    from engine import (extract_lines_with_backbone, load_config,
                           compile_patterns)
    bb = BackboneIndex({"WF45B6300AP/US": {"description": "", "category": ""}})
    inc, _ = compile_patterns(load_config())
    page = ("0006 12816 2 EA SSW WF45B6300AP PLATIN 599.00 1198.00\n"
            "0008 12816 3 EA SSW WF45B6300AP PLATINUM 599.00 1797.00\n")
    recs = extract_lines_with_backbone(page, [], bb, inc, "246155", 1,
                                      "t.pdf", 24, review=[])
    qtys = sorted(str(r.get("quantity")) for r in recs)
    assert len(recs) == 2, f"lines merged: {recs}"
    assert qtys == ["2", "3"], qtys


@check("Separate order lines split even when OCR lost one quantity")
def t_same_model_missing_qty():
    """
    PO 246155 exactly as it scans - this is the real page text, OCR noise and
    all. Row 0008 lost its quantity and has the code glued to the description.
    Both rows must appear as separate items, told apart by the printed line
    number, and the money must not be torn in half ('1198.0' -> 119 + 8.0).
    """
    from engine import BackboneIndex
    from engine import (extract_lines_with_backbone, load_config,
                           compile_patterns)
    bb = BackboneIndex({"WF45B6300AP/US": {"description": "", "category": ""}})
    inc, _ = compile_patterns(load_config())
    page = (
        "0006  12816  2 EA SSW  WF4SB6300AP PLATIN13970  00:665  00665  599.00  1198.0\n"
        "TAG FOR: GROBA  CONSTR. COMPANY  ORDER# uK9250-002\n"
        "0008  12816  EA  SSw  WF45B6300APPLATINUM  599.00  00:665  00*665  1198.0\n"
        "TAG FOR: CODY  THOMAS  ORDER# uL0268-00S\n")
    recs = extract_lines_with_backbone(page, [], bb, inc, "246155", 1,
                                      "t.pdf", 24, review=[])
    lines = sorted(str(r.get("po_line") or "") for r in recs)
    assert len(recs) == 2, f"rows merged (0008 lost): {recs}"
    assert lines == ["0006", "0008"], lines
    # both must report the corrected code, not the OCR spelling
    assert all(r["material_code"] == "WF45B6300AP" for r in recs), recs
    # money must stay whole
    for r in recs:
        for f in ("unit_price", "amount"):
            v = str(r.get(f) or "")
            assert v not in ("119", "8.0", "1"), f"{f} split: {r}"



@check("Mirrored OCR ghosts are not read as money")
def t_mirror_money():
    """
    PO 246155 is a carbon-copy scan, so OCR reads the back of the sheet too and
    every amount arrives twice - once printed, once rotated 180 degrees:

        630.00 -> 00'069      599.00 -> 00:665 / 00665 / 00*665
        1198.0 -> O'8611      327.0  -> O'LZE

    Taking the last two numbers on the line published 8,611.00 as the extended
    cost where 1,198.00 belonged.
    """
    from engine import money_values

    cases = [
        ("0002  18161  1 EA SSW  NE63A6511SG BLK STAINLESS  630.00  00'069  630.0",
         ["630.00", "630.0"]),
        ("0006  12816  2 EA SSW  WF4SB6300AP PLATIN13970  00:665  00665  599.00  1198.0",
         ["599.00", "1198.0"]),
        ("0008  12816  EA  SSw  WF45B6300APPLATINUM  599.00  00:665  00*665  1198.0",
         ["599.00", "1198.0"]),
        ("0009  12839  2 EA SSW  DVE45B6300PPLATINUM  00665  599.00  599.00  O'8611",
         ["599.00", "599.00"]),
    ]
    for line, want_tail in cases:
        got = money_values(line)
        assert got[-2:] == want_tail, f"{line[:24]}... -> {got}"
        # the rotated ghosts must be gone entirely
        for ghost in ("069", "665", "8611", "13970"):
            assert ghost not in got, f"ghost {ghost} kept: {got}"

    # A normal, un-mirrored line is untouched
    assert money_values("1 EA  1,257.00  1257.00")[-2:] == ["1257.00", "1257.00"]
    # Leading '00' is never a real amount, but a genuine sub-dollar value is
    assert money_values("FOB DEST  .00") == []
    assert "0.99" in money_values("PART  0.99")



@check("Backbone spelling is published even when a parser leaks a misread")
def t_normalize_output_codes():
    """
    PO 246155 printed 'WF4SB6300AP' (5 read as S) and that reached the Excel
    file verbatim, labelled 'pattern' as though the code were unknown. Rather
    than chase every parsing path, finished records are resolved against the
    backbone one last time.
    """
    from engine import BackboneIndex
    from engine import normalize_output_codes

    bb = BackboneIndex({"WF45B6300AP/US": {"description": "", "category": "Laundry"}})
    recs = [
        {"material_code": "WF4SB6300AP", "page": 1, "po_line": "0008",
         "match_type": "pattern", "category": ""},
        {"material_code": "WF45B6300APPLATINUM", "page": 1, "po_line": "0006",
         "match_type": "pattern", "category": ""},
        {"material_code": "TOTALLYUNKNOWN9", "page": 1, "po_line": "0011",
         "match_type": "pattern", "category": ""},
    ]
    normalize_output_codes(recs, bb)

    assert recs[0]["material_code"] == "WF45B6300AP", recs[0]
    assert "reference" in recs[0]["match_type"], recs[0]
    assert recs[0]["category"] == "Laundry", recs[0]
    assert recs[1]["material_code"] == "WF45B6300AP", recs[1]
    # An unknown code is left alone and still faces the accuracy gate
    assert recs[2]["material_code"] == "TOTALLYUNKNOWN9"
    assert recs[2]["match_type"] == "pattern"
    assert not recs[2].get("backbone_code")


@check("Final de-duplication keeps repeat order lines")
def t_dedupe_keeps_po_lines():
    """
    The last stage of extract_material_codes() collapses duplicates.  It used
    to key on (code, page) only, which quietly deleted line 0008 of PO 246155
    AFTER the parser had correctly produced it - the row reached the Excel file
    on neither the zone nor the fallback path.  The parser tests above cannot
    catch that, because they stop before this stage.
    """
    from engine import dedupe_records

    recs = [
        {"material_code": "WF45B6300AP", "page": 1, "po_line": "0006"},
        {"material_code": "WF45B6300AP", "page": 1, "po_line": "0008"},
    ]
    out = dedupe_records(recs)
    assert len(out) == 2, f"repeat order line dropped: {out}"
    assert [r["po_line"] for r in out] == ["0006", "0008"]

    # true duplicates of the same printed line still collapse
    dup = [
        {"material_code": "RF32CG5900SR", "page": 1, "po_line": "0003"},
        {"material_code": "RF32CG5900SR", "page": 1, "po_line": "0003"},
    ]
    assert len(dedupe_records(dup)) == 1

    # unnumbered rows keep the old (code, page) behaviour
    plain = [
        {"material_code": "DW80CG4021SR", "page": 1, "po_line": ""},
        {"material_code": "DW80CG4021SR", "page": 1},
        {"material_code": "DW80CG4021SR", "page": 2},
    ]
    out = dedupe_records(plain)
    assert len(out) == 2, f"unnumbered dedupe broke: {out}"

    # a numbered row is not suppressed by an earlier unnumbered one
    mixed = [
        {"material_code": "NE63A6511SG", "page": 1},
        {"material_code": "NE63A6511SG", "page": 1, "po_line": "0002"},
    ]
    assert len(dedupe_records(mixed)) == 2, "numbered row lost to unnumbered"


@check("Wrapped code also gets its Unit Price / Amount")
def t_wrapped_money():
    """
    BM736499: codes recovered from a wrapped MODEL column had empty money
    columns, because the full code never appears on one line in the page text.
    The enrichment must match on the printed stem too.
    """
    from engine import enrich_money_from_pages
    from engine import BackboneIndex
    bb = BackboneIndex({"DW80CG4051SRAA": {"description": "", "category": ""}})
    recs = [{"material_code": "DW80CG4051SR",
             "backbone_code": "DW80CG4051SRAA",
             "quantity": "24", "unit_price": "", "amount": "", "page": 1}]
    pages = [{"page_num": 1, "text":
              "51DBA/HYBRD/3RDRCK/AUTRL\n"
              "DW80CG4051S\n"
              "24 SAMSU UPC: 887276772905 FDC $383.20 $383.20 $9,196.80\n"
              "R\n"
              "Part #:\n"}]
    enrich_money_from_pages(recs, pages, bb)
    assert recs[0]["unit_price"] == "383.20", recs[0]
    assert recs[0]["amount"] == "9196.80", recs[0]


@check("Stray trailing character is not accepted as a market suffix")
def t_no_stray_suffix():
    """
    'DW80CG4051SRAAB' - the 'B' is the next line's item label - must NOT be
    matched or published. Only recognised market suffixes (AA/US/XAA...) may
    differ between the document and the list.
    """
    from engine import BackboneIndex
    bb = BackboneIndex({"DW80CG4051SRAA": {"description": "", "category": ""}})

    code, kind = bb.lookup("DW80CG4051SRAAB")
    assert code == "", f"stray suffix accepted: {code} ({kind})"

    # A genuine market suffix still matches, and keeps the printed spelling
    code2, _ = bb.lookup("DW80CG4051SR")
    assert code2 == "DW80CG4051SRAA", code2
    assert bb.printed_form("DW80CG4051SRAA", "DW80CG4051SR") == "DW80CG4051SR"
    # And a corrupted token never reaches the output
    assert bb.printed_form("DW80CG4051SRAA",
                           "DW80CG4051SRAAB") == "DW80CG4051SRAA"


@check("Wrapped-code repair ignores lines that start a new item")
def t_repair_not_fooled_by_labels():
    from engine import BackboneIndex
    from engine import repair_wrapped_codes
    bb = BackboneIndex({"DW80CG4051SRAA": {"description": "", "category": ""},
                        "ME21DG6300SRAA": {"description": "", "category": ""}})
    lines = ["A - (DW80CG4051SRAA) 1 EA $ 411.00",
             "B - (ME21DG6300SRAA) 2 EA $ 209.00"]
    out = repair_wrapped_codes(lines, bb)
    joined = " ".join(out)
    assert "DW80CG4051SRAAB" not in joined, out
    for orig in lines:
        assert orig in out


@check("Ghost still blocked when a confirmed code exists")
def t_ghost_still_blocked():
    from engine import BackboneIndex, select_row_codes, extract_codes_from_line
    REF = {"DW80CG4051SR": {"description": "DW", "category": "MDA"}}
    bb = BackboneIndex(REF)
    cands = extract_codes_from_line(
        "(DW80CG4051SRAA) DISWH8W0ACSGH4E0R5 1 EA", bb, None)
    keep, _ = select_row_codes(cands, bb)
    assert len(keep) == 1 and keep[0]["code"] == "DW80CG4051SRAA", keep


@check("Line-items table parsing")
def t_table():
    import engine as tp
    from engine import BackboneIndex, extract_codes_from_line, parse_quantity

    def W(t, x0, x1, top):
        return {"text": t, "x0": x0, "x1": x1, "top": top, "bottom": top + 10}

    words = [W("Style/Color", 340, 410, 80), W("Qty", 820, 845, 80),
             W("Unit", 900, 930, 80),
             W("(DW80CG4051SRAA)", 340, 470, 150),
             W("1", 828, 836, 150), W("EA", 902, 920, 150)]
    parsed = tp.parse_line_items(words, 50, 950)
    assert parsed["header_found"], "header not detected"
    assert "quantity" in parsed["columns"]
    blocks = tp.split_blocks_by_quantity(parsed["rows"])
    assert len(blocks) == 1, blocks

    bb = BackboneIndex({"DW80CG4051SR": {"description": "", "category": ""}})
    found = extract_codes_from_line(blocks[0]["text"], bb, None)
    q, u = parse_quantity(tp.cell_from_block(blocks[0], "quantity"))
    assert found and found[0]["code"] == "DW80CG4051SRAA"
    assert (q, u) == ("1", "")


@check("Column identity: wording, split labels, amount shapes")
def t_column_identity():
    """
    A value must be published under the column it was printed in, whatever the
    header happens to say. Each assertion here is a defect reproduced against
    the real engine in .workbuddy\\column_probe.py (see COLUMN_ALIGNMENT.md);
    they are the acceptance test for the column-identity fixes.
    """
    import engine as ex

    def W(t, x0, x1, top):
        return {"text": t, "x0": x0, "x1": x1, "top": top, "bottom": top + 10}

    # -- 1. Header wording -> role. Short aliases ("qty") used to be dead
    #       because substring matching required len(word) >= 4.
    assert ex.classify_header("Ord Qty") == "quantity"
    assert ex.classify_header("Total Qty") == "quantity"      # was 'amount'
    assert ex.classify_header("Order Total") == "amount"      # still a total
    assert ex.classify_header("Grand Total") == "amount"
    assert ex.classify_header("Description") == "description"  # was material_code
    assert ex.classify_header("Item #") == "material_code"
    assert ex.classify_header("U/P") == "unit_price"
    assert ex.classify_header("Unit Price") == "unit_price"
    assert ex.classify_header("Extended Price") == "amount"

    # -- 2. Every amount a PO actually prints is accepted as one. The old
    #       validator rejected any 4+ digit figure without a thousands comma.
    for v in ("599.00", "$599.00", "1,198.00", "1198.00", "1234.00",
              "1060.00", "1060.0000", "21,580.56", "186"):
        assert ex._MONEY_CELL.match(v), v

    # -- 3. A value that fails validation is handed on and flagged, not lost;
    #       pure description text is still refused.
    blk = {"rows": [{"cells": {"unit_price": "1,198.00 USD"}}]}
    assert ex.cell_from_block(blk, "unit_price") == "1,198.00 USD"
    assert blk.get("low_confidence") == ["unit_price"]
    assert ex.cell_from_block({"rows": [{"cells": {"unit_price": "WASHER"}}]},
                              "unit_price") == ""

    # -- 4. "Unit" + "Price" is ONE column. It used to become two anchors, so
    #       the boundary fell mid-column and the price landed in 'unit'.
    words = [W("Item", 60, 80, 0), W("Description", 200, 255, 0),
             W("Qty", 400, 415, 0), W("Unit", 520, 540, 0), W("Price", 545, 570, 0)]
    data = [[("WF45B6300AP", 60, 115), ("WASHER", 200, 230),
             ("2", 400, 405), ("599.00", 520, 550)],
            [("RS27T5200SR", 60, 115), ("FRIDGE", 200, 230),
             ("1", 400, 405), ("857.00", 520, 550)]]
    y = 20
    for row in data:
        for t, x0, x1 in row:
            words.append(W(t, x0, x1, y))
        y += 20
    parsed = ex.parse_line_items(words, 0, 700)
    cells = parsed["rows"][0]["cells"]
    assert cells.get("quantity") == "2", cells
    assert cells.get("unit_price") == "599.00", cells
    assert "unit" not in parsed["columns"], parsed["columns"]

    # -- 5. The result does not depend on how the quantity header is spelled.
    got = []
    for label in ("Qty", "Quantity", "Order Qty", "Total Qty"):
        w = [W("Item", 60, 80, 0), W(label, 400, 400 + len(label) * 5, 0),
             W("Unit", 520, 540, 0), W("Price", 545, 570, 0)]
        yy = 20
        for row in data:
            for t, x0, x1 in row:
                w.append(W(t, x0, x1, yy))
            yy += 20
        got.append(ex.parse_line_items(w, 0, 700)["rows"][0]["cells"].get("quantity"))
    assert got == ["2", "2", "2", "2"], got

    # -- 6. A header printed on two lines ("Unit" above "Price") completes the
    #       label instead of pushing the word "Price" into a data cell.
    two = [W("Item", 60, 95, 0), W("Qty", 400, 420, 0), W("Unit", 520, 540, 0),
           W("WF45B6300AP", 60, 115, 20), W("2", 400, 405, 20),
           W("599.00", 520, 550, 20), W("Price", 520, 546, 20),
           W("RS27T5200SR", 60, 115, 40), W("1", 400, 405, 40),
           W("857.00", 520, 550, 40)]
    r3 = ex.parse_line_items(two, 0, 700)
    for row in r3["rows"]:
        for role in ("unit", "unit_price"):
            assert "Price" not in (row["cells"].get(role) or ""), row["cells"]
    assert r3["rows"][0]["cells"].get("unit_price") == "599.00", r3["rows"][0]

    # -- 7. "Description | Item #" is description first, code second. The
    #       description used to win the material_code role and the real code
    #       column was dropped.
    w4 = [W("Description", 60, 115, 0), W("Item #", 400, 430, 0),
          W("Qty", 520, 535, 0), W("Price", 560, 585, 0),
          W("SAMSUNG WASHER", 60, 135, 20), W("WF45B6300AP", 400, 455, 20),
          W("2", 520, 525, 20), W("599.00", 560, 590, 20)]
    r4 = ex.parse_line_items(w4, 0, 700)
    assert "material_code" in r4["columns"], r4["columns"]
    assert round(r4["columns"]["material_code"][0]) == 400, r4["columns"]
    assert r4["rows"][0]["cells"].get("material_code") == "WF45B6300AP"

    # -- 8. Two narrow, genuinely separate columns must NOT be fused into one
    #       phrase just because they sit close together.
    narrow = [W("Description", 60, 115, 0), W("Qty", 120, 135, 0),
              W("SAMSUNG WASHER", 60, 135, 20), W("2", 120, 125, 20)]
    rn = ex.parse_line_items(narrow, 0, 400)
    assert "quantity" in rn["columns"], rn["columns"]
    assert rn["rows"][0]["cells"].get("quantity") == "2", rn["rows"][0]

    # -- 9. Header routing on a real cell grid: 'Extended Price' contains
    #       'price' as a substring and used to overwrite the unit price column,
    #       publishing the line total as the unit price.
    config = {"column_keywords": ["item", "material", "code"],
              "min_code_length": 5, "max_code_length": 20}
    table = [["Item", "Description", "Qty", "Unit Price", "Extended Price"],
             ["WF45B6300AP", "SAMSUNG WASHER", "2", "599.00", "1198.00"]]
    recs = ex.extract_from_table([table], config, [], [],
                                 {"WF45B6300AP": {}}, "95778", 1, "f.pdf")
    assert recs and recs[0]["unit_price"] == "599.00", recs
    assert recs[0]["amount"] == "1198.00", recs
    assert recs[0]["quantity"] == "2", recs

    # -- 10. One printed value belongs to one order line, not to two.
    values = [{"y": 103.0, "text": "599.00"}]
    a = ex.align_value_to_row(100.0, values, tol=6.0)
    b = ex.align_value_to_row(107.0, values, tol=6.0)
    assert a == "599.00" and b == "", (a, b)


@check("Whole-page columns: quantity vs a number inside the description")
def t_page_columns():
    """
    PO 6-95635-1026 (Encompass, 2026-10-06) - real failure, reproduced here.

    The item table is a text layout with no ruled lines and no zone template,
    so pdfplumber returns no table at all and the line-by-line fallback ran.
    Its row text is

        1  6  SMG  HAF-CIN-2P/EXP  WATER FILTER 2 PACK  0.00  45.26

    The quantity is the 6; the 2 belongs to "2 PACK" in the description, and
    the form has NO extended-cost column (the money columns are "Unit Core"
    and "Unit Price"). Reading only the flattened line, the engine took the
    number nearest the price column as the count - the description's 2 - and
    then paired the last two amounts into unit price / amount, so both the
    quantity and the unit cost came out wrong on every row:

        line 1  printed 6  -> read 2      line 3  printed 1  -> read 4
        line 2  printed 30 -> read 2      line 9  printed 3  -> read 4

    With the word coordinates and the page's own header row, every value is
    read from the column it was printed in. The check below asserts exactly
    that, plus the arithmetic the PO itself prints: sum(qty x unit price)
    equals the document total 2,785.31 and the pieces total is 52.
    """
    import engine as ex

    def W(t, x0, x1, top):
        return {"text": str(t), "x0": x0, "x1": x1,
                "top": top, "bottom": top + 10}

    # Column x-ranges copied from the real page. "Brand" and "Core" are
    # columns the vocabulary has no name for - they must keep their own width.
    def header_row(top):
        return [W("Line#", 18, 45, top), W("Qty", 63, 81, top),
                W("Brand", 90, 120, top), W("Part", 126, 146, top),
                W("Number", 149, 190, top), W("Description", 261, 319, top),
                W("Unit", 466, 487, top), W("Core", 490, 513, top),
                W("Unit", 537, 558, top), W("Price", 561, 585, top)]

    def item_row(ln, qty, code, desc_words, core, price, top):
        row = [W(ln, 39, 44, top), W(qty, 75, 80, top), W("SMG", 93, 108, top),
               W(code, 129, 183, top)]
        x = 264
        for t in desc_words:
            row.append(W(t, x, x + len(t) * 5, top))
            x += len(t) * 5 + 4
        row += [W(core, 498, 512, top), W(price, 565, 584, top)]
        return row

    words = []
    # Address / date / terms blocks above the table, so the header is NOT
    # within the first 8 rows of the page.
    for i in range(14):
        words += [W("ENCOMPASS", 30 + j * 60, 90 + j * 60, i * 10)
                  for j in range(3)]
    words += header_row(150)
    rows = [(1, "6", "HAF-CIN-2P/EXP", ["WATER", "FILTER", "2", "PACK"],
             "0.00", "45.26"),
            (2, "30", "HAF-QIN-2P/EXP", ["WATER", "FILTER", "2", "PACK"],
             "0.00", "45.26"),
            (3, "1", "RA-F18DBBQL/AA", ["BESPOKE", "4-DOOR", "FLEX"],
             "0.00", "66.95")]
    for n, (ln, qty, code, desc, core, price) in enumerate(rows):
        words += item_row(ln, qty, code, desc, core, price, 170 + n * 18)

    # The header is past the old 8-row scan, which is why the page-level pass
    # has to look further (PAGE_HEADER_SCAN).
    grouped = ex.group_words_into_rows(words)
    assert ex.find_header_row(grouped, max_scan=8)[0] == -1
    assert ex.find_header_row(grouped, max_scan=ex.PAGE_HEADER_SCAN)[0] >= 0

    # "Brand" and "Core" get their own columns, so their text cannot be read
    # as the quantity.
    parsed = ex.parse_line_items(words, 0, 612, max_scan=ex.PAGE_HEADER_SCAN)
    assert set(parsed["columns"]) == {"line_no", "quantity", "material_code",
                                      "description", "unit", "unit_price"}
    first = parsed["rows"][0]["cells"]
    assert first.get("quantity") == "6", first
    assert first.get("unit_price") == "45.26", first
    assert first.get("description") == "WATER FILTER 2 PACK", first

    bb = ex.BackboneIndex({c: {"description": "", "category": ""}
                           for _l, _q, c, _d, _c, _p in rows})
    recs = ex.extract_page_line_items(
        words, bb, None, "6-95635-1026", 1, "PO6-95635-1026.pdf")
    got = {r["material_code"]: (r["quantity"], r["unit_price"]) for r in recs}
    assert got == {"HAF-CIN-2P/EXP": ("6", "45.26"),
                   "HAF-QIN-2P/EXP": ("30", "45.26"),
                   "RA-F18DBBQL/AA": ("1", "66.95")}, got

    # The page-level pass must stay out of the way when there is no header to
    # read: the line scan remains the fallback for those pages.
    assert ex.extract_page_line_items(
        [W("SOME TEXT", 10, 60, 10)], bb, None, "1", 1, "x.pdf") == []


@check("Stacked two-line header: Qty/Ord, Unit|Extend Cost (PO 189743)")
def t_stacked_header():
    """
    PO 189743 (Electronic Express, 2026-10-10) - real failure, reproduced.

    The column labels are printed across TWO header lines with a junk row
    between them, and the picked (lower) line alone names the columns wrong:

        Lin   Item   Vendor    Qty    Qty    Item  Unit   Extend  Retail
        Num   Code   Reference Ord    Rec    U/M   Description Cost Cost Price

    The quantity value sits under "Qty" / "Ord", but "Ord" was not in the
    vocabulary, so the column went unnamed and 240 was never read. The bare
    "Price" (a RETAIL column that is always empty) also grabbed unit_price on
    label length, leaving 500.00 / 120000.00 in unnamed columns - the PO came
    back as "Quantity missing / Unit cost missing: NSE6DG8502SRAA".

    Fixes under test here:
      * "Ord" anchors the quantity column;
      * a word in the rows above completes a stacked label ("Unit" + "Cost"
        -> unit_price, "Extend" + "Cost" -> amount) and takes the role from a
        weaker solo claim;
      * vertical rule glyphs (upright=False "(cid:...)" words) are kept out of
        row grouping so they cannot corrupt the cells.
    """
    import engine as ex

    def W(t, x0, x1, top, upright=True):
        return {"text": str(t), "x0": x0, "x1": x1,
                "top": top, "bottom": top + 10, "upright": upright}

    # Junk row printed between the two header halves: vertical rule glyphs.
    junk = [W(f"(cid:{n})", 190 + n * 7, 197 + n * 7, 156, upright=False)
            for n in range(3)]

    header1 = [W("Lin", 22.1, 35.0, 150), W("Item", 39.4, 56.6, 150),
               W("Vendor", 95.5, 134.4, 150), W("Qty", 161.9, 178.9, 150),
               W("Qty", 181.9, 194.9, 150), W("Item", 238.1, 285.6, 150),
               W("Unit", 376.3, 393.6, 150), W("Extend", 402.2, 423.8, 150),
               W("Retail", 458.4, 480.0, 150)]
    header2 = [W("Num", 22.1, 35.0, 162), W("Code", 39.4, 56.6, 162),
               W("Reference", 95.5, 134.4, 162), W("Ord", 181.9, 194.9, 162),
               W("Rec", 199.2, 212.2, 162), W("U/M", 220.8, 233.8, 162),
               W("Description", 238.1, 285.6, 162),
               W("Cost", 376.3, 393.6, 162), W("Cost", 423.8, 441.1, 162),
               W("Price", 458.4, 480.0, 162)]
    item = [W("1", 30.7, 35.0, 178), W("NSE6DG8502SR", 39.4, 91.2, 178),
            W("NSE6DG8502SRAA", 95.5, 156.0, 178), W("240", 181.9, 194.9, 178),
            W("EA", 216.5, 225.1, 178), W("SAM", 238.1, 251.0, 178),
            W('30"', 255.4, 268.3, 178), W("SS", 272.6, 281.3, 178),
            W("CONX", 285.6, 302.9, 178), W("SLIDE-IN", 307.2, 341.8, 178),
            W("RA", 346.1, 354.8, 178), W("500.00", 367.7, 393.6, 178),
            W("120000.00", 402.2, 441.1, 178)]
    # A rule glyph sharing the item row's band must not enter its cells.
    item += [W("(cid:7)", 250.0, 257.0, 178, upright=False)]

    words = junk + header1 + header2 + item

    grouped = ex.group_words_into_rows(words)
    # The junk row is vertical-only: filtering it must not leave a rogue row.
    assert not any("(cid:" in r["text"] for r in grouped), grouped

    idx, colmap, _abs, _band = ex.find_header_row(grouped, max_scan=60)
    assert idx >= 0
    assert colmap.get("quantity") == (181.9, 194.9), colmap.get("quantity")
    assert colmap.get("unit_price") == (376.3, 393.6), colmap.get("unit_price")
    assert colmap.get("amount") == (402.2, 441.1), colmap.get("amount")

    parsed = ex.parse_line_items(words, None, None, max_scan=60)
    assert {"quantity", "unit_price", "amount"} <= set(parsed["columns"])
    cells = parsed["rows"][0]["cells"]
    assert cells.get("quantity") == "240", cells
    assert cells.get("unit") == "EA", cells
    # The description header word is narrower than its data, so the trailing
    # "RA" crosses the boundary into the unit-price cell; the money itself is
    # re-sanitised downstream (see cell_from_block / _clean_money).
    assert cells.get("unit_price", "").endswith("500.00"), cells
    assert cells.get("amount") == "120000.00", cells
    assert "(cid" not in (cells.get("description") or ""), cells

    # End to end, the record is complete: no more "Quantity missing /
    # Unit cost missing".
    bb = ex.BackboneIndex({"NSE6DG8502SR": {"description": "", "category": ""}})
    recs = ex.extract_page_line_items(
        words, bb, None, "189743", 1, "PO-189743.pdf")
    assert len(recs) == 1, recs
    r = recs[0]
    assert r["material_code"] == "NSE6DG8502SR", r
    assert r["quantity"] == "240", r
    assert r["unit_price"] == "500.00", r
    assert r["amount"] == "120000.00", r


# ══════════════════════════════════════════════
# 5. Code-list cells and labor/service codes
# ══════════════════════════════════════════════
# Reading a code-list FILE is Master Data > Material Codes' job now
# (the MATERIAL MASTER section of src/of_master.py, covered by
# `python src\selftest.py excel`). The engine keeps the cell rules both
# sides share.
@check("Code-list cells: labeled and service codes")
def t_import_labor_codes():
    """
    Real code lists contain entries typed with a label or a space:
        'Model E3-DW'   -> E3-DW
        'Model E5-RANE' -> E5-RANE
        'Labor REF'     -> LABOR-REF
    These were previously discarded ('not code-shaped' / 'section heading'),
    which is why PO 2170541 and 56098288 never matched their labor lines.
    """
    from engine import clean_code_cell

    assert clean_code_cell("Model E3-DW") == "E3-DW"
    assert clean_code_cell("Model E5-RANE") == "E5-RANE"
    assert clean_code_cell("Model E5-MWO") == "E5-MWO"
    assert clean_code_cell("Labor REF") == "LABOR-REF"
    assert clean_code_cell("RF18A5101SR/AA") == "RF18A5101SR/AA"
    assert clean_code_cell("2170541.0") == "2170541"

    # Digit-free part codes are real: water filters, accessory numbers
    assert clean_code_cell("HAFQIN") == "HAFQIN"
    assert clean_code_cell("HAFCU1") == "HAFCU1"

    # genuine headings still rejected
    assert clean_code_cell("Refrigerator") == ""
    assert clean_code_cell("07.OVEN") == ""
    assert clean_code_cell("Accessory") == ""
    assert clean_code_cell("Cooking") == ""
    # ...also when typed in capitals, which is how headings often appear
    assert clean_code_cell("REFRIGERATOR") == ""
    assert clean_code_cell("MICROWAVE") == ""

    # And the matcher must find them in PO text
    from engine import BackboneIndex, extract_codes_from_line
    bb = BackboneIndex({"E3-DW": {"description": "", "category": "Service"},
                        "LABOR-REF": {"description": "", "category": "Service"}})
    hit = extract_codes_from_line(
        "DISHWASHER Both Samsung and Dacor (Model E3-DW) - Install 1 EA",
        bb, None)
    assert any(h["backbone_code"] == "E3-DW" for h in hit), hit
    hit2 = extract_codes_from_line(
        "Labor REF Free Standing Both Samsung and Dacor EA 1 $ 50.00", bb, None)
    assert any(h["backbone_code"] == "LABOR-REF" for h in hit2), hit2

    # OCR welds a stray letter onto the first word: "HLabor Washer"
    bb2 = BackboneIndex({"LABOR-WASHER": {"description": "", "category": "ETC"}})
    hit3 = extract_codes_from_line("HLabor Washer EA 1 $ 50.00", bb2, None)
    assert any(h["backbone_code"] == "LABOR-WASHER" for h in hit3), hit3


@check("Company code list: matcher tolerates both suffix spellings")
def t_company_suffixes():
    # SamsungCodestructor mixes '/AA' and glued 'AA'; PO text prints either
    from engine import BackboneIndex, extract_codes_from_line
    blank = {"description": "", "category": ""}   # the shape the engine loads
    bb = BackboneIndex({"RF18A5101SR/AA": blank, "DW80CG4051SRAA": blank})
    hits = extract_codes_from_line(
        "Samsung Refrigerator - (RF18A5101SRAA) 1 EA", bb, None)
    assert hits and hits[0]["backbone_code"] == "RF18A5101SR/AA", hits
    assert bb.lookup("DW80CG4051SR")[0] == "DW80CG4051SRAA"
    # /AA wins over another market variant, whichever is listed first
    bb2 = BackboneIndex({"DVE45T6000W/A3": blank, "DVE45T6000W/AA": blank})
    assert bb2.lookup("DVE45T6000W")[0] == "DVE45T6000W/AA"


# ══════════════════════════════════════════════
# 6. Caching integrity
# ══════════════════════════════════════════════
# ══════════════════════════════════════════════
@check("Caching: config / backbone / signature")
def t_cache():
    import engine as ex
    c1, c2 = ex.load_config(), ex.load_config()
    assert c1 is c2, "config not cached"
    assert ex.config_signature() == ex.config_signature()
    b1, b2 = ex.get_backbone(), ex.get_backbone()
    assert b1 is b2, "backbone index not cached"


@check("Unicode dashes normalise (soft hyphen in PDF text)")
def t_unicode_dash():
    """
    PDFs use several dash characters that look identical: soft hyphen
    (U+00AD), en dash, non-breaking hyphen. '583<AD>DVE45T6000W' must match
    the same code as '583-DVE45T6000W'.
    """
    from engine import normalize, BackboneIndex, extract_codes_from_line
    soft = "­"
    assert normalize(f"583{soft}DVE45T6000W") == "583DVE45T6000W"
    assert normalize("E3–DW") == normalize("E3-DW")

    bb = BackboneIndex({"DVE45T6000W/A3": {"description": "", "category": ""}})
    line = f"583{soft}DVE45T6000W Samsung Dryer EA 1 $ 521.00"
    r = extract_codes_from_line(line, bb, None)
    assert r and r[0]["backbone_code"] == "DVE45T6000W/A3", r
    # the internal category prefix must not appear in the output
    assert r[0]["code"] == "DVE45T6000W", r[0]

    # A token must never swallow the money that follows it
    from engine import _TOKEN
    toks = [m.group(0) for m in
            _TOKEN.finditer("(DW80CG4051SRAA) 1 EA $ 411.00 $ 411.00 *")]
    assert "DW80CG4051SRAA" in toks, toks
    assert not any(t.startswith("DW80CG4051SRAA") and len(t) > 14
                   for t in toks), toks
    assert not any("411.00" in t and len(t) > 6 for t in toks), toks


@check("Multi-page PO: pages outside the template are still scanned")
def t_multipage():
    """
    A zone belongs to one page. Item tables continuing on later pages must not
    be dropped (PO 4046792 has 3 pages).
    """
    from engine import BackboneIndex
    from engine import (extract_lines_with_backbone, load_config,
                           compile_patterns)
    REF = {"RF18A5101SR/AA": {"description": "", "category": "Refrigerator"},
           "WD90F53AVSUS":   {"description": "", "category": "Laundry"}}
    bb = BackboneIndex(REF)
    inc, _ = compile_patterns(load_config())

    # page 3 content must yield its code when scanned
    recs = extract_lines_with_backbone(
        "2 EA 06/19/2026 WD90F53AVS 1,650.00 EA 3,300.00", [], bb, inc,
        "4046792", 3, "t.pdf", 24, review=[])
    assert any(r["material_code"].startswith("WD90F53AVS") for r in recs), recs
    assert recs[0]["page"] == 3


@check("UI strings: every key the app asks for exists")
def t_ui_strings():
    """
    A missing language key shows the raw key name in the interface - 'nav_badge_codes'
    where a count should be. T() falls back silently, so nothing crashes and
    nothing warns; only a reader of the screen would notice. Checked here
    because the sidebar and the two new screens added a batch of keys at once.
    """
    import re
    _TPL_MARKER = "#  SECTION: template editor"
    _SELFTEST_MARKER = "#  SECTION: self test"
    # STRINGS now lives in this file (section: lang)

    here = Path(__file__).parent
    en = STRINGS["en"]

    # T("key") and T("key", n=...) - the key is always the first argument
    pat = re.compile(r"""\bT\(\s*["']([a-zA-Z0-9_]+)["']""")
    missing = {}
    # Only the template editor calls T(). Scan just that section of this file,
    # otherwise the comment documenting the pattern above is picked up as a key.
    src_file = here / "devtools.py"
    if src_file.exists():
        text = src_file.read_text(encoding="utf-8", errors="replace")
        if _TPL_MARKER in text:
            text = text.split(_TPL_MARKER, 1)[1]
        end = text.find(_SELFTEST_MARKER)
        if end != -1:
            text = text[:end]
        for key in sorted(set(pat.findall(text))):
            if key not in en:
                missing.setdefault("template editor", []).append(key)

    assert not missing, "missing language keys: " + "; ".join(
        f"{f}: {', '.join(k)}" for f, k in missing.items())

    # The Korean table may be partial (English is the documented fallback), but
    # the navigation must be fully translated - it is the first thing seen.
    ko = STRINGS.get("ko", {})
    nav_keys = [k for k in en if k.startswith("nav_")]
    ko_missing = [k for k in nav_keys if k not in ko]
    assert not ko_missing, f"Korean navigation incomplete: {ko_missing}"

    # Formatted strings must accept the arguments the app passes
    for key, kwargs in (("nav_badge_codes", {"n": 603}),
                        ("nav_badge_layouts", {"n": 5})):
        for lang_code in ("en", "ko"):
            tmpl = STRINGS.get(lang_code, {}).get(key)
            if tmpl is None:
                continue
            try:
                tmpl.format(**kwargs)
            except (KeyError, IndexError) as e:
                raise AssertionError(f"{lang_code}/{key} rejects {kwargs}: {e}")


@check("Engine export surface is intact")
def t_engine_surface():
    """
    The dashboard reaches into the engine by name. A rename on either side
    fails here rather than as an empty screen or a silent blank column.
    """
    import engine as ex

    assert hasattr(ex, "dedupe_records")
    assert hasattr(ex, "money_values")
    assert hasattr(ex, "normalize_output_codes")
    # The arithmetic cross-check machinery is gone for good
    for gone in ("find_document_total_qty", "reconcile_money",
                 "finalize_money", "qty_from_money", "is_clipped_amount",
                 "_lost_leading_char"):
        assert not hasattr(ex, gone), f"{gone} should be removed"


@check("OCR quality gate: a lost quantity asks for a higher-DPI retry")
def t_ocr_quality_gate():
    """
    The retry that escalates DPI exists because the cheap OCR failure is NOT
    "no text". It is a page whose descriptions and prices came through while
    the small count beside them did not - the order then looks extracted and
    adds up short.

    Both directions are asserted here, on synthetic pages so the check needs
    no scanned PDF and no OCR engine:

      * a line priced but without its count  -> retry
      * a line priced and counted            -> no retry
      * a totals line                        -> never counted as an item line
    """
    import engine as ex

    # The header block is padded to a realistic page length: a very short page
    # trips the separate "barely read" rule, and this case is about the
    # quantity rule alone.
    HEADER = ("PURCHASE ORDER\n"
              "Dacor Appliances - 360 5th Avenue, Brooklyn, NY 11218\n"
              "Purchase Order 25407327   Open Date Apr 15th 26 11:09AM\n"
              "Deliver To  Vendor\n"
              "AJ Madison  Samsung Electronics America\n"
              "2600 Fondren Road  Ridgefield Park, NJ 07660\n"
              "TERMS Net30  ACCOUNT# 2477749\n"
              "Brand  Item#  Description  Qty  Component  Cost  Cost\n")

    broken = [{"text": HEADER +
                       'Dacor  DRZ30980LAPDA  Freezer  2,771.55  2,771.55\n'
                       'Total  5,448.60\n'}]
    q = ex._ocr_quality(broken)
    assert q["amount_lines"] == 1, q          # only the item line, not Total
    assert q["qty_lines"] == 0, q
    assert ex._ocr_needs_retry(q) is True, q

    good = [{"text": HEADER +
                     'Dacor  DRR30980RAPDA  Refrigerator  1  2,677.05  2,677.05\n'
                     'Total  2,677.05\n'}]
    q2 = ex._ocr_quality(good)
    assert q2["amount_lines"] == 1, q2
    assert q2["qty_lines"] == 1, q2
    assert ex._ocr_needs_retry(q2) is False, q2

    # An empty result is a retry (nothing came back at all), and the DPI
    # escalation stays inside its documented ceiling.
    assert ex._ocr_needs_retry(ex._ocr_quality([])) is True
    assert min(ex.OCR_RETRY_MAX_DPI, int(300 * ex.OCR_RETRY_FACTOR)) <= ex.OCR_RETRY_MAX_DPI


@check("OCR engine status (informational)")
def t_ocr():
    """
    A scan needs TWO things, and either one missing looks identical from the
    outside: the file comes back with zero codes and no error. Reporting only
    the OCR engine hid the other half - this machine had Tesseract installed
    (just not on PATH) and no rasteriser at all, so "no OCR engine" was only
    half the story.
    """
    import engine as ocr_engine
    st = ocr_engine.status_summary()
    print(f"      rasteriser: {st['renderer'] or '(none)'}"
          f"   OCR engine: {st['engine'] or '(none)'}")
    if not st["renderer_ok"]:
        print("      note: no PDF rasteriser - a scanned page cannot be turned "
              "into an image (pip install pypdfium2)")
    if not st["engine"]:
        # Not a failure - OCR is optional. Report it.
        print("      note: no OCR engine installed "
              "(scanned PDFs will not be readable)")


# ══════════════════════════════════════════════
# Reading numbers the document printed badly
#
# The rules below were ported from po_extractor.py, whose per-vendor layouts
# taught them. Each test names the shape that made the rule necessary, because
# every one of them published a wrong figure before it existed.
# ══════════════════════════════════════════════

@check("Money field OCR mangled: letter for a digit, lost separator")
def t_money_ocr_repair():
    """
    Three shapes, each of which used to publish the wrong price:

        "$ 41l.00"    tesseract read 411.00 with a lower-case L
        "1,19B.00"    1,198.00 with the 8 read as B
        "S99.00"      599.00 with the 5 read as S
        "$ 1 198.00"  the thousands separator came out as a space, so only the
                      trailing "198.00" matched and a $1,198.00 dryer was
                      priced at $198.00

    The repairs are narrow: the look-alike pass needs the token to mix digits
    with look-alikes AND carry a decimal part, so words never become numbers.
    """
    from engine import money_values

    assert money_values("$ 41l.00") == ["411.00"]
    assert money_values("1,19B.00") == ["1198.00"]
    assert money_values("S99.00") == ["599.00"]

    # the head of a corrupted thousands figure is part of that number, not a value
    assert money_values("$ 1,19B.00") == ["1198.00"]

    # a lost separator must not publish the tail of the number as the price
    vals = money_values("DVE45T6000W/AA DRYER 7.4CF 1 $ 1 198.00 $ 1,198.00")
    assert vals[-2:] == ["1198.00", "1198.00"], vals

    # and the guards that were already there still hold
    assert money_values("2.1CF/LEDDIS/AUTCONN/GLSCNT") == []
    assert money_values("30IN 120V 4.5CF") == []
    assert money_values("TOTAL 263.20USD") == ["263.20"]
    # a spec figure must not be turned into money by the repair
    assert "8.12" not in money_values("MODEL B.12")
    assert "0.5" not in money_values("QTY O.5")



@check("Footer totals are never an item's cost")
def t_footer_guard():
    """
    A PO prints its own total a few lines under the last item. On a page whose
    item rows lost their cost columns, "Sub Total $ 6,316.80" is close enough to
    be adopted as that row's unit price - which is how a page total ended up on
    an item. Footer lines stop the search; item rows that merely open with two
    short tokens ("2 EA $ 411.00 $ 822.00") must not be mistaken for footers.
    """
    from engine import enrich_money_from_pages, is_footer_line, BackboneIndex

    assert is_footer_line("Sub Total  $ 6,316.80")
    assert is_footer_line("Page 2 of 3")
    assert is_footer_line("Total Quantity: 14")
    assert not is_footer_line("2 EA $ 411.00 $ 822.00")
    assert not is_footer_line("DVE45T6000W/AA DISHWASHER 1 EA $ 411.00")

    bb = BackboneIndex({"DW80CG4051SRAA": {"description": "", "category": ""}})
    recs = [{"material_code": "DW80CG4051SRAA",
             "backbone_code": "DW80CG4051SRAA",
             "quantity": "", "unit_price": "", "amount": "", "page": 1}]
    pages = [{"page_num": 1, "text":
              "ITEM  DESCRIPTION  QTY  UNIT PRICE  AMOUNT\n"
              "DW80CG4051SRAA  DISHWASHER 24IN  EA\n"
              "Page 2 of 3\n"
              "Sub Total  $ 6,316.80\n"}]
    enrich_money_from_pages(recs, pages, bb)
    assert not recs[0]["unit_price"], recs[0]
    assert not recs[0]["amount"], recs[0]


@check("Quantity with a decimal column, and a fractional count left alone")
def t_qty_decimal():
    """
    Some layouts print the count through a decimal column - "2.00 ea" - and the
    strict digit rules rejected it, so the quantity came out empty.

    Two shapes must keep returning nothing, because a quantity the document did
    not print is worse than a missing one: "1.5 EA" (the digits after the point
    used to be published as the quantity 5) and "6.0 cf" (a capacity, and
    reading the 6 put six machines on a PO that ordered one).
    """
    from engine import parse_quantity

    assert parse_quantity("2.00 ea")[0] == "2"
    assert parse_quantity("123456 789 DISHWASHER 2.00 ea 263.20 526.40")[0] == "2"
    assert parse_quantity("24 EA")[0] == "24"

    assert parse_quantity("1.5 EA")[0] == ""
    assert parse_quantity("6.0 cf")[0] == ""
    assert parse_quantity("30 in")[0] == ""
    assert parse_quantity("120 v")[0] == ""
    # ... but a plain count next to a plain unit still reads
    assert parse_quantity("12 ea")[0] == "12"


@check("A model named in a description is not an order line")
def t_code_quoted_in_description():
    """
    CMH 00958-2329551 prints the trim kit's fit on the line under the item:

        3  ... MICROWAVE 30" TRIM KIT FOR  MA-TK8020TS/AA  5 EA 101.0000   505.00
           MS19M8000AS SS                    <- the model the trim kit is FOR

    That wrap line opened the NEXT item's block, its code was confirmed against
    the master, and it then took the next line's quantity and price: the order
    came out with a ninth line worth 8,034.00 against a printed total of
    28,412.00 - OVER by exactly one line, on a document every part of which had
    been read correctly.

    What separates the two cases is where the numbers are, not what the code
    looks like:

      * the block's own row (the one carrying the QUANTITY) names the item ->
        any OTHER code on a wrap line that prints no money is description text;
      * the block's own row names nothing -> the wrap-line code IS the item
        (ERP One 01001129 prints the code BELOW its numbers) and everything is
        kept, exactly as before.
    """
    import engine as ex

    def cand(code):
        return {"code": code, "backbone_code": code, "confidence": 100,
                "match_kind": "exact", "description": "", "category": ""}

    def row(text, anchor):
        cells = {"quantity": "13 EA"} if anchor else {}
        return {"text": text, "cells": cells, "y": 0.0, "top": 0.0}

    # (a) quantity row carries the item's code, wrap line names another model.
    wrap = row("MS19M8000AS SS", anchor=False)
    own = row('4 025-00200-00272 RANGE ELE NE63D6511SR/AA 13 EA 618.0000 8,034.00',
              anchor=True)
    found = [cand("MS19M8000AS"), cand("NE63D6511SR/AA")]
    quoted = ex._codes_quoted_in_descriptions([(wrap, [cand("MS19M8000AS")]),
                                               (own, [cand("NE63D6511SR/AA")])],
                                              found)
    assert [c["code"] for c in quoted] == ["MS19M8000AS"], quoted

    # (b) the "code printed BELOW its numbers" layout: the quantity row carries
    # no code, so the wrap-line code must be KEPT (ERP One 01001129).
    numbers = row("1 EA 7.4 cu. ft. Smart Electric Dryer 648.00 EA 648.00",
                  anchor=True)
    below = row("DVE55CG7500EA3", anchor=False)
    assert ex._codes_quoted_in_descriptions(
        [(numbers, []), (below, [cand("DVE55CG7500EA3")])],
        [cand("DVE55CG7500EA3")]) == []

    # (c) a wrap line that prints money is another item, not prose.
    priced_wrap = {"text": "NSE6DG8502SRAA 2 500.00 1,000.00",
                   "cells": {}, "y": 0.0, "top": 0.0}
    assert ex._codes_quoted_in_descriptions(
        [(priced_wrap, [cand("NSE6DG8502SRAA")]), (own, [cand("NE63D6511SR/AA")])],
        [cand("NSE6DG8502SRAA"), cand("NE63D6511SR/AA")]) == []


@check("A quantity cell carries the neighbouring column's $, and a figure split by kerning")
def t_cells_currency_and_split_figures():
    """
    Two layout accidents that both ended in a WRONG ORDER, not a blank.

    1) Marcone MNH090926-HZL279 prints "1 $ 407.95": the amount column's own
       "$" sits a point left of its header, so it lands inside the quantity
       band and the cell reads "1 $". A "$" is never part of a count, but it
       made "1" unreadable as a quantity - the row stopped being an anchor, no
       block boundary was cut, and the fallback read the footer's piece count
       ("Total 48") as the quantity of ALL 31 lines.

    2) The same file prints "$57.11" as two words, "5" (x 281.7-284.4) and
       "7.11" (284.4-294.0) - the second starts exactly where the first ends.
       Joined with a space they read as two figures and the unit price came out
       as 5 instead of 57.11; only the amount (114.22 = 2 x 57.11) stayed right.

    Neither needs a PDF: both are decisions about words and cells.
    """
    import engine as ex

    # ---- 1: a currency mark on the quantity cell is not part of the count
    assert ex._qty_cell_text("1 $") == "1"
    assert ex._qty_cell_text("$ 2") == "2"
    assert ex._qty_cell_text("85.00") == "85.00"
    assert ex._qty_from_cell("1 $") == "1", ex._qty_from_cell("1 $")
    assert ex.is_quantity_anchor({"cells": {"quantity": "1 $"}}) is True
    # ...and the cells that must NOT anchor still do not
    assert ex._qty_from_cell("1.5") == ""
    assert ex._qty_from_cell("99999") == ""
    assert ex.is_quantity_anchor({"cells": {"quantity": "$ 407.95"}}) is False

    # A footer line is never the source of a count, even when the block has no
    # anchor row at all (that is what "Total 48" became).
    footer_block = {"rows": [{"text": "PA-A74/HZL279 RF32CG5B30SRAA Refrigerator "
                                       "- French Door $ 407.95 $ 407.95"},
                             {"text": "Total 48"}]}
    assert ex._quantity_from_anchor_row(footer_block) == ("", ""), \
        "the footer's piece count became an item quantity"

    # ---- 2: words that touch are one number
    def w(text, x0, x1):
        return {"text": text, "x0": float(x0), "x1": float(x1),
                "top": 0.0, "bottom": 9.0}

    assert ex._join_cell_words([w("$", 260.0, 262.7), w("5", 281.7, 284.4),
                                w("7.11", 284.4, 294.0)]) == "$ 57.11"
    # A real column break keeps its space, so two figures stay two figures.
    assert ex._join_cell_words([w("1", 100.0, 105.0),
                                w("2", 108.0, 113.0)]) == "1 2"
    # ...and letters are never fused across a gap this small either.
    assert ex._join_cell_words([w("EA", 100.0, 110.0),
                                w("85", 110.0, 120.0)]) == "EA 85"


@check("A price cell holding two amounts keeps both (price, amount)")
def t_price_cell_with_two_amounts():
    """
    Electronic Express PO-189743 prints "Unit Cost 500.00  Extend Cost
    120000.00" with the values ~15pt LEFT of their headers, so both numbers
    landed in the unit-price cell and the extended cost was lost:

        {'unit_price': 'RA 500.00 120000.00', 'amount': ''}

    The amount column came back empty and the price cell holds the pair, so the
    second value is moved - not derived - into the amount. Anything else is
    left exactly as it was.
    """
    import engine as ex

    assert ex._split_price_amount("500.00", "", "RA 500.00 120000.00") \
        == ("500.00", "120000.00")
    # A cell that holds only the price is untouched.
    assert ex._split_price_amount("500.00", "", "500.00") == ("500.00", "")
    # A four-decimal cost ("411.0000") is one value, not two.
    assert ex._split_price_amount("411.00", "", "411.0000") == ("411.00", "")
    # An amount already found is never overwritten.
    assert ex._split_price_amount("500.00", "120000.00", "500.00 120000.00") \
        == ("500.00", "120000.00")
    # A pair whose first value is NOT the price already read is not split: the
    # cell then belongs to something else and silence is safer.
    assert ex._split_price_amount("499.00", "", "500.00 120000.00") \
        == ("499.00", "")


@check("A missing quantity is reported, never borrowed from the row's text")
def t_missing_quantity_is_not_guessed():
    """
    Marcone MNH090926-HZL279 and AJ Madison's scans print two text bands on
    every row, and the count is not in either of them:

        PA-A74/HZL279  RF32CG5B30SRAA  Refrigerator - French Door $ 407.95 1 $ 407.95
        ^ warehouse code + special instruction, ONE band            ^^^ price  ^ count

    When the quantity column came back empty the engine fell back to ANY
    number on the block, and on that layout the answer was the warehouse code:
    all 31 lines came back with quantity 48. The order looked complete and was
    wrong on every line. On Last Samsung Order the same fallback answered with
    the year (2026) and with a spec number.

    The rule now: a count is taken from the row that IS the item's numbers
    (a line that opens with "<n> EA", or the row the quantity column filled),
    and never from a number that could be a date, a code or a spec. When there
    is none, the quantity stays EMPTY and a diagnostic says so - the order
    still goes out, with one field for a human instead of a silent invention.

    Synthetic rows only: no PDF, no OCR engine.
    """
    import engine as ex

    def parse(words, x0=0.0, x1=600.0):
        rows = ex.parse_line_items(words, zone_x0=x0, zone_x1=x1, max_scan=3)
        return rows

    def word(text, x, top, width=None):
        w = width if width is not None else max(8.0, 5.5 * len(text))
        return {"text": text, "x0": float(x), "x1": float(x + w),
                "top": float(top), "bottom": float(top + 9.0)}

    # The Marcone table: five columns, one row per item, no printed count.
    header = [word("WH", 58, 20), word("DC", 75, 20), word("/", 90, 20),
              word("Load#", 100, 20), word("Description", 195, 20),
              word("Unit", 268, 20), word("Price", 300, 20),
              word("QTY", 330, 20), word("Total", 360, 20)]
    item = [word("PA-A74/HZL279", 58, 32), word("RF32CG5B30SRAA", 100, 32),
            word("Refrigerator", 195, 32), word("-", 260, 32),
            word("French", 268, 32), word("Door", 300, 32),
            word("$", 330, 32), word("407.95", 340, 32)]
    parsed = parse(header + item)
    assert parsed["header_found"] and "quantity" in parsed["columns"], parsed["columns"]

    block = {"rows": parsed["rows"], "text": " ".join(r["text"] for r in parsed["rows"])}
    assert ex.is_quantity_anchor(parsed["rows"][-1]) is False
    assert ex._quantity_from_anchor_row(block) == ("", ""), \
        "a count was borrowed from a row that prints none"

    # The layouts that DO print one keep working, through the same call.
    lead = {"rows": [{"text": "1 EA 10/12/2026 RF22A4111SR 818.30 EA 818.30"}],
            "text": ""}
    assert ex._quantity_from_anchor_row(lead)[0] == "1"
    # ... and a bare leading number is still refused (that is a line number,
    # a year or a package size, never a count on its own).
    assert ex._leading_count("2026 4 1,265.00") == ("", "")
    assert ex._leading_count("85.00 EA") == ("", "")

    # The rule the whole thing serves: a printed code that stops short of the
    # listed one is either completed from the master or REJECTED - never
    # published as printed, and never guessed between two services.
    bb = ex.BackboneIndex({"L-INST/E2-BEV": {}, "L-INST/E2-UIC": {},
                           "NSE6DG8550SRAA": {}, "DVE45T6000W/A3": {},
                           "26A": {}})
    assert ex._suffix_verdict("L-INST/E2", "L-INST/E2-BEV", bb) == "reject"
    assert ex._suffix_verdict("NSE6DG8550SR", "NSE6DG8550SRAA", bb) == "copy"
    assert ex._suffix_verdict("DVE45T6000W", "DVE45T6000W/A3", bb) == "copy"
    assert ex._suffix_verdict("NSE6DG8550SRAA", "NSE6DG8550SRAA", bb) == "keep"
    # '26' from "Apr 18th, 26" is not a model, however many listed codes
    # happen to start with it.
    assert bb.lookup("26") == ("", "")


@check("Quantity column wins over the line number printed at the left")
def t_qty_before_price():
    """
    Scanned POs (PO 95778 from Van Vreede) print an unpadded line number in the
    first column and the real count just before the price:

        1 WF45B6300AP SAMSUNG FL/WASHER-PLATINUM 2 $599.00 $1,198.00

    parse_quantity() finds nothing on that shape, so the leading-number fallback
    took over and adopted 1..6 as the quantities. Every row that prints its
    extended cost equal to its unit price (a single unit - lines 2..4 here) then
    had its amount recomputed from the wrong count: line 2 went to the Excel
    file as $1,714 instead of $857.
    """
    from engine import qty_before_price

    van_vreede = [
        ("1 WF45B6300AP SAMSUNG FL/WASHER-PLATINUM 2 $599.00 $1,198.00", "599.00", "2"),
        ("2 RS27T5200SR SAMSUNG SS/I/W-REFRIG-SS-AGO 1 $857.00 $857.00", "857.00", "1"),
        ("3 RF22A4221SR SAMSUNG FD BM REFRIG-SS 1 $1,169.00 $1,169.00", "1,169.00", "1"),
        ("6 WE402NP SAMSUNG PEDESTAL-PLATINUM 4 $186.00 $744.00", "186.00", "4"),
    ]
    for line, price, want in van_vreede:
        got = qty_before_price(line, price)
        assert got == want, f"{line[:40]!r}: got {got!r}, want {want!r}"

    # A capacity in the description must not become the count. The CMH scan
    # prints "MICROWAVE OTR 1.6CF 300 CFM" and the 300 sits closer to the price
    # than the real count 14 does once OCR turns the column break into "14, EA".
    cmh = ("6 025-00300-01147_ MICROWAVE OTR 1.6CF 300 CFM ME16A4021AS/AA "
           "14, EA [] 160.0000; 2,240.00,")
    assert qty_before_price(cmh, "160.00") == "14"

    # Sizes glued to their unit are not counts at all.
    assert qty_before_price("DVE45T6000W/AA DRYER 7.4CF 30IN 120V 1 $1,198.00", "1,198.00") == "1"
    # No price column -> not this rule's business (leading-count layouts).
    assert qty_before_price("24 SAMSU DW80CG4051SR UPC: 887276827308", "") == ""



@check("A hyphenated PO number is kept whole")
def t_po_hyphen_suffix():
    """
    CMH prints its department code and the order sequence as one hyphenated PO.
    Only the first group was kept, so every order from that department produced
    the same PO number - and (customer, PO) is what the duplicate check keys on,
    which would have flagged each new CMH order as a re-send.

    A date or the next labelled field must never be glued on.
    """
    from engine import find_po_number

    assert find_po_number("Purchase Order Page 1 of 1 PO#: 00931 - 2309035") == "00931-2309035"
    # A scan reads the hyphen as "="
    assert find_po_number("PO#: 00931 = 2309035") == "00931-2309035"
    # ... but the date after the number is not a suffix
    assert find_po_number("PO Number: 0736499  Date: 06/19/2026") == "0736499"
    assert find_po_number("P.O. No. 4046792  Date: 6/19/2026") == "4046792"


@check("Zone boxes are trimmed to the sheet and translated for pdfium")
def t_clip_geometry():
    """
    A zone template is drawn against one scan, but the same customer can send a
    later PDF with different paper. An out-of-sheet box is a crash for
    pypdfium2 and a silently empty image for PyMuPDF, so it is trimmed first.

    pypdfium2 also does not take the rectangle to keep: its `crop` is how much
    to cut off each edge. Passing the rectangle itself removed the entire page
    and every zone OCR failed with "Crop exceeds page dimensions".
    """
    from engine import clamp_clip, clip_to_pdfium_cuts

    page = (612.0, 792.0)

    assert clamp_clip((457, 35, 573, 55), page) == (457, 35, 573, 55)
    assert clamp_clip((500, 700, 900, 900), page) == (500.0, 700.0, 612.0, 792.0)
    assert clamp_clip((-20, -20, 100, 100), page) == (0.0, 0.0, 100.0, 100.0)
    # Nothing left of the box once it is trimmed
    assert clamp_clip((700, 900, 800, 1000), page) is None
    assert clamp_clip(None, page) is None

    # A 116 x 20 box in the top-right corner cuts 457 from the left, 737 from
    # the bottom, 39 from the right and 35 from the top - leaving exactly
    # 116 x 20 for the rasteriser to draw.
    left, bottom, right, top = clip_to_pdfium_cuts((457, 35, 573, 55), page)
    assert (left, bottom, right, top) == (457, 792 - 55, 612 - 573, 35)
    assert (612 - left - right, 792 - bottom - top) == (116, 20)


@check("Two real PO layouts: a Qty column printed as a decimal, and a row "
       "carrying two spellings of one model")
def t_real_po_price_and_qty():
    """
    Two live purchase orders that both came back with no price, for two
    different reasons. Both are covered here so a regression in either rule
    is visible on any machine that has the files.

    1) Samsung PO 514 (my own ERP format). Three defects stacked:
         - "Discount" matched the quantity role by SUBSTRING ("count") and
           "Barcode" matched material_code ("code"), so the real Qty and
           Model columns were orphaned and the price column swallowed a
           second number and was rejected;
         - "Discount / amount" is a stacked label on a NEIGHBOURING line, so
           that column had no x-range at all and donated it to Unit price;
         - the count is printed through a decimal column ("85.00") with the
           UOM in a column of its own, so parse_quantity refused it and the
           block-text fallback took 300 from the description's "300 CFM".

    2) PO 189743 (Electronic Express). One row prints both the item code and
       the vendor reference ("NSE6DG8502SR" and "NSE6DG8502SRAA"). The master
       lists both, so both were confirmed and `multi` blanked the price.
    """
    from engine import (classify_header, find_header_row,
                       group_words_into_rows, parse_line_items,
                       _qty_from_cell, _distinct_models,
                       extract_material_codes)

    # ---- the header must not invent a column from a substring ----
    assert classify_header("Discount") == "", "Discount stole the Qty role"
    assert classify_header("Discount %") == "", "Discount % stole the Qty role"
    assert classify_header("Barcode") == "", "Barcode stole the Model role"
    assert classify_header("Account #") == "", "Account stole the Qty role"
    # ...and the real columns still resolve, squashed spellings included
    assert classify_header("Qty") == "quantity"
    assert classify_header("Model") == "material_code"
    assert classify_header("Unit price") == "unit_price"
    assert classify_header("Ext cost") == "amount"
    assert classify_header("NETPRICE") == "unit_price"

    # ---- a Qty column holds a count even written as a decimal ----
    assert _qty_from_cell("85.00") == "85"
    assert _qty_from_cell("2.00") == "2"
    assert _qty_from_cell("85") == "85"
    # A real fraction, a zero, a line number and junk are still refused
    assert _qty_from_cell("1.5") == ""
    assert _qty_from_cell("0.00") == ""
    assert _qty_from_cell("0008") == ""
    assert _qty_from_cell("99999") == ""
    assert _qty_from_cell("abc") == ""

    # ---- two spellings of one model are ONE item ----
    one = _distinct_models([{"code": "NSE6DG8502SR"},
                            {"code": "NSE6DG8502SRAA"}])
    assert [i["code"] for i in one] == ["NSE6DG8502SRAA"], one
    two = _distinct_models([{"code": "DW80CG4051SR"},
                            {"code": "DVE45T6000W"}])
    assert len(two) == 2, two

    # ---- the real PDFs, when they are present ----
    # The answer key is typed off the paper, so these two run as fixtures
    # rather than being committed: they carry customer data. Point
    # ORDERFLOW_PROBE_PDF_DIR at the folder holding them to run them, and
    # the unit assertions above always run.
    here = Path(__file__).parent
    extra = os.environ.get("ORDERFLOW_PROBE_PDF_DIR") or ""
    pdf_dirs = [here, Path.cwd()] + [Path(extra)] if extra else [here, Path.cwd()]
    # Samsung PO 514 prints "ME17R7021ES" in the Model column and "/AA" on the
    # wrapped description line underneath, so the FULL SKU is
    # ME17R7021ES/AA - the spelling the master list carries and ERP is keyed
    # on. The engine completes the printed code to that form (the line's
    # `printed_code` keeps the short spelling), so the expectation is the /AA
    # one; it said "ME17R7021ES" while the file was absent from the tree.
    for stem, want in (
            ("Samsung PO 514", {"ME17R7021ES/AA": ("85", "199.00", "16915.00")}),
            ("PO-189743",      {"NSE6DG8502SRAA": ("240", "500.00",
                                                    "120000.00")}),
    ):
        pdf = next((p for d in pdf_dirs
                    for p in d.rglob(f"{stem}.pdf") if p.is_file()), None)
        if pdf is None:
            print(f"      note: {stem}.pdf not present - "
                  f"set ORDERFLOW_PROBE_PDF_DIR to run it")
            continue
        res = extract_material_codes(str(pdf), force=True)
        got = {r["material_code"]: (r.get("quantity", ""),
                                    r.get("unit_price", ""),
                                    r.get("amount", ""))
               for r in res.get("records") or []}
        for code, (q, p, a) in want.items():
            assert code in got, f"{stem}: {code} missing, got {sorted(got)}"
            assert got[code][0] == q, f"{stem}: {code} qty {got[code][0]!r} != {q!r}"
            assert got[code][1] == p, f"{stem}: {code} price {got[code][1]!r} != {p!r}"
            assert got[code][2] == a, f"{stem}: {code} amount {got[code][2]!r} != {a!r}"
        # A second spelling of the same model must not remain as its own row
        if stem == "PO-189743":
            assert "NSE6DG8502SR" not in got, sorted(got)


# ══════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════
def st_main():
    # Windows console may not be UTF-8; keep output ASCII-safe
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("=" * 62)
    print(" Material Code Extractor - Local Self-Test")
    print("=" * 62)

    passed, failed, env_issues = 0, 0, 0
    for name, fn in RESULTS:
        try:
            fn()
            passed += 1
            print(f"  [PASS] {name}")
        except (PermissionError, OSError) as e:
            # A locked temp file is an environment problem, not a code defect
            env_issues += 1
            print(f"  [SKIP] {name}")
            print(f"         file locked by another program - "
                  f"close Excel and re-run")
            print(f"         {type(e).__name__}: {e}")
            if VERBOSE:
                traceback.print_exc()
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {name}")
            print(f"         {type(e).__name__}: {e}")
            if VERBOSE:
                traceback.print_exc()

    # Remove this run's scratch directory, and the parent if it is now empty
    try:
        import shutil
        shutil.rmtree(_SCRATCH, ignore_errors=True)
        parent = _SCRATCH.parent
        if parent.name == "_selftest" and not any(parent.iterdir()):
            parent.rmdir()
    except Exception:
        pass

    print("-" * 62)
    line = f"  {passed} passed, {failed} failed"
    if env_issues:
        line += f", {env_issues} skipped (environment)"
    print(line)
    if failed == 0 and env_issues == 0:
        print("  BUILD OK - safe to distribute.")
    elif failed == 0:
        print("  No code defects. Re-run after closing Excel to confirm.")
    else:
        print("  DO NOT distribute until failures are resolved.")
    print("=" * 62)
    return 1 if failed else 0




# ==========================================================================
#  SECTION: dispatcher
# ==========================================================================

USAGE = """Usage:
    python devtools.py                     engine regression tests (default)
    python devtools.py selftest            the same, spelled out
    python devtools.py template            zone-template editor (GUI)
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = "selftest"
    if argv and not argv[0].startswith("-"):
        cmd = argv.pop(0)

    # The two entry points read their options from sys.argv, so hand them
    # whatever is left after the sub-command.
    sys.argv = ["devtools.py"] + argv

    if cmd in ("selftest", "test", "tests"):
        return st_main()
    if cmd in ("template", "editor", "template_editor"):
        tpl_main()
        return 0

    print(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main() or 0)
