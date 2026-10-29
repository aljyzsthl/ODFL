@echo off
rem ============================================================
rem  devtools.bat - one entry point for every CodeExtract tool
rem
rem    devtools.bat                 regression tests (default)
rem    devtools.bat selftest        the same, spelled out
rem    devtools.bat template        zone-template editor (GUI)
rem ============================================================
cd /d "%~dp0"
title Material Code Extractor - Dev Tools

rem Remove stale bytecode so an edited module cannot be shadowed by a .pyc.
rem PYTHONDONTWRITEBYTECODE stops new .pyc files being created at all, which
rem also prevents mixing bytecode from two Python installations.
if exist "__pycache__" rd /s /q "__pycache__" 2>nul
set PYTHONDONTWRITEBYTECODE=1

python devtools.py %*
echo.
pause
