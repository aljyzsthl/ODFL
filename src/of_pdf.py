# -*- coding: utf-8 -*-
"""of_pdf.py

OrderFlow PDF path: DRM-wrapped PDF reading, Quick Convert and the bridge into the extractor.

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
#  SECTION: PDF ACCESS - read DRM-wrapped PO PDFs
#  (formerly pdf_access.py)
# ==========================================================================

# -*- coding: utf-8 -*-
"""pdf_access.py - read a PO PDF that OrderFlow itself is not allowed to open

On a corporate PC the document-security agent (NASCA DRM) decrypts a file only
for processes on its allow-list. OrderFlow is not on it, so its own read returns
ciphertext and the PDF libraries report nonsense such as "No /Root object".

The way out is the one already used for price-sheet Excel files: ask an
application that IS allow-listed to do the reading, through its published
automation interface. Nothing here bypasses a security control - no password
cracking, no screen scraping, no keystroke injection. If the authorised
application refuses, so does OrderFlow.

Routes, best first:
  L3   Acrobat / Word / WPS re-exports the document to a plain PDF, which the
       extractor reads as a PDF. Preferred.
  L4a  Acrobat hands over the text: first its own Save-As-Text converter, then
       a word-by-word walk that also returns each word's position, so the line
       structure a PO table needs can be rebuilt.
  L4b  Word / WPS opens the document and returns the story text.

L4a/L4b give text rather than a PDF. All three then make the SAME extraction
call (`claude_engine.extract_material_codes` / `claude_engine.from_text`),
through the same prompt and the same accuracy gate - so a protected document
reads by exactly the rules a plain one does. This used to be two parsers, and
keeping them in step was the most expensive maintenance problem in the project.
"""

COM_TIMEOUT = 25            # any single COM call
# Word rebuilds a PDF into an editable document before it can be read, which
# is slower than a plain document open. Kept short on purpose: the application
# runs hidden, so a prompt it decides to show cannot be answered and the call
# just sits there. Better to give up and say so.
CONVERT_TIMEOUT = 30
# Hard ceiling for the whole delegation attempt, so the dashboard never
# appears to hang while four clients are tried one after another.
TOTAL_BUDGET = 70
WORD_WALK_TIMEOUT = 120     # the whole per-word walk
MAX_WORDS = 40000
LINE_TOLERANCE = 3.0        # pt; words this close vertically share a line

# Applications that can re-export a PDF, best first.
# (ProgID, display name, minimum version able to import PDF)
EXPORT_CLIENTS = [
    ("AcroExch.PDDoc", "Acrobat", None),
    ("KPDF.Application", "WPS PDF", None),
    ("KWPS.Application", "WPS Writer", 12),
    ("Word.Application", "Microsoft Word", 15),   # PDF import needs Word 2013+
]
TEXT_CLIENTS = [("KWPS.Application", "WPS Writer"),
                ("Word.Application", "Microsoft Word")]

ACROBAT_TEXT_CONVERTERS = ("com.adobe.acrobat.accesstext",
                           "com.adobe.acrobat.plain-text")


def is_drm(path):
    """True when the stored bytes are DRM-wrapped rather than a PDF."""
    try:
        with open(path, "rb") as f:
            return f.read(3) == b"<##"
    except Exception:
        return False


def _run_with_timeout(fn, timeout, *a, **kw):
    """Run fn in a daemon thread and give up after `timeout` seconds.

    An office application sitting on a modal dialog never answers the COM call
    that opened it. Abandoning the thread keeps the rest of the batch alive.
    """
    box = {}

    def target():
        try:
            box["v"] = fn(*a, **kw)
        except Exception as e:
            box["err"] = e

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise RuntimeError(f"timed out after {timeout:.0f}s - the application "
                           "never answered (it is probably showing a dialog)")
    if "err" in box:
        raise box["err"]
    return box.get("v")


def _registered(progid):
    """Cheap registry check. Dispatching a missing ProgID can take 30s to fail."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid):
            return True
    except Exception:
        return False


def _looks_like_text(s):
    """True when a recovered blob plausibly is text.

    A security agent that re-encrypts on write turns a Save-As-Text result into
    bytes full of replacement characters while the application still reports
    success, so every route's output is read back and checked.
    """
    if not s or len(s.strip()) < 20:
        return False
    bad = sum(1 for c in s if c == "\ufffd" or ord(c) < 9)
    return bad / max(1, len(s)) < 0.05


# ── Acrobat (its own automation interface, not the Word-shaped one) ────────

def _di_path(path):
    """Acrobat's device-independent path: C:\\tmp\\x.pdf -> /C/tmp/x.pdf.
    saveAs silently does nothing when handed a Windows-style path."""
    p = os.path.abspath(path).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return re.sub(r"^/([A-Za-z]):", r"/\1", p)


def _acrobat_running():
    """True when Acrobat was already up. AcroExch.App is a singleton, so on the
    way out we must not close documents the user opened themselves."""
    import subprocess
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Acrobat.exe", "/NH"],
            capture_output=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return b"Acrobat.exe" in out.stdout
    except Exception:
        return True          # unknown -> leave the application alone


def _acrobat_open(src):
    """Open one document -> (app, avdoc, pddoc, jso).

    COM objects are apartment-bound, so everything a caller does with these
    must happen on the thread that called this function.
    """
    import pythoncom
    import win32com.client as wc
    pythoncom.CoInitialize()
    app = avdoc = None
    try:
        # Dispatch, not DispatchEx: Acrobat's objects are singletons.
        app = wc.Dispatch("AcroExch.App")
        avdoc = wc.Dispatch("AcroExch.AVDoc")
        if not avdoc.Open(os.path.abspath(src), ""):
            raise RuntimeError("Acrobat refused to open the document")
        pddoc = avdoc.GetPDDoc()
        if pddoc is None:
            raise RuntimeError("Acrobat returned no document object")
        try:
            jso = pddoc.GetJSObject()      # None when JavaScript is disabled
        except Exception:
            jso = None
        return app, avdoc, pddoc, jso
    except Exception:
        _acrobat_close(app, avdoc, _acrobat_running())
        raise


def _acrobat_close(app, avdoc, keep_app):
    """Release everything we opened. A leftover Acrobat keeps the document
    locked and blocks the next attempt."""
    for step in ((lambda: avdoc.Close(True)) if avdoc is not None else None,
                 (lambda: app.CloseAllDocs(1)) if app is not None
                 and not keep_app else None,
                 (lambda: app.Exit()) if app is not None
                 and not keep_app else None):
        if step is None:
            continue
        try:
            step()
        except Exception:
            pass
    try:
        import pythoncom
        pythoncom.CoUninitialize()
    except Exception:
        pass


def _acrobat_save_as(jso, dst, conv_id=None):
    """doc.saveAs - Acrobat's own File > Save As, run inside the application."""
    if jso is None:
        raise RuntimeError("Acrobat's JavaScript object is unavailable "
                           "(Preferences > JavaScript)")
    di = _di_path(dst)
    if conv_id:
        jso.saveAs(di, conv_id)
    else:
        jso.saveAs(di)
    return os.path.exists(dst) and os.path.getsize(dst) > 0


def _js_word(jso, page, index):
    """One word plus its position -> (text, (x, y)) or (None, None).

    Acrobat builds disagree about the bQuads form: some return the word as a
    string, some return the quad numbers, so the shape is inspected.
    """
    try:
        raw = jso.getPageNthWord(page, index, True)
    except Exception:
        return None, None
    if isinstance(raw, str):
        return raw.strip(), None
    if raw is None:
        return None, None
    try:
        seq = list(raw)
    except Exception:
        return None, None
    word = next((x for x in seq if isinstance(x, str)), None)
    nums = [float(x) for x in seq
            if isinstance(x, (int, float)) and not isinstance(x, bool)]
    quad = (nums[0], nums[1]) if len(nums) >= 2 else None
    if word is None:
        try:
            again = jso.getPageNthWord(page, index, False)
            word = again if isinstance(again, str) else None
        except Exception:
            word = None
    return (word.strip() if word else None), quad


def _lines_from_words(words):
    """Group (word, (x, y)) back into text lines.

    getPageNthWord hands over one word at a time, which loses exactly what a PO
    table is made of. Re-grouping by vertical position and sorting left to right
    reproduces the line structure the extraction rules expect.
    """
    placed = [(w, q) for w, q in words if q]
    if not placed:
        return None
    bands = []                                   # [(y, [(x, word)])]
    for word, (x, y) in placed:
        for band in bands:
            if abs(band[0] - y) <= LINE_TOLERANCE:
                band[1].append((x, word))
                break
        else:
            bands.append((y, [(x, word)]))
    # PDF user space has its origin bottom-left: a larger y is higher up.
    out = [" ".join(w for _, w in sorted(items))
           for _, items in sorted(bands, key=lambda b: -b[0])]
    loose = [w for w, q in words if not q]       # never drop unplaced words
    if loose:
        out.append(" ".join(loose))
    return "\n".join(out)


