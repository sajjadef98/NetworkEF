@echo off
REM ============================================================
REM  DNSEF - Administrator launcher for Windows
REM  This .bat relaunches itself with admin rights and then
REM  runs dnsef.py using the system Python.
REM ============================================================

setlocal

REM --- Check whether we are already running as admin ---
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
echo   DNSEF - DNS Speed ^& Availability Tester
echo   Running with administrator privileges.
echo ============================================================
echo.

REM --- Locate python ---
where python >nul 2>&1
if %errorlevel% NEQ 0 (
    echo [ERROR] Python was not found in PATH.
    echo Install Python 3.9+ from https://www.python.org/downloads/
    echo and make sure "Add Python to PATH" is checked during setup.
    echo.
    pause
    exit /b 1
)

REM --- Verify dnsef.py exists ---
if not exist "%~dp0dnsef.py" (
    echo [ERROR] dnsef.py was not found in this folder:
    echo    %~dp0
    echo Put dnsef_admin.bat next to dnsef.py.
    echo.
    pause
    exit /b 1
)

REM --- Run the app ---
python "%~dp0dnsef.py"

if %errorlevel% NEQ 0 (
    echo.
    echo [ERROR] DNSEF exited with code %errorlevel%.
    pause
)

endlocal