@echo off
setlocal

echo ============================================================
echo  SwimMate Test Runner
echo ============================================================
echo.

set PYTHONPATH=api
set PYTHONUTF8=1

echo [1/2] Core unit, contract, and Jira integration tests
python -m pytest tests/test_api_unit.py tests/test_training_product_contracts.py tests/test_coach_crew_jira.py tests/test_jira_integration.py -q
if errorlevel 1 (
  echo.
  echo Core tests failed. Playwright E2E was not started.
  exit /b %ERRORLEVEL%
)

if "%1"=="--core" (
  echo.
  echo Core tests passed.
  exit /b 0
)

for /f %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set DATESTR=%%a
set SHOT_DIR=tests\screenshots\%DATESTR%
set REPORT_DIR=tests\reports\%DATESTR%

if not exist "%SHOT_DIR%" mkdir "%SHOT_DIR%"
if not exist "%REPORT_DIR%" mkdir "%REPORT_DIR%"

echo.
echo [2/2] Playwright E2E against https://localhost
echo  Screenshots: %SHOT_DIR%
echo  Report     : %REPORT_DIR%\report.html
echo.

python -m pytest tests/test_swimtech.py ^
  --screenshot=on ^
  --output=%SHOT_DIR% ^
  --html=%REPORT_DIR%/report.html ^
  --self-contained-html ^
  -v ^
  --tb=short

set EXIT_CODE=%ERRORLEVEL%
echo.
if %EXIT_CODE% EQU 0 (
  echo All core and Playwright tests passed.
) else (
  echo Playwright tests failed. See %REPORT_DIR%\report.html.
)
exit /b %EXIT_CODE%
