r"""claude_engine.py - PO extraction by the DeepSeek API.

Replaces the 7,200-line local engine (now `CodeExtract/_legacy/engine.py`).
Where the old engine rasterised, OCR'd, found header rows, built column bounds
and assigned cells by geometry, this module renders PDF pages to images, sends
them to DeepSeek and gets back the ordered line items as JSON.

WHAT DID NOT CHANGE - the two rules the project is built on
----------------------------------------------------------
1. **Extraction proposes, master data decides.** DeepSeek's material code is a
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

ENDPOINT (DeepSeek local-test branch)
------------------------------------
This talks to DeepSeek's Anthropic-compatible Messages API:

    base_url    Settings screen > $DEEPSEEK_BASE_URL > claude_config.json
                default https://api.deepseek.com/anthropic
    API key     Settings screen > $DEEPSEEK_API_KEY >
                CodeExtract/.deepseek_api_key

    POST {base_url}/v1/messages
    x-api-key: <DeepSeek API key>

DeepSeek does not accept Anthropic PDF `document` blocks. Plain PDFs are
rendered locally to JPEG page images with PyMuPDF and sent to the
vision-capable `deepseek-flash` model. DRM documents recovered as text keep
the text route. The API key is never shipped with the program.
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

# DeepSeek exposes an Anthropic-compatible Messages API. Keeping that wire
# shape lets the existing tool schema and response parser stay unchanged.
#
# Both of the two things the guide asks you to configure are settings, and both
# are overridable in three places (first one found wins):
#
#   base_url   config/settings.json deepseek.base_url
#              > $DEEPSEEK_BASE_URL > claude_config.json > DEFAULT_BASE_URL
#   API key    config/settings.json deepseek.api_key
#              > $DEEPSEEK_API_KEY > .deepseek_api_key
#
# The Settings screen wins over both environment variables, for both values:
# a key pasted once has to keep working on a machine that also has a stale
# environment variable exported in its profile.
#
# ⚠️ THE TOKEN IS NOT INCLUDED ANYWHERE - IT HAS TO BE PASTED IN. Paste it on
# the Settings screen under "PO reading", or set $DEEPSEEK_API_KEY. Without
# it every PO comes back with zero codes and no error, which is why
# `_load_module` refuses to run without one.
DEFAULT_BASE_URL = "https://api.deepseek.com/anthropic"
MESSAGES_PATH = "/v1/messages"

# Exactly the IDs the guide lists, with the guide's own notes. Anything else is
# not offered by this endpoint, and a wrong ID comes back as a 400 that says
# nothing useful - so the list is published in the error message instead.
KNOWN_MODELS = {
    "deepseek-flash": "Vision-capable model required for PDF page images",
}

DEFAULTS = {
    "model": "deepseek-flash",
    "base_url": DEFAULT_BASE_URL,
    "max_tokens": 8000,
    "timeout_sec": 180,
    "max_pdf_bytes": 20_000_000,
    "max_pdf_pages": 100,
    "max_request_bytes": 45_000_000, # below DeepSeek's 48 MiB body limit
    "pdf_dpi": 144,
    "jpeg_quality": 82,
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
    chosen = str((_deepseek_settings() or {}).get("model") or "").strip()
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


def _deepseek_settings() -> dict:
    """The isolated `deepseek` block written by this test branch."""
    block = _user_settings().get("deepseek") or {}
    return block if isinstance(block, dict) else {}


def api_key() -> str:
    """The DeepSeek API key, in the order the Settings screen promises.

    The stored setting comes FIRST. It used to be read after the environment
    variables, which contradicted the contract at the top of this file and
    quietly defeated the screen: a machine with a stale environment key
    exported in its profile ignored every token pasted in Settings, so the paste
    looked like it had not been saved. An environment variable is now what it
    says on the box - a fallback for a machine nobody configures by hand.
    """
    block = _deepseek_settings()
    for field in ("api_key", "token", "auth_token"):
        k = str(block.get(field) or "").strip()
        if k:
            return k
    for env in ("DEEPSEEK_API_KEY",):
        k = (os.environ.get(env) or "").strip()
        if k:
            return k
    try:
        return (HERE / ".deepseek_api_key").read_text(
            encoding="utf-8").strip()
    except Exception:
        return ""


def base_url() -> str:
    """The endpoint root, without a trailing slash.

    Order: Settings screen > $DEEPSEEK_BASE_URL > claude_config.json >
    DEFAULT_BASE_URL. The config file is the *shipped default*, so it sits
    below the two places an operator actually edits - otherwise a value in the
    file would silently pin the address and the Settings box would look broken.

    A value ending in /v1/messages is accepted too (people paste the full URL)
    and trimmed back to the root.
    """
    url = ""
    sources = (_deepseek_settings().get("base_url"),
               os.environ.get("DEEPSEEK_BASE_URL"),
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
    """DeepSeek's Anthropic-compatible endpoint accepts `x-api-key`."""
    return {"x-api-key": key or api_key()}


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
                    "material_code": {"type": "string"},
                    "description": {"type": "string"},
                    "quantity": {"type": "string"},
                    "unit": {"type": "string"},
                    "unit_price": {"type": "string"},
                    "amount": {"type": "string"},
                    "po_line": {"type": "string"},
                    "page": {"type": "string"},
                    "source_line": {"type": "string"},
                },
                "required": ["material_code", "description", "quantity",
                             "unit", "unit_price", "amount", "po_line",
                             "page", "source_line"],
            },
        },
    },
    "required": ["po_number", "document_total", "po_date", "rdd",
                 "ship_to", "lines"],
}

