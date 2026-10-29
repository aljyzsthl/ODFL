# -*- coding: utf-8 -*-
"""End-to-end check of the two-table customer data over the real HTTP handler.

Uploads BOTH sheets of the ERP file the way the browser does (base64 POST), then
drives the grid, edit, export and lookup endpoints and prints what came back.

Run:  python tools/check_two_table_master.py <path-to-erp-file.xlsx>
"""
import base64
import json
import os
import sys
import tempfile
import threading
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))
import orderflow  # noqa: E402
from of_server import make_handler  # noqa: E402

BASE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    ".."))


def post(port, path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}",
                                timeout=60) as r:
        return r.status, r.headers, r.read()


def main():
    if len(sys.argv) < 2:
        print("usage: check_two_table_master.py <erp-file.xlsx>")
        return 2
    src = sys.argv[1]
    if not os.path.isfile(src):
        print("not a file:", src)
        return 2

    # A scratch base so the real config is never touched.
    base = tempfile.mkdtemp(prefix="of2t_")
    settings = {"_base": base, "server": {"port": 0, "open_browser": False}}

    # Split the workbook into the two uploads the browser would send.
    import openpyxl
    wb = openpyxl.load_workbook(src, read_only=True)
    sheets = {}
    for name in wb.sheetnames:
        ws = wb[name]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        # Formulas are not readable values; the importer would read them as
        # text, so strip them the way a values-only save would.
        rows = [["" if (c is not None and str(c).startswith("=")) else c
                 for c in r] for r in rows]
        sheets[name] = rows
    wb.close()
    print(f"workbook sheets: {list(sheets)} "
          f"({', '.join(f'{k}={len(v)} rows' for k, v in sheets.items())})")

    hdl = make_handler(os.path.join(base, "po_mail.db"), {}, settings)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), hdl)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"handler on 127.0.0.1:{port}\n")

    def upload(path, fname, rows):
        import io
        from openpyxl import Workbook
        out = Workbook()
        ws = out.active
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        out.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return post(port, path, {"filename": fname, "data": b64})

    # -- the pair sheet ----------------------------------------------------
    pair_sheet = next(iter(sheets.values()))
    r = upload("/api/erp_upload", "Ship To Locations.xlsx", pair_sheet)
    print("erp_upload ->", {k: r.get(k) for k in
                            ("ok", "rows", "domains", "sold_tos", "ship_tos",
                             "conflict_count")})
    assert not r.get("error"), r

    # -- the domain sheet --------------------------------------------------
    dom_sheet = sheets[wb.sheetnames[1]] if len(wb.sheetnames) > 1 else None
    if dom_sheet:
        r = upload("/api/domain_table_upload", "Domains.xlsx", dom_sheet)
        print("domain_table_upload ->", {k: r.get(k) for k in
                                        ("ok", "rows", "domains", "named",
                                         "unmatched_names")})
        assert not r.get("error"), r

    # -- the dashboard payload --------------------------------------------
    st, hd, body = get(port, "/api/dashboard")
    d = json.loads(body.decode())
    print("\ndashboard payload:")
    print("  erp            :", d.get("erp"))
    print("  domain_status  :", d.get("domain_status"))
    print("  ship_columns   :", [c["header"] for c in d.get("ship_columns", [])])
    print("  domain_columns :", [c["header"] for c in d.get("domain_columns", [])])
    assert "domain" not in [c["key"] for c in d.get("ship_columns", [])], \
        "the pair table must not carry a domain column"

    # -- both grids --------------------------------------------------------
    r = post(port, "/api/master_rows", {"limit": 5, "offset": 0})
    print("\nmaster_rows  -> total", r.get("total"), "| first row keys:",
          sorted(r["rows"][0].keys()) if r.get("rows") else None)
    r = post(port, "/api/domain_row_list", {"limit": 5, "offset": 0})
    print("domain_row_list -> total", r.get("total"), "| first row:",
          r["rows"][0] if r.get("rows") else None)

    # -- editing both tables ----------------------------------------------
    r = post(port, "/api/master_add", {"blank": True})
    print("\nmaster_add blank -> index", r.get("index"))
    post(port, "/api/master_set", {"index": r["index"], "key": "sold_to_name",
                                   "value": "ZZ TEST ROW"})
    r = post(port, "/api/domain_row_add",
             {"row": {"sold_to_name": "ZZ TEST ROW", "domain": "zztest.com"}})
    print("domain_row_add -> index", r.get("index"))
    di = r["index"]
    post(port, "/api/domain_row_set", {"index": di, "key": "domain",
                                       "value": "zztest2.com"})
    r = post(port, "/api/domain_row_list", {"q": "zztest", "limit": 5})
    print("  ...edit landed:", r["rows"][0] if r.get("rows") else None)

    # -- party options resolve through the join ---------------------------
    dom = None
    r = post(port, "/api/domain_row_list", {"q": "", "limit": 1})
    if r.get("rows"):
        dom = r["rows"][0]["domain"]
        r = post(port, "/api/party_options", {"domain": dom})
        print(f"\nparty_options({dom}) -> sold_tos={len(r.get('sold_tos', []))} "
              f"ship_tos={len(r.get('ship_tos', []))}")

    # -- both exports ------------------------------------------------------
    for name in ("customers", "domains"):
        st, hd, body = get(port, f"/api/master_export?set={name}")
        import io
        from openpyxl import load_workbook
        wb2 = load_workbook(io.BytesIO(body))
        ws2 = wb2.active
        print(f"export set={name} -> {ws2.max_row - 1} row(s), headers:",
              [c.value for c in next(ws2.iter_rows(max_row=1))])
        assert st == 200

    # -- clearing is per table --------------------------------------------
    r = post(port, "/api/domain_row_clear", {})
    print("\ndomain_row_clear -> removed", r.get("removed"))
    r = post(port, "/api/master_rows", {"limit": 1})
    print("  pair table still has", r.get("total"), "row(s)")
    r = post(port, "/api/master_clear", {})
    print("master_clear -> removed", r.get("removed"))

    srv.shutdown()
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
