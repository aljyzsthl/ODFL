# -*- coding: utf-8 -*-
"""of_core.py

OrderFlow core data layer: the SQLite store, customer/PO classification, duplicate detection and plain-text PO records.

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


# ==========================================================================
#  SECTION: STORE - SQLite schema and CRUD
#  (formerly store.py)
# ==========================================================================

# -*- coding: utf-8 -*-
"""store.py - SQLite schema and CRUD"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS mails (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id    TEXT UNIQUE NOT NULL,
    received_at   TEXT,
    sender        TEXT,
    sender_domain TEXT,
    subject       TEXT,
    attachments   TEXT DEFAULT '[]',
    pdf_paths     TEXT DEFAULT '[]',
    customer      TEXT,
    po_number     TEXT,
    is_duplicate  INTEGER DEFAULT 0,
    dup_reason    TEXT DEFAULT '',
    dup_kind      TEXT DEFAULT '',
    status        TEXT DEFAULT 'Not yet',
    retail_builder TEXT DEFAULT '',
    ship_to       TEXT DEFAULT '',
    sold_to       TEXT DEFAULT '',
    erp_uploaded  INTEGER DEFAULT 0,
    note          TEXT DEFAULT '',
    -- Which Outlook store the mail was read from ("" = the default inbox).
    -- Without it two mailboxes collected into one table are indistinguishable,
    -- and picking a mailbox in the Inbox could only change where NEW mail came
    -- from - everything already stored stayed on screen under every mailbox.
    mailbox       TEXT DEFAULT '',
    created_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_mails_received ON mails(received_at);
CREATE INDEX IF NOT EXISTS idx_mails_po ON mails(customer, po_number);
-- idx_mails_mailbox is created by connect(), AFTER the column is added: an
-- index over a column an older table does not have yet makes executescript
-- throw "no such column: mailbox" and the app cannot start at all.
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

# The Ship-To block the user fills on an Inbox row. Column letters are the
# Standard Order Upload ones; see of_erp.COLUMNS for the full mapping.
#
#   N  ship_to_name      Ship-to Name        (defaults to the master, editable)
#   O  ship_to_name2     Ship-to Name 2      \
#   P  ship_to_name3     Ship-to Name 3       |  folded away on screen
#   Q  ship_to_name4     Ship-to Name 4      /
#   R  ship_to_address   Ship-to Address     (always shown)
#   S  ship_to_street2   Ship-to Street 2    \
#   T  ship_to_street3   Ship-to Street 3     |
#   U  ship_to_street4   Ship-to Street 4     |  folded away on screen
#   V  ship_to_street5   Ship-to Street 5     |
#   W  ship_to_zip       Ship-to Postal Code  |
#   X  ship_to_city      Ship-to City        /
#  AZ  ship_to_region    Ship-to Region      (state, chosen from a list)
#
# Address fields are TYPED, never copied from the Ship-To master: the master's
# address is a billing-site address and the delivery address on a PO is
# routinely different. Only the Ship-to Name keeps a master default.
SHIP_DETAIL_FIELDS = ("ship_to_name", "ship_to_name2", "ship_to_name3",
                      "ship_to_name4", "ship_to_address", "ship_to_street2",
                      "ship_to_street3", "ship_to_street4", "ship_to_street5",
                      "ship_to_zip", "ship_to_city", "ship_to_region")

# The two per-ORDER dates. They are not part of the Ship-To block, but they are
# typed on the same row and follow exactly the same rule, so they are carried by
# the same plumbing:
#
#   K   rdd        R.D.D (required delivery date)
#   M   po_date    P/O Date
#
# Precedence for both, and for the address block above: what the operator typed
# > what the PO printed > the computed default (RDD only: PO date + 6 working
# days). An empty box means "use what the PO said", NOT "blank the cell" - the
# ERP form rejects a line without a delivery date, and the document is a better
# source than an empty field.
ORDER_FIELDS = ("rdd", "po_date")

