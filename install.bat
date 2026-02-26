@echo off
:: ╔══════════════════════════════════════════════════╗
:: ║      ZENCODE v10 — One-Shot Installer (Windows)   ║
:: ╚══════════════════════════════════════════════════╝
setlocal enabledelayedexpansion
title ZENCODE v10 Installer

echo.
echo   ███████╗███████╗███╗   ██╗ ██████╗ ██████╗ ██████╗ ███████╗
echo   ╚══███╔╝██╔════╝████╗  ██║██╔════╝██╔═══██╗██╔══██╗██╔════╝
echo     ███╔╝ █████╗  ██╔██╗ ██║██║     ██║   ██║██║  ██║█████╗
echo    ███╔╝  ██╔══╝  ██║╚██╗██║██║     ██║   ██║██║  ██║██╔══╝
echo   ███████╗███████╗██║ ╚████║╚██████╗╚██████╔╝██████╔╝███████╗
echo   ╚══════╝╚══════╝╚═╝  ╚═══╝ ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝
echo.
echo   ZENCODE v10 -- Autonomous AI Code Shell
echo   Installing...
echo.

:: Check Python
echo   [*] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo   [X] Python not found. Install from python.org
        pause
        exit /b 1
    ) else (
        set PYTHON=py
    )
) else (
    set PYTHON=python
)

for /f "tokens=*" %%i in ('%PYTHON% --version 2^>^&1') do echo   [OK] %%i

:: Install Python deps
echo   [*] Installing Python dependencies...
%PYTHON% -m pip install --quiet --upgrade mistralai rich click prompt_toolkit
if errorlevel 1 (
    echo   [!] pip install had issues, trying with --user...
    %PYTHON% -m pip install --quiet --upgrade --user mistralai rich click prompt_toolkit
)
echo   [OK] Dependencies installed

:: Install zencode package
echo   [*] Installing zencode...
cd /d "%~dp0"
%PYTHON% -m pip install --quiet -e .
if errorlevel 1 (
    %PYTHON% -m pip install --quiet --user -e .
)
echo   [OK] Package installed

:: Create config dir
if not exist "%USERPROFILE%\.zencode" mkdir "%USERPROFILE%\.zencode"
echo   [OK] Config dir: %USERPROFILE%\.zencode

:: API Key
echo.
echo   ================================================
echo   Setup Mistral API Key
echo   Get one free at: console.mistral.ai
echo   ================================================
echo.
set /p APIKEY="  Enter Mistral API key (Enter to skip): "
if not "!APIKEY!"=="" (
    %PYTHON% -m zencode --setkey "!APIKEY!"
    echo   [OK] API key saved
) else (
    echo   [!] Skipped -- run "zencode --setkey YOUR_KEY" later
)

echo.
echo   ================================================
echo   [OK] ZENCODE v10 INSTALLED
echo   ================================================
echo.
echo   Usage:
echo     cd C:\myproject
echo     zencode
echo.
echo   If 'zencode' is not found, add Python Scripts to PATH:
for /f "tokens=*" %%i in ('%PYTHON% -c "import sys; print(sys.prefix + chr(92) + chr(83) + chr(99) + chr(114) + chr(105) + chr(112) + chr(116) + chr(115))"') do echo     %%i
echo.
pause
