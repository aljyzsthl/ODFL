@echo off
rem ============================================================
rem  Prepare the source tree for hand-over to another developer
rem
rem  Removes: build output, caches, collected mail data, logs,
rem           obsolete / one-off scripts, old master-list versions,
rem           past extraction outputs, personal settings,
rem           .workbuddy work logs / screenshots / backups.
rem  Keeps:   all runtime code, config, the reference PDFs,
rem           selftest tools, docs.
rem
rem  DESTRUCTIVE - run this on a COPY of the folder, never on your
rem  working copy. make_release.bat makes that copy for you and
rem  then calls this script with /y, which is the normal way in.
rem ============================================================
cd /d %~dp0

if /i "%~1"=="/y" goto :go
echo.
echo  This DELETES build output, collected emails, attachments,
echo  logs and obsolete scripts in:
echo    %CD%
echo.
echo  If that is your working folder, answer N and run
echo  make_release.bat instead.
echo.
set /p ok="Continue? (Y/N): "
if /i not "%ok%"=="Y" exit /b 0
:go

echo.
echo [1/6] Build output and Python caches...
if exist build rd /s /q build
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
del /s /q *.pyc >nul 2>&1

echo [2/6] Collected email data, attachments, generated files, logs...
if exist data\po_mail.db      del /q data\po_mail.db
if exist data\po_mail.db-wal  del /q data\po_mail.db-wal
if exist data\po_mail.db-shm  del /q data\po_mail.db-shm
if exist data\attachments     rd /s /q data\attachments
if exist data\erp_upload      rd /s /q data\erp_upload
if exist data\export          rd /s /q data\export
rem data\exports (plural) is where the CSV export used to go before it was
rem pointed at the same folder as the workbook export; clean it if an older
rem working copy still has one.
if exist data\exports         rd /s /q data\exports
if exist data\tmp             rd /s /q data\tmp
if exist logs                 rd /s /q logs
if exist tests\test_mails     rd /s /q tests\test_mails
mkdir data\attachments
mkdir data\tmp
mkdir tests\test_mails
echo Put .eml / .msg test files here (Mail Source = Test folder).> "tests\test_mails\README.txt"

echo [3/6] Obsolete dashboard modules and one-off scripts...
rem The dashboard code lives in src\orderflow.py + the six of_*.py modules
rem (split 2026-10-10), PO reading in CodeExtract\claude_engine.py + code_rules.py
rem (2026-10-21), so there is no per-module cleanup left to do here - the
rem one-off inspectors are already gone from the tree.

rem The build id a tester quotes ("which build are you on?") is DERIVED at
rem runtime from the sources it names - see src\version.py. Do NOT write a
rem literal over that file: a stamped date goes stale the moment the code
rem under it changes, which is exactly the bug this replaced (the tree shipped
rem "src-20260925-1123" a month after that date). What ships is the derivation
rem itself, so the copy reports its own version on the first run.
echo       build id: derived from the sources (src\version.py)

echo [3b/6] .workbuddy: drop the scratch state...
rem Only port_probe.py ships (README test list, HANDOVER 7), so what must not
rem travel with it:
rem   memory\  work logs written while developing
rem   backup\  a copy of the DRM-wrapped ERP form (an internal document)
rem   shots\, scan\  screenshots and rendered pages - regenerable, bulky
rem   pydeps\  third-party wheels installed locally to run the test suites
rem            (see docs\COLUMN_ALIGNMENT.md "how to run the probes on a
rem            machine without the packages"); never ship someone's venv
if exist .workbuddy\memory       rd /s /q .workbuddy\memory
if exist .workbuddy\backup       rd /s /q .workbuddy\backup
if exist .workbuddy\shots        rd /s /q .workbuddy\shots
if exist .workbuddy\scan         rd /s /q .workbuddy\scan
if exist .workbuddy\pydeps       rd /s /q .workbuddy\pydeps
if exist .workbuddy\__pycache__  rd /s /q .workbuddy\__pycache__
del /q .workbuddy\*.png >nul 2>&1

echo [4/6] CodeExtract: one-off investigation scripts...
rem trace_wrapped.* and check_outlook.* were removed from CodeExtract entirely
rem (source cleanup) - nothing left to delete here at release time.
rem None of these are imported by the dashboard or by the engine.
for %%f in (make_briefing_ppt.py make_briefing_ppt.bat) do (
  if exist "CodeExtract\%%f" del /q "CodeExtract\%%f"
)

echo [5/6] CodeExtract: past outputs and caches...
if exist CodeExtract\data_output rd /s /q CodeExtract\data_output
if exist CodeExtract\data_cache  rd /s /q CodeExtract\data_cache
mkdir CodeExtract\data_output
mkdir CodeExtract\data_cache
if exist CodeExtract\app.log del /q CodeExtract\app.log

echo [6/6] Personal settings -> neutral defaults...
powershell -NoProfile -Command ^
  "$p='config\settings.json';" ^
  "if (-not (Test-Path $p)) { echo '      (no settings.json here - nothing to blank)'; exit 0 };" ^
  "$j = Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json;" ^
  "$j.outlook.mailbox_name = '';" ^
  "$j.quick_folder = '';" ^
  "if ($j.PSObject.Properties.Name -contains 'claude') { $j.claude.api_key = ''; $j.claude.base_url = '' };" ^
  "[IO.File]::WriteAllText($p, ($j | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding $false))"
rem The auth token is a CREDENTIAL, so it never travels with a handover copy -
rem the recipient puts their own in on the Settings screen (PO reading). The
rem endpoint is blanked too, so a copy cannot keep pointing at a server only the
rem sender can reach; blank means "use the address in claude_config.json".
rem config\ship_to_master.json is KEPT, and nothing else is: it is the whole
rem customer master (the ERP Ship To Locations export, one row per
rem (Sold-To, Ship-To) pair, column C the domain). Empty it and every stored
rem mail loses its customer until a master is uploaded again.
rem config\customer_master.csv and config\erp_accounts.json were DELETED in
rem the 2026-10 refactor - do not look for them.

echo.
echo  Done. Kept on purpose:
echo    CodeExtract\data_upload\*.pdf         reference POs to try extraction on
echo    CodeExtract\_legacy\                  the retired local engine, kept for reference
echo    config\ship_to_master.json, config\material_master.json
echo    Upload_Template_MaterialCodes.xlsx, Upload_Template_ShipToLocations.xlsx
echo.
echo  Hand over the whole folder together with docs\HANDOVER.md.
echo.
if /i "%~1"=="/y" exit /b 0
pause