# Everything typed on an Inbox row. The database migration, the Confirm
# pass-through and the writer all iterate THIS, so a field added above cannot be
# silently left behind (which has happened: the address boxes were shown, were
# saved, and never reached the ERP file).
TYPED_FIELDS = SHIP_DETAIL_FIELDS + ORDER_FIELDS

EDITABLE_FIELDS = {"status", "retail_builder", "ship_to", "sold_to",
                   "erp_uploaded", "customer", "po_number", "note",
                   "confirmed_at", "excluded", "cancel_flag",
                   "erp_file", "erp_file2"} | set(TYPED_FIELDS)

ATT_FIELDS = {"status", "confirmed_at", "erp_file", "erp_file2", "note",
              "erp_uploaded", "po_number"}


def get_att_states(conn, mail_id):
    row = conn.execute("SELECT att_states FROM mails WHERE id=?",
                       (mail_id,)).fetchone()
    if not row:
        return {}
    try:
        return json.loads(row["att_states"] or "{}")
    except Exception:
        return {}


def update_att_field(conn, mail_id, index, field, value):
    """Update a state field for attachment `index` (per-attachment order handling)"""
    if field not in ATT_FIELDS:
        raise ValueError(f"not editable per attachment: {field}")
    st = get_att_states(conn, mail_id)
    key = str(int(index))
    st.setdefault(key, {})[field] = value
    conn.execute("UPDATE mails SET att_states=? WHERE id=?",
                 (json.dumps(st, ensure_ascii=False), mail_id))
    conn.commit()
    return st


# Databases whose schema has already been applied by THIS process.
#
# connect() used to run the whole DDL script plus a PRAGMA and a dozen
# conditional ALTERs on every call - and it is called once per HTTP request
# (plus once per collect), so the cost was paid dozens of times per page view
# for a schema that cannot change while the app is running. The first call for a
# given file still does all of it, which is what creates a new database.
#
# Deleting data\po_mail.db while the app runs and pointing it at the same path
# again would need a restart to be picked up - that is a development gesture,
# not a supported one.
_SCHEMA_READY = set()


