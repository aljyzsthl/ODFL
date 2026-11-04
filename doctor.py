#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OrderFlow - environment check.

Answers one question: "this machine cannot read a PO - what is missing?"

It is READ-ONLY. It opens the database with `mode=ro`, calls no writer, and
never touches the extraction cache beyond counting it. The only network traffic
is the same 16-token round trip the Settings screen's **Test PO reading** button
makes, and only when a token exists.

    python doctor.py

Exit code 0 when nothing failed, 1 when something did (so a .bat wrapper or a
human can branch on it).

WHY THIS EXISTS (2026-11-03): the workspace was moved to another PC and every
Extract ended up as "goes to Read, cannot be read, comes back to the Inbox".
That is the *correct* behaviour for a failed reading - nothing is cached, so the
row returns - but the only explanation was an alert box that vanished with the
click that dismissed it. A moved workspace loses exactly the files git does not
carry (`config/settings.json`, the master data, the templates, `.api_key`), and
loses the network the endpoint lives on; this prints which of those it is.
"""

import json
import os
import platform
import sqlite3
import sys
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
IS_WIN = os.name == "nt"

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
_results = []          # [(level, section, text)]


def say(level, section, text):
    _results.append((level, section, text))
    marks = {OK: " ok  ", WARN: "warn ", FAIL: "FAIL ", INFO: "     "}
    print("  %s %s" % (marks[level], text))


def head(title):
    print("\n-- %s %s" % (title, "-" * max(0, 58 - len(title))))


def size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.0f %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0


def load_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


# ── 1. the folder ──────────────────────────────────────────────────────────
def check_layout():
    head("1. the folder")
    print("  %s" % BASE)
    for rel, why in (("src", "the dashboard"),
                     ("CodeExtract", "the PO reader"),
                     ("config", "settings + master data"),
                     ("data", "the mail database and its attachments")):
        p = os.path.join(BASE, rel)
        if os.path.isdir(p):
            n = len([x for x in os.listdir(p) if not x.startswith(".")])
            say(OK, "layout", "%-14s %d item(s)" % (rel + "/", n))
        else:
            say(FAIL, "layout", "%-14s MISSING - %s" % (rel + "/", why))
    low = BASE.lower()
    if "onedrive" in low or "dropbox" in low or "icloud" in low:
        say(WARN, "layout",
            "this folder is inside a sync client (OneDrive/Dropbox/iCloud). "
            "The SQLite file does not like being synchronised while the app "
            "runs; keep the working copy outside the synced tree.")
    if any(ord(c) > 127 for c in BASE):
        say(WARN, "layout",
            "the path has non-ASCII characters. Nothing here forbids it, but a "
            "batch file, Excel or Outlook can each mangle it differently - if "
            "things fail in odd places, try a plain C:\\OrderFlow.")


# ── 2. what a git clone does NOT carry ─────────────────────────────────────
NEEDED = [
    ("config/settings.json", "the endpoint and the token THIS machine uses",
     False),
    ("config/erp_template.XLSX", "the Standard Order Upload form", True),
    ("config/ship_to_master.json",
     "the (Sold-To, Ship-To) pairs - columns F/G, and the drop-downs", True),
    ("config/domain_master.json", "which customer a sender domain is", True),
    ("config/material_master.json", "the short-SKU map behind Code Learning",
     True),
    ("CodeExtract/material_codes_reference.csv",
     "the Material Code list the accuracy gate checks every code against", True),
    ("CodeExtract/.api_key", "an alternative place for the token", False),
]


def check_files():
    head("2. files a git clone does NOT carry")
    print("     (they are in .gitignore - copying the folder keeps them, "
          "cloning it does not)")
    for rel, why, required in NEEDED:
        p = os.path.join(BASE, rel.replace("/", os.sep))
        if os.path.isfile(p):
            say(OK, "files", "%-42s %s" % (rel, size(os.path.getsize(p))))
        elif required:
            say(FAIL, "files", "%-42s MISSING - %s" % (rel, why))
        else:
            say(INFO, "files", "%-42s absent - %s" % (rel, why))
    for rel, why in (("data/po_mail.db", "every mail and its state"),
                     ("data/attachments", "the documents themselves"),
                     ("CodeExtract/data_cache", "readings already paid for")):
        p = os.path.join(BASE, rel.replace("/", os.sep))
        if os.path.exists(p):
            say(OK, "files", "%-42s %s" % (rel, size(
                os.path.getsize(p) if os.path.isfile(p) else sum(
                    os.path.getsize(os.path.join(dp, f))
                    for dp, _dn, fn in os.walk(p) for f in fn))))
        else:
            say(INFO, "files", "%-42s absent - %s" % (rel, why))


# ── 3. the reader ──────────────────────────────────────────────────────────
def import_engine():
    ce = os.path.join(BASE, "CodeExtract")
    if ce not in sys.path:
        sys.path.insert(0, ce)
    try:
        import claude_engine
        return claude_engine, ""
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def check_engine():
    head("3. the PO reader")
    eng, err = import_engine()
    if not eng:
        say(FAIL, "engine", "CodeExtract/claude_engine.py will not import - %s"
            % err)
        return None, None
    cfg = eng.load_config()
    say(OK, "engine", "CodeExtract/claude_engine.py imports")
    endpoint = eng.base_url()
    say(OK, "engine", "endpoint   %s" % endpoint)
    model = cfg.get("model", "")
    known = list(getattr(eng, "KNOWN_MODELS", {}) or {})
    if known and model not in known:
        say(FAIL, "model",
            "model      %s is NOT one this endpoint serves - a call will fail "
            "with a bare 400. Offered: %s" % (model, ", ".join(known)))
    else:
        say(OK, "engine", "model      %s" % model)
    mt = int(cfg.get("max_tokens") or 0)
    ceil = int(cfg.get("max_tokens_ceiling") or 0)
    if mt and mt < 16000:
        say(WARN, "engine",
            "max_tokens %d - a multi-PO document needs ~9,000 and an 8,000 "
            "budget cuts the JSON off mid-answer ('the reading was cut off'). "
            "Set max_tokens to 16000 or higher in CodeExtract/claude_config.json."
            % mt)
    else:
        say(OK, "engine", "max_tokens %d (ceiling %d)" % (mt, ceil or mt))
    return eng, cfg


def check_token(eng, cfg):
    head("4. the DeepSeek API key")
    if not eng:
        say(INFO, "token", "skipped - the reader did not import")
        return ""
    key = eng.api_key()
    user_cfg = load_json(os.path.join(BASE, "config", "settings.json")) or {}
    stored = str((user_cfg.get("deepseek") or {}).get("api_key") or "")
    env_k = os.environ.get("DEEPSEEK_API_KEY") or ""
    src = ""
    if stored:
        src = "config/settings.json > deepseek.api_key"
    elif env_k:
        src = "$DEEPSEEK_API_KEY"
    elif key:
        src = "CodeExtract/.deepseek_api_key"
    if key:
        say(OK, "token", "found in %s  (…%s)" % (src, key[-4:]))
    else:
        say(FAIL, "token",
            "no key anywhere. Paste the DeepSeek API key on Settings > PO "
            "reading, or set DEEPSEEK_API_KEY. Without it every Extract "
            "fails and the row goes straight back to the Inbox.")
    return key


def check_api(eng, cfg, key):
    head("5. the round trip (16 tokens)")
    if not eng:
        say(INFO, "api", "skipped - the reader did not import")
        return False
    if not key:
        say(INFO, "api", "skipped - no token to send")
        return False
    r = eng.test_connection()
    if r.get("ok"):
        say(OK, "api", "%s answered %r in %d ms"
            % (r.get("endpoint"), r.get("reply"), r.get("latency_ms")))
        return True
    say(FAIL, "api", "%s  (%d ms)" % (r.get("error"), r.get("latency_ms")))
    if r.get("hint"):
        say(INFO, "api", "hint: " + r["hint"])
    return False


# ── 6. master data ─────────────────────────────────────────────────────────
def rows_of(data, key="rows"):
    """The row list of a master file. They are `{"uploaded_at", "source_file",
    "rows": [...]}` since the two-table split, but an older copy is a bare
    list - accept both rather than reporting a healthy file as unreadable."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        v = data.get(key)
        return v if isinstance(v, list) else None
    return None


