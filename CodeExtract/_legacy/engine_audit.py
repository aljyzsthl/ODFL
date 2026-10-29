# -*- coding: utf-8 -*-
"""
engine_audit.py - the arithmetic check: does the extraction add up?

Every PO prints its own total. If the lines the engine extracted are right,
`sum(quantity x unit_price)` must equal that printed figure. Nothing else has
to be known - no answer key, no annotations, no maintained baseline.

This complements `engine_baseline.py`. That one answers "did anything CHANGE?";
this one answers "is what we have PLAUSIBLE?" - and it is the only one of the
two that can catch a value that was wrong from the very first run.

    python engine_audit.py                 check every PDF in data_upload
    python engine_audit.py <file.pdf>      check one file
    python engine_audit.py --verbose       show every line it read
    python engine_audit.py --by-line       also add the AMOUNT column per line

Exit codes:  0 = every PO that prints a total agrees
             1 = at least one PO disagrees
             2 = nothing could be checked (no totals found)

Why `--by-line` exists
----------------------
`sum(qty x price)` and `sum(amount)` substitute algebraically: a misread
quantity and a misread price can trade places and this check still reads OK.
AJ Madison 25475097 did exactly that until it was fixed by hand (qty 3 at
1,098.57 for a line the document prices as one unit at $3,295.71). Adding the
AMOUNT column per line reaches the total by an independent route, and a line
where `qty x price` disagrees with its own printed amount is listed by name.

How a verdict is reached
------------------------
For each PO we read the printed total out of the document text (a line that
says Total / Sub Total / Order Total / Amount Due and carries an amount), and
compare it with the sum of the extracted lines:

    OK            the two agree to the cent
    SHORT         extracted sum is LOWER  -> lines or quantities are missing
    OVER          extracted sum is HIGHER -> a value was invented or misread
    NO TOTAL      the document prints no total we can read -> not checkable
    ZERO          a printed total, but nothing extracted at all

`SHORT` is the common case on a real PO: a missed item, or a quantity read as
empty (it contributes 0). `OVER` is usually a price that swallowed a
neighbouring number.

What it cannot see
------------------
Two errors that cancel out (one line missing, another line invented at the
same value) pass. And a PO that prints no total is simply not checkable -
that is reported, not guessed at. It also says nothing about WHICH line is
wrong; for that, fix the engine and read the `engine_baseline.py compare`
diff.
"""

import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# A money token: 1,234.56 / 1234.56 / $1,234.56 / 1234
_MONEY = re.compile(r"(?:[$\u00a3\u20ac]\s*)?(\d{1,3}(?:,\d{3})+(?:\.\d{1,4})?|\d+\.\d{1,4}|\d{3,})")

# A PDF whose font has no Unicode mapping comes out as "(cid:18)(cid:14) TOTAL"
# (Electronic Express PO-189743). The glyph codes carry no text, so they are
# dropped before anything is read - otherwise every such line looks like it
# contains letters and the search for a figure stops on it.
_CID = re.compile(r"\(cid:\d+\)")

# Nothing inside a date or a phone number is an amount. CMH prints
# "PO Total: $28,412.00Date Needed: 10/23/2026" in ONE line, and the year at the
# end was read as the total - the audit then reported a correct order as
# "OVER by 53,071.00". Blanked out before any money is read.
_NOT_MONEY = re.compile(
    r"\d{1,4}[/-]\d{1,2}[/-]\d{2,4}"          # 10/23/2026, 23-10-26
    r"|\(\d{3}\)\s*\d{3}[-.\s]\d{4}"          # (704) 463-6416
    r"|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"       # 704-463-6416
    r"|\b(?:19|20)\d{2}\b"                    # a bare year, never a total
)

# A line that states a document total. Ordered most-specific first: 'Order
# Total' / 'PO Total' beat a bare 'Total', and 'Sub Total' is kept separately
# because on many forms it excludes freight and tax.
_TOTAL_LINE = re.compile(
    r"\b(grand\s*total|order\s*total|po\s*total|"
    r"total\s*(?:order\s*)?(?:value|amount)|amount\s*due|"
    r"sub\s*-?\s*total|subtotal|total)\b",
    re.I)

