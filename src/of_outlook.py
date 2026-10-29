# -*- coding: utf-8 -*-
"""of_outlook.py

OrderFlow mail collection: Outlook COM collection, attachment housekeeping, window focus helpers and the periodic sync scheduler.

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
#  SECTION: COLLECTOR - Outlook COM mail collection
#  (formerly collector.py)
# ==========================================================================

# -*- coding: utf-8 -*-
"""collector.py - mail collector
Incremental collection from a given mailbox/folder via classic Outlook COM.
Output: list of dicts (message_id, received_at, sender, sender_domain,
           subject, attachments, pdf_paths)
"""


LAST_DIAG = {"hint": ""}   # diagnostic message from the last collection (e.g. reason for 0 results)

PR_INTERNET_MESSAGE_ID = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"
PR_SMTP_ADDRESS = "http://schemas.microsoft.com/mapi/proptag/0x39FE001F"

# Pattern to exclude junk files such as signature/inline images in the body
JUNK_ATT = re.compile(r"^image\d{3}\.(png|gif|jpe?g)$", re.IGNORECASE)
# Attachment extensions to save to disk (skipping logo/signature images speeds up collection)
SAVE_EXT = {".pdf", ".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".txt",
            ".docx", ".doc", ".zip", ".xml", ".edi"}
# Body images such as signatures/logos (skipping them is normal, so no warning)
IMAGE_EXT = {".png", ".gif", ".jpg", ".jpeg", ".bmp", ".svg", ".ico",
             ".tif", ".tiff", ".emf", ".wmf"}


def _want_save(fname):
    return os.path.splitext(fname)[1].lower() in SAVE_EXT


def _domain(addr):
    return addr.split("@")[-1].lower() if "@" in (addr or "") else (addr or "").lower()


def _smtp_sender(item):
    """Try to convert an internal Exchange address (/O=...) to an SMTP address"""
    try:
        addr = str(item.SenderEmailAddress or "")
        if addr.startswith("/"):  # Exchange DN
            sender = item.Sender
            if sender is not None:
                exch = sender.GetExchangeUser()
                if exch is not None:
                    return str(exch.PrimarySmtpAddress or addr)
            try:
                return str(item.PropertyAccessor.GetProperty(PR_SMTP_ADDRESS))
            except Exception:
                pass
        return addr
    except Exception:
        return ""


def _message_id(item, fallback_parts):
    try:
        mid = str(item.PropertyAccessor.GetProperty(PR_INTERNET_MESSAGE_ID) or "")
        if mid:
            return mid
    except Exception:
        pass
    raw = "|".join(str(p) for p in fallback_parts)
    return "hash-" + hashlib.md5(raw.encode("utf-8", "replace")).hexdigest()


def _save_pdfs(item, attachments_dir, message_id):
    """Save attachments to data/attachments/YYYY-MM/ (junk excluded, all formats)"""
    paths = []
    try:
        n = item.Attachments.Count
    except Exception:
        return paths
    if n == 0:
        return paths
    ym = datetime.date.today().strftime("%Y-%m")
    outdir = os.path.join(attachments_dir, ym)
    os.makedirs(outdir, exist_ok=True)
    tag = hashlib.md5(message_id.encode("utf-8", "replace")).hexdigest()[:8]
    for i in range(1, n + 1):
        att = item.Attachments.Item(i)
        try:
            fname = str(att.FileName or "")
        except Exception as e:
            print(f"  [ATT] cannot read attachment {i} name: {e}")
            continue
        if not fname or JUNK_ATT.match(fname):
            continue
        if not _want_save(fname):
            # Signature/logo images are skipped by design, no need to report
            if os.path.splitext(fname)[1].lower() not in IMAGE_EXT:
                print(f"  [ATT] skipped (extension not collected): {fname}")
            continue
        safe = re.sub(r'[\\/:*?"<>|]', "_", fname).strip(" .")
        # Shorten the name so saving does not fail on the Windows path limit (260 chars)
        stem, ext = os.path.splitext(safe)
        room = 240 - len(outdir) - len(tag) - len(ext) - 2
        if room > 20 and len(stem) > room:
            stem = stem[:room]
        safe = stem + ext
        path = os.path.abspath(os.path.join(outdir, f"{tag}_{safe}"))
        try:
            if not os.path.exists(path):
                att.SaveAsFile(path)
            paths.append(path)
        except Exception as e:
            # Failing silently would make the dashboard look like there is no attachment
            print(f"  [ATT] could not save '{fname}': {e}")
    return paths


# Called by the server to re-download attachments that failed to save
save_attachments = _save_pdfs


def _has_document(item):
    """True if the mail carries at least one attachment we would save
    (PDF, Excel, ...). Signature/logo images do not count."""
    try:
        atts = item.Attachments
        for i in range(1, int(atts.Count) + 1):
            try:
                fname = str(atts.Item(i).FileName or "")
            except Exception:
                continue
            if fname and not JUNK_ATT.match(fname) and _want_save(fname):
                return True
    except Exception:
        pass
    return False


def _to_record(item, attachments_dir, source_ref=None):
    if source_ref is None:
        # Outlook item: EntryID + StoreID to open the original mail later
        try:
            eid = str(getattr(item, "EntryID", "") or "")
            sid = ""
            try:
                sid = str(item.Parent.StoreID or "")
            except Exception:
                pass
            source_ref = f"entryid:{eid}:{sid}" if eid else ""
        except Exception:
            source_ref = ""
    received = getattr(item, "ReceivedTime", None)
    received_s = ""
    if received is not None:
        try:
            received_s = received.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            received_s = str(received)[:19].replace(" ", "T")
    sender = _smtp_sender(item)
    subject = str(getattr(item, "Subject", "") or "")
    try:
        body = str(getattr(item, "Body", "") or "")[:4000]
    except Exception:
        body = ""
    mid = _message_id(item, [sender, subject, received_s])
    atts = []
    try:
        for i in range(1, item.Attachments.Count + 1):
            atts.append(str(item.Attachments.Item(i).FileName or ""))
    except Exception:
        pass
    return {
        "message_id": mid,
        "received_at": received_s,
        "sender": sender,
        "sender_domain": _domain(sender),
        "subject": subject,
        "body": body,
        "attachments": atts,
        "pdf_paths": _save_pdfs(item, attachments_dir, mid),
        "source_ref": source_ref or "",
    }


def _resolve_folder(ns, mailbox_name, folder_path):
    """If mailbox_name is empty use the default Inbox; otherwise search within that mailbox.
    folder_path examples: 'Inbox' or 'Inbox/PO' (localized folder names also work)"""
    if not mailbox_name:
        folder = ns.GetDefaultFolder(6)  # olFolderInbox
        parts = [p for p in (folder_path or "").split("/") if p][1:]
    else:
        want = mailbox_name.strip().lower()
        store_root = None
        # Priority 1: exact match, priority 2: partial match (handles naming differences)
        for f in ns.Folders:
            if str(f.Name).strip().lower() == want:
                store_root = f
                break
        if store_root is None:
            for f in ns.Folders:
                if want in str(f.Name).strip().lower():
                    store_root = f
                    break
        if store_root is None:
            names = ", ".join(str(f.Name) for f in ns.Folders)
            raise RuntimeError(
                f"Mailbox '{mailbox_name}' not found. "
                f"Mailboxes in this Outlook profile: {names}")
        folder = store_root
        parts = [p for p in (folder_path or "").split("/") if p]
        if not parts:
            # Priority 1: the store's default Inbox (independent of language/naming)
            try:
                inbox = store_root.Store.GetDefaultFolder(6)
                if inbox is not None:
                    return inbox
            except Exception:
                pass
            # Priority 2: search by name. The Korean variants are kept so the
            # tool still works on a Korean-locale Outlook profile (developer PCs).
            names = ("Inbox", "받은 편지함", "받은편지함", "받은메일함")
            for nm in names:
                try:
                    folder.Folders[nm]
                    parts = [nm]
                    break
                except Exception:
                    continue
            # Priority 3: the subfolder with the most mails
            if not parts:
                best, best_n = None, 0
                try:
                    for sub in folder.Folders:
                        try:
                            n = int(sub.Items.Count)
                        except Exception:
                            n = 0
                        if n > best_n:
                            best, best_n = sub, n
                except Exception:
                    pass
                if best is not None:
                    return best
    for p in parts:
        folder = folder.Folders[p]
    return folder


def collect_outlook(settings, conn, base_dir, on_date=None, progress=None):
    """If on_date('YYYY-MM-DD') is given, collect only that day (requested from the calendar).
    Otherwise collect incrementally from the last collection / lookback period.

    progress(done, total, phase) is called while the folder is walked, so the UI
    can show a real percentage instead of an animation that says "something is
    happening, somehow". `total` is Outlook's own restricted count and is -1 when
    the store refuses to report one - the caller then falls back to an
    indeterminate indicator, which is the honest thing to do.
    """
    import win32com.client
    import pythoncom
    pythoncom.CoInitialize()
    try:
        try:
            ns = win32com.client.Dispatch(
                "Outlook.Application").GetNamespace("MAPI")
            _ = ns.Folders.Count  # check that the profile is logged in
        except Exception as e:
            raise RuntimeError(
                "Cannot connect to Outlook. Please open Outlook, sign in, "
                f"and run this again. ({e})")
        cfg = settings.get("outlook", {})
        # The identity every row gets. It is the value the Inbox's picker
        # sends, so the list can be scoped to exactly what was picked; "" is a
        # real value (the default inbox), not "unknown".
        mb = str(cfg.get("mailbox_name") or "").strip()
        folder = _resolve_folder(ns, cfg.get("mailbox_name", ""),
                                 cfg.get("folder_path", ""))

        # Mail collected before this column existed carries the store in
        # source_ref but nothing in `mailbox`. Claim it now, from the store we
        # are already reading: one UPDATE, no item opened.
        try:
            claimed = store.backfill_mailbox(
                conn, mb, str(getattr(folder, "StoreID", "") or ""))
            if claimed:
                print(f"      claimed {claimed} older email(s) as "
                      f"'{mb or 'default inbox'}'")
        except Exception as e:
            print(f"  [WARN] mailbox backfill skipped: {e}")

        if on_date:
            d0 = datetime.datetime.strptime(on_date, "%Y-%m-%d")
            d1 = d0 + datetime.timedelta(days=1)
            filt = ("[ReceivedTime] >= '"
                    + d0.strftime("%m/%d/%Y %I:%M %p") + "' AND "
                    "[ReceivedTime] < '"
                    + d1.strftime("%m/%d/%Y %I:%M %p") + "'")
        else:
            last = store.get_meta(conn, "last_collected")
            if last:
                since = (datetime.datetime.fromisoformat(last)
                         - datetime.timedelta(minutes=10))
            else:
                since = (datetime.datetime.now() - datetime.timedelta(
                    days=int(cfg.get("lookback_days", 1))))
            filt = ("[ReceivedTime] >= '"
                    + since.strftime("%m/%d/%Y %I:%M %p") + "'")

        # Only emails that carry an attachment. Cheap first pass done by
        # Outlook itself; the document-type check happens per item below,
        # because a signature image alone also counts as "has attachment".
        # Off by default: with it on, an inbox whose mail has no attachment
        # collects nothing, which looks like a broken connection.
        attachments_only = bool(cfg.get("attachments_only", False))
        date_filt = filt
        if attachments_only:
            filt = "(" + date_filt + ") AND [Attachment] = True"

        items = folder.Items
        items.Sort("[ReceivedTime]", False)  # ascending
        try:
            items = items.Restrict(filt)
        except Exception:
            # Some stores reject the [Attachment] term - fall back to the date
            # filter alone; the per-item check below still applies.
            items = folder.Items
            items.Sort("[ReceivedTime]", False)
            items = items.Restrict(date_filt)
        try:
            total = int(items.Count)
        except Exception:
            total = -1
        max_items = int(cfg.get("max_items", 500))
        print(f"      folder: {folder.Name} | matching emails: "
              f"{total if total >= 0 else '?'}"
              f"{f' (limit {max_items})' if 0 < max_items < total else ''}")

        attachments_dir = os.path.join(base_dir, settings.get(
            "attachments_dir", "data/attachments"))
        records, newest, n, skipped = [], None, 0, 0
        if progress:
            try:
                progress(0, total, f"Reading '{folder.Name}'")
            except Exception:
                pass
        item = items.GetFirst()
        while item is not None:
            try:
                if getattr(item, "Class", 0) == 43:  # olMail only
                    if attachments_only and not _has_document(item):
                        skipped += 1
                    else:
                        rec = _to_record(item, attachments_dir)
                        rec["mailbox"] = mb
                        records.append(rec)
                        if rec["received_at"]:
                            newest = max(newest or "", rec["received_at"])
            except Exception as e:
                print(f"  [WARN] item read failed: {e}")
            n += 1
            # Every few items, not every item: the COM round trip is the slow
            # part here, and a progress callback per mail would compete with it.
            if progress and (n % 5 == 0):
                try:
                    progress(n, total, "")
                except Exception:
                    pass
            if n % 25 == 0:
                print(f"      ... {n} processed", flush=True)
            if max_items and len(records) >= max_items:
                print(f"      reached limit of {max_items} emails "
                      f"(raise outlook.max_items in settings.json)")
                break
            item = items.GetNext()
        print(f"      done: {len(records)} emails read"
              + (f", {skipped} without a document attachment skipped"
                 if skipped else ""))

        if not records:
            # If 0 results, report the reason (usually no mails within the period)
            try:
                # The attachment filter runs inside the Outlook query, so
                # "no emails" would be a lie when mail exists but none of it
                # carries an attachment. Count again without that condition.
                unfiltered = -1
                if attachments_only:
                    try:
                        probe = folder.Items
                        probe.Sort("[ReceivedTime]", False)
                        unfiltered = int(probe.Restrict(date_filt).Count)
                    except Exception:
                        unfiltered = -1

                if attachments_only and unfiltered > 0:
                    LAST_DIAG["hint"] = (
                        f"{unfiltered} email(s) found"
                        + (f" on {on_date}" if on_date else
                           f" in the last {cfg.get('lookback_days', 1)} day(s)")
                        + f" in '{folder.Name}', but none of them has a "
                        f"document attachment, so nothing was collected. "
                        f"Turn off 'Only emails with a document attachment' "
                        f"in Settings to collect them anyway.")
                elif on_date:
                    LAST_DIAG["hint"] = (
                        f"No emails received on {on_date} in "
                        f"'{folder.Name}'.")
                else:
                    allitems = folder.Items
                    allitems.Sort("[ReceivedTime]", True)
                    first = allitems.GetFirst()
                    if first is not None:
                        d = first.ReceivedTime.strftime("%Y-%m-%d")
                        LAST_DIAG["hint"] = (
                            f"No emails in the last "
                            f"{cfg.get('lookback_days', 1)} day(s). "
                            f"The newest email in '{folder.Name}' is from "
                            f"{d} — pick that date in Inbox to sync it.")
                    else:
                        LAST_DIAG["hint"] = (
                            f"The folder '{folder.Name}' is empty.")
            except Exception:
                pass
            print(f"      [INFO] {LAST_DIAG.get('hint', '')}")

        # When only a specific date was fetched, leave the incremental checkpoint untouched
        if newest and not on_date:
            store.set_meta(conn, "last_collected", newest)
        return records
    finally:
        pythoncom.CoUninitialize()


def claim_mailbox(settings, conn):
    """File the mail collected before the `mailbox` column existed.

    Outlook is contacted only to learn the StoreID of the configured mailbox -
    no item is opened and no mail is read, so this is a fraction of a second
    rather than a collection. Returns how many rows were claimed.
    """
    try:
        import win32com.client
        import pythoncom
    except Exception as e:
        raise RuntimeError(f"pywin32 is not installed: {e}")
    pythoncom.CoInitialize()
    try:
        try:
            ns = win32com.client.Dispatch(
                "Outlook.Application").GetNamespace("MAPI")
            _ = ns.Folders.Count
        except Exception as e:
            # A raw COM tuple ("invalid class string") tells the user nothing.
            raise RuntimeError(
                "Cannot connect to Outlook. Open Outlook, sign in, and try "
                f"again. ({e})")
        cfg = settings.get("outlook", {})
        folder = _resolve_folder(ns, cfg.get("mailbox_name", ""),
                                 cfg.get("folder_path", ""))
        return store.backfill_mailbox(
            conn, str(cfg.get("mailbox_name") or "").strip(),
            str(getattr(folder, "StoreID", "") or ""))
    finally:
        pythoncom.CoUninitialize()


def test_outlook(settings):
    """Outlook connection diagnostics. Returns: dict (for UI display)"""
    out = {"ok": False, "outlook": "", "profile": "", "mailboxes": [],
           "target": "", "folder": "", "count": None, "latest": "",
           "error": "", "hint": ""}
    cfg = settings.get("outlook", {})
    out["target"] = cfg.get("mailbox_name", "") or "(default inbox)"

    try:
        import win32com.client
        import pythoncom
    except Exception as e:
        out["error"] = f"pywin32 not installed: {e}"
        out["hint"] = "Run: pip install pywin32"
        return out

    pythoncom.CoInitialize()
    try:
        try:
            app = win32com.client.Dispatch("Outlook.Application")
            ns = app.GetNamespace("MAPI")
            out["outlook"] = str(getattr(app, "Version", "") or "")
            _ = ns.Folders.Count
        except Exception as e:
            out["error"] = f"Cannot connect to Outlook: {e}"
            out["hint"] = ("Open Outlook and sign in, then test again. "
                           "The new Outlook (Store app) does not support "
                           "this connection - classic Outlook is required.")
            return out

        try:
            out["profile"] = str(ns.CurrentUser)
        except Exception:
            pass

        for f in ns.Folders:
            try:
                out["mailboxes"].append(str(f.Name))
            except Exception:
                pass

        try:
            folder = _resolve_folder(ns, cfg.get("mailbox_name", ""),
                                     cfg.get("folder_path", ""))
            out["folder"] = str(folder.FolderPath or folder.Name)
            items = folder.Items
            out["count"] = int(items.Count)
            try:
                items.Sort("[ReceivedTime]", True)
                first = items.GetFirst()
                if first is not None:
                    out["latest"] = (
                        f"{first.ReceivedTime.strftime('%Y-%m-%d %H:%M')} | "
                        f"{str(first.Subject or '')[:60]}")
            except Exception:
                pass
            out["ok"] = True
            if not out["count"]:
                out["hint"] = (
                    "This folder is empty. If the mailbox stores mail in a "
                    "sub-folder, set folder_path in config/settings.json "
                    "(for example \"Inbox\" or \"Inbox/PO\").")
        except Exception as e:
            out["error"] = str(e)
            out["hint"] = ("Check the mailbox name in Settings. "
                           "Available mailboxes are listed above.")
        return out
    finally:
        pythoncom.CoUninitialize()


def split_by_attachment(records):
    """Split a mail with multiple attached documents into one order row per document.

    Separate PO attachments mean separate orders, so Role / Sold-To / Ship-To /
    Confirm must be handled individually for each.
    #N is appended to message_id to keep a unique key per row.
    """
    out = []
    for m in records:
        pdfs = m.get("pdf_paths") or []
        if len(pdfs) <= 1:
            out.append(m)
            continue
        for i, p in enumerate(pdfs, start=1):
            d = dict(m)
            d["message_id"] = f"{m['message_id']}#{i}"
            d["pdf_paths"] = [p]
            base = os.path.basename(p)
            d["attachments"] = [re.sub(r"^[0-9a-f]{8}_", "", base)]
            d["att_seq"] = i
            d["att_total"] = len(pdfs)
            out.append(d)
    return out


def collect(settings, conn, base_dir, on_date=None, progress=None):
    recs = collect_outlook(settings, conn, base_dir, on_date=on_date,
                           progress=progress)
    # Splitting by attachment is pure CPU on a list already in memory, so the
    # bar sits at the end of the reading phase rather than jumping back.
    if progress:
        try:
            progress(len(recs), max(len(recs), 1), "Filing attachments")
        except Exception:
            pass
    return split_by_attachment(recs)


# ==========================================================================
#  SECTION: HOUSEKEEPING - attachment retention
#  (formerly housekeeping.py)
# ==========================================================================

# -*- coding: utf-8 -*-
"""housekeeping.py - automatic cleanup of old attachment files