def _acrobat_walk_text(pddoc, jso):
    """Assemble the document text from Acrobat's per-word calls.

    Slower than Save-As-Text, but nothing is written to disk, so a security
    agent cannot re-encrypt the result on the way out.
    """
    deadline = time.time() + WORD_WALK_TIMEOUT
    pages = int(pddoc.GetNumPages())
    chunks, seen = [], 0
    for page in range(pages):
        try:
            count = int(jso.getPageNumWords(page))
        except Exception as e:
            raise RuntimeError(f"getPageNumWords({page}) failed: "
                               f"{str(e).splitlines()[0][:80]}")
        words = []
        for i in range(count):
            if time.time() > deadline:
                raise RuntimeError(f"gave up after {WORD_WALK_TIMEOUT}s "
                                   f"(page {page + 1} of {pages})")
            if seen > MAX_WORDS:
                raise RuntimeError(f"document is larger than {MAX_WORDS} words")
            word, quad = _js_word(jso, page, i)
            seen += 1
            if word:
                words.append((word, quad))
        grouped = _lines_from_words(words)
        chunks.append(grouped if grouped is not None
                      else " ".join(w for w, _ in words))
    text = "\n".join(c for c in chunks if c)
    if not text.strip():
        raise RuntimeError("Acrobat returned no words - the page has no text "
                           "layer, and this route has no image to send")
    return text


def acrobat_export(src, dst):
    """L3: have Acrobat write a plain copy of the document."""
    if not _registered("AcroExch.PDDoc"):
        raise RuntimeError("Acrobat is not installed")
    app = avdoc = None
    already = _acrobat_running()
    try:
        app, avdoc, pddoc, jso = _acrobat_open(src)
        _acrobat_save_as(jso, dst)
        return os.path.exists(dst) and os.path.getsize(dst) > 0
    finally:
        _acrobat_close(app, avdoc, already)


def acrobat_text(src):
    """L4a: read the document text through Acrobat."""
    if not _registered("AcroExch.PDDoc"):
        raise RuntimeError("Acrobat is not installed")
    app = avdoc = None
    already = _acrobat_running()
    errors = []
    tmp = tempfile.mkdtemp(prefix="acrotxt_")
    try:
        app, avdoc, pddoc, jso = _acrobat_open(src)
        if jso is None:
            errors.append("JavaScript is disabled in Acrobat")
        else:
            for conv in ACROBAT_TEXT_CONVERTERS:
                out = os.path.join(tmp, conv.rsplit(".", 1)[-1] + ".txt")
                try:
                    _acrobat_save_as(jso, out, conv)
                    with open(out, encoding="utf-8", errors="replace") as f:
                        text = f.read()
                    if _looks_like_text(text):
                        return text
                    errors.append(f"{conv}: came back unreadable "
                                  "(re-encrypted on write)")
                except Exception as e:
                    errors.append(f"{conv}: {str(e).splitlines()[0][:100]}")
            try:
                text = _acrobat_walk_text(pddoc, jso)
                if _looks_like_text(text):
                    return text
                errors.append("word walk: no usable text")
            except Exception as e:
                errors.append(f"word walk: {str(e).splitlines()[0][:100]}")
    finally:
        _acrobat_close(app, avdoc, already)
        shutil.rmtree(tmp, ignore_errors=True)
    raise RuntimeError(" | ".join(errors) or "no Acrobat route available")


# ── Word / WPS (the generic Documents.Open shape) ──────────────────────────

def _version_ok(progid, minver):
    """Skip a client whose version provably cannot import PDF (Word < 2013).
    An unreadable version is not a reason to skip - WPS reports none but works."""
    if minver is None:
        return True
    try:
        import pythoncom
        import win32com.client as wc
        pythoncom.CoInitialize()
        app = wc.DispatchEx(progid)
        try:
            ver = str(app.Version)
        except Exception:
            ver = ""
        try:
            app.Quit()
        except Exception:
            pass
        m = re.match(r"(\d+)", ver)
        return True if not m else int(m.group(1)) >= minver
    except Exception:
        return False


def office_export(progid, src, dst):
    """L3 for Word/WPS: open the PDF and export it back out as a plain PDF."""
    import pythoncom
    import win32com.client as wc
    pythoncom.CoInitialize()
    app = None
    try:
        app = wc.DispatchEx(progid)
        for attr, val in (("Visible", False), ("DisplayAlerts", 0)):
            try:
                setattr(app, attr, val)
            except Exception:
                pass
        try:
            app.Options.DoNotPromptForConvert = True
        except Exception:
            pass
        doc = app.Documents.Open(os.path.abspath(src), False, True, False)
        if doc is None:
            raise RuntimeError("PDF import unavailable or blocked")
        try:
            try:
                doc.ExportAsFixedFormat(os.path.abspath(dst), 17)
            except Exception:
                doc.SaveAs2(os.path.abspath(dst), 17)   # 17 = wdFormatPDF
        finally:
            try:
                doc.Close(0)
            except Exception:
                pass
        return os.path.exists(dst) and os.path.getsize(dst) > 0
    finally:
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def office_text(progid, src):
    """L4b: open the document and read the whole story text out of it.

    Content.Text is read inside the application, so it needs no foreground
    window and writes no file.
    """
    import pythoncom
    import win32com.client as wc
    pythoncom.CoInitialize()
    app = None
    try:
        app = wc.DispatchEx(progid)
        for attr, val in (("Visible", False), ("DisplayAlerts", 0)):
            try:
                setattr(app, attr, val)
            except Exception:
                pass
        # Word asks "Word will now convert your PDF..." when opening a PDF.
        # Without this the call waits for a dialog nobody can answer.
        try:
            app.Options.DoNotPromptForConvert = True
        except Exception:
            pass
        doc = app.Documents.Open(os.path.abspath(src), False, True, False)
        if doc is None:
            raise RuntimeError("PDF import unavailable or blocked")
        try:
            return doc.Content.Text or ""
        finally:
            try:
                doc.Close(0)
            except Exception:
                pass
    finally:
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


# ── Public entry point ────────────────────────────────────────────────────

def resolve(path, log=None, enabled=True, budget=TOTAL_BUDGET):
    """Make a DRM-protected PDF readable.

    Returns (mode, value, note):
      "path" -> value is a plain PDF the extraction engine can open directly
      "text" -> value is the document text (no page coordinates)
      "fail" -> value is "" and note explains every route that was tried

    A file that is not DRM-wrapped is returned unchanged.
    `enabled=False` skips delegation entirely and reports the file as blocked,
    which is what you want when the routes are known to fail on this PC and
    waiting for four of them to time out only wastes the user's time.
    """
    def say(m):
        if log:
            log(m)

    if not is_drm(path):
        return "path", path, ""

    name = os.path.basename(path)
    errors = []
    if not enabled:
        return "fail", "", ("delegation to Acrobat / Word is switched off "
                            "(Settings)")
    deadline = time.time() + budget

    # L3 - a plain copy is read as a PDF, which is the best input there is
    dst = os.path.join(tempfile.mkdtemp(prefix="pdfacc_"), name)
    for progid, label, minver in EXPORT_CLIENTS:
        if not _registered(progid):
            continue
        if not _version_ok(progid, minver):
            errors.append(f"{label}: version cannot import PDF")
            continue
        if time.time() > deadline:
            errors.append("gave up - out of time")
            break
        say(f"  [PDF] asking {label} to re-export {name}…")
        try:
            fn = (acrobat_export if progid == "AcroExch.PDDoc"
                  else (lambda s, d, p=progid: office_export(p, s, d)))
            if _run_with_timeout(fn, CONVERT_TIMEOUT, path, dst) \
                    and not is_drm(dst):
                return "path", dst, f"re-exported by {label}"
            why = "the copy came back protected"
            errors.append(f"{label}: {why}")
            say(f"        -> {why}")
        except Exception as e:
            why = str(e).splitlines()[0][:110]
            errors.append(f"{label}: {why}")
            say(f"        -> {why}")

    # L4a / L4b - text only, but nothing is written to disk
    routes = [("Acrobat text", lambda: _run_with_timeout(
        acrobat_text, WORD_WALK_TIMEOUT + 2 * COM_TIMEOUT, path))]
    for progid, label in TEXT_CLIENTS:
        if _registered(progid):
            routes.append((f"{label} text", lambda p=progid: _run_with_timeout(
                office_text, CONVERT_TIMEOUT, p, path)))
    for label, fn in routes:
        if time.time() > deadline:
            errors.append("gave up - out of time")
            say("        -> out of time, stopping here")
            break
        say(f"  [PDF] asking {label} to read {name}…")
        try:
            text = fn()
            if text and text.strip():
                return "text", text, f"text read by {label}"
            why = "returned no text"
        except Exception as e:
            why = str(e).splitlines()[0][:110]
        errors.append(f"{label}: {why}")
        say(f"        -> {why}")

    return "fail", "", " | ".join(errors) or "no authorised application available"


def pdf_status():
    """Which authorised applications this PC can use. For diagnostics."""
    out = []
    for progid, label, _ in EXPORT_CLIENTS:
        out.append({"name": label, "progid": progid,
                    "installed": _registered(progid)})
    return out


# ── Diagnose this PC ─────────────────────────────────────────────────────
# `of_pdf.py` is a library module — it is never run as a script, so the
# historical `python src\pdf_access.py --scan` (and its `of_pdf.py` spelling)
# does not work. Use one of these instead:
#
#   python -c "import sys; sys.path.insert(0,'src'); import of_pdf; \
# of_pdf._report()"
#   python -c "import sys; sys.path.insert(0,'src'); import orderflow; \
# print(orderflow.pdf_status())"
#
# Run the same thing on the PC that works and on the PC that does not, then
# compare the two reports. It answers three questions in order:
#   1. can THIS process read the file at all?
#   2. which authorised applications are installed here?
#   3. does any of them hand the document over?

def _reg_value(root, key, name=""):
    import winreg
    try:
        with winreg.OpenKey(root, key) as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except Exception:
        return ""


