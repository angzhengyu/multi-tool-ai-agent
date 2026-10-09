@echo off
cd /d %~dp0
setlocal

rem ============================================================
rem  Multi-tool AI Agent - one-click start
rem
rem  NOTE: ASCII-only on purpose. cmd.exe parses .bat byte-by-byte
rem  using the current console codepage, so UTF-8 Chinese in this
rem  file turns into garbage commands and the script dies.
rem
rem  It VERIFIES the interpreter actually has pandas/openpyxl before
rem  using it. A venv that starts the server but lacks pandas is the
rem  worst case: the page opens, then every tool fails at runtime.
rem ============================================================

set "PY="

rem Optional override: set PY_AGENT=C:\path\to\python.exe before running.
if defined PY_AGENT if exist "%PY_AGENT%" (
  "%PY_AGENT%" -c "import pandas, openpyxl" >nul 2>nul
  if not errorlevel 1 set "PY=%PY_AGENT%"
)

rem Candidate order: project venv, then workspace-root venv.
for %%C in (".venv\Scripts\python.exe" "..\..\.venv\Scripts\python.exe") do (
  if not defined PY if exist "%%~C" (
    "%%~C" -c "import pandas, openpyxl" >nul 2>nul
    if not errorlevel 1 set "PY=%%~C"
  )
)

if not defined PY (
  echo.
  echo [x] No interpreter with pandas + openpyxl was found.
  echo     Checked: .venv\ and ..\..\.venv\
  echo.
  echo     Fix one of these:
  echo       1^) install the deps into the venv you want to use:
  echo            .venv\Scripts\python.exe -m pip install pandas openpyxl
  echo       2^) or point this script at your own interpreter:
  echo            set PY_AGENT=C:\path\to\python.exe
  echo.
  pause
  exit /b 1
)

echo ================================================
echo   Multi-tool AI Agent
echo   Interpreter : %PY%
echo   Open in browser: http://127.0.0.1:8001
echo   Stop: Ctrl + C
echo ================================================
echo.

"%PY%" main.py

echo.
echo [server stopped]
pause