The original mails remain in each user's Outlook, so attachments past the
retention period are deleted to free disk space. DB records (mail history,
PO numbers, processing status) and the cleanup log are kept.

settings["retention"]:
  attachments_days   retention in days (0 = no cleanup)
"""


def _log_path(settings):
    d = os.path.join(settings.get("_base", ""), "logs")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "cleanup.log")


def _write_log(settings, lines):
    try:
        with open(_log_path(settings), "a", encoding="utf-8") as f:
            for ln in lines:
                f.write(ln + "\n")
    except Exception:
        pass


def cleanup_attachments(conn, settings, dry_run=False):
    """Delete attachments past the retention period. Returns: dict (summary)"""
    cfg = settings.get("retention", {})
    try:
        days = int(cfg.get("attachments_days", 180))
    except (TypeError, ValueError):
        days = 180
    if days <= 0:
        return {"enabled": False, "deleted": 0, "freed_mb": 0,
                "cutoff": "", "dry_run": dry_run}

    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT id, received_at, pdf_paths FROM mails "
        "WHERE substr(received_at,1,10) < ? AND pdf_paths != '[]'",
        (cutoff,)).fetchall()

    deleted, freed, touched = 0, 0, []
    for r in rows:
        try:
            paths = json.loads(r["pdf_paths"] or "[]")
        except Exception:
            continue
        gone = []
        for p in paths:
            if os.path.exists(p):
                try:
                    size = os.path.getsize(p)
                    if not dry_run:
                        os.remove(p)
                    deleted += 1
                    freed += size
                    gone.append(os.path.basename(p))
                except Exception:
                    pass
        if gone and not dry_run:
            # Delete the files but keep the list of what the attachments were
            conn.execute("UPDATE mails SET pdf_paths='[]' WHERE id=?",
                         (r["id"],))
            touched.append(f"  id={r['id']} {r['received_at'][:10]} "
                           f"{', '.join(gone)}")

    if not dry_run and touched:
        conn.commit()
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        _write_log(settings, [
            f"[{stamp}] cleanup: removed {deleted} file(s), "
            f"{freed/1048576:.1f} MB freed, older than {cutoff} "
            f"({days} days)"] + touched)

    # Remove empty monthly folders
    if not dry_run:
        base = os.path.join(settings.get("_base", ""),
                            settings.get("attachments_dir", "data/attachments"))
        try:
            for name in os.listdir(base):
                sub = os.path.join(base, name)
                if os.path.isdir(sub) and not os.listdir(sub):
                    os.rmdir(sub)
        except Exception:
            pass

    return {"enabled": True, "deleted": deleted,
            "freed_mb": round(freed / 1048576, 1), "cutoff": cutoff,
            "days": days, "dry_run": dry_run}


def disk_usage(settings):
    """Summary of attachment folder disk usage"""
    base = os.path.join(settings.get("_base", ""),
                        settings.get("attachments_dir", "data/attachments"))
    total, count, oldest = 0, 0, ""
    for root, _dirs, files in os.walk(base):
        for fn in files:
            p = os.path.join(root, fn)
            try:
                total += os.path.getsize(p)
                count += 1
            except Exception:
                pass
        b = os.path.basename(root)
        if b and (not oldest or b < oldest) and b != os.path.basename(base):
            oldest = b
    db = os.path.join(settings.get("_base", ""),
                      settings.get("db_path", "data/po_mail.db"))
    db_mb = 0
    try:
        db_mb = round(os.path.getsize(db) / 1048576, 1)
    except Exception:
        pass
    return {"files": count, "size_mb": round(total / 1048576, 1),
            "oldest_month": oldest, "db_mb": db_mb}


# ==========================================================================
#  SECTION: WIN FOCUS - raise opened windows on Windows
#  (formerly win_focus.py)
# ==========================================================================

# -*- coding: utf-8 -*-
"""win_focus.py - bring newly opened windows to the front