def _exe_of_progid(progid):
    """Executable behind a ProgID, via its CLSID server or its shell command."""
    import winreg
    clsid = _reg_value(winreg.HKEY_CLASSES_ROOT, progid + r"\CLSID")
    for key in ((r"CLSID\%s\LocalServer32" % clsid) if clsid else None,
                (r"CLSID\%s\InprocServer32" % clsid) if clsid else None,
                progid + r"\shell\open\command",
                progid + r"\shell\Read\command"):
        if not key:
            continue
        v = _reg_value(winreg.HKEY_CLASSES_ROOT, key)
        if v:
            v = v.strip()
            return v[1:].split('"')[0] if v.startswith('"') else v.split(" /")[0].strip()
    return ""


def _scan():
    """Find every PDF-capable application and COM server registered on this PC.

    Needed because the useful client is not always one of the well-known ones:
    a Korean office suite (ALPDF, Hancom, WPS) can be the allow-listed viewer
    here, and its automation interface is not documented anywhere.
    """
    import winreg

    print("=" * 66)
    print("PDF applications and COM servers registered on this PC")
    print("=" * 66)

    print("\nDefault .pdf handler")
    print("-" * 66)
    prog = _reg_value(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer"
        r"\FileExts\.pdf\UserChoice", "ProgId")
    print(f"  ProgId : {prog or '(unknown)'}")
    if prog:
        print(f"  Exe    : {_exe_of_progid(prog) or '(not found)'}")

    print("\nApplications registered for .pdf")
    print("-" * 66)
    seen = set()
    for hive, key in ((winreg.HKEY_CLASSES_ROOT, r".pdf\OpenWithProgids"),
                      (winreg.HKEY_CLASSES_ROOT, r".pdf\OpenWithList")):
        try:
            with winreg.OpenKey(hive, key) as k:
                i = 0
                while True:
                    try:
                        name = winreg.EnumValue(k, i)[0]
                    except OSError:
                        break
                    i += 1
                    if name and name not in seen:
                        seen.add(name)
                        print(f"  {name:<34} {_exe_of_progid(name) or ''}")
        except Exception:
            pass
    if not seen:
        print("  (none listed)")

    print("\nCOM servers whose name mentions PDF")
    print("-" * 66)
    hits = 0
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "") as root:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                low = name.lower()
                if "pdf" not in low or low.startswith("."):
                    continue
                if not _reg_value(winreg.HKEY_CLASSES_ROOT, name + r"\CLSID"):
                    continue          # no CLSID = not an automation server
                hits += 1
                print(f"  {name:<34} {_exe_of_progid(name) or ''}")
    except Exception as e:
        print(f"  registry scan failed: {e}")
    if not hits:
        print("  (none - no PDF application here exposes COM automation)")

    print("\nOther office suites that can import PDF")
    print("-" * 66)
    for progid, label in (("Word.Application", "Microsoft Word"),
                          ("HwpFrame.HwpObject", "Hancom Office Hangul"),
                          ("KWPS.Application", "WPS Writer"),
                          ("Excel.Application", "Microsoft Excel")):
        mark = "yes" if _registered(progid) else "no "
        print(f"  [{mark}] {label:<26} ({progid})")
    print()
    print("A client is usable only if it appears above AND exposes automation.")
    print("Send this whole output back - the next step depends on what is here.")
    return 0


def _report(path=None):
    import getpass
    import platform
    import sys

    print("=" * 66)
    print("OrderFlow - PDF access diagnostic")
    print("=" * 66)
    print(f"  PC          : {platform.node()}")
    print(f"  User        : {getpass.getuser()}")
    print(f"  Process     : {os.path.basename(sys.executable)}")
    print(f"  Frozen exe  : {getattr(sys, 'frozen', False)}")
    print()

    print("Authorised applications installed here")
    print("-" * 66)
    any_client = False
    for c in pdf_status():
        mark = "yes" if c["installed"] else "no "
        any_client = any_client or c["installed"]
        print(f"  [{mark}] {c['name']:<16} ({c['progid']})")
    if not any_client:
        print("  none - there is no application this PC can delegate to")
    print()

    if not path:
        print("Pass a PO PDF to test it:")
        print(r'  python -c "import sys; sys.path.insert(0,\'src\'); '
              r'import of_pdf; of_pdf._report(r\'D:\POs\example.pdf\')"')
        return 0
    if not os.path.isfile(path):
        print(f"File not found: {path}")
        return 1

    print(f"File: {path}")
    print("-" * 66)
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except Exception as e:
        print(f"  cannot even open the file: {e}")
        return 1
    print(f"  first bytes : {head[:4]!r}")

    if head[:4] == b"%PDF":
        print("  -> this process reads it as a plain PDF. No DRM in the way.")
        print("     (If OrderFlow still fails here, the problem is elsewhere.)")
        return 0
    if head[:3] != b"<##":
        print("  -> not a PDF and not DRM-wrapped either. Wrong file?")
        return 1

    print("  -> NASCA DRM wrapped: this process is NOT on the decryption")
    print("     allow-list, so it receives ciphertext.")
    print()
    print("Trying the authorised applications")
    print("-" * 66)
    mode, value, note = resolve(path, log=lambda m: print(m.strip()))
    print()
    if mode == "path":
        print(f"  RESULT: readable copy obtained - {note}")
        print("          read as a PDF, like any other")
        return 0
    if mode == "text":
        print(f"  RESULT: text obtained - {note}")
        print(f"          {len(value.strip())} characters, no page layout")
        print("          codes are matched against the Material Code master")
        return 0
    print("  RESULT: no installed application could read it.")
    for part in note.split(" | "):
        print("          - " + part)
    print()
    print("  Next step: ask IT to add this program to the NASCA DRM viewer")
    print("  allow-list (by path), or install Acrobat on this PC.")
    return 1


# The former `pdf_access.py` CLI is disabled on purpose: this file is a library
# module, never a script. Its entry points are `_report()` and `_scan()`,
# reachable as `python -c "import sys; sys.path.insert(0,'src'); import of_pdf;
# of_pdf._report()"` and …of_pdf._scan()" — see the comment above the section.
# Deleting this block instead would lose the exact historical spelling; the
# guard name is deliberately impossible to match.
if __name__ == "__section_cli_disabled__":   # CLI guard, inactive after the merge
    import sys
    if "--scan" in sys.argv:
        sys.exit(_scan())
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(_report(args[0] if args else None))


# ==========================================================================
#  SECTION: QUICK CONVERT - file straight to Order Upload
#  (formerly quick_convert.py)
# ==========================================================================

# -*- coding: utf-8 -*-
"""quick_convert.py - convert a PO file straight into an Order Upload Excel

Bypassing mail: drag and drop a PO file you have on hand (PDF / Excel) and
only Material Code, qty and unit price are extracted to build the ERP upload form.

PDF   : uses the existing extraction engine (extractor_bridge) as is.
Excel : finds codes present in the Material Code master and reads the qty and
        unit price columns from that row. Codes not in the master are skipped and reported separately.
"""


QTY_HEADERS = ("qty", "quantity", "order qty", "qty ordered", "ordered",
               "order quantity", "qty order", "units", "pcs", "ea")
COST_HEADERS = ("unit price", "unit cost", "net cost", "net unit price",
                "net price", "dealer cost", "dealer price", "price", "cost",
                "rate", "each", "invoice", "dealer")
TOTAL_HEADERS = ("extended cost", "extended price", "extended", "ext price",
                 "ext cost", "line total", "total cost", "total amount",
                 "line amount", "total", "amount")
PO_HEADERS = ("po number", "po no", "po #", "po#", "po", "purchase order",
              "purchase order no", "purchase order number", "order number",
              "order no", "customer po")

# The first cell of the row that closes the line-item table. Everything below
# is a total, a note or a signature block - never an order line.
FOOTER_WORDS = ("total", "subtotal", "sub total", "grand total", "order total",
                "net order", "tax", "note", "notes", "comment", "comments",
                "remark", "remarks", "terms", "signature", "approved",
                "authorized", "thank", "please")


DRM_HEAD = b"<##"


def _head(b, n=8):
    return b[:n] if isinstance(b, (bytes, bytearray)) else b""


# What the extractor can open: a real PDF, or a real .xlsx/.xlsm (a zip).
READABLE_HEADS = (b"%PDF", b"PK")


def _usable(got, want):
    """True when the copy that landed on disk is something we can read.

    Two different outcomes both count as success.

    The bytes came back exactly as written - an ordinary, unprotected file.

    Or the bytes came back DECRYPTED. A browser is not a process the NASCA
    agent decrypts for, so a DRM-protected PO uploads as its raw container
    ('<##...'). Writing that container to disk produces a valid container,
    and reading it back as python.exe - which IS allow-listed - hands back
    plain '%PDF'. Measured on 2026-09-24: a byte copy of a protected PO,
    made by cmd, opened as a 4-page PDF when read by python.exe. The NASCA
    grant follows the PROCESS, not a registry of specific files.

    That second case used to be rejected here, because this function only
    accepted an exact byte match. That single equality check is why a
    DRM-protected file dropped into the browser could never be converted.
    """
    if got == want:
        return True
    return any(got.startswith(h) for h in READABLE_HEADS)


