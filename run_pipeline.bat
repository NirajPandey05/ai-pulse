@echo off
setlocal

set SCRIPT_DIR=%~dp0
set LOG_FILE=%SCRIPT_DIR%logs\scheduler.log

if not exist "%SCRIPT_DIR%logs" mkdir "%SCRIPT_DIR%logs"

echo ======================================== >> "%LOG_FILE%"
echo Run started: %DATE% %TIME% >> "%LOG_FILE%"
echo ======================================== >> "%LOG_FILE%"

cd /d "%SCRIPT_DIR%"

uv run python main.py >> "%LOG_FILE%" 2>&1

if %ERRORLEVEL% EQU 0 (
    echo Run completed successfully: %DATE% %TIME% >> "%LOG_FILE%"
) else (
    echo Run FAILED (exit code %ERRORLEVEL%): %DATE% %TIME% >> "%LOG_FILE%"
)

echo. >> "%LOG_FILE%"
exit /b %ERRORLEVEL%