Windows prevents background processes from raising a window to the
foreground (foreground lock). Release the lock right before opening a
file/mail, then find the newly created window and bring it to the front.
"""

ASFW_ANY = -1


def allow_foreground():
    """Allow another process to take the foreground window"""
    try:
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
    except Exception:
        pass


def _snapshot():
    """Set of currently visible top-level window handles"""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = set()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            found.add(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found


def _force_front(hwnd):
    """Bypass the foreground lock and bring the given window to the front"""
    import ctypes
    user32 = ctypes.windll.user32
    SW_RESTORE, VK_MENU, KEYEVENTF_KEYUP = 9, 0x12, 0x0002
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        # Tap the ALT key to release the foreground lock (standard workaround)
        ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.SetForegroundWindow(hwnd)
        ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        user32.BringWindowToTop(hwnd)
    except Exception:
        pass


def raise_new_window(before, timeout=6.0):
    """Find windows created since `before` (a _snapshot result) and bring them to the front.
    Call from a background thread."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.25)
        try:
            new = _snapshot() - before
        except Exception:
            return
        if new:
            _force_front(max(new))
            return


def open_and_focus(open_callable):
    """Open a file/mail via open_callable(), then bring its window to the front."""
    try:
        before = _snapshot()
    except Exception:
        before = set()
    allow_foreground()
    open_callable()
    threading.Thread(target=raise_new_window, args=(before,),
                     daemon=True).start()


