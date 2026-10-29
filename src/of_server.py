# -*- coding: utf-8 -*-
"""of_server.py

OrderFlow dashboard server: the local HTTP API on 127.0.0.1.

Split out of the former single-file orderflow.py at its SECTION
boundaries; the code is byte-for-byte what used to live there.
The facade namespaces (store, collector, ...) are still built by
orderflow.py, which also late-binds sibling facade names into this
module's globals.
"""

import sys
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import csv
import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import traceback
import webbrowser
import socket
import subprocess

# SYNC_LOCK below is scheduler.LOCK itself, read at import time - the one
# import-time cross-module reference left after the file split.
import of_outlook as _scheduler_mod


# ==========================================================================
#  SECTION: SERVER - local dashboard HTTP API
#  (formerly server.py)
# ==========================================================================

# -*- coding: utf-8 -*-
"""server.py - local dashboard server based on the standard-library http.server"""

import report

from urllib.parse import parse_qs, urlparse

# The DATA EXPORT section above defines data_export / schema / contract_ok at
# module level, so the /api/master_export route reaches them directly.

# The one place the default dashboard port is named. It used to be written out
# twice - 8766 in _same_origin and 8765 in serve() - so with no port saved in
# settings the server bound 8765 while the cross-site guard checked the Host
# header against 8766, and every POST from the page came back 403.
PORT_DEFAULT = 8766

# The port this process ACTUALLY bound. _same_origin compares the Host header
# against this, not against the configured value: when the configured port is
# taken and serve() moves to the next free one, checking the old number made
# the page refuse its own requests. Written once, right after the bind.
_BOUND_PORT = {"port": None}


def _progress(done, total, phase=""):
    """Publish the collector's position to SYNC, which the page polls.

    `total` stays 0 when Outlook will not say how many items the filter matched;
    the page reads that as "no percentage to show" and animates instead of
    inventing one.
    """
    SYNC["done"] = int(done or 0)
    SYNC["total"] = int(total or 0) if int(total or 0) > 0 else 0
    if phase:
        SYNC["phase"] = phase


def _run_pipeline(conn, master, settings, on_date=None, progress=None):
    """Collect immediately from the dashboard after a settings change (same logic as main.run_pipeline).
    If on_date is given, fetch only that single day from Outlook."""
    base = settings.get("_base", "")
    collector.LAST_DIAG["hint"] = ""
    mails = collect(settings, conn, base, on_date=on_date, progress=progress)
    new = 0
    empty = sum(1 for m in mails if not m.get("sender") and not m.get("subject"))
    for m in mails:
        customer, po, _e = classify(m, master, settings)
        m["customer"], m["po_number"] = customer, po
        d, kind, r = check_duplicate(conn, customer, po, m, settings)
        m["is_duplicate"], m["dup_kind"], m["dup_reason"] = int(d), kind, r
        m["cancel_flag"] = int(is_cancellation(m, settings))
        if store.insert_mail(conn, m):
            new += 1
    latest = max((m.get("received_at") or "" for m in mails), default="")
    SYNC["hint"] = collector.LAST_DIAG.get("hint", "")
    return len(mails), new, empty, latest[:10]


def _master_values(mail, master):
    """The values an Order Upload for this mail is built with.

    Sold-To and Ship-To are the pair picked on screen for this row and are
    passed through as stored: one domain owns many pairs, so there is no
    sensible default to choose - matching only settles which customer the mail
    belongs to.

    **The Ship-To block typed on the Inbox row travels with it too.** These
    twelve fields (N O-P-Q R S-T-U-V W X AZ - `store.TYPED_FIELDS`) are
    typed per order and have no master fallback, so whoever drops them drops
    the delivery address: the boxes showed the typed street, `Confirm` ran, and
    the Order Upload came out with R/S-V/W/X empty because this function built
    a fixed five-key dict and threw the rest of the row away. Add a new
    per-order field to `SHIP_DETAIL_FIELDS` and it is carried here
    automatically - do not go back to listing keys by hand.
    """
    out = {"po_number": mail.get("po_number") or "",
           "ship_to": mail.get("ship_to") or "",
           "sold_to": mail.get("sold_to") or "",
           "customer": mail.get("customer") or "",
           # The email's received date. The ERP form's column M is "P/O Date"
           # and is filled from this, so it has to survive the trip from the
           # mail row to the writer - without it M would always be blank.
           "received_at": mail.get("received_at") or ""}

    # Empty boxes are left out rather than passed as "": the ERP cell must stay
    # blank, and _ship_details() already treats a missing key as "not typed".
    for field in store.TYPED_FIELDS:
        value = str(mail.get(field) or "").strip()
        if value:
            out[field] = value

    if out["customer"]:
        return out
    entry = classifier.match_customer(
        mail.get("sender"), mail.get("sender_domain"), master)
    if entry:
        out["customer"] = entry["customer"]
    return out


def _typed_party(body):
    """The Sold-To / Ship-To the row is SHOWING, taken from the request.

    This is the fix for "I picked both and the file came out with F, G and D
    empty". The pickers on the Inbox row do not save what they display: the
    <select> is rendered with a value the page derives from the master
    (`rowPick()` - the stored code if the domain still owns it, else the single
    code the domain has), and /api/update only fires when the user actually
    CHANGES the dropdown. So a row that arrived with one account on file showed
    it, saved nothing, and Confirm built the file from an empty mail row.

    Same principle as `_typed_ship()`: the request carries the values that are
    on screen at the moment the button was pressed, so the file matches what the
    user is looking at. Nothing is invented - an empty selection stays empty and
    the preview says so.

    Returns {} when the row carries neither, so a caller cannot accidentally
    blank a stored value by omitting the key.
    """
    out = {}
    for field in ("sold_to", "ship_to"):
        if field not in (body or {}):
            continue
        value = str(body.get(field) or "").strip()
        # A code, not prose: the ERP column is a 10-digit account number.
        value = "".join(ch for ch in value if ch.isalnum() or ch in "-_")[:20]
        out[field] = value
    return out


def _typed_ship(body):
    """
    The Ship-To block the browser sent WITH the Confirm request, or {}.

    The Inbox rows save a Ship-To box on `onchange` - i.e. when the box loses
    focus - through a separate /api/update request. Clicking Confirm blurs the
    box and fires that save at the same moment it posts /api/action, so the two
    requests race: on a slow disk the file was built from a row that did not
    have the address yet, and the box the user had just filled looked like it
    had been ignored. Confirm therefore carries the values that are on screen,
    and they are written down before extraction starts.

    Only the twelve fields a person can type are accepted, so this cannot
    become a general-purpose write of arbitrary request keys.
    """
    sent = (body or {}).get("ship")
    if not isinstance(sent, dict):
        return {}
    out = {}
    for field in store.TYPED_FIELDS:
        if field in sent:
            out[field] = str(sent.get(field) or "").strip()
    return out


def _persist_typed_ship(conn, mail_id, typed):
    """
    Write the block Confirm received onto the mail row, so the file and the row
    can never disagree. An emptied box is written as "" - the row has to stop
    carrying an address the user just cleared, or a later re-Confirm would put
    the old one back.
    """
    for field, value in (typed or {}).items():
        store.update_field(conn, mail_id, field, value)


# Background collection progress state (for UI display)
SYNC = {"running": False, "phase": "", "done": 0, "total": 0,
        "found": 0, "new": 0, "error": "", "finished_at": "", "hint": ""}
# Only one collection at a time (prevents overlap of startup auto-collect / manual / scheduler).
# This is scheduler.LOCK itself, not a separate lock - two independent locks previously let a
# scheduled sync and a manual "Save & Collect Now" run concurrently, each opening its own Outlook
# COM session on a different thread, which caused intermittent wrong-folder / wrong-mailbox results.
SYNC_LOCK = _scheduler_mod.LOCK


def sync_status():
    return dict(SYNC)


def run_sync_bg(db_path, master, settings):
    """Collect in the background after the server is up (does not block the UI).
    Skips if a collection is already running - concurrent runs would process the same mails twice."""
    import datetime as _dt
    if not SYNC_LOCK.acquire(blocking=False):
        print("[INFO] A sync is already running - skipping this one.")
        return
    SYNC.update({"running": True, "phase": "Collecting emails…",
                 "done": 0, "total": 0, "found": 0, "new": 0, "error": ""})
    conn = store.connect(db_path)
    try:
        found, new, empty, latest = _run_pipeline(conn, master, settings,
                                                  progress=_progress)
        SYNC.update({"found": found, "new": new, "phase": "Done"})
    except Exception as e:
        SYNC["error"] = str(e)
        SYNC["phase"] = "Failed"
        print(f"[ERROR] sync failed: {e}")
    finally:
        conn.close()
        SYNC["running"] = False
        SYNC["finished_at"] = _dt.datetime.now().isoformat(timespec="seconds")
        SYNC_LOCK.release()


