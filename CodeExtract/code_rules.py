"""code_rules.py - what a material code IS, and how two spellings match.

Lifted verbatim out of the retired `engine.py` (its `code_matcher` section)
when PO extraction moved to the Claude API. The API does the *reading*; this
module still owns the *deciding*, because that is the rule the project is
built on:

    extraction proposes, master data decides.
    (docs/HANDOVER.md 4.0, principle 1)

A material code Claude reads beautifully is still only a *candidate* until
`BackboneIndex` finds it in the reference list. Anything it cannot confirm is
moved to `review` and kept out of the ERP upload - a code that does not exist
must never reach ERP.

Consumers:
  - `claude_engine.py`  the accuracy gate after every extraction
  - `src/of_master.py`  `code_rules()` - reading an uploaded code list
  - `src/of_pdf.py`    `normalise_to_master()` - spelling -> listed spelling

One implementation, three callers. Do not add a second matcher anywhere.
"""

import re
from collections import defaultdict

# Separators that carry no meaning when two spellings are compared:
# 'RF18A5101SR/AA', 'RF18A5101SR-AA' and 'RF18A5101SR AA' are one code.
_NORM_STRIP = re.compile(r"[\s\-_./­‐‑‒–—―−⁃－]")

# The same characters, minus '-', '/' and '.', which ARE part of how a code is
# written ('L-INST/E2-BEV'). A comparison about identity keeps them.
_PRINT_STRIP = re.compile(r"[\s­‐‑‒–—―−⁃－]")

# Market / region suffix on a Samsung code: DVE45T6000W/AA, ... /A3.
MARKET_SUFFIX = re.compile(r"(?i)(XAA|XAC|AA|US|A[0-9]|A)")

# A trailing market suffix as it appears inside one glued token (...SRAA).
VARIANT_SUFFIX = re.compile(r"(XAA|XAC|AA|US|A)$", re.IGNORECASE)

_DASHES = "\\-\u2010\u2011\u2012\u2013\u2014\u2015\u2212"

# Characters OCR engines routinely swap inside alphanumeric codes.
_CONFUSE_MAP = str.maketrans({"S": "5", "O": "0", "I": "1", "B": "8", "Z": "2"})


def normalize(code: str) -> str:
    """Uppercase and remove separators for tolerant comparison."""
    if not code:
        return ""
    return _NORM_STRIP.sub("", str(code)).upper()


