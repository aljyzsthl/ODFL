r"""
engine.py - PO extraction engine (single file)

Merged from the four modules that used to live side by side. Behaviour is
unchanged; only the file boundaries are gone:

  ocr_engine     RapidOCR > Tesseract > EasyOCR abstraction, scanned-PDF fallback
  table_parser   word coordinates -> rows / columns / cells (the line_items zone)
  code_matcher   BackboneIndex reference index, code-candidate detection, quantity parsing
  extractor      orchestration: template selection -> zone/text extraction -> PO number
                 -> normalise -> dedupe -> money -> accuracy gate

The single public entry point is extract_material_codes(pdf_path, ...), called by
src\orderflow.py. Everything else below is internal.

Regression tests : python devtools.py
Baseline drift   : python engine_baseline.py compare
Arithmetic check : python engine_audit.py
"""

import os
import re
import csv
import json
import shutil
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from collections import defaultdict

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

# ocr_engine is now part of this file, so the module is always present.
# Whether a real OCR backend can actually be loaded is still decided at
# runtime by ocr_available().
OCR_MODULE_AVAILABLE = True

logger = logging.getLogger(__name__)


# ==========================================================================
#  SECTION: OCR ENGINE - RapidOCR / Tesseract / EasyOCR fallback
#  (formerly ocr_engine.py)
# ==========================================================================

"""
ocr_engine.py - Automatic OCR engine for scanned PDFs

Design principles:
  - Prefer engines installable via pip alone, with no external program (RapidOCR)
  - Auto-discover available engines and fall back (RapidOCR > Tesseract > EasyOCR)
  - Run silently without prompting the user

Engine priority:
  1. RapidOCR (onnxruntime)  - pip install rapidocr-onnxruntime  <- recommended, no external install
  2. Tesseract               - pip install pytesseract + Tesseract-OCR program required
  3. EasyOCR                 - pip install easyocr (PyTorch dependency, large)
"""



# ──────────────────────────────────────────────
# Rendering dependencies (PDF -> image)
# ──────────────────────────────────────────────
try:
    import pymupdf as fitz          # PyMuPDF 1.24+
    FITZ_AVAILABLE = True
except ImportError:
    try:
        import fitz                  # legacy fallback
        FITZ_AVAILABLE = True
    except ImportError:
        FITZ_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

# Second rasteriser. A scanned PO needs the page turned into a bitmap before
# any OCR engine can read it, and PyMuPDF is the only thing the pipeline used
# to accept - so a machine with the pip wheels but no PyMuPDF could not read a
# scan at all. pypdfium2 ships as a plain wheel too (no external program, in
# the same spirit as RapidOCR), so it is used whenever PyMuPDF is missing.
try:
    import pypdfium2 as pdfium
    PDFIUM_AVAILABLE = True
except ImportError:
    PDFIUM_AVAILABLE = False


# ──────────────────────────────────────────────
# Engine discovery (lazy loaded)
# ──────────────────────────────────────────────
_ENGINE_CACHE = {"name": None, "instance": None, "checked": False}

# Render DPI - higher is more accurate but slower.
#
# This is only a FALLBACK. The value that actually renders a scan comes from
# config.json ("ocr_dpi"), because the advice the engine prints on a failed
# scan - "Increase ocr_dpi to 400-600" - is useless if a module constant
# shadows it. See _ocr_with_retry() for the automatic escalation.
OCR_DPI = 300

# A scan whose OCR came back thin is re-rendered once at a higher DPI before
# giving up. Small print (model numbers, the quantity column) is what a low
# raster resolution loses first, and the loss is irreversible once the bitmap
# is gone - PO 25407327 reads "Dacor DRZ30980LAPDA Freezer 2,771.55 2,771.55"
# at 300 DPI with the quantity simply absent.
OCR_RETRY_FACTOR = 1.6
OCR_RETRY_MAX_DPI = 600
# Characters per page below which a first pass is considered thin. A real PO
# page carries several hundred characters; this is deliberately low so that a
# merely sparse page is not re-OCR'd (which would double the run time).
OCR_MIN_CHARS_PER_PAGE = 120


def _try_rapidocr():
    """RapidOCR (ONNXRuntime) - pip only, no external install required."""
    try:
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR()
        logger.info("OCR engine: RapidOCR (onnxruntime)")
        return "rapidocr", engine
    except Exception as e:
        logger.debug(f"RapidOCR unavailable: {e}")
        return None, None


def _tesseract_candidates() -> list:
    """
    Where the Tesseract program may live.

    pytesseract only looks on PATH, but the Windows installer does NOT add
    itself to PATH by default. A machine with Tesseract installed and working
    was therefore reported as "no OCR engine available", and every scanned PO
    came back empty. The usual install folders are checked explicitly.
    """
    if os.name == "nt":
        roots = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.environ.get("LOCALAPPDATA", "")]
        out = [os.path.join(r, "Tesseract-OCR", "tesseract.exe")
               for r in roots if r]
        out += [
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "Programs", "Tesseract-OCR", "tesseract.exe"),
            r"C:\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        ]
    else:
        out = ["/usr/bin/tesseract",
               "/usr/local/bin/tesseract",
               "/opt/homebrew/bin/tesseract",
               "/opt/local/bin/tesseract"]
    return [p for p in out if p]


def find_tesseract() -> str:
    """Absolute path to the Tesseract program, or '' when it is not installed."""
    which = shutil.which("tesseract") if hasattr(shutil, "which") else None
    if which:
        return which
    for cand in _tesseract_candidates():
        if os.path.isfile(cand):
            return cand
    return ""


def _try_tesseract():
    """Tesseract - requires the external Tesseract-OCR program."""
    try:
        import pytesseract

        exe = find_tesseract()
        if exe:
            pytesseract.pytesseract.tesseract_cmd = exe

        # Language data can sit beside the program on a portable/unpacked
        # build, where Tesseract will not find it on its own.
        tessdata = os.path.join(os.path.dirname(exe), "tessdata") if exe else ""
        if tessdata and os.path.isdir(tessdata):
            os.environ.setdefault("TESSDATA_PREFIX", tessdata)

        # Verify the binary is callable
        pytesseract.get_tesseract_version()
        logger.info(f"OCR engine: Tesseract ({exe or 'PATH'})")
        return "tesseract", pytesseract
    except Exception as e:
        logger.debug(f"Tesseract unavailable: {e}")
        return None, None


def _try_easyocr():
    """EasyOCR - depends on PyTorch."""
    try:
        import easyocr
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        logger.info("OCR engine: EasyOCR")
        return "easyocr", reader
    except Exception as e:
        logger.debug(f"EasyOCR unavailable: {e}")
        return None, None


def get_ocr_engine(preferred: str = "auto") -> tuple:
    """
    Return an available OCR engine. Discovery runs once and is cached.
    Returns: (engine_name, engine_instance) or (None, None)
    """
    if _ENGINE_CACHE["checked"] and preferred == "auto":
        return _ENGINE_CACHE["name"], _ENGINE_CACHE["instance"]

    finders = {
        "rapidocr":  _try_rapidocr,
        "tesseract": _try_tesseract,
        "easyocr":   _try_easyocr,
    }

    # If a specific engine is requested, try only that one
    if preferred in finders:
        name, inst = finders[preferred]()
        if inst is not None:
            _ENGINE_CACHE.update(name=name, instance=inst, checked=True)
            return name, inst

    # Auto: probe in priority order
    for key in ("rapidocr", "tesseract", "easyocr"):
        name, inst = finders[key]()
        if inst is not None:
            _ENGINE_CACHE.update(name=name, instance=inst, checked=True)
            return name, inst

    _ENGINE_CACHE.update(name=None, instance=None, checked=True)
    logger.warning(
        "No OCR engine available. "
        "Run: pip install rapidocr-onnxruntime"
    )
    return None, None


def ocr_available() -> bool:
    name, _ = get_ocr_engine()
    return name is not None


def ocr_engine_name() -> str:
    name, _ = get_ocr_engine()
    return name or "(none)"


# ──────────────────────────────────────────────
# Post-processing - reconstruct lines from coordinates
# ──────────────────────────────────────────────
def _group_lines(items: list[dict]) -> str:
    """
    Group token-level OCR output by y coordinate to restore original lines.
    e.g. ["PO","Number:","0736499"] -> "PO Number: 0736499"
    Essential for preserving column alignment in tabular documents.
    """
    if not items:
        return ""

    # Use 60% of mean glyph height as the same-line threshold. A word's y is
    # its BASELINE (see _ocr_words), and on a skewed scan the baseline drifts
    # by more than that across a wide line, so each word is compared with the
    # line's own running baseline rather than with the previous word.
    heights = [i["h"] for i in items if i["h"] > 0]
    tol = (sum(heights) / len(heights) * 0.6) if heights else 8

    items.sort(key=lambda i: (i["y"], i["x"]))

    lines = []
    current = [items[0]]
    for it in items[1:]:
        base = max(w["y"] for w in current)
        if abs(it["y"] - base) <= tol:
            current.append(it)
        else:
            lines.append(current)
            current = [it]
    lines.append(current)

    return _group_word_list([w for line in lines for w in line], tol=tol)


def _group_word_list(items: list[dict], tol: float = None) -> str:
    """Rows from words carrying {text, x, y, h}; `y` is the baseline."""
    if not items:
        return ""
    if tol is None:
        heights = [i["h"] for i in items if i.get("h", 0) > 0]
        tol = (sum(heights) / len(heights) * 0.6) if heights else 8

    lines, current = [], []
    for it in sorted(items, key=lambda i: (i["y"], i["x"])):
        if current and abs(it["y"] - max(w["y"] for w in current)) > tol:
            lines.append(current)
            current = []
        current.append(it)
    if current:
        lines.append(current)

    out = []
    for line in lines:
        line.sort(key=lambda i: i["x"])
        out.append("  ".join(str(t["text"]).strip() for t in line
                             if str(t.get("text") or "").strip()))
    return "\n".join(l for l in out if l)


def _ocr_words(pil_image) -> list[dict]:
    """
    Per-WORD boxes from the OCR engine, in the same shape pdfplumber uses:
    {text, x0, x1, top, bottom}.

    A scan has no text layer, so without this the only thing the engine knows
    is the flattened OCR text - and on a scanned table that means reading
    "2026 4 1,265.00" as "quantity 2026, price 4". Models, quantities and
    prices are then resolved by the column a word was printed in, exactly as
    for a PDF with a text layer (extract_page_line_items).
    """
    name, engine = get_ocr_engine()
    if engine is None:
        return []

    if name == "tesseract":
        data = engine.image_to_data(pil_image, lang="eng", config="--psm 6",
                                    output_type=engine.Output.DICT)
        words = []
        for i, raw in enumerate(data.get("text") or []):
            t = str(raw or "").strip()
            if not t or not any(ch.isalnum() for ch in t):
                continue
            try:
                conf = float(data["conf"][i])
            except (KeyError, TypeError, ValueError):
                conf = 100.0
            if conf < 0:                 # -1 marks a non-word box
                continue
            x = float(data["left"][i])
            y = float(data["top"][i])
            w = float(data["width"][i])
            h = float(data["height"][i])
            if w <= 0 or h <= 0:
                continue
            words.append({"text": t, "x0": x, "x1": x + w, "top": y,
                          "bottom": y + h})
        return words

    if name == "rapidocr":
        if not NUMPY_AVAILABLE:
            return []
        arr = np.array(pil_image.convert("RGB"))
        result, _ = engine(arr)
        words = []
        for it in result or []:
            if len(it) < 2 or not it[1]:
                continue
            xs = [p[0] for p in it[0]]
            ys = [p[1] for p in it[0]]
            t = str(it[1]).strip()
            if not t:
                continue
            words.append({"text": t, "x0": float(min(xs)),
                          "x1": float(max(xs)), "top": float(min(ys)),
                          "bottom": float(max(ys))})
        return words

    return []


# ──────────────────────────────────────────────
# Image -> text
# ──────────────────────────────────────────────
def image_to_text(pil_image, lang: str = "eng") -> str:
    """Extract text from a PIL image."""
    name, engine = get_ocr_engine()
    if engine is None:
        return ""

    try:
        if name == "rapidocr":
            if not NUMPY_AVAILABLE:
                return ""
            return _group_lines([
                {"text": w["text"], "x": w["x0"], "y": w["bottom"],
                 "h": w["bottom"] - w["top"]} for w in _ocr_words(pil_image)])

        elif name == "tesseract":
            # PSM 6: assume a uniform block of text (suits tabular documents).
            # The text is rebuilt from the WORD boxes rather than taken from
            # image_to_string, so the flattened text and the words the column
            # reader uses are the same reading of the page.
            words = _ocr_words(pil_image)
            if words:
                return _group_word_list(
                    [{"text": w["text"], "x": w["x0"], "y": w["bottom"],
                      "h": w["bottom"] - w["top"]} for w in words])
            return engine.image_to_string(
                pil_image, lang=lang, config="--psm 6"
            )

        elif name == "easyocr":
            if not NUMPY_AVAILABLE:
                return ""
            return _group_lines([
                {"text": w["text"], "x": w["x0"], "y": w["bottom"],
                 "h": w["bottom"] - w["top"]} for w in _ocr_words(pil_image)])

    except Exception as e:
        logger.error(f"OCR execution error ({name}): {e}")

    return ""


# ──────────────────────────────────────────────
# PDF -> bitmap (PyMuPDF preferred, pypdfium2 fallback)
# ──────────────────────────────────────────────
def render_backend() -> str:
    """Which rasteriser can be used: 'pymupdf', 'pdfium' or ''."""
    if FITZ_AVAILABLE and PIL_AVAILABLE:
        return "pymupdf"
    if PDFIUM_AVAILABLE and PIL_AVAILABLE:
        return "pdfium"
    return ""


def clamp_clip(clip: tuple, page_size: tuple) -> Optional[tuple]:
    """
    Clip a (x0, y0, x1, y1) box to the sheet; None when nothing is left.

    A zone template is drawn against one scan, but the same customer can send a
    later PDF with a different paper size. Handing an out-of-sheet rectangle to
    a rasteriser is either a crash (pypdfium2 refuses it) or a silently empty
    image (PyMuPDF), so the box is trimmed to the page first.
    """
    if not clip:
        return None
    w, h = page_size
    x0, y0, x1, y1 = (float(v) for v in clip)
    x0, x1 = max(0.0, min(x0, w)), max(0.0, min(x1, w))
    y0, y1 = max(0.0, min(y0, h)), max(0.0, min(y1, h))
    return (x0, y0, x1, y1) if (x1 > x0 and y1 > y0) else None


def clip_to_pdfium_cuts(clip: tuple, page_size: tuple) -> tuple:
    """
    Convert a top-left rect into the per-edge cut amounts pypdfium2 expects.

    pypdfium2's `crop` is not the rectangle to keep - it is how much to cut off
    each edge, as (left, bottom, right, top) measured from a bottom-left origin.
    Passing the rectangle itself cut the whole page away and every zone OCR
    came back as "Crop exceeds page dimensions".
    """
    x0, y0, x1, y1 = clip
    w, h = page_size
    return (x0, h - y1, w - x1, y0)


class PageRasteriser:
    """
    Rasterise PDF pages to PIL images for OCR.

    PyMuPDF is tried first: the zone rectangles in customer_templates.json
    were drawn against its top-left origin, so it keeps existing templates
    pixel-identical. pypdfium2 is the fallback - it is a pip wheel with no
    external program, so a laptop that only ran `pip install -r requirements`
    can still read a scanned PO.

    Both are addressed by page index and accept a clip box in PDF points with a
    top-left origin (the convention customer_templates.json was drawn in).
    pypdfium2 therefore needs translating twice - its crop is the amount cut
    off each edge, measured from a bottom-left origin - and that is done here
    so callers never have to care which backend is in use.
    """

    def __init__(self, pdf_path: str):
        self.kind = render_backend()
        if not self.kind:
            raise RuntimeError(
                "No PDF rasteriser available - install PyMuPDF or pypdfium2"
            )
        if self.kind == "pymupdf":
            self._doc = fitz.open(pdf_path)
        else:
            self._doc = pdfium.PdfDocument(pdf_path)

    def __len__(self) -> int:
        return len(self._doc)

    def page_size(self, index: int) -> tuple:
        """(width, height) of one page, in PDF points."""
        if self.kind == "pymupdf":
            r = self._doc[index].rect
            return r.width, r.height
        return self._doc[index].get_size()

    def render(self, index: int, dpi: int = OCR_DPI, clip: Optional[tuple] = None):
        """Rasterise a page (or a clip box, top-left origin) to a PIL image."""
        scale = dpi / 72.0

        if clip:
            clip = clamp_clip(clip, self.page_size(index))

        if self.kind == "pymupdf":
            page = self._doc[index]
            mat = fitz.Matrix(scale, scale)
            pix = (page.get_pixmap(matrix=mat, clip=fitz.Rect(*clip))
                   if clip else page.get_pixmap(matrix=mat))
            return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        page = self._doc[index]
        kwargs = {"scale": scale}
        if clip:
            kwargs["crop"] = clip_to_pdfium_cuts(clip, self.page_size(index))
        return page.render(**kwargs).to_pil()

    def close(self):
        try:
            self._doc.close()
        except Exception:
            pass


# ──────────────────────────────────────────────
# Full-PDF OCR
# ──────────────────────────────────────────────
def ocr_pdf(pdf_path: str, lang: str = "eng",
            dpi: int = OCR_DPI,
            progress_callback=None) -> list[dict]:
    """
    OCR an entire scanned PDF.
    Returns: [{page_num, text, tables}, ...] (same shape as extractor.get_pages)
    """
    if not render_backend() or not PIL_AVAILABLE:
        logger.error(
            "Cannot render for OCR: PyMuPDF or pypdfium2 plus Pillow are required"
        )
        return []

    if not ocr_available():
        return []

    pages = []
    doc = None
    try:
        doc = PageRasteriser(pdf_path)
        total = len(doc)

        for i in range(total):
            if progress_callback:
                progress_callback(
                    int(100 * i / max(1, total)),
                    f"Running OCR ({ocr_engine_name()}): page {i+1}/{total}"
                )

            img = doc.render(i, dpi)
            text = image_to_text(img, lang)
            # Word boxes, scaled from pixels back into PDF points. A scan then
            # carries the same coordinates a text layer does, and the page
            # column reader can resolve quantity and price by the column they
            # were printed in instead of by their order on the line.
            words = []
            for w in _ocr_words(img):
                words.append({
                    "text":   w["text"],
                    "x0":     w["x0"] * 72.0 / dpi,
                    "x1":     w["x1"] * 72.0 / dpi,
                    "top":    w["top"] * 72.0 / dpi,
                    "bottom": w["bottom"] * 72.0 / dpi,
                })
            pages.append({
                "page_num": i + 1,
                "text": text,
                "tables": [],       # OCR does not provide table structure
                "words": words,
                "ocr": True,
            })

        logger.info(
            f"OCR complete: {Path(pdf_path).name} "
            f"({total} page(s), {sum(len(p['text']) for p in pages):,} chars, "
            f"{doc.kind})"
        )
    except Exception as e:
        logger.error(f"OCR processing failed: {e}")
        return []
    finally:
        if doc is not None:
            doc.close()

    return pages


# ──────────────────────────────────────────────
# Zone-area OCR (Zone Template + scanned PDF)
# ──────────────────────────────────────────────
def ocr_zone(pdf_path: str, zone: dict,
             lang: str = "eng", dpi: int = OCR_DPI) -> str:
    """
    Crop only the given zone to an image and OCR it.
    Zone coordinates are in PDF points (same system as pdfplumber/PyMuPDF).
    """
    if not render_backend() or not PIL_AVAILABLE or not ocr_available():
        return ""

    doc = None
    try:
        doc = PageRasteriser(pdf_path)
        page_idx = zone.get("page", 0)
        if page_idx >= len(doc):
            return ""

        clip = (zone["x0"], zone["y0"], zone["x1"], zone["y1"])
        img = doc.render(page_idx, dpi, clip=clip)

        if img.width < 5 or img.height < 5:
            return ""

        # Upscale small areas to improve recognition
        if img.width < 300 or img.height < 60:
            img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)

        return image_to_text(img, lang).strip()

    except Exception as e:
        logger.error(f"Zone OCR error: {e}")
        return ""
    finally:
        if doc is not None:
            doc.close()


# ──────────────────────────────────────────────
# Install hint (used by the UI)
# ──────────────────────────────────────────────
def install_hint() -> str:
    return (
        "Installing an OCR engine enables automatic processing of scanned PDFs.\n\n"
        "Recommended (no external program required):\n"
        "    pip install rapidocr-onnxruntime\n\n"
        "Alternatives:\n"
        "    pip install pytesseract   (+ Tesseract-OCR program required, found\n"
        "                               on PATH or in its usual install folder)\n"
        "    pip install easyocr       (large, PyTorch based)\n\n"
        "A scanned PDF also has to be turned into an image first:\n"
        "    pip install pypdfium2     (used when PyMuPDF is not installed)"
    )


def status_summary() -> dict:
    """OCR status summary for the UI."""
    name, _ = get_ocr_engine()
    backend = render_backend()
    return {
        "available":   name is not None and bool(backend),
        "engine":      name or "",
        "renderer":    backend,
        "renderer_ok": bool(backend),
        "hint":        "" if (name and backend) else install_hint(),
    }


# ==========================================================================
#  SECTION: TABLE PARSER - word coordinates to rows / columns / cells
#  (formerly table_parser.py)
# ==========================================================================

"""
table_parser.py - Structure a line-item table from word coordinates

Why this exists
---------------
Asking the user to draw one box for Material Code and a second box for Quantity
is fragile: the two boxes must line up vertically, and any drift breaks the
pairing. It also forces the user to reason about pixel-level column edges.

Instead the user draws ONE box around the whole line-item table. This module
then works out the structure from the words inside it:

    1. Group words into visual rows by y coordinate
    2. Locate the header row (Qty / Unit / Price / Description / ...)
    3. Derive column boundaries from the header word positions
    4. Assign every word to a column, producing real table cells
    5. Merge continuation rows (wrapped description text) into their parent

The result is a list of line items where the code and its quantity are joined
because they physically sit on the same row - not because two separate zones
happened to align.
"""




# ──────────────────────────────────────────────
# Column header vocabulary
# ──────────────────────────────────────────────
COLUMN_ROLES = {
    # NB: "description" is deliberately NOT listed here. It used to be, and
    # because the lookup is longest-word-first it won the material_code role
    # over the real code column ("Description | Item #" -> the description was
    # read as the model and the item number spilled into the quantity cell).
    # A column headed "Description" is a description; the code column is
    # whatever else the table names it (item #, sku, material, model ...).
    "material_code": [
        "material code", "material", "item code", "item no", "item #", "item",
        "part number", "part no", "part #", "part", "model no", "model #",
        "model", "sku", "product code", "product", "code", "mfg", "vendor code",
        "option selection", "style/color", "style / color",
        # "Model Number" / "Item Number" spell the same column out in full.
        # Without these the two-word label could not be joined - the join step
        # only accepts a KNOWN phrase - so the header stayed split: "Model"
        # anchored a column only as wide as itself and "Number" became an
        # unnamed cell of its own. The code, printed wider than "Model", then
        # fell into that unnamed cell and material_code came back empty
        # (PO 170891). "part number" was listed while its synonyms were not,
        # which is what made the gap look arbitrary.
        "model number", "item number", "material number", "product number",
        "model num", "item num", "part num", "catalog number", "catalog no",
        "catalog #", "catalog",
    ],
    "quantity": [
        "qty", "quantity", "order qty", "qty ordered", "ordered", "q'ty",
        "units", "count",
        # Stacked headers print the qualifier on the line BELOW the shared
        # label: "Qty" over "Ord" / "Rec" (PO 189743). "Ord" alone must anchor
        # the quantity column or the count falls into an unnamed one. "Rec"
        # (received) deliberately stays unnamed - received is not ordered.
        # Word-boundary matching keeps "ord" away from "Order"/"Ordered".
        "ord",
    ],
    # A printed line number is a column of its own, NOT a quantity. While the
    # vocabulary had no name for it, the header cell matched nothing, so its
    # x-range was handed to the neighbouring named column and the line number
    # was read as the count (PO 6-95635-1026 prints "Line# ... Qty ...").
    "line_no": [
        "line#", "line #", "line no", "line no.", "line number", "ln#",
        "seq#", "line",
    ],
    "unit": [
        "unit", "uom", "u/m", "each", "per",
    ],
    # Priority is expressed through term length: _role_score prefers the
    # longest matching term, so "unit cost" (9) beats "po cost" (7) beats a
    # bare "cost" (4). Purchase orders often print several cost columns
    # (PO COST / INV COST / EXT COST) and only one is the unit price.
    "unit_price": [
        "unit price", "unit cost", "cost each", "each cost", "list price",
        "po cost", "inv cost", "invoice cost", "net price", "u/p", "rate",
        "price", "cost",
    ],
    "amount": [
        "extended cost", "extended price", "extended amount", "ext cost",
        "ext price", "ext amount", "line total", "net amount", "line amount",
        "extended", "amount", "total", "value",
        # ERP One (Tri State) prints the line total as "Line Value", in the
        # same row as "Quantity Product Expected Unit Price" - 'Line' alone is
        # the LINE-NUMBER column, so the pair has to be a known phrase for the
        # two halves to be joined. Without it the values were read as line
        # numbers and the amount column came back empty.
        "line value",
        # Stacked headers: "Extend" above "Cost" (PO 189743). The document
        # prints "Extend", the vocabulary says "extended" - both must resolve.
        "extend cost", "extend price",
        # 'ext' is the abbreviation the cell-grid path used to catch with a bare
        # substring test; as a word-boundary alias it still resolves a column
        # headed "EXT" without also claiming "Extension"/"Extra".
        "ext",
    ],
    "description": [
        "description", "desc", "product name", "style/color",
        "style / color", "name", "details",
        # Removed on purpose: "item description". It is a two-word phrase, so
        # it beat the bare "Item" that sits beside it and claimed the whole
        # width of both cells. N104789 page 2 is headed
        #
        #     Unit Size | Date | Item | Description | Unit Price ...
        #
        # where "Item" is the model column and "Description" the text column.
        # The phrase made material_code coincide with the description, the
        # code fell into the description cell, and the order came out one
        # line short ($833.00). A PO that really labels a column "Item
        # Description" is still read as a description - the bare word
        # "description" in that phrase matches on its own.
    ],
}

# Longer phrases first so "unit price" beats "unit"
_ROLE_LOOKUP = []
for _role, _words in COLUMN_ROLES.items():
    for _w in _words:
        _ROLE_LOOKUP.append((_w, _role))
_ROLE_LOOKUP.sort(key=lambda x: -len(x[0]))

# Header words are matched on WORD BOUNDARIES, never as a bare substring.
# The vocabulary carries short but load-bearing aliases ("qty", "u/m", "u/p")
# that a substring rule needs a length floor to survive, and that floor made
# them unreachable: 'Ord Qty' resolved to nothing and 'Total Qty' to amount,
# so a quantity column either vanished or became the money column.
_BOUNDARY_RE = {}
for _w, _r in _ROLE_LOOKUP:
    _BOUNDARY_RE.setdefault(
        _w, re.compile(r"(?<![a-z0-9])" + re.escape(_w) + r"(?![a-z0-9])"))

# The exact phrase table: normalized header text -> role. Only a phrase listed
# here may be formed by joining two words (see _row_header_anchors), which is
# what keeps "Unit" + "Price" from being treated like "Description" + "Qty".
_EXACT_ROLE = {}
for _w, _r in _ROLE_LOOKUP:
    _EXACT_ROLE.setdefault(_w, _r)

# Qualifier words a PO prints in front of a column name, and which lose their
# meaning once a header is printed without spaces ("NETPRICE", "EXTPRICE").
# They are what makes pass 3 of classify_header safe to run at all: a fragment
# is accepted only when what is left over is one of these (or a vocabulary
# phrase), so "barcode" (leftover "bar") and "discount" (leftover "dis") are
# refused instead of stealing the material_code / quantity role.
_HEADER_MODIFIERS = {
    "net", "unit", "u", "ext", "list", "po", "inv", "invoice", "total",
    "each", "cost", "price", "order", "ord", "std", "suggested", "sku",
    "item", "part", "item's", "customer's",
}


def _norm_header(text: str) -> str:
    """Fold a header cell to the form the vocabulary is written in."""
    t = (text or "").strip().lower()
    t = re.sub(r"[^\w\s/'#]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _phrase_re(word: str):
    """Compiled word-boundary matcher for one vocabulary entry."""
    r = _BOUNDARY_RE.get(word)
    if r is None:
        r = re.compile(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])")
        _BOUNDARY_RE[word] = r
    return r


def _names_quantity(t: str) -> bool:
    """True when a header cell names a quantity anywhere in its text."""
    return any(role == "quantity" and _phrase_re(word).search(t)
               for word, role in _ROLE_LOOKUP)


def _alias_conf(text: str, span: int) -> int:
    """
    How reliably a header cell was matched: 3 = exact entry, 2 = on a word
    boundary, 1 = only as a fragment of a squashed header.

    Used to break ties when two cells claim the same column role, so the
    better match wins regardless of which label is longer. On PO 514 the
    "Qty" and "Model" cells are exact hits while "Discount" ("count") and
    "Barcode" ("code") only resolve as fragments; without this the fragment
    won on length and both real columns were orphaned.
    """
    t = _norm_header(text)
    if not t:
        return 0
    if _EXACT_ROLE.get(t):
        return 3
    for word, role in _ROLE_LOOKUP:
        if role and _phrase_re(word).search(t):
            return 2
    return 1


def classify_header(text: str) -> str:
    """Map a header cell to a column role, or '' when unknown.

    Three passes, most reliable first:

      1. the cell IS a vocabulary entry ("Qty", "Unit Price")
      2. a vocabulary entry appears in it on word boundaries ("Ord Qty")
      3. a longer entry appears inside it, but ONLY when the rest of the cell
         is itself a known header modifier or a vocabulary phrase
         ("NETPRICE" -> "net" + "price"), so a squashed header still resolves
         while an English word is never mistaken for a column.

    Pass 3 is deliberately NARROW, because a bare substring is a trap: a
    vocabulary word sitting inside an ordinary English word is NOT that
    column. "count" inside "Discount" made every discount column a QUANTITY,
    and "code" inside "Barcode" made the barcode column the MATERIAL CODE -
    which is exactly how PO 514 lost its Qty and Model columns and with them
    the price. The pass runs only when what is left over is meaningful.
    """
    t = _norm_header(text)
    if not t:
        return ""

    exact = _EXACT_ROLE.get(t)
    if exact:
        return exact

    for word, role in _ROLE_LOOKUP:
        if not _phrase_re(word).search(t):
            continue
        # 'total' is the weakest amount alias there is. A cell that also names
        # a quantity is a quantity column ("Total Qty"), never an amount one;
        # a pure total ("Order Total", "Grand Total") still is an amount.
        if word == "total" and role == "amount" and _names_quantity(t):
            continue
        return role

    for word, role in _ROLE_LOOKUP:
        if len(word) < 4 or word not in t:
            continue
        rest = t.replace(word, "", 1).strip()
        # Only a fragment of the cell is a column name. Accept that ONLY when
        # the rest is a header word in its own right: "netprice" -> "net" +
        # "price", "extcost" -> "ext" + "cost", "unitprice" -> "unit" +
        # "price". Anything else is an ordinary English word that merely
        # CONTAINS an alias: "discount" holds "count", "barcode" holds "code",
        # "account" holds "count" - and none of them is a quantity or a
        # material column.
        if not rest:
            continue
        if (_EXACT_ROLE.get(rest)
                or rest in _HEADER_MODIFIERS):
            return role
    return ""


# ──────────────────────────────────────────────
# Row grouping
# ──────────────────────────────────────────────
def group_words_into_rows(words: list, tol_ratio: float = 0.35) -> list:
    """
    Group words into visual rows by their vertical position.

    The tolerance is deliberately tight. If two printed lines are merged into
    one row, their words interleave once sorted by x, producing corrupted
    tokens such as 'DISWH8W0ACSGH4E0R5' from two overlapping text columns.
    A slightly split row is harmless because blocks are merged afterwards,
    whereas a wrongly merged row destroys the data.

    Returns: [{"top", "bottom", "words": [...]}, ...] ordered top to bottom.
    """
    if not words:
        return []

    # Vertical glyphs (table rules / decorative borders emitted as characters,
    # pdfplumber reports them with upright=False) cannot be grouped into a
    # horizontal row: they interleave with the real text once sorted by x and
    # corrupt the tokens around them - "(cid:7)" fragments landing inside the
    # description and money cells of PO 189743. Horizontal text only, and the
    # row tolerance is derived from it alone (the 0.48pt-tall rule glyphs
    # would otherwise drag the average down).
    horizontal = [w for w in words if w.get("upright", True)]
    heights = [w["bottom"] - w["top"] for w in horizontal
               if w["bottom"] > w["top"]]
    tol = (sum(heights) / len(heights) * tol_ratio) if heights else 3.0
    ordered = sorted(horizontal, key=lambda w: (w["top"], w["x0"]))
    if not ordered:
        return []
    rows, current = [], [ordered[0]]

    for w in ordered[1:]:
        # Compare against the row's first word rather than a running mean so
        # the band cannot drift downwards and swallow the next line.
        ref = current[0]["top"]
        if abs(w["top"] - ref) <= tol:
            current.append(w)
        else:
            rows.append(current)
            current = [w]
    rows.append(current)

    out = []
    for r in rows:
        r.sort(key=lambda w: w["x0"])
        out.append({
            "top":    min(w["top"] for w in r),
            "bottom": max(w["bottom"] for w in r),
            "words":  r,
            "text":   " ".join(w["text"] for w in r).strip(),
        })
    return out