# Forms that print a count next to the total: 'Total 42 36,565.00 USD'.
_TOTAL_QTY = re.compile(r"\btotal\b[^\d]{0,12}(\d{1,6})\s", re.I)


# A figure the PDF printed as TWO tokens: "Subtotal $ 1 4,246.85" is
# 14,246.85, not 4,246.85. The leading digits sit on the far side of a space
# because of kerning, not because they are a separate number - which is exactly
# the shape Marcone MNH090926-HZL279 prints, and reading only the tail made a
# correct extraction report OVER by 10,000.00.
# A currency mark must sit before the first group, so "Total 42 36,565.00"
# (pieces, then amount) is left alone.
_SPLIT_FIGURE = re.compile(
    r"(\$|\u00a3|\u20ac)\s*(\d{1,2})\s+(\d{1,3}(?:,\d{3})+(?:\.\d{1,4})?)")


def _fuse_split_figures(text: str) -> str:
    """Close a figure the PDF split with a space after its first digits."""
    return _SPLIT_FIGURE.sub(lambda m: f"{m.group(1)} {m.group(2)}{m.group(3)}",
                             text or "")


def _dec(text) -> Decimal:
    """Parse a printed money figure. Returns Decimal('0') when unparseable."""
    s = str(text or "").strip().replace("$", "").replace(",", "")
    if not s:
        return Decimal("0")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


def _clean(text: str) -> str:
    """One printed line, with glyph codes and non-money numbers removed."""
    return _NOT_MONEY.sub(" ", _CID.sub("", text or ""))


def printed_total(text: str):
    """The document's own total, or None.

    Prefer an explicitly grand/order/PO total over a bare 'Total', and prefer
    the LAST occurrence - the summary block is at the bottom of a form. A
    'Sub Total' is used only when no stronger label exists and is flagged, so
    a PO whose subtotal excludes freight is not silently judged wrong.

    The figure is the one printed AT the label: the first amount after it, or
    - when the form prints the amount first ('36,565.00 Total') - the last one
    before it. Taking simply the last number on the line is what read the year
    of "Date Needed: 10/23/2026" as CMH's PO total.
    """
    strong, weak, sub = None, None, None
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        line = _fuse_split_figures(_clean(raw))
        m = _TOTAL_LINE.search(line)
        if not m:
            continue
        after = _MONEY.search(line[m.end():])
        if after:
            amount = _dec(after.group(1))
        else:
            before = _MONEY.findall(line[:m.start()])
            amount = _dec(before[-1]) if before else Decimal("0")
        if amount <= 0:
            # The label and its figure can print on DIFFERENT lines - a
            # summary block is often two columns of text that pdfplumber
            # splits. PO-189743 prints "TOTAL P.O." alone, then "240", then
            # "120000.00", and the check reported NO TOTAL for a document
            # that states one. Only consecutive NUMBER-ONLY lines are looked
            # at, and a line carrying letters ends the search, so the next
            # labelled field cannot be mistaken for this figure.
            amount = _amount_after_label(lines, i)
        if amount <= 0:
            continue
        label = m.group(1).lower()
        if "sub" in label:
            sub = (amount, raw.strip())
        elif label in ("total", "grand total"):
            weak = (amount, raw.strip())
        else:
            strong = (amount, raw.strip())
    chosen = strong or weak or sub
    if not chosen:
        return None
    amount, line = chosen
    return {"amount": amount, "line": line, "kind": (
        "strong" if strong else "bare" if weak else "subtotal")}


# A line that states the sales tax on the order.
_TAX_LINE = re.compile(r"\b(?:sales\s*tax|est\.?\s*tax|tax)\b", re.I)


def printed_tax(text: str) -> Decimal:
    """The tax the document adds on top of the goods, or 0.

    Some POs print a total that INCLUDES tax, and then the sum of the lines can
    never equal it:

        Net Order 1,111.00 / Tax 88.88 / TOTAL ORDER 1,199.88

    The lines are the net figures, so the check has to be allowed to compare
    against `total - tax` as well. Returns 0 when no tax is printed.
    """
    tax = Decimal("0")
    for raw in (text or "").splitlines():
        line = _clean(raw)
        if not _TAX_LINE.search(line) or _TOTAL_LINE.search(line):
            continue
        m = _MONEY.search(line[_TAX_LINE.search(line).end():])
        if not m:
            vals = _MONEY.findall(line)
            m_val = _dec(vals[0]) if vals else Decimal("0")
        else:
            m_val = _dec(m.group(1))
        if m_val > 0:
            tax = m_val
    return tax


