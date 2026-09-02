@echo off
REM ============================================================================
REM  prune_month.bat  --  end-of-month Tribulation Times archive maintenance
REM ============================================================================
REM
REM  HOW TO USE
REM  ----------
REM  Place this .bat file in the same folder as prune_month.py, news2.html,
REM  and (for template refresh) template.html + your month archives.
REM
REM  Option A - DOUBLE-CLICK:
REM     Just double-click the file. It will show the DEFAULT target month
REM     (previous calendar month) and let you either accept it or type a
REM     different YYYY-MM. Then it prompts for confirmation, whether to
REM     refresh template.html, the Ladder source file, etc.
REM
REM  Option B - RUN WITH ARGS from a command prompt:
REM     prune_month.bat 2026-08
REM     prune_month.bat 2026-08 --refresh-template --ladder-source oct08.html
REM     prune_month.bat 2026-08 --yes --no-refresh-template
REM
REM  When arguments are passed, they are forwarded directly to prune_month.py
REM  and the target-month prompt is skipped.
REM ============================================================================

setlocal EnableDelayedExpansion

REM ---- 1. Switch to the folder this .bat lives in ----------------------------
REM %~dp0 expands to the drive+path of this batch file, so news2.html and
REM template.html are found no matter where the .bat is launched from
REM (double-click, Start Menu, a shortcut on the desktop, etc.).
cd /d "%~dp0"

REM ---- 2. Sanity check: is prune_month.py here? -----------------------------
if not exist "prune_month.py" (
    echo.
    echo ERROR: prune_month.py is not in this folder:
    echo   %CD%
    echo.
    echo Put prune_month.bat in the same folder as prune_month.py and try again.
    echo.
    pause
    exit /b 1
)

REM ---- 3. Pick the Python command -------------------------------------------
REM Prefer the "py" launcher that ships with Python-for-Windows; fall back to
REM plain "python" if the launcher isn't installed.
set "PYCMD=py"
where py >nul 2>nul
if errorlevel 1 set "PYCMD=python"

REM ---- 4. If args were passed, forward them and skip the prompt --------------
if not "%~1"=="" (
    %PYCMD% prune_month.py %*
    goto :end
)

REM ---- 5. Interactive mode: show default target month, allow override --------
REM Ask Python itself to compute "previous calendar month" so the .bat doesn't
REM have to parse locale-specific %date% strings.
for /f "delims=" %%i in ('%PYCMD% -c "import datetime as d; x=d.date.today().replace(day=1)-d.timedelta(days=1); print(f'{x.year}-{x.month:02d}')"') do set "DEFAULT_MONTH=%%i"

echo.
echo -----------------------------------------------------------------
echo  Default target month: !DEFAULT_MONTH!  (previous calendar month)
echo -----------------------------------------------------------------
echo.
echo  Press ENTER to accept this default, OR
echo  Type a different month as YYYY-MM (e.g. 2026-08 to prune August 2026):
echo.

set "USER_MONTH="
set /p "USER_MONTH=Target month [!DEFAULT_MONTH!]: "
if "!USER_MONTH!"=="" set "USER_MONTH=!DEFAULT_MONTH!"

echo.
echo Running: %PYCMD% prune_month.py !USER_MONTH!
echo.
%PYCMD% prune_month.py !USER_MONTH!

:end
REM ---- 6. Keep the window open so you can read the output -------------------
echo.
pause
endlocal
