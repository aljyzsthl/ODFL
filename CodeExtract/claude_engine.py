r"""claude_engine.py - PO extraction by the Claude API.

Replaces the 7,200-line local engine (now `CodeExtract/_legacy/engine.py`).
Where the old engine rasterised, OCR'd, found header rows, built column bounds
and assigned cells by geometry, this module sends the document to Claude and
gets back the ordered line items as JSON.

WHAT DID NOT CHANGE - the two rules the project is built on
----------------------------------------------------------
1. **Extraction proposes, master data decides.** Claude's material code is a
   *candidate*. `code_rules.BackboneIndex` looks it up in
   `material_codes_reference.csv`; anything it cannot confirm is moved to
   `review` and kept out of `records`. A code that does not exist must never
   reach ERP. (docs/HANDOVER.md 4.0, principle 1)

2. **Never invent a value, never repair one.** Numbers are published exactly
   as the document prints them. `qty x unit_price == amount` is checked and a
   mismatch is *reported* - it is never used to overwrite anything. This is the
   2026-10 decision to remove `reconcile()` / `finalize_money()` and it still
   stands. (HANDOVER 4.0, principle 3 and the 2.2 note)

WHAT THIS REPLACES
------------------
    ocr_engine    RapidOCR / Tesseract / EasyOCR + the page rasteriser  (~540 lines)
    table_parser  word coordinates -> rows / columns / cells          (~718 lines)
    code_matcher  BackboneIndex + candidate detection                 (~875 lines)  -> code_rules.py keeps the matching rules
    extractor     orchestration, templates, zone boxes, 4 fallback paths (~3,100 lines)

One path now, not four - and not two either: a PDF and a DRM document whose
text had to be recovered both go through the same call, which retires the
"A/B routes must agree" problem entirely.

ENTRY POINTS
------------
    extract_material_codes(pdf_path, force=False, customer_name="", progress_callback=None) -> dict
    from_text(text, source="")                                        -> dict

The result dict has the same shape the dashboard has always consumed
(docs/HANDOVER.md 4.7); read every field with `.get()`.

ENDPOINT ("SEA Claude API Guide")
--------------------------------
This talks to the SEA private inference endpoint, NOT api.anthropic.com. It
implements the standard Messages API, but two things differ and both are
configurable:

    base_url    claude_config.json > Settings screen > $ANTHROPIC_BASE_URL
                default https://seadev-claude.sec.samsung.net:8081
    auth token  Settings screen ("PO reading") > $ANTHROPIC_AUTH_TOKEN >
                $ANTHROPIC_API_KEY > CodeExtract/.api_key

    POST {base_url}/v1/messages
    Authorization: Bearer <token>        <- not x-api-key
    anthropic-version: 2023-06-01
    content-type: application/json

⚠️ The token is NOT shipped with this program. It has to be pasted in once.

Standard library only - no pip package, so a locked-down corporate PC needs
nothing installed to run this.
"""

import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from code_rules import BackboneIndex

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "claude_config.json"
REFERENCE_PATH = HERE / "material_codes_reference.csv"
CACHE_DIR = HERE / "data_cache"
SETTINGS_PATH = HERE.parent / "config" / "settings.json"

API_VERSION = "2023-06-01"

# The endpoint this project talks to. It is NOT api.anthropic.com: it is the
# SEA private inference endpoint from "SEA Claude API Guide", which implements
# the standard Messages API but authenticates differently (see `auth_header`).
#
# Both of the two things the guide asks you to configure are settings, and both
# are overridable in three places (first one found wins):
#
#   base_url   config/settings.json claude.base_url (Settings screen)
#              > $ANTHROPIC_BASE_URL > claude_config.json > DEFAULT_BASE_URL
#   auth token config/settings.json claude.api_key (Settings screen)
#              > $ANTHROPIC_AUTH_TOKEN > $ANTHROPIC_API_KEY > .api_key
#
# The Settings screen wins over both environment variables, for both values:
# a token pasted once has to keep working on a machine that also has a stale
# $ANTHROPIC_AUTH_TOKEN exported in its profile.
#
# ⚠️ THE TOKEN IS NOT INCLUDED ANYWHERE - IT HAS TO BE PASTED IN. Paste it on
# the Settings screen under "PO reading", or set $ANTHROPIC_AUTH_TOKEN. Without
# it every PO comes back with zero codes and no error, which is why
# `_load_module` refuses to run without one.
DEFAULT_BASE_URL = "https://seadev-claude.sec.samsung.net:8081"
MESSAGES_PATH = "/v1/messages"

# Exactly the IDs the guide lists, with the guide's own notes. Anything else is
# not offered by this endpoint, and a wrong ID comes back as a 400 that says
# nothing useful - so the list is published in the error message instead.
KNOWN_MODELS = {
    "claude-sonnet-5": "Default / general-purpose (1M context)",
    "claude-opus-5": "Higher-capability tier (1M context)",
    "claude-sonnet-4-6": "Previous-generation Sonnet (1M context)",
    "claude-haiku-4-5": "Fastest / lowest-latency tier",
}

DEFAULTS = {
    # The guide's "Default / general-purpose" model, and the one it shows in
    # both examples. Available: claude-sonnet-5, claude-opus-5,
    # claude-sonnet-4-6, claude-haiku-4-5.
    "model": "claude-sonnet-5",
    "base_url": DEFAULT_BASE_URL,
    # The OUTPUT budget, not the document size. One line item is ~100 tokens
    # (nine fields, `source_line` being most of it), so a one-page PO needs a
    # few hundred and a four-PO bundle of 88 lines needs ~9,000. 8,000 was the
    # old value and it cut exactly those bundles off mid-JSON - see `_call()`.
    "max_tokens": 16_000,
    # A truncated answer is retried once with double the room, up to this. The
    # endpoint accepts more, but a PO that needs 32k is a sign the document
    # should be split, so this is a ceiling and not a target.
    "max_tokens_ceiling": 32_000,
    "timeout_sec": 180,
    "max_pdf_bytes": 20_000_000,     # request limit is 32 MB
    "max_input_chars": 200_000,      # recovered text (DRM path)
    "prompt_version": 1,
}


# ──────────────────────────────────────────────
# Config and credentials
# ──────────────────────────────────────────────
def load_config() -> dict:
    """claude_config.json over DEFAULTS, with the Settings screen's model on top.

    The model can be picked from a dropdown on the Settings screen, and that
    choice wins over the file: it is the thing the operator just changed, so
    having a value in `claude_config.json` silently outrank it would make the
    dropdown look broken. An unknown ID is ignored rather than sent - the
    endpoint answers a bad model with a bare 400.
    """
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    chosen = str((_claude_settings() or {}).get("model") or "").strip()
    if chosen and chosen in KNOWN_MODELS:
        cfg["model"] = chosen
    return cfg


def config_signature() -> str:
    """Changes whenever anything that can change a result changes, so the
    cache cannot hand back a reading taken under a different model, prompt or
    material-code list.

    The PROMPT ITSELF is hashed, not just `prompt_version`. Hashing the version
    number alone meant editing `_SYSTEM` - say, relaxing "never recalculate" -
    left every cached reading looking valid, so the edit appeared to do
    nothing. That is the worst possible feedback: the change is real, the
    result is stale, and nothing says so. `prompt_version` stays available as a
    deliberate manual nudge, but it is no longer load-bearing.
    """
    h = hashlib.md5()
    try:
        h.update(CONFIG_PATH.read_bytes())
    except Exception:
        pass
    try:
        h.update(REFERENCE_PATH.read_bytes())
    except Exception:
        pass
    # _SYSTEM and _TOOL are defined further down the file; look them up at call
    # time so this stays correct wherever it sits.
    for part in (globals().get("_SYSTEM", ""),
                 globals().get("_USER_PDF", ""),
                 json.dumps(globals().get("_TOOL", {}), sort_keys=True)):
        h.update(str(part).encode("utf-8"))
    h.update(str(DEFAULTS["prompt_version"]).encode())
    # Which model read the document is part of the result, and it can be picked
    # on the Settings screen - where a change touches no file this hash reads.
    h.update(str(load_config().get("model", DEFAULTS["model"])).encode())
    return h.hexdigest()


def _user_settings() -> dict:
    """config/settings.json, or {} when it cannot be read."""
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _claude_settings() -> dict:
    """The `claude` block of config/settings.json - what the Settings screen writes."""
    block = _user_settings().get("claude") or {}
    return block if isinstance(block, dict) else {}