def _save_settings(settings):
    sp = settings.get("_settings_path")
    if sp:
        clean = {k: v for k, v in settings.items() if not k.startswith("_")}
        # Written in one step, for the same reason the master files are: this
        # is rewritten on every Save, so an in-place truncate plus a crash
        # would leave settings.json unparseable and the app unable to start.
        tmp = f"{sp}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, sp)


def make_handler(db_path, master, settings):
    # The identity list, re-read whenever the CUSTOMER DATA changes on disk.
    #
    # `master` is computed once in main(). Both tables are edited from the
    # browser though - ERP upload, "+ Add row", an inline cell edit, Clear - and
    # a domain that arrives that way has to be recognised on the very next
    # request, or the PO screen would offer no Sold-To / Ship-To for it until
    # the server restarted. `master_key()` is the change signal for BOTH files
    # (mtime+size), so a dashboard poll costs two stats and not a walk of 7,000
    # rows.
    _cache = {"key": None, "master": master}
    # The conflict list for the dashboard, on the same signal: see the call
    # site in /api/dashboard.
    _conflicts_cache = {"key": None, "value": []}

    def _master():
        # ⚠️ Both tables, not just the pair table. A customer is a DOMAIN, so
        # a row added to the domain table - which is the only thing that gives
        # a domain a customer name - changes this list too. Keying on the pair
        # file alone meant "add a domain row" did nothing visible in the Inbox
        # until the server was restarted (2026-10-27).
        key = ship_master.master_key(settings)
        if key != _cache["key"]:
            # Read first, THEN record the key. Recording it before the read
            # would leave a failed read cached as "already up to date", and
            # every later request would be served the stale list.
            fresh = ship_master.domain_master(settings)
            _cache["key"] = key
            _cache["master"] = fresh
        return _cache["master"]

    def _dm_status():
        """Headline numbers for the domain table's own card."""
        recs = ship_master.dm_rows(settings)
        meta = ship_master.dm_load(settings)
        return {"total": len(recs),
                "domains": len(ship_master.dm_count(settings)),
                "uploaded_at": meta.get("uploaded_at", ""),
                "source_file": meta.get("source_file", "")}

    class Handler(BaseHTTPRequestHandler):

        def log_message(self, fmt, *args):
            pass  # suppress console logging

        def _send(self, body, ctype="application/json; charset=utf-8", code=200):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            # Every response here is live state - the page is rebuilt from
            # src/report.py per request and the JSON comes straight from the
            # database - so nothing is cacheable. Without this a cached page
            # after an update is indistinguishable from "the dashboard did not
            # change", and the only way out is a hard refresh.
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code=200):
            self._send(json.dumps(obj, ensure_ascii=False), code=code)

        def _same_origin(self):
            """
            Cross-site guard for every state-changing endpoint.

            Being bound to 127.0.0.1 is a network position, not an access
            control: any page the user has open can POST to this server. A
            cross-origin <form enctype="text/plain"> is a SIMPLE request - no
            preflight - so /api/master_clear (wipes both customer tables),
            /api/mm_clear, /api/domain_row_clear, /api/cleanup (deletes files)
            and /api/reset_processing were all blind-fireable from anywhere
            on the web.

            Two checks, both only enforced when the header is actually sent:

              * Host must be ours. This stops DNS rebinding, where a name the
                attacker owns resolves to 127.0.0.1 and the browser happily
                talks to this server carrying a foreign Host header.
              * Origin / Referer, when present, must be our own page. A
                missing header is allowed - curl and a console script have no
                browser policy to send one, and this tool is meant to be
                scriptable.
            """
            import urllib.parse
            # The bound port wins over the configured one: after serve() moves
            # to a free port, the Host header carries the NEW number and only
            # that one is ours.
            port = str(_BOUND_PORT["port"]
                       or settings.get("server", {}).get("port", PORT_DEFAULT))
            mine = {"127.0.0.1", "localhost", "127.0.0.1:" + port,
                    "localhost:" + port}

            host = (self.headers.get("Host") or "").split(",")[0].strip()
            if host and host not in mine:
                return False

            for key in ("Origin", "Referer"):
                raw = (self.headers.get(key) or "").strip()
                if not raw or raw.lower() == "null":
                    continue
                try:
                    netloc = urllib.parse.urlsplit(raw).netloc
                except Exception:
                    return False
                if netloc and netloc not in mine:
                    return False
            return True

        def do_GET(self):
            # A master that cannot be read raises instead of quietly looking
            # empty (see of_master._read_json). Without this guard that
            # exception escapes the handler, so the browser sees a dropped
            # connection and a blank page instead of the reason.
            try:
                self._do_GET()
            except Exception as e:
                try:
                    self._json({"error": str(e)}, 500)
                except Exception:
                    pass

        def _do_GET(self):
            # Route on the path alone. A page URL can pick up a query string -
            # a bookmark, a tracking parameter, someone typing ?tab=today - and
            # every branch below matches the path exactly, so the request used
            # to fall through all of them and answer a raw JSON 404 instead of
            # the app. The page reads no parameters, so dropping the query is
            # safe. /api/master_export is the one route that DOES read them, so
            # the raw string is kept aside first.
            raw = self.path
            self.query = parse_qs(urlparse(raw).query)
            self.path = self.path.split("?", 1)[0]
            if self.path == "/" or self.path.startswith("/index"):
                self._send(report.render_page(), "text/html; charset=utf-8")
            elif self.path == "/api/sync_state":
                # Polled by the page while a collection runs, so the full-screen
                # indicator can show a real percentage when Outlook will say how
                # many items matched, and animate when it will not.
                self._json(sync_status())

            elif self.path == "/api/codes":
                try:
                    self._json({"reviews": material_master.pending_reviews(settings),
                                "materials": material_master.items(settings),
                                "customers": [m["customer"] for m in _master()]})
                except Exception as e:
                    self._json({"error": str(e)}, 500)

            elif self.path == "/api/master_export":
                # Download the master data as the upload template's twin.
                # GET, so the browser handles it like any other download.
                # scope=filter narrows to what the list on screen shows.
                # set=... picks which of the two upload files to build.
                try:
                    q = self.query
                    # The schema key is "customers" but the file the user sees
                    # is the Ship-To locations master, so either spelling (or
                    # just its first letter) picks it. "d" is the domain table,
                    # the third upload file. Anything unrecognised falls back
                    # to materials rather than erroring.
                    head = str((q.get("set") or [""])[0]).strip().lower()
                    if head.startswith("d"):
                        name = "domains"
                    elif head.startswith(("c", "s")):
                        name = "customers"
                    else:
                        name = "materials"
                    scope = "filter" if str(
                        (q.get("scope") or [""])[0]).startswith("f") \
                        else "all"
                    codes = [c for c in (q.get("code") or []) if c.strip()]
                    custs = [c for c in (q.get("customer") or [])
                             if c.strip()]
                    search = str((q.get("q") or [""])[0]).strip()
                    data, fn, n = export_data(
                        settings, name, scope=scope,
                        customers=custs or None, codes=codes or None,
                        q=search)
                except Exception as e:
                    self._json({"error": str(e)}, 400)
                    return
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{fn}"')
                self.send_header("X-Row-Count", str(n))
                self.send_header("Cache-Control", "no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                print(f"[export] {fn}: {n} row(s), scope={scope}")

            elif self.path.startswith("/download/"):
                # Serve a generated Order Upload file to the browser as a
                # download. Only bare file names inside data/erp_upload are
                # allowed - no path components.
                from urllib.parse import unquote
                name = os.path.basename(unquote(self.path[len("/download/"):]))
                outdir = os.path.join(settings.get("_base", ""),
                                      "data", "erp_upload")
                p = os.path.join(outdir, name)
                if not name or not os.path.isfile(p):
                    self._json({"error": "file not found"}, 404)
                    return
                with open(p, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            elif self.path == "/api/read_list":
                # The register behind the Inbox's "Read" tab: every order
                # document that has a reading on disk. Served from the
                # extraction CACHE, so opening the tab cannot cost an API call -
                # the whole point is to look at what has ALREADY been read.
                #
                # One row per ATTACHMENT, not per mail: an email with four POs
                # is four readings and four separate output files.
                try:
                    conn = store.connect(db_path)
                    sold_names = {}
                    try:
                        for r in ship_master.rows(settings):
                            code = str(r.get("sold_to_code") or "").strip()
                            name = str(r.get("sold_to_name") or "").strip()
                            if code and name and code not in sold_names:
                                sold_names[code] = name
                    except Exception:
                        pass
                    rows = []
                    _mb = str((settings.get("outlook") or {})
                              .get("mailbox_name") or "")
                    mails = conn.execute(
                        "SELECT * FROM mails WHERE excluded=0 "
                        "AND lower(coalesce(mailbox,''))=lower(?) "
                        "ORDER BY received_at DESC LIMIT 400", (_mb,)
                    ).fetchall()
                    for m in mails:
                        mail = dict(m)
                        docs = store.order_attachments(
                            json.loads(mail.get("pdf_paths") or "[]"),
                            settings.get("_base", ""))
                        if not docs:
                            continue
                        try:
                            states = json.loads(
                                mail.get("att_states") or "{}")
                        except Exception:
                            states = {}
                        for idx, path in docs:
                            summary = extractor_bridge.read_summary(
                                settings, path)
                            if not summary:
                                continue
                            st = states.get(str(idx)) or {}
                            status = st.get("status") or mail.get("status")
                            sold = str(mail.get("sold_to") or "").strip()
                            rows.append({
                                "id": mail.get("id"),
                                "index": idx,
                                "name": store.att_name(path),
                                "ext": os.path.splitext(path)[1]
                                         .lstrip(".").lower(),
                                "customer": mail.get("customer") or "",
                                "sold_to": sold,
                                "sold_to_name": sold_names.get(sold, ""),
                                "po_number": (summary.get("po_number")
                                              or mail.get("po_number") or ""),
                                # A document can hold several POs; the row then
                                # says "4 POs" and the expanded body lists them.
                                "po_count": summary.get("po_count") or 1,
                                "po_numbers": summary.get("po_numbers") or [],
                                "read_at": summary.get("read_at"),
                                "lines": summary.get("lines"),
                                "review": summary.get("review"),
                                "done": status == "Done",
                                "erp_file": st.get("erp_file") or "",
                                "note": st.get("note") or mail.get("note") or "",
                            })
                    self._json({"rows": rows})
                except Exception as e:
                    self._json({"rows": [], "error": str(e)}, 500)

            elif self.path == "/api/master_list":
                # The customer data on its own, for the page to re-read after a
                # row is added or edited on the Customer Master screen.
                #
                # The Inbox draws its Sold-To / Ship-To pickers only for a
                # domain the identity list knows (`domainKnown()` reads
                # DATA.master), so a stale copy means a brand-new domain shows
                # plain text instead of two drop-downs - the "I added the row
                # and the Inbox still will not offer it" report (2026-10-27).
                # Refetching the whole dashboard for that would be ~140 KB per
                # edit; this is the four keys that actually change.
                self._json({"master": _master(),
                            "erp": ship_master.status(settings),
                            "domain_status": _dm_status(),
                            "ship_conflicts": [
                                a + "|" + b for a, b, _n in
                                ship_master.conflicts(
                                    ship_master.rows(settings))]})

            elif self.path == "/api/dashboard":
                conn = store.connect(db_path)
                try:
                    data = store.dashboard_data(
                        conn, settings.get("today_window_days", 1),
                        # Scoped to the mailbox the desk is reading. Passing ""
                        # is not the same as passing None: "" is the default
                        # inbox, and it must exclude the other stores.
                        mailbox=str((settings.get("outlook") or {})
                                    .get("mailbox_name") or ""))
                    # One entry per DOMAIN - the identity, and a domain can
                    # only appear once in the table, so there is no "two
                    # owners of one domain" payload for the UI to show.
                    data["master"] = _master()
                    data["quick_folder"] = settings.get("quick_folder", "")
                    # "full" (the ERP form) / "simple" (four columns) - the
                    # choice the user made in the Confirm / Quick Convert card.
                    # `erp_formats` is the LIST (both versions can be ticked);
                    # `erp_format` stays as its first entry for the few corners
                    # that can only draw one.
                    data["erp_formats"] = erp_excel.output_formats(
                        settings.get("erp_format"))
                    data["erp_format"] = data["erp_formats"][0]
                    data["pdf_delegation"] = settings.get(
                        "pdf_delegation", True)
                    data["erp"] = ship_master.status(settings)
                    # Rows the Ship-To table should flag red: a (Sold-To,
                    # Ship-To) pair listed more than once with details that
                    # disagree. The export refuses to guess those, so the user
                    # has to fix them here.
                    #
                    # Memoised on the two master files (2026-10-28): this walks
                    # all 7,418 pair rows and used to re-parse the 2.8 MB file
                    # on EVERY dashboard request - 60 s poll, 3 s during a
                    # sync, and every tab the page redrew. It is a pure
                    # function of those files, so the answer cannot change
                    # without `master_key()` changing.
                    _ckey = ship_master.master_key(settings)
                    if _conflicts_cache["key"] != _ckey:
                        _conflicts_cache["key"] = _ckey
                        _conflicts_cache["value"] = [
                            a + "|" + b for a, b, _n in
                            ship_master.conflicts(ship_master.rows(settings))]
                    data["ship_conflicts"] = _conflicts_cache["value"]
                    # AZ "Ship-to Region" is a state code, chosen from a list
                    # rather than typed: a mistyped code is rejected by the
                    # ERP, and a free-text box on a 12-field folded row is
                    # where typos come from. The list is what the Ship-To
                    # master actually carries, so an odd territorial code
                    # (PR, VI) is offered when it is real and never invented.
                    data["ship_states"] = ship_master.states(settings)
                    # The column list itself comes from DATA_SCHEMAS, so the
                    # on-screen grid and the upload template never drift.
                    data["ship_columns"] = [
                        {"key": c["key"], "header": c["header"],
                         "width": c.get("width", 18),
                         "title": c.get("title", "")}
                        for c in data_export.schema("customers")["columns"]]
                    # The same for the second table, so its grid, its upload
                    # template and its export all read one column definition.
                    data["domain_columns"] = [
                        {"key": c["key"], "header": c["header"],
                         "width": c.get("width", 18),
                         "title": c.get("title", "")}
                        for c in data_export.schema("domains")["columns"]]
                    # Headline numbers for the domain table's own card.
                    data["domain_status"] = _dm_status()
                    data["po_presets"] = [
                        {"value": v, "label": t}
                        for v, t in classifier.PO_PRESETS]
                    # Which preset is active. The list above was sent but the
                    # choice was never read by the page, so it could not be set.
                    data["po_regex"] = settings.get("po_regex", "")
                    data["last_collected"] = store.get_meta(conn, "last_collected")
                    data["sync_status"] = sync_status()
                    data["settings"] = {
                        "outlook": settings.get("outlook", {}),
                        "sync": settings.get("sync", {}),
                        # Which collector the mail came from. The page shows
                        # "Sync this date" only when this is "outlook", because
                        # re-reading a date from Outlook is meaningless for any
                        # other source. It was never sent at all, so the page
                        # read `undefined`, the button and its empty-state
                        # prompt were dead, and /api/sync_date was unreachable
                        # from the UI. Outlook COM is the only collector that
                        # exists, so that is the default.
                        "source": settings.get("source", "outlook"),
                    }
                    # The key itself is never sent to the page - only whether
                    # one is stored, so the box can say so.
                    # The PO-reading endpoint, as it will actually be used:
                    # the effect the config file, the stored setting and the
                    # environment resolve to, so an empty box still shows the
                    # address a PO will be sent to. It also carries `key_set`,
                    # so the page has ONE source for "is a token stored" - the
                    # flat `claude_key_set` this replaces said the same thing a
                    # second time, which is how the two get to disagree.
                    data["settings"]["claude"] = \
                        extractor_bridge.po_reading_state(settings)
                    data["sync_state"] = scheduler.state()
                    data["settings"]["retention"] = settings.get(
                        "retention", {})
                    data["disk"] = housekeeping.disk_usage(settings)
                    self._json(data)
                finally:
                    conn.close()
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            self.path = self.path.split("?", 1)[0]   # same as do_GET
            if not self._same_origin():
                self._json({"error": "cross-origin request refused"}, 403)
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self._json({"error": "bad json"}, 400)
                return

            conn = store.connect(db_path)
            try:
                if self.path == "/api/update":
                    if body.get("index") is not None:
                        store.update_att_field(
                            conn, int(body["id"]), int(body["index"]),
                            str(body["field"]), body["value"])
                    else:
                        store.update_field(conn, int(body["id"]),
                                           str(body["field"]), body["value"])
                    self._json({"ok": True})

                elif self.path == "/api/action":
                    mail_id = int(body["id"])
                    action = body.get("action")
                    mail = store.get_mail(conn, mail_id)
                    if not mail:
                        self._json({"error": "mail not found"}, 404)
                        return
                    now = __import__("datetime").datetime.now().isoformat(
                        timespec="seconds")
                    # If index is given, process only that attachment (= individual order)
                    idx = body.get("index")
                    idx = None if idx in (None, "") else int(idx)
                    # Re-root the stored paths: a database carried over from
                    # another PC or folder points at files that are not here.
                    # The narrowing rule lives in store.order_attachments, so
                    # the browser, Confirm and /api/open all agree on which
                    # files are orders and what index each one has.
                    docs = store.order_attachments(
                        json.loads(mail.get("pdf_paths") or "[]"),
                        settings.get("_base", ""))

                    def setf(field, value):
                        if idx is None:
                            store.update_field(conn, mail_id, field, value)
                        else:
                            store.update_att_field(conn, mail_id, idx,
                                                   field, value)

                    if action == "reject":
                        setf("status", "Rejected")
                        setf("confirmed_at", now)
                        self._json({"ok": True})
                    elif action == "confirm":
                        # Confirm exactly the order documents this row stands
                        # for. With no index that is every order attachment -
                        # which is now the same list the browser showed, so a
                        # mail whose first attachment is a price sheet no
                        # longer has that sheet extracted alongside the PO.
                        if idx is None:
                            pdfs = [p for _i, p in docs]
                        else:
                            pdfs = [p for i, p in docs if i == idx]
                        if not pdfs:
                            # This row has no attachment the extractor can read
                            # as a PO - a mail split per attachment can leave a
                            # row holding only a spec sheet or a .txt. Report it
                            # instead of marking the row Done and producing no
                            # file, which reads as a silent failure.
                            self._json({"error":
                                "This row has no order document (PDF or "
                                "Excel) to extract. If the page was open while "
                                "the mail changed, reload it and try again."},
                                404)
                            return
                        missing = [p for p in pdfs if not os.path.exists(p)]
                        if missing and len(missing) == len(pdfs):
                            # The record is in the database but the files are
                            # not on this PC - usually a folder copied from
                            # another machine without data/attachments.
                            self._json({"error":
                                "The attachment file is not on this PC:\n  "
                                + "\n  ".join(os.path.basename(p)
                                              for p in missing)
                                + "\n\nThis email was collected on another PC, "
                                "so only the record came across. Click the "
                                "attachment link in the row to fetch it from "
                                "Outlook again, or press Sync this date to "
                                "collect the day fresh."}, 404)
                            return
                        setf("status", "Done")
                        setf("confirmed_at", now)
                        # Written before extraction starts so a concurrent poll
                        # (another tab, or the background sync poll) sees
                        # "still extracting" instead of a bare empty erp_file,
                        # which otherwise reads as a silent failure. Extraction
                        # itself can take a while (DRM PDFs are delegated to
                        # Acrobat/Word, scanned PDFs are OCR'd), and this whole
                        # request blocks until it is done.
                        setf("note", "Extracting…")
                        # The Ship-To block as it stands on screen RIGHT NOW.
                        # Its own save is a separate request that the browser
                        # fired on blur, a moment ago, and which may still be
                        # in flight - so take the values from the request and
                        # write them down before the file is built. See
                        # _typed_ship().
                        typed = _typed_ship(body)
                        # ...and the two account numbers, for the same reason:
                        # the row's pickers show a value they never saved, so
                        # without this F, G and D came out empty even though
                        # both accounts were on screen.
                        typed.update(_typed_party(body))
                        if typed:
                            _persist_typed_ship(conn, mail_id, typed)
                            mail = store.get_mail(conn, mail_id) or mail
                        # force=False: the preview already read these exact
                        # documents, so reuse that reading instead of paying
                        # for the same extraction twice. If no valid cache
                        # exists (the preview was skipped), the reader simply
                        # extracts.
                        #
                        # `format` may be a LIST since 2026-10-27: both versions
                        # ticked means one reading and two files.
                        ok, msg, made = extractor_bridge.run_extractor_multi(
                            pdfs, settings, _master_values(mail, _master()),
                            body.get("format"), force=False)
                        setf("note", msg[:500])
                        # Always write BOTH slots: a run that asks for one
                        # version after a run that asked for two must not leave
                        # the old second file listed on the row.
                        setf("erp_file", made[0][1] if made else "")
                        setf("erp_file2", made[1][1] if len(made) > 1 else "")
                        xlsx = made[0][1] if made else ""
                        self._json({
                            "ok": True,
                            "message": f"Confirmed. Extractor: {msg}",
                            # The page uses these for step 4 of the flow and
                            # for the download link, instead of having the user
                            # go find the file under Completed.
                            "file": xlsx,
                            "name": os.path.basename(xlsx) if xlsx else "",
                            "url": ("/download/" + os.path.basename(xlsx)
                                    if xlsx else ""),
                            # One entry per file written, each with its own
                            # format, so step 4 can offer both.
                            "files": [{"fmt": f,
                                       "name": os.path.basename(p),
                                       "url": "/download/" + os.path.basename(p)}
                                      for f, p in made]})
                    else:
                        self._json({"error": "unknown action"}, 400)

                elif self.path == "/api/master_rows":
                    # A window of the Ship-To master for the Customer Master table
                    try:
                        limit = int(body.get("limit") or 300)
                        offset = int(body.get("offset") or 0)
                    except (TypeError, ValueError):
                        limit, offset = 300, 0
                    rows_, total = ship_master.page(
                        settings, str(body.get("q", "")), limit, offset)
                    self._json({"rows": rows_, "total": total})

                elif self.path == "/api/master_add":
                    try:
                        at = ship_master.add_row(
                            settings, body.get("row") or {},
                            blank=bool(body.get("blank")))
                    except ValueError as e:
                        self._json({"error": str(e)}, 400)
                        return
                    self._json({"ok": True, "index": at})

                elif self.path == "/api/master_del":
                    ok = ship_master.delete_row(settings, body.get("index"))
                    self._json({"ok": ok} if ok else
                               {"error": "row not found"}, 404)

                elif self.path == "/api/master_set":
                    ok = ship_master.set_cell(
                        settings, body.get("index"), str(body.get("key", "")),
                        body.get("value", ""))
                    if not ok:
                        self._json({"error": "row or field not found"}, 404)
                        return
                    # Saving a cell does not re-read the dashboard, and an edit
                    # is exactly what creates or clears a conflicting pair, so
                    # the red-row list goes back with the answer.
                    self._json({"ok": True, "conflicts": [
                        a + "|" + b for a, b, _n in
                        ship_master.conflicts(ship_master.rows(settings))]})

                elif self.path == "/api/master_clear":
                    # Empty BOTH customer tables. The customer data is two
                    # files now, and a "Clear all" that left the domain table
                    # behind would look like the clear failed; one that cleared
                    # it alone is /api/domain_row_clear.
                    removed = (ship_master.clear(settings)
                               + ship_master.dm_clear(settings))
                    self._json({"ok": True, "removed": removed})

                elif self.path == "/api/quick_convert":
                    # Drag-and-dropped PO file -> Order Upload Excel
                    try:
                        import base64
                        paths, own, blocked, recovered = [], [], [], []
                        # Paths are read in place - no copy, no re-encryption
                        if str(body.get("paths", "")).strip():
                            paths = quick_convert.resolve_paths(body["paths"])
                        for f in (body.get("files") or []):
                            nm = os.path.basename(str(f.get("name", "po")))
                            raw = base64.b64decode(f.get("data", ""))
                            # A DRM-protected PO uploads as its raw container,
                            # because the browser is not a process the agent
                            # decrypts for. Write it out anyway: read back as
                            # python.exe - which IS allow-listed - the same
                            # container comes back as a plain PDF. Refusing
                            # '<##' here without trying is what used to make a
                            # dropped DRM file impossible to convert.
                            drm = raw[:3] == quick_convert.DRM_HEAD
                            try:
                                p = quick_convert.save_input(raw, nm, settings)
                                paths.append(p)
                                own.append(p)   # our copy, delete afterwards
                                if drm:
                                    recovered.append(nm)
                            except Exception as e:
                                # Last resort: the original is still on disk
                                # and readable by path. The browser never
                                # sends one, so look the name up in the
                                # folders the user has already pointed at.
                                found = quick_convert.locate_by_name(
                                    nm, settings, str(body.get("folder", "")))
                                if found:
                                    paths.append(found)  # not ours to delete
                                    recovered.append(nm)
                                else:
                                    blocked.append(f"{nm} ({e})")
                        if not paths:
                            looked = [d for d in
                                      (str(body.get("folder", "")).strip(),
                                       settings.get("quick_folder", ""))
                                      if str(d or "").strip()]
                            self._json({"error": (
                                "Could not read:\n  "
                                + "\n  ".join(blocked)
                                + "\n\nThe uploaded copy could not be written "
                                "somewhere this PC can read it back, and the "
                                "original was not found by name in:\n  "
                                + ("\n  ".join(looked) or "(no folder set)")
                                + "\n\nPut the folder the file is actually in "
                                "into the PO folder box, press Open folder, "
                                "tick the file and press Extract - that reads "
                                "it straight from its path."
                            ) if blocked else "No files received."}, 400)
                            return
                        try:
                            r = quick_convert.convert(
                                paths, settings,
                                str(body.get("po_number", "")).strip(),
                                str(body.get("sold_to", "")).strip(),
                                str(body.get("ship_to", "")).strip())
                        finally:
                            # Delete only the copies we made. Files given by
                            # path belong to the user and are left alone.
                            quick_convert.cleanup_inputs(own)
                        if recovered:
                            r.setdefault("messages", []).insert(
                                0, f"{', '.join(recovered)}: DRM-protected — "
                                   "decrypted on read and processed normally.")
                        if blocked:
                            r.setdefault("messages", []).insert(
                                0, f"{', '.join(blocked)}: skipped — could not "
                                   "be read, and the original was not found by "
                                   "name. Tick it in the PO folder box "
                                   "instead.")
                        r["ok"] = True
                        self._json(r)
                    except Exception as e:
                        self._json({"error": str(e)}, 500)

                elif self.path == "/api/quick_scan":
                    # List PO files in a folder. Reading files in place is
                    # what lets DRM-protected POs be processed at all.
                    try:
                        folder = str(body.get("folder", "")).strip()
                        r = quick_convert.scan_folder(folder)
                        settings["quick_folder"] = r["folder"]
                        _save_settings(settings)
                        r["ok"] = True
                        self._json(r)
                    except Exception as e:
                        self._json({"error": str(e)}, 400)

                elif self.path == "/api/quick_export":
                    # Reviewed lines -> Order Upload Excel
                    # (Material / Quantity / Unit Cost, plus the P/O No. and the
                    #  Sold-To / Ship-To picked on the review card)
                    #
                    # `format` may be a LIST (2026-10-27): both versions ticked
                    # writes both files from the same reviewed lines.
                    try:
                        lines = body.get("lines") or []
                        fmts = erp_excel.output_formats(
                            body.get("format")
                            or settings.get("erp_format"))
                        made = []
                        for one in fmts:
                            path, n = quick_convert.export(
                                lines, settings, str(body.get("tag", "")),
                                str(body.get("po", "")), one,
                                str(body.get("sold_to", "")).strip(),
                                str(body.get("ship_to", "")).strip(),
                                ship=body.get("ship") or {},
                                # The header the PO printed, echoed back from
                                # the page: K / M and the address block. Values
                                # typed on the card override it inside
                                # build_upload_lines.
                                order=body.get("order") or None)
                            made.append({"fmt": one, "path": path,
                                         "count": n,
                                         "name": os.path.basename(path),
                                         "url": "/download/" +
                                                os.path.basename(path)})
                        first = made[0]
                        self._json({"ok": True, "count": first["count"],
                                    "path": first["path"],
                                    "name": first["name"],
                                    "url": first["url"],
                                    "files": made})
                    except Exception as e:
                        self._json({"error": str(e)}, 500)

                elif self.path == "/api/erp_format":
                    # Remember which output the user wants: the full ERP form,
                    # the plain four-column sheet, or BOTH (2026-10-27 - the
                    # choice is a list now). Stored in settings.json so it
                    # survives a restart and applies to both the Confirm button
                    # and Quick Convert.
                    want = erp_excel.output_formats(
                        body.get("formats", body.get("format")))
                    settings["erp_format"] = want
                    _save_settings(settings)
                    self._json({"ok": True, "formats": want, "format": want[0]})

                elif self.path == "/api/quick_open":
                    # os.startfile() RUNS whatever it is handed - an .exe, a
                    # .bat or a .lnk would all execute. This endpoint's job is
                    # only to show the user a document OrderFlow just produced
                    # or read, so it is limited to the file types the tool
                    # works in - the same ALLOWED_EXT Quick Convert enforces
                    # at of_pdf.py. The extension is checked on the RESOLVED
                    # path too, so a link named "po.pdf" pointing at a payload
                    # does not slip through.
                    p = str(body.get("path", ""))
                    real = os.path.realpath(p) if p else ""
                    if not p or not os.path.isfile(real):
                        self._json({"error": "File not found."}, 404)
                        return
                    if os.path.splitext(real)[1].lower() \
                            not in quick_convert.ALLOWED_EXT:
                        self._json({"error":
                                    "That file type cannot be opened from "
                                    "the dashboard."}, 400)
                        return
                    win_focus.open_and_focus(lambda: os.startfile(real))
                    self._json({"ok": True})

                elif self.path == "/api/erp_upload":
                    # Build the Ship-To master from the file downloaded from ERP
                    try:
                        import base64
                        import tempfile
                        raw = base64.b64decode(body.get("data", ""))
                        fname = os.path.basename(
                            str(body.get("filename", "ship_to.xlsx")))
                        tmp = os.path.join(tempfile.mkdtemp(), fname)
                        with open(tmp, "wb") as f:
                            f.write(raw)
                        r = ship_master.upload(settings, tmp, fname)
                        r["ok"] = True
                        self._json(r)
                    except Exception as e:
                        self._json({"error": str(e)}, 500)

                elif self.path == "/api/domain_table_upload":
                    # The SECOND table of the customer data: SOLD_TO_NAME ->
                    # DOMAIN. Its own endpoint and its own file, so uploading
                    # one never drops the other's rows.
                    try:
                        import base64
                        import tempfile
                        raw = base64.b64decode(body.get("data", ""))
                        fname = os.path.basename(
                            str(body.get("filename", "domains.xlsx")))
                        tmp = os.path.join(tempfile.mkdtemp(), fname)
                        with open(tmp, "wb") as f:
                            f.write(raw)
                        r = ship_master.dm_upload(settings, tmp, fname)
                        r["ok"] = True
                        self._json(r)
                    except Exception as e:
                        self._json({"error": str(e)}, 500)

                elif self.path == "/api/domain_row_list":
                    # A window of the domain table for its own grid
                    try:
                        limit = int(body.get("limit") or 300)
                        offset = int(body.get("offset") or 0)
                    except (TypeError, ValueError):
                        limit, offset = 300, 0
                    rows_, total = ship_master.dm_page(
                        settings, str(body.get("q", "")), limit, offset)
                    self._json({"rows": rows_, "total": total})

                elif self.path == "/api/domain_row_add":
                    try:
                        at = ship_master.dm_add(
                            settings, body.get("row") or {},
                            blank=bool(body.get("blank")))
                    except ValueError as e:
                        self._json({"error": str(e)}, 400)
                        return
                    self._json({"ok": True, "index": at})

                elif self.path == "/api/domain_row_del":
                    ok = ship_master.dm_delete_row(settings, body.get("index"))
                    self._json({"ok": ok} if ok else
                               {"error": "row not found"}, 404)

                elif self.path == "/api/domain_row_set":
                    ok = ship_master.dm_set_cell(
                        settings, body.get("index"), str(body.get("key", "")),
                        body.get("value", ""))
                    if not ok:
                        self._json({"error": "row or field not found"}, 404)
                        return
                    self._json({"ok": True})

                elif self.path == "/api/domain_row_clear":
                    # Empty the domain table ONLY. The pair table is untouched -
                    # "Clear all" is per table, because a click that wiped both
                    # would lose the customer data in one go.
                    self._json({"ok": True,
                                "removed": ship_master.dm_clear(settings)})

                elif self.path == "/api/party_options":
                    # Sold-To / Ship-To codes a DOMAIN owns. The domain is the
                    # identity (column C of the master); the Sold-To narrows the
                    # Ship-To list, because the two together are the key the ERP
                    # columns are filled from.
                    #
                    # `domains: [...]` answers the whole Inbox page in ONE round
                    # trip (2026-10-28). The Inbox used to fire one request per
                    # distinct customer - twelve of them for a full page - and
                    # each paid for the same 2.8 MB master read. Batching also
                    # means the page has a single moment when the drop-downs
                    # fill in, instead of one row popping in at a time.
                    many = body.get("domains")
                    if isinstance(many, list):
                        out, seen = {}, set()
                        for d in many[:40]:            # 12 rows a page; 40 is slack
                            d = str(d or "").strip()
                            if not d or d in seen:
                                continue
                            seen.add(d)
                            out[d] = {
                                "domain": classifier.norm_domain(d),
                                "sold_tos": ship_master.sold_options(settings, d),
                                "ship_tos": ship_master.ship_options(settings, d)}
                        self._json({"options": out})
                        return
                    domain = str(body.get("domain")
                                 or body.get("customer", "")).strip()
                    sold_to = str(body.get("sold_to", "")).strip()
                    self._json({
                        "domain": classifier.norm_domain(domain),
                        "sold_tos": ship_master.sold_options(settings, domain),
                        "ship_tos": ship_master.ship_options(settings, domain,
                                                             sold_to)})

                elif self.path == "/api/settings_reset":
                    # The refresh glyph beside the "System" parent. Puts every
                    # stored PREFERENCE back to its default; it does not touch
                    # master data, collected mail, attachments or generated
                    # files, and it deliberately keeps db_path /
                    # attachments_dir / extractor - those are where things
                    # LIVE, not how they behave, and moving them would point
                    # the app at nothing.
                    #
                    # The auth token does NOT go. This is the "reset for
                    # re-testing" button, not a factory reset: it is pressed
                    # between trial runs, and wiping the credential each time is
                    # exactly how a machine ends up re-typing the endpoint and
                    # the token on every launch. Machine configuration
                    # (claude, server) stays; behaviour and desk choices go.
                    try:
                        gone = []
                        for key in ("outlook", "sync", "retention",
                                    "quick_folder", "po_regex", "erp_format",
                                    "pdf_delegation", "source",
                                    "today_window_days"):
                            if key in settings:
                                settings.pop(key, None)
                                gone.append(key)
                        _save_settings(settings)
                        self._json({"ok": True, "reset": gone})
                    except Exception as e:
                        self._json({"error": str(e)}, 500)

                elif self.path == "/api/settings":
                    o = settings.setdefault("outlook", {})
                    if "mailbox_name" in body:
                        o["mailbox_name"] = str(body["mailbox_name"]).strip()
                    if "folder_path" in body:
                        o["folder_path"] = str(body["folder_path"]).strip()
                    if "lookback_days" in body:
                        try:
                            o["lookback_days"] = max(1, int(body["lookback_days"]))
                        except (TypeError, ValueError):
                            pass
                    if "attachments_only" in body:
                        o["attachments_only"] = bool(body["attachments_only"])
                    if "pdf_delegation" in body:
                        settings["pdf_delegation"] = bool(
                            body["pdf_delegation"])
                    if "claude_api_key" in body:
                        # The key PO extraction runs on. An EMPTY box means
                        # "leave what is stored alone" - saving the rest of the
                        # form must not wipe it.
                        want = str(body["claude_api_key"]).strip()
                        if want:
                            settings.setdefault("claude", {})["api_key"] = want
                    if "claude_model" in body:
                        # The model dropdown. Only an ID the endpoint actually
                        # offers is stored; anything else is dropped, because a
                        # wrong ID is a bare HTTP 400 at extraction time.
                        want = str(body["claude_model"] or "").strip()
                        if want:
                            settings.setdefault("claude", {})["model"] = want
                        else:
                            settings.setdefault("claude", {}).pop("model", None)
                    if "claude_base_url" in body:
                        # The PO-reading endpoint. Empty means "go back to the
                        # address in claude_config.json", which is why it is
                        # stored as "" rather than deleted-and-then-stale.
                        settings.setdefault("claude", {})["base_url"] = \
                            str(body["claude_base_url"] or "").strip()
                    if "po_regex" in body:
                        # The machine-wide PO-number rule. Only a value the
                        # preset list actually offers is accepted, so a typo
                        # cannot silently disable PO-number reading; anything
                        # unrecognised falls back to the standard rule ("").
                        want = str(body["po_regex"])
                        settings["po_regex"] = (
                            want if want in classifier.PO_PRESET_VALUES else "")
                    _save_settings(settings)
                    self._json({"ok": True})

                elif self.path == "/api/read_detail":
                    # One expanded row of the Read list: the address, the two
                    # dates, the postal code and the lines, straight out of the
                    # saved reading. Fetched per row because the list itself can
                    # hold hundreds of them.
                    #
                    # The browser sends (id, index) and the server resolves the
                    # path itself - a request naming a file path would be an
                    # arbitrary-file-read endpoint wearing a tab's clothes.
                    try:
                        mail_id = int(body.get("id"))
                        mail = store.get_mail(conn, mail_id)
                        if not mail:
                            self._json({"error": "mail not found"}, 404)
                            return
                        idx = body.get("index")
                        idx = None if idx in (None, "") else int(idx)
                        docs = store.order_attachments(
                            json.loads(mail.get("pdf_paths") or "[]"),
                            settings.get("_base", ""))
                        paths = [p for i, p in docs
                                 if idx is None or i == idx]
                        if not paths:
                            self._json({"error":
                                "This row has no order document to describe."},
                                404)
                            return
                        out = None
                        for p in paths:
                            out = extractor_bridge.read_detail(settings, p)
                            if out and not out.get("error"):
                                break
                        self._json(out or {"error":
                            "This document has no saved reading yet."})
                    except Exception as e:
                        self._json({"error": str(e)}, 500)

                elif self.path == "/api/order_preview":
                    # READ the PO, then describe the file that would be written.
                    # Since 2026-10-23 the reading happens here so the preview
                    # can show the delivery address and the two dates, which are
                    # printed on the document. The generate step reuses this
                    # reading from the cache, so the API is called once.
                    #
                    # Still no file and no database write: nothing is committed
                    # until the preview's own button is pressed.
                    try:
                        mail_id = int(body.get("id"))
                        mail = store.get_mail(conn, mail_id)
                        if not mail:
                            self._json({"error": "mail not found"}, 404)
                            return
                        idx = body.get("index")
                        idx = None if idx in (None, "") else int(idx)
                        docs = store.order_attachments(
                            json.loads(mail.get("pdf_paths") or "[]"),
                            settings.get("_base", ""))
                        pdfs = ([p for _i, p in docs] if idx is None
                                else [p for i, p in docs if i == idx])
                        if not pdfs:
                            self._json({"error":
                                "This row has no order document (PDF or "
                                "Excel) to read. If the page was open while the "
                                "mail changed, reload it and try again."}, 404)
                            return
                        party = _typed_party(body)
                        self._json(extractor_bridge.preview_order(
                            pdfs, settings, mail,
                            typed_ship=_typed_ship(body),
                            sold_to=party.get("sold_to",
                                              mail.get("sold_to") or ""),
                            ship_to=party.get("ship_to",
                                              mail.get("ship_to") or ""),
                            fmt=body.get("format")))
                    except Exception as e:
                        self._json({"error": str(e)}, 500)

                elif self.path == "/api/outlook_test":
                    try:
                        o = settings.setdefault("outlook", {})
                        if "mailbox_name" in body:
                            o["mailbox_name"] = str(
                                body["mailbox_name"]).strip()
                        self._json(test_outlook(settings))
                    except Exception as e:
                        self._json({"error": str(e)}, 500)

                elif self.path == "/api/po_test":
                    # Settings > "Test PO reading". One 16-token round trip
                    # through the same client a real extraction uses, so a
                    # green result means the endpoint, the key and the model
                    # are all right. It never reads a PO, so it costs nothing
                    # measurable and cannot touch the extraction cache.
                    try:
                        self._json(extractor_bridge.test_po_reading(
                            settings,
                            base_url=str(body.get("base_url") or "").strip(),
                            api_key=str(body.get("api_key") or "").strip()))
                    except Exception as e:
                        self._json({"ok": False, "error": str(e),
                                    "hint": "The test itself failed to run."},
                                   500)

                elif self.path == "/api/pick_folder":
                    # A browser can never hand back a real filesystem path from
                    # its own folder picker, so this asks the desktop directly
                    # (tkinter has no browser sandbox) and returns the path the
                    # PO folder box needs. Empty string = user cancelled.
                    try:
                        import tkinter as tk
                        from tkinter import filedialog
                        root = tk.Tk()
                        root.withdraw()
                        root.attributes("-topmost", True)
                        start = str(body.get("start") or "") or None
                        folder = filedialog.askdirectory(
                            parent=root, title="Select the PO folder",
                            initialdir=start) or ""
                        root.destroy()
                        self._json({"folder": folder})
                    except Exception as e:
                        self._json({"error": str(e)}, 500)

                elif self.path == "/api/cleanup":
                    if "attachments_days" in body:
                        try:
                            settings.setdefault("retention", {})[
                                "attachments_days"] = max(
                                    0, int(body["attachments_days"]))
                            _save_settings(settings)
                        except (TypeError, ValueError):
                            pass
                    r = housekeeping.cleanup_attachments(
                        conn, settings, dry_run=bool(body.get("dry_run")))
                    r["disk"] = housekeeping.disk_usage(settings)
                    self._json(r)

                elif self.path == "/api/sync_config":
                    cfg = settings.setdefault("sync", {})
                    if body.get("mode") in ("off", "interval", "times"):
                        cfg["mode"] = body["mode"]
                    if "interval_min" in body:
                        try:
                            cfg["interval_min"] = max(
                                5, int(body["interval_min"]))
                        except (TypeError, ValueError):
                            pass
                    if isinstance(body.get("times"), list):
                        cfg["times"] = [str(t) for t in body["times"] if t]
                    _save_settings(settings)
                    scheduler.refresh_next_due(settings)
                    self._json({"ok": True, "sync": cfg,
                                "state": scheduler.state()})

                elif self.path == "/api/claim_mailbox":
                    # Mail collected before the mailbox column existed belongs
                    # to no mailbox, so it is hidden while one is selected. This
                    # files it, without re-reading a single email.
                    try:
                        n = collector.claim_mailbox(settings, conn)
                        self._json({"ok": True, "claimed": n,
                                    "message": (f"{n} email(s) filed to "
                                                f"this mailbox.") if n else
                                               "Nothing left to file."})
                    except Exception as e:
                        self._json({"error": str(e)}, 500)

                elif self.path == "/api/sync_date":
                    # A specific date was requested from the calendar - collect only that day from Outlook
                    day = str(body.get("date", "")).strip()
                    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
                        self._json({"error": "Invalid date."}, 400)
                        return
                    if not SYNC_LOCK.acquire(blocking=False):
                        self._json({"ok": True, "message":
                                    "A sync is already running — please wait."})
                        return
                    try:
                        SYNC.update({"running": True, "done": 0, "total": 0,
                                     "phase": f"Syncing {day}…"})
                        found, new, empty, latest = _run_pipeline(
                            conn, _master(), settings, on_date=day,
                            progress=_progress)
                        msg = (f"{day}: {found} email(s) found, "
                               f"{new} new saved.")
                        if SYNC.get("hint"):
                            msg += "\n\n" + SYNC["hint"]
                        self._json({"ok": True, "message": msg,
                                    "found": found, "new": new})
                    except Exception as e:
                        self._json({"error": str(e)}, 500)
                    finally:
                        SYNC["running"] = False
                        SYNC_LOCK.release()

                elif self.path == "/api/collect":
                    if not SYNC_LOCK.acquire(blocking=False):
                        self._json({"ok": True, "message":
                                    "A sync is already running — please wait "
                                    "for it to finish."})
                        return
                    try:
                        # "Switch mailbox and read it" used to be two round
                        # trips (POST the setting, then POST collect), and the
                        # first one re-rendered the whole page against the old
                        # mailbox before the second one even started. Taking the
                        # mailbox here makes it one request.
                        want_mb = str(body.get("mailbox") or "").strip()
                        # `in body`, not truthiness: picking "(my default
                        # inbox)" sends "", and `if want_mb:` silently ignored
                        # it - once a named mailbox had been chosen there was no
                        # way back, because the saved value never changed.
                        if "mailbox" in body:
                            settings.setdefault("outlook", {})["mailbox_name"] = want_mb
                            _save_settings(settings)
                        # `error` is cleared here: it survives the previous
                        # run, and the page stops waiting as soon as it sees one.
                        SYNC.update({"running": True, "done": 0, "total": 0,
                                     "phase": "Connecting to Outlook…",
                                     "error": "", "finished_at": ""})
                        found, new, empty, latest = _run_pipeline(
                            conn, _master(), settings, progress=_progress)
                        msg = f"{found} emails found, {new} new saved."
                        if latest:
                            msg += f"\nNewest email date: {latest}"
                        if SYNC.get("hint"):
                            msg += "\n\n" + SYNC["hint"]
                        if empty:
                            msg += (f"\n\nWARNING: {empty} file(s) had no "
                                    f"From/Subject header. If everything shows "
                                    f"blank, delete data\\po_mail.db and "
                                    f"collect again.")
                        if found and not new:
                            msg += ("\n\nNothing new was saved — these emails "
                                    "are already in the database. To re-import "
                                    "them, delete data\\po_mail.db first.")
                        self._json({"ok": True, "message": msg,
                                    "latest_date": latest,
                                    "mailbox": settings.get(
                                        "outlook", {}).get("mailbox_name", "")})
                    except Exception as e:
                        SYNC["error"] = str(e)
                        SYNC["phase"] = "Failed"
                        self._json({"error": str(e)}, 500)
                    finally:
                        SYNC["running"] = False
                        SYNC_LOCK.release()

                elif self.path == "/api/reset_processing":
                    # Reset processing status only (collected mails/Master are kept)
                    conn.execute(
                        "UPDATE mails SET status='Not yet', erp_uploaded=0, "
                        "confirmed_at='', erp_file='', note='', excluded=0")
                    # Re-evaluate the cancellation-candidate flag based on subject keywords
                    for r in conn.execute(
                            "SELECT id, subject FROM mails").fetchall():
                        flag = int(is_cancellation(
                            {"subject": r["subject"]}, settings))
                        conn.execute(
                            "UPDATE mails SET cancel_flag=? WHERE id=?",
                            (flag, r["id"]))
                    conn.commit()
                    n = conn.execute(
                        "SELECT COUNT(*) c FROM mails").fetchone()["c"]
                    self._json({"ok": True,
                                "message": f"Processing state reset for {n} emails."})

                elif self.path == "/api/mm_upload":
                    # Extract only Material Codes from the price list Excel and merge into the master
                    try:
                        import base64
                        import tempfile
                        data = base64.b64decode(body.get("data", ""))
                        fname = os.path.basename(
                            str(body.get("filename", "codes.xlsx")))
                        tmp = os.path.join(tempfile.mkdtemp(), fname)
                        with open(tmp, "wb") as f:
                            f.write(data)
                        col = lambda k: (str(body.get(k, "")).strip()
                                         .upper() or None)
                        r = material_master.upload(
                            settings, tmp, col("code_col"),
                            product_col=col("product_col"),
                            type1_col=col("type1_col"))
                        r["ok"] = True
                        r["file"] = fname
                        self._json(r)
                    except Exception as e:
                        self._json({"error": str(e)}, 500)

                elif self.path == "/api/mm_add":
                    ok, msg = material_master.add_one(
                        settings, str(body.get("code", "")),
                        str(body.get("product", "")),
                        str(body.get("cate1", "")),
                        str(body.get("cate2", "")))
                    self._json({"ok": ok, "message": msg})

                elif self.path == "/api/mm_delete":
                    self._json({"ok": material_master.delete(
                        settings, str(body.get("code", "")))})

                elif self.path == "/api/mm_clear":
                    # Delete the entire master (to re-upload when classifications have piled up incorrectly)
                    self._json({"ok": True,
                                "removed": material_master.clear(settings)})

                elif self.path == "/api/mm_clear_reviews":
                    # "Unknown codes found in POs" -> Clear. Dismisses the list
                    # (all of it, or the codes named in `codes`). It does NOT
                    # approve them and does NOT touch the extraction cache -
                    # see material_master.dismiss_reviews.
                    try:
                        codes = body.get("codes")
                        if codes is not None and not isinstance(codes, list):
                            codes = [codes]
                        n = material_master.dismiss_reviews(settings, codes)
                        self._json({"ok": True, "cleared": n})
                    except Exception as e:
                        self._json({"error": str(e)}, 500)

                elif self.path == "/api/mm_export":
                    try:
                        p = material_master.export_csv(settings)
                        win_focus.open_and_focus(lambda: os.startfile(p))
                        self._json({"ok": True, "path": p})
                    except Exception as e:
                        self._json({"error": str(e)}, 500)

                elif self.path == "/api/master_apply":
                    # Re-match every stored mail against the Ship-To master.
                    # Only the customer (the domain) is written back - the
                    # Sold-To / Ship-To pair stays whatever was picked on the row.
                    n = 0
                    for r in conn.execute(
                            "SELECT id, sender, sender_domain FROM mails"):
                        entry = classifier.match_customer(
                            r["sender"], r["sender_domain"], _master())
                        if not entry:
                            continue
                        conn.execute(
                            "UPDATE mails SET customer=?, retail_builder=? "
                            "WHERE id=?",
                            (entry["customer"], entry.get("role", ""), r["id"]))
                        n += 1
                    conn.commit()
                    self._json({"ok": True,
                                "message": f"Ship-To master applied to {n} POs."})

                elif self.path == "/api/refetch_att":
                    # Re-open mails whose attachments were not saved in Outlook and
                    # download only the attachments again (does not re-collect the mails)
                    mail = store.get_mail(conn, int(body["id"]))
                    if not mail:
                        self._json({"error": "mail not found"}, 404)
                        return
                    ref = mail.get("source_ref") or ""
                    if not ref.startswith("entryid:"):
                        self._json({"error": "This email did not come from "
                                    "Outlook, so it cannot be re-fetched."},
                                   400)
                        return
                    parts = ref.split(":", 2)
                    eid = parts[1]
                    sid = parts[2] if len(parts) > 2 else ""
                    import pythoncom
                    import win32com.client
                    pythoncom.CoInitialize()
                    try:
                        ns = win32com.client.Dispatch(
                            "Outlook.Application").GetNamespace("MAPI")
                        item = (ns.GetItemFromID(eid, sid) if sid
                                else ns.GetItemFromID(eid))
                        adir = os.path.join(
                            settings.get("_base", ""),
                            settings.get("attachments_dir",
                                         "data/attachments"))
                        paths = collector.save_attachments(
                            item, adir, mail["message_id"])
                    except Exception as e:
                        self._json({"error": f"Outlook error: {e}"}, 500)
                        return
                    finally:
                        pythoncom.CoUninitialize()

                    if not paths:
                        self._json({"error":
                                    "Outlook opened the email but no document "
                                    "attachment could be saved. See the "
                                    "console window for the reason."}, 500)
                        return
                    conn.execute("UPDATE mails SET pdf_paths=? WHERE id=?",
                                 (json.dumps(paths, ensure_ascii=False),
                                  mail["id"]))
                    conn.commit()
                    self._json({"ok": True, "count": len(paths)})

                elif self.path == "/api/openmail":
                    mail = store.get_mail(conn, int(body["id"]))
                    if not mail:
                        self._json({"error": "mail not found"}, 404)
                        return
                    ref = mail.get("source_ref") or ""
                    if ref.startswith("entryid:"):
                        parts = ref.split(":", 2)
                        eid = parts[1]
                        sid = parts[2] if len(parts) > 2 else ""
                        import win32com.client
                        import pythoncom
                        pythoncom.CoInitialize()
                        try:
                            ns = win32com.client.Dispatch(
                                "Outlook.Application").GetNamespace("MAPI")
                            item = (ns.GetItemFromID(eid, sid) if sid
                                    else ns.GetItemFromID(eid))

                            def _show():
                                item.Display()
                                try:
                                    item.GetInspector.Activate()
                                except Exception:
                                    pass

                            win_focus.open_and_focus(_show)
                            self._json({"ok": True})
                        finally:
                            pythoncom.CoUninitialize()
                    elif ref and os.path.exists(ref):
                        try:
                            win_focus.open_and_focus(
                                lambda: os.startfile(ref))
                            self._json({"ok": True})
                        except OSError as e:
                            self._json({"error":
                                f"Could not open file ({e}). Check the default "
                                f"app for .eml files in Windows settings."}, 500)
                    elif ref:
                        self._json({"error":
                            f"Email file has been moved or deleted: {ref}"}, 404)
                    else:
                        self._json({"error":
                            "No source reference for this email. It was "
                            "collected before this feature was added — delete "
                            "data/po_mail.db and run again."}, 404)

                elif self.path == "/api/openerp":
                    mail = store.get_mail(conn, int(body["id"]))
                    # `which` = 2 opens the SECOND file (the simple sheet when
                    # both versions were ticked). Default 1 = the primary, so an
                    # older page that sends only `id` keeps working.
                    try:
                        which = int(body.get("which") or 1)
                    except (TypeError, ValueError):
                        which = 1
                    f = (mail or {}).get(
                        "erp_file2" if which == 2 else "erp_file") or ""
                    if f and os.path.exists(f):
                        win_focus.open_and_focus(lambda: os.startfile(f))
                        self._json({"ok": True})
                    else:
                        self._json({"error": "ERP Excel not generated yet "
                                    "(or file was moved)."}, 404)

                elif self.path == "/api/open":
                    mail = store.get_mail(conn, int(body["id"]))
                    if not mail:
                        self._json({"error": "mail not found"}, 404)
                        return
                    # The index is a STORED index, the same one the page renders
                    # for every saved attachment. Opening is not restricted to
                    # order documents - a price sheet or a .txt that arrived
                    # with the PO is still a file the user may want to see - but
                    # the index space has to be the stored one, or the link on
                    # screen points at a different file than it opens.
                    paths = store.resolve_attachments(
                        json.loads(mail.get("pdf_paths") or "[]"),
                        settings.get("_base", ""))
                    idx = int(body.get("index", 0))
                    if 0 <= idx < len(paths) and os.path.exists(paths[idx]):
                        p = paths[idx]
                        win_focus.open_and_focus(lambda: os.startfile(p))
                        self._json({"ok": True})
                    else:
                        self._json({"error": "File not found on disk."}, 404)
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as e:
                self._json({"error": str(e)}, 500)
            finally:
                conn.close()

    return Handler


# ---------------------------------------------------------------------------
# Port allocation - safe start-up even when the configured port is taken
# ---------------------------------------------------------------------------

def port_in_use(port):
    """True when something is listening on 127.0.0.1:<port> right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", int(port))) == 0


def looks_like_orderflow(port):
    """True when the listener answers like the OrderFlow dashboard.

    Used to tell a leftover dashboard instance (which must not be shadowed by
    a second window pointing at it) apart from any other program that happens
    to occupy the port (which is safe to route around).
    """
    try:
        import urllib.request
        with urllib.request.urlopen(
                f"http://127.0.0.1:{int(port)}/", timeout=1.5) as r:
            head = r.read(4096).decode("utf-8", "replace").lower()
        return "orderflow" in head
    except Exception:
        return False


def find_free_port(start, tries=10):
    """The first free port at or after `start`, or None."""
    for p in range(int(start), int(start) + int(tries)):
        if not port_in_use(p):
            return p
    return None


def pids_on_port(port):
    """PIDs of the processes with a socket on 127.0.0.1:<port> (Windows netstat)."""
    try:
        raw = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, timeout=8).stdout or b""
    except Exception:
        return []
    # netstat prints in the console code page (GBK on a Chinese Windows);
    # only the ASCII columns matter here, so decode losslessly-enough.
    out = raw.decode("utf-8", "replace")
    pids = set()
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") \
                and parts[3] == "LISTENING":
            pids.add(parts[-1])
    return sorted(pids)


def refuse_stale_instance(port):
    """A previous dashboard instance still owns the port.

    Starting a second window would show the OLD interface and look exactly
    like 'the dashboard did not change'. Say so, name the PID, and start
    nothing. Never kills anything on its own.
    """
    print(f"[ERROR] Port {port} is already served by an OrderFlow instance.")
    pids = pids_on_port(port)
    for pid in pids:
        print(f"        listener PID: {pid}")
    print("        Close that dashboard window first (or, from a console:")
    for pid in pids:
        print(f"            taskkill /f /pid {pid}")
    print("        ) and start OrderFlow again. Nothing was started here.")


def serve(db_path, master, settings):
    # Start the auto-sync scheduler (collection uses a separate connection)
    def _scheduled_collect():
        c = store.connect(db_path)
        try:
            return _run_pipeline(c, master, settings)
        finally:
            c.close()

    scheduler.start(_scheduled_collect, settings)

    # The engine's code list is a mirror of Master Data > Material Codes.
    # Rebuilding it on every start means it can never drift from the master,
    # whatever else touched the file since the last run.
    try:
        n = material_master.sync_to_engine(settings)
        if n >= 0:
            print(f"[codes] engine code list rebuilt from the master: {n} codes")
    except Exception as e:
        print(f"[WARN] could not rebuild the engine code list: {e}")

    # The export writes the upload file back out, so it is only as trustworthy
    # as the match between DATA_SCHEMAS and the importers. Say so at start-up
    # rather than after someone has exported a file that will not re-import.
    for _name in ("materials", "customers"):
        try:
            _bad = contract_ok(_name)
        except Exception as e:
            _bad = [f"check failed: {e}"]
        for _b in _bad:
            print(f"[WARN] export contract ({_name}): {_b}")

    port = int(settings.get("server", {}).get("port", PORT_DEFAULT))
    ThreadingHTTPServer.allow_reuse_address = False  # prevent running twice on the same port

    # Port conflict handling, in order of preference:
    #   1. the configured port is free          -> bind it (the normal case)
    #   2. an OrderFlow instance owns it        -> refuse to start a second
    #      window onto the old process; name the PID and stop
    #   3. another program owns it              -> move to the next free port
    #      and say so, instead of refusing or (worse) killing anything
    if port_in_use(port):
        if looks_like_orderflow(port):
            refuse_stale_instance(port)
            return
        nxt = find_free_port(port + 1)
        if nxt is None:
            print(f"[ERROR] Port {port} is in use by another program, and no "
                  f"free port was found in {port + 1}..{port + 10}.")
            return
        print(f"[WARN] Port {port} is taken by another program - "
              f"using port {nxt} instead.")
        port = nxt
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port),
                                    make_handler(db_path, master, settings))
    except OSError:
        # Lost the race between the probe above and this bind: someone else
        # took the port in between. Same rule as case 2 - never point a
        # window at a process this run does not own.
        if looks_like_orderflow(port):
            refuse_stale_instance(port)
        else:
            print(f"[ERROR] Port {port} was taken just as this run tried to "
                  f"bind it. Start OrderFlow again.")
        return
    # Publish the port we actually own, for the cross-site guard. Without this
    # a relocated instance rejected its own POSTs (see _same_origin).
    _BOUND_PORT["port"] = port
    print(f"\nDashboard running at http://127.0.0.1:{port}")
    print("Press Ctrl+C or close this window to stop.\n")
    # Open the window only once THIS process owns the port. Arming the timer
    # before the bind - as this used to - opened a browser onto whatever was
    # already listening, so a second launch showed the old instance and looked
    # exactly like "the dashboard did not change".
    if settings.get("server", {}).get("open_browser", True):
        threading.Timer(0.4, lambda: open_ui(port)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


