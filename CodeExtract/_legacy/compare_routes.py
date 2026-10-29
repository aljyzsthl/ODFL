# -*- coding: utf-8 -*-
"""Compare the two PO read routes document by document.

OrderFlow reads a PO one of two ways:

  ROUTE A  "pdf"   CodeExtract/engine.extract_material_codes()
                   Full page geometry: word coordinates, header detection,
                   column bounds, zone templates, OCR, regex fallback.

  ROUTE B  "text"  src/of_core.text_records.from_text()
                   Flat text only, no coordinates. Reached when a DRM-wrapped
                   PDF can only be handed over as TEXT by an authorised
                   application (of_pdf.resolve() returns mode "text", i.e.
                   L4a Acrobat words / L4b Word Content.Text).

HANDOVER 6.6 says "the same PO must read the same through both routes, and
that is a requirement, not a nicety". This script measures whether it does.

It runs BOTH routes over every PDF in data_upload/ that has a text layer -
so no DRM file is needed, because a text-layer PDF exercises exactly the
code path a DRM text handover produces - and reports where they disagree.

Usage:
    python tools/compare_routes.py            # every PDF in data_upload
    python tools/compare_routes.py FILE.pdf   # just one
    python tools/compare_routes.py --json     # machine-readable

Exit code is the number of documents that differ, so it can gate a change.
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, os.path.join(_ROOT, "src"), os.path.join(_ROOT, "CodeExtract")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── the fields an order line is judged on ────────────────────────────────
# These four are what reaches the ERP Order Upload. A difference in any of
# them is a real difference to the customer; a difference in `description`
# is not, so it is deliberately not compared.
FIELDS = ("material_code", "quantity", "unit_price", "amount")


def _norm(value):
    """Canonical form of one cell, for comparison only."""
    s = "" if value is None else str(value).strip()
    return s


def _num(value):
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except Exception:
        return None


def _money_key(value):
    """
    A price compared NUMERICALLY, so "199" and "199.00" are the same amount.

    They are still reported separately as `format` (see classify()), because
    _money_2dp exists precisely so the two routes cannot print the same
    amount two different ways - a silent format drift is how the extended
    cost started masquerading as a unit price.
    """
    n = _num(value)
    return None if n is None else round(n, 4)


def _row_key(r):
    return (_norm(r.get("material_code")),
            _norm(r.get("quantity")),
            _money_key(r.get("unit_price")),
            _money_key(r.get("amount")))


def _rows_of(result):
    out = []
    for r in result.get("records") or []:
        out.append({
            "code": _norm(r.get("material_code")),
            "qty": _norm(r.get("quantity")),
            "price": _norm(r.get("unit_price")),
            "amount": _norm(r.get("amount")),
            "mode": r.get("match_type", ""),
            "math_error": r.get("math_error", ""),
        })
    return out


# ── classification ──────────────────────────────────────────────────────
def classify(pdf_rows, txt_rows):
    """
    Why do the two routes disagree on this document?

    Returns (verdict, details) where verdict is one of
      identical          the two agree on every order line
      format             same numbers, different spelling ("199" vs "199.00")
      missing_on_text    a code the engine published, the text route lost
      extra_on_text      a code the text route published, the engine did not
      value_diff         same code, different quantity or price
      mixed              more than one of the above
    """
    p_by_code = {}
    t_by_code = {}
    for r in pdf_rows:
        p_by_code.setdefault(r["code"], []).append(r)
    for r in txt_rows:
        t_by_code.setdefault(r["code"], []).append(r)

    kinds, details = set(), []

    for code in sorted(set(p_by_code) | set(t_by_code)):
        p, t = p_by_code.get(code, []), t_by_code.get(code, [])
        if p and not t:
            kinds.add("missing_on_text")
            details.append(f"missing_on_text {code}: engine {p[0]['qty']} @"
                           f" {p[0]['price']}")
            continue
        if t and not p:
            kinds.add("extra_on_text")
            details.append(f"extra_on_text {code}: text {t[0]['qty']} @"
                           f" {t[0]['price']}")
            continue
        # same code on both sides - compare its figures
        for a, b in zip(p, t):
            if _money_key(a["price"]) != _money_key(b["price"]) \
                    or _money_key(a["amount"]) != _money_key(b["amount"]) \
                    or _norm(a["qty"]) != _norm(b["qty"]):
                kinds.add("value_diff")
                details.append(
                    f"value_diff {code}: engine qty={a['qty']} price={a['price']}"
                    f" amount={a['amount']} | text qty={b['qty']}"
                    f" price={b['price']} amount={b['amount']}")
            elif (a["price"], a["amount"]) != (b["price"], b["amount"]):
                kinds.add("format")
                details.append(
                    f"format {code}: engine {a['price']}/{a['amount']} vs "
                    f"text {b['price']}/{b['amount']}")

    if not kinds:
        return "identical", []
    if kinds == {"format"}:
        return "format", details
    if len(kinds) == 1:
        return kinds.pop(), details
    return "mixed", details


# ── the two routes ──────────────────────────────────────────────────────
def read_text_layer(engine, pdf_path, cfg):
    """Plain text of a PDF, exactly as an L4 text handover would deliver it."""
    pages = engine.get_pages(pdf_path, cfg)
    return "\n".join(p.get("text") or "" for p in pages)


def run(pdf_path, as_json=False):
    # orderflow, not of_core: `text_records` is one of the facade objects the
    # entry point builds in its flat namespace - importing the module alone
    # does not give you it (see HANDOVER 2.1). This is exactly the coupling
    # the comparison exists to keep honest.
    import engine
    import orderflow as OF

    cfg = engine.load_config()
    settings = {"_base": _ROOT}

    name = os.path.basename(pdf_path)

    # Route A - the PDF engine
    try:
        a = engine.extract_material_codes(pdf_path, force=True)
    except Exception as e:
        return {"file": name, "verdict": "engine_failed", "details": [str(e)]}

    # Route B - the text reader, fed the same document's plain text
    text = read_text_layer(engine, pdf_path, cfg)
    if not text.strip():
        return {"file": name, "verdict": "no_text_layer",
                "details": ["scanned - OCR only, no text route to compare"]}
    try:
        b = OF.text_records.from_text(text, settings, source=name)
    except Exception as e:
        return {"file": name, "verdict": "text_failed", "details": [str(e)]}

    pdf_rows, txt_rows = _rows_of(a), _rows_of(b)
    verdict, details = classify(pdf_rows, txt_rows)
    return {
        "file": name,
        "verdict": verdict,
        "details": details,
        "engine": pdf_rows,
        "text": txt_rows,
        "engine_mode": a.get("extraction_mode", ""),
    }


def main(argv):
    want_json = "--json" in argv
    args = [a for a in argv if not a.startswith("--")]
    if args:
        pdfs = [os.path.abspath(a) for a in args]
    else:
        folder = os.path.join(_ROOT, "CodeExtract", "data_upload")
        pdfs = sorted(
            os.path.join(folder, f) for f in os.listdir(folder)
            if f.lower().endswith(".pdf"))

    results = [run(p) for p in pdfs]
    comparable = [r for r in results
                  if r["verdict"] not in ("no_text_layer", "engine_failed",
                                          "text_failed")]
    differing = [r for r in comparable if r["verdict"] != "identical"]

    if want_json:
        print(json.dumps({"results": results,
                          "comparable": len(comparable),
                          "differing": len(differing)}, ensure_ascii=False,
                         indent=2))
        return len(differing)

    print("=" * 78)
    print("ROUTE COMPARISON  -  PDF engine  vs  DRM text route")
    print("=" * 78)
    for r in results:
        mark = {"identical": "  ok  ", "format": " fmt  "}.get(r["verdict"],
                                                               " DIFF ")
        print(f"{mark} {r['file'][:52]:54s} {r['verdict']}")
        for d in r["details"][:6]:
            print(f"        {d}")

    print("-" * 78)
    print(f"documents compared : {len(comparable)}")
    print(f"identical          : {len(comparable) - len(differing)}")
    print(f"differing          : {len(differing)}")
    by = {}
    for r in differing:
        by[r["verdict"]] = by.get(r["verdict"], 0) + 1
    for k, v in sorted(by.items(), key=lambda kv: -kv[1]):
        print(f"   {k:22s} {v}")
    skipped = [r for r in results if r not in comparable]
    if skipped:
        print(f"not comparable     : {len(skipped)} (no text layer / error)")
    print("=" * 78)
    return len(differing)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