def save_input(raw, name, settings):
    """Write an uploaded file to disk so the extractor can open it.

    The bytes a browser uploads may be a DRM container rather than the
    document itself (see _usable). Writing them out and reading them back
    as python.exe is what turns them back into a readable file, so the
    check afterwards asks "can we read this?", not "is it unchanged?".

    Several directories are tried, because %TEMP% is often redirected into
    a managed Documents folder on corporate PCs.
    """
    import tempfile
    base = settings.get("_base", "")
    # The app's own folder comes first on purpose. %TEMP% is often redirected
    # into a managed Documents folder on corporate PCs, and DRM agents
    # auto-encrypt anything written there.
    candidates = [
        os.path.join(base, "data", "tmp"),      # inside the app folder
        tempfile.gettempdir(),                  # %TEMP%
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp"),
    ]
    want = _head(raw)
    tried = []
    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            sub = tempfile.mkdtemp(dir=d)
            p = os.path.join(sub, os.path.basename(name))
            with open(p, "wb") as f:
                f.write(raw)
            with open(p, "rb") as f:
                got = f.read(8)
            if _usable(got, want):
                return p
            tried.append(f"{d} -> {got[:3]!r}")
        except Exception as e:
            tried.append(f"{d} -> {e}")

    raise RuntimeError(
        f"'{name}' was written to disk but could not be read back as a PDF "
        "or a spreadsheet.\n\n"
        "A DRM-protected file normally still works here: the container is "
        "written out and comes back decrypted, because python.exe is "
        "allow-listed. Getting this far means neither that nor a plain copy "
        "succeeded - check with IT whether this PC still has the NASCA "
        "Decrypt with Python permission.\n\nTried: " + "; ".join(tried))


ALLOWED_EXT = (".pdf", ".xlsx", ".xlsm", ".xls", ".csv")


def resolve_paths(text):
    """Turn pasted text into a list of existing file paths.

    Accepts one file OR folder path per line, with or without quotes; a folder
    contributes every PDF/Excel file directly inside it.

    Reading files in place is what makes DRM-protected POs work. A browser
    upload always arrives encrypted because the browser is not an authorised
    process, while reading the path directly goes through the same route the
    Phase 1 extractor used with its data_upload folder.
    """
    out, bad = [], []
    for line in str(text or "").splitlines():
        p = line.strip().strip('"').strip("'")
        if not p:
            continue
        p = os.path.expandvars(os.path.expanduser(p))
        if os.path.isdir(p):
            found = [os.path.abspath(os.path.join(p, f))
                     for f in sorted(os.listdir(p))
                     if os.path.splitext(f)[1].lower() in ALLOWED_EXT
                     and os.path.isfile(os.path.join(p, f))]
            if found:
                out.extend(found)
            else:
                bad.append(f"{p} (no PDF or Excel file in this folder)")
        elif not os.path.isfile(p):
            bad.append(f"{p} (not found)")
        elif os.path.splitext(p)[1].lower() not in ALLOWED_EXT:
            bad.append(f"{os.path.basename(p)} (PDF or Excel only)")
        else:
            out.append(os.path.abspath(p))
    if bad:
        raise RuntimeError("These paths could not be used:\n  " +
                           "\n  ".join(bad))
    if not out:
        raise RuntimeError("No file or folder path was given.")
    # Same file given twice (e.g. a folder plus one of its files)
    seen, uniq = set(), []
    for p in out:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def scan_folder(folder):
    """List the PO files in a folder, for the file picker.
    Returns: [{name, path, size, kind}] sorted newest first."""
    p = os.path.expandvars(os.path.expanduser(str(folder or "").strip()
                                              .strip('"').strip("'")))
    if not p:
        raise RuntimeError("No folder was given.")
    if not os.path.isdir(p):
        raise RuntimeError(f"Folder not found: {p}")
    out = []
    for f in os.listdir(p):
        full = os.path.join(p, f)
        ext = os.path.splitext(f)[1].lower()
        if ext not in ALLOWED_EXT or not os.path.isfile(full):
            continue
        try:
            st = os.stat(full)
        except OSError:
            continue
        out.append({"name": f, "path": os.path.abspath(full),
                    "size": st.st_size, "mtime": st.st_mtime,
                    "kind": "PDF" if ext == ".pdf" else "Excel"})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    for x in out:
        x.pop("mtime", None)
    return {"folder": os.path.abspath(p), "files": out}


def locate_by_name(name, settings, folder=""):
    """Find a dropped file on disk by its name. Returns a path or "".

    A browser never hands over the full path of a dropped file, only its
    name and its bytes - and on a DRM-protected PO those bytes are cipher
    text, because the browser is not a process the DRM agent decrypts for.
    The file itself is perfectly readable, but only through its path, by
    this process.

    So when a drop turns out to be encrypted, look the name up in the
    folders the user has already pointed at: the box at the top of the
    Quick Convert screen, and the folder remembered from last time. Only an
    exact, unambiguous filename match counts - if the same name exists in
    both folders with different contents there is no way to tell which one
    was dragged, so nothing is returned and the user is asked instead.
    """
    name = os.path.basename(str(name or "").strip())
    if not name:
        return ""
    seen, hits = set(), []
    for d in (folder, settings.get("quick_folder", "")):
        d = os.path.expandvars(os.path.expanduser(
            str(d or "").strip().strip('"').strip("'")))
        if not d or not os.path.isdir(d):
            continue
        key = os.path.normcase(os.path.abspath(d))
        if key in seen:
            continue
        seen.add(key)
        p = os.path.join(d, name)
        if os.path.isfile(p):
            hits.append(os.path.abspath(p))
    # Same name in two different folders - which one was dragged is unknowable
    if len(set(os.path.normcase(h) for h in hits)) != 1:
        return ""
    return hits[0]


def cleanup_inputs(paths):
    """Delete the working copies written by save_input().
    PO files are confidential - they must not pile up on disk."""
    import shutil
    for p in paths or []:
        try:
            shutil.rmtree(os.path.dirname(p), ignore_errors=True)
        except Exception:
            pass


def qc_num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip().replace(",", "").replace("$", "")
    if not s:
        return None
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except ValueError:
        return None


def _header_row(rows):
    """Scan for a header row. Returns (columns, first data row, strict).

    Two passes, because two different things have to be true at once.

    The strict pass accepts a header only when it names a quantity column AND
    a money column. That pair is what tells a real order table apart from the
    reference sheets customers ship alongside their POs - a price list is
    "Model | Net Invoice": a price, but no quantity. Reading one of those as
    an order would invent a line for every model the customer sells.

    The loose pass is the rule this reader used before: any quantity OR money
    header, and failing even that, no header at all with the numbers read
    positionally from the code cell rightwards. Real POs do arrive without a
    header the strict pass recognises, and refusing them outright was a
    regression. Sheets that only match here are still read - but the caller
    then insists on seeing a real quantity in the rows before accepting the
    sheet as an order, which is what keeps the price lists out.
    """
    def scan(row):
        cells = [str(c).strip().lower() if c is not None else "" for c in row]
        if not any(cells):
            return None
        qty = cost = total = None
        for j, t in enumerate(cells):
            if not t:
                continue
            if qty is None and any(t == h or t.startswith(h)
                                   for h in QTY_HEADERS):
                qty = j
            elif total is None and any(h in t for h in TOTAL_HEADERS):
                total = j
            elif cost is None and any(h in t for h in COST_HEADERS):
                cost = j
        return qty, cost, total

    loose = None
    for idx, row in enumerate(rows[:25]):
        found = scan(row)
        if not found:
            continue
        qty, cost, total = found
        if qty is not None and (cost is not None or total is not None):
            return {"qty": qty, "cost": cost, "total": total}, idx + 1, True
        if loose is None and (qty is not None or cost is not None
                              or total is not None):
            loose = ({"qty": qty, "cost": cost, "total": total}, idx + 1)

    if loose:
        return loose[0], loose[1], False
    # No header at all - read every row and infer the numbers by position.
    return {"qty": None, "cost": None, "total": None}, 0, False


def _is_footer(row):
    """True when this row closes the table (a total, a note, a signature)."""
    for c in row:
        if c in (None, ""):
            continue
        t = str(c).strip().lower().rstrip(":").strip()
        return bool(t) and any(t == w or t.startswith(w + " ") or t == w + "s"
                               for w in FOOTER_WORDS)
    return False


def _po_value(cell):
    """A cell read as a PO number, or None.

    Guards the label/value scan against two things seen on real forms: a
    "PURCHASE ORDER" title sitting directly above a "PO Number:" label, which
    would otherwise be read as its value, and an empty cell beside a label.
    Every PO number carries a digit, so that is the test.
    """
    if cell in (None, ""):
        return None
    t = str(cell).strip()
    if not t or not re.search(r"\d", t):
        return None
    if t.lower().rstrip(":").strip() in PO_HEADERS:
        return None
    return t


def _find_po(rows):
    """Find a PO number written somewhere on the sheet."""
    rx = re.compile(r"(?:P\.?O\.?|PURCHASE\s*ORDER)"
                    r"(?:\s*(?:NUMBER|NO|#))?[\s#:.\-]*"
                    r"([A-Z0-9][A-Z0-9\-]{3,19})", re.IGNORECASE)
    for i, row in enumerate(rows[:40]):
        for j, c in enumerate(row):
            if c is None:
                continue
            t = str(c).strip()
            mo = rx.search(t)
            # A PO number always carries a digit. Without this check the
            # label itself is captured - "PO Number:" yields "Number".
            if mo and re.search(r"\d", mo.group(1)):
                return mo.group(1)
            if t.lower().rstrip(":").strip() not in PO_HEADERS:
                continue
            # Value beside the label ...
            for k in range(j + 1, min(j + 4, len(row))):
                v = _po_value(row[k])
                if v:
                    return v
            # ... or directly under it, the way a column-style form prints it
            if i + 1 < len(rows) and j < len(rows[i + 1]):
                v = _po_value(rows[i + 1][j])
                if v:
                    return v
    return ""


