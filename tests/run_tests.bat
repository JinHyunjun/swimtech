@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo  SwimTech E2E Test Runner
echo ============================================================
echo.

REM Run pytest and save HTML report
pytest tests/test_swimtech.py ^
    --html=tests/report.html ^
    --self-contained-html ^
    -v ^
    --tb=short ^
    2>&1 | tee tests\test_output.txt

REM Capture exit code
set EXIT_CODE=%ERRORLEVEL%

echo.
echo ============================================================
echo  FAILED TESTS SUMMARY
echo ============================================================

REM Extract and print only failed test lines
findstr /R "FAILED ERROR" tests\test_output.txt

if %EXIT_CODE% EQU 0 (
    echo.
    echo  All tests passed.
) else (
    echo.
    echo  Some tests failed. See tests\report.html for full details.
)

echo.
echo  Report saved to: tests\report.html
echo ============================================================

REM Clean up temp output file
del tests\test_output.txt 2>nul

exit /b %EXIT_CODE%
