# -*- coding: utf-8 -*-
"""Port-mechanism probe (replaces the handover-stripped serve_probe):
 - port_in_use / find_free_port
 - looks_like_orderflow distinguishes a real dashboard from a foreign server
 - a real serve() refuses to start a second window on an OrderFlow-owned port
Run:  python .workbuddy/port_probe.py
"""
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "src")
sys.stdout.reconfigure(errors="replace")
import orderflow  # noqa: E402  (facades + wiring)
from of_server import port_in_use, find_free_port, looks_like_orderflow  # noqa

fails = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# 1 - free / busy detection
p = free_port()
check("free port reports not in use", not port_in_use(p))
srv = ThreadingHTTPServer(("127.0.0.1", p), BaseHTTPRequestHandler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.2)
check("listening port reports in use", port_in_use(p))

# 2 - foreign server is not mistaken for OrderFlow
check("foreign server not mistaken for OrderFlow",
      not looks_like_orderflow(p))

# 3 - a page mentioning OrderFlow is recognised
class OFHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<html><title>OrderFlow</title></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


p2 = free_port()
srv2 = ThreadingHTTPServer(("127.0.0.1", p2), OFHandler)
threading.Thread(target=srv2.serve_forever, daemon=True).start()
time.sleep(0.2)
check("OrderFlow-like server recognised", looks_like_orderflow(p2))

# 4 - find_free_port skips busy ports
nxt = find_free_port(p2)
check("find_free_port skips the busy port", nxt is not None and nxt > p2,
      f"-> {nxt}")

# 5 - serve() on an OrderFlow-owned port refuses instead of shadowing
settings = {"server": {"port": p2, "open_browser": False}, "_base": os.getcwd()}
import io, contextlib  # noqa: E402
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    orderflow.server.serve("data/po_mail.db", {}, settings)
out = buf.getvalue()
check("serve() refuses an OrderFlow-owned port",
      "already served by an OrderFlow instance" in out and "PID" in out,
      out.strip().splitlines()[0] if out.strip() else "(no output)")
check("refusal names a PID from netstat", "listener PID:" in out)

srv.shutdown(), srv2.shutdown()
print()
print("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S): {fails}")
sys.exit(1 if fails else 0)
