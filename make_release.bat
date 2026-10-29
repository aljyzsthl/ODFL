@echo off
rem ============================================================
rem  make_release.bat - build the zip you share with colleagues
rem
rem  YOUR WORKING FOLDER IS NEVER MODIFIED. Nothing here is
rem  deleted. The script makes a separate copy next to this
rem  folder, and the things that must not leave your PC are
rem  simply not copied into it:
rem
rem    data\attachments        real customer PO files
rem    data\po_mail.db         collected mail - each user pulls their own
rem    data\erp_upload         generated ERP upload files
rem    tests\test_mails        saved .eml / .msg mail
rem    CodeExtract\data_cache  extraction cache, rebuilt on first run
rem    CodeExtract\data_output past extraction output
rem    build, __pycache__, logs
rem
rem    config\settings.json     THIS MACHINE'S configuration - the PO-reading
rem      endpoint, the token, the mailbox, the port. Not copied on purpose:
rem      shipping it would both leak the sender's credential and overwrite the
rem      recipient's copy on every update, which is why a fresh zip used to mean
rem      typing the endpoint and the token again. config\settings.default.json
rem      goes instead; the app merges it under whatever settings.json exists.
rem
rem  KEPT on purpose, because the app needs them to work:
rem    config\ship_to_master.json  the PAIR table - the ERP Ship To Locations
rem      export, one row per (Sold-To, Ship-To) pair. Without it the ERP columns
rem      have nothing to be filled from.
rem    config\domain_master.json   the DOMAIN table - the customer identity.
rem      Without it every mail comes back unclassified and the Sold-To / Ship-To
rem      picker has nothing to offer. Both files together are the customer data.
rem    config\material_master.json, config\price_lists, config\erp_template.XLSX
rem    Upload_Template_MaterialCodes.xlsx, Upload_Template_ShipToLocations.xlsx,
rem      Upload_Template_Domains.xlsx
rem    CodeExtract\data_upload (the PDFs engine_baseline.py measures)
rem
rem  tools\ is NOT copied: those are one-off dev scripts (the domain-table
rem  migration, the template generator, the two-table HTTP check). They are
rem  documented in HANDOVER's folder layout and live in the working copy only.
rem
rem  Then it stamps a build id and zips the copy. Upload the zip.
rem ============================================================
setlocal
cd /d %~dp0
set SRC=%CD%

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set STAMP=%%i
set REL=..\OrderFlow_src_%STAMP%
set ZIP=..\OrderFlow_src_%STAMP%.zip

echo ============================================
echo  OrderFlow - build a release copy
echo ============================================
echo   from : %CD%
echo   to   : %REL%
echo   zip  : %ZIP%
echo.
echo   Your working folder is NOT touched.
echo.

echo [1/4] Copying the source (collected data is skipped)...
rem /XD and /XF match by name at any depth. robocopy returns 0-7 for
rem success, 8 and above for a real failure.
robocopy . "%REL%" /E /NFL /NDL /NJH /NJS /NP ^
  /XD attachments erp_upload export exports tmp logs build .git .venv ^
      __pycache__ tools test_mails data_cache data_output pydeps ^
      _legacy ^
  /XF *.pyc *.pyo po_mail.db po_mail.db-wal po_mail.db-shm app.log ^
      settings.json
if errorlevel 8 goto :err

echo [2/4] Recreating the empty working folders...
for %%d in ("%REL%\data\attachments" "%REL%\data\tmp" "%REL%\tests\test_mails" ^
            "%REL%\CodeExtract\data_cache" "%REL%\CodeExtract\data_output") do (
  if not exist %%d mkdir %%d
)
> "%REL%\tests\test_mails\README.txt" echo Put .eml / .msg test files here (Mail Source = Test folder).

rem A PO file left loose in the project root - the usual residue of a
rem one-off diagnosis - would otherwise ship inside the zip. The reference
rem PDFs under CodeExtract\data_upload are kept on purpose and are not
rem touched here.
for %%x in (pdf xlsx xlsm xls msg eml) do (
  for %%f in ("%REL%\*.%%x") do (
    echo       dropped loose file from the root: %%~nxf
    del /q "%%f"
  )
)

echo [3/4] Cleaning settings, obsolete scripts, stamping the build id...
rem prepare_handover.bat DELETES what it cleans, so the next few lines
rem prove we are standing in the copy before it is called. If the copy
rem is missing, or if pushd silently failed and left us in the working
rem folder, the script stops here instead of deleting your data.
if not exist "%REL%\prepare_handover.bat" goto :nocopy
pushd "%REL%"
if errorlevel 1 goto :nocopy
if /i "%CD%"=="%SRC%" goto :nocopy
call prepare_handover.bat /y
popd

echo [4/4] Zipping...
if exist "%ZIP%" del /q "%ZIP%"
powershell -NoProfile -Command ^
  "Compress-Archive -Path '%REL%\*' -DestinationPath '%ZIP%' -Force"
if errorlevel 1 goto :err

echo.
echo ============================================
echo  Done.
echo ============================================
for %%f in ("%ZIP%") do echo   zip      : %%~ff  (%%~zf bytes)
echo   folder   : %REL%
echo.
echo   Upload the .zip. Open the folder first if you want to
echo   check what is in it - the collected mail, attachments and
echo   ERP upload files should all be absent.
echo.
pause
exit /b 0

:nocopy
echo.
echo [STOPPED] Could not switch into the release copy:
echo             %REL%
echo           The cleanup step was NOT run, so nothing was deleted.
echo           Your working folder is untouched.
pause
exit /b 1

:err
echo.
echo [ERROR] Release build failed. Check the message above.
echo         Your working folder was not modified.
pause
exit /b 1