# ──────────────────────────────────────────────
# Header detection
# ──────────────────────────────────────────────
def _header_pair_gap(words: list) -> float:
    """
    How far apart two words may sit and still be one printed header label.

    "Unit Price" is two words about one space apart; "Qty   Price" is two
    columns. The threshold is relative to the glyph height so it survives a
    change of font size. Too generous and two columns get merged into one
    label; too tight and split labels stay split, which is the bug this
    exists to fix (COLUMN_ALIGNMENT P0-3).
    """
    hs = [w["bottom"] - w["top"] for w in words if w["bottom"] > w["top"]]
    return max(3.0, (sum(hs) / len(hs)) * 0.8) if hs else 8.0


def _right_aligned_header_pairs(words: list) -> list:
    """
    Candidate header anchors for a two-word label whose halves both sit in a
    column of right-aligned numbers ('Line' + 'Value' -> 'line value').

    Returns the same tuples `_row_header_anchors()` builds, so the caller can
    add them to its own list. The evidence is the columns, not the wording: a
    cell formed by BOTH words must still classify as a role, and the RIGHT
    edges of the two words must fall within that role's own value column.
    """
    cands = []
    gap_max = _header_pair_gap(words)
    for i in range(len(words) - 1):
        a, b = words[i], words[i + 1]
        # Far apart, or in one cell already? Not two halves.
        gap = b["x0"] - a["x1"]
        if gap > gap_max or gap < -1.0 or a["top"] != b["top"]:
            continue
        text = f"{a['text']} {b['text']}"
        role = _EXACT_ROLE.get(_norm_header(text), "")
        if not role or role not in ("amount", "unit_price", "quantity"):
            continue
        if abs(a["x1"] - b["x1"]) > 4.0:
            continue                    # the two halves do not share an edge
        if classify_header(a["text"]) or classify_header(b["text"]):
            continue                    # a half that is its own column label
        cands.append((2, _alias_conf(text, 2), len(text), i, i + 2, role))
    return cands


def _row_header_anchors(row: dict, max_span: int = 2,
                        upper: list = None) -> tuple:
    """
    The column anchors one printed row provides.

    Returns (anchors, blanks):
      anchors  {role: (x0, x1)}    for every header cell the vocabulary named
      blanks   [(x0, x1), ...]     for header cells it did NOT name

    Header words are considered as phrases of up to `max_span` adjacent words
    ("Unit" + "Price"), and a longer phrase beats its own fragments. A word
    may belong to at most one role, so a label can no longer be split into two
    half-width anchors - which is how the price column ended up bounded down
    its middle and the number fell into the neighbouring 'unit' column.

    `upper` are the words of the row printed directly ABOVE this one. Several
    PO layouts stack one column label across two lines - "Unit" over "Cost",
    "Extend" over "Cost", "Qty" over "Ord" (PO 189743). When the chosen header
    row leaves such a column unnamed, the word above completes the phrase:
    "Unit" + "Cost" joins to the known phrase "unit cost". A join may also
    TAKE OVER a role a weaker label already claimed: on PO 189743 the bare
    "Price" (retail column, always empty) grabbed unit_price ahead of the
    "Unit / Cost" pair; the more specific phrase wins and the weaker word
    returns to the unnamed pool.

    The unnamed cells are returned rather than dropped because a column the
    vocabulary does not know ("Brand") would otherwise donate its width to the
    column beside it, and its text would be read as that column's value.
    """
    words = row.get("words") or []
    if not words:
        return {}, []
    gap_max = _header_pair_gap(words)

    cands = []
    for i in range(len(words)):
        for span in range(1, max_span + 1):
            j = i + span
            if j > len(words):
                break
            if span > 1:
                gap = words[j - 1]["x0"] - words[j - 2]["x1"]
                if gap > gap_max:
                    break          # a gap that wide is a column boundary
            text = " ".join(w["text"] for w in words[i:j])
            if span == 1:
                role = classify_header(text)
            else:
                # Two words are joined only when the result is a KNOWN header
                # phrase ("Unit Price"). Otherwise they are two columns that
                # happen to sit close together ("Description" + "Qty"), and
                # fusing them would delete one of them.
                role = _EXACT_ROLE.get(_norm_header(text), "")
            if role:
                # (span, confidence, text length) - the longest phrase wins,
                # then the most reliably-matched one, and the sort is stable so
                # an entry registered under two roles keeps the first one
                # (style/color stays material_code, as before).
                #
                # Confidence is what keeps a weak label from stealing a role:
                # PO 514 prints "Qty" (word-boundary/alias hit) beside
                # "Discount" (only a substring of it - "count"), and "Model"
                # beside "Barcode" ("code"). Ranking on length alone let the
                # longer-but-wrong word win, orphaning the real Qty and Model
                # columns as unnamed cells.
                cands.append((span, _alias_conf(text, span), len(text), i, j, role))

    # A numeric label can be split over two lines of a ONE-line header row:
    # ERP One prints "Quantity Product Expected Unit Price Line Value", where
    # "Line" and "Value" are the two halves of "Line Value" and "Qty" and
    # "Unit Price" sit between them. Joining is refused above unless the pair
    # is a known phrase, because "Description Qty" is two columns - but the
    # RIGHT-aligned numeric columns are the exception, and the data proves it:
    # both halves of "Line Value" print at exactly the same right edge, while a
    # neighbouring "OD Qty" or "Qty Price" never does. Read without this, the
    # amount column lost its bounds and the line values were read as LINE
    # numbers, the amount column came back empty, and the audit's per-line
    # check called a correct extraction "SWAPPED".
    cands += _right_aligned_header_pairs(words)
    cands.sort(key=lambda c: (-c[0], -c[1], -c[2]))

    used = [False] * len(words)
    anchors = {}
    holder_text = {}        # role -> the label that claimed it
    holder_span = {}        # role -> (i, j) of the claiming words
    for _span, _conf, _tlen, i, j, role in cands:
        if role in anchors or any(used[i:j]):
            continue
        for k in range(i, j):
            used[k] = True
        anchors[role] = (words[i]["x0"], words[j - 1]["x1"])
        holder_text[role] = " ".join(w["text"] for w in words[i:j])
        holder_span[role] = (i, j)

    # Stacked-label completion: an unnamed cell whose x-band lines up with a
    # word in the row above may be the lower half of that word's label.
    if upper:
        for k, w in enumerate(words):
            if used[k]:
                continue
            for u in upper:
                if u["x1"] < w["x0"] or w["x1"] < u["x0"]:
                    continue            # not the same column band
                phrase = _norm_header(f"{u['text']} {w['text']}")
                role = _EXACT_ROLE.get(phrase, "")
                if not role:
                    continue
                cur = anchors.get(role)
                if cur is not None and len(holder_text.get(role, "")) >= len(phrase):
                    continue            # current claim is at least as specific
                if cur is not None:
                    # The weaker label loses the role; its words go back to
                    # the unnamed pool so they bound their own column again.
                    for m in range(*holder_span[role]):
                        used[m] = False
                anchors[role] = (min(u["x0"], w["x0"]), max(u["x1"], w["x1"]))
                holder_text[role] = phrase
                holder_span[role] = (k, k + 1)
                used[k] = True
                break

    blanks = [(w["x0"], w["x1"]) for k, w in enumerate(words) if not used[k]]
    return anchors, blanks


def _absorb_split_header(rows: list, idx: int, colmap: dict) -> set:
    """
    Complete a header label that was printed across two lines.

    "Unit" on the header line and "Price" on the line below describe ONE
    column. Left alone, the lower word was read as data ('599.00 Price' landed
    in the unit cell) and the column stayed anchored on half a label. Here the
    two are joined, the fragment anchor is dropped, and the words taken from
    the lower line are reported back so the caller can leave them out of the
    body (COLUMN_ALIGNMENT P0-3 / P0-6).

    Returns a set of id()s of the absorbed word dicts.
    """
    absorbed = set()
    if idx < 0 or idx + 1 >= len(rows):
        return absorbed

    upper = rows[idx]["words"]
    for w in rows[idx + 1]["words"]:
        role = classify_header(w["text"])
        if not role:
            continue
        for u in upper:
            if u["x1"] < w["x0"] or w["x1"] < u["x0"]:
                continue                       # not the same column band
            # As on one line, only a KNOWN phrase may be joined.
            joined = _EXACT_ROLE.get(
                _norm_header(f"{u['text']} {w['text']}"), "")
            # Only a phrase that CHANGES the role counts: "Description" +
            # "Name" still means description, so nothing was split and the
            # lower word must stay data.
            if not joined or joined == classify_header(u["text"]):
                continue
            if joined in colmap and colmap[joined] != (u["x0"], u["x1"]):
                continue                       # role already owned elsewhere
            for sub, span in list(colmap.items()):
                if span == (u["x0"], u["x1"]):
                    del colmap[sub]            # drop the fragment anchor
            colmap[joined] = (min(u["x0"], w["x0"]), max(u["x1"], w["x1"]))
            absorbed.add(id(w))
            break
    return absorbed


def find_header_row(rows: list, max_scan: int = 8) -> tuple:
    """
    Find the row that looks like a column header.
    Returns: (row_index, {role: (x0, x1)}, absorbed_word_ids, band) or
    (-1, {}, set(), []) - `band` is the neighbouring header lines
    (see _header_band), empty when there are none.

    The returned map may also carry the unnamed header cells under the reserved
    keys '_blank1', '_blank2' ... . They exist only so `build_column_bounds`
    can draw a boundary where the document draws one; they are filtered out of
    the `columns` a caller sees (see parse_line_items).

    `max_scan` is how far down the page to look. A zone is cropped to its table
    so 8 rows is plenty, but a whole page carries the address and date blocks
    first - on PO 6-95635-1026 the item header is row 15, so a page-level scan
    has to reach further (see extract_page_line_items).
    """
    best_idx, best_map, best_score = -1, {}, 0

    for idx, row in enumerate(rows[:max_scan]):
        # The rows above complete stacked labels ("Unit" over "Cost", "Qty"
        # over "Ord"). A separator/junk row often sits between the two halves
        # of the label, so look up to three rows back; junk words cannot form
        # a vocabulary phrase, so widening the window is safe.
        upper = [w for r in rows[max(0, idx - 3):idx] for w in r["words"]] \
            if idx > 0 else None
        anchors, blanks = _row_header_anchors(row, upper=upper)
        # Only a NAMED column counts towards "this row is the header": an
        # unnamed cell is not evidence of anything.
        score = sum(2 if role in ("quantity", "unit_price", "amount") else 1
                    for role in anchors)
        if score > best_score:
            colmap = dict(anchors)
            for n, (bx0, bx1) in enumerate(blanks, start=1):
                colmap[f"_blank{n}"] = (bx0, bx1)
            best_idx, best_map, best_score = idx, colmap, score

    absorbed = set()
    # Need at least a quantity-ish column to be useful
    if best_score >= 2 and best_map:
        absorbed = _absorb_split_header(rows, best_idx, best_map)
        # A label printed on a NEIGHBOURING line of the header is still a
        # header: PO 514 splits "Discount / amount" and "Item / No." around
        # the row that names the money columns. Those words were treated as
        # DATA, so "No." became the description and - worse - the Discount
        # amount column had no boundary at all and donated its x-range to the
        # Unit price column, which then held two numbers and was rejected.
        band = _header_band(rows, best_idx, best_map)
        for _spans, _idx in band:
            for x0, x1 in _spans:
                # One blank per column: "Item" on the line above and "No." on
                # the line below name the SAME column, so a span that already
                # exists only widens the band it belongs to.
                dup = next((r for r, s in best_map.items()
                            if not r.startswith("_blank")
                            and s[0] - 2.0 <= x0 and x1 <= s[1] + 2.0), "")
                if dup:
                    best_map[dup] = (min(x0, best_map[dup][0]),
                                     max(x1, best_map[dup][1]))
                    continue
                dup = next((r for r, s in best_map.items()
                            if r.startswith("_blank") and x0 < s[1] and s[0] < x1),
                           "")
                if dup:
                    continue
                n = 1
                while f"_blank{n}" in best_map:
                    n += 1
                best_map[f"_blank{n}"] = (x0, x1)
        return best_idx, best_map, absorbed, band
    return -1, {}, absorbed, []


def _header_band(rows: list, hdr_idx: int, colmap: dict) -> list:
    """
    Rows that belong to the same stacked header as `hdr_idx`, as
    [(spans, row_index), ...] EXCLUDING hdr_idx itself.

    A PO that splits a label over several lines prints the header as a
    two- or three-line block. Only the row naming the money columns is chosen
    as "the" header, so the others - "Item / No.", "Discount / amount" on PO
    514 - would otherwise be read as the first data row. The rows either side
    belong to the same header when they are:

      * close to it vertically (stacked lines sit nearer together than the
        gap to the first data row), and
      * carry no data shape - no number that could be a quantity or an
        amount - because a data row always carries at least one.

    Only the words that fall into a column band already known from the header
    are returned, so prose above the table (an address line that happens to
    be close by) never contributes.
    """
    if hdr_idx < 0:
        return []
    band = []
    for direction in (-1, 1):
        step = 0
        while True:
            idx = hdr_idx + direction * (step + 1)
            if idx < 0 or idx >= len(rows):
                break
            row = rows[idx]
            step += 1
            if step > 2:
                break
            if not _same_header_block(rows, hdr_idx, idx):
                break
            if _row_has_data_shape(row):
                break
            spans = _band_spans(row, colmap)
            if spans:
                band.append((spans, idx))
    return band


def _same_header_block(rows: list, hdr_idx: int, idx: int) -> bool:
    """True when rows[idx] sits close enough to the header to be part of it."""
    a, b = rows[hdr_idx], rows[idx]
    gap = abs((b["top"] + b["bottom"]) / 2 - (a["top"] + a["bottom"]) / 2)
    limit = 1.6 * max(_row_height(a), _row_height(b), 1.0)
    return gap <= limit


def _row_height(row: dict) -> float:
    return abs((row.get("bottom") or 0) - (row.get("top") or 0)) or 8.0


def _row_has_data_shape(row: dict) -> bool:
    """
    True when a row carries a number that could be order data.

    A quantity or money value means this is a data row, not a label line.
    Careful: a line number or a part number counted as data would break the
    test, so only shapes that appear inside a TABLE column are considered -
    a bare 1-5 digit integer with up to two decimals, or a grouped amount.
    """
    for w in row.get("words") or []:
        t = str(w["text"]).replace(",", "")
        if _QTY_CELL.match(t or "") and any(ch.isdigit() for ch in t):
            return True
        if _MONEY_CELL.match(t or ""):
            return True
    return False


def _band_spans(row: dict, colmap: dict) -> list:
    """
    The x-spans a neighbouring header line contributes as unnamed columns.

    The rule is deliberately the INVERSE of "the word sits inside a known
    column": an unnamed label lies in a GAP between the named columns, which
    is exactly where a column with no vocabulary name belongs. PO 514 prints
    "Discount / amount" around the money row; "amount" sits at x=446, between
    the Unit price and Ext cost columns and inside no named band - so it
    bounds its own column and stops the Discount figure from sliding into
    the Unit price column.
    """
    named = sorted((s for r, s in colmap.items()
                    if not r.startswith("_blank")), key=lambda s: s[0])
    taken = set(s for r, s in colmap.items())
    spans = []
    for w in row.get("words") or []:
        cx = (w["x0"] + w["x1"]) / 2
        inside = any(hx0 - 2.0 <= cx <= hx1 + 2.0 for hx0, hx1 in named)
        if inside:
            continue          # the chosen header already names this column
        # Never duplicate a span the header row already established, and skip
        # a word that is merely the continuation of a phrase it owns.
        if any(abs(w["x0"] - s[0]) < 1.0 and abs(w["x1"] - s[1]) < 1.0
               for s in taken):
            continue
        spans.append((w["x0"], w["x1"]))
    return spans


def build_column_bounds(colmap: dict, x_min: float, x_max: float,
                        rows: list = None) -> list:
    """
    Turn the header x-ranges into [(role, left, right), ...] spanning the table.

    `colmap` maps role -> (x0, x1). A boundary sits in the GAP between two
    neighbouring header cells, not at the midpoint of their centres: the centre
    of a long label ("Total Qty") drifts away from the number printed under it
    and drags the boundary along, which is how one value ended up counted in
    the neighbouring column (COLUMN_ALIGNMENT P0-1 / P0-3).

    `rows` (the body rows, when known) lets a column be widened to where its
    data actually prints. Headers are usually LEFT-aligned while numbers are
    RIGHT-aligned, so the header's own width is not where the values live:
    PO-157669 prints "QTY" at x=459..479 but every quantity at x=536, and the
    header-only boundary cut the column at 512 - so each quantity landed in
    the price cell and all 32 of them were lost.
    """
    if not colmap:
        return []
    items = sorted(colmap.items(), key=lambda kv: kv[1][0])
    bounds = []
    for i, (role, (hx0, hx1)) in enumerate(items):
        if i == 0:
            left = x_min
        else:
            px0, px1 = items[i - 1][1]
            left = ((px1 + hx0) / 2 if px1 < hx0
                    else (px0 + px1 + hx0 + hx1) / 4)
        if i == len(items) - 1:
            right = x_max
        else:
            nx0, nx1 = items[i + 1][1]
            right = ((hx1 + nx0) / 2 if hx1 < nx0
                     else (hx0 + hx1 + nx0 + nx1) / 4)

            # A right-aligned number column can start past the right edge of
            # its left-aligned header. If this column's data runs beyond the
            # header-derived boundary, move the boundary into the gap between
            # this column's data and the next column's data.
            if rows:
                # Only a NUMERIC column can be right-aligned against its
                # header. A text column ("EA", "UOM", "Description") prints
                # left-aligned right beside its label, so widening it would
                # swallow the neighbouring price - 50-00075696N prints
                # "EA $1,230.400" and an over-eager unit column emptied
                # unit_price.
                numeric_only = role in ("quantity", "unit_price", "amount",
                                        "line_no", "line_total")
                mine = (_data_extent(rows, hx0, hx1, limit=nx0)
                        if numeric_only else None)
                if mine and mine[1] > right:
                    nxt = _data_extent(rows, nx0, nx1)
                    if nxt and nxt[0] > mine[1]:
                        right = (mine[1] + nxt[0]) / 2
                    else:
                        right = max(right, mine[1] + 2.0)
        bounds.append((role, left, right))

    # Widening a column must not create overlaps: enforce left <= right and
    # a monotonically increasing order, so each word lands in exactly one
    # column and the loop in assign_cells() stays deterministic.
    prev_right = None
    fixed = []
    for role, left, right in bounds:
        if prev_right is not None and left < prev_right:
            left = prev_right
        if right <= left:
            right = left + 1.0
        fixed.append((role, left, right))
        prev_right = right
    return fixed