def api_key() -> str:
    """The auth token, in the order the Settings screen promises.

    The stored setting comes FIRST. It used to be read after the environment
    variables, which contradicted the contract at the top of this file and
    quietly defeated the screen: a machine with a stale $ANTHROPIC_AUTH_TOKEN
    exported in its profile ignored every token pasted in Settings, so the paste
    looked like it had not been saved. An environment variable is now what it
    says on the box - a fallback for a machine nobody configures by hand.
    """
    block = _claude_settings()
    for field in ("api_key", "token", "auth_token"):
        k = str(block.get(field) or "").strip()
        if k:
            return k
    for env in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
        k = (os.environ.get(env) or "").strip()
        if k:
            return k
    try:
        return (HERE / ".api_key").read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def base_url() -> str:
    """The endpoint root, without a trailing slash.

    Order: Settings screen > $ANTHROPIC_BASE_URL > claude_config.json >
    DEFAULT_BASE_URL. The config file is the *shipped default*, so it sits
    below the two places an operator actually edits - otherwise a value in the
    file would silently pin the address and the Settings box would look broken.

    A value ending in /v1/messages is accepted too (people paste the full URL)
    and trimmed back to the root.
    """
    url = ""
    sources = (_claude_settings().get("base_url"),
               os.environ.get("ANTHROPIC_BASE_URL"),
               load_config().get("base_url"))
    for candidate in sources:
        if str(candidate or "").strip():
            url = str(candidate).strip()
            break
    url = (url or DEFAULT_BASE_URL).rstrip("/")
    for tail in (MESSAGES_PATH, "/v1/messages/", "/v1"):
        if url.endswith(tail):
            url = url[:-len(tail)]
    return url.rstrip("/")


def messages_url() -> str:
    return base_url() + MESSAGES_PATH


def auth_header(key: str = "") -> dict:
    """The one header that differs from the public API.

    The guide is explicit: `Authorization: Bearer <token>`, "auth_token, not
    api_key". Sending `x-api-key` here would be rejected - which is exactly the
    mistake this function exists to prevent.
    """
    return {"Authorization": "Bearer " + (key or api_key())}


def status_summary() -> dict:
    """What the console prints about the extractor on start-up."""
    cfg = load_config()
    return {
        "available": bool(api_key()),
        "endpoint": messages_url(),
        "model": cfg.get("model", DEFAULTS["model"]),
        "api_key_set": bool(api_key()),
        "reference_codes": len(load_reference_codes()),
    }


# ──────────────────────────────────────────────
# The reference list (master data)
# ──────────────────────────────────────────────
_REF_CACHE = {"sig": None, "ref": None, "index": None}


def load_reference_codes() -> dict:
    """material_codes_reference.csv -> {material_code: {description, category}}.

    A generated mirror of Master Data > Material Codes, rebuilt by
    `material_master.sync_to_engine()` on every dashboard start. It carries
    each FULL SKU **and** the unambiguous short SKUs, so a code as a PO prints
    it is confirmed on sight.
    """
    try:
        sig = (REFERENCE_PATH.stat().st_mtime, REFERENCE_PATH.stat().st_size)
    except Exception:
        return {}
    if _REF_CACHE["sig"] == sig:
        return _REF_CACHE["ref"] or {}

    ref = {}
    try:
        with open(REFERENCE_PATH, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(",", 2)
                if parts and parts[0].strip():
                    code = parts[0].strip().strip('"').upper()
                    if code and code != "MATERIAL_CODE":
                        ref[code] = {
                            "description": parts[1].strip().strip('"')
                            if len(parts) > 1 else "",
                            "category": parts[2].strip().strip('"')
                            if len(parts) > 2 else "",
                        }
    except Exception:
        return {}

    _REF_CACHE["sig"] = sig
    _REF_CACHE["ref"] = ref
    _REF_CACHE["index"] = BackboneIndex(ref)
    return ref


def get_backbone() -> BackboneIndex:
    """The shared index over the reference list. Empty when there is no list -
    the caller then publishes what was read and says so, rather than dropping
    every line."""
    load_reference_codes()
    if _REF_CACHE["index"] is None:
        _REF_CACHE["index"] = BackboneIndex({})
    return _REF_CACHE["index"]


# ──────────────────────────────────────────────
# The API call
# ──────────────────────────────────────────────
# One ORDER: the number, the total, the two dates, the delivery address and
# its own lines. This is the unit the ERP upload carries per row (column A is
# the P/O No.), which is why a document holding several POs is returned as
# several of these instead of one merged order - see `orders` below.
_ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "po_number": {
            "type": "string",
            "description": "The purchase order number of THIS order, as "
                           "printed - usually the 'P/O #' or 'Order No' at the "
                           "top of its page. Empty string when it prints none."},
        "document_total": {
            "type": "string",
            "description": "THIS order's printed grand total, digits only. "
                           "Not the sum of the document when the document "
                           "holds several orders. Empty string when it prints "
                           "none."},
        "po_date": {
            "type": "string",
            "description": "The date THIS purchase order was issued, as "
                           "printed, in YYYY-MM-DD. This is the 'PO Date' / "
                           "'Ordered' / 'Order Date' in its header - NOT the "
                           "requested / required delivery date and NOT the "
                           "date the email arrived. Empty string when it "
                           "prints none."},
        "rdd": {
            "type": "string",
            "description": "THIS order's REQUIRED DELIVERY DATE, in "
                           "YYYY-MM-DD. The document may label it 'Required "
                           "Date', 'Required Delivery Date', 'RDD', 'ETA "
                           "Date', 'Requested Delivery', 'Delivery Date' or "
                           "'Ship Date'. Empty string when it prints none - "
                           "do NOT use the PO date as a stand-in."},
        "ship_to": {
            "type": "object",
            "description": "THIS order's DELIVERY address as printed. Empty "
                           "strings when it prints none. This is the ship-to "
                           "/ deliver-to block, not the bill-to block and not "
                           "the seller's own address.",
            "properties": {
                "name": {"type": "string"},
                "address_lines": {
                    "type": "array",
                    "description": "The street lines exactly as printed, "
                                   "top to bottom, at most 5. Do not put "
                                   "the city / state / postcode here.",
                    "items": {"type": "string"}},
                "city": {"type": "string"},
                "state": {"type": "string",
                          "description": "Two-letter state or province "
                                         "code when the document prints one."},
                "postal_code": {"type": "string"},
            },
            "required": ["name", "address_lines", "city", "state",
                         "postal_code"],
        },
        "lines": {
            "type": "array",
            "description": "One object per ordered line item OF THIS ORDER, "
                           "in the order the document prints them.",
            "items": {
                "type": "object",
                "properties": {
                    "material_code": {
                        "type": "string",
                        "description": "The ordered line's material code / SKU "
                                       "only. This includes product, installation, "
                                       "delivery, recycling and other service SKUs. "
                                       "Preserve a complete L-INST code: printed "
                                       "'DSW- L-INST/E3-DW, Samsung, Dishwasher "
                                       "install' means L-INST/E3-DW; DSW- is a "
                                       "category prefix but L-INST is part of the "
                                       "SKU. If an ITEM ID prefixes a product model "
                                       "with store segments, omit those segments: "
                                       "printed 51E-863-RT16A6195SR means "
                                       "RT16A6195SR, and printed 'DSW-SSI Samsung "
                                       "DW80CG4021SRAA 53 dBA' means "
                                       "DW80CG4021SRAA."},
                    "description": {"type": "string"},
                    "quantity": {"type": "string"},
                    "unit": {"type": "string"},
                    "unit_price": {"type": "string"},
                    "amount": {"type": "string"},
                    "sales_tax": {
                        "type": "string",
                        "description": "The tax printed in THIS line's own "
                                       "tax column ('Sales tax', 'Tax'), "
                                       "digits only. Empty string when the "
                                       "document has no such column or "
                                       "prints none for the line. It is NOT "
                                       "part of unit_price - the printed "
                                       "amount already includes it."},
                    "po_line": {"type": "string"},
                    "page": {"type": "string"},
                    "source_line": {"type": "string"},
                },
                "required": ["material_code", "description", "quantity",
                             "unit", "unit_price", "amount", "sales_tax",
                             "po_line", "page", "source_line"],
            },
        },
    },
    "required": ["po_number", "document_total", "po_date", "rdd",
                 "ship_to", "lines"],
}

