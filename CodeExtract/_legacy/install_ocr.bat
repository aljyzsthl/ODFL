@echo off
cd /d "%~dp0"
title OCR Engine Installer

echo.
echo  Offline / OCR Installation - Samsung Material Code Extractor
echo  ------------------------------------------------------------
echo.
echo  This installs RapidOCR - no external program needed.
echo  If the corporate network blocks PyPI, connect to a mobile
echo  hotspot before running this.
echo.

python -c "import rapidocr_onnxruntime" >nul 2>&1
if %errorlevel% equ 0 goto already

echo [1/2] Installing RapidOCR (about 30MB, may take a few minutes)...
set no_proxy=*
set NO_PROXY=*
pip install rapidocr-onnxruntime numpy --timeout 600 --disable-pip-version-check
echo.

echo [2/2] Verifying...
python -c "import rapidocr_onnxruntime; print('  OCR engine ready.')" 2>nul
if %errorlevel% neq 0 goto failed

echo.
echo [OK] OCR installed. Scanned PDFs will now be processed automatically.
echo      Restart the application to activate.
pause
exit /b 0

:already
echo [OK] OCR engine is already installed.
python -c "import rapidocr_onnxruntime; print('  rapidocr_onnxruntime OK')"
pause
exit /b 0

:failed
echo.
echo [ERROR] Installation failed.
echo.
echo  Try manually with a hotspot connection:
echo    pip install rapidocr-onnxruntime numpy --timeout 600
echo.
pause
exit /b 1