def _data_extent(rows: list, hx0: float, hx1: float, limit: float = None):
    """
    Where this column's values actually print, when that is NOT under the
    header cell itself.

    Headers are left-aligned and numbers are right-aligned, so a narrow header
    ("QTY", 20pt wide) can sit well left of a wide value ("$1,610.49"). Only a
    column of NUMBERS that lines up on a consistent right edge is accepted -
    that alignment is the evidence, and it is what distinguishes a genuinely
    right-aligned number column from a neighbour's overflow.

    Returns (x0, x1) of the aligned value column, or None when the values
    already sit under the header (the common case, and the one every existing
    layout relies on).
    """
    width = max(hx1 - hx0, 1.0)
    reach = (limit - 4.0) if limit is not None else (hx1 + width * 3.0)
    right_edges, spans = [], []
    for r in rows:
        for w in r.get("words") or []:
            txt = (w["text"] or "").replace("$", "").replace(",", "").strip()
            if not txt or not txt.replace(".", "").isdigit():
                continue                    # numbers only - alignment evidence
            if hx0 <= w["x0"] < max(hx1, reach):
                right_edges.append(w["x1"])
                spans.append((w["x0"], w["x1"]))
    if len(spans) < 3:
        return None                         # too few to prove an alignment

    edges = sorted(right_edges)
    median = edges[len(edges) // 2]
    aligned = [s for s, e in zip(spans, right_edges) if abs(e - median) <= 3.0]
    if len(aligned) < 3 or len(aligned) < 0.6 * len(spans):
        return None                         # not a right-aligned column

    x1 = max(e for _s, e in aligned)
    if x1 <= hx1 + 1.0:
        return None                         # values already under the header
    # No upper bound on the reach: a narrow header ("QTY", 20pt) can sit far
    # to the left of a right-aligned value column (PO-157669 prints the values
    # at x=536, 77pt away), and clamping that distance would undo the fix.
    # Text columns are excluded by the caller, so a unit label ("EA") can
    # never be stretched over the price beside it.
    return (min(s for s, _e in aligned), x1)


def assign_cells(row: dict, bounds: list) -> dict:
    """Distribute a row's words into columns. Returns {role: text}.

    A word is filed under the column it STARTS in, not the column its centre
    falls in. Cell text is routinely wider than the header that names it -
    N104789 prints "Item" over six characters but the code beneath it is
    "WW25FG6B34BE", which starts in the Item column (x=191) and runs past the
    start of "Description" (x=208). Measured by centre, that code landed in
    the description column and material_code came back empty, losing the line
    and $833.00 of the order. The starting edge is what the column layout is
    actually keyed on.

    The centre is kept as a fallback for a word that starts before the first
    column (a line number printed in the margin).
    """
    cells = {role: [] for role, _, _ in bounds}
    for w in row["words"]:
        x0 = w["x0"]
        placed = False
        for role, left, right in bounds:
            if left <= x0 < right:
                cells[role].append(w)
                placed = True
                break
        if placed:
            continue
        cx = (w["x0"] + w["x1"]) / 2
        for role, left, right in bounds:
            if left <= cx < right:
                cells[role].append(w)
                break
    return {r: _join_cell_words(v) for r, v in cells.items()}


def _join_cell_words(words: list, touch: float = 0.6) -> str:
    """
    Join a cell's words, keeping words that TOUCH each other as one token.

    pdfplumber splits a number wherever the PDF happens to end a text run, and
    a zero gap is not a space: Marcone MNH090926-HZL279 prints "$57.11" as two
    words, "5" (x 281.7-284.4) and "7.11" (284.4-294.0) - the second starts
    exactly where the first ends. Joined with a space they read as two figures
    and the line was published as unit price 5 instead of 57.11; only the
    amount (114.22 = 2 x 57.11) stayed right.

    The test uses the positions, so it is exact rather than heuristic: a real
    column break always leaves a visible gap, and this only fires when there is
    none. Two DIGITS are required on both sides, so "$ 5" (a currency mark and
    its figure, 19pt apart) is untouched.
    """
    out = ""
    prev = None
    for w in words:
        text = str(w.get("text") or "")
        if not out:
            out = text
        elif (prev is not None and text[:1].isdigit() and out[-1:].isdigit()
              and abs(float(w.get("x0") or 0.0)
                      - float(prev.get("x1") or 0.0)) <= touch):
            out += text
        else:
            out += " " + text
        prev = w
    return out.strip()


# ──────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────
def parse_line_items(words: list, zone_x0: float = None,
                     zone_x1: float = None, max_scan: int = 8) -> dict:
    """
    Parse a line-item table from words inside a single zone.

    Returns:
        {
          "header_found": bool,
          "columns": {role: (x0, x1)},
          "rows": [ {"y", "text", "cells": {role: text}}, ... ]
        }

    `columns` carries only the roles the vocabulary named. Unnamed header cells
    ('_blank1' ...) take part in the bounds but are left out of the returned
    map, and out of the cells, so a column nobody asked for cannot be mistaken
    for data.
    """
    rows = group_words_into_rows(words)
    if not rows:
        return {"header_found": False, "columns": {}, "rows": []}

    x_min = zone_x0 if zone_x0 is not None else min(w["x0"] for w in words)
    x_max = zone_x1 if zone_x1 is not None else max(w["x1"] for w in words)

    hdr_idx, colmap, absorbed, band = find_header_row(rows, max_scan=max_scan)
    named = {r: s for r, s in colmap.items() if not r.startswith("_blank")}

    body = rows[hdr_idx + 1:] if hdr_idx >= 0 else rows
    # Bounds are built AFTER the body is known so a right-aligned number column
    # can be widened to where its values actually print (see build_column_bounds).
    bounds = build_column_bounds(colmap, x_min, x_max, rows=body) if colmap else []
    if band:
        # Neighbouring lines of a stacked header are header text, not data
        # (PO 514: "No." under the header became the description, and the
        # Discount amount column it named had no boundary).
        skip = {idx for _spans, idx in band}
        body = [r for i, r in enumerate(body, start=hdr_idx + 1)
                if i not in skip]

    out_rows = []
    for r in body:
        words = r["words"]
        if absorbed:
            # A word completing a header phrase printed on two lines is header
            # text, not data - it must not be joined into a cell.
            words = [w for w in words if id(w) not in absorbed]
        if not words:
            continue
        cells = assign_cells({"words": words}, bounds) if bounds else {}
        out_rows.append({
            "y":     (r["top"] + r["bottom"]) / 2,
            "top":   r["top"],
            "text":  " ".join(w["text"] for w in words).strip(),
            "cells": cells,
        })

    return {
        "header_found": hdr_idx >= 0,
        "columns": named,
        "rows": out_rows,
    }


# ──────────────────────────────────────────────
# Item block merging
# ──────────────────────────────────────────────
def split_blocks_by_quantity(parsed_rows: list, has_code_fn=None) -> list:
    """
    Split rows into item blocks using the Quantity column as the anchor.

    In a purchase-order table each item has exactly one quantity, while its
    code and description may wrap across several rows:

        4200-0430  Samsung - Dishwasher 24" - Stainless -
                   (DW80CG4051SRAA)
                   Samsung - Dishwasher 24" ...            1   EA   <- anchor
        4200-1030  Samsung - Microwave ...

    Everything up to and including a row carrying a quantity forms one block,
    so the code is paired with its own quantity regardless of where it wraps.
    This is far more stable than looking for the code first, because a code
    split across lines would otherwise fail to open a new block.

    `has_code_fn` (optional) also opens a new block on a row that carries a
    material code. Some layouts print the code BELOW the description block,
    after the quantity/price row, e.g. ERP One 01001129:

        1 EA 7.4 cu. ft. Smart Electric Dryer  648.00 EA  648.00   <- item 1
        with Steam Sanitize+
        DVE55CG7500EA3                                            <- item 1
        1 EA 7.4 cu. ft. Smart Gas Dryer       713.00 EA  713.00   <- item 2

    Anchoring on the quantity alone put the code line of item 1 at the HEAD of
    item 2's block, so every item was priced with its neighbour's figures and
    the order came out $648.00 over its printed total. Opening a block on a
    code row as well keeps each code with the numbers printed beside it.
    A code row closes the running block only when that block already has its
    own quantity, so the code-before-numbers order above still works.

    Requires the quantity column to have been detected.
    """
    # Pass 1: cut the rows into runs at every quantity row. A run is either
    # [carried-over wrapper rows ... quantity row] (the usual layout, code and
    # description printed ABOVE the numbers) or [quantity row] alone.
    runs, buf = [], []
    for row in parsed_rows:
        buf.append(row)
        if is_quantity_anchor(row):
            runs.append(buf)
            buf = []
    if buf:
        runs.append(buf)

    if has_code_fn is None:
        blocks = [{"rows": r} for r in runs]
    else:
        # Pass 2: a run that carries no code takes the code from the run that
        # follows it. Some layouts print the code on the line AFTER its own
        # quantity/price row (ERP One 01001129):
        #
        #   1 EA 7.4 cu. ft. Smart Electric Dryer  648.00 EA  648.00   <- run 0
        #   with Steam Sanitize+                                      <- run 0
        #   DVE55CG7500EA3                                            <- item 1!
        #   1 EA 7.4 cu. ft. Smart Gas Dryer       713.00 EA  713.00   <- run 1
        #
        # Cutting on the quantity alone left DVE55CG7500EA3 at the head of
        # run 1, so every item was priced with its neighbour's figures and
        # the order came out exactly one price over its printed total. Such a
        # leading code is MOVED to the headless run before it, which is the
        # only run whose numbers it can belong to.
        attached = [None] * len(runs)

        def codes_in(rows):
            return [i for i, r in enumerate(rows) if has_code_fn(r["text"])]

        for idx, run in enumerate(runs):
            if codes_in(run):
                attached[idx] = run
                continue
            nxt = idx + 1
            if nxt >= len(runs):
                attached[idx] = run
                continue
            leads = codes_in(runs[nxt])
            # Only the code rows printed before the next quantity row may move;
            # the next run's own numbers stay with the next item.
            movable = []
            for j in leads:
                if is_quantity_anchor(runs[nxt][j]):
                    break
                movable.append(j)
            if movable:
                taken = [runs[nxt][j] for j in movable]
                attached[idx] = run + taken
                runs[nxt] = [r for j, r in enumerate(runs[nxt])
                             if j not in movable]
            else:
                attached[idx] = run

        blocks = [{"rows": r} for r in attached if r]

    for b in blocks:
        b["text"] = " ".join(r["text"] for r in b["rows"])
    return blocks


# A genuine quantity cell holds only a number, optionally with a unit.
# Long description text that spills into the Qty column must not be mistaken
# for an anchor, so anything else is rejected.
_QTY_CELL = re.compile(
    r"^\s*\d{1,5}(?:,\d{3})*(?:\.\d+)?\s*"
    r"(?:EA|EACH|PCS?|PC|UNITS?|SET|BOX|CS|CTN|LOT)?\s*$",
    re.IGNORECASE
)

# A currency mark that the column boundary pinned to the QTY cell. Marcone
# MNH090926-HZL279 prints "1 $ 407.95": the amount column's own "$" sits a
# point left of its header, so it lands in the quantity band and the cell reads
# "1 $". A "$" is never part of a count, so it is dropped rather than being
# allowed to make a perfectly good "1" unreadable - which is what happened:
# the row stopped being a quantity anchor, no block boundary was cut, and the
# anchor fallback then read the footer's piece count ("Total 48") as every
# line's quantity.
_CELL_CURRENCY = re.compile(r"[$£€]\s*")


def _qty_cell_text(cell: str) -> str:
    """A quantity cell with stray currency marks removed ('1 $' -> '1')."""
    return _CELL_CURRENCY.sub(" ", cell or "").strip()


def is_quantity_anchor(row: dict) -> bool:
    """
    True when the row's quantity cell holds a plausible order quantity.
    Large values (MFG numbers, UPCs) and zero-padded line numbers are
    rejected so they cannot anchor a block or become the quantity.
    """
    cell = _qty_cell_text((row.get("cells") or {}).get("quantity", ""))
    if not cell or not _QTY_CELL.match(cell):
        return False
    digits = re.sub(r"\D", "", cell)
    if not digits:
        return False
    if len(digits) >= 4 and digits[0] == "0":
        return False
    return 0 < int(digits) <= 9999


def _distinct_models(items: list) -> list:
    """
    Collapse the codes of one row to one entry per MODEL, keeping the most
    specific spelling of each.

    A purchase order can print the same appliance in two notations on one
    row - its own item code and the vendor reference (PO 189743 prints
    "NSE6DG8502SR" and "NSE6DG8502SRAA"). When the master carries both
    spellings they both look like confirmed codes, and treating them as two
    items blanked the line's price and amount entirely.

    Grouping is on the variant-stripped stem, so only genuine market
    variants of one another collapse: "NSE6DG8502SR" and "NSE6DG8502SRAA"
    share the stem "NSE6DG8502SR", while two different models never do.
    Within a group the spelling printed with its market suffix wins, because
    that is the form ERP is keyed on and it is the one the document quotes
    as its reference.
    """
    groups = {}
    order = []
    for it in items:
        stem = normalize(strip_variant(it.get("code", "")))
        if not stem:
            continue
        if stem not in groups:
            groups[stem] = []
            order.append(stem)
        groups[stem].append(it)
    out = []
    for stem in order:
        g = groups[stem]
        if len(g) == 1:
            out.append(g[0])
            continue
        # Prefer the most specific spelling, then the highest confidence.
        best = max(g, key=lambda it: (len(str(it.get("code", ""))),
                                      _alias_conf(str(it.get("code", "")), 1)))
        out.append(best)
    return out


def _qty_from_cell(cell: str) -> str:
    """
    The value of a cell that sat in the Qty column, or "".

    The column identity is the proof here, not the shape: parse_quantity
    reads prose, and its guards ("a number attached to a decimal is not a
    count") exist to keep "6.0 cf" out of the quantity column. Inside a
    column the header already named, those guards cost more than they
    protect: Samsung's ERP prints the count through a decimal column
    ("85.00"), and rejecting it sent the engine to the description text,
    where the "300" of "Capacity; 300" became the order quantity.
    """
    t = _qty_cell_text(cell).replace(",", "")
    if not _QTY_CELL.fullmatch(t):
        return ""
    # A decimal whose fraction is all zeros is an integer ("85.00" -> 85).
    # A real fraction ("1.5") is a count of a split unit and stays as
    # printed rather than being silently truncated.
    if "." in t:
        head, frac = t.split(".", 1)
        if frac and set(frac) != {"0"}:
            return ""
        t = head
    return t if _valid_qty(t) and int(t) >= 1 else ""


def _split_price_amount(price: str, amount: str, price_cell: str) -> tuple:
    """
    (unit price, amount) from a unit-price cell that may hold BOTH numbers.

    Some forms print their values ~15pt LEFT of their headers, so the column
    boundary falls between the price and the extended cost and both land in
    the unit-price cell. PO-189743 (Electronic Express) reads

        {'unit_price': 'RA 500.00 120000.00', 'amount': ''}

    and the amount was lost. The two columns have a fixed printed order, so
    when the amount column came back empty and the price cell holds two
    amounts, the first is the price and the second the amount. Nothing is
    derived: the second value only MOVES from one field to the other, and only
    when the price already found is the first of the pair.
    """
    if amount or not price_cell:
        return price, amount
    vals = money_values(price_cell)
    if len(vals) < 2:
        return price, amount
    if _clean_money(vals[-2]) != price:
        return price, amount
    return vals[-2], _clean_money(vals[-1])


def _quantity_from_anchor_row(block: dict) -> tuple:
    """
    (quantity, unit) for an item whose quantity COLUMN came back empty.

    Read from the row that carries the item's own numbers and nowhere else.
    Every other row of a block is description or spec text, and a number
    lifted out of it ("HZL279", "60HZ", "4 EA" in a spec list) is not a count.
    Returns ("", "") when no row prints an unmistakable count.
    """
    rows = block.get("rows") or []
    anchors = [r for r in rows if is_quantity_anchor(r)]
    # A row that STARTED with the count ("1 EA 10/12/2026 RF22A4111SR
    # 818.30 EA 818.30") is the item's own numbers even when the header's
    # qty column could not see it - the count and its unit word are the first
    # thing printed. Checked before the anchor row, because on a layout like
    # Google Express's the anchor cell holds something else entirely.
    for r in rows:
        q, u = _leading_count(r.get("text") or "")
        if q:
            return q, u
    # Otherwise only the quantity COLUMN counts. A row that merely looks
    # numeric elsewhere is not evidence.
    if anchors:
        q, u = parse_quantity(anchors[-1].get("text") or "")
        return (q, u) if q else ("", "")
    # No anchor row at all: the block was cut by something other than a
    # quantity (a code row, or the whole table when no cell was recognised as
    # a count). Read the LAST item-shaped row, never a footer: Marcone
    # MNH090926-HZL279 printed "Total 48" under the table, and taking the
    # block's last line made 48 the quantity of ALL 31 lines.
    for r in reversed(rows):
        text = r.get("text") or ""
        if is_footer_line(text):
            continue
        if not (money_values(text) or _line_looks_like_item(text)):
            continue
        q, u = parse_quantity(text)
        if q:
            return q, u
    return "", ""


def _leading_count(text: str) -> tuple:
    """
    (quantity, unit) when a printed line OPENS with a count: '3 EA', '55 ea',
    '24 PCS'. A description never does; an order row almost always does.

    Deliberately narrow. A bare leading integer is NOT accepted - that is how
    '2026' from a remark or '48' from a package size would become an order
    quantity. The unit word has to be there.
    """
    m = re.match(r"^\s*(\d{1,4})\s*(EA|EACH|PCS?|PC|UNITS?|SET|BOX|CS|CTN)\b",
                 text or "", re.IGNORECASE)
    if not m:
        return "", ""
    q = m.group(1)
    return (q, m.group(2).upper()) if int(q) >= 1 else ("", "")


def _codes_quoted_in_descriptions(row_hits: list, found: list) -> list:
    """
    Candidates that are only ever printed on a description WRAP line, inside a
    block whose own numbers row already names the item.

    The evidence, and why it is positional rather than a guess:

      * `row_hits` is [(row, [candidate, ...])] for one block, so we know on
        WHICH printed line each code was seen;
      * a block's own row is the one that carries the QUANTITY
        (`is_quantity_anchor`). If that row prints a code, that code is the
        item.
      * A code that appears only on the other rows - and those rows print no
        money of their own - is part of the sentence above/below: CMH prints
        "MICROWAVE 30\" TRIM KIT FOR" over "MS19M8000AS SS", where the second
        half names the model the trim kit FITS, not a second thing being
        bought.

    Returns [] when the block's numbers row carries no code at all: that is
    the "code printed ABOVE its numbers" layout (ERP One 01001129, 4200-0430
    wrappers), where the wrap-line code IS the item and must be kept.

    A wrap line that DOES print money keeps its code too - two real items whose
    numbers were merged into one block look exactly like that, and dropping one
    of them would lose an order line.
    """
    rows = [r for r, _hits in row_hits]
    anchor_keys = set()
    for r, hits in row_hits:
        if is_quantity_anchor(r):
            anchor_keys.update(normalize(h["code"]) for h in hits)
    if not anchor_keys:
        return []                      # code-above-numbers layout: keep all

    quoted_keys = set()
    for r, hits in row_hits:
        if is_quantity_anchor(r) or not hits:
            continue
        if money_values(r["text"]):
            continue                   # a wrap line with money is another item
        for h in hits:
            key = normalize(h["code"])
            if key not in anchor_keys:
                quoted_keys.add(key)
    if not quoted_keys:
        return []

    out, seen = [], set()
    for c in found:
        key = normalize(c["code"])
        if key in quoted_keys and key not in seen:
            seen.add(key)
            out.append(c)
    return out


def merge_item_blocks(parsed_rows: list, has_code_fn,
                      max_gap_rows: int = 4) -> list:
    """
    A purchase-order item usually spans several printed rows:

        4200-0430  Samsung - Dishwasher 24" - Stainless -
                   (DW80CG4051SRAA)
                   Samsung - Dishwasher 24" ...              1   EA

    The code and the quantity can therefore sit on different rows. This groups
    consecutive rows into blocks so that a code found anywhere in the block is
    paired with the quantity found anywhere in the same block.

    has_code_fn(text) -> bool decides whether a row starts/contains an item.
    Returns: [{"rows": [...], "text": str}, ...]
    """
    blocks, current = [], None

    for row in parsed_rows:
        starts_item = has_code_fn(row["text"])

        if starts_item:
            if current:
                blocks.append(current)
            current = {"rows": [row]}
        elif current is not None and len(current["rows"]) < max_gap_rows:
            current["rows"].append(row)
        # rows before the first code are ignored

    if current:
        blocks.append(current)

    for b in blocks:
        b["text"] = " ".join(r["text"] for r in b["rows"])
    return blocks


# The shape of a printed amount: optional thousands separators, optional
# decimals. Defined ONCE and shared, because two copies of this drifted apart
# and the stale one truncated prices silently.
#
# `\d{1,3}` was the original - it rejects every amount of four or more digits
# printed WITHOUT a separator ('1198.00', '1234.00', '1060.0000') even though
# the money scanner (_MONEY, below) reads exactly those forms. `_MONEY_CELL`
# was corrected to `\d+` (COLUMN_ALIGNMENT P0-4), but `_extract_price` - the
# fallback path used by extract_from_text - kept its own `\d{1,3}` copy. The
# result was worse than a rejection: on 'Unit Price: 1198.00' the pattern
# matched the leading '119' and the function returned "119" as the unit price,
# so a wrong price reached the ERP file instead of no price at all.
_AMOUNT = r"\d+(?:,\d{3})*(?:\.\d+)?"

# A printed amount standing alone in a table cell.
_MONEY_CELL = re.compile(r"^\s*[-+]?\s*\$?\s*" + _AMOUNT + r"\s*$")

# Roles whose validator is a closed vocabulary rather than a shape. A wrong
# unit ('PRICE' read as the unit of measure) is worse than a missing one, so
# these still reject a value that fails validation.
_NO_FALLBACK_ROLES = {"unit"}

# Description text that overflows into a numeric column would otherwise be
# picked up as the value, so numeric roles are validated before being accepted.
_CELL_VALIDATORS = {
    "quantity":   lambda v: is_quantity_anchor({"cells": {"quantity": v}}),
    "unit_price": lambda v: bool(_MONEY_CELL.match(v)),
    "amount":     lambda v: bool(_MONEY_CELL.match(v)),
    "unit":       lambda v: bool(re.fullmatch(
        r"(?i)\s*(EA|EACH|PCS?|PC|UNITS?|SET|BOX|CS|CTN|LOT)\s*", v)),
}


def cell_from_block(block: dict, role: str) -> str:
    """
    Best value for a column role within a block.

    A numeric role only accepts cells that look numeric, so overflow text from
    a neighbouring column is skipped rather than returned. When nothing passes
    validation the first value that at least CONTAINS a digit is returned and
    the block is marked low-confidence, instead of the value disappearing with
    no trace - every caller re-sanitises these fields anyway (_clean_money /
    parse_quantity), so a mangled figure can still be recovered, while pure
    description text is still refused.
    """
    validator = _CELL_VALIDATORS.get(role)
    fallback = ""

    for r in block["rows"]:
        v = (r.get("cells") or {}).get(role, "").strip()
        if not v:
            continue
        if validator is None:
            return v
        if validator(v):
            return v
        if not fallback:
            fallback = v

    if not fallback or validator is None:
        return fallback
    if role in _NO_FALLBACK_ROLES or not any(ch.isdigit() for ch in fallback):
        return ""
    # Record it rather than dropping it silently (COLUMN_ALIGNMENT P0-5). The
    # list (not a set) keeps the block JSON-serialisable.
    lc = block.setdefault("low_confidence", [])
    if role not in lc:
        lc.append(role)
    return fallback


# ==========================================================================
#  SECTION: CODE MATCHER - backbone reference index and candidate detection
#  (formerly code_matcher.py)
# ==========================================================================

"""
code_matcher.py - Material code recognition against a backbone reference list

Design goals
------------
1. ACCURACY FIRST. A wrong code sent to a customer is worse than a missing one.
   When a backbone list is loaded, only codes confirmed against that list are
   reported as results. Everything else is routed to a review list instead of
   being silently mixed into the output.

2. SCALE. Subsidiaries run tens of thousands of material codes. Scanning the
   list with one regex per code would be O(codes x lines) and unusable at that
   size. Instead the list is indexed into hash maps and each line is tokenised
   once, giving O(tokens) lookups per line regardless of list size.

Matching order
--------------
  1. Exact          DW80CG4051SRAA == DW80CG4051SRAA
  2. Variant        DW80CG4051SR   ~= DW80CG4051SRAA   (market suffix)
  3. Multi-token    codes containing spaces or split across words
  4. Parenthesized  "... - (DW80CG4051SRAA)"          <- review only
  5. Regex pattern  from config.json                   <- review only
"""




# ──────────────────────────────────────────────
# Normalization
# ──────────────────────────────────────────────
# Separators removed before comparison. PDFs carry several dash variants that
# look identical on screen: soft hyphen (U+00AD), non-breaking hyphen, figure
# dash, en/em dash, minus sign. "583­DVE45T6000W" must normalise to the
# same value as "583-DVE45T6000W", otherwise the code never matches.
_NORM_STRIP = re.compile(
    "[\\s\\-_./­‐‑‒–—―−⁃－]")

# The same characters, but with ONLY the invisible ones removed: '-', '/' and
# '.' are part of how a code is written ('L-INST/E2-BEV'), so a comparison
# about identity keeps them. See _print_form().
_PRINT_STRIP = re.compile("[\\s­‐‑‒–—―−⁃－]")

# Market / region suffixes appended to Samsung model codes
VARIANT_SUFFIX = re.compile(r"(XAA|XAC|AA|US|A)$", re.IGNORECASE)

# The same set, used with fullmatch() to validate a difference between the
# document's spelling and the list's spelling. Anything not in this set is
# treated as corruption rather than a regional variant.
#
# A BARE DIGIT IS NOT A SUFFIX. Allowing it let a quantity printed next to a
# code ("DVE45T6000W 1 EA") fuse into 'DVE45T6000W1' and still match, which
# published a code that does not exist.
MARKET_SUFFIX = re.compile(r"(?i)(XAA|XAC|AA|US|A[0-9]|A)")

# Token pattern used to slice a line into code candidates.
#
# Unicode dashes belong INSIDE a token so that "583­DVE45T6000W" (soft hyphen)
# is captured whole. But a token must not swallow the money that follows it:
# allowing '.' freely turned "(DW80CG4051SRAA) 1 EA $ 411.00" into one giant
# token. So '.' and '/' are permitted only when followed by a letter or digit
# AND not part of a decimal amount, and a token may never end on a separator.
_DASHES = "\\-_­‐‑‒–—―−⁃－"
_TOKEN = re.compile(
    "[A-Za-z0-9]"                       # starts alphanumeric
    "(?:"
    f"[{_DASHES}]"                       # a dash, or
    "|[./](?![0-9]{2}\\b)"               # '.' or '/' not starting a decimal
    "|[A-Za-z0-9]"                       # or an alphanumeric
    "){2,39}"
    "(?<![" + _DASHES + "./])"           # must not end on a separator
)


def normalize(code: str) -> str:
    """Uppercase and remove separators for tolerant comparison."""
    if not code:
        return ""
    return _NORM_STRIP.sub("", str(code)).upper()


def _print_form(code: str) -> str:
    """
    The spelling a document would print, with separators KEPT:
    'DVE45T6000W/A3' -> 'DVE45T6000W/A3', 'L-INST/E2-BEV' -> 'L-INST/E2-BEV'.

    `normalize()` throws the separators away and cannot tell 'L-INST/E2' from
    'L-INST/E3' once they differ by one character, so any comparison that is
    about WHICH CODE this is rather than how it is spelled must use this form.
    """
    if not code:
        return ""
    return _PRINT_STRIP.sub("", str(code)).upper()


# Characters OCR engines routinely swap in alphanumeric codes
_CONFUSE_MAP = str.maketrans({"S": "5", "O": "0", "I": "1", "B": "8", "Z": "2"})


def _confuse(normalized: str) -> str:
    """Fold OCR-ambiguous characters to one canonical form."""
    return (normalized or "").translate(_CONFUSE_MAP)


def strip_variant(code: str) -> str:
    """Remove a trailing market suffix (DW80CG4051SRAA -> DW80CG4051SR)."""
    n = normalize(code)
    stripped = VARIANT_SUFFIX.sub("", n)
    return stripped if len(stripped) >= 5 else n


# ──────────────────────────────────────────────
# Code-list cells: what counts as a material code
# ──────────────────────────────────────────────
# Used when a code list is read (Master Data > Material Codes upload), so
# the list and the matcher agree by construction.
# Moved here from the retired backbone_import.py.

# A plausible material code: alphanumeric, no spaces
_CELL_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-\_\./]{2,29}$")

# Numbered section labels such as "07.OVEN" or "01_REF" - category headings in
# product-organised lists, never material codes.
_SECTION_LABEL = re.compile(r"^\d{1,3}[\.\-_]\s*[A-Za-z가-힣]+$")

# Words that precede a code in a list cell, e.g. "Model E3-DW". They are
# labels, not part of the code, and are stripped before validation.
_CELL_PREFIX = re.compile(
    r"(?i)^(model|mdl|item|part|code|sku|type|no\.?|#)\s*[:#\-]?\s+")

# Service / labor entries are legitimate codes even without a digit:
# "Labor REF", "E5-RANE", "INST-DW".
_SERVICE_CODE = re.compile(
    r"(?i)^(labor|inst|install|svc|service|delivery|haul|setup)\b"
    r"|^[A-Z]{1,6}[\-][A-Z0-9\-]{1,12}$")

# Category names and notes, never codes. Lets digit-free codes (HAFQIN water
# filters, accessory part numbers) through without accepting headings.
_NOT_A_CODE_WORD = re.compile(
    r"(?i)^(refrigerator|freezer|washer|dryer|laundry|dishwasher|range|oven|"
    r"cooktop|microwave|cooking|hood|vacuum|aircon|ac|tv|monitor|"
    r"accessory|accessories|service|etc|total|subtotal|others?|misc|"
    r"product|category|type|model|item|code|note|remark|na|n/a)$")


def is_code_cell(value) -> bool:
    """True when a single code-list cell value is shaped like a code."""
    v = str(value or "").strip()
    if not (3 <= len(v) <= 30) or not _CELL_SHAPE.match(v):
        return False
    if _SECTION_LABEL.match(v):
        return False
    if re.search(r"\d", v):
        return True
    if _SERVICE_CODE.match(v):
        return True
    return v.isupper() and 4 <= len(v) <= 20 and not _NOT_A_CODE_WORD.match(v)


def clean_code_cell(value) -> str:
    """Normalise a code-list cell into a code, or "" when it is not one.

        'Model E3-DW'      -> 'E3-DW'       (label prefix removed)
        'Labor REF'        -> 'LABOR-REF'   (service entry, words joined)
        'HAFQIN'           -> 'HAFQIN'      (digit-free part code)
        ' RF18A5101SR/AA ' -> 'RF18A5101SR/AA'
        'Refrigerator'     -> ''            (heading)
    """
    v = str(value or "").strip()
    if not v:
        return ""
    if re.fullmatch(r"\d+\.0", v):              # Excel float artefact
        v = v[:-2]
    v = _CELL_PREFIX.sub("", v).strip()
    if not v:
        return ""
    if is_code_cell(v):
        return v
    if " " in v and _SERVICE_CODE.match(v):
        joined = "-".join(v.split()).upper()
        if 3 <= len(joined) <= 30 and re.fullmatch(
                r"[A-Z0-9][A-Z0-9\-_./]+", joined):
            return joined
    if " " not in v and _SERVICE_CODE.match(v) and 3 <= len(v) <= 30:
        return v
    return ""


# ──────────────────────────────────────────────
# Backbone index
# ──────────────────────────────────────────────
class BackboneIndex:
    """
    Hash-based lookup over the reference list.

    Build cost is linear in list size and happens once per run. Lookup is O(1)
    per token, so a list of 100,000 codes costs the same per line as a list of
    100. No per-code regex is compiled.
    """

    # Codes shorter than this are ignored to avoid matching stray words
    MIN_CODE_LEN = 3

    # ...and shorter than THIS they are not allowed to grow into a listed code
    # by the prefix rule alone ('26' -> '26A' is a date, not a model).
    MIN_SHORT_PREFIX_LEN = 5

    def __init__(self, ref_codes: dict):
        self.raw = ref_codes or {}
        self.by_norm = {}                 # normalized      -> original
        self.by_stem = {}                 # variant-stripped -> original
        self.by_base = {}                 # part before "/" -> original
        self.by_confuse = {}              # OCR-confusion-folded -> [originals]
        self.by_prefix = defaultdict(list)  # stem -> [originals] for suffix growth
        self.multi_token = []             # codes that contain separators/spaces
        self.max_token_span = 1           # words a multi-token code can span

        for code in self.raw:
            n = normalize(code)
            if len(n) < self.MIN_CODE_LEN:
                continue

            self.by_norm.setdefault(n, code)
            stem = strip_variant(code)
            self._put(self.by_stem, stem, code)
            self.by_prefix[stem].append(code)

            # Samsung codes are stored as BASE/MARKET (DVE45T6000W/A3) while
            # purchase orders usually print only the base (DVE45T6000W).
            # The "/" is an explicit delimiter, so indexing the base form is
            # precise - unlike blind suffix stripping, it cannot misfire.
            s = str(code)
            base = ""
            if "/" in s:
                base = normalize(s.split("/", 1)[0])
                if len(base) >= 5:
                    self._put(self.by_base, base, code)

            # OCR-confusion form: scanned POs misread 5<->S, 0<->O, 1<->I,
            # 8<->B, 2<->Z (WF45B6300AP printed, WF4SB6300AP recognised).
            # Both sides are folded to one canonical form so either spelling
            # finds the other. Used as a LAST-resort lookup only. Every code
            # that folds to a key is kept: when TWO listed codes share one
            # folded key the lookup is ambiguous and returns nothing rather
            # than whichever happened to be registered first.
            self.by_confuse.setdefault(_confuse(n), []).append(code)
            if base:
                self.by_confuse.setdefault(_confuse(base), []).append(code)

            # Multi-word codes. Two shapes reach here:
            #   - stored with a space:  "E5 RANE"
            #   - stored hyphen-joined by the importer: "LABOR-REF", which the
            #     PDF prints as two words ("Labor REF")
            # Both must be findable across a word boundary, so any code with a
            # space or an internal hyphen is registered as multi-token.
            s = str(code)
            if re.search(r"\s", s):
                span = len(s.split())
                self.multi_token.append((n, code, span))
                self.max_token_span = max(self.max_token_span, span)
            elif "-" in s:
                parts = [p for p in s.split("-") if p]
                if len(parts) >= 2 and all(len(p) >= 2 for p in parts):
                    self.multi_token.append((n, code, len(parts)))
                    self.max_token_span = max(self.max_token_span, len(parts))

        logger.info(f"Backbone index built: {len(self.by_norm)} codes")

    @staticmethod
    def _put(index, key, code):
        """First code wins a key - except that a /AA variant replaces any
        other market variant (.../A3, .../A0). Customers who order on manual
        POs only ever take the /AA SKU, so a short code printed on a PO
        ("DVE45T6000W") must resolve to it, not to whichever variant happened
        to come first in the master list."""
        cur = index.get(key)
        if cur is None or (not str(cur).upper().endswith("/AA")
                           and str(code).upper().endswith("/AA")):
            index[key] = code

    def __len__(self):
        return len(self.raw)

    @property
    def enabled(self) -> bool:
        return bool(self.raw)

    def info(self, code: str) -> dict:
        return self.raw.get(code, {})

    # ── single-token lookup ───────────────────
    def lookup(self, candidate: str) -> tuple:
        """
        Match one token against the backbone.
        Returns: (matched_code, kind) or ("", "")
        """
        if not candidate or not self.raw:
            return "", ""

        n = normalize(candidate)
        if len(n) < self.MIN_CODE_LEN:
            return "", ""

        # 1) exact
        hit = self.by_norm.get(n)
        if hit:
            return hit, "exact"

        # 2) the token carries a market suffix the list does not
        stem = strip_variant(candidate)
        hit = self.by_stem.get(stem) or self.by_norm.get(stem)
        if hit:
            return hit, "variant"

        # 3) the PO printed the BASE model while the list stores BASE/MARKET
        #    (DVE45T6000W  ->  DVE45T6000W/A3)
        hit = self.by_base.get(n)
        if hit:
            return hit, "variant"

        # 4) the token itself carries a market part - compare its base too
        #    (DVE45T6000W/A0 printed, list stores DVE45T6000W or DVE45T6000W/A3)
        if "/" in candidate:
            base = normalize(str(candidate).split("/", 1)[0])
            if len(base) >= self.MIN_CODE_LEN:
                hit = (self.by_norm.get(base) or self.by_base.get(base)
                       or self.by_stem.get(base))
                if hit:
                    return hit, "variant"

        # 5) the token extends a listed code by a MARKET suffix.
        #    Only recognised suffixes are cut: trimming arbitrary characters
        #    matched corrupted tokens such as 'DW80CG4051SRAAB' (the trailing
        #    'B' came from the next line) to a real code.
        for cut in range(1, 5):
            if len(n) - cut < self.MIN_CODE_LEN:
                break
            if not MARKET_SUFFIX.fullmatch(n[-cut:]):
                continue
            hit = self.by_norm.get(n[:-cut])
            if hit:
                return hit, "variant"

        cands = self.by_prefix.get(n)
        if cands:
            # Same stem, several market variants (.../AA, .../A3, ...): the
            # customers who place manual (non-EDI) POs only ever take the /AA
            # SKU, so when it's among the candidates it is the safe pick
            # rather than whichever variant happens to sit first in the
            # master list.
            #
            # A BARE DIGIT IS NOT A MARKET VARIANT. The printed token has
            # already stopped short of the listed code here, and a token that
            # is only a few characters long plus a digit is a dated reference,
            # not a model: PO 25407327's line only read
            # "PO  ID#  25407327 ... Apr  18th,  26" and '26' alone looked up
            # to the listed '26A' / '2612' appliances. Such a token is not a
            # code at all.
            if len(n) < self.MIN_SHORT_PREFIX_LEN and any(ch.isdigit() for ch in n):
                return "", ""
            if len(cands) > 1:
                aa = next((c for c in cands
                           if str(c).upper().endswith("/AA")), None)
                if aa:
                    return aa, "variant"
            return cands[0], "variant"

        # 5b) The document prefixes the code with an internal category number:
        #     "583-DVE45T6000W", "584-L-INST-E2". Strip a leading numeric
        #     segment followed by a separator and retry. Safe because the
        #     remainder must still match the backbone exactly.
        mpx = re.match(r"^\d{1,4}[" + _DASHES + r"./]\s*(.+)$", str(candidate))
        if mpx:
            tail = mpx.group(1)
            nt = normalize(tail)
            if len(nt) >= self.MIN_CODE_LEN:
                hit = (self.by_norm.get(nt) or self.by_base.get(nt)
                       or self.by_stem.get(strip_variant(tail)))
                if hit:
                    return hit, "variant"

        # 6) OCR glued the code to the next word: WF45B6300APPLATINUM.
        #    Peel a purely-alphabetic tail (a description word) off the token
        #    and retry - the remainder must be letters only and the surviving
        #    prefix long enough that a wrong-model hit is impossible.
        #    "glued" is returned so callers can trim the printed form: the
        #    description word must not end up inside the Material Code column.
        if len(n) >= 14:
            for cut in range(4, len(n) - 9):
                tail = n[-cut:]
                if not tail.isalpha():
                    continue
                head = n[:-cut]
                hit = (self.by_norm.get(head) or self.by_base.get(head)
                       or self.by_stem.get(head))
                if hit:
                    return hit, "glued"

        # 7) OCR character confusion (5<->S, 0<->O, 1<->I, 8<->B, 2<->Z):
        #    WF4SB6300AP recognised for WF45B6300AP. Last resort, but still
        #    backbone-confirmed - it can only ever return a listed code, and
        #    only when exactly ONE listed code folds to this key. Two codes
        #    sharing a folded form make the reading ambiguous, and ambiguity
        #    is reported, never guessed.
        c = _confuse(n)
        hits = self.by_confuse.get(c) or []
        if len(hits) == 1:
            return hits[0], "variant"
        if len(hits) > 1:
            return "", ""
        if "/" in str(candidate):
            cb = _confuse(normalize(str(candidate).split("/", 1)[0]))
            hits = self.by_confuse.get(cb) or []
            if len(hits) == 1:
                return hits[0], "variant"
        # confusion + glued tail combined (single unambiguous hit only)
        if len(c) >= 14:
            for cut in range(4, len(c) - 9):
                if not c[-cut:].isalpha() and not n[-cut:].isalpha():
                    continue
                hits = self.by_confuse.get(c[:-cut]) or []
                if len(hits) == 1:
                    return hits[0], "glued"

        return "", ""

    # ── printed form ──────────────────────────
    def printed_form(self, matched_code: str, token: str) -> str:
        """
        The value written to the Material Code column.

        The document's own spelling is preserved whenever the token IS the
        code. Three shapes count as "is the code":

            token == listed code                 DW80CG4051SRAA
            token == listed code, market part    DVE45T6000W  (list: .../A3)
            token == code + short market suffix  RF18A5101SRAA (list: .../AA)
            token == code minus its suffix       DW80CG4051SR  (list: ...SRAA)

        Anything else means the token is not a clean code - OCR glued a
        description word to it ('WF45B6300APPLATINUM') or swapped characters
        ('WF4SB6300AP') - and publishing it would be wrong. The backbone
        spelling is used instead, base part only, so the output stays a clean
        model number.
        """
        tok = (token or "").strip().upper()
        if not tok:
            return str(matched_code).split("/", 1)[0].upper()

        base_src = str(matched_code).split("/", 1)[0]
        nt = normalize(tok)
        nb = normalize(base_src)
        nm = normalize(matched_code)

        # Exact match against either spelling of the listed code
        if nt in (nm, nb):
            return tok

        # Token adds a suffix the list does not carry. Only a RECOGNISED
        # market suffix is accepted. Allowing any short tail let stray
        # characters through: 'DW80CG4051SRAAB' (the 'B' was the next line's
        # item label) was published as if it were a real code.
        for ref in (nb, nm):
            if nt.startswith(ref) and len(nt) > len(ref):
                tail = nt[len(ref):]
                if MARKET_SUFFIX.fullmatch(tail):
                    return tok

        # Token is the code without the market suffix the list carries
        # (list DW80CG4051SRAA, document DW80CG4051SR)
        for ref in (nb, nm):
            if ref.startswith(nt) and len(ref) > len(nt):
                if MARKET_SUFFIX.fullmatch(ref[len(nt):]):
                    return tok

        # Otherwise the token carries extra text or misread characters.
        return base_src.upper()

    # ── line scan ─────────────────────────────
    def _glued_prefix(self, token: str):
        """
        (code, kind) when `token` starts with a known code and then continues
        into prose; None otherwise.

        BackboneIndex is hash-based, so this is at most len(token) lookups
        (about 40) and runs only for tokens that already failed an exact
        match.
        """
        t = (token or "").strip()
        if len(t) < self.MIN_CODE_LEN + 4:
            return None
        for cut in range(len(t) - 4, self.MIN_CODE_LEN - 1, -1):
            head, tail = t[:cut], t[cut:]
            # The remainder must look like the beginning of a description, not
            # a longer model. Two accepted shapes:
            #   "INCHWARMINGDRAWER"  - prose straight away
            #   "30INCHWARMINGDRAWER" - a size ("30 inch") then prose
            # A remainder that is mostly digits ("12A3") is a different, longer
            # model and is left alone.
            if len(tail) < 4 or not tail.isalnum():
                continue
            words = re.findall(r"[A-Za-z]+", tail)
            if not words or len(words[0]) < 3:
                continue
            digits = sum(1 for ch in tail if ch.isdigit())
            if digits > len(tail) / 3:
                continue
            hit = self.by_norm.get(normalize(head)) \
                or self.by_base.get(normalize(head))
            if hit:
                return hit, "glued"
        return None

    def scan_line(self, line: str) -> list:
        """
        Find every backbone code present in a line.
        Tokenises once, then does hash lookups - independent of list size.
        Returns: [(matched_code, kind, printed_token), ...]
        """
        if not line or not self.raw:
            return []

        found, seen = [], set()
        tokens = [(m.group(0), m.start()) for m in _TOKEN.finditer(line)]

        # single tokens
        for tok, _pos in tokens:
            clean = tok.strip(" .,;:()[]")
            code, kind = self.lookup(clean)
            if code and code not in seen:
                seen.add(code)
                found.append((code, kind, self.printed_form(code, clean)))
                continue

            # OCR sometimes welds the model onto the description with no
            # space: "DWR30U900WPDA30INCHWARMINGDRAWERPANELREADY". The whole
            # token matches nothing and the description would hide a real
            # order line. Try the longest prefix that IS a known code, and
            # accept it only when what follows looks like the start of prose
            # (a letter run of 4+), never when a digit follows - that would
            # be a different, longer model.
            glued = self._glued_prefix(clean)
            if glued:
                gcode, gkind = glued
                if gcode not in seen:
                    seen.add(gcode)
                    found.append((gcode, gkind,
                                  self.printed_form(gcode, gcode)))

        # multi-word codes, e.g. a list entry written "E5 RANE", or one the
        # importer joined ("LABOR-WASHER" <- "Labor Washer")
        if self.multi_token and len(tokens) > 1:
            words = [t for t, _ in tokens]
            for span in range(2, min(self.max_token_span, 4) + 1):
                for i in range(len(words) - span + 1):
                    group = words[i:i + span]
                    joined = "".join(group)

                    variants = [joined]
                    # OCR often welds a stray letter onto the first word
                    # ("HLabor Washer" for "Labor Washer"). Try dropping it.
                    if len(group[0]) > 3 and group[0][0].isalpha():
                        variants.append("".join([group[0][1:]] + group[1:]))

                    for cand in variants:
                        n = normalize(cand)
                        if len(n) < self.MIN_CODE_LEN:
                            continue
                        hit = (self.by_norm.get(n)
                               or self.by_stem.get(strip_variant(cand)))
                        if hit and hit not in seen:
                            seen.add(hit)
                            found.append((hit, "exact",
                                          str(hit).upper()))
                            break

        return found