def parse_excel_sheet(path, settings, mm, sheet=None):
    """One worksheet -> a result dict, or None when the sheet is not a PO.

    None is the normal answer for the reference sheets that travel with a PO
    workbook; the caller skips them rather than reporting a failure.
    """
    rows = material_master._read_rows(path, sheet)
    if not rows:
        return None
    cols, start, strict = _header_row(rows)

    records, unknown = [], []
    for row in rows[start:]:
        hit_code = hit_col = None
        for j, cell in enumerate(row):
            if cell is None:
                continue
            token = str(cell).strip()
            if len(token) < 4 or " " in token:
                continue
            found = material_master.lookup(mm, token)
            if found:
                hit_code, hit_col = found.get("code") or token, j
                break
            if material_master.looks_like_code(token):
                unknown.append(token)
        if not hit_code:
            # The first row below the table that is a total or a note closes
            # it; anything further down is not an order line.
            if _is_footer(row):
                break
            continue

        def pick(field, fallback_after):
            j = cols.get(field)
            v = qc_num(row[j]) if j is not None and j < len(row) else None
            if v is not None:
                return v
            # No column for this field - infer from the numbers right of the code
            nums = [qc_num(row[k]) for k in range(hit_col + 1, len(row))]
            nums = [v for v in nums if v is not None]
            if not nums:
                return None
            if field == "qty":
                # A lone number beside a code is a price, never a quantity -
                # that is exactly what a price-list row looks like. Only infer
                # a quantity when the row carries a second number for the
                # money to live in.
                return nums[0] if len(nums) >= 2 else None
            return nums[fallback_after] if len(nums) > fallback_after else None

        qty = pick("qty", 0)
        cost = pick("cost", 1)
        # The extended amount is carried through as printed; no arithmetic is
        # applied to it anywhere downstream.
        j = cols.get("total")
        amount = qc_num(row[j]) if j is not None and j < len(row) else None

        # Order templates leave pre-filled rows below the last real item,
        # zero across the board. A row with no quantity and no money is one.
        if not qty and not cost and not amount:
            continue

        records.append({
            "material_code": hit_code,
            "quantity": "" if qty is None else qty,
            "unit_price": "" if cost is None else cost,
            "amount": "" if amount is None else amount,
            "description": " ".join(
                str(c) for c in row if c not in (None, ""))[:300],
        })

    if not records:
        return None

    # A sheet matched only by the loose pass has to prove it is an order:
    # at least one row carrying a real quantity. A price list reaches this
    # point with a code and a price on every row and no quantity anywhere,
    # and must not be turned into an order for the customer's whole catalogue.
    if not strict and not any(qc_num(r["quantity"]) for r in records):
        return None

    po = _find_po(rows)
    from_sheet = False
    if not po and sheet and not re.match(r"^Sheet\d*$", str(sheet), re.I):
        # These workbooks name the tab after the PO it holds ("SMA8673-DIS").
        # That is a value printed on the document, not a guess - but it is
        # flagged so the screen can say where it came from.
        po, from_sheet = str(sheet).strip(), True

    return {
        "po_number": po,
        "records": records,
        "_pdf_path": "",
        "_unknown": sorted(set(unknown))[:10],
        "_columns": cols,
        "_sheet": sheet or "",
        "_po_from_sheet_name": from_sheet,
    }


def parse_excel_pos(path, settings):
    """Every PO in one workbook, in tab order.

    A workbook routinely holds more than one PO - one per worksheet - next to
    reference sheets that are not orders at all. Reading only the active sheet
    silently dropped the rest.
    """
    mm = material_master.load(settings)
    if not mm.get("codes"):
        raise RuntimeError(
            "No Material Codes yet. Upload a price sheet under Material "
            "Codes first — Quick Convert matches codes against that list.")

    names = material_master.sheet_names(path) or [None]
    out, seen = [], []
    for name in names:
        seen.append(name or "(only sheet)")
        try:
            res = parse_excel_sheet(path, settings, mm, name)
        except Exception as e:
            # One unreadable sheet must not lose the POs on the others.
            print(f"  [XLS] sheet '{name}' could not be read: {e}")
            continue
        if res:
            out.append(res)

    if not out:
        raise RuntimeError(
            "No purchase-order table found in this workbook. A sheet is read "
            "as a PO only when it has a header row naming a quantity column "
            "and a price or amount column.\n\nSheets seen: " +
            ", ".join(seen))
    return out


def parse_excel_po(path, settings):
    """The first PO in a workbook. Kept for callers that expect one result."""
    return parse_excel_pos(path, settings)[0]


def convert(paths, settings, po_number="", sold_to="", ship_to=""):
    """Dropped files -> one Order Upload Excel.
    Returns: {file, lines, messages, ...}"""

    pdfs = [p for p in paths if p.lower().endswith(".pdf")]
    sheets = [p for p in paths
              if os.path.splitext(p)[1].lower() in
              (".xlsx", ".xlsm", ".xls", ".csv")]
    other = [p for p in paths if p not in pdfs and p not in sheets]

    results, msgs, unknown = [], [], []

    if pdfs:
        extract_fn = extractor_bridge._load_engine(settings)
        for p in pdfs:
            name = os.path.basename(p)
            try:
                path = p
                if pdf_access.is_drm(p):
                    # Have an allow-listed application read it, the same way
                    # price-sheet Excel files go through Excel.
                    mode, value, note = pdf_access.resolve(
                        p, log=print,
                        enabled=bool(settings.get("pdf_delegation", True)))
                    if mode == "path":
                        path, msgs = value, msgs + [f"{name}: DRM, {note}"]
                    elif mode == "text":
                        # Recovered text goes to the same API call as a PDF,
                        # so a DRM document is read by exactly the same rules
                        # as a plain one.
                        r = _load_module(settings).from_text(
                            value, source=name)
                        results.append(r)
                        msgs.append(f"{name}: DRM, {note} - "
                                    f"{len(r['records'])} code(s), text only")
                        continue
                    else:
                        raise RuntimeError(
                            "the file is NASCA DRM protected and no installed "
                            "application could read it. " + note)
                with open(path, "rb") as f:
                    head = f.read(8)
                if head[:4] != b"%PDF":
                    raise RuntimeError(
                        f"this is not a PDF (file starts with {head[:4]!r}).")
                r = extract_fn(str(path), force=True)
                r["_pdf_path"] = str(path)
                results.append(r)
                msgs.append(f"{name}: {len(r.get('records', []))} code(s)")
            except Exception as e:
                msgs.append(f"{name}: FAILED - {e}")

    for p in sheets:
        name = os.path.basename(p)
        try:
            found = parse_excel_pos(p, settings)
            for r in found:
                results.append(r)
                unknown.extend(r.get("_unknown", []))
                where = f" [{r['_sheet']}]" if r.get("_sheet") else ""
                note = ""
                if r.get("_po_from_sheet_name"):
                    note = (f", PO {r['po_number']} taken from the sheet name "
                            "(not printed in the sheet)")
                msgs.append(f"{name}{where}: {len(r['records'])} code(s){note}")
        except Exception as e:
            msgs.append(f"{name}: FAILED - {e}")

    for p in other:
        msgs.append(f"{os.path.basename(p)}: skipped (PDF or Excel only)")

    if not any(r.get("records") for r in results):
        raise RuntimeError("No material codes found.\n\n" + "\n".join(msgs))

    # One dropped file can hold several POs. Split it here, so the review card
    # shows 100 lines with four different P/O numbers instead of one order.
    results = expand_orders(results)

    # Same master normalisation the mail Confirm path applies, so a PDF gives
    # identical codes whichever way it is processed.
    fixed, notlisted, err = extractor_bridge.normalise_to_master(
        results, settings)
    if err:
        msgs.append(f"(material master check skipped: {err})")
    if fixed:
        msgs.append("normalised to master: " + ", ".join(fixed[:5]))
    unknown.extend(notlisted)

    # A value entered on screen takes precedence over the PO number found in the file
    if po_number:
        for r in results:
            r["po_number"] = po_number

    # Clean up and propose lines only - the user reviews them on screen and
    # the Excel file is written by export() afterwards.
    # Models judged to be quoted inside another item's description come back
    # too, unticked, so the reviewer decides instead of the heuristic.
    lines, no_qty, no_cost, dropped, fixes = erp_excel.prepare_lines(
        results, {"po_number": po_number}, keep_dropped=True)
    # The per-order header the document printed: the two dates and the delivery
    # address. Sent back to the page so the review card can show them (and let
    # the user override them) and so export() can write them into columns
    # K / M / R-S-V / W / X / AZ.
    order = erp_excel._po_header(results)[0]
    return {
        "count": sum(1 for l in lines if l["include"]),
        "messages": msgs, "fixes": fixes,
        "no_qty": no_qty, "no_cost": no_cost, "dropped": dropped,
        "unknown": sorted(set(unknown))[:10],
        "order": order,
        "po_number": (results[0].get("po_number") if results else ""),
        # Everything the document turned out to hold. `po_number` stays the
        # first (or the only) one so an old caller keeps working; the list is
        # what the card shows when there is more than one.
        "po_numbers": [r.get("po_number") for r in results if r.get("po_number")],
        "order_count": len(results),
        # `needs_review` is what the review card highlights and what holds the
        # line back from the file: a code the Material Code list does not carry
        # is shown with its quantity and price, unchecked, and only goes into
        # the Order Upload once somebody ticks it.
        "lines": [{"code": l["code"], "qty": l["qty"], "cost": l["cost"],
                   "use": l["include"],
                   # The order the row was printed on, so the export can give
                   # this row its own P/O No., address and dates. `order` is
                   # the header only - never the records.
                   "po": l.get("po") or "",
                   "order": (erp_excel.order_brief(l.get("order"))
                             if l.get("order") else None),
                   "needs_review": bool(l.get("needs_review")),
                   "review_reason": l.get("review_reason") or "",
                   "note": (l.get("review_reason")
                            if l.get("needs_review") else
                            "" if l["include"] else
                            "quoted in a description?")}
                  for l in lines][:200],
    }