# ==========================================================================
#  SECTION: SCHEDULER - periodic mail sync
#  (formerly scheduler.py)
# ==========================================================================

# -*- coding: utf-8 -*-
"""scheduler.py - automatic mail sync scheduler

settings["sync"]:
  mode         "off" | "interval" | "times"
  interval_min interval in minutes - mode=interval
  times        ["09:00","14:00"] - mode=times

Runs in a background thread; the collect function is injected (minimal coupling to the server).
A lock ensures only one collection runs at a time.
"""

# Shared with server.py so a scheduled sync and a manual "Save & Collect Now"
# (or a calendar-date sync) can never run at the same time. Two independent
# locks used to guard these paths, which let two Outlook COM sessions touch
# Outlook.exe from different threads at once - the likely cause of
# intermittent wrong-folder / wrong-mailbox results.
LOCK = threading.Lock()
_state = {
    "running": False,        # collection in progress
    "last_started": "",
    "last_finished": "",
    "last_result": "",
    "last_error": "",
    "next_due": "",
}


def state():
    return dict(_state)


def _parse_times(times):
    out = []
    for t in times or []:
        try:
            hh, mm = str(t).split(":")
            out.append((int(hh), int(mm)))
        except Exception:
            continue
    return sorted(out)


def _next_due(settings, now=None):
    """Next scheduled sync time (datetime), or None (off)"""
    cfg = settings.get("sync", {})
    mode = cfg.get("mode", "interval")
    now = now or datetime.datetime.now()
    if mode == "off":
        return None
    if mode == "times":
        pts = _parse_times(cfg.get("times"))
        if not pts:
            return None
        for hh, mm in pts:
            cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if cand > now:
                return cand
        hh, mm = pts[0]
        return (now + datetime.timedelta(days=1)).replace(
            hour=hh, minute=mm, second=0, microsecond=0)
    # interval
    try:
        mins = max(5, int(cfg.get("interval_min", 60)))
    except (TypeError, ValueError):
        mins = 60
    base = _state.get("last_finished") or ""
    try:
        last = datetime.datetime.fromisoformat(base) if base else None
    except Exception:
        last = None
    return (last or now) + datetime.timedelta(minutes=mins)


def refresh_next_due(settings):
    nd = _next_due(settings)
    _state["next_due"] = nd.isoformat(timespec="minutes") if nd else ""
    return _state["next_due"]


def run_once(collect_fn, settings, source="manual"):
    """Run one collection (prevents concurrent runs). Returns: (ok, message)"""
    if not LOCK.acquire(blocking=False):
        return False, "A sync is already running."
    try:
        _state["running"] = True
        _state["last_started"] = datetime.datetime.now().isoformat(
            timespec="seconds")
        _state["last_error"] = ""
        try:
            found, new, empty, latest = collect_fn()
            _state["last_result"] = (f"{found} found, {new} new"
                                     f"{f' (source: {source})' if source else ''}")
            return True, _state["last_result"]
        except Exception as e:
            _state["last_error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()
            return False, _state["last_error"]
        finally:
            _state["last_finished"] = datetime.datetime.now().isoformat(
                timespec="seconds")
            _state["running"] = False
            refresh_next_due(settings)
    finally:
        LOCK.release()


def start(collect_fn, settings):
    """Start the scheduler thread (keeps running while the app is up)"""
    refresh_next_due(settings)

    def loop():
        while True:
            try:
                nd = _next_due(settings)
                if nd is None:
                    _state["next_due"] = ""
                else:
                    _state["next_due"] = nd.isoformat(timespec="minutes")
                    if datetime.datetime.now() >= nd:
                        print(f"[sync] scheduled sync at "
                              f"{datetime.datetime.now():%H:%M}")
                        run_once(collect_fn, settings, source="scheduled")
            except Exception:
                traceback.print_exc()
            threading.Event().wait(30)      # check the schedule every 30 seconds

    t = threading.Thread(target=loop, daemon=True, name="sync-scheduler")
    t.start()
    return t