_TOOL = {
    "name": "return_line_items",
    "description": "Return the purchase order(s) or work order(s) read from the "
                   "document, each with its own number, total, dates, delivery "
                   "address and ordered line items.",
    "input_schema": {
        "type": "object",
        "properties": {
            "orders": {
                "type": "array",
                "description": "One entry per DISTINCT purchase order in the "
                               "document, in the order they appear. A document "
                               "that is a single order returns exactly one "
                               "entry - that is the normal case. Never merge "
                               "two order numbers into one entry and never "
                               "split one order number across two.",
                "items": _ORDER_SCHEMA,
            },
        },
        "required": ["orders"],
    },
}

_CORE_SYSTEM = """You extract structured orders for Samsung home appliances.

UNIVERSAL CONTRACT - apply these rules to every document.

1. INVENTORY BEFORE LINES. Inspect every page in sequence and inventory its explicit order number. Return exactly one `orders` entry per DISTINCT explicit order number, in document order. A continuation page that repeats or omits the current number stays in that order. A new explicit number starts a new order. Never merge two numbers or split one number. A shared buyer block or letterhead is not an order.

2. KEEP OWNERSHIP LOCAL. A line, date, total and delivery address belong to the nearest explicit order header above them. Several orders in one file may have different values. Do not copy the first order's header into later orders, and do not deduplicate equal lines across different orders.

3. RETURN ORDERED LINES ONLY. Return one line for each product or coded service/add-on that was actually ordered. Include installation, delivery and recycling when the row has its own SKU and quantity and/or price. Skip subtotal, total, tax-summary, discount, uncoded freight, field-label and other summary rows. Skip a model mentioned only inside another item's prose. A per-line tax COLUMN is data; a standalone tax ROW is not an ordered line.

4. TRANSCRIBE, DO NOT REPAIR. Copy printed values without recalculating, rounding or guessing. For numeric fields only, remove currency marks, thousands separators and spaces while preserving every digit and decimal place. Convert printed dates to YYYY-MM-DD without changing the day. If a field is absent, return an empty string. Never derive a missing quantity, price, amount, date or total.

5. MATERIAL CODE. Return the ordered product or service SKU, not a vendor/category prefix, description word or customer reference. Preserve the complete SKU suffix, slash and hyphen spelling. `L-INST/...` is a real service SKU and must stay complete. Keep the whole printed row in `source_line`; downstream master data independently validates the code, so do not choose a plausible model that the row does not print.

6. MONEY FIELDS. `quantity` is units ordered; `unit_price` is one unit; `amount` is the printed extended line total. If only one money value is printed, put it in `unit_price` and leave `amount` empty. `sales_tax` is only the value in THIS line's own Sales tax/Tax column. If no such column/value exists, return an empty string. An Amount may already include printed tax; never net it down or gross it up.

7. ORDER HEADER. `po_number` is that order's explicit order number. `document_total` is its printed Grand total/Total/PO Total/PO Cost. `po_date` is the issue/order date. `rdd` is the requested delivery date, not the issue date. `ship_to` is the DELIVERY destination, never bill-to, seller or head-office data. Put up to five street lines in `address_lines`, and city/state/postal code in their own fields.

8. AUDIT FIELDS. `page` is the 1-based printed page number as a string. `source_line` is the complete row copied onto one line. Before returning, verify the count of `orders` against the distinct explicit order numbers inventoried in rule 1.

DOCUMENT PROFILE ISOLATION. The profiles below are exceptions to layout, not replacements for the universal contract. Apply a profile only when its identifying cues are visibly present. Never transfer one profile's column meanings, prefixes, number parsing or address layout to another document. If no special profile matches, use STANDARD PO."""

_PROFILE_STANDARD_PO = """PROFILE: STANDARD PO

Identifying cues: conventional P/O #, P/O No, PO Number or Order No header and a normal item table.

- Read `po_number` beside the explicit order-number label. Common date labels include PO Date, P/O Date, Order Date and Ordered. Common RDD labels include Required Date, Required Delivery Date, RDD, ETA Date, Requested Delivery, Delivery Date and Delivery On.
- Read delivery data from the block labelled Ship To, Deliver To, Ship-To or Consignee.
- A retailer ITEM ID may join a store prefix to the Samsung model. `51E-863-RT16A6195SR` means material code `RT16A6195SR`; preserve the full printed ID only in `source_line`. Do not strip an arbitrary hyphenated prefix unless the row clearly prints the Samsung model as its final identifier."""

_PROFILE_WORK_ORDER = """PROFILE: BUILDER WORK ORDER

Identifying cues: the document is explicitly titled WORK ORDER and prints Work order/WO fields, often with appliance rows whose descriptions start with category prefixes such as DSW-, MCR- or RNG-.

- WORK ORDER NUMBER: use the value in the dated detail block beside Work order date/Revision date, including its revision suffix. `Work order 182555832-2` means `182555832-2`. A separate bare number under the large Work order letterhead, such as `10028814`, is a job/reference, not `po_number`.
- Each appliance group may contain three rows. `DSW- Included Dishwasher - Samsung` is an uncoded bundled-appliance placeholder: skip it. `DSW- L-INST/E3-DW...` is the ordered installation service: return `L-INST/E3-DW`. `DSW-SSI Samsung DW80CG4021SRAA...` is the appliance: return `DW80CG4021SRAA`. The same layout may use other three-letter category prefixes; remove the category prefix and the word Samsung, but preserve the complete model/service SKU.
- A row labelled Requested Delivery Date is a FIELD LABEL, not an item. Its following value, for example `RDD 11.30.26`, is `rdd` = `2026-11-30`.
- The delivery address may be unlabelled under the Work order heading. A community/phase/lot line such as `Parkside II - Edgewood at Peach Avenue/6379/069` is the job name, not a street. The following street and `City, ST ZIP` are the delivery address.
- If the item table has a Sales tax column, place that line's value in `sales_tax`. The printed Amount already INCLUDES that tax; copy both as printed."""

_PROFILE_CMH = """PROFILE: CMH / CLAYTON PURCHASE ORDER

Identifying cues: CMH/Clayton branding, a `PO#:` value containing a department and order number, and an item table with both `Item Number` and `VIN`/Model/Mfr Part columns.

- `PO#: 00952 - 2337110` contains department `00952` (also printed as `Dept 00952`) and order number `2337110`. Return only `2337110` as `po_number`.
- `Item Number` is the builder's customer part, for example `025-00100-00398`; it is not the material code. The Samsung model is in `VIN`, Model or Mfr Part. In a row containing `025-00100-00398 ... RS27T5201SR/AA`, return `RS27T5201SR/AA` and retain the customer part only inside `source_line`.
- `Date Needed` is `rdd`. `PO Total` or `PO Cost` is `document_total`.
- The Ship To block begins with a site name. `Clayton Athens / 3429 State Highway 31 - West / Athens, TX 75751` means name `Clayton Athens`, street `3429 State Highway 31 - West`, city `Athens`, state `TX`, postal code `75751`.
- A Taxable checkbox is not a numeric per-line tax. Leave `sales_tax` empty unless the line table prints an actual tax amount column."""

_SYSTEM = "\n\n".join((_CORE_SYSTEM, _PROFILE_STANDARD_PO,
                         _PROFILE_WORK_ORDER, _PROFILE_CMH))

_USER_PDF = ("Read every labelled PDF page before extracting. Inventory the "
             "explicit order numbers first, then return every distinct order "
             "with only its own lines and header values. Use the universal "
             "contract and apply only the matching document profile; do not "
             "transfer a special profile's conventions to another layout.")
_USER_TEXT = ("Below is text recovered from an order document, so there are "
              "no page coordinates and columns may have run together. It may "
              "hold more than one order. Apply the universal contract and "
              "only the visibly matching document profile; return every "
              "order with its own header and ordered lines.\n\n<po_text>\n%s\n"
              "</po_text>")


