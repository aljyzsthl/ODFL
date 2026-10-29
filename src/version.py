# -*- coding: utf-8 -*-
"""The build stamp the sidebar shows (`SRC-...`).

DERIVED, not typed. It used to be a literal written by `prepare_handover.bat`
at release time, so every working copy carried the date of the LAST release:
this one said `src-20260925-1123` while the code was a month newer. The stamp
is exactly what a support call asks for ("which build are you on?"), so it must
not be able to drift from the code it names.

The id is `src-<newest mtime>-<6 hex of the sources>`:

  * the timestamp is when the newest source file was written - readable, and it
    answers "how old is this copy";
  * the digest is over the CONTENT of every source file - so two builds in the
    same minute still differ, and touching a file without changing it does not
    invent a new version.

Cost: one stat per source file per call. The digest is computed only when that
stat signature changes (`_CACHE`), so a page render costs a handful of stats
and nothing more.

`prepare_handover.bat` no longer writes this file. If it ever does again, it
overwrites the derivation with a literal and the stamp goes stale again - which
is the failure this file exists to prevent.
"""
import hashlib
import os
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


def _sources():
    """Every .py that decides what the program does, in a stable order."""
    out = []
    for rel in ("src", "CodeExtract"):
        d = os.path.join(_ROOT, rel)
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            if not n.endswith(".py"):
                continue
            p = os.path.join(d, n)
            if os.path.isfile(p):
                out.append(p)
    return out


_CACHE = {"sig": None, "id": "dev"}


def build_id():
    """`src-YYYYMMDD-HHMM-abcdef`, recomputed when any source changes."""
    files = _sources()
    if not files:
        return "dev"
    try:
        sig = tuple((p, os.path.getsize(p), int(os.path.getmtime(p)))
                    for p in files)
    except OSError:
        return _CACHE["id"]
    if sig == _CACHE["sig"]:
        return _CACHE["id"]

    digest = hashlib.sha1()
    newest = 0.0
    for p in files:
        try:
            with open(p, "rb") as f:
                digest.update(f.read())
            newest = max(newest, os.path.getmtime(p))
        except OSError:
            continue
    stamp = time.strftime("%Y%m%d-%H%M",
                          time.localtime(newest or time.time()))
    _CACHE["sig"] = sig
    _CACHE["id"] = "src-%s-%s" % (stamp, digest.hexdigest()[:6])
    return _CACHE["id"]


# Kept as a plain name because `report.render_page()` and anything else that
# wants "the version" reads it this way. It is computed on import AND cheap
# enough to recompute per request - see `build_id()`.
BUILD = build_id()