_TOOL = {
    "name": "return_line_items",
    "description": "Return the purchase order(s) read from the document, each "
                   "with its own number, total, dates, delivery address and "
                   "ordered line items.",
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

_SYSTEM = """You read purchase orders (POs) for Samsung home appliances and return what was ordered, as structured data.

Follow these rules exactly.

1. Return one entry in `orders` per DISTINCT PURCHASE ORDER in the document. Most documents are ONE order and then `orders` holds exactly one entry - that is the normal case, not an error. A document may also hold several POs glued together: four pages, each with its own "P/O #" header and its own table, are FOUR orders. Never merge two different order numbers into one entry, and never split one order number across two entries.

2. A line item belongs to the order whose header (the P/O number block) is the nearest one ABOVE it. When a page continues the previous page's table and prints no new order number, its lines belong to the order above it - usually the one on the previous page. When a page prints a NEW order number, every line below that header belongs to the new order.

3. Inside each order, return one object per ORDERED LINE ITEM - one row of that order's items table that names a product ordered and carries its own quantity.

4. Copy every value EXACTLY AS PRINTED. Never recalculate, round, convert, reformat or "fix" a number. Write digits with the decimal point as printed and no currency symbol and no thousands separator: printed "1,234.50" is returned as "1234.50" (removing the $ and the comma is not a change of value; changing the digits is).

5. NEVER INVENT A VALUE. If a quantity, unit price or amount is not printed for a line, return an empty string for that field. An empty field is a success - it is flagged for a human. A plausible number you constructed is a failure, because it cannot be told from a real one.

6. SKIP rows that are not ordered items: subtotal, total, tax, freight, shipping, handling, discount, grand total, and any other summary row. The grand total of an order still belongs in that order's `document_total` - it is just not a line.

7. SKIP a model number that appears only inside ANOTHER item's description or notes ("...includes RF28R7201SR..."). A model named in prose is not an order line.

8. material_code: the product / model / SKU code as printed - the identifier alone, with no description words and no leading category number.

9. quantity: the number of units ordered. unit_price: the price of ONE unit. amount: the line's extended total. If the document prints only ONE money figure for a line, put it in unit_price and leave amount empty - do not multiply it yourself.

10. page: the 1-based page number the row is printed on, as a string. source_line: the row, copied as printed, on one line.

11. po_number: the order number printed in THAT order's header - usually next to "P/O #", "P/O No", "PO Number" or "Order No". document_total: that order's printed grand total. Empty strings when the order prints neither. When the document holds several orders, each entry carries ITS OWN number and ITS OWN total - never the first order's number copied down, and never the sum of the document.

12. po_date is the date THAT ORDER was issued - the value next to "PO Date", "P/O Date", "Order Date", "Ordered" or "Date" in that order's header. rdd is the date the customer wants the goods DELIVERED, printed as "Required Date", "Required Delivery Date", "RDD", "ETA Date", "Requested Delivery", "Delivery Date" or "Delivery On". Return both as YYYY-MM-DD, converting the printed format without changing the day: a document printing "10/14/26" gives "2026-10-14"; one printing "14-Oct-2026" gives "2026-10-14". These are two DIFFERENT dates - never copy one into the other, and return an empty string rather than guessing. Orders in the same document routinely print different delivery dates; keep each with its own order.

13. ship_to is THAT ORDER's DELIVERY address: the block labelled "Ship To", "Deliver To", "Ship-To" or "Consignee". Not the bill-to block, not the seller's address, not the customer's head office. Put the street lines in address_lines in the order printed (at most 5) and the city / state / postcode in their own fields. Return empty strings for anything the order does not print. A "SHIP TO: 4444-46 AYERS AVE VERNON CA 90058" line is street "4444-46 AYERS AVE", city "VERNON", state "CA", postal code "90058".

14. When several orders share one buyer block, that block is NOT an order - it is the document's letterhead. The number of entries in `orders` is decided by the number of distinct order numbers, not by the number of addresses or the number of pages."""

_USER_PDF = ("Read this purchase order document and return every order in it "
             "with its ordered line items. Most documents hold one order.")
_USER_TEXT = ("Below is the text of a purchase order document recovered from a "
              "protected file, so there are no page coordinates and the "
              "columns may have run together. It may hold more than one "
              "order. Read it and return every order it contains with its "
              "ordered line items.\n\n<po_text>\n%s\n</po_text>")


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
                "Check the DeepSeek key on the Settings screen - it is sent "
                "as 'x-api-key'. " + d)
    if code == 404:
        return (f"no API at {url} (HTTP 404). The base URL is probably wrong - "
                "it should normally be https://api.deepseek.com/anthropic, "
                "with "
                "/v1/messages added by this program. " + d)
    if code == 400 and ("model" in low or "not found" in low):
        return (f"the endpoint does not offer that model (HTTP 400). "
                f"Available: {', '.join(KNOWN_MODELS)}. " + d)
    if code == 400 and ("document" in low or "pdf" in low or "media" in low):
        return ("the endpoint refused a rendered PDF page image (HTTP 400). "
                "Use deepseek-flash and verify the image limits. " + d)
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
            "DEEPSEEK_API_KEY.")

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
    """One extraction call. Returns the tool input (the line items)."""
    payload = {
        "model": cfg.get("model", DEFAULTS["model"]),
        "max_tokens": int(cfg.get("max_tokens", DEFAULTS["max_tokens"])),
        "system": _SYSTEM,
        "tools": [_TOOL],
        # Forced: the answer must be the structured line items, not prose
        # about them. Getting JSON back is what makes the gate below possible.
        "tool_choice": {"type": "tool", "name": _TOOL["name"]},
        "messages": [{"role": "user", "content": content_blocks}],
    }
    data = _post(payload, cfg)
    for block in data.get("content") or []:
        if block.get("type") == "tool_use":
            return block.get("input") or {}
    raise RuntimeError("the DeepSeek API returned no line items")


