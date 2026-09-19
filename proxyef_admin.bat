@echo off
REM ============================================================
REM  ProxyEF - Administrator launcher for Windows
REM  Relaunches itself with admin rights and then runs proxyef.py
REM ============================================================

setlocal

REM --- Are we already admin? ---
net session >nul 2>&1
if %errorlevel% NEQ 0 (
    echo Requesting administrator privileges...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

REM --- We are admin now ---
cd /d "%~dp0"

echo ============================================================
echo   ProxyEF - Proxy Speed ^& Availability Tester
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

if not exist "%~dp0proxyef.py" (
    echo [ERROR] proxyef.py was not found next to this .bat file.
    echo Put proxyef_admin.bat and proxyef.py in the same folder.
    echo.
    pause
    exit /b 1
)

python "%~dp0proxyef.py"

if %errorlevel% NEQ 0 (
    echo.
    echo [ERROR] ProxyEF exited with code %errorlevel%.
    pause
)

endlocal