def check_master():
    head("6. master data")
    pairs = load_json(os.path.join(BASE, "config", "ship_to_master.json"))
    rows = rows_of(pairs)
    if rows is None:
        say(FAIL, "master", "ship_to_master.json unreadable or the wrong shape")
    elif not rows:
        say(FAIL, "master",
            "ship_to_master.json is EMPTY - upload the ERP Ship To Locations "
            "file on Customer Master, or every Sold-To / Ship-To drop-down is "
            "blank and F/G come out empty")
    else:
        say(OK, "master", "ship_to_master.json  %s pair row(s)" % f"{len(rows):,}")

    dom = load_json(os.path.join(BASE, "config", "domain_master.json"))
    drows = rows_of(dom)
    if drows is None:
        say(FAIL, "master",
            "domain_master.json unreadable or the wrong shape - no mail can be "
            "matched to a customer")
    else:
        doms = {str(r.get("domain") or "").strip().lower()
                for r in drows if isinstance(r, dict)}
        doms.discard("")
        say(OK, "master", "domain_master.json  %s row(s) / %s domain(s)"
            % (f"{len(drows):,}", f"{len(doms):,}"))
        if not drows:
            say(FAIL, "master",
                "domain_master.json is EMPTY - no mail can be matched to a "
                "customer, so the Inbox lists everything as unclaimed")

    mm = load_json(os.path.join(BASE, "config", "material_master.json"))
    codes = (mm or {}).get("codes") if isinstance(mm, dict) else None
    if isinstance(codes, dict):
        say(OK, "master", "material_master.json  %s code(s), %s short-SKU "
            "mapping(s)" % (f"{len(codes):,}",
                            f"{len(mm.get('sku_map') or {}):,}"))
        if not codes:
            say(WARN, "master", "material_master.json has no codes - the Code "
                 "Learning card and the short-SKU map are empty")
    else:
        say(WARN, "master", "material_master.json unreadable or missing")

    ref = os.path.join(BASE, "CodeExtract", "material_codes_reference.csv")
    if os.path.isfile(ref):
        with open(ref, encoding="utf-8-sig") as f:
            n = max(0, sum(1 for _ in f) - 1)
        say(OK, "master", "material_codes_reference.csv  %s code(s)" % f"{n:,}")
        if not n:
            say(FAIL, "master",
                "the Material Code list has no rows - the accuracy gate is off "
                "and every code is published unconfirmed")
    else:
        say(FAIL, "master",
            "material_codes_reference.csv is missing - the accuracy gate has "
            "nothing to check codes against, so every line is published "
            "unconfirmed (HANDOVER 4.4)")


def check_template():
    head("7. the ERP template")
    p = os.path.join(BASE, "config", "erp_template.XLSX")
    if not os.path.isfile(p):
        say(FAIL, "template", "config/erp_template.XLSX is missing - Generate "
             "cannot build the Full form (the Simple sheet still works)")
        return
    try:
        with zipfile.ZipFile(p) as z:
            bad = z.testzip()
        if bad:
            say(FAIL, "template", "the file is corrupt (first bad member: %s)"
                % bad)
            return
        say(OK, "template", "config/erp_template.XLSX  %s, a readable .xlsx"
            % size(os.path.getsize(p)))
    except Exception as e:
        say(FAIL, "template", "config/erp_template.XLSX is not a workbook: %s"
            % e)
        return
    try:
        import openpyxl
        wb = openpyxl.load_workbook(p, read_only=True)
        ws = wb[wb.sheetnames[0]]
        first = [c for c in next(ws.iter_rows(max_row=1, values_only=True), ())
                 if c not in (None, "")]
        wb.close()
        say(OK, "template", "sheet %r, %d non-empty header cell(s), first: %r"
            % (ws.title, len(first), first[:3]))
    except ImportError:
        say(WARN, "template",
            "openpyxl is not installed, so the header row could not be read. "
            "pip install openpyxl (requirements.txt)")
    except Exception as e:
        say(WARN, "template", "openpyxl could not open it: %s" % e)