# ──────────────────────────────────────────────
# Parenthesized code extraction
# ──────────────────────────────────────────────
PAREN_TOKEN = re.compile(r"\(([^)]{3,40})\)")

PAREN_NOISE = re.compile(
    r"(?i)^(install|installation|each|ea|pcs|total|qty|quantity|"
    r"optional|included|see|note|tbd|n/?a|new|used|opt)$"
)

MODEL_PREFIX = re.compile(r"(?i)^(model|mdl|item|part|sku|code)\s*[#:\-]?\s*")

# Pure measurements that must never be treated as codes
MEASUREMENT = re.compile(
    r"(?i)^[\d\.]+\s*(IN|INCH|CM|MM|CF|CU|CFM|FT|LB|KG|OZ|W|V|HZ|AMP|BTU|\"|')?$"
)


def extract_parenthesized_codes(line: str) -> list:
    """Pull code-like tokens out of parentheses, in order of appearance."""
    out = []
    for m in PAREN_TOKEN.finditer(line or ""):
        inner = MODEL_PREFIX.sub("", m.group(1).strip()).strip()
        if not inner or PAREN_NOISE.match(inner):
            continue

        cand = max(inner.split(), key=len) if " " in inner else inner
        cand = cand.strip(" .,;:").upper()

        if not (3 <= len(cand) <= 24):
            continue
        if not re.search(r"\d", cand):
            continue
        if MEASUREMENT.match(cand):
            continue
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9\-\/]{2,23}", cand):
            continue
        if looks_like_scrambled(cand):
            continue

        out.append(cand)
    return out


# ──────────────────────────────────────────────
# Scrambled-text guard
# ──────────────────────────────────────────────
def looks_like_scrambled(code: str) -> bool:
    """
    Detect tokens produced by two text columns being merged, e.g.
    'DISWH8W0ACSGH4E0R5'.

    Real material codes have structure: a letter prefix, then digits, then an
    optional short letter suffix. Interleaved text produces long tokens with
    letters and digits alternating irregularly.
    """
    raw = code or ""
    c = raw.upper()
    if len(c) < 8:
        return False

    # Mixed upper/lower inside one token is a strong interleaving signal;
    # real codes are printed in a single case.
    body = raw[1:]
    if any(ch.islower() for ch in body) and any(ch.isupper() for ch in body):
        return True

    # Count letter<->digit transitions over the ALPHANUMERIC characters only.
    #
    # Counting them across the raw string made the separators themselves count
    # as transitions: in 'DVE45T6000W/A3' the 'W' -> '/' -> 'A' pair is two
    # flips on top of the five real ones, pushing a perfectly ordinary market
    # suffix over the threshold. Every '/A3', '/A5', '/A2' code was therefore
    # reported as scrambled and DROPPED from the parenthesised path - silently,
    # because the guard sits before the backbone lookup. A separator is
    # structure, not interleaving, so it is removed before counting.
    alnum = [ch for ch in c if ch.isalnum()]
    transitions = sum(
        1 for a, b in zip(alnum, alnum[1:])
        if a.isalpha() != b.isalpha()
    )
    # Measured on the live POs: DW80CG4051SRAA 4, NZ36K7880USAA 4,
    # WD53DBA900HB 4, RF70H30KER 4, DRZ30980LAPDA 2 - and WW25FG6B34BE 6,
    # which the old floor of 6 rejected outright and dropped from the order.
    # Interleaved junk (DISWH8W0ACSGH4E0R5) sits at 9. A floor of 8 keeps a
    # genuine model with four letter/digit groups while still catching text
    # printed from two columns that ran together.
    return transitions >= max(8, len(alnum) * 0.45)


# ──────────────────────────────────────────────
# Quantity / unit parsing
# ──────────────────────────────────────────────
UNIT_WORDS = r"(?:EA|EACH|PCS?|PC|UNITS?|SET|BOX|CS|CTN|LOT)"

# Measures. A number next to one of these describes the appliance, not the
# order: "6.0 cf", "30 in", "120 v", "4.5 cu ft".
MEASURE_WORDS = (r"(?:CF|CU|CUFT|IN|INCH|V|VAC|W|WATT|HZ|LB|LBS|KG|MM|CM|"
                 r"AMP|BTU|RPM|FT|SQ|GAL|OZ|DEG|LITER|L)")

# Order quantities on a purchase order line are small. Manufacturer sequence
# numbers (12816) sit next to the unit marker in some layouts and would
# otherwise be read as the quantity, so 4+ digit values are not accepted from
# a bare "<n> EA" match, and the unitless single-number last resort in
# parse_quantity() is capped here as well. Explicitly labelled quantities
# may be larger.
MAX_BARE_QTY = 999

QTY_PATTERNS = [
    # The lookbehind keeps a fractional count whole: on "1.5 EA" the digits
    # after the point used to match on their own and publish a quantity of 5.
    # A quantity the document did not print is worse than none at all, so the
    # rule is to find nothing here and let the operator fill it in.
    re.compile(r"(?<![\d.])(\d{1,4}(?:,\d{3})*)\s*" + UNIT_WORDS + r"\b",
               re.IGNORECASE),
    re.compile(r"(?i)\bq(?:ty|uantity)\.?\s*[:\-]?\s*(\d{1,5}(?:,\d{3})*)\b"),
    re.compile(r"(?i)\border\s*qty\.?\s*[:\-]?\s*(\d{1,5}(?:,\d{3})*)\b"),
    # A count printed with a decimal column: "2.00 ea". Anchored to a QUANTITY
    # unit, which is what keeps the old failure out - "6.0 cf" is a capacity and
    # must never become the quantity 6.
    re.compile(r"\b(\d{1,4})\.0{1,3}\s*" + UNIT_WORDS + r"\b", re.IGNORECASE),
]

UNIT_PATTERN = re.compile(r"\b(" + UNIT_WORDS + r")\b", re.IGNORECASE)
QTY_HEADER = re.compile(r"(?i)^(qty|quantity|unit|uom|ea|each|pcs?)$")


# An order quantity above this is almost certainly a different field
# (MFG number, UPC, item id) that leaked into the quantity position.
# Real appliance PO lines are single or double digit; 999 leaves ample room
# while excluding 5-digit manufacturer numbers such as 12816.
# Large bulk orders are legitimate, so the ceiling stays generous. The
# manufacturer-number problem (12816 sitting next to "EA") is handled by the
# digit-count limit in the "<n> EA" pattern instead of by a small ceiling,
# which would have rejected real 4-digit order quantities.
MAX_QUANTITY = 9999


def _valid_qty(value: str) -> bool:
    """Reject values that cannot be an order quantity."""
    v = (value or "").replace(",", "").strip()
    if not v.isdigit():
        return False
    n = int(v)
    if n <= 0 or n > MAX_QUANTITY:
        return False
    # 4+ digit zero-padded values are line numbers (0001, 0008), not counts
    if len(v) >= 4 and v[0] == "0":
        return False
    return True


# ── printed shapes shared with the DRM text route ────────────────────────
# A DRM-wrapped PO is sometimes handed over as TEXT only - no word
# coordinates, no columns (of_pdf.resolve() returns mode "text", HANDOVER
# 6.6 L4a/L4b). That route used to carry its own readers for these three
# shapes, and the two implementations drifted: the same printed line read a
# different quantity and price depending on HOW the document had been opened,
# which is not acceptable - HANDOVER 6.6 makes route agreement a requirement.
# The shapes live here now so there is one implementation of them.

# The count printed BETWEEN two amounts: "$ 151.98 1 $ 151.98" (Marcone
# prints price, count, extended). No unit word and no column identifies it,
# so only the two currency marks bracket it.
_QTY_BETWEEN_MONEY = re.compile(
    r"[$£€]\s*[\d,]+(?:\.\d{1,4})?\s+(\d{1,4})\s+[$£€]\s*[\d,]+(?:\.\d{1,4})")

# "<unit price> EA <extended>" - the Samsung / Google Express line shape:
#   '3 EA 10/12/2026 NSG80H60SR 832.30 EA 2,496.90'
# The price comes FIRST. Reading "the figure after the unit word" published
# the EXTENDED cost as the unit price (832.30 -> 2,496.90).
_PRICE_EA_EXTENDED = re.compile(
    r"(?<!\S)([\d,]+\.\d{2})\s+(?:EA|EACH|PCS?|UNITS?)\s+([\d,]+\.\d{2})(?!\d)",
    re.IGNORECASE)

# The first figure after a currency mark: "$ 599.00". A PO prints the unit
# price before the extended cost, so the first one is the price.
_CURRENCY_PRICE = re.compile(r"[$£€]\s*([\d,]+(?:\.\d{1,4})?)(?!\d)")

# "$ 5 7.11" - one figure whose first 1-2 digits were split off behind the
# currency mark. The glyphs touch and the PDF ends a text run between them.
_SPLIT_AFTER_CURRENCY = re.compile(
    r"([$£€])\s*(\d{1,2})\s+(\d{1,3}(?:,\d{3})+(?:\.\d{1,4})?|\d{1,2}\.\d{1,4})")


def _fuse_split_figures(line: str) -> str:
    """
    Close a figure the document split with a space after its first digits.

    Marcone prints "$57.11" and the text layer hands back "$ 5 7.11": two
    tokens. Joined they read as one price; the amount on the same line
    confirms it (2 x 57.11 = 114.22).

    Only a figure split behind a CURRENCY MARK is fused, and only when the
    first part is 1-2 digits - so a piece count followed by an amount
    ("Total 42 36,565.00") is left alone.

    Moved out of the DRM text route so both read routes see the same figures.
    """
    return _SPLIT_AFTER_CURRENCY.sub(
        lambda m: f"{m.group(1)} {m.group(2)}{m.group(3)}", line or "")


def _price_amount_by_shape(line: str, money: list, qty) -> tuple:
    """
    Read (price, amount) from a printed SHAPE, when the figures alone do not
    say which is which.

    Used only after `_assign_money()` has declined - i.e. when no pair of the
    line's money figures satisfies qty x price == amount. Two layouts carry
    the answer in their typography instead:

      * "$599.00 ... $1,198.00"  - the first figure after a currency mark is
        the unit price;
      * "832.30 EA 2,496.90"     - the figure before the unit word is the
        price and the one after it is the extended cost.

    The figure must be POSITIVE. A PO line prints discount and adjustment
    columns of "0.00" to the left of the price ("$0.00 $45.26 $45.26"), and
    taking the first currency mark on the page published 0.00 as the unit
    price of every one of those rows. 0.00 is not a price on a purchase order
    - the same bar `_order_line_is_plausible()` sets.

    Values are returned AS PRINTED - this assigns, it does not compute.
    Returns None to leave the caller on the positional reading.
    """
    if not line:
        return None

    price = None
    cur = _CURRENCY_PRICE.search(line)
    if cur:
        # Walk the currency marks and take the first figure that is actually
        # a price; skip the zero-valued discount columns in front of it.
        for m in _CURRENCY_PRICE.finditer(line):
            cand = m.group(1).replace(",", "")
            try:
                if float(cand) > 0:
                    price = cand
                    break
            except ValueError:
                continue
    else:
        pair = _PRICE_EA_EXTENDED.search(line)
        if pair:
            cand = pair.group(1).replace(",", "")
            try:
                if float(cand) > 0:
                    price = cand
            except ValueError:
                price = None
    if not price:
        return None
    amount = money[-1] if money else ""
    return (price, amount)


def parse_quantity(text: str) -> tuple:
    """
    Extract (quantity, unit) from a text fragment.

    Anything failing _valid_qty is discarded rather than returned: on OCR'd
    tables an MFG number sitting next to 'EA' would otherwise be published as
    the order quantity (12816 instead of 2).
    """
    if not text:
        return "", ""

    t = text.strip()
    if QTY_HEADER.match(t):
        return "", ""

    unit = ""
    um = UNIT_PATTERN.search(t)
    if um:
        unit = um.group(1).upper()
        if unit == "EACH":
            unit = "EA"

    for pat in QTY_PATTERNS:
        for m in pat.finditer(t):
            v = m.group(1).replace(",", "")
            # "2.00 ea" is the integer 2. Only an all-zero decimal part is
            # dropped, so a fractional count ("1.5 EA") is left alone.
            if re.fullmatch(r"\d+\.0+", v):
                v = v.split(".", 1)[0]
            if _valid_qty(v):
                return v, unit

    m = re.fullmatch(r"\s*(\d{1,5}(?:,\d{3})*)\s*" + UNIT_WORDS + r"?\s*", t,
                     re.IGNORECASE)
    if m and _valid_qty(m.group(1)):
        return m.group(1).replace(",", ""), unit

    nums = [n for n in re.findall(r"\b(\d{1,5})\b", t) if _valid_qty(n)]
    if len(nums) == 1:
        # Last resort: one number on the line is the quantity. It is not one
        # when the document is describing a size - "6.0 cf" is a 6 cu.ft.
        # capacity, and reading the 6 as an order quantity put six machines on
        # a PO that ordered one. A number attached to a measure is not a count.
        # A bare number with no unit is also capped at MAX_BARE_QTY: long
        # values that survive the measure guards (a UPC tail, a serial) are
        # line identifiers, not how many units were ordered.
        n = nums[0]
        if int(n) <= MAX_BARE_QTY \
                and not re.search(r"\b" + re.escape(n) + r"\s*\.\s*\d", t) \
                and not re.search(r"\b" + re.escape(n) + r"\s*" + MEASURE_WORDS
                                  + r"\b", t, re.IGNORECASE):
            return n, unit

    # The count printed BETWEEN two amounts: "$ 187.78 1 $ 187.78" (Marcone).
    # Nothing above can see it - there is no unit word, and it is not the only
    # number on the line. Only the two currency marks bracket it. This shape
    # was worked out on the DRM text route and is MOVED HERE so the two read
    # routes cannot disagree about the same printed line.
    between = _QTY_BETWEEN_MONEY.search(t)
    if between and _valid_qty(between.group(1)):
        return between.group(1), unit

    return "", unit


# ──────────────────────────────────────────────
# Line-level extraction
# ──────────────────────────────────────────────
LINE_NOISE = re.compile(
    r"(?i)^\s*("
    r"option\s*selection|style\s*/?\s*color|material\s*code|item\s*code|"
    r"description|quantity|qty|unit|price|amount|total|page|date|"
    r"purchase\s*order|p\.?o\.?|subtotal|sales\s*tax|grand\s*total"
    r")\s*$"
)

_HYPHEN_WRAP = re.compile(r"(?<=[A-Za-z0-9])-\s+(?=[A-Za-z0-9])")


def dehyphenate(text: str) -> str:
    """Rejoin tokens split across lines at a hyphen."""
    return _HYPHEN_WRAP.sub("-", text or "")


# Confidence ranking - higher wins when several candidates share one row
KIND_RANK = {
    "exact":   100,
    "variant":  90,
    "glued":    85,   # backbone-confirmed, but the printed token was corrupted
    "paren":    50,
    "pattern":  10,
}


def extract_codes_from_line(line: str,
                            backbone: BackboneIndex,
                            regex_patterns: list = None,
                            min_len: int = 4,
                            max_len: int = 24,
                            allow_pattern: bool = True) -> list:
    """
    Extract material code candidates from one line.

    Returns: [{"code", "match_kind", "confidence", "description", "category"}]
    sorted by confidence, highest first.
    """
    results = []
    if not line or LINE_NOISE.match(line):
        return results

    line = dehyphenate(line)
    seen = set()

    def add(code, kind, printed=None):
        key = normalize(code)
        if not key or key in seen:
            return
        seen.add(key)
        info = backbone.info(code) if backbone.enabled else {}
        results.append({
            "code": printed or code,
            "backbone_code": code if info else "",
            "match_kind": kind,
            "confidence": KIND_RANK.get(kind, 0),
            "description": info.get("description", ""),
            "category": info.get("category", ""),
        })

    # 1) Backbone matches - the only source trusted for output
    if backbone.enabled:
        for code, kind, printed in backbone.scan_line(line):
            add(code, kind, printed=printed)

    # 2) Parenthesized candidates
    for cand in extract_parenthesized_codes(line):
        if backbone.enabled:
            matched, kind = backbone.lookup(cand)
            if matched:
                add(matched, kind, printed=backbone.printed_form(matched, cand))
                continue
        add(cand, "paren")

    # 3) Regex fallback
    if not results and regex_patterns and allow_pattern:
        for pat in regex_patterns:
            for m in pat.finditer(line):
                cand = m.group(0).strip().upper()
                if not (min_len <= len(cand) <= max_len):
                    continue
                if not re.search(r"\d", cand):
                    continue
                if re.search(r"[A-Z]{7,}", cand):
                    continue
                if looks_like_scrambled(cand) or MEASUREMENT.match(cand):
                    continue
                if backbone.enabled:
                    matched, kind = backbone.lookup(cand)
                    if matched:
                        add(matched, kind, printed=backbone.printed_form(matched, cand))
                        continue
                add(cand, "pattern")

    results.sort(key=lambda r: -r["confidence"])
    return results


def select_row_codes(candidates: list, backbone: BackboneIndex) -> tuple:
    """
    Decide which candidates from one row/block become output records.

    Policy:
      - EVERY backbone-confirmed candidate is kept. Confirmed codes cannot be
        ghosts, and several distinct confirmed codes in one block means the
        block simply covers several real items (row merging is imperfect).
        Dropping any of them loses a genuine order line.
      - Unconfirmed candidates are kept only when NOTHING confirmed exists on
        the row - and then only the single strongest one. This is the ghost
        filter: a scrambled token never outranks a confirmed code.

    Returns: (keep: [candidate], rejected: [candidate])
    """
    if not candidates:
        return [], []

    # Dedupe by normalized code, keeping the highest-confidence sighting
    best_by = {}
    for c in candidates:
        k = normalize(c.get("code", ""))
        if not k:
            continue
        if k not in best_by or c["confidence"] > best_by[k]["confidence"]:
            best_by[k] = c

    ordered = sorted(best_by.values(),
                     key=lambda c: (-c["confidence"], -len(c["code"])))
    if not ordered:
        return [], []

    confirmed = [c for c in ordered if c.get("backbone_code")]

    if backbone.enabled and confirmed:
        keep = confirmed
        rejected = [c for c in ordered if not c.get("backbone_code")]
    else:
        keep = [ordered[0]]
        rejected = ordered[1:]

    return keep, rejected


def _editorial_note(matched: str, listed: int) -> str:
    return ("which one is meant is not printed" if listed > 1
            else "the document prints the code short")


def _suffix_verdict(printed: str, matched: str, backbone) -> str:
    """
    What to do with a record whose printed token is a PREFIX of the listed
    code `matched`, the document having said nothing about the rest:

        'L-INST/E2'      -> 'L-INST/E2-BEV' / '-UIC'   list both: "reject"
        'NSE6DG8550SR'   -> 'NSE6DG8550SRAA'           list one:  "copy"
        'DVE45T6000W'    -> 'DVE45T6000W/A3'           list one:  "keep"

    Returns "keep" (nothing to do), "copy" or "reject".

    The failure this closes happened on Marcone MNH090926-HZL279: the line
    "L-INST/E2  Rebate included." was confirmed against 'L-INST/E2-BEV', and
    the record kept the PRINTED 'L-INST/E2' - a code the master does not
    carry, published next to thirty confirmed lines. Which service line the
    customer meant (BEV cooktop or UIC under-counter ice?) is not printed, so
    a guess could bill the wrong one: that is "reject".

    When exactly ONE listed code extends the printed one, the master list is
    the authority on how the SKU is spelled, and the extension past the
    printed text is the regional suffix that all three shapes here share:
        DVE45T6000W -> DVE45T6000W/A3   '/A3'      ERP prints the market
        NSE6DG8550SR -> NSE6DG8550SRAA  'AA'       ERP prints the suffix
        L-INST/E2 -> L-INST/E2-BEV      '-BEV'     <- NOT a dealer notation
    A '-' tail is a service/package distinction, not a market suffix, so it
    is never copied: it is rejected like the ambiguous case.
    """
    p = _print_form(printed)
    m = _print_form(matched)
    if not p or not m or p == m:
        return "keep"
    stem = m
    if not stem.startswith(p):
        # 'DVE45T6000W' vs 'DVE45T6000W/A3': compare without separators, so
        # the slash cannot hide the growth.
        pn, mn = normalize(printed), normalize(matched)
        if not mn.startswith(pn) or len(mn) - len(pn) > 4:
            return "keep"
        if not MARKET_SUFFIX.fullmatch(mn[len(pn):]):
            return "keep"
        return "keep"                     # normal ERP notation - unchanged

    tail = stem[len(p):]
    if len(tail) > 4 or not MARKET_SUFFIX.fullmatch(normalize(tail)):
        return "reject"
    if tail.startswith("-"):
        # '-BEV' / '-UIC' / '-DW' separate two SERVICES; they are not a dealer
        # notation, so the printed text is never completed into one of them.
        return "reject"

    # One listed code extends the printed one -> the master's spelling wins.
    same_prefix = [c for c in (getattr(backbone, "by_prefix", {}) or {}).get(
        _print_form(matched), []) if _print_form(c).startswith(p)]
    return "copy" if len(same_prefix) <= 1 else "reject"


def _resolve_short_codes(records: list, backbone: BackboneIndex,
                         review_items: list, source_file: str,
                         doc_po: str) -> list:
    """
    Copy the master's spelling onto a line whose printed code stops short of
    it, and send the genuinely ambiguous ones to `review`.
    See `_suffix_verdict()` for the rule and for why it exists.
    """
    kept = []
    for r in records:
        printed = str(r.get("material_code") or "")
        matched = str(r.get("backbone_code") or "")
        verdict = ("keep" if not matched or not printed
                   or backbone.by_norm.get(normalize(printed)) == matched
                   else _suffix_verdict(printed, matched, backbone))
        if verdict == "keep":
            kept.append(r)
            continue
        if verdict == "copy":
            r["material_code"] = matched
            r["printed_code"] = printed
            kept.append(r)
            continue
        listed = [c for c in (getattr(backbone, "by_prefix", {}) or {}).get(
            _print_form(matched), []) if _print_form(c).startswith(
                _print_form(printed))]
        review_items.append({
            "candidate":   printed,
            "score":       _mt_score(r.get("match_type")),
            "match":       r.get("match_type", ""),
            "reason":      (f"An incomplete code - the master lists "
                            f"{matched}"
                            + (f" and {len(listed)} entries share this "
                               f"prefix" if len(listed) > 1 else "")
                            + f"; {_editorial_note(matched, len(listed))}"),
            "context":     (r.get("description") or "")[:160],
            "page":        r.get("page"),
            "source_file": source_file,
            "po_number":   r.get("po_number") or doc_po,
        })
        # KEEP the line when it carries everything an order line needs - a
        # printed code, a quantity and a believable price. Marcone
        # LV0218FWF26SAM prints "HAF-QIN" (the master carries only
        # HAF-QIN/CIN, /EXP, /XME - three answers, so the right one cannot be
        # picked), and dropping it emptied the WHOLE order: one line, 60 water
        # filters, 1,649.40. An order missing its only line is worse than one
        # line a human must look at, and the review list already names it.
        # The spelling stays as printed and the backbone link is cleared, so
        # normalize_output_codes() cannot quietly rewrite it to a guess.
        if _order_line_is_plausible(r):
            r["backbone_code"] = ""
            r["needs_review"] = True
            r["match_type"] = "pattern (unlisted)"
            kept.append(r)
    return kept


def match_kind_to_type(kind: str, from_zone: bool = False) -> str:
    """
    Map an internal match kind to the stored match_type.

    'glued' means the backbone DID confirm the code but the printed token was
    corrupted - a description word fused to it, or characters misread. Those
    rows were labelled 'pattern', which reads as "not in the master list" and
    made a correct extraction look untrustworthy in the report. They are
    reported as reference matches, with the repair noted so a reviewer can
    still spot-check them.
    """
    if kind in ("exact", "variant"):
        return "zone+reference" if from_zone else "reference"
    if kind == "glued":
        return "zone+reference (repaired)" if from_zone else "reference (repaired)"
    if kind == "paren":
        return "zone+paren" if from_zone else "paren"
    return "zone" if from_zone else "pattern"


def is_confirmed(record: dict) -> bool:
    """True when the record was validated against the backbone list."""
    return bool(record.get("backbone_code")) or \
        "reference" in (record.get("match_type") or "")


# The shape of a printed model number, used only to decide whether a code the
# master list does not carry still LOOKS like one. Samsung prints a run of
# letters, digits, more letters and digits, optionally with a market suffix
# (WD53DBA900HB, NZ36K7880USAA, WF45B6300AP/US, DVG52A5500W/A3).
_MODEL_SHAPE = re.compile(
    r"^[A-Z]{2,6}\d{1,5}[A-Z0-9]{2,12}(?:/[A-Z0-9]{2})?$")


def _pattern_row_is_plausible(record: dict) -> bool:
    """
    Would a human accept this unlisted code as an order line?

    Evidence required, all of it already on the record:
      * the code has a model-number shape (not a stray token the regex caught),
      * the row carries a quantity AND a unit price - an order line always
        prints both, a stray match in prose usually does not,
      * the price is a believable amount (not 0.00, not astromically large).

    Kept deliberately conservative: a code that fails any of these still goes
    to `review`, so nothing that used to be reported has stopped being
    reported - it has only stopped being DROPPED from the output.
    """
    code = str(record.get("material_code") or "").strip().upper()
    if not _MODEL_SHAPE.match(code):
        return False

    qty = str(record.get("quantity") or "").strip()
    if not qty or not qty.replace(",", "").replace(".", "").isdigit():
        return False

    price = str(record.get("unit_price") or "").strip().replace("$", "").replace(",", "")
    try:
        amount = float(price)
    except ValueError:
        return False
    # 0.00 is not a price on a purchase order; $200k is not a unit price.
    return 0.0 < amount < 200000.0


def _order_line_is_plausible(record: dict) -> bool:
    """
    Is this a complete order line, whatever the code looks like?

    The bar is the one `_pattern_row_is_plausible()` uses for unlisted codes -
    a quantity and a believable unit price - WITHOUT the model-shape test. That
    test is right for a regex hit ("could this token be a product code?") but
    wrong here: the token was already recognised against the master as a short
    form of a listed code, so `HAF-QIN` (no digits, a hyphen) is strong
    evidence, not a stray match.
    """
    qty = str(record.get("quantity") or "").strip()
    if not qty or not qty.replace(",", "").replace(".", "").isdigit():
        return False
    price = str(record.get("unit_price") or "").strip()
    price = price.replace("$", "").replace(",", "")
    try:
        amount = float(price)
    except ValueError:
        return False
    return 0.0 < amount < 200000.0


def _apply_accuracy_gate(records: list, backbone, review_items: list,
                         source_file: str, doc_po: str,
                         zone_diag: list = None) -> list:
    """
    Keep confirmed rows, and keep plausible unlisted ones flagged for review.

    This gate used to exist twice - once for the zone path and once for the
    pattern path - and the two copies drifted: fixing the pattern copy left
    the zone copy still dropping every model the master list had not learned
    yet. N104789 printed WW25FG6B34BE at $833.00 and only the zone copy could
    see that line, so the order stayed one line short after the first fix.
    Both callers now go through here.

    Returns the records that reach the main output.
    """
    confirmed, unconfirmed = [], []
    for r in records:
        (confirmed if is_confirmed(r) else unconfirmed).append(r)

    # A printed code that stops short of the listed one ('L-INST/E2' for
    # 'L-INST/E2-BEV') is resolved here - see _suffix_verdict().
    confirmed = _resolve_short_codes(
        confirmed, backbone, review_items, source_file, doc_po)

    kept = 0
    for r in unconfirmed:
        if _pattern_row_is_plausible(r):
            r["needs_review"] = True
            r["match_type"] = f"{r.get('match_type') or 'pattern'} (unlisted)"
            confirmed.append(r)
            kept += 1
            continue
        review_items.append({
            "candidate":   r["material_code"],
            "score":       _mt_score(r.get("match_type")),
            "match":       r.get("match_type", ""),
            "reason":      "Not found in the backbone list",
            "context":     (r.get("description") or "")[:160],
            "page":        r.get("page"),
            "source_file": source_file,
            "po_number":   r.get("po_number") or doc_po,
        })

    if kept and zone_diag is not None:
        zone_diag.append(
            f"{kept} code(s) were used but are not in the Material Code "
            f"master - check them before uploading (flagged for review).")
    return confirmed


# ==========================================================================
#  SECTION: EXTRACTOR - orchestration and the public entry point
#  (formerly extractor.py)
# ==========================================================================

"""
extractor.py - Extract Material Codes / PO Numbers from PDFs and cache as JSON
v3.0: Zone-template extraction + reference-list matching + advanced PO Number parsing
"""







# A zero-padded line number printed at the start of an item row:
#   "0006  12816  2 EA SSW  WF4SB6300AP ..."
# This is the PO's own identifier for the line, and the most reliable way to
# tell two order lines of the SAME model apart when OCR loses a quantity.
_PO_LINE_NO = re.compile(r"^\s*(0\d{2,4})\b")

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
CACHE_DIR = BASE_DIR / "data_cache"
UPLOAD_DIR = BASE_DIR / "data_upload"
OUTPUT_DIR = BASE_DIR / "data_output"
REFERENCE_PATH = BASE_DIR / "material_codes_reference.csv"
TEMPLATES_PATH = BASE_DIR / "customer_templates.json"