def _plain_error(code: int, detail: str, url: str) -> str:
    """Turn an HTTP failure into something an operator can act on.

    A private endpoint fails differently from the public one, and "HTTP 401:
    {"type":"error"...}" on its own does not say which of the four possible
    mistakes was made. The three that are actually likely are named.
    """
    d = (detail or "").strip()
    low = d.lower()
    if code in (401, 403):
        return (f"the endpoint rejected the key (HTTP {code}) at {url}. "
                "Check the token on the Settings screen - it is sent as "
                "'Authorization: Bearer <key>', not as x-api-key. " + d)
    if code == 404:
        return (f"no API at {url} (HTTP 404). The base URL is probably wrong - "
                "it should be the endpoint root from the API guide, with "
                "/v1/messages added by this program. " + d)
    if code == 400 and ("model" in low or "not found" in low):
        return (f"the endpoint does not offer that model (HTTP 400). "
                f"Available: {', '.join(KNOWN_MODELS)}. " + d)
    if code == 400 and ("document" in low or "pdf" in low or "media" in low):
        return ("the endpoint refused the PDF itself (HTTP 400). This "
                "deployment may accept text only - report it, because without "
                "PDF input a scanned PO cannot be read. " + d)
    if code == 413:
        return ("the document is larger than the endpoint accepts (HTTP 413). "
                "Split the PO or raise max_pdf_bytes only if the server "
                "allows it. " + d)
    return f"HTTP {code} from {url}: {d or 'no detail'}"


def _post(payload: dict, cfg: dict, url: str = "", key: str = "",
          attempts: int = 3) -> dict:
    """POST one message to the endpoint. Retries a rate limit or a server
    error; never retries a bad request, because it will fail identically.

    `url` and `key` are only passed by the Settings screen's Test button, so it
    can try a value that has been typed but not yet saved. `attempts=1` there
    too: a Test button that sits for nine seconds while it retries a network
    error looks like a hung window, and pressing it again is free.
    """
    key = key or api_key()
    if not key:
        raise RuntimeError(
            "no API key stored. Paste one on the Settings screen under "
            '"PO reading", or set the environment variable '
            "ANTHROPIC_AUTH_TOKEN.")

    url = url or messages_url()
    body = json.dumps(payload).encode("utf-8")
    timeout = float(cfg.get("timeout_sec", DEFAULTS["timeout_sec"]))
    last = ""
    attempts = max(1, int(attempts))
    for attempt in range(attempts):
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers=dict({"content-type": "application/json",
                          "anthropic-version": API_VERSION},
                         **auth_header(key)))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:400]
            except Exception:
                pass
            last = _plain_error(e.code, detail, url)
            if e.code not in (429, 500, 502, 503, 529) or attempt == attempts - 1:
                raise RuntimeError(last) from None
            time.sleep(2 ** attempt * 3)
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            if "CERTIFICATE" in str(reason).upper() or "SSL" in str(reason).upper():
                raise RuntimeError(
                    f"TLS verification failed for {url} ({reason}). The "
                    "corporate root certificate is probably not installed on "
                    "this PC; ask IT, and do NOT work around it by disabling "
                    "verification.") from None
            last = f"could not reach {url}: {reason}"
            if attempt == attempts - 1:
                raise RuntimeError(last) from None
            time.sleep(2 ** attempt * 3)
    raise RuntimeError(last or f"the call to {url} failed")


def _resolve_url(raw: str) -> str:
    """A typed endpoint -> the full /v1/messages URL."""
    url = (raw or "").strip().rstrip("/")
    for tail in (MESSAGES_PATH, "/v1/messages/", "/v1"):
        if url.endswith(tail):
            url = url[:-len(tail)]
    return (url.rstrip("/") or base_url()) + MESSAGES_PATH


def test_connection(cfg: dict = None, base_url_override: str = "",
                    key_override: str = "") -> dict:
    """One tiny round trip, shaped for the Settings screen's Test button.

    Deliberately NOT an extraction: this answers "is the endpoint, the key and
    the model OK?" without spending a PO's worth of tokens or touching the
    cache. It goes through the same `_post` as a real read, so a green result
    here means the configured path works.

    Returns {ok, endpoint, model, latency_ms, reply, error, hint} - the same
    keys the Outlook test returns, so the page renders both the same way.
    """
    cfg = cfg or load_config()
    model = cfg.get("model", DEFAULTS["model"])
    url = _resolve_url(base_url_override)
    key = (key_override or "").strip()
    out = {"ok": False, "endpoint": url, "model": model,
           "latency_ms": 0, "reply": "", "error": "", "hint": ""}
    started = time.time()
    try:
        data = _post({
            "model": model,
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "Reply with the single "
                                                     "word: ready"}],
        }, dict(cfg, timeout_sec=min(60, float(cfg.get("timeout_sec", 180)))),
            url=url, key=key, attempts=1)
    except Exception as e:
        out["error"] = str(e)
        out["latency_ms"] = int((time.time() - started) * 1000)
        # The hint has to match the failure. A network error and a rejected key
        # look nothing alike, and telling someone to re-paste a correct key is
        # worse than saying nothing.
        low = str(e).lower()
        if not (key or api_key()):
            out["hint"] = ("No key is stored. Paste the assigned token above "
                           "and test again.")
        elif ("could not reach" in low or "tunnel" in low
                or "timed out" in low or "ssl" in low or "certificate" in low
                or "refused" in low or "name or service" in low):
            out["hint"] = ("The address did not answer. Check the endpoint, "
                           "and whether this PC is on the network that can "
                           "reach it (VPN / internal). Nothing is wrong with "
                           "the saved key.")
        elif key and key != api_key():
            out["hint"] = ("That is the key you just typed. If it is right, "
                           "press Save - the test used it but did not store "
                           "it.")
        else:
            out["hint"] = ("If the key is right, check the endpoint address "
                           "and that this PC can reach it (VPN / internal "
                           "network, and the corporate root certificate).")
        return out

    out["latency_ms"] = int((time.time() - started) * 1000)
    text = "".join(b.get("text") or "" for b in (data.get("content") or [])
                   if b.get("type") == "text").strip()
    out["reply"] = text or "(empty reply)"
    out["model"] = data.get("model") or model
    out["ok"] = True
    if not text:
        out["error"] = "the endpoint answered but returned no text"
        out["ok"] = False
    return out


def _call(content_blocks: list, cfg: dict) -> dict:
    """One extraction call. Returns the tool input (the line items).

    The OUTPUT budget has to fit the DOCUMENT, not the model: every line costs
    roughly 100 tokens (nine fields, `source_line` being most of it), so a
    four-order scan of 88 lines needs ~9,000 and an 8,000 ceiling cut the answer
    off mid-JSON. A truncated `tool_use` block arrives with an EMPTY `input`,
    which looks exactly like "this document held no line items" - that is how a
    perfectly readable 4-PO PDF came back as "No material codes found"
    (2026-10-29). So `stop_reason` is read rather than assumed, and a cut-off
    answer is retried once with double the room instead of being reported as an
    empty document.
    """
    budget = int(cfg.get("max_tokens", DEFAULTS["max_tokens"]))
    ceiling = int(cfg.get("max_tokens_ceiling", DEFAULTS["max_tokens_ceiling"]))
    while True:
        payload = {
            "model": cfg.get("model", DEFAULTS["model"]),
            "max_tokens": budget,
            "system": _SYSTEM,
            "tools": [_TOOL],
            # Forced: the answer must be the structured line items, not prose
            # about them. Getting JSON back is what makes the gate below
            # possible.
            "tool_choice": {"type": "tool", "name": _TOOL["name"]},
            "messages": [{"role": "user", "content": content_blocks}],
        }
        data = _post(payload, cfg)
        for block in data.get("content") or []:
            if block.get("type") == "tool_use" and (block.get("input") or {}):
                return block.get("input") or {}
        stop = str(data.get("stop_reason") or "")
        used = (data.get("usage") or {}).get("output_tokens")
        if stop == "max_tokens":
            if budget < ceiling:
                budget = min(ceiling, budget * 2)
                continue
            raise RuntimeError(
                "the reading was cut off - the answer needed more than "
                f"{budget} output tokens"
                + (f" (used {used})" if used else "") +
                ". Split the document, or raise max_tokens_ceiling in "
                "CodeExtract/claude_config.json.")
        # No tool_use block and no truncation: the endpoint answered, but with
        # nothing this program can use (prose, an empty list, a refusal). That
        # is a reading with zero lines - which the caller already reports as
        # "nothing found" - and not a reason to throw away the document.
        return {}