# ── 8. the database ────────────────────────────────────────────────────────
def resolve_attachment(path, base):
    """Same rule as store.resolve_attachment - a moved database points at the
    old PC's absolute paths, and only the tail below data/attachments is
    re-rooted."""
    p = str(path or "")
    if not p or os.path.exists(p):
        return p
    norm = p.replace("/", os.sep)
    i = norm.lower().find(os.path.join("data", "attachments").lower())
    if i >= 0:
        moved = os.path.join(base, norm[i:])
        if os.path.exists(moved):
            return moved
    return p


def check_db():
    head("8. the mail database")
    p = os.path.join(BASE, "data", "po_mail.db")
    if not os.path.isfile(p):
        say(FAIL, "db", "data/po_mail.db is missing - the Inbox is empty and "
             "the mail that is failing cannot even be found")
        return
    try:
        # A URI, so `mode=ro` holds: the check must not create or migrate a
        # database it was only asked to look at. as_uri() also percent-encodes
        # spaces, which is what SQLite expects in a URI ("1021 2" -> "1021%202").
        import pathlib
        conn = sqlite3.connect(pathlib.Path(p).as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        n = conn.execute("SELECT COUNT(*) c FROM mails").fetchone()["c"]
        say(OK, "db", "data/po_mail.db  %s mail(s), %s" % (f"{n:,}", size(
            os.path.getsize(p))))
        if not n:
            say(WARN, "db", "the database holds no mail - collect from Outlook "
                 "before expecting anything in the Inbox")
        rows = conn.execute(
            "SELECT id, pdf_paths FROM mails WHERE excluded=0 "
            "ORDER BY id DESC LIMIT 500").fetchall()
        missing = 0
        checked = 0
        for r in rows:
            try:
                paths = json.loads(r["pdf_paths"] or "[]")
            except Exception:
                paths = []
            for one in paths:
                checked += 1
                if not os.path.exists(resolve_attachment(one, BASE)):
                    missing += 1
        if checked and missing == checked:
            say(FAIL, "db",
                "none of the %d attachment path(s) exist on this PC - the "
                "database came across but data/attachments did not, so every "
                "Extract fails with 'The attachment file is not on this PC'"
                % missing)
        elif missing:
            say(WARN, "db", "%d of %d attachment path(s) are missing on this PC"
                % (missing, checked))
        else:
            say(OK, "db", "all %d attachment path(s) resolve on this PC"
                % checked)
        conn.close()
    except Exception as e:
        say(FAIL, "db", "cannot open the database: %s" % e)


def check_cache(eng):
    head("9. readings already on disk")
    d = os.path.join(BASE, "CodeExtract", "data_cache")
    if not os.path.isdir(d):
        say(INFO, "cache", "no cache folder - the first Extract will call the "
            "API")
        return
    files = [f for f in os.listdir(d) if f.endswith(".json")]
    if not files:
        say(INFO, "cache", "empty - the first Extract will call the API")
        return
    if not eng:
        say(OK, "cache", "%d reading file(s)" % len(files))
        return
    try:
        sig = eng.config_signature()
    except Exception:
        say(OK, "cache", "%d reading file(s)" % len(files))
        return
    fresh = 0
    for f in files:
        one = load_json(os.path.join(d, f))
        if isinstance(one, dict) and one.get("config_sig") == sig:
            fresh += 1
    if fresh:
        say(OK, "cache", "%d reading(s), %d still valid under this "
            "configuration" % (len(files), fresh))
    else:
        say(INFO, "cache",
            "%d reading(s), none valid under this configuration (a different "
            "model, prompt or code list) - each will be read again"
            % len(files))


def check_python():
    head("10. python")
    say(OK, "python", "%s %s on %s" % (platform.python_implementation(),
                                       platform.python_version(),
                                       platform.platform()))
    if sys.version_info < (3, 8):
        say(FAIL, "python", "OrderFlow needs Python 3.8 or newer")
    for mod, why in (("openpyxl", "writing the ERP workbook"),
                     ("pymupdf", "rendering PDF pages for DeepSeek"),
                     ("pywin32", "Outlook + Excel automation (Windows)")):
        try:
            __import__("win32com" if mod == "pywin32" else mod)
            say(OK, "python", "%s present" % mod)
        except Exception:
            if mod == "pywin32" and not IS_WIN:
                say(INFO, "python", "pywin32 not needed on this OS")
            elif mod == "pywin32":
                say(FAIL, "python", "pywin32 missing (pip install pywin32) - "
                     "no mail can be collected and no Excel is written")
            elif mod == "pymupdf":
                say(FAIL, "python", "pymupdf missing (pip install pymupdf) - "
                     "PDF pages cannot be sent to DeepSeek")
            else:
                say(FAIL, "python", "openpyxl missing (pip install openpyxl) - "
                     "Generate cannot write any file")


# ── verdict ────────────────────────────────────────────────────────────────
VERDICT = {
    "layout": "The folder itself is incomplete - copy the whole working "
              "directory, not just src/.",
    "files": "A file that .gitignore excludes was not carried across. Copy the "
             "missing file(s) from the old PC by hand (HANDOVER 2).",
    "engine": "CodeExtract/claude_engine.py must import before anything can be "
              "read - check the Python version and that the file was copied "
              "whole.",
    "model": "The model id is not one the DeepSeek endpoint serves. Put it back "
             "to deepseek-flash in "
             "CodeExtract/claude_config.json or on Settings.",
    "token": "Paste the DeepSeek API key on Settings > PO reading (or set "
             "DEEPSEEK_API_KEY), then press Test PO reading.",
    "api": "The endpoint did not answer. Check Internet/proxy access to "
           "api.deepseek.com, or correct the endpoint on Settings.",
    "db": "The database and the documents are out of step - copy "
          "data/attachments together with data/po_mail.db.",
    "master": "Master data is empty or unreadable - upload it on the Customer "
              "Master / Material Codes screens (HANDOVER 6.9).",
    "template": "config/erp_template.XLSX is the Standard Order Upload form - "
                "copy it from the old PC.",
    "python": "Install the missing package from requirements.txt.",
}

# What to fix first when several things are wrong. A missing token makes the
# round trip fail too, so it has to outrank the network error it causes.
PRIORITY = ["layout", "files", "engine", "model", "token", "api", "db",
            "master", "template", "python"]


def summary():
    fails = [r for r in _results if r[0] == FAIL]
    warns = [r for r in _results if r[0] == WARN]
    head("summary")
    if not fails:
        print("  Nothing failed." + (" (%d warning(s) above)" % len(warns)
                                     if warns else ""))
    else:
        print("  %d FAIL, %d warning(s)." % (len(fails), len(warns)))
        seen = sorted({r[1] for r in fails},
                      key=lambda s: PRIORITY.index(s)
                      if s in PRIORITY else len(PRIORITY))
        print("\n  Fix in this order:")
        for i, sec in enumerate(seen, 1):
            print("    %d. %s" % (i, VERDICT.get(sec, "see above")))
    print("\n  Full manual: docs/HANDOVER.md 4.8 (API) and section 2 "
          "(what a moved folder needs).")
    return 0 if not fails else 1


def main():
    print("OrderFlow - environment check")
    print("  folder: %s" % BASE)
    check_layout()
    check_files()
    eng, cfg = check_engine()
    key = check_token(eng, cfg)
    check_api(eng, cfg, key)
    check_master()
    check_template()
    check_db()
    check_cache(eng)
    check_python()
    return summary()


if __name__ == "__main__":
    sys.exit(main())
