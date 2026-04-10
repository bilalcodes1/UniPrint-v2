@echo off
REM ============================================================
REM  UniPrint — Windows Service Installer (NSSM)
REM  Requires: NSSM (Non-Sucking Service Manager) in PATH
REM  Download: https://nssm.cc/download
REM  Run as Administrator!
REM ============================================================

setlocal EnableDelayedExpansion

set "SERVICE_NAME=UniPrint"
set "SCRIPT_DIR=%~dp0"
set "BACKEND_DIR=%SCRIPT_DIR%.."
set "VENV_PYTHON=%BACKEND_DIR%\venv\Scripts\python.exe"
set "RUN_SCRIPT=%BACKEND_DIR%\run.py"
set "LOG_DIR=%BACKEND_DIR%\logs"

echo.
echo === UniPrint Windows Service Installer ===
echo.

REM Check admin rights
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Please run this script as Administrator.
    pause & exit /b 1
)

REM Check NSSM
where nssm >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] NSSM not found in PATH.
    echo         Download from: https://nssm.cc/download
    echo         Place nssm.exe somewhere in PATH or in this folder.
    pause & exit /b 1
)

REM Check Python venv
if not exist "%VENV_PYTHON%" (
    echo [ERROR] Python venv not found: %VENV_PYTHON%
    echo         Run: python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    pause & exit /b 1
)

mkdir "%LOG_DIR%" 2>nul

REM Remove existing service if present
nssm stop  %SERVICE_NAME% 2>nul
nssm remove %SERVICE_NAME% confirm 2>nul

REM Install service
nssm install %SERVICE_NAME% "%VENV_PYTHON%" "%RUN_SCRIPT%"
nssm set %SERVICE_NAME% AppDirectory     "%BACKEND_DIR%"
nssm set %SERVICE_NAME% DisplayName      "UniPrint Backend"
nssm set %SERVICE_NAME% Description      "UniPrint library print service — Flask backend"
nssm set %SERVICE_NAME% Start            SERVICE_AUTO_START
nssm set %SERVICE_NAME% AppStdout        "%LOG_DIR%\uniprint.log"
nssm set %SERVICE_NAME% AppStderr        "%LOG_DIR%\uniprint-error.log"
nssm set %SERVICE_NAME% AppRotateFiles   1
nssm set %SERVICE_NAME% AppRotateBytes   5242880

REM Start
nssm start %SERVICE_NAME%

echo.
echo [OK] UniPrint service installed and started!
echo      Logs : %LOG_DIR%\
echo      Stop : nssm stop UniPrint
echo      Start: nssm start UniPrint
echo      URL  : http://localhost:5001
echo.
pause