def _pdf_blocks(path: str, cfg: dict) -> list:
    data = Path(path).read_bytes()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("this is not a PDF")
    limit = int(cfg.get("max_pdf_bytes", DEFAULTS["max_pdf_bytes"]))
    if len(data) > limit:
        raise RuntimeError(
            f"this PDF is {len(data) // 1024} KB; the limit for one document "
            f"is {limit // 1024} KB")
    return [
        {"type": "document",
         "source": {"type": "base64", "media_type": "application/pdf",
                    "data": base64.standard_b64encode(data).decode("ascii")}},
        {"type": "text", "text": _USER_PDF},
    ]


def _text_blocks(text: str, cfg: dict) -> list:
    limit = int(cfg.get("max_input_chars", DEFAULTS["max_input_chars"]))
    body = (text or "")[:limit]
    return [{"type": "text", "text": _USER_TEXT % body}]


# ──────────────────────────────────────────────
# Numbers - published as printed, never repaired
# ──────────────────────────────────────────────
_CURRENCY = re.compile(r"[$£€]")


def _clean_num(value) -> str:
    """Drop the currency mark and the thousands separator. The digits stay.

    '1,198.00' -> '1198.00' and '1060.0000' stays '1060.0000': removing the
    separator is not a change of value, but changing the digits would be, so
    nothing past the decimal point is ever touched. The result-dict contract
    (docs/HANDOVER.md 4.7) is strings with commas and $ removed.
    """
    s = str(value or "").strip()
    if not s:
        return ""
    return _CURRENCY.sub("", s).replace(" ", "").replace(",", "")


def _num(value):
    """A number for COMPARING only. Never written back into a record."""
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _tolerance(amount: float) -> float:
    """A scan loses a trailing zero, so a small relative slack is allowed
    before a mismatch is called. Absolute floor for cheap lines."""
    return max(0.02, abs(amount) * 0.002)


# ──────────────────────────────────────────────
# The accuracy gate
# ──────────────────────────────────────────────
_MODEL_TOKEN = re.compile(r"[A-Za-z0-9/]+")


def _master_codes_in(text: str, backbone) -> list:
    """The DISTINCT material codes the row itself prints.

    Some buyers do not put the Samsung model where a column title suggests.
    CMH/Clayton prints the builder's own part in `Item Number`
    (`025-00100-00398`) and the SAMSUNG MODEL in a column headed `VIN`
    (`RS27T5201SR/AA`). A reader that answers with the column called "Item
    Number" is not lying - it is answering the question the table looks like it
    asks - so the gate has to be able to find the model the row really carries.

    Recognition, not inference: a token is only returned when it independently
    exists in the Material Code master. Two different master codes in one row
    means the row does not say which one is the order, and the caller must
    decline rather than pick.
    """
    found = []
    for token in _MODEL_TOKEN.findall(text or ""):
        # A Samsung model has letters AND digits and is at least 6 characters;
        # that excludes "025", "00398", "24", "1000W" and the plain words of a
        # description, so a builder part number can never come back.
        if len(token) < 6:
            continue
        if not any(c.isdigit() for c in token):
            continue
        if not any(c.isalpha() for c in token):
            continue
        code, _kind = backbone.lookup(token)
        if code and code not in found:
            found.append(code)
    return found


def apply_gate(records: list, backbone: BackboneIndex,
               source_file: str = "", po_number: str = "") -> tuple:
    """Master data decides which codes are PUBLISHED - not which are shown.

    A code the list does not carry is a candidate, not an order line. Since
    2026-10-22 it is kept in `records` (so the operator can see the line, its
    quantity and its price) but flagged `needs_review`, and everything
    downstream treats that as "not included until a human ticks it"
    (`of_erp.prepare_lines`). It is also still listed in `review`, so the
    Code Learning card keeps offering it for approval.

    Showing is not publishing. The rule this protects is unchanged: a code the
    list does not carry never reaches ERP on its own, because a wrong model on
    an appliance PO is a truckload delivered to the wrong place.
    """
    kept, review = [], []
    for r in records:
        raw = str(r.get("material_code") or "").strip()
        recovered_from_source = False
        if not raw and backbone.enabled:
            # A vision model can read a service row and all of its values
            # correctly, yet leave material_code empty because the description
            # says "install" rather than naming a physical product. Recover only
            # an explicit L-INST token from that SAME returned row, and only
            # when the complete token independently exists in the Material
            # Code master.  This is recognition, not inference: descriptions
            # mentioning an appliance model still remain blank and reviewable.
            source = str(r.get("source_line") or "")
            for token in re.findall(
                    r"(?i)(?<![A-Z0-9])L-INST(?:[/_-][A-Z0-9_\-]+)+",
                    source):
                listed, _kind = backbone.lookup(token)
                if listed and re.sub(r"[^A-Z0-9]", "", listed.upper()).startswith(
                        "LINST"):
                    raw = token
                    r["material_code"] = token
                    recovered_from_source = True
                    break
        if not raw:
            r["needs_review"] = True
            r["match_type"] = "unconfirmed"
            r["review_reason"] = "no material code printed on this line"
            kept.append(r)
            review.append({"candidate": "", "score": 0, "match": "",
                           "reason": "no material code printed on this line",
                           "context": (r.get("source_line") or "")[:200],
                           "page": r.get("page"), "source_file": source_file,
                           "po_number": po_number})
            continue
        if not backbone.enabled:
            # No list on this machine: publish what was read and say so,
            # rather than silently dropping every line of every PO.
            r.setdefault("match_type", "unconfirmed")
            kept.append(r)
            continue
        code, kind = backbone.lookup(raw)
        matched_input = raw
        if not code and "-" in raw:
            # Some retailers print an ITEM ID such as
            # `51E-863-RT16A6195SR`: the final segment is the Samsung model,
            # while the leading groups are the retailer/category/supplier
            # key. This is not a heuristic rewrite: accept a shorter suffix
            # only when that exact suffix is independently present in the
            # Material Code master. Preserve the complete printed ID for
            # review/audit.
            parts = raw.split("-")
            for start in range(1, len(parts)):
                candidate = "-".join(parts[start:]).strip()
                suffix_code, suffix_kind = backbone.lookup(candidate)
                if suffix_code:
                    code, kind = suffix_code, "prefixed_" + suffix_kind
                    matched_input = candidate
                    r["raw_material_code"] = raw
                    break
        if not code:
            # Last resort, and the only one that looks OUTSIDE the column the
            # code was read from: a customer part number is not a material
            # code (2026-11-03). If the row itself prints exactly one code the
            # master knows - the Samsung model in CMH's "VIN" column, say - and
            # the answer we got is not in the master, take the row's own code
            # and keep the printed one for audit. Two candidates, or none:
            # stay in review, because the row then does not say which is the
            # order.
            alt = _master_codes_in(r.get("source_line") or "", backbone)
            if len(alt) == 1 and alt[0] != code:
                r["raw_material_code"] = raw
                code, kind = alt[0], "recovered_row"
                matched_input = alt[0]
        if not code:
            r["needs_review"] = True
            r["match_type"] = "unconfirmed"
            r["review_reason"] = "not in the Material Code list"
            kept.append(r)
            review.append({"candidate": raw, "score": 0, "match": "",
                           "reason": "not in the Material Code list",
                           "context": (r.get("source_line") or "")[:200],
                           "page": r.get("page"), "source_file": source_file,
                           "po_number": po_number})
            continue
        r["backbone_code"] = code
        r["match_type"] = ("source_line_" + kind
                           if recovered_from_source else kind)
        r["material_code"] = backbone.printed_form(code, matched_input)
        kept.append(r)
    return kept, review