def export(lines, settings, tag="", po="", fmt=None, sold_to="", ship_to="",
           ship=None, order=None):
    """Reviewed lines -> Order Upload Excel.

    Material Code, Quantity and Unit Cost are written for every ticked line, and
    the P/O No. as well when `po` is given - the ERP form marks that column
    mandatory, and Quick Convert has the number on screen. Sales Org and
    Division come from the constants; `sold_to` goes to column F and `ship_to`
    to column G, and it is the Ship-To that decides the Distribution Channel
    (column D) - see erp_excel._party_fill().

    `ship` is the Ship-To block typed on the review card:
    {ship_to_name, ship_to_name2/3/4, ship_to_address, ship_to_street2..5,
     ship_to_zip, ship_to_city, ship_to_region} -> ERP columns N, O-Q, R,
    S-V, W, X, AZ. Typed values win; the Ship-to Name keeps the master's
    default when the box is empty. Address fields have no master fallback.

    `order` is what the PO printed for the whole order - {po_date, rdd,
    rdd_source, rdd_defaulted, ship_to_address, ship_to_street2..5,
    ship_to_city, ship_to_zip, ship_to_region}. It reaches columns K, M and the
    address block under the typed values, so a box on the review card always
    wins. None is allowed: the file is then built from what was typed only.

    fmt: "full" for the ERP form, "simple" for the four-column sheet. Omitted
      or unrecognised means the dashboard's saved choice (settings.erp_format),
      then the full form.
    Unticked lines (use == False) are never written.
    Returns: (path, line count)"""
    lines = [l for l in (lines or []) if l.get("use", True) is not False]
    if fmt in (None, ""):
        fmt = settings.get("erp_format", erp_excel.FORMAT_FULL)
    return erp_excel.build_upload_lines(
        lines, settings, tag or "QuickConvert", po=po,
        sold_to=sold_to, ship_to=ship_to, fmt=fmt, ship=ship, order=order)


# ==========================================================================
#  SECTION: EXTRACTOR BRIDGE - call into the extraction engine
#  (formerly extractor_bridge.py)
# ==========================================================================

# -*- coding: utf-8 -*-
"""extractor_bridge.py - call into the PO extraction engine

Imports CodeExtract/claude_engine.py (formerly CodeExtract/engine.py) and, on
Confirm, builds document -> (code, qty, unit price) records -> Order Upload
Excel (the ERP EXCEL section of of_erp.py).

The DeepSeek test engine renders PDF pages to images, sends them to DeepSeek
and gets the ordered line items back as JSON. It still keeps its own paths (claude_config.json,
data_cache) relative to CodeExtract/, and its code list is a mirror of Master
Data > Material Codes, rebuilt by material_master.sync_to_engine().

See docs/HANDOVER.md chapter 4 for the shape of the dict the engine returns
and for what the accuracy gate does with it.
"""
import sys


_ENGINE = None   # the extract function
_ENGINE_MOD = None   # the extraction module


def _import_engine(settings):
    """Import `CodeExtract/claude_engine.py`. Does NOT require a key.

    Split out of `_load_module` so the Settings screen can show the endpoint,
    the model and whether a key is stored *before* one exists - otherwise the
    first screen a new machine opens would raise instead of explaining.
    """
    global _ENGINE_MOD
    if _ENGINE_MOD is not None:
        return _ENGINE_MOD
    base = settings.get("_base", "")
    ce_dir = os.path.join(base, "CodeExtract")
    if not os.path.isdir(ce_dir):
        raise RuntimeError(f"CodeExtract folder not found: {ce_dir}")
    if ce_dir not in sys.path:
        sys.path.insert(0, ce_dir)
    import claude_engine
    _ENGINE_MOD = claude_engine
    return _ENGINE_MOD


def _load_module(settings):
    """The PO extraction engine - `CodeExtract/claude_engine.py`.

    PDF extraction is done by DeepSeek Vision: pages are rendered locally and
    the ordered line items come back as JSON. The local engine that used to do
    this (OCR, table geometry, four fallback paths) is retired in
    `CodeExtract/_legacy/`.
    """
    mod = _import_engine(settings)
    if not mod.api_key():
        raise RuntimeError(
            "no API key stored. Paste one on the Settings screen under "
            '"PO reading", or set the environment variable '
            "DEEPSEEK_API_KEY.")
    return mod


def po_reading_state(settings):
    """What the Settings screen shows about PO reading.

    {"base_url", "model", "key_set", "models": [{id, note}], "error"}.
    Nothing secret is returned - a key is only ever reported as present.
    """
    try:
        mod = _import_engine(settings)
    except Exception as e:
        return {"base_url": "", "stored_base_url": "", "model": "",
                "key_set": False, "models": [], "error": str(e)}
    cfg = mod.load_config()
    return {
        "provider": "DeepSeek",
        # `base_url` is the address a PO will actually go to; the Settings box
        # shows `stored_base_url` as its value, so an empty box still reads as
        # "use the default" rather than looking like the default was typed in.
        "base_url": mod.base_url(),
        "stored_base_url": str(
            ((settings.get("deepseek") or {}).get("base_url")) or ""),
        "model": cfg.get("model", ""),
        # The dropdown shows `stored_model` as its selection and offers
        # `models`; `model` is the one a PO would actually be read with
        # (settings > claude_config.json > default).
        "stored_model": str(
            ((settings.get("deepseek") or {}).get("model")) or ""),
        "default_model": mod.DEFAULTS.get("model", ""),
        "key_set": bool(mod.api_key()),
        "models": [{"id": k, "note": v} for k, v in mod.KNOWN_MODELS.items()],
        "error": "",
    }


def test_po_reading(settings, base_url="", api_key=""):
    """The Settings screen's Test button - one cheap round trip.

    Same shape as `test_outlook()` on the Outlook side, so the page can render
    both results with the same block: {ok, endpoint, model, latency_ms, reply,
    error, hint}.

    `base_url` / `api_key` are whatever is currently typed in the boxes, so the
    test reflects the form rather than only what was last saved. They are used
    for this one request and never stored - pressing Save is what stores them.
    """
    try:
        mod = _import_engine(settings)
    except Exception as e:
        return {"ok": False, "endpoint": "", "model": "", "latency_ms": 0,
                "reply": "", "error": str(e),
                "hint": "CodeExtract/claude_engine.py could not be imported."}
    return mod.test_connection(base_url_override=base_url or "",
                               key_override=api_key or "")


def _load_engine(settings):
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    _ENGINE = _load_module(settings).extract_material_codes
    return _ENGINE


def _code_base(code, material_master):
    """The part before a market-suffix slash, normalized.
    'DW80R9950QN/AA' -> 'DW80R9950QN'."""
    return material_master.norm(str(code or "").split("/")[0])


def _backbone_class(settings):
    """code_rules.BackboneIndex - the matcher the engine gates on, and the one
    this rewrite uses. ONE set of rules for what a code is."""
    return material_master.code_rules(settings.get("_base", "")).BackboneIndex


def normalise_to_master(results, settings):
    """Rewrite extracted codes to the Material Code master's spelling.

    ERP is operated on the master notation, so whatever spelling the PDF or
    Excel PO used must be replaced by the listed one. Shared by the mail
    Confirm path and by Quick Convert so both produce identical codes.

    Two rewrites run, in this order:

    1. **short SKU → FULL SKU**, from the Product Mapping Table's `sku_map`. A
       PO prints the short SKU and ERP is keyed on the FULL SKU, so this is what
       makes a mapped SKU land in the right place. The mapping table is the
       authority, never a string rule - 110 of its real rows have a short SKU
       that is not a prefix of its FULL SKU. A short SKU that maps to several
       FULL SKUs is left alone for a human, never guessed.
    2. **spelling → the listed spelling**, through the engine's own
       `BackboneIndex`, built from the master: ONE set of matching rules for
       extraction and for this rewrite. Keeping a second, simpler rule here is
       what broke glued market suffixes: the engine knew "DW80CG4051SR" is
       "DW80CG4051SRAA", but this step only split on "/" and so left the short
       code in the Order Upload file.

    Market variants sharing a base ("/AA" vs "/A3"): customers who order on
    manual POs only ever take /AA, so /AA is chosen. When several variants
    share a base and none of them is /AA, the code is left as extracted
    rather than guessed - it shows up in the unknown list for a human.

    Returns: (fixed, unknown, error_message)
    """
    try:
        mm = material_master.load(settings)
        codes = mm.get("codes") or {}
        if not codes:
            return [], [], ""

        index = _backbone_class(settings)(
            {e["code"]: e for e in codes.values() if e.get("code")})

        # Market variants that share a base ("RF23A9671SR/AA", ".../A3")
        variants = {}
        for entry in codes.values():
            variants.setdefault(_code_base(entry.get("code"), material_master),
                                []).append(entry.get("code"))

        fixed, unknown = [], []
        for r in results:
            for rec in r.get("records", []):
                raw = rec.get("material_code")
                # 1) short SKU -> FULL SKU, from the mapping table
                full = material_master.sku_full(settings, raw or "")
                code = full or raw
                if full and full != raw:
                    fixed.append(f"{raw} -> {full} (short SKU)")
                # 2) -> the listed spelling
                hit = material_master.lookup(mm, code)
                listed = (hit or {}).get("code") or ""
                if not listed:
                    listed, _kind = index.lookup(code or "")
                    group = variants.get(
                        _code_base(listed, material_master)) or []
                    if (listed and len(group) > 1
                            and not str(listed).upper().endswith("/AA")):
                        listed = ""      # several variants, no /AA: don't guess
                if not listed:
                    # The FULL SKU of a mapped short is still the right thing to
                    # publish: it is what ERP is keyed on even when the master
                    # does not carry it as a code of its own.
                    if full:
                        if full != raw:
                            rec["material_code"] = full
                        continue
                    unknown.append(raw or "?")
                    continue
                if listed != raw:
                    if not (full and listed == full):
                        fixed.append(f"{raw} -> {listed}")
                    rec["material_code"] = listed
        return fixed, unknown, ""
    except Exception as e:
        return [], [], str(e)


