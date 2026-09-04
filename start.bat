@echo off
setlocal EnableExtensions

title LVM - LRC Video Maker
cd /d "%~dp0"

rem Clear inherited environment variables before selecting Python.
set "VIRTUAL_ENV="
set "PYTHONHOME="

if not exist "%~dp0main.py" (
    echo [ERROR] main.py was not found. Run this file from the project root.
    set "EXIT_CODE=1"
    goto :error
)

rem Use the system Python Launcher and keep the launcher independent of the shell.
set "PYTHON_CMD="
where py >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3"

if not defined PYTHON_CMD (
    where python >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo [ERROR] Python 3 was not found. Install Python 3.10 or newer and add it to PATH.
    set "EXIT_CODE=1"
    goto :error
)

%PYTHON_CMD% -c "import operator, sys; raise SystemExit(not operator.ge((sys.version_info.major, sys.version_info.minor), (3, 10)))" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10 or newer is required.
    set "EXIT_CODE=1"
    goto :error
)

echo Starting LVM...
%PYTHON_CMD% "%~dp0main.py" gui
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] LVM exited with code %EXIT_CODE%.
    goto :error
)

endlocal
exit /b 0

:error
echo.
pause
endlocal & exit /b %EXIT_CODE%