def _pdf_blocks(path: str, cfg: dict) -> list:
    data = Path(path).read_bytes()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("this is not a PDF")
    limit = int(cfg.get("max_pdf_bytes", DEFAULTS["max_pdf_bytes"]))
    if len(data) > limit:
        raise RuntimeError(
            f"this PDF is {len(data) // 1024} KB; the limit for one document "
            f"is {limit // 1024} KB")
    try:
        import pymupdf as fitz
    except ImportError:
        raise RuntimeError(
            "PyMuPDF is required for the DeepSeek test branch. Run "
            "'py -m pip install -r requirements.txt'.") from None

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        raise RuntimeError(f"this PDF could not be rendered: {e}") from None

    page_limit = int(cfg.get("max_pdf_pages", DEFAULTS["max_pdf_pages"]))
    if doc.page_count > page_limit:
        pages = doc.page_count
        doc.close()
        raise RuntimeError(
            f"this PDF has {pages} pages; the local-test limit is "
            f"{page_limit}")

    dpi = max(72, min(200, int(cfg.get("pdf_dpi", DEFAULTS["pdf_dpi"]))))
    quality = max(50, min(95, int(cfg.get(
        "jpeg_quality", DEFAULTS["jpeg_quality"]))))
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    blocks = [{"type": "text", "text": _USER_PDF}]
    encoded_bytes = 0
    try:
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False,
                                  colorspace=fitz.csRGB)
            jpg = pix.tobytes("jpeg", jpg_quality=quality)
            encoded = base64.standard_b64encode(jpg).decode("ascii")
            encoded_bytes += len(encoded)
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": encoded,
                },
            })
    finally:
        doc.close()

    request_limit = int(cfg.get(
        "max_request_bytes", DEFAULTS["max_request_bytes"]))
    if encoded_bytes > request_limit:
        raise RuntimeError(
            f"the rendered pages are {encoded_bytes // 1024} KB; the "
            f"DeepSeek inline-request limit for this branch is "
            f"{request_limit // 1024} KB")
    return blocks


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
        r["match_type"] = kind
        r["material_code"] = backbone.printed_form(code, raw)
        kept.append(r)
    return kept, review


def check_arithmetic(records: list, document_total: str) -> list:
    """`qty x unit_price == amount` needs no reference data and catches a
    large share of misread rows.

    It only ever REPORTS. The 2026-10 decision stands: a value is published as
    printed and the operator corrects it. A derived price that is wrong is
    worse than a price that is visibly missing.
    """
    diags = []
    total = 0.0
    checked = 0
    for r in records:
        q, p, a = (_num(r.get("quantity")), _num(r.get("unit_price")),
                   _num(r.get("amount")))
        if q and p:
            total += q * p
        if not (q and p and a):
            continue
        checked += 1
        if abs(q * p - a) > _tolerance(a):
            label = r.get("po_line") or r.get("material_code") or "?"
            diags.append(
                f"line {label} ({r.get('material_code')}): "
                f"{q:g} x {p:g} = {q * p:.2f} but the document printed "
                f"{a:.2f}. Both are published as printed - check this line.")
    dt = _num(document_total)
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
            "po_line": str(ln.get("po_line") or "").strip(),
            "po_number": po_number,
            "page": page,
            "source_file": source_file,
            "match_type": "deepseek",
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
                 "%d %B %Y", "%B %d %Y")


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
        "extraction_mode": "deepseek",
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

    tick(20, "Rendering pages and sending them to DeepSeek...")
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