def print_form(code: str) -> str:
    """The spelling a document would print, separators KEPT.

    `normalize()` throws them away and cannot tell 'L-INST/E2' from
    'L-INST/E3' once they differ by one character, so any comparison about
    WHICH CODE this is - rather than how it is spelled - uses this form.
    """
    if not code:
        return ""
    return _PRINT_STRIP.sub("", str(code)).upper()


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
# Used when a code list is read (Master Data > Material Codes upload), so the
# list and the matcher agree by construction.

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
# The reference index
# ──────────────────────────────────────────────
class BackboneIndex:
    """Hash-based lookup over the reference list.

    Build cost is linear in list size and happens once per run. Lookup is O(1)
    per token, so a list of 100,000 codes costs the same per line as a list of
    100. No per-code regex is compiled.

    It can only ever return a code that is IN the list. That is the whole
    point: it never guesses, it only recognises.
    """

    # Codes shorter than this are ignored to avoid matching stray words
    MIN_CODE_LEN = 3

    # ...and shorter than THIS they are not allowed to grow into a listed code
    # by the prefix rule alone ('26' -> '26A' is a date, not a model).
    MIN_SHORT_PREFIX_LEN = 5

    def __init__(self, ref_codes: dict):
        self.raw = ref_codes or {}
        self.by_norm = {}                  # normalized        -> original
        self.by_stem = {}                  # variant-stripped  -> original
        self.by_base = {}                  # part before "/"   -> original
        self.by_confuse = {}               # OCR-folded        -> [originals]
        self.by_prefix = defaultdict(list)  # stem -> [originals]

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

    def lookup(self, candidate: str) -> tuple:
        """Match one token against the list.

        Returns: (matched_code, kind) or ("", ""). Matched_code is always a
        code the list actually carries.
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

        # 5a) the token is a PREFIX of a listed code - grow it into the code.
        cands = self.by_prefix.get(n)
        if cands:
            # A BARE DIGIT IS NOT A MARKET VARIANT. The printed token has
            # already stopped short of the listed code here, and a token that
            # is only a few characters long plus a digit is a dated reference,
            # not a model: PO 25407327's line only read
            # "PO  ID#  25407327 ... Apr  18th,  26" and '26' alone looked up
            # to the listed '26A' / '2612' appliances.
            if len(n) < self.MIN_SHORT_PREFIX_LEN and any(
                    ch.isdigit() for ch in n):
                return "", ""
            if len(cands) > 1:
                # Same stem, several market variants (.../AA, .../A3, ...):
                # customers on manual POs only ever take the /AA SKU, so when
                # it is among the candidates it is the safe pick rather than
                # whichever variant sits first in the master list.
                aa = next((c for c in cands
                           if str(c).upper().endswith("/AA")), None)
                if aa:
                    return aa, "variant"
            return cands[0], "variant"

        # 5b) The document prefixes the code with an internal category number:
        #     "583-DVE45T6000W", "584-L-INST-E2". Safe because the remainder
        #     must still match the list exactly.
        mpx = re.match(r"^\d{1,4}[" + _DASHES + r"./]\s*(.+)$",
                       str(candidate))
        if mpx:
            tail = mpx.group(1)
            nt = normalize(tail)
            if len(nt) >= self.MIN_CODE_LEN:
                hit = (self.by_norm.get(nt) or self.by_base.get(nt)
                       or self.by_stem.get(strip_variant(tail)))
                if hit:
                    return hit, "variant"

        # 6) OCR glued the code to the next word: WF45B6300APPLATINUM.
        #    Peel a purely-alphabetic tail off the token and retry - the
        #    remainder must be letters only and the surviving prefix long
        #    enough that a wrong-model hit is impossible.
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
        #    list-confirmed - it can only ever return a listed code, and only
        #    when exactly ONE listed code folds to this key. Two codes sharing
        #    a folded form make the reading ambiguous, and ambiguity is
        #    reported, never guessed.
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

    def printed_form(self, matched_code: str, token: str) -> str:
        """The value written to the Material Code column.

        The document's own spelling is preserved whenever the token IS the code:

            token == listed code                 DW80CG4051SRAA
            token == listed code, market part     DVE45T6000W  (list: .../A3)
            token == code + short market suffix   RF18A5101SRAA (list: .../AA)
            token == code minus its suffix        DW80CG4051SR (list: ...SRAA)

        Anything else means the token is not a clean code - OCR glued a
        description word to it ('WF45B6300APPLATINUM') or swapped characters
        ('WF4SB6300AP') - and publishing it would be wrong. The list spelling
        is used instead, base part only.
        """
        tok = (token or "").strip().upper()
        if not tok:
            return str(matched_code).split("/", 1)[0].upper()

        base_src = str(matched_code).split("/", 1)[0]
        nt = normalize(tok)
        nb = normalize(base_src)
        nm = normalize(matched_code)

        # The FULL listed code, spelled differently in separators.
        #
        # "The document's spelling is preserved" cannot mean "keep a slash the
        # document dropped": ERP is keyed on the master notation, so a PO that
        # prints DDW24M999UMDA while the list carries DDW24M999UM/DA must
        # publish the LISTED form. That missing separator is exactly what made
        # the uploaded code not match. Same for RF18A5101SRAA vs .../AA.
        if nt == nm:
            return print_form(matched_code)

        # The token is the code's BASE, which the list extends with a market
        # part (document DVE45T6000W, list DVE45T6000W/A3). Here the document
        # is not wrong, only shorter, so its spelling stands.
        if nt == nb:
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