for d in [CACHE_DIR, UPLOAD_DIR, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────
# Config loading (mtime-cached: batch runs reload nothing)
# ──────────────────────────────────────────────
_FILE_CACHE = {}    # path -> (mtime, size, parsed_value)


def _cached_load(path: Path, loader):
    """Reload a file only when its mtime or size changed."""
    try:
        st = path.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return loader()
    hit = _FILE_CACHE.get(path)
    if hit and hit[0] == key:
        return hit[1]
    value = loader()
    _FILE_CACHE[path] = (key, value)
    return value


def load_config() -> dict:
    def _read():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return _cached_load(CONFIG_PATH, _read)


# ──────────────────────────────────────────────
# Customer template loading
# ──────────────────────────────────────────────
def load_templates() -> dict:
    """Load customer_templates.json. Returns: {customer_name: {zones:[...], ...}}"""
    if not TEMPLATES_PATH.exists():
        return {}
    try:
        data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
        customers = data.get("customers", {})
        _backfill_fingerprints(customers)
        return customers
    except Exception as e:
        logger.error(f"Template load failed: {e}")
        return {}


def _backfill_fingerprints(customers: dict):
    """
    Older templates were saved without a content fingerprint. Short template
    names (e.g. 'PO') are excluded from filename matching to avoid hijacking
    unrelated files, so without a fingerprint they could never match at all.
    Build the missing fingerprints once from each stored sample PDF.
    """
    changed = False
    for name, tmpl in customers.items():
        if tmpl.get("fingerprint"):
            continue
        sample = tmpl.get("sample_pdf", "")
        if not sample or not Path(sample).exists():
            continue
        try:
            pages = get_pages(sample, load_config())
            head = "\n".join(p["text"] for p in (pages or [])[:2])
            fp = build_fingerprint(head)
            if fp:
                tmpl["fingerprint"] = fp
                changed = True
                logger.info(f"Fingerprint backfilled for template '{name}'")
        except Exception as e:
            logger.debug(f"Fingerprint backfill failed for '{name}': {e}")

    if changed:
        try:
            data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
            data["customers"] = customers
            TEMPLATES_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not persist backfilled fingerprints: {e}")


def build_fingerprint(text: str, max_terms: int = 40) -> list:
    """
    Build a layout fingerprint from a document's leading text.

    Purchase orders from the same customer repeat the same labels, headings and
    company wording even though numbers change from file to file. Keeping the
    distinctive words lets a saved template be recognised later even when the
    filename carries no customer name (e.g. PO_0736499.pdf).
    """
    if not text:
        return []

    head = text[:2500].upper()
    tokens = re.findall(r"[A-Z][A-Z&/\.'-]{2,}", head)

    stop = {
        "THE", "AND", "FOR", "WITH", "FROM", "THIS", "THAT", "ALL", "ANY",
        "PAGE", "DATE", "TOTAL", "QTY", "EACH", "UNIT", "ITEM", "LINE",
        "PURCHASE", "ORDER", "NUMBER", "AMOUNT", "PRICE", "COST", "DESCRIPTION",
        "SHIP", "BILL", "SOLD", "ATTN", "PHONE", "FAX", "EMAIL", "ADDRESS",
        "SUBTOTAL", "TAX", "USD", "NET", "FOB", "TERMS", "STAINLESS", "INSTALL",
    }
    terms = []
    for t in tokens:
        t = t.strip(".-'/")
        if len(t) >= 4 and t not in stop and t not in terms:
            terms.append(t)
        if len(terms) >= max_terms:
            break
    return terms


def fingerprint_score(doc_terms: list, tmpl_terms: list) -> float:
    """Overlap ratio between two fingerprints (0.0 - 1.0)."""
    if not doc_terms or not tmpl_terms:
        return 0.0
    a, b = set(doc_terms), set(tmpl_terms)
    return len(a & b) / len(b)


def find_customer_template(pdf_filename: str, templates: dict,
                           doc_text: str = "") -> tuple[str, dict]:
    """
    Resolve which saved template applies to this PDF.

    1. Filename match  - the customer name appears in the filename
    2. Fingerprint     - the document's wording matches a template's sample

    Templates are optional. When nothing matches, extraction still runs using
    the backbone list and parenthesis parsing.

    Returns: (customer_name, template_dict) or ("", {})
    """
    fname_lower = pdf_filename.lower()

    # 1) Filename match (longest customer name wins, to avoid partial hits).
    #    Names shorter than 4 characters are excluded from filename matching:
    #    a template named 'PO' would otherwise hijack every file containing
    #    the letters 'po' (e.g. SAMSUNGNJ.PO4046792...), applying the wrong
    #    zone coordinates. Short-named templates still match via fingerprint.
    named = [c for c in templates
             if c and len(c) >= 4 and c.lower() in fname_lower]
    if named:
        best = max(named, key=len)
        return best, templates[best]

    # 2) Content fingerprint
    if doc_text:
        doc_terms = build_fingerprint(doc_text)
        best_name, best_score = "", 0.0
        for customer, tmpl in templates.items():
            score = fingerprint_score(doc_terms, tmpl.get("fingerprint", []))
            if score > best_score:
                best_name, best_score = customer, score
        if best_score >= 0.45:
            logger.info(
                f"{pdf_filename}: matched template '{best_name}' "
                f"by content fingerprint (score {best_score:.2f})"
            )
            return best_name, templates[best_name]

    return "", {}


# ──────────────────────────────────────────────
# Coordinate-based row extraction
# ──────────────────────────────────────────────
def words_to_rows(words: list) -> list:
    """
    Turn pre-extracted zone words into text rows.

    Pure function - no file access. Delegates to the single row-grouping
    implementation in table_parser so tolerance behaviour cannot drift
    between code paths.

    Returns: [{"y": float, "text": str}, ...] ordered top to bottom.
    """
    if not words:
        return []
    return [
        {"y": (g["top"] + g["bottom"]) / 2, "text": g["text"]}
        for g in group_words_into_rows(words)
        if g["text"]
    ]


# ──────────────────────────────────────────────
# Line-items zone: one box around the whole table
# ──────────────────────────────────────────────
def parse_line_items_zone(zone: dict, words: list, backbone,
                          regex_patterns: list, po_number: str,
                          source_file: str, max_code_len: int = 24,
                          review: list = None,
                          diag: list = None,
                          max_scan: int = 8,
                          from_zone: bool = True) -> list[dict]:
    """
    Parse a single 'line_items' zone covering the entire item table.

    `words` are the coordinates captured during zone extraction - the PDF is
    not reopened. Rows and columns are derived from those coordinates, so a
    code and its quantity are paired because they physically share a row.

    `max_scan` is how many rows down the header may sit: 8 inside a zone box
    (cropped to the table), more when the caller passes a whole page.
    `from_zone` only labels the resulting match_type - a page-level caller is
    not a template match and says so.
    """
    if review is None:
        review = []

    if not words:
        return []

    parsed = parse_line_items(words, zone.get("x0"), zone.get("x1"),
                              max_scan=max_scan)
    page = zone.get("page", 0) + 1

    def row_has_code(text: str) -> bool:
        return bool(extract_codes_from_line(
            text, backbone, regex_patterns,
            max_len=max_code_len,
            allow_pattern=_line_looks_like_item(text)
        ))

    # Prefer splitting on the Quantity column: one quantity per item makes a
    # reliable anchor even when the code wraps onto another line. A code row
    # also opens a block, because some layouts print the code BELOW the
    # quantity/price row (ERP One 01001129) and pairing by quantity alone gave
    # every item its neighbour's figures.
    if "quantity" in parsed["columns"]:
        blocks = split_blocks_by_quantity(parsed["rows"], row_has_code)
        split_mode = "quantity-anchored"
    else:
        # Without a Qty column inside the box, items cannot be split reliably
        # and quantities cannot be paired. This is almost always a box that is
        # too narrow - it must include the Qty / Unit columns and their header.
        if diag is not None:
            diag.append(
                f"Line Items box '{zone.get('label', '')}' does not include a "
                f"Qty column (detected: {list(parsed['columns']) or 'none'}). "
                f"Redraw the box to cover the Qty/Unit columns and the header row."
            )
        blocks = merge_item_blocks(parsed["rows"], row_has_code)
        split_mode = "code-anchored"

    logger.info(
        f"{source_file}: line_items zone -> header={parsed['header_found']}, "
        f"columns={list(parsed['columns'])}, split={split_mode}, "
        f"blocks={len(blocks)}"
    )

    # Wrapped codes can straddle a block boundary, so the repair is also run
    # across ALL rows of the zone. Any code recovered here that no block
    # produced is appended as its own item, with the quantity found alongside.
    zone_lines = [r["text"] for r in parsed["rows"]]
    zone_synth = repair_wrapped_codes(zone_lines, backbone)[len(zone_lines):]

    records, by_key = [], {}
    # Codes this zone showed to be description text (see
    # _codes_quoted_in_descriptions). Kept for the whole zone so the wide
    # wrap-repair pass below cannot put one back.
    quoted_keys = set()

    for block in blocks:
        # Quantity / price from dedicated columns first, then from raw text
        qty  = cell_from_block(block, "quantity")
        unit = cell_from_block(block, "unit")
        price = cell_from_block(block, "unit_price")
        amount = cell_from_block(block, "amount")

        q, u = parse_quantity(qty)
        if not q:
            # The value came from a column the header already named as Qty,
            # so it IS a count even when parse_quantity cannot read it: a
            # decimal column prints "85.00" and the unit word sits in its own
            # column, so no QTY_PATTERN matches and the decimal guard refuses
            # it as prose ("6.0 cf"). Losing the value here is what made PO
            # 514 read 300 from the "Capacity; 300" description line instead.
            q = _qty_from_cell(qty)
        if not q:
            # Column value unusable (often because neighbouring text overflowed
            # into it) - fall back to the ANCHOR row only. That row IS the
            # item's own numbers, so a count printed there belongs to it.
            #
            # It used to scan every row of the block, and then the whole block
            # text, for ANY number. On Last Samsung Order the spec text above
            # the row ("...60HZ, 4 EA") answered, and on Marcone
            # MNH090926-HZL279 the warehouse code 'HZL279' did: all 31 lines
            # came back as quantity 48. A count this engine is not sure of is
            # now reported and left empty - never guessed.
            q, u2 = _quantity_from_anchor_row(block)
            if q:
                u = u or u2
        if not q and diag is not None:
            diag.append(
                f"{source_file}: no quantity printed for {block['text'][:70]!r} "
                f"- left empty for a human; the number elsewhere on the row "
                f"is not a count")
        if not unit:
            unit = u
        qty = q

        price = _clean_money(price)
        amount = _clean_money(amount)

        price, amount = _split_price_amount(
            price, amount, cell_from_block(block, "unit_price"))

        # Codes may appear on any row of the block. Remember which row each
        # candidate came from so a multi-item block can give every code the
        # quantity printed on ITS OWN row.
        found = []
        own_row = {}          # normalized code -> row text of first sighting
        row_hits = []         # [(row, [candidate, ...]), ...] - keeps WHERE
        for r in block["rows"]:
            hits = extract_codes_from_line(
                r["text"], backbone, regex_patterns,
                max_len=max_code_len,
                allow_pattern=_line_looks_like_item(r["text"])
            )
            row_hits.append((r, hits))
            for h in hits:
                own_row.setdefault(normalize(h["code"]), r["text"])
            found += hits

        # Also scan the joined block text: a code split across printed lines
        # ("(Model E3-" / "DW) - Install") is only readable once rejoined.
        found += extract_codes_from_line(
            block["text"], backbone, regex_patterns,
            max_len=max_code_len,
            allow_pattern=_line_looks_like_item(block["text"])
        )

        # A narrow MODEL column inside the zone wraps codes the same way the
        # full page does ("DW80CG4051S" + "R" on a later row). Without this,
        # a zone template silently lost those items while the no-template
        # path found them.
        if not any(c.get("backbone_code") for c in found):
            block_lines = [r["text"] for r in block["rows"]]
            for synth in repair_wrapped_codes(block_lines, backbone)[len(block_lines):]:
                found += extract_codes_from_line(
                    synth, backbone, regex_patterns,
                    max_len=max_code_len, allow_pattern=True
                )
                if not qty:
                    q3, u3 = parse_quantity(synth)
                    if q3:
                        qty, unit = q3, (unit or u3)

        # A printed line number glued to the model code ("1WF45B6300AP") is
        # split off the same way. A scan reads that row as one token, so the
        # code carries a leading digit and matches neither the patterns nor
        # the backbone: PO 95778 lost four of its six lines this way and the
        # order came out 4,051.00 short. Only backbone-confirmed variants are
        # added - the code list decides where the number ends - and the
        # original rows are untouched, so nothing stops matching.
        for synth in _unglued_line_variants([r["text"] for r in block["rows"]],
                                            backbone):
            found += extract_codes_from_line(
                synth, backbone, regex_patterns,
                max_len=max_code_len,
                allow_pattern=_line_looks_like_item(synth)
            )
            if not qty:
                q3, u3 = parse_quantity(synth)
                if q3:
                    qty, unit = q3, (unit or u3)

        # A model NAMED INSIDE A DESCRIPTION is not an item. CMH 00958-2329551
        # prints the trim kit as
        #     3  ... MICROWAVE 30" TRIM KIT FOR  MA-TK8020TS/AA  5 EA 101.00 505.00
        #        MS19M8000AS SS                       <- the fit it is FOR
        # The wrap line starts the NEXT item's block, its code was confirmed
        # against the master, and it then took the next line's quantity and
        # price: the order came out with a 9th line worth 8,034.00 against a
        # printed total of 28,412.00 (OVER by exactly that line).
        quoted = _codes_quoted_in_descriptions(row_hits, found)
        if quoted:
            quoted_keys.update(normalize(c["code"]) for c in quoted)
            found = [h for h in found if normalize(h["code"]) not in quoted_keys]
            for c in quoted:
                if review is not None:
                    review.append({
                        "candidate":   c["code"],
                        "score":       c.get("confidence", 0),
                        "match":       c.get("match_kind", ""),
                        "reason":      ("Printed inside another item's "
                                        "description - not an order line"),
                        "context":     own_row.get(normalize(c["code"]), "")[:160],
                        "page":        page,
                        "source_file": source_file,
                        "po_number":   po_number,
                    })
            logger.info(f"{source_file}: {len(quoted)} code(s) read as "
                        f"description text: "
                        f"{', '.join(c['code'] for c in quoted[:4])}")

        if not found:
            continue

        # Ghost filter with multi-item support:
        #   - every backbone-CONFIRMED code is kept (block merging sometimes
        #     packs several real items into one block; all are genuine)
        #   - unconfirmed candidates survive only when nothing confirmed
        #     exists, and then only the strongest one
        keep, rejected = select_row_codes(found, backbone)
        if not keep:
            continue

        # Two spellings of ONE model on the same row are not two items.
        #
        # A PO can print both its own item code and the vendor reference
        # (PO 189743: "NSE6DG8502SR" and "NSE6DG8502SRAA" on one row), and
        # when the master lists BOTH spellings - 1,869 such pairs in the real
        # reference file - `select_row_codes` keeps both as separate confirmed
        # codes. `multi` was then true and the price of the line was blanked
        # out for every code, so the price and the amount were lost entirely.
        # Collapsing to the model first makes `multi` mean what its comment
        # says: several DIFFERENT items in one block.
        priced = _distinct_models(keep)
        multi = len(priced) > 1

        desc = cell_from_block(block, "description")

        # The PO's printed line number for this block, if the layout has one.
        # The leading zero-padded form is recognised anywhere on the row; a
        # plain numbered column ("Line# 1 2 3") is read from its own column,
        # which is what keeps two order lines of the same model apart.
        blk_line = ""
        for r in block["rows"]:
            m_ln = _PO_LINE_NO.match(r["text"] or "")
            if m_ln:
                blk_line = m_ln.group(1)
                break
        if not blk_line:
            cand = cell_from_block(block, "line_no")
            if cand.isdigit():
                blk_line = cand

        for item in priced:
            code_key = normalize(item["code"])
            # Include the line number so two order lines of the same model
            # cannot collapse into one record.
            key = (code_key, blk_line) if blk_line else code_key

            # Quantity: with several items in one block, the block-level qty
            # belongs to only one of them - prefer the qty on the code's own row.
            iq, iu = qty, unit
            if multi:
                q2, u2 = parse_quantity(own_row.get(code_key, ""))
                if q2:
                    iq, iu = q2, (u2 or unit)

            if key in by_key:
                ex = by_key[key]
                # Same model on a separate order line (own quantity) must stay
                # a separate record - see the note in extract_lines_with_backbone.
                prev_q = str(ex.get("quantity") or "").strip()
                if not (iq and prev_q and iq != prev_q):
                    for f, v in (("quantity", iq), ("unit", iu),
                                 ("unit_price", price), ("amount", amount)):
                        if v and not ex.get(f):
                            ex[f] = v
                    continue

            rec = {
                "material_code": item["code"],
                "backbone_code": item.get("backbone_code", ""),
                "description":   item["description"] or desc or block["text"][:140],
                "category":      item["category"],
                "quantity":      iq,
                "unit":          iu,
                "unit_price":    "" if multi else price,
                "amount":        "" if multi else amount,
                "po_line":       blk_line,
                "po_number":     po_number,
                "page":          page,
                "source_file":   source_file,
                "match_type":    match_kind_to_type(item["match_kind"], from_zone=from_zone),
                "zone_label":    zone.get("label", "Line Items"),
                "extracted_at":  datetime.now().isoformat(),
            }
            records.append(rec)
            by_key[key] = rec
            by_key.setdefault(code_key, rec)

        for c in rejected:
            review.append({
                "candidate":   c["code"],
                "score":       c.get("confidence", 0),
                "match":       c.get("match_kind", ""),
                "reason":      "Unconfirmed - a backbone-confirmed code exists on the same row",
                "context":     block["text"][:160],
                "page":        page,
                "source_file": source_file,
                "po_number":   po_number,
            })

    # Codes recovered from the zone-wide repair that no block emitted. This
    # happens when the fragment line and the code line fall into different
    # blocks, so the per-block repair above cannot see both halves.
    for synth in zone_synth:
        hits = extract_codes_from_line(
            synth, backbone, regex_patterns,
            max_len=max_code_len, allow_pattern=True
        )
        if not hits:
            continue
        q4, u4 = parse_quantity(synth)
        money4 = re.findall(r"\d[\d,]*\.\d{2}", synth)
        for item in hits:
            if not item.get("backbone_code"):
                continue
            key = normalize(item["code"])
            if key in quoted_keys:
                # The wrap repair rejoins description lines into one string, so
                # a model quoted in a description reappears here as a "code
                # recovered from a wrapped line". Dropping it from its block is
                # not enough - this pass would recreate it, with the money of
                # whatever the rejoined line happened to span.
                continue
            if key in by_key:
                ex_rec = by_key[key]
                for f, v in (("quantity", q4), ("unit", u4)):
                    if v and not ex_rec.get(f):
                        ex_rec[f] = v
                continue
            rec = {
                "material_code": item["code"],
                "backbone_code": item.get("backbone_code", ""),
                "description":   item["description"] or synth[:120],
                "category":      item["category"],
                "quantity":      q4,
                "unit":          u4,
                "unit_price":    money4[-2].replace(",", "") if len(money4) >= 2 else "",
                "amount":        money4[-1].replace(",", "") if money4 else "",
                "po_number":     po_number,
                "page":          page,
                "source_file":   source_file,
                "match_type":    match_kind_to_type(item["match_kind"], from_zone=True),
                "zone_label":    zone.get("label", "Line Items"),
                "extracted_at":  datetime.now().isoformat(),
            }
            records.append(rec)
            by_key[key] = rec
            logger.info(f"Zone-wide repair recovered {item['code']}")

    return records


# How far down a page the item-table header may sit. A zone box is cropped to
# the table so the default 8 rows is enough there; a whole page carries the
# address / date / terms blocks first (PO 6-95635-1026: the header is row 15).
PAGE_HEADER_SCAN = 60


def extract_page_line_items(words: list, backbone, regex_patterns: list,
                            po_number: str, page_num: int, source_file: str,
                            max_code_len: int = 24, review: list = None,
                            diag: list = None) -> list[dict]:
    """
    Read a whole page as one line-item table, using its own header row.

    This is the template-free counterpart of the 'line_items' zone, and it
    exists because the line-by-line fallback has no geometry at all. Given only
    the flattened text of

        1  6  SMG  HAF-CIN-2P/EXP  WATER FILTER 2 PACK  0.00  45.26

    there is no way to tell the quantity (6) from the number inside the
    description (2), so the old code took whichever number stood nearest the
    price column and cross-checked it arithmetically - which made BOTH the
    quantity and the unit cost wrong. With the word coordinates and the header
    row every number is resolved by the column it was printed in.

    Returns [] when the page has no header row with a quantity column, so the
    caller can fall back to the existing behaviour unchanged.
    """
    if not words:
        return []
    rows = group_words_into_rows(words)
    if not rows:
        return []
    # Gate: only take over when a real Quantity column was recognised. Without
    # one there is nothing to anchor items on, and the existing line scan is
    # the better tool.
    _idx, colmap, _absorbed, _band = find_header_row(
        rows, max_scan=PAGE_HEADER_SCAN)
    if "quantity" not in colmap:
        return []
    if not any(r in colmap for r in ("unit_price", "amount")):
        return []

    zone = {
        "type":      "line_items",
        "label":     "Page (header row detected)",
        "page":      max(page_num - 1, 0),
        "x0":        min(w["x0"] for w in words),
        "x1":        max(w["x1"] for w in words),
    }
    return parse_line_items_zone(
        zone, words, backbone, regex_patterns, po_number, source_file,
        max_code_len=max_code_len, review=review, diag=diag,
        max_scan=PAGE_HEADER_SCAN, from_zone=False)


# A line that carries a quantity or money is very likely a real item line,
# so loose regex matching is acceptable there even with a backbone loaded.
#
# The money branch needs the integer part widened, not the decimal made
# optional: its old local `\d{1,3}` missed a bare four-digit price
# ('1198.00'), so such a line was not recognised as an item line and loose
# matching was skipped on exactly the layouts that need it most - the same
# drift that truncated _extract_price. The decimal part stays MANDATORY: a
# bare integer is not evidence of money, and relaxing that would make almost
# any numbered line qualify.
_ITEM_HINT = re.compile(
    r"(\b\d{1,5}\s*(?:EA|EACH|PCS?|PC|UNITS?|SET|BOX|CS|CTN)\b)"
    r"|(\$\s*\d)"
    r"|(\b\d+(?:,\d{3})*\.\d{2}\b)",
    re.IGNORECASE
)


def _line_looks_like_item(text: str) -> bool:
    return bool(_ITEM_HINT.search(text or ""))


def align_value_to_row(target_y: float, value_rows: list,
                       tol: float = 6.0) -> str:
    """
    Return the text from value_rows whose y is closest to target_y.

    A value row is claimed by at most one item row. Plain nearest-match let
    two order lines only a few points apart both read the same printed price
    (COLUMN_ALIGNMENT P0-7); the winning row is remembered on the value row
    itself, which is local to one zone parse, so the assignment stays inside
    the table it belongs to. Item rows are offered top to bottom, so the
    nearer of two competing rows keeps the value.
    """
    if not value_rows:
        return ""
    best, best_d, best_row = "", None, None
    for r in value_rows:
        claimed = r.get("_claimed_by")
        if claimed is not None and claimed != target_y:
            continue                    # already belongs to another item row
        d = abs(r["y"] - target_y)
        if best_d is None or d < best_d:
            best, best_d, best_row = r["text"], d, r
    if best_row is None or best_d is None or best_d > tol:
        return ""
    best_row["_claimed_by"] = target_y
    return best


# ──────────────────────────────────────────────
# Zone-based extraction (priority 1 - when a template exists)
# ──────────────────────────────────────────────
def extract_zone_text(pdf_path: str, zones: list[dict],
                      config: dict = None,
                      progress_callback=None) -> list[dict]:
    """
    Extract text only from the defined zones.
    If no text layer exists (scanned PDF), the zone is OCR'd automatically.
    Returns: [{zone_type, zone_label, page, text, tables, ocr}, ...]
    """
    config = config or {}
    zone_results = []
    empty_zones = []      # zones with no text (OCR candidates)

    # The PDF is opened ONCE for every zone. Text, tables and word coordinates
    # are all captured in this single pass; downstream steps (row alignment,
    # line-items parsing) reuse the words instead of reopening the file.
    if PDFPLUMBER_AVAILABLE:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for zi, zone in enumerate(zones):
                    page_idx = zone.get("page", 0)
                    if page_idx >= len(pdf.pages):
                        continue
                    page = pdf.pages[page_idx]
                    try:
                        cropped = page.crop((zone["x0"], zone["y0"],
                                             zone["x1"], zone["y1"]))
                        text   = (cropped.extract_text() or "").strip()
                        tables = cropped.extract_tables() or []
                        words  = cropped.extract_words(
                            use_text_flow=False, keep_blank_chars=False) or []
                    except Exception as e:
                        logger.warning(f"Zone crop error ({zone.get('label')}): {e}")
                        text, tables, words = "", [], []

                    entry = {
                        "zone_idx":   zi,
                        "zone_type":  zone.get("type", "material_code"),
                        "zone_label": zone.get("label", zone.get("type", "")),
                        "page":       page_idx + 1,
                        "text":       text,
                        "tables":     tables,
                        "words":      words,
                        "ocr":        False,
                    }
                    zone_results.append(entry)
                    if not text:
                        empty_zones.append((len(zone_results) - 1, zone))
        except Exception as e:
            logger.warning(f"Zone extraction failed (pdfplumber): {e}")
            empty_zones = [(i, z) for i, z in enumerate(zones)]
            zone_results = [{
                "zone_idx":   i,
                "zone_type":  z.get("type", "material_code"),
                "zone_label": z.get("label", z.get("type", "")),
                "page":       z.get("page", 0) + 1,
                "text": "", "tables": [], "words": [], "ocr": False,
            } for i, z in enumerate(zones)]
    else:
        empty_zones = [(i, z) for i, z in enumerate(zones)]
        zone_results = [{
            "zone_idx":   i,
            "zone_type":  z.get("type", "material_code"),
            "zone_label": z.get("label", z.get("type", "")),
            "page":       z.get("page", 0) + 1,
            "text": "", "tables": [], "words": [], "ocr": False,
        } for i, z in enumerate(zones)]

    # -- Fill empty zones with OCR --
    if empty_zones and config.get("auto_ocr", True) and OCR_MODULE_AVAILABLE:
        if ocr_available():
            logger.info(
                f"{Path(pdf_path).name}: filling {len(empty_zones)} zone(s) "
                f"via OCR ({ocr_engine_name()})"
            )
            lang = config.get("ocr_language", "eng")
            dpi  = config.get("ocr_dpi", OCR_DPI)
            for n, (idx, zone) in enumerate(empty_zones):
                if progress_callback:
                    progress_callback(
                        25 + int(10 * n / max(1, len(empty_zones))),
                        f"Zone OCR: {zone.get('label', zone.get('type'))}"
                    )
                ocr_text = ocr_zone(pdf_path, zone, lang=lang, dpi=dpi)
                if ocr_text:
                    zone_results[idx]["text"] = ocr_text
                    zone_results[idx]["ocr"] = True

    return zone_results


# ──────────────────────────────────────────────
# PO Number zone text cleanup
# ──────────────────────────────────────────────
# Zones often capture the label too; strip labels and keep only the number
PO_LABEL_NOISE = re.compile(
    r"(?i)\b("
    r"purchase\s*order|p\.?\s*o\.?|order|"
    r"number|no\.?|num\.?|"
    r"date|page|phone|fax|tel|telephone|"
    r"vendor|supplier|ship\s*to|bill\s*to|sold\s*to|"
    r"release|revision|rev|customer|account|"
    r"invoice|terms|f\.?o\.?b\.?|"
    r"of|and|the"
    r")\b\s*[:\-#]?"
)

# Dates, phone numbers and bare labels are not PO numbers
PO_BAD_VALUE = re.compile(
    r"^("
    r"\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"        # 5/28/2026
    r"|\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2}"          # 2026-05-28
    r"|\(?\d{3}\)?[\-\s\.]\d{3}[\-\s\.]\d{4}"      # phone number
    r"|\d{1,2}"                                      # 1-2 digit number
    r"|(19|20)\d{2}"                                 # year
    r"|[A-Z]{1,3}"                                   # letters only
    r")$",
    re.IGNORECASE
)


def clean_po_from_zone(text: str) -> str:
    """
    Extract only the PO number from PO Number zone text.
    e.g. "Purchase Order Number\n0736499"  -> "0736499"
        "PO #: 4046792  Date: 6/19/2026"  -> "4046792"
    """
    if not text or not text.strip():
        return ""

    # Pass 1: prefer an explicit PO pattern inside the zone
    explicit = find_po_number(text)
    if explicit and _is_valid_po(explicit) and not PO_BAD_VALUE.match(explicit):
        return explicit

    # Pass 2: strip label noise, then tokenize
    cleaned = PO_LABEL_NOISE.sub(" ", text)
    cleaned = re.sub(r"[:\|#]+", " ", cleaned)

    tokens = re.findall(r"[A-Za-z0-9][\w\-\./]{2,24}", cleaned)

    # Filter candidates: drop labels/dates/phones/short tokens; digits required
    candidates = []
    for t in tokens:
        t = t.strip().rstrip(".,;:")
        if not _is_valid_po(t):
            continue
        if PO_BAD_VALUE.match(t):
            continue
        candidates.append(t)

    if not candidates:
        return ""

    # Prefer tokens with a high digit ratio and reasonable length
    def score(tok: str) -> tuple:
        digits = sum(c.isdigit() for c in tok)
        return (-digits / len(tok), -len(tok))

    candidates.sort(key=score)
    return candidates[0]


def parse_zone_results(zone_results: list[dict], backbone,
                       po_number: str, source_file: str,
                       max_code_len: int = 24,
                       regex_patterns: list = None) -> tuple[list[dict], str]:
    """
    Parse zone texts into records and a PO number.

    Word coordinates captured during zone extraction are reused for row
    alignment - the PDF is never reopened here. `backbone` is the shared
    BackboneIndex instance, not rebuilt per call.
    """
    records = []
    by_key = {}
    extracted_po = po_number

    # -- PO Number zone first, so every record can carry it --
    for zr in zone_results:
        if zr["zone_type"] == "po_number":
            po_candidate = clean_po_from_zone(zr["text"])
            if po_candidate:
                extracted_po = po_candidate
                logger.info(f"Zone PO parsed: '{zr['text'][:60]}' -> '{po_candidate}'")
                break

    # -- Value zones as coordinate rows (from words captured earlier) --
    value_rows = {}      # zone_type -> [{"y","text"}, ...]
    use_rows = not any(zr.get("ocr") for zr in zone_results)
    if use_rows:
        for zr in zone_results:
            vt = zr["zone_type"]
            if vt in ("quantity", "unit_price", "amount", "description") \
                    and vt not in value_rows:
                rows = words_to_rows(zr.get("words") or [])
                if rows:
                    value_rows[vt] = rows

    for zr in zone_results:
        ztype = zr["zone_type"]
        page  = zr["page"]

        if ztype != "material_code":
            continue

        # ---- Build the list of lines to scan ----
        code_rows = []
        if use_rows:
            code_rows = words_to_rows(zr.get("words") or [])

        if not code_rows:
            # Table cells joined per row, else plain text lines
            lines = []
            if zr["tables"]:
                for table in zr["tables"]:
                    for row in (table or []):
                        joined = " ".join(str(c) for c in (row or []) if c).strip()
                        if joined:
                            lines.append(joined)
            if not lines:
                lines = [l for l in zr["text"].splitlines() if l.strip()]
            code_rows = [{"y": float(i), "text": l} for i, l in enumerate(lines)]

        # ---- Extract codes row by row ----
        for row in code_rows:
            allow_pattern = (not backbone.enabled) or _line_looks_like_item(row["text"])
            found = extract_codes_from_line(
                row["text"], backbone, regex_patterns,
                max_len=max_code_len, allow_pattern=allow_pattern
            )
            if not found:
                continue

            # Quantity / price / amount on the same visual row
            qty = unit = price = amount = ""
            desc_extra = ""

            if use_rows and value_rows:
                qtxt = align_value_to_row(row["y"], value_rows.get("quantity", []))
                if qtxt:
                    qty, unit = parse_quantity(qtxt)
                ptxt = align_value_to_row(row["y"], value_rows.get("unit_price", []))
                if ptxt:
                    price = _clean_money(ptxt)
                atxt = align_value_to_row(row["y"], value_rows.get("amount", []))
                if atxt:
                    amount = _clean_money(atxt)
                desc_extra = align_value_to_row(row["y"], value_rows.get("description", []))

            # Fall back to the code line itself
            if not qty:
                qty, u2 = parse_quantity(row["text"])
                unit = unit or u2

            for item in found:
                key = normalize(item["code"])
                existing = by_key.get(key)
                if existing:
                    # Same code seen again (summary line vs detail line): fill gaps
                    for field, val in (("quantity", qty), ("unit", unit),
                                       ("unit_price", price), ("amount", amount)):
                        if val and not existing.get(field):
                            existing[field] = val
                    continue

                rec = {
                    "material_code": item["code"],
                    "backbone_code": item.get("backbone_code", ""),
                    "description":   item["description"] or desc_extra or row["text"][:120],
                    "category":      item["category"],
                    "quantity":      qty,
                    "unit":          unit,
                    "unit_price":    price,
                    "amount":        amount,
                    "po_number":     extracted_po,
                    "page":          page,
                    "source_file":   source_file,
                    "match_type":    match_kind_to_type(item["match_kind"], from_zone=True),
                    "zone_label":    zr["zone_label"],
                    "extracted_at":  datetime.now().isoformat(),
                }
                records.append(rec)
                by_key[key] = rec

    return records, extracted_po


# Money on a PO line. Two-decimal amounts are matched FIRST and as a whole,
# otherwise '1198.0' was split into '119' + '8.0' and both halves published
# as a price and an amount. A trailing single decimal (OCR dropped the last
# digit) is accepted as one token rather than being torn apart.
_MONEY = re.compile(
    r"[-+]?\$?\s*("
    r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"   # 1,198.00 / 9,196.8
    r"|\d+\.\d{2}"                         # 599.00
    r"|\d+\.\d"                            # 1198.0  (OCR lost a digit)
    r"|\d+"                                # 599
    r")")


_FRAG_LEAD = re.compile(r"^\s*([A-Za-z0-9]{1,3})(?=\s|$)")
_LONG_TOK = re.compile(r"[A-Z0-9]{6,}")
_LEAD_QTY = re.compile(r"^\s*(\d{1,4})\s+[A-Za-z]{2,}")

# A plain count standing on its own - not glued to a word, a decimal point or a
# currency sign. "24IN" is a size and "7.4CF" a capacity, so both are refused
# here; a grouped figure ("1,198") is money and the lookahead refuses it too.
# A single trailing comma IS allowed: the CMH scan printed "14, EA" because OCR
# read the column separator as part of the token.
_PLAIN_INT = re.compile(r"(?<![\w.,$])(\d{1,4})(?:,(?!\d))?(?![\d\w.])")
# "300 CFM" is a capacity and "120 V" a voltage - neither is a count. Same
# reasoning as the MEASURE_WORDS guard on the last-resort quantity.
_MEASURE_AFTER = re.compile(r"\s*" + MEASURE_WORDS + r"\b", re.IGNORECASE)


def qty_before_price(line: str, price: str) -> str:
    """
    The count printed immediately to the left of the unit price, or "".

    Every line-item table puts the quantity column just before the price
    column, so on a row that also prints a line number at the far left the
    number next to the price is the count and the leading one is not:

        1 WF45B6300AP SAMSUNG FL/WASHER-PLATINUM 2 $599.00 $1,198.00
        ^ line number                             ^ quantity

    Without this the leading-number rule adopted 1..6 as the quantities of
    PO 95778, which mis-stated every order line. The rule only runs when the
    caller already found a price column,
    so it can never turn a specification figure into a quantity.
    """
    if not line or not price:
        return ""

    # Locate the price as printed (its separators may differ from the digits
    # we carry), then look at what stands in front of it.
    want = price.lstrip("0").replace(",", "")
    pos = -1
    for m in _MONEY.finditer(line):
        if m.group(1).lstrip("0").replace(",", "") == want:
            pos = m.start(1)
            break
    if pos < 0:
        return ""

    head = line[:pos]
    found = ""
    for m in _PLAIN_INT.finditer(head):
        n = m.group(1)
        if not _valid_qty(n):
            continue
        # "MICROWAVE OTR 1.6CF 300 CFM ... 160.0000" - the 300 is a cubic-feet
        # rating sitting in the description, not the count of a table row.
        if _MEASURE_AFTER.match(head, m.end()):
            continue
        found = n
    return found


# ──────────────────────────────────────────────
# Money on a scanned line
# ──────────────────────────────────────────────
# Carbon-copy and duplex scans expose the back of the sheet, so OCR reads every
# amount TWICE: once as printed and once rotated 180 degrees. On PO 246155
# '630.00' also arrives as "00'069", '599.00' as "00:665" / "00665" / "00*665",
# and '1198.0' as "O'8611". A rotated amount is not a value - one of them was
# published as 8,611.00 in the Amount column where 1,198.00 belonged.
#
# Rotation is recognisable without guessing at the digits:
#   * the mirrored decimal point lands to the LEFT of the figures and OCR reads
#     it as an apostrophe, colon or asterisk;
#   * the mirrored trailing '.00' becomes a LEADING '00'. A real amount is
#     never printed as 00665.
_MIRROR_LEAD = "'’`´:*·"


_CURRENCY_WORD = re.compile(r"(?i)^(USD|EUR|KRW|CAD|MXN|DLLS?)\b")


# ---------------------------------------------------------------------------
# Reading a number OCR mangled
# ---------------------------------------------------------------------------
# Two shapes reach us again and again from scanned and DRM-rendered POs, and
# both used to publish a wrong figure:
#
#   (a) a LETTER stands in for a digit inside a money field. Tesseract reads
#       "41l.00" for 411.00, "1,19B.00" for 1,198.00, "S99.00" for 599.00. The
#       strict money pattern cannot see those, so the column was skipped and the
#       quantity next to it was published as the unit price instead.
#   (b) the THOUSANDS SEPARATOR came out as a SPACE. "$ 1 198.00" matched only
#       the trailing "198.00", so a $1,198.00 dryer was priced at $198.00.
#
# Both repairs are deliberately narrow: (a) is only attempted on a token that
# already mixes digits with look-alike letters AND ends in a decimal part, so
# words ("BOX", "SO", "EACH") can never turn into numbers; (b) only triggers on
# the exact signature of a lost separator - a digit, whitespace, then another
# digit that starts a figure with cents.
_OCR_DIGIT_FIX = {"S": "5", "s": "5", "O": "0", "o": "0", "l": "1", "I": "1",
                  "B": "8", "Z": "2", "G": "6", "g": "9", "q": "9"}


def repair_ocr_digits(text: str) -> str:
    """Map letter/digit look-alikes onto digits ('41l.00' -> '411.00')."""
    return "".join(_OCR_DIGIT_FIX.get(ch, ch) for ch in (text or ""))


# A money token that a look-alike corrupted: needs at least one real digit, at
# least one look-alike, and a decimal part (the decimal part is what keeps
# ordinary words out).
_MONEY_LOOKALIKE = re.compile(
    r"(?<![\w$])"
    r"\$?\s*"
    r"(?=[0-9OSolIBZGgq]*[0-9])"          # at least one genuine digit
    r"([0-9OSolIBZGgq][0-9OSolIBZGgq,]*\.[0-9OSolIBZGgq]{1,2})"
    r"(?![\w])"
)
# What the repaired token has to look like. A thousands separator is itself
# strong evidence of money, so "1,198.00" is accepted as it stands; without one,
# two integer digits are required, which keeps a stray "B.12" or "O.5" in a
# spec string from becoming 8.12 / 0.5. A genuine one-digit price still gets
# through when it is printed with its currency sign.
_MONEY_REPAIRED_OK = re.compile(r"^\d{1,3}(?:,\d{3})+\.\d{1,2}$|^\d{2,}\.\d{1,2}$")
_MONEY_REPAIRED_OK_CCY = re.compile(r"^\d+\.\d{1,2}$")

# A digit, a space, then exactly three digits and the cents: the thousands
# separator was lost ("$ 1 198.00", "21 580.56").
#
# The tail must be three digits DIRECTLY followed by the decimal point, with
# no comma. Without that requirement the pattern also matched two SEPARATE
# columns on an OCR'd line - "2  4,916.67" - and closing that gap invented
# 24,916.67, turning a $4,916.67 line into a five-figure one. A real lost
# separator never has a comma in the group that follows the space: once the
# comma survives there is nothing to repair.
_FUSED_THOUSANDS_SIG = re.compile(
    r"(?<![,\d])\d{1,3}[ \t]+(?=\d{3}\.\d{1,2}(?![\d,]))")


def _money_from_lookalikes(line: str) -> list:
    """(position, value) for money tokens that only read once look-alikes map."""
    if not line or not any(ch in line for ch in _OCR_DIGIT_FIX):
        return []
    out = []
    for m in _MONEY_LOOKALIKE.finditer(line):
        raw = m.group(1)
        if not any(ch in _OCR_DIGIT_FIX for ch in raw):
            continue                      # nothing was corrupted - strict pass has it
        start = m.start(1)
        prev = line[start - 1] if start else " "
        end = m.end(1)
        nxt = line[end] if end < len(line) else " "
        # The same guards the strict pass applies, so a repaired token cannot
        # enter where the strict one would have been rejected.
        if prev.isalpha() or prev in _MIRROR_LEAD:
            continue
        if nxt.isalpha() and not _CURRENCY_WORD.match(line[end:]):
            continue
        fixed = repair_ocr_digits(raw)
        has_ccy = line[max(0, start - 2):start].rstrip().endswith("$")
        if not (_MONEY_REPAIRED_OK.match(fixed)
                or (has_ccy and _MONEY_REPAIRED_OK_CCY.match(fixed))):
            continue
        fixed = fixed.replace(",", "")
        if fixed.startswith("00") and not fixed.startswith("00."):
            continue
        out.append((start, fixed))
    return out


def _money_pass(line: str, cents_only: bool) -> list:
    """One reading of a line: (position, value) pairs, strict then repaired."""
    out = []
    for m in _MONEY.finditer(line):
        val = m.group(1)
        start = m.start(1)
        prev = line[start - 1] if start else " "
        end = m.end(1)
        nxt = line[end] if end < len(line) else " "

        # Glued to a word: 'PLATIN13970' is description text, not a price.
        if prev.isalpha():
            continue
        # A unit or spec suffix follows the figure: '2.1CF', '30IN', '120V'.
        # A real amount is followed by whitespace or a column break; only a
        # currency word may legitimately trail it.
        if nxt.isalpha() and not _CURRENCY_WORD.match(line[end:]):
            continue
        # Rotated: mirrored decimal separator sits in front of the digits.
        if prev in _MIRROR_LEAD:
            continue
        digits = val.replace(",", "")
        # Rotated: mirrored '.00' became a leading '00'. This also discards the
        # zero-padded line number ('0008'), which is not money either.
        if digits.startswith("00") and not digits.startswith("00."):
            continue
        # The head of a thousands-separated figure whose group OCR corrupted
        # ("1,19B.00"): this bare '1' is a fragment of that one number, not a
        # value of its own, and publishing it as the unit price is exactly how a
        # $1,198.00 line came out at $1.00.
        if val.isdigit() and nxt == ",":
            continue
        if cents_only and not (re.search(r"\.\d{2}$", val) or "," in val):
            continue
        out.append((start, digits))

    # A repaired token and a strict one can sit on the same line, so the two
    # readings are merged back into left-to-right order. Duplicates are kept:
    # a single-unit line really does print the same figure twice.
    return sorted(out + _money_from_lookalikes(line), key=lambda t: t[0])


def _fused_reading_is_better(out: list, fused: list) -> bool:
    """
    Decide between the two readings of a line with a lost thousands separator.

    The strict reading of "$ 1 198.00" is the pair (198.00, 1198.00) - it saw
    the tail of the number as a figure of its own. The fused reading sees
    (1198.00, 1198.00). Three signals pick the fused one, and every one of them
    is evidence rather than preference:

      * the strict reading contains a value that is a SUFFIX of a fused value
        and shorter than it - literally the truncation;
      * the fused reading's own last two values agree, which is how a
        single-unit line prints (price == amount).
    """
    # A pair is the least a reading must offer to be worth anything: the engine
    # needs a unit price and an amount. Comparing the two readings by how MANY
    # values they hold would be wrong - the strict pass invents extra ones out
    # of the digits it mistook for figures ("$ 1 198.00" reads as 1, 1, 198.00,
    # 1198.00), so more values is not more correct.
    if len(fused) < 2:
        return False
    if any(o and f.endswith(o) and len(f) > len(o) for o in out for f in fused):
        return True
    return fused[-1] == fused[-2]


def money_tokens(line: str, cents_only: bool = False) -> list:
    """
    Amounts on one line WITH their character offset: [(pos, value), ...].

    Same reading as money_values(), but the caller keeps the position so it can
    look at what is around a figure - a currency mark, a unit word - before
    trusting it. See _without_qty_echo().
    """
    if not line:
        return []
    out = _money_pass(line, cents_only)
    if _FUSED_THOUSANDS_SIG.search(line):
        fused = _money_pass(_collapse_digit_gaps(line), cents_only)
        if _fused_reading_is_better([v for _pos, v in out],
                                    [v for _pos, v in fused]):
            out = fused
    return out


def _values(tokens: list) -> list:
    """The values of (position, value) pairs, in printed order."""
    return [v for _pos, v in tokens or []]


def _without_qty_echo(tokens: list, line: str, qty: str) -> list:
    """
    Drop the figures that are really this line's own QUANTITY.

    Chafin/CMH GRO105A0 prints a rebate line with no price at all:

        900006356 3000 Refrigerator RS27T5201SR (Samsung) 1.00 ea

    and the cost-column search read "1.00" - the count, written with decimals
    because the column is decimal - as a price: the line went out at 1.00 x 1
    and the order came out at 51.00 against a printed 50.00. A count is never
    money, so a figure that EQUALS the quantity is dropped unless a currency
    mark sits right before it ("$1.00 ea" is a price).
    """
    if not tokens or not qty:
        return tokens
    try:
        q = float(str(qty).replace(",", ""))
    except ValueError:
        return tokens
    keep = []
    for pos, val in tokens:
        try:
            if float(str(val).replace(",", "")) == q:
                head = line[:pos].rstrip()
                if not head or head[-1] not in "$£€":
                    continue
        except ValueError:
            pass
        keep.append((pos, val))
    return keep


def money_values(line: str, cents_only: bool = False) -> list:
    """
    Amounts printed on one line, with rotated and glued OCR ghosts removed.

    cents_only keeps only values written with two decimal places or a thousands
    separator - the way a price is actually printed. Use it when searching a
    NEIGHBOURING line, where a specification figure is otherwise mistaken for a
    price: '2.1CF/LEDDIS/AUTCONN/GLSCNT' describes a 2.1 cu.ft. microwave, and
    reading 2.1 as the unit cost turned a $263.20 item into $2.10.

    A line whose thousands separator came out as a space is re-read with the gap
    closed ("$ 1 198.00" -> "$ 1198.00"), because the strict pass would otherwise
    publish the trailing 198.00 as the price. That re-read is only attempted
    when the lost-separator signature is present.
    """
    return [v for _pos, v in money_tokens(line, cents_only)]


def _collapse_digit_gaps(text: str) -> str:
    """Close a thousands separator that OCR rendered as a space."""
    return re.sub(r"(?<=\d)[ \t]+(?=\d)", "", text or "")


def normalize_output_codes(records: list, backbone) -> int:
    """
    Last safety net before de-duplication: publish the backbone's spelling.

    Several parsing paths reach the output, and one of them let an OCR misread
    through verbatim - PO 246155 printed WF4SB6300AP (5 read as S) and that is
    what reached the Excel file, flagged 'pattern' as though the code were
    unknown. Rather than hunting every path, each finished record is resolved
    against the backbone one final time here.

    Only backbone-confirmed rewrites happen, so a genuinely unknown code is
    left exactly as extracted and still faces the accuracy gate.
    """
    if not backbone or not backbone.enabled:
        return 0
    n = 0
    for r in records or []:
        code = r.get("material_code") or ""
        bb = r.get("backbone_code") or ""
        if not bb:
            matched, kind = backbone.lookup(code)
            if not matched:
                continue
            bb = matched
            r["backbone_code"] = matched
            from_zone = "zone" in (r.get("match_type") or "")
            r["match_type"] = match_kind_to_type(kind, from_zone=from_zone)
            info = backbone.info(matched) or {}
            if info.get("category") and not r.get("category"):
                r["category"] = info["category"]
        printed = backbone.printed_form(bb, code)
        if printed and printed != code:
            r["material_code"] = printed
            n += 1
    return n



def repair_wrapped_codes(lines: list, backbone) -> list:
    """
    Narrow MODEL columns wrap a code across printed lines:

        DW80CG4051S
        24 SAMSU UPC: 887276772905 ... $9,196.80
        R

    An orphan fragment line ('R') is fused back onto a long token found 1-2
    lines above - but only when the fused form matches the backbone list, so
    this can never invent a code. The fused code is attached to the nearby
    quantity-bearing line so code and quantity land on the same line.
    """
    if not backbone or not backbone.enabled:
        return lines

    # NON-DESTRUCTIVE: original lines are never edited. A repaired line is
    # APPENDED instead. Rewriting the source lines risked destroying codes
    # that were already being read correctly, which showed up as a drop in
    # overall extraction rate.
    out = list(lines)
    extra = []
    fused_seen = set()

    # Pass A: the code is split WITHIN one line by a stray column character:
    #     "DW80CG4021S V"      -> DW80CG4021S + (R from a later line)
    #     "ME21DG6300S"        -> handled by pass B
    # Here we join a long token with a following 1-2 char token on the SAME
    # line, keeping the result only if the backbone confirms it.
    for ln in lines:
        toks = re.findall(r"[A-Za-z0-9]+", (ln or "").upper())
        for i in range(len(toks) - 1):
            a, b = toks[i], toks[i + 1]
            if len(a) < 6 or not (1 <= len(b) <= 2):
                continue
            # The trailing piece of a wrapped code is a LETTER fragment
            # ("DW80CG4021S" + "V"). A digit here is the order quantity or a
            # line number - fusing it invented codes like 'DVE45T6000W1'.
            if not b.isalpha():
                continue
            # Skip when the first token is already a complete listed code:
            # nothing is wrapped, the next token is a separate field.
            if backbone.lookup(a)[0]:
                continue
            code, _k = backbone.lookup(a + b)
            if code and normalize(a + b) not in fused_seen:
                qn = _LEAD_QTY.match(ln or "")
                money = re.findall(r"\d[\d,]*\.\d{2}", ln or "")
                synth = a + b
                if qn:
                    synth = f"{qn.group(1)} EA {synth}"
                if money:
                    synth += " " + " ".join(money[-2:])
                extra.append(synth)
                fused_seen.add(normalize(a + b))
                logger.info(f"In-line split code repaired: {a}+{b} -> {a+b}")

    # Pass B: the code is split ACROSS lines - a short orphan fragment sits on
    # its own line below the code.
    for k, ln in enumerate(lines):
        m = _FRAG_LEAD.match(ln or "")
        if not m:
            continue
        frag = m.group(1).upper()
        if frag.isdigit():
            continue

        # A short leading token is a wrapped FRAGMENT only when the rest of
        # its line does not start a new item. Two real shapes must both work:
        #
        #   "R"                        <- pure fragment
        #   "R UPC: 887276772882"      <- fragment plus leftover column text
        #   "B - (ME21DG6300SRAA) 2 EA" <- NOT a fragment: new item label
        #
        # So the test is whether the rest contains another CODE-like token
        # (letters+digits mixed, or a parenthesised code), not merely any
        # long token: 'UPC: 887276772882' is digits only and harmless.
        rest = (ln or "")[m.end():]
        if "(" in rest:
            continue
        if any(re.search(r"[A-Z]", t) and re.search(r"\d", t)
               for t in _LONG_TOK.findall(rest.upper())):
            continue

        done = False
        for j in (k - 1, k - 2):
            if j < 0 or done:
                break
            toks = _LONG_TOK.findall((lines[j] or "").upper())
            for t1 in reversed(toks[-3:]):
                # A token that already matches on its own is not truncated,
                # so nothing should be appended to it.
                if backbone.lookup(t1)[0]:
                    continue
                code, _kind = backbone.lookup(t1 + frag)
                if not code:
                    continue
                fused = t1 + frag
                if normalize(fused) in fused_seen:
                    done = True
                    break

                # Build a synthetic line in a shape the parser reads reliably:
                #   "<qty> EA <code> <money> <money>"
                # Relying on the raw context line was fragile because its
                # quantity is not always in a recognised position.
                # The window may reach ANOTHER item's row (k-2 .. k+2), so a
                # line that carries its own backbone-confirmed code is skipped:
                # its quantity and money belong to that item, not to this one.
                qty_num, money = "", []
                for t in range(max(0, k - 2), min(len(lines), k + 3)):
                    src = lines[t] or ""
                    if t != j and any(
                            normalize(hit[0]) not in (normalize(t1),
                                                      normalize(t1 + frag))
                            for hit in backbone.scan_line(src)):
                        continue
                    if not qty_num:
                        mq = _LEAD_QTY.match(src)
                        if mq:
                            qty_num = mq.group(1)
                    if not money:
                        money = re.findall(r"\d[\d,]*\.\d{2}", src)
                synth = fused
                if qty_num:
                    synth = f"{qty_num} EA {synth}"
                if money:
                    synth += " " + " ".join(money[-2:])
                extra.append(synth)
                fused_seen.add(normalize(fused))
                logger.info(f"Wrapped code repaired: '{t1}' + '{frag}' -> {fused}")
                done = True
                break

    return out + extra


# ---------------------------------------------------------------------------
# Lines that must never supply a cost to an item row
# ---------------------------------------------------------------------------
# A PO prints its own totals a few lines under the last item, and they are the
# most tempting wrong answer in the document: on a page whose item rows lost
# their cost columns, "Sub Total  $ 6,316.80" sits close enough to be picked up
# as the unit price. Everything below is a footer, not an item.
_FOOTER_STOP = re.compile(
    r"(?i)^\s*(?:"
    r"total|sub\s*-?\s*total|subtotal|net\s+order|sales\s+tax|tax\b|"
    r"grand\s+total|balance|amount\s+due|remit|currency|freight|"
    r"item\s+count|terms|page\b|phone|fax|please|important|"
    r"the\s+work|by\s*:|company|authorized|purchase\s+order|procurement|"
    r"purchased|vendor|ship\s*to|bill\s*to|invoice\s+total|order\s+total"
    r")"
)
_FOOTER_URL = re.compile(r"(https?://|\S+\.(?:com|net|org)\b)", re.I)
# OCR noise such as "a nn 2 ee en" - runs of one- and two-character tokens.
_OCR_NOISE_LINE = re.compile(r"^([A-Za-z0-9]{1,2}\s+){2,}")
# How far a cost column may sit from its code (see enrich_money_from_pages).
_MONEY_NEIGHBOUR_SPAN = 4


def is_footer_line(line: str) -> bool:
    """A total / legal / address line - never a source of an item's cost."""
    s = (line or "").strip()
    if not s:
        return False
    if _FOOTER_STOP.match(s) or _FOOTER_URL.search(s):
        return True
    # The noise test is deliberately narrow: an item row can also open with two
    # short tokens ("2 EA $ 411.00 $ 822.00"), so a line that carries money or a
    # code-length token is an item row no matter how short its first words are.
    if _OCR_NOISE_LINE.match(s):
        return not (re.search(r"\d[\d,]*\.\d{2}", s)
                    or re.search(r"[A-Z0-9]{6,}", s.upper()))
    return False


def _money_line_score(values: list) -> int:
    """
    How much a neighbouring line looks like the cost columns of an item row.

    2 = at least two amounts, i.e. the shape of a cost row.
    1 = a single amount - could be a price, could be anything.
    """
    if not values:
        return 0
    return 2 if len(values) >= 2 else 1


def _carries_other_code(line: str, mine: set, backbone) -> bool:
    """True when `line` names a listed code that is not this record's."""
    if not line or backbone is None or not backbone.enabled:
        return False
    try:
        hits = extract_codes_from_line(line, backbone, [], max_len=40,
                                      allow_pattern=False)
    except Exception:                                   # pragma: no cover
        return False
    for h in hits:
        if not h.get("backbone_code"):
            continue
        key = normalize(h["code"])
        if key and key not in mine:
            return True
    return False


def _money_num(value) -> float:
    """
    A printed figure as a float, or None when it is not one.

    Handles the shapes the engine hands around: "1,060.0000", "$399.64",
    an empty string, and the trailing-minus an OCR rotation leaves behind.
    """
    if value in (None, ""):
        return None
    s = str(value).replace("$", "").replace("£", "").replace("€", "")
    s = s.replace(",", "").strip()
    if s.endswith("-") and not s.startswith("-"):
        s = "-" + s[:-1]
    try:
        return float(s)
    except ValueError:
        return None


def _money_tolerance(amount: float) -> float:
    """
    How far a printed amount may sit from qty x price and still be that figure.

    Prices print to the cent, but a scan drops trailing zeros ("21580.5" for
    21580.56), so allow 0.2% as well as two cents. Measured over the 34 real
    POs in data_cache this separates every genuine mis-read from every correct
    line with no overlap: the wrong ones start at 20% relative error.
    """
    return max(0.02, abs(amount) * 0.002)


def _assign_money(money: list, qty) -> tuple:
    """
    Decide which printed figures are the unit price and the extended amount.

    A purchase-order line satisfies  qty x unit price == amount. When a line
    prints more than two figures and the conventional "last two" reading is
    IMPOSSIBLE, the pair that satisfies that identity IS the price and the
    amount. This only ASSIGNS values the document already printed - nothing
    is computed, rounded or invented - so it stays inside the "values pass
    through exactly as printed" rule (HANDOVER 2.2). It chooses which printed
    figure goes in which column, which is not arithmetic.

    Why it matters: reading the last two tokens positionally published

        ME90H1780R   qty 54   unit price 21580.5   amount 54

    on 'Scanned from a Xerox Multifunction Printer.pdf' - the extended total
    landed in the unit-price column and a trailing count landed in the amount
    column, so the line reached the Order Upload priced at 21,580.50 instead
    of 399.64.

    The override is deliberately narrow. It fires ONLY when the conventional
    reading cannot be right:

        qty > 1  and  amount <= unit price

    because with two or more units the extended cost is necessarily greater
    than the unit cost. A single-unit line (price == amount) or a row whose
    amount column is simply absent is left exactly as it was - those are the
    cases devtools pins as the contract.

    Returns (price, amount) as printed strings, or None to keep the caller's
    positional reading.
    """
    vals = [v for v in (money or []) if v not in (None, "")]
    q = _money_num(qty)
    if len(vals) < 2 or not q or q <= 1:
        return None

    nums = [_money_num(v) for v in vals]
    p0, a0 = nums[-2], nums[-1]
    if not (p0 and a0 and p0 > 0 and a0 > 0):
        return None
    # A multi-unit row whose "amount" is not above its "unit price" is not
    # holding that pair at all. Fall through to the identity.
    if a0 > p0:
        return None

    best = None
    for i in range(len(vals)):
        for j in range(i + 1, len(vals)):
            p, a = nums[i], nums[j]
            if not (p and a and p > 0 and a > 0):
                continue
            if a <= p:            # extended cost exceeds unit cost
                continue
            err = abs(q * p - a)
            if err > _money_tolerance(a):
                continue
            key = (err, j, i)
            if best is None or key < best[0]:
                best = (key, vals[i], vals[j])
    return (best[1], best[2]) if best else None


def enrich_money_from_pages(records: list, pages: list, backbone) -> int:
    """
    Fill in Unit Price / Amount from the full page text.

    A Line Items box drawn around the code and quantity columns usually stops
    short of the money columns further right, so those values are missing even
    though the extraction itself was correct. Rather than forcing the user to
    redraw every template, the line containing each code is located in the
    page text and its money tokens are read from there.

    Convention on a PO line:  ... <unit price> <extended cost>
    so the LAST two money tokens are unit price and amount respectively. No
    arithmetic is applied: a value is published only where the document
    actually printed one.

    Returns the number of records enriched.
    """
    if not records or not pages:
        return 0

    # code -> line(s) containing it, per page
    by_page = {}
    for p in pages:
        by_page[p["page_num"]] = [l for l in (p.get("text") or "").splitlines()
                                  if l.strip()]

    filled = 0
    for rec in records:
        if rec.get("unit_price") and rec.get("amount"):
            continue

        code_norm = normalize(rec.get("material_code", ""))
        bb_norm = normalize(rec.get("backbone_code", ""))
        bases = {code_norm, bb_norm}
        bb = str(rec.get("backbone_code") or "")
        if "/" in bb:
            bases.add(normalize(bb.split("/", 1)[0]))
        bases.discard("")
        if not bases:
            continue

        # A code recovered from a WRAPPED line never appears whole in the page
        # text ("DW80CG4051S" on one line, "R" on another), so searching for
        # the full code finds nothing. Also look for the leading portion,
        # which is how the document actually prints it.
        stems = set()
        for b in list(bases):
            if len(b) >= 8:
                stems.add(b[:-1])          # code minus the wrapped character
                stems.add(b[:-2])
        stems = {s for s in stems if len(s) >= 7}

        lines = by_page.get(rec.get("page")) or []
        if not lines:
            # fall back to any page
            lines = [l for ls in by_page.values() for l in ls]

        for idx, line in enumerate(lines):
            ln = normalize(line)
            hit_full = any(b in ln for b in bases)
            hit_stem = (not hit_full) and any(s in ln for s in stems)
            if not (hit_full or hit_stem):
                continue

            money = _values(_without_qty_echo(
                money_tokens(line, cents_only=True), line,
                rec.get("quantity")))

            # The money often sits on a NEIGHBOURING line: many POs print the
            # code on its own line and the qty/price on the line above or
            # below (2170541 prints it above, BM736499 below).
            #
            # Every neighbour is scored rather than taking the nearest one that
            # happens to contain a number. On BM736499 the line above the code
            # is the spec text '2.1CF/LEDDIS/...' while the line below carries
            # the cost row shape ('$263.20 $263.20 $6,316.80') - two amounts
            # beat one, and the nearest such line wins.
            if not money:
                best = None
                # Walk outwards from the code, nearest first. A footer line
                # stops that direction: the PO's own totals sit below the item
                # table, and reading one as this row's cost is exactly the
                # mistake this guard exists for.
                cands = []
                for direction in (1, -1):
                    for k in range(1, _MONEY_NEIGHBOUR_SPAN + 1):
                        j = idx + direction * k
                        if not (0 <= j < len(lines)):
                            break
                        cand_line = lines[j]
                        if is_footer_line(cand_line):
                            break
                        # A line that carries a DIFFERENT item's code belongs
                        # to that item - its money is not this one's. On Chafin
                        # GRO105A0 the rebate line prints no price at all, and
                        # the search took the next line's "50.00 50.00" (the
                        # installation charge) as the fridge's cost.
                        if backbone is not None and backbone.enabled \
                                and _carries_other_code(cand_line, bases,
                                                       backbone):
                            break
                        cands.append((k, direction, cand_line))
                for _k, _dir, cand_line in sorted(cands, key=lambda t: t[0]):
                    m2 = _values(_without_qty_echo(
                        money_tokens(cand_line, cents_only=True), cand_line,
                        rec.get("quantity")))
                    if not m2:
                        continue
                    score = _money_line_score(m2)
                    if best is None or score > best[0]:
                        best = (score, m2, cand_line)
                    if score >= 2:      # a cost-row shape - stop looking
                        break
                if best:
                    money, line = best[1], best[2]

            if not money:
                continue

            qty = str(rec.get("quantity") or "").strip()
            if not qty:
                # The neighbouring line usually carries the quantity too
                q2, _u = parse_quantity(line)
                if q2:
                    qty = q2
                    rec["quantity"] = q2
            price = amount = ""

            pair = _assign_money(money, qty) or _price_amount_by_shape(
                line, money, qty)
            if pair:
                price, amount = pair
            elif len(money) >= 2:
                # Convention on a PO line: ... <unit price> <extended cost>,
                # so the LAST two money tokens are the pair. Only reached
                # when no pair satisfies qty x price == amount, i.e. when the
                # amount column is absent - see _assign_money().
                price, amount = money[-2], money[-1]
            else:
                only = money[0]
                if qty.isdigit() and int(qty) == 1:
                    price = amount = only
                else:
                    price = only

            if price and not rec.get("unit_price") \
                    and _money_num(price) not in (None, 0.0):
                # 0.00 is not a price on a purchase order - a row that prints
                # a discount column beside the price must not publish the
                # zero. Same rule as _assign_money's caller: left empty and
                # flagged rather than guessed.
                rec["unit_price"] = price
            if amount and not rec.get("amount"):
                rec["amount"] = amount

            if rec.get("unit_price") or rec.get("amount"):
                filled += 1
            break

    return filled


def _flag_lost_leading_digit(records: list, review_items: list = None) -> list:
    """
    Report a unit price that OCR read with its first digit missing.

    SKM_C751i26090906450 prints "1060.0000" and OCR returned "060.00" - a
    price that begins with a zero is implausible for an appliance, and the
    line's own printed amount (16,960.00 = 16 x 1,060.00) says what the digit
    was.

    The value is NOT changed: the engine publishes what it read (section 2.2 -
    no arithmetic repair). The line is marked `needs_review`, listed for
    review so it reaches the Code Learning screen rather than only the
    console, and the note names the candidate, so the row is checked instead
    of being trusted. Only a price starting with "0" is considered, and only
    when exactly one leading digit reproduces the printed amount.
    """
    notes = []
    for r in records or []:
        price = str(r.get("unit_price") or "").strip().replace(",", "")
        if not price.startswith("0") or price.startswith("0."):
            continue
        qty = str(r.get("quantity") or "").strip()
        amount = str(r.get("amount") or "").strip().replace(",", "")
        if not (qty.isdigit() and amount):
            continue
        try:
            q, amt = float(qty), float(amount)
        except ValueError:
            continue
        if not q or not amt:
            continue
        fits = [d for d in "123456789"
                if abs(float(d + price) * q - amt) < 0.005]
        if len(fits) != 1:
            continue
        r["needs_review"] = True
        note = (f"{r.get('material_code') or '?'}: unit price read as {price} - a "
                f"price starting with 0; {fits[0]}{price} would make the line add "
                f"up ({qty} x {fits[0]}{price} = {amount}). Left as printed - "
                f"check it.")
        notes.append(note)
        if review_items is not None:
            review_items.append({
                "candidate":   r.get("material_code") or "?",
                "score":       _mt_score(r.get("match_type")),
                "match":       r.get("match_type", ""),
                "reason":      f"Unit price read as {price} - a price starting "
                               f"with 0. {fits[0]}{price} would make the line "
                               f"add up. Left as printed.",
                "context":     (r.get("description") or "")[:160],
                "page":        r.get("page"),
                "source_file": r.get("source_file") or "",
                "po_number":   r.get("po_number") or "",
            })
    return notes


def _check_line_arithmetic(records: list, review_items: list,
                           source_file: str, doc_po: str) -> list:
    """
    Report every line whose own printed figures disagree with each other.

    A PO line is a multiplication:  qty x unit price == amount. That identity
    is not a heuristic - it is what the document printed - so a line that
    violates it has at least one mis-read field. The engine cannot say WHICH
    field without doing arithmetic, and arithmetic repair is out of scope
    (HANDOVER 2.2: values pass through exactly as printed). So the values are
    left exactly as read and the line is flagged for a human.

    A wrong price in the Order Upload costs the customer more than a missing
    one does - the same rule the material-code gate follows ("never guess into
    the output"). Silently publishing a line that does not add up is the
    guess: the column assignment was wrong and nothing said so.

    Measured over the 34 real POs in data_cache, 96 of 387 complete lines
    violated the identity and not one of them was rounding or tax - the
    relative errors run from 20% to 8,400%. _assign_money() now repairs the
    determinable ones at assignment time; what reaches here is genuinely
    ambiguous and needs a person.

    Returns the diagnostic notes, for the caller to append to zone_diag.
    """
    notes = []
    for r in records or []:
        q = _money_num(r.get("quantity"))
        p = _money_num(r.get("unit_price"))
        a = _money_num(r.get("amount"))
        if not (q and p and a):
            continue
        if q <= 0 or p <= 0 or a <= 0:
            continue
        if abs(q * p - a) <= _money_tolerance(a):
            continue
        code = r.get("material_code") or "?"
        detail = f"{q:g} x {p:g} = {q * p:g}, but the amount column reads {a:g}"
        r["needs_review"] = True
        r["math_error"] = detail
        review_items.append({
            "candidate":   code,
            "score":       _mt_score(r.get("match_type")),
            "match":       r.get("match_type", ""),
            "reason":      f"Line does not add up: {detail}",
            "context":     (r.get("description") or "")[:160],
            "page":        r.get("page"),
            "source_file": source_file,
            "po_number":   r.get("po_number") or doc_po,
        })
        notes.append(f"{code}: line does not add up - {detail}. Check the "
                     f"quantity and unit price before uploading.")
    return notes


def _mt_score(match_type: str) -> int:
    """Confidence score for a stored match_type string (for review display)."""
    mt = match_type or ""
    if "reference" in mt:
        return KIND_RANK.get("exact", 100)
    if "paren" in mt:
        return KIND_RANK.get("paren", 50)
    if "zone" in mt:
        return 30
    return KIND_RANK.get("pattern", 10)


def _dedupe_review(items: list) -> list:
    """
    Collapse duplicate review entries. The same candidate is often reported
    twice (per-row scan and joined-block scan) - one entry per
    (candidate, page, reason) is enough for a human reviewer.
    """
    seen, out = set(), []
    for it in items:
        key = (normalize(it.get("candidate", "")), it.get("page"),
               it.get("reason", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _clean_money(text: str) -> str:
    """Pull a numeric amount out of a currency cell, ignoring rotated ghosts."""
    if not text:
        return ""
    vals = money_values(text)
    return vals[0] if vals else ""


# ──────────────────────────────────────────────
# Backbone-driven whole-page extraction (no zone template)
# ──────────────────────────────────────────────
def _unglued_line_variants(lines: list, backbone) -> list:
    """
    Extra candidates with a printed line number split off the model code it
    is printed against.

    RapidOCR merges '1WF45B6300AP' into a single token where the document
    prints '1  WF45B6300AP', so the code carries a leading digit and neither
    the patterns nor the backbone can find it. PO 95778 lost four of its six
    order lines that way (WF45B6300AP, NE63A6751SS, DVE45B6300P, WE402NP)
    and the order came out 4,051.00 short of its printed total.

    Only ADDITIONAL candidates are returned - the caller keeps the original
    lines, so nothing that used to match stops matching. A variant is kept
    only when the unglued remainder resolves against the backbone, which is
    what makes this safe: the code list decides where the number ends, not a
    guess about digit counts. A variant is never invented from a line whose
    tail is not a listed code.
    """
    out = []
    if not lines or backbone is None or not getattr(backbone, "enabled", False):
        return out
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        m = re.match(r"(\d{1,4})(?=[A-Za-z])", stripped)
        if not m:
            continue
        for n in range(1, len(m.group(1)) + 1):
            variant = line[:indent + n] + " " + line[indent + n:]
            hits = extract_codes_from_line(variant, backbone, [],
                                           max_len=40, allow_pattern=False)
            if any(h.get("backbone_code") for h in hits):
                out.append(variant)
                break
    return out


def extract_lines_with_backbone(text: str, tables: list,
                                backbone, regex_patterns: list,
                                po_number: str, page_num: int,
                                source_file: str,
                                max_code_len: int = 24,
                                review: list = None) -> list[dict]:
    """
    Scan a page line by line, matching each line against the backbone list and
    parenthesized code tokens. Quantity found on the same line is attached.

    This is the no-template counterpart of parse_zone_results.
    """
    if review is None:
        review = []
    records = []
    by_key = {}          # normalized code -> record (for enrichment)

    # Table rows first (each row joined so code and qty stay together)
    lines = []
    for table in (tables or []):
        for row in (table or []):
            joined = " ".join(str(c) for c in (row or []) if c).strip()
            if joined:
                lines.append(joined)

    # Then plain text lines
    # Plain text lines, with a figure split behind a currency mark rejoined
    # first ("$ 5 7.11" -> "$ 57.11"): the price reader must see the figure
    # the document actually printed.
    raw_lines = [_fuse_split_figures(l) for l in (text or "").splitlines()
                 if l.strip()]
    # Fuse codes that a narrow MODEL column wrapped across printed lines
    # (backbone-confirmed only - cannot invent codes)
    raw_lines = repair_wrapped_codes(raw_lines, backbone)
    lines += raw_lines
    # Plus a variant of each line with a printed line number split off the
    # code it was printed against ("1WF45B6300AP" -> "1 WF45B6300AP"), which
    # is how a scan reads that row. Backbone-confirmed only. Added as extra
    # candidates so `raw_lines` stays intact for the pairing loop below.
    lines += _unglued_line_variants(raw_lines, backbone)

    # Plus each adjacent pair joined, so codes broken across two printed lines
    # ("(Model E3-" / "DW) - Install") are still recovered.
    for a, b in zip(raw_lines, raw_lines[1:]):
        if a.rstrip().endswith("-") or "(" in a and ")" not in a:
            lines.append(f"{a} {b}")

    # Regex fallback policy:
    #   - no backbone list  -> always allowed
    #   - backbone loaded   -> allowed only on lines that carry a quantity or
    #                          money value, i.e. real item lines. This keeps
    #                          new codes discoverable while still rejecting
    #                          PO numbers, ZIP codes and header text.
    for line in lines:
        allow_pattern = (not backbone.enabled) or _line_looks_like_item(line)
        found = extract_codes_from_line(
            line, backbone, regex_patterns,
            max_len=max_code_len, allow_pattern=allow_pattern
        )
        if not found:
            continue

        qty, unit = parse_quantity(line)
        # Rotated OCR ghosts are stripped first: taking the last two raw
        # numbers made "O'8611" (upside-down 1198.0) the extended cost.
        raw_money = money_values(line)

        # The quantity column sits immediately left of the price column. This
        # must be tried BEFORE the leading-number rule below: a row that starts
        # with a line number ("1 WF45B6300AP ... 2 $599.00") has two candidate
        # numbers and only the one beside the price is the count.
        if not qty and len(raw_money) >= 2 \
                and any(c.get("backbone_code") for c in found):
            q2 = qty_before_price(line, raw_money[-2])
            if q2:
                qty = q2

        # Leading-count layouts ("24 SAMSU DW80CG4051SR UPC: ...") carry the
        # quantity as the first token with no EA marker. Adopt it only when a
        # backbone-confirmed code sits on the same line - never for free text.
        if not qty and any(c.get("backbone_code") for c in found):
            m = _LEAD_QTY.match(line)
            if m:
                qty = m.group(1)

        # With the quantity known, drop the figures that are just this row's
        # own count echoed into a money column. On 'Scanned from a Xerox
        # Multifunction Printer.pdf' the trailing "54" was the quantity, and
        # reading it as the amount pushed the extended total (21,580.50) into
        # the unit-price column - the line went out priced at 21,580.50
        # instead of 399.64. A count is never money.
        money = _values(_without_qty_echo(money_tokens(line), line, qty))

        # Which printed figures are the unit price and the extended amount.
        # When the conventional "last two" reading is impossible on a
        # multi-unit row,  qty x price == amount  picks the pair instead -
        # see _assign_money(). A printed SHAPE is consulted before the
        # positional rule, so the flat-text DRM route and the PDF route agree
        # on the same line. See _price_amount_by_shape().
        price = amount = ""
        pair = _assign_money(money, qty) or _price_amount_by_shape(
            line, money, qty)
        if pair:
            price, amount = pair
        elif len(money) >= 2:
            price, amount = money[-2], money[-1]
        elif len(money) == 1:
            amount = money[0]

        # 0.00 is not a price on a purchase order. A row that prints its
        # discount column beside the price ("... WATER FILTER 0.00 45.26")
        # must not publish that zero as the unit price: with no currency mark
        # and no column header to say which figure is which, the positional
        # reading lands on the discount. The price is left EMPTY and the row
        # is flagged - the same rule the accuracy gate applies elsewhere. A
        # wrong price in the Order Upload costs the customer more than a
        # missing one does, and `prepare_lines` already reports a missing cost
        # by name.
        if price not in (None, ""):
            try:
                if float(str(price).replace(",", "")) == 0.0:
                    price = ""
                    review.append({
                        "candidate":   None,
                        "score":       0,
                        "match":       "line",
                        "reason":      ("A zero was read where the unit price "
                                        "should be - the row prints a 0.00 "
                                        "discount column. Price left empty."),
                        "context":     line.strip()[:160],
                        "page":        page_num,
                        "source_file": source_file,
                        "po_number":   po_number,
                    })
            except ValueError:
                pass

        # The PO's own line number, when the layout prints one at the start of
        # the row ("0006  12816  2 EA SSW  ..."). Used to tell two order lines
        # of the SAME model apart.
        po_line = ""
        mln = _PO_LINE_NO.match(line)
        if mln:
            po_line = mln.group(1)

        # Ghost filter, applied consistently whether or not a quantity was
        # found on this line. Confirmed codes are ALL kept; unconfirmed
        # candidates are dropped only when something confirmed is present.
        # (Previously this ran only when a quantity was parsed, so a changed
        # quantity heuristic could silently alter which codes survived.)
        chosen, rejected = select_row_codes(found, backbone)
        for c in rejected:
            review.append({
                "candidate":   c["code"],
                "score":       c.get("confidence", 0),
                "match":       c.get("match_kind", ""),
                "reason":      "Unconfirmed - a stronger candidate exists on the same line",
                "context":     line.strip()[:160],
                "page":        page_num,
                "source_file": source_file,
                "po_number":   po_number,
            })

        for item in chosen:
            if not item:
                continue

            # The record key includes the PO's printed line number. Keying on
            # the code alone made row 0008 of PO 246155 resolve to the record
            # already created for row 0006, so the second order line could
            # never be created no matter how the merge rules were written.
            code_key = normalize(item["code"])
            key = (code_key, po_line) if po_line else code_key
            existing = by_key.get(key)

            # Without a line number, fall back to matching on the code alone
            # so a summary line and its detail line still merge.
            if existing is None and not po_line:
                existing = by_key.get(code_key)

            if existing:
                # Two different situations produce a repeated code:
                #
                #  (a) the SAME item printed twice - a summary line plus the
                #      detail line that carries the quantity. Merge them.
                #  (b) the same model ordered on SEPARATE lines, each with its
                #      own quantity (PO 246155 lines 0006 and 0008). These are
                #      distinct order lines; merging them loses a quantity.
                #
                # The strongest signal is the PO's own line number, printed at
                # the start of the row ("0006", "0008"). When two rows carry
                # different line numbers they are different order lines, even
                # if OCR lost one of the quantities - which is exactly what
                # happened on PO 246155 row 0008.
                prev_q = str(existing.get("quantity") or "").strip()
                prev_ln = str(existing.get("po_line") or "").strip()
                cur_ln = po_line or ""

                if cur_ln and prev_ln and cur_ln != prev_ln:
                    pass          # (b) different printed line -> new record
                elif qty and prev_q and qty != prev_q:
                    pass          # (b) different quantity -> new record
                elif qty and prev_q and qty == prev_q and amount \
                        and str(existing.get("amount") or "") not in ("", amount):
                    pass          # same qty but a different amount -> new line
                else:
                    for f, v in (("quantity", qty), ("unit", unit),
                                 ("unit_price", price), ("amount", amount)):
                        if v and not existing.get(f):
                            existing[f] = v
                    continue

            rec = {
                "material_code": item["code"],
                "backbone_code": item.get("backbone_code", ""),
                "description":   item["description"] or line.strip()[:120],
                # The printed line the record came from, so a consumer can
                # read the original row instead of re-parsing the PDF.
                "source_line":   line.strip()[:200],
                "category":      item["category"],
                "quantity":      qty,
                "unit":          unit,
                "unit_price":    price,
                "amount":        amount,
                "po_line":       po_line,
                "po_number":     po_number,
                "page":          page_num,
                "source_file":   source_file,
                "match_type":    match_kind_to_type(item["match_kind"], from_zone=False),
                "extracted_at":  datetime.now().isoformat(),
            }
            records.append(rec)
            by_key[key] = rec
            # Also reachable by code alone, so a continuation line with no
            # line number of its own still enriches this record.
            by_key.setdefault(code_key, rec)

    return records


# ──────────────────────────────────────────────
# Reference list loading
# ──────────────────────────────────────────────
def load_reference_codes() -> dict:
    """
    Load material_codes_reference.csv (mtime-cached).
    Returns: {material_code: {description, category}, ...}
    """
    def _read():
        ref = {}
        if not REFERENCE_PATH.exists():
            return ref
        with open(REFERENCE_PATH, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(",", 2)
                if parts and parts[0].strip():
                    code = parts[0].strip().strip('"').upper()
                    if code and code != "MATERIAL_CODE":
                        ref[code] = {
                            "description": parts[1].strip().strip('"') if len(parts) > 1 else "",
                            "category": parts[2].strip().strip('"') if len(parts) > 2 else "",
                        }
        logger.info(f"Loaded {len(ref)} reference code(s)")
        return ref
    return _cached_load(REFERENCE_PATH, _read)


_BACKBONE_CACHE = {"key": None, "index": None}


def get_backbone() -> "BackboneIndex":
    """
    Shared BackboneIndex, rebuilt only when the reference CSV changes.
    In a batch run every PDF reuses the same index instead of rebuilding it.
    """
    codes = load_reference_codes()
    key = id(codes)          # _cached_load returns the same object until reload
    if _BACKBONE_CACHE["key"] != key:
        _BACKBONE_CACHE["key"] = key
        _BACKBONE_CACHE["index"] = BackboneIndex(codes)
    return _BACKBONE_CACHE["index"]


# ──────────────────────────────────────────────
# File hashing
# ──────────────────────────────────────────────
def file_md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def diagnose_pdf(pdf_path: str) -> dict:
    """
    Diagnose a PDF: text layer, page count, tables, extractability.
    Use this to find out why a specific file yields no results.
    """
    info = {
        "file": Path(pdf_path).name,
        "readable": False,
        "page_count": 0,
        "total_chars": 0,
        "pages_with_text": 0,
        "table_count": 0,
        "is_scanned": False,
        "engine": "",
        "sample_text": "",
        "issues": [],
        "recommendations": [],
    }

    # Try pdfplumber
    if PDFPLUMBER_AVAILABLE:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                info["readable"] = True
                info["engine"] = "pdfplumber"
                info["page_count"] = len(pdf.pages)
                samples = []
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    if t.strip():
                        info["pages_with_text"] += 1
                        if len(samples) < 3:
                            samples.append(t[:400])
                    info["total_chars"] += len(t.strip())
                    try:
                        info["table_count"] += len(page.extract_tables() or [])
                    except Exception:
                        pass
                info["sample_text"] = "\n---\n".join(samples)
        except Exception as e:
            info["issues"].append(f"pdfplumber error: {e}")

    # pypdf fallback
    if not info["readable"] and PYPDF_AVAILABLE:
        try:
            reader = PdfReader(pdf_path)
            info["readable"] = True
            info["engine"] = "pypdf"
            info["page_count"] = len(reader.pages)
            samples = []
            for page in reader.pages:
                t = page.extract_text() or ""
                if t.strip():
                    info["pages_with_text"] += 1
                    if len(samples) < 3:
                        samples.append(t[:400])
                info["total_chars"] += len(t.strip())
            info["sample_text"] = "\n---\n".join(samples)
        except Exception as e:
            info["issues"].append(f"pypdf error: {e}")

    # Verdict
    if not info["readable"]:
        info["issues"].append("Cannot open the PDF (corrupted or encrypted).")
        info["recommendations"].append("Re-save the PDF or ask the customer to resend it")
        return info

    if info["total_chars"] < 20:
        info["is_scanned"] = True
        info["issues"].append(
            f"No text layer found (only {info['total_chars']} characters detected). "
            f"This appears to be a scanned image PDF."
        )
        info["recommendations"] += [
            "Install an OCR engine: pip install rapidocr-onnxruntime",
            "Verify auto_ocr is true in config.json",
            "Increase ocr_dpi to 400-600 in config.json for low-quality scans",
            "Or ask the customer to send a text-based PDF",
        ]
    elif info["pages_with_text"] < info["page_count"]:
        info["issues"].append(
            f"{info['page_count'] - info['pages_with_text']} page(s) contain no text "
            f"(some pages may be scanned images)."
        )

    if info["table_count"] == 0 and not info["is_scanned"]:
        info["issues"].append(
            "No table structure detected (text present but no table borders)."
        )
        info["recommendations"].append(
            "Define a Material Code zone using Zone Templates"
        )

    return info


_SIG_CACHE = {"key": None, "value": ""}

# Extraction logic itself is part of the cache key. Without this, improving the
# code leaves every cached result stale: the app would keep serving the old
# output until the user remembered to tick "ignore cache". Any edit to these
# modules changes their mtime and therefore invalidates all cached results.
_LOGIC_FILES = ["engine.py"]


def config_signature() -> str:
    """
    Combined fingerprint of everything that can change an extraction result:
    config.json, customer_templates.json, material_codes_reference.csv, and
    the extraction modules themselves.

    Memoised on file mtimes, so a batch of N PDFs stats the files once
    instead of reading them N times.
    """
    watched = [CONFIG_PATH, TEMPLATES_PATH, REFERENCE_PATH] + \
              [BASE_DIR / f for f in _LOGIC_FILES]

    key = []
    for p in watched:
        try:
            st = p.stat()
            key.append((st.st_mtime_ns, st.st_size))
        except OSError:
            key.append(None)
    key = tuple(key)

    if _SIG_CACHE["key"] == key:
        return _SIG_CACHE["value"]

    h = hashlib.md5()
    # Data files: hash content. Logic files: hash mtime+size only, which is
    # enough to detect an edit without re-reading the source on every run.
    for p in [CONFIG_PATH, TEMPLATES_PATH, REFERENCE_PATH]:
        if p.exists():
            h.update(p.read_bytes())
    for f in _LOGIC_FILES:
        p = BASE_DIR / f
        try:
            st = p.stat()
            h.update(f"{f}:{st.st_mtime_ns}:{st.st_size}".encode())
        except OSError:
            pass

    _SIG_CACHE["key"] = key
    _SIG_CACHE["value"] = h.hexdigest()
    return _SIG_CACHE["value"]


# ──────────────────────────────────────────────
# Text extraction
# ──────────────────────────────────────────────
def extract_text_pdfplumber(pdf_path: str) -> list[dict]:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            tables = page.extract_tables() or []
            # Word coordinates are kept as well as the flattened text: the
            # template-free path uses them to work out which column a number
            # was printed in. Without them the only thing left is the order of
            # the tokens in the line, and a description that contains a number
            # ("WATER FILTER 2 PACK") is indistinguishable from a quantity
            # (see extract_page_line_items).
            try:
                words = page.extract_words(use_text_flow=False,
                                           keep_blank_chars=False) or []
            except Exception as e:
                logger.debug(f"extract_words failed on page {i+1}: {e}")
                words = []
            pages.append({"page_num": i + 1, "text": text,
                          "tables": tables, "words": words})
    return pages


def extract_text_pypdf(pdf_path: str) -> list[dict]:
    pages = []
    reader = PdfReader(pdf_path)
    for i in range(len(reader.pages)):
        text = reader.pages[i].extract_text() or ""
        pages.append({"page_num": i + 1, "text": text, "tables": [],
                      "words": []})
    return pages


def extract_text_ocr(pdf_path: str, lang: str = "eng",
                     dpi: int = 300, progress_callback=None) -> list[dict]:
    """OCR via the ocr_engine module (RapidOCR/Tesseract/EasyOCR auto-selected)"""
    if not OCR_MODULE_AVAILABLE:
        logger.error("ocr_engine module not found.")
        return []
    return ocr_pdf(pdf_path, lang=lang, dpi=dpi,
                              progress_callback=progress_callback)


# An order line on a PO prints its count as a small integer separated by
# SPACES from everything around it:
#
#     Dacor  DRR30980RAPDA|Refrigerator  1  2,677.05  2,677.05
#                                        ^ space on both sides
#
# The whitespace requirement is what makes this usable. Looking for a bare
# number anywhere also matches the digits inside a model (DWR30U900WPDA),
# and subtracting the money first eats those same digits, so both simpler
# rules reported every line as having a count. A line whose count was lost
# has no space-delimited integer left:
#
#     Dacor  DRZ30980LAPDA  Freezer  2,771.55  2,771.55
_QTY_ISLAND = re.compile(r"(?<=\s)\d{1,4}(?=\s)")


def _ocr_quality(pages: list) -> dict:
    """
    How much a scan's OCR actually recovered.

    Four measurements, because they fail differently:

      chars_per_page  the page was barely read at all
      has_money       no amount anywhere - the numbers were not read
      amount_lines    lines that print money
      qty_lines       of those, the ones that ALSO print a bare count

    The last pair is the one that matters. A model number survives a low
    resolution while the small digits beside it do not, so the telling failure
    is not "no text" - it is an order line with a price and no quantity:

        Dacor  DRZ30980LAPDA  Freezer  2,771.55  2,771.55     <- no count
        Dacor  DRR30980RAPDA  Refrigerator  1  2,677.05  2,677.05

    `pages` may be empty, which is a quality of zero rather than an error.
    """
    pages = pages or []
    if not pages:
        return {"chars_per_page": 0.0, "has_money": False, "pages": 0,
                "chars": 0, "amount_lines": 0, "qty_lines": 0}

    total, amount_lines, qty_lines = 0, 0, 0
    has_money = False
    for p in pages:
        text = p.get("text") or ""
        total += len(text.strip())
        for line in text.splitlines():
            if not _MONEY.search(line):
                continue
            has_money = True
            # Only an ITEM line is judged: it carries a model-shaped token
            # as well as money. A totals/footer line legitimately prints an
            # amount and no count, and counting those made the ratio look
            # broken on scans that extract perfectly.
            if not any(_MODEL_SHAPE.match(tok) for tok in line.split()):
                continue
            amount_lines += 1
            if _QTY_ISLAND.search(line):
                qty_lines += 1

    return {
        "chars_per_page": total / len(pages),
        "has_money": has_money,
        "pages": len(pages),
        "chars": total,
        "amount_lines": amount_lines,
        "qty_lines": qty_lines,
    }


def _ocr_needs_retry(q: dict, min_chars: int = OCR_MIN_CHARS_PER_PAGE) -> bool:
    """A first OCR pass worth re-rendering at a higher resolution."""
    if not q["pages"]:
        return True                    # nothing came back at all
    if q["chars_per_page"] < min_chars:
        return True                    # the page was barely read
    if not q["has_money"]:
        return True                    # text came back but no numbers
    # Priced lines outnumber lines that also show a count: some quantities
    # were dropped while the descriptions and prices survived.
    return q["qty_lines"] < q["amount_lines"]


def _ocr_with_retry(pdf_path: str, lang: str, dpi: int,
                    config: dict, progress_callback=None,
                    diag: list = None) -> list:
    """
    OCR a scan, then re-render once at a higher DPI if the first pass is thin.

    The retry exists because the cheap failure mode is not "OCR returns
    nothing" - it is "OCR returns the descriptions but drops the small digits
    beside them". The order then looks extracted and adds up short: PO 25407327
    yields one priced line out of two, and the missing half is exactly the line
    whose quantity was never read.

    It is a single escalation, not a loop: resolution costs time (roughly
    quadratic in DPI), and two failed passes mean the scan itself is the
    limit - which is what the returned diagnostics then say.

    Returns the better of the two readings (more pages, then more characters).
    """
    first = extract_text_ocr(pdf_path, lang=lang, dpi=dpi,
                             progress_callback=progress_callback)
    q1 = _ocr_quality(first)
    if not _ocr_needs_retry(q1):
        return first

    if not config.get("ocr_retry", True):
        return first

    retry_dpi = min(OCR_RETRY_MAX_DPI, int(dpi * OCR_RETRY_FACTOR))
    if retry_dpi <= dpi:
        retry_dpi = min(OCR_RETRY_MAX_DPI, dpi + 100)
    if retry_dpi <= dpi:
        return first                   # already at the ceiling

    name = Path(pdf_path).name
    logger.info(f"{name}: OCR thin at {dpi} DPI "
                f"({q1['chars_per_page']:.0f} chars/page, "
                f"money={q1['has_money']}) - retrying at {retry_dpi}")
    if progress_callback:
        progress_callback(35, f"Re-reading the scan at {retry_dpi} DPI...")

    second = extract_text_ocr(pdf_path, lang=lang, dpi=retry_dpi,
                              progress_callback=progress_callback)
    q2 = _ocr_quality(second)

    # "Better" means it recovered MORE OF WHAT WAS MISSING, not merely a few
    # more characters. A retry that adds 5 characters while the quantity
    # column is still absent has not helped, and saying so is the whole point
    # of the message - the user needs to know the scan is the limit rather
    # than keep re-running the extraction.
    improved = (q2["qty_lines"] - q2["amount_lines"]
                > q1["qty_lines"] - q1["amount_lines"]) or \
        (q2["pages"], q2["chars"]) > (q1["pages"], q1["chars"]) and \
        q2["qty_lines"] >= q1["qty_lines"] and \
        (q2["qty_lines"] > q1["qty_lines"] or q1["qty_lines"] == q1["amount_lines"])

    if diag is not None:
        if improved:
            diag.append(
                f"OCR retried at {retry_dpi} DPI: {q1['chars']:,} -> "
                f"{q2['chars']:,} characters, "
                f"{q2['qty_lines']}/{q2['amount_lines']} priced lines carry a "
                f"count (was {q1['qty_lines']}/{q1['amount_lines']}).")
        else:
            diag.append(
                f"OCR retried at {retry_dpi} DPI without recovering the "
                f"missing numbers ({q2['qty_lines']}/{q2['amount_lines']} "
                f"priced lines carry a count). The scan itself is the limit - "
                f"ask for a better copy, or key the missing quantity by hand.")
    logger.info(f"{name}: retry at {retry_dpi} DPI -> "
                f"{q2['chars']:,} chars (was {q1['chars']:,})")
    return second if improved else first


def _has_meaningful_text(pages: list[dict], min_chars: int = 20) -> bool:
    """Return True if a meaningful text layer exists."""
    total = sum(len((p.get("text") or "").strip()) for p in pages)
    return total >= min_chars


def get_pages(pdf_path: str, config: dict,
              progress_callback=None, diag: list = None) -> list[dict]:
    """
    Extract PDF text. Falls back to OCR automatically when no text layer
    is present. Runs silently without prompting the user.

    `diag` (a list) receives human-readable notes from the OCR path - today the
    outcome of the high-DPI retry, so a user who still sees missing quantities
    is told the scan itself was the limit rather than being left to guess.
    """
    min_chars = config.get("min_text_chars", 20)

    # 1) pdfplumber (preferred - also yields table structure)
    if PDFPLUMBER_AVAILABLE:
        try:
            pages = extract_text_pdfplumber(pdf_path)
            if _has_meaningful_text(pages, min_chars):
                return pages
        except Exception as e:
            logger.warning(f"pdfplumber failed: {e}")

    # 2) pypdf
    if PYPDF_AVAILABLE:
        try:
            pages = extract_text_pypdf(pdf_path)
            if _has_meaningful_text(pages, min_chars):
                return pages
        except Exception as e:
            logger.warning(f"pypdf failed: {e}")

    # 3) Automatic OCR fallback (enabled by default)
    if config.get("auto_ocr", True) and OCR_MODULE_AVAILABLE:
        if ocr_available():
            logger.info(
                f"{Path(pdf_path).name}: no text layer -> "
                f"running OCR automatically ({ocr_engine_name()})"
            )
            if progress_callback:
                progress_callback(
                    30, f"Scanned PDF detected - running OCR ({ocr_engine_name()})"
                )
            pages = _ocr_with_retry(
                pdf_path,
                lang=config.get("ocr_language", "eng"),
                dpi=config.get("ocr_dpi", OCR_DPI),
                config=config,
                progress_callback=progress_callback,
                diag=diag,
            )
            if pages and _has_meaningful_text(pages, 5):
                return pages
            logger.warning(f"{Path(pdf_path).name}: OCR produced no text")
        else:
            logger.warning(
                f"{Path(pdf_path).name}: scanned PDF but no OCR engine. "
                f"pip install rapidocr-onnxruntime"
            )

    return []


# ──────────────────────────────────────────────
# PO Number extraction
# ──────────────────────────────────────────────
# Supported formats:
#   Purchase Order Number / Purchase Order No. / Purchase Order #
#   P.O. Number / P.O. No. / P.O. #
#   PO Number / PO No. / PO # / P.O.Number
#   Order Number / Order No. / Order #
#   PO: XXXX  /  P.O.: XXXX

PO_PATTERNS = [
    # Most specific patterns first
    r"(?:Purchase\s+Order|P\.?\s*O\.?)\s*(?:Number|No\.?|Num\.?|#|:)\s*[:\-]?\s*([A-Z0-9][\w\-\.\/]{2,24})",
    r"P\.?\s*O\.?\s*(?:Number|No\.?|#)\s*[:\-]?\s*([A-Z0-9][\w\-\.\/]{2,24})",
    r"PO\s*(?:Number|No\.?|Num\.?|#)\s*[:\-]?\s*([A-Z0-9][\w\-\.\/]{2,24})",
    r"PO\s*[:\-]\s*([A-Z0-9][\w\-\.\/]{2,24})",
    r"Order\s*(?:Number|No\.?|#)\s*[:\-]?\s*([A-Z0-9][\w\-\.\/]{2,24})",
    # Value immediately after a header label (newline allowed)
    r"(?:Purchase\s+Order|P\.?\s*O\.?)\s*[\r\n]+\s*([A-Z0-9][\w\-\.\/]{2,24})",
]

# Labels/keywords that must never be treated as PO numbers
PO_EXCLUDE = re.compile(
    r"^("
    r"DATE|PAGE|SHIP|SHIPPED|FROM|TO|BILL|BILLED|SOLD|ATTN|FAX|TEL|TELEPHONE|PHONE|"
    r"USD|NET|FOB|F\.?O\.?B\.?|N/?A|NUMBER|NO|NUM|ORDER|PURCHASE|"
    r"P\.?O\.?|VENDOR|SUPPLIER|CUSTOMER|ACCOUNT|INVOICE|TERMS|"
    r"RELEASE|REVISION|REV|TOTAL|QTY|ITEM|LINE|OF|AND|THE"
    r")$",
    re.IGNORECASE
)


def _is_valid_po(val: str) -> bool:
    """Validate a PO number candidate."""
    if not val or len(val) < 3:
        return False
    v = val.strip().rstrip(".,;:")
    if PO_EXCLUDE.match(v):
        return False
    # A PO number must contain digits
    if not re.search(r"\d", v):
        return False
    # Reject date and phone number formats
    if re.fullmatch(r"\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}", v):
        return False
    if re.fullmatch(r"\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2}", v):
        return False
    if re.fullmatch(r"\(?\d{3}\)?[\-\s\.]?\d{3}[\-\s\.]?\d{4}", v):
        return False
    # Reject bare years and 1-2 digit numbers
    if re.fullmatch(r"(19|20)\d{2}", v) or re.fullmatch(r"\d{1,2}", v):
        return False
    return True


def _join_po_suffix(text: str, end: int, val: str) -> str:
    """
    Attach a second group printed after a separator: "00931 - 2309035".

    CMH prints its department code and the order sequence as one hyphenated PO.
    Keeping only the first group made every order from that department look
    like the same PO - and (customer, PO) is exactly what the duplicate check
    keys on, so each new CMH order would have been flagged a re-send.

    Only a run of at least three digits is accepted after the separator, so a
    date, a revision label or the next field is never glued on. "=" is included
    because a scan reads the hyphen as one ("00931 = 2309035").
    """
    m = re.match(r"\s*[-–—=]\s*(\d{3,})(?![\d/])", (text or "")[end:])
    if not m:
        return val
    joined = f"{val}-{m.group(1)}"
    return joined if _is_valid_po(joined) else val


def find_po_number(text: str) -> str:
    """Extract the PO number from full text as accurately as possible."""
    candidates = []

    for pattern in PO_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
            val = m.group(1).strip().rstrip(".,;:")
            if _is_valid_po(val):
                candidates.append((m.start(), m.end(1), val))

    if not candidates:
        return ""

    # Return the first valid candidate by position
    candidates.sort(key=lambda x: x[0])
    _start, end, val = candidates[0]
    return _join_po_suffix(text, end, val)


_PO_TOKEN = re.compile(r"\b([A-Z]{0,3}\d{5,10}[A-Z]{0,2})\b")
_FNAME_TOKEN = re.compile(r"([A-Za-z]{0,4}\d{4,12})")


def po_from_filename_and_text(filename: str, text: str) -> str:
    """
    Recover a PO number when label-based parsing fails.

    Many layouts print the column headings on one line and the values on the
    next ("P.O. Number" / "... 04/16/2026 BM736499 Standard"), so a
    label-anchored pattern finds nothing. Two document facts are used instead:

      1. The filename usually carries the PO number
         (SAMSUNGNJ.PO4046792..., PO_0736499...)
      2. The PO number is repeated in the body (header and footer)

    A body token is accepted only when it also appears in the filename - or
    shares the filename's digit run, which covers BM736499 vs PO_0736499.
    This never invents a value: the result always exists in the document.
    """
    if not text:
        return ""

    body = text.upper()
    counts = {}
    for m in _PO_TOKEN.finditer(body):
        tok = m.group(1)
        if _is_valid_po(tok):
            counts[tok] = counts.get(tok, 0) + 1
    if not counts:
        return ""

    fname_digits = {re.sub(r"\D", "", t)
                    for t in _FNAME_TOKEN.findall(filename or "")}
    fname_digits = {d for d in fname_digits if len(d) >= 5}

    def score(tok: str) -> tuple:
        digits = re.sub(r"\D", "", tok)
        exact = any(digits == d for d in fname_digits)
        shared = any(digits in d or d in digits for d in fname_digits)
        return (exact, shared, counts[tok], len(tok))

    best = max(counts, key=score)
    exact, shared, freq, _ = score(best)
    if exact or shared or freq >= 2:
        logger.info(f"PO recovered from filename/frequency: {best} "
                    f"(exact={exact} shared={shared} freq={freq})")
        return best
    return ""


_PO_LABEL = re.compile(r"(?i)^(p\.?\s*o\.?|purchase)$")
_PO_LABEL2 = re.compile(r"(?i)^(number|no\.?|num\.?|#|order)$")


def find_po_by_layout(pdf_path: str) -> str:
    """
    Locate a PO number in COLUMN layouts, where the label and the value sit on
    different lines:

        P.O. Date    P.O. Number   P.O. Type
        04/16/2026   BM736499      Standard

    Word coordinates are used: find the 'P.O. Number' label, then take the
    nearest value below it (or to its right) whose horizontal span overlaps
    the label. Text-only regexes cannot do this reliably.
    """
    if not PDFPLUMBER_AVAILABLE:
        return ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:2]:
                words = page.extract_words(use_text_flow=False,
                                           keep_blank_chars=False) or []
                if not words:
                    continue

                # Find "P.O./Purchase" followed by "Number/No" on the same line
                labels = []
                for i, w in enumerate(words):
                    if not _PO_LABEL.match(w["text"].strip()):
                        continue
                    for w2 in words[i + 1:i + 4]:
                        if abs(w2["top"] - w["top"]) > 3:
                            break
                        if _PO_LABEL2.match(w2["text"].strip()):
                            labels.append((w, w2))
                            break

                for w1, w2 in labels:
                    lx0, lx1 = w1["x0"], w2["x1"]
                    lbot = w2["bottom"]

                    # Candidates below the label, horizontally overlapping it
                    below = [
                        v for v in words
                        if v["top"] > lbot - 2
                        and v["top"] - lbot < 40
                        and v["x1"] > lx0 - 6 and v["x0"] < lx1 + 6
                    ]
                    below.sort(key=lambda v: (v["top"], v["x0"]))
                    for v in below:
                        cand = v["text"].strip().rstrip(".,;:")
                        if _is_valid_po(cand):
                            logger.info(f"PO found by layout (below label): {cand}")
                            return cand

                    # Otherwise the value may sit to the right on the same line
                    right = [
                        v for v in words
                        if abs(v["top"] - w1["top"]) <= 3 and v["x0"] > w2["x1"]
                    ]
                    right.sort(key=lambda v: v["x0"])
                    for v in right[:4]:
                        cand = v["text"].strip().rstrip(".,;:")
                        if _is_valid_po(cand):
                            logger.info(f"PO found by layout (right of label): {cand}")
                            return cand
    except Exception as e:
        logger.debug(f"Layout PO search failed: {e}")
    return ""


def po_from_filename(name: str) -> str:
    """
    Last-resort PO from the file name: SAMSUNGNJ.PO4046792.06192026.pdf,
    PO_0736499.pdf, 2170541.pdf. Only used when the document yields nothing.
    """
    stem = Path(name).stem
    m = re.search(r"(?i)\bP\.?O\.?[_\-\.# ]?([A-Z]{0,3}\d{5,12})\b", stem)
    if m and _is_valid_po(m.group(1)):
        return m.group(1)
    nums = re.findall(r"\b([A-Z]{0,3}\d{5,12})\b", stem, re.IGNORECASE)
    for n in nums:
        if _is_valid_po(n):
            return n
    return ""


def find_all_po_numbers(pages: list[dict]) -> dict:
    """
    Extract PO numbers per page.
    Returns: {page_num: po_number}
    """
    po_map = {}
    full_text = "\n".join(p["text"] for p in pages)

    # Search the whole document first
    doc_po = find_po_number(full_text)

    for page in pages:
        page_po = find_po_number(page["text"])
        po_map[page["page_num"]] = page_po or doc_po

    return po_map, doc_po


# ──────────────────────────────────────────────
# Material Code pattern matching
# ──────────────────────────────────────────────
_PATTERN_CACHE = {"key": None, "value": ([], [])}


def compile_patterns(config: dict):
    """Compile config regexes once per config object (config is mtime-cached)."""
    key = id(config)
    if _PATTERN_CACHE["key"] == key:
        return _PATTERN_CACHE["value"]
    include = [re.compile(p) for p in config.get("material_code_patterns", [])]
    exclude = [re.compile(p) for p in config.get("exclude_patterns", [])]
    _PATTERN_CACHE["key"] = key
    _PATTERN_CACHE["value"] = (include, exclude)
    return include, exclude


def is_excluded(value: str, exclude_patterns: list) -> bool:
    return any(p.fullmatch(value) for p in exclude_patterns)


def apply_exclusions(records: list, exclude_pats: list) -> tuple:
    """
    Drop records whose material code matches an exclude pattern.

    The exclude patterns used to be honoured only on the Excel-table and
    text-fallback paths; the main line-scan path ignored them. This single
    choke point runs over the finished record list of every path, so a pattern
    in config.json now excludes a code everywhere.
    Returns: (kept, dropped_codes)
    """
    if not exclude_pats or not records:
        return list(records or []), []
    kept, dropped = [], []
    for r in records:
        code = str(r.get("material_code") or "").strip()
        if code and is_excluded(code, exclude_pats):
            dropped.append(code)
        else:
            kept.append(r)
    return kept, dropped


def _extract_qty(context: str) -> str:
    """Extract a quantity from context (simple heuristic)."""
    patterns = [
        r"[Qq](?:ty|uantity|'?ty)\.?\s*[:\-]?\s*(\d+(?:,\d{3})*(?:\.\d+)?)",
        r"(\d+(?:,\d{3})*)\s*(?:EA|PCS|PC|EACH|UNITS?)\b",
    ]
    for p in patterns:
        m = re.search(p, context, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _extract_price(context: str) -> str:
    """Extract a unit price from context.

    Uses the shared _AMOUNT shape, so every form the rest of the engine reads
    is read here too. The old local `\\d{1,3}` matched only the first three
    digits of a bare four-digit price and returned that fragment: on
    'Unit Price: 1198.00' it produced "119", publishing a wrong unit price
    rather than none (see _AMOUNT).
    """
    patterns = [
        r"(?:Unit\s*Price|U/?P|Price)\s*[:\-]?\s*\$?\s*(" + _AMOUNT + r")",
        r"\$\s*(" + _AMOUNT + r")",
    ]
    for p in patterns:
        m = re.search(p, context, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


# ──────────────────────────────────────────────
# Table-based extraction
# ──────────────────────────────────────────────
def extract_from_table(tables: list, config: dict,
                       include_pats: list, exclude_pats: list,
                       ref_codes: dict, po_number: str,
                       page_num: int, source_file: str) -> list[dict]:
    results = []
    col_keywords = [k.lower() for k in config.get("column_keywords", [])]
    min_len = config.get("min_code_length", 5)
    max_len = config.get("max_code_length", 20)

    for table in tables:
        if not table or len(table) < 2:
            continue

        header_row = table[0]
        if not header_row:
            continue
        headers = [str(h).lower().strip() if h else "" for h in header_row]

        # Header names are resolved with the SAME vocabulary the zone parser
        # uses (classify_header), so the two paths can no longer disagree about
        # what a column is, and each role is owned by exactly ONE column. The
        # old substring rules overwrote in place, so 'Extended Price' matched
        # 'price' as well as 'extended' and the unit price was published as the
        # line total (COLUMN_ALIGNMENT P0-5).
        roles = {}
        for idx, h in enumerate(headers):
            role = classify_header(h)
            if role and role not in roles:
                roles[role] = idx

        mat_col = roles.get("material_code")
        desc_col = roles.get("description")
        qty_col = roles.get("quantity")
        price_col = roles.get("unit_price")
        amount_col = roles.get("amount")

        # The configured keyword list still decides the material column when
        # the vocabulary did not name one: a house word ('mat', 'vendor part')
        # that the shared role list does not carry must not be lost.
        if mat_col is None:
            for idx, h in enumerate(headers):
                if h and any(kw in h for kw in col_keywords):
                    mat_col = idx
                    break

        for row in table[1:]:
            if not row:
                continue

            # Material code column found
            if mat_col is not None and mat_col < len(row):
                code_raw = str(row[mat_col]).strip() if row[mat_col] else ""
                code = code_raw.upper()
                if not code or len(code) < min_len:
                    continue

                # Check reference match
                match_type = "reference" if code in ref_codes else "pattern"
                ref_info = ref_codes.get(code, {})

                results.append({
                    "material_code": code,
                    "description": (str(row[desc_col]).strip() if desc_col is not None and desc_col < len(row) and row[desc_col] else "") or ref_info.get("description", ""),
                    "category": ref_info.get("category", ""),
                    "quantity": str(row[qty_col]).strip() if qty_col is not None and qty_col < len(row) and row[qty_col] else "",
                    "unit_price": str(row[price_col]).strip() if price_col is not None and price_col < len(row) and row[price_col] else "",
                    "amount": str(row[amount_col]).strip() if amount_col is not None and amount_col < len(row) and row[amount_col] else "",
                    "po_number": po_number,
                    "page": page_num,
                    "source_file": source_file,
                    "match_type": match_type,
                    "extracted_at": datetime.now().isoformat()
                })
            else:
                # No header -> pattern-match each cell
                for cell in row:
                    if not cell:
                        continue
                    cell_str = str(cell).strip()
                    code = cell_str.upper()
                    if min_len <= len(cell_str) <= max_len:
                        is_ref = code in ref_codes
                        if is_ref:
                            results.append({
                                "material_code": code,
                                "description": ref_codes[code].get("description", ""),
                                "category": ref_codes[code].get("category", ""),
                                "quantity": "", "unit_price": "", "amount": "",
                                "po_number": po_number, "page": page_num,
                                "source_file": source_file,
                                "match_type": "reference",
                                "extracted_at": datetime.now().isoformat()
                            })
                        else:
                            for pat in include_pats:
                                if pat.fullmatch(cell_str) and not is_excluded(cell_str, exclude_pats):
                                    results.append({
                                        "material_code": cell_str,
                                        "description": "", "category": "",
                                        "quantity": "", "unit_price": "", "amount": "",
                                        "po_number": po_number, "page": page_num,
                                        "source_file": source_file,
                                        "match_type": "pattern",
                                        "extracted_at": datetime.now().isoformat()
                                    })

    return results


# ──────────────────────────────────────────────
# Text pattern extraction (fallback)
# ──────────────────────────────────────────────
def extract_from_text(text: str, config: dict,
                      include_pats: list, exclude_pats: list,
                      ref_codes: dict, po_number: str,
                      page_num: int, source_file: str) -> list[dict]:
    results = []
    min_len = config.get("min_code_length", 5)
    max_len = config.get("max_code_length", 20)
    seen = set()

    for pat in include_pats:
        for m in pat.finditer(text):
            code = m.group(0).strip()
            code_upper = code.upper()
            if min_len <= len(code) <= max_len and code_upper not in seen:
                if not is_excluded(code, exclude_pats):
                    seen.add(code_upper)
                    is_ref = code_upper in ref_codes
                    ref_info = ref_codes.get(code_upper, {})

                    start = max(0, m.start() - 60)
                    end = min(len(text), m.end() + 120)
                    context = text[start:end].replace("\n", " ").strip()

                    results.append({
                        "material_code": code_upper if is_ref else code,
                        "description": ref_info.get("description", context),
                        "category": ref_info.get("category", ""),
                        "quantity": _extract_qty(context),
                        "unit_price": _extract_price(context),
                        "amount": "",
                        "po_number": po_number,
                        "page": page_num,
                        "source_file": source_file,
                        "match_type": "reference" if is_ref else "pattern",
                        "extracted_at": datetime.now().isoformat()
                    })

    return results


# ──────────────────────────────────────────────
# JSON cache
# ──────────────────────────────────────────────
def get_cache_path(pdf_path: str) -> Path:
    return CACHE_DIR / f"{Path(pdf_path).stem}.json"


def is_mac_sidecar(path) -> bool:
    """True for macOS AppleDouble files ('._PO 2147.pdf') beside a real one.

    The source tree travels between a Mac and this PC, and every copy of it
    brings a '._' twin for each file: 4 KB of Finder metadata that happens to
    end in .pdf. A whole-folder sweep (engine_audit.py, engine_baseline.py)
    picked those up as POs, then failed on them - "No /Root object! - Is this
    really a PDF?" - and buried the real verdicts under 16 errors. They are
    never a document, so every sweep skips them.
    """
    return Path(path).name.startswith("._")


def load_cache(cache_path: Path) -> Optional[dict]:
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_cache(cache_path: Path, data: dict):
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_index(pdf_path: str, file_md5_hash: str, record_count: int, po_number: str):
    index_path = CACHE_DIR / "index.json"
    index = {}
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
    index[Path(pdf_path).name] = {
        "path": str(pdf_path),
        "md5": file_md5_hash,
        "record_count": record_count,
        "po_number": po_number,
        "processed_at": datetime.now().isoformat()
    }
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# Record de-duplication
# ──────────────────────────────────────────────
def dedupe_records(records: list) -> list:
    """Collapse duplicate rows while preserving genuine repeat order lines.

    The same material code legitimately appears on two different lines of one
    purchase order (e.g. line 0006 and line 0008 of PO 246155, two separate
    deliveries of the same washer).  De-duplicating on (code, page) alone
    silently deletes the second line, so the PO's own printed line number is
    part of the identity whenever it is available.

    Rows with no printed line number keep the old (code, page) behaviour, so
    repeated noise from a full-page text sweep is still collapsed.  A numbered
    row never suppresses an unnumbered one and vice versa only in the safe
    direction: unnumbered rows are dropped if that exact code/page was already
    emitted, because they carry strictly less information.
    """
    seen = set()
    seen_plain = set()
    unique = []
    for r in records:
        po_line = str(r.get("po_line") or "").strip()
        plain = (r.get("material_code"), r.get("page"))
        key = plain + (po_line,) if po_line else plain
        if key in seen:
            continue
        if not po_line and plain in seen_plain:
            continue
        seen.add(key)
        seen_plain.add(plain)
        unique.append(r)
    return unique


# ──────────────────────────────────────────────
# Main extraction entry point
# ──────────────────────────────────────────────
def extract_material_codes(pdf_path: str,
                           force: bool = False,
                           customer_name: str = "",
                           progress_callback=None) -> dict:
    config = load_config()
    include_pats, exclude_pats = compile_patterns(config)
    ref_codes = load_reference_codes()
    backbone = get_backbone()
    templates = load_templates()
    cache_path = get_cache_path(pdf_path)
    md5_hash = file_md5(pdf_path)
    cfg_sig = config_signature()
    source_file = Path(pdf_path).name

    # Cache hit only when the PDF and all config files are unchanged
    if not force:
        cached = load_cache(cache_path)
        if (cached
                and cached.get("md5") == md5_hash
                and cached.get("config_sig") == cfg_sig):
            if progress_callback:
                progress_callback(100, "Loaded from cache")
            return cached

    if progress_callback:
        progress_callback(10, "Extracting PDF text...")

    probe_pages = None      # set by the fingerprint probe; reused below

    # -- Look up Zone Template (optional; extraction works without one) --
    matched_customer = customer_name
    matched_tmpl = templates.get(customer_name, {})
    if not matched_tmpl:
        matched_customer, matched_tmpl = find_customer_template(source_file, templates)

        # Filename gave nothing - try matching on document content instead.
        # The probe result is kept and reused as the main page extraction so
        # the PDF is parsed (and, for scans, OCR'd) exactly once.
        if not matched_tmpl and templates:
            try:
                probe_pages = get_pages(pdf_path, config, progress_callback,
                                        diag=zone_diag)
                probe_text = ("\n".join(p["text"] for p in probe_pages[:2])
                              if probe_pages else "")
                if probe_text:
                    matched_customer, matched_tmpl = find_customer_template(
                        source_file, templates, probe_text
                    )
            except Exception as e:
                logger.debug(f"Fingerprint probe failed: {e}")

    zones = matched_tmpl.get("zones", []) if matched_tmpl else []
    zone_types = {z.get("type") for z in zones}
    has_li_zone = "line_items" in zone_types
    has_mc_zone = "material_code" in zone_types or has_li_zone
    has_po_zone = "po_number" in zone_types

    zone_records = []
    zone_po = ""
    zone_diag = []          # diagnostic messages
    review_items = []       # candidates not written to the main output
    zone_scope_locked = False   # a Line Items box defines the extraction scope

    # -- Zone extraction (uses whatever zones exist) --
    if zones:
        zone_diag.append(f"Template applied: '{matched_customer}'")
        if progress_callback:
            progress_callback(20, f"Applying Zone Template: {matched_customer}")
        try:
            zone_results = extract_zone_text(
                pdf_path, zones, config, progress_callback
            )
            zone_records, zone_po = parse_zone_results(
                zone_results, backbone, "", source_file,
                max_code_len=config.get("max_code_length", 24),
                regex_patterns=include_pats,
            )

            # line_items zones: one box around the whole table.
            # Parsed separately because rows and columns are derived internally.
            if has_li_zone:
                li_records = []
                words_by_idx = {zr.get("zone_idx"): zr.get("words") or []
                                for zr in zone_results}
                for zi, z in enumerate(zones):
                    if z.get("type") != "line_items":
                        continue
                    li_records += parse_line_items_zone(
                        z, words_by_idx.get(zi, []), backbone, include_pats,
                        zone_po or "", source_file,
                        config.get("max_code_length", 24),
                        review=review_items, diag=zone_diag
                    )
                if li_records:
                    # The user drew this box deliberately, so it defines the
                    # scope. Results from other zones are dropped rather than
                    # merged, otherwise codes from outside the table reappear.
                    zone_records = li_records
                    zone_scope_locked = True
                else:
                    zone_diag.append(
                        "The Line Items zone produced no rows. "
                        "Make sure the box covers the header row and all item rows."
                    )

            if any(zr.get("ocr") for zr in zone_results):
                zone_diag.append(
                    f"Some zones were processed with OCR ({ocr_engine_name()})."
                    if OCR_MODULE_AVAILABLE else "Some zones were processed with OCR."
                )
            if has_po_zone and not zone_po:
                zone_diag.append("No value found in the PO Number zone. Check the area.")
            if has_mc_zone and not zone_records:
                zone_diag.append("No codes found in the Material Code zone. Check the area.")
            if not has_mc_zone:
                zone_diag.append("No Material Code zone defined; automatic extraction was used.")
        except Exception as e:
            logger.error(f"Zone extraction failed: {e}")
            zone_diag.append(f"Zone extraction error: {e}")

    # -- Full-document parsing (always run, for fallback/enrichment) --
    if progress_callback:
        progress_callback(35, "Analyzing full PDF text...")

    pages = (probe_pages if probe_pages is not None
             else get_pages(pdf_path, config, progress_callback,
                            diag=zone_diag))
    used_ocr = any(p.get("ocr") for p in pages) if pages else False
    if used_ocr:
        zone_diag.append(
            f"Scanned PDF was processed automatically with OCR"
            + (f" ({ocr_engine_name()})." if OCR_MODULE_AVAILABLE else ".")
        )

    if not pages:
        # Run diagnostics to report a concrete cause
        ocr_ready = OCR_MODULE_AVAILABLE and ocr_available()
        try:
            diag = diagnose_pdf(pdf_path)
            zone_diag.extend(diag.get("issues", []))
            if diag.get("is_scanned") and not ocr_ready:
                # Two separate things have to be installed before a scan can be
                # read at all: something that rasterises the page, and something
                # that reads the image. Naming the missing one is the difference
                # between "the file just looks empty" and a one-line fix.
                missing = []
                if not render_backend():
                    missing.append("a PDF rasteriser "
                                   "(pip install pypdfium2)")
                if not get_ocr_engine()[0]:
                    missing.append("an OCR engine "
                                   "(pip install rapidocr-onnxruntime)")
                if not missing:
                    missing.append("an OCR stack")
                err_msg = ("Scanned image PDF - there is no text layer, and "
                           "nothing on this PC can read the image. Missing: "
                           + "; ".join(missing))
                zone_diag.extend(f"-> missing {m}" for m in missing)
            elif diag.get("is_scanned") and ocr_ready:
                err_msg = (f"OCR ({ocr_engine_name()}) ran but recognized no text. "
                           f"The scan quality may be too low.")
                zone_diag.append("-> Increase ocr_dpi to 400-600 in config.json")
            else:
                err_msg = "Text extraction failed. Use [Diagnose PDF] for details."
                zone_diag.extend(f"→ {r}" for r in diag.get("recommendations", []))
        except Exception:
            err_msg = "Text extraction failed (possibly a scanned PDF)"

        result = {
            "source_file": source_file, "md5": md5_hash,
            "config_sig": cfg_sig,
            "records": zone_records, "po_number": zone_po,
            "customer": matched_customer,
            "extraction_mode": "zone_template" if zone_records else "failed",
            "error": err_msg,
            # Same keys as a successful run. A consumer that reads ocr_used
            # directly should not have to know that this one path built a
            # smaller dict.
            "ocr_used": used_ocr,
            "ocr_engine": (ocr_engine_name()
                           if (used_ocr and OCR_MODULE_AVAILABLE) else ""),
            "diagnostics": zone_diag,
            "review": _dedupe_review(review_items),
            "processed_at": datetime.now().isoformat(), "page_count": 0,
            "stats": {"total": len(zone_records), "reference_matched": 0,
                      "paren_matched": 0, "zone_matched": 0,
                      "pattern_matched": len(zone_records),
                      "review_count": len(review_items),
                      "backbone_size": len(backbone)}
        }
        save_cache(cache_path, result)
        return result

    # PO number extraction (document-wide + per page)
    if progress_callback:
        progress_callback(45, "Extracting PO Number...")
    po_map, doc_po = find_all_po_numbers(pages)

    # Label-anchored text parsing fails on COLUMN layouts, where the heading
    # and the value sit on different lines. Escalate through the fallbacks.
    if not doc_po and not used_ocr:
        doc_po = find_po_by_layout(pdf_path)
        if doc_po:
            po_map = {k: (v or doc_po) for k, v in po_map.items()}
            zone_diag.append(f"PO number found by column layout: {doc_po}")

    if not doc_po:
        doc_po = po_from_filename_and_text(
            source_file, "\n".join(p["text"] for p in pages))
        if doc_po:
            po_map = {k: (v or doc_po) for k, v in po_map.items()}
            zone_diag.append(f"PO number recovered without a label: {doc_po}")

    if not doc_po:
        doc_po = po_from_filename(source_file)
        if doc_po:
            po_map = {k: (v or doc_po) for k, v in po_map.items()}
            zone_diag.append(f"PO number taken from the file name: {doc_po}")

    # Zone PO wins - it was defined explicitly by the user
    if zone_po:
        doc_po = zone_po
        po_map = {k: zone_po for k in po_map}

    # -- If the zone yielded material codes, use them as-is --
    if has_mc_zone and zone_records:
        for r in zone_records:
            r["po_number"] = doc_po

        # A zone is bound to ONE page. Multi-page purchase orders continue the
        # item table on later pages that no zone covers, and those pages would
        # be silently dropped (PO 4046792: 3 pages, only page 1 extracted).
        # Pages outside the template are scanned with the full-page engine.
        zone_pages = {z.get("page", 0) + 1 for z in zones}
        extra_pages = [p for p in pages if p["page_num"] not in zone_pages]
        if extra_pages:
            added = []
            for page_data in extra_pages:
                added += extract_lines_with_backbone(
                    page_data["text"], page_data["tables"], backbone,
                    include_pats, po_map.get(page_data["page_num"], doc_po),
                    page_data["page_num"], source_file,
                    config.get("max_code_length", 24), review=review_items
                )
            if added:
                zone_records = zone_records + added
                zone_diag.append(
                    f"{len(added)} item(s) recovered from page(s) "
                    f"{sorted(p['page_num'] for p in extra_pages)} - "
                    f"the template covers page {sorted(zone_pages)} only."
                )

        # Publish the backbone's spelling before de-duplicating, so an OCR
        # misread and its correct twin resolve to one identity.
        normalize_output_codes(zone_records, backbone)

        # Deduplicate on (code, page, quantity, amount): the same model can be
        # ordered on several lines of one PO, and those lines must survive as
        # separate records or their quantities are lost.
        seen = set()
        unique = []
        for r in zone_records:
            key = (r["material_code"], r["page"], str(r.get("po_line") or ""),
                   str(r.get("quantity") or ""), str(r.get("amount") or ""))
            if key not in seen:
                seen.add(key)
                unique.append(r)

        # A Line Items box usually stops before the money columns, so prices
        # are recovered from the full page text for the same code line.
        n_money = enrich_money_from_pages(unique, pages, backbone)
        if n_money:
            zone_diag.append(
                f"Unit Price / Amount recovered from the page for "
                f"{n_money} item(s) (the zone did not cover the cost columns)."
            )

        # With a backbone list loaded, unconfirmed codes are moved out of the
        # main output. A wrong code shared with a customer is worse than a
        # missing one, so only validated rows are reported.
        #
        # A code the list does not carry is kept, flagged for review, when the
        # row still looks like a real order line - see
        # _pattern_row_is_plausible(). New models reach a PO before the master
        # list (N104789 printed WW25FG6B34BE at $833.00 and this second copy
        # of the gate was dropping it while the pattern-mode gate had already
        # been fixed).
        if backbone.enabled:
            unique = _apply_accuracy_gate(
                unique, backbone, review_items, source_file, doc_po,
                zone_diag=zone_diag)

        # exclude_patterns are honoured on every path (see apply_exclusions)
        unique, excluded = apply_exclusions(unique, exclude_pats)
        if excluded:
            zone_diag.append(
                f"{len(excluded)} code(s) dropped by exclude_patterns: "
                f"{', '.join(sorted(set(excluded))[:8])}")

        ref_matched   = sum(1 for r in unique if "reference" in r.get("match_type", ""))
        paren_matched = sum(1 for r in unique if "paren" in r.get("match_type", ""))
        result = {
            "source_file": source_file, "md5": md5_hash, "config_sig": cfg_sig,
            "records": unique, "po_number": doc_po,
            "customer": matched_customer,
            "extraction_mode": "zone_template",
            "diagnostics": zone_diag,
            "review": _dedupe_review(review_items),
            "processed_at": datetime.now().isoformat(),
            "page_count": len(pages),
            "stats": {"total": len(unique),
                      "reference_matched": ref_matched,
                      "paren_matched": paren_matched,
                      "zone_matched": len(unique) - ref_matched - paren_matched,
                      "pattern_matched": 0,
                      "review_count": len(review_items),
                      "backbone_size": len(backbone)}
        }
        save_cache(cache_path, result)
        update_index(pdf_path, md5_hash, len(unique), doc_po)
        if progress_callback:
            progress_callback(100, f"Zone complete: {len(unique)} code(s) (Template: {matched_customer})")
        return result

    # -- Hybrid / pattern mode below --
    # (no material_code zone, or the zone produced nothing)

    all_records = []
    total = len(pages)

    for i, page_data in enumerate(pages):
        if progress_callback:
            pct = 45 + int(50 * (i + 1) / total)
            progress_callback(pct, f"Analyzing page {i+1}/{total}...")

        page_num = page_data["page_num"]
        text = page_data["text"]
        tables = page_data["tables"]
        po_number = po_map.get(page_num, doc_po)

        # Priority 0: the page's own header row, when it has one. Reading the
        # value out of the column it was printed in beats every positional
        # guess in the line scan below, and it is the only thing that can tell
        # a quantity from a number inside a description. Returns [] when no
        # header/quantity column was found, so nothing else changes.
        col_records = extract_page_line_items(
            page_data.get("words") or [], backbone, include_pats,
            po_number, page_num, source_file,
            config.get("max_code_length", 24), review=review_items
        )

        # Priority 1: backbone / parenthesis matching, line by line.
        # Each line is scanned so quantity printed on the same line is captured.
        line_records = [] if col_records else extract_lines_with_backbone(
            text, tables, backbone, include_pats,
            po_number, page_num, source_file,
            config.get("max_code_length", 24),
            review=review_items
        )

        if col_records or line_records:
            page_records = col_records or line_records
        else:
            # Priority 2: table structure with header detection
            table_records = extract_from_table(
                tables, config, include_pats, exclude_pats,
                ref_codes, po_number, page_num, source_file
            )
            # Priority 3: loose pattern matching
            text_records = []
            if not table_records:
                text_records = extract_from_text(
                    text, config, include_pats, exclude_pats,
                    ref_codes, po_number, page_num, source_file
                )
            page_records = table_records + text_records

        all_records.extend(page_records)

    # Prepend zone records to preserve their priority
    if zone_records:
        for r in zone_records:
            r["po_number"] = doc_po
        all_records = zone_records + all_records

    # Resolve every code against the backbone BEFORE de-duplicating, so an OCR
    # misread and its correct twin collapse into one identity instead of
    # surviving as two different-looking codes on the same order line.
    normalize_output_codes(all_records, backbone)

    unique_records = dedupe_records(all_records)

    # Apply the PO number to all records
    if doc_po:
        for r in unique_records:
            if not r.get("po_number"):
                r["po_number"] = doc_po

    # Accuracy gate: confirmed rows stay, plausible unlisted ones stay and
    # are flagged, the rest move to the review list. One implementation for
    # every path - see _apply_accuracy_gate().
    if backbone.enabled:
        unique_records = _apply_accuracy_gate(
            unique_records, backbone, review_items, source_file, doc_po,
            zone_diag=zone_diag)

    # Recover money the same way in pattern / hybrid mode
    enrich_money_from_pages(unique_records, pages, backbone)

    # A price that lost its leading digit is REPORTED, never repaired - the
    # same rule the missing quantity follows. See _flag_lost_leading_digit().
    for note in _flag_lost_leading_digit(unique_records, review_items):
        zone_diag.append(note)

    # And so is a line whose printed figures disagree: qty x price != amount
    # means the column assignment or a digit went wrong somewhere, and the
    # numbers alone cannot say which. See _check_line_arithmetic().
    for note in _check_line_arithmetic(unique_records, review_items,
                                       source_file, doc_po):
        zone_diag.append(note)

    # exclude_patterns are honoured on every path (see apply_exclusions)
    unique_records, excluded = apply_exclusions(unique_records, exclude_pats)
    if excluded:
        zone_diag.append(
            f"{len(excluded)} code(s) dropped by exclude_patterns: "
            f"{', '.join(sorted(set(excluded))[:8])}")

    ref_matched   = sum(1 for r in unique_records if "reference" in r.get("match_type", ""))
    paren_matched = sum(1 for r in unique_records if "paren" in r.get("match_type", ""))
    zone_matched  = sum(1 for r in unique_records
                        if "zone" in r.get("match_type", "")
                        and "reference" not in r.get("match_type", "")
                        and "paren" not in r.get("match_type", ""))
    pattern_matched = len(unique_records) - ref_matched - paren_matched - zone_matched

    # Determine extraction mode
    if zones and zone_records:
        mode = "hybrid"           # zone + automatic extraction
    elif zones:
        mode = "zone_fallback"    # zone defined but empty; auto extraction used
    else:
        mode = "pattern"

    if not backbone.enabled and unique_records:
        zone_diag.append(
            "No backbone list loaded - results rely on pattern guessing. "
            "Add your codes in [Material Codes] for reliable extraction."
        )

    if not unique_records:
        zone_diag.append(
            "No codes were extracted. "
            "1) Define a Material Code zone in Zone Templates, "
            "2) adjust material_code_patterns in config.json, or "
            "3) add your real codes to material_codes_reference.csv."
        )

    result = {
        "source_file": source_file,
        "md5": md5_hash,
        "config_sig": cfg_sig,
        "records": unique_records,
        "po_number": doc_po,
        "customer": matched_customer,
        "extraction_mode": mode,
        "review": _dedupe_review(review_items),
        "ocr_used": used_ocr,
        "ocr_engine": (ocr_engine_name()
                       if (used_ocr and OCR_MODULE_AVAILABLE) else ""),
        "diagnostics": zone_diag,
        "processed_at": datetime.now().isoformat(),
        "page_count": total,
        "stats": {
            "total": len(unique_records),
            "reference_matched": ref_matched,
            "paren_matched": paren_matched,
            "zone_matched": zone_matched,
            "pattern_matched": pattern_matched,
            "review_count": len(review_items),
            "backbone_size": len(backbone),
        }
    }

    save_cache(cache_path, result)
    update_index(pdf_path, md5_hash, len(unique_records), doc_po)

    if progress_callback:
        progress_callback(
            100,
            f"Complete: {len(unique_records)} code(s) "
            f"(zone:{zone_matched} / ref:{ref_matched} / pattern:{pattern_matched})"
        )

    return result
