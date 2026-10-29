@echo off
rem ============================================================
rem  One-time setup for a PC that will run OrderFlow.
rem
rem  Installs the Python packages listed in requirements.txt -
rem  that file is the single list; this script does not repeat
rem  it, so the two can never drift apart.
rem
rem  Does NOT install Python itself; see the message below if
rem  Python is missing.
rem ============================================================
cd /d %~dp0
set HTTP_PROXY=
set HTTPS_PROXY=

echo ============================================
echo  OrderFlow - environment setup
echo ============================================
echo.

rem Find a Python that actually works.
rem
rem "where python" is not good enough. Windows ships a 0-byte stub at
rem %LOCALAPPDATA%\Microsoft\WindowsApps\python.exe that answers to the
rem name "python", prints "Python was not found; run without arguments to
rem install from the Microsoft Store" and exits. It looks installed and is
rem not. So each candidate has to prove itself by printing a token we check
rem for - a stub cannot fake that.
rem
rem "py" (the Python launcher, installed by the python.org installer) is
rem tried first because the Store stub never shadows it.
set PYEXE=
for %%p in (py python python3) do (
    if not defined PYEXE (
        %%p -c "print('PYOK')" 2>nul | findstr /b /c:"PYOK" >nul && set PYEXE=%%p
    )
)

if not defined PYEXE goto :nopython

for /f "tokens=*" %%v in ('%PYEXE% -c "import sys;print(sys.version.split()[0])"') do set PYVER=%%v
for /f "tokens=*" %%v in ('%PYEXE% -c "import sys;print(sys.executable)"') do set PYPATH=%%v
echo [OK] Python %PYVER%
echo      %PYPATH%
echo      (launched as "%PYEXE%")

for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    if %%a LSS 3 goto :oldpython
    if %%a EQU 3 if %%b LSS 9 goto :oldpython
)
echo.

if not exist requirements.txt (
    echo [ERROR] requirements.txt is missing from this folder.
    echo         Run this from the OrderFlow folder, not from a copy of
    echo         the .bat on its own.
    pause
    exit /b 1
)

echo [1/3] Upgrading pip...
%PYEXE% -m pip install --upgrade pip
echo.

echo [2/3] Installing packages from requirements.txt...
%PYEXE% -m pip install -r requirements.txt
if errorlevel 1 goto :err
echo.

echo [3/3] Registering pywin32 (Outlook / Excel automation)...
rem Usually unnecessary - OrderFlow uses late-bound COM - so a failure here
rem is not fatal and must not stop the setup.
%PYEXE% -m pywin32_postinstall -install >nul 2>nul
echo.

echo Verifying...
rem [1] The packages OrderFlow cannot start without.
%PYEXE% -c "import sys, win32com.client, openpyxl; print('  [OK] core packages load')"
if errorlevel 1 goto :verifyfail

rem [2] The EXTRACTOR is asked, not a hand-written import list: it reports
rem the model it will use and whether a key is stored. Without a key every PO
rem comes back with zero codes and nothing explains why - the file just looks
rem empty, which is exactly the failure this step is here to prevent.
pushd CodeExtract
%PYEXE% -c "import sys; sys.path.insert(0, '.'); import claude_engine as c; s = c.status_summary(); print('  [OK] PO endpoint:', s['endpoint']); print('  [OK] extraction model:', s['model']); print('  [OK] material codes on file:', s['reference_codes']); print('  [WARN] NO AUTH TOKEN - no PO can be read until one is pasted on the Settings screen (PO reading)') if not s['api_key_set'] else None"
set VERC=%errorlevel%
popd
if not "%VERC%"=="0" goto :verifyfail

echo.
echo ============================================
echo  Setup complete.
echo ============================================
echo  Next steps:
echo   1. Request "NASCA Decrypt with Python" via IT4U for THIS PC
echo      (needed to read DRM-protected PO attachments).
echo   2. Run run_dashboard.bat to start OrderFlow.
echo ============================================
pause
exit /b 0

:verifyfail
echo.
echo [WARN] Verification failed - read the message above.
echo.
echo   "No module named ..."      that package did not install. Run this
echo                              file again and read the output to the end.
echo   "NO AUTH TOKEN"             no auth token is stored, so no PO can be
echo                              read. Paste the assigned token on the
echo                              Settings screen (PO reading box), or set
echo                              $ANTHROPIC_AUTH_TOKEN. It is sent as
echo                              "Authorization: Bearer <token>".
echo.
echo   If the interpreter path printed above is not the Python you
echo   installed, "py" and "pip" are using different interpreters - report
echo   that before using the app.
echo.
echo   Re-running this file is safe; it only installs what is missing.
pause
exit /b 1

:nopython
echo [ERROR] No working Python on this PC.
echo.
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" (
    echo   Windows has a placeholder that pretends to be Python:
    echo     %LOCALAPPDATA%\Microsoft\WindowsApps\python.exe
    echo   It is not an interpreter - it only advertises the Microsoft Store.
    echo.
)
echo   Install real Python 3.11 or later from:
echo     https://www.python.org/downloads/windows/
echo.
echo   TICK "Add python.exe to PATH" on the installer's first screen.
echo   It is off by default and is the usual reason setup fails.
echo.
echo   If Python IS installed, Windows is shadowing it. Turn the
echo   placeholder off:
echo     Settings ^> Apps ^> Advanced app settings ^> App execution aliases
echo     switch OFF both "python.exe" and "python3.exe"
echo.
echo   Then close this window, open a NEW command prompt, and run this
echo   file again.
echo.
pause
exit /b 1

:oldpython
echo.
echo [ERROR] Python %PYVER% is too old. Please install 3.11 or later:
echo         https://www.python.org/downloads/windows/
echo.
pause
exit /b 1

:err
echo.
echo [ERROR] Package installation failed - read the message above.
echo         If it looks like a network or proxy error, ask IT for access
echo         to pypi.org, or ask Jacob for the offline package bundle.
pause
exit /b 1