def _amount_after_label(lines: list, idx: int, max_values: int = 3) -> Decimal:
    """
    The figure of a total whose label printed on its own line.

    Walks the following lines, skipping blank ones, while they carry no letters
    (a bare number, or a short column of them) and returns the LAST
    money-SHAPED value found - a summary block prints its piece count first and
    the amount underneath:

        TOTAL P.O.      <- label line
        240             <- pieces: 3 digits, no separator - not money-shaped
        (cid:10)        <- glyph codes, blank after cleaning
        120000.00       <- the figure

    "Money-shaped" is what keeps this safe: a bare small integer is a count, so
    a form that prints only a count under its total is still reported as
    NO TOTAL rather than judged against a piece count.

    Returns Decimal("0") when nothing qualifying follows.
    """
    found = Decimal("0")
    seen = 0
    for j in range(idx + 1, len(lines)):
        nxt = _fuse_split_figures(_clean(lines[j])).strip()
        if not nxt:
            continue
        if re.search(r"[A-Za-z]", nxt):
            break                    # a new labelled field - stop here
        for val in _MONEY.findall(nxt):
            if "." in val or "," in val or len(val) >= 4:
                found = _dec(val)
                seen += 1
        if seen >= max_values:
            break
    return found


def page_totals(pages) -> list:
    """One printed total per page that states one.

    A single PDF sometimes carries several separate purchase orders, one per
    page (the Blossoms export does exactly that: ten pages, ten DIFFERENT PO
    numbers, ten totals). Comparing the sum of ALL extracted lines against a
    single page's total would then report a false OVER. Reading a total per
    page keeps the comparison like-for-like.
    """
    out = []
    for p in pages or []:
        t = p.get("text") or ""
        r = printed_total(t)
        if r:
            m = re.search(r"\b\d{3,6}-\d{3,7}\b", t)
            out.append({"total": r["amount"],
                        "po_hint": m.group(0) if m else ""})
    return out


def printed_qty_total(text: str):
    """A piece count printed beside the total ('Total 42 36,565.00'), or None."""
    for line in text.splitlines():
        if not _TOTAL_LINE.search(line):
            continue
        m = _TOTAL_QTY.search(line)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


# A unit price above this is not a price on a home-appliance PO. It is either
# a mangled reading (digits glued together across columns) or a quantity that
# swallowed the amount. Reported separately so it does not drown the total.
IMPLAUSIBLE_PRICE = Decimal("200000")


def line_sum(records) -> tuple:
    """(sum of qty x unit_price, lines contributing, lines with a suspect price)."""
    total = Decimal("0")
    used = 0
    suspect = []
    for r in records or []:
        q = _dec(r.get("quantity"))
        p = _dec(r.get("unit_price"))
        if p > IMPLAUSIBLE_PRICE:
            suspect.append((r.get("material_code") or "?", p))
            continue
        if q and p:
            total += q * p
            used += 1
    return total, used, suspect


def amount_sum(records) -> tuple:
    """
    (sum of the printed AMOUNT column, lines that carry one, lines whose own
    qty x price disagrees with that amount).

    Independent of `sum(qty * price)` on purpose - see the module docstring.
    A line without a printed amount simply does not add to either side.
    """
    total = Decimal("0")
    used = 0
    inconsistent = []
    for r in records or []:
        a = _dec(r.get("amount"))
        if not a:
            continue
        total += a
        used += 1
        q = _dec(r.get("quantity"))
        p = _dec(r.get("unit_price"))
        if q and p and p <= IMPLAUSIBLE_PRICE and q * p != a:
            inconsistent.append((r.get("material_code") or "?",
                                 f"{q} x {p} = {q * p}",
                                 f"printed {a}"))
    return total, used, inconsistent


