@echo off
cd /d %~dp0
set HTTP_PROXY=
set HTTPS_PROXY=

echo ============================================
echo  OrderFlow  (developer run - not the release)
echo ============================================

rem Same Python detection as setup_python_env.bat. Windows ships a 0-byte
rem stub named python.exe that only advertises the Microsoft Store, so a
rem candidate has to prove itself by printing a token we check for. "py"
rem is tried first because the stub never shadows it.
set PYEXE=
for %%p in (py python python3) do (
    if not defined PYEXE (
        %%p -c "print('PYOK')" 2>nul | findstr /b /c:"PYOK" >nul && set PYEXE=%%p
    )
)

if not defined PYEXE (
    echo.
    echo [ERROR] No working Python on this PC.
    echo         Run setup_python_env.bat first - it explains how to fix this.
    echo.
    pause
    exit /b 1
)

%PYEXE% src\orderflow.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Check the message above.
    pause
)