def connect(db_path):
    key = os.path.abspath(str(db_path))
    ready = key in _SCHEMA_READY
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if ready:
        return conn
    conn.executescript(SCHEMA)
    # Migration: add source_ref column if missing from an existing DB
    cols = [r[1] for r in conn.execute("PRAGMA table_info(mails)")]
    if "source_ref" not in cols:
        conn.execute("ALTER TABLE mails ADD COLUMN source_ref TEXT DEFAULT ''")
    if "confirmed_at" not in cols:
        conn.execute("ALTER TABLE mails ADD COLUMN confirmed_at TEXT DEFAULT ''")
    if "excluded" not in cols:
        conn.execute("ALTER TABLE mails ADD COLUMN excluded INTEGER DEFAULT 0")
    if "cancel_flag" not in cols:
        conn.execute("ALTER TABLE mails ADD COLUMN cancel_flag INTEGER DEFAULT 0")
    if "erp_file" not in cols:
        conn.execute("ALTER TABLE mails ADD COLUMN erp_file TEXT DEFAULT ''")
    # The SECOND generated file. Since 2026-10-27 the full form and the simple
    # sheet are not alternatives: ticking both writes two files in one Confirm,
    # and a row that offered only one of them would leave the other findable
    # nowhere but data/erp_upload. `erp_file` is always the primary (full when
    # it was written); this is the second (simple), '' when only one was made.
    if "erp_file2" not in cols:
        conn.execute("ALTER TABLE mails ADD COLUMN erp_file2 TEXT DEFAULT ''")
    # Mail with multiple attachments = one order per attachment. Per-index state stored as JSON
    if "att_states" not in cols:
        conn.execute("ALTER TABLE mails ADD COLUMN att_states TEXT DEFAULT '{}'")
    if "att_seq" not in cols:
        conn.execute("ALTER TABLE mails ADD COLUMN att_seq INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE mails ADD COLUMN att_total INTEGER DEFAULT 0")
    # 'repeat' (a real re-receipt) vs 'keyword' (a first receipt whose subject
    # merely suggests a revision). Both used to arrive as is_duplicate=1, so
    # the screen could not tell a duplicate from a brand-new PO.
    if "dup_kind" not in cols:
        conn.execute("ALTER TABLE mails ADD COLUMN dup_kind TEXT DEFAULT ''")
    # The store a mail was read from. Added 2026-10-26: the Inbox's mailbox
    # picker used to be a collection source only, so every mail ever collected
    # appeared under every mailbox. Rows written before this column existed keep
    # '' until backfill_mailbox() claims them from the StoreID already recorded
    # in source_ref.
    if "mailbox" not in cols:
        conn.execute("ALTER TABLE mails ADD COLUMN mailbox TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mails_mailbox "
                 "ON mails(mailbox, received_at)")
    # Everything typed on an Inbox row - the Ship-To block plus the two dates.
    # An empty value means "use what the PO printed" (and, for RDD, the computed
    # default), never "blank the ERP cell": clearing a box must not turn a
    # delivery address the document stated into an empty column.
    #
    # One migration for the whole set, driven by TYPED_FIELDS: a field added to
    # that tuple is created here automatically, which is what stopped the old
    # hand-written list from drifting behind the set of editable fields.
    for _f in TYPED_FIELDS:
        if _f not in cols:
            conn.execute(f"ALTER TABLE mails ADD COLUMN {_f} TEXT DEFAULT ''")
    conn.commit()
    _SCHEMA_READY.add(key)
    return conn


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key, value):
    conn.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    conn.commit()