def duplicate_pages(pages) -> int:
    """How many pages repeat an earlier page verbatim.

    Some POs (Blossoms) print the whole order on every page. The extractor
    reads each page, so those lines are counted once per copy and the total
    comes out many times too high. Counting the repeats lets the check say so
    instead of blaming the numbers.
    """
    seen, dupes = set(), 0
    for p in pages or []:
        t = re.sub(r"\s+", " ", (p.get("text") or "")).strip()
        if len(t) < 40:            # a nearly empty page is not evidence
            continue
        if t in seen:
            dupes += 1
        else:
            seen.add(t)
    return dupes


def audit_one(engine, pdf_path: str, by_line: bool = False) -> dict:
    """Check one PDF. Returns a verdict dict; never raises for a bad PDF."""
    name = os.path.basename(pdf_path)
    try:
        res = engine.extract_material_codes(pdf_path, force=True)
    except Exception as e:
        return {"file": name, "verdict": "ERROR",
                "detail": f"{type(e).__name__}: {e}", "printed": None,
                "extracted": None, "lines": 0}

    records = res.get("records") or []
    try:
        pages = engine.get_pages(pdf_path, engine.load_config())
    except Exception:
        pages = []
    text = "\n".join(p.get("text", "") for p in pages)

    printed = printed_total(text)
    per_page = page_totals(pages)
    got, used, suspect = line_sum(records)
    qty_printed = printed_qty_total(text)
    qty_got = sum(int(_dec(r.get("quantity"))) for r in records)
    dupes = duplicate_pages(pages)

    # Several separate POs in one file: the figure to match is their sum, not
    # the last page's own total.
    multi_po = len(per_page) > 1
    if multi_po:
        summed = sum((p["total"] for p in per_page), Decimal("0"))
        printed = {"amount": summed,
                   "line": f"{len(per_page)} separate POs in this file",
                   "kind": "per-page sum"}

    base = {
        "file": name,
        "po": res.get("po_number") or "",
        "lines": len(records),
        "lines_priced": used,
        "duplicate_pages": dupes,
        "multi_po": multi_po,
        "suspect_prices": suspect,
        "printed": printed["amount"] if printed else None,
        "printed_line": printed["line"] if printed else "",
        "printed_kind": printed["kind"] if printed else "",
        "extracted": got,
        "qty_printed": qty_printed,
        "qty_extracted": qty_got,
    }

    if by_line:
        amt_total, amt_used, inconsistent = amount_sum(records)
        base["amount_total"] = amt_total
        base["amount_lines"] = amt_used
        base["amount_inconsistent"] = inconsistent
        if printed is not None and amt_used and amt_total != got \
                and got == printed["amount"]:
            # qty x price agrees but the documents' own amounts do not: the
            # quantity and the price have swapped places in the reading.
            base["verdict"] = "SWAPPED"
            base["detail"] = (f"qty x price adds up, but the AMOUNT column "
                              f"sums to {amt_total:,.2f} instead of "
                              f"{printed['amount']:,.2f} - a quantity and a "
                              f"price disagree on "
                              f"{len(inconsistent)} line(s)")
            base["diff"] = got - printed["amount"]
            return base

    if printed is None:
        base["verdict"] = "NO TOTAL"
        base["detail"] = "the document prints no total this check can read"
        return base

    # A repeated page makes the sum meaningless before any comparison: the
    # lines were counted N times. Say that instead of reporting OVER.
    if dupes:
        base["verdict"] = "DUP PAGES"
        base["detail"] = (f"{dupes} page(s) repeat an earlier page verbatim, so "
                          f"every line is counted more than once")
        base["diff"] = got - printed["amount"]
        return base

    diff = got - printed["amount"]
    if got == 0 and printed["amount"] > 0:
        base["verdict"] = "ZERO"
        base["detail"] = "a total is printed but no priced line was extracted"
        base["diff"] = diff
        return base

    if diff == 0:
        base["verdict"] = "OK"
        base["detail"] = "sum(qty x price) equals the printed total"
        base["diff"] = diff
        return base

    # A tax-inclusive total cannot be matched by the goods lines - the engine
    # reads the net figures, and it should. Accept `total - tax` before
    # reporting a false SHORT.
    tax = printed_tax(text)
    if tax and got == printed["amount"] - tax:
        base["verdict"] = "OK"
        base["detail"] = (f"net sum equals the printed total less tax "
                          f"({printed['amount']:,.2f} - {tax:,.2f})")
        base["diff"] = Decimal("0")
        base["printed_net"] = printed["amount"] - tax
        return base

    # Explain the direction, which is what tells you what went wrong.
    if diff < 0:
        base["verdict"] = "SHORT"
        base["detail"] = f"extracted sum is {abs(diff):,.2f} LOWER than printed"
    else:
        base["verdict"] = "OVER"
        base["detail"] = f"extracted sum is {abs(diff):,.2f} HIGHER than printed"
    base["diff"] = diff
    if qty_printed is not None:
        base["qty_note"] = (f"pieces {qty_got} extracted vs {qty_printed} printed")
    if suspect:
        base["detail"] += (f"; {len(suspect)} price(s) too large to be a unit "
                           f"price were left out of the sum")
    return base