def check_arithmetic(records: list, document_total: str) -> list:
    """`qty x unit_price == amount` needs no reference data and catches a
    large share of misread rows.

    It only ever REPORTS. The 2026-10 decision stands: a value is published as
    printed and the operator corrects it. A derived price that is wrong is
    worse than a price that is visibly missing.

    2026-11-02: a builder work order prints a per-line SALES TAX column and an
    Amount that already includes it, so `qty x price` is legitimately smaller
    than the printed amount on every appliance line. Comparing them alone
    produced four alarms on a perfectly read work order - and an alarm that
    fires on a good document is how the real one gets ignored. The printed tax
    is therefore part of the comparison, and the total is compared against the
    printed AMOUNTS where the document prints them (they are, by definition,
    what the printed total sums).
    """
    diags = []
    price_total = 0.0      # sum of qty x price (+ printed tax)
    amount_total = 0.0     # sum of the printed Amount column
    checked = 0
    any_amount = False
    every_line_has_amount = True
    for r in records:
        q, p, a = (_num(r.get("quantity")), _num(r.get("unit_price")),
                   _num(r.get("amount")))
        tax = _num(r.get("sales_tax")) or 0.0    # None when the line has none
        if q and p:
            price_total += q * p + tax
        if a:
            amount_total += a
            any_amount = True
        else:
            every_line_has_amount = False
        if not (q and p and a):
            continue
        checked += 1
        if abs(q * p + tax - a) > _tolerance(a):
            label = r.get("po_line") or r.get("material_code") or "?"
            diags.append(
                f"line {label} ({r.get('material_code')}): "
                f"{q:g} x {p:g}"
                + (f" + {tax:g} tax" if tax else "")
                + f" = {q * p + tax:.2f} but the document printed "
                f"{a:.2f}. Both are published as printed - check this line.")
    dt = _num(document_total)
    total = amount_total if (any_amount and every_line_has_amount) else price_total
    if dt and checked:
        if abs(total - dt) > _tolerance(dt):
            diags.append(
                f"the lines add up to {total:.2f} but the document prints a "
                f"total of {dt:.2f} - a line may have been missed.")
    return diags


# ──────────────────────────────────────────────
# Cache - one API call per document, not per click
# ──────────────────────────────────────────────
def file_md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_cache_path(name: str) -> Path:
    return CACHE_DIR / (Path(name).stem + ".json")


