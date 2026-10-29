# -*- coding: utf-8 -*-
"""
engine_baseline.py - "did my change alter a result I already had?"

Replaces the golden set (deleted 2026-10-19). The golden set asked "is this
right?" and needed a hand-filled answer workbook - which was never in the
tree, and whose check silently SKIPPED instead of failing, so it guarded
nothing. This asks the cheaper and more useful question instead:

    "is this different from what the engine produced last time?"

No answer key, no annotations. Every run of the extractor is a fingerprint of
the engine's behaviour on real POs; the baseline pins that fingerprint, and
`compare` shows exactly which line of which PO moved.

    python engine_baseline.py capture      pin the current results
    python engine_baseline.py compare      what changed since the baseline?
    python engine_baseline.py show         print the stored baseline

Exit codes for `compare`:  0 = identical   1 = drift   2 = no baseline yet

Reading a diff
--------------
    + WF45B6300AP      NEW      a line that was not there before
    - DW80R9950QN/AA   GONE     a line that disappeared
    ~ RF18A5101SR/AA   qty      6 -> 2        was 6, now 2
    ~ RF18A5101SR/AA   price    599.00 -> 1198.00

A diff is not automatically a regression - it is a prompt to look. When the
new numbers are the ones you want, re-run `capture` to accept them.

What it deliberately does NOT do
--------------------------------
- It cannot tell you a value is CORRECT, only that it is UNCHANGED. A value
  that was always wrong never shows as drift. The arithmetic check
  (sum(qty x unit_price) vs the PO's printed total) is the complement; see
  docs/COLUMN_ALIGNMENT.md 4.2.
- It compares values, not column positions, so a price moved to the wrong
  column is still invisible. See docs/COLUMN_ALIGNMENT.md 4.1.

The PDFs in data_upload are read on this machine; '._' Finder sidecars are
skipped. On a PC where the documents cannot be read the baseline comes out
empty - capture on a machine that can read them, or drop readable POs in.

"Lines" here means EVERY field an order line carries - code, quantity, unit
price and amount - not just the quantity. Amount is included because it is the
field the dashboard shows and the ERP upload does not recompute: a line whose
amount column lost its bounds kept a plausible qty and a plausible price and
compared identical, which is exactly the drift this tool exists to show.
The 'amount' field is only compared where BOTH sides carry one, so a baseline
taken before 2026-10-20 (when amounts were not stored) still works.
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

BASELINE_PATH = BASE_DIR / "engine_baseline.json"
BASELINE_VERSION = 1

# Fields compared per line. Order is also the order they are reported in.
# 'amount' was added 2026-10-20 (see the docstring for why).
LINE_FIELDS = ("quantity", "unit_price", "amount")
ENTRY_FIELDS = ("code",) + LINE_FIELDS


def _import_engine():
    try:
        import engine
    except Exception as e:                       # pragma: no cover
        print(f"Cannot import engine.py: {type(e).__name__}: {e}")
        raise SystemExit(2)
    return engine


def _sorted_lines(lines: list) -> list:
    """Stable order for a PO's lines; tolerates an older entry without them."""
    return sorted(lines, key=lambda x: tuple(str(x.get(f) or "")
                                             for f in ENTRY_FIELDS))


def _pdfs(engine) -> list:
    """Every PDF the baseline is measured against, sorted for stable output."""
    pdfs = sorted(p for p in engine.UPLOAD_DIR.glob("*.pdf")
                  if not engine.is_mac_sidecar(p))
    if not pdfs:
        print(f"No PDFs in {engine.UPLOAD_DIR}")
        print("  Put the real POs the engine should not regress on in there.")
    return pdfs


def _snapshot(engine) -> dict:
    """Extract every PDF and reduce it to the values worth guarding.

    Returns {po_or_filename: {"source": name, "mode": ..., "lines": [...]}}
    where `lines` is a sorted list of {code, quantity, unit_price}.
    """
    snap = {}
    for pdf in _pdfs(engine):
        try:
            res = engine.extract_material_codes(str(pdf), force=True)
        except Exception as e:
            # A crash is itself a fact worth recording: it must not silently
            # look like "this PO has no lines".
            snap[pdf.name] = {
                "source": pdf.name,
                "mode": "error",
                "error": f"{type(e).__name__}: {e}",
                "lines": [],
            }
            print(f"  ! {pdf.name}: {type(e).__name__}: {e}")
            continue

        lines = []
        for r in res.get("records") or []:
            lines.append({
                "code": str(r.get("material_code") or ""),
                "quantity": str(r.get("quantity") or ""),
                "unit_price": str(r.get("unit_price") or ""),
                "amount": str(r.get("amount") or ""),
            })
        # Sort so that a change in extraction order is not reported as drift.
        lines = _sorted_lines(lines)

        # Key on the PO number, but keep the filename: two POs can share a
        # number across customers, and a PO that fails to be recognised keys
        # on the filename instead of collapsing into "".
        key = str(res.get("po_number") or "").strip() or pdf.name
        entry = {
            "source": pdf.name,
            "mode": res.get("extraction_mode") or "",
            "lines": lines,
        }
        if key in snap:
            entry["source"] = f"{snap[key]['source']} + {pdf.name}"
            entry["lines"] = _sorted_lines(snap[key]["lines"] + lines)
            entry["mode"] = "combined"
        snap[key] = entry
    return snap


def capture(quiet: bool = False) -> int:
    engine = _import_engine()
    snap = _snapshot(engine)
    payload = {
        "version": BASELINE_VERSION,
        "note": "Written by engine_baseline.py capture. Commit this file.",
        "pos": snap,
    }
    BASELINE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")

    total = sum(len(v["lines"]) for v in snap.values())
    if not quiet:
        print(f"Baseline captured: {len(snap)} PO(s), {total} line(s)")
        print(f"  written to {BASELINE_PATH}")
        if not total:
            print("  ! The baseline is EMPTY - the PDFs could not be read on "
                  "this machine")
            print("    (the data_upload POs are NASCA DRM files). Capture on a "
                  "PC that can read")
            print("    them, or add readable POs to data_upload and re-capture.")
    return 0


def load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        return {}
    try:
        data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Baseline unreadable ({e}). Run: capture")
        return {}
    if data.get("version") != BASELINE_VERSION:
        print(f"Baseline is version {data.get('version')}, "
              f"this tool writes {BASELINE_VERSION}. Run: capture")
        return {}
    return data.get("pos") or {}


def compare() -> int:
    old = load_baseline()
    if not old:
        print("No baseline yet.")
        print("  Run:  python engine_baseline.py capture")
        return 2

    engine = _import_engine()
    new = _snapshot(engine)

    drift = 0
    for key in sorted(set(old) | set(new)):
        before = old.get(key)
        after = new.get(key)

        if before is None:
            print(f"\nPO {key}  [NEW PO]  ({after['source']})")
            for ln in after["lines"]:
                print(f"    + {ln['code']:<20} NEW")
            drift += 1
            continue
        if after is None:
            print(f"\nPO {key}  [PO NO LONGER EXTRACTED]  "
                  f"was {before['source']}")
            drift += 1
            continue

        if before.get("mode") != after.get("mode"):
            print(f"\nPO {key}  mode {before.get('mode')} -> "
                  f"{after.get('mode')}")
            drift += 1
        if before.get("error") or after.get("error"):
            if before.get("error") != after.get("error"):
                print(f"\nPO {key}  error {before.get('error')!r} -> "
                      f"{after.get('error')!r}")
                drift += 1
            continue

        # Compare as multisets so a repeated line keeps its multiplicity.
        b = list(before.get("lines") or [])
        a = list(after.get("lines") or [])

        removed = []
        for ln in b:
            if ln in a:
                a.remove(ln)
            else:
                removed.append(ln)
        added = a

        # Pair removed/added lines that share a code: those are field CHANGES
        # on the same order line, which read better than a delete plus an add.
        # A field is only compared where BOTH sides carry it - a baseline from
        # before 'amount' existed must not report 217 additions of "".
        changes = []
        for rl in list(removed):
            for al in added:
                if al["code"] == rl["code"]:
                    changed = {f: (rl.get(f, ""), al.get(f, ""))
                               for f in LINE_FIELDS
                               if f in rl and f in al
                               and rl.get(f) != al.get(f)}
                    if not changed:
                        # Same line, a field the baseline never stored: not
                        # drift, just a field the two sides cannot compare.
                        removed.remove(rl)
                        added.remove(al)
                        break
                    changes.append((rl["code"], changed))
                    removed.remove(rl)
                    added.remove(al)
                    break

        if not (changes or added or removed):
            continue

        print(f"\nPO {key}  ({after['source']})")
        for ln in added:
            print(f"    + {ln['code']:<20} NEW      "
                  f"qty={ln['quantity'] or '-'} "
                  f"price={ln['unit_price'] or '-'} "
                  f"amount={ln.get('amount') or '-'}")
        for ln in removed:
            print(f"    - {ln['code']:<20} GONE     "
                  f"qty={ln['quantity'] or '-'} "
                  f"price={ln['unit_price'] or '-'} "
                  f"amount={ln.get('amount') or '-'}")
        for code, changed in changes:
            for field, (was, now) in changed.items():
                print(f"    ~ {code:<20} {field:<8} {was or '-'} -> {now or '-'}")
        drift += 1

    print()
    if drift == 0:
        print("No change: every PO matches the baseline.")
        return 0
    print(f"{drift} PO(s) differ from the baseline.")
    print("  Look at each one. If the new values are what you want, run:")
    print("      python engine_baseline.py capture")
    return 1


def show() -> int:
    data = load_baseline()
    if not data:
        print("No baseline yet. Run: capture")
        return 2
    for key in sorted(data):
        entry = data[key]
        print(f"PO {key}  ({entry.get('source')})  mode={entry.get('mode')}")
        for ln in entry.get("lines") or []:
            print(f"    {ln['code']:<20} qty={ln['quantity'] or '-':<8} "
                  f"price={ln['unit_price'] or '-':<12} "
                  f"amount={ln.get('amount') or '-'}")
    return 0


USAGE = """Usage:
    python engine_baseline.py capture    pin the current results as the baseline
    python engine_baseline.py compare    what changed since the baseline?
    python engine_baseline.py show       print the stored baseline
"""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "compare"
    if cmd == "capture":
        return capture()
    if cmd == "compare":
        return compare()
    if cmd == "show":
        return show()
    print(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main())