EXCEL_EXT = (".xlsx", ".xlsm", ".xls", ".csv")


def preview_order(paths, settings, mail, typed_ship=None, sold_to="",
                  ship_to="", fmt=None):
    """Read the documents, then describe the file that would be written.

    Named `preview_order`, not `order_preview`, on purpose: `of_erp` already has
    an `order_preview()` and `orderflow.py` merges every module's globals into
    ONE flat namespace, so two same-named functions silently become one - and
    the wrong one gets called with the wrong arguments. That is exactly what
    happened the first time this was written.

    The reading happens HERE, not at generate time (2026-10-23). The delivery
    address and the two dates are printed on the PO, so a preview that skipped
    the reading could not show them - and those are precisely the columns the
    preview exists to let a person confirm.

    It costs one API call. The generate step calls `run_extractor(force=False)`,
    which finds this reading in the cache and does NOT pay again.
    """
    results, msgs, ok = read_orders(paths, settings, force=True)
    prev = erp_excel.order_preview(
        mail, settings, typed_ship=typed_ship, sold_to=sold_to,
        ship_to=ship_to, results=results, read_ok=bool(results),
        fmt=fmt or settings.get("erp_format", erp_excel.FORMAT_FULL))
    prev["messages"] = msgs
    prev["read"] = ok
    if not results:
        # Nothing was read, so every column the document was supposed to supply
        # is empty. Say it once, at the top of the page, instead of leaving the
        # user to work out why the address block is blank.
        why = next((m for m in msgs if m), "")
        prev["warnings"] = list(prev.get("warnings") or []) + [
            "Nothing could be read from this email's attachments"
            + (": " + why[:220] if why else "")
            + " - the address and both dates are blank and will stay blank "
              "unless you type them on the row."]
    return prev


# ==========================================================================
#  SECTION: READINGS ALREADY ON DISK (the Inbox's "Read" tab)
# ==========================================================================
# A confirmation already pays for a reading and caches it, keyed by the
# document's file name. Until now that cache was only ever read on the way to
# writing a file, so a document that had been read but not yet turned into an
# Order Upload existed nowhere a person could see it: it had left the Inbox
# (status Done) and had not arrived in Completed (no file).
#
# These three functions expose that cache. They never call the API - the whole
# point of the tab is "what has been read", and a list that costs one request
# per row would make looking more expensive than doing.

# What the expanded row shows, in the order the ERP columns ask for them. The
# labels say "not printed" when the document carried nothing, which is a fact
# about the PO, not an error - a blank address is sometimes correct.
_READ_FIELDS = (
    ("PO date", "po_date"),
    ("RDD", "rdd"),
    ("RDD source", "rdd_source"),
    ("Ship-To name", "ship_to_name"),
    ("Address", "ship_to_address"),
    ("Street 2", "ship_to_street2"),
    ("Street 3", "ship_to_street3"),
    ("City", "ship_to_city"),
    ("State", "ship_to_region"),
    ("ZIP", "ship_to_zip"),
)


def _read_str(value):
    return str(value or "").strip()


def cached_read(settings, path):
    """The reading already on disk for one document, or None. NO API call."""
    try:
        eng = _import_engine(settings)
        return eng.load_cache(eng.get_cache_path(path))
    except Exception:
        return None


def _cache_orders(d):
    """The orders a saved reading holds, as small display dicts.

    A cache written before 2026-10-28 has no `orders` list, only the top-level
    header: that is one order and it is described from those keys, so an old
    reading still shows a PO number and a date instead of nothing.
    """
    blocks = d.get("orders") or []
    if not blocks:
        blocks = [{"po_number": d.get("po_number") or "",
                   "po_date": d.get("po_date") or "",
                   "rdd": d.get("rdd") or "",
                   "rdd_defaulted": d.get("rdd_defaulted"),
                   "document_total": d.get("document_total") or "",
                   "ship_to_address": d.get("ship_to_address") or "",
                   "ship_to_city": d.get("ship_to_city") or "",
                   "ship_to_zip": d.get("ship_to_zip") or ""}]
    recs = d.get("records") or []
    out = []
    for b in blocks:
        idx = b.get("index")
        out.append({
            "po": _read_str(b.get("po_number")),
            "po_date": _read_str(b.get("po_date")),
            "rdd": _read_str(b.get("rdd")),
            "rdd_defaulted": bool(b.get("rdd_defaulted")),
            "total": _read_str(b.get("document_total")),
            "address": _read_str(b.get("ship_to_address")),
            "city": _read_str(b.get("ship_to_city")),
            "zip": _read_str(b.get("ship_to_zip")),
            "lines": (sum(1 for r in recs if r.get("order_index") == idx)
                      if idx is not None else
                      int(b.get("line_count") or len(recs))),
        })
    return out


def read_summary(settings, path):
    """One line for the Read tab, or None when nothing has been read.

    Kept small on purpose: the list can hold hundreds of rows and the expanded
    body is its own request (`read_detail`).
    """
    d = cached_read(settings, path)
    if not d:
        return None
    recs = d.get("records") or []
    orders = _cache_orders(d)
    return {
        "read_at": _read_str(d.get("processed_at")),
        "po_number": _read_str(d.get("po_number")),
        # A document can hold several POs, and then it has no single number -
        # the row says "4 POs" and the expanded row lists them.
        "po_count": len(orders),
        "po_numbers": [o["po"] for o in orders if o["po"]],
        "lines": len(recs),
        "review": sum(1 for r in recs if r.get("needs_review")),
        "po_date": _read_str(d.get("po_date")),
        "rdd": _read_str(d.get("rdd")),
        "rdd_source": _read_str(d.get("rdd_source")),
    }


def read_detail(settings, path, limit=40):
    """What the reading actually took off the page, for one expanded row.

    Capped at `limit` lines: this is a preview of a reading that already exists,
    not a second copy of the file, and the operator can open the Order Upload
    for the full list.
    """
    d = cached_read(settings, path)
    if not d:
        return {"error": "This document has no saved reading yet. Confirm it "
                         "from the Inbox - then it appears here."}
    orders = _cache_orders(d)
    multi = len(orders) > 1
    # With several POs there is no "the" address, no "the" PO date and no "the"
    # R.D.D - the top of the cache is deliberately empty for them. A single
    # field grid would then say "not printed" about four dates that ARE
    # printed, so the panel shows the order list instead (see `orders` below).
    fields = ([] if multi else
              [[label, _read_str(d.get(key))] for label, key in _READ_FIELDS])
    fields.append(["Read at", _read_str(d.get("processed_at"))])
    fields.append(["Source file", _read_str(d.get("source_file"))])
    recs = d.get("records") or []
    rows = [{
        "code": _read_str(r.get("material_code")),
        "desc": _read_str(r.get("description")),
        "qty": _read_str(r.get("quantity")),
        "price": _read_str(r.get("unit_price")),
        "amount": _read_str(r.get("amount")),
        "review": bool(r.get("needs_review")),
    } for r in recs[:limit]]
    return {
        "fields": fields,
        # The orders this document held, when it held more than one.
        "orders": orders if multi else [],
        "records": rows,
        "more": max(0, len(recs) - limit),
        "page_count": d.get("page_count") or 0,
        # Readings taken before 2026-10-22 came from the retired local engine,
        # which never captured the header block. Their address fields are not
        # "blank on the PO", they were never looked for - and saying "not
        # printed" about them would be a lie the operator could act on.
        "legacy": not any(key in d for _label, key in _READ_FIELDS),
    }


# Keys of an order block that describe the BLOCK, not the order. Everything
# else on a block is a per-order value in the shape the ERP columns want, and
# is copied straight onto the result it is split into.
_ORDER_BLOCK_META = ("index", "po_number", "document_total", "line_count",
                     "review_count", "diagnostics")


