@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo.
echo ============================================================
echo   SwimTech ML Pipeline
echo   Working dir: %CD%
echo ============================================================
echo.

:: -------------------------------------------------------------
:: Step 1. Video download
:: -------------------------------------------------------------
echo [1/6] Video download (full_restock)...
python 01_download_videos.py --mode full_restock
if errorlevel 1 (
    echo.
    echo [FAIL] Step 1 failed: 01_download_videos.py
    echo Stopping pipeline.
    pause
    exit /b 1
)
echo [OK] Step 1 done
echo.

:: -------------------------------------------------------------
:: Step 2. Feature extraction
:: -------------------------------------------------------------
echo [2/6] Feature extraction...
python 02_extract_features.py
if errorlevel 1 (
    echo.
    echo [FAIL] Step 2 failed: 02_extract_features.py
    echo Stopping pipeline.
    pause
    exit /b 2
)
echo [OK] Step 2 done
echo.

:: -------------------------------------------------------------
:: Step 3. Data validation
:: -------------------------------------------------------------
echo [3/6] Data validation...
python 06_validate_data.py
if errorlevel 1 (
    echo.
    echo [FAIL] Step 3 failed: 06_validate_data.py
    echo Stopping pipeline.
    pause
    exit /b 3
)
echo [OK] Step 3 done
echo.

:: -------------------------------------------------------------
:: Step 4. Auto labeling
:: -------------------------------------------------------------
echo [4/6] Auto labeling...
python 05_auto_label.py --min-detect 0.5
if errorlevel 1 (
    echo.
    echo [FAIL] Step 4 failed: 05_auto_label.py
    echo Stopping pipeline.
    pause
    exit /b 4
)
echo [OK] Step 4 done
echo.

:: -------------------------------------------------------------
:: Step 5. Model training
:: -------------------------------------------------------------
echo [5/6] Model training...
python 03_train_model.py
if errorlevel 1 (
    echo.
    echo [FAIL] Step 5 failed: 03_train_model.py
    echo Stopping pipeline.
    pause
    exit /b 5
)
echo [OK] Step 5 done
echo.

:: -------------------------------------------------------------
:: Step 6. Model evaluation
:: -------------------------------------------------------------
echo [6/6] Model evaluation...
python 04_evaluate_model.py
if errorlevel 1 (
    echo.
    echo [FAIL] Step 6 failed: 04_evaluate_model.py
    echo Stopping pipeline.
    pause
    exit /b 6
)
echo [OK] Step 6 done
echo.

:: -------------------------------------------------------------
:: Git commit & push (from C:\swim root)
:: -------------------------------------------------------------
echo [Git] Committing and pushing changes...
cd /d "%~dp0\..\..\"

git add .
if errorlevel 1 (
    echo [FAIL] git add failed
    pause
    exit /b 7
)

git commit -m "feat: automated ML retraining pipeline complete"
if errorlevel 1 (
    echo [FAIL] git commit failed (nothing to commit?)
    pause
    exit /b 8
)

git push
if errorlevel 1 (
    echo [FAIL] git push failed
    pause
    exit /b 9
)

echo.
echo ============================================================
echo   Pipeline completed successfully
echo ============================================================
echo.
pause
exit /b 0