def load_cache(cache_path: Path):
    try:
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_cache(cache_path: Path, data: dict):
    """Written for `material_master.pending_reviews()`, which reads the
    `review` entries back out of these files for the Code Learning screen."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def dedupe_records(records: list) -> list:
    """Collapse identical rows. A repeated order line is real when the
    document gave it its own line number, so that is part of the identity.

    The order number is part of it too (2026-10-28): one PDF can carry several
    POs that order the SAME model in the SAME quantity at the SAME price on the
    SAME page. Those are different lines of different orders - dropping the
    second one as a duplicate deletes a real order.
    """
    seen, out = set(), []
    for r in records:
        key = (r.get("po_number"), r.get("material_code"),
               r.get("quantity"), r.get("unit_price"),
               str(r.get("po_line") or "").strip(), r.get("page"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# ──────────────────────────────────────────────
# Assembling the result dict
# ──────────────────────────────────────────────
def _records_from(payload: dict, source_file: str, po_number: str) -> list:
    out = []
    for i, ln in enumerate(payload.get("lines") or []):
        if not isinstance(ln, dict):
            continue
        try:
            page = int(str(ln.get("page") or "1").strip() or 1)
        except ValueError:
            page = 1
        out.append({
            "material_code": str(ln.get("material_code") or "").strip(),
            "backbone_code": "",
            "description": str(ln.get("description") or "").strip(),
            "source_line": str(ln.get("source_line") or "").strip(),
            "category": "",
            "quantity": _clean_num(ln.get("quantity")),
            "unit": str(ln.get("unit") or "").strip(),
            "unit_price": _clean_num(ln.get("unit_price")),
            "amount": _clean_num(ln.get("amount")),
            # Printed tax for THIS line, when the table has a tax column. It
            # is not published anywhere - the ERP form has no tax column - but
            # it is what makes `qty x price == amount` true on the documents
            # that print a tax-inclusive Amount (2026-11-02).
            "sales_tax": _clean_num(ln.get("sales_tax")),
            "po_line": str(ln.get("po_line") or "").strip(),
            "po_number": po_number,
            "page": page,
            "source_file": source_file,
            "match_type": "claude",
            "extracted_at": datetime.now().isoformat(timespec="seconds"),
        })
    return out


# ──────────────────────────────────────────────
# Header fields: the two dates and the delivery address
# ──────────────────────────────────────────────
# The ERP form wants these as real dates (columns K and M), and a PO prints them
# in whatever shape the customer's system chose. Rather than teach the model one
# format, it is told to return YYYY-MM-DD and this parser accepts the shapes that
# still slip through - the document is the authority, not the format.
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y",
                 "%m-%d-%Y", "%m-%d-%y", "%Y%m%d", "%d-%b-%Y", "%d %b %Y",
                 "%b %d, %Y", "%b %d %Y", "%d-%B-%Y", "%B %d, %Y",
                 "%d %B %Y", "%B %d %Y",
                 # Dotted dates. Builder work orders print the RDD as
                 # "11.30.26" under the "Requested Delivery Date" row, and
                 # without these the date was UNREADABLE - so the R.D.D
                 # silently fell back to "PO date + 6 working days", which
                 # looks like a read date and is not one (2026-11-02).
                 # Month first, because every customer on this desk is US;
                 # "%d.%m.%y" still catches "30.11.26", where month-first
                 # cannot parse. An ambiguous "05.06.26" stays month-first.
                 "%m.%d.%Y", "%m.%d.%y", "%d.%m.%Y", "%d.%m.%y", "%Y.%m.%d")


def _as_date(value) -> str:
    """Any printed date -> 'YYYY-MM-DD', or '' when it cannot be read.

    Unreadable returns EMPTY rather than a guess: the same rule the quantity
    and the price follow, and for the same reason - a date the operator cannot
    tell from a real one is worse than a blank cell they will notice.
    """
    s = str(value or "").strip()
    if not s:
        return ""
    s = re.sub(r"(?i)\b(\d{1,2})(st|nd|rd|th)\b", r"\1", s)   # 14th -> 14
    s = s.replace(",", " ") if re.search(r"[A-Za-z]", s) else s
    s = re.sub(r"\s+", " ", s).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    # Last resort: a date embedded in a longer string ("Date: 10/14/2026").
    mo = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if mo:
        try:
            return datetime(int(mo.group(1)), int(mo.group(2)),
                            int(mo.group(3))).date().isoformat()
        except ValueError:
            pass
    mo = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})", s)
    if mo:
        y = int(mo.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return datetime(y, int(mo.group(1)), int(mo.group(2))).date().isoformat()
        except ValueError:
            pass
    # ...and the dotted form, guarded so a long code ("18.25.55832") cannot be
    # mistaken for one: the year must be a whole group, not the head of a
    # longer number.
    mo = re.search(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{2,4})(?![\d.])", s)
    if mo:
        y = int(mo.group(3))
        y = y + 2000 if y < 100 else y
        for a, b in ((1, 2), (2, 1)):        # month-day first, then day-month
            try:
                return datetime(y, int(mo.group(a)),
                                int(mo.group(b))).date().isoformat()
            except ValueError:
                continue
    return ""


def add_business_days(iso_date: str, days: int) -> str:
    """A date `days` working days later. Weekends are skipped, holidays are not.

    Holidays are deliberately NOT modelled: there is no calendar on this PC that
    knows a customer's shutdown week, and inventing one would move a real
    delivery date on a guess. The result is therefore a floor, and the cell is a
    default the operator can overwrite - see RDD_DEFAULT_NOTE.
    """
    d = _as_date(iso_date)
    if not d:
        return ""
    cur = datetime.strptime(d, "%Y-%m-%d").date()
    left = max(0, int(days))
    while left:
        cur += timedelta(days=1)
        if cur.weekday() < 5:          # Mon..Fri
            left -= 1
    return cur.isoformat()


RDD_DEFAULT_WORKING_DAYS = 6
RDD_DEFAULT_NOTE = ("read the PO date and added 6 working days")


def _header_fields(payload: dict) -> tuple:
    """(fields, diagnostics) - the dates and the delivery address, normalised.

    Returns a dict of ERP-shaped keys plus a note saying where RDD came from,
    so the screen can show "defaulted" instead of presenting a computed date as
    if the customer had printed it.
    """
    diags = []
    po_date_raw = str(payload.get("po_date") or "").strip()
    rdd_raw = str(payload.get("rdd") or "").strip()
    po_date = _as_date(po_date_raw)
    rdd = _as_date(rdd_raw)
    rdd_note = "read from the PO" if rdd else ""

    if po_date_raw and not po_date:
        diags.append(f"the PO date {po_date_raw!r} could not be read as a "
                     "date - column M left empty")
    if rdd_raw and not rdd:
        diags.append(f"the required-delivery date {rdd_raw!r} could not be read "
                     "as a date - using the default instead")

    if not rdd:
        if po_date:
            rdd = add_business_days(po_date, RDD_DEFAULT_WORKING_DAYS)
            if rdd:
                rdd_note = f"no date printed on the PO - {RDD_DEFAULT_NOTE}"
                diags.append(
                    f"R.D.D defaulted to {rdd} ({RDD_DEFAULT_WORKING_DAYS} "
                    "working days after the PO date) - the document printed "
                    "none")
        else:
            diags.append("no PO date and no R.D.D on the document - both cells "
                         "left empty")

    out = {"po_date": po_date, "rdd": rdd, "rdd_source": rdd_note,
           "rdd_defaulted": bool(rdd) and not _as_date(rdd_raw)}

    ship = payload.get("ship_to")
    fields, note = _ship_block(ship)
    if note:
        diags.append(note)
    out.update(fields)
    return out, diags


# Keys the model has been seen to use for the same thing. The tool schema asks
# for address_lines / postal_code / state, but a model that is asked for a
# postal code will sometimes answer "zip" - and the old code then produced an
# EMPTY W column with no diagnostic, which is indistinguishable from a PO that
# prints no postal code. Accepting the synonyms costs nothing and removes one
# silent failure mode.
_SHIP_KEYS = {
    "lines": ("address_lines", "address", "lines", "street", "street_address",
              "address1", "line1"),
    "city": ("city", "town", "locality"),
    "state": ("state", "region", "province", "state_province"),
    "zip": ("postal_code", "postcode", "zip", "zip_code", "postal", "postalCode"),
    "name": ("name", "ship_to_name", "company", "consignee"),
}


def _pick(d, names):
    """The first non-empty value among `names`, as a stripped string."""
    for n in names:
        if n in d:
            v = d.get(n)
            if isinstance(v, (list, tuple)):
                v = " ".join(str(x) for x in v if str(x or "").strip())
            v = str(v or "").strip()
            if v:
                return v
    return ""


def _ship_block(ship) -> tuple:
    """(ERP ship fields, diagnostic) from whatever shape the model returned.

    Three shapes happen in practice and all three must land in R-S-V / W / X /
    AZ, because a preview that cannot show the delivery address is not a
    preview:

      1. the documented object  {name, address_lines[], city, state, postal_code}
      2. the same object with different key names ("zip", "region", ...)
      3. a single STRING - "9 ONE-OFF WAY, NEWARK, NJ 07102"

    Shape 3 used to be dropped wholesale (`isinstance(ship, dict)` failed), so
    a PO whose address was printed as one line previewed as "not printed on the
    PO" even though it had been read.
    """
    empty = {k: "" for k in (
        "ship_to_name", "ship_to_address", "ship_to_street2",
        "ship_to_street3", "ship_to_street4", "ship_to_street5",
        "ship_to_city", "ship_to_region", "ship_to_zip")}

    if not ship:
        return empty, ""

    note = ""
    if isinstance(ship, str):
        # One printed line. Split on newlines if it has them, else on commas -
        # the way an address is written on a US purchase order.
        raw = ship.strip()
        if not raw:
            return empty, ""
        parts = ([p.strip() for p in raw.splitlines() if p.strip()]
                 if "\n" in raw else
                 [p.strip() for p in raw.split(",") if p.strip()])
        street, city, region, zipcode = _consume_tail(parts)
        fields = dict(empty)
        fields.update({
            "ship_to_address": street[0] if street else "",
            "ship_to_street2": street[1] if len(street) > 1 else "",
            "ship_to_street3": street[2] if len(street) > 2 else "",
            "ship_to_street4": street[3] if len(street) > 3 else "",
            "ship_to_street5": street[4] if len(street) > 4 else "",
            "ship_to_city": city, "ship_to_region": region,
            "ship_to_zip": zipcode,
        })
        note = ("the deliver-to address arrived as one line - it was split "
                "across R-S / X / AZ; check the row before generating")
        return fields, note

    if not isinstance(ship, dict):
        return empty, ""

    raw_lines = None
    for k in _SHIP_KEYS["lines"]:
        if k in ship:
            raw_lines = ship.get(k)
            break
    if isinstance(raw_lines, str):
        raw_lines = [x.strip() for x in raw_lines.splitlines() if x.strip()]
    elif isinstance(raw_lines, (list, tuple)):
        raw_lines = [str(x).strip() for x in raw_lines if str(x or "").strip()]
    else:
        raw_lines = []
    lines = raw_lines[:5]

    fields = dict(empty)
    fields.update({
        "ship_to_name": _pick(ship, _SHIP_KEYS["name"]),
        "ship_to_address": lines[0] if lines else "",
        "ship_to_street2": lines[1] if len(lines) > 1 else "",
        "ship_to_street3": lines[2] if len(lines) > 2 else "",
        "ship_to_street4": lines[3] if len(lines) > 3 else "",
        "ship_to_street5": lines[4] if len(lines) > 4 else "",
        "ship_to_city": _pick(ship, _SHIP_KEYS["city"]),
        "ship_to_region": _pick(ship, _SHIP_KEYS["state"]).upper()[:2],
        "ship_to_zip": _pick(ship, _SHIP_KEYS["zip"]),
    })

    # City / state / postcode printed as the tail of the address instead of in
    # their own fields is common, and it is recoverable: "NEWARK, NJ 07102".
    if lines and not (fields["ship_to_city"] or fields["ship_to_zip"]):
        tail = lines[-1]
        if any(c.isdigit() for c in tail) or "," in tail:
            keep, city, region, zipcode = _consume_tail(lines)
            if zipcode or city or region:
                fields["ship_to_city"] = fields["ship_to_city"] or city
                fields["ship_to_region"] = fields["ship_to_region"] or region
                fields["ship_to_zip"] = fields["ship_to_zip"] or zipcode
                # ...and drop the tail from the street lines so it is not
                # printed twice (R-S-V then X / AZ).
                for i in range(5):
                    fields[f"ship_to_street{i + 1}" if i else
                           "ship_to_address"] = keep[i] if i < len(keep) else ""

    if not (fields["ship_to_address"] or fields["ship_to_zip"]
            or fields["ship_to_city"]):
        note = ("the document's deliver-to block was returned in a shape that "
                "could not be read - the address columns are empty; type them "
                "on the row if the file needs them")
    return fields, note


_ZIP_ONLY = None


def _consume_tail(parts):
    """(street_lines, city, state, zip) from the END of a printed address.

    A US PO writes the tail in one of four ways, and every one of them has been
    seen on a Samsung PO:

        [... , "NEWARK, NJ 07102"]   city + state + zip, one line
        [... , "NJ 07102"]           the city is the line before
        [... , "NJ", "07102"]        each on its own line
        [... , "NEWARK NJ"]          no postcode at all

    Working backwards is what makes the first two distinguishable, and it keeps
    the city out of the STREET columns - "NEWARK" in S (street 2) is a real
    mistake on an ERP form, not a cosmetic one.
    """
    global _ZIP_ONLY
    if _ZIP_ONLY is None:
        _ZIP_ONLY = re.compile(r"^(\d{5}(?:-\d{4})?)$")
    out = [str(x).strip() for x in (parts or []) if str(x or "").strip()]
    city = region = zipcode = ""

    # 1. a bare postcode on its own line
    if out:
        m = _ZIP_ONLY.match(out[-1].strip(" ,"))
        if m:
            zipcode = m.group(1)
            out.pop()

    # 2. a bare two-letter state on its own line
    if out and len(out) > 1 and re.match(r"^[A-Za-z]{2}$", out[-1].strip(" ,")):
        region = out[-1].strip(" ,").upper()
        out.pop()

    # 3. "CITY, ST 07102"  /  "CITY ST"  /  "ST 07102" on the last line
    if out and (not zipcode or not region or not city):
        tail = out[-1]
        m = re.match(r"^(?P<rest>.*?),?\s*(?P<st>[A-Za-z]{2})"
                     r"\s+(?P<zip>\d{5}(?:-\d{4})?)$", tail.strip(" ,"))
        if m:
            cand_city = m.group("rest").strip(" ,")
            # "NEWARK" from "NEWARK, NJ 07102"; empty for "NJ 07102".
            if cand_city and not re.search(r"\d", cand_city):
                # "NEWARK, NJ 07102": the city was on the tail line, but the
                # state and the postcode came with it and must not be dropped.
                city = city or cand_city
                region = region or m.group("st").upper()
                zipcode = zipcode or m.group("zip")
                out.pop()
            elif not cand_city and not zipcode:
                zipcode = m.group("zip")
                region = region or m.group("st").upper()
                out.pop()
            elif not zipcode:
                zipcode = m.group("zip")
                region = region or m.group("st").upper()
                if not city:
                    city = cand_city
                out.pop()
        else:
            m2 = re.match(r"^(?P<city>.*?),?\s*(?P<st>[A-Za-z]{2})$",
                          tail.strip(" ,"))
            if m2 and not region and len(out) > 1:
                rest = m2.group("city").strip(" ,")
                if rest and not re.search(r"\d", rest):
                    city = city or rest
                    region = region or m2.group("st").upper()
                    out.pop()

    # 4. the last remaining line is the city (option 2's shape)
    if not city and out and len(out) > 1 and (zipcode or region):
        cand = out[-1].strip(" ,")
        if cand and not re.search(r"\d", cand) and len(cand) <= 24:
            city = cand
            out.pop()

    return out, city, region, zipcode



# The per-ORDER values every order block carries, flat, keyed the way the ERP
# columns want them. `of_pdf.expand_orders()` copies these off a block to make
# one result per order, so this tuple is the contract between the two files -
# it must stay in step with `_header_fields()`.
ORDER_HEADER_KEYS = ("po_date", "rdd", "rdd_source", "rdd_defaulted",
                     "ship_to_name", "ship_to_address", "ship_to_street2",
                     "ship_to_street3", "ship_to_street4", "ship_to_street5",
                     "ship_to_city", "ship_to_region", "ship_to_zip")


def _orders_from(payload: dict) -> list:
    """The orders a payload holds, whatever shape it arrived in.

    The tool schema asks for `orders`, but two other shapes reach here and both
    have to work: a model that ignores the wrapper and answers with the old
    single-order object, and a cache file written before 2026-10-28. Both are
    ONE order, read exactly as before.
    """
    if not isinstance(payload, dict):
        return [{}]
    raw = payload.get("orders")
    orders = [o for o in (raw or []) if isinstance(o, dict)] \
        if isinstance(raw, list) else []
    if orders:
        return orders
    return [payload]


def _finalise(payload: dict, source_file: str, cache_path: Path, md5_hash: str,
              customer_name: str = "") -> dict:
    """The result dict for ONE document - which may hold several orders.

    Until 2026-10-28 a document was an order: one number, one total, one
    delivery address, one set of dates. Curacao sends four POs stapled into one
    PDF, and that assumption published four orders' lines under the first
    order's number, the first order's dates and one merged total. Nothing
    errored - the file simply said the wrong thing on every row it wrote.

    So every order now keeps its own block: its number, its printed total, its
    two dates, its delivery address, its own lines - and each record carries the
    `order_index` that ties it to that block. The tops of the dict are still
    filled in (a single-order document looks exactly as it did) but only while
    there IS one order: with several, the top-level header stays EMPTY rather
    than nominating one order's address as if it applied to all of them.
    """
    blocks = _orders_from(payload)

    backbone = get_backbone()
    doc_diags = []
    if not backbone.enabled:
        doc_diags.append(
            "No Material Code list on this machine, so codes were published "
            "as read without being confirmed. Upload Master Data > Material "
            "Codes.")

    orders, records, review, diags = [], [], [], []
    for i, one in enumerate(blocks):
        po_number = str(one.get("po_number") or "").strip()
        total = _clean_num(one.get("document_total"))
        header, header_diags = _header_fields(one)

        recs = _records_from(one, source_file, po_number)
        for r in recs:
            r["order_index"] = i
        recs, rev = apply_gate(recs, backbone, source_file, po_number)
        for x in rev:
            x["order_index"] = i
        # Per ORDER, not per document: Curacao's four POs repeat the same 25
        # models on page after page, and a document-wide dedupe would have
        # deleted three orders' worth of rows as "identical".
        recs = dedupe_records(recs)

        order_diags = list(header_diags) + check_arithmetic(recs, total)
        if rev:
            order_diags.append(
                f"{len(rev)} line(s) set aside for review - their code is not "
                "in the Material Code list.")
        # With several orders a note has to say WHICH one it is about, or
        # "R.D.D defaulted to 2026-05-07" is unattributable.
        if len(blocks) > 1:
            tag = f"PO {po_number}: " if po_number else f"order {i + 1}: "
            order_diags = [tag + d for d in order_diags]

        block = {"index": i, "po_number": po_number, "document_total": total,
                 "line_count": len(recs), "review_count": len(rev),
                 "diagnostics": order_diags}
        block.update({k: header.get(k, "") for k in ORDER_HEADER_KEYS})
        orders.append(block)
        records.extend(recs)
        review.extend(rev)
        diags.extend(order_diags)

    single = len(orders) == 1
    first = orders[0] if orders else {}
    # What the top of the dict says. One order -> its own values, exactly as
    # before. Several -> empty, because "the" delivery address does not exist.
    top = ({k: first.get(k, "") for k in ORDER_HEADER_KEYS} if single
           else {k: "" for k in ORDER_HEADER_KEYS})

    result = {
        "source_file": source_file,
        "md5": md5_hash,
        "config_sig": config_signature(),
        "po_number": first.get("po_number", "") if single else "",
        # All of them, so a list or a file name can say what is inside without
        # pretending one of them is the document's number.
        "po_numbers": [o["po_number"] for o in orders if o["po_number"]],
        "order_count": len(orders),
        "customer": customer_name or "",
        "extraction_mode": "claude",
        **top,
        "records": records,
        "review": review,
        "diagnostics": doc_diags + diags,
        # The per-order blocks: of_pdf splits a document into one result per
        # order from this list, so a four-PO PDF reaches the ERP writer as four
        # orders with four numbers, four totals and four delivery dates.
        "orders": orders,
        "processed_at": datetime.now().isoformat(timespec="seconds"),
        "page_count": 0,
        "stats": {
            "total": len(records),
            "reference_matched": sum(
                1 for r in records if r.get("backbone_code")),
            "review_count": len(review),
            "backbone_size": len(backbone),
            "orders": len(orders),
        },
    }
    save_cache(cache_path, result)
    return result


# ──────────────────────────────────────────────
# Entry points
# ──────────────────────────────────────────────
def extract_material_codes(pdf_path: str, force: bool = False,
                           customer_name: str = "",
                           progress_callback=None) -> dict:
    """Read one PO PDF. Returns the result dict (docs/HANDOVER.md 4.7).

    `force=True` bypasses the cache - the dashboard always passes it, because
    Confirm is re-run precisely when the master has just changed.
    """
    cfg = load_config()
    source_file = Path(pdf_path).name
    md5_hash = file_md5(pdf_path)
    cache_path = get_cache_path(pdf_path)

    def tick(pct, msg):
        if progress_callback:
            progress_callback(pct, msg)

    tick(5, "Preparing the document...")
    if not force:
        cached = load_cache(cache_path)
        if (cached and cached.get("md5") == md5_hash
                and cached.get("config_sig") == config_signature()):
            tick(100, "Loaded from cache")
            return cached

    tick(20, "Sending the PDF to Claude...")
    payload = _call(_pdf_blocks(pdf_path, cfg), cfg)
    tick(80, "Checking the reading against the Material Code list...")
    result = _finalise(payload, source_file, cache_path, md5_hash,
                       customer_name)
    tick(100, f"{len(result['records'])} line(s)")
    return result


def from_text(text: str, source: str = "") -> dict:
    """Read a PO from plain text.

    Used when a DRM-protected PDF could only be recovered as text
    (`pdf_access` L4a/L4b), which used to need a second, weaker parser. Same
    call, same gate, same output shape - so the same PO reads the same whether
    it arrives as a PDF or as recovered text.
    """
    cfg = load_config()
    source_file = source or "text"
    payload = _call(_text_blocks(text, cfg), cfg)
    return _finalise(payload, source_file, get_cache_path(source_file), "",
                     "")


def is_mac_sidecar(path) -> bool:
    """True for macOS AppleDouble files ('._PO 2147.pdf') beside a real one.

    The source tree travels between a Mac and this PC, and every copy brings
    a '._' twin for each file: 4 KB of Finder metadata that happens to end in
    .pdf. They are never a document, so every sweep skips them.
    """
    return Path(path).name.startswith("._")