def insert_mail(conn, m):
    """Save one collected mail. Skip if message_id already exists. Returns: whether saved"""
    try:
        conn.execute(
            """INSERT INTO mails(message_id, received_at, sender, sender_domain,
                   subject, attachments, pdf_paths, customer, po_number,
                   is_duplicate, dup_reason, dup_kind, source_ref, cancel_flag,
                   att_seq, att_total, mailbox, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (m["message_id"], m["received_at"], m["sender"], m["sender_domain"],
             m["subject"], json.dumps(m.get("attachments", []), ensure_ascii=False),
             json.dumps(m.get("pdf_paths", []), ensure_ascii=False),
             m.get("customer"), m.get("po_number"),
             m.get("is_duplicate", 0), m.get("dup_reason", ""),
             m.get("dup_kind", ""),
             m.get("source_ref", ""), m.get("cancel_flag", 0),
             m.get("att_seq", 0), m.get("att_total", 0),
             m.get("mailbox", "") or "",
             datetime.datetime.now().isoformat(timespec="seconds")))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # mail already collected


def backfill_mailbox(conn, mailbox, store_id):
    """Claim the rows collected before `mailbox` existed.

    `source_ref` has always carried the Outlook StoreID
    (`entryid:<entry id>:<store id>`), so the mail that came from THIS store can
    be recognised without opening a single item: whatever store we are
    collecting from now owns the unclaimed rows whose StoreID matches. Called on
    every collect, so picking a mailbox in the Inbox heals the history for that
    mailbox in the same click that already re-reads it.

    Returns: how many rows were claimed.
    """
    store_id = str(store_id or "").strip()
    if not store_id:
        return 0
    cur = conn.execute(
        "UPDATE mails SET mailbox=? "
        "WHERE (mailbox IS NULL OR mailbox='') AND instr(source_ref, ?) > 0",
        (mailbox or "", store_id))
    conn.commit()
    return cur.rowcount or 0


def update_field(conn, mail_id, field, value):
    if field not in EDITABLE_FIELDS:
        raise ValueError(f"field not editable: {field}")
    conn.execute(f"UPDATE mails SET {field}=? WHERE id=?", (value, mail_id))
    conn.commit()


def resolve_attachment(path, base):
    """Re-root a stored attachment path onto this installation.

    Attachment paths are written to the database as absolute paths. A database
    that was created on another PC - or in another folder - therefore points at
    files that do not exist here, which used to surface as a bare
    "No such file or directory". Everything below data/attachments is stable,
    so the tail of the path is re-joined to the current base folder.
    """
    p = str(path or "")
    if not p or os.path.exists(p):
        return p
    marker = os.path.join("data", "attachments")
    norm = p.replace("/", os.sep)
    i = norm.lower().find(marker.lower())
    if i >= 0:
        moved = os.path.join(base, norm[i:])
        if os.path.exists(moved):
            return moved
    return p


def resolve_attachments(paths, base):
    return [resolve_attachment(p, base) for p in (paths or [])]


# The attachment kinds an order can arrive as. "pdf_paths" is a legacy column
# name - it holds every saved document, PDF or spreadsheet.
ORDER_DOC_EXT = (".pdf", ".xlsx", ".xlsm", ".xls", ".csv")


def _is_order_doc(path):
    return str(path or "").lower().endswith(ORDER_DOC_EXT)


def order_attachments(paths, base=""):
    """The order documents among a mail's saved attachments, re-rooted.

    Returns [(stored_index, resolved_path), ...] in stored order.

    THE one definition of "which attachments are orders, and in what order".
    The browser, Confirm and the open-file route each used to filter this list
    for themselves - the browser to ".pdf" only, Confirm to all four kinds,
    the open route not at all - so the same row index meant three different
    files:

      pdf_paths = [quote.xlsx, order.pdf]
      browser   -> one row for "order.pdf"      as index 0
      Confirm   -> index 0 is quote.xlsx, and no index at all confirmed BOTH
      /api/open -> index 0 is quote.xlsx

    The index returned is the position in the STORED list, not in the narrowed
    one, because that is what the per-attachment state (att_states) and
    split_by_attachment's "#N" keys are written against. Renumbering here would
    silently re-point every stored per-attachment status.
    """
    return [(i, resolve_attachment(p, base))
            for i, p in enumerate(paths or []) if _is_order_doc(p)]


def order_att_list(paths):
    """The same list for the browser: [{i, name}, ...] - index + display name.

    Shares `_is_order_doc` with order_attachments, so the page cannot disagree
    with the server about which attachment a row index refers to.
    """
    return [{"i": i, "name": att_name(p)}
            for i, p in enumerate(paths or []) if _is_order_doc(p)]


def att_name(path):
    """Display name of a saved attachment: file name, md5 prefix removed."""
    return re.sub(r"^[0-9a-f]{8}_", "", os.path.basename(str(path or "")))


def get_mail(conn, mail_id):
    row = conn.execute("SELECT * FROM mails WHERE id=?", (mail_id,)).fetchone()
    return dict(row) if row else None


def po_exists(conn, customer, po_number, exclude_message_id=None):
    """Whether the same (customer, PO number) already exists - for re-receipt detection"""
    if not customer or not po_number:
        return False
    q = "SELECT COUNT(*) c FROM mails WHERE customer=? AND po_number=?"
    args = [customer, po_number]
    if exclude_message_id:
        q += " AND message_id != ?"
        args.append(exclude_message_id)
    return conn.execute(q, args).fetchone()["c"] > 0


def _rows(conn, query, args=()):
    out = []
    for r in conn.execute(query, args).fetchall():
        d = dict(r)
        d["attachments"] = json.loads(d.get("attachments") or "[]")
        d["pdf_paths"] = json.loads(d.get("pdf_paths") or "[]")
        try:
            d["att_states"] = json.loads(d.get("att_states") or "{}")
        except Exception:
            d["att_states"] = {}
        # Which of those paths are order documents, and the index each one has.
        # Sent to the page so the browser never filters the list itself: that
        # second filter is what let a row's index mean a different file on the
        # screen than on the server (see order_attachments).
        d["att_docs"] = order_att_list(d["pdf_paths"])
        out.append(d)
    return out


def dashboard_data(conn, today_window_days=1, mailbox=None):
    since = (datetime.date.today()
             - datetime.timedelta(days=today_window_days - 1)).isoformat()
    # Every list here belongs to the Inbox, so every list is scoped to the
    # mailbox the desk is reading. `mailbox=None` means "not scoped" (a caller
    # that genuinely wants all mail); "" is a real value - the default inbox.
    #
    # This is the fix for "picking a mailbox still shows the other mailbox's
    # mail": the picker was only a collection source, and these queries asked
    # for every stored mail regardless of which store it came from.
    # Always a non-empty string: the queries below are concatenated without a
    # separator, and an empty one produced "excluded=0ORDER BY".
    if mailbox is None:
        mb_sql, mb_arg = " ", ()
    else:
        mb_sql = " AND lower(coalesce(mailbox,''))=lower(?) "
        mb_arg = (str(mailbox),)
    return {
        # NOTE: `cancel_flag` no longer hides a mail from any of these lists.
        # It used to, which is what kept cancellation emails out of the Inbox
        # and parked them on the Cold Feet screen; that screen is gone, so
        # filtering on the flag here would make those emails invisible with
        # nowhere left to review them. The flag is still set and still shown
        # (dup_kind 'keyword'), it just no longer removes the mail.
        "today": _rows(conn,
            "SELECT * FROM mails WHERE substr(received_at,1,10) >= ? "
            "AND excluded=0" + mb_sql +
            "ORDER BY customer, received_at DESC", (since,) + mb_arg),
        "history": _rows(conn,
            "SELECT * FROM mails WHERE excluded=0" + mb_sql +
            "ORDER BY received_at DESC LIMIT 2000", mb_arg),
        "unclassified": _rows(conn,
            "SELECT * FROM mails WHERE (customer IS NULL OR customer='') "
            "AND excluded=0" + mb_sql + "ORDER BY received_at DESC", mb_arg),
        "duplicates": _rows(conn,
            "SELECT * FROM mails WHERE is_duplicate=1 AND excluded=0"
            + mb_sql + "ORDER BY received_at DESC", mb_arg),
        "unprocessed": _rows(conn,
            "SELECT * FROM mails WHERE status='Done' AND erp_uploaded=0 "
            "AND excluded=0" + mb_sql + "ORDER BY received_at ASC", mb_arg),
        "excluded": _rows(conn,
            "SELECT * FROM mails WHERE excluded=1" + mb_sql +
            "ORDER BY received_at DESC", mb_arg),
        "daily_counts": [dict(r) for r in conn.execute(
            "SELECT substr(received_at,1,10) d, "
            "COALESCE(NULLIF(customer,''), '@'||sender_domain) c, "
            "COUNT(*) n FROM mails "
            "WHERE substr(received_at,1,10) >= date('now','-13 days') "
            "AND excluded=0" + mb_sql +
            "GROUP BY d, c ORDER BY d DESC", mb_arg).fetchall()],
        "weekly_counts": [dict(r) for r in conn.execute(
            "SELECT strftime('%Y-W%W', received_at) w, "
            "COALESCE(NULLIF(customer,''), '@'||sender_domain) c, COUNT(*) n FROM mails "
            "WHERE substr(received_at,1,10) >= date('now','-56 days') "
            "AND excluded=0" + mb_sql +
            "GROUP BY w, c ORDER BY w DESC", mb_arg).fetchall()],
        # Mail collected before the mailbox column existed is not filed to any
        # mailbox, so it is invisible while one is selected - see
        # backfill_mailbox(). The page says so instead of looking empty.
        "unclaimed": conn.execute(
            "SELECT COUNT(*) c FROM mails "
            "WHERE coalesce(mailbox,'')='' AND excluded=0").fetchone()["c"],
    }


# ==========================================================================
#  SECTION: CLASSIFIER - customer matching and PO-number rules
#  (formerly classifier.py)
# ==========================================================================

# -*- coding: utf-8 -*-
"""classifier.py - customer classification by sender DOMAIN + PO number extraction (regex)

A customer is identified by the DOMAIN of the sender address and by nothing
else. The individual address is never consulted, so a new person at a customer
is recognised on their first mail - and nobody can pull a whole customer's mail
onto themselves by being listed as a contact.

The domain list is built from the Ship-To master (ship_master.domain_master()),
whose column C IS the domain. That table is the only customer data there is -
there is no separate customer file any more. A mail whose domain is in the
table belongs to it; one whose domain is not stays unclassified.

A domain belongs to exactly ONE customer. A domain two rows disagree about
cannot decide anything, so those mails stay unclassified (see
domain_conflicts).
"""

def norm_domain(value):
    """The domain behind whatever was typed: a bare domain, an @domain, a full
    address, or a 'Name <addr>' form.

    Lower-cased and stripped of a leading '@' / 'www.' and a trailing dot, so
    the Customer Master does not end up with both 'abt.com' and 'www.ABT.com'
    recorded as two different rules for one customer.
    """
    s = str(value or "").strip().lower()
    mo = re.search(r"@([^\s>;,]+)", s)
    if mo:
        s = mo.group(1)
    s = s.strip().strip(".")
    if s.startswith("www."):
        s = s[4:]
    return s


# Free mail providers. A domain like this is a person, not a company: claiming
# it hands every gmail sender to one customer, so the UI warns about it.
PUBLIC_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com",
    "outlook.com", "live.com", "msn.com", "aol.com", "icloud.com", "me.com",
    "mac.com", "comcast.net", "verizon.net", "att.net", "sbcglobal.net",
    "bellsouth.net", "protonmail.com", "proton.me", "qq.com", "163.com",
    "126.com", "sina.com", "foxmail.com",
}


def public_domain(domain):
    return norm_domain(domain) in PUBLIC_DOMAINS


def mail_domain(sender, sender_domain=""):
    """The domain a mail is judged by.

    Taken from the address itself; the stored sender_domain column is only used
    when there is no address at all, so a row whose domain column was written
    by an older revision (or by hand) cannot override the address in front of us.
    """
    return norm_domain(sender) or norm_domain(sender_domain)


def domain_owners(master, domain):
    """Customers that own `domain`, most specific first.

    A registered domain also covers its subdomains - 'mail.abt.com' is Abt's
    mail even though only 'abt.com' is on file. When several registered domains
    are a suffix of the mail domain the longest one wins, so registering
    'sea.samsung.com' separately from 'samsung.com' works as expected.
    """
    d = norm_domain(domain)
    if not d:
        return []
    exact = [g["customer"] for g in master if d in (g.get("domains") or [])]
    if exact:
        return exact
    best, owners = 0, []
    for g in master:
        for dom in (g.get("domains") or []):
            if not dom or not d.endswith("." + dom):
                continue
            if len(dom) > best:
                best, owners = len(dom), [g["customer"]]
            elif len(dom) == best and g["customer"] not in owners:
                owners.append(g["customer"])
    return owners


def domain_conflicts(master):
    """[(domain, [customer, ...]), ...] - domains claimed more than once.

    Matching is by domain, so a domain held by two customers cannot decide
    anything: those mails stay unclassified until one of the claims is removed.
    The Customer Master screen shows this list.
    """
    seen = {}
    for g in master:
        for d in (g.get("domains") or []):
            owners = seen.setdefault(d, [])
            if g["customer"] not in owners:
                owners.append(g["customer"])
    return sorted((d, c) for d, c in seen.items() if len(c) > 1)


def match_customer(sender, sender_domain, master):
    """The customer that owns the sender's DOMAIN - nothing else is consulted.

    The address, the display name and any contact list are deliberately ignored:
    a new person at a known customer is recognised on their first mail, and
    nobody can pull a customer's mail onto themselves by being listed somewhere.
    A domain claimed by several customers is ambiguous, so the mail is left
    unclassified for a human to sort out (see domain_conflicts).
    """
    owners = domain_owners(master, mail_domain(sender, sender_domain))
    if len(owners) != 1:
        return None
    for g in master:
        if g["customer"] == owners[0]:
            return g
    return None


# Per-customer PO number rule presets.
#   value  : the value stored in po_regex of customer_master.csv
#   label  : description shown on the Customer Master screen
# If it starts with 'subject:', the regex that follows is applied to the mail subject only.
# This avoids mistaking long numbers in attachment names or the body for a PO number.
PO_PRESETS = [
    ("", "Standard - subject or attachment says PO# / Purchase Order"),
    ("subject:\\b(\\d{8,12})\\b",
     "Number only - the subject has no PO# label, just the number "
     "(8-12 digits). Example: KB Home"),
    ("subject:\\b(\\d{6,7})\\b",
     "Number only - shorter numbers (6-7 digits)"),
]
PO_PRESET_VALUES = [p[0] for p in PO_PRESETS]


def _po_patterns(rule, subject, all_texts):
    """One configured PO rule -> [(regex, texts-to-search), ...].

    A rule may be prefixed `subject:` to search ONLY the subject, which is what
    keeps a long number in an attachment name or the body from being mistaken
    for the PO number (KB Home prints a bare number in the subject and has no
    "PO#" label anywhere).
    """
    rule = (rule or "").strip()
    if not rule:
        return []
    if rule.lower().startswith("subject:"):
        return [(rule[8:], [subject])]
    return [(rule, all_texts)]


def extract_po_number(subject, attachments, entry, settings, body=""):
    """Extract the PO number. Search order: subject -> attachment names -> body.

    Rules are tried in order, first match wins:
      1. the per-customer rule on `entry` (`po_regex`), if one is set
      2. `settings["po_regex_default"]` - the standard "PO# / Purchase Order"
         label rule
      3. the machine-wide preset in `settings["po_regex"]` - the choice made on
         the Settings screen (see PO_PRESETS)
      4. last resort: a 7-12 digit run in an attachment filename, dates skipped

    The labelled rule runs BEFORE the preset deliberately. A digits-only preset
    matches any 8-12 digit run, which includes a date ("Order 20260901 for
    PO 12345"), so running it first would corrupt mail that the label rule
    reads correctly. Preset-as-fallback keeps every labelled mail byte-identical
    and only adds a rule for the customers that have no label at all.
    """
    subject = subject or ""
    all_texts = [subject] + list(attachments or []) + [body or ""]

    # List of (regex, search targets)
    patterns = []
    patterns += _po_patterns((entry or {}).get("po_regex"), subject, all_texts)
    patterns += _po_patterns(
        settings.get("po_regex_default",
                     r"(?:P\.?O\.?|PURCHASE\s*ORDER)[\s#:.\-]*"
                     r"([A-Z0-9\-]{5,20})"),
        subject, all_texts)
    # The machine-wide preset. Until this was read, PO_PRESETS was sent to the
    # browser but never consulted here, so a customer like KB Home - whose
    # subject carries a bare number and no PO# label - could not be read at
    # all: the preset that handles it existed and was unreachable.
    patterns += _po_patterns(settings.get("po_regex"), subject, all_texts)

    for pat, texts in patterns:
        try:
            rx = re.compile(pat, re.IGNORECASE)
        except re.error:
            continue        # skip malformed regexes
        for t in texts:
            mo = rx.search(t)
            if mo:
                return (mo.group(1) if mo.groups() else mo.group(0)).strip()

    # Last resort: long digit runs in attachment filenames.
    # Filenames often contain dates (Invoice-20260901-...), so dates are filtered out.
    att_pat = settings.get("po_attachment_regex", r"(\d{7,12})")
    rx = re.compile(att_pat)
    for t in (attachments or []):
        for mo in rx.finditer(t):
            n = mo.group(1)
            if not looks_like_date(n):
                return n
    return None


def looks_like_date(n):
    """Whether the number reads as a date, like 20260901, 260901, 09012026"""
    def ymd(y, m, d):
        return 2000 <= y <= 2099 and 1 <= m <= 12 and 1 <= d <= 31

    if len(n) == 8:
        y, m, d = int(n[:4]), int(n[4:6]), int(n[6:])
        if ymd(y, m, d):
            return True
        m, d, y = int(n[:2]), int(n[2:4]), int(n[4:])   # MMDDYYYY (US style)
        if ymd(y, m, d):
            return True
    if len(n) == 6:                                     # YYMMDD
        y, m, d = 2000 + int(n[:2]), int(n[2:4]), int(n[4:])
        if ymd(y, m, d):
            return True
    return False


def classify(mail, master, settings):
    """Returns: (customer name or None, po_number or None, master entry or None)"""
    entry = match_customer(mail.get("sender"), mail.get("sender_domain"), master)
    po = extract_po_number(mail.get("subject"), mail.get("attachments"),
                           entry, settings, body=mail.get("body", ""))
    return (entry["customer"] if entry else None), po, entry


# ==========================================================================
#  SECTION: DEDUP - duplicate and cancel/revision detection
#  (formerly dedup.py)
# ==========================================================================

# -*- coding: utf-8 -*-
"""dedup.py - detect re-receipt of the same PO number (revision/cancellation candidates)"""


def is_cancellation(mail, settings):
    """True if the subject contains a cancellation keyword (for Cold Feet classification)"""
    subject_up = (mail.get("subject") or "").upper()
    return any(k.upper() in subject_up
               for k in settings.get("cancel_keywords", []))


def check_duplicate(conn, customer, po_number, mail, settings):
    """Classify a freshly collected mail. Returns (is_duplicate, kind, reason).

    Two different things used to be collapsed into one boolean, so the UI could
    not tell them apart - both drew the same amber row and the same red warning
    glyph:

      "repeat"   the same (customer, PO number) is already in the database.
                 This is what `is_duplicate` means, and what the Duplicates
                 list claims to hold.
      "keyword"  a FIRST receipt whose subject merely contains a revision or
                 cancellation word. Nothing has been received twice; the mail
                 is flagged because "REV"/"UPDATE"/"수정" suggests it may
                 replace an earlier PO that was never collected.

    The old code returned True for both, so a brand-new PO whose subject said
    "UPDATE" was stored as a duplicate - a false positive that teaches the user
    to ignore the flag. Now only a real re-receipt sets `is_duplicate`; the
    weaker signal travels in `kind`, and the screen shows it differently.
    """
    subject_up = (mail.get("subject") or "").upper()

    rev_kw = [k.upper() for k in settings.get("revision_keywords", [])]
    can_kw = [k.upper() for k in settings.get("cancel_keywords", [])]
    tags = []
    if any(k in subject_up for k in can_kw):
        tags.append("cancellation candidate")
    elif any(k in subject_up for k in rev_kw):
        tags.append("revision candidate")

    if store.po_exists(conn, customer, po_number,
                       exclude_message_id=mail.get("message_id")):
        reason = "PO number received again"
        if tags:
            reason += " — " + ", ".join(tags)
        else:
            reason += " — possible duplicate order, review required"
        return True, "repeat", reason

    # First receipt. A keyword is worth a look, but it is NOT a duplicate.
    if tags:
        return False, "keyword", ("First receipt, but the subject contains a "
                                  + ", ".join(tags) + " keyword")
    return False, "", ""

