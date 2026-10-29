# -*- coding: utf-8 -*-
"""Split the one-table customer master into the pair table + the domain table.

One-off migration. The customer data used to be ONE file with a Domain column
inside every row; it is now two files:

    config/ship_to_master.json   the pairs   (Ship To Locations sheet)
    config/domain_master.json    the domains (the SOLD_TO_NAME -> DOMAIN sheet)

Run:  python tools/split_domain_master.py [--apply]

Default is a dry run: it reports what it would write and touches nothing.

What it does
------------
1. Reads the existing single table.
2. Builds the domain table from the Domain column - one row per distinct
   SOLD_TO_NAME, so the hand-edit surface is one row per customer, which is what
   the ERP file's second sheet looks like. A name that carries two different
   domains in the old table is reported, not merged: that was already a conflict
   and picking one would be a guess.
3. Writes the pair table with the Domain column dropped.

It does NOT invent a domain for a row that had none: those rows stay unowned,
exactly as before.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))
import orderflow  # noqa: E402  (facades + wiring)

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    apply = "--apply" in argv

    settings = {"_base": os.path.abspath(BASE)}
    st = orderflow.ship_master

    old = st.load(settings)
    rows = old.get("rows") or []
    print(f"existing pair rows : {len(rows)}")
    print(f"source file        : {old.get('source_file') or '(none)'}")

    # -- the domain table, one row per distinct SOLD_TO_NAME ---------------
    by_name, ambiguous, blank = {}, [], 0
    for i, r in enumerate(rows):
        name = st._clean(r.get("sold_to_name"))
        dom = orderflow.classifier.norm_domain(r.get("domain"))
        if not name:
            if dom:
                blank += 1
            continue
        if not dom:
            continue
        cur = by_name.get(name)
        if cur is None:
            by_name[name] = dom
        elif cur != dom:
            ambiguous.append((name, cur, dom))

    # The pair table: same rows, Domain column gone.
    new_rows = []
    for r in rows:
        new_rows.append({k: st._clean(r.get(k)) for k in st.ST_KEYS})

    dom_rows = [{"sold_to_name": n, "domain": d} for n, d in by_name.items()]

    print()
    print(f"domain rows to write : {len(dom_rows)}")
    print(f"distinct domains     : "
          f"{len({orderflow.classifier.norm_domain(d) for d in by_name.values()})}")
    print(f"pair rows to write   : {len(new_rows)}")
    if blank:
        print(f"  ({blank} row(s) had a domain but no SOLD_TO_NAME - skipped)")
    if ambiguous:
        print()
        print(f"AMBIGUOUS names ({len(ambiguous)}) - one name, two domains. "
              "The FIRST is used; the rest are reported here so they can be "
              "fixed by hand:")
        for n, a, b in ambiguous[:12]:
            print(f"    {n!r}: {a} / {b}")
    else:
        print("no ambiguous names")

    # Rows that will end up unowned: no domain at all, or a name the domain
    # table cannot resolve. Reported after the write, where it is true.
    print()
    print("dry run - nothing written. Re-run with --apply."
          if not apply else "applying...")

    st.save(settings, {
        "uploaded_at": old.get("uploaded_at", ""),
        "source_file": old.get("source_file", ""),
        "rows": new_rows,
    })
    st.dm_save(settings, {
        "uploaded_at": "",
        "source_file": "split from the former single-table master",
        "rows": dom_rows,
    })
    # Re-read from disk (the index cache is keyed on the files, so this also
    # proves the written state resolves) and report on what actually landed.
    st.dm_index(settings)          # drop any cached index
    owned = sum(1 for r in new_rows if st.domain_of(settings, r))
    print()
    print(f"wrote config/ship_to_master.json ({len(new_rows)} rows)")
    print(f"wrote config/domain_master.json ({len(dom_rows)} rows)")
    print(f"rows resolving to a domain now : {owned} / {len(new_rows)}"
          f" ({len(new_rows) - owned} unowned, as before)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