def _pdfs(arg=None) -> list:
    if arg:
        return [arg]
    engine = __import__("engine")
    found = sorted(engine.UPLOAD_DIR.glob("*.pdf")) + \
        sorted(engine.UPLOAD_DIR.glob("*.PDF"))
    # '._PO 2147.pdf' is a macOS Finder sidecar, not a document
    return [str(p) for p in found if not engine.is_mac_sidecar(p)]


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    verbose = "--verbose" in argv or "-v" in argv
    by_line = "--by-line" in argv
    args = [a for a in argv if not a.startswith("-")]

    try:
        import engine
    except Exception as e:
        print(f"Cannot import engine.py: {type(e).__name__}: {e}")
        return 2

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    files = _pdfs(args[0] if args else None)
    if not files:
        print("No PDFs found in data_upload.")
        return 2

    # A folder sweep must visit each document ONCE. glob('*.pdf') and
    # glob('*.PDF') are a case-insensitive match on Windows, so every file
    # used to be checked twice and each failure was printed twice.
    seen, unique = set(), []
    for f in files:
        key = os.path.normcase(os.path.abspath(f))
        if key not in seen:
            seen.add(key)
            unique.append(f)
    files = unique

    results = [audit_one(engine, f, by_line=by_line) for f in files]

    ask = ("SHORT", "OVER", "ZERO", "ERROR", "DUP PAGES", "SWAPPED")
    bad = [r for r in results if r["verdict"] in ask]
    checkable = [r for r in results if r["verdict"] not in ("NO TOTAL",)]
    ok = [r for r in results if r["verdict"] == "OK"]

    print("=" * 78)
    print("ARITHMETIC CHECK  -  sum(qty x unit_price) vs the total each PO prints")
    if by_line:
        print("                     plus the AMOUNT column, line by line")
    print("=" * 78)
    print(f"{'file':<40}{'lines':>6}{'extracted':>14}{'printed':>14}  verdict")
    print("-" * 78)
    for r in results:
        ext = f"{r['extracted']:,.2f}" if r["extracted"] is not None else "-"
        prn = f"{r['printed']:,.2f}" if r["printed"] is not None else "-"
        print(f"{r['file'][:39]:<40}{r['lines']:>6}{ext:>14}{prn:>14}  {r['verdict']}")
        if verbose or r["verdict"] in ask:
            print(f"    {r['detail']}")
            if r.get("printed_line"):
                print(f"    printed: {r['printed_line'][:66]}")
            if r.get("qty_note"):
                print(f"    {r['qty_note']}")
        for code, price in (r.get("suspect_prices") or [])[:5]:
            print(f"    ! {code}: unit price {price:,.2f} is not plausible")
        if by_line and r.get("amount_total") is not None:
            print(f"    amount column sums to {r['amount_total']:,.2f} "
                  f"over {r['amount_lines']} line(s)")
        if by_line:
            for code, calc, printed_amt in (r.get("amount_inconsistent") or [])[:6]:
                print(f"    ! {code}: {calc} but {printed_amt}")

    print("-" * 78)
    print(f"{len(ok)}/{len(checkable)} checkable PO(s) agree with their printed "
          f"total; {len(results) - len(checkable)} could not be checked.")
    if bad:
        print(f"\n{len(bad)} PO(s) need a look:")
        for r in bad:
            print(f"  - {r['file']}: {r['verdict']} ({r['detail']})")

    print()
    if not checkable:
        print("Nothing could be checked - no readable totals in these documents.")
        return 2
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
