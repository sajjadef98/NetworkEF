@echo off
REM ============================================================
REM  VPNEF - Administrator launcher for Windows
REM  TUN mode requires admin rights. This .bat relaunches itself
REM  with elevation and then runs vpnef.py.
REM ============================================================

setlocal

net session >nul 2>&1
if %errorlevel% NEQ 0 (
    echo Requesting administrator privileges...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ============================================================
echo   VPNEF - VPN Config Tester ^& Tunnel
echo   Running with administrator privileges.
echo ============================================================
echo.

where python >nul 2>&1
if %errorlevel% NEQ 0 (
    echo [ERROR] Python was not found in PATH.
    echo Install Python 3.9+ from https://www.python.org/downloads/
    echo and check "Add Python to PATH" during setup.
    echo.
    pause
    exit /b 1
)

if not exist "%~dp0vpnef.py" (
    echo [ERROR] vpnef.py was not found next to this .bat file.
    echo.
    pause
    exit /b 1
)

python "%~dp0vpnef.py"

if %errorlevel% NEQ 0 (
    echo.
    echo [ERROR] VPNEF exited with code %errorlevel%.
    pause
)

endlocal