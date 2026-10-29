# _legacy - the retired local extraction engine

**Nothing in this folder is imported by OrderFlow.** It is kept so a reading
can be compared against it, and so any of it can be recovered if the Claude
API turns out to be worse on a particular layout.

The README that used to be here (the engine's own) is preserved below under
"Original README".

## Why it was retired

PO reading moved to the Claude API (`../claude_engine.py`): the document is
sent as a PDF and the ordered line items come back as JSON. That removed the
need for everything in this folder.

| File | Lines | What it did |
|---|---|---|
| `engine.py` | 7,193 | the whole local engine: OCR abstraction, page rasterising, word coordinates → rows/columns/cells (`table_parser`), the code matcher (`code_matcher`) and ~3,100 lines of orchestration with four fallback paths |
| `devtools.py` | 3,163 | its regression suite and the zone-template editor |
| `engine_audit.py` | 568 | `sum(qty x price)` vs each PO's printed total |
| `engine_baseline.py` | 323 | snapshot diff over `..\data_upload\*.pdf` |
| `engine_baseline.json` | — | the pinned snapshot it diffed against |
| `customer_templates.json` | — | per-customer zone rectangles; the API reads layout itself |
| `config.json` | — | regexes, OCR and column keywords. Superseded by `../claude_config.json` |
| `install_ocr.bat`, `devtools.bat` | — | entry points for the above |

## What survived

`code_matcher`'s matching rules were **not** a reading concern, they are a
master-data concern, so they were lifted out into `../code_rules.py` and are
still used - by the extraction gate, by `material_master.code_rules()` and by
`normalise_to_master()`. That is the part that decides whether a material code
is real, and it was never the part that found it.

## Running it again

It needs the packages the project's `requirements.txt` no longer installs:

```
pip install pdfplumber pymupdf pypdf pypdfium2 rapidocr-onnxruntime opencv-python-headless
cd CodeExtract\_legacy
python devtools.py
```

It reads `config.json` and `customer_templates.json` next to itself, and
`material_codes_reference.csv` one folder up - so copy the CSV beside it, or
point `REFERENCE_PATH` at it, before expecting real results.

---

# Original README

# Samsung Material Code Extractor (engine)

**Samsung Electronics | Home Appliance Division | North America Sales**

Extracts **Material Codes** and **PO Numbers** from unstructured PDF purchase
orders. This folder is the extraction **engine** — the standalone GUI/CLI it
originally shipped with has been retired. In normal use nobody runs anything
in this folder directly: the OrderFlow dashboard calls into it through the
**EXTRACTOR BRIDGE** section of `src\of_pdf.py` whenever a PO is Confirmed
from mail or converted with Quick Convert.
