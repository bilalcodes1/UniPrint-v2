@echo off
REM UniPrint — Windows Service Uninstaller
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Please run as Administrator.
    pause & exit /b 1
)
nssm stop   UniPrint 2>nul
nssm remove UniPrint confirm 2>nul
echo [OK] UniPrint service removed.
pause
