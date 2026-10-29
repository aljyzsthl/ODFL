# OrderFlow — Setup

Four steps. Everything is done from a normal command prompt; no installer
script is needed.

## 1. Install Python

Go to <https://www.python.org/downloads/windows/> and download **Python
3.14.7 — Windows installer (64-bit)**.

When the installer opens, **tick "Add python.exe to PATH" on the first
screen** before clicking Install Now. It is off by default, and skipping it
is the most common reason the later steps fail.

> **If you have ever seen** *"Python was not found; run without arguments to
> install from the Microsoft Store"*: Windows has a placeholder shadowing the
> real Python. Turn it off under
> `Settings > Apps > Advanced app settings > App execution aliases` — switch
> **off** both `python.exe` and `python3.exe`. Then close every command
> prompt and open a new one.

## 2. Unzip OrderFlow

Extract the OrderFlow zip anywhere you like, for example `D:\OrderFlow`.

## 3. Install the packages

Open a command prompt, change to the folder you just extracted, and run:

```
set HTTP_PROXY=
set HTTPS_PROXY=
py -m pip install -r requirements.txt
```

The first two lines clear the corporate proxy, which otherwise blocks the
download. This installs **two** packages — `pywin32` (Outlook and Excel) and
`openpyxl` (spreadsheets) — and takes under a minute. PO reading is done by
the Claude API over HTTPS with the standard library, so there is no PDF or OCR
package to install any more.

**Then confirm it worked — do not skip this.** The check below prints the
address a PO will be sent to, the model, the number of material codes on file
and whether a token is stored, because a missing token otherwise fails
silently: the PO simply comes back with zero codes and nothing says why.

```
py -c "import sys, win32com.client, openpyxl; print('ALL OK -', sys.executable)"
cd CodeExtract && py -c "import claude_engine as c; s = c.status_summary(); print(s)" && cd ..
```

You should see `ALL OK` followed by a path, then `endpoint` (the SEA address
ending in `/v1/messages`), `model`, `reference_codes`, and `api_key_set: True`.
Anything else — especially `ModuleNotFoundError` — means a package did not
install; run step 3 again and read the output to the end.

**Then paste the token.** Start the app, go to Settings, find **PO reading**,
paste the auth token you were assigned and press **Save**, then press
**Test PO reading**. You want a green *"The endpoint answered"* with a round
trip in milliseconds. A red result names the fix — a rejected key says so, an
unreachable address says so. Nothing else proves the setup works.

If the path printed is **not** the Python you installed in step 1, `py` and
`pip` are using different interpreters. Tell Jacob before going further; the
app may appear to work and then fail on certain POs.

## 4. Run it

```
py src\orderflow.py
```

The dashboard opens in a window. Leave the command prompt open while you use
it — closing it stops the app.

---

## Also required: DRM access

Purchase orders arrive DRM-protected, and OrderFlow cannot read them until
your PC is authorised.

Raise a request through **IT4U** using the exact wording
**"NASCA Decrypt with Python"**. The TX Security team is familiar with this
request and approves it without follow-up questions when that phrase is
used. Access is granted **per PC, not per person** — request it on the
machine you will actually use.

Until it is approved, OrderFlow still works on POs that are not
DRM-protected.

---

## If something fails

| What you see | What it means |
|---|---|
| `No module named 'win32com'` or `'pythoncom'` | Step 3 has not completed. Run it again. |
| **Every PO extracts 0 codes** | No token is stored. Paste it on the Settings screen (PO reading) or set `$ANTHROPIC_AUTH_TOKEN`, then press **Save** and **Test PO reading**. Without one no document can be read, and no error names the cause. |
| **Test PO reading says the endpoint rejected the key** | The token is wrong or expired. It is sent as `Authorization: Bearer …` — a public Anthropic `sk-ant-…` key will not work here, because this is the SEA endpoint. Ask for a new one. |
| **Test PO reading says the address did not answer** | This PC cannot reach `seadev-claude.sec.samsung.net:8081`. Check VPN / internal network. The token is fine. |
| **Every PO says "HTTP 404"** | The endpoint box holds the wrong address, e.g. the full `/v1/messages` URL of a different service. Leave it **blank** to use the shipped default. |
| A PO extracts 0 codes and it is **not** a scan | Check `Master Data > Material Codes` is populated — the console prints `[codes] engine code list rebuilt from the master: N codes` at startup. If N is 0, the code list is empty and nothing can match. |
| `Python was not found…` | See the note in step 1. |
| pip cannot reach the network | The proxy is still blocking. Tell Jacob — there is an offline package bundle for this case. |
| A PO PDF will not open | Usually the DRM approval above is still pending. |

Anything else, send the console output — the messages it prints are enough
to identify almost every problem.
