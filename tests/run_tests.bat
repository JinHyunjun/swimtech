@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo  SwimTech E2E Test Runner
echo ============================================================
echo.

REM ── 오늘 날짜 (YYYYMMDD) 구하기 ─────────────────────────────
for /f %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set DATESTR=%%a

REM ── 날짜별 디렉토리 생성 ──────────────────────────────────────
set SHOT_DIR=tests\screenshots\%DATESTR%
set REPORT_DIR=tests\reports\%DATESTR%

if not exist "%SHOT_DIR%" mkdir "%SHOT_DIR%"
if not exist "%REPORT_DIR%" mkdir "%REPORT_DIR%"

echo  Date       : %DATESTR%
echo  Screenshots: %SHOT_DIR%
echo  Report     : %REPORT_DIR%\report.html
echo.

REM ── pytest 실행 ───────────────────────────────────────────────
pytest tests/test_swimtech.py ^
    --screenshot=on ^
    --output=%SHOT_DIR% ^
    --html=%REPORT_DIR%/report.html ^
    --self-contained-html ^
    -v ^
    --tb=short ^
    2>&1 | tee tests\test_output.txt

REM ── 종료 코드 캡처 ────────────────────────────────────────────
set EXIT_CODE=%ERRORLEVEL%

echo.
echo ============================================================
echo  FAILED TESTS SUMMARY
echo ============================================================

findstr /R "FAILED ERROR" tests\test_output.txt

if %EXIT_CODE% EQU 0 (
    echo.
    echo  All tests passed.
) else (
    echo.
    echo  Some tests FAILED. See %REPORT_DIR%\report.html for details.
)

echo.
echo  Screenshots : %SHOT_DIR%\
echo  Report      : %REPORT_DIR%\report.html
echo ============================================================

del tests\test_output.txt 2>nul

exit /b %EXIT_CODE%