def _read_note(r):
    """'25 code(s), PO ALRRY-A' / '100 code(s), 4 POs (ALRRY-A, ...)'.

    A multi-PO document has no single number, so the message has to name them
    all - otherwise the log line for a four-PO attachment reads like a
    one-PO one and nobody notices three orders were read.
    """
    n = len(r.get("records") or [])
    numbers = [str(x) for x in (r.get("po_numbers") or []) if x]
    count = int(r.get("order_count") or 1)
    if count > 1:
        shown = ", ".join(numbers[:4]) + (" …" if len(numbers) > 4 else "")
        return (f"{n} code(s) in {count} POs"
                + (f" ({shown})" if shown else ""))
    po = r.get("po_number") or ""
    return f"{n} code(s)" + (f", PO {po}" if po else "")


def expand_orders(results):
    """One result per ORDER (2026-10-28). A single-order document passes through.

    Every consumer downstream was written around "one reading is one order":
    the accuracy gate labels a line with the order's number, `prepare_lines`
    stamps that number on the line, the ERP writer puts it in column A, and the
    address and the two dates are read once per reading. A PDF holding four POs
    breaks every one of those assumptions at once, so it is split here, once,
    instead of teaching six call sites about `orders`.

    A document with one order - every document until Curacao stapled four into
    one file - comes back as the very same object, so nothing about the normal
    path changes.
    """
    out = []
    for r in results or []:
        blocks = r.get("orders") or []
        recs = r.get("records") or []
        if len(blocks) < 2:
            out.append(r)
            continue
        review = r.get("review") or []
        for b in blocks:
            idx = b.get("index")
            sub = dict(r)
            for k, v in (b or {}).items():
                if k not in _ORDER_BLOCK_META:
                    sub[k] = v
            sub["po_number"] = str(b.get("po_number") or "")
            sub["document_total"] = str(b.get("document_total") or "")
            sub["records"] = [x for x in recs if x.get("order_index") == idx]
            sub["review"] = [x for x in review if x.get("order_index") == idx]
            sub["orders"] = [b]
            sub["order_count"] = len(blocks)
            sub["order_index"] = idx
            sub["order_label"] = (f"PO {idx + 1} of {len(blocks)}"
                                  f" ({sub['po_number'] or 'no number'})")
            stats = dict(r.get("stats") or {})
            stats["total"] = len(sub["records"])
            stats["review_count"] = len(sub["review"])
            stats["orders"] = len(blocks)
            sub["stats"] = stats
            out.append(sub)
    return out


def read_orders(paths, settings, force=True):
    """Read every PO attachment -> (results, msgs, ok). NO file is written.

    Split out of `run_extractor()` on 2026-10-23 because Confirm became two
    steps: the preview has to show the address and the dates the DOCUMENT
    carries, so the reading now happens before the user agrees to anything, and
    the file is built afterwards from what was already read.

    `force=True` re-reads even when the cache is valid (the preview path: the
    Material Code list may have changed). `force=False` reuses the cache, which
    is what makes the second step free - the preview already paid for the API
    call, so generating must not pay again.

    paths: attachment paths, PDF and/or Excel mixed together. Each kind is read
    by its own path - the PDF engine, or the same Excel reader Quick Convert
    uses - and the results are merged before the caller builds anything. A PO
    that arrives as a spreadsheet used to be silently dropped here (only ".pdf"
    paths were ever looked at), which Confirmed the mail but produced no
    Order Upload file.
    """
    cfg = settings.get("extractor", {})
    if not cfg.get("enabled", True):
        return [], ["Extractor disabled (settings.json extractor.enabled=false)"], 0
    if not paths:
        return [], ["No PDF or Excel attachments on this email"], 0

    pdf_paths = [p for p in paths if p.lower().endswith(".pdf")]
    sheet_paths = [p for p in paths
                  if os.path.splitext(p)[1].lower() in EXCEL_EXT]

    results, msgs, ok = [], [], 0

    # Excel attachments: the same reader Quick Convert uses, so a PO produces
    # identical codes whether it is Confirmed from mail or converted directly.
    if sheet_paths:
        for p in sheet_paths:
            name = os.path.basename(p)
            try:
                found = quick_convert.parse_excel_pos(p, settings)
                for r in found:
                    results.append(r)
                    ok += 1
                    where = f" [{r['_sheet']}]" if r.get("_sheet") else ""
                    msgs.append(f"{name}{where}: {len(r['records'])} code(s)")
            except Exception as e:
                msgs.append(f"{name}: FAILED - {e}")

    if pdf_paths:
        try:
            extract_fn = _load_engine(settings)
        except Exception as e:
            extract_fn = None
            msgs.append(f"Extractor engine not available: {e}")

        if extract_fn:
            # A DRM-protected attachment reads as ciphertext, and the PDF
            # libraries then report confusing things like "No /Root object".
            # Check first and say plainly what is wrong.
            readable, as_text = [], []
            for pdf in pdf_paths:
                if not pdf_access.is_drm(pdf):
                    readable.append(pdf)
                    continue
                # Ask an application that IS allow-listed to read it for us,
                # exactly as price-sheet Excel files are read through Excel.
                mode, value, note = pdf_access.resolve(
                    pdf, log=print,
                    enabled=bool(settings.get("pdf_delegation", True)))
                name = os.path.basename(pdf)
                if mode == "path":
                    readable.append(value)
                    msgs.append(f"{name}: DRM-protected, {note}")
                elif mode == "text":
                    as_text.append((pdf, value))
                    msgs.append(f"{name}: DRM-protected, {note} "
                                "(text only - no page layout)")
                else:
                    msgs.append(f"{name}: DRM-protected and no installed "
                                f"application could read it. {note}")

            for pdf, text in as_text:
                name = os.path.basename(pdf)
                try:
                    r = _load_module(settings).from_text(text, source=name)
                    results.append(r)
                    msgs.append(f"{name}: {_read_note(r)} from text")
                except Exception as e:
                    msgs.append(f"{name}: FAILED - {e}")

            for pdf in readable:
                name = os.path.basename(pdf)
                try:
                    # force=True: when Confirm is re-run after adding a code to
                    # the master, the cache must be bypassed and re-extracted
                    # with the new master so learning applies
                    r = extract_fn(str(pdf), force=force)
                    r["_pdf_path"] = str(pdf)   # used to re-verify qty/unit price against the original
                    results.append(r)
                    ok += 1
                    msgs.append(f"{name}: " + _read_note(r))
                    rev = r.get("review") or []
                    if rev:
                        msgs.append(f"  ? {len(rev)} unknown code(s) — review "
                                    f"in Code Learning: " +
                                    ", ".join(x.get("candidate", "?")
                                             for x in rev[:5]))
                    for d in r.get("diagnostics", []):
                        msgs.append(f"  ! {d}")
                except Exception as e:
                    msgs.append(f"{name}: FAILED - {e}")

    # Cross-check against the Material Code master (ERP operates on the master's notation)
    fixed, unknown, err = normalise_to_master(results, settings)
    if err:
        msgs.append(f"(material master check skipped: {err})")
    if fixed:
        msgs.append("  = normalised to master: " + ", ".join(fixed[:5]))
    if unknown:
        msgs.append("  ? not in Material Codes: " + ", ".join(unknown[:5]))
    return expand_orders(results), msgs, ok


def run_extractor_multi(paths, settings, mail=None, fmt=None, force=True):
    """Read the attachments ONCE, then write every format that was asked for.

    Returns: (success count, message, [(format, path), ...])

    `fmt` may be a single value or a LIST (2026-10-27): the two versions are no
    longer exclusive, so "full + simple" is one reading and two files. The
    reading is what costs money, and it is shared - only `build_upload()` runs
    per format. Each entry carries its own format, because a version that FAILS
    must not shift the label of the one after it.

    force: pass False when the same documents were just read for the preview -
    the reader then reuses its cache and the API is not billed twice.
    """
    mail = mail or {}
    results, msgs, ok = read_orders(paths, settings, force=force)
    if not results:
        return ok, (" | ".join(msgs) or
                    "Nothing could be read from this email's attachments."), []

    if fmt in (None, ""):
        fmt = settings.get("erp_format", erp_excel.FORMAT_FULL)
    fmts = erp_excel.output_formats(fmt)

    out = []
    for one in fmts:
        try:
            xlsx, n, no_qty, no_cost, dropped, fixes = erp_excel.build_upload(
                results, mail, settings, one)
        except Exception as e:
            # One version failing must not throw away the other: the lines are
            # the same either way, and a template problem is worth reporting
            # beside a file that DID get written.
            msgs.append(f"Order Upload export ({one}) failed: {e}")
            continue
        out.append((one, xlsx))
        msgs.append(f"Order Upload file ({one}): {n} line(s)"
                    + (" - 4 columns" if one == erp_excel.FORMAT_SIMPLE else ""))
        if fixes:
            msgs.append("  = corrected: " + "; ".join(fixes[:4]))
        if dropped:
            msgs.append("  (removed duplicate model(s) quoted inside "
                        "item descriptions: " + ", ".join(dropped) + ")")
        if no_qty:
            msgs.append("! Quantity missing for: " + ", ".join(no_qty))
        if no_cost:
            msgs.append("! Cost missing for: " + ", ".join(no_cost) +
                        " — upload this customer's price list in "
                        "Material Codes")

    return ok, " | ".join(msgs), out


def run_extractor(paths, settings, mail=None, fmt=None, force=True):
    """The single-file form of `run_extractor_multi()`.

    Returns: (success count, message, path of the file, or '')

    Kept because most callers want one file and a string; it is exactly the
    first of the requested formats. Everything that must write ALL of them
    calls `run_extractor_multi()`.
    """
    ok, msg, files = run_extractor_multi(paths, settings, mail, fmt, force)
    return ok, msg, (files[0][1] if files else "")


