@echo off
setlocal enabledelayedexpansion

REM ── --ai 옵션: AI 분析 전용 테스트 별도 실행 ─────────────────────────────────
if "%1"=="--ai" goto :ai_tests

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

echo.
echo [INFO] AI 분析 관련 테스트는 내부 테스트 전용입니다 (run_tests.bat --ai 옵션으로 별도 실행)
echo.

exit /b %EXIT_CODE%


REM ════════════════════════════════════════════════════════════
REM  :ai_tests — AI 분析 전용 테스트 (--ai 옵션으로 호출)
REM ════════════════════════════════════════════════════════════
:ai_tests

REM 날짜 디렉토리 준비
for /f %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set DATESTR=%%a
set SHOT_DIR=tests\screenshots\%DATESTR%
set REPORT_DIR=tests\reports\%DATESTR%
if not exist "%SHOT_DIR%" mkdir "%SHOT_DIR%"
if not exist "%REPORT_DIR%" mkdir "%REPORT_DIR%"

echo ============================================================
echo  SwimTech AI 분析 전용 테스트 (upload / viewer / meta / analysis)
echo ============================================================
echo  Date       : %DATESTR%
echo  Report     : %REPORT_DIR%\report_ai.html
echo.

pytest tests/test_swimtech.py ^
    -k "upload or viewer or meta or analysis" ^
    --screenshot=on ^
    --output=%SHOT_DIR% ^
    --html=%REPORT_DIR%/report_ai.html ^
    --self-contained-html ^
    -v ^
    --tb=short ^
    --override-ini="addopts=" ^
    2>&1 | tee tests\test_output_ai.txt

set AI_EXIT=%ERRORLEVEL%
del tests\test_output_ai.txt 2>nul

echo.
echo ============================================================
echo  AI 분析 테스트 완료. Report: %REPORT_DIR%\report_ai.html
echo ============================================================

exit /b %AI_EXIT